"""One-file Library restore into a new folder, with verified staged publication.

Only unencrypted Vaults and exact repository snapshots are supported here.
The Windows desktop workflow never merges into an existing destination.
Receipts are ordinary local plaintext notes; publication and receipt creation
are separate operations, so a failed receipt cannot hide a successful restore.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from . import library, library_search, repository_engine, vault_engine


@dataclass(frozen=True)
class RestoreRequest:
    result: library_search.SearchResult
    destination: Path


@dataclass(frozen=True)
class RestorePlan:
    request: RestoreRequest
    item: library.LibraryItem
    member: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RestoreResult:
    path: Path
    destination: Path
    size: int
    sha256: str
    snapshot_id: str | None
    event: library.TimelineEvent | None = None
    catalogue_error: str | None = None


def _within(path, parent):
    return path == parent or parent in path.parents


def validate_destination(store, destination):
    destination = library._absolute(destination)
    library._guard_path(destination, missing_ok=True)
    if os.path.lexists(destination):
        raise library.LibraryError("Choose a NEW restore folder. Existing folders and files are never replaced or merged")
    if not destination.parent.is_dir():
        raise library.LibraryError("Choose an existing parent folder for the new restore folder")
    if _within(destination, store.catalog_path.parent) or _within(store.catalog_path, destination):
        raise library.LibraryError("Keep restored files outside the Library catalogue folder")
    # Also protect other projects' registered repositories, not just the source.
    for item in store.list_items():
        path = library._absolute(item.path)
        if destination == path or (item.kind == "repository" and (_within(destination, path) or _within(path, destination))):
            raise library.LibraryError("Keep restored files separate from registered storage")
    return destination


def validate_request(store, request):
    if os.name != "nt":
        raise library.LibraryError("Direct Library restore currently requires Windows")
    hit = request.result
    if hit.kind != "File" or not hit.item_id or not hit.member:
        raise library.LibraryError("Select an individual filename from Library search")
    member = repository_engine._normalise_stored_path(hit.member)
    if member != hit.member:
        raise library.LibraryError("Search again to obtain an exact portable filename")
    destination = validate_destination(store, request.destination)
    item, _ = library_search.validate_result(store, hit)
    if item.protected or item.kind not in {"vault", "repository"}:
        raise library.LibraryError("Direct restore currently supports unencrypted Vaults and versioned backups only")
    if item.project_id != hit.project_id:
        raise library.LibraryError("The item's project changed. Search again before restoring")
    path = Path(item.path)
    if item.kind == "repository":
        if not hit.snapshot_id or not hit.manifest_sha256:
            raise library.LibraryError("An exact backup snapshot and checksum are required")
        manifest = library._json_object(library._read_bounded(
            path / "manifests" / (hit.manifest_sha256 + ".rtsnap.json"), library.MAX_MANIFEST_BYTES))
        if repository_engine._manifest_hash(manifest) != hit.manifest_sha256:
            raise library.LibraryError("The selected snapshot changed; nothing was restored")
        rows = [entry for entry in manifest["entries"] if entry["kind"] == "file" and entry["path"] == member]
    else:
        if hit.snapshot_id is not None:
            raise library.LibraryError("Vault archives do not have backup snapshot IDs")
        with closing(library._readonly_sqlite(path, immutable=True)) as connection:
            rows = connection.execute("SELECT path,size,sha256 FROM files WHERE path=? LIMIT 2", (member,)).fetchall()
    if len(rows) != 1:
        raise library.LibraryError("The exact selected file is unavailable; search again")
    row = rows[0]
    if (type(row["size"]) is not int or row["size"] < 0 or row["size"] != hit.size or
            not isinstance(row["sha256"], str) or not library._HEX64.fullmatch(row["sha256"])):
        raise library.LibraryError("Selected file metadata is invalid or changed")
    return RestorePlan(RestoreRequest(hit, destination), item, member, row["size"], row["sha256"])


def _verify_output(root, plan):
    expected = root / Path(plan.member)
    library._guard_path(expected)
    files = []
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in (*directories, *names):
            candidate = Path(parent) / name
            library._guard_path(candidate)
            if candidate.is_file():
                files.append(candidate)
    if files != [expected] or expected.stat().st_size != plan.size:
        raise library.LibraryError("Restore did not produce exactly the selected file")
    digest = hashlib.sha256()
    with expected.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != plan.sha256:
        raise library.LibraryError("Restored file checksum failed; no destination was published")


def _publish(staged, destination):
    # Windows rename refuses any existing destination atomically. Do not fall
    # back to POSIX rename, which can replace an existing empty directory.
    if os.name != "nt":
        raise library.LibraryError("Direct Library restore publication currently requires Windows")
    os.rename(staged, destination)


def restore_file(store, request, *, progress=None):
    plan = validate_request(store, request)
    destination, hit = plan.request.destination, plan.request.result
    parent_identity = library._signature(destination.parent)[:2]
    def report(text):
        if progress:
            # A disconnected UI must never turn published data into a reported
            # failure, or prevent the durable receipt from being attempted.
            try:
                progress(text)
            except Exception:
                pass
    report("Restoring the selected file into private staging…")
    with tempfile.TemporaryDirectory(prefix=".rat-trap-library-restore-", dir=destination.parent,
                                     ignore_cleanup_errors=True) as temporary:
        staged = Path(temporary) / "restored"
        if plan.item.kind == "vault":
            vault_engine.extract_vault(Path(plan.item.path), staged, paths=[plan.member], immutable=True)
        else:
            repository_engine.restore_snapshot(Path(plan.item.path), hit.snapshot_id, staged,
                paths=[plan.member], expected_manifest_sha256=hit.manifest_sha256)
        report("Checking restored bytes and the exact source version…")
        _verify_output(staged, plan)
        current, _ = library_search.validate_result(store, hit)
        if current.project_id != plan.item.project_id:
            raise library.LibraryError("The item's project changed during restore; nothing was published")
        validate_destination(store, destination)
        if library._signature(destination.parent)[:2] != parent_identity:
            raise library.LibraryError("The destination parent changed during restore")
        library._guard_path(staged)
        _publish(staged, destination)
    restored = destination / Path(plan.member)
    report("File restored and verified. Recording the timeline receipt…")
    try:
        event = store.record_restored(plan.item.id, identity=plan.item.identity, project_id=plan.item.project_id,
            member=plan.member, destination=str(restored), sha256=plan.sha256, snapshot_id=hit.snapshot_id)
    except Exception as exc:
        return RestoreResult(restored, destination, plan.size, plan.sha256, hit.snapshot_id,
                             catalogue_error=f"{type(exc).__name__}: {exc}")
    return RestoreResult(restored, destination, plan.size, plan.sha256, hit.snapshot_id, event=event)
