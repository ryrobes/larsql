"""
Smart Search - LLM-powered RAG result filtering and synthesis.

This module wraps raw vector search with intelligent LLM filtering to:
1. Filter out false positives that vector similarity misses
2. Rank by actual relevance, not just cosine similarity
3. Provide reasoning for why results are relevant
4. Optionally synthesize key findings

The goal is to reduce context bloat by returning fewer, higher-quality
results that are truly relevant to the query.

Usage:
    from lars.rag.smart_search import smart_search_chunks, smart_schema_search

    # Smart RAG search
    results = smart_search_chunks(
        rag_ctx, query, k=5,
        explore_mode=True,  # Fetch more, filter harder
        synthesize=True     # Include synthesis
    )

    # Smart schema search
    results = smart_schema_search(
        query, raw_results, k=5,
        task_context="write a query to find inactive users"
    )

Configuration:
    LARS_SMART_SEARCH: Enable/disable smart search (default: true)
    LARS_SMART_SEARCH_MODEL: Model for filtering (default: gemini-2.5-flash-lite)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RagContext

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class SmartSearchConfig:
    """Configuration for smart search behavior."""
    enabled: bool = True
    model: str = "google/gemini-2.5-flash-lite"
    fetch_multiplier: int = 3  # Fetch k*3 results, filter to k
    explore_multiplier: int = 4  # In explore mode, fetch k*4
    max_raw_results: int = 30  # Cap on raw results to process
    timeout_seconds: float = 30.0
    fallback_on_error: bool = True  # Return raw results if smart search fails


def get_smart_search_config() -> SmartSearchConfig:
    """Get smart search configuration from config/environment."""
    from ..config import get_config

    cfg = get_config()
    return SmartSearchConfig(
        enabled=cfg.smart_search_enabled,
        model=cfg.smart_search_model
    )


# =============================================================================
# Smart RAG Search
# =============================================================================

def smart_search_chunks(
    rag_ctx: "RagContext",
    query: str,
    k: int = 5,
    explore_mode: bool = False,
    synthesize: bool = False,
    context_hint: Optional[str] = None,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Smart RAG search with LLM-powered filtering.

    Fetches more results than needed, then uses LLM to filter to the
    most truly relevant results with reasoning.

    Args:
        rag_ctx: RAG context with rag_id and session info
        query: Search query text
        k: Number of final results to return
        explore_mode: If True, fetch more aggressively and filter harder
        synthesize: If True, include a synthesis of findings
        context_hint: Optional hint about search context (e.g., "SQL query generation")
        score_threshold: Minimum similarity score for raw results
        doc_filter: Optional filter on document path

    Returns:
        Dict with:
        - results: List of filtered results with reasoning
        - synthesis: Optional synthesis of key findings
        - dropped_count: Number of results filtered out
        - raw_count: Number of raw results processed
        - smart_search_used: True if LLM filtering was applied
    """
    from .store import search_chunks
    from .context import RagContext

    config = get_smart_search_config()

    # Determine how many raw results to fetch
    if explore_mode:
        raw_k = min(k * config.explore_multiplier, config.max_raw_results)
    else:
        raw_k = min(k * config.fetch_multiplier, config.max_raw_results)

    # Get raw results
    raw_results = search_chunks(
        rag_ctx=rag_ctx,
        query=query,
        k=raw_k,
        score_threshold=score_threshold,
        doc_filter=doc_filter
    )

    # If smart search disabled or not enough results to filter, return raw
    if not config.enabled or len(raw_results) <= k:
        return {
            "results": raw_results[:k],
            "synthesis": None,
            "dropped_count": 0,
            "raw_count": len(raw_results),
            "smart_search_used": False
        }

    # Apply LLM filtering via cascade
    try:
        filtered = _execute_smart_rag_cascade(
            query=query,
            raw_results=raw_results,
            k=k,
            synthesize=synthesize,
            context_hint=context_hint,
            config=config
        )
        return filtered

    except Exception as e:
        logger.warning(f"Smart search filtering failed: {e}")
        if config.fallback_on_error:
            return {
                "results": raw_results[:k],
                "synthesis": None,
                "dropped_count": 0,
                "raw_count": len(raw_results),
                "smart_search_used": False,
                "error": str(e)
            }
        raise


