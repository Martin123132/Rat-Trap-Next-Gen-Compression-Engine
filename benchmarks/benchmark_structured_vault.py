"""Build and validate a Rat-Trap 5.1 structured Vault benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path

from rat_trap import vault_engine


def tree_digest(folder: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total = 0
    count = 0
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(data)
        total += len(data)
        count += 1
    return digest.hexdigest(), total, count


def median_ms(operation, repeats: int = 9) -> tuple[float, object]:
    timings = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = operation()
        timings.append((time.perf_counter() - started) * 1000)
    return statistics.median(timings), result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    vault = args.vault.resolve()

    started = time.perf_counter()
    metadata = vault_engine.create_vault(source, vault)
    build_seconds = time.perf_counter() - started
    sources = vault_engine.list_structured_sources(vault)
    adult = next((item for item in sources if item.path.lower().endswith("adult.data")), None)
    if adult is None:
        raise RuntimeError("The beta corpus did not produce an adult.data table")
    columns = vault_engine.list_structured_columns(vault, adult.id)
    category_column = columns[1].column_name
    age_column = columns[0].column_name

    find_ms, find_result = median_ms(
        lambda: vault_engine.query_structured_source(
            vault, adult.id, search="Private", column=category_column, limit=5000
        )
    )
    sql = (
        f'SELECT "{age_column}", "{category_column}" FROM "{adult.table_name}" '
        f'WHERE "{age_column}" >= 50 ORDER BY "{age_column}" DESC LIMIT 1000'
    )
    sql_ms, sql_result = median_ms(
        lambda: vault_engine.execute_structured_sql(vault, sql, limit=5000)
    )

    verify_started = time.perf_counter()
    vault_engine.verify_vault(vault)
    verify_seconds = time.perf_counter() - verify_started
    with tempfile.TemporaryDirectory(prefix="rat-trap-structured-benchmark-") as temporary:
        root = Path(temporary)
        restored = root / "restored"
        extract_started = time.perf_counter()
        vault_engine.extract_vault(vault, restored)
        extract_seconds = time.perf_counter() - extract_started
        restored_digest = tree_digest(restored)
        source_digest = tree_digest(source)
        if restored_digest != source_digest:
            raise RuntimeError("Structured Vault restoration digest mismatch")
        export = root / "private-results.csv"
        vault_engine.export_structured_result(find_result, export)
        export_rows = len(export.read_text(encoding="utf-8-sig").splitlines()) - 1

    payload = {
        "schema": "rat-trap-structured-vault-benchmark-1",
        "version": "5.1.0",
        "source": str(source),
        "vault": str(vault),
        "source_files": metadata.file_count,
        "source_bytes": metadata.total_bytes,
        "vault_bytes": vault.stat().st_size,
        "retained_percent": vault.stat().st_size / metadata.total_bytes * 100,
        "build_seconds": build_seconds,
        "verify_seconds": verify_seconds,
        "extract_seconds": extract_seconds,
        "round_trip_verified": True,
        "structured_sources": [
            {
                "path": item.path,
                "table_name": item.table_name,
                "format": item.data_format,
                "rows": item.row_count,
                "columns": item.column_count,
            }
            for item in sources
        ],
        "structured_source_count": metadata.structured_source_count,
        "structured_row_count": metadata.structured_row_count,
        "adult_data": {
            "rows": adult.row_count,
            "columns": [
                {
                    "source_name": item.source_name,
                    "column_name": item.column_name,
                    "type": item.declared_type,
                }
                for item in columns
            ],
            "private_filter_rows": len(find_result.rows),
            "private_filter_median_ms": find_ms,
            "private_export_rows": export_rows,
            "numeric_sql_rows_returned": len(sql_result.rows),
            "numeric_sql_median_ms": sql_ms,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
