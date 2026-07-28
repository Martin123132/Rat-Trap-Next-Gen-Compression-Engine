"""Reproducible, round-trip-verified benchmark for Rat-Trap engines.

Every method archives the same directory tree, preserves filenames, and must
extract byte-for-byte before its result is accepted.  This corrects the main
comparability problems in the historical repository notebooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import stat
import statistics
import tempfile
import time
import zlib
from pathlib import Path
from typing import Callable

from rat_trap import gmw_tool


METHODS: dict[str, dict[str, object]] = {
    "solid-zstd-1": dict(archive_mode="solid", compressor="zstd", zstd_level=1),
    "solid-zstd-3": dict(archive_mode="solid", compressor="zstd", zstd_level=3),
    "solid-zstd-6": dict(archive_mode="solid", compressor="zstd", zstd_level=6),
    "solid-zstd-9": dict(archive_mode="solid", compressor="zstd", zstd_level=9),
    "solid-zstd-19": dict(archive_mode="solid", compressor="zstd", zstd_level=19),
    "solid-zstd-6-mt": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6, threads=-1
    ),
    "chunked-zstd-3": dict(archive_mode="chunked", compressor="zstd", zstd_level=3),
    "chunked-zstd-6": dict(archive_mode="chunked", compressor="zstd", zstd_level=6),
    "chunked-zstd-6-64k": dict(
        archive_mode="chunked", compressor="zstd", zstd_level=6, chunk_size=64 * 1024
    ),
    "chunked-zstd-6-256k": dict(
        archive_mode="chunked", compressor="zstd", zstd_level=6, chunk_size=256 * 1024
    ),
    "chunked-zstd-6-1m": dict(
        archive_mode="chunked", compressor="zstd", zstd_level=6, chunk_size=1024 * 1024
    ),
    "chunked-zstd-6-4m": dict(
        archive_mode="chunked", compressor="zstd", zstd_level=6, chunk_size=4 * 1024 * 1024
    ),
    "solid-zstd-6-ext": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6, entry_order="extension"
    ),
    "solid-zstd-6-w27": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6, zstd_window_log=27
    ),
    "solid-zstd-6-ldm-w27": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6,
        zstd_window_log=27, zstd_long_distance=True
    ),
    "solid-zstd-6-ext-ldm-w27": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6,
        entry_order="extension", zstd_window_log=27, zstd_long_distance=True
    ),
    "solid-zstd-3-file-dedup": dict(
        archive_mode="solid", compressor="zstd", zstd_level=3, whole_file_dedup=True
    ),
    "solid-zstd-6-file-dedup": dict(
        archive_mode="solid", compressor="zstd", zstd_level=6, whole_file_dedup=True
    ),
    "solid-zstd-19-file-dedup": dict(
        archive_mode="solid", compressor="zstd", zstd_level=19, whole_file_dedup=True
    ),
    "solid-xz-6": dict(archive_mode="solid", compressor="xz", zstd_level=6),
}


def _remove_readonly(function: Callable[[str], None], path: str, _error) -> None:
    """Allow cleanup of read-only files restored from source metadata."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onexc=_remove_readonly)