def _execute_smart_rag_cascade(
    query: str,
    raw_results: List[Dict[str, Any]],
    k: int,
    synthesize: bool,
    context_hint: Optional[str],
    config: SmartSearchConfig
) -> Dict[str, Any]:
    """Execute the smart_rag_search cascade for filtering."""
    from ..config import get_config

    cfg = get_config()

    # Try to load and run the cascade
    cascade_path = os.path.join(
        cfg.root_dir, "cascades", "smart_search", "smart_rag_search.cascade.yaml"
    )

    # Check if cascade exists, fallback to inline LLM call if not
    if not os.path.exists(cascade_path):
        return _smart_filter_inline(
            query, raw_results, k, synthesize, context_hint, config
        )

    # Prepare input
    cascade_input = {
        "query": query,
        "results": json.dumps(raw_results, default=str),
        "k": k,
        "synthesize": synthesize,
        "context_hint": context_hint
    }

    # Run cascade
    try:
        from ..runner import LARSRunner

        runner = LARSRunner(
            config_path=cascade_path,
            session_id=f"smart_search_{hash(query) % 10000:04d}"
        )
        result = runner.run(cascade_input)

        # Extract the filter_and_rank cell output
        if result and "filter_and_rank" in result:
            filtered_output = result["filter_and_rank"]
            if isinstance(filtered_output, str):
                filtered_output = json.loads(filtered_output)

            return {
                "results": filtered_output.get("filtered_results", raw_results[:k]),
                "synthesis": filtered_output.get("synthesis"),
                "dropped_count": filtered_output.get("dropped_count", 0),
                "dropped_reasons": filtered_output.get("dropped_reasons", []),
                "raw_count": len(raw_results),
                "smart_search_used": True
            }

    except Exception as e:
        logger.warning(f"Cascade execution failed, using inline fallback: {e}")

    # Fallback to inline LLM
    return _smart_filter_inline(
        query, raw_results, k, synthesize, context_hint, config
    )


def _smart_filter_inline(
    query: str,
    raw_results: List[Dict[str, Any]],
    k: int,
    synthesize: bool,
    context_hint: Optional[str],
    config: SmartSearchConfig
) -> Dict[str, Any]:
    """
    Inline LLM filtering when cascade not available.

    This is a simpler, faster approach that doesn't require cascade infrastructure.
    """
    from ..agent import Agent

    # Format results for LLM
    results_text = json.dumps(raw_results, indent=2, default=str)

    # Build prompt
    context_line = f"CONTEXT: {context_hint}" if context_hint else ""
    synthesis_line = '3. "synthesis": Brief 1-2 sentence synthesis of key findings' if synthesize else ""

    prompt = f"""Evaluate these search results for relevance to the query.

QUERY: {query}
{context_line}

SEARCH RESULTS:
{results_text}

Return a JSON object with:
1. "filtered_results": Array of the top {k} most relevant results (keep original fields, add "relevance_score" 0-1 and "reasoning")
2. "dropped_count": Number of results you're filtering out
{synthesis_line}

Evaluation criteria:
- Does the result DIRECTLY help answer the query?
- Is the information specific and actionable?
- Would including this reduce noise or add noise to context?

Return ONLY valid JSON, no explanation."""

    try:
        agent = Agent(
            model=config.model,
            system_prompt="You are a search result evaluator. Return only valid JSON."
        )
        response = agent.run(input_message=prompt)
        content = response.get("content", "")

        # Parse JSON from response
        # Handle potential markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content.strip())

        return {
            "results": parsed.get("filtered_results", raw_results[:k]),
            "synthesis": parsed.get("synthesis"),
            "dropped_count": parsed.get("dropped_count", 0),
            "dropped_reasons": parsed.get("dropped_reasons", []),
            "raw_count": len(raw_results),
            "smart_search_used": True
        }

    except Exception as e:
        logger.error(f"Inline smart filter failed: {e}")
        # Final fallback - return raw results
        return {
            "results": raw_results[:k],
            "synthesis": None,
            "dropped_count": 0,
            "raw_count": len(raw_results),
            "smart_search_used": False,
            "error": str(e)
        }


# =============================================================================
# Smart Schema Search
# =============================================================================

