"""
LLM-facing SQL tools for schema search and query execution.
"""

import json
import math
import os
import re
import duckdb
import threading
import time
import copy
from collections import OrderedDict
from pathlib import Path
from typing import Optional


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    This is necessary because pandas converts SQL NULLs to float('nan')
    for numeric columns, and json.dumps outputs literal NaN which is
    invalid JSON that JavaScript's JSON.parse() cannot handle.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


def _truncate_text(value, max_chars: int) -> tuple[object, bool]:
    """Truncate long strings and return (value, was_truncated)."""
    if isinstance(value, str) and max_chars > 0 and len(value) > max_chars:
        return value[:max_chars] + "...", True
    return value, False


def _cardinality_key(value) -> str:
    """Create a stable, hashable key for cardinality counting."""
    safe_value = sanitize_for_json(value)
    if isinstance(safe_value, (dict, list)):
        return json.dumps(safe_value, sort_keys=True, default=str)
    return str(safe_value)


def _compute_column_cardinality(rows: list[dict], columns: list[str]) -> dict[str, int]:
    """Compute distinct counts per column over the returned preview rows."""
    cardinality = {}
    for col in columns:
        seen = set()
        for row in rows:
            seen.add(_cardinality_key(row.get(col)))
        cardinality[col] = len(seen)
    return cardinality


def _normalized_schema_value(database: Optional[str], schema: Optional[str]) -> Optional[str]:
    if schema is None:
        return None
    norm_schema = _normalize_identifier(schema)
    norm_db = _normalize_identifier(database)
    if not norm_schema:
        return None
    if norm_db and _ident_equal(norm_schema, norm_db):
        return None
    return norm_schema


def _sql_error_response(
    *,
    sql: str,
    connection: Optional[str],
    error_message: str,
    error_type: str,
    hint: str,
    phase: str = "execute",
) -> str:
    """Build a clear, structured SQL error response while keeping legacy fields."""
    return json.dumps({
        "status": "error",
        "error": error_message,  # Legacy field retained for compatibility
        "error_message": error_message,  # Explicit field for agents/UI
        "error_type": error_type,
        "phase": phase,
        "sql": sql,
        "connection": connection,
        "hint": hint,
        "action": "Fix the SQL using the exact error_message and retry.",
        "columns": [],
        "rows": [],
        "results": [],
        "row_count": 0
    })


def _resolve_connection_name(connection: Optional[str], connections: dict) -> Optional[str]:
    """Resolve a connection name against configured connections (case-insensitive)."""
    normalized = _normalize_identifier(connection)
    if not normalized:
        return None
    if normalized in connections:
        return normalized
    target = normalized.lower()
    for name in connections.keys():
        if str(name).strip().lower() == target:
            return str(name)
    return None


def _execute_sql_via_pgwire_pipeline(
    *,
    sql: str,
    connection: Optional[str],
):
    """
    Execute SQL using the same high-level pipeline as pgwire/session mode:
      1) best-effort UDF registration
      2) lazy attach from SQL references
      3) rewrite LARS SQL extensions to DuckDB SQL
      4) execute on DuckDB cursor

    Returns:
        (conn, cursor, executed_sql, resolved_connection)
    """
    connections = load_sql_connections()
    resolved_connection = _resolve_connection_name(connection, connections) if connection else None

    conn = duckdb.connect(":memory:")
    conn.execute("SET threads TO 2")

    # Register UDFs (best-effort).
    try:
        from .udf import register_lars_udf, register_dynamic_sql_functions

        register_lars_udf(conn, config={})
        register_dynamic_sql_functions(conn)
    except Exception:
        pass

    # Attach referenced connections (best-effort, relies on qualified refs).
    try:
        from .lazy_attach import LazyAttachManager

        lazy = LazyAttachManager(conn, connections)
        lazy.ensure_for_query(sql, aggressive=False)
    except Exception:
        pass

    executed_sql = sql
    try:
        from ..sql_rewriter import rewrite_lars_syntax

        executed_sql = rewrite_lars_syntax(sql, duckdb_conn=conn)
    except Exception:
        # Fall back to raw SQL when rewriter is not applicable.
        executed_sql = sql

    cursor = conn.execute(executed_sql)
    return conn, cursor, executed_sql, resolved_connection


from ..config import get_config
from ..rag.store import search_chunks
from .sql_duckdb_index import (
    USE_DEDICATED_SQL_DUCKDB_INDEX,
    get_sql_index_meta,
    search_sql_index,
)

try:
    import yaml as _yaml  # PyYAML
except ImportError:
    _yaml = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(str(raw).strip())
    except Exception:
        return default
    return max(min_value, parsed)


# Duck-local default: skip ES import/ping path unless explicitly enabled.
_SQL_SEARCH_USE_ELASTIC = _env_bool("LARS_SQL_SEARCH_USE_ELASTIC", False)
_RAG_META_CACHE_TTL_SECONDS = max(5.0, float(os.getenv("LARS_SQL_RAG_META_CACHE_TTL_SECONDS", "300")))
_DISCOVERY_META_CACHE_TTL_SECONDS = max(1.0, float(os.getenv("LARS_SQL_DISCOVERY_META_CACHE_TTL_SECONDS", "30")))
_TABLE_META_CACHE_MAX_ENTRIES = max(64, int(os.getenv("LARS_SQL_TABLE_META_CACHE_MAX_ENTRIES", "4096")))
_SQL_SEARCH_RESULT_CACHE_MAX_ENTRIES = max(64, int(os.getenv("LARS_SQL_SEARCH_RESULT_CACHE_MAX_ENTRIES", "1024")))
_CONNECTION_TYPES_CACHE_TTL_SECONDS = max(1.0, float(os.getenv("LARS_SQL_CONNECTION_TYPES_CACHE_TTL_SECONDS", "30")))
_SQL_SEARCH_MAX_COLUMNS = int(os.getenv("LARS_SQL_SEARCH_MAX_COLUMNS", "40"))
_SQL_TABLE_META_MAX_VALUE_DISTRIBUTION = _env_int("LARS_SQL_TABLE_META_MAX_VALUE_DISTRIBUTION", 5, min_value=0)

_discovery_meta_cache_lock = threading.Lock()
_discovery_meta_cache: dict[str, object] = {
    "expires_at": 0.0,
    "value": None,
}

_rag_meta_cache_lock = threading.Lock()
_rag_meta_cache: dict[str, dict[str, object]] = {}

_table_meta_cache_lock = threading.Lock()
_table_meta_cache: dict[str, tuple[int, dict]] = {}

_sql_search_result_cache_lock = threading.Lock()
_sql_search_result_cache: "OrderedDict[str, str]" = OrderedDict()

_connection_types_cache_lock = threading.Lock()
_connection_types_cache: dict[str, object] = {
    "expires_at": 0.0,
    "value": {},
}


