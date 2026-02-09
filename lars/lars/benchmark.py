"""
LARS Model Benchmark Runner

Runs semantic SQL operators against multiple models to find the cheapest
model that meets accuracy thresholds. Results stored in model_benchmarks table.
"""

import os
import uuid
import time
import json
import hashlib
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@dataclass
class BenchmarkResult:
    """Single benchmark run result."""
    benchmark_id: str
    run_id: str
    operator_id: str        # cascade_id
    operator_name: str      # SQL function name
    model_id: str
    input_hash: str
    input_tokens: int
    input_complexity: float
    input_sample: str       # truncated
    passed: bool
    output_value: str
    expected_value: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost: float
    provider: str
    created_at: str


def compute_complexity(operator_id: str, inputs: dict) -> float:
    """
    Score 0.0 (trivial) to 1.0 (complex).
    Fast heuristic — no LLM calls.
    """
    scores = []

    for key, value in inputs.items():
        v = str(value) if value is not None else ""

        # Length factor
        char_len = len(v)
        if char_len < 50:
            scores.append(0.1)
        elif char_len < 200:
            scores.append(0.3)
        elif char_len < 1000:
            scores.append(0.5)
        elif char_len < 5000:
            scores.append(0.7)
        else:
            scores.append(0.9)

        # Structural complexity
        if any(c in v for c in '{}[]<>'):
            scores.append(0.2)
        if v.count('\n') > 10:
            scores.append(0.2)
        if len(v.split()) > 100:
            scores.append(0.3)

    OPERATOR_BASE_COMPLEXITY = {
        "valid_single": 0.0,
        "fill_single": 0.1,
        "means": 0.2,
        "semantic_matches": 0.2,
        "implies": 0.3,
        "sentiment_single": 0.2,
        "summarize": 0.5,
        "parse": 0.4,
        "parse_name_single": 0.3,
        "ask_data": 0.6,
        "research": 0.8,
    }
    base = OPERATOR_BASE_COMPLEXITY.get(operator_id, 0.3)
    scores.append(base)

    return min(1.0, sum(scores) / max(len(scores), 1))


def _hash_input(inputs: dict) -> str:
    """Create a stable hash of inputs for dedup."""
    s = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _extract_provider(model_id: str) -> str:
    """Extract provider from model ID."""
    if model_id.startswith("ollama/") or model_id.startswith("ollama@"):
        return "ollama"
    if model_id.startswith("lmstudio/"):
        return "lmstudio"
    if model_id.startswith("anthropic-direct/"):
        return "anthropic-direct"
    if model_id.startswith("vertex_ai/"):
        return "vertex_ai"
    if model_id.startswith("bedrock/"):
        return "bedrock"
    if "/" in model_id:
        return model_id.split("/")[0]
    return "unknown"


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_benchmark_table(db):
    """Create the model_benchmarks table if it doesn't exist."""
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS model_benchmarks (
            benchmark_id    VARCHAR,
            run_id          VARCHAR,
            operator_id     VARCHAR,
            operator_name   VARCHAR,
            model_id        VARCHAR,
            input_hash      VARCHAR,
            input_tokens    INTEGER,
            input_complexity DOUBLE,
            input_sample    VARCHAR,
            passed          BOOLEAN,
            output_value    VARCHAR,
            expected_value  VARCHAR,
            latency_ms      DOUBLE,
            tokens_in       INTEGER,
            tokens_out      INTEGER,
            cost            DOUBLE,
            provider        VARCHAR,
            created_at      TIMESTAMP
        )
    """)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create benchmark table via db_adapter, trying direct: {e}[/yellow]")
        # Try direct DuckDB connection
        from .lars_db import LarsDB
        lars_db = LarsDB()
        conn = lars_db.get_cached_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_benchmarks (
                benchmark_id VARCHAR, run_id VARCHAR, operator_id VARCHAR,
                operator_name VARCHAR, model_id VARCHAR, input_hash VARCHAR,
                input_tokens INTEGER, input_complexity DOUBLE, input_sample VARCHAR,
                passed BOOLEAN, output_value VARCHAR, expected_value VARCHAR,
                latency_ms DOUBLE, tokens_in INTEGER, tokens_out INTEGER,
                cost DOUBLE, provider VARCHAR, created_at TIMESTAMP
            )
        """)


# ---------------------------------------------------------------------------
# Discover test cases from cascade YAMLs
# ---------------------------------------------------------------------------

