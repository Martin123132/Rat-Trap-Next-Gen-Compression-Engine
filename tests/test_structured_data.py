import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rat_trap import vault_engine


class StructuredVaultTests(unittest.TestCase):
    def _build_source(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "people.csv").write_text(
            "name,age,score,active\nAlice,31,9.5,true\nBob,27,8.0,false\nCarla,42,9.5,true\n",
            encoding="utf-8",
        )
        (source / "metrics.tsv").write_text(
            "key\tvalue\nlatency\t12.5\nrequests\t80\n", encoding="utf-8"
        )
        (source / "records.json").write_text(
            json.dumps(
                {
                    "records": [
                        {"id": 1, "city": "York", "tags": ["north", "historic"]},
                        {"id": 2, "city": "Bath", "tags": ["south"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (source / "events.jsonl").write_text(
            '{"event":"open","ok":true}\n{"event":"close","ok":false}\n',
            encoding="utf-8",
        )
        (source / "adult.data").write_text(
            "39, State-gov, 77516, Bachelors\n50, Self-emp, 83311, Doctorate\n",
            encoding="utf-8",
        )
        (source / "adult.test").write_text(
            "| test split\n25, Private, 226802, 11th\n38, Private, 89814, HS-grad\n",
            encoding="utf-8",
        )
        (source / "adult.names").write_text(
            "age: continuous.\nworkclass: Private, State-gov.\n"
            "fnlwgt: continuous.\neducation: Bachelors, Doctorate.\n",
            encoding="utf-8",
        )
        (source / "broken.json").write_text("{not json", encoding="utf-8")
        (source / "notes.txt").write_text("ordinary searchable text", encoding="utf-8")
        return source

    def test_ingest_query_sql_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "structured.vault.gmw"
            metadata = vault_engine.create_vault(self._build_source(root), archive, chunk_size=1024)

            self.assertEqual(metadata.schema_version, 2)
            self.assertEqual(metadata.structured_source_count, 6)
            self.assertEqual(metadata.structured_row_count, 13)
            sources = vault_engine.list_structured_sources(archive)
            self.assertEqual({item.path for item in sources}, {
                "adult.data", "adult.test", "events.jsonl", "metrics.tsv", "people.csv",
                "records.json"
            })

            people = next(item for item in sources if item.path == "people.csv")
            columns = vault_engine.list_structured_columns(archive, people.id)
            self.assertEqual(
                [(item.column_name, item.declared_type) for item in columns],
                [("name", "TEXT"), ("age", "INTEGER"), ("score", "REAL"), ("active", "INTEGER")],
            )
            filtered = vault_engine.query_structured_source(
                archive, people.id, search="9.5", column="score", sort_by="age", descending=True
            )
            self.assertEqual(filtered.columns, ("__row__", "name", "age", "score", "active"))
            self.assertEqual([row[1] for row in filtered.rows], ["Carla", "Alice"])

            adult = next(item for item in sources if item.path == "adult.data")
            self.assertEqual(
                [item.column_name for item in vault_engine.list_structured_columns(archive, adult.id)],
                ["age", "workclass", "fnlwgt", "education"],
            )
            adult_result = vault_engine.query_structured_source(
                archive, adult.id, search="Doctorate"
            )
            self.assertEqual(len(adult_result.rows), 1)
            self.assertEqual(adult_result.rows[0][-1], "Doctorate")

            sql_result = vault_engine.execute_structured_sql(
                archive,
                f'SELECT name, age FROM "{people.table_name}" WHERE age >= 30 ORDER BY age',
            )
            self.assertEqual(sql_result.rows, (("Alice", 31), ("Carla", 42)))

            csv_output = root / "result.csv"
            json_output = root / "result.json"
            vault_engine.export_structured_result(sql_result, csv_output)
            vault_engine.export_structured_result(sql_result, json_output)
            with open(csv_output, encoding="utf-8-sig", newline="") as source:
                self.assertEqual(list(csv.reader(source))[1], ["Alice", "31"])
            self.assertEqual(json.loads(json_output.read_text(encoding="utf-8"))[1]["name"], "Carla")

    def test_read_only_sql_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "structured.vault.gmw"
            vault_engine.create_vault(self._build_source(root), archive)

            with self.assertRaisesRegex(ValueError, "read-only"):
                vault_engine.execute_structured_sql(archive, "DELETE FROM files")
            with self.assertRaisesRegex(ValueError, "read-only"):
                vault_engine.execute_structured_sql(archive, "PRAGMA table_info(files)")
            with self.assertRaises((ValueError, sqlite3.ProgrammingError)):
                vault_engine.execute_structured_sql(archive, "SELECT 1; SELECT 2")
            with self.assertRaises(sqlite3.DatabaseError):
                vault_engine.execute_structured_sql(
                    archive, "WITH chosen AS (SELECT 1) DELETE FROM files RETURNING id"
                )
            sources = vault_engine.list_structured_sources(archive)
            people = next(item for item in sources if item.path == "people.csv")
            limited = vault_engine.query_structured_source(archive, people.id, limit=2)
            self.assertEqual(len(limited.rows), 2)
            self.assertTrue(limited.truncated)

    def test_verify_detects_structured_catalog_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "structured.vault.gmw"
            vault_engine.create_vault(self._build_source(root), archive)
            with closing(sqlite3.connect(archive)) as connection:
                connection.execute(
                    "UPDATE structured_sources SET row_count = row_count + 1 WHERE id = 1"
                )
                connection.commit()
            with self.assertRaisesRegex(ValueError, "row count|totals"):
                vault_engine.verify_vault(archive)

    def test_schema_one_vault_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "legacy.vault.gmw"
            vault_engine.create_vault(self._build_source(root), archive)
            with closing(sqlite3.connect(archive)) as connection:
                table_names = [
                    row[0]
                    for row in connection.execute("SELECT table_name FROM structured_sources").fetchall()
                ]
                for table_name in table_names:
                    connection.execute(f'DROP TABLE "{table_name}"')
                connection.execute("DROP TABLE structured_columns")
                connection.execute("DROP TABLE structured_sources")
                connection.execute(
                    "UPDATE vault_metadata SET value = '1' WHERE key = 'schema_version'"
                )
                connection.execute(
                    "DELETE FROM vault_metadata WHERE key IN "
                    "('structured_source_count', 'structured_row_count')"
                )
                connection.commit()

            metadata = vault_engine.read_metadata(archive)
            self.assertEqual(metadata.schema_version, 1)
            self.assertEqual(metadata.structured_source_count, 0)
            self.assertEqual(vault_engine.list_structured_sources(archive), [])


if __name__ == "__main__":
    unittest.main()
