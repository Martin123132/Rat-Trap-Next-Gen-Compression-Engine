"""Explicit read-only storage checks and dated, schema-v1 Library receipts.

Never invoke repository recovery, repair, extraction or on-disk cache rebuild.
Receipts are unencrypted historical observations, not live health guarantees.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
from collections import OrderedDict
from contextlib import closing, contextmanager
from pathlib import Path

from . import library, repository_engine as engine, vault_engine

MAX_ITEMS = 1000
MAX_PATHS = 50000
MAX_OBJECTS = 250000
MAX_PACK_BYTES = 2 * 1024**3
STATUSES = {"Verified", "Needs attention", "Locked", "Not checked"}
AVAILABILITY = {"Located", "Missing", "Changed", "Unavailable", "Not checked"}


class Cancelled(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class HealthResult:
    item_id: str
    identity: str
    path: str
    project_id: str | None
    checked_at: str
    availability: str
    status: str
    detail: str
    file_count: int = 0
    snapshot_count: int = 0
    logical_bytes: int = 0
    fingerprint: str = ""
    receipt_error: str = ""

    def receipt(self):
        value = dataclasses.asdict(self)
        value.pop("receipt_error")
        return json.dumps({"schema": "rat-trap-library-health/v1", **value}, ensure_ascii=False, sort_keys=True)


@dataclasses.dataclass(frozen=True)
class HealthReport:
    results: tuple[HealthResult, ...]
    cancelled: bool = False
    limited: bool = False


def parse_receipt(raw, item):
    """Reject damaged, stale-context or arbitrary notes, never invent a green result."""
    try:
        value = json.loads(raw)
        if value.pop("schema") != "rat-trap-library-health/v1":
            return None
        result = HealthResult(**value)
        if (result.item_id != item.id or result.identity != item.identity or result.path != item.path
                or result.project_id != item.project_id or result.status not in STATUSES
                or result.availability not in AVAILABILITY or result.receipt_error
                or any(type(getattr(result, field)) is not int or getattr(result, field) < 0
                       for field in ("file_count", "snapshot_count", "logical_bytes"))):
            return None
        library._stored_time(result.checked_at)
        library._text(result.detail, "Health details", 4000)
        if result.fingerprint and not library._HEX64.fullmatch(result.fingerprint):
            return None
        if result.status == "Verified" and (result.availability != "Located" or not result.fingerprint):
            return None
        return result
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def latest_results(store, items):
    receipts = store.latest_health_receipts()
    results = {}
    for item in items:
        result = parse_receipt(receipts.get(item.id, ""), item)
        if result is None:
            continue
        if item.status != "available" and item.last_checked_at > result.checked_at:
            result = dataclasses.replace(result, status="Needs attention", fingerprint="",
                availability={"missing": "Missing", "changed": "Changed"}.get(item.status, "Unavailable"),
                detail="A newer availability check found a problem. The previous health result is no longer sufficient; check again.")
        results[item.id] = result
    return results


def describe(result):
    return (f"{result.status} — {result.availability}\nChecked at: {result.checked_at}\n"
            f"{result.detail}\nFiles checked: {result.file_count:,}; snapshots: {result.snapshot_count:,}; "
            f"logical bytes: {result.logical_bytes:,}\n"
            "Historical result only. Recheck after changes; keep an independent backup."
            + (f"\nReceipt NOT saved: {result.receipt_error}" if result.receipt_error else ""))


@contextmanager
def _read_lock(root):
    """Use an existing lifecycle lock read-only; never create or repair it."""
    path = root / "locks" / "repository.lock"
    library._guard_path(path)
    if path.stat().st_size < 1:
        raise library.LibraryError("Repository lock is incomplete; use Backups & history to investigate")
    with path.open("rb") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            raise library.LibraryError("Repository is busy. Close other backup operations and check again") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _inventory(root, checkpoint):
    """Guard before descent; do not follow links or enumerate trash/source paths."""
    paths = {"repository.json": library._signature(root / "repository.json")}
    pending = [root / name for name in ("packs", "manifests", "refs/pins", "staging")]
    while pending:
        checkpoint()
        current = pending.pop()
        library._guard_path(current)
        relative = current.relative_to(root).as_posix()
        if len(paths) >= MAX_PATHS or len(current.relative_to(root).parts) > 8:
            raise library.LibraryError("Repository exceeds the health-check path/depth limit")
        paths[relative] = library._signature(current)
        if current.is_dir():
            with os.scandir(current) as entries:
                for entry in entries:
                    if len(pending) + len(paths) >= MAX_PATHS:
                        raise library.LibraryError("Repository exceeds the health-check path limit")
                    pending.append(Path(entry.path))
        elif relative.endswith(("-wal", "-shm", "-journal")):
            raise library.LibraryError("Active database sidecar found; close writers and check again")
    return paths


class _MemoryReader(engine._ObjectReader):
    """Reuse the engine's checked object reader with a disposable RAM-only index."""
    def __init__(self, root):
        self.root = root
        self.catalog = sqlite3.connect(":memory:")
        self.catalog.row_factory = sqlite3.Row
        self.catalog.executescript("""PRAGMA temp_store=MEMORY;
            CREATE TABLE packs(pack_id TEXT PRIMARY KEY,relpath TEXT,created_at_ns INTEGER);
            CREATE TABLE object_locations(object_id TEXT,pack_id TEXT,raw_size INTEGER);
            CREATE INDEX objects_by_id ON object_locations(object_id);""")
        self.packs = OrderedDict()
        self.decompressor = engine.zstd.ZstdDecompressor()

    def _pack(self, relpath):
        path = self.root / relpath
        library._guard_path(path)
        for suffix in ("-wal", "-shm", "-journal"):
            if os.path.lexists(str(path) + suffix):
                raise library.LibraryError("Pack writer appeared during verification")
        return super()._pack(relpath)