def _compact_tables(tables: list) -> list:
    """
    Strip heavy metadata from table schemas to reduce output size.

    Removes value_distribution arrays from column metadata which can be
    massive (thousands of entries per column). Keeps essential info:
    - Table name, database, schema
    - Row count
    - Column names and types
    - Basic stats (min, max, distinct_count)

    This prevents issues with:
    - JDBC clients failing on huge VARCHAR values
    - PostgreSQL wire protocol message limits
    - JSON parsing overhead in downstream tools
    """
    compacted = []
    conn_types = _get_cached_connection_types()
    for table in tables:
        database = table.get("database")
        schema = table.get("schema")
        table_name = table.get("table_name")
        normalized_schema = _normalized_schema_value(database, schema)
        conn_type = conn_types.get(str(database), "")
        sql_table_ref = (
            table.get("sql_table_ref")
            or _sql_table_ref_for_table(
                database=database,
                schema=schema,
                table_name=table_name,
                conn_type=conn_type,
            )
            or _build_qualified_name(table)
        )
        compact_table = {
            "qualified_name": table.get("qualified_name"),
            "sql_table_ref": sql_table_ref,
            "database": database,
            "schema": normalized_schema,
            "table_name": table_name,
            "description": table.get("description"),
            "row_count": table.get("row_count"),
            "match_score": table.get("match_score"),
        }

        # Compact columns - keep type info but strip value_distribution.
        # Bound per-table column payload to reduce token bloat in tool results.
        if "columns" in table:
            raw_columns = table.get("columns", []) or []
            total_columns = len(raw_columns)
            max_columns = _SQL_SEARCH_MAX_COLUMNS
            if max_columns > 0:
                raw_columns = raw_columns[:max_columns]
            if total_columns > len(raw_columns):
                compact_table["columns_truncated"] = True
                compact_table["total_columns"] = total_columns
            compact_columns = []
            for col in raw_columns:
                compact_col = {
                    "name": col.get("name"),
                    "type": col.get("type"),
                    "nullable": col.get("nullable"),
                }
                # Keep basic metadata but exclude value_distribution
                if "metadata" in col and col["metadata"]:
                    compact_col["metadata"] = {
                        "distinct_count": col["metadata"].get("distinct_count"),
                        "min": col["metadata"].get("min"),
                        "max": col["metadata"].get("max"),
                        # Explicitly exclude value_distribution
                    }
                compact_columns.append(compact_col)
            compact_table["columns"] = compact_columns

        compacted.append(compact_table)

    return compacted
from ..rag.context import RagContext
from .config import load_discovery_metadata, load_sql_connections
from .connector import DatabaseConnector


def _pivot_tables_to_rows(tables: list, query: str, source: str, schema_brief: Optional[str] = None) -> list:
    """
    Convert a list of table metadata dicts into a flat row-per-table format.

    Instead of returning one row with all tables in a nested array, this returns
    one row per table with flattened fields. The columns array is pre-serialized
    as JSON to avoid STRUCT[] type issues with PostgreSQL wire protocol.

    Output structure per row:
    - query: The search query
    - source: Data source (elasticsearch, rag, etc.)
    - qualified_name: Full table reference
    - sql_table_ref: Canonical relation name to use in DuckDB SQL
    - database, schema, table_name: Table identifiers
    - description: Table description
    - row_count: Number of rows
    - match_score: Search relevance score
    - columns_json: Pre-serialized JSON of column metadata
    - schema_brief: Optional LLM-generated summary (only on first row if present)
    - relevance, reasoning, key_columns_json, join_hint: Smart search enrichments (if present)
    """
    rows = []
    compacted = _compact_tables(tables)

    # Also need to preserve smart search fields that aren't in _compact_tables
    # Build a lookup by qualified_name
    smart_fields_by_name = {
        t.get("qualified_name"): {
            "relevance": t.get("relevance"),
            "reasoning": t.get("reasoning"),
            "key_columns": t.get("key_columns"),
            "join_hint": t.get("join_hint"),
        }
        for t in tables
    }

    for i, table in enumerate(compacted):
        qname = table.get("qualified_name")
        smart_fields = smart_fields_by_name.get(qname, {})

        row = {
            "query": query,
            "source": source,
            "qualified_name": qname,
            "sql_table_ref": table.get("sql_table_ref"),
            "database": table.get("database"),
            "schema": table.get("schema"),
            "table_name": table.get("table_name"),
            "description": table.get("description", ""),
            "row_count": table.get("row_count"),
            "match_score": table.get("match_score"),
            "columns_json": json.dumps(table.get("columns", [])),
        }
        if table.get("columns_truncated"):
            row["columns_truncated"] = True
            row["total_columns"] = table.get("total_columns")

        # Add smart search enrichments if present
        if smart_fields.get("relevance"):
            row["relevance"] = smart_fields["relevance"]
        if smart_fields.get("reasoning"):
            row["reasoning"] = smart_fields["reasoning"]
        if smart_fields.get("key_columns"):
            row["key_columns_json"] = json.dumps(smart_fields["key_columns"])
        if smart_fields.get("join_hint"):
            row["join_hint"] = smart_fields["join_hint"]

        # Include schema_brief only on first row to avoid repetition
        if i == 0 and schema_brief:
            row["schema_brief"] = schema_brief

        rows.append(row)

    return rows


def _rows_to_tables(rows: list[dict]) -> list[dict]:
    """
    Convert row-per-table output back into table dicts for smart filtering.

    Used when sql_search falls back to sql_rag_search (which returns rows).
    """
    tables = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        columns = []
        raw_columns = row.get("columns_json")
        if isinstance(raw_columns, str):
            try:
                columns = json.loads(raw_columns)
            except Exception:
                columns = []
        elif isinstance(raw_columns, list):
            columns = raw_columns

        tables.append({
            "qualified_name": row.get("qualified_name"),
            "sql_table_ref": row.get("sql_table_ref"),
            "database": row.get("database"),
            "schema": row.get("schema"),
            "table_name": row.get("table_name"),
            "description": row.get("description", ""),
            "row_count": row.get("row_count"),
            "match_score": row.get("match_score"),
            "columns": columns,
        })

    return tables


def _get_cached_discovery_metadata():
    now = time.time()
    with _discovery_meta_cache_lock:
        expires_at = float(_discovery_meta_cache.get("expires_at") or 0.0)
        cached = _discovery_meta_cache.get("value")
        if cached is not None and now < expires_at:
            return cached

    meta = load_discovery_metadata()
    with _discovery_meta_cache_lock:
        _discovery_meta_cache["value"] = meta
        _discovery_meta_cache["expires_at"] = now + _DISCOVERY_META_CACHE_TTL_SECONDS
    return meta


def _get_cached_connection_types() -> dict[str, str]:
    now = time.time()
    with _connection_types_cache_lock:
        expires_at = float(_connection_types_cache.get("expires_at") or 0.0)
        cached = _connection_types_cache.get("value")
        if isinstance(cached, dict) and now < expires_at:
            return dict(cached)

    conn_types: dict[str, str] = {}
    try:
        connections = load_sql_connections()
        for name, cfg in connections.items():
            conn_types[str(name)] = str(getattr(cfg, "type", "") or "")
    except Exception:
        conn_types = {}

    with _connection_types_cache_lock:
        _connection_types_cache["value"] = conn_types
        _connection_types_cache["expires_at"] = now + _CONNECTION_TYPES_CACHE_TTL_SECONDS
    return dict(conn_types)