def discover_test_cases(operators: List[str] = None) -> List[dict]:
    """
    Discover test cases from cascade YAML files.

    Returns list of dicts with:
      - operator_id: cascade_id
      - operator_name: SQL function name
      - test_sql: the SQL query
      - expected: expected value
      - description: test description
      - source_file: path to cascade YAML
    """
    import yaml
    from .config import get_config, get_builtin_cascades_dir

    cfg = get_config()

    cascade_dirs = [
        Path(get_builtin_cascades_dir()) / "semantic_sql",
        Path(cfg.cascades_dir) / "semantic_sql",
    ]

    test_cases = []
    seen_files = set()

    for cascade_dir in cascade_dirs:
        if not cascade_dir.exists():
            continue
        for yaml_file in sorted(cascade_dir.glob("*.cascade.yaml")):
            if yaml_file.name in seen_files:
                continue
            seen_files.add(yaml_file.name)

            try:
                with open(yaml_file) as f:
                    cascade = yaml.safe_load(f)

                cascade_id = cascade.get("cascade_id", "")
                sql_func = cascade.get("sql_function", {})
                func_name = sql_func.get("name", "")
                cases = sql_func.get("test_cases", [])

                # Filter by requested operators
                # Match against: function name, cascade_id, or SQL operator keywords
                if operators:
                    op_patterns = sql_func.get("operators", [])
                    # Extract keywords from operator patterns (e.g., "MEANS" from "{{ text }} MEANS {{ criterion }}")
                    op_keywords = set()
                    for pat in op_patterns:
                        for word in pat.split():
                            if not word.startswith("{"):
                                op_keywords.add(word.lower().strip("'\""))
                    match = (
                        func_name in operators
                        or cascade_id in operators
                        or any(op.lower() in op_keywords for op in operators)
                    )
                    if not match:
                        continue

                for tc in cases:
                    if tc.get("skip"):
                        continue

                    test_cases.append({
                        "operator_id": cascade_id,
                        "operator_name": func_name,
                        "test_sql": tc.get("sql", ""),
                        "expected": tc.get("expect", ""),
                        "description": tc.get("description", ""),
                        "source_file": str(yaml_file),
                    })
            except Exception as e:
                console.print(f"[yellow]Warning: Could not parse {yaml_file}: {e}[/yellow]")

    return test_cases


# ---------------------------------------------------------------------------
# Execute a single benchmark
# ---------------------------------------------------------------------------

def _init_ssql_session(session_id: str):
    """
    Initialize a DuckDB session with semantic SQL UDFs registered.
    Returns (conn, lock, rewriter_func).
    """
    from .sql_tools.session_db import get_session_db, get_session_lock
    from .sql_tools.udf import register_lars_udf, register_dynamic_sql_functions
    from .semantic_sql.registry import initialize_registry
    from .sql_rewriter import rewrite_lars_syntax

    initialize_registry(force=True)

    conn = get_session_db(session_id)
    lock = get_session_lock(session_id)

    with lock:
        register_lars_udf(conn)
        register_dynamic_sql_functions(conn)

    return conn, lock, rewrite_lars_syntax


def _execute_internal(sql: str, conn, lock, rewriter_func):
    """
    Execute SQL via internal DuckDB connection.
    Returns (actual_value, error_message or None)
    """
    try:
        rewritten_sql = rewriter_func(sql, duckdb_conn=conn)
        with lock:
            result = conn.execute(rewritten_sql)
            df = result.fetchdf()

        if df.empty:
            return None, None
        return df.iloc[0, 0], None
    except Exception as e:
        return None, str(e)


