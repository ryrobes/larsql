"""
Shared SQL helpers for creating the unified_logs view.

This keeps unified_logs merge semantics consistent across:
- LarsDB internal view registration
- attach_system_views() for external DuckDB connections
- Studio shadow read store
"""

from __future__ import annotations

from typing import List, Optional, Tuple


def unified_logs_view_strategies(
    *,
    include_parent_cast_fallback: bool = True,
) -> List[Tuple[str, str]]:
    """
    Return ordered SQL strategies for creating unified_logs.

    Strategy order matters:
    1. Join unified_logs_base + costs (preferred: shows async cost updates)
    2. Base-only with parent_session_id cast (compat fallback)
    3. Simple alias to unified_logs_base (last resort)
    """
    strategies: List[Tuple[str, str]] = [
        (
            "costs_join",
            """
            CREATE OR REPLACE VIEW unified_logs AS
            SELECT
                ul.* EXCLUDE (cost, tokens_in, tokens_out, tokens_reasoning, parent_session_id),
                COALESCE(c.cost, ul.cost) AS cost,
                COALESCE(c.tokens_in, ul.tokens_in) AS tokens_in,
                COALESCE(c.tokens_out, ul.tokens_out) AS tokens_out,
                COALESCE(c.tokens_reasoning, ul.tokens_reasoning) AS tokens_reasoning,
                CAST(ul.parent_session_id AS VARCHAR) AS parent_session_id
            FROM unified_logs_base ul
            LEFT JOIN costs c ON ul.trace_id = c.trace_id
            """,
        )
    ]

    if include_parent_cast_fallback:
        strategies.append(
            (
                "base_with_parent_cast",
                """
                CREATE OR REPLACE VIEW unified_logs AS
                SELECT *, CAST(parent_session_id AS VARCHAR) AS parent_session_id
                FROM (SELECT * EXCLUDE (parent_session_id) FROM unified_logs_base)
                """,
            )
        )

    strategies.append(
        ("simple_alias", "CREATE OR REPLACE VIEW unified_logs AS SELECT * FROM unified_logs_base")
    )
    return strategies


def create_unified_logs_view(
    conn,
    *,
    include_parent_cast_fallback: bool = True,
) -> Optional[str]:
    """
    Try creating unified_logs with progressively simpler strategies.

    Returns:
        Strategy name used on success, or None if all strategies fail.
    """
    for strategy, sql in unified_logs_view_strategies(
        include_parent_cast_fallback=include_parent_cast_fallback
    ):
        try:
            conn.execute(sql)
            return strategy
        except Exception:
            continue
    return None
