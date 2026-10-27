import hashlib
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, library, library_search as search, repository_engine

FIXTURES = Path(__file__).parent / "fixtures" / "formats"


class LibrarySearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = library.LibraryStore(self.base / "library.sqlite3")
        self.project = self.store.create_project("Straße project", "Design records")

    def fixture(self, name):
        path = self.base / name
        shutil.copyfile(FIXTURES / name, path)
        return self.store.register(path, project_id=self.project.id)

    def generated(self, profile="balanced"):
        source = self.base / (profile + "-source")
        source.mkdir()
        (source / "Proposal_100%.txt").write_text("Private file contents are not searchable here", encoding="utf-8")
        (source / "Straße.txt").write_text("second file", encoding="utf-8")
        path = self.base / (profile + ".gmw")
        gmw_tool.compress_folder(source, path, profile=profile)
        return self.store.register(path, project_id=self.project.id)

    def repository(self):
        source = self.base / "source"
        source.mkdir()
        (source / "old-only.txt").write_text("old revision", encoding="utf-8")
        repo = self.base / "repo"
        repository_engine.init_repository(repo)
        first = repository_engine.create_snapshot(repo, source, label="First")
        (source / "old-only.txt").unlink()
        (source / "new-only.txt").write_text("new revision", encoding="utf-8")
        second = repository_engine.create_snapshot(repo, source, label="Second")
        return self.store.register(repo, project_id=self.project.id), first, second

    def fingerprint(self):
        return {str(p.relative_to(self.base)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in self.base.rglob("*") if p.is_file()}

    def test_lazy_empty_search_does_not_create_catalogue(self):
        missing = library.LibraryStore(self.base / "never-created.sqlite3")
        self.assertEqual(search.search_library(missing, "anything").results, ())
        self.assertFalse(missing.catalog_path.exists())

    def test_project_unicode_casefold_and_description(self):
        self.assertEqual(search.search_library(self.store, "STRASSE").results[0].kind, "Project")
        self.assertEqual(search.search_library(self.store, "design records").results[0].project_id, self.project.id)

    def test_old_notes_are_filtered_before_limit_and_wildcards_literal(self):
        note = self.store.add_note("Old Straße 100%_ note", project_id=self.project.id, event_date="2000-01-01")
        with self.store._connection(write=True) as con:
            import uuid
            for i in range(510):
                con.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, None, self.project.id,
                    "note", "2026-10-21", "user-entered date", "Project note", f"Unrelated {i}", None, None))
        report = search.search_library(self.store, "100%_", filenames=False)
        self.assertEqual([r.detail for r in report.results], [note.detail])
        self.assertTrue(any(r.kind == "Note" for r in search.search_library(self.store, "STRASSE").results))

    def test_all_supported_archive_formats_are_read_only(self):
        names = ("gmw-solid-2-4.3.gmw", "gmw-solid-2-4.4-dedup.gmw", "gmw-sqlite-1-4.2.gmw",
                 "gmw-vault-1-schema-1.gmw", "gmw-vault-1-schema-2.gmw")
        for name in names:
            self.fixture(name)
        before = self.fingerprint()
        report = search.search_library(self.store, ".")
        self.assertEqual(report.warnings, ())
        self.assertEqual(report.searched_items, len(names))
        self.assertEqual({r.item_label for r in report.results if r.kind == "File"}, set(names))
        self.assertEqual(before, self.fingerprint())

    def test_literal_filenames_not_file_contents_solid_and_vault(self):
        for profile in ("balanced", "vault"):
            self.generated(profile)
        report = search.search_library(self.store, "100%_")
        # Our actual name contains _ before 100%, not after: no wildcard expansion.
        self.assertFalse(any(r.kind == "File" for r in report.results))
        report = search.search_library(self.store, "_100%")
        self.assertEqual(len([r for r in report.results if r.kind == "File"]), 2)
        self.assertFalse(search.search_library(self.store, "Private file contents").results)
        self.assertEqual(len([r for r in search.search_library(self.store, "STRASSE.TXT").results if r.kind == "File"]), 2)

    def test_locked_contents_never_inspected_even_when_label_matches(self):
        item = self.fixture("rat-trap-encrypted-1-5.3.gmw")
        sealed = self.fixture("rat-trap-sealed-file-1-5.4.rtsf")
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError("Must not inspect locked contents")):
            report = search.search_library(self.store, "rat-trap")
        self.assertEqual(report.protected_items, 2)
        self.assertEqual({r.item_id for r in report.results}, {item.id, sealed.id})
        self.assertTrue(all(r.kind == "Locked item" for r in report.results))

    def test_repository_exact_old_version_without_catalogue_recovery(self):
        item, first, second = self.repository()
        before = self.fingerprint()
        with mock.patch.object(repository_engine, "list_snapshots", side_effect=AssertionError("No recovery")):
            report = search.search_library(self.store, "old-only")
        self.assertEqual(report.warnings, ())
        hit, = report.results
        self.assertEqual((hit.snapshot_id, hit.manifest_sha256), (first.snapshot_id, first.manifest_sha256))
        self.assertNotEqual(hit.snapshot_id, second.snapshot_id)
        self.assertEqual(search.validate_result(self.store, hit)[0].id, item.id)
        self.assertEqual(before, self.fingerprint())

    def test_deleted_snapshot_never_substitutes_newest(self):
        item, first, _ = self.repository()
        hit, = search.search_library(self.store, "old-only").results
        (Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).unlink()
        with self.assertRaisesRegex(library.LibraryError, "exact backup version"):
            search.validate_result(self.store, hit)

    def test_changed_or_missing_archives_report_partial_coverage(self):
        item = self.generated()
        Path(item.path).write_bytes(b"not the registered archive")
        report = search.search_library(self.store, "proposal")
        self.assertFalse(report.results)
        self.assertEqual(len(report.warnings), 1)
        Path(item.path).unlink()
        self.assertEqual(len(search.search_library(self.store, "proposal").warnings), 1)

    def test_replaced_archive_cannot_open_stale_filename(self):
        item = self.generated()
        hit, = search.search_library(self.store, "proposal").results
        shutil.copyfile(FIXTURES / "gmw-solid-2-4.3.gmw", item.path)
        with self.assertRaises(library.LibraryError):
            search.validate_result(self.store, hit)

    def test_no_filename_reads_when_disabled(self):
        self.generated()
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError()):
            self.assertEqual(search.search_library(self.store, "proposal", filenames=False).searched_items, 0)

    def test_cancel_discards_unfinished_source_hits(self):
        self.generated()
        cancel = threading.Event()
        original = search._files
        def interrupted(*args):
            for entry in original(*args):
                yield entry
                cancel.set()
        with mock.patch.object(search, "_files", interrupted):
            report = search.search_library(self.store, ".txt", cancel=cancel)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.results, ())

    def test_limits_are_explicit_not_silent_no_matches(self):
        self.generated()
        report = search.search_library(self.store, ".txt", limit=1)
        self.assertEqual(len(report.results), 1)
        self.assertTrue(report.limited)
        with mock.patch.object(search, "MAX_EXPANDED_BYTES", 20):
            report = search.search_library(self.store, "proposal")
        self.assertEqual(report.results, ())
        self.assertTrue(report.warnings)
        with mock.patch.object(search, "MAX_ENTRIES", 1):
            self.assertTrue(search.search_library(self.store, "proposal").warnings)

    def test_corrupt_stream_discards_preceding_hits(self):
        self.generated()
        with mock.patch.object(search.solid_engine, "_finish_read", side_effect=ValueError("Corruption")):
            report = search.search_library(self.store, "proposal")
        self.assertEqual(report.results, ())
        self.assertIn("Corruption", report.warnings[0])

    def test_invalid_queries_and_limits(self):
        for query in ("", " ", "x" * 301, "\x00"):
            with self.subTest(query=query), self.assertRaises(library.LibraryError):
                search.search_library(self.store, query)
        for limit in (0, 1001, True):
            with self.assertRaises(library.LibraryError):
                search.search_library(self.store, "a", limit=limit)

    def test_sqlite_search_does_not_touch_content_index(self):
        item = self.generated("vault")
        with mock.patch("rat_trap.vault_engine.search_vault", side_effect=AssertionError("Full text search not allowed")):
            hit, = search.search_library(self.store, "proposal").results
        self.assertEqual(hit.item_id, item.id)

    def test_source_changes_during_scan_discard_that_sources_hits(self):
        item = self.generated()
        original = search._files
        def changing(*args):
            yield from original(*args)
            shutil.copyfile(FIXTURES / "gmw-solid-2-4.3.gmw", item.path)
        with mock.patch.object(search, "_files", changing):
            report = search.search_library(self.store, "proposal")
        self.assertFalse(report.results)
        self.assertTrue(report.warnings)

    def test_active_sqlite_sidecar_refused_without_source_writes(self):
        item = self.generated("vault")
        sidecar = Path(item.path + "-wal")
        sidecar.write_bytes(b"Generated active-writer sentinel")
        before = self.fingerprint()
        report = search.search_library(self.store, "proposal")
        self.assertFalse(report.results)
        self.assertTrue(report.warnings)
        self.assertEqual(before, self.fingerprint())

    def test_missing_source_does_not_hide_healthy_source_matches(self):
        missing = self.generated("balanced")
        healthy = self.generated("vault")
        Path(missing.path).unlink()
        report = search.search_library(self.store, "proposal")
        self.assertEqual([hit.item_id for hit in report.results], [healthy.id])
        self.assertEqual(report.searched_items, 1)
        self.assertEqual(len(report.warnings), 1)

    def test_pre_cancelled_search_does_not_read_sources(self):
        self.generated()
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError("Cancelled")):
            report = search.search_library(self.store, "proposal", cancel=cancel)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.results, ())

    def test_smallest_xz_profile_filename_search(self):
        item = self.generated("smallest")
        report = search.search_library(self.store, "proposal")
        self.assertEqual(report.warnings, ())
        self.assertEqual([hit.item_id for hit in report.results], [item.id])


if __name__ == "__main__":
    unittest.main()
