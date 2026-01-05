"""
Lazy ATTACH for configured external data sources.

Goal: make queries like `SELECT * FROM prod_db.public.users` "just work" by
attaching the referenced connection from `sql_connections/*.json` on demand.

Design principles:
- Best-effort: never fail a query just because an auto-attach failed.
- Low false-positives: default detection focuses on relation references (FROM/JOIN/UPDATE/INTO).
- No credential persistence: auto-attached connections are NOT written to _rvbbit_attachments.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .config import SqlConnectionConfig
from .connector import sanitize_name

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Token:
    typ: str  # word, ident, punct, string, other
    text: str


def _tokenize(sql: str) -> List[_Token]:
    """
    Very small SQL tokenizer for lazy attach detection.

    - Skips comments and string literals (single-quoted and dollar-quoted).
    - Treats double-quoted identifiers as ident tokens.
    - Emits punctuation tokens for '.', ',', '(', ')', ';'.
    """
    tokens: List[_Token] = []
    i = 0
    n = len(sql)

    def emit(typ: str, start: int, end: int) -> None:
        if end > start:
            tokens.append(_Token(typ, sql[start:end]))

    while i < n:
        ch = sql[i]

        # Whitespace
        if ch.isspace():
            i += 1
            continue

        # Line comment
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            continue

        # Block comment
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            continue

        # Single-quoted string
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # escaped ''
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        # Dollar-quoted string ($$...$$ or $tag$...$tag$)
        if ch == "$":
            m = re.match(r"\$[A-Za-z0-9_]*\$", sql[i:])
            if m:
                tag = m.group(0)
                i += len(tag)
                end = sql.find(tag, i)
                if end == -1:
                    # Unclosed; treat rest as string
                    break
                i = end + len(tag)
                continue

        # Double-quoted identifier
        if ch == '"':
            start = i + 1
            i += 1
            buf = []
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':  # escaped ""
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(_Token("ident", "".join(buf)))
            continue

        # Punctuation
        if ch in (".", ",", "(", ")", ";"):
            tokens.append(_Token("punct", ch))
            i += 1
            continue

        # Word/identifier
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
            emit("word", start, i)
            continue

        # Fallback
        tokens.append(_Token("other", ch))
        i += 1

    return tokens


def _parse_qualified_name(tokens: Sequence[_Token], start: int) -> Tuple[List[str], int]:
    """
    Parse `ident(.ident)+` starting at `start`.

    Returns: (parts, next_index)
    """
    if start >= len(tokens) or tokens[start].typ not in ("word", "ident"):
        return [], start

    parts = [tokens[start].text]
    i = start + 1
    while i + 1 < len(tokens) and tokens[i].typ == "punct" and tokens[i].text == "." and tokens[i + 1].typ in ("word", "ident"):
        parts.append(tokens[i + 1].text)
        i += 2
    return parts, i


_RELATION_KEYWORDS = {
    "FROM",
    "JOIN",
    "UPDATE",
    "INTO",
    "DELETE",
}

_RELATION_STOP_KEYWORDS = {
    "WHERE",
    "GROUP",
    "ORDER",
    "HAVING",
    "LIMIT",
    "QUALIFY",
    "WINDOW",
    "UNION",
    "EXCEPT",
    "INTERSECT",
    "RETURNING",
}

_RELATION_PREFIX_KEYWORDS = {"LATERAL", "ONLY"}


def extract_relation_qualified_names(sql: str) -> List[List[str]]:
    """
    Extract qualified relation names from common relation positions:
    - FROM <rel>
    - JOIN <rel>
    - UPDATE <rel>
    - INSERT INTO <rel>
    - DELETE FROM <rel>

    This is intentionally conservative to avoid capturing `t.col` expressions.
    """
    tokens = _tokenize(sql)
    out: List[List[str]] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.typ != "word":
            i += 1
            continue

        kw = tok.text.upper()
        if kw not in _RELATION_KEYWORDS:
            i += 1
            continue

        # DELETE FROM <rel>
        if kw == "DELETE":
            if i + 1 < len(tokens) and tokens[i + 1].typ == "word" and tokens[i + 1].text.upper() == "FROM":
                i += 1  # treat as FROM
                kw = "FROM"
            else:
                i += 1
                continue

        # INTO is only interesting for INSERT INTO (we don't enforce INSERT)
        i += 1

        # Skip optional modifiers like LATERAL/ONLY
        while i < len(tokens) and tokens[i].typ == "word" and tokens[i].text.upper() in _RELATION_PREFIX_KEYWORDS:
            i += 1

        # Subquery or derived table: FROM (SELECT ...)
        if i < len(tokens) and tokens[i].typ == "punct" and tokens[i].text == "(":
            # don't attempt to skip; inner FROM/JOIN will be caught by the main scan
            i += 1
            continue

        parts, next_i = _parse_qualified_name(tokens, i)
        if len(parts) >= 2:
            out.append(parts)

        i = max(i + 1, next_i)

    return out


def extract_any_dotted_prefixes(sql: str) -> Set[str]:
    """
    Aggressive fallback: extract the left-most identifier of any dotted path `x.y`.
    Intended for retry-on-error when conservative extraction misses.
    """
    tokens = _tokenize(sql)
    prefixes: Set[str] = set()

    i = 0
    while i + 2 < len(tokens):
        if tokens[i].typ in ("word", "ident") and tokens[i + 1].typ == "punct" and tokens[i + 1].text == "." and tokens[i + 2].typ in ("word", "ident"):
            # Only collect the LEFT-most segment in a chain like a.b.c
            if i == 0 or not (tokens[i - 1].typ == "punct" and tokens[i - 1].text == "."):
                prefixes.add(tokens[i].text)
            i += 1
            continue
        i += 1

    return prefixes


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _escape_single_quotes(value: str) -> str:
    return value.replace("'", "''")


class LazyAttachManager:
    """
    Per-connection lazy attach manager.

    Keeps small caches (failed attachments, folder file maps) to avoid repeatedly
    retrying broken connections on every query.
    """

    def __init__(self, duckdb_conn, sql_connections: Dict[str, SqlConnectionConfig]):
        self._conn = duckdb_conn
        self._configs = dict(sql_connections)

        # Some "connections" are folder-based and generate multiple attach targets
        self._duckdb_folder_configs = [
            cfg for cfg in self._configs.values() if cfg.type == "duckdb_folder" and cfg.folder_path
        ]

        self._failed_configs: Set[str] = set()
        self._duckdb_file_maps: Dict[str, Dict[str, Path]] = {}  # folder_path -> {db_name: file_path}
        self._csv_file_maps: Dict[str, Dict[str, Path]] = {}  # connection_name -> {table_name: file_path}

    def ensure_for_query(self, sql: str, *, aggressive: bool = False) -> None:
        """
        Ensure any referenced configured sources are attached/materialized.

        If aggressive=True, falls back to scanning any dotted prefixes in addition
        to conservative FROM/JOIN/etc extraction.
        """
        if not _lazy_attach_enabled():
            return

        qualified = extract_relation_qualified_names(sql)

        dotted_prefixes: Set[str] = set()
        if aggressive:
            dotted_prefixes = extract_any_dotted_prefixes(sql)

        needed_catalogs: Set[str] = set()
        needed_csv_tables: Dict[str, Set[str]] = {}

        # From relation-qualified names
        for parts in qualified:
            if not parts:
                continue
            prefix = parts[0]
            if prefix in self._configs:
                cfg = self._configs[prefix]
                if cfg.type == "csv_folder" and len(parts) >= 2:
                    needed_csv_tables.setdefault(prefix, set()).add(parts[1])
                else:
                    needed_catalogs.add(prefix)
            else:
                # Might be a DuckDB file in a duckdb_folder connection
                needed_catalogs.add(prefix)

        # From aggressive dotted prefixes
        for prefix in dotted_prefixes:
            if prefix in self._configs:
                cfg = self._configs[prefix]
                if cfg.type == "csv_folder":
                    # Not enough info to know which table; skip
                    continue
                needed_catalogs.add(prefix)
            else:
                needed_catalogs.add(prefix)

        # Attach catalogs (postgres/mysql/sqlite or duckdb files)
        for catalog in sorted(needed_catalogs):
            self._ensure_catalog_attached(catalog)

        # Ensure CSV schema/tables (view/table) exist
        for schema_name, tables in needed_csv_tables.items():
            self._ensure_csv_tables(schema_name, tables)

    # ---------------------------------------------------------------------
    # Attachment helpers
    # ---------------------------------------------------------------------

    def _attached_catalogs(self) -> Set[str]:
        try:
            rows = self._conn.execute(
                """
                SELECT database_name
                FROM duckdb_databases()
                WHERE NOT internal
                """
            ).fetchall()
            return {r[0] for r in rows}
        except Exception:
            return set()

    def _ensure_catalog_attached(self, catalog: str) -> None:
        # Already attached?
        if catalog in self._attached_catalogs():
            return

        # Known configured connection?
        cfg = self._configs.get(catalog)
        if cfg:
            if cfg.connection_name in self._failed_configs:
                return
            try:
                self._attach_config(cfg)
            except Exception as e:
                self._failed_configs.add(cfg.connection_name)
                log.debug("[lazy_attach] Failed attaching %s: %s", cfg.connection_name, e)
            return

        # Otherwise: see if it matches a duckdb_folder file name
        try:
            attached = self._attach_duckdb_file_if_present(catalog)
            if attached:
                return
        except Exception as e:
            log.debug("[lazy_attach] Failed attaching duckdb file %s: %s", catalog, e)

    def _attach_config(self, cfg: SqlConnectionConfig) -> None:
        if cfg.type == "postgres":
            self._attach_postgres(cfg)
            return
        if cfg.type == "mysql":
            self._attach_mysql(cfg)
            return
        if cfg.type == "sqlite":
            self._attach_sqlite(cfg)
            return
        # csv_folder is handled via schema/table materialization (not catalog attach)
        if cfg.type == "csv_folder":
            return
        if cfg.type == "duckdb_folder":
            # Individual duckdb files are attached on demand by name.
            return
        raise ValueError(f"Unsupported connection type for lazy attach: {cfg.type}")

    def _attach_postgres(self, cfg: SqlConnectionConfig) -> None:
        # Best-effort extension setup
        try:
            self._conn.execute("INSTALL postgres;")
        except Exception:
            pass
        self._conn.execute("LOAD postgres;")

        if not (cfg.database and cfg.host and cfg.port and cfg.user):
            raise ValueError(f"postgres config missing required fields for {cfg.connection_name}")

        conn_str = f"dbname={cfg.database} host={cfg.host} port={cfg.port} user={cfg.user}"
        if cfg.password:
            conn_str += f" password={cfg.password}"

        alias = _quote_ident(cfg.connection_name)
        self._conn.execute(
            f"ATTACH '{_escape_single_quotes(conn_str)}' AS {alias} (TYPE postgres);"
        )

    def _attach_mysql(self, cfg: SqlConnectionConfig) -> None:
        try:
            self._conn.execute("INSTALL mysql;")
        except Exception:
            pass
        self._conn.execute("LOAD mysql;")

        if not (cfg.database and cfg.host and cfg.port and cfg.user):
            raise ValueError(f"mysql config missing required fields for {cfg.connection_name}")

        conn_str = f"host={cfg.host} port={cfg.port} database={cfg.database} user={cfg.user}"
        if cfg.password:
            conn_str += f" password={cfg.password}"

        alias = _quote_ident(cfg.connection_name)
        self._conn.execute(
            f"ATTACH '{_escape_single_quotes(conn_str)}' AS {alias} (TYPE mysql);"
        )

    def _attach_sqlite(self, cfg: SqlConnectionConfig) -> None:
        if not cfg.database:
            raise ValueError(f"sqlite config missing database path for {cfg.connection_name}")
        alias = _quote_ident(cfg.connection_name)
        self._conn.execute(
            f"ATTACH '{_escape_single_quotes(cfg.database)}' AS {alias} (TYPE sqlite);"
        )

    def _attach_duckdb_file_if_present(self, db_name: str) -> bool:
        # Avoid reserved/system catalogs
        if db_name.lower() in {"system", "temp", "memory"}:
            return False

        for folder_cfg in self._duckdb_folder_configs:
            folder_path = folder_cfg.folder_path
            if not folder_path:
                continue

            file_map = self._duckdb_file_maps.get(folder_path)
            if file_map is None:
                file_map = self._build_duckdb_file_map(folder_path)
                self._duckdb_file_maps[folder_path] = file_map

            db_file = file_map.get(db_name)
            if not db_file:
                continue

            _attach_duckdb_read_only_with_snapshot_fallback(self._conn, db_file, db_name)
            return True

        return False

    def _build_duckdb_file_map(self, folder_path: str) -> Dict[str, Path]:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return {}
        mapping: Dict[str, Path] = {}
        for db_file in folder.glob("*.duckdb"):
            mapping[sanitize_name(db_file.name)] = db_file
        return mapping

    def _ensure_csv_tables(self, connection_name: str, tables: Set[str]) -> None:
        cfg = self._configs.get(connection_name)
        if not cfg or cfg.type != "csv_folder":
            return
        if not cfg.folder_path:
            return

        # Ensure schema exists
        self._conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(connection_name)};")

        # Build file map once per connection
        file_map = self._csv_file_maps.get(connection_name)
        if file_map is None:
            file_map = self._build_csv_file_map(cfg.folder_path)
            self._csv_file_maps[connection_name] = file_map

        for table_name in sorted(tables):
            try:
                if self._csv_table_exists(connection_name, table_name):
                    continue

                csv_file = file_map.get(table_name)
                if not csv_file:
                    continue

                full_name = f"{_quote_ident(connection_name)}.{_quote_ident(table_name)}"

                if _lazy_attach_csv_materialize():
                    self._conn.execute(
                        f"""
                        CREATE TABLE {full_name} AS
                        SELECT * FROM read_csv_auto('{_escape_single_quotes(str(csv_file))}', AUTO_DETECT=TRUE, ignore_errors=true)
                        """.strip()
                    )
                else:
                    self._conn.execute(
                        f"""
                        CREATE OR REPLACE VIEW {full_name} AS
                        SELECT * FROM read_csv_auto('{_escape_single_quotes(str(csv_file))}', AUTO_DETECT=TRUE, ignore_errors=true)
                        """.strip()
                    )
            except Exception as e:
                log.debug("[lazy_attach] Failed ensuring csv table %s.%s: %s", connection_name, table_name, e)

    def _csv_table_exists(self, schema_name: str, table_name: str) -> bool:
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = ? AND table_name = ?
                """,
                [schema_name, table_name],
            ).fetchone()
            return bool(row and row[0] > 0)
        except Exception:
            return False

    def _build_csv_file_map(self, folder_path: str) -> Dict[str, Path]:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return {}
        mapping: Dict[str, Path] = {}
        for csv_file in folder.glob("*.csv"):
            mapping[sanitize_name(csv_file.name)] = csv_file
        return mapping