def _sql_table_ref_for_table(
    *,
    database: Optional[str],
    schema: Optional[str],
    table_name: Optional[str],
    conn_type: Optional[str] = None,
) -> Optional[str]:
    db = _normalize_identifier(database)
    table = _normalize_identifier(table_name)
    if not db or not table:
        return None

    schema_norm = _normalize_identifier(schema)
    schema_out = _normalized_schema_value(db, schema_norm)
    ctype = str(conn_type or "").strip().lower()

    # For duckdb_folder, tables are queried as db_name.table_name where db_name
    # is stored in metadata.schema.
    if ctype == "duckdb_folder":
        if schema_norm:
            return f"{schema_norm}.{table}"
        return f"{db}.{table}"

    # Connection-local, schema-less query forms.
    if ctype in {
        "csv_folder",
        "jsonl_folder",
        "markdown_folder",
        "sqlite",
        "duckdb",
        "native",
        "s3",
        "azure",
        "gcs",
        "http",
        "mongodb",
        "cassandra",
        "oracle",
        "mssql",
        "db2",
        "hana",
        "excel",
        "gsheets",
        "delta",
        "iceberg",
        "clickhouse",
    }:
        return f"{db}.{table}"

    if schema_out:
        return f"{db}.{schema_out}.{table}"
    return f"{db}.{table}"


def _get_cached_rag_index_meta(rag_id: str) -> tuple[bool, int]:
    now = time.time()
    with _rag_meta_cache_lock:
        entry = _rag_meta_cache.get(rag_id)
        if entry and now < float(entry.get("expires_at") or 0.0):
            return bool(entry.get("has_chunks")), int(entry.get("embedding_dim") or 0)

    if USE_DEDICATED_SQL_DUCKDB_INDEX:
        has_chunks, embedding_dim = get_sql_index_meta(rag_id)
    else:
        from ..db_adapter import get_db

        db = get_db()
        rows = db.query(
            f"SELECT count() as cnt, any(embedding_dim) as embedding_dim FROM rag_chunks WHERE rag_id = '{rag_id}'"
        )
        cnt = int(rows[0].get("cnt") or 0) if rows else 0
        embedding_dim = int(rows[0].get("embedding_dim") or 0) if rows else 0
        has_chunks = cnt > 0

    with _rag_meta_cache_lock:
        _rag_meta_cache[rag_id] = {
            "has_chunks": has_chunks,
            "embedding_dim": embedding_dim,
            "expires_at": now + _RAG_META_CACHE_TTL_SECONDS,
        }

    return has_chunks, embedding_dim


