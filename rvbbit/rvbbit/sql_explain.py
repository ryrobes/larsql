"""
EXPLAIN RVBBIT MAP - Query planning and cost estimation.

Provides cost estimates and execution plan details WITHOUT running the cascade.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import re
import os
import json


@dataclass
class ExplainResult:
    """Result of EXPLAIN RVBBIT MAP analysis."""
    input_rows: int
    parallelism: Optional[int]
    cascade_path: str
    phases: List[str]
    model: str
    candidates: int
    cost_per_row: float
    total_cost: float
    cache_hit_rate: float
    rewritten_sql: str


def explain_rvbbit_map(
    stmt,
    duckdb_conn,
    check_cache: bool = True
) -> ExplainResult:
    """
    Analyze RVBBIT MAP query and estimate cost.

    Args:
        stmt: Parsed RVBBITStatement
        duckdb_conn: DuckDB connection for row count estimation
        check_cache: Whether to estimate cache hit rate

    Returns:
        ExplainResult with cost estimation and plan details
    """
    # 1. Estimate input rows from USING query
    try:
        count_query = f"SELECT COUNT(*) FROM ({stmt.using_query}) AS t"
        input_rows = duckdb_conn.execute(count_query).fetchone()[0]
    except:
        # Fallback: extract LIMIT if present
        limit_match = re.search(r'LIMIT\s+(\d+)', stmt.using_query, re.IGNORECASE)
        input_rows = int(limit_match.group(1)) if limit_match else 1000

    # 2. Load cascade config
    cascade_info = _load_cascade_info(stmt.cascade_path)

    # 3. Estimate cost per row
    cost_per_row = _estimate_cost_per_row(
        cascade_info['model'],
        cascade_info['phases'],
        cascade_info['candidates']
    )

    # 4. Estimate cache hit rate
    cache_hit_rate = 0.0
    if check_cache:
        cache_hit_rate = _estimate_cache_hit_rate(
            stmt.cascade_path,
            stmt.using_query,
            duckdb_conn
        )

    # 5. Calculate total cost
    actual_llm_calls = int(input_rows * (1 - cache_hit_rate))
    total_cost = cost_per_row * actual_llm_calls

    # 6. Generate rewritten SQL
    from rvbbit.sql_rewriter import _rewrite_map
    rewritten_sql = _rewrite_map(stmt)

    return ExplainResult(
        input_rows=input_rows,
        parallelism=stmt.parallel,
        cascade_path=stmt.cascade_path,
        phases=cascade_info['phases'],
        model=cascade_info['model'],
        candidates=cascade_info['candidates'],
        cost_per_row=cost_per_row,
        total_cost=total_cost,
        cache_hit_rate=cache_hit_rate,
        rewritten_sql=rewritten_sql
    )


def _load_cascade_info(cascade_path: str) -> Dict[str, Any]:
    """Load cascade file and extract metadata."""
    # Resolve cascade path
    if not os.path.isabs(cascade_path):
        cascade_path = os.path.join(os.getcwd(), cascade_path)

    # Try with different extensions
    for ext in ['', '.yaml', '.yml', '.json']:
        full_path = cascade_path + ext
        if os.path.exists(full_path):
            cascade_path = full_path
            break

    if not os.path.exists(cascade_path):
        # Return defaults if cascade not found
        return {
            'phases': ['unknown'],
            'model': 'google/gemini-2.5-flash-lite',
            'candidates': 1
        }

    # Load cascade config
    try:
        import yaml

        with open(cascade_path, 'r') as f:
            if cascade_path.endswith('.json'):
                config = json.load(f)
            else:
                config = yaml.safe_load(f)
    except Exception:
        return {
            'phases': ['unknown'],
            'model': 'google/gemini-2.5-flash-lite',
            'candidates': 1
        }

    # Extract info
    cells = config.get('cells', [])
    phases = [cell.get('name', f'phase_{i}') for i, cell in enumerate(cells)]

    # Get model (first cell's model or default)
    model = cells[0].get('model') if cells else None
    if not model:
        from rvbbit.config import get_config
        model = get_config().default_model

    # Get candidates count
    candidates = 1
    if cells:
        candidates_config = cells[0].get('candidates', {})
        if isinstance(candidates_config, dict):
            factor = candidates_config.get('factor', 1)
            if isinstance(factor, int):
                candidates = factor
            # If factor is a string (Jinja template), estimate as 1

    return {
        'phases': phases,
        'model': model,
        'candidates': candidates
    }


def _estimate_cost_per_row(model: str, phases: List[str], candidates: int) -> float:
    """Estimate cost per row based on model pricing."""
    # Simplified pricing table (real implementation should query OpenRouter API)
    pricing_map = {
        'google/gemini-2.5-flash-lite': {'input': 0.000001, 'output': 0.000002},
        'google/gemini-2.0-flash-exp': {'input': 0.000001, 'output': 0.000002},
        'google/gemini-flash-1.5': {'input': 0.00000075, 'output': 0.000003},
        'anthropic/claude-sonnet-4.5': {'input': 0.000003, 'output': 0.000015},
        'anthropic/claude-opus-4.5': {'input': 0.000015, 'output': 0.000075},
        'anthropic/claude-haiku-4.5': {'input': 0.0000008, 'output': 0.000004},
    }

    prices = pricing_map.get(model, {'input': 0.000005, 'output': 0.000010})

    # Rough estimate: 500 prompt tokens, 200 completion tokens per phase
    # This is conservative - actual usage varies by instruction length
    prompt_tokens = 500
    completion_tokens = 200

    cost_per_phase = (prompt_tokens * prices['input'] + completion_tokens * prices['output'])
    cost_per_row = cost_per_phase * len(phases) * candidates

    return cost_per_row


def _estimate_cache_hit_rate(
    cascade_path: str,
    using_query: str,
    duckdb_conn
) -> float:
    """Estimate cache hit rate by sampling first 10 rows."""
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
    except:
        return 0.0  # Unknown cache status


def format_explain_result(result: ExplainResult) -> str:
    """Format ExplainResult as human-readable text."""
    lines = [
        "→ Query Plan:",
        f"  ├─ Input Rows: {result.input_rows}",
    ]

    if result.parallelism:
        lines.append(f"  ├─ Parallelism: {result.parallelism} workers (requested, currently sequential)")

    lines.extend([
        f"  ├─ Cascade: {result.cascade_path}",
        f"  │  ├─ Phases: {len(result.phases)} ({', '.join(result.phases)})",
        f"  │  ├─ Model: {result.model}",
        f"  │  ├─ Candidates: {result.candidates}",
        f"  │  └─ Cost Estimate: ${result.cost_per_row:.6f} per row → ${result.total_cost:.2f} total",
    ])

    if result.cache_hit_rate > 0:
        actual_calls = int(result.input_rows * (1 - result.cache_hit_rate))
        adjusted_cost = result.total_cost * (1 - result.cache_hit_rate)
        lines.append(f"  ├─ Cache Hit Rate: {result.cache_hit_rate:.0%} ({actual_calls} LLM calls, ${adjusted_cost:.2f} actual cost)")
    else:
        lines.append(f"  ├─ Cache Hit Rate: 0% (first run, all rows will call LLM)")

    lines.extend([
        "  └─ Rewritten SQL:",
        *[f"      {line}" for line in result.rewritten_sql.split('\n')[:10]]  # First 10 lines
    ])

    if len(result.rewritten_sql.split('\n')) > 10:
        lines.append("      ... (truncated)")

    return '\n'.join(lines)
