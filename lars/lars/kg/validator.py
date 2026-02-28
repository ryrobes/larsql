"""
KG Contract Validator — Tier 3 observation validation.

Re-runs evidence_sql for observations with contracts, detects breaches
(result hash changed), and triggers investigation cascades for significant
changes.

Three contract types:
  - invariant: Expected to always hold. Breach = significant event.
  - trend: Directional pattern. Breach = trend reversal.
  - snapshot: Point-in-time fact. Breach = expected update, low priority.

Breach severity: invariant > trend > snapshot

Writes:
  - New "breach" observations with investigation findings
  - Supersedes old observations when contracts break
  - Updates evidence_hash for snapshot changes (quiet update)
"""

import hashlib
import json
import logging
import re
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


def _query(sql: str) -> List[Dict[str, Any]]:
    """Reuse KG query helper with CH routing + DuckDB fallback."""
    from .skills import _query as kg_query
    return kg_query(sql)


def _run_evidence(sql: str, connection: str) -> Optional[Dict[str, Any]]:
    """Execute an evidence SQL query and return result + hash.

    Returns:
        {"result_json": str, "hash": str, "row_count": int} or None on failure.
    """
    try:
        from ..sql_tools.tools import safe_sql_run
        result_json = safe_sql_run(
            sql=sql,
            connection=connection,
            row_limit=100,
            text_max_chars=500,
        )
        result = json.loads(result_json)
        if result.get("error"):
            log.debug("Evidence SQL error: %s", result["error"])
            return None
        # Hash only the data (results array) — must match dreamer's
        # hashing logic for stable comparison across runs.
        hash_payload = json.dumps(
            result.get("results", []),
            sort_keys=True,
            default=str,
        )
        result_hash = hashlib.sha256(hash_payload.encode()).hexdigest()[:16]
        return {
            "result_json": result_json,
            "hash": result_hash,
            "row_count": result.get("row_count", 0),
            "results": result.get("results", []),
            "columns": result.get("columns", []),
        }
    except Exception as e:
        log.debug("Evidence SQL execution failed: %s", e)
        return None


def _investigate_breach(
    observation: Dict[str, Any],
    old_hash: str,
    new_result: Dict[str, Any],
    entity: Dict[str, Any],
    model_tier: str = "fast",
) -> Optional[Dict[str, Any]]:
    """Run LLM investigation on a contract breach.

    Gives the LLM the original observation, the new evidence result,
    and asks it to explain what changed and why it matters.

    Returns:
        {"finding": str, "severity": str, "new_observation": str} or None.
    """
    from ..agent import Agent
    from ..models import get_model_for_tier

    model = get_model_for_tier(model_tier)
    contract_type = observation.get("contract_type", "snapshot")
    entity_name = entity.get("qualified_name", entity.get("name", "unknown"))

    system = (
        "You are a data analyst investigating a change in a database. "
        "An automated monitoring system detected that a previously-recorded "
        "observation about a table is no longer accurate. Your job is to "
        "explain what changed, why it matters, and whether it's concerning.\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "finding": "1-3 sentence explanation of what changed and why",\n'
        '  "severity": "critical|notable|minor",\n'
        '  "new_observation": "Updated observation text reflecting current state"\n'
        "}\n\n"
        "Severity guide:\n"
        "- critical: Data integrity issue, unexpected structural change, or "
        "business-impacting anomaly\n"
        "- notable: Interesting change worth flagging but not alarming\n"
        "- minor: Expected drift or routine update\n\n"
        "Return ONLY the JSON object, no markdown fences."
    )

    # Format new evidence as readable text
    new_data_lines = []
    results = new_result.get("results", [])
    columns = new_result.get("columns", [])
    if results and columns:
        new_data_lines.append("| " + " | ".join(columns) + " |")
        for row in results[:20]:
            vals = [str(row.get(c, ""))[:60] for c in columns]
            new_data_lines.append("| " + " | ".join(vals) + " |")
    new_data_text = "\n".join(new_data_lines) if new_data_lines else "(no rows returned)"

    prompt = (
        f"## Contract Breach Detected\n\n"
        f"**Table:** {entity_name}\n"
        f"**Contract type:** {contract_type}\n"
        f"**Original observation:** {observation.get('content', '')}\n"
        f"**Evidence SQL:** {observation.get('evidence_sql', '')}\n\n"
        f"**Previous result hash:** {old_hash}\n"
        f"**New result hash:** {new_result['hash']}\n\n"
        f"**Current query result ({new_result.get('row_count', 0)} rows):**\n"
        f"{new_data_text}\n\n"
        f"What changed? Is this concerning?"
    )

    try:
        agent = Agent(model=model, system_prompt=system)
        response = agent.run(input_message=prompt)
        content = (response.get("content") or "").strip()

        # Parse response
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        data = json.loads(content)
        return {
            "finding": data.get("finding", ""),
            "severity": data.get("severity", "minor"),
            "new_observation": data.get("new_observation", ""),
            "cost": response.get("cost", 0),
            "tokens_in": response.get("tokens_in", 0),
            "tokens_out": response.get("tokens_out", 0),
        }
    except Exception as e:
        log.warning("Investigation failed for %s: %s", observation.get("observation_id"), e)
        return None


