#!/usr/bin/env python3
"""
Benchmark sql_search/sql_rag_search under multi-process concurrency.

This complements scripts/benchmark_sql_search.py (thread-based) by using
ProcessPoolExecutor with spawn to mimic separate worker processes.

Usage:
  LARS_ROOT=~/.rvbbit/lars PYTHONPATH=lars \
    python3 scripts/benchmark_sql_search_process.py \
      --output benchmarks/sql_search/baseline-process.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import multiprocessing as mp
import os
import statistics as st
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PARALLEL = [1, 2, 4, 8, 10, 12]
BASE_QUERY = "tables with user information and email columns and signup data"
QUERY_BANK = [
    "customer tables with email and signup timestamps",
    "orders and payments with statuses and amounts",
    "products with inventory and pricing fields",
    "user session or login activity tables",
    "events table with user_id and created_at",
    "subscriptions and plan status fields",
    "accounts with billing and country columns",
    "support tickets with customer identifiers",
    "marketing attribution touchpoint tables",
    "churn or cancellation related tables",
    "revenue metrics tables by date",
    "table with order_line items and quantities",
    "user profile fields like name, email, phone",
    "invoice or billing tables with totals",
    "shipment or fulfillment status tables",
    "web analytics sessions and page views",
    "cohort analysis tables with signup_date",
    "refund and dispute transaction tables",
    "warehouse inventory movement tables",
    "returns and reverse logistics tables",
]


@dataclass
class LatencySummary:
    ok: int
    errors: int
    min: float
    mean: float
    p50: float
    p95: float
    p99: float
    max: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "min": round(self.min, 6),
            "mean": round(self.mean, 6),
            "p50": round(self.p50, 6),
            "p95": round(self.p95, 6),
            "p99": round(self.p99, 6),
            "max": round(self.max, 6),
        }


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * p))
    return sorted_values[idx]


def _summarize(samples: list[dict[str, Any]]) -> LatencySummary:
    lats = sorted(float(s["latency"]) for s in samples)
    ok = sum(1 for s in samples if bool(s.get("ok")))
    errors = len(samples) - ok
    if not lats:
        return LatencySummary(ok=ok, errors=errors, min=0.0, mean=0.0, p50=0.0, p95=0.0, p99=0.0, max=0.0)
    return LatencySummary(
        ok=ok,
        errors=errors,
        min=min(lats),
        mean=st.mean(lats),
        p50=_percentile(lats, 0.50),
        p95=_percentile(lats, 0.95),
        p99=_percentile(lats, 0.99),
        max=max(lats),
    )


def _build_query_sets(parallel: int, nonce: str) -> tuple[list[str], list[str]]:
    same = [BASE_QUERY for _ in range(parallel)]
    unique = [
        f"{QUERY_BANK[i % len(QUERY_BANK)]} process_bench_variant_{nonce}_{i}"
        for i in range(parallel)
    ]
    return same, unique


def _worker(task: tuple[str, str]) -> dict[str, Any]:
    bench_name, query = task
    t0 = time.perf_counter()

    try:
        from lars.sql_tools.tools import sql_rag_search, sql_search

        if bench_name == "sql_search":
            payload = sql_search(query, k=5, smart=False)
        elif bench_name == "sql_rag_search":
            payload = sql_rag_search(query, k=5, score_threshold=0.3)
        else:
            raise ValueError(f"Unknown benchmark name: {bench_name}")

        elapsed = time.perf_counter() - t0
        return {"ok": True, "latency": elapsed, "payload": payload}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"ok": False, "latency": elapsed, "error": str(e)}


def _run_parallel(
    bench_name: str,
    scenario: str,
    parallel: int,
    queries: list[str],
) -> dict[str, Any]:
    tasks = [(bench_name, q) for q in queries]
    ctx = mp.get_context("spawn")
    batch_start = time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=parallel, mp_context=ctx) as ex:
        results = list(ex.map(_worker, tasks))
    batch_elapsed = time.perf_counter() - batch_start

    summary = _summarize(results)
    error_messages = [r.get("error") for r in results if not r.get("ok")]
    error_messages = [e for e in error_messages if e]

    return {
        "name": f"{bench_name}:{scenario}",
        "parallel": parallel,
        "batch_elapsed_s": round(batch_elapsed, 6),
        "throughput_rps": round(parallel / batch_elapsed, 6) if batch_elapsed > 0 else None,
        "latency": summary.as_dict(),
        "errors_sample": error_messages[:5],
    }


def benchmark(output_path: Path, parallel_counts: list[int]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "python": sys.version,
        "lars_root_env": os.environ.get("LARS_ROOT"),
        "parallel_counts": parallel_counts,
        "mp_start_method": "spawn",
        "benchmarks": [],
    }

    run_nonce = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for bench_name in ("sql_search", "sql_rag_search"):
        for p in parallel_counts:
            same, unique = _build_query_sets(p, nonce=f"{run_nonce}_{bench_name}_{p}")
            report["benchmarks"].append(_run_parallel(bench_name, "same_query", p, same))
            report["benchmarks"].append(_run_parallel(bench_name, "unique_query", p, unique))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-process benchmark for sql_search/sql_rag_search.")
    parser.add_argument(
        "--output",
        type=str,
        default=f"benchmarks/sql_search/baseline-process-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--parallel",
        type=str,
        default="1,2,4,8,10,12",
        help="Comma-separated parallel counts",
    )
    args = parser.parse_args()

    parallel_counts = [int(x.strip()) for x in args.parallel.split(",") if x.strip()]
    output_path = Path(args.output)

    report = benchmark(output_path, parallel_counts)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "generated_at": report.get("generated_at"),
                "parallel_counts": parallel_counts,
                "benchmarks": len(report.get("benchmarks", [])),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
