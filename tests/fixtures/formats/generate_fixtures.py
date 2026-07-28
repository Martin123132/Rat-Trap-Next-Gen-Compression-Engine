"""Generate the small GMW compatibility fixtures committed beside this file.

The binary fixtures are the test inputs. This script records how they were
constructed and is not run by the normal test suite. Regeneration requires an
explicit --replace because replacing a golden archive is a compatibility
decision, not routine test cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
from contextlib import closing
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = FIXTURE_DIR.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from rat_trap import gmw_tool, solid_engine, vault_engine  # noqa: E402


FIXED_TIMESTAMP = 1_700_000_000.0
TARGETS = (
    "gmw-sqlite-1-4.2.gmw",
    "gmw-solid-2-4.3.gmw",
    "gmw-solid-2-4.4-dedup.gmw",
    "gmw-vault-1-schema-1.gmw",
    "gmw-vault-1-schema-2.gmw",
)
LEGACY_METADATA_KEYS = (
    "format",
    "chunk_size",
    "compressor",
    "checksum",
    "checksum_algorithm",
    "created_at",
    "elapsed_seconds",
    "file_count",
    "total_bytes",
)


def _build_source(root: Path) -> Path:
    source = root / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "hello.txt").write_bytes(b"Rat-Trap compatibility fixture\n")
    (source / "people.csv").write_bytes(
        b"name,age,active\nAlice,31,true\nBob,27,false\n"
    )
    duplicate = bytes(range(256)) * 32
    (source / "duplicate-a.bin").write_bytes(duplicate)
    (source / "duplicate-b.bin").write_bytes(duplicate)
    (nested / "data.bin").write_bytes(
        bytes((index * 29 + 7) % 256 for index in range(2048))
    )
    (nested / "empty.txt").write_bytes(b"")

    for path in sorted(source.rglob("*"), reverse=True):
        os.utime(path, (FIXED_TIMESTAMP, FIXED_TIMESTAMP))
    os.utime(source, (FIXED_TIMESTAMP, FIXED_TIMESTAMP))
    return source


def _patch_legacy_metadata(path: Path) -> None:
    placeholders = ",".join("?" for _ in LEGACY_METADATA_KEYS)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            f"DELETE FROM metadata WHERE key NOT IN ({placeholders})",
            LEGACY_METADATA_KEYS,
        )
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'created_at'",
            (json.dumps(FIXED_TIMESTAMP),),
        )
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'elapsed_seconds'",
            (json.dumps(0.0),),
        )
        connection.commit()
        connection.execute("VACUUM")


def _rewrite_solid_metadata(
    path: Path, *, remove_dedup_fields: bool = False
) -> None:
    archive = path.read_bytes()
    footer_size = 8 + len(solid_engine.FOOTER_MAGIC)
    metadata_size = struct.unpack("<Q", archive[-footer_size:-len(solid_engine.FOOTER_MAGIC)])[0]
    metadata_start = len(archive) - footer_size - metadata_size
    metadata = json.loads(archive[metadata_start : metadata_start + metadata_size])
    metadata["created_at"] = FIXED_TIMESTAMP
    metadata["elapsed_seconds"] = 0.0
    if remove_dedup_fields:
        metadata.pop("whole_file_dedup", None)
        metadata.pop("duplicate_file_count", None)
    encoded = json.dumps(metadata, separators=(",", ":"), sort_keys=True).encode("utf-8")
    rebuilt = (
        archive[:metadata_start]
        + encoded
        + struct.pack("<Q", len(encoded))
        + solid_engine.FOOTER_MAGIC
    )
    path.write_bytes(rebuilt)


def _patch_vault_metadata(path: Path, *, schema_one: bool) -> None:
    with closing(sqlite3.connect(path)) as connection:
        if schema_one:
            table_names = [
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM structured_sources ORDER BY id"
                )
            ]
            for table_name in table_names:
                if not table_name.startswith("rt_data_"):
                    raise RuntimeError(f"Unexpected generated table name: {table_name}")
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DROP TABLE structured_columns")
            connection.execute("DROP TABLE structured_sources")
            connection.execute(
                "UPDATE vault_metadata SET value = '1' WHERE key = 'schema_version'"
            )
            connection.execute(
                "DELETE FROM vault_metadata WHERE key IN "
                "('structured_source_count', 'structured_row_count')"
            )
        connection.execute(
            "UPDATE vault_metadata SET value = ? WHERE key = 'created_at'",
            (json.dumps(FIXED_TIMESTAMP),),
        )
        connection.execute(
            "UPDATE vault_metadata SET value = ? WHERE key = 'elapsed_seconds'",
            (json.dumps(0.0),),
        )
        connection.commit()
        connection.execute("VACUUM")


def _tree(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in folder.rglob("*") if item.is_file())
    }


def _verify(source: Path, paths: list[Path]) -> None:
    expected = _tree(source)
    with tempfile.TemporaryDirectory(prefix="rat-trap-fixture-check-") as temporary:
        root = Path(temporary)
        for archive in paths:
            metadata = gmw_tool.read_metadata(archive)
            restored = root / archive.stem
            gmw_tool.extract_archive(archive, restored)
            if _tree(restored) != expected:
                raise RuntimeError(f"Fixture round trip failed: {archive.name}")
            if metadata.format == vault_engine.FORMAT:
                vault_engine.verify_vault(archive)


def generate(replace: bool) -> None:
    destinations = [FIXTURE_DIR / name for name in TARGETS]
    existing = [path for path in destinations if path.exists()]
    if existing and not replace:
        names = ", ".join(path.name for path in existing)
        raise SystemExit(f"Refusing to replace golden fixtures without --replace: {names}")

    with tempfile.TemporaryDirectory(prefix="rat-trap-fixture-build-") as temporary:
        root = Path(temporary)
        source = _build_source(root)
        generated = root / "generated"
        generated.mkdir()

        legacy = generated / TARGETS[0]
        gmw_tool.compress_folder(
            source,
            legacy,
            archive_mode="chunked",
            compressor="zlib",
            chunk_size=1024,
            profile=None,
        )
        _patch_legacy_metadata(legacy)

        solid_43 = generated / TARGETS[1]
        solid_engine.compress_folder(
            source,
            solid_43,
            compressor="zstd",
            level=3,
            profile="fast",
            whole_file_dedup=False,
        )
        _rewrite_solid_metadata(solid_43, remove_dedup_fields=True)

        solid_44 = generated / TARGETS[2]
        solid_engine.compress_folder(
            source,
            solid_44,
            compressor="zstd",
            level=6,
            profile="balanced",
            whole_file_dedup=True,
        )
        _rewrite_solid_metadata(solid_44)

        vault_1 = generated / TARGETS[3]
        vault_engine.create_vault(source, vault_1, level=6, chunk_size=1024)
        _patch_vault_metadata(vault_1, schema_one=True)

        vault_2 = generated / TARGETS[4]
        vault_engine.create_vault(source, vault_2, level=6, chunk_size=1024)
        _patch_vault_metadata(vault_2, schema_one=False)

        generated_paths = [generated / name for name in TARGETS]
        _verify(source, generated_paths)
        for source_path, destination in zip(generated_paths, destinations):
            shutil.copyfile(source_path, destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            print(f"{destination.name} {destination.stat().st_size} {digest}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace already committed golden fixtures",
    )
    args = parser.parse_args()
    generate(args.replace)


if __name__ == "__main__":
    main()
