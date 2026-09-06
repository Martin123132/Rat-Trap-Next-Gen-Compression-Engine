"""Pure tutorial definitions and disposable sample-Vault safety checks."""

import dataclasses
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, tutorials


def file_snapshot(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class TutorialDefinitionTests(unittest.TestCase):
    def test_catalog_is_immutable_unique_and_only_promises_available_journeys(self):
        self.assertIsInstance(tutorials.TUTORIALS, tuple)
        self.assertTrue(tutorials.TUTORIALS)
        self.assertEqual(tutorials.TUTORIALS[0].id, "vault-search")
        self.assertEqual(len({item.id for item in tutorials.TUTORIALS}), len(tutorials.TUTORIALS))
        self.assertEqual([item.id for item in tutorials.TUTORIALS if item.available], ["vault-search", "compress", "restore", "protect", "history"])
        for item in tutorials.TUTORIALS:
            with self.subTest(tutorial=item.id):
                self.assertTrue(item.title.strip())
                self.assertTrue(item.description.strip())
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    item.title = "Changed"

    def test_each_step_explains_where_what_why_and_expected_result(self):
        steps = tutorials.VAULT_SEARCH_STEPS
        self.assertIsInstance(steps, tuple)
        self.assertEqual([step.id for step in steps], [
            "navigate", "load", "query", "search", "select", "preview", "finish"
        ])
        for step in steps:
            with self.subTest(step=step.id):
                for field in ("title", "where", "action", "why", "expect"):
                    self.assertTrue(getattr(step, field).strip(), field)
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    step.action = "Changed"


class TutorialDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-demo-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.parent_sentinel = self.base / "not-owned-by-tutorial.txt"
        self.parent_sentinel.write_text("Generated stand-in for unrelated data", encoding="utf-8")

    def make_demo(self):
        demo = tutorials.create_demo(self.base)
        self.addCleanup(demo.cleanup)
        return demo

    def test_demo_is_contained_in_fresh_owned_child_with_deterministic_source(self):
        before = self.parent_sentinel.read_bytes()
        first, second = self.make_demo(), self.make_demo()
        self.assertNotEqual(first.root, second.root)
        for demo in (first, second):
            self.assertEqual(demo.root.parent.resolve(), self.base.resolve())
            self.assertTrue(demo.source.is_relative_to(demo.root))
            self.assertTrue(demo.archive.is_relative_to(demo.root))
            self.assertTrue(demo.archive.is_file())
            self.assertTrue(gmw_tool.is_vault_archive(demo.archive))
            self.assertIn(tutorials.DEMO_PATH, file_snapshot(demo.source))
        self.assertEqual(file_snapshot(first.source), file_snapshot(second.source))
        self.assertEqual(self.parent_sentinel.read_bytes(), before)

    def test_sample_vault_search_preview_and_verify_do_not_modify_sources(self):
        demo = self.make_demo()
        self.assertTrue(demo.is_intact())
        before = file_snapshot(demo.root)
        results = gmw_tool.search_vault(demo.archive, tutorials.DEMO_QUERY)
        self.assertIn(tutorials.DEMO_PATH, [result.path for result in results])
        preview = gmw_tool.preview_vault_file(demo.archive, tutorials.DEMO_PATH)
        self.assertIn(tutorials.DEMO_MARKER, preview)
        self.assertEqual(preview, (demo.source / tutorials.DEMO_PATH).read_text(encoding="utf-8"))
        self.assertGreater(gmw_tool.verify_vault(demo.archive).file_count, 0)
        self.assertEqual(file_snapshot(demo.root), before)
        self.assertTrue(demo.is_intact())

    def test_cleanup_removes_only_unchanged_owned_demo_and_is_idempotent(self):
        demo = self.make_demo()
        before = self.parent_sentinel.read_bytes()
        demo.cleanup()
        self.assertFalse(demo.root.exists())
        demo.cleanup()
        self.assertEqual(self.parent_sentinel.read_bytes(), before)
        self.assertEqual(list(self.base.iterdir()), [self.parent_sentinel])

    def test_cleanup_preserves_modified_sample_file(self):
        demo = self.make_demo()
        changed = demo.source / tutorials.DEMO_PATH
        changed.write_text("Generated simulated user edit", encoding="utf-8")
        demo.cleanup()
        self.assertEqual(changed.read_text(encoding="utf-8"), "Generated simulated user edit")
        self.assertTrue(self.parent_sentinel.is_file())

    def test_cleanup_preserves_unexpected_nested_file(self):
        demo = self.make_demo()
        extra = demo.root / "unrelated" / "retained.gmw"
        extra.parent.mkdir()
        extra.write_bytes(b"Generated unrelated archive fixture")
        demo.cleanup()
        self.assertEqual(extra.read_bytes(), b"Generated unrelated archive fixture")
        self.assertTrue(self.parent_sentinel.is_file())

    def test_parent_file_is_rejected_without_overwriting_it(self):
        before = self.parent_sentinel.read_bytes()
        with self.assertRaises(OSError):
            tutorials.create_demo(self.parent_sentinel)
        self.assertEqual(self.parent_sentinel.read_bytes(), before)

    def test_creation_failure_removes_only_the_generated_fixture(self):
        before = file_snapshot(self.base)
        with mock.patch.object(tutorials.vault_engine, "create_vault", side_effect=RuntimeError("Generated build failure")):
            with self.assertRaisesRegex(RuntimeError, "Generated build failure"):
                tutorials.create_demo(self.base)
        self.assertEqual(file_snapshot(self.base), before)
        self.assertEqual(list(self.base.iterdir()), [self.parent_sentinel])

    def test_cleanup_preserves_changed_archive_instead_of_deleting_by_filename(self):
        demo = self.make_demo()
        replacement = b"Generated replacement archive with changed contents"
        demo.archive.write_bytes(replacement)
        demo.cleanup()
        self.assertEqual(demo.archive.read_bytes(), replacement)
        self.assertTrue(self.parent_sentinel.is_file())

    @unittest.skipUnless(os.name == "nt", "Windows directory-junction cleanup boundary")
    def test_cleanup_never_removes_directories_through_replaced_source_junction(self):
        import _winapi

        demo = self.make_demo()
        outside = self.base / "generated-outside-demo"
        for name in ("projects", "documents"):
            (outside / name).mkdir(parents=True)
        original = demo.root / "original-generated-source"
        demo.source.rename(original)
        _winapi.CreateJunction(str(outside), str(demo.source))
        try:
            self.assertTrue(demo.source.is_junction())
            demo.cleanup()
            for name in ("projects", "documents"):
                self.assertTrue((outside / name).is_dir(), "Cleanup traversed a substituted ancestor")
            self.assertTrue((original / tutorials.DEMO_PATH).is_file())
        finally:
            # Remove this generated junction itself, never its target tree.
            if demo.source.is_junction():
                demo.source.rmdir()

    def test_sample_integrity_rejects_same_bytes_in_replaced_file(self):
        demo = self.make_demo()
        replacement = demo.root / "generated-identical-replacement.gmw"
        replacement.write_bytes(demo.archive.read_bytes())
        replacement.replace(demo.archive)
        self.assertFalse(demo.is_intact())

    def test_sample_integrity_rejects_an_additional_hard_link(self):
        demo = self.make_demo()
        link = self.base / "generated-hardlink.gmw"
        try:
            os.link(demo.archive, link)
        except OSError as exc:
            self.skipTest(f"Hard links unavailable in the temporary filesystem: {exc}")
        self.assertFalse(demo.is_intact())
        link.unlink()
        self.assertTrue(demo.is_intact())


if __name__ == "__main__":
    unittest.main()
