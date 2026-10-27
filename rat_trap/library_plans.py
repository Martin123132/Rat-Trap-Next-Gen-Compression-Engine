"""Manually run, identity-pinned backup plans; no scheduler or saved credentials.

Plan settings live in bounded library_meta records in the existing v1 catalogue.
Older apps leave them alone. Only explicit plan actions read source/storage.
"""
from __future__ import annotations

import dataclasses
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from . import library, library_storage, repository_engine as engine

PREFIX = "backup_plan:"
MAX_PLANS = 1000
MAX_RECORD = 24000
STATUSES = {"Never run", "Running / review required", "Succeeded", "Needs attention", "Saved; Library needs attention"}


@dataclass(frozen=True)
class BackupPlan:
    id: str
    name: str
    source: str
    destination: str
    project_id: str
    source_identity: tuple[int, int]
    repository_identity: str
    destination_identity: tuple[int, int] | None
    parent_identity: tuple[int, int]
    created_at: str
    updated_at: str
    last_status: str = "Never run"
    last_run_at: str = ""
    last_detail: str = ""
    last_snapshot_id: str = ""
    last_success_at: str = ""
    last_success_snapshot: str = ""


@dataclass(frozen=True)
class RunResult:
    plan: BackupPlan
    saved: library_storage.StoreResult | None = None
    record_error: str = ""


def _directory_id(path):
    library._guard_path(path)
    if not path.is_dir():
        raise library.LibraryError("Expected an ordinary local folder")
    info = path.stat()
    if not info.st_ino:
        raise library.LibraryError("This filesystem cannot provide a stable folder identity")
    return info.st_dev, info.st_ino


def _decode(raw):
    try:
        value = library._json_object(raw.encode("utf-8"))
        if value.pop("schema") != "rat-trap-backup-plan/v1":
            raise ValueError("schema")
        for field in ("source_identity", "destination_identity", "parent_identity"):
            pair = value[field]
            if pair is None and field == "destination_identity":
                continue
            if not isinstance(pair, list) or len(pair) != 2 or any(type(v) is not int or v < 0 for v in pair) or not pair[1]:
                raise ValueError("folder identity")
            value[field] = tuple(pair)
        plan = BackupPlan(**value)
        if any(not isinstance(getattr(plan, field), str) for field in (
                "id", "name", "source", "destination", "project_id", "repository_identity",
                "created_at", "updated_at", "last_status", "last_run_at", "last_detail",
                "last_snapshot_id", "last_success_at", "last_success_snapshot")):
            raise ValueError("text fields")
        if not library._HEX32.fullmatch(plan.id) or not library._HEX32.fullmatch(plan.project_id):
            raise ValueError("id")
        library._text(plan.name, "Plan name", 200)
        for path in (plan.source, plan.destination):
            if not isinstance(path, str) or not Path(path).is_absolute() or len(path) > 4096:
                raise ValueError("path")
            library._absolute(path)
        if plan.repository_identity and not (
                plan.repository_identity.startswith("repository:") and library._HEX32.fullmatch(plan.repository_identity[11:])):
            raise ValueError("repository identity")
        if plan.last_status not in STATUSES:
            raise ValueError("status")
        for stamp in (plan.created_at, plan.updated_at, plan.last_run_at, plan.last_success_at):
            if stamp:
                library._stored_time(stamp)
        if not plan.created_at or not plan.updated_at:
            raise ValueError("timestamp")
        for snapshot in (plan.last_snapshot_id, plan.last_success_snapshot):
            if snapshot and not library._HEX32.fullmatch(snapshot):
                raise ValueError("snapshot")
        if bool(plan.last_success_at) != bool(plan.last_success_snapshot):
            raise ValueError("success")
        if plan.last_status in {"Succeeded", "Saved; Library needs attention"} and not plan.last_snapshot_id:
            raise ValueError("successful result")
        library._text(plan.last_detail, "Plan result", 5000, empty=True)
        return plan
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise library.LibraryError("Saved backup plan metadata is damaged or unsupported; no backup was started") from exc