def _evaluate_expectation(actual, expect):
    """
    Evaluate if actual value matches expectation.
    Replicates the logic from cli.py cmd_sql_test.
    Returns (passed: bool, reason: str)
    """
    import re

    if actual is None:
        if expect is None:
            return True, "Both None"
        return False, f"Got None, expected {expect}"

    actual_str = str(actual).strip()
    actual_lower = actual_str.lower()

    # Literal expectation
    if not isinstance(expect, dict):
        if isinstance(expect, bool):
            actual_bool = actual_lower in ('true', '1', 'yes')
            if expect:
                return actual_bool, "Boolean match" if actual_bool else f"Expected True, got {actual}"
            else:
                return not actual_bool, "Boolean match" if not actual_bool else f"Expected False, got {actual}"

        if isinstance(expect, (int, float)):
            try:
                actual_num = float(actual)
                if abs(actual_num - expect) < 0.01:
                    return True, "Numeric match"
                return False, f"Expected {expect}, got {actual_num}"
            except (ValueError, TypeError):
                return False, f"Expected numeric {expect}, got {actual}"

        if str(expect).strip().lower() == actual_lower:
            return True, "Exact match"
        return False, f"Expected '{expect}', got '{actual}'"

    # Complex expectation types
    exp_type = expect.get('type')

    if exp_type == 'range':
        try:
            actual_num = float(actual)
            min_val = expect.get('min', float('-inf'))
            max_val = expect.get('max', float('inf'))
            if min_val <= actual_num <= max_val:
                return True, f"In range [{min_val}, {max_val}]"
            return False, f"Value {actual_num} not in range [{min_val}, {max_val}]"
        except (ValueError, TypeError):
            return False, f"Could not convert '{actual}' to number for range check"

    elif exp_type == 'contains':
        value = expect.get('value', '')
        if value.lower() in actual_lower:
            return True, f"Contains '{value}'"
        return False, f"'{actual}' does not contain '{value}'"

    elif exp_type == 'one_of':
        values = [str(v).strip().lower() for v in expect.get('values', [])]
        if actual_lower in values:
            return True, f"One of {expect.get('values')}"
        return False, f"'{actual}' not in {expect.get('values')}"

    elif exp_type == 'regex':
        pattern = expect.get('pattern', '')
        if re.search(pattern, actual_str):
            return True, f"Matches pattern '{pattern}'"
        return False, f"'{actual}' does not match pattern '{pattern}'"

    elif exp_type == 'json_contains':
        try:
            actual_json = json.loads(actual_str)
            for key, val in expect.get('fields', {}).items():
                if key not in actual_json:
                    return False, f"Missing key '{key}' in JSON"
                if val is not None and actual_json[key] != val:
                    return False, f"Key '{key}' expected '{val}', got '{actual_json[key]}'"
            return True, "JSON contains expected fields"
        except json.JSONDecodeError:
            return False, f"Could not parse as JSON: {actual_str[:50]}"

    return False, f"Unknown expectation type: {exp_type}"


def _run_single_benchmark(
    test_sql: str,
    model_id: str,
    expected,
    conn,
    lock,
    rewriter_func,
    verbose: bool = False,
) -> dict:
    """
    Run a single semantic SQL query with a specific model override.

    Overrides all model tiers via environment variables so the cascade
    uses the benchmark model regardless of which tier it references.

    Returns dict with: output, tokens_in, tokens_out, cost, error
    """
    # Override all model tiers to point at our benchmark model
    old_env = {}
    for tier in ["fast", "standard", "flagship"]:
        env_key = f"LARS_MODEL_{tier.upper()}"
        old_env[env_key] = os.environ.get(env_key)
        os.environ[env_key] = model_id

    # Disable cascade cache so each model gets fresh LLM calls
    old_env["LARS_BENCHMARK_NO_CACHE"] = os.environ.get("LARS_BENCHMARK_NO_CACHE")
    os.environ["LARS_BENCHMARK_NO_CACHE"] = "1"

    try:
        # Capture timestamp before execution for cost correlation
        from datetime import datetime, timezone
        t_before = datetime.now(timezone.utc)

        actual, error = _execute_internal(test_sql, conn, lock, rewriter_func)

        t_after = datetime.now(timezone.utc)

        if error:
            return {"output": None, "error": error, "tokens_in": 0, "tokens_out": 0, "cost": 0.0,
                    "t_before": t_before, "t_after": t_after}

        return {
            "output": actual,
            "error": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "t_before": t_before,
            "t_after": t_after,
        }
    finally:
        # Restore environment
        for key, val in old_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


# ---------------------------------------------------------------------------
# Cost backfill
# ---------------------------------------------------------------------------

