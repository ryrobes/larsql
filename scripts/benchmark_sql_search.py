#!/usr/bin/env python3
"""
Benchmark sql_search/sql_rag_search and related components.

Produces a JSON report suitable for before/after backend experiments.

Usage:
  LARS_ROOT=~/.rvbbit/lars PYTHONPATH=lars \
    python3 scripts/benchmark_sql_search.py \
      --output benchmarks/sql_search/baseline.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import statistics as st
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


# Import from repo with PYTHONPATH=lars
from lars.db_adapter import get_db
from lars.rag.context import RagContext
from lars.rag.indexer import embed_texts
from lars.rag.store import search_chunks
from lars.sql_tools.config import load_discovery_metadata
from lars.sql_tools.sql_duckdb_index import (
    USE_DEDICATED_SQL_DUCKDB_INDEX,
    get_sql_index_meta,
)
from lars.sql_tools.tools import sql_rag_search, sql_search


DEFAULT_PARALLEL = [1, 2, 4, 8, 12, 16, 20]
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


def _run_parallel(
    name: str,
    parallel: int,
    queries: list[str],
    fn: Callable[[str], Any],
) -> dict[str, Any]:
    def one(query: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            payload = fn(query)
            elapsed = time.perf_counter() - t0
            return {"ok": True, "latency": elapsed, "payload": payload}
        except Exception as e:
            elapsed = time.perf_counter() - t0
            return {"ok": False, "latency": elapsed, "error": str(e)}

    batch_start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = [ex.submit(one, q) for q in queries]
        results = [f.result() for f in cf.as_completed(futs)]
    batch_elapsed = time.perf_counter() - batch_start

    summary = _summarize(results)
    error_messages = [r.get("error") for r in results if not r.get("ok")]
    error_messages = [e for e in error_messages if e]

    return {
        "name": name,
        "parallel": parallel,
        "batch_elapsed_s": round(batch_elapsed, 6),
        "throughput_rps": round(parallel / batch_elapsed, 6) if batch_elapsed > 0 else None,
        "latency": summary.as_dict(),
        "errors_sample": error_messages[:5],
    }


def _build_query_sets(parallel: int, nonce: str) -> tuple[list[str], list[str]]:
    same = [BASE_QUERY for _ in range(parallel)]
    unique = [
        f"{QUERY_BANK[i % len(QUERY_BANK)]} benchmark_variant_{nonce}_{i}"
        for i in range(parallel)
    ]
    return same, unique


def _discover_rag_context() -> tuple[str, str, int]:
    meta = load_discovery_metadata()
    if not meta:
        raise RuntimeError("No discovery metadata found. Run `lars sql chart` first.")

    rag_id = str(meta.rag_id)
    embed_model = str(meta.embed_model)
    if USE_DEDICATED_SQL_DUCKDB_INDEX:
        has_chunks, embedding_dim = get_sql_index_meta(rag_id)
        if not has_chunks:
            raise RuntimeError(
                f"Dedicated SQL index has no chunks for rag_id={rag_id}. Run `lars sql crawl` first."
            )
    else:
        rows = get_db().query(
            f"SELECT any(embedding_dim) as embedding_dim FROM rag_chunks WHERE rag_id = '{rag_id}' LIMIT 1"
        )
        embedding_dim = int(rows[0].get("embedding_dim") or 0) if rows else 0

    if embedding_dim <= 0:
        raise RuntimeError(f"Could not resolve embedding_dim for rag_id={rag_id}")
    return rag_id, embed_model, embedding_dim


def benchmark(output_path: Path, parallel_counts: list[int]) -> dict[str, Any]:
    rag_id, embed_model, embedding_dim = _discover_rag_context()
    rag_ctx = None
    if not USE_DEDICATED_SQL_DUCKDB_INDEX:
        rag_ctx = RagContext(
            rag_id=rag_id,
            directory="",
            embed_model=embed_model,
            embedding_dim=embedding_dim,
            stats={},
        )

    # Precompute one stable embedding for component-level vector-only benchmark.
    base_embed = embed_texts(
        texts=[BASE_QUERY],
        model=embed_model,
        session_id=None,
        trace_id=None,
        parent_id=None,
        cell_name="bench_sql_search",
        cascade_id=None,
    )
    base_vec = base_embed["embeddings"][0]
    base_dim = int(base_embed.get("dim") or len(base_vec))

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "python": sys.version,
        "lars_root_env": os.environ.get("LARS_ROOT"),
        "parallel_counts": parallel_counts,
        "backend": "dedicated_sql_duckdb" if USE_DEDICATED_SQL_DUCKDB_INDEX else "legacy_rag_store",
        "discovery": {
            "rag_id": rag_id,
            "embed_model": embed_model,
            "embedding_dim": embedding_dim,
        },
        "benchmarks": [],
    }

    run_nonce = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    def run_suite(label: str, fn: Callable[[str], Any]) -> None:
        for p in parallel_counts:
            same, unique = _build_query_sets(p, nonce=f"{run_nonce}_{label}_{p}")
            report["benchmarks"].append(_run_parallel(f"{label}:same_query", p, same, fn))
            report["benchmarks"].append(_run_parallel(f"{label}:unique_query", p, unique, fn))

    run_suite("sql_search", lambda q: sql_search(q, k=5, smart=False))
    run_suite("sql_rag_search", lambda q: sql_rag_search(q, k=5, score_threshold=0.3))
    run_suite(
        "embed_texts",
        lambda q: embed_texts(
            texts=[q],
            model=embed_model,
            session_id=None,
            trace_id=None,
            parent_id=None,
            cell_name="bench_embed",
            cascade_id=None,
        ),
    )
    if rag_ctx is not None:
        run_suite(
            "search_chunks_preembedded",
            lambda q: search_chunks(
                rag_ctx=rag_ctx,
                query=q,
                k=5,
                score_threshold=0.3,
                query_embedding=base_vec,
                query_embedding_dim=base_dim,
            ),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark sql_search/sql_rag_search performance.")
    parser.add_argument(
        "--output",
        type=str,
        default=f"benchmarks/sql_search/baseline-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--parallel",
        type=str,
        default="1,2,4,8,12,16,20",
        help="Comma-separated parallel counts",
    )
    args = parser.parse_args()

    parallel_counts = [int(x.strip()) for x in args.parallel.split(",") if x.strip()]
    output_path = Path(args.output)

    report = benchmark(output_path, parallel_counts)
    print(json.dumps({
        "output": str(output_path),
        "generated_at": report.get("generated_at"),
        "parallel_counts": parallel_counts,
        "benchmarks": len(report.get("benchmarks", [])),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
