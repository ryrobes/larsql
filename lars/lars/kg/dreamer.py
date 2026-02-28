"""
Tier 2 LLM-based KG enrichment ("dreaming").

Walks the knowledge graph looking for entities that lack semantic
enrichment, builds context prompts from crawl YAML + Tier 1
observations, calls an LLM, and writes back:

  - Improved natural-language descriptions
  - Business domain tags
  - Data quality, relationship, and pattern observations

All writes go through db_adapter (parquet + CH shadow).
Re-running is additive: new observations are appended, descriptions
are updated, and a new dream_session is recorded.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Entities are enriched in priority order: tables first (most value),
# then schemas, then connections.  Columns are enriched indirectly
# through their parent table context.
_ENRICHMENT_PRIORITY = ["table", "schema", "connection"]

_SYSTEM_PROMPT = """\
You are a database analyst.  You are given structural metadata AND real
sample data from a database table and must produce semantic enrichment.

You will receive:
- Column schema (types, cardinality, ranges, top values)
- ACTUAL SAMPLE ROWS from the live database (when available)
- Existing observations (that you must NOT repeat)
- Related entities (other tables/columns with relationships)

Return ONLY a JSON object with these keys:

{
  "description": "A concise 1-3 sentence description of what this table
                   contains and its likely business purpose.",
  "domain_tags": ["tag1", "tag2"],
  "observations": [
    {
      "category": "domain|quality|relationship|pattern|usage",
      "content":  "One clear observation a data analyst would find useful.",
      "confidence": 0.0-1.0,
      "evidence_sql": "SELECT ... FROM table ... -- a SQL query that validates this observation",
      "contract_type": "invariant|trend|snapshot"
    }
  ]
}

Guidelines:
- description: Write the kind of description a data analyst would put in
  a data dictionary.  Mention the business domain, what a row represents,
  and key data points.  Ground this in the ACTUAL DATA you see.
- domain_tags: 2-5 short lowercase tags (e.g. "e-commerce", "geospatial",
  "time-series", "reference-data", "government", "music").
- observations: 3-8 observations.  Focus on insights from the REAL DATA:
  • What the actual values tell you about business meaning
  • Data quality issues visible in the sample (nulls, inconsistencies,
    suspicious values, encoding issues)
  • Patterns in the data (date ranges, value distributions, coded values
    and what they likely mean)
  • Relationships to other tables based on actual foreign key values
  • Temporal patterns, partitioning signals, or data freshness
  • Potential join strategies or denormalization notes
  • Anything surprising or noteworthy in the sample rows
- confidence: How sure you are (0.6 = educated guess, 0.8 = likely,
  0.95 = very confident).
- evidence_sql: A SQL query against the table (use the qualified table name
  from the header) that proves or validates the observation.  The query result
  should make the observation verifiable.  For example, if you observe
  "Class field has 3 distinct values", write:
  SELECT class, COUNT(*) FROM csv_files.bigfoot_sightings GROUP BY class
  Use simple, efficient SQL.  Omit if the observation can't be validated
  by a single query (e.g. domain tag observations).
