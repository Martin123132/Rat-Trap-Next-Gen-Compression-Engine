"""Relational structured-data layer for Rat-Trap queryable Vaults.

New Vaults retain their original files and additionally materialise supported
tabular data as typed SQLite tables.  The catalog keeps user-facing names
separate from safe internal identifiers so untrusted input never becomes SQL.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


DEFAULT_STRUCTURED_LIMIT = 64 * 1024 * 1024
MAX_COLUMNS = 256
MAX_ROWS = 250_000
MAX_QUERY_LIMIT = 100_000


@dataclass(frozen=True)
class StructuredSource:
    id: int
    file_id: int
    path: str
    name: str
    table_name: str
    data_format: str
    row_count: int
    column_count: int


@dataclass(frozen=True)
class StructuredColumn:
    ordinal: int
    source_name: str
    column_name: str
    declared_type: str


@dataclass(frozen=True)
class StructuredQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool = False
    source_id: Optional[int] = None


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE structured_sources (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            table_name TEXT NOT NULL UNIQUE,
            data_format TEXT NOT NULL,
            row_count INTEGER NOT NULL CHECK(row_count >= 0),
            column_count INTEGER NOT NULL CHECK(column_count > 0)
        );

        CREATE TABLE structured_columns (
            source_id INTEGER NOT NULL REFERENCES structured_sources(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            source_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            declared_type TEXT NOT NULL CHECK(declared_type IN ('INTEGER', 'REAL', 'TEXT')),
            PRIMARY KEY(source_id, ordinal),
            UNIQUE(source_id, column_name)
        );

        CREATE INDEX structured_sources_path ON structured_sources(path);
        """
    )


def _decode_text(data: bytes) -> Optional[str]:
    if b"\0" in data:
        return None
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    if text:
        controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
        if controls / len(text) > 0.01:
            return None
    return text


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _object_rows(payload: object) -> Optional[tuple[list[str], list[list[object]], str]]:
    data_format = "json"
    if isinstance(payload, dict):
        nested = [
            (key, value)
            for key, value in payload.items()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        if nested:
            _, payload = max(nested, key=lambda item: len(item[1]))
        else:
            payload = [payload]
    if not isinstance(payload, list) or not payload or not all(
        isinstance(item, dict) for item in payload
    ):
        return None
    if len(payload) > MAX_ROWS:
        return None
    names: list[str] = []
    seen: set[str] = set()
    for item in payload:
        for key in item:
            name = str(key)
            if name not in seen:
                names.append(name)
                seen.add(name)
            if len(names) > MAX_COLUMNS:
                return None
    if not names:
        return None
    rows = [[_json_value(item.get(name)) for name in names] for item in payload]
    return names, rows, data_format


def _parse_json_lines(text: str) -> Optional[tuple[list[str], list[list[object]], str]]:
    objects: list[dict[object, object]] = []
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                return None
            objects.append(value)
            if len(objects) > MAX_ROWS:
                return None
    except json.JSONDecodeError:
        return None
    parsed = _object_rows(objects)
    if parsed is None:
        return None
    return parsed[0], parsed[1], "jsonl"


def _looks_like_header(row: Sequence[str]) -> bool:
    if not row or len(set(row)) != len(row):
        return False
    return all(bool(value.strip()) for value in row) and any(
        re.search(r"[A-Za-z_]", value) for value in row
    )


def _parse_delimited(
    text: str, suffix: str
) -> Optional[tuple[list[str], list[list[object]], str]]:
    if suffix in {".data", ".test"}:
        text = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith(("|", "#"))
        )
    sample = text[:128 * 1024]
    if not sample.strip():
        return None
    if suffix == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except csv.Error:
            return None
    parsed_rows: list[list[str]] = []
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if not row or not any(value.strip() for value in row):
                continue
            parsed_rows.append([value.strip() for value in row])
            if len(parsed_rows) > MAX_ROWS + 1:
                return None
    except csv.Error:
        return None
    if len(parsed_rows) < 2:
        return None
    width = len(parsed_rows[0])
    if width < 2 or width > MAX_COLUMNS or any(len(row) != width for row in parsed_rows):
        return None
    if suffix in {".csv", ".tsv"}:
        has_header = _looks_like_header(parsed_rows[0])
    else:
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = False
    if has_header:
        names = parsed_rows.pop(0)
    else:
        names = [f"column_{index + 1}" for index in range(width)]
    if not parsed_rows:
        return None
    label = "tsv" if delimiter == "\t" else "csv"
    return names, parsed_rows, label