def _lazy_attach_enabled() -> bool:
    val = os.environ.get("RVBBIT_LAZY_ATTACH", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def _lazy_attach_csv_materialize() -> bool:
    val = os.environ.get("RVBBIT_LAZY_ATTACH_CSV_MATERIALIZE", "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def _attach_duckdb_read_only_with_snapshot_fallback(duckdb_conn, db_file: Path, db_name: str, max_retries: int = 2) -> None:
    """
    Attach a DuckDB file READ_ONLY with snapshot fallback (copy-on-read) if locked.

    Adapted from `DatabaseConnector._attach_duckdb_file`, but scoped for the
    pgwire server's per-session DuckDB connection.
    """
    last_error = None

    # Strategy 1/2: direct attach with retries
    for attempt in range(max_retries):
        try:
            duckdb_conn.execute(f"ATTACH '{_escape_single_quotes(str(db_file))}' AS {_quote_ident(db_name)} (READ_ONLY)")
            return
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_lock_error = any(
                phrase in error_str
                for phrase in ("lock", "could not set lock", "database is locked", "unable to open", "exclusive")
            )
            if not is_lock_error:
                raise
            if attempt < max_retries - 1:
                time.sleep(0.3 * (2**attempt))

    # Strategy 3: snapshot copy
    temp_dir = Path(tempfile.gettempdir()) / "rvbbit_duckdb_snapshots"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{db_name}.duckdb"

    try:
        shutil.copy2(db_file, temp_path)
        duckdb_conn.execute(f"ATTACH '{_escape_single_quotes(str(temp_path))}' AS {_quote_ident(db_name)} (READ_ONLY)")
        return
    except Exception as copy_error:
        raise Exception(
            f"Failed to attach {db_file.name}: direct attach failed ({last_error}), snapshot copy failed ({copy_error})"
        )
