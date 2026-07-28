import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
import zlib
from contextlib import closing
from pathlib import Path

from rat_trap import gmw_tool, solid_engine, vault_engine


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "formats"
MANIFEST = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))


def file_manifest(folder: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(folder).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in folder.rglob("*") if item.is_file())
    }


class FormatCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected_files = {
            item["path"]: (item["bytes"], item["sha256"])
            for item in MANIFEST["source_tree"]["files"]
        }

    def test_golden_archives_match_manifest_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for fixture in MANIFEST["fixtures"]:
                with self.subTest(fixture=fixture["name"]):
                    archive = FIXTURE_ROOT / fixture["name"]
                    self.assertTrue(archive.is_file())
                    self.assertEqual(archive.stat().st_size, fixture["bytes"])
                    self.assertEqual(
                        hashlib.sha256(archive.read_bytes()).hexdigest(),
                        fixture["sha256"],
                    )

                    metadata = gmw_tool.read_metadata(archive)
                    self.assertEqual(metadata.format, fixture["family"])
                    self.assertEqual(metadata.file_count, MANIFEST["source_tree"]["file_count"])
                    self.assertEqual(metadata.total_bytes, MANIFEST["source_tree"]["total_bytes"])
                    for key, value in fixture["expected"].items():
                        self.assertEqual(getattr(metadata, key), value)

                    if fixture["family"] == "GMW-SQLITE-1":
                        self.assertTrue(gmw_tool.is_chunked_archive(archive))
                    elif fixture["family"] == "GMW-SOLID-2":
                        self.assertTrue(solid_engine.is_solid_archive(archive))
                    else:
                        self.assertTrue(vault_engine.is_vault_archive(archive))
                        vault_engine.verify_vault(archive)

                    restored = root / f"{archive.stem}-restored"
                    gmw_tool.extract_archive(archive, restored)
                    self.assertEqual(file_manifest(restored), self.expected_files)

                    exported = root / f"{archive.stem}.zip"
                    gmw_tool.export_zip(archive, exported)
                    with zipfile.ZipFile(exported) as output:
                        self.assertIsNone(output.testzip())
                        self.assertEqual(
                            sorted(output.namelist()), sorted(self.expected_files)
                        )
                        for path, (_, expected_hash) in self.expected_files.items():
                            self.assertEqual(
                                hashlib.sha256(output.read(path)).hexdigest(),
                                expected_hash,
                            )

    def test_release_specific_schema_shapes_are_preserved(self) -> None:
        legacy = FIXTURE_ROOT / "gmw-sqlite-1-4.2.gmw"
        with closing(sqlite3.connect(legacy)) as connection:
            keys = {
                str(row[0])
                for row in connection.execute("SELECT key FROM metadata")
            }
        self.assertEqual(
            keys,
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

        solid_43 = FIXTURE_ROOT / "gmw-solid-2-4.3.gmw"
        with open(solid_43, "rb") as source:
            metadata_43, _ = solid_engine._read_layout(source)
        self.assertFalse(metadata_43.whole_file_dedup)
        self.assertEqual(metadata_43.duplicate_file_count, 0)

        schema_1 = FIXTURE_ROOT / "gmw-vault-1-schema-1.gmw"
        schema_2 = FIXTURE_ROOT / "gmw-vault-1-schema-2.gmw"
        with closing(sqlite3.connect(schema_1)) as connection:
            tables_1 = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        with closing(sqlite3.connect(schema_2)) as connection:
            tables_2 = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("structured_sources", tables_1)
        self.assertNotIn("structured_columns", tables_1)
        self.assertIn("structured_sources", tables_2)
        self.assertIn("structured_columns", tables_2)

        self.assertEqual(vault_engine.list_structured_sources(schema_1), [])
        sources = vault_engine.list_structured_sources(schema_2)
        self.assertEqual([(item.path, item.row_count) for item in sources], [("people.csv", 2)])
        result = vault_engine.query_structured_source(schema_2, sources[0].id)
        self.assertEqual(result.rows, ((1, "Alice", 31, 1), (2, "Bob", 27, 0)))

    def test_future_vault_schema_fails_closed_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            future = root / "future-schema.gmw"
            shutil.copyfile(
                FIXTURE_ROOT / "gmw-vault-1-schema-2.gmw",
                future,
            )
            with closing(sqlite3.connect(future)) as connection:
                connection.execute(
                    "UPDATE vault_metadata SET value = '999' "
                    "WHERE key = 'schema_version'"
                )
                connection.commit()

            self.assertFalse(vault_engine.is_vault_archive(future))
            with self.assertRaisesRegex(ValueError, "Unsupported Vault format"):
                vault_engine.read_metadata(future)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.read_metadata(future)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.extract_archive(future, root / "restored")
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.export_zip(future, root / "export.zip")
            self.assertFalse((root / "restored").exists())
            self.assertFalse((root / "export.zip").exists())

    def test_legacy_chunk_corruption_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corrupt = root / "corrupt.gmw"
            shutil.copyfile(
                FIXTURE_ROOT / "gmw-sqlite-1-4.2.gmw",
                corrupt,
            )
            with closing(sqlite3.connect(corrupt)) as connection:
                chunk_id, raw_size = connection.execute(
                    "SELECT id, raw_size FROM chunks ORDER BY rowid LIMIT 1"
                ).fetchone()
                connection.execute(
                    "UPDATE chunks SET data = ? WHERE id = ?",
                    (zlib.compress(b"Z" * int(raw_size)), chunk_id),
                )
                connection.commit()

            self.assertTrue(gmw_tool.is_chunked_archive(corrupt))
            with self.assertRaisesRegex(ValueError, "content digest"):
                gmw_tool.extract_archive(corrupt, root / "restored")
            with self.assertRaisesRegex(ValueError, "content digest"):
                gmw_tool.export_zip(corrupt, root / "export.zip")
            self.assertFalse((root / "export.zip").exists())

    def test_legacy_missing_file_row_is_detected_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corrupt = root / "missing-row.gmw"
            shutil.copyfile(
                FIXTURE_ROOT / "gmw-sqlite-1-4.2.gmw",
                corrupt,
            )
            with closing(sqlite3.connect(corrupt)) as connection:
                connection.execute("DELETE FROM files WHERE path = 'hello.txt'")
                connection.commit()

            self.assertTrue(gmw_tool.is_chunked_archive(corrupt))
            with self.assertRaisesRegex(ValueError, "file inventory"):
                gmw_tool.extract_archive(corrupt, root / "restored")
            with self.assertRaisesRegex(ValueError, "file inventory"):
                gmw_tool.export_zip(corrupt, root / "export.zip")
            self.assertFalse((root / "restored").exists())
            self.assertFalse((root / "export.zip").exists())

    def test_incomplete_vault_schema_is_rejected_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incomplete = root / "incomplete-vault.gmw"
            shutil.copyfile(
                FIXTURE_ROOT / "gmw-vault-1-schema-2.gmw",
                incomplete,
            )
            with closing(sqlite3.connect(incomplete)) as connection:
                connection.execute("DROP TABLE objects")
                connection.commit()

            self.assertFalse(vault_engine.is_vault_archive(incomplete))
            with self.assertRaisesRegex(ValueError, "missing required table"):
                vault_engine.read_metadata(incomplete)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.read_metadata(incomplete)
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.extract_archive(incomplete, root / "restored")
            with self.assertRaisesRegex(ValueError, "not a supported Rat-Trap archive"):
                gmw_tool.export_zip(incomplete, root / "export.zip")
            self.assertFalse((root / "restored").exists())
            self.assertFalse((root / "export.zip").exists())

    def test_invalid_vault_metadata_types_fail_closed(self) -> None:
        mutations = {
            "schema_version": "2",
            "file_count": "6",
            "compression_level": "6",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for key, invalid_value in mutations.items():
                with self.subTest(key=key):
                    invalid = root / f"invalid-{key}.gmw"
                    shutil.copyfile(
                        FIXTURE_ROOT / "gmw-vault-1-schema-2.gmw",
                        invalid,
                    )
                    with closing(sqlite3.connect(invalid)) as connection:
                        connection.execute(
                            "UPDATE vault_metadata SET value = ? WHERE key = ?",
                            (json.dumps(invalid_value), key),
                        )
                        connection.commit()

                    self.assertFalse(vault_engine.is_vault_archive(invalid))
                    with self.assertRaisesRegex(ValueError, "invalid format metadata"):
                        vault_engine.read_metadata(invalid)
                    with self.assertRaisesRegex(
                        ValueError, "not a supported Rat-Trap archive"
                    ):
                        gmw_tool.read_metadata(invalid)


if __name__ == "__main__":
    unittest.main()