def _parse_structured(path: Path, text: str) -> Optional[tuple[list[str], list[list[object]], str]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return _object_rows(json.loads(text))
        except json.JSONDecodeError:
            return None
    if suffix in {".jsonl", ".ndjson"}:
        return _parse_json_lines(text)
    if suffix in {".csv", ".tsv", ".data", ".test"}:
        return _parse_delimited(text, suffix)
    return None


def _safe_names(names: Sequence[str]) -> list[str]:
    output: list[str] = []
    used: set[str] = set()
    for index, original in enumerate(names):
        candidate = re.sub(r"[^0-9A-Za-z_]", "_", original.strip()).strip("_")
        candidate = re.sub(r"_+", "_", candidate) or f"column_{index + 1}"
        if candidate[0].isdigit():
            candidate = f"column_{candidate}"
        base = candidate
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate.lower())
        output.append(candidate)
    return output


_INTEGER = re.compile(r"[-+]?(?:0|[1-9][0-9]*)\Z")
_REAL = re.compile(
    r"[-+]?(?:(?:[0-9]+\.[0-9]*)|(?:\.[0-9]+)|(?:[0-9]+[eE][-+]?[0-9]+)|"
    r"(?:[0-9]+\.[0-9]*[eE][-+]?[0-9]+))\Z"
)


def _value_kind(value: object) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    text = str(value).strip()
    if text.lower() in {"true", "false"} or _INTEGER.fullmatch(text):
        return "INTEGER"
    if _REAL.fullmatch(text):
        return "REAL"
    return "TEXT"


def _column_types(rows: Sequence[Sequence[object]], width: int) -> list[str]:
    types = ["INTEGER"] * width
    observed = [False] * width
    for row in rows:
        for index, value in enumerate(row):
            kind = _value_kind(value)
            if kind is None:
                continue
            observed[index] = True
            if kind == "TEXT" or types[index] == "TEXT":
                types[index] = "TEXT"
            elif kind == "REAL":
                types[index] = "REAL"
    return [declared if observed[index] else "TEXT" for index, declared in enumerate(types)]


def _coerce(value: object, declared_type: str) -> object:
    if value is None or value == "":
        return None
    if declared_type == "TEXT":
        return str(value)
    if isinstance(value, bool):
        return int(value)
    if declared_type == "INTEGER":
        text = str(value).strip().lower()
        if text in {"true", "false"}:
            return int(text == "true")
        return int(value)
    return float(value)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sidecar_names(path: Path, width: int) -> Optional[list[str]]:
    if path.suffix.lower() not in {".data", ".test"}:
        return None
    sidecar = path.with_suffix(".names")
    if not sidecar.is_file() or sidecar.stat().st_size > 1024 * 1024:
        return None
    text = _decode_text(sidecar.read_bytes())
    if text is None:
        return None
    names: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(("|", "#")):
            continue
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*:", line)
        if match:
            names.append(match.group(1))
    if len(names) == width:
        return names
    if len(names) + 1 == width:
        return [*names, "class"]
    return None


