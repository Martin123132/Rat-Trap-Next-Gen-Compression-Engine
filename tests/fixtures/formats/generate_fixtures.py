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
import unicodedata
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock


FIXTURE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = FIXTURE_DIR.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from rat_trap import (  # noqa: E402
    gmw_tool,
    secure_engine,
    solid_engine,
    vault_engine,
)


FIXED_TIMESTAMP = 1_700_000_000.0
FIXED_TIMESTAMP_NS = 1_700_000_000_123_456_789
TARGETS = (
    "gmw-sqlite-1-4.2.gmw",
    "gmw-solid-2-4.3.gmw",
    "gmw-solid-2-4.4-dedup.gmw",
    "gmw-vault-1-schema-1.gmw",
    "gmw-vault-1-schema-2.gmw",
)
SECURE_TARGETS = (
    "rat-trap-encrypted-1-5.3.gmw",
    "rat-trap-encrypted-1-5.3.rtrk",
    "rat-trap-encrypted-1-5.3-vector.json",
)
SECURE_PASSWORD = "Cafe\u0301 Rat-Trap public fixture"
SECURE_DATA_KEY = bytes(range(0x00, 0x20))
SECURE_UUIDS = (
    "00112233445566778899aabbccddeeff",
    "102132435465768798a9bacbdcedfe0f",
    "ffeeddccbbaa99887766554433221100",
)
SECURE_RANDOM_INPUTS = (
    ("recovery_key", bytes(range(0x20, 0x40))),
    ("sealed_metadata_nonce", bytes(range(0x40, 0x4C))),
    ("password_salt", bytes(range(0x50, 0x60))),
    ("password_wrap_nonce", bytes(range(0x60, 0x6C))),
    ("recovery_salt", bytes(range(0x70, 0x90))),
    ("recovery_wrap_nonce", bytes(range(0x90, 0x9C))),
    ("header_auth_nonce", bytes(range(0xA0, 0xAC))),
    ("chunk_0_nonce", bytes(range(0xB0, 0xBC))),
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


class _FixedRandom:
    def __init__(self) -> None:
        self._remaining = list(SECURE_RANDOM_INPUTS)

    def __call__(self, size: int) -> bytes:
        if not self._remaining:
            raise RuntimeError(
                f"Unexpected secure-fixture random request for {size} bytes"
            )
        name, value = self._remaining.pop(0)
        if len(value) != size:
            raise RuntimeError(
                f"Secure-fixture random request for {name} expected "
                f"{len(value)} bytes, got {size}"
            )
        return value

    def verify_consumed(self) -> None:
        if self._remaining:
            names = ", ".join(name for name, _value in self._remaining)
            raise RuntimeError(
                f"Secure-fixture random inputs were not consumed: {names}"
            )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_secure_vector(
    archive: Path,
    recovery_file: Path,
    inner: Path,
) -> dict[str, object]:
    header, header_bytes, data_offset, encrypted_size = (
        secure_engine._read_header(archive)
    )
    data_context = secure_engine._data_context(header)
    slots = list(header["key_slots"])
    password_slot = next(
        slot for slot in slots if slot["type"] == "password"
    )
    recovery_slot = next(
        slot for slot in slots if slot["type"] == "recovery"
    )
    password_bytes = unicodedata.normalize(
        "NFC",
        SECURE_PASSWORD,
    ).encode("utf-8")
    password_salt = secure_engine._unb64(
        password_slot["kdf"]["salt"],
        label="fixture password salt",
        expected=16,
    )
    recovery_salt = secure_engine._unb64(
        recovery_slot["kdf"]["salt"],
        label="fixture recovery salt",
        expected=32,
    )
    recovery_key = dict(SECURE_RANDOM_INPUTS)["recovery_key"]
    password_kek = secure_engine._argon2_key(
        password_bytes,
        password_salt,
        str(header["file_id"]),
    )
    recovery_kek = secure_engine._recovery_kek(
        recovery_key,
        recovery_salt,
    )
    sealed_plaintext = secure_engine._canonical_json(
        {
            "format": secure_engine.SEALED_METADATA_FORMAT,
            "plaintext_sha256": _sha256(inner),
        }
    )
    header_without_auth = secure_engine._header_without_auth(header)
    raw = archive.read_bytes()
    chunk = raw[data_offset:]
    recovery_payload = json.loads(
        recovery_file.read_text(encoding="utf-8")
    )
    return {
        "schema": "rat-trap-secure-interoperability-vector/v1",
        "warning": (
            "Public test credentials only. Never reuse these keys or this "
            "password for private data."
        ),
        "format": secure_engine.SECURE_FORMAT,
        "schema_version": secure_engine.SECURE_SCHEMA_VERSION,
        "writer_version": secure_engine.WRITER_VERSION,
        "source_inner": {
            "name": inner.name,
            "bytes": inner.stat().st_size,
            "sha256": _sha256(inner),
        },
        "credentials": {
            "password_input": SECURE_PASSWORD,
            "password_nfc": unicodedata.normalize("NFC", SECURE_PASSWORD),
            "password_nfc_utf8_hex": password_bytes.hex(),
            "recovery_key_hex": recovery_key.hex(),
            "recovery_code": recovery_payload["recovery_key"],
        },
        "fixed_inputs": {
            "created_at_ns": FIXED_TIMESTAMP_NS,
            "file_id": SECURE_UUIDS[0],
            "password_slot_id": SECURE_UUIDS[1],
            "recovery_slot_id": SECURE_UUIDS[2],
            "data_key_hex": SECURE_DATA_KEY.hex(),
            **{
                f"{name}_hex": value.hex()
                for name, value in SECURE_RANDOM_INPUTS
            },
        },
        "derived_values": {
            "password_kek_hex": password_kek.hex(),
            "recovery_kek_hex": recovery_kek.hex(),
            "data_context_hex": data_context.hex(),
        },
        "canonical_json_hex": {
            "base_descriptor": secure_engine._canonical_json(
                secure_engine._base_descriptor(header)
            ).hex(),
            "password_slot_descriptor": secure_engine._canonical_json(
                secure_engine._slot_descriptor(password_slot)
            ).hex(),
            "recovery_slot_descriptor": secure_engine._canonical_json(
                secure_engine._slot_descriptor(recovery_slot)
            ).hex(),
            "sealed_plaintext": sealed_plaintext.hex(),
            "header_without_auth": secure_engine._canonical_json(
                header_without_auth
            ).hex(),
            "header": header_bytes.hex(),
        },
        "associated_data_hex": {
            "password_argon2": (
                secure_engine._PASSWORD_AD_PREFIX
                + bytes.fromhex(str(header["file_id"]))
            ).hex(),
            "password_slot": secure_engine._slot_aad(
                password_slot,
                data_context,
            ).hex(),
            "recovery_slot": secure_engine._slot_aad(
                recovery_slot,
                data_context,
            ).hex(),
            "sealed_metadata": (
                secure_engine._METADATA_AAD_PREFIX + data_context
            ).hex(),
            "header_auth": (
                secure_engine._HEADER_AAD_PREFIX
                + secure_engine._canonical_json(header_without_auth)
            ).hex(),
            "chunk_0": secure_engine._chunk_aad(
                data_context,
                0,
                inner.stat().st_size,
            ).hex(),
        },
        "stored_values": {
            "sealed_metadata": header["sealed_metadata"],
            "password_wrap": password_slot["wrap"],
            "recovery_wrap": recovery_slot["wrap"],
            "header_auth": header["header_auth"],
            "chunk_0_nonce_hex": chunk[:12].hex(),
            "chunk_0_ciphertext_and_tag_hex": chunk[12:].hex(),
        },
        "outputs": {
            "archive": {
                "name": archive.name,
                "bytes": encrypted_size,
                "sha256": _sha256(archive),
                "header_bytes": len(header_bytes),
                "data_offset": data_offset,
            },
            "recovery_file": {
                "name": recovery_file.name,
                "bytes": recovery_file.stat().st_size,
                "sha256": _sha256(recovery_file),
            },
        },
    }


def generate_secure(replace: bool) -> None:
    destinations = [FIXTURE_DIR / name for name in SECURE_TARGETS]
    existing = [path for path in destinations if path.exists()]
    if existing and not replace:
        names = ", ".join(path.name for path in existing)
        raise SystemExit(
            "Refusing to replace golden secure fixtures without --replace: "
            f"{names}"
        )

    inner = FIXTURE_DIR / "gmw-solid-2-4.3.gmw"
    with tempfile.TemporaryDirectory(
        prefix="rat-trap-secure-fixture-build-"
    ) as temporary:
        root = Path(temporary)
        archive = root / SECURE_TARGETS[0]
        recovery = root / SECURE_TARGETS[1]
        vector_path = root / SECURE_TARGETS[2]
        fixed_random = _FixedRandom()
        fixed_uuids = [
            uuid.UUID(hex=value)
            for value in SECURE_UUIDS
        ]
        with (
            mock.patch.object(
                secure_engine.AESGCMSIV,
                "generate_key",
                return_value=SECURE_DATA_KEY,
            ),
            mock.patch.object(
                secure_engine.os,
                "urandom",
                side_effect=fixed_random,
            ),
            mock.patch.object(
                secure_engine.uuid,
                "uuid4",
                side_effect=fixed_uuids,
            ),
            mock.patch.object(
                secure_engine.time,
                "time_ns",
                return_value=FIXED_TIMESTAMP_NS,
            ),
        ):
            secure_engine.encrypt_file(
                inner,
                archive,
                password=SECURE_PASSWORD,
                recovery_key_output=recovery,
                chunk_size=64 * 1024,
            )
        fixed_random.verify_consumed()

        password_output = root / "password-output.gmw"
        secure_engine.decrypt_file(
            archive,
            password_output,
            password=unicodedata.normalize("NFC", SECURE_PASSWORD),
        )
        recovery_output = root / "recovery-output.gmw"
        secure_engine.decrypt_file(
            archive,
            recovery_output,
            recovery_key=recovery,
        )
        expected = inner.read_bytes()
        if (
            password_output.read_bytes() != expected
            or recovery_output.read_bytes() != expected
        ):
            raise RuntimeError("Secure fixture round trip failed")

        vector = _build_secure_vector(archive, recovery, inner)
        vector_path.write_text(
            json.dumps(
                vector,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        for source_path, destination in zip(
            (archive, recovery, vector_path),
            destinations,
        ):
            shutil.copyfile(source_path, destination)
            print(
                f"{destination.name} {destination.stat().st_size} "
                f"{_sha256(destination)}"
            )


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
    parser.add_argument(
        "--secure-only",
        action="store_true",
        help="generate only the deterministic schema-1 encrypted fixture",
    )
    args = parser.parse_args()
    if args.secure_only:
        generate_secure(args.replace)
    else:
        generate(args.replace)


if __name__ == "__main__":
    main()
