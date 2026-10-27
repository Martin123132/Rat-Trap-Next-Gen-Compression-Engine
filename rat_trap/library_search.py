"""Explicit, read-only Library search. Results live in memory, never on disk.

Search is filename/metadata discovery, not payload verification or full text
search. Protected items are never opened. Ordinary solid archives must be
streamed to discover filenames, with a bounded expanded stream and no extract.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from . import library, repository_engine, solid_engine

MAX_ITEMS = 1000
MAX_ENTRIES = 250000
MAX_NAMES_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024


class SearchCancelled(Exception):
    pass


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise SearchCancelled()


@dataclass(frozen=True)
class SearchResult:
    kind: str
    title: str
    project_id: str | None = None
    project: str = "Unassigned"
    item_id: str | None = None
    item_label: str = ""
    identity: str = ""
    path: str = ""
    member: str = ""
    snapshot_id: str | None = None
    manifest_sha256: str | None = None
    date: str = ""
    detail: str = ""
    size: int = 0


@dataclass(frozen=True)
class SearchReport:
    results: tuple[SearchResult, ...]
    warnings: tuple[str, ...]
    searched_items: int
    protected_items: int
    limited: bool
    cancelled: bool


def _member(path, size):
    if not isinstance(path, str) or len(path) > 4096 or any(ord(c) < 32 for c in path):
        raise library.LibraryError("Invalid or oversized filename metadata")
    solid_engine._normalise_member_path(path)
    if type(size) is not int or size < 0:
        raise library.LibraryError("Invalid file size metadata")
    return path, size


def _archive_files(path, cancel):
    """Yield filename metadata, without writes or payload materialization."""
    if solid_engine.is_solid_archive(path):
        with path.open("rb") as source:
            metadata, payload_size = solid_engine._read_layout(source)
            limited, decompressed, archive = solid_engine._open_tar_stream(
                source, metadata, payload_size, max_output_bytes=MAX_EXPANDED_BYTES)
            count = total = name_bytes = 0
            seen = {}
            try:
                for entry in archive:
                    _check(cancel)
                    if len(seen) >= MAX_ENTRIES:
                        raise library.LibraryError("Archive entry limit exceeded")
                    solid_engine._validate_tar_member(entry, allow_hardlinks=metadata.whole_file_dedup)
                    name, size = _member(entry.name, solid_engine._hardlink_size(entry) if entry.islnk() else entry.size)
                    name_bytes += len(name.encode("utf-8"))
                    if name_bytes > MAX_NAMES_BYTES:
                        raise library.LibraryError("Archive filename metadata limit exceeded")
                    folded = name.replace("\\", "/").casefold()
                    if folded in seen:
                        raise library.LibraryError("Duplicate archive filename")
                    if entry.islnk():
                        target = entry.linkname.replace("\\", "/").casefold()
                        if seen.get(target) != size:
                            raise library.LibraryError("Invalid deduplicated file target")
                    seen[folded] = None if entry.isdir() else size
                    if not entry.isdir():
                        count += 1
                        total += size
                        yield name, size
                _check(cancel)
                solid_engine._finish_read(limited, decompressed, metadata)
                if count != metadata.file_count or total != metadata.total_bytes:
                    raise library.LibraryError("Archive inventory does not match its metadata")
            finally:
                archive.close()
                decompressed.close()
    else:
        # Identity/schema were inspected first. Immutable mode cannot write a
        # journal/SHM beside the archive; active writers are explicitly refused.
        library._inspect_sqlite(path)
        with closing(library._readonly_sqlite(path, immutable=True)) as connection:
            for row in connection.execute("SELECT path,size FROM files LIMIT ?", (MAX_ENTRIES + 1,)):
                _check(cancel)
                yield _member(row["path"], row["size"])


def _files(item, inspection, cancel):
    path = Path(item.path)
    if item.kind != "repository":
        for name, size in _archive_files(path, cancel):
            yield name, size, None
        return
    for snapshot in sorted(inspection.snapshots, key=lambda s: (s.occurred_at, s.snapshot_id), reverse=True):
        _check(cancel)
        raw = library._read_bounded(path / "manifests" / (snapshot.manifest_sha256 + ".rtsnap.json"), library.MAX_MANIFEST_BYTES)
        manifest = library._json_object(raw)
        if repository_engine._manifest_hash(manifest) != snapshot.manifest_sha256:
            raise library.LibraryError("Snapshot changed during search")
        for entry in manifest["entries"]:
            _check(cancel)
            if entry["kind"] == "file":
                name, size = _member(entry["path"], entry["size"])
                yield name, size, snapshot


def search_library(store, query, *, filenames=True, limit=500, cancel=None, progress=None):
    """Literal Unicode-insensitive substring search, all projects by default.

    A source's matching filenames are published only after its complete bounded
    scan succeeds and its identity is rechecked. Failures leave catalogue-only
    matches usable and are always reported; no stale filename cache is used.
    """
    query = library._text(query, "Search", 300).casefold()
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise library.LibraryError("Search result limit must be between 1 and 1000")
    projects = {p.id: p for p in store.list_projects()}
    items = store.list_items()
    by_id = {i.id: i for i in items}
    results, warnings = [], []
    searched = protected = 0
    limited = cancelled = False

    def add(result):
        nonlocal limited
        if len(results) < limit:
            results.append(result)
        else:
            limited = True

    def project_name(key):
        return projects[key].name if key in projects else "Unassigned"

    for project in projects.values():
        if query in (project.name + " " + project.description).casefold():
            add(SearchResult("Project", project.name, project.id, project.name, detail=project.description))
    for item in items:
        if query in (item.label + " " + item.path).casefold():
            add(SearchResult("Locked item" if item.protected else "Stored item", item.label,
                item.project_id, project_name(item.project_id), item.id, item.label, item.identity, item.path,
                detail="Catalogue label/location only; contents have not been searched."))
    # Filtering happens before LIMIT, so old matching notes aren't hidden by the
    # timeline's 500 newest-event display limit. '%' and '_' are literal text.
    for event in store.timeline(query=query, limit=limit + 1):
        item = by_id.get(event.item_id)
        add(SearchResult("Note" if event.kind == "note" else "Timeline", event.detail if event.kind == "note" else event.title,
            event.project_id, project_name(event.project_id), event.item_id,
            item.label if item else "", item.identity if item else "", item.path if item else "",
            snapshot_id=event.snapshot_id, date=event.occurred_at, detail=event.detail))
    try:
        _check(cancel)
        if filenames:
            for index, item in enumerate(items):
                _check(cancel)
                if index >= MAX_ITEMS:
                    warnings.append(f"Only the first {MAX_ITEMS} registered items were considered for filenames.")
                    limited = True
                    break
                if item.protected:
                    protected += 1
                    continue
                if progress:
                    progress(f"Searching filenames: {index + 1}/{len(items)} · {item.label}")
                pending = []
                item_limited = False
                try:
                    inspection = store.inspect_item(item.id)
                    before = library._signature(Path(item.path)) if item.kind != "repository" else None
                    count = name_bytes = 0
                    iterator = _files(item, inspection, cancel)
                    with closing(iterator):
                        for name, size, snapshot in iterator:
                            count += 1
                            name_bytes += len(name.encode("utf-8"))
                            if count > MAX_ENTRIES or name_bytes > MAX_NAMES_BYTES:
                                raise library.LibraryError("Filename search limit exceeded for this stored item")
                            if query in name.casefold():
                                if len(pending) < limit + 1:
                                    pending.append(SearchResult("File", name, item.project_id,
                                        project_name(item.project_id), item.id, item.label, item.identity, item.path, name,
                                        snapshot.snapshot_id if snapshot else None,
                                        snapshot.manifest_sha256 if snapshot else None,
                                        snapshot.occurred_at if snapshot else "", "Filename match; use Verify to check stored data.", size))
                                else:
                                    item_limited = True
                    _check(cancel)
                    after = store.inspect_item(item.id)
                    current = store.get_item(item.id)
                    if current != item or after != inspection or (before is not None and before != library._signature(Path(item.path))):
                        raise library.LibraryError("Stored item changed during search; run the search again")
                    searched += 1
                    limited |= item_limited
                    for result in pending:
                        add(result)
                except SearchCancelled:
                    raise
                except Exception as exc:
                    warnings.append(f"{item.label}: {str(exc)[:500]}")
    except SearchCancelled:
        cancelled = True
    return SearchReport(tuple(results), tuple(warnings), searched, protected, limited, cancelled)


def validate_result(store, result):
    """Never silently route a stale hit to different bytes or another version."""
    item = store.get_item(result.item_id)
    if item.identity != result.identity:
        raise library.LibraryError("This search result is stale. Search again.")
    inspection = store.inspect_item(item.id)
    if result.snapshot_id:
        snapshot = next((s for s in inspection.snapshots if s.snapshot_id == result.snapshot_id), None)
        if snapshot is None or (result.manifest_sha256 and snapshot.manifest_sha256 != result.manifest_sha256):
            raise library.LibraryError("That exact backup version is unavailable or changed. No other version was selected.")
    if result.member and item.protected:
        raise library.LibraryError("Protected contents cannot be opened from Library search")
    return item, inspection
