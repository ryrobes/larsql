#!/usr/bin/env python3
"""
Run a side-by-side SQL embedding bakeoff.

For each model:
1. Rebuild dedicated SQL DuckDB index from sql_connections/samples
2. Update discovery metadata to point sql_search/sql_rag_search at that index
3. Run quality panel (hit@1, hit@k, MRR)
4. Run thread/process latency benchmarks

Outputs:
- Per-model benchmark JSON files
- Consolidated summary JSON
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lars.config import get_config
from lars.sql_tools.config import (
    DiscoveryMetadata,
    load_discovery_metadata,
    save_discovery_metadata,
)
from lars.sql_tools.sql_duckdb_index import rebuild_sql_index, search_sql_index


QUALITY_PANEL = [
    {
        "query": "user emails and message content",
        "expected_any": ["enron_emails"],
    },
    {
        "query": "retail orders sales profit and discounts",
        "expected_any": ["superstore", "orders"],
    },
    {
        "query": "customer support tickets with status and priority",
        "expected_any": ["support_tickets"],
    },
    {
        "query": "products catalog with category and price",
        "expected_any": ["products", "superstore"],
    },
    {
        "query": "album tracks setlists and venues",
        "expected_any": ["tracks", "setlists", "locations_venue", "metallica_tracks", "metallica_setlists"],
    },
    {
        "query": "bigfoot sightings with latitude longitude and county",
        "expected_any": ["bigfoot_sightings_locations", "bigfoot_sightings"],
    },
    {
        "query": "US zip code and county reference data",
        "expected_any": ["us_zipcodes", "ref_us_zipcodes", "us_counties", "ref_us_counties"],
    },
    {
        "query": "ufo sightings with city state date duration",
        "expected_any": ["ufo_sightings"],
    },
    {
        "query": "crypto market prices and symbols",
        "expected_any": ["crypto"],
    },
    {
        "query": "air traffic passenger statistics by airport",
        "expected_any": ["air_traffic_passenger_statistics"],
    },
    {
        "query": "customer activity events and timestamps",
        "expected_any": ["activities"],
    },
    {
        "query": "orders joined to customers by customer_id",
        "expected_any": ["orders", "customers"],
    },
]


def _slug(model: str) -> str:
    return model.replace("/", "__").replace(":", "_").replace(" ", "_")


def _table_key_from_source(source: str) -> str:
    value = (source or "").replace("\\", "/")
    if value.endswith("_fields.yaml"):
        value = value[: -len("_fields.yaml")] + ".yaml"
    for suffix in (".yaml", ".yml", ".json"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.replace("/", ".").lower()


def _load_bench(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_row(report: dict[str, Any], name: str, parallel: int) -> dict[str, Any] | None:
    for row in report.get("benchmarks", []):
        if str(row.get("name")) == name and int(row.get("parallel") or 0) == int(parallel):
            return row
    return None


def _quality_eval(*, rag_id: str, embed_model: str, k: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    hit1 = 0
    hitk = 0
    mrr = 0.0

    for item in QUALITY_PANEL:
        query = str(item["query"])
        expected = [str(x).lower() for x in item["expected_any"]]

        results = search_sql_index(
            rag_id=rag_id,
            embed_model=embed_model,
            query=query,
            k=k,
            score_threshold=0.0,
            session_id=None,
            trace_id=None,
            parent_id=None,
            cell_name="sql_embed_bakeoff",
            cascade_id=None,
        )

        tables: list[str] = []
        scores: list[float] = []
        for r in results:
            key = _table_key_from_source(str(r.get("source") or ""))
            if key in tables:
                continue
            tables.append(key)
            try:
                scores.append(float(r.get("score") or 0.0))
            except Exception:
                scores.append(0.0)

        rank = None
        for idx, t in enumerate(tables, start=1):
            if any(exp in t for exp in expected):
                rank = idx
                break

        if rank == 1:
            hit1 += 1
        if rank is not None:
            hitk += 1
            mrr += 1.0 / float(rank)

        rows.append(
            {
                "query": query,
                "expected_any": expected,
                "top_tables": tables[:k],
                "top_scores": scores[:k],
                "match_rank": rank,
                "hit_at_1": rank == 1,
                f"hit_at_{k}": rank is not None,
            }
        )

    n = max(1, len(QUALITY_PANEL))
    return {
        "queries": len(QUALITY_PANEL),
        "k": k,
        "hit_at_1": hit1,
        f"hit_at_{k}": hitk,
        "hit_at_1_rate": hit1 / n,
        f"hit_at_{k}_rate": hitk / n,
        "mrr": mrr / n,
        "details": rows,
    }


def _run_cmd(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> float:
    t0 = time.perf_counter()
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    return time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description="SQL embedding model bakeoff.")
    parser.add_argument(
        "--models",
        type=str,
        default="openai/text-embedding-3-large,qwen/qwen3-embedding-8b",
        help="Comma-separated embedding model ids",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=f"benchmarks/sql_search/model-bakeoff-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        help="Directory for all outputs",
    )
    parser.add_argument(
        "--thread-parallel",
        type=str,
        default="1,4,8,12",
        help="Parallel counts for thread benchmark script",
    )
    parser.add_argument(
        "--process-parallel",
        type=str,
        default="1,2,4,8",
        help="Parallel counts for process benchmark script",
    )
    parser.add_argument(
        "--skip-process",
        action="store_true",
        help="Skip multi-process benchmark",
    )
    parser.add_argument(
        "--quality-k",
        type=int,
        default=5,
        help="Top-K for quality panel scoring",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        raise SystemExit("No models provided.")

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = get_config()
    samples_dir = str((Path(cfg.root_dir) / "sql_connections" / "samples").resolve())
    if not os.path.isdir(samples_dir):
        raise SystemExit(f"SQL samples dir not found: {samples_dir}")

    base_meta = load_discovery_metadata()

    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "lars")

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "lars_root": str(cfg.root_dir),
        "samples_dir": samples_dir,
        "models": models,
        "thread_parallel": args.thread_parallel,
        "process_parallel": args.process_parallel,
        "skip_process": bool(args.skip_process),
        "quality_k": int(args.quality_k),
        "runs": [],
    }

    for model in models:
        model_slug = _slug(model)
        model_dir = output_dir / model_slug
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n=== MODEL: {model} ===")
        run_row: dict[str, Any] = {
            "model": model,
            "slug": model_slug,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        rebuild_start = time.perf_counter()
        stats = rebuild_sql_index(
            samples_dir=samples_dir,
            embed_model=model,
            session_id=f"sql_embed_bakeoff_{int(time.time())}",
            trace_id=None,
            parent_id=None,
            cell_name="sql_embed_bakeoff",
            cascade_id=None,
        )
        run_row["rebuild_seconds"] = time.perf_counter() - rebuild_start
        run_row["index_stats"] = stats

        if base_meta:
            dbs = base_meta.databases_indexed
            table_count = int(base_meta.table_count)
            total_columns = int(base_meta.total_columns)
        else:
            dbs = []
            table_count = int(stats.get("doc_count") or 0)
            total_columns = 0

        save_discovery_metadata(
            DiscoveryMetadata(
                last_discovery=datetime.now().isoformat(),
                rag_id=str(stats["rag_id"]),
                databases_indexed=list(dbs),
                table_count=table_count,
                total_columns=total_columns,
                embed_model=str(stats["embed_model"]),
            )
        )

        quality = _quality_eval(
            rag_id=str(stats["rag_id"]),
            embed_model=str(stats["embed_model"]),
            k=int(args.quality_k),
        )
        quality_path = model_dir / "quality.json"
        quality_path.write_text(json.dumps(quality, indent=2, sort_keys=True), encoding="utf-8")
        run_row["quality_path"] = str(quality_path)
        run_row["quality_summary"] = {
            "hit_at_1_rate": quality["hit_at_1_rate"],
            f"hit_at_{args.quality_k}_rate": quality[f"hit_at_{args.quality_k}_rate"],
            "mrr": quality["mrr"],
        }
        print(
            f"quality: hit@1={quality['hit_at_1_rate']:.3f}, "
            f"hit@{args.quality_k}={quality[f'hit_at_{args.quality_k}_rate']:.3f}, "
            f"mrr={quality['mrr']:.3f}"
        )

        thread_path = model_dir / "thread.json"
        thread_cmd = [
            sys.executable,
            "scripts/benchmark_sql_search.py",
            "--parallel",
            args.thread_parallel,
            "--output",
            str(thread_path),
        ]
        print("running thread benchmark...")
        run_row["thread_bench_seconds"] = _run_cmd(thread_cmd, cwd=repo_root, env=env)
        run_row["thread_path"] = str(thread_path)

        thread_report = _load_bench(thread_path)
        thread_slice = {}
        for p in (1, 4, 8, 12):
            row = _extract_row(thread_report, "sql_search:unique_query", p)
            if row:
                thread_slice[str(p)] = row.get("latency", {})
        run_row["thread_sql_search_unique"] = thread_slice

        if not args.skip_process:
            process_path = model_dir / "process.json"
            process_cmd = [
                sys.executable,
                "scripts/benchmark_sql_search_process.py",
                "--parallel",
                args.process_parallel,
                "--output",
                str(process_path),
            ]
            print("running process benchmark...")
            run_row["process_bench_seconds"] = _run_cmd(process_cmd, cwd=repo_root, env=env)
            run_row["process_path"] = str(process_path)

            process_report = _load_bench(process_path)
            process_slice = {}
            for p in (1, 2, 4, 8):
                row = _extract_row(process_report, "sql_search:unique_query", p)
                if row:
                    process_slice[str(p)] = row.get("latency", {})
            run_row["process_sql_search_unique"] = process_slice

        run_row["completed_at"] = datetime.now(timezone.utc).isoformat()
        summary["runs"].append(run_row)

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nSummary written: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