- contract_type: How this observation should be monitored over time:
  • "invariant" — you expect this to always be true (e.g. "all values in
    column X are positive", "table has exactly 3 distinct classes").
    A change means something significant happened.
  • "trend" — this describes a directional pattern (e.g. "row count grows
    ~5% monthly", "average order value has been increasing").
    A reversal means the trend broke.
  • "snapshot" — this is a point-in-time fact (e.g. "table has 5,035 rows",
    "date range is 1968-2022").  Changes are expected and low-priority.
  Default to "snapshot" if unsure.  Use "invariant" sparingly — only for
  things that would genuinely surprise a data analyst if they changed.
- Do NOT repeat observations that are already provided as "existing".
- Be concrete and specific.  Reference actual values you see in the data.
- If sample data is provided, your observations MUST reference it.

Return ONLY the JSON object, no markdown fences or commentary.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _obs_id(entity_id: str, category: str, content: str) -> str:
    """Deterministic observation ID from entity + category + content.

    Same approach as Tier 1 extractor: hash-based IDs so re-running
    dreaming produces the same observation_ids and the dedup view
    collapses duplicates instead of accumulating them.
    """
    key = f"{entity_id}|{category}|{content}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _sample_table_data(entity: Dict[str, Any], crawl_data: Optional[Dict]) -> Optional[str]:
    """Query the actual database for sample rows via the pgwire pipeline.

    Uses safe_sql_run() which goes through lazy attach + LARS SQL rewrite,
    so it queries the real connected database — not just the LARS metadb.

    Returns a formatted text block of sample data, or None on failure.
    """
    try:
        from ..sql_tools.tools import safe_sql_run
    except ImportError:
        log.debug("Tier 2: safe_sql_run not available, skipping data sampling")
        return None

    # Build the qualified table reference for the SQL pipeline.
    # Priority: crawl YAML → entity properties_json → entity qualified_name
    sql_table_ref = None
    if crawl_data:
        sql_table_ref = crawl_data.get("sql_table_ref")

    if not sql_table_ref:
        # Try entity properties_json (set by extractor from crawl YAML)
        try:
            props = json.loads(entity.get("properties_json") or "{}")
            sql_table_ref = props.get("sql_table_ref")
        except (json.JSONDecodeError, TypeError):
            pass

    if not sql_table_ref:
        qname = entity.get("qualified_name", "")
        parts = qname.split(".")
        if len(parts) >= 2:
            # For the pgwire pipeline: connection_name.table_name
            # (or connection_name.schema.table_name for PG/MySQL)
            sql_table_ref = qname
        else:
            return None

    conn_name = entity.get("source_connection", "")
    if not conn_name:
        return None

    try:
        # Get a small sample — 5 rows is enough for the LLM to understand
        # the actual data shape. Use safe_sql_run for bounded output.
        result_json = safe_sql_run(
            sql=f"SELECT * FROM {sql_table_ref} LIMIT 5",
            connection=conn_name,
            row_limit=5,
            text_max_chars=200,
        )
        result = json.loads(result_json)

        if result.get("error"):
            log.debug("Tier 2: data sample failed for %s: %s", sql_table_ref, result["error"])
            return None

        # safe_sql_run returns: columns=[str], results=[{col: val}], rows=[[val]]
        results_list = result.get("results", [])
        col_names = result.get("columns", [])
        if not results_list or not col_names:
            return None

        # Format as a readable text table for the LLM
        lines = [f"### Sample data ({len(results_list)} rows from live database)"]
        # Header
        lines.append("| " + " | ".join(col_names) + " |")
        lines.append("| " + " | ".join(["---"] * len(col_names)) + " |")
        # Rows — use results (list of dicts) for reliable column access
        for row in results_list:
            vals = [str(row.get(cn, ""))[:80] for cn in col_names]
            lines.append("| " + " | ".join(vals) + " |")

        return "\n".join(lines)

    except Exception as e:
        log.debug("Tier 2: data sample exception for %s: %s", sql_table_ref, e)
        return None


def _load_crawl_yaml(samples_dir: str, entity: Dict[str, Any]) -> Optional[Dict]:
    """Load the crawl YAML for a table entity."""
    props = {}
    try:
        props = json.loads(entity.get("properties_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    qname = entity.get("qualified_name", "")
    parts = qname.split(".")
    if len(parts) < 2:
        return None

    conn_name = parts[0]
    table_name = parts[-1]

    # Try direct path: samples/{conn}/{table}.yaml
    candidates = [
        Path(samples_dir) / conn_name / f"{table_name}.yaml",
    ]
    # Also try with schema: samples/{conn}/{schema}/{table}.yaml  (unlikely but safe)
    if len(parts) == 3:
        schema_name = parts[1]
        candidates.insert(0, Path(samples_dir) / conn_name / schema_name / f"{table_name}.yaml")

    for p in candidates:
        if p.exists():
            try:
                with open(p) as fh:
                    return yaml.safe_load(fh)
            except Exception:
                continue
    return None


def _build_table_prompt(
    entity: Dict[str, Any],
    children: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    related: List[Dict[str, Any]],
    crawl_data: Optional[Dict],
    sample_data: Optional[str] = None,
) -> str:
    """Build the user prompt for enriching a table entity."""
    lines: List[str] = []

    # Header
    lines.append(f"## Table: {entity['qualified_name']}")
    props = {}
    try:
        props = json.loads(entity.get("properties_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass
    if props.get("row_count"):
        lines.append(f"Row count: {props['row_count']:,}")
    lines.append(f"Connection: {entity.get('source_connection', '?')}")
    lines.append("")

    # Columns — prefer crawl YAML for richer detail
    lines.append("### Columns")
    if crawl_data and crawl_data.get("columns"):
        for col in crawl_data["columns"]:
            col_name = col.get("name", "?")
            col_type = col.get("type", "?")
            nullable = "nullable" if col.get("nullable", True) else "NOT NULL"
            meta = col.get("metadata", {})
            parts = [f"- **{col_name}** ({col_type}, {nullable})"]
            if meta.get("distinct_count") is not None:
                parts.append(f"  distinct={meta['distinct_count']}")
            if meta.get("min") is not None:
                parts.append(f"  range=[{meta['min']} .. {meta.get('max', '?')}]")
            dist = meta.get("value_distribution", [])
            if dist:
                vals = [str(d.get("value")) for d in dist[:5]]
                parts.append(f"  top_values=[{', '.join(vals)}]")
            lines.append(" ".join(parts))
    elif children:
        for child in children:
            cp = {}
            try:
                cp = json.loads(child.get("properties_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            dtype = cp.get("data_type", "?")
            lines.append(f"- **{child['name']}** ({dtype})")
    lines.append("")

    # Sample data from the actual database
    if sample_data:
        lines.append(sample_data)
        lines.append("")

    # Existing observations (so the LLM doesn't repeat them)
    if observations:
        lines.append("### Existing observations (do NOT repeat these)")
        for obs in observations[:15]:
            lines.append(f"- [{obs.get('category', '?')}] {obs.get('content', '')}")
        lines.append("")

    # Related entities
    if related:
        lines.append("### Related entities")
        for rel in related[:10]:
            lines.append(
                f"- {rel.get('rel_type', '?')}: {rel.get('name', '?')} "
                f"({rel.get('entity_type', '?')}) — {rel.get('evidence', '')}"
            )
        lines.append("")

    return "\n".join(lines)


def _parse_llm_response(content: str) -> Optional[Dict]:
    """Parse the LLM JSON response, tolerating markdown fences."""
    text = content.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove first line (```json or ```) and last line (```)
        text_lines = text.split("\n")
        if text_lines[0].startswith("```"):
            text_lines = text_lines[1:]
        if text_lines and text_lines[-1].strip() == "```":
            text_lines = text_lines[:-1]
        text = "\n".join(text_lines)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "description" in data:
            return data
        return None
    except (json.JSONDecodeError, TypeError):
        log.warning("Tier 2: failed to parse LLM response as JSON")
        return None


# ---------------------------------------------------------------------------
# Core enrichment loop
# ---------------------------------------------------------------------------

def _find_candidates(
    query_fn,
    entity_types: List[str],
    max_entities: int = 0,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """Find entities that need Tier 2 enrichment.

    Returns entities that have no Tier 2 observations yet,
    ordered by priority (tables first).

    Args:
        max_entities: 0 = unlimited (all candidates), >0 = cap.
        force: If True, return ALL entities regardless of existing observations.
    """
    candidates: List[Dict[str, Any]] = []

    for etype in entity_types:
        if max_entities > 0 and len(candidates) >= max_entities:
            break

        limit_clause = ""
        if max_entities > 0:
            remaining = max_entities - len(candidates)
            limit_clause = f"LIMIT {int(remaining)}"

        if force:
            # Force mode: return all entities of this type
            sql = f"""
                SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
                       e.description, e.properties_json, e.source_connection
                FROM kg_entities e
                WHERE e.entity_type = '{etype}'
                ORDER BY e.name
                {limit_clause}
            """
        else:
            # Find entities that need enrichment:
            #  1) Never enriched (no Tier 2 observations), OR
            #  2) Description was clobbered by re-crawl (still generic Tier 1 pattern
            #     like "Table 'X' with N columns..." but has Tier 2 observations)
            sql = f"""
                SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
                       e.description, e.properties_json, e.source_connection
                FROM kg_entities e
                WHERE e.entity_type = '{etype}'
                  AND (
                      e.entity_id NOT IN (
                          SELECT DISTINCT entity_id FROM kg_observations
                          WHERE tier >= 2
                      )
                      OR (
                          e.description LIKE 'Table ''%'' with %% columns%%'
                          AND e.entity_id IN (
                              SELECT DISTINCT entity_id FROM kg_observations
                              WHERE tier >= 2
                          )
                      )
                  )
                ORDER BY e.name
                {limit_clause}
            """
        rows = query_fn(sql)
        candidates.extend(rows)

    return candidates


def _get_entity_context(query_fn, entity_id: str) -> Dict[str, Any]:
    """Get children, observations, and related entities for an entity."""
    eid_safe = entity_id.replace("'", "''")

    children = query_fn(f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               e.description, e.properties_json
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.target_id
        WHERE ed.source_id = '{eid_safe}' AND ed.rel_type = 'contains'
        ORDER BY e.name
    """)

    observations = query_fn(f"""
        SELECT observation_id, entity_id, level, category, content,
               confidence, tier
        FROM kg_observations
        WHERE (entity_id = '{eid_safe}'
               OR entity_ids_json LIKE '%{eid_safe}%')
          AND superseded_by IS NULL
        ORDER BY confidence DESC
    """)

    related = query_fn(f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               ed.rel_type, ed.confidence, ed.evidence
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.target_id
        WHERE ed.source_id = '{eid_safe}' AND ed.rel_type != 'contains'
        UNION ALL
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               ed.rel_type, ed.confidence, ed.evidence
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.source_id
        WHERE ed.target_id = '{eid_safe}' AND ed.rel_type != 'contains'
    """)

    return {"children": children, "observations": observations, "related": related}


def dream_tier2(
    max_entities: int = 0,
    model_tier: str = "standard",
    samples_dir: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Run Tier 2 LLM enrichment over the knowledge graph.

    Finds entities that lack Tier 2 observations, builds context
    from crawl YAML + existing KG data + real sample rows, calls
    the LLM for semantic enrichment, and writes results back.

    Args:
        max_entities: Max entities to enrich (0 = all, default).
        force: Re-enrich ALL entities, even those with existing Tier 2 observations.
        model_tier: LLM tier — "fast", "standard", "quality" (default "standard").
        samples_dir: Path to crawl samples. Auto-detected if None.
        dry_run: If True, build prompts but don't call the LLM.

    Returns:
        Summary dict with counts and costs.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel

    from ..agent import Agent
    from ..config import get_config
    from ..db_adapter import get_db_adapter
    from ..models import get_model_for_tier

    # Late import to reuse the _query helper from skills
    from .skills import _query as kg_query

    console = Console()
    cfg = get_config()
    db = get_db_adapter()
    if samples_dir is None:
        samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    model_name = get_model_for_tier(model_tier)
    dream_session_id = str(uuid.uuid4())
    now = _now()
    scope_label = f"tier2:all:model={model_tier}" if max_entities == 0 else f"tier2:max={max_entities}:model={model_tier}"

    # Record session start
    db.insert_rows("kg_dream_sessions", [{
        "session_id": dream_session_id,
        "tier": 2,
        "scope": scope_label,
        "status": "running",
        "entities_added": 0,
        "entities_updated": 0,
        "edges_added": 0,
        "observations_added": 0,
        "summary": None,
        "started_at": now,
        "completed_at": None,
    }])

    t0 = time.monotonic()
    total_observations = 0
    total_descriptions_updated = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    errors = 0
    sampled_count = 0

    try:
        # Find candidates
        candidates = _find_candidates(kg_query, _ENRICHMENT_PRIORITY, max_entities, force=force)
        log.info("Tier 2 dreaming: %d candidates found", len(candidates))

        if not candidates:
            summary = "Tier 2: no candidates — all entities already enriched"
            db.insert_rows("kg_dream_sessions", [{
                "session_id": dream_session_id, "tier": 2,
                "scope": scope_label,
                "status": "completed",
                "entities_added": 0, "entities_updated": 0,
                "edges_added": 0, "observations_added": 0,
                "summary": summary,
                "started_at": now, "completed_at": _now(),
            }])
            console.print("[dim]  ✓ All entities already enriched[/dim]")
            return {"session_id": dream_session_id, "candidates": 0, "summary": summary}

        if dry_run:
            prompts = []
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Building prompts (dry run)", total=len(candidates))
                for entity in candidates:
                    ctx = _get_entity_context(kg_query, entity["entity_id"])
                    crawl = _load_crawl_yaml(samples_dir, entity)
                    sample_data = _sample_table_data(entity, crawl)
                    prompt = _build_table_prompt(
                        entity, ctx["children"], ctx["observations"], ctx["related"],
                        crawl, sample_data=sample_data,
                    )
                    prompts.append({
                        "entity_id": entity["entity_id"],
                        "prompt_length": len(prompt),
                        "has_sample_data": sample_data is not None,
                        "prompt": prompt[:1000],
                    })
                    progress.advance(task)
            return {"session_id": dream_session_id, "dry_run": True, "candidates": len(candidates), "prompts": prompts}

        # --- Enrichment loop with Rich progress ---
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("[dim]{task.fields[status]}[/dim]"),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                "Dreaming",
                total=len(candidates),
                status="starting...",
            )

            for i, entity in enumerate(candidates):
                entity_id = entity["entity_id"]
                entity_name = entity.get("name", "?")
                progress.update(
                    task,
                    description=f"Dreaming [bold white]{entity_name}[/bold white]",
                    status=f"obs={total_observations} desc={total_descriptions_updated} err={errors} ${total_cost:.4f}",
                )

                try:
                    ctx = _get_entity_context(kg_query, entity_id)
                    crawl = _load_crawl_yaml(samples_dir, entity)

                    # Sample real data from the actual database via pgwire pipeline
                    sample_data = _sample_table_data(entity, crawl)
                    if sample_data:
                        sampled_count += 1

                    prompt = _build_table_prompt(
                        entity, ctx["children"], ctx["observations"], ctx["related"],
                        crawl, sample_data=sample_data,
                    )

                    agent = Agent(model=model_name, system_prompt=_SYSTEM_PROMPT)
                    response = agent.run(input_message=prompt)

                    total_tokens_in += response.get("tokens_in") or 0
                    total_tokens_out += response.get("tokens_out") or 0
                    total_cost += response.get("cost") or 0.0

                    enrichment = _parse_llm_response(response.get("content", ""))
                    if not enrichment:
                        log.warning("Tier 2: failed to parse enrichment for %s", entity_id)
                        errors += 1
                        progress.advance(task)
                        continue

                    # Persist enrichments
                    obs_rows = []
                    enrich_now = _now()

                    # Domain tags observation
                    tags = enrichment.get("domain_tags", [])
                    if tags:
                        domain_content = f"Domain tags: {', '.join(tags)}"
                        obs_rows.append({
                            "observation_id": _obs_id(entity_id, "domain", domain_content),
                            "entity_id": entity_id,
                            "entity_ids_json": json.dumps([entity_id]),
                            "level": entity["entity_type"],
                            "tier": 2,
                            "category": "domain",
                            "content": domain_content,
                            "confidence": 0.8,
                            "evidence_sql": None,
                            "evidence_hash": None,
                            "contract_type": None,
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": None,
                            "dream_session_id": dream_session_id,
                            "created_at": enrich_now,
                        })

                    # LLM-generated observations
                    for obs_data in enrichment.get("observations", []):
                        cat = obs_data.get("category", "general")
                        content = obs_data.get("content", "")
                        conf = min(max(float(obs_data.get("confidence", 0.7)), 0.0), 1.0)
                        if not content:
                            continue

                        # Evidence SQL and contract type (new: observation contracts)
                        evidence_sql = obs_data.get("evidence_sql") or None
                        contract_type = obs_data.get("contract_type") or None
                        if contract_type and contract_type not in ("invariant", "trend", "snapshot"):
                            contract_type = "snapshot"

                        # Compute evidence hash if we have SQL
                        evidence_hash = None
                        if evidence_sql:
                            try:
                                from ..sql_tools.tools import safe_sql_run
                                ev_result = safe_sql_run(
                                    sql=evidence_sql,
                                    connection=entity.get("source_connection", ""),
                                    row_limit=100,
                                    text_max_chars=500,
                                )
                                evidence_hash = hashlib.sha256(
                                    ev_result.encode()
                                ).hexdigest()[:16]
                            except Exception as e:
                                log.debug(
                                    "Tier 2: evidence SQL failed for %s: %s",
                                    entity_id, e,
                                )
                                # Keep the SQL but no hash — validator can retry

                        obs_rows.append({
                            "observation_id": _obs_id(entity_id, cat, content),
                            "entity_id": entity_id,
                            "entity_ids_json": json.dumps([entity_id]),
                            "level": entity["entity_type"],
                            "tier": 2,
                            "category": cat,
                            "content": content,
                            "confidence": conf,
                            "evidence_sql": evidence_sql,
                            "evidence_hash": evidence_hash,
                            "contract_type": contract_type,
                            "embedding": None,
                            "embedding_model": None,
                            "superseded_by": None,
                            "dream_session_id": dream_session_id,
                            "created_at": enrich_now,
                        })

                    if obs_rows:
                        db.insert_rows("kg_observations", obs_rows)
                        total_observations += len(obs_rows)

                    # Update entity description if the LLM produced a better one
                    new_desc = enrichment.get("description", "")
                    if new_desc and new_desc != entity.get("description", ""):
                        db.insert_rows("kg_entities", [{
                            "entity_id": entity_id,
                            "entity_type": entity["entity_type"],
                            "name": entity["name"],
                            "qualified_name": entity["qualified_name"],
                            "description": new_desc,
                            "properties_json": entity.get("properties_json"),
                            "source_connection": entity.get("source_connection"),
                            "embedding": None,
                            "embedding_model": None,
                            "tier": 2,
                            "discovered_at": enrich_now,
                            "updated_at": enrich_now,
                        }])
                        total_descriptions_updated += 1

                    log.debug(
                        "Tier 2: enriched %s — %d observations, desc=%s",
                        entity_id, len(obs_rows), bool(new_desc),
                    )

                except Exception as e:
                    log.warning("Tier 2: failed to enrich %s: %s", entity_id, e)
                    errors += 1

                progress.advance(task)

            # Final status update on the progress bar
            progress.update(
                task,
                description="Dreaming [bold green]complete[/bold green]",
                status=f"obs={total_observations} desc={total_descriptions_updated} err={errors} ${total_cost:.4f}",
            )

        # --- Summary table ---
        elapsed = time.monotonic() - t0
        summary = (
            f"Tier 2: {len(candidates)} entities, "
            f"{total_observations} observations, "
            f"{total_descriptions_updated} descriptions, "
            f"{errors} errors, "
            f"${total_cost:.4f}, {elapsed:.1f}s"
        )

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="dim")
        table.add_column(style="bold")
        table.add_row("Entities enriched", str(len(candidates)))
        table.add_row("  with live data", f"{sampled_count}/{len(candidates)}")
        table.add_row("Observations", str(total_observations))
        table.add_row("Descriptions", str(total_descriptions_updated))
        table.add_row("Errors", str(errors) if errors else "[green]0[/green]")
        table.add_row("Cost", f"${total_cost:.4f}")
        table.add_row("Time", f"{elapsed:.1f}s")
        table.add_row("Model", model_name)
        console.print(Panel(table, title="[bold cyan]🧠 Tier 2 Dream Summary", border_style="cyan", expand=False))

        db.insert_rows("kg_dream_sessions", [{
            "session_id": dream_session_id,
            "tier": 2,
            "scope": scope_label,
            "status": "completed",
            "entities_added": 0,
            "entities_updated": total_descriptions_updated,
            "edges_added": 0,
            "observations_added": total_observations,
            "summary": summary,
            "started_at": now,
            "completed_at": _now(),
        }])

        log.info("KG Tier 2: %s", summary)
        return {
            "session_id": dream_session_id,
            "candidates": len(candidates),
            "observations_added": total_observations,
            "descriptions_updated": total_descriptions_updated,
            "errors": errors,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "cost_usd": round(total_cost, 6),
            "elapsed_seconds": round(elapsed, 2),
            "summary": summary,
        }

    except Exception as e:
        elapsed = time.monotonic() - t0
        db.insert_rows("kg_dream_sessions", [{
            "session_id": dream_session_id,
            "tier": 2,
            "scope": scope_label,
            "status": "failed",
            "entities_added": 0,
            "entities_updated": total_descriptions_updated,
            "edges_added": 0,
            "observations_added": total_observations,
            "summary": f"Failed after {elapsed:.1f}s: {e}",
            "started_at": now,
            "completed_at": _now(),
        }])
        raise
