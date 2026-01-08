"""
SQL Directives Parser - Token-based parsing for special SQL prefixes.

Handles:
- BACKGROUND { sql } - Async query execution in background thread
- ANALYZE 'prompt' { sql } - Execute query + LLM analysis of results
- CREATE WATCH name ... - Create reactive SQL subscription
- SHOW WATCHES - List all watches
- DROP WATCH name - Delete a watch
- TRIGGER WATCH name - Force immediate evaluation
- ALTER WATCH name SET ... - Modify watch settings
- DESCRIBE WATCH name - Show watch details

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


@dataclass
class WatchDirective:
    """A parsed WATCH SQL command."""
    command: str  # CREATE, DROP, SHOW, DESCRIBE, TRIGGER, ALTER

    # For CREATE WATCH
    name: Optional[str] = None
    query: Optional[str] = None
    action_type: Optional[str] = None  # 'cascade', 'signal', 'sql'
    action_spec: Optional[str] = None
    poll_interval: Optional[str] = None
    description: Optional[str] = None

    # For ALTER WATCH
    set_field: Optional[str] = None
    set_value: Optional[str] = None


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
# WATCH Command Parsing
# ============================================================================

def is_watch_command(sql: str) -> bool:
    """
    Quick check if SQL is a WATCH-related command.

    Returns True for:
    - CREATE WATCH ...
    - DROP WATCH ...
    - SHOW WATCHES
    - DESCRIBE WATCH ...
    - TRIGGER WATCH ...
    - ALTER WATCH ...
    """
    sql_upper = sql.strip().upper()

    # Check for various WATCH command patterns
    if sql_upper.startswith('CREATE WATCH') or sql_upper.startswith('CREATE  WATCH'):
        return True
    if sql_upper.startswith('DROP WATCH') or sql_upper.startswith('DROP  WATCH'):
        return True
    if sql_upper.startswith('SHOW WATCH') or sql_upper == 'SHOW WATCHES':
        return True
    if sql_upper.startswith('DESCRIBE WATCH') or sql_upper.startswith('DESC WATCH'):
        return True
    if sql_upper.startswith('TRIGGER WATCH'):
        return True
    if sql_upper.startswith('ALTER WATCH'):
        return True

    return False


def parse_watch_command(sql: str) -> Optional[WatchDirective]:
    """
    Parse a WATCH SQL command using token-based parsing.

    Syntax:
        CREATE WATCH name
        [POLL EVERY 'interval']
        AS select_query
        [HAVING condition]
        ON TRIGGER {CASCADE 'path' | SIGNAL 'name' | SQL 'statement'};

        DROP WATCH name;

        SHOW WATCHES;

        DESCRIBE WATCH name;

        TRIGGER WATCH name;

        ALTER WATCH name SET {enabled = true|false | POLL EVERY 'interval'};

    Returns:
        WatchDirective if parsed successfully, None otherwise
    """
    sql_stripped = sql.strip()
    if sql_stripped.endswith(';'):
        sql_stripped = sql_stripped[:-1].strip()

    try:
        from .semantic_rewriter_v2 import _tokenize
        tokens = _tokenize(sql_stripped)

        # Find first meaningful tokens
        meaningful_tokens = [t for t in tokens if t.typ != 'ws']

        if len(meaningful_tokens) < 2:
            return None

        first_token = meaningful_tokens[0].text.upper()
        second_token = meaningful_tokens[1].text.upper()

        # Route to specific parser
        if first_token == 'CREATE' and second_token == 'WATCH':
            return _parse_create_watch(tokens, sql_stripped)
        elif first_token == 'DROP' and second_token == 'WATCH':
            return _parse_drop_watch(tokens)
        elif first_token == 'SHOW' and (second_token == 'WATCHES' or second_token == 'WATCH'):
            return WatchDirective(command='SHOW')
        elif first_token in ('DESCRIBE', 'DESC') and second_token == 'WATCH':
            return _parse_describe_watch(tokens)
        elif first_token == 'TRIGGER' and second_token == 'WATCH':
            return _parse_trigger_watch(tokens)
        elif first_token == 'ALTER' and second_token == 'WATCH':
            return _parse_alter_watch(tokens)

        return None

    except Exception as e:
        log.warning(f"[sql_directives] WATCH parsing failed: {e}")
        return None


def _parse_create_watch(tokens, original_sql: str) -> Optional[WatchDirective]:
    """
    Parse CREATE WATCH statement.

    Syntax:
        CREATE WATCH name
        [POLL EVERY 'interval']
        AS select_query
        ON TRIGGER {CASCADE 'path' | SIGNAL 'name' | SQL 'statement'}
    """
    meaningful = [t for t in tokens if t.typ != 'ws']

    # Basic validation: CREATE WATCH name ...
    if len(meaningful) < 3:
        log.warning("[sql_directives] CREATE WATCH requires a name")
        return None

    # Token 0: CREATE, Token 1: WATCH, Token 2: name
    watch_name = meaningful[2].text

    directive = WatchDirective(
        command='CREATE',
        name=watch_name,
        poll_interval='5m',  # Default
    )

    # Find key positions in token stream
    token_texts_upper = [t.text.upper() for t in meaningful]

    # Find POLL EVERY 'interval'
    poll_every_idx = _find_token_sequence(token_texts_upper, ['POLL', 'EVERY'])
    if poll_every_idx is not None:
        # Next token should be string literal with interval
        interval_idx = poll_every_idx + 2
        if interval_idx < len(meaningful) and meaningful[interval_idx].typ == 'string':
            directive.poll_interval = meaningful[interval_idx].text[1:-1]  # Strip quotes

    # Find AS keyword (start of query)
    as_idx = _find_token_index(token_texts_upper, 'AS', start=3)
    if as_idx is None:
        log.warning("[sql_directives] CREATE WATCH requires AS clause")
        return None

    # Find ON TRIGGER
    on_trigger_idx = _find_token_sequence(token_texts_upper, ['ON', 'TRIGGER'])
    if on_trigger_idx is None:
        log.warning("[sql_directives] CREATE WATCH requires ON TRIGGER clause")
        return None

    # Extract query (between AS and ON TRIGGER)
    # Need to reconstruct from original SQL using token positions
    as_token = meaningful[as_idx]
    on_token = meaningful[on_trigger_idx]

    # Find character positions
    as_char_pos = _token_char_position(tokens, as_token)
    on_char_pos = _token_char_position(tokens, on_token)

    # Query is between AS and ON
    query_start = as_char_pos + len('AS')
    query = original_sql[query_start:on_char_pos].strip()

    directive.query = query

    # Parse action: CASCADE 'path' | SIGNAL 'name' | SQL 'statement'
    action_start_idx = on_trigger_idx + 2  # After ON TRIGGER
    if action_start_idx < len(meaningful):
        action_token = meaningful[action_start_idx].text.upper()

        if action_token == 'CASCADE':
            directive.action_type = 'cascade'
            if action_start_idx + 1 < len(meaningful) and meaningful[action_start_idx + 1].typ == 'string':
                directive.action_spec = meaningful[action_start_idx + 1].text[1:-1]

        elif action_token == 'SIGNAL':
            directive.action_type = 'signal'
            if action_start_idx + 1 < len(meaningful) and meaningful[action_start_idx + 1].typ == 'string':
                directive.action_spec = meaningful[action_start_idx + 1].text[1:-1]

        elif action_token == 'SQL':
            directive.action_type = 'sql'
            if action_start_idx + 1 < len(meaningful) and meaningful[action_start_idx + 1].typ == 'string':
                directive.action_spec = meaningful[action_start_idx + 1].text[1:-1]

    if not directive.action_type or not directive.action_spec:
        log.warning("[sql_directives] CREATE WATCH requires valid action (CASCADE/SIGNAL/SQL 'spec')")
        return None

    return directive


def _parse_drop_watch(tokens) -> Optional[WatchDirective]:
    """Parse DROP WATCH name."""
    meaningful = [t for t in tokens if t.typ != 'ws']

    if len(meaningful) < 3:
        log.warning("[sql_directives] DROP WATCH requires a name")
        return None

    # Token 0: DROP, Token 1: WATCH, Token 2: name
    watch_name = meaningful[2].text

    return WatchDirective(command='DROP', name=watch_name)


def _parse_describe_watch(tokens) -> Optional[WatchDirective]:
    """Parse DESCRIBE WATCH name."""
    meaningful = [t for t in tokens if t.typ != 'ws']

    if len(meaningful) < 3:
        log.warning("[sql_directives] DESCRIBE WATCH requires a name")
        return None

    # Token 0: DESCRIBE/DESC, Token 1: WATCH, Token 2: name
    watch_name = meaningful[2].text

    return WatchDirective(command='DESCRIBE', name=watch_name)


def _parse_trigger_watch(tokens) -> Optional[WatchDirective]:
    """Parse TRIGGER WATCH name."""
    meaningful = [t for t in tokens if t.typ != 'ws']

    if len(meaningful) < 3:
        log.warning("[sql_directives] TRIGGER WATCH requires a name")
        return None

    # Token 0: TRIGGER, Token 1: WATCH, Token 2: name
    watch_name = meaningful[2].text

    return WatchDirective(command='TRIGGER', name=watch_name)


def _parse_alter_watch(tokens) -> Optional[WatchDirective]:
    """
    Parse ALTER WATCH name SET ...

    Supported:
        ALTER WATCH name SET enabled = true|false
        ALTER WATCH name SET POLL EVERY 'interval'
    """
    meaningful = [t for t in tokens if t.typ != 'ws']

    if len(meaningful) < 5:
        log.warning("[sql_directives] ALTER WATCH requires name and SET clause")
        return None

    # Token 0: ALTER, Token 1: WATCH, Token 2: name, Token 3: SET
    watch_name = meaningful[2].text
    token_texts_upper = [t.text.upper() for t in meaningful]

    if meaningful[3].text.upper() != 'SET':
        log.warning("[sql_directives] ALTER WATCH requires SET clause")
        return None

    directive = WatchDirective(command='ALTER', name=watch_name)

    # Parse what's being set
    if len(meaningful) >= 7 and token_texts_upper[4] == 'POLL' and token_texts_upper[5] == 'EVERY':
        # ALTER WATCH name SET POLL EVERY 'interval'
        directive.set_field = 'poll_interval'
        if meaningful[6].typ == 'string':
            directive.set_value = meaningful[6].text[1:-1]

    elif len(meaningful) >= 7 and token_texts_upper[4] == 'ENABLED':
        # ALTER WATCH name SET enabled = true|false
        directive.set_field = 'enabled'
        if meaningful[5].text == '=':
            directive.set_value = meaningful[6].text.lower()

    return directive


def _find_token_index(tokens_upper: list, target: str, start: int = 0) -> Optional[int]:
    """Find index of a token (case-insensitive)."""
    for i in range(start, len(tokens_upper)):
        if tokens_upper[i] == target:
            return i
    return None


def _find_token_sequence(tokens_upper: list, sequence: list, start: int = 0) -> Optional[int]:
    """Find starting index of a token sequence."""
    seq_len = len(sequence)
    for i in range(start, len(tokens_upper) - seq_len + 1):
        if tokens_upper[i:i + seq_len] == sequence:
            return i
    return None


def _token_char_position(all_tokens: list, target_token) -> int:
    """Find character position of a token in original string."""
    pos = 0
    for tok in all_tokens:
        if tok is target_token:
            return pos
        pos += len(tok.text)
    return pos


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
