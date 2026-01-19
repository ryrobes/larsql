"""
Early Termination for Semantic SQL Queries.

Provides limit-aware early termination for queries like:
    SELECT * FROM reviews WHERE text MEANS 'damaged' LIMIT 10

Instead of processing ALL rows through the LLM, we track matches and
stop processing once we have enough. This can save 60-90% of LLM calls
for queries with small LIMITs on large tables.

Architecture:
    1. postgres_server.py detects "limit-friendly" queries before rewriting
    2. Sets limit hint in session context
    3. make_vectorized_wrapper checks hint during parallel execution
    4. Stops submitting new work when enough matches found
    5. Returns False for remaining rows (no LLM call)

Thread Safety:
    Match counting uses threading.Lock for correctness with parallel UDF execution.
    Slight over-counting is acceptable (we may process 1-2 extra batches in flight).

Future: ORDER BY support can be added by pre-sorting the source data before
semantic processing. The detection logic has affordances for this.
"""

import threading
import logging
from typing import Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class EarlyTerminationContext:
    """
    Per-query context for early termination.

    Tracks the limit hint and match count for a single query execution.
    Thread-safe for parallel UDF execution.
    """
    limit_hint: int  # Target number of matches (usually LIMIT * buffer_factor)
    match_count: int = 0
    processed_count: int = 0  # Total rows processed (cache + LLM)
    terminated: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def increment_processed(self, count: int = 1) -> int:
        """Thread-safe increment of processed count."""
        with self._lock:
            self.processed_count += count
            return self.processed_count

    def increment_matches(self, count: int = 1) -> int:
        """
        Thread-safe increment of match count.

        Returns the new total match count.
        """
        with self._lock:
            self.match_count += count
            return self.match_count

    def should_terminate(self) -> bool:
        """
        Check if we've reached the limit and should stop processing.

        Once terminated, always returns True (no un-terminating).
        """
        with self._lock:
            if self.terminated:
                return True
            if self.match_count >= self.limit_hint:
                self.terminated = True
                log.debug(f"[EarlyTermination] Terminating: {self.match_count} matches >= {self.limit_hint} limit")
                return True
            return False

    def get_stats(self) -> dict:
        """Get current stats for logging/debugging."""
        with self._lock:
            return {
                "limit_hint": self.limit_hint,
                "match_count": self.match_count,
                "processed_count": self.processed_count,
                "terminated": self.terminated,
            }


# Global registry of active early termination contexts, keyed by caller_id
_contexts: dict[str, EarlyTerminationContext] = {}
_contexts_lock = threading.Lock()


def set_early_termination_hint(caller_id: str, limit: int, buffer_factor: float = 1.5) -> None:
    """
    Set early termination hint for a query.

    Args:
        caller_id: The query's caller_id (from postgres_server session)
        limit: The LIMIT value from the query
        buffer_factor: Multiplier for safety margin (default 1.5x)
                      Allows for some in-flight work to complete

    Called by postgres_server.py before query execution for limit-friendly queries.
    """
    limit_hint = max(1, int(limit * buffer_factor))

    with _contexts_lock:
        _contexts[caller_id] = EarlyTerminationContext(limit_hint=limit_hint)

    log.debug(f"[EarlyTermination] Set hint for {caller_id}: LIMIT {limit} -> hint {limit_hint}")


def get_early_termination_context(caller_id: str) -> Optional[EarlyTerminationContext]:
    """
    Get the early termination context for a query.

    Returns None if no hint is set (query should process all rows).
    """
    if not caller_id:
        return None

    with _contexts_lock:
        return _contexts.get(caller_id)


def clear_early_termination_hint(caller_id: str) -> Optional[dict]:
    """
    Clear early termination hint after query completion.

    Returns stats dict if context existed, None otherwise.
    Called by postgres_server.py after query execution.
    """
    with _contexts_lock:
        ctx = _contexts.pop(caller_id, None)

    if ctx:
        stats = ctx.get_stats()
        # Log summary: processed X rows, found Y matches (target: Z)
        log.info(f"[EarlyTermination] processed {stats['processed_count']} rows, found {stats['match_count']} matches (target: {stats['limit_hint']}, terminated: {stats['terminated']})")
        return stats

    return None


def check_early_termination(caller_id: str) -> bool:
    """
    Quick check if early termination is active and should stop.

    Returns True if we should stop processing (have enough matches).
    Returns False if no hint set or still need more matches.
    """
    ctx = get_early_termination_context(caller_id)
    if ctx is None:
        return False
    return ctx.should_terminate()


def record_matches(caller_id: str, count: int) -> Tuple[int, bool]:
    """
    Record that we found `count` matches for this query.

    Args:
        caller_id: The query's caller_id
        count: Number of matches found in this batch

    Returns:
        Tuple of (new_total_matches, should_terminate)
    """
    ctx = get_early_termination_context(caller_id)
    if ctx is None:
        return (0, False)

    new_total = ctx.increment_matches(count)
    should_stop = ctx.should_terminate()

    return (new_total, should_stop)