def _encode(plan):
    raw = json.dumps({"schema": "rat-trap-backup-plan/v1", **dataclasses.asdict(plan)}, ensure_ascii=False, sort_keys=True)
    if len(raw.encode("utf-8")) > MAX_RECORD:
        raise library.LibraryError("Backup plan exceeds the metadata limit")
    _decode(raw)
    return raw


def _put(connection, plan):
    connection.execute("INSERT INTO library_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (PREFIX + plan.id, _encode(plan)))


def list_plans(store):
    """Catalogue only: no source/repository inspection, even on app startup."""
    with store._connection() as connection:
        if connection is None:
            return []
        rows = connection.execute("SELECT key,value FROM library_meta WHERE key GLOB 'backup_plan:*' ORDER BY key LIMIT ?",
                                  (MAX_PLANS + 1,)).fetchall()
        if len(rows) > MAX_PLANS:
            raise library.LibraryError("Too many saved backup plans for this preview")
        plans = []
        for row in rows:
            if not isinstance(row["value"], str) or len(row["value"].encode("utf-8")) > MAX_RECORD:
                raise library.LibraryError("Backup plan exceeds the metadata limit")
            plan = _decode(row["value"])
            if row["key"] != PREFIX + plan.id:
                raise library.LibraryError("Backup plan identity is inconsistent")
            plans.append(plan)
        return sorted(plans, key=lambda p: (p.name.casefold(), p.id))


def get_plan(store, plan_id):
    for plan in list_plans(store):
        if plan.id == plan_id:
            return plan
    raise library.LibraryError("Backup plan not found")


@contextmanager
def _operation_lock(store):
    """OS-released lock serializes plan runs and edits across app instances."""
    store._initialize()
    path = Path(str(store.catalog_path) + ".plans.lock")
    library._guard_path(path, missing_ok=True, catalog=True)
    with path.open("a+b") as handle:
        library._guard_path(path, catalog=True)
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise library.LibraryError("Another saved-plan operation is running. Let it finish first") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save_plan(store, *, name, source, destination, project_id, previous=None):
    """Save explicit settings only. Does not initialize storage or create a version."""
    name = library._text(name, "Plan name", 200)
    if not str(source).strip() or not str(destination).strip():
        raise library.LibraryError("Choose both source and backup destination")
    with _operation_lock(store):
        plans = list_plans(store)
        if previous is not None:
            current = get_plan(store, previous.id)
            if current != previous:
                raise library.LibraryError("Plan changed; reload it before editing")
            if current.last_status == "Running / review required":
                raise library.LibraryError("Review the interrupted run before editing this plan")
        elif len(plans) >= MAX_PLANS:
            raise library.LibraryError("This preview supports at most 1,000 saved plans")
        request = library_storage.validate_request(store, library_storage.StoreRequest(
            Path(source), Path(destination), project_id, mode="backup"))
        source_id = _directory_id(request.source)
        parent_id = _directory_id(request.destination.parent)
        destination_id = _directory_id(request.destination) if request.destination.exists() else None
        identity = library.inspect_storage(request.destination).identity if (
            request.destination.exists() and any(request.destination.iterdir())) else ""
        for other in plans:
            if previous and other.id == previous.id:
                continue
            if Path(other.source) == request.source and Path(other.destination) == request.destination:
                raise library.LibraryError("A plan already uses this source and destination; edit that plan instead")
        now = library._now()
        plan = BackupPlan(previous.id if previous else uuid.uuid4().hex, name, str(request.source),
                          str(request.destination), project_id, source_id, identity, destination_id,
                          parent_id, previous.created_at if previous else now, now)
        if previous and all(getattr(plan, key) == getattr(previous, key) for key in (
                "source", "destination", "project_id", "source_identity", "repository_identity", "destination_identity", "parent_identity")):
            plan = replace(previous, name=name, updated_at=now)
        with store._connection(write=True) as connection:
            store._project_exists(connection, project_id)
            _put(connection, plan)
        return plan


def delete_plan(store, previous):
    """Forget settings only. Never delete source files, versions or receipts."""
    with _operation_lock(store):
        if get_plan(store, previous.id) != previous:
            raise library.LibraryError("Plan changed; reload it before removing it")
        if previous.last_status == "Running / review required":
            raise library.LibraryError("Review the interrupted run before removing this plan")
        with store._connection(write=True) as connection:
            connection.execute("DELETE FROM library_meta WHERE key=?", (PREFIX + previous.id,))


def acknowledge_interrupted(store, previous):
    """Explicit review acknowledgement, not repository recovery or a success claim."""
    with _operation_lock(store):
        if get_plan(store, previous.id) != previous or previous.last_status != "Running / review required":
            raise library.LibraryError("This plan no longer has the interrupted result shown")
        plan = replace(previous, last_status="Needs attention", updated_at=library._now(),
                       last_detail="Interrupted run acknowledged. Inspect Backups & history before retrying. No storage was recovered, repaired or deleted.")
        with store._connection(write=True) as connection:
            _put(connection, plan)
        return plan


def _preflight(store, plan, *, allow_new=False):
    request = library_storage.validate_request(store, library_storage.StoreRequest(
        Path(plan.source), Path(plan.destination), plan.project_id, mode="backup", snapshot_label=plan.name))
    if _directory_id(request.source) != plan.source_identity:
        raise library.LibraryError("The source folder was replaced. Edit and explicitly save the plan to accept a new source")
    if _directory_id(request.destination.parent) != plan.parent_identity:
        raise library.LibraryError("The destination parent/drive changed. Review and edit the plan; no replacement was accepted")
    if plan.repository_identity:
        if _directory_id(request.destination) != plan.destination_identity:
            raise library.LibraryError("The backup folder was replaced or moved. Review and edit the plan")
        if library.inspect_storage(request.destination).identity != plan.repository_identity:
            raise library.IdentityMismatchError("The saved backup repository identity changed; no replacement was accepted")
        staging = request.destination / "staging"
        jobs = staging / "jobs"
        library._guard_path(jobs)
        if any(jobs.iterdir()) or any(p.name != "jobs" for p in staging.iterdir()):
            raise library.LibraryError("Pending backup/recovery work exists. Review Backups & history; this plan will not resume it automatically")
    else:
        if not allow_new:
            raise library.LibraryError("The plan has no pinned repository identity")
        if plan.destination_identity is None:
            if os.path.lexists(request.destination):
                raise library.LibraryError("Something appeared at the planned new destination. Review and edit the plan")
        elif _directory_id(request.destination) != plan.destination_identity or any(request.destination.iterdir()):
            raise library.LibraryError("The planned empty destination changed. Review and edit the plan")
    return request


def run_plan(store, previous, *, progress=None):
    """One explicit run; refuses pending recovery rather than returning an older job."""
    with _operation_lock(store):
        if get_plan(store, previous.id) != previous:
            raise library.LibraryError("Plan changed since it was selected; reload and confirm it again")
        if previous.last_status == "Running / review required":
            raise library.LibraryError("Previous run needs review. Inspect the repository before acknowledging the interruption")
        plan = replace(previous, last_status="Running / review required", last_run_at=library._now(),
                       last_detail="Run started; completion has not been confirmed.", last_snapshot_id="", updated_at=library._now())
        with store._connection(write=True) as connection:
            _put(connection, plan)
        saved = None
        record_error = ""

        def report(text):
            if progress:
                try:
                    progress(text)
                except Exception:
                    pass  # A detached progress listener must not hide a published backup.

        try:
            report("Checking saved source and destination…")
            request = _preflight(store, plan, allow_new=True)
            # Validate the full source before any repository initialization.
            engine._enumerate_source(request.source)
            if not plan.repository_identity:
                _preflight(store, plan, allow_new=True)
                info = engine.init_repository(request.destination, require_new=True)
                plan = replace(plan, repository_identity="repository:" + info.repository_id,
                               destination_identity=_directory_id(request.destination), updated_at=library._now())
                # Pin before writing any snapshot. If this fails, leave the new
                # empty repository in place and report the failure; no snapshot
                # has been written. An unrecorded identity needs explicit review.
                with store._connection(write=True) as connection:
                    _put(connection, plan)

            def guarded():
                if get_plan(store, plan.id) != plan:
                    raise library.LibraryError("Plan changed during the run")
                _preflight(store, plan)

            snapshot = engine.create_snapshot(request.destination, request.source, label=plan.name,
                preflight=guarded, progress=lambda event: report("Publishing backup…" if event.get("phase") == "publish"
                    else f"Backing up {event.get('completed_files', 0):,}/{event.get('total_files', 0):,} files…"))
            # From here onward storage publication succeeded. Never describe
            # a later receipt/catalogue failure as a failed backup.
            try:
                item = store.record_saved(request.destination, project_id=plan.project_id,
                                           identity=plan.repository_identity, snapshot_id=snapshot.snapshot_id)
                catalogue_error = None
            except Exception as exc:
                item, catalogue_error = None, f"{type(exc).__name__}: {exc}"[:1500]
            saved = library_storage.StoreResult(request.destination, item, snapshot.file_count, snapshot.total_bytes,
                                               False, snapshot.snapshot_id, catalogue_error, snapshot.resumed)
            plan = replace(plan, last_status="Saved; Library needs attention" if catalogue_error else "Succeeded",
                last_detail=(f"Backup saved: {snapshot.file_count:,} files; {snapshot.total_bytes:,} logical bytes. "
                             "Not encrypted. Integrity health check is separate."
                             + (" Library listing needs attention; do not back up again just to fix it. " + catalogue_error if catalogue_error else "")),
                last_snapshot_id=snapshot.snapshot_id, last_success_at=library._now(), last_success_snapshot=snapshot.snapshot_id)
        except Exception as exc:
            plan = replace(plan, last_status="Needs attention", last_detail=(
                f"{type(exc).__name__}: {exc}\nNo completed backup result was confirmed. "
                "Inspect Backups & history before retrying; originals and earlier versions were not deleted.")[:4500])
        plan = replace(plan, updated_at=library._now())
        try:
            with store._connection(write=True) as connection:
                _put(connection, plan)
                project = connection.execute("SELECT 1 FROM projects WHERE id=?", (plan.project_id,)).fetchone()
                if project:
                    detail = (f"Plan: {plan.name}\nSource: {plan.source}\nDestination: {plan.destination}\n"
                              f"Result: {plan.last_status}\nSnapshot: {plan.last_snapshot_id or 'Not confirmed'}\n{plan.last_detail}")
                    connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (
                        uuid.uuid4().hex, None, plan.project_id, "note", plan.updated_at, "Library note time",
                        "Backup plan run", library._text(detail[:7900], "Backup plan receipt", 8000), None, None))
                else:
                    record_error = "Project was removed; plan result saved but no project timeline receipt could be added."
        except Exception as exc:
            record_error = f"Result/receipt could not be saved: {type(exc).__name__}: {exc}"[:1500]
        return RunResult(plan, saved, record_error)


def describe(plan):
    return (f"Source: {plan.source}\nDestination: {plan.destination}\n"
            f"Last attempt: {plan.last_run_at or 'Never'} — {plan.last_status}\n"
            f"Last successful backup: {plan.last_success_at or 'Never'}\n"
            f"Last successful snapshot: {plan.last_success_snapshot or 'None'}\n"
            f"{plan.last_detail}\nManual only. Not encrypted. Health verification is separate.")