def ingest_file(
    connection: sqlite3.Connection,
    file_id: int,
    stored_path: str,
    path: Path,
    *,
    size_limit: int = DEFAULT_STRUCTURED_LIMIT,
) -> Optional[StructuredSource]:
    """Materialise one supported file, returning ``None`` when it is not tabular."""
    size = path.stat().st_size
    if size <= 0 or size > size_limit:
        return None
    suffix = path.suffix.lower()
    if suffix not in {
        ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".data", ".test"
    }:
        return None
    text = _decode_text(path.read_bytes())
    if text is None:
        return None
    parsed = _parse_structured(path, text)
    if parsed is None:
        return None
    source_names, rows, data_format = parsed
    sidecar_names = _sidecar_names(path, len(source_names))
    if sidecar_names is not None:
        source_names = sidecar_names
    column_names = _safe_names(source_names)
    types = _column_types(rows, len(column_names))
    table_name = f"rt_data_{file_id}"
    definitions = ", ".join(
        f"{_quote(name)} {declared_type}" for name, declared_type in zip(column_names, types)
    )
    connection.execute(f"CREATE TABLE {_quote(table_name)} ({definitions})")
    placeholders = ", ".join("?" for _ in column_names)
    connection.executemany(
        f"INSERT INTO {_quote(table_name)} VALUES ({placeholders})",
        ([ _coerce(value, types[index]) for index, value in enumerate(row)] for row in rows),
    )
    display_name = Path(stored_path).stem or Path(stored_path).name
    cursor = connection.execute(
        "INSERT INTO structured_sources(file_id, path, name, table_name, data_format, "
        "row_count, column_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (file_id, stored_path, display_name, table_name, data_format, len(rows), len(column_names)),
    )
    source_id = int(cursor.lastrowid)
    connection.executemany(
        "INSERT INTO structured_columns(source_id, ordinal, source_name, column_name, declared_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            (source_id, ordinal, source_names[ordinal], column_names[ordinal], types[ordinal])
            for ordinal in range(len(column_names))
        ),
    )
    return StructuredSource(
        source_id,
        file_id,
        stored_path,
        display_name,
        table_name,
        data_format,
        len(rows),
        len(column_names),
    )


def schema_available(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'structured_sources'"
    ).fetchone()
    return row is not None


def _row_to_source(row: sqlite3.Row) -> StructuredSource:
    source = StructuredSource(
        id=int(row["id"]),
        file_id=int(row["file_id"]),
        path=str(row["path"]),
        name=str(row["name"]),
        table_name=str(row["table_name"]),
        data_format=str(row["data_format"]),
        row_count=int(row["row_count"]),
        column_count=int(row["column_count"]),
    )
    if (
        source.id <= 0
        or source.file_id <= 0
        or source.table_name != f"rt_data_{source.file_id}"
        or source.row_count < 0
        or not 1 <= source.column_count <= MAX_COLUMNS
    ):
        raise ValueError("Vault contains invalid structured-data catalog metadata")
    return source


def list_sources(connection: sqlite3.Connection) -> list[StructuredSource]:
    if not schema_available(connection):
        return []
    return [
        _row_to_source(row)
        for row in connection.execute("SELECT * FROM structured_sources ORDER BY lower(path)")
    ]


def get_source(connection: sqlite3.Connection, source_id: int) -> StructuredSource:
    if not schema_available(connection):
        raise ValueError("This Vault does not contain structured data tables")
    row = connection.execute(
        "SELECT * FROM structured_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Structured data source {source_id} was not found")
    return _row_to_source(row)


def list_columns(connection: sqlite3.Connection, source_id: int) -> list[StructuredColumn]:
    get_source(connection, source_id)
    columns = [
        StructuredColumn(
            ordinal=int(row["ordinal"]),
            source_name=str(row["source_name"]),
            column_name=str(row["column_name"]),
            declared_type=str(row["declared_type"]),
        )
        for row in connection.execute(
            "SELECT * FROM structured_columns WHERE source_id = ? ORDER BY ordinal", (source_id,)
        )
    ]
    if any(
        item.ordinal != index
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.column_name)
        or item.declared_type not in {"INTEGER", "REAL", "TEXT"}
        for index, item in enumerate(columns)
    ):
        raise ValueError("Vault contains invalid structured column metadata")
    return columns


def validate_catalog(
    connection: sqlite3.Connection, expected_source_count: int, expected_row_count: int
) -> None:
    if not schema_available(connection):
        if expected_source_count or expected_row_count:
            raise ValueError("Vault structured-data catalog is missing")
        return
    sources = list_sources(connection)
    if len(sources) != expected_source_count or sum(item.row_count for item in sources) != expected_row_count:
        raise ValueError("Vault structured-data totals do not match its metadata")
    for source in sources:
        file_row = connection.execute(
            "SELECT path FROM files WHERE id = ?", (source.file_id,)
        ).fetchone()
        if file_row is None or str(file_row["path"]) != source.path:
            raise ValueError("Vault structured-data source does not match its original file")
        columns = list_columns(connection, source.id)
        if len(columns) != source.column_count:
            raise ValueError("Vault structured-data column count is inconsistent")
        actual_columns = connection.execute(
            f"PRAGMA table_info({_quote(source.table_name)})"
        ).fetchall()
        if [str(row["name"]) for row in actual_columns] != [item.column_name for item in columns]:
            raise ValueError("Vault structured-data table schema is inconsistent")
        row_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {_quote(source.table_name)}").fetchone()[0]
        )
        if row_count != source.row_count:
            raise ValueError("Vault structured-data row count is inconsistent")