def _backfill_costs(results: List['BenchmarkResult']):
    """
    Backfill cost/token data from the costs parquet table.

    Costs are batch-flushed with identical timestamps, so per-result
    time windows don't work. Instead:
    1. Get the full time window for each (operator, model) group
    2. Query total costs in that window
    3. Divide evenly across results in the group
    """
    try:
        from .lars_db import LarsDB
        from datetime import timezone as _tz

        lars_db = LarsDB()
        cost_conn = lars_db.get_cached_connection()

        # Group results by model_id
        from collections import defaultdict
        model_groups = defaultdict(list)
        for r in results:
            t_before = getattr(r, '_t_before', None)
            if t_before:
                model_groups[r.model_id].append(r)

        if not model_groups:
            return

        def _to_utc(dt):
            if dt.tzinfo is not None:
                return dt.astimezone(_tz.utc)
            return dt.replace(tzinfo=_tz.utc)

        # Use global time window (costs batch-flush after model finishes)
        all_t = [_to_utc(r._t_before) for r in results if getattr(r, '_t_before', None)]
        all_t += [_to_utc(r._t_after) for r in results if getattr(r, '_t_after', None)]
        if not all_t:
            return
        t_min = min(all_t)
        t_max = max(all_t)

        # Get all costs in the benchmark window
        all_costs = cost_conn.execute("""
            SELECT model, COALESCE(SUM(cost), 0), COALESCE(SUM(tokens_in), 0),
                   COALESCE(SUM(tokens_out), 0), COUNT(*)
            FROM costs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY model
        """, [t_min, t_max]).fetchall()

        if not all_costs:
            return

        # Build model→costs lookup (cost model names may differ from benchmark names)
        model_costs = {}
        for model, cost, tok_in, tok_out, n in all_costs:
            model_costs[model] = (float(cost), int(tok_in), int(tok_out))

        backfilled = 0
        for model_id, group in model_groups.items():
            # Try exact match first, then fuzzy match on model substring
            costs = model_costs.get(model_id)
            if not costs:
                # Fuzzy: benchmark uses "anthropic/claude-sonnet-4" but costs have "anthropic/claude-4-sonnet-20250522"
                # Strategy: match on provider + all significant name parts
                bench_parts = set(model_id.replace("/", "-").split("-"))
                bench_parts.discard("")  # remove empties
                best_match = None
                best_score = 0
                for cost_model, cost_data in model_costs.items():
                    # Exact substring match (either direction)
                    if model_id in cost_model or cost_model in model_id:
                        best_match = cost_data
                        break
                    # Part overlap scoring — require at least 3 matching parts
                    # to avoid "claude" matching everything
                    cost_parts = set(cost_model.replace("/", "-").split("-"))
                    cost_parts.discard("")
                    overlap = len(bench_parts & cost_parts)
                    if overlap >= 3 and overlap > best_score:
                        best_score = overlap
                        best_match = cost_data
                if best_match:
                    costs = best_match

            if not costs or (costs[0] == 0 and costs[1] == 0):
                continue

            total_cost, total_in, total_out = costs
            n_results = len(group)
            per_cost = total_cost / n_results
            per_in = total_in // n_results
            per_out = total_out // n_results
            for r in group:
                r.cost = per_cost
                r.tokens_in = per_in
                r.tokens_out = per_out
                backfilled += 1

        if backfilled > 0:
            console.print(f"[dim]Backfilled costs for {backfilled}/{len(results)} results[/dim]")

    except Exception as e:
        console.print(f"[yellow]Cost backfill failed (non-fatal): {e}[/yellow]")


# ---------------------------------------------------------------------------
# Store results
# ---------------------------------------------------------------------------

def _store_results(results: List[BenchmarkResult]):
    """Store benchmark results as parquet via LarsDB."""
    from .lars_db import LarsDB

    lars_db = LarsDB()
    
    rows = []
    for r in results:
        rows.append({
            "benchmark_id": str(r.benchmark_id), "run_id": str(r.run_id),
            "operator_id": str(r.operator_id), "operator_name": str(r.operator_name),
            "model_id": str(r.model_id), "input_hash": str(r.input_hash),
            "input_tokens": int(r.input_tokens or 0),
            "input_complexity": float(r.input_complexity or 0.0),
            "input_sample": str(r.input_sample or ""),
            "passed": bool(r.passed),
            "output_value": str(r.output_value or ""),
            "expected_value": str(r.expected_value or ""),
            "latency_ms": float(r.latency_ms or 0.0),
            "tokens_in": int(r.tokens_in or 0),
            "tokens_out": int(r.tokens_out or 0),
            "cost": float(r.cost or 0.0),
            "provider": str(r.provider or ""),
            "created_at": datetime.fromisoformat(r.created_at) if isinstance(r.created_at, str) else r.created_at,
        })
    
    lars_db.write("model_benchmarks", rows)
    console.print(f"[green]Stored {len(results)} benchmark results[/green]")


# ---------------------------------------------------------------------------
# Run benchmark sweep
# ---------------------------------------------------------------------------

