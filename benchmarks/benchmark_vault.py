"""Verify and benchmark a queryable Rat-Trap Vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
import zipfile
from pathlib import Path

from rat_trap import vault_engine


def tree_digest(folder: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    file_count = 0
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        with open(path, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                total_bytes += len(block)
        file_count += 1
    return digest.hexdigest(), total_bytes, file_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument(
        "--queries",
        nargs="+",
        default=["airplane1.png", "Wherefore art thou", "Private"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be at least one")
    source = args.source.resolve()
    vault = args.vault.resolve()
    if not source.is_dir():
        raise ValueError(f"Source folder not found: {source}")
    if not vault_engine.is_vault_archive(vault):
        raise ValueError(f"Queryable Vault not found: {vault}")

    expected_digest = tree_digest(source)
    metadata = vault_engine.read_metadata(vault)
    query_rows = []
    for query in args.queries:
        durations = []
        results = []
        for _ in range(args.repetitions):
            started = time.perf_counter()
            results = vault_engine.search_vault(vault, query, limit=1000)
            durations.append(time.perf_counter() - started)
        query_rows.append(
            {
                "query": query,
                "result_count": len(results),
                "first_paths": [result.path for result in results[:10]],
                "seconds_median": statistics.median(durations),
                "seconds_all": durations,
            }
        )

    started = time.perf_counter()
    vault_engine.verify_vault(vault)
    verify_seconds = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix="rat-trap-vault-benchmark-") as temporary:
        temporary_root = Path(temporary)
        restored = temporary_root / "restored"
        started = time.perf_counter()
        vault_engine.extract_vault(vault, restored)
        extract_seconds = time.perf_counter() - started
        restored_digest = tree_digest(restored)
        if restored_digest != expected_digest:
            raise RuntimeError("Vault full round-trip verification failed")

        selected_path = None
        for row in query_rows:
            if row["first_paths"]:
                selected_path = row["first_paths"][0]
                break
        if selected_path is None:
            raise RuntimeError("No search result was available for selective extraction")
        selective = temporary_root / "selected"
        vault_engine.extract_vault(vault, selective, paths=[selected_path])
        if not (selective / selected_path).is_file():
            raise RuntimeError("Vault selective extraction failed")

        exported = temporary_root / "vault-export.zip"
        started = time.perf_counter()
        vault_engine.export_zip(vault, exported)
        zip_seconds = time.perf_counter() - started
        with zipfile.ZipFile(exported) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Vault ZIP export failed its CRC check")
            if len([name for name in archive.namelist() if not name.endswith("/")]) != metadata.file_count:
                raise RuntimeError("Vault ZIP export has the wrong file count")

    result = {
        "schema": "rat-trap-vault-benchmark-1",
        "created_at": time.time(),
        "source": str(source),
        "vault": str(vault),
        "vault_bytes": vault.stat().st_size,
        "retained_percent": vault.stat().st_size / metadata.total_bytes * 100,
        "metadata": metadata.as_dict(),
        "queries": query_rows,
        "verify_seconds": verify_seconds,
        "extract_seconds": extract_seconds,
        "zip_export_seconds": zip_seconds,
        "round_trip_verified": True,
        "selective_extract_verified": True,
        "zip_export_verified": True,
        "source_tree_digest": expected_digest[0],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
