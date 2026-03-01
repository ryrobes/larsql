"""
Tier 1.5 Dimensional Fingerprinting.

Auto-generates evidence-backed observations for every table by running
simple SQL queries against the live data. No LLM needed — purely
deterministic.

Creates tight contracts that the validator can check:
  - Row counts (trend contract)
  - Distinct value sets for low-cardinality columns (invariant)
  - Date range boundaries (trend)
  - NULL counts for nullable columns (snapshot)
  - Key aggregate fingerprints (snapshot)

These are the observations that catch "a new student was added" or
"a new campus appeared" — things that LLM-generated observations
miss because they're too abstract.

Run after crawl, before dreaming. Cheap and fast.
"""

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _obs_id(entity_id: str, category: str, content: str) -> str:
    key = f"{entity_id}|{category}|{content}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _evidence_hash(results: list) -> str:
    """Hash just the results array for stable comparison."""
    payload = json.dumps(results, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _safe_run(sql: str, connection: str) -> Optional[Dict]:
    """Run SQL and return parsed result or None."""
    try:
        from ..sql_tools.tools import safe_sql_run
        result_json = safe_sql_run(
            sql=sql, connection=connection,
            row_limit=200, text_max_chars=500,
        )
        result = json.loads(result_json)
        if result.get("error"):
            return None
        return result
    except Exception as e:
        log.debug("Fingerprint SQL failed: %s", e)
        return None


def fingerprint_tables(
    max_tables: int = 0,
    connections: Optional[List[str]] = None,
    force: bool = False,
    parallel: int = 1,
) -> Dict[str, Any]:
    """
    Generate dimensional fingerprint observations for all tables.

    Creates evidence-backed observations that capture the current
    dimensional state of each table — row counts, value distributions,
    date ranges, null patterns.

    Args:
        max_tables: 0 = all, >0 = cap.
        connections: Filter to specific connections (default: all).
        force: Regenerate even if fingerprints already exist.

    Returns:
        Summary dict with counts.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn, MofNCompleteColumn, Progress,
        SpinnerColumn, TextColumn, TimeElapsedColumn,
    )
    from rich.panel import Panel
    from rich.table import Table

    from ..db_adapter import get_db_adapter
    from .skills import _query as kg_query
    from .progress import ProgressTracker

    console = Console()
    db = get_db_adapter()
    now = _now()
    session_id = str(uuid.uuid4())

    # Find table entities
    conn_filter = ""
    if connections:
        safe_conns = [c.replace("'", "") for c in connections]
        conn_filter = f"AND e.source_connection IN ({','.join(repr(c) for c in safe_conns)})"

    # Skip tables that already have fingerprint observations unless force
    fingerprint_filter = ""
    if not force:
        fingerprint_filter = """
            AND e.entity_id NOT IN (
                SELECT DISTINCT entity_id FROM kg_observations
                WHERE category = 'fingerprint' AND superseded_by IS NULL
            )
        """

    limit_clause = f"LIMIT {int(max_tables)}" if max_tables > 0 else ""

    candidates = kg_query(f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               e.description, e.properties_json, e.source_connection
        FROM kg_entities e
        WHERE e.entity_type = 'table'
          {conn_filter}
          {fingerprint_filter}
        ORDER BY e.name
        {limit_clause}
    """)

    if not candidates:
        console.print("[dim]  ✓ All tables already fingerprinted[/dim]")
        return {"session_id": session_id, "tables": 0, "observations": 0}

    tracker = ProgressTracker("fingerprint", session_id, total=len(candidates))
    t0 = time.monotonic()
    total_obs = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Fingerprinting", total=len(candidates),
            status="starting...",
        )

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        _counters_lock = threading.Lock()

        def _fingerprint_one_entity(i, entity):
            """Fingerprint a single table entity."""
            nonlocal total_obs, errors

            entity_id = entity["entity_id"]
            entity_name = entity.get("name", "?")
            qname = entity.get("qualified_name", "")
            conn = entity.get("source_connection", "")

            # Get sql_table_ref
            props = {}
            try:
                props = json.loads(entity.get("properties_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            sql_ref = props.get("sql_table_ref", qname)

            if not sql_ref or not conn:
                with _counters_lock:
                    errors += 1
                return entity_id, entity_name, 0

            obs_rows = []

            # ── 1. Row count ─────────────────────────────────────────
            row_sql = f"SELECT COUNT(*) as row_count FROM {sql_ref}"
            row_result = _safe_run(row_sql, conn)
            if row_result and row_result.get("results"):
                row_count = row_result["results"][0].get("row_count", 0)
                content = f"Table {qname} has {row_count:,} rows"
                obs_rows.append({
                    "observation_id": _obs_id(entity_id, "fingerprint", f"row_count:{qname}"),
                    "entity_id": entity_id,
                    "entity_ids_json": json.dumps([entity_id]),
                    "level": "table",
                    "tier": 1,
                    "category": "fingerprint",
                    "content": content,
                    "confidence": 1.0,
                    "evidence_sql": row_sql,
                    "evidence_hash": _evidence_hash(row_result["results"]),
                    "contract_type": "trend",
                    "embedding": None,
                    "embedding_model": None,
                    "superseded_by": None,
                    "dream_session_id": session_id,
                    "created_at": now,
                })

            # ── 2. Get column metadata for targeted fingerprints ─────
            eid_safe = entity_id.replace("'", "''")
            columns = kg_query(f"""
                SELECT e.name, e.properties_json
                FROM kg_edges ed
                JOIN kg_entities e ON e.entity_id = ed.target_id
                WHERE ed.source_id = '{eid_safe}' AND ed.rel_type = 'contains'
                  AND e.entity_type = 'column'
                ORDER BY e.name
            """)

            for col in columns:
                col_name = col.get("name", "")
                if not col_name:
                    continue
                cp = {}
                try:
                    cp = json.loads(col.get("properties_json") or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass

                distinct_count = cp.get("distinct_count")
                data_type = (cp.get("data_type") or "").upper()
                nullable = cp.get("nullable", True)

                # ── 2a. Low-cardinality value sets (≤50 distinct) ────
                if distinct_count is not None and 1 <= distinct_count <= 50:
                    val_sql = (
                        f'SELECT DISTINCT "{col_name}" as val '
                        f"FROM {sql_ref} "
                        f'WHERE "{col_name}" IS NOT NULL '
                        f'ORDER BY "{col_name}"'
                    )
                    val_result = _safe_run(val_sql, conn)
                    if val_result and val_result.get("results"):
                        values = [str(r.get("val", "")) for r in val_result["results"]]
                        content = (
                            f"Column {col_name} has {len(values)} distinct values: "
                            f"{', '.join(values[:30])}"
                            + (f" ... (+{len(values)-30} more)" if len(values) > 30 else "")
                        )
                        ctype = "invariant" if distinct_count <= 10 else "snapshot"

                        obs_rows.append({
                            "observation_id": _obs_id(entity_id, "fingerprint", f"values:{qname}.{col_name}"),
                            "entity_id": entity_id,
                            "entity_ids_json": json.dumps([entity_id]),
                            "level": "column",
                            "tier": 1,
                            "category": "fingerprint",
                            "content": content,
                            "confidence": 1.0,
                            "evidence_sql": val_sql,
                            "evidence_hash": _evidence_hash(val_result["results"]),
                            "contract_type": ctype,
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": None,
                            "dream_session_id": session_id,
                            "created_at": now,
                        })

                # ── 2b. Date range boundaries ────────────────────────
                if any(t in data_type for t in ["DATE", "TIMESTAMP", "TIME"]):
                    range_sql = (
                        f'SELECT MIN("{col_name}") as min_val, '
                        f'MAX("{col_name}") as max_val, '
                        f'COUNT(DISTINCT "{col_name}") as distinct_dates '
                        f"FROM {sql_ref} "
                        f'WHERE "{col_name}" IS NOT NULL'
                    )
                    range_result = _safe_run(range_sql, conn)
                    if range_result and range_result.get("results"):
                        r = range_result["results"][0]
                        content = (
                            f"Column {col_name} date range: "
                            f"{r.get('min_val')} to {r.get('max_val')} "
                            f"({r.get('distinct_dates', '?')} distinct)"
                        )
                        obs_rows.append({
                            "observation_id": _obs_id(entity_id, "fingerprint", f"daterange:{qname}.{col_name}"),
                            "entity_id": entity_id,
                            "entity_ids_json": json.dumps([entity_id]),
                            "level": "column",
                            "tier": 1,
                            "category": "fingerprint",
                            "content": content,
                            "confidence": 1.0,
                            "evidence_sql": range_sql,
                            "evidence_hash": _evidence_hash(range_result["results"]),
                            "contract_type": "trend",
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": None,
                            "dream_session_id": session_id,
                            "created_at": now,
                        })

                # ── 2c. NULL counts for nullable columns ─────────────
                if nullable and distinct_count is not None:
                    null_sql = (
                        f'SELECT COUNT(*) as total, '
                        f'COUNT("{col_name}") as non_null, '
                        f'COUNT(*) - COUNT("{col_name}") as null_count '
                        f"FROM {sql_ref}"
                    )
                    null_result = _safe_run(null_sql, conn)
                    if null_result and null_result.get("results"):
                        r = null_result["results"][0]
                        null_count = r.get("null_count", 0)
                        total = r.get("total", 0)
                        if total > 0 and null_count > 0:
                            pct = round(null_count / total * 100, 1)
                            content = (
                                f"Column {col_name}: {null_count:,} NULL values "
                                f"out of {total:,} rows ({pct}%)"
                            )
                            obs_rows.append({
                                "observation_id": _obs_id(entity_id, "fingerprint", f"nulls:{qname}.{col_name}"),
                                "entity_id": entity_id,
                                "entity_ids_json": json.dumps([entity_id]),
                                "level": "column",
                                "tier": 1,
                                "category": "fingerprint",
                                "content": content,
                                "confidence": 1.0,
                                "evidence_sql": null_sql,
                                "evidence_hash": _evidence_hash(null_result["results"]),
                                "contract_type": "snapshot",
                                "embedding": None,
                                "embedding_model": None,
                                "superseded_by": None,
                                "dream_session_id": session_id,
                                "created_at": now,
                            })

            # ── 3. Recent activity (if timestamp columns exist) ──────
            timestamp_cols = [
                col for col in columns
                if any(t in (json.loads(col.get("properties_json") or "{}").get("data_type") or "").upper()
                       for t in ["TIMESTAMP", "DATETIME"])
            ]
            if timestamp_cols:
                ts_col = None
                for tc in timestamp_cols:
                    name = tc.get("name", "").lower()
                    if name in ("created_at", "inserted_at", "created", "timestamp"):
                        ts_col = tc.get("name")
                        break
                if not ts_col:
                    ts_col = timestamp_cols[0].get("name")

                if ts_col:
                    recent_sql = (
                        f'SELECT COUNT(*) as recent_rows '
                        f"FROM {sql_ref} "
                        f"WHERE \"{ts_col}\" >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
                    )
                    recent_result = _safe_run(recent_sql, conn)
                    if recent_result and recent_result.get("results"):
                        recent_count = recent_result["results"][0].get("recent_rows", 0)
                        if recent_count > 0:
                            content = (
                                f"Table {qname}: {recent_count:,} rows added/modified "
                                f"in last 7 days (based on {ts_col})"
                            )
                            obs_rows.append({
                                "observation_id": _obs_id(entity_id, "fingerprint", f"recent:{qname}.{ts_col}"),
                                "entity_id": entity_id,
                                "entity_ids_json": json.dumps([entity_id]),
                                "level": "table",
                                "tier": 1,
                                "category": "fingerprint",
                                "content": content,
                                "confidence": 1.0,
                                "evidence_sql": recent_sql,
                                "evidence_hash": _evidence_hash(recent_result["results"]),
                                "contract_type": "trend",
                                "embedding": None,
                                "embedding_model": None,
                                "superseded_by": None,
                                "dream_session_id": session_id,
                                "created_at": now,
                            })

            # Persist
            if obs_rows:
                db.insert_rows("kg_observations", obs_rows)
                with _counters_lock:
                    total_obs += len(obs_rows)

            return entity_id, entity_name, len(obs_rows)

        # Run entities — parallel or sequential
        effective_parallel = max(1, min(parallel, len(candidates)))
        if effective_parallel > 1:
            futures = {}
            with ThreadPoolExecutor(max_workers=effective_parallel) as pool:
                for i, entity in enumerate(candidates):
                    fut = pool.submit(_fingerprint_one_entity, i, entity)
                    futures[fut] = (i, entity)

                for fut in as_completed(futures):
                    i, entity = futures[fut]
                    entity_name = entity.get("name", "?")
                    try:
                        fut.result()
                    except Exception as e:
                        log.warning("Fingerprint: exception for %s: %s", entity_name, e)
                        with _counters_lock:
                            errors += 1
                    progress.update(
                        task,
                        description=f"Fingerprinting [bold white]{entity_name}[/bold white]",
                        status=f"obs={total_obs} err={errors}",
                    )
                    tracker.step(
                        sum(1 for f in futures if f.done()),
                        entity_id=entity.get("entity_id", ""),
                        entity_name=entity_name,
                        observations=total_obs, errors=errors,
                    )
                    progress.advance(task)
        else:
            for i, entity in enumerate(candidates):
                entity_name = entity.get("name", "?")
                progress.update(
                    task,
                    description=f"Fingerprinting [bold white]{entity_name}[/bold white]",
                    status=f"obs={total_obs} err={errors}",
                )
                _fingerprint_one_entity(i, entity)
                tracker.step(
                    i + 1, entity_id=entity.get("entity_id", ""),
                    entity_name=entity_name,
                    observations=total_obs, errors=errors,
                )
                progress.advance(task)

        progress.update(
            task,
            description="Fingerprinting [bold green]complete[/bold green]",
            status=f"obs={total_obs} err={errors}",
        )

    tracker.complete(observations=total_obs, errors=errors)
    elapsed = time.monotonic() - t0

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Tables fingerprinted", str(len(candidates)))
    table.add_row("Observations created", str(total_obs))
    table.add_row("Errors", str(errors) if errors else "[green]0[/green]")
    table.add_row("Time", f"{elapsed:.1f}s")
    console.print(Panel(
        table,
        title="[bold cyan]📊 Fingerprint Summary",
        border_style="cyan",
        expand=False,
    ))

    return {
        "session_id": session_id,
        "tables": len(candidates),
        "observations": total_obs,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
    }