def _check_pack(path, remaining, checkpoint):
    library._guard_path(path)
    if path.stat().st_size > MAX_PACK_BYTES:
        raise library.LibraryError("Pack exceeds the 2 GiB health-check limit")
    with closing(engine._open_sqlite_readonly(path, immutable=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        definitions = connection.execute("SELECT type FROM sqlite_master LIMIT 101").fetchall()
        if len(definitions) > 100 or any(row[0] in {"trigger", "view"} for row in definitions):
            raise library.LibraryError("Unsupported pack database schema")
        count, largest = connection.execute("SELECT count(*),max(length(data)) FROM objects").fetchone()
        if count > remaining or (largest is not None and largest > engine.MAX_OBJECT_SIZE):
            raise library.LibraryError("Pack exceeds health-check object or payload limits")
        checkpoint()
        rows = connection.execute("PRAGMA integrity_check").fetchall()
        if len(rows) != 1 or rows[0][0] != "ok":
            raise library.LibraryError("Pack database integrity check failed")


def _verify_repository(store, item, checkpoint):
    root = Path(item.path)
    with _read_lock(root):
        checkpoint()
        inspection = store.inspect_item(item.id)
        if not inspection.snapshots:
            raise library.LibraryError("No completed backup snapshots to verify")
        jobs = root / "staging" / "jobs"
        if any(jobs.iterdir()) or any(path.name != "jobs" for path in (root / "staging").iterdir()):
            raise library.LibraryError("Pending backup/recovery work exists. Review Backups & history; nothing was repaired")
        before = _inventory(root, checkpoint)
        config = library._json_object(library._read_bounded(root / "repository.json", 65536))
        current = {s.snapshot_id: s.manifest_sha256 for s in inspection.snapshots}
        with store._connection() as connection:
            known = dict(connection.execute("SELECT snapshot_id,manifest_sha256 FROM events WHERE item_id=? AND kind='snapshot'", (item.id,)))
        if any(current.get(key) != value for key, value in known.items()):
            raise library.LibraryError("Previously listed backup versions are missing or changed. Check history before relying on this repository")
        for name in before:
            if name.startswith("refs/pins/"):
                path = root / name
                if not path.is_file() or path.suffix != ".json" or path.stem not in current:
                    raise library.LibraryError("Repository has an unexpected or orphaned snapshot pin")
        count = total = objects = 0
        with _MemoryReader(root) as reader:
            for name in sorted(before):
                checkpoint()
                if not name.startswith("packs/") or (root / name).is_dir():
                    continue
                path = root / name
                if path.suffix != ".rtpack":
                    raise library.LibraryError("Unexpected file in repository packs")
                _check_pack(path, MAX_OBJECTS - objects, checkpoint)
                info, rows = engine._load_pack_index(path, config, full=True, checkpoint=checkpoint)
                if engine._pack_path(root, info["pack_id"]) != path:
                    raise library.LibraryError("Pack location does not match its identity")
                objects += len(rows)
                reader.catalog.execute("INSERT INTO packs VALUES(?,?,?)", (info["pack_id"], name, info["created_at_ns"]))
                reader.catalog.executemany("INSERT INTO object_locations VALUES(?,?,?)",
                    ((row["object_id"], info["pack_id"], row["raw_size"]) for row in rows))
            for snapshot in inspection.snapshots:
                checkpoint()
                value = library._json_object(library._read_bounded(
                    root / "manifests" / (snapshot.manifest_sha256 + ".rtsnap.json"), library.MAX_MANIFEST_BYTES))
                _, value = engine._validate_manifest(value, config, expected_hash=snapshot.manifest_sha256)
                for entry in value["entries"]:
                    checkpoint()
                    if entry["kind"] != "file":
                        continue
                    digest, size = hashlib.sha256(), 0
                    for object_id, raw_size in entry["chunks"]:
                        checkpoint()
                        raw = reader.read(object_id, raw_size)
                        digest.update(raw)
                        size += len(raw)
                    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                        raise library.LibraryError("Backup file checksum verification failed")
                    count += 1
                    total += size
        if before != _inventory(root, checkpoint):
            raise library.LibraryError("Repository changed during verification; check again when idle")
        fingerprint = hashlib.sha256(engine._canonical_json({"identity": item.identity, "inventory": before})).hexdigest()
        return count, len(inspection.snapshots), total, fingerprint


def check_item(store, item, *, cancel=None, progress=None):
    def checkpoint():
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled before verification completed")

    availability, status, detail = "Not checked", "Not checked", "Not checked"
    counts, fingerprint = (0, 0, 0), ""
    try:
        checkpoint()
        path = library._absolute(item.path)
        library._guard_path(path)
        availability = "Located"
        if progress:
            progress(f"Checking {item.label} — reading stored data; no repair or restore…")
        if item.protected:
            status, detail = "Locked", "Storage is located. Protected contents were not opened, decrypted or verified."
        elif item.kind not in {"vault", "repository"}:
            detail = "Storage is located. Integrity checks in this stage cover Vaults and versioned backups only."
        else:
            inspection = store.inspect_item(item.id)
            checkpoint()
            if item.kind == "vault":
                # Refuse abnormally oversized BLOBs before the engine materialises
                # them; decompressed chunks are also bounded by its normal checks.
                with closing(vault_engine._open_readonly(path, immutable=True)) as connection:
                    metadata = vault_engine._load_metadata(connection)
                    largest = connection.execute("SELECT max(length(data)) FROM objects").fetchone()[0]
                    if largest is not None and largest > metadata.chunk_size + 1024 * 1024:
                        raise library.LibraryError("Vault object exceeds the health-check payload limit")
                metadata = vault_engine.verify_vault(path, immutable=True, checkpoint=checkpoint)
                checkpoint()
                after = store.inspect_item(item.id)
                if inspection != after:
                    raise library.LibraryError("Vault changed during verification")
                counts = metadata.file_count, 0, metadata.total_bytes
                fingerprint = item.identity.removeprefix("sha256:")
                detail = "All stored file contents and Vault database integrity checked. Search indexes are not a second backup."
            else:
                files, snapshots, size, fingerprint = _verify_repository(store, item, checkpoint)
                counts = files, snapshots, size
                detail = "All completed snapshot files and sealed packs checked. Cache, trash and original source folders were not verified or repaired."
            checkpoint()
            current = store.get_item(item.id)
            if any(getattr(current, key) != getattr(item, key) for key in ("identity", "path", "project_id", "kind")):
                raise library.LibraryError("Library item changed during verification; check again")
            status = "Verified"
    except FileNotFoundError:
        availability = "Missing" if availability == "Not checked" else availability
        status, detail = "Needs attention", "Storage or required data is missing. Locate the same item or inspect an independent backup."
    except library.IdentityMismatchError:
        availability, status, detail = "Changed", "Needs attention", "Storage no longer matches its registered identity. No replacement was accepted."
    except Exception as exc:
        if isinstance(exc, Cancelled) or (cancel is not None and cancel.is_set()):
            status, detail = "Not checked", "Cancelled — this item was not fully verified."
        else:
            status, detail = "Needs attention", f"Verification did not complete: {type(exc).__name__}: {exc}"[:3500]
            if availability == "Not checked":
                availability = "Unavailable"
        counts, fingerprint = (0, 0, 0), ""
    if status != "Verified":
        counts, fingerprint = (0, 0, 0), ""
    result = HealthResult(item.id, item.identity, item.path, item.project_id, library._now(),
                          availability, status, detail, *counts, fingerprint)
    try:
        store.record_health(item, result.receipt())
    except Exception as exc:
        result = dataclasses.replace(result, receipt_error=f"{type(exc).__name__}: {exc}"[:1000])
    return result


def check_library(store, *, item_ids=None, cancel=None, progress=None):
    items = store.list_items()
    if item_ids is not None:
        items = [item for item in items if item.id in item_ids]
    limited = len(items) > MAX_ITEMS
    results = []
    for item in items[:MAX_ITEMS]:
        if cancel is not None and cancel.is_set():
            break
        results.append(check_item(store, item, cancel=cancel, progress=progress))
    return HealthReport(tuple(results), bool(cancel is not None and cancel.is_set()), limited)