def validate_contracts(
    contract_types: Optional[List[str]] = None,
    max_observations: int = 0,
    investigate: bool = True,
    model_tier: str = "fast",
    dry_run: bool = False,
    parallel: int = 1,
) -> Dict[str, Any]:
    """
    Validate observation contracts by re-running evidence SQL.

    Finds observations with evidence_sql and evidence_hash, re-runs
    the queries, and detects changes. For invariant and trend breaches,
    optionally runs an LLM investigation to explain what changed.

    Args:
        contract_types: Which types to validate (default: all).
            Options: ["invariant", "trend", "snapshot"]
        max_observations: Max observations to check (0 = all).
        investigate: Run LLM investigation on breaches (default True).
        model_tier: Model tier for investigation ("fast", "standard").
        dry_run: If True, check contracts but don't write findings.

    Returns:
        Summary dict with breach counts, findings, and costs.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.panel import Panel
    from rich.table import Table

    from ..db_adapter import get_db_adapter

    from ..skills.state_tools import set_current_session_id, set_current_cascade_id

    console = Console()
    db = get_db_adapter()
    now = _now()
    session_id = str(uuid.uuid4())

    # Set context so Agent.run() calls are logged under this session in unified_logs
    set_current_session_id(f"kg_validate_{session_id[:8]}")
    set_current_cascade_id("kg_validate")

    # Build filter clause
    type_filter = ""
    if contract_types:
        safe_types = [t.replace("'", "") for t in contract_types]
        type_filter = f"AND contract_type IN ({','.join(repr(t) for t in safe_types)})"

    limit_clause = f"LIMIT {int(max_observations)}" if max_observations > 0 else ""

    # Find observations with evidence contracts
    candidates = _query(f"""
        SELECT o.observation_id, o.entity_id, o.category, o.content,
               o.confidence, o.evidence_sql, o.evidence_hash, o.contract_type,
               o.tier, o.dream_session_id,
               e.qualified_name, e.source_connection, e.name AS entity_name
        FROM kg_observations o
        JOIN kg_entities e ON e.entity_id = o.entity_id
        WHERE o.evidence_sql IS NOT NULL
          AND o.evidence_hash IS NOT NULL
          AND o.superseded_by IS NULL
          {type_filter}
        ORDER BY
            CASE o.contract_type
                WHEN 'invariant' THEN 1
                WHEN 'trend' THEN 2
                WHEN 'snapshot' THEN 3
                ELSE 4
            END,
            o.confidence DESC
        {limit_clause}
    """)

    if not candidates:
        console.print("[dim]  ✓ No observations with evidence contracts to validate[/dim]")
        return {
            "session_id": session_id,
            "checked": 0,
            "breaches": 0,
            "summary": "No evidence contracts found",
        }

    # Progress tracker for UI polling
    from .progress import ProgressTracker
    progress_tracker = ProgressTracker("validate", session_id, total=len(candidates))

    # Track results
    checked = 0
    breaches = []
    unchanged = 0
    errors = 0
    total_cost = 0.0
    total_tokens_in = 0
    total_tokens_out = 0

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
            "Validating contracts",
            total=len(candidates),
            status="starting...",
        )

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        _counters_lock = threading.Lock()

        def _validate_one_obs(obs):
            """Validate a single observation — called from pool or sequentially."""
            nonlocal checked, unchanged, errors, total_cost, total_tokens_in, total_tokens_out

            obs_id = obs["observation_id"]
            entity_name = obs.get("entity_name", "?")
            contract_type = obs.get("contract_type", "snapshot")

            # Update cascade context per-entity for Studio traceability
            _qname = obs.get("qualified_name", entity_name)
            _safe_name = re.sub(r'[^a-zA-Z0-9_.]', '_', _qname)[:60]
            set_current_cascade_id(f"kg_validate:{_safe_name}")
            set_current_session_id(f"kg_validate_{session_id[:8]}:{_safe_name}")

            # Re-run evidence SQL
            new_result = _run_evidence(
                obs["evidence_sql"],
                obs.get("source_connection", ""),
            )

            if new_result is None:
                with _counters_lock:
                    errors += 1
                return None  # Signal: error

            with _counters_lock:
                checked += 1

            old_hash = obs.get("evidence_hash", "")

            if new_result["hash"] == old_hash:
                with _counters_lock:
                    unchanged += 1
                return None  # Signal: unchanged

            # ── CONTRACT BREACH ──
            breach_info = {
                "observation_id": obs_id,
                "entity_id": obs["entity_id"],
                "entity_name": obs.get("qualified_name", entity_name),
                "contract_type": contract_type,
                "original_observation": obs["content"],
                "old_hash": old_hash,
                "new_hash": new_result["hash"],
                "evidence_sql": obs["evidence_sql"],
                "finding": None,
                "severity": None,
                "new_observation": None,
            }

            # Investigate if enabled — ALL contract types including snapshots
            if investigate and not dry_run:
                entity_info = {
                    "qualified_name": obs.get("qualified_name"),
                    "name": entity_name,
                    "source_connection": obs.get("source_connection"),
                }
                finding = _investigate_breach(
                    obs, old_hash, new_result, entity_info, model_tier,
                )
                if finding:
                    breach_info["finding"] = finding["finding"]
                    breach_info["severity"] = finding["severity"]
                    breach_info["new_observation"] = finding["new_observation"]
                    with _counters_lock:
                        total_cost += finding.get("cost", 0)
                        total_tokens_in += finding.get("tokens_in", 0)
                        total_tokens_out += finding.get("tokens_out", 0)

                    # Write breach observation
                    breach_content = (
                        f"⚠️ CONTRACT BREACH ({contract_type}): "
                        f"{finding['finding']}"
                    )
                    breach_obs_id = _obs_id(
                        obs["entity_id"], "breach", breach_content,
                    )
                    db.insert_rows("kg_observations", [{
                        "observation_id": breach_obs_id,
                        "entity_id": obs["entity_id"],
                        "entity_ids_json": json.dumps([obs["entity_id"]]),
                        "level": "table",
                        "tier": 3,
                        "category": "breach",
                        "content": breach_content,
                        "confidence": 0.95,
                        "evidence_sql": obs["evidence_sql"],
                        "evidence_hash": new_result["hash"],
                        "contract_type": contract_type,
                        "embedding": None,
                        "embedding_model": None,
                        "superseded_by": None,
                        "dream_session_id": session_id,
                        "created_at": now,
                    }])

                    # Write updated observation if provided
                    if finding.get("new_observation"):
                        updated_obs_id = _obs_id(
                            obs["entity_id"],
                            obs["category"],
                            finding["new_observation"],
                        )
                        db.insert_rows("kg_observations", [{
                            "observation_id": updated_obs_id,
                            "entity_id": obs["entity_id"],
                            "entity_ids_json": obs.get(
                                "entity_ids_json",
                                json.dumps([obs["entity_id"]]),
                            ),
                            "level": "table",
                            "tier": 3,
                            "category": obs["category"],
                            "content": finding["new_observation"],
                            "confidence": obs.get("confidence", 0.8),
                            "evidence_sql": obs["evidence_sql"],
                            "evidence_hash": new_result["hash"],
                            "contract_type": contract_type,
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": None,
                            "dream_session_id": session_id,
                            "created_at": now,
                        }])

                        # Supersede the old observation
                        db.insert_rows("kg_observations", [{
                            "observation_id": obs_id,
                            "entity_id": obs["entity_id"],
                            "entity_ids_json": obs.get(
                                "entity_ids_json",
                                json.dumps([obs["entity_id"]]),
                            ),
                            "level": obs.get("level", "table"),
                            "tier": obs.get("tier", 2),
                            "category": obs["category"],
                            "content": obs["content"],
                            "confidence": obs.get("confidence", 0.8),
                            "evidence_sql": obs["evidence_sql"],
                            "evidence_hash": old_hash,
                            "contract_type": contract_type,
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": updated_obs_id,
                            "dream_session_id": obs.get(
                                "dream_session_id", session_id,
                            ),
                            "created_at": now,
                        }])
                else:
                    # No finding from investigation — just update hash
                    breach_info["severity"] = "minor"
                    breach_info["finding"] = "Snapshot updated (expected drift)"
                    db.insert_rows("kg_observations", [{
                        "observation_id": obs_id,
                        "entity_id": obs["entity_id"],
                        "entity_ids_json": obs.get(
                            "entity_ids_json",
                            json.dumps([obs["entity_id"]]),
                        ),
                        "level": obs.get("level", "table"),
                        "tier": obs.get("tier", 2),
                        "category": obs["category"],
                        "content": obs["content"],
                        "confidence": obs.get("confidence", 0.8),
                        "evidence_sql": obs["evidence_sql"],
                        "evidence_hash": new_result["hash"],
                        "contract_type": "snapshot",
                        "embedding": obs.get("embedding"),
                        "embedding_model": obs.get("embedding_model"),
                        "superseded_by": None,
                        "dream_session_id": obs.get(
                            "dream_session_id", session_id,
                        ),
                        "created_at": now,
                    }])

            return breach_info

        # Run observations — parallel or sequential
        effective_parallel = max(1, min(parallel, len(candidates)))
        if effective_parallel > 1:
            log.info("Validate: running %d observations with parallelism=%d", len(candidates), effective_parallel)
            futures = {}
            with ThreadPoolExecutor(max_workers=effective_parallel) as pool:
                for obs in candidates:
                    fut = pool.submit(_validate_one_obs, obs)
                    futures[fut] = obs

                for fut in as_completed(futures):
                    obs = futures[fut]
                    entity_name = obs.get("entity_name", "?")
                    try:
                        result = fut.result()
                        if result is not None:
                            breaches.append(result)
                    except Exception as e:
                        log.warning("Validate: exception for %s: %s", entity_name, e)
                        with _counters_lock:
                            errors += 1
                    progress.update(
                        task,
                        description=f"Validating [bold white]{entity_name}[/bold white]",
                        status=f"ok={unchanged} breach={len(breaches)} err={errors}",
                    )
                    progress_tracker.step(
                        checked + errors, entity_name=entity_name,
                        observations=unchanged, breaches=len(breaches),
                        errors=errors, cost=total_cost,
                    )
                    progress.advance(task)
        else:
            for obs in candidates:
                entity_name = obs.get("entity_name", "?")
                progress.update(
                    task,
                    description=f"Validating [bold white]{entity_name}[/bold white]",
                    status=f"ok={unchanged} breach={len(breaches)} err={errors}",
                )
                result = _validate_one_obs(obs)
                if result is not None:
                    breaches.append(result)
                progress_tracker.step(
                    checked + errors, entity_name=entity_name,
                    observations=unchanged, breaches=len(breaches),
                    errors=errors, cost=total_cost,
                )
                progress.advance(task)

        progress.update(
            task,
            description="Validating [bold green]complete[/bold green]",
            status=f"ok={unchanged} breach={len(breaches)} err={errors} ${total_cost:.4f}",
        )

    # ── Summary ──────────────────────────────────────────────────────
    progress_tracker.complete(
        observations=unchanged,
        breaches=len(breaches),
        errors=errors,
        cost=total_cost,
        detail={"checked": checked, "unchanged": unchanged},
    )

    invariant_breaches = [b for b in breaches if b["contract_type"] == "invariant"]
    trend_breaches = [b for b in breaches if b["contract_type"] == "trend"]
    snapshot_changes = [b for b in breaches if b["contract_type"] == "snapshot"]

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Checked", str(checked))
    table.add_row("Unchanged", f"[green]{unchanged}[/green]")
    table.add_row("Invariant breaches", f"[red]{len(invariant_breaches)}[/red]" if invariant_breaches else "0")
    table.add_row("Trend breaches", f"[yellow]{len(trend_breaches)}[/yellow]" if trend_breaches else "0")
    table.add_row("Snapshot changes", str(len(snapshot_changes)))
    table.add_row("Errors", str(errors) if errors else "[green]0[/green]")
    table.add_row("Investigation cost", f"${total_cost:.4f}")
    console.print(Panel(
        table,
        title="[bold cyan]🔍 Contract Validation Summary",
        border_style="cyan",
        expand=False,
    ))

    # Print critical findings
    for b in invariant_breaches + trend_breaches:
        if b.get("finding"):
            severity_color = "red" if b.get("severity") == "critical" else "yellow"
            console.print(
                f"\n  [{severity_color}]⚠️ {b['contract_type'].upper()} BREACH[/{severity_color}]"
                f" — {b['entity_name']}"
            )
            console.print(f"  [dim]Was:[/dim] {b['original_observation']}")
            console.print(f"  [bold]Finding:[/bold] {b['finding']}")
            if b.get("new_observation"):
                console.print(f"  [dim]Updated to:[/dim] {b['new_observation']}")

    return {
        "session_id": session_id,
        "checked": checked,
        "unchanged": unchanged,
        "breaches": len(breaches),
        "invariant_breaches": len(invariant_breaches),
        "trend_breaches": len(trend_breaches),
        "snapshot_changes": len(snapshot_changes),
        "errors": errors,
        "cost_usd": round(total_cost, 6),
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "findings": [
            {
                "entity": b["entity_name"],
                "contract_type": b["contract_type"],
                "severity": b.get("severity"),
                "finding": b.get("finding"),
                "original": b["original_observation"],
                "updated": b.get("new_observation"),
            }
            for b in breaches
            if b.get("finding")
        ],
    }