def query_source(
    connection: sqlite3.Connection,
    source_id: int,
    *,
    search: str = "",
    column: str = "",
    sort_by: str = "",
    descending: bool = False,
    limit: int = 1000,
    offset: int = 0,
) -> StructuredQueryResult:
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"Query limit must be between 1 and {MAX_QUERY_LIMIT:,}")
    if offset < 0:
        raise ValueError("Query offset cannot be negative")
    source = get_source(connection, source_id)
    columns = list_columns(connection, source_id)
    allowed = {item.column_name for item in columns}
    if column and column not in allowed:
        raise ValueError(f"Unknown structured column '{column}'")
    if sort_by and sort_by not in allowed:
        raise ValueError(f"Unknown structured sort column '{sort_by}'")
    names = [item.column_name for item in columns]
    sql = f"SELECT rowid AS __row__, * FROM {_quote(source.table_name)}"
    parameters: list[object] = []
    if search:
        targets = [column] if column else names
        sql += " WHERE " + " OR ".join(
            f"CAST({_quote(name)} AS TEXT) LIKE ? ESCAPE '\\' COLLATE NOCASE" for name in targets
        )
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        parameters.extend([f"%{escaped}%"] * len(targets))
    sql += f" ORDER BY {_quote(sort_by) if sort_by else 'rowid'}"
    if descending:
        sql += " DESC"
    sql += " LIMIT ? OFFSET ?"
    parameters.extend((limit + 1, offset))
    fetched = connection.execute(sql, parameters).fetchall()
    truncated = len(fetched) > limit
    return StructuredQueryResult(
        columns=("__row__", *names),
        rows=tuple(tuple(row) for row in fetched[:limit]),
        truncated=truncated,
        source_id=source_id,
    )


def execute_sql(
    connection: sqlite3.Connection, sql: str, *, limit: int = 1000
) -> StructuredQueryResult:
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"Query limit must be between 1 and {MAX_QUERY_LIMIT:,}")
    statement = sql.strip()
    statement_without_comments = re.sub(
        r"\A(?:(?:--[^\n]*(?:\n|\Z))|(?:/\*.*?\*/)|\s)+", "", statement, flags=re.DOTALL
    )
    if not re.match(r"(?is)^(SELECT|WITH)\b", statement_without_comments):
        raise ValueError("Only read-only SELECT or WITH queries are allowed")

    denied_actions = {
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_ALTER_TABLE,
    }

    def authorizer(action, argument1, argument2, database, trigger):
        if action in denied_actions:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(argument2).lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorizer)
    try:
        cursor = connection.execute(statement)
    except sqlite3.ProgrammingError as exc:
        raise ValueError("Run one SQL statement at a time") from exc
    if cursor.description is None:
        raise ValueError("The SQL query did not return rows")
    columns = tuple(str(item[0]) for item in cursor.description)
    fetched = cursor.fetchmany(limit + 1)
    return StructuredQueryResult(
        columns=columns,
        rows=tuple(tuple(row) for row in fetched[:limit]),
        truncated=len(fetched) > limit,
    )


def export_result(result: StructuredQueryResult, output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix not in {".csv", ".tsv", ".json"}:
        raise ValueError("Structured results must be exported as .csv, .tsv, or .json")
    staging_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix=f".{output.name}.",
            suffix=".rat-trap-result",
            dir=output.parent,
            delete=False,
            encoding="utf-8" if suffix == ".json" else "utf-8-sig",
            newline="",
        ) as destination:
            staging_name = destination.name
            if suffix == ".json":
                records = [
                    dict(zip(result.columns, row))
                    for row in result.rows
                ]
                json.dump(
                    records,
                    destination,
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                delimiter = "\t" if suffix == ".tsv" else ","
                writer = csv.writer(destination, delimiter=delimiter)
                writer.writerow(result.columns)
                writer.writerows(result.rows)
        os.replace(staging_name, output)
        staging_name = None
    finally:
        if staging_name:
            try:
                os.unlink(staging_name)
            except FileNotFoundError:
                pass
