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
import re
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
      "contract_type": "invariant|trend|snapshot",
      "related_tables": ["qualified.name.of.other.table"]
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
- **NEVER make observations about row counts, column counts, table structure,
  cardinality, nullability, or data types.**  These are metadata facts that
  are already captured elsewhere and become stale instantly.  BAD examples:
  "table has 3 rows", "column X has 5 distinct values", "student_id is
  nullable", "date range spans 5 years".  GOOD examples: "Students Bobby
  Bouchard and Sammy Sort share the yeye.com email domain, suggesting test
  accounts", "Ledger entries show a $500 payment followed by a $500 refund
  for enrollment E-001, which may indicate a billing correction", "The
  Austin campus handles 80% of enrollments despite being one of three
  locations".  Focus on what a data analyst would actually want to know:
  who are these entities, what do the values mean, what business patterns
  exist in the ACTUAL DATA.
- **Cross-table analysis**: If related tables are provided, make observations
  about the RELATIONSHIPS between tables.  Look for:
  • Join quality: Do FK values in this table all exist in the related table?
    Are there orphaned records?
  • Data consistency: Do shared columns (e.g. dates, categories) have
    consistent value ranges across tables?
  • Business insights: What does the JOIN tell you that neither table says alone?
    (e.g. "3 customers have no orders", "revenue per category shows electronics
    dominates at 60%")
  • Anomalies visible only through joins (e.g. orders referencing a deleted
    product, timestamps that don't align)
  Cross-table observations are the MOST valuable — prioritize them when
  related table context is available.  Use "relationship" as the category
  for cross-table observations.
  When writing evidence_sql for cross-table observations, use JOIN queries
  that reference both tables by their qualified names.
- related_tables: For cross-table observations, list the qualified names
  of the OTHER tables involved (not the primary table). This links the
  observation to all relevant entities.  Omit for single-table observations.

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


def _sample_join_data(
    entity: Dict[str, Any],
    related_table: Dict[str, Any],
    join_column: str,
) -> Optional[str]:
    """Run a sample join between two tables to show cross-table relationships.

    Returns a formatted text block or None on failure.
    """
    try:
        from ..sql_tools.tools import safe_sql_run
    except ImportError:
        return None

    src_ref = entity.get("qualified_name", "")
    tgt_ref = related_table.get("qualified_name", "")
    conn = entity.get("source_connection", "")

    if not src_ref or not tgt_ref or not conn:
        return None

    # Try a sample join showing a few rows
    sql = (
        f"SELECT a.*, b.* FROM {src_ref} a "
        f"JOIN {tgt_ref} b ON a.{join_column} = b.{join_column} "
        f"LIMIT 3"
    )

    try:
        result_json = safe_sql_run(
            sql=sql,
            connection=conn,
            row_limit=3,
            text_max_chars=300,
        )
        result = json.loads(result_json)
        if result.get("error"):
            return None

        results_list = result.get("results", [])
        col_names = result.get("columns", [])
        if not results_list or not col_names:
            return None

        lines = [f"### Sample join: {src_ref} ⟷ {tgt_ref} ON {join_column} ({len(results_list)} rows)"]
        lines.append("| " + " | ".join(col_names[:15]) + " |")
        lines.append("| " + " | ".join(["---"] * min(len(col_names), 15)) + " |")
        for row in results_list:
            vals = [str(row.get(cn, ""))[:50] for cn in col_names[:15]]
            lines.append("| " + " | ".join(vals) + " |")

        return "\n".join(lines)
    except Exception:
        return None


def _get_related_table_context(
    query_fn,
    related_entities: List[Dict[str, Any]],
    samples_dir: str,
    source_entity: Dict[str, Any],
) -> str:
    """Build rich context for related tables.

    For each related table, includes: description, key columns,
    observations, and optionally a sample join result.
    """
    lines: List[str] = []

    # Group related by actual table entities (skip columns for now,
    # but use FK column info to know what to join on)
    seen_tables = set()
    related_tables = []
    fk_columns = {}  # target_table_id -> source_column_name

    for rel in related_entities:
        # For likely_fk edges, the source is a column in our table,
        # and the target is the related table
        if rel.get("rel_type") == "likely_fk" and rel.get("entity_type") == "table":
            if rel["entity_id"] not in seen_tables:
                seen_tables.add(rel["entity_id"])
                related_tables.append(rel)
                # Extract column name from evidence
                evidence = rel.get("evidence", "")
                if "column '" in evidence:
                    col = evidence.split("column '")[1].split("'")[0]
                    fk_columns[rel["entity_id"]] = col

        # For same_name edges between columns, resolve to parent table
        elif rel.get("rel_type") == "same_name" and rel.get("entity_type") == "column":
            # The related column's parent table
            qname = rel.get("qualified_name", "")
            parts = qname.rsplit(".", 1)
            if len(parts) > 1:
                table_qname = parts[0]
                # Find the table entity
                table_rows = query_fn(f"""
                    SELECT entity_id, entity_type, name, qualified_name,
                           description, properties_json, source_connection
                    FROM kg_entities
                    WHERE qualified_name = '{table_qname.replace("'", "''")}'
                      AND entity_type = 'table'
                    LIMIT 1
                """)
                if table_rows and table_rows[0]["entity_id"] not in seen_tables:
                    seen_tables.add(table_rows[0]["entity_id"])
                    related_tables.append(table_rows[0])
                    fk_columns[table_rows[0]["entity_id"]] = rel.get("name", "")

    if not related_tables:
        return ""

    lines.append("### Related tables (explore cross-table patterns!)")
    lines.append("")

    for rel_table in related_tables[:5]:  # Cap at 5 to avoid token explosion
        rel_eid = rel_table["entity_id"]
        rel_eid_safe = rel_eid.replace("'", "''")

        lines.append(f"#### {rel_table.get('qualified_name', rel_table.get('name', '?'))}")

        # Description
        desc = rel_table.get("description", "")
        if desc:
            lines.append(f"Description: {desc}")

        # Row count
        try:
            rprops = json.loads(rel_table.get("properties_json") or "{}")
            if rprops.get("row_count"):
                lines.append(f"Row count: {rprops['row_count']:,}")
        except (json.JSONDecodeError, TypeError):
            pass

        # Key columns (compact)
        rel_children = query_fn(f"""
            SELECT e.name, e.properties_json
            FROM kg_edges ed
            JOIN kg_entities e ON e.entity_id = ed.target_id
            WHERE ed.source_id = '{rel_eid_safe}' AND ed.rel_type = 'contains'
              AND e.entity_type = 'column'
            ORDER BY e.name
        """)
        if rel_children:
            col_parts = []
            for ch in rel_children[:20]:
                cp = {}
                try:
                    cp = json.loads(ch.get("properties_json") or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
                dtype = cp.get("data_type", "?")
                dc = cp.get("distinct_count")
                col_str = f"{ch['name']} ({dtype})"
                if dc is not None:
                    col_str += f" [{dc} distinct]"
                col_parts.append(col_str)
            lines.append(f"Columns: {', '.join(col_parts)}")

        # Observations from related table
        rel_obs = query_fn(f"""
            SELECT category, content
            FROM kg_observations
            WHERE (entity_id = '{rel_eid_safe}'
                   OR entity_ids_json LIKE '%{rel_eid_safe}%')
              AND superseded_by IS NULL
              AND tier >= 2
            ORDER BY confidence DESC
            LIMIT 5
        """)
        if rel_obs:
            lines.append("Key observations:")
            for o in rel_obs:
                lines.append(f"  - [{o.get('category', '?')}] {o.get('content', '')[:200]}")

        # Sample data from related table
        rel_sample = _sample_table_data(rel_table, _load_crawl_yaml(samples_dir, rel_table))
        if rel_sample:
            lines.append(rel_sample)

        # Sample join if we know the join column
        join_col = fk_columns.get(rel_eid)
        if join_col:
            join_sample = _sample_join_data(source_entity, rel_table, join_col)
            if join_sample:
                lines.append(join_sample)

        lines.append("")

    return "\n".join(lines)


def _build_table_prompt(
    entity: Dict[str, Any],
    children: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    related: List[Dict[str, Any]],
    crawl_data: Optional[Dict],
    sample_data: Optional[str] = None,
    related_context: Optional[str] = None,
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

    # Related entities (brief list)
    if related:
        lines.append("### Related entities (graph edges)")
        for rel in related[:10]:
            lines.append(
                f"- {rel.get('rel_type', '?')}: {rel.get('name', '?')} "
                f"({rel.get('entity_type', '?')}) — {rel.get('evidence', '')}"
            )
        lines.append("")

    # Rich related table context (descriptions, columns, observations, sample joins)
    if related_context:
        lines.append(related_context)
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

    # Get relationships: direct edges from/to this entity PLUS
    # edges from this table's child columns (e.g. orders.customer_id → customers)
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
        UNION ALL
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               ed.rel_type, ed.confidence, ed.evidence
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.target_id
        WHERE ed.source_id IN (
            SELECT child.entity_id FROM kg_edges ce
            JOIN kg_entities child ON child.entity_id = ce.target_id
            WHERE ce.source_id = '{eid_safe}' AND ce.rel_type = 'contains'
              AND child.entity_type = 'column'
        ) AND ed.rel_type != 'contains'
    """)

    return {"children": children, "observations": observations, "related": related}


def dream_tier2(
    max_entities: int = 0,
    model_tier: str = "standard",
    samples_dir: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    fresh: bool = False,
    parallel: int = 1,
) -> Dict[str, Any]:
    """
    Run Tier 2 LLM enrichment over the knowledge graph.

    Finds entities that lack Tier 2 observations, builds context
    from crawl YAML + existing KG data + real sample rows, calls
    the LLM for semantic enrichment, and writes results back.

    Args:
        max_entities: Max entities to enrich (0 = all, default).
        force: Re-enrich ALL entities, even those with existing Tier 2 observations.
        fresh: Delete all existing Tier 2 observations before dreaming (clean slate).
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

    from ..skills.state_tools import set_current_session_id, set_current_cascade_id

    model_name = get_model_for_tier(model_tier)
    dream_session_id = str(uuid.uuid4())

    # Set context so Agent.run() calls are logged under this session in unified_logs
    set_current_session_id(f"kg_dream_{dream_session_id[:8]}")
    set_current_cascade_id("kg_dream")
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
        # Fresh mode: supersede existing Tier 2 observations for a clean slate
        # (Can't DELETE from dedup views — re-insert with superseded_by set instead)
        if fresh:
            force = True  # fresh implies force
            existing = db.query("""
                SELECT * FROM kg_observations
                WHERE tier IN (2, 3) AND superseded_by IS NULL
            """)
            if existing and not dry_run:
                console.print(f"[bold yellow]🧹 Fresh mode: superseding {len(existing)} Tier 2+3 observations[/bold yellow]")
                fresh_marker = f"fresh_{dream_session_id[:8]}"
                superseded_rows = []
                for row in existing:
                    row_copy = dict(row)
                    row_copy["superseded_by"] = fresh_marker
                    row_copy["created_at"] = _now()  # newer timestamp wins in dedup
                    superseded_rows.append(row_copy)
                # Batch insert in chunks to avoid huge single inserts
                chunk_size = 500
                for i in range(0, len(superseded_rows), chunk_size):
                    db.insert_rows("kg_observations", superseded_rows[i:i + chunk_size])
                console.print(f"[dim]  ✓ {len(existing)} observations superseded[/dim]")
            elif existing:
                console.print(f"[dim]  Fresh mode (dry-run): would supersede {len(existing)} Tier 2 observations[/dim]")

        # Find candidates
        candidates = _find_candidates(kg_query, _ENRICHMENT_PRIORITY, max_entities, force=force)
        log.info("Tier 2 dreaming: %d candidates found", len(candidates))

        # Progress tracker for UI visibility
        from .progress import ProgressTracker
        progress_tracker = ProgressTracker("dream", dream_session_id, total=len(candidates))

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
                    related_ctx = _get_related_table_context(
                        kg_query, ctx["related"], samples_dir, entity,
                    )
                    prompt = _build_table_prompt(
                        entity, ctx["children"], ctx["observations"], ctx["related"],
                        crawl, sample_data=sample_data, related_context=related_ctx,
                    )
                    prompts.append({
                        "entity_id": entity["entity_id"],
                        "prompt_length": len(prompt),
                        "has_sample_data": sample_data is not None,
                        "has_related_context": bool(related_ctx),
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

            import threading
            from concurrent.futures import ThreadPoolExecutor, as_completed

            _counters_lock = threading.Lock()

            def _dream_one_entity(i, entity):
                """Process a single entity — called from thread pool or sequentially."""
                nonlocal total_observations, total_descriptions_updated, total_tokens_in
                nonlocal total_tokens_out, total_cost, errors, sampled_count

                entity_id = entity["entity_id"]
                entity_name = entity.get("name", "?")

                # Update cascade context per-entity for Studio traceability
                _safe_name = re.sub(r'[^a-zA-Z0-9_.]', '_', entity.get("qualified_name", entity_name))[:60]
                set_current_cascade_id(f"kg_dream:{_safe_name}")
                set_current_session_id(f"kg_dream_{dream_session_id[:8]}:{_safe_name}")

                try:
                    ctx = _get_entity_context(kg_query, entity_id)
                    crawl = _load_crawl_yaml(samples_dir, entity)

                    # Sample real data from the actual database via pgwire pipeline
                    sample_data = _sample_table_data(entity, crawl)

                    # Build rich context from related tables
                    related_ctx = _get_related_table_context(
                        kg_query, ctx["related"], samples_dir, entity,
                    )

                    prompt = _build_table_prompt(
                        entity, ctx["children"], ctx["observations"], ctx["related"],
                        crawl, sample_data=sample_data, related_context=related_ctx,
                    )

                    agent = Agent(model=model_name, system_prompt=_SYSTEM_PROMPT)
                    response = agent.run(input_message=prompt)

                    enrichment = _parse_llm_response(response.get("content", ""))
                    if not enrichment:
                        log.warning("Tier 2: failed to parse enrichment for %s", entity_id)
                        with _counters_lock:
                            errors += 1
                        return entity_id, entity_name, False

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

                        evidence_sql = obs_data.get("evidence_sql") or None
                        contract_type = obs_data.get("contract_type") or None
                        if contract_type and contract_type not in ("invariant", "trend", "snapshot"):
                            contract_type = "snapshot"

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
                                ev_parsed = json.loads(ev_result)
                                hash_payload = json.dumps(
                                    ev_parsed.get("results", []),
                                    sort_keys=True,
                                    default=str,
                                )
                                evidence_hash = hashlib.sha256(
                                    hash_payload.encode()
                                ).hexdigest()[:16]
                            except Exception as e:
                                log.debug(
                                    "Tier 2: evidence SQL failed for %s: %s",
                                    entity_id, e,
                                )

                        entity_ids_list = [entity_id]
                        related_tables = obs_data.get("related_tables") or []
                        if related_tables and isinstance(related_tables, list):
                            for rt_name in related_tables[:5]:
                                rt_safe = str(rt_name).replace("'", "''")
                                rt_rows = kg_query(f"""
                                    SELECT entity_id FROM kg_entities
                                    WHERE qualified_name = '{rt_safe}'
                                      AND entity_type = 'table'
                                    LIMIT 1
                                """)
                                if rt_rows:
                                    entity_ids_list.append(rt_rows[0]["entity_id"])

                        obs_level = "cross_table" if len(entity_ids_list) > 1 else entity["entity_type"]

                        obs_rows.append({
                            "observation_id": _obs_id(entity_id, cat, content),
                            "entity_id": entity_id,
                            "entity_ids_json": json.dumps(entity_ids_list),
                            "level": obs_level,
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

                    new_desc = enrichment.get("description", "")
                    desc_updated = False
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
                        desc_updated = True

                    log.debug(
                        "Tier 2: enriched %s — %d observations, desc=%s",
                        entity_id, len(obs_rows), bool(new_desc),
                    )

                    with _counters_lock:
                        total_tokens_in += response.get("tokens_in") or 0
                        total_tokens_out += response.get("tokens_out") or 0
                        total_cost += response.get("cost") or 0.0
                        total_observations += len(obs_rows)
                        if desc_updated:
                            total_descriptions_updated += 1
                        if sample_data:
                            sampled_count += 1

                    return entity_id, entity_name, True

                except Exception as e:
                    log.warning("Tier 2: failed to enrich %s: %s", entity_id, e)
                    with _counters_lock:
                        errors += 1
                    return entity_id, entity_name, False

            # Run entities — parallel or sequential
            effective_parallel = max(1, min(parallel, len(candidates)))
            if effective_parallel > 1:
                log.info("Tier 2: running %d entities with parallelism=%d", len(candidates), effective_parallel)
                futures = {}
                with ThreadPoolExecutor(max_workers=effective_parallel) as pool:
                    for i, entity in enumerate(candidates):
                        fut = pool.submit(_dream_one_entity, i, entity)
                        futures[fut] = (i, entity)

                    for fut in as_completed(futures):
                        i, entity = futures[fut]
                        entity_name = entity.get("name", "?")
                        try:
                            fut.result()
                        except Exception:
                            pass
                        progress.update(
                            task,
                            description=f"Dreaming [bold white]{entity_name}[/bold white]",
                            status=f"obs={total_observations} desc={total_descriptions_updated} err={errors} ${total_cost:.4f}",
                        )
                        progress_tracker.step(
                            sum(1 for f in futures if f.done()),
                            entity_id=entity.get("entity_id", ""),
                            entity_name=entity_name,
                            observations=total_observations,
                            errors=errors,
                            cost=total_cost,
                        )
                        progress.advance(task)
            else:
                for i, entity in enumerate(candidates):
                    entity_name = entity.get("name", "?")
                    progress.update(
                        task,
                        description=f"Dreaming [bold white]{entity_name}[/bold white]",
                        status=f"obs={total_observations} desc={total_descriptions_updated} err={errors} ${total_cost:.4f}",
                    )
                    _dream_one_entity(i, entity)
                    progress_tracker.step(
                        i + 1,
                        entity_id=entity.get("entity_id", ""),
                        entity_name=entity_name,
                        observations=total_observations,
                        errors=errors,
                        cost=total_cost,
                    )
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

        progress_tracker.complete(
            observations=total_observations,
            errors=errors,
            cost=total_cost,
            detail={"summary": summary},
        )
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
