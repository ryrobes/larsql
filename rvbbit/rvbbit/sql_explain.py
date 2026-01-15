"""
EXPLAIN for Semantic SQL - Query planning and cost estimation.

Provides comprehensive cost estimates and execution plan details for:
- RVBBIT MAP/RUN statements
- Semantic SQL queries with UDF calls (semantic_clean_year, CONDENSE, etc.)
- Semantic operators (MEANS, ABOUT, ~, etc.)

Key features:
- Executes DISTINCT queries to get actual unique value counts
- Queries historical cost data from ClickHouse (unified_logs, cascade_template_vectors)
- Checks cache hit rates from semantic_sql_cache
- Provides optimization hints (prewarm suggestions, parallel annotations)
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
import re
import os
import json
import logging
import time

log = logging.getLogger(__name__)


# ============================================================================
# Model & Pricing Helpers
# ============================================================================

# Cache for model pricing (avoid repeated DB queries)
_model_pricing_cache: Dict[str, Dict[str, float]] = {}


def _get_default_model() -> str:
    """Get the system default model from config."""
    try:
        from rvbbit.config import get_config
        return get_config().default_model
    except Exception:
        return "x-ai/grok-4.1-fast"  # Hardcoded fallback


def _get_model_pricing(model_id: str) -> Dict[str, float]:
    """
    Get pricing for a model from the openrouter_models table.

    Returns dict with 'prompt_price' and 'completion_price' (per token).
    Falls back to estimates if model not found.
    """
    global _model_pricing_cache

    if model_id in _model_pricing_cache:
        return _model_pricing_cache[model_id]

    # Default fallback pricing (conservative estimates)
    fallback = {'prompt_price': 0.000002, 'completion_price': 0.000008}

    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        query = """
            SELECT prompt_price, completion_price
            FROM openrouter_models
            WHERE model_id = %(model_id)s
            LIMIT 1
        """
        rows = db.query(query, {'model_id': model_id})

        if rows and len(rows) > 0:
            row = rows[0]
            if isinstance(row, dict):
                pricing = {
                    'prompt_price': float(row.get('prompt_price', 0) or 0),
                    'completion_price': float(row.get('completion_price', 0) or 0),
                }
                # Only use if we got valid prices
                if pricing['prompt_price'] > 0 or pricing['completion_price'] > 0:
                    _model_pricing_cache[model_id] = pricing
                    return pricing

    except Exception as e:
        log.debug(f"[explain] Could not get pricing for {model_id}: {e}")

    _model_pricing_cache[model_id] = fallback
    return fallback


def _get_model_for_cascade(cascade_id: str) -> str:
    """
    Get the model used by a cascade.

    Looks up cascade in registry and extracts model from cell definitions.
    Falls back to system default if not specified.
    """
    try:
        from rvbbit.semantic_sql.registry import get_sql_function
        entry = get_sql_function(cascade_id)

        if entry:
            # Extract model from cells in cascade config
            cells = entry.config.get('cells', [])
            for cell in cells:
                if isinstance(cell, dict) and cell.get('model'):
                    return cell['model']

            # Check for top-level model override
            if entry.config.get('model'):
                return entry.config['model']

    except Exception as e:
        log.debug(f"[explain] Could not get model for cascade {cascade_id}: {e}")

    return _get_default_model()


def _estimate_cost_from_pricing(
    pricing: Dict[str, float],
    prompt_tokens: int,
    completion_tokens: int
) -> float:
    """Calculate cost from pricing and token counts."""
    return (prompt_tokens * pricing['prompt_price'] +
            completion_tokens * pricing['completion_price'])


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SemanticOperation:
    """A single scalar semantic operation detected in the query."""
    function: str               # e.g., 'semantic_clean_year', 'semantic_condense'
    cascade_path: str           # Path to backing cascade
    model: str                  # LLM model used
    cells: List[str]            # Cell names in cascade
    takes: int             # Take factor (default 1)
    arg_expression: str         # SQL expression passed to function
    distinct_query: str         # Query to get distinct values
    distinct_count: int         # Actual count of distinct values
    cache_hits: int             # Cached results found
    cache_total: int            # Total cacheable entries checked
    cache_hit_rate: float       # cache_hits / distinct_count
    historical_cost_per_call: float  # From unified_logs
    historical_cost_stddev: float    # Cost standard deviation
    historical_runs: int        # Number of historical runs
    estimated_llm_calls: int    # distinct_count * (1 - cache_hit_rate)
    estimated_cost: float       # estimated_llm_calls * cost_per_call
    prewarm_eligible: bool      # Whether prewarm would help
    prewarm_reason: str         # Why/why not eligible


@dataclass
class AggregateOperation:
    """An LLM aggregate operation detected in the query (e.g., SUMMARIZE, TOPICS)."""
    function: str               # e.g., 'SUMMARIZE', 'TOPICS', 'SENTIMENT_AGG'
    canonical_name: str         # e.g., 'LLM_SUMMARIZE', 'LLM_THEMES'
    impl_function: str          # e.g., 'llm_summarize_impl', 'llm_themes_impl'
    column_expression: str      # The column being aggregated
    extra_args: List[str]       # Additional arguments (e.g., num_topics)
    estimated_groups: int       # Number of groups (= number of LLM calls)
    avg_group_size: int         # Average rows per group
    total_rows: int             # Total rows being aggregated
    historical_cost_per_call: float  # From unified_logs
    historical_cost_stddev: float
    historical_runs: int
    estimated_cost: float       # estimated_groups * cost_per_call
    model: str                  # Model used (from impl function)


@dataclass
class HistoricalQueryStats:
    """Statistics from similar historical queries."""
    fingerprint: str
    match_count: int
    avg_cost: float
    stddev_cost: float
    avg_duration_ms: float
    avg_cache_hit_rate: float
    last_run: Optional[str]


@dataclass
class ExplainResult:
    """Result of EXPLAIN analysis."""
    # Query metadata
    query_type: str             # 'semantic_query', 'rvbbit_map', 'rvbbit_run'
    fingerprint: str            # Query fingerprint hash

    # For RVBBIT MAP/RUN
    input_rows: Optional[int] = None
    parallelism: Optional[int] = None
    cascade_path: Optional[str] = None
    cells: List[str] = field(default_factory=list)
    model: str = ""
    takes: int = 1
    rewritten_sql: str = ""

    # Semantic operations (for any query type)
    operations: List[SemanticOperation] = field(default_factory=list)

    # LLM aggregate operations (SUMMARIZE, TOPICS, SENTIMENT_AGG, etc.)
    aggregates: List[AggregateOperation] = field(default_factory=list)

    # Cost summary
    total_estimated_cost: float = 0.0
    total_estimated_llm_calls: int = 0
    estimated_duration_seconds: float = 0.0

    # Historical comparison
    historical: Optional[HistoricalQueryStats] = None

    # Optimization hints
    optimization_hints: List[str] = field(default_factory=list)

    # Analysis metadata
    analysis_duration_ms: float = 0.0


# ============================================================================
# Main Entry Points
# ============================================================================

def explain_semantic_query(
    query: str,
    duckdb_conn,
    execute_distinct: bool = True
) -> ExplainResult:
    """
    Analyze any semantic SQL query and estimate cost.

    This is the main entry point for EXPLAIN on semantic queries.
    Handles both RVBBIT MAP/RUN and inline semantic UDF calls.

    Args:
        query: SQL query string
        duckdb_conn: DuckDB connection for executing distinct queries
        execute_distinct: If True, run DISTINCT queries for accurate counts

    Returns:
        ExplainResult with comprehensive cost analysis
    """
    start_time = time.time()

    # Get query fingerprint and classification
    from rvbbit.sql_trail import fingerprint_query
    fingerprint, template, udf_types = fingerprint_query(query)

    # Determine query type
    try:
        from rvbbit.sql_trail import _determine_query_type
        query_type = _determine_query_type(udf_types, query)
    except ImportError:
        # Fallback if internal function not available
        if any('semantic' in udf.lower() for udf in udf_types):
            query_type = 'semantic_query'
        elif any('rvbbit' in udf.lower() for udf in udf_types):
            query_type = 'rvbbit_query'
        else:
            query_type = 'sql_query'

    result = ExplainResult(
        query_type=query_type,
        fingerprint=fingerprint,
    )

    # Analyze for prewarm opportunities (scalar semantic function calls)
    from rvbbit.sql_tools.prewarm_analyzer import analyze_query_for_prewarm
    prewarm_specs = analyze_query_for_prewarm(query)

    # Analyze each scalar semantic operation
    for spec in prewarm_specs:
        operation = _analyze_semantic_operation(
            spec=spec,
            duckdb_conn=duckdb_conn,
            execute_distinct=execute_distinct
        )
        result.operations.append(operation)

    # Analyze LLM aggregate functions (SUMMARIZE, TOPICS, SENTIMENT_AGG, etc.)
    aggregate_specs = _detect_llm_aggregates(query)
    for agg_spec in aggregate_specs:
        agg_operation = _analyze_aggregate_operation(
            spec=agg_spec,
            query=query,
            duckdb_conn=duckdb_conn,
        )
        result.aggregates.append(agg_operation)

    # Sum up totals from both scalar operations and aggregates
    scalar_cost = sum(op.estimated_cost for op in result.operations)
    scalar_calls = sum(op.estimated_llm_calls for op in result.operations)
    agg_cost = sum(agg.estimated_cost for agg in result.aggregates)
    agg_calls = sum(agg.estimated_groups for agg in result.aggregates)

    result.total_estimated_cost = scalar_cost + agg_cost
    result.total_estimated_llm_calls = scalar_calls + agg_calls

    # Estimate duration (rough: 0.5-2s per LLM call depending on model)
    if result.total_estimated_llm_calls > 0:
        avg_latency_per_call = 1.0  # seconds, conservative estimate
        result.estimated_duration_seconds = result.total_estimated_llm_calls * avg_latency_per_call

    # Get historical stats for similar queries
    result.historical = _get_historical_query_stats(fingerprint)

    # Generate optimization hints
    result.optimization_hints = _generate_optimization_hints(result)

    result.analysis_duration_ms = (time.time() - start_time) * 1000

    return result


def explain_rvbbit_map(
    stmt,
    duckdb_conn,
    check_cache: bool = True
) -> ExplainResult:
    """
    Analyze RVBBIT MAP query and estimate cost.

    This is called from sql_rewriter.py for EXPLAIN RVBBIT MAP queries.

    Args:
        stmt: Parsed RVBBITStatement
        duckdb_conn: DuckDB connection for row count estimation
        check_cache: Whether to estimate cache hit rate

    Returns:
        ExplainResult with cost estimation and plan details
    """
    start_time = time.time()

    # Get query fingerprint
    from rvbbit.sql_trail import fingerprint_query
    full_query = f"RVBBIT MAP '{stmt.cascade_path}' USING ({stmt.using_query})"
    fingerprint, _, udf_types = fingerprint_query(full_query)

    result = ExplainResult(
        query_type='rvbbit_map',
        fingerprint=fingerprint,
        cascade_path=stmt.cascade_path,
        parallelism=stmt.parallel,
    )

    # 1. Estimate input rows from USING query
    try:
        count_query = f"SELECT COUNT(*) FROM ({stmt.using_query}) AS t"
        result.input_rows = duckdb_conn.execute(count_query).fetchone()[0]
    except Exception as e:
        log.warning(f"[explain] Could not count input rows: {e}")
        limit_match = re.search(r'LIMIT\s+(\d+)', stmt.using_query, re.IGNORECASE)
        result.input_rows = int(limit_match.group(1)) if limit_match else 1000

    # 2. Load cascade config
    cascade_info = _load_cascade_info(stmt.cascade_path)
    result.cells = cascade_info['cells']
    result.model = cascade_info['model']
    result.takes = cascade_info['takes']

    # 3. Get historical cost for this cascade
    historical_cascade = _get_historical_cascade_stats(cascade_info.get('cascade_id', stmt.cascade_path))

    # 4. Estimate cost per row
    if historical_cascade and historical_cascade.get('avg_cost', 0) > 0:
        cost_per_row = historical_cascade['avg_cost']
    else:
        cost_per_row = _estimate_cost_per_row(
            result.model,
            result.cells,
            result.takes
        )

    # 5. Estimate cache hit rate
    cache_hit_rate = 0.0
    if check_cache:
        cache_hit_rate = _estimate_map_cache_hit_rate(
            stmt.cascade_path,
            stmt.using_query,
            duckdb_conn
        )

    # 6. Calculate totals
    actual_llm_calls = int(result.input_rows * (1 - cache_hit_rate))
    result.total_estimated_llm_calls = actual_llm_calls
    result.total_estimated_cost = cost_per_row * actual_llm_calls
    result.estimated_duration_seconds = actual_llm_calls * 1.0  # 1s avg per call

    # 7. Create a synthetic operation for the MAP
    operation = SemanticOperation(
        function='rvbbit_map',
        cascade_path=stmt.cascade_path,
        model=result.model,
        cells=result.cells,
        takes=result.takes,
        arg_expression='(entire row)',
        distinct_query=stmt.using_query,
        distinct_count=result.input_rows,
        cache_hits=int(result.input_rows * cache_hit_rate),
        cache_total=result.input_rows,
        cache_hit_rate=cache_hit_rate,
        historical_cost_per_call=cost_per_row,
        historical_cost_stddev=historical_cascade.get('stddev_cost', 0) if historical_cascade else 0,
        historical_runs=historical_cascade.get('run_count', 0) if historical_cascade else 0,
        estimated_llm_calls=actual_llm_calls,
        estimated_cost=result.total_estimated_cost,
        prewarm_eligible=False,  # MAP doesn't benefit from prewarm (unique rows)
        prewarm_reason="RVBBIT MAP processes unique rows; prewarm not applicable"
    )
    result.operations.append(operation)

    # 8. Generate rewritten SQL for reference
    from rvbbit.sql_rewriter import _rewrite_map
    result.rewritten_sql = _rewrite_map(stmt)

    # 9. Get historical query stats
    result.historical = _get_historical_query_stats(fingerprint)

    # 10. Generate optimization hints
    result.optimization_hints = _generate_optimization_hints(result)

    result.analysis_duration_ms = (time.time() - start_time) * 1000

    return result


# ============================================================================
# Analysis Helpers
# ============================================================================

def _analyze_semantic_operation(
    spec: Dict[str, Any],
    duckdb_conn,
    execute_distinct: bool = True
) -> SemanticOperation:
    """
    Analyze a single semantic operation from prewarm_analyzer spec.

    Args:
        spec: Dict from analyze_query_for_prewarm with function, cascade, distinct_query
        duckdb_conn: DuckDB connection
        execute_distinct: Whether to execute distinct query

    Returns:
        SemanticOperation with full analysis
    """
    function_name = spec['function']
    cascade_path = spec['cascade']
    distinct_query = spec['distinct_query']
    arg_sql = spec.get('arg_sql', '')

    # Load cascade info
    cascade_info = _load_cascade_info(cascade_path)

    # Execute distinct query to get actual count
    distinct_count = 0
    if execute_distinct and duckdb_conn:
        try:
            # Wrap in COUNT to get just the number
            count_query = f"SELECT COUNT(*) FROM ({distinct_query}) AS _distinct_vals"
            distinct_count = duckdb_conn.execute(count_query).fetchone()[0]
        except Exception as e:
            log.warning(f"[explain] Could not execute distinct query for {function_name}: {e}")
            distinct_count = 100  # Conservative estimate

    # Check cache for this function
    cache_hits, cache_total = _check_cache_for_function(
        function_name=function_name,
        distinct_query=distinct_query,
        duckdb_conn=duckdb_conn,
        sample_size=min(distinct_count, 100)  # Sample up to 100 values
    )

    cache_hit_rate = cache_hits / cache_total if cache_total > 0 else 0.0

    # Get historical cost for this cascade
    cascade_id = cascade_info.get('cascade_id', function_name)
    historical = _get_historical_cascade_stats(cascade_id)

    if historical and historical.get('avg_cost', 0) > 0:
        cost_per_call = historical['avg_cost']
        cost_stddev = historical.get('stddev_cost', 0)
        run_count = historical.get('run_count', 0)
    else:
        # Fall back to model-based estimate
        cost_per_call = _estimate_cost_per_row(
            cascade_info['model'],
            cascade_info['cells'],
            cascade_info['takes']
        )
        cost_stddev = 0
        run_count = 0

    # Calculate estimates
    estimated_llm_calls = int(distinct_count * (1 - cache_hit_rate))
    estimated_cost = estimated_llm_calls * cost_per_call

    # Determine prewarm eligibility
    prewarm_eligible = False
    prewarm_reason = ""

    if distinct_count < 10:
        prewarm_reason = f"Too few distinct values ({distinct_count}); serial execution is fine"
    elif distinct_count > 500:
        prewarm_reason = f"Too many distinct values ({distinct_count}); diminishing returns from prewarm"
    elif cache_hit_rate > 0.8:
        prewarm_reason = f"High cache hit rate ({cache_hit_rate:.0%}); prewarm not needed"
    else:
        prewarm_eligible = True
        prewarm_reason = f"Good take: {distinct_count} distinct values, {cache_hit_rate:.0%} cache hits"

    return SemanticOperation(
        function=function_name,
        cascade_path=cascade_path,
        model=cascade_info['model'],
        cells=cascade_info['cells'],
        takes=cascade_info['takes'],
        arg_expression=arg_sql,
        distinct_query=distinct_query,
        distinct_count=distinct_count,
        cache_hits=cache_hits,
        cache_total=cache_total,
        cache_hit_rate=cache_hit_rate,
        historical_cost_per_call=cost_per_call,
        historical_cost_stddev=cost_stddev,
        historical_runs=run_count,
        estimated_llm_calls=estimated_llm_calls,
        estimated_cost=estimated_cost,
        prewarm_eligible=prewarm_eligible,
        prewarm_reason=prewarm_reason,
    )


# ============================================================================
# LLM Aggregate Analysis
# ============================================================================

def _get_llm_agg_registry() -> tuple:
    """
    Get LLM aggregate function registry from cascade system.

    Returns (functions_dict, aliases_dict) dynamically loaded from cascades.
    This replaces the old hardcoded LLM_AGG_FUNCTIONS/LLM_AGG_ALIASES.
    """
    try:
        from rvbbit.sql_tools.aggregate_registry import get_llm_agg_functions_compat
        return get_llm_agg_functions_compat()
    except ImportError:
        log.warning("[explain] Could not import aggregate registry")
        return {}, {}


def _detect_llm_aggregates(query: str) -> List[Dict[str, Any]]:
    """
    Detect LLM aggregate function calls in a query.

    Returns list of dicts with:
    - function: Original function name as written
    - canonical_name: Canonical LLM_* name
    - impl_function: Implementation function name
    - column_expression: The column being aggregated
    - extra_args: Additional arguments
    - model: Default model for this function
    """
    LLM_AGG_FUNCTIONS, LLM_AGG_ALIASES = _get_llm_agg_registry()
    if not LLM_AGG_FUNCTIONS:
        return []

    results = []

    # Build pattern for all function names (canonical + aliases)
    all_names = list(LLM_AGG_FUNCTIONS.keys()) + list(LLM_AGG_ALIASES.keys())

    for search_name in all_names:
        # Case-insensitive search for function calls
        pattern = re.compile(
            rf'\b({re.escape(search_name)})\s*\(',
            re.IGNORECASE
        )

        for match in pattern.finditer(query):
            start = match.start()
            func_start = match.end() - 1  # Position of opening paren

            # Find matching closing paren
            paren_depth = 0
            end = func_start
            for i, char in enumerate(query[func_start:], start=func_start):
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                    if paren_depth == 0:
                        end = i + 1
                        break

            if paren_depth != 0:
                continue  # Unbalanced parens, skip

            # Extract arguments
            args_str = query[func_start + 1:end - 1]
            args = _split_function_args(args_str)

            if not args:
                continue

            # Resolve alias to canonical name
            func_written = match.group(1).upper()
            canonical_name = LLM_AGG_ALIASES.get(func_written, func_written)

            # Get function info from registry (LLMAggFunction object)
            func_def = LLM_AGG_FUNCTIONS.get(canonical_name)
            if not func_def:
                continue

            results.append({
                'function': match.group(1),  # Original case
                'canonical_name': canonical_name,
                'impl_function': func_def.impl_name,
                'column_expression': args[0] if args else '',
                'extra_args': args[1:] if len(args) > 1 else [],
                'start': start,
                'end': end,
            })

    # Deduplicate by position (in case alias and canonical both matched)
    seen_positions = set()
    deduped = []
    for item in results:
        if item['start'] not in seen_positions:
            seen_positions.add(item['start'])
            deduped.append(item)

    # Further deduplicate by expression (same function + args should count once)
    # e.g., TOPICS(text, 4) in SELECT and GROUP BY is the same computation
    seen_expressions = set()
    final_results = []
    for item in deduped:
        expr_key = (item['canonical_name'], item['column_expression'], tuple(item['extra_args']))
        if expr_key not in seen_expressions:
            seen_expressions.add(expr_key)
            final_results.append(item)

    return final_results


def _split_function_args(args_str: str) -> List[str]:
    """Split function arguments, respecting nested parens and quotes."""
    args = []
    current = []
    paren_depth = 0
    in_string = False
    string_char = None

    for char in args_str:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
        elif char == string_char and in_string:
            in_string = False
            string_char = None

        if not in_string:
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == ',' and paren_depth == 0:
                args.append(''.join(current).strip())
                current = []
                continue

        current.append(char)

    if current:
        args.append(''.join(current).strip())

    return [a for a in args if a]


# Mapping from canonical aggregate names to their backing cascade_ids
# These cascades are in cascades/semantic_sql/
_AGG_TO_CASCADE = {
    "LLM_SUMMARIZE": "semantic_summarize",
    "LLM_THEMES": "semantic_themes",
    "LLM_SENTIMENT": "semantic_sentiment",
    "LLM_CLASSIFY": "semantic_classify",
    "LLM_CONSENSUS": "semantic_consensus",
    "LLM_OUTLIERS": "semantic_outliers",
    "LLM_DEDUPE": "semantic_dedupe",
    "LLM_CLUSTER": "semantic_cluster",
    "LLM_AGG": None,  # Generic LLM_AGG uses system default
}


def _get_model_for_function(function_name: str, canonical_name: str | None = None) -> str:
    """
    Get the actual model for a function by checking the SQL function registry first.

    This handles cases where a function name (like TOPICS) might be:
    1. A DIMENSION function registered directly (topics → x-ai/grok-4)
    2. An alias for an aggregate (TOPICS → LLM_THEMES → semantic_themes)

    The registry takes precedence since it has the actual cascade config.
    """
    # First, check if the function is directly in the SQL function registry
    # This catches DIMENSION functions like 'topics' which have their own cascade
    try:
        from rvbbit.semantic_sql.registry import get_sql_function

        # Try the original function name (case-insensitive)
        fn_lower = function_name.lower()
        entry = get_sql_function(fn_lower)
        if entry:
            # Found in registry - extract model from cascade config
            cells = entry.config.get('cells', [])
            for cell in cells:
                if isinstance(cell, dict) and cell.get('model'):
                    return cell['model']
            if entry.config.get('model'):
                return entry.config['model']
    except Exception as e:
        log.debug(f"[explain] Registry lookup failed for {function_name}: {e}")

    # Fall back to aggregate mapping
    if canonical_name:
        cascade_id = _AGG_TO_CASCADE.get(canonical_name)
        if cascade_id:
            return _get_model_for_cascade(cascade_id)

    return _get_default_model()


def _analyze_aggregate_operation(
    spec: Dict[str, Any],
    query: str,
    duckdb_conn,
) -> AggregateOperation:
    """
    Analyze an LLM aggregate operation.

    For aggregates, the number of LLM calls = number of groups.
    We estimate groups by analyzing the GROUP BY clause.
    Looks up the actual model from the backing cascade definition.
    """
    function = spec['function']
    canonical_name = spec['canonical_name']
    impl_function = spec['impl_function']
    column_expr = spec['column_expression']
    extra_args = spec['extra_args']

    # Look up the actual model - check registry first, then aggregate mapping
    model = _get_model_for_function(function, canonical_name)

    # Try to estimate number of groups and total rows
    estimated_groups, total_rows, avg_group_size = _estimate_group_count(query, duckdb_conn)

    # Get historical cost for this aggregate function
    historical = _get_historical_aggregate_stats(impl_function)

    if historical and historical.get('avg_cost', 0) > 0:
        cost_per_call = historical['avg_cost']
        cost_stddev = historical.get('stddev_cost', 0)
        run_count = historical.get('run_count', 0)
    else:
        # Fall back to model-based estimate using actual pricing
        cost_per_call = _estimate_aggregate_cost(model, avg_group_size)
        cost_stddev = 0
        run_count = 0

    estimated_cost = estimated_groups * cost_per_call

    return AggregateOperation(
        function=function,
        canonical_name=canonical_name,
        impl_function=impl_function,
        column_expression=column_expr,
        extra_args=extra_args,
        estimated_groups=estimated_groups,
        avg_group_size=avg_group_size,
        total_rows=total_rows,
        historical_cost_per_call=cost_per_call,
        historical_cost_stddev=cost_stddev,
        historical_runs=run_count,
        estimated_cost=estimated_cost,
        model=model,
    )


def _expression_contains_semantic_function(expr: str) -> bool:
    """Check if an expression contains any semantic/LLM function that would make actual LLM calls."""
    expr_lower = expr.lower()

    # Get aggregate functions from llm_agg_rewriter registry
    LLM_AGG_FUNCTIONS, LLM_AGG_ALIASES = _get_llm_agg_registry()
    all_agg_names = list(LLM_AGG_FUNCTIONS.keys()) + list(LLM_AGG_ALIASES.keys())

    # Check for aggregate functions
    for name in all_agg_names:
        if re.search(rf'\b{re.escape(name.lower())}\s*\(', expr_lower):
            return True

    # Check functions from the SQL function registry (cascade-backed functions)
    try:
        from rvbbit.semantic_sql.registry import get_sql_function_registry
        for fn_name in get_sql_function_registry().keys():
            fn_lower = fn_name.lower()
            if re.search(rf'\b{re.escape(fn_lower)}\s*\(', expr_lower):
                return True
            # Also check short aliases (semantic_X -> X)
            if fn_lower.startswith('semantic_'):
                alias = fn_lower.replace('semantic_', '', 1)
                if re.search(rf'\b{re.escape(alias)}\s*\(', expr_lower):
                    return True
    except Exception:
        pass

    # Check for other semantic/LLM patterns (fallback)
    semantic_patterns = [
        r'\bsemantic_',       # semantic_clean_year, semantic_condense, etc.
        r'\bllm_',            # llm_matches, llm_score, etc.
        r'\brvbbit_udf\s*\(',
        r'\brvbbit_cascade_udf\s*\(',
    ]

    for pattern in semantic_patterns:
        if re.search(pattern, expr_lower):
            return True

    return False


def _estimate_group_count(query: str, duckdb_conn) -> Tuple[int, int, int]:
    """
    Estimate the number of groups in a GROUP BY query.

    Returns (estimated_groups, total_rows, avg_group_size).

    IMPORTANT: Does NOT execute queries that contain semantic/LLM functions
    to avoid triggering actual LLM calls during EXPLAIN.
    """
    if not duckdb_conn:
        return 1, 100, 100  # Default single group

    try:
        # Extract FROM clause to get the base table/view
        from_match = re.search(r'\bFROM\s+(\S+)', query, re.IGNORECASE)
        if not from_match:
            return 1, 100, 100

        base_table = from_match.group(1)

        # Extract WHERE clause if present
        where_match = re.search(r'\bWHERE\s+(.+?)(?:\bGROUP\s+BY|\bORDER\s+BY|\bLIMIT|$)', query, re.IGNORECASE | re.DOTALL)
        where_clause = where_match.group(1).strip() if where_match else None

        # Check if WHERE clause contains semantic functions - if so, skip executing it
        where_is_safe = where_clause is None or not _expression_contains_semantic_function(where_clause)

        # First, count total rows (with WHERE if it's safe)
        if where_is_safe:
            if where_clause:
                count_query = f"SELECT COUNT(*) FROM {base_table} WHERE {where_clause}"
            else:
                count_query = f"SELECT COUNT(*) FROM {base_table}"

            try:
                total_rows = duckdb_conn.execute(count_query).fetchone()[0]
            except Exception:
                total_rows = 1000  # Fallback
        else:
            # WHERE has semantic functions - just count total rows without filter
            try:
                count_query = f"SELECT COUNT(*) FROM {base_table}"
                total_rows = duckdb_conn.execute(count_query).fetchone()[0]
            except Exception:
                total_rows = 1000

        # Check for GROUP BY clause
        group_by_match = re.search(r'\bGROUP\s+BY\s+(.+?)(?:\bHAVING|\bORDER\s+BY|\bLIMIT|$)', query, re.IGNORECASE | re.DOTALL)

        if not group_by_match:
            # No GROUP BY - entire result is one group
            return 1, total_rows, total_rows

        group_by_expr = group_by_match.group(1).strip()

        # Clean up the GROUP BY expression (remove trailing ORDER BY etc)
        group_by_expr = re.sub(r'\bORDER\s+BY.*$', '', group_by_expr, flags=re.IGNORECASE).strip()
        group_by_expr = re.sub(r'\bLIMIT.*$', '', group_by_expr, flags=re.IGNORECASE).strip()

        # Check if GROUP BY expression contains semantic functions
        if _expression_contains_semantic_function(group_by_expr):
            # Can't safely execute - use heuristic based on total rows
            # Semantic GROUP BY typically creates fewer groups (clustering/topic extraction)
            log.debug(f"[explain] GROUP BY contains semantic function, using heuristic")
            estimated_groups = max(1, min(total_rows // 20, 50))  # Assume ~20 rows per group, max 50 groups
            avg_group_size = max(1, total_rows // max(1, estimated_groups))
            return estimated_groups, total_rows, avg_group_size

        # Safe to execute - try to count distinct groups
        try:
            if where_is_safe and where_clause:
                groups_query = f"SELECT COUNT(*) FROM (SELECT DISTINCT {group_by_expr} FROM {base_table} WHERE {where_clause}) t"
            else:
                groups_query = f"SELECT COUNT(*) FROM (SELECT DISTINCT {group_by_expr} FROM {base_table}) t"

            estimated_groups = duckdb_conn.execute(groups_query).fetchone()[0]
        except Exception as e:
            # GROUP BY might contain function calls that fail - estimate from total rows
            log.debug(f"[explain] Could not count groups: {e}")
            # Rough estimate: assume ~10 groups per 100 rows
            estimated_groups = max(1, total_rows // 10)

        avg_group_size = max(1, total_rows // max(1, estimated_groups))

        return estimated_groups, total_rows, avg_group_size

    except Exception as e:
        log.debug(f"[explain] Group estimation failed: {e}")
        return 1, 100, 100


def _get_historical_aggregate_stats(impl_function: str) -> Optional[Dict[str, Any]]:
    """
    Get historical cost statistics for an aggregate function from ClickHouse.

    Looks for LLM calls made by the aggregate implementation.
    """
    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        # Look for calls where the cell_name or caller_id suggests this aggregate
        # The impl functions are called from within the aggregate framework
        query = """
            SELECT
                COUNT(*) as run_count,
                AVG(cost) as avg_cost,
                stddevPop(cost) as stddev_cost,
                AVG(tokens_in + tokens_out) as avg_tokens,
                AVG(duration_ms) as avg_duration_ms
            FROM unified_logs
            WHERE (
                cell_name LIKE %(pattern1)s
                OR cell_name LIKE %(pattern2)s
                OR caller_id LIKE %(pattern1)s
                OR udf_type = 'llm_aggregate'
            )
            AND cost IS NOT NULL
            AND cost > 0
        """

        # Try to match by impl function name patterns
        pattern1 = f"%{impl_function.replace('_impl', '')}%"
        pattern2 = f"%{impl_function}%"

        rows = db.query(query, {'pattern1': pattern1, 'pattern2': pattern2})

        if rows and len(rows) > 0:
            row = rows[0]
            if isinstance(row, dict):
                run_count = row.get('run_count', 0)
                if run_count and run_count > 0:
                    return {
                        'run_count': int(run_count),
                        'avg_cost': float(row.get('avg_cost', 0) or 0),
                        'stddev_cost': float(row.get('stddev_cost', 0) or 0),
                        'avg_tokens': float(row.get('avg_tokens', 0) or 0),
                        'avg_duration_ms': float(row.get('avg_duration_ms', 0) or 0),
                    }

        return None

    except Exception as e:
        log.debug(f"[explain] Could not get historical aggregate stats: {e}")
        return None


def _estimate_aggregate_cost(model: str, avg_group_size: int) -> float:
    """
    Estimate cost for an aggregate function call.

    Aggregates process all rows in a group, so cost scales with group size.
    Uses actual pricing from openrouter_models table.
    """
    pricing = _get_model_pricing(model)

    # Estimate tokens: prompt overhead + ~50 tokens per row in group + output
    prompt_overhead = 200
    tokens_per_row = 50
    output_tokens = 500  # Aggregates produce longer outputs

    input_tokens = prompt_overhead + (tokens_per_row * min(avg_group_size, 100))  # Cap at 100 rows sampled
    cost = _estimate_cost_from_pricing(pricing, input_tokens, output_tokens)

    return cost


def _check_cache_for_function(
    function_name: str,
    distinct_query: str,
    duckdb_conn,
    sample_size: int = 100
) -> Tuple[int, int]:
    """
    Check cache hit rate for a function by sampling distinct values.

    Args:
        function_name: The semantic function name
        distinct_query: Query to get distinct values
        duckdb_conn: DuckDB connection
        sample_size: How many values to sample

    Returns:
        Tuple of (hits, total_checked)
    """
    if sample_size <= 0:
        return 0, 0

    try:
        # Get sample of distinct values
        sample_query = f"SELECT * FROM ({distinct_query}) AS t LIMIT {sample_size}"
        sample_df = duckdb_conn.execute(sample_query).fetchdf()

        if len(sample_df) == 0:
            return 0, 0

        # Check cache for each value
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()

        hits = 0
        total = len(sample_df)

        for _, row in sample_df.iterrows():
            # Build args dict from row (first column is typically the value)
            if len(row) == 1:
                args = {'text': str(row.iloc[0])}
            else:
                args = row.to_dict()

            # Check cache (don't track hit)
            found, _, _ = cache.get(function_name, args, track_hit=False)
            if found:
                hits += 1

        return hits, total

    except Exception as e:
        log.debug(f"[explain] Cache check failed for {function_name}: {e}")
        return 0, 0


def _get_historical_cascade_stats(cascade_id: str) -> Optional[Dict[str, Any]]:
    """
    Get historical cost statistics for a cascade from ClickHouse.

    Queries unified_logs to aggregate actual costs.

    Args:
        cascade_id: The cascade_id to look up

    Returns:
        Dict with avg_cost, stddev_cost, avg_tokens, run_count or None
    """
    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        # Query aggregated session-level costs
        query = """
            SELECT
                COUNT(DISTINCT session_id) as run_count,
                AVG(session_cost) as avg_cost,
                stddevPop(session_cost) as stddev_cost,
                AVG(session_tokens) as avg_tokens,
                AVG(session_duration_ms) as avg_duration_ms
            FROM (
                SELECT
                    session_id,
                    SUM(cost) as session_cost,
                    SUM(tokens_in + tokens_out) as session_tokens,
                    dateDiff('millisecond', MIN(timestamp), MAX(timestamp)) as session_duration_ms
                FROM unified_logs
                WHERE cascade_id = %(cascade_id)s
                  AND cost IS NOT NULL
                  AND cost > 0
                GROUP BY session_id
            )
        """

        rows = db.query(query, {'cascade_id': cascade_id})

        if rows and len(rows) > 0:
            row = rows[0]
            if isinstance(row, dict):
                run_count = row.get('run_count', 0)
                if run_count and run_count > 0:
                    return {
                        'run_count': int(run_count),
                        'avg_cost': float(row.get('avg_cost', 0) or 0),
                        'stddev_cost': float(row.get('stddev_cost', 0) or 0),
                        'avg_tokens': float(row.get('avg_tokens', 0) or 0),
                        'avg_duration_ms': float(row.get('avg_duration_ms', 0) or 0),
                    }

        return None

    except Exception as e:
        log.debug(f"[explain] Could not get historical cascade stats: {e}")
        return None


def _get_historical_query_stats(fingerprint: str) -> Optional[HistoricalQueryStats]:
    """
    Get historical statistics for queries with the same fingerprint.

    Args:
        fingerprint: Query fingerprint hash

    Returns:
        HistoricalQueryStats or None
    """
    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        query = """
            SELECT
                COUNT(*) as match_count,
                AVG(total_cost) as avg_cost,
                stddevPop(total_cost) as stddev_cost,
                AVG(duration_ms) as avg_duration_ms,
                AVG(cache_hits / (cache_hits + cache_misses + 0.001)) as avg_cache_hit_rate,
                MAX(timestamp) as last_run
            FROM sql_query_log
            WHERE query_fingerprint = %(fingerprint)s
              AND status = 'completed'
              AND total_cost IS NOT NULL
        """

        rows = db.query(query, {'fingerprint': fingerprint})

        if rows and len(rows) > 0:
            row = rows[0]
            if isinstance(row, dict):
                match_count = row.get('match_count', 0)
                if match_count and match_count > 0:
                    return HistoricalQueryStats(
                        fingerprint=fingerprint,
                        match_count=int(match_count),
                        avg_cost=float(row.get('avg_cost', 0) or 0),
                        stddev_cost=float(row.get('stddev_cost', 0) or 0),
                        avg_duration_ms=float(row.get('avg_duration_ms', 0) or 0),
                        avg_cache_hit_rate=float(row.get('avg_cache_hit_rate', 0) or 0),
                        last_run=str(row.get('last_run', '')) if row.get('last_run') else None,
                    )

        return None

    except Exception as e:
        log.debug(f"[explain] Could not get historical query stats: {e}")
        return None


def _load_cascade_info(cascade_path: str) -> Dict[str, Any]:
    """Load cascade file and extract metadata."""
    import yaml

    # Resolve cascade path
    if not os.path.isabs(cascade_path):
        # Try relative to cwd first
        if os.path.exists(cascade_path):
            pass
        else:
            # Try with config root
            try:
                from rvbbit.config import get_config
                config = get_config()
                cascade_path = os.path.join(config.root_dir, cascade_path)
            except Exception:
                cascade_path = os.path.join(os.getcwd(), cascade_path)

    # Try with different extensions
    for ext in ['', '.yaml', '.yml', '.json', '.cascade.yaml']:
        full_path = cascade_path + ext if not cascade_path.endswith(ext) else cascade_path
        if os.path.exists(full_path):
            cascade_path = full_path
            break

    if not os.path.exists(cascade_path):
        # Return defaults if cascade not found - use system default model
        return {
            'cascade_id': os.path.basename(cascade_path).replace('.cascade.yaml', '').replace('.yaml', ''),
            'cells': ['unknown'],
            'model': _get_default_model(),
            'takes': 1
        }

    # Load cascade config
    try:
        with open(cascade_path, 'r') as f:
            if cascade_path.endswith('.json'):
                config = json.load(f)
            else:
                config = yaml.safe_load(f)
    except Exception as e:
        log.warning(f"[explain] Could not load cascade {cascade_path}: {e}")
        return {
            'cascade_id': os.path.basename(cascade_path),
            'cells': ['unknown'],
            'model': _get_default_model(),
            'takes': 1
        }

    # Extract cascade_id
    cascade_id = config.get('cascade_id', os.path.basename(cascade_path))

    # Extract cell info
    cells = config.get('cells', [])
    cell_names = []
    model = None
    takes = 1

    for i, cell in enumerate(cells):
        if isinstance(cell, dict):
            cell_names.append(cell.get('name', f'cell_{i}'))
            # Get model from first cell that has one
            if not model and cell.get('model'):
                model = cell.get('model')
            # Get takes from first cell that has it
            if takes == 1:
                takes_config = cell.get('takes', {})
                if isinstance(takes_config, dict):
                    factor = takes_config.get('factor', 1)
                    if isinstance(factor, int):
                        takes = factor

    # Default model - use system default from config
    if not model:
        model = _get_default_model()

    return {
        'cascade_id': cascade_id,
        'cells': cell_names if cell_names else ['unknown'],
        'model': model,
        'takes': takes
    }


def _estimate_cost_per_row(model: str, cells: List[str], takes: int) -> float:
    """
    Estimate cost per row based on model pricing from openrouter_models table.

    Uses _get_model_pricing() which queries ClickHouse and caches results.
    """
    pricing = _get_model_pricing(model)

    # Rough estimate: 500 prompt tokens, 200 completion tokens per cell
    prompt_tokens = 500
    completion_tokens = 200

    cost_per_cell = _estimate_cost_from_pricing(pricing, prompt_tokens, completion_tokens)
    return cost_per_cell * len(cells) * takes


def _estimate_map_cache_hit_rate(
    cascade_path: str,
    using_query: str,
    duckdb_conn
) -> float:
    """Estimate cache hit rate for RVBBIT MAP by sampling first 10 rows."""
    try:
        from rvbbit.sql_tools.udf import _cascade_udf_cache, _make_cascade_cache_key

        # Sample first 10 rows
        sample_query = f"SELECT * FROM ({using_query}) AS t LIMIT 10"
        sample_rows = duckdb_conn.execute(sample_query).fetchdf()

        if len(sample_rows) == 0:
            return 0.0

        # Check cache for each row
        hits = 0
        for _, row in sample_rows.iterrows():
            row_dict = row.to_dict()
            cache_key = _make_cascade_cache_key(cascade_path, row_dict)
            if cache_key in _cascade_udf_cache:
                hits += 1

        return hits / len(sample_rows)
    except Exception as e:
        log.debug(f"[explain] Cache hit estimation failed: {e}")
        return 0.0


def _generate_optimization_hints(result: ExplainResult) -> List[str]:
    """Generate optimization hints based on analysis."""
    hints = []

    # Check for prewarm opportunities
    prewarm_takes = [op for op in result.operations if op.prewarm_eligible]
    if prewarm_takes:
        for op in prewarm_takes:
            hints.append(
                f"✓ Prewarm eligible: {op.function} ({op.distinct_count} distinct values). "
                f"Add: -- @ parallel: 10"
            )

    # High cache hit rate - good!
    high_cache_ops = [op for op in result.operations if op.cache_hit_rate > 0.5]
    for op in high_cache_ops:
        hints.append(
            f"✓ Good cache utilization: {op.function} ({op.cache_hit_rate:.0%} hit rate)"
        )

    # Low historical data warning
    low_data_ops = [op for op in result.operations if op.historical_runs < 5]
    for op in low_data_ops:
        if op.historical_runs == 0:
            hints.append(
                f"⚠ No historical data: {op.function} - cost estimate is model-based"
            )

    # Parallel suggestion for large workloads
    if result.total_estimated_llm_calls > 50:
        if not any('parallel' in h.lower() for h in hints):
            hints.append(
                f"💡 Consider parallel execution for {result.total_estimated_llm_calls} LLM calls"
            )

    # Historical comparison
    if result.historical and result.historical.match_count >= 3:
        cost_diff = abs(result.total_estimated_cost - result.historical.avg_cost)
        if result.historical.avg_cost > 0:
            pct_diff = cost_diff / result.historical.avg_cost * 100
            if pct_diff > 20:
                hints.append(
                    f"📊 Estimate differs from historical avg by {pct_diff:.0f}% "
                    f"(estimate: ${result.total_estimated_cost:.4f}, historical: ${result.historical.avg_cost:.4f})"
                )

    return hints


# ============================================================================
# Formatting
# ============================================================================

def format_explain_result(result: ExplainResult) -> str:
    """Format ExplainResult as human-readable text."""
    lines = [
        "→ Query Plan:",
        f"  ├─ Query Type: {result.query_type}",
        f"  ├─ Fingerprint: {result.fingerprint}",
    ]

    if result.input_rows is not None:
        lines.append(f"  ├─ Input Rows: {result.input_rows:,}")

    if result.parallelism:
        lines.append(f"  ├─ Parallelism: {result.parallelism} workers")

    # Semantic operations
    if result.operations:
        lines.append(f"  │")
        lines.append(f"  ├─ Semantic Operations: {len(result.operations)}")

        for i, op in enumerate(result.operations):
            prefix = "  │  └─" if i == len(result.operations) - 1 else "  │  ├─"
            inner_prefix = "  │     " if i == len(result.operations) - 1 else "  │  │  "

            lines.append(f"{prefix} {op.function}({op.arg_expression[:40]}{'...' if len(op.arg_expression) > 40 else ''})")
            lines.append(f"{inner_prefix}├─ Cascade: {op.cascade_path}")
            lines.append(f"{inner_prefix}├─ Model: {op.model}")
            lines.append(f"{inner_prefix}├─ Cells: {len(op.cells)} ({', '.join(op.cells[:3])}{'...' if len(op.cells) > 3 else ''})")
            lines.append(f"{inner_prefix}├─ Distinct Values: {op.distinct_count:,}")
            lines.append(f"{inner_prefix}├─ Cache Status: {op.cache_hits:,}/{op.cache_total:,} = {op.cache_hit_rate:.0%} hit rate")

            if op.historical_runs > 0:
                lines.append(f"{inner_prefix}├─ Historical Cost: ${op.historical_cost_per_call:.6f}/call (±${op.historical_cost_stddev:.6f}, n={op.historical_runs})")
            else:
                lines.append(f"{inner_prefix}├─ Estimated Cost: ${op.historical_cost_per_call:.6f}/call (model-based)")

            lines.append(f"{inner_prefix}├─ Estimated LLM Calls: {op.estimated_llm_calls:,}")
            lines.append(f"{inner_prefix}└─ Estimated Cost: ${op.estimated_cost:.4f}")

    # LLM Aggregate operations
    if result.aggregates:
        lines.append(f"  │")
        lines.append(f"  ├─ LLM Aggregate Operations: {len(result.aggregates)}")

        for i, agg in enumerate(result.aggregates):
            is_last = i == len(result.aggregates) - 1
            prefix = "  │  └─" if is_last else "  │  ├─"
            inner_prefix = "  │     " if is_last else "  │  │  "

            # Function name with args
            args_display = agg.column_expression[:30]
            if len(agg.column_expression) > 30:
                args_display += '...'
            if agg.extra_args:
                args_display += f", {', '.join(str(a)[:10] for a in agg.extra_args[:2])}"

            lines.append(f"{prefix} {agg.function}({args_display})")
            lines.append(f"{inner_prefix}├─ Type: {agg.canonical_name} → {agg.impl_function}")
            lines.append(f"{inner_prefix}├─ Model: {agg.model}")
            lines.append(f"{inner_prefix}├─ Total Rows: {agg.total_rows:,}")
            lines.append(f"{inner_prefix}├─ Estimated Groups: {agg.estimated_groups:,} (1 LLM call per group)")
            lines.append(f"{inner_prefix}├─ Avg Group Size: {agg.avg_group_size:,} rows/group")

            if agg.historical_runs > 0:
                lines.append(f"{inner_prefix}├─ Historical Cost: ${agg.historical_cost_per_call:.6f}/group (±${agg.historical_cost_stddev:.6f}, n={agg.historical_runs})")
            else:
                lines.append(f"{inner_prefix}├─ Estimated Cost: ${agg.historical_cost_per_call:.6f}/group (model-based)")

            lines.append(f"{inner_prefix}└─ Estimated Total: ${agg.estimated_cost:.4f}")

    # Cost summary
    lines.append(f"  │")
    lines.append(f"  ├─ Total Estimated Cost: ${result.total_estimated_cost:.4f}")
    lines.append(f"  ├─ Total Estimated LLM Calls: {result.total_estimated_llm_calls:,}")

    if result.estimated_duration_seconds > 0:
        if result.estimated_duration_seconds < 60:
            lines.append(f"  ├─ Estimated Duration: ~{result.estimated_duration_seconds:.0f}s")
        else:
            minutes = result.estimated_duration_seconds / 60
            lines.append(f"  ├─ Estimated Duration: ~{minutes:.1f}m")

    # Historical comparison
    if result.historical and result.historical.match_count > 0:
        lines.append(f"  │")
        lines.append(f"  ├─ Historical Comparison ({result.historical.match_count} similar runs):")
        lines.append(f"  │  ├─ Avg Cost: ${result.historical.avg_cost:.4f} (±${result.historical.stddev_cost:.4f})")
        lines.append(f"  │  ├─ Avg Duration: {result.historical.avg_duration_ms:.0f}ms")
        lines.append(f"  │  └─ Avg Cache Hit Rate: {result.historical.avg_cache_hit_rate:.0%}")

    # Optimization hints
    if result.optimization_hints:
        lines.append(f"  │")
        lines.append(f"  ├─ Optimization Hints:")
        for hint in result.optimization_hints:
            lines.append(f"  │  • {hint}")

    # Rewritten SQL (for MAP)
    if result.rewritten_sql:
        lines.append(f"  │")
        lines.append(f"  └─ Rewritten SQL:")
        sql_lines = result.rewritten_sql.split('\n')[:10]
        for sql_line in sql_lines:
            lines.append(f"      {sql_line}")
        if len(result.rewritten_sql.split('\n')) > 10:
            lines.append("      ... (truncated)")
    else:
        # Close the tree
        if lines[-1].startswith("  │"):
            lines[-1] = lines[-1].replace("├─", "└─")

    # Analysis metadata
    lines.append(f"")
    lines.append(f"  (Analysis took {result.analysis_duration_ms:.1f}ms)")

    return '\n'.join(lines)


def format_explain_json(result: ExplainResult) -> Dict[str, Any]:
    """Format ExplainResult as JSON-serializable dict."""
    return {
        'query_type': result.query_type,
        'fingerprint': result.fingerprint,
        'input_rows': result.input_rows,
        'parallelism': result.parallelism,
        'cascade_path': result.cascade_path,
        'operations': [
            {
                'function': op.function,
                'cascade_path': op.cascade_path,
                'model': op.model,
                'cells': op.cells,
                'takes': op.takes,
                'arg_expression': op.arg_expression,
                'distinct_count': op.distinct_count,
                'cache_hits': op.cache_hits,
                'cache_total': op.cache_total,
                'cache_hit_rate': op.cache_hit_rate,
                'historical_cost_per_call': op.historical_cost_per_call,
                'historical_cost_stddev': op.historical_cost_stddev,
                'historical_runs': op.historical_runs,
                'estimated_llm_calls': op.estimated_llm_calls,
                'estimated_cost': op.estimated_cost,
                'prewarm_eligible': op.prewarm_eligible,
                'prewarm_reason': op.prewarm_reason,
            }
            for op in result.operations
        ],
        'aggregates': [
            {
                'function': agg.function,
                'canonical_name': agg.canonical_name,
                'impl_function': agg.impl_function,
                'column_expression': agg.column_expression,
                'extra_args': agg.extra_args,
                'estimated_groups': agg.estimated_groups,
                'avg_group_size': agg.avg_group_size,
                'total_rows': agg.total_rows,
                'historical_cost_per_call': agg.historical_cost_per_call,
                'historical_cost_stddev': agg.historical_cost_stddev,
                'historical_runs': agg.historical_runs,
                'estimated_cost': agg.estimated_cost,
                'model': agg.model,
            }
            for agg in result.aggregates
        ],
        'total_estimated_cost': result.total_estimated_cost,
        'total_estimated_llm_calls': result.total_estimated_llm_calls,
        'estimated_duration_seconds': result.estimated_duration_seconds,
        'historical': {
            'fingerprint': result.historical.fingerprint,
            'match_count': result.historical.match_count,
            'avg_cost': result.historical.avg_cost,
            'stddev_cost': result.historical.stddev_cost,
            'avg_duration_ms': result.historical.avg_duration_ms,
            'avg_cache_hit_rate': result.historical.avg_cache_hit_rate,
            'last_run': result.historical.last_run,
        } if result.historical else None,
        'optimization_hints': result.optimization_hints,
        'analysis_duration_ms': result.analysis_duration_ms,
    }
