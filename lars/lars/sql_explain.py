"""
EXPLAIN for Semantic SQL - Query planning and cost estimation.

Provides comprehensive cost estimates and execution plan details for:
- LARS MAP/RUN statements
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

# Cache for model class token profiles (avoid repeated DB queries)
_token_profile_cache: Dict[str, Dict[str, float]] = {}


def _get_default_model() -> str:
    """Get the system default model from config."""
    try:
        from lars.config import get_config
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
        from lars.db_adapter import get_db
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
        from lars.semantic_sql.registry import get_sql_function
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
class PipelineStageExplain:
    """Explanation for a single pipeline stage (THEN operator)."""
    stage_name: str             # e.g., 'PIVOT', 'MELT', 'ANALYZE', 'FILTER'
    stage_index: int            # Position in pipeline (0-based)
    cascade_id: str             # Backing cascade ID
    cascade_path: str           # Path to cascade file
    output_mode: str            # 'value', 'table_sql_execute', etc.
    model: str                  # LLM model used
    cells: List[str]            # Cell names in cascade
    args: List[str]             # Arguments passed to stage
    into_table: Optional[str]   # Optional per-stage INTO table
    cache_enabled: bool         # Whether this stage uses caching
    estimated_cost: float       # Estimated cost for this stage
    description: str            # Human-readable description


@dataclass
class ExplainResult:
    """Result of EXPLAIN analysis."""
    # Query metadata
    query_type: str             # 'semantic_query', 'lars_map', 'lars_run'
    fingerprint: str            # Query fingerprint hash

    # For LARS MAP/RUN
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

    # Pipeline stages (for THEN/INTO queries)
    pipeline_stages: List[PipelineStageExplain] = field(default_factory=list)

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

    # Native DuckDB EXPLAIN output for the rewritten query
    native_plan: Optional[str] = None


# ============================================================================
# Native DuckDB EXPLAIN Helper
# ============================================================================

def _strip_deref_patterns(sql: str) -> str:
    """
    Strip @cascade() deref patterns from SQL for EXPLAIN purposes.

    Deref patterns like @param_get('key') are evaluated at runtime
    and injected into the query. For EXPLAIN, we replace them with
    NULL placeholders so DuckDB can parse the query structure.

    Args:
        sql: SQL that may contain @cascade() patterns

    Returns:
        SQL with deref patterns replaced by NULL
    """
    import re

    # Pattern: @identifier( ... ) with balanced parens
    # We need to handle nested parens inside the deref call
    result = sql
    pattern = re.compile(r'@(\w+)\s*\(')

    max_iterations = 50  # Safety limit
    for _ in range(max_iterations):
        match = pattern.search(result)
        if not match:
            break

        start = match.start()
        paren_start = match.end() - 1

        # Find matching close paren
        depth = 1
        pos = paren_start + 1
        while pos < len(result) and depth > 0:
            if result[pos] == '(':
                depth += 1
            elif result[pos] == ')':
                depth -= 1
            pos += 1

        if depth == 0:
            # Replace the entire @cascade(...) with NULL
            result = result[:start] + 'NULL /*@deref*/' + result[pos:]
        else:
            # Unbalanced parens, just break to avoid infinite loop
            break

    return result


def _get_native_duckdb_plan(sql: str, duckdb_conn) -> Optional[str]:
    """
    Get the native DuckDB EXPLAIN output for a SQL query.

    Rewrites the query to replace semantic operators with UDF calls,
    then runs DuckDB's native EXPLAIN to show the execution plan.

    Args:
        sql: SQL query (may contain semantic operators)
        duckdb_conn: DuckDB connection

    Returns:
        Formatted EXPLAIN output string, or None if EXPLAIN fails
    """
    if not duckdb_conn:
        return "(Native plan unavailable: no database connection)"

    rewritten_sql = None
    try:
        # Rewrite the query to replace semantic operators with UDF calls
        from lars.sql_rewriter import rewrite_lars_syntax

        rewritten_sql = rewrite_lars_syntax(sql, duckdb_conn=duckdb_conn)

        # Strip @cascade() deref patterns - these are runtime-resolved
        # and can't be EXPLAINed by DuckDB. Replace with NULL placeholders.
        explain_sql = _strip_deref_patterns(rewritten_sql)

        # Run native EXPLAIN on the processed query
        explain_query = f"EXPLAIN {explain_sql}"
        result = duckdb_conn.execute(explain_query)
        rows = result.fetchall()

        # DuckDB EXPLAIN returns rows with (plan_type, plan_text)
        # e.g., ('physical_plan', '┌───────────...┘')
        if rows:
            plan_parts = []

            # Show the rewritten SQL for transparency (full, no truncation)
            plan_parts.append(f"Rewritten SQL:\n  {rewritten_sql}\n")

            for row in rows:
                if len(row) >= 2:
                    # Format: "plan_type:\n plan_text"
                    plan_type = str(row[0])
                    plan_text = str(row[1])
                    plan_parts.append(f"{plan_type}:\n{plan_text}")
                else:
                    plan_parts.append(str(row[0]))
            return '\n'.join(plan_parts)

    except Exception as e:
        log.warning(f"[explain] Failed to get native DuckDB plan: {e}")
        # Return helpful error message instead of None
        error_msg = str(e).split('\n')[0]  # First line only

        lines = []
        if rewritten_sql and rewritten_sql != sql:
            lines.append(f"Rewritten SQL:")
            # Show full rewritten SQL (no truncation)
            lines.append(f"  {rewritten_sql}")
            lines.append("")

        if "Catalog Error" in str(e) and "does not exist" in str(e):
            lines.append(f"(Native plan unavailable: Semantic UDFs not registered)")
            lines.append(f"  Hint: The DuckDB EXPLAIN requires UDFs like semantic_matches()")
            lines.append(f"  to be registered. This works in PGwire sessions but not in")
            lines.append(f"  standalone analysis. The rewritten SQL above shows the query")
            lines.append(f"  that would be executed after semantic operator substitution.")
        else:
            lines.append(f"(Native plan unavailable: {error_msg})")

        return '\n'.join(lines) if lines else None

    return None


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
    Handles both LARS MAP/RUN and inline semantic UDF calls.

    Args:
        query: SQL query string
        duckdb_conn: DuckDB connection for executing distinct queries
        execute_distinct: If True, run DISTINCT queries for accurate counts

    Returns:
        ExplainResult with comprehensive cost analysis
    """
    start_time = time.time()

    # Get query fingerprint and classification
    from lars.sql_trail import fingerprint_query
    fingerprint, template, udf_types = fingerprint_query(query)

    # Determine query type
    try:
        from lars.sql_trail import _determine_query_type
        query_type = _determine_query_type(udf_types, query)
    except ImportError:
        # Fallback if internal function not available
        if any('semantic' in udf.lower() for udf in udf_types):
            query_type = 'semantic_query'
        elif any('lars' in udf.lower() for udf in udf_types):
            query_type = 'lars_query'
        else:
            query_type = 'sql_query'

    result = ExplainResult(
        query_type=query_type,
        fingerprint=fingerprint,
    )

    # Extract LIMIT clause for row estimation (if present)
    estimated_rows = _extract_limit_from_query(query)

    # Detect LLM aggregate functions BEFORE rewriting
    # (rewriter changes function names, making detection harder)
    aggregate_specs = _detect_llm_aggregates(query)

    # Analyze for prewarm opportunities on ORIGINAL query BEFORE rewriting
    # This allows prewarm_analyzer to generate proper distinct queries with correct table context
    from lars.sql_tools.prewarm_analyzer import analyze_query_for_prewarm
    prewarm_specs_original = analyze_query_for_prewarm(query)

    # Rewrite query to convert infix operators to function calls
    # This ensures fallback detection can find infix operators that prewarm_analyzer might miss
    try:
        from lars.sql_tools.unified_operator_rewriter import rewrite_all_operators
        query_for_analysis = rewrite_all_operators(query)
        log.debug(f"[explain] Rewrote query for analysis (infix → function calls)")
    except Exception as e:
        log.warning(f"[explain] Query rewriting failed, using original: {e}")
        query_for_analysis = query

    # Also analyze prewarm on rewritten query (catches what original analysis missed due to infix)
    prewarm_specs_rewritten = analyze_query_for_prewarm(query_for_analysis)

    # Merge both sets of prewarm specs, preferring original (has better context)
    prewarm_specs = prewarm_specs_original.copy()
    # Add rewritten specs that aren't in original (by function name)
    original_funcs = {spec['function'] for spec in prewarm_specs_original}
    for spec in prewarm_specs_rewritten:
        if spec['function'] not in original_funcs:
            prewarm_specs.append(spec)

    # Analyze each scalar semantic operation
    for spec in prewarm_specs:
        operation = _analyze_semantic_operation(
            spec=spec,
            duckdb_conn=duckdb_conn,
            execute_distinct=execute_distinct
        )
        # Adjust LLM calls based on LIMIT if available
        if estimated_rows and operation.estimated_llm_calls == 1:
            operation = _adjust_operation_row_count(operation, estimated_rows)
        result.operations.append(operation)

    # Fallback: Detect scalar semantic functions via regex (catches what sqlglot misses)
    try:
        scalar_funcs = _detect_scalar_semantic_functions_fallback(query_for_analysis)
        existing_funcs = {op.function.lower() for op in result.operations}
        for scalar_spec in scalar_funcs:
            if scalar_spec['function'].lower() not in existing_funcs:
                # Enhance fallback spec with query context for distinct query generation
                scalar_spec['full_query'] = query_for_analysis
                operation = _create_scalar_operation_fallback(scalar_spec, duckdb_conn, execute_distinct)
                # Adjust LLM calls based on LIMIT if available
                if estimated_rows:
                    operation = _adjust_operation_row_count(operation, estimated_rows)
                result.operations.append(operation)
    except Exception as e:
        log.debug(f"[explain] Failed to detect scalar functions (fallback): {e}")

    # Analyze LLM aggregate functions (already detected above before rewriting)
    for agg_spec in aggregate_specs:
        agg_operation = _analyze_aggregate_operation(
            spec=agg_spec,
            query=query_for_analysis,
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

    # Get native DuckDB execution plan for the rewritten query
    result.native_plan = _get_native_duckdb_plan(query, duckdb_conn)

    result.analysis_duration_ms = (time.time() - start_time) * 1000

    return result


def explain_lars_map(
    stmt,
    duckdb_conn,
    check_cache: bool = True
) -> ExplainResult:
    """
    Analyze LARS MAP query and estimate cost.

    This is called from sql_rewriter.py for EXPLAIN LARS MAP queries.

    Args:
        stmt: Parsed LARSStatement
        duckdb_conn: DuckDB connection for row count estimation
        check_cache: Whether to estimate cache hit rate

    Returns:
        ExplainResult with cost estimation and plan details
    """
    start_time = time.time()

    # Get query fingerprint
    from lars.sql_trail import fingerprint_query
    full_query = f"LARS MAP '{stmt.cascade_path}' USING ({stmt.using_query})"
    fingerprint, _, udf_types = fingerprint_query(full_query)

    result = ExplainResult(
        query_type='lars_map',
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
        function='lars_map',
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
        prewarm_reason="LARS MAP processes unique rows; prewarm not applicable"
    )
    result.operations.append(operation)

    # 8. Generate rewritten SQL for reference
    from lars.sql_rewriter import _rewrite_map
    result.rewritten_sql = _rewrite_map(stmt)

    # 9. Get historical query stats
    result.historical = _get_historical_query_stats(fingerprint)

    # 10. Generate optimization hints
    result.optimization_hints = _generate_optimization_hints(result)

    result.analysis_duration_ms = (time.time() - start_time) * 1000

    return result


def explain_pipeline_query(
    pipeline,
    original_query: str,
    duckdb_conn,
    execute_distinct: bool = True
) -> ExplainResult:
    """
    Analyze a pipeline query (with THEN/INTO stages) and estimate cost.

    Pipeline queries have the form:
        SELECT * FROM t WHERE col MEANS 'x' THEN PIVOT 'by region' INTO result

    This analyzes both the base SQL semantic operations and each pipeline stage.

    Args:
        pipeline: ParsedPipeline from pipeline_parser
        original_query: Full original query for fingerprinting
        duckdb_conn: DuckDB connection for analysis
        execute_distinct: Whether to execute distinct queries

    Returns:
        ExplainResult with base SQL analysis + pipeline stage details
    """
    start_time = time.time()

    # Get query fingerprint (returns tuple: hash, template, udf_types)
    from lars.sql_trail import fingerprint_query
    fingerprint_hash, _, _ = fingerprint_query(original_query)

    result = ExplainResult(
        query_type='pipeline_query',
        fingerprint=fingerprint_hash,
        rewritten_sql=original_query,
    )

    # Extract LIMIT clause for row estimation (from base SQL)
    estimated_rows = _extract_limit_from_query(pipeline.base_sql)

    # Detect LLM aggregate functions BEFORE rewriting
    # (rewriter changes function names, making detection harder)
    try:
        aggregate_specs_pipeline = _detect_llm_aggregates(pipeline.base_sql)
    except Exception as e:
        log.debug(f"[explain] Failed to detect aggregates: {e}")
        aggregate_specs_pipeline = []

    # Rewrite base SQL to convert infix operators to function calls
    # This ensures detection functions can find all semantic operations
    # (e.g., "observed CONSENSUS" → "lars_cascade_udf('semantic_consensus', observed)")
    try:
        from lars.sql_tools.unified_operator_rewriter import rewrite_all_operators
        base_sql_for_analysis = rewrite_all_operators(pipeline.base_sql)
        log.debug(f"[explain] Rewrote pipeline base SQL for analysis (infix → function calls)")
    except Exception as e:
        log.warning(f"[explain] Base SQL rewriting failed, using original: {e}")
        base_sql_for_analysis = pipeline.base_sql

    # 1. Analyze base SQL for semantic operations (scalar functions)
    try:
        from lars.sql_tools.prewarm_analyzer import analyze_query_for_prewarm
        prewarm_specs = analyze_query_for_prewarm(base_sql_for_analysis)

        for spec in prewarm_specs:
            operation = _analyze_semantic_operation(spec, duckdb_conn, execute_distinct)
            # Adjust LLM calls based on LIMIT if available
            if estimated_rows and operation.estimated_llm_calls == 1:
                operation = _adjust_operation_row_count(operation, estimated_rows)
            result.operations.append(operation)
    except Exception as e:
        log.debug(f"[explain] Failed to analyze base SQL operations: {e}")

    # 1b. Detect LATERAL semantic table functions (e.g., LATERAL triples_rows(...))
    try:
        lateral_funcs = _detect_lateral_semantic_functions(base_sql_for_analysis)
        for lateral_spec in lateral_funcs:
            operation = _create_lateral_operation(lateral_spec)
            # Adjust LLM calls based on LIMIT if available
            if estimated_rows:
                operation = _adjust_operation_row_count(operation, estimated_rows)
            result.operations.append(operation)
    except Exception as e:
        log.debug(f"[explain] Failed to detect LATERAL functions: {e}")

    # 1c. Fallback: Detect scalar semantic functions via regex (catches what sqlglot misses)
    try:
        scalar_funcs = _detect_scalar_semantic_functions_fallback(base_sql_for_analysis)
        # Only add functions not already detected
        existing_funcs = {op.function.lower().replace('lateral ', '') for op in result.operations}
        for scalar_spec in scalar_funcs:
            if scalar_spec['function'].lower() not in existing_funcs:
                # Enhance spec with query context
                scalar_spec['full_query'] = base_sql_for_analysis
                operation = _create_scalar_operation_fallback(scalar_spec, duckdb_conn, execute_distinct)
                # Adjust LLM calls based on LIMIT if available
                if estimated_rows:
                    operation = _adjust_operation_row_count(operation, estimated_rows)
                result.operations.append(operation)
    except Exception as e:
        log.debug(f"[explain] Failed to detect scalar functions (fallback): {e}")

    # 2. Analyze aggregates (already detected above before rewriting)
    for agg_spec in aggregate_specs_pipeline:
        try:
            agg_operation = _analyze_aggregate_operation(agg_spec, pipeline.base_sql, duckdb_conn)
            result.aggregates.append(agg_operation)
        except Exception as e:
            log.debug(f"[explain] Failed to analyze aggregate {agg_spec.get('function', 'unknown')}: {e}")

    # 3. Analyze each pipeline stage
    for idx, stage in enumerate(pipeline.stages):
        stage_explain = _analyze_pipeline_stage(stage, idx)
        result.pipeline_stages.append(stage_explain)

    # 4. Sum up totals
    # Base SQL costs
    scalar_cost = sum(op.estimated_cost for op in result.operations)
    scalar_calls = sum(op.estimated_llm_calls for op in result.operations)
    agg_cost = sum(agg.estimated_cost for agg in result.aggregates)
    agg_calls = sum(agg.estimated_groups for agg in result.aggregates)

    # Pipeline stage costs
    pipeline_cost = sum(stage.estimated_cost for stage in result.pipeline_stages)
    pipeline_calls = len(result.pipeline_stages)  # Each stage = 1 LLM call (roughly)

    result.total_estimated_cost = scalar_cost + agg_cost + pipeline_cost
    result.total_estimated_llm_calls = scalar_calls + agg_calls + pipeline_calls

    # Estimate duration
    if result.total_estimated_llm_calls > 0:
        avg_latency_per_call = 1.0
        result.estimated_duration_seconds = result.total_estimated_llm_calls * avg_latency_per_call

    # Get historical stats
    result.historical = _get_historical_query_stats(fingerprint_hash)

    # Generate optimization hints
    result.optimization_hints = _generate_optimization_hints(result)

    # Add pipeline-specific hints
    for stage in result.pipeline_stages:
        if stage.output_mode == 'table_sql_execute' and stage.cache_enabled:
            result.optimization_hints.append(
                f"[CACHE] {stage.stage_name}: Uses structural caching (schema fingerprint + prompt)")

    # Get native DuckDB execution plan for the base query
    # (Pipeline stages are post-processing and not part of DuckDB execution)
    result.native_plan = _get_native_duckdb_plan(pipeline.base_sql, duckdb_conn)

    result.analysis_duration_ms = (time.time() - start_time) * 1000

    return result


def _analyze_pipeline_stage(stage, index: int) -> PipelineStageExplain:
    """Analyze a single pipeline stage and return its explanation."""
    from lars.semantic_sql.registry import get_pipeline_cascade

    # Look up the cascade for this stage
    cascade_entry = get_pipeline_cascade(stage.name)

    if cascade_entry is None:
        # Unknown stage
        return PipelineStageExplain(
            stage_name=stage.name,
            stage_index=index,
            cascade_id='unknown',
            cascade_path='',
            output_mode='unknown',
            model='unknown',
            cells=[],
            args=stage.args,
            into_table=getattr(stage, 'into_table', None),
            cache_enabled=False,
            estimated_cost=0.0,
            description=f"Unknown pipeline stage: {stage.name}"
        )

    # Get cascade details
    cascade_id = cascade_entry.cascade_id
    cascade_path = cascade_entry.cascade_path
    output_mode = cascade_entry.output_mode or 'value'
    cache_enabled = cascade_entry.cache_enabled

    # Get model and cells from cascade config
    config = cascade_entry.config
    cells = []
    model = _get_default_model()

    if config and 'cells' in config:
        for cell in config['cells']:
            if isinstance(cell, dict):
                cells.append(cell.get('name', 'unknown'))
                if 'model' in cell:
                    model = cell['model']

    # Estimate cost (rough: based on model pricing)
    pricing = _get_model_pricing(model)
    # Assume ~500 input tokens, ~200 output tokens per stage
    estimated_cost = (500 * pricing['prompt_price']) + (200 * pricing['completion_price'])

    # Build description
    args_str = f"({', '.join(repr(a) for a in stage.args)})" if stage.args else ""
    description = cascade_entry.sql_function.get('description', f"{stage.name} stage") if cascade_entry.sql_function else f"{stage.name} stage"

    return PipelineStageExplain(
        stage_name=stage.name,
        stage_index=index,
        cascade_id=cascade_id,
        cascade_path=cascade_path,
        output_mode=output_mode,
        model=model,
        cells=cells,
        args=stage.args,
        into_table=getattr(stage, 'into_table', None),
        cache_enabled=cache_enabled,
        estimated_cost=estimated_cost,
        description=description
    )


# ============================================================================
# Analysis Helpers
# ============================================================================

def _extract_limit_from_query(sql: str) -> Optional[int]:
    """
    Extract LIMIT value from a SQL query for row estimation.

    Returns:
        The LIMIT value if found, None otherwise.
    """
    import re

    # Match LIMIT followed by a number (with optional whitespace)
    # Must not be inside a string or comment
    # Simple approach: find LIMIT at word boundary followed by digits
    match = re.search(r'\bLIMIT\s+(\d+)\b', sql, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    return None


def _adjust_operation_row_count(operation: 'SemanticOperation', row_count: int) -> 'SemanticOperation':
    """
    Create a copy of a SemanticOperation with adjusted row count estimates.

    Args:
        operation: Original operation
        row_count: Estimated number of rows

    Returns:
        New SemanticOperation with adjusted estimates
    """
    # Estimate cost per call (use historical or model-based)
    cost_per_call = operation.historical_cost_per_call if operation.historical_cost_per_call > 0 else 0.0001

    return SemanticOperation(
        function=operation.function,
        cascade_path=operation.cascade_path,
        model=operation.model,
        cells=operation.cells,
        takes=operation.takes,
        arg_expression=operation.arg_expression,
        distinct_query=operation.distinct_query,
        distinct_count=operation.distinct_count or row_count,
        cache_hits=operation.cache_hits,
        cache_total=operation.cache_total,
        cache_hit_rate=operation.cache_hit_rate,
        historical_cost_per_call=operation.historical_cost_per_call,
        historical_cost_stddev=operation.historical_cost_stddev,
        historical_runs=operation.historical_runs,
        estimated_llm_calls=row_count,
        estimated_cost=row_count * cost_per_call,
        prewarm_eligible=operation.prewarm_eligible,
        prewarm_reason=operation.prewarm_reason,
    )


def _detect_lateral_semantic_functions(sql: str) -> List[Dict[str, Any]]:
    """
    Detect LATERAL semantic table functions in SQL.

    Looks for patterns like:
        LATERAL triples_rows(e.message)
        LATERAL timeline_rows(content)
        LATERAL normalize_rows(text)

    These are _rows variants of TABLE-shaped semantic SQL functions.

    Returns:
        List of dicts with function info (base_function, args, etc.)
    """
    import re

    results = []
    seen = set()

    # Get registered TABLE-shaped functions from registry
    try:
        from lars.semantic_sql.registry import get_sql_function_registry
        registry = get_sql_function_registry()

        # Find functions that have returns_columns (TABLE shape)
        table_functions = {}
        for name, entry in registry.items():
            if entry.returns_columns:
                table_functions[name.lower()] = {
                    'name': name,
                    'cascade_path': entry.cascade_path,
                    'returns_columns': entry.returns_columns,
                }
                # Also track the _rows variant name
                rows_name = f"{name.lower()}_rows"
                table_functions[rows_name] = {
                    'name': name,  # Base function name
                    'cascade_path': entry.cascade_path,
                    'returns_columns': entry.returns_columns,
                    'is_rows_variant': True,
                }

    except Exception as e:
        log.debug(f"[explain] Could not load TABLE functions from registry: {e}")
        table_functions = {}

    if not table_functions:
        return []

    # Build regex pattern for LATERAL func_name(...)
    # Pattern: LATERAL whitespace func_name whitespace* (
    func_names_pattern = '|'.join(re.escape(fn) for fn in table_functions.keys())
    pattern = re.compile(
        rf'\bLATERAL\s+({func_names_pattern})\s*\(',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        func_name = match.group(1).lower()
        func_info = table_functions.get(func_name)
        if not func_info:
            continue

        # Extract the argument(s) by finding balanced parens
        start_paren = match.end() - 1
        depth = 1
        i = start_paren + 1
        while i < len(sql) and depth > 0:
            if sql[i] == '(':
                depth += 1
            elif sql[i] == ')':
                depth -= 1
            i += 1

        args_str = sql[start_paren + 1:i - 1].strip() if depth == 0 else ""

        # Dedupe by base function name + args
        key = (func_info['name'].lower(), args_str)
        if key in seen:
            continue
        seen.add(key)

        results.append({
            'function': func_name,
            'base_function': func_info['name'],
            'cascade_path': func_info['cascade_path'],
            'returns_columns': func_info['returns_columns'],
            'args_str': args_str,
            'is_rows_variant': func_info.get('is_rows_variant', False),
        })

    return results


def _create_lateral_operation(spec: Dict[str, Any]) -> SemanticOperation:
    """
    Create a SemanticOperation for a LATERAL table function.

    Args:
        spec: Dict from _detect_lateral_semantic_functions

    Returns:
        SemanticOperation describing the LATERAL function
    """
    function_name = spec['function']
    base_function = spec['base_function']
    cascade_path = spec['cascade_path']
    returns_columns = spec.get('returns_columns', [])
    args_str = spec.get('args_str', '')

    # Load cascade info
    cascade_info = _load_cascade_info(cascade_path)

    # Format returns_columns for display
    cols_display = ', '.join(f"{c['name']}:{c['type']}" for c in returns_columns[:3])
    if len(returns_columns) > 3:
        cols_display += f", ... ({len(returns_columns)} cols)"

    return SemanticOperation(
        function=f"LATERAL {function_name}",
        cascade_path=cascade_path,
        model=cascade_info['model'],
        cells=cascade_info['cells'],
        takes=cascade_info['takes'],
        arg_expression=args_str,
        distinct_query="",  # Not applicable for LATERAL
        distinct_count=0,  # Unknown at explain time
        cache_hits=0,
        cache_total=0,
        cache_hit_rate=0.0,
        historical_cost_per_call=0.0,  # Would need historical data
        historical_cost_stddev=0.0,
        historical_runs=0,
        estimated_llm_calls=1,  # At least 1 call (depends on row count)
        estimated_cost=0.0,  # Unknown without row count
        prewarm_eligible=False,
        prewarm_reason=f"TABLE function ({base_function}) returns: {cols_display}",
    )


def _detect_scalar_semantic_functions_fallback(sql: str) -> List[Dict[str, Any]]:
    """
    Fallback detection for scalar semantic functions via regex.

    This catches functions that sqlglot's parser might miss due to
    complex SQL syntax or qualified references like t.column.

    Returns:
        List of dicts with function info
    """
    import re

    results = []
    seen = set()

    # Get all SCALAR functions from registry (including operator aliases)
    try:
        from lars.semantic_sql.registry import get_sql_function_registry
        registry = get_sql_function_registry()

        scalar_functions = {}
        for name, entry in registry.items():
            if entry.shape == 'SCALAR':
                # Add the canonical name
                scalar_functions[name.lower()] = {
                    'name': name,
                    'cascade_path': entry.cascade_path,
                }
                # Also track without semantic_ prefix
                if name.lower().startswith('semantic_'):
                    short_name = name.lower().replace('semantic_', '')
                    scalar_functions[short_name] = {
                        'name': name,
                        'cascade_path': entry.cascade_path,
                    }

                # ALSO extract function names from operator patterns
                # Patterns like "TLDR({{ text }})" or "CONDENSE({{ text }}, '{{ focus }}')"
                if entry.operators:
                    for operator_pattern in entry.operators:
                        op_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*\(', operator_pattern)
                        if op_match:
                            op_func_name = op_match.group(1).lower()
                            if op_func_name not in scalar_functions:
                                scalar_functions[op_func_name] = {
                                    'name': name,  # Map to canonical name
                                    'cascade_path': entry.cascade_path,
                                }

    except Exception as e:
        log.debug(f"[explain] Could not load SCALAR functions from registry: {e}")
        return []

    if not scalar_functions:
        return []

    # Build regex pattern for func_name(...)
    # Must NOT be preceded by LATERAL (those are handled separately)
    func_names_pattern = '|'.join(re.escape(fn) for fn in scalar_functions.keys())
    pattern = re.compile(
        rf'(?<!\bLATERAL\s)(?<!\bLATERAL\s\s)\b({func_names_pattern})\s*\(',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        func_name = match.group(1).lower()
        func_info = scalar_functions.get(func_name)
        if not func_info:
            continue

        # Extract the argument(s) by finding balanced parens
        start_paren = match.end() - 1
        depth = 1
        i = start_paren + 1
        while i < len(sql) and depth > 0:
            if sql[i] == '(':
                depth += 1
            elif sql[i] == ')':
                depth -= 1
            i += 1

        args_str = sql[start_paren + 1:i - 1].strip() if depth == 0 else ""

        # Dedupe by canonical function name + args
        key = (func_info['name'].lower(), args_str)
        if key in seen:
            continue
        seen.add(key)

        results.append({
            'function': func_info['name'],
            'cascade_path': func_info['cascade_path'],
            'args_str': args_str,
        })

    return results


def _strip_semantic_filters_from_query(query: str) -> str:
    """
    Strip WHERE/HAVING clauses that contain semantic functions from a query.

    This is critical for EXPLAIN - we need to count distinct values WITHOUT
    executing expensive cascade operations.

    Example:
        SELECT DISTINCT col FROM t WHERE semantic_matches(col, 'x') LIMIT 500
        → SELECT DISTINCT col FROM t LIMIT 500

    Args:
        query: SQL query possibly containing semantic functions in WHERE

    Returns:
        Query with semantic filters removed
    """
    import re

    # Check if query has WHERE clause with semantic functions
    if not re.search(r'\bWHERE\b', query, re.IGNORECASE):
        return query

    # Get list of semantic function names that would trigger cascade execution
    semantic_patterns = [
        r'\bsemantic_\w+\s*\(',
        r'\blars_cascade_udf\s*\(',
        r'\bllm_\w+\s*\(',
    ]

    # Check if WHERE clause contains any semantic functions
    where_match = re.search(r'\bWHERE\s+(.+?)(?:\s+LIMIT|\s+ORDER|\s+GROUP|\s*$)', query, re.IGNORECASE | re.DOTALL)

    if where_match:
        where_clause = where_match.group(1)

        # Check if WHERE contains semantic functions
        has_semantic = any(re.search(pattern, where_clause, re.IGNORECASE) for pattern in semantic_patterns)

        if has_semantic:
            # Remove the entire WHERE clause to avoid cascade execution
            # Keep everything before WHERE and everything after (LIMIT, ORDER BY, etc.)
            before_where = query[:where_match.start()]
            after_where_match = re.search(r'\b(LIMIT|ORDER\s+BY|GROUP\s+BY)\b', query[where_match.end():], re.IGNORECASE)

            if after_where_match:
                # Preserve LIMIT/ORDER/GROUP after WHERE
                after_clause = query[where_match.end() + after_where_match.start():]
                stripped = before_where + ' ' + after_clause
            else:
                # Just remove WHERE entirely
                stripped = before_where

            log.debug(f"[explain] Stripped semantic WHERE clause to avoid cascade execution during EXPLAIN")
            return stripped.strip()

    return query


def _create_scalar_operation_fallback(
    spec: Dict[str, Any],
    duckdb_conn=None,
    execute_distinct: bool = True
) -> SemanticOperation:
    """
    Create a SemanticOperation for a scalar function detected via fallback.

    Now enhanced to actually analyze the function properly with cache checking!

    Args:
        spec: Dict from _detect_scalar_semantic_functions_fallback
        duckdb_conn: DuckDB connection for executing distinct queries
        execute_distinct: Whether to execute distinct queries

    Returns:
        SemanticOperation describing the scalar function
    """
    function_name = spec['function']
    cascade_path = spec['cascade_path']
    args_str = spec.get('args_str', '')
    full_query = spec.get('full_query', '')

    # Load cascade info
    cascade_info = _load_cascade_info(cascade_path)

    # Try to generate a proper distinct query by extracting table context from full query
    distinct_query = ""
    arg_sql = ""

    if args_str and full_query:
        # Extract the first argument (usually the column)
        first_arg = args_str.split(',')[0].strip()

        # Try to extract table name from FROM clause (including aliases)
        import re
        # Pattern: FROM table_name [AS] alias
        from_match = re.search(r'\bFROM\s+([\w.]+)(?:\s+(?:AS\s+)?(\w+))?', full_query, re.IGNORECASE)

        if from_match and first_arg:
            table_name = from_match.group(1)
            table_alias = from_match.group(2)  # May be None

            # Strip table alias prefix from column name if present
            # e.g., "d.markdown_body" -> "markdown_body"
            column_name = first_arg
            if table_alias and column_name.startswith(f"{table_alias}."):
                column_name = column_name[len(table_alias)+1:]  # Remove "d."

            # Build a proper distinct query (use table name, not alias)
            distinct_query = f"SELECT DISTINCT {column_name} FROM {table_name}"

            # Check for LIMIT in original query
            limit_match = re.search(r'\bLIMIT\s+(\d+)', full_query, re.IGNORECASE)
            if limit_match:
                distinct_query += f" LIMIT {limit_match.group(1)}"
            else:
                distinct_query += " LIMIT 500"  # Default limit

            arg_sql = column_name  # Use column without alias prefix

    # If we have a valid distinct query, analyze it properly!
    if distinct_query and arg_sql and duckdb_conn:
        # Build a proper spec for full analysis
        analysis_spec = {
            'function': function_name,
            'cascade': cascade_path,
            'distinct_query': distinct_query,
            'arg_sql': arg_sql,
        }
        # Use the full analysis path
        return _analyze_semantic_operation(analysis_spec, duckdb_conn, execute_distinct)

    # Fallback if we couldn't build a good distinct query
    return SemanticOperation(
        function=function_name,
        cascade_path=cascade_path,
        model=cascade_info['model'],
        cells=cascade_info['cells'],
        takes=cascade_info['takes'],
        arg_expression=args_str,
        distinct_query=distinct_query,
        distinct_count=0,
        cache_hits=0,
        cache_total=0,
        cache_hit_rate=0.0,
        historical_cost_per_call=0.0,
        historical_cost_stddev=0.0,
        historical_runs=0,
        estimated_llm_calls=1,
        estimated_cost=0.0,
        prewarm_eligible=False,
        prewarm_reason="Detected via fallback (limited analysis)",
    )


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
    # IMPORTANT: Strip semantic functions from distinct query to avoid executing cascades during EXPLAIN!
    distinct_count = 0
    if execute_distinct and duckdb_conn and distinct_query:
        try:
            # Strip WHERE clauses that contain semantic functions
            # This prevents cascade execution during EXPLAIN
            distinct_query_safe = _strip_semantic_filters_from_query(distinct_query)

            # Wrap in COUNT to get just the number
            count_query = f"SELECT COUNT(*) FROM ({distinct_query_safe}) AS _distinct_vals"
            distinct_count = duckdb_conn.execute(count_query).fetchone()[0]
        except Exception as e:
            log.warning(f"[explain] Could not execute distinct query for {function_name}: {e}")
            distinct_count = 100  # Conservative estimate

    # Check cache for this function
    # IMPORTANT: Extract function args BEFORE stripping WHERE clause!
    # We need the full args (column + criterion) to match cache entries
    cache_sample_size = min(max(distinct_count, 10), 100) if distinct_count > 0 else 10

    # Extract static args (like criterion) from the original distinct query
    function_args_template = _extract_function_args_from_query(distinct_query, function_name) if distinct_query else {}

    # Check if this function has complex/nested args that can't be predicted without execution
    # CASCADE(), JSON_OBJECT(), nested functions, computed expressions, etc.
    # IMPORTANT: Ignore LARS rewriting artifacts (__LARS_SOURCE__, ROW_NUMBER injection)
    is_lars_rewriting_artifact = '__LARS_SOURCE:' in arg_sql and 'ROW_NUMBER()' in arg_sql.upper()

    if is_lars_rewriting_artifact:
        # This is just our rewriting artifact for row tracking - underlying query is simple
        # Extract the actual arg before the '__LARS_SOURCE:' injection
        first_arg = arg_sql.split(',')[0].strip() if ',' in arg_sql else arg_sql
        check_arg = first_arg  # Check complexity on the actual column arg
    else:
        check_arg = arg_sql

    has_complex_args = (
        'CASCADE(' in check_arg.upper() or
        'JSON_OBJECT(' in check_arg.upper() or
        'JSON_ARRAY(' in check_arg.upper() or
        '||' in check_arg or  # String concatenation (but not in LARS injection)
        'SELECT' in check_arg.upper() or  # Subquery
        check_arg.count('(') > 1  # Nested function calls
    )

    # Now strip WHERE to get safe query for sampling
    distinct_query_for_cache = _strip_semantic_filters_from_query(distinct_query) if distinct_query else ""

    # Only check cache for simple arg patterns
    # Complex/nested args require execution to predict, which defeats the purpose of EXPLAIN
    if has_complex_args:
        log.debug(f"[explain] Skipping cache check for {function_name} - complex args: {arg_sql[:100]}")
        cache_hits, cache_total = 0, 0  # Will show "Cache not checked"
    else:
        cache_hits, cache_total = _check_cache_for_function(
            function_name=function_name,
            distinct_query=distinct_query_for_cache,
            duckdb_conn=duckdb_conn,
            sample_size=cache_sample_size,
            function_args_template=function_args_template  # Pass the extracted args!
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
        from lars.sql_tools.aggregate_registry import get_llm_agg_functions_compat
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
        from lars.semantic_sql.registry import get_sql_function

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
        from lars.semantic_sql.registry import get_sql_function_registry
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
        r'\blars_udf\s*\(',
        r'\blars_cascade_udf\s*\(',
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
        from lars.db_adapter import get_db
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

    Token estimation strategy (waterfall):
    1. Try to use actual token averages from historical executions
    2. Fall back to model-class defaults if insufficient data
    """
    pricing = _get_model_pricing(model)

    # Estimate tokens: prompt overhead + ~50 tokens per row in group + output
    prompt_overhead = 200
    tokens_per_row = 50

    # TIER 1: Try to get actual token averages from historical data
    historical_profile = _get_model_class_token_profile(model)

    if historical_profile:
        # Use actual average output tokens from past executions!
        output_tokens = int(historical_profile['avg_output'])
        log.debug(f"[cost] Using historical aggregate profile: {output_tokens} output tokens "
                  f"(from {historical_profile['sample_size']} samples)")

    else:
        # TIER 2: Fall back to model-class defaults
        model_lower = model.lower()

        # IMAGE GENERATION aggregates - very high output
        if any(keyword in model_lower for keyword in [
            'dall-e', 'dalle', 'imagen', 'flux', 'stable-diffusion', 'midjourney'
        ]):
            output_tokens = 2000  # Image generation in aggregates

        # VISION aggregates - moderate output
        elif any(keyword in model_lower for keyword in [
            'vision', 'gpt-4o', 'claude-3', 'gemini-pro-vision'
        ]):
            output_tokens = 600

        # TEXT aggregates - default (summaries, themes, etc.)
        else:
            output_tokens = 500  # Aggregates produce longer outputs

    input_tokens = prompt_overhead + (tokens_per_row * min(avg_group_size, 100))  # Cap at 100 rows sampled
    cost = _estimate_cost_from_pricing(pricing, input_tokens, output_tokens)

    return cost


def _extract_function_args_from_query(query: str, function_name: str) -> Dict[str, Any]:
    """
    Extract the static arguments from a function call in a query.

    Example:
        Query: SELECT DISTINCT col FROM t WHERE semantic_matches(col, 'common name')
        Function: semantic_matches
        Returns: {'criterion': 'common name'}

    This helps build complete args dicts for cache checking.
    """
    import re

    # Find function call pattern: function_name(arg1, arg2, ...)
    pattern = rf'\b{re.escape(function_name)}\s*\((.*?)\)'
    match = re.search(pattern, query, re.IGNORECASE)

    if not match:
        return {}

    # Extract arguments string
    args_str = match.group(1)

    # Parse arguments (simple approach: split by comma, extract string literals)
    args = {}

    # Split by comma (naive - doesn't handle nested parens perfectly but good enough)
    parts = args_str.split(',')

    if len(parts) >= 2:
        # Second argument is typically the criterion for semantic functions
        criterion_part = parts[1].strip()

        # Extract string literal value
        if criterion_part.startswith("'") or criterion_part.startswith('"'):
            quote = criterion_part[0]
            # Find closing quote
            end = criterion_part.find(quote, 1)
            if end > 0:
                criterion_value = criterion_part[1:end]
                # Strip any __LARS_SOURCE__ prefixes
                criterion_value = re.sub(r'__LARS_[A-Z_]+:\{.*?\}__\s*', '', criterion_value)
                args['criterion'] = criterion_value

    return args


def _strip_cache_key_prefixes(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip __LARS_SOURCE__, __LARS_TAKES__, and other prefixes from cache key args.

    This allows matching cache entries that have execution context with
    plain values from EXPLAIN analysis.

    Args:
        args: Argument dict possibly containing prefixed strings

    Returns:
        Args dict with prefixes stripped
    """
    import re

    stripped = {}
    prefix_pattern = r'__LARS_[A-Z_]+:\{.*?\}__\s*'

    for key, value in args.items():
        if isinstance(value, str):
            # Strip all __LARS_*:...__ prefixes
            cleaned = re.sub(prefix_pattern, '', value)
            stripped[key] = cleaned
        else:
            stripped[key] = value

    return stripped


def _args_match_ignoring_order(args1: Dict[str, Any], args2: Dict[str, Any]) -> bool:
    """
    Check if two argument dicts match, ignoring key order.

    Both dicts should already have prefixes stripped.
    """
    if set(args1.keys()) != set(args2.keys()):
        return False

    for key in args1.keys():
        val1 = str(args1[key]).strip()
        val2 = str(args2[key]).strip()
        if val1 != val2:
            return False

    return True


def _check_cache_for_function(
    function_name: str,
    distinct_query: str,
    duckdb_conn,
    sample_size: int = 100,
    function_args_template: Optional[Dict[str, Any]] = None
) -> Tuple[int, int]:
    """
    Check cache hit rate for a function by sampling distinct values.

    This queries the semantic_sql_cache table directly and strips __LARS_SOURCE__
    and other prefixes to match execution cache keys.

    Args:
        function_name: The semantic function name
        distinct_query: Query to get distinct values (with WHERE stripped)
        duckdb_conn: DuckDB connection
        sample_size: How many values to sample
        function_args_template: Static args extracted from function call (e.g., criterion)

    Returns:
        Tuple of (hits, total_checked)
    """
    if function_args_template is None:
        function_args_template = {}
    if sample_size <= 0:
        log.debug(f"[explain] Cache check skipped for {function_name}: sample_size={sample_size}")
        return 0, 0

    try:
        # Get sample of distinct values
        sample_query = f"SELECT * FROM ({distinct_query}) AS t LIMIT {sample_size}"
        sample_df = duckdb_conn.execute(sample_query).fetchdf()

        if len(sample_df) == 0:
            log.debug(f"[explain] Cache check for {function_name}: distinct query returned 0 rows")
            return 0, 0

        # Query the cache table directly for this function
        # This is more reliable than using cache.get() with prefix mismatches
        from lars.db_adapter import get_db
        db = get_db()

        # Get all cached args for this function
        cached_entries = db.query("""
            SELECT args_json, args_preview
            FROM semantic_sql_cache
            WHERE function_name = %(function_name)s
            LIMIT 1000
        """, {'function_name': function_name})

        if not cached_entries:
            log.debug(f"[explain] No cache entries found for {function_name}")
            return 0, len(sample_df)

        log.debug(f"[explain] Found {len(cached_entries)} cache entries for {function_name}")

        # Parse cached args and strip prefixes for matching
        import json
        cached_values_stripped = []
        for entry in cached_entries:
            try:
                args = json.loads(entry['args_json'])
                # Strip __LARS_SOURCE__, __LARS_TAKES__, etc. from all string values
                stripped_args = _strip_cache_key_prefixes(args)
                cached_values_stripped.append(stripped_args)
            except Exception:
                continue

        # Use the function args template passed in (extracted before WHERE was stripped)
        # This contains static args like criterion that don't vary per row

        # Check each sampled value against cache
        hits = 0
        total = len(sample_df)

        log.debug(f"[explain] Checking {total} sampled values against {len(cached_values_stripped)} cached entries")
        log.debug(f"[explain] Function args template: {function_args_template}")

        for idx, row in enumerate(sample_df.iterrows()):
            _, row_data = row
            # Build complete args dict including both column value and other arguments
            if len(row_data) == 1:
                column_value = str(row_data.iloc[0])
                # Combine column value with template args
                sample_args = {'text': column_value}
                # Add other args from the function call (e.g., criterion)
                if function_args_template:
                    sample_args.update(function_args_template)
            else:
                sample_args = {k: str(v) for k, v in row_data.to_dict().items()}

            # Check if this value is in cached entries (ignoring prefixes)
            matched = False
            for cached in cached_values_stripped:
                if _args_match_ignoring_order(sample_args, cached):
                    hits += 1
                    matched = True
                    break

            if idx < 3:  # Log first 3 for debugging
                status = "HIT" if matched else "MISS"
                log.debug(f"[explain]   Sample {idx+1}: {status} - {sample_args}")

        hit_rate = (hits/total*100) if total > 0 else 0
        log.info(f"[explain] Cache check for {function_name}: {hits}/{total} hits ({hit_rate:.0f}%)")
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
        from lars.db_adapter import get_db
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
        from lars.db_adapter import get_db
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
                from lars.config import get_config
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


def _get_model_class_token_profile(model: str) -> Optional[Dict[str, float]]:
    """
    Get actual average token usage for this model class from historical data.

    Queries unified_logs to find real token averages from past executions.
    Results are cached to avoid repeated queries.

    Returns:
        Dict with avg_input, avg_output, sample_size or None if insufficient data
    """
    global _token_profile_cache

    # Determine model class first for cache key
    model_lower = model.lower()

    # Determine model class
    if any(keyword in model_lower for keyword in [
        'dall-e', 'dalle', 'imagen', 'flux', 'stable-diffusion', 'midjourney', 'firefly', 'recraft'
    ]):
        model_class = 'IMAGE_GEN'
        # Match any image generation model (escape % for SQL LIKE)
        patterns = ['dall-e', 'dalle', 'imagen', 'flux', 'stable-diffusion', 'midjourney', 'firefly', 'recraft']

    elif any(keyword in model_lower for keyword in [
        'vision', 'gpt-4o', 'gpt-4-turbo', 'claude-3', 'gemini-pro-vision', 'gemini-1.5', 'gemini-2.0'
    ]):
        model_class = 'VISION'
        patterns = ['vision', 'gpt-4o', 'gpt-4-turbo', 'claude-3', 'gemini-pro-vision', 'gemini-1.5', 'gemini-2.0']

    elif any(keyword in model_lower for keyword in [
        'tts', 'whisper', 'elevenlabs', 'audio', 'speech'
    ]):
        model_class = 'AUDIO_GEN'
        patterns = ['tts', 'whisper', 'elevenlabs', 'audio', 'speech']

    else:
        # TEXT - use empty patterns (will query all non-specialized)
        model_class = 'TEXT'
        patterns = []

    # Check cache first
    if model_class in _token_profile_cache:
        return _token_profile_cache[model_class]

    try:
        from lars.db_adapter import get_db
        db = get_db()

        # Build WHERE clause based on patterns
        if patterns:
            # Build OR conditions for pattern matching
            conditions = " OR ".join([f"positionCaseInsensitive(model, '{p}') > 0" for p in patterns])
            where_clause = f"({conditions})"
        else:
            # TEXT class - exclude specialized models
            exclusions = ['dall-e', 'dalle', 'imagen', 'flux', 'stable-diffusion',
                         'vision', 'gpt-4o', 'whisper', 'tts', 'elevenlabs']
            conditions = " AND ".join([f"positionCaseInsensitive(model, '{ex}') = 0" for ex in exclusions])
            where_clause = conditions

        # Query actual token averages from unified_logs
        # Note: Using positionCaseInsensitive instead of LIKE to avoid % character issues
        query = f"""
            SELECT
                AVG(tokens_in) as avg_input,
                AVG(tokens_out) as avg_output,
                stddevPop(tokens_out) as stddev_output,
                COUNT(*) as sample_size
            FROM unified_logs
            WHERE {where_clause}
              AND tokens_in IS NOT NULL
              AND tokens_out IS NOT NULL
              AND tokens_in > 0
              AND tokens_out > 0
              AND cost > 0
            HAVING sample_size >= 10
        """

        rows = db.query(query)

        if rows and len(rows) > 0:
            row = rows[0]
            sample_size = row.get('sample_size', 0)
            if sample_size >= 10:
                profile = {
                    'avg_input': float(row['avg_input'] or 0),
                    'avg_output': float(row['avg_output'] or 0),
                    'stddev_output': float(row['stddev_output'] or 0),
                    'sample_size': int(sample_size),
                    'model_class': model_class,
                }
                # Cache the result
                _token_profile_cache[model_class] = profile
                log.info(f"[cost] Loaded token profile for {model_class} from {sample_size} historical executions: "
                         f"avg_in={profile['avg_input']:.0f}, avg_out={profile['avg_output']:.0f}")
                return profile

        log.debug(f"[cost] Insufficient historical data for {model_class} (need ≥10 samples)")
        return None

    except Exception as e:
        log.debug(f"[cost] Could not load token profile for {model}: {e}")
        return None


def _estimate_cost_per_row(model: str, cells: List[str], takes: int) -> float:
    """
    Estimate cost per row based on model pricing from openrouter_models table.

    Uses _get_model_pricing() which queries ClickHouse and caches results.

    Token estimation strategy (waterfall):
    1. Try to use actual token averages from historical executions (unified_logs)
    2. Fall back to model-class defaults if insufficient historical data

    This learns from YOUR actual usage patterns!
    """
    pricing = _get_model_pricing(model)

    # TIER 1: Try to get actual token averages from historical data
    historical_profile = _get_model_class_token_profile(model)

    if historical_profile:
        # Use ACTUAL averages from past executions! 🎯
        prompt_tokens = int(historical_profile['avg_input'])
        completion_tokens = int(historical_profile['avg_output'])
        log.info(f"[cost] Using historical token profile for {model}: "
                 f"{prompt_tokens} in, {completion_tokens} out "
                 f"(from {historical_profile['sample_size']} executions)")

    else:
        # TIER 2: Fall back to model-class defaults
        model_lower = model.lower()

        # IMAGE GENERATION - Very high output tokens (images encoded as tokens)
        if any(keyword in model_lower for keyword in [
            'dall-e', 'dalle', 'imagen', 'stable-diffusion', 'flux',
            'midjourney', 'firefly', 'imagen', 'recraft'
        ]):
            prompt_tokens = 600       # Prompt + API overhead
            completion_tokens = 2000  # Images use ~1500-3000 tokens!
            log.debug(f"[cost] Using IMAGE_GEN fallback profile for {model}")

        # VISION MODELS - Higher input (process images), moderate output
        elif any(keyword in model_lower for keyword in [
            'vision', 'gpt-4o', 'gpt-4-turbo', 'claude-3', 'claude-3.5',
            'gemini-pro-vision', 'gemini-1.5', 'gemini-2.0'
        ]):
            prompt_tokens = 800   # Often includes image tokens in input
            completion_tokens = 300
            log.debug(f"[cost] Using VISION fallback profile for {model}")

        # AUDIO GENERATION - Very high output tokens
        elif any(keyword in model_lower for keyword in [
            'tts', 'whisper', 'elevenlabs', 'audio', 'speech'
        ]):
            prompt_tokens = 400
            completion_tokens = 2500  # Audio tokens
            log.debug(f"[cost] Using AUDIO_GEN fallback profile for {model}")

        # TEXT MODELS - Generic estimate (works well for most cases)
        else:
            prompt_tokens = 500
            completion_tokens = 200
            log.debug(f"[cost] Using TEXT fallback profile for {model}")

    cost_per_cell = _estimate_cost_from_pricing(pricing, prompt_tokens, completion_tokens)
    return cost_per_cell * len(cells) * takes


def _estimate_map_cache_hit_rate(
    cascade_path: str,
    using_query: str,
    duckdb_conn
) -> float:
    """Estimate cache hit rate for LARS MAP by sampling first 10 rows."""
    try:
        from lars.sql_tools.udf import _cascade_udf_cache, _make_cascade_cache_key

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

    # Add cache estimation caveat if any operations have cache data
    has_cache_data = any(op.cache_hit_rate > 0 for op in result.operations)
    if has_cache_data:
        hints.append(
            "[INFO] Cache hit estimates are conservative - actual execution may have higher "
            "hit rates due to row-level cache keys and dynamic context"
        )

    # Check for prewarm opportunities
    prewarm_takes = [op for op in result.operations if op.prewarm_eligible]
    if prewarm_takes:
        for op in prewarm_takes:
            hints.append(
                f"[OK] Prewarm eligible: {op.function} ({op.distinct_count} distinct values). "
                f"Add: -- @ parallel: 10"
            )

    # High cache hit rate - good!
    high_cache_ops = [op for op in result.operations if op.cache_hit_rate > 0.5]
    for op in high_cache_ops:
        hints.append(
            f"[OK] Good cache utilization: {op.function} ({op.cache_hit_rate:.0%} hit rate)"
        )

    # Low historical data warning
    low_data_ops = [op for op in result.operations if op.historical_runs < 5]
    for op in low_data_ops:
        if op.historical_runs == 0:
            hints.append(
                f"[WARN] No historical data: {op.function} - cost estimate is model-based"
            )

    # Parallel suggestion for large workloads
    if result.total_estimated_llm_calls > 50:
        if not any('parallel' in h.lower() for h in hints):
            hints.append(
                f"[TIP] Consider parallel execution for {result.total_estimated_llm_calls} LLM calls"
            )

    # Historical comparison
    if result.historical and result.historical.match_count >= 3:
        cost_diff = abs(result.total_estimated_cost - result.historical.avg_cost)
        if result.historical.avg_cost > 0:
            pct_diff = cost_diff / result.historical.avg_cost * 100
            if pct_diff > 20:
                hints.append(
                    f"[CHART] Estimate differs from historical avg by {pct_diff:.0f}% "
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

            # Show cache status with caveat about estimation accuracy
            if op.cache_total > 0:
                cache_note = " (estimated - may be higher in execution)" if op.cache_hit_rate > 0 else ""
                # Check if this looks like a complex arg pattern (nested functions, etc.)
                is_complex = (
                    'CASCADE(' in op.arg_expression.upper() or
                    'JSON_OBJECT(' in op.arg_expression.upper() or
                    '||' in op.arg_expression
                )
                if is_complex and op.cache_hit_rate == 0:
                    cache_note = " (complex args - actual hit rate likely higher at execution)"
                lines.append(f"{inner_prefix}├─ Cache Status: {op.cache_hits:,}/{op.cache_total:,} = {op.cache_hit_rate:.0%} hit rate{cache_note}")
            elif op.distinct_count == 0:
                lines.append(f"{inner_prefix}├─ Cache Status: Not checked (distinct values unknown)")
            else:
                lines.append(f"{inner_prefix}├─ Cache Status: Not checked")

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

    # Pipeline stages (for THEN/INTO queries)
    if result.pipeline_stages:
        lines.append(f"  │")
        lines.append(f"  ├─ Pipeline Stages: {len(result.pipeline_stages)}")

        for i, stage in enumerate(result.pipeline_stages):
            is_last = i == len(result.pipeline_stages) - 1
            prefix = "  │  └─" if is_last else "  │  ├─"
            inner_prefix = "  │     " if is_last else "  │  │  "

            args_display = ', '.join(repr(a)[:30] for a in stage.args[:2]) if stage.args else "(no args)"
            lines.append(f"{prefix} [{stage.stage_index + 1}] {stage.stage_name}({args_display})")
            lines.append(f"{inner_prefix}├─ Cascade: {stage.cascade_id}")
            lines.append(f"{inner_prefix}├─ Model: {stage.model}")
            lines.append(f"{inner_prefix}├─ Cells: {', '.join(stage.cells) if stage.cells else '(none)'}")
            lines.append(f"{inner_prefix}├─ Output Mode: {stage.output_mode}")
            if stage.cache_enabled:
                lines.append(f"{inner_prefix}├─ Cache: enabled (structural caching)")
            if stage.into_table:
                lines.append(f"{inner_prefix}├─ INTO: {stage.into_table}")
            lines.append(f"{inner_prefix}└─ Estimated Cost: ${stage.estimated_cost:.4f}")

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
        lines.append(f"  ├─ Rewritten SQL:")
        sql_lines = result.rewritten_sql.split('\n')
        for sql_line in sql_lines:
            lines.append(f"  │    {sql_line}")

    # Native DuckDB execution plan (data processing after LLM calls)
    if result.native_plan:
        lines.append(f"  │")
        lines.append(f"  └─ Data Processing Plan (DuckDB):")
        lines.append(f"      ─────────────────────────────────")
        plan_lines = result.native_plan.split('\n')
        for plan_line in plan_lines:
            lines.append(f"      {plan_line}")
    else:
        # Show message if native plan couldn't be generated
        lines.append(f"  │")
        lines.append(f"  └─ Data Processing Plan: (not available)")
        # Close the tree if no native plan
        if lines and len(lines) > 2 and lines[-3].startswith("  │"):
            lines[-3] = lines[-3].replace("├─", "└─")

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
        'pipeline_stages': [
            {
                'stage_name': stage.stage_name,
                'stage_index': stage.stage_index,
                'cascade_id': stage.cascade_id,
                'cascade_path': stage.cascade_path,
                'output_mode': stage.output_mode,
                'model': stage.model,
                'cells': stage.cells,
                'args': stage.args,
                'into_table': stage.into_table,
                'cache_enabled': stage.cache_enabled,
                'estimated_cost': stage.estimated_cost,
                'description': stage.description,
            }
            for stage in result.pipeline_stages
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
        'native_plan': result.native_plan,
    }