def smart_schema_search(
    query: str,
    raw_results: List[Dict[str, Any]],
    k: int = 5,
    task_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Smart SQL schema search with LLM-powered filtering and synthesis.

    Takes raw schema search results (from sql_search or sql_rag_search)
    and applies intelligent filtering to:
    1. Identify truly relevant tables (not just keyword matches)
    2. Highlight the specific columns that matter
    3. Generate a compact "schema brief" for efficient LLM consumption

    Args:
        query: Natural language query describing what to find
        raw_results: List of table metadata dicts from schema search
        k: Number of tables to return
        task_context: Optional context about what the user is trying to do

    Returns:
        Dict with:
        - tables: List of relevant tables with key columns highlighted
        - schema_brief: Compact summary for LLM consumption
        - dropped_tables: Tables that were filtered out with reasons
        - smart_search_used: True if LLM filtering was applied
    """
    config = get_smart_search_config()

    # If smart search disabled or not enough results to filter, return as-is
    if not config.enabled or len(raw_results) <= k:
        return {
            "tables": raw_results[:k],
            "schema_brief": None,
            "dropped_tables": [],
            "smart_search_used": False
        }

    # Apply LLM filtering
    try:
        return _execute_smart_schema_cascade(
            query=query,
            raw_results=raw_results,
            k=k,
            task_context=task_context,
            config=config
        )
    except Exception as e:
        logger.warning(f"Smart schema search failed: {e}")
        if config.fallback_on_error:
            return {
                "tables": raw_results[:k],
                "schema_brief": None,
                "dropped_tables": [],
                "smart_search_used": False,
                "error": str(e)
            }
        raise


def _execute_smart_schema_cascade(
    query: str,
    raw_results: List[Dict[str, Any]],
    k: int,
    task_context: Optional[str],
    config: SmartSearchConfig
) -> Dict[str, Any]:
    """Execute the smart_schema_search cascade."""
    from ..agent import Agent

    # For schema search, we use inline LLM for simplicity
    # (The cascade adds overhead and schema search is already structured)

    # Truncate results to avoid context explosion
    # Keep essential fields only
    truncated_results = []
    for table in raw_results[:15]:  # Cap at 15 tables to evaluate
        truncated = {
            "qualified_name": table.get("qualified_name"),
            "table_name": table.get("table_name"),
            "row_count": table.get("row_count"),
            "match_score": table.get("match_score"),
            "columns": []
        }
        # Only include column name and type, not distributions/samples
        for col in table.get("columns", [])[:30]:  # Cap columns too
            if isinstance(col, dict):
                truncated["columns"].append({
                    "name": col.get("name"),
                    "type": col.get("type"),
                    "nullable": col.get("nullable")
                })
        truncated_results.append(truncated)

    results_text = json.dumps(truncated_results, indent=2, default=str)

    task_context_line = f"TASK CONTEXT: {task_context}" if task_context else ""

    prompt = f"""Evaluate these SQL schema search results for relevance.

USER QUERY: {query}
{task_context_line}

SCHEMA SEARCH RESULTS:
{results_text}

Return a JSON object with:
1. "relevant_tables": Array of top {k} most useful tables, each with:
   - "qualified_name": Full table name
   - "row_count": Row count
   - "relevance": "high" or "medium"
   - "reasoning": Why this table is useful (1 sentence)
   - "key_columns": Array of relevant column objects (name, type, why_useful)
   - "join_hint": Optional hint about how to join with other tables

2. "dropped_tables": Array of tables you're filtering out with reason

3. "schema_brief": 2-3 sentence summary like:
   "For finding user emails, use users.email (1M rows). Join to user_sessions
   for login timestamps. Avoid user_preferences - sparse optional settings."

Evaluation criteria:
- Does this table contain the ACTUAL DATA needed?
- Are the columns the right type for the use case?
- Is this a useful fact table or just a lookup table?
- Would this table help or add noise to a query?

Return ONLY valid JSON."""

    try:
        agent = Agent(
            model=config.model,
            system_prompt="You are a SQL schema analyst. Return only valid JSON."
        )
        response = agent.run(input_message=prompt)
        content = response.get("content", "")

        # Parse JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content.strip())

        return {
            "tables": parsed.get("relevant_tables", raw_results[:k]),
            "schema_brief": parsed.get("schema_brief"),
            "dropped_tables": parsed.get("dropped_tables", []),
            "smart_search_used": True
        }

    except Exception as e:
        logger.error(f"Smart schema filter failed: {e}")
        return {
            "tables": raw_results[:k],
            "schema_brief": None,
            "dropped_tables": [],
            "smart_search_used": False,
            "error": str(e)
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def is_smart_search_enabled() -> bool:
    """Check if smart search is enabled."""
    return get_smart_search_config().enabled


def set_smart_search_enabled(enabled: bool) -> None:
    """Enable or disable smart search via environment variable."""
    os.environ["LARS_SMART_SEARCH"] = "true" if enabled else "false"
    logger.info(f"Smart search {'enabled' if enabled else 'disabled'}")
