"""Build a compact, source-documented Rat-Trap beta test corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path, PurePosixPath


SOURCES = {
    "shakespeare": {
        "url": "https://storage.googleapis.com/download.tensorflow.org/data/shakespeare.txt",
        "filename": "shakespeare.txt",
    },
    "adult": {
        "url": "https://archive.ics.uci.edu/static/public/2/adult.zip",
        "filename": "adult.zip",
    },
    "speech": {
        "url": "https://storage.googleapis.com/download.tensorflow.org/data/mini_speech_commands.zip",
        "filename": "mini_speech_commands.zip",
    },
}

README = """Rat-Trap beta test data
=======================

Purpose
-------
This compact corpus exercises text, structured records, many small PNG files,
WAV audio, exact duplicate blocks, and files that are already compressed.
Extract this ZIP, choose the Rat-Trap-Beta-Test-Data folder in the Windows app,
and try each compression profile. MANIFEST.json records a SHA-256 digest for
every file so restored output can be checked exactly.

Sources and terms
-----------------
1. Tiny Shakespeare, downloaded from the official TensorFlow text-generation
   tutorial data URL:
   https://storage.googleapis.com/download.tensorflow.org/data/shakespeare.txt

2. UCI Adult, Becker and Kohavi (1996), DOI 10.24432/C5XW20. UCI publishes
   this dataset under Creative Commons Attribution 4.0:
   https://archive.ics.uci.edu/dataset/2/adult

3. CIFAR-10, Alex Krizhevsky, Vinod Nair, and Geoffrey Hinton. This pack
   contains the 100 sample PNGs displayed on the official dataset page. Cite
   "Learning Multiple Layers
   of Features from Tiny Images", Alex Krizhevsky, 2009. The official page
   does not state an explicit dataset license; keep this subset for local
   evaluation and consult the source before redistributing it:
   https://www.cs.toronto.edu/~kriz/cifar.html

4. Mini Speech Commands, collected by Google and released under CC BY. This
   pack selects 12 WAV files from each of its eight command folders:
   https://www.tensorflow.org/tutorials/audio/simple_audio

Folder guide
------------
01-text             one large, highly compressible text file
02-structured       CSV-like census records and schema text
03-images-png       100 small, already-compressed PNG images
04-audio-wav        96 real speech WAV files
05-duplicate-blocks three exact copies of an 8 MiB block built from the PNGs
06-many-small-files Shakespeare split into 256 small files
07-precompressed    a ZIP of 100 PNG images (archive-inside-archive case)

