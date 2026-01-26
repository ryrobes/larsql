"""
INTO Table Rewriter - JIT rewriting of into_ table references.

Tables created with `THEN PASS INTO xxx` are stored in ClickHouse as `lars_results.into_xxx`.
This rewriter detects references to `into_xxx` in table positions (FROM, JOIN) and rewrites
them to read from ClickHouse via clickhouse_scan_1().

Example:
    Input:  SELECT * FROM into_sales WHERE category = 'Electronics'
    Output: SELECT * FROM read_json_auto(clickhouse_scan_1('lars_results.into_sales')) AS into_sales WHERE category = 'Electronics'

Token-aware: never rewrites inside strings or comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import logging

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Token:
    typ: str  # ws, ident, punct, string, comment_line, comment_block
    text: str


def rewrite_into_tables(sql: str) -> Tuple[str, bool]:
    """
    Rewrite into_ table references to read from ClickHouse.

    Args:
        sql: Input SQL query

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
    # We look for: FROM <table>, JOIN <table>, etc.
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
                # Rewrite: into_xxx -> read_json_auto(clickhouse_scan_1('lars_results.into_xxx')) AS into_xxx
                table_name = tok.text
                ch_table = f"lars_results.{table_name}"
                rewritten = f"read_json_auto(clickhouse_scan_1('{ch_table}')) AS {table_name}"
                out_tokens.append(_Token("other", rewritten))
                changed = True
                log.debug(f"[into_rewriter] Rewrote {table_name} -> clickhouse_scan_1('{ch_table}')")
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