def _build_sql_search_cache_key(
    *,
    query: str,
    k: int,
    min_row_count: Optional[int],
    use_smart: bool,
    task_context: Optional[str],
    sql_search_use_elastic: bool,
    index_version: dict[str, object],
) -> str:
    payload = {
        "query": query,
        "k": int(k),
        "min_row_count": min_row_count,
        "use_smart": bool(use_smart),
        "task_context": task_context,
        "sql_search_use_elastic": bool(sql_search_use_elastic),
        "index_version": index_version,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _get_sql_search_cached_result(cache_key: str) -> Optional[str]:
    with _sql_search_result_cache_lock:
        cached = _sql_search_result_cache.get(cache_key)
        if cached is None:
            return None
        _sql_search_result_cache.move_to_end(cache_key)
        return cached


def _set_sql_search_cached_result(cache_key: str, payload: str) -> None:
    if not payload:
        return
    with _sql_search_result_cache_lock:
        _sql_search_result_cache[cache_key] = payload
        _sql_search_result_cache.move_to_end(cache_key)
        while len(_sql_search_result_cache) > _SQL_SEARCH_RESULT_CACHE_MAX_ENTRIES:
            _sql_search_result_cache.popitem(last=False)


def _is_cacheable_sql_search_payload(payload: str) -> bool:
    try:
        data = json.loads(payload)
    except Exception:
        return False
    if isinstance(data, list):
        return True
    if isinstance(data, dict):
        return "error" not in data
    return False


def _maybe_cache_sql_search_result(cache_key: str, payload: str) -> str:
    if _is_cacheable_sql_search_payload(payload):
        _set_sql_search_cached_result(cache_key, payload)
    return payload


def _clear_sql_search_result_cache() -> None:
    with _sql_search_result_cache_lock:
        _sql_search_result_cache.clear()


def _load_table_meta_cached(full_path: str) -> Optional[dict]:
    try:
        stat = os.stat(full_path)
    except Exception:
        return None

    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
    with _table_meta_cache_lock:
        cached = _table_meta_cache.get(full_path)
        if cached and cached[0] == mtime_ns:
            return cached[1]

    ext = os.path.splitext(full_path)[1].lower()
    try:
        with open(full_path, encoding="utf-8") as f:
            if ext in (".yaml", ".yml"):
                if _yaml is None:
                    raise ImportError(
                        "PyYAML is required to read YAML SQL samples. Install with: pip install pyyaml"
                    )
                parsed = _yaml.safe_load(f)
            else:
                parsed = json.load(f)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    with _table_meta_cache_lock:
        _table_meta_cache[full_path] = (mtime_ns, parsed)
        if len(_table_meta_cache) > _TABLE_META_CACHE_MAX_ENTRIES:
            # Evict oldest inserted item (dict preserves insertion order on py3.7+)
            try:
                first_key = next(iter(_table_meta_cache))
                _table_meta_cache.pop(first_key, None)
            except Exception:
                pass
    return parsed


def _normalize_identifier(value: Optional[str]) -> Optional[str]:
    """Normalize SQL identifiers provided by callers."""
    if value is None:
        return None
    ident = str(value).strip()
    if not ident:
        return None

    if len(ident) >= 2:
        if ident[0] == ident[-1] and ident[0] in {"'", '"', "`"}:
            ident = ident[1:-1].strip()
        elif ident[0] == "[" and ident[-1] == "]":
            ident = ident[1:-1].strip()
    return ident or None


def _ident_equal(left: Optional[str], right: Optional[str]) -> bool:
    if left is None or right is None:
        return False
    return str(left).strip().lower() == str(right).strip().lower()


def _build_qualified_name(table_meta: dict) -> Optional[str]:
    table_name = table_meta.get("table_name")
    database = table_meta.get("database")
    if not table_name or not database:
        return None
    schema = _normalized_schema_value(database, table_meta.get("schema"))
    if schema:
        return f"{database}.{schema}.{table_name}"
    return f"{database}.{table_name}"


def _parse_qualified_name(qualified_name: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a qualified table name into (database, schema, table_name, error).

    Supported forms:
      - database.table
      - database.schema.table
    """
    normalized = _normalize_identifier(qualified_name)
    if not normalized:
        return None, None, None, None

    parts: list[str] = []
    for raw in normalized.split("."):
        part = _normalize_identifier(raw)
        if part:
            parts.append(part)

    if len(parts) < 2:
        return None, None, None, (
            "qualified_name must be in the form 'database.table' "
            "or 'database.schema.table'"
        )

    database = parts[0]
    table_name = parts[-1]
    schema = ".".join(parts[1:-1]) if len(parts) > 2 else None
    return database, schema, table_name, None


def _table_meta_matches(
    table_meta: dict,
    *,
    database: Optional[str],
    schema: Optional[str],
    table_name: Optional[str],
) -> bool:
    if not isinstance(table_meta, dict):
        return False

    if not table_meta.get("table_name"):
        return False

    if table_name and not _ident_equal(table_meta.get("table_name"), table_name):
        return False

    if database and not _ident_equal(table_meta.get("database"), database):
        return False

    if schema and not _ident_equal(table_meta.get("schema"), schema):
        return False

    return True


def _candidate_table_meta_paths(
    samples_dir: Path,
    *,
    database: Optional[str],
    schema: Optional[str],
    table_name: Optional[str],
) -> list[Path]:
    if not table_name:
        return []

    exts = (".yaml", ".yml", ".json")
    candidates: list[Path] = []

    if database and schema:
        for ext in exts:
            candidates.append(samples_dir / database / schema / f"{table_name}{ext}")

    if database:
        for ext in exts:
            candidates.append(samples_dir / database / f"{table_name}{ext}")
            candidates.append(samples_dir / database / "default" / f"{table_name}{ext}")

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def sql_rag_search(
    query: str,
    k: int = 10,
    score_threshold: Optional[float] = 0.3,
    query_embedding: Optional[list[float]] = None,
    query_embedding_model: Optional[str] = None,
    query_embedding_dim: Optional[int] = None,
) -> str:
    """
    Search SQL schema metadata using DuckDB-backed RAG (vector search).

    This is the local SQL schema retrieval path used by `sql_search`.
    It supports optional precomputed query embeddings to avoid duplicate embed calls.

    Finds relevant tables and columns across all configured databases.
    Returns table metadata including column info, distributions, and sample values.

    This tool searches the unified schema index built by `lars sql chart`.
    If you get an error about missing index, ask the user to run: lars sql chart

    Example queries:
      - "tables with user information"
      - "sales or revenue data"
      - "bigfoot sightings location data"
      - "customer country information"

    Args:
        query: Natural language description of what to find
        k: Number of results to return (default: 10)
        score_threshold: Minimum similarity score (default: 0.3)

    Returns:
        JSON array with one row per matching table:
        - query: Search query used
        - source: "rag"
        - qualified_name: Metadata identifier for sql_get_table_meta
        - sql_table_ref: Canonical relation to use in SQL (do not append .main)
        - database, schema, table_name: Table identifiers
        - description, row_count, match_score: Table metadata
        - columns_json: JSON string of column metadata
    """
    # Load discovery metadata (cached)
    meta = _get_cached_discovery_metadata()
    if not meta:
        return json.dumps({
            "error": "No SQL schema index found. Run: lars sql chart",
            "hint": "The discovery process charts all databases and builds a searchable index."
        })

    # Get RAG context
    cfg = get_config()
    samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    # Resolve index metadata once per cache TTL (avoids per-call table scans).
    has_chunks, rag_embedding_dim = _get_cached_rag_index_meta(meta.rag_id)
    if not has_chunks:
        return json.dumps({
            "error": f"RAG index not found in database for rag_id: {meta.rag_id}",
            "hint": "Run: lars sql chart"
        })

    use_precomputed_embedding = False
    if query_embedding is not None:
        model_matches = (query_embedding_model is None) or (query_embedding_model == meta.embed_model)
        vector_dim = int(query_embedding_dim or len(query_embedding) or 0)
        dim_matches = (
            vector_dim <= 0
            or rag_embedding_dim <= 0
            or vector_dim == int(rag_embedding_dim)
        )
        use_precomputed_embedding = model_matches and dim_matches

    # Search
    if USE_DEDICATED_SQL_DUCKDB_INDEX:
        results = search_sql_index(
            rag_id=meta.rag_id,
            embed_model=meta.embed_model,
            query=query,
            k=k,
            score_threshold=score_threshold,
            index_embedding_dim=rag_embedding_dim,
            query_embedding=query_embedding if use_precomputed_embedding else None,
            query_embedding_model=query_embedding_model if use_precomputed_embedding else None,
            query_embedding_dim=(query_embedding_dim or len(query_embedding or [])) if use_precomputed_embedding else None,
            session_id=None,
            trace_id=None,
            parent_id=None,
            cell_name="sql_rag_search",
            cascade_id=None,
        )
    else:
        rag_ctx = RagContext(
            rag_id=meta.rag_id,
            directory=samples_dir,
            embed_model=meta.embed_model,
            embedding_dim=rag_embedding_dim,
            stats={},
            session_id=None,
            cascade_id=None,
            cell_name=None,
            trace_id=None,
            parent_id=None
        )
        results = search_chunks(
            rag_ctx=rag_ctx,
            query=query,
            k=k,
            score_threshold=score_threshold,
            query_embedding=query_embedding if use_precomputed_embedding else None,
            query_embedding_dim=(query_embedding_dim or len(query_embedding or [])) if use_precomputed_embedding else None,
        )

    if not results:
        return json.dumps({
            "query": query,
            "message": "No matching tables found. Try a broader query or different keywords.",
            "rag_id": meta.rag_id,
            "databases_available": meta.databases_indexed
        })

    # Parse results - each chunk is from a table.yaml/.yml/.json file
    tables = []
    seen_tables = set()  # Deduplicate if multiple chunks from same table
    conn_types = _get_cached_connection_types()

    for result in results:
        # result['source'] is like "csv_files/bigfoot_sightings.yaml"
        full_path = os.path.join(samples_dir, result['source'])

        # If this is a _fields.yaml file, redirect to the parent table file
        if full_path.endswith("_fields.yaml"):
            full_path = full_path.replace("_fields.yaml", ".yaml")

        # Deduplicate by file path
        if full_path in seen_tables:
            continue
        seen_tables.add(full_path)

        table_meta = _load_table_meta_cached(full_path)
        if not table_meta:
            continue

        # Skip if this is a fields-only file that wasn't redirected
        if 'fields' in table_meta and 'table_name' not in table_meta:
            continue

        try:
            # Build qualified table name
            qualified_name = _build_qualified_name(table_meta)
            if not qualified_name:
                continue
            database = table_meta.get("database")
            schema = table_meta.get("schema")
            table_name = table_meta.get("table_name")
            conn_type = conn_types.get(str(database), "")
            sql_table_ref = _sql_table_ref_for_table(
                database=database,
                schema=schema,
                table_name=table_name,
                conn_type=conn_type,
            ) or qualified_name

            tables.append({
                "qualified_name": qualified_name,
                "sql_table_ref": sql_table_ref,
                "database": database,
                "schema": _normalized_schema_value(database, schema),
                "table_name": table_name,
                "row_count": table_meta['row_count'],
                "columns": table_meta.get('columns', []),
                "sample_rows": (table_meta.get('sample_rows') or [])[:5],  # First 5 samples
                "match_score": result['score']
            })
        except Exception:
            continue

    # Return one row per table for easier SQL consumption
    rows = _pivot_tables_to_rows(tables, query, source="rag")
    return json.dumps(rows, default=str)


def sql_search(
    query: str,
    k: int = 10,
    min_row_count: Optional[int] = None,
    smart: Optional[bool] = None,
    task_context: Optional[str] = None
) -> str:
    """
    Search SQL schema metadata using local DuckDB/RAG by default.

    This is the recommended search entry point for SQL schema discovery.
    It returns compact, structured table metadata for LLM and UI consumption.
    Elasticsearch hybrid search is optional and only used when explicitly enabled.

    Finds relevant tables and columns across all configured databases.
    Returns clean table metadata optimized for LLM consumption.

    Example queries:
      - "tables with user information"
      - "sales or revenue data"
      - "bigfoot sightings location data"
      - "customer country information"
      - "find tables with email addresses and login timestamps"

    The query can be verbose - both semantic meaning and keywords are used for matching.

    Args:
        query: Natural language description (can be multi-word, verbose)
        k: Number of results to return (default: 10)
        min_row_count: Optional filter for minimum table size
        smart: Enable LLM-powered smart filtering (default: from LARS_SMART_SEARCH env)
        task_context: Optional context about what user is trying to do

    Returns:
        JSON array with one row per matching table:
        - query: Search query used
        - source: "rag", "rag+smart", or optional elastic variants when enabled
        - qualified_name: Metadata identifier for sql_get_table_meta
        - sql_table_ref: Canonical relation to use in SQL (do not append .main)
        - database, schema, table_name: Table identifiers
        - description, row_count, match_score: Table metadata
        - columns_json: JSON string of column metadata
        - schema_brief (first row only, if smart=True): Compact summary for LLM consumption
    """
    from ..rag.smart_search import is_smart_search_enabled

    use_smart = smart if smart is not None else is_smart_search_enabled()
    fetch_k = k * 3 if use_smart else k

    discovery_meta = _get_cached_discovery_metadata()
    index_version = {
        "last_discovery": getattr(discovery_meta, "last_discovery", None),
        "table_count": getattr(discovery_meta, "table_count", None),
        "embed_model": getattr(discovery_meta, "embed_model", None),
        "rag_id": getattr(discovery_meta, "rag_id", None),
    }
    cache_key = _build_sql_search_cache_key(
        query=query,
        k=k,
        min_row_count=min_row_count,
        use_smart=use_smart,
        task_context=task_context,
        sql_search_use_elastic=_SQL_SEARCH_USE_ELASTIC,
        index_version=index_version,
    )
    cached_payload = _get_sql_search_cached_result(cache_key)
    if cached_payload is not None:
        return cached_payload

    tables = []
    source = "rag"
    fallback_reason = None
    query_embedding = None
    query_embedding_model = None
    query_embedding_dim = None

    # Try Elasticsearch first only when explicitly enabled; otherwise go direct Duck/RAG.
    if _SQL_SEARCH_USE_ELASTIC:
        try:
            from ..elastic import get_elastic_client, hybrid_search_sql_schemas
            from ..rag.indexer import embed_texts

            es = get_elastic_client()
            if es.ping():
                cfg = get_config()
                embed_result = embed_texts(
                    texts=[query],
                    model=cfg.default_embed_model,
                    session_id=None,
                    trace_id=None,
                    parent_id=None,
                    cell_name="sql_search",
                    cascade_id=None
                )
                query_embedding = embed_result['embeddings'][0]
                query_embedding_model = cfg.default_embed_model
                query_embedding_dim = int(embed_result.get("dim") or 0)
                tables = hybrid_search_sql_schemas(
                    query=query,
                    query_embedding=query_embedding,
                    k=fetch_k,
                    min_row_count=min_row_count
                )
                source = "elasticsearch"
            else:
                fallback_reason = "Elasticsearch ping returned false"
        except Exception as e:
            fallback_reason = str(e)

    # RAG fallback (now still supports smart filtering below)
    if not tables:
        rag_json = sql_rag_search(
            query,
            k=fetch_k,
            score_threshold=0.3,
            query_embedding=query_embedding,
            query_embedding_model=query_embedding_model,
            query_embedding_dim=query_embedding_dim,
        )
        try:
            rag_data = json.loads(rag_json)
        except Exception:
            return rag_json

        if isinstance(rag_data, dict):
            if fallback_reason:
                rag_data["fallback_reason"] = fallback_reason
            payload = json.dumps(rag_data, default=str)
            return _maybe_cache_sql_search_result(cache_key, payload)

        tables = _rows_to_tables(rag_data if isinstance(rag_data, list) else [])
        source = "rag"

    # Apply smart filtering for whichever backend produced raw tables.
    if use_smart and len(tables) > k:
        from ..rag.smart_search import smart_schema_search

        smart_result = smart_schema_search(
            query=query,
            raw_results=tables,
            k=k,
            task_context=task_context
        )

        smart_tables = smart_result.get("tables", tables[:k])
        schema_brief = smart_result.get("schema_brief")

        # Merge smart search results with original table metadata
        # Smart search returns different structure (relevance, reasoning, key_columns)
        # We need to map back to original tables and enrich with smart fields
        tables_by_name = {t.get("qualified_name"): t for t in tables}
        merged_tables = []
        for smart_table in smart_tables:
            qname = smart_table.get("qualified_name")
            original = tables_by_name.get(qname, {})
            # Start with original table metadata
            merged = {**original}
            # Add smart search enrichments
            if smart_table.get("relevance"):
                merged["relevance"] = smart_table.get("relevance")
            if smart_table.get("reasoning"):
                merged["reasoning"] = smart_table.get("reasoning")
            if smart_table.get("key_columns"):
                merged["key_columns"] = smart_table.get("key_columns")
            if smart_table.get("join_hint"):
                merged["join_hint"] = smart_table.get("join_hint")
            merged_tables.append(merged)

        # Return one row per table for easier SQL consumption
        rows = _pivot_tables_to_rows(merged_tables, query, source=f"{source}+smart", schema_brief=schema_brief)
        if rows and fallback_reason and source == "rag":
            rows[0]["fallback_reason"] = fallback_reason
        payload = json.dumps(rows, default=str)
        return _maybe_cache_sql_search_result(cache_key, payload)

    # Return one row per table for easier SQL consumption
    rows = _pivot_tables_to_rows(tables[:k], query, source=source)
    if rows and fallback_reason and source == "rag":
        rows[0]["fallback_reason"] = fallback_reason
    payload = json.dumps(rows, default=str)
    return _maybe_cache_sql_search_result(cache_key, payload)


def smart_sql_search(
    query: str,
    k: int = 5,
    task_context: Optional[str] = None
) -> str:
    """
    Smart SQL schema search with LLM-powered filtering and synthesis.

    This is the recommended search for exploration and query building.
    It fetches more results than needed, then uses LLM to:
    1. Filter out irrelevant tables (keyword matches that aren't useful)
    2. Highlight only the columns that matter
    3. Generate a compact "schema_brief" for efficient context

    The schema_brief is ideal for LLM consumption - instead of passing
    all column metadata, it provides a 2-3 sentence summary like:
    "For finding user emails, use users.email (1M rows). Join to
    user_sessions for login timestamps."

    Args:
        query: Natural language description of what to find
        k: Number of tables to return (default: 5)
        task_context: Optional context about what you're trying to do
            (e.g., "write a query to find inactive users")

    Returns:
        JSON array with one row per matching table:
        - query, source, qualified_name, database, schema, table_name
        - description, row_count, match_score, columns_json
        - schema_brief (first row only): Compact LLM-ready summary

    Example:
        smart_sql_search("user email addresses", task_context="find inactive users")
    """
    return sql_search(
        query=query,
        k=k,
        smart=True,
        task_context=task_context
    )


def sql_get_table_meta(
    qualified_name: Optional[str] = None,
    database: Optional[str] = None,
    schema: Optional[str] = None,
    table_name: Optional[str] = None,
    include_sample_rows: bool = False,
    include_value_distribution: bool = False,
    sample_row_limit: int = 5,
) -> str:
    """
    Return canonical metadata for one SQL table from the discovery samples store.

    This is a hydration tool for `sql_search`/`sql_rag_search` results:
    pass `qualified_name` from a search row to fetch full table metadata.

    Args:
        qualified_name: Preferred identifier (database.table or database.schema.table)
        database: Optional database/connection name (used when qualified_name omitted)
        schema: Optional schema name (used when qualified_name omitted)
        table_name: Table name (used when qualified_name omitted)
        include_sample_rows: Include sample rows/columns in response (default: False)
        include_value_distribution: Include column value_distribution arrays (default: False)
        sample_row_limit: Max sample rows when include_sample_rows=True (default: 5)

    Returns:
        JSON object with table metadata, including:
        - qualified_name: metadata lookup identifier
        - sql_table_ref: canonical relation name to query directly
        or error payload with hints.
    """
    parsed_db, parsed_schema, parsed_table, parse_error = _parse_qualified_name(qualified_name)
    if parse_error:
        return json.dumps({
            "error": parse_error,
            "qualified_name": qualified_name,
            "hint": "Use qualified_name from sql_search output (e.g., csv_files.bigfoot_sightings)"
        })

    database = _normalize_identifier(database) or parsed_db
    schema = _normalize_identifier(schema) or parsed_schema
    table_name = _normalize_identifier(table_name) or parsed_table

    if not table_name:
        return json.dumps({
            "error": "Missing table identifier",
            "hint": "Provide qualified_name or database+table_name (optionally schema)"
        })

    cfg = get_config()
    samples_dir = Path(cfg.root_dir) / "sql_connections" / "samples"
    if not samples_dir.exists():
        return json.dumps({
            "error": "SQL sample metadata directory not found",
            "samples_dir": str(samples_dir),
            "hint": "Run: lars sql crawl"
        })

    target_qname = None
    if qualified_name:
        target_qname = ".".join([p for p in [parsed_db, parsed_schema, parsed_table] if p])

    matches: list[tuple[Path, dict]] = []
    seen_paths: set[str] = set()

    # Fast path: probe likely paths first.
    for path in _candidate_table_meta_paths(
        samples_dir,
        database=database,
        schema=schema,
        table_name=table_name,
    ):
        if not path.exists() or not path.is_file():
            continue
        table_meta = _load_table_meta_cached(str(path))
        if not _table_meta_matches(
            table_meta or {},
            database=database,
            schema=schema,
            table_name=table_name,
        ):
            continue
        key = str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        matches.append((path, table_meta))

    # Fallback: scan samples tree for matching table metadata files.
    if not matches:
        for path in sorted(samples_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in (".yaml", ".yml", ".json"):
                continue
            lower_name = path.name.lower()
            if lower_name.endswith("_fields.yaml") or lower_name.endswith("_fields.yml") or lower_name.endswith("_fields.json"):
                continue
            if table_name and path.stem.lower() != table_name.lower():
                continue

            table_meta = _load_table_meta_cached(str(path))
            if not _table_meta_matches(
                table_meta or {},
                database=database,
                schema=schema,
                table_name=table_name,
            ):
                continue

            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            matches.append((path, table_meta))

    if not matches:
        # Recovery path: ignore provided schema if no exact match.
        # This handles common mistakes like csv_files.main.table_name.
        if schema:
            for path in sorted(samples_dir.rglob("*")):
                if not path.is_file():
                    continue
                suffix = path.suffix.lower()
                if suffix not in (".yaml", ".yml", ".json"):
                    continue
                lower_name = path.name.lower()
                if lower_name.endswith("_fields.yaml") or lower_name.endswith("_fields.yml") or lower_name.endswith("_fields.json"):
                    continue
                if table_name and path.stem.lower() != table_name.lower():
                    continue
                table_meta = _load_table_meta_cached(str(path))
                if not _table_meta_matches(
                    table_meta or {},
                    database=database,
                    schema=None,
                    table_name=table_name,
                ):
                    continue
                key = str(path)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                matches.append((path, table_meta))

    if not matches:
        return json.dumps({
            "error": "Table metadata not found",
            "qualified_name": qualified_name,
            "database": database,
            "schema": schema,
            "table_name": table_name,
            "hint": "Run `sql_search` first and pass one returned qualified_name to sql_get_table_meta"
        })

    if target_qname:
        filtered = []
        for path, table_meta in matches:
            qname = _build_qualified_name(table_meta) or ""
            if _ident_equal(qname, target_qname):
                filtered.append((path, table_meta))
        if filtered:
            matches = filtered

    if len(matches) > 1:
        candidates = []
        for path, table_meta in matches[:25]:
            qname = _build_qualified_name(table_meta)
            rel_path = path.relative_to(samples_dir).as_posix()
            candidates.append({
                "qualified_name": qname,
                "source": rel_path,
            })

        return json.dumps({
            "error": "Ambiguous table selection",
            "qualified_name": qualified_name,
            "database": database,
            "schema": schema,
            "table_name": table_name,
            "candidate_count": len(matches),
            "candidates": candidates,
            "hint": "Specify full qualified_name as database.schema.table"
        })

    match_path, raw_meta = matches[0]
    meta = copy.deepcopy(raw_meta)
    qualified = _build_qualified_name(meta)
    conn_types = _get_cached_connection_types()
    conn_type = conn_types.get(str(meta.get("database")), "")
    sql_table_ref = _sql_table_ref_for_table(
        database=meta.get("database"),
        schema=meta.get("schema"),
        table_name=meta.get("table_name"),
        conn_type=conn_type,
    ) or qualified
    sample_row_limit = max(0, int(sample_row_limit))

    if include_sample_rows:
        sample_rows = meta.get("sample_rows") or []
        meta["sample_rows"] = sample_rows[:sample_row_limit] if sample_row_limit > 0 else []
    else:
        meta.pop("sample_rows", None)
        meta.pop("sample_columns", None)

    if not include_value_distribution:
        for col in meta.get("columns", []):
            if not isinstance(col, dict):
                continue
            column_meta = col.get("metadata")
            if isinstance(column_meta, dict):
                column_meta.pop("value_distribution", None)
    else:
        dist_limit = _SQL_TABLE_META_MAX_VALUE_DISTRIBUTION
        if dist_limit > 0:
            for col in meta.get("columns", []):
                if not isinstance(col, dict):
                    continue
                column_meta = col.get("metadata")
                if not isinstance(column_meta, dict):
                    continue
                dist = column_meta.get("value_distribution")
                if isinstance(dist, list) and len(dist) > dist_limit:
                    column_meta["value_distribution"] = dist[:dist_limit]

    meta["schema"] = _normalized_schema_value(meta.get("database"), meta.get("schema"))
    meta["qualified_name"] = qualified
    meta["sql_table_ref"] = sql_table_ref
    meta["source"] = match_path.relative_to(samples_dir).as_posix()
    return json.dumps(meta, default=str)


def run_sql(sql: str, connection: Optional[str] = None, limit: Optional[int] = 200) -> str:
    """
    Execute SQL query through the pgwire-style SQL pipeline.

    Pipeline stages:
    1. Best-effort UDF registration
    2. Lazy attach of referenced configured sources
    3. LARS SQL rewrite to executable DuckDB SQL
    4. Query execution

    IMPORTANT: Use qualified table names in queries:
      - PostgreSQL/MySQL: connection_name.schema.table
      - SQLite: connection_name.table
      - CSV folders: connection_name.table_name
        (Do NOT use connection_name.main.table_name)
        Example: SELECT * FROM csv_files.bigfoot_sightings
      - DuckDB folders (research_dbs): db_name.table_name
        Example: SELECT * FROM market_research.zollege_schools
        (Each .duckdb file is attached directly as a database)

    Examples:
      - "SELECT * FROM prod_db.public.users LIMIT 10"
      - "SELECT COUNT(*) FROM csv_files.bigfoot_sightings WHERE state = 'California'"
      - "SELECT * FROM market_research.zollege_schools LIMIT 10"

    Args:
        sql: SQL query to execute
        connection: Optional connection name. If provided, validated against
            configured SQL connections.
        limit: Maximum rows to return (default: 200)

    Returns:
        JSON with query results, row count, and any errors
    """
    connections = load_sql_connections()
    if connection is not None:
        resolved_connection = _resolve_connection_name(connection, connections)
        if not resolved_connection:
            return json.dumps({
                "error": f"Connection '{connection}' not found",
                "available_connections": list(connections.keys()),
                "hint": "Check sql_connections/*.yaml files"
            })
    else:
        resolved_connection = None

    conn = None
    try:
        conn, cursor, executed_sql, _ = _execute_sql_via_pgwire_pipeline(
            sql=sql,
            connection=resolved_connection,
        )
        columns = [desc[0] for desc in (cursor.description or [])]

        if limit:
            fetched = cursor.fetchmany(max(1, int(limit)))
        else:
            fetched = cursor.fetchall()

        results = sanitize_for_json([
            {col: (row[i] if i < len(row) else None) for i, col in enumerate(columns)}
            for row in fetched
        ])
        rows = [list(row.values()) for row in results]

        return json.dumps({
            "sql": executed_sql,
            "connection": resolved_connection,
            "row_count": len(results),
            "columns": columns,
            "results": results,
            "rows": rows
        }, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "sql": sql,
            "connection": resolved_connection,
            "hint": "Check table names are qualified correctly (e.g., csv_files.bigfoot_sightings)",
            "columns": [],
            "rows": [],
            "results": [],
            "row_count": 0
        })
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def safe_sql_run(
    sql: str,
    connection: Optional[str] = None,
    row_limit: int = 15,
    text_max_chars: int = 400,
    stats_mode: str = "sample",
) -> str:
    """
    Execute SQL and return a bounded preview.

    The query is run through the pgwire-style SQL pipeline (lazy attach + rewrite)
    and the returned payload is truncated for preview safety.

    Use this for agent workflows where large outputs are expensive.

    Args:
        sql: SQL query to execute (unchanged)
        connection: Optional SQL connection name.
            If provided, validated against configured SQL connections.
        row_limit: Max rows returned to caller (default: 15)
        text_max_chars: Max chars per string cell before truncation (default: 400)
        stats_mode: "sample" (default) or "full"
            - "sample": return cardinality over preview rows only; no full row count scan
            - "full": consume full cursor to compute exact total_row_count (more expensive)

    Returns:
        JSON payload with bounded preview rows plus preview/stats metadata.
    """
    connections = load_sql_connections()
    if connection is not None:
        resolved_connection = _resolve_connection_name(connection, connections)
        if not resolved_connection:
            return json.dumps({
                "status": "error",
                "error": f"Connection '{connection}' not found",
                "error_message": f"Connection '{connection}' not found",
                "error_type": "ConnectionNotFound",
                "phase": "validate_connection",
                "connection": connection,
                "available_connections": list(connections.keys()),
                "hint": "Check sql_connections/*.yaml files",
                "action": "Use one of the available_connections values."
            })
    else:
        resolved_connection = None

    if stats_mode not in {"sample", "full"}:
        return json.dumps({
            "status": "error",
            "error": f"Invalid stats_mode '{stats_mode}'",
            "error_message": f"Invalid stats_mode '{stats_mode}'",
            "error_type": "InvalidArgument",
            "phase": "validate_arguments",
            "sql": sql,
            "connection": resolved_connection,
            "hint": "Use stats_mode='sample' or stats_mode='full'",
            "action": "Set stats_mode to 'sample' (cheap) or 'full' (exact, more expensive).",
            "columns": [],
            "rows": [],
            "results": [],
            "row_count": 0
        })

    row_limit = max(1, int(row_limit))
    text_max_chars = max(1, int(text_max_chars))

    conn = None
    try:
        conn, cursor, executed_sql, resolved_from_pipeline = _execute_sql_via_pgwire_pipeline(
            sql=sql,
            connection=resolved_connection,
        )
        resolved_connection = resolved_connection or resolved_from_pipeline
        columns = [desc[0] for desc in (cursor.description or [])]

        # Fetch one extra row to determine truncation without rewriting SQL.
        fetched = cursor.fetchmany(row_limit + 1)
        is_truncated = len(fetched) > row_limit
        preview_rows = fetched[:row_limit]

        results = []
        rows = []
        truncated_cell_count = 0

        for raw_row in preview_rows:
            row_obj = {}
            row_values = []
            for i, col in enumerate(columns):
                value = raw_row[i] if i < len(raw_row) else None
                value, was_truncated = _truncate_text(value, text_max_chars)
                if was_truncated:
                    truncated_cell_count += 1
                value = sanitize_for_json(value)
                row_obj[col] = value
                row_values.append(value)
            results.append(row_obj)
            rows.append(row_values)

        rows_returned = len(results)
        total_row_count = rows_returned if not is_truncated else None
        total_row_count_known = not is_truncated

        if stats_mode == "full":
            # Count all remaining rows from the cursor to get an exact total.
            total = len(fetched)
            while True:
                chunk = cursor.fetchmany(1000)
                if not chunk:
                    break
                total += len(chunk)
            total_row_count = total
            total_row_count_known = True

        column_cardinality = _compute_column_cardinality(results, columns)

        return json.dumps({
            "sql": executed_sql,
            "connection": resolved_connection,
            "row_count": rows_returned,
            "total_row_count": total_row_count,
            "total_row_count_known": total_row_count_known,
            "columns": columns,
            "results": results,
            "rows": rows,
            "preview": {
                "row_limit": row_limit,
                "rows_returned": rows_returned,
                "is_truncated": is_truncated,
                "text_max_chars": text_max_chars,
                "truncated_cell_count": truncated_cell_count,
            },
            "stats": {
                "mode": stats_mode,
                "column_cardinality": column_cardinality,
            },
            "note": "This is an automatic preview. The underlying query result may contain more rows/longer text.",
        }, indent=2, default=str)

    except Exception as e:
        error_message = str(e)
        return _sql_error_response(
            sql=sql,
            connection=resolved_connection,
            error_message=error_message,
            error_type=type(e).__name__,
            hint="Check SQL syntax and qualified table names (e.g., csv_files.bigfoot_sightings).",
            phase="execute",
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def limited_sql_run(
    sql: str,
    connection: Optional[str] = None,
    row_limit: int = 15,
    text_max_chars: int = 400,
    stats_mode: str = "sample",
) -> str:
    """
    Alias for safe_sql_run with the same behavior and defaults.
    """
    return safe_sql_run(
        sql=sql,
        connection=connection,
        row_limit=row_limit,
        text_max_chars=text_max_chars,
        stats_mode=stats_mode,
    )


def validate_sql(sql: str | None = None, connection: Optional[str] = None, *, content: str | None = None, **kwargs) -> str:
    """
    Validate SQL syntax and optionally check schema references.

    Uses DuckDB's EXPLAIN to parse and validate the query without executing it.
    If connection is provided, validates against that database's schema (tables exist, etc.).

    This tool is designed to be used as:
    1. A ward validator in cascades that generate SQL
    2. A loop_until validator: `loop_until: validate_sql`
    3. Direct function call: `validate_sql("SELECT * FROM users")`

    Returns the standard validator format: {"valid": bool, "reason": str}

    Args:
        sql: SQL query to validate (positional)
        connection: Optional connection name for schema validation.
                   If provided, validates that referenced tables/columns exist.
                   If omitted, auto-detects from SQL (e.g., csv_files.table → csv_files)
        content: Alternative to sql (used by loop_until validator interface)
        **kwargs: Ignored (accepts extra args from validator system)

    Returns:
        JSON with validation result: {"valid": bool, "reason": str}

    Examples:
        validate_sql("SELECT * FROM users")  # Syntax check only
        validate_sql("SELECT * FROM csv_files.data", "csv_files")  # With schema validation
        loop_until: validate_sql  # In cascade YAML
    """
    import duckdb
    import re

    # Support both direct call (sql=) and validator interface (content=)
    sql = sql or content
    if not sql:
        return json.dumps({
            "valid": False,
            "reason": "No SQL provided"
        })

    sql = sql.strip()

    # Remove markdown code blocks if LLM wrapped the SQL
    if sql.startswith("```sql"):
        sql = sql[6:]
    if sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    # Remove trailing semicolon for EXPLAIN (DuckDB doesn't like it)
    if sql.endswith(';'):
        sql = sql[:-1]

    # Basic sanity check
    if not sql:
        return json.dumps({
            "valid": False,
            "reason": "Empty SQL query"
        })

    # Check it starts with SELECT or WITH (safety)
    sql_upper = sql.upper().strip()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return json.dumps({
            "valid": False,
            "reason": f"Only SELECT/WITH queries allowed, got: {sql[:30]}..."
        })

    # Auto-detect connection from SQL if not provided (e.g., csv_files.table → csv_files)
    if not connection:
        match = re.search(r'(?:FROM|JOIN)\s+["\']?(\w+)["\']?\s*\.', sql, re.IGNORECASE)
        if match:
            detected = match.group(1)
            # Verify it's a valid connection
            connections = load_sql_connections()
            if detected in connections:
                connection = detected

    try:
        if connection:
            # Validate with schema context - attach the database
            connections = load_sql_connections()
            if connection not in connections:
                return json.dumps({
                    "valid": False,
                    "reason": f"Connection '{connection}' not found. Available: {list(connections.keys())}"
                })

            conn_config = connections[connection]
            connector = DatabaseConnector(use_cache=False)
            connector.attach(conn_config)

            # Run EXPLAIN to validate syntax + schema
            connector.conn.execute(f"EXPLAIN {sql}")
            connector.close()
        else:
            # Syntax-only validation (no schema context)
            conn = duckdb.connect(':memory:')
            conn.execute("SET threads TO 4")  # Limit CPU usage
            conn.execute(f"EXPLAIN {sql}")
            conn.close()

        return json.dumps({
            "valid": True,
            "reason": "SQL is valid"
        })

    except Exception as e:
        error_msg = str(e)

        # Categorize the error for better feedback
        if "Parser Error" in error_msg or "syntax error" in error_msg.lower():
            return json.dumps({
                "valid": False,
                "reason": f"Syntax error: {error_msg}"
            })
        elif "Catalog Error" in error_msg:
            # Table/column doesn't exist
            return json.dumps({
                "valid": False,
                "reason": f"Schema error (table/column not found): {error_msg}"
            })
        elif "Binder Error" in error_msg:
            # Column ambiguity, type mismatch, etc.
            return json.dumps({
                "valid": False,
                "reason": f"Binding error: {error_msg}"
            })
        else:
            return json.dumps({
                "valid": False,
                "reason": f"Validation failed: {error_msg}"
            })


def list_sql_connections() -> str:
    """
    List all configured SQL database connections.

    Shows which databases are available for querying and when they were last indexed.

    Returns:
        JSON with connection names, types, and last discovery info
    """
    meta = load_discovery_metadata()
    connections = load_sql_connections()

    conn_list = []
    for name, config in connections.items():
        conn_list.append({
            "name": name,
            "type": config.type,
            "enabled": config.enabled,
            "indexed": name in (meta.databases_indexed if meta else [])
        })

    return json.dumps({
        "connections": conn_list,
        "last_discovery": meta.last_discovery if meta else None,
        "rag_id": meta.rag_id if meta else None,
        "total_tables_indexed": meta.table_count if meta else 0,
        "hint": "Run 'lars sql chart' to index/re-index databases"
    }, indent=2)
