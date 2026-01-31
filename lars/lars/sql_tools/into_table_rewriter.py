"""
INTO Table Rewriter - JIT rewriting of into_ table references.

Tables created with `... INTO my_table` are persisted as parquet files in:
    $LARS_ROOT/data/user/<results_db>/into_<name>/data.parquet

This rewriter detects references to `into_*` in table positions (FROM, JOIN)
and rewrites them to read directly from parquet.

Example:
    Input:  SELECT * FROM into_sales WHERE category = 'Electronics'
    Output: SELECT * FROM read_parquet('/path/to/data/user/lars_results/into_sales/data.parquet') AS into_sales WHERE category = 'Electronics'

Token-aware: never rewrites inside strings or comments.
No views or session state needed - works across all connections.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional
import logging

log = logging.getLogger(__name__)

# Cache LARS_ROOT to avoid repeated lookups
_lars_root: Optional[Path] = None


def _get_lars_root() -> Path:
    """Get LARS_ROOT path, cached for efficiency."""
    global _lars_root
    if _lars_root is None:
        try:
            from ..lars_db import get_lars_db
            _lars_root = get_lars_db().root
        except Exception:
            # Fallback to env var or current dir
            _lars_root = Path(os.environ.get('LARS_ROOT', '.'))
    return _lars_root


def _get_parquet_path(results_db: str, table_name: str) -> Optional[Path]:
    """
    Get path to parquet file for an INTO table.
    
    Returns None if file doesn't exist.
    
    Path structure: $LARS_ROOT/data/user/{results_db}/into_{name}/data.parquet
    Note: _get_lars_root() returns $LARS_ROOT/data already
    """
    root = _get_lars_root()
    # INTO tables are stored with into_ prefix in the filename
    if not table_name.startswith('into_'):
        parquet_name = f"into_{table_name}"
    else:
        parquet_name = table_name
    
    # root is $LARS_ROOT/data, so path is: root/user/{results_db}/{table}/data.parquet
    parquet_path = root / "user" / results_db / parquet_name / "data.parquet"
    
    if parquet_path.exists():
        return parquet_path
    return None


@dataclass(frozen=True)
class _Token:
    typ: str  # ws, ident, punct, string, comment_line, comment_block, other
    text: str


def rewrite_into_tables(sql: str, results_db: str = "lars_results") -> Tuple[str, bool]:
    """
    Rewrite into_ table references to read directly from parquet files.

    This approach:
    - Reads directly from parquet (no views needed)
    - Works across sessions (no sync required)
    - Falls back gracefully if file doesn't exist

    Args:
        sql: Input SQL query
        results_db: Results database namespace (e.g., "lars_results_memory")
                    Maps to: $LARS_ROOT/data/user/{results_db}/

    Returns:
        Tuple of (rewritten_sql, changed)
    """
    try:
        tokens = _tokenize(sql)
    except Exception as e:
        log.warning(f"[into_rewriter] Tokenization failed: {e}")
        return sql, False

    out_tokens: List[_Token] = []
    changed = False
    i = 0

    # Keywords that precede table names
    TABLE_KEYWORDS = {'FROM', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'CROSS', 'FULL', 'INTO'}

    # Track if we're in a position where a table reference is expected
    prev_keyword = None

    while i < len(tokens):
        tok = tokens[i]

        # Never rewrite within strings/comments
        if tok.typ in ("string", "comment_line", "comment_block"):
            out_tokens.append(tok)
            i += 1
            continue

        # Track keywords for context
        if tok.typ == "ident":
            upper = tok.text.upper()

            # Check if this identifier follows a table-introducing keyword
            if upper in TABLE_KEYWORDS:
                prev_keyword = upper
                out_tokens.append(tok)
                i += 1
                continue

            # Check if this is an into_ table reference in a table position
            if tok.text.lower().startswith('into_') and prev_keyword in ('FROM', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'CROSS', 'FULL'):
                table_name = tok.text
                
                # Check if parquet file exists
                parquet_path = _get_parquet_path(results_db, table_name)
                
                if parquet_path:
                    # Rewrite to read_parquet() - direct file access
                    rewritten = f"read_parquet('{parquet_path}') AS {table_name}"
                    out_tokens.append(_Token("other", rewritten))
                    changed = True
                    log.debug(f"[into_rewriter] Rewrote {table_name} -> read_parquet('{parquet_path}')")
                else:
                    # File doesn't exist - leave as-is (will error with helpful message)
                    log.warning(f"[into_rewriter] INTO table not found: {table_name} (checked {results_db})")
                    out_tokens.append(tok)
                
                i += 1
                prev_keyword = None
                continue

            # Reset keyword tracking for non-table keywords
            if upper not in ('AS', 'ON', 'AND', 'OR', 'WHERE', 'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET'):
                prev_keyword = None

        # Whitespace doesn't reset keyword tracking
        if tok.typ == "ws":
            out_tokens.append(tok)
            i += 1
            continue

        # Punctuation resets keyword tracking (except comma which might have more tables)
        if tok.typ == "punct":
            if tok.text == ',':
                # Comma after table list - next identifier could be another table
                pass
            else:
                prev_keyword = None

        out_tokens.append(tok)
        i += 1

    if not changed:
        return sql, False

    sql_out = "".join(t.text for t in out_tokens)
    return sql_out, True


def list_into_tables(results_db: str = "lars_results") -> List[dict]:
    """
    List all INTO tables available in a results database.
    
    Returns list of dicts with:
        - name: Table name (e.g., 'into_shared_sales')
        - path: Full parquet path
        - size_bytes: File size
        - modified: Last modified time
    """
    root = _get_lars_root()
    # root is $LARS_ROOT/data
    results_dir = root / "user" / results_db
    
    if not results_dir.exists():
        return []
    
    tables = []
    for table_dir in results_dir.iterdir():
        if not table_dir.is_dir():
            continue
        if not table_dir.name.startswith('into_'):
            continue
            
        parquet_path = table_dir / "data.parquet"
        if not parquet_path.exists():
            continue
        
        stat = parquet_path.stat()
        tables.append({
            'name': table_dir.name,
            'path': str(parquet_path),
            'size_bytes': stat.st_size,
            'modified': stat.st_mtime,
        })
    
    return tables


def _tokenize(sql: str) -> List[_Token]:
    """
    Tokenize SQL into tokens, preserving strings and comments.

    Token types:
    - ws: whitespace
    - ident: identifier (alphanumeric + underscore)
    - punct: punctuation/operators
    - string: quoted string (single or double)
    - comment_line: -- comment
    - comment_block: /* comment */
    - other: rewritten content
    """
    tokens: List[_Token] = []
    i = 0
    n = len(sql)

    def emit(typ: str, start: int, end: int) -> None:
        if end > start:
            tokens.append(_Token(typ, sql[start:end]))

    while i < n:
        ch = sql[i]

        # Line comment
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            start = i
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            emit("comment_line", start, i)
            continue

        # Block comment
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            start = i
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            emit("comment_block", start, i)
            continue

        # Single-quoted string
        if ch == "'":
            start = i
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # escaped ''
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            emit("string", start, i)
            continue

        # Double-quoted string / identifier
        if ch == '"':
            start = i
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            emit("string", start, i)
            continue

        # Whitespace
        if ch.isspace():
            start = i
            i += 1
            while i < n and sql[i].isspace():
                i += 1
            emit("ws", start, i)
            continue

        # Identifiers
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
            emit("ident", start, i)
            continue

        # Numbers (don't want to match into_123 as number)
        if ch.isdigit():
            start = i
            i += 1
            while i < n and (sql[i].isdigit() or sql[i] == "."):
                i += 1
            emit("ident", start, i)  # treat as ident for simplicity
            continue

        # Punctuation / operators
        emit("punct", i, i + 1)
        i += 1

    return tokens