def record_processed(caller_id: str, count: int) -> int:
    """
    Record that we processed `count` rows for this query.

    Args:
        caller_id: The query's caller_id
        count: Number of rows processed

    Returns:
        New total processed count
    """
    ctx = get_early_termination_context(caller_id)
    if ctx is None:
        return 0
    return ctx.increment_processed(count)


# ============================================================================
# Query Detection - Token-based detection of limit-friendly queries
# ============================================================================

def is_limit_friendly_query(tokens: list) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Detect if a query is suitable for early termination.

    A query is limit-friendly if:
    - Has LIMIT clause
    - No GROUP BY
    - No aggregate functions (COUNT, SUM, AVG, etc.)
    - No DISTINCT (for now - could be optimized later)
    - ORDER BY is absent OR on semantic columns only (future enhancement)

    Args:
        tokens: List of token objects with .typ and .text attributes
                (from semantic_rewriter_v2._tokenize)
                Token types: ws, ident, punct, string, comment_line, comment_block

    Returns:
        Tuple of (is_friendly, limit_value, reason_if_not_friendly)

    Future: Add order_by_columns to return value for pre-sort optimization.
    """
    # Track what we find
    has_limit = False
    limit_value = None
    has_group_by = False
    has_aggregate = False
    has_distinct = False
    has_order_by = False
    order_by_columns = []  # For future ORDER BY optimization

    # Aggregate function names (case-insensitive check)
    aggregates = {
        'count', 'sum', 'avg', 'min', 'max', 'array_agg', 'list', 'string_agg',
        'group_concat', 'first', 'last', 'any_value', 'stddev', 'variance',
        # Semantic aggregates
        'summarize', 'themes', 'sentiment', 'consensus', 'outliers',
    }

    def skip_ws(idx: int) -> int:
        """Skip whitespace tokens, return new index."""
        while idx < len(tokens) and tokens[idx].typ == 'ws':
            idx += 1
        return idx

    def is_numeric(text: str) -> bool:
        """Check if text represents a number."""
        try:
            int(text)
            return True
        except ValueError:
            return False

    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]

        # Skip whitespace and comments
        # Note: semantic_rewriter_v2 uses 'comment_line' and 'comment_block'
        if tok.typ in ('ws', 'comment_line', 'comment_block'):
            i += 1
            continue

        # Check for keywords and identifiers
        if tok.typ == 'ident':
            upper = tok.text.upper()

            # LIMIT clause
            if upper == 'LIMIT':
                has_limit = True
                # Look for the limit value (next non-whitespace token)
                j = skip_ws(i + 1)
                # Numbers are tokenized as 'ident' in semantic_rewriter_v2
                if j < n and tokens[j].typ == 'ident' and is_numeric(tokens[j].text):
                    try:
                        limit_value = int(tokens[j].text)
                    except ValueError:
                        pass

            # GROUP BY
            elif upper == 'GROUP':
                # Check if followed by BY
                j = skip_ws(i + 1)
                if j < n and tokens[j].typ == 'ident' and tokens[j].text.upper() == 'BY':
                    has_group_by = True

            # ORDER BY (track for future optimization)
            elif upper == 'ORDER':
                j = skip_ws(i + 1)
                if j < n and tokens[j].typ == 'ident' and tokens[j].text.upper() == 'BY':
                    has_order_by = True
                    # Future: extract order_by_columns here

            # DISTINCT
            elif upper == 'DISTINCT':
                has_distinct = True

            # Aggregate functions
            elif upper.lower() in aggregates:
                # Check if followed by ( to confirm it's a function call
                # Note: semantic_rewriter_v2 uses 'punct' for parentheses
                j = skip_ws(i + 1)
                if j < n and tokens[j].typ == 'punct' and tokens[j].text == '(':
                    has_aggregate = True

        i += 1

    # Determine if query is limit-friendly
    if not has_limit:
        return (False, None, "no LIMIT clause")

    if limit_value is None:
        return (False, None, "could not parse LIMIT value")

    if has_group_by:
        return (False, limit_value, "has GROUP BY")

    if has_aggregate:
        return (False, limit_value, "has aggregate functions")

    if has_distinct:
        return (False, limit_value, "has DISTINCT")

    # ORDER BY check - for now, disable optimization if ORDER BY present
    # Future: Allow ORDER BY if we can pre-sort the source
    if has_order_by:
        return (False, limit_value, "has ORDER BY (optimization pending)")

    return (True, limit_value, None)


def extract_limit_from_sql(sql: str) -> Optional[int]:
    """
    Quick extraction of LIMIT value from SQL string.

    Uses simple pattern matching - for cases where we don't have tokens.
    Returns None if no LIMIT found or parse error.
    """
    import re

    # Match LIMIT followed by a number
    match = re.search(r'\bLIMIT\s+(\d+)\b', sql, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    return None
