"""
SQL Directives Parser - Token-based parsing for special SQL prefixes.

Handles:
- BACKGROUND { sql } - Async query execution in background thread
- ANALYZE 'prompt' { sql } - Execute query + LLM analysis of results

These are SQL extensions that modify query execution behavior rather than
query semantics. They're processed BEFORE semantic operator rewriting.

Token-based parsing ensures robust handling of edge cases:
- String literals in queries
- Comments
- Multi-line formatting
- Whitespace variations
"""

import re
import logging
from typing import Optional, Tuple
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SQLDirective:
    """A parsed SQL directive (BACKGROUND or ANALYZE)."""
    directive_type: str  # "BACKGROUND" or "ANALYZE"
    inner_sql: str       # The wrapped SQL query
    prompt: Optional[str] = None  # For ANALYZE: the prompt string


def parse_sql_directives(sql: str) -> Tuple[Optional[SQLDirective], str]:
    """
    Parse SQL directives (BACKGROUND, ANALYZE) using token-aware logic.

    Returns:
        Tuple of (directive, stripped_sql)
        - directive: SQLDirective if found, None otherwise
        - stripped_sql: The original SQL if no directive, or inner SQL if directive found

    Examples:
        >>> parse_sql_directives("BACKGROUND SELECT * FROM t")
        (SQLDirective(directive_type='BACKGROUND', inner_sql='SELECT * FROM t'), 'SELECT * FROM t')

        >>> parse_sql_directives("ANALYZE 'why sales low?' SELECT * FROM sales")
        (SQLDirective(directive_type='ANALYZE', inner_sql='SELECT * FROM sales', prompt='why sales low?'), 'SELECT * FROM sales')

        >>> parse_sql_directives("SELECT * FROM t")
        (None, 'SELECT * FROM t')
    """
    sql_stripped = sql.strip()
    sql_upper = sql_stripped.upper()

    # Quick check: does it start with a directive keyword?
    # Don't require specific whitespace - token parser handles that
    has_background = sql_upper.startswith('BACKGROUND')
    has_analyze = sql_upper.startswith('ANALYZE')

    if not (has_background or has_analyze):
        return None, sql

    # Token-based parsing for robustness
    try:
        from .semantic_rewriter_v2 import _tokenize

        tokens = _tokenize(sql_stripped)

        # Find the directive keyword (first non-whitespace token)
        directive_idx = None
        directive_type = None

        for i, tok in enumerate(tokens):
            if tok.typ == 'ws':
                continue
            if tok.typ == 'ident':
                if tok.text.upper() == 'BACKGROUND':
                    directive_idx = i
                    directive_type = 'BACKGROUND'
                    break
                elif tok.text.upper() == 'ANALYZE':
                    directive_idx = i
                    directive_type = 'ANALYZE'
                    break
            break

        if not directive_type:
            return None, sql

        # Parse based on type
        if directive_type == 'BACKGROUND':
            return _parse_background(tokens, directive_idx, sql_stripped)
        elif directive_type == 'ANALYZE':
            return _parse_analyze(tokens, directive_idx, sql_stripped)

    except Exception as e:
        log.warning(f"[sql_directives] Token-based parsing failed, falling back to regex: {e}")
        # Fall back to simple regex-based parsing
        return _parse_directives_regex(sql_stripped)


def _parse_background(tokens, directive_idx: int, original_sql: str) -> Tuple[Optional[SQLDirective], str]:
    """
    Parse BACKGROUND directive.

    Syntax: BACKGROUND SELECT ...

    Returns:
        Tuple of (SQLDirective, inner_sql)
    """
    # Find start of inner SQL (skip BACKGROUND keyword and whitespace)
    inner_start_idx = directive_idx + 1

    # Skip whitespace
    while inner_start_idx < len(tokens) and tokens[inner_start_idx].typ == 'ws':
        inner_start_idx += 1

    if inner_start_idx >= len(tokens):
        log.warning("[sql_directives] BACKGROUND directive has no inner SQL")
        return None, original_sql

    # Inner SQL is everything after BACKGROUND keyword
    # Calculate character position
    char_pos = sum(len(tokens[i].text) for i in range(inner_start_idx))
    inner_sql = original_sql[char_pos:].strip()

    directive = SQLDirective(
        directive_type='BACKGROUND',
        inner_sql=inner_sql,
        prompt=None
    )

    return directive, inner_sql


