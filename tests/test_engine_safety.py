import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rat_trap import gmw_tool


class EngineSafetyTests(unittest.TestCase):
    def test_default_profile_uses_solid_engine_and_preserves_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "empty").mkdir()
            (source / "data.txt").write_text("solid archive\n" * 1000, encoding="utf-8")
            archive = root / "archive.gmw"
            destination = root / "restored"

            created = gmw_tool.compress_folder(source, archive, profile="balanced")
            restored = gmw_tool.extract_archive(archive, destination)

            self.assertEqual(created.format, "GMW-SOLID-2")
            self.assertEqual(restored.profile, "balanced")
            self.assertTrue((destination / "empty").is_dir())
            self.assertEqual(
                (destination / "data.txt").read_bytes(),
                (source / "data.txt").read_bytes(),
            )

    def test_solid_archive_detects_payload_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "data.bin").write_bytes(bytes(range(256)) * 8192)
            archive = root / "archive.gmw"
            gmw_tool.compress_folder(source, archive, profile="balanced")

            with open(archive, "r+b") as fp:
                fp.seek(24)
                value = fp.read(1)
                fp.seek(24)
                fp.write(bytes([value[0] ^ 0x01]))

            with self.assertRaises(Exception):
                gmw_tool.extract_archive(archive, root / "restored")

    def test_balanced_profile_stores_exact_duplicate_files_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            repeated = bytes(range(256)) * 4096
            (source / "first.bin").write_bytes(repeated)
            (source / "second.bin").write_bytes(repeated)
            (source / "different.bin").write_bytes(repeated[:-1] + b"x")

            archive = root / "archive.gmw"
            destination = root / "restored"
            created = gmw_tool.compress_folder(source, archive, profile="balanced")
            gmw_tool.extract_archive(archive, destination)

            self.assertTrue(created.whole_file_dedup)
            self.assertEqual(created.duplicate_file_count, 1)
            for name in ("first.bin", "second.bin", "different.bin"):
                self.assertEqual((destination / name).read_bytes(), (source / name).read_bytes())

    def test_compress_and_extract_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "hello.txt").write_text("hello Rat-Trap", encoding="utf-8")
            nested = source / "nested"
            nested.mkdir()
            (nested / "data.bin").write_bytes(bytes(range(256)) * 4096)

            archive = root / "archive.gmw"
            destination = root / "restored"
            gmw_tool.compress_folder(source, archive, compressor="zlib")
            gmw_tool.extract_archive(archive, destination)

            self.assertEqual((destination / "hello.txt").read_text(encoding="utf-8"), "hello Rat-Trap")
            self.assertEqual((destination / "nested" / "data.bin").read_bytes(), bytes(range(256)) * 4096)

    def test_archive_cannot_be_created_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "input.txt").write_text("content", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside the source folder"):
                gmw_tool.compress_folder(source, source / "bad.gmw", compressor="zlib")

    def test_extract_rejects_parent_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "safe.txt").write_text("do not escape", encoding="utf-8")
            archive = root / "archive.gmw"
            destination = root / "restored"
            escaped = root / "escaped.txt"
            gmw_tool.compress_folder(source, archive, compressor="zlib")

            with closing(sqlite3.connect(archive)) as conn:
                conn.execute("UPDATE files SET path = '../escaped.txt'")
                conn.commit()

            with self.assertRaisesRegex(ValueError, "unsafe file path"):
                gmw_tool.extract_archive(archive, destination)
            self.assertFalse(escaped.exists())


if __name__ == "__main__":
    unittest.main()
