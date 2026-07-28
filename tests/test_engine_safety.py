import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rat_trap import gmw_tool, gmw_tool_v4


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
            self.assertTrue(gmw_tool.is_chunked_archive(archive))
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

    def test_unknown_sqlite_family_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "safe.txt").write_text("must not be dispatched", encoding="utf-8")
            archive = root / "unknown.gmw"
            gmw_tool.compress_folder(source, archive, compressor="zlib")
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute(
                    "UPDATE metadata SET value = ? WHERE key = 'format'",
                    (json.dumps("NOT-RAT-TRAP-9"),),
                )
                connection.commit()

            self.assertFalse(gmw_tool.is_chunked_archive(archive))
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.read_metadata(archive)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.extract_archive(archive, root / "restored")
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.export_zip(archive, root / "export.zip")
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.serve_archive(archive, "127.0.0.1", 0)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool_v4.extract_archive(archive, root / "v4-restored")
            self.assertFalse((root / "restored").exists())
            self.assertFalse((root / "export.zip").exists())
            self.assertFalse((root / "v4-restored").exists())

    def test_unrelated_or_incomplete_sqlite_database_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unrelated = root / "unrelated.gmw"
            with closing(sqlite3.connect(unrelated)) as connection:
                connection.execute("CREATE TABLE notes(message TEXT)")
                connection.execute("INSERT INTO notes VALUES ('not an archive')")
                connection.commit()

            incomplete = root / "incomplete.gmw"
            with closing(sqlite3.connect(incomplete)) as connection:
                connection.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
                connection.execute("CREATE TABLE chunks(id TEXT)")
                connection.execute("CREATE TABLE files(path TEXT)")
                connection.execute(
                    "INSERT INTO metadata VALUES ('format', ?)",
                    (json.dumps("GMW-SQLITE-1"),),
                )
                connection.commit()

            for candidate in (unrelated, incomplete):
                self.assertFalse(gmw_tool.is_chunked_archive(candidate))
                with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                    gmw_tool.read_metadata(candidate)

    def test_ambiguous_sqlite_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "safe.txt").write_text("one family only", encoding="utf-8")
            archive = root / "ambiguous.gmw"
            gmw_tool.compress_folder(source, archive, compressor="zlib")
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute(
                    "CREATE TABLE vault_metadata(key TEXT PRIMARY KEY, value TEXT)"
                )
                connection.executemany(
                    "INSERT INTO vault_metadata(key, value) VALUES (?, ?)",
                    (("format", "GMW-VAULT-1"), ("schema_version", "999")),
                )
                connection.commit()

            self.assertFalse(gmw_tool.is_chunked_archive(archive))
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.read_metadata(archive)

    def test_missing_archive_reports_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.gmw"
            with self.assertRaisesRegex(ValueError, "not found"):
                gmw_tool.read_metadata(missing)

    def test_deprecated_v4_facade_uses_the_hardened_legacy_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "hello.txt").write_text("legacy API", encoding="utf-8")
            archive = root / "legacy.gmw"

            created = gmw_tool_v4.compress_folder(
                source,
                archive,
                compressor="zlib",
                zstd_level=3,
            )
            self.assertEqual(created.format, "GMW-SQLITE-1")
            self.assertEqual(
                set(created.as_dict()),
                {
                    "format",
                    "chunk_size",
                    "compressor",
                    "checksum",
                    "checksum_algorithm",
                    "created_at",
                    "elapsed_seconds",
                    "file_count",
                    "total_bytes",
                },
            )
            with closing(sqlite3.connect(archive)) as connection:
                stored_keys = {
                    str(row[0])
                    for row in connection.execute("SELECT key FROM metadata")
                }
            self.assertEqual(stored_keys, set(created.as_dict()))
            self.assertTrue(gmw_tool.is_chunked_archive(archive))

            restored = root / "restored"
            gmw_tool_v4.extract_archive(archive, restored)
            self.assertEqual(
                (restored / "hello.txt").read_text(encoding="utf-8"),
                "legacy API",
            )
            parsed = gmw_tool_v4.build_parser().parse_args(
                ["info", str(archive)]
            )
            self.assertEqual(parsed.command, "info")


if __name__ == "__main__":
    unittest.main()