def _write_repeated(target: Path, block: bytes, size: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fp:
        remaining = size
        while remaining:
            piece = block[: min(remaining, len(block))]
            fp.write(piece)
            remaining -= len(piece)


def create_fixtures(root: Path, scale_mb: int) -> dict[str, Path]:
    rng = random.Random(742_2026)
    unit = max(1, scale_mb) * 1024 * 1024

    text = root / "text-and-code"
    text.mkdir(parents=True)
    record = (
        b'{"service":"rat-trap","status":"ok","tags":["windows","benchmark"],'
        b'"message":"repeatable structured text for solid compression"}\n'
    )
    for index in range(160):
        _write_repeated(text / f"module_{index:03d}" / "events.jsonl", record, unit // 80)

    duplicates = root / "duplicate-binaries"
    duplicates.mkdir(parents=True)
    shared = rng.randbytes(1024 * 1024)
    duplicate_count = max(8, scale_mb * 2)
    for index in range(duplicate_count):
        (duplicates / f"checkpoint_{index:03d}.bin").write_bytes(shared)
    for index in range(max(2, scale_mb // 2)):
        variant = bytearray(shared)
        variant[index * 4096 : index * 4096 + 4096] = bytes([index & 0xFF]) * 4096
        (duplicates / f"variant_{index:03d}.bin").write_bytes(variant)

    mixed = root / "mixed"
    mixed.mkdir(parents=True)
    incompressible = rng.randbytes(unit)
    (mixed / "camera_payload.png").write_bytes(zlib.compress(incompressible, 9))
    (mixed / "video_payload.mp4").write_bytes(zlib.compress(rng.randbytes(unit), 1))
    _write_repeated(mixed / "application.log", record, unit)
    _write_repeated(mixed / "settings.json", record[:64], max(1, unit // 2))
    (mixed / "model.bin").write_bytes(rng.randbytes(max(1, unit // 2)))
    return {"text-and-code": text, "duplicate-binaries": duplicates, "mixed": mixed}


def tree_digest(folder: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    size = 0
    count = 0
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        with open(path, "rb") as fp:
            while True:
                block = fp.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
        count += 1
    return digest.hexdigest(), size, count


def benchmark_method(
    source: Path,
    method_name: str,
    work: Path,
    repetitions: int,
) -> dict[str, object]:
    expected_digest, original_size, expected_files = tree_digest(source)
    compression_times: list[float] = []
    extraction_times: list[float] = []
    sizes: list[int] = []

    options = dict(METHODS[method_name])
    for repetition in range(repetitions):
        archive = work / f"{source.name}-{method_name}-{repetition}.gmw"
        restored = work / f"restored-{source.name}-{method_name}-{repetition}"

        started = time.perf_counter()
        gmw_tool.compress_folder(source, archive, profile=None, **options)
        compression_times.append(time.perf_counter() - started)
        sizes.append(archive.stat().st_size)

        started = time.perf_counter()
        gmw_tool.extract_archive(archive, restored)
        extraction_times.append(time.perf_counter() - started)
        actual_digest, actual_size, actual_files = tree_digest(restored)
        if (actual_digest, actual_size, actual_files) != (
            expected_digest,
            original_size,
            expected_files,
        ):
            raise RuntimeError(f"Round-trip verification failed for {method_name}")

        archive.unlink()
        remove_tree(restored)

    archive_size = statistics.median(sizes)
    return {
        "method": method_name,
        "original_bytes": original_size,
        "archive_bytes": int(archive_size),
        "retained_percent": archive_size / original_size * 100 if original_size else 0.0,
        "ratio": original_size / archive_size if archive_size else 0.0,
        "compression_seconds_median": statistics.median(compression_times),
        "extraction_seconds_median": statistics.median(extraction_times),
        "compression_seconds_all": compression_times,
        "extraction_seconds_all": extraction_times,
        "repetitions": repetitions,
        "round_trip_verified": True,
        "file_count": expected_files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--fixture-mb", type=int, default=8)
    parser.add_argument("--real-folder", type=Path)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Benchmark each immediate subfolder as an independent dataset",
    )
    parser.add_argument("--work-root", type=Path)
    parser.add_argument(
        "--only-real",
        action="store_true",
        help="Skip generated fixtures (requires --real-folder)",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=sorted(METHODS),
        default=list(METHODS),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be at least one")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.only_real and not (args.real_folder or args.dataset_root):
        raise ValueError("--only-real requires --real-folder or --dataset-root")
    if args.work_root:
        args.work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="rat-trap-benchmark-", dir=args.work_root
    ) as temporary:
        root = Path(temporary)
        datasets = {} if args.only_real else create_fixtures(root / "fixtures", args.fixture_mb)
        if args.real_folder:
            real_folder = args.real_folder.resolve()
            if not real_folder.is_dir():
                raise ValueError(f"Real folder not found: {real_folder}")
            datasets[f"real:{real_folder.name}"] = real_folder
        if args.dataset_root:
            dataset_root = args.dataset_root.resolve()
            if not dataset_root.is_dir():
                raise ValueError(f"Dataset root not found: {dataset_root}")
            category_folders = sorted(path for path in dataset_root.iterdir() if path.is_dir())
            if not category_folders:
                raise ValueError(f"Dataset root has no category folders: {dataset_root}")
            for category in category_folders:
                datasets[f"category:{category.name}"] = category

        results: dict[str, object] = {
            "schema": "rat-trap-controlled-benchmark-2",
            "created_at": time.time(),
            "python": os.sys.version,
            "repetitions": args.repetitions,
            "fixture_scale_mb": args.fixture_mb,
            "methods": args.methods,
            "datasets": {},
        }
        for dataset_name, source in datasets.items():
            print(f"Benchmarking {dataset_name}", flush=True)
            rows = []
            for method_name in args.methods:
                print(f"  {method_name}", flush=True)
                rows.append(
                    benchmark_method(source, method_name, root / "runs", args.repetitions)
                )
            results["datasets"][dataset_name] = rows  # type: ignore[index]

        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
