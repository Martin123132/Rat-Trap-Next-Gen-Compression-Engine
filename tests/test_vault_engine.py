import hashlib
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from rat_trap import gmw_tool, vault_engine


def tree_digest(folder: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    file_count = 0
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(data)
        total_bytes += len(data)
        file_count += 1
    return digest.hexdigest(), total_bytes, file_count


class VaultEngineTests(unittest.TestCase):
    def _build_source(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        documents = source / "documents"
        documents.mkdir()
        (source / "empty-directory").mkdir()
        repeated = ("Rat-Trap searchable curvature record\n" * 400).encode("utf-8")
        (documents / "notes.txt").write_bytes(repeated)
        (documents / "notes-copy.txt").write_bytes(repeated)
        (documents / "records.json").write_text(
            '{"project":"rat-trap","status":"queryable"}\n', encoding="utf-8"
        )
        (source / "binary.bin").write_bytes(bytes(range(256)) * 64)
        (source / "records.data").write_text(
            "Private census record without a standard text extension\n", encoding="utf-8"
        )
        (source / "empty.txt").write_bytes(b"")
        return source

    def test_create_search_preview_extract_verify_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._build_source(root)
            archive = root / "sample.vault.gmw"

            metadata = vault_engine.create_vault(source, archive, chunk_size=4096)

            self.assertEqual(metadata.format, vault_engine.FORMAT)
            self.assertEqual(metadata.file_count, 6)
            self.assertEqual(metadata.duplicate_file_count, 1)
            self.assertGreater(metadata.deduplicated_bytes, 0)
            self.assertEqual(vault_engine.verify_vault(archive).file_count, 6)

            results = vault_engine.search_vault(archive, "searchable curvature")
            self.assertEqual(
                {item.path for item in results},
                {"documents/notes.txt", "documents/notes-copy.txt"},
            )
            text_results = vault_engine.search_vault(archive, extension="txt")
            self.assertEqual(len(text_results), 3)
            binary_name_results = vault_engine.search_vault(archive, "binary.bin")
            self.assertEqual([item.path for item in binary_name_results], ["binary.bin"])
            detected_text_results = vault_engine.search_vault(archive, "Private census")
            self.assertEqual([item.path for item in detected_text_results], ["records.data"])
            preview = vault_engine.preview_text(archive, "documents/notes.txt", limit=128)
            self.assertIn("Rat-Trap searchable", preview)
            self.assertIn("Preview truncated", preview)
            self.assertEqual(
                vault_engine.preview_text(archive, "binary.bin"),
                "[Binary preview unavailable]",
            )

            selected = root / "selected"
            vault_engine.extract_vault(
                archive, selected, paths=["documents/records.json"]
            )
            self.assertTrue((selected / "documents" / "records.json").is_file())
            self.assertFalse((selected / "documents" / "notes.txt").exists())

            restored = root / "restored"
            vault_engine.extract_vault(archive, restored)
            self.assertEqual(tree_digest(restored), tree_digest(source))
            self.assertTrue((restored / "empty-directory").is_dir())

            exported = root / "sample.zip"
            vault_engine.export_zip(archive, exported)
            with zipfile.ZipFile(exported) as output:
                self.assertIsNone(output.testzip())
                self.assertEqual(
                    output.read("documents/notes-copy.txt"),
                    (source / "documents" / "notes-copy.txt").read_bytes(),
                )

    def test_shared_api_dispatches_vault_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._build_source(root)
            archive = root / "dispatch.vault.gmw"
            restored = root / "restored"

            created = gmw_tool.compress_folder(source, archive, profile="vault")
            inspected = gmw_tool.read_metadata(archive)
            results = gmw_tool.search_vault(archive, "queryable")
            gmw_tool.extract_archive(archive, restored)

            self.assertEqual(created.format, vault_engine.FORMAT)
            self.assertEqual(inspected.profile, "vault")
            self.assertEqual([result.path for result in results], ["documents/records.json"])
            self.assertEqual(tree_digest(restored), tree_digest(source))

    def test_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._build_source(root)
            archive = root / "sample.vault.gmw"
            vault_engine.create_vault(source, archive)
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute("UPDATE files SET path = '../escaped.txt' WHERE id = 1")
                connection.commit()

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                vault_engine.extract_vault(archive, root / "restored")
            self.assertFalse((root / "escaped.txt").exists())

    def test_verify_detects_corrupted_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._build_source(root)
            archive = root / "sample.vault.gmw"
            vault_engine.create_vault(source, archive)
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute(
                    "UPDATE objects SET data = ? WHERE id = (SELECT id FROM objects LIMIT 1)",
                    (sqlite3.Binary(b"not-zstandard-data"),),
                )
                connection.commit()

            with self.assertRaises(Exception):
                vault_engine.verify_vault(archive)

    def test_verify_rejects_oversized_chunk_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._build_source(root)
            archive = root / "sample.vault.gmw"
            vault_engine.create_vault(source, archive)
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute(
                    "UPDATE file_chunks SET raw_size = ? WHERE rowid = "
                    "(SELECT rowid FROM file_chunks LIMIT 1)",
                    (1024**4,),
                )
                connection.commit()

            with self.assertRaisesRegex(ValueError, "invalid size metadata"):
                vault_engine.verify_vault(archive)


if __name__ == "__main__":
    unittest.main()