The data is for local compression testing. Source datasets retain their own
terms and attribution requirements.
"""


def digest_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as fp:
        while True:
            block = fp.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": "Rat-Trap-Beta-Builder/1"})
    for attempt in range(1, 6):
        print(f"Downloading {url} (attempt {attempt})", flush=True)
        try:
            with urllib.request.urlopen(request, timeout=120) as response, open(temporary, "wb") as out:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
            temporary.replace(target)
            return
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            if attempt == 5:
                raise
            time.sleep(2 ** (attempt - 1))


def safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe downloaded archive entry: {name!r}")
    return path


def add_adult(source_zip: Path, output: Path) -> None:
    target = output / "02-structured"
    target.mkdir(exist_ok=True)
    wanted = {"adult.data", "adult.test", "adult.names", "old.adult.names", "Index"}
    with zipfile.ZipFile(source_zip) as archive:
        for info in archive.infolist():
            name = safe_name(info.filename)
            if info.is_dir() or name.name not in wanted:
                continue
            with archive.open(info) as source, open(target / name.name, "wb") as out:
                shutil.copyfileobj(source, out)


def add_cifar(cache: Path, output: Path) -> dict[str, tuple[Path, str]]:
    png_dir = output / "03-images-png"
    png_dir.mkdir(exist_ok=True)
    raw_dir = output / "05-duplicate-blocks"
    raw_dir.mkdir(exist_ok=True)
    classes = (
        "airplane", "automobile", "bird", "cat", "deer",
        "dog", "frog", "horse", "ship", "truck",
    )
    downloaded: dict[str, tuple[Path, str]] = {}
    payload_parts: list[bytes] = []
    for label in classes:
        label_dir = png_dir / label
        label_dir.mkdir(exist_ok=True)
        for index in range(1, 11):
            filename = f"{label}{index}.png"
            url = f"https://cave.cs.toronto.edu/kriz/cifar-10-sample/{filename}"
            cached = cache / filename
            download(url, cached)
            data = cached.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Official CIFAR sample is not a PNG: {filename}")
            shutil.copy2(cached, label_dir / filename)
            payload_parts.append(struct.pack("<I", len(data)) + data)
            downloaded[f"cifar-{filename}"] = (cached, url)

    seed = b"".join(payload_parts)
    target_size = 8 * 1024 * 1024
    # Use a deterministic high-entropy payload so this fixture measures exact
    # cross-file deduplication. Repeating the small PNG bundle inside each file
    # let an ordinary short-window compressor appear to deduplicate it.
    duplicate_payload = hashlib.shake_256(seed).digest(target_size)
    for copy_index in range(3):
        (raw_dir / f"cifar_raw_copy_{copy_index + 1}.bin").write_bytes(duplicate_payload)
    return downloaded


def add_speech(source_zip: Path, output: Path) -> None:
    target = output / "04-audio-wav"
    target.mkdir(exist_ok=True)
    labels = {"down", "go", "left", "no", "right", "stop", "up", "yes"}
    selected: dict[str, int] = {label: 0 for label in labels}
    with zipfile.ZipFile(source_zip) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            name = safe_name(info.filename)
            if (
                info.is_dir()
                or name.suffix.lower() != ".wav"
                or len(name.parts) < 2
                or "__MACOSX" in name.parts
                or name.name.startswith("._")
                or info.file_size < 44
            ):
                continue
            label = name.parts[-2]
            if label not in labels or selected[label] >= 12:
                continue
            label_dir = target / label
            label_dir.mkdir(exist_ok=True)
            with archive.open(info) as source:
                wav = source.read()
            if not (wav.startswith(b"RIFF") and wav[8:12] == b"WAVE"):
                continue
            (label_dir / name.name).write_bytes(wav)
            selected[label] += 1
    if any(count != 12 for count in selected.values()):
        raise ValueError(f"Speech sample selection was incomplete: {selected}")


def add_small_files(shakespeare: bytes, output: Path) -> None:
    target = output / "06-many-small-files"
    target.mkdir(exist_ok=True)
    chunk_size = (len(shakespeare) + 255) // 256
    for index in range(256):
        block = shakespeare[index * chunk_size : (index + 1) * chunk_size]
        (target / f"scene_{index:03d}.txt").write_bytes(block)


def add_precompressed(output: Path) -> None:
    target = output / "07-precompressed"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(target / "cifar_png_sample.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((output / "03-images-png").rglob("*.png"))[:100]:
            archive.write(path, path.name)


def build_manifest(output: Path, downloads: dict[str, tuple[Path, str]]) -> None:
    files = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "MANIFEST.json":
            continue
        files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest_file(path),
            }
        )
    manifest = {
        "schema": "rat-trap-beta-data-1",
        "files": files,
        "total_bytes": sum(item["bytes"] for item in files),
        "file_count": len(files),
        "downloads": {
            name: {
                "url": url,
                "bytes": path.stat().st_size,
                "sha256": digest_file(path),
            }
            for name, (path, url) in downloads.items()
        },
    }
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (args.folder.exists() and not args.resume) or args.zip.exists():
        raise FileExistsError("Beta output already exists; choose new paths or remove it explicitly")
    downloads: dict[str, tuple[Path, str]] = {}
    for name, source in SOURCES.items():
        target = args.cache / str(source["filename"])
        download(str(source["url"]), target)
        expected_md5 = source.get("md5")
        if expected_md5 and digest_file(target, "md5") != expected_md5:
            raise ValueError(f"Checksum mismatch for {target.name}")
        downloads[name] = (target, str(source["url"]))

    args.folder.mkdir(parents=True, exist_ok=True)
    text = downloads["shakespeare"][0].read_bytes()
    text_dir = args.folder / "01-text"
    text_dir.mkdir(exist_ok=True)
    (text_dir / "shakespeare.txt").write_bytes(text)
    add_adult(downloads["adult"][0], args.folder)
    downloads.update(add_cifar(args.cache / "cifar-samples", args.folder))
    add_speech(downloads["speech"][0], args.folder)
    add_small_files(text, args.folder)
    add_precompressed(args.folder)
    (args.folder / "README.txt").write_text(README, encoding="utf-8")
    build_manifest(args.folder, downloads)

    args.zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(item for item in args.folder.rglob("*") if item.is_file()):
            archive.write(path, (Path(args.folder.name) / path.relative_to(args.folder)).as_posix())
    print(f"Built {args.folder}")
    print(f"Built {args.zip}")


if __name__ == "__main__":
    main()
