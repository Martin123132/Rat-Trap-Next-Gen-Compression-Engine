"""Explicit Store-a-folder orchestration over the existing storage engines.

No schedules, source deletion, automatic retention or saved credentials.
Publication and catalogue updates are separate commits: a catalogue failure
must never hide a successful save, or encourage overwriting the saved copy.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import gmw_tool, library, repository_engine, secure_engine


@dataclass(frozen=True)
class StoreRequest:
    source: Path
    destination: Path
    project_id: str
    mode: str = "archive"
    profile: str = "balanced"
    snapshot_label: str = ""


@dataclass(frozen=True)
class StoreResult:
    path: Path
    item: library.LibraryItem | None
    file_count: int
    total_bytes: int
    encrypted: bool
    snapshot_id: str | None = None
    catalogue_error: str | None = None
    resumed: bool = False


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_request(store: library.LibraryStore, request: StoreRequest) -> StoreRequest:
    """Read-only preflight; also repeated on the worker before any writes."""
    if request.mode not in {"archive", "backup"}:
        raise library.LibraryError("Choose a one-off archive or versioned backup")
    if request.profile not in {"fast", "balanced", "smallest"}:
        raise library.LibraryError("Choose Fast, Balanced or Smallest compression")
    if request.project_id not in {p.id for p in store.list_projects()}:
        raise library.LibraryError("Choose an existing Library project before storing a folder")
    source, destination = library._absolute(request.source), library._absolute(request.destination)
    library._guard_path(source)
    library._guard_path(destination, missing_ok=True)
    if not source.is_dir():
        raise library.LibraryError("Choose an existing source folder")
    if not destination.parent.is_dir():
        raise library.LibraryError("Choose an existing destination parent folder")
    if _within(destination, source) or (request.mode == "backup" and _within(source, destination)):
        raise library.LibraryError("Keep stored output outside the source; backup folders must not overlap")
    catalogue = store.catalog_path
    if _within(catalogue, source) or _within(destination, catalogue.parent) or (
            request.mode == "backup" and _within(catalogue, destination)):
        raise library.LibraryError("Keep the source and stored output separate from the Library catalogue folder")
    if request.mode == "archive":
        if destination.suffix.lower() != ".gmw":
            raise library.LibraryError("Use a new .gmw filename for the archive")
        if destination.exists():
            raise library.LibraryError("Archives are never overwritten here. Choose a new filename")
    elif destination.exists():
        if not destination.is_dir():
            raise library.LibraryError("Choose a new, empty or existing Rat-Trap backup folder")
        if any(destination.iterdir()):
            if not (destination / "repository.json").is_file():
                raise library.LibraryError("The selected nonempty folder is not a Rat-Trap backup repository")
            inspection = library.inspect_storage(destination)
            if inspection.kind != "repository":
                raise library.LibraryError("The selected folder is not a Rat-Trap backup repository")
    for item in store.list_items():
        if Path(item.path) == destination:
            if request.mode != "backup":
                raise library.LibraryError("This location is already in Library; choose a new archive filename")
            if item.project_id != request.project_id:
                raise library.LibraryError("This backup belongs to another project or is unassigned. Use Assign first")
            store.inspect_item(item.id)  # Reject swapped identities/manifests before mutation.
    if not isinstance(request.snapshot_label, str) or len(request.snapshot_label) > 500:
        raise library.LibraryError("Snapshot labels must contain at most 500 characters")
    return StoreRequest(source, destination, request.project_id, request.mode,
                        request.profile, request.snapshot_label.strip())


def store_folder(store: library.LibraryStore, request: StoreRequest, *,
                 encryption: dict | None = None,
                 progress: Callable[[str], None] | None = None) -> StoreResult:
    request = validate_request(store, request)
    encryption = dict(encryption or {})  # Secrets are transient, never persisted in Library.
    if set(encryption) - {"encryption_password", "recovery_key_output", "allow_plaintext_temp"}:
        raise library.LibraryError("Unsupported encryption options; replacement is not allowed")
    if encryption:
        if request.mode != "archive":
            raise library.LibraryError("Live versioned backups are not encrypted. Choose an encrypted archive instead")
        if (not encryption.get("encryption_password") or not encryption.get("recovery_key_output")
                or encryption.get("allow_plaintext_temp") is not True):
            raise library.LibraryError("Archive encryption requires a password, new recovery key and temporary-plaintext acknowledgement")
        secure_engine.validate_new_password(encryption["encryption_password"])
        recovery = library._absolute(encryption["recovery_key_output"])
        library._guard_path(recovery, missing_ok=True)
        if (recovery.exists() or recovery == request.destination or _within(recovery, request.source)
                or _within(recovery, store.catalog_path.parent)):
            raise library.LibraryError("Choose a new recovery-key location outside the source and Library catalogue")
        if not recovery.parent.is_dir():
            raise library.LibraryError("Choose an existing recovery-key parent folder")
        encryption["recovery_key_output"] = recovery

    def report(value):
        if progress:
            progress(value)

    source, destination = request.source, request.destination
    snapshot_id = None
    resumed = False
    report("Checking source folder…")
    # Shared engine policy rejects links, reparse points, ADS, unsupported
    # attributes and Windows name collisions before any destination is created.
    before = repository_engine._enumerate_source(source)
    if request.mode == "archive":
        report("Compressing folder… Original files will be kept.")
        with tempfile.TemporaryDirectory(prefix=".rat-trap-library-", dir=destination.parent,
                                         ignore_cleanup_errors=True) as temporary:
            staged = Path(temporary) / "archive.gmw"
            metadata = gmw_tool.compress_folder(source, staged, profile=request.profile, **encryption)
            if repository_engine._enumerate_source(source) != before:
                raise library.LibraryError("The source changed during compression. No archive was published; close editing apps and try again")
            inspection = library.inspect_storage(staged)
            identity = inspection.identity
            library._guard_path(destination, missing_ok=True)
            # Same-volume, no-replace publication. Do not use the engine's
            # ordinary replace-output path for an existing Library item.
            if os.name == "nt":
                os.rename(staged, destination)
            else:
                os.link(staged, destination)
                staged.unlink()
        file_count, total_bytes = metadata.file_count, metadata.total_bytes
    else:
        del before  # The backup engine owns its own source inventory.
        if not destination.exists() or not any(destination.iterdir()):
            repository_engine.init_repository(destination)
        identity = library.inspect_storage(destination).identity

        def snapshot_progress(event):
            report("Publishing snapshot…" if event.get("phase") == "publish" else
                   f"Backing up {event.get('completed_files', 0):,}/{event.get('total_files', 0):,} files…")

        # No automatic restart/prune. Interrupted work remains recoverable in
        # the existing Backups & history tools if source validation fails.
        snapshot = repository_engine.create_snapshot(destination, source,
                                                     label=request.snapshot_label,
                                                     progress=snapshot_progress)
        snapshot_id = snapshot.snapshot_id
        resumed = snapshot.resumed
        file_count, total_bytes = snapshot.file_count, snapshot.total_bytes
    report("Saved. Adding the result to your Library…")
    try:
        item = store.record_saved(destination, project_id=request.project_id,
                                  identity=identity, snapshot_id=snapshot_id)
    except Exception as exc:
        # Publication already succeeded. Preserve both data and an actionable
        # result even on DB locks, full disks or a concurrently removed project.
        return StoreResult(destination, None, file_count, total_bytes, bool(encryption),
                           snapshot_id, f"{type(exc).__name__}: {exc}", resumed)
    return StoreResult(destination, item, file_count, total_bytes, bool(encryption), snapshot_id, resumed=resumed)