def run_benchmark(
    operators: List[str] = None,
    models: List[str] = None,
    verbose: bool = False,
) -> str:
    """
    Run benchmark sweep.

    Args:
        operators: List of operator/function names to benchmark (None = all)
        models: List of model IDs to test
        verbose: Show detailed output

    Returns:
        run_id for this benchmark batch
    """
    run_id = f"bench_{uuid.uuid4().hex[:12]}"

    # Discover test cases
    test_cases = discover_test_cases(operators)
    if not test_cases:
        console.print("[red]No test cases found for specified operators[/red]")
        return run_id

    console.print(f"\n[bold cyan]LARS Model Benchmark[/bold cyan]")
    console.print(f"Run ID: {run_id}")
    console.print(f"Test cases: {len(test_cases)}")
    console.print(f"Models: {', '.join(models)}")
    console.print(f"Total runs: {len(test_cases) * len(models)}\n")

    # Initialize ssql session once
    session_id = f"bench-{uuid.uuid4().hex[:8]}"
    try:
        conn, lock, rewriter_func = _init_ssql_session(session_id)
    except Exception as e:
        console.print(f"[red]Failed to initialize semantic SQL session: {e}[/red]")
        return run_id

    results = []

    for model_id in models:
        console.print(f"\n[bold]Model: {model_id}[/bold]")

        for tc in test_cases:
            start_time = time.time()

            try:
                result = _run_single_benchmark(
                    test_sql=tc["test_sql"],
                    model_id=model_id,
                    expected=tc["expected"],
                    conn=conn,
                    lock=lock,
                    rewriter_func=rewriter_func,
                    verbose=verbose,
                )

                latency_ms = (time.time() - start_time) * 1000

                if result.get("error"):
                    passed = False
                    reason = result["error"]
                    output_val = result["error"]
                else:
                    passed, reason = _evaluate_expectation(
                        result.get("output"),
                        tc["expected"],
                    )
                    output_val = str(result.get("output", ""))

                complexity = compute_complexity(
                    tc["operator_id"],
                    {"input": tc["test_sql"]},
                )

                status_icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
                desc = tc["description"] or tc["test_sql"][:40]
                console.print(f"  {status_icon} {desc}")
                if verbose and not passed:
                    console.print(f"      [dim]{reason}[/dim]")

                br = BenchmarkResult(
                    benchmark_id=uuid.uuid4().hex[:16],
                    run_id=run_id,
                    operator_id=tc["operator_id"],
                    operator_name=tc["operator_name"],
                    model_id=model_id,
                    input_hash=_hash_input({"sql": tc["test_sql"]}),
                    input_tokens=len(tc["test_sql"].split()) * 2,
                    input_complexity=complexity,
                    input_sample=tc["test_sql"][:200],
                    passed=passed,
                    output_value=output_val[:500],
                    expected_value=str(tc["expected"])[:500],
                    latency_ms=latency_ms,
                    tokens_in=result.get("tokens_in", 0),
                    tokens_out=result.get("tokens_out", 0),
                    cost=result.get("cost", 0.0),
                    provider=_extract_provider(model_id),
                    created_at=datetime.utcnow().isoformat(),
                )
                # Stash execution timestamps for cost backfill
                br._t_before = result.get("t_before")
                br._t_after = result.get("t_after")
                results.append(br)

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                console.print(f"  [red]✗ {tc.get('description', 'unknown')}: ERROR - {e}[/red]")

                br = BenchmarkResult(
                    benchmark_id=uuid.uuid4().hex[:16],
                    run_id=run_id,
                    operator_id=tc["operator_id"],
                    operator_name=tc["operator_name"],
                    model_id=model_id,
                    input_hash=_hash_input({"sql": tc["test_sql"]}),
                    input_tokens=0,
                    input_complexity=0.0,
                    input_sample=tc["test_sql"][:200],
                    passed=False,
                    output_value=str(e)[:500],
                    expected_value=str(tc["expected"])[:500],
                    latency_ms=latency_ms,
                    tokens_in=0,
                    tokens_out=0,
                    cost=0.0,
                    provider=_extract_provider(model_id),
                    created_at=datetime.utcnow().isoformat(),
                )
                results.append(br)

            # Memory cleanup between runs
            try:
                from .echo import cleanup_all_echoes
                cleanup_all_echoes()
            except Exception:
                pass

    # Backfill costs from the costs table
    # Costs are written asynchronously with variable latency, retry until stable
    if results:
        import time as _time
        _time.sleep(3)
        _backfill_costs(results)
        # Retry once more after additional wait for stragglers
        unfilled = sum(1 for r in results if r.cost == 0.0 and r.provider not in ("ollama", "lmstudio"))
        if unfilled > 0:
            _time.sleep(5)
            _backfill_costs(results)

    # Store results
    if results:
        _store_results(results)

    # Print summary
    _print_summary(results, run_id)

    return run_id


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _print_summary(results: List[BenchmarkResult], run_id: str):
    """Print benchmark summary table."""
    if not results:
        console.print("[yellow]No results to summarize.[/yellow]")
        return

    groups = defaultdict(list)
    for r in results:
        groups[(r.operator_name, r.model_id)].append(r)

    table = Table(title=f"Benchmark Results — {run_id}")
    table.add_column("Operator", style="cyan")
    table.add_column("Model", style="white")
    table.add_column("Passed", justify="center")
    table.add_column("Accuracy", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Avg Cost", justify="right")

    for (op, model), runs in sorted(groups.items()):
        passed = sum(1 for r in runs if r.passed)
        total = len(runs)
        accuracy = (passed / total * 100) if total > 0 else 0
        avg_latency = sum(r.latency_ms for r in runs) / total
        avg_cost = sum(r.cost for r in runs) / total

        acc_style = "green" if accuracy >= 90 else "yellow" if accuracy >= 70 else "red"

        table.add_row(
            op,
            model,
            f"{passed}/{total}",
            f"[{acc_style}]{accuracy:.0f}%[/{acc_style}]",
            f"{avg_latency:.0f}ms",
            f"${avg_cost:.6f}",
        )

    console.print()
    console.print(table)


def print_routing_report():
    """Print the current routing recommendations based on all benchmark data."""
    from .lars_db import LarsDB

    lars_db = LarsDB()
    conn = lars_db.get_cached_connection()

    try:
        results = conn.execute("""
            SELECT
                operator_name,
                model_id,
                provider,
                COUNT(*) as total_runs,
                SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_count,
                ROUND(SUM(CASE WHEN passed THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as accuracy_pct,
                ROUND(AVG(cost), 6) as avg_cost,
                ROUND(AVG(latency_ms), 0) as avg_latency_ms
            FROM model_benchmarks
            GROUP BY operator_name, model_id, provider
            HAVING COUNT(*) >= 1
            ORDER BY operator_name, avg_cost ASC
        """).fetchall()
    except Exception:
        console.print("[yellow]No benchmark data found. Run 'lars benchmark' first.[/yellow]")
        return

    if not results:
        console.print("[yellow]No benchmark data found. Run 'lars benchmark' first.[/yellow]")
        return

    # Find cheapest model per operator meeting 90% accuracy
    recommendations = {}
    for row in results:
        op = row[0]
        if op not in recommendations and row[5] >= 90.0:
            recommendations[op] = row

    if recommendations:
        table = Table(title="Model Routing Recommendations (≥90% accuracy, cheapest)")
        table.add_column("Operator", style="cyan")
        table.add_column("Recommended Model", style="green")
        table.add_column("Accuracy", justify="right")
        table.add_column("Avg Cost", justify="right")
        table.add_column("Avg Latency", justify="right")
        table.add_column("Runs", justify="right")

        for op, row in sorted(recommendations.items()):
            table.add_row(
                row[0],
                row[1],
                f"{row[5]}%",
                f"${row[6]:.6f}",
                f"{row[7]:.0f}ms",
                str(row[3]),
            )

        console.print()
        console.print(table)

    # Full breakdown
    full_table = Table(title="Full Benchmark Results (all models)")
    full_table.add_column("Operator", style="cyan")
    full_table.add_column("Model")
    full_table.add_column("Runs", justify="right")
    full_table.add_column("Accuracy", justify="right")
    full_table.add_column("Avg Cost", justify="right")
    full_table.add_column("Avg Latency", justify="right")

    for row in results:
        acc = row[5]
        acc_style = "green" if acc >= 90 else "yellow" if acc >= 70 else "red"
        full_table.add_row(
            row[0], row[1], str(row[3]),
            f"[{acc_style}]{acc}%[/{acc_style}]",
            f"${row[6]:.6f}", f"{row[7]:.0f}ms",
        )

    console.print()
    console.print(full_table)