def _parse_analyze(tokens, directive_idx: int, original_sql: str) -> Tuple[Optional[SQLDirective], str]:
    """
    Parse ANALYZE directive.

    Syntax: ANALYZE 'prompt here' SELECT ...
           ANALYZE "prompt here" SELECT ...

    Returns:
        Tuple of (SQLDirective, inner_sql)
    """
    # Find the prompt string (should be next non-whitespace token after ANALYZE)
    prompt_idx = directive_idx + 1

    # Skip whitespace
    while prompt_idx < len(tokens) and tokens[prompt_idx].typ == 'ws':
        prompt_idx += 1

    if prompt_idx >= len(tokens):
        log.warning("[sql_directives] ANALYZE directive missing prompt")
        return None, original_sql

    # Prompt should be a string literal
    prompt_tok = tokens[prompt_idx]
    if prompt_tok.typ != 'string':
        log.warning(f"[sql_directives] ANALYZE directive expects string prompt, got {prompt_tok.typ}: {prompt_tok.text}")
        return None, original_sql

    # Extract prompt (remove quotes)
    prompt = prompt_tok.text[1:-1]  # Strip surrounding quotes

    # Find start of inner SQL (after prompt)
    inner_start_idx = prompt_idx + 1

    # Skip whitespace
    while inner_start_idx < len(tokens) and tokens[inner_start_idx].typ == 'ws':
        inner_start_idx += 1

    if inner_start_idx >= len(tokens):
        log.warning("[sql_directives] ANALYZE directive has no inner SQL after prompt")
        return None, original_sql

    # Inner SQL is everything after the prompt
    char_pos = sum(len(tokens[i].text) for i in range(inner_start_idx))
    inner_sql = original_sql[char_pos:].strip()

    directive = SQLDirective(
        directive_type='ANALYZE',
        inner_sql=inner_sql,
        prompt=prompt
    )

    return directive, inner_sql


def _parse_directives_regex(sql: str) -> Tuple[Optional[SQLDirective], str]:
    """
    Fallback regex-based parsing for directives.

    Used if token-based parsing fails.
    """
    sql_stripped = sql.strip()
    sql_upper = sql_stripped.upper()

    # Try BACKGROUND
    if sql_upper.startswith('BACKGROUND '):
        inner_sql = sql_stripped[11:].strip()  # Skip "BACKGROUND "
        directive = SQLDirective(
            directive_type='BACKGROUND',
            inner_sql=inner_sql,
            prompt=None
        )
        return directive, inner_sql

    # Try ANALYZE
    if sql_upper.startswith('ANALYZE '):
        # Parse: ANALYZE 'prompt' SQL
        match = re.match(r"""^ANALYZE\s+(['"])(.*?)\1\s+(.+)$""", sql_stripped, re.IGNORECASE | re.DOTALL)
        if match:
            prompt = match.group(2)
            inner_sql = match.group(3).strip()
            directive = SQLDirective(
                directive_type='ANALYZE',
                inner_sql=inner_sql,
                prompt=prompt
            )
            return directive, inner_sql
        else:
            log.warning("[sql_directives] Failed to parse ANALYZE directive (regex)")
            return None, sql

    return None, sql


def strip_directive(sql: str) -> Tuple[str, Optional[SQLDirective]]:
    """
    Remove directive prefix and return clean SQL + directive info.

    This is the main entry point for integrating with the rewriter pipeline.

    Args:
        sql: Raw SQL query (may have directive prefix)

    Returns:
        Tuple of (clean_sql, directive)
        - clean_sql: SQL with directive removed (ready for rewriting)
        - directive: SQLDirective if found, None otherwise

    Example:
        >>> clean_sql, directive = strip_directive("BACKGROUND SELECT * FROM t")
        >>> clean_sql
        'SELECT * FROM t'
        >>> directive.directive_type
        'BACKGROUND'
    """
    directive, stripped_sql = parse_sql_directives(sql)
    return stripped_sql, directive


# ============================================================================
# Example Usage & Testing
# ============================================================================

if __name__ == "__main__":
    test_cases = [
        "BACKGROUND SELECT * FROM products",
        "ANALYZE 'why were sales low?' SELECT * FROM sales WHERE month = 'Dec'",
        "ANALYZE \"what are the trends?\" SELECT year, SUM(revenue) FROM sales GROUP BY year",
        "SELECT * FROM users",  # No directive
        "  BACKGROUND   SELECT COUNT(*) FROM large_table  ",  # Extra whitespace
    ]

    for sql in test_cases:
        print(f"\nInput:  {sql!r}")
        directive, inner = parse_sql_directives(sql)
        if directive:
            print(f"  Directive: {directive.directive_type}")
            if directive.prompt:
                print(f"  Prompt: {directive.prompt!r}")
            print(f"  Inner SQL: {inner!r}")
        else:
            print(f"  No directive")
