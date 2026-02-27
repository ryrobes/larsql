"""
Knowledge Graph skills for LARS cascades and agents.

These are registered as LARS tools so any cascade can call them:
  - kg_search: Semantic search over entities and observations
  - kg_context: Get everything known about a table/entity
  - kg_related: Find related entities via graph edges
  - kg_observe: Add an observation (agents can contribute during normal work)
  - kg_stats: Get KG statistics
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from ..skill_registry import register_skill

log = logging.getLogger(__name__)


def _get_db():
    from ..db_adapter import get_db_adapter
    return get_db_adapter()


def _get_duck_conn():
    """Get a DuckDB connection with system views registered.

    Used as a safety-net fallback when db_adapter.query() fails
    (e.g., strict CH mode with no fallback).  Primary reads go
    through db_adapter which handles CH routing automatically.
    """
    from ..lars_db import get_lars_db
    return get_lars_db().get_cached_connection()


def _esc(val: str) -> str:
    """Escape a string value for SQL interpolation."""
    return str(val).replace("'", "''")


def _query(sql: str, params: list = None) -> List[Dict[str, Any]]:
    """Execute a KG read query with CH routing and DuckDB fallback.

    Primary path: db_adapter.query() — routes through ClickHouse when
    enabled (LARS_CH_READ_ENABLED=1), with automatic DuckDB fallback
    when LARS_CH_READ_FALLBACK_TO_DUCK=1.

    When the primary path returns *empty* results, also tries direct
    DuckDB → parquet to handle the case where CH tables exist but
    haven't been populated yet (migration period).  Once CH is fully
    caught up the DuckDB check is a cheap no-op.

    If db_adapter raises entirely (e.g., strict CH mode failure),
    falls back to direct DuckDB → parquet as a safety net.

    Writes still flow through db_adapter.insert_rows() for the
    normal parquet + CH shadow path.
    """
    # --- Primary path: db_adapter (CH routing + DuckDB) ---
    try:
        db = _get_db()
        result = db.query(sql, output_format="dict")
        if isinstance(result, list) and result:
            return result
        # Empty result — CH tables may not be populated yet, try DuckDB
    except Exception as e:
        log.debug("KG query via db_adapter failed, trying direct DuckDB: %s", e)

    # --- DuckDB fallback: covers both CH-empty and CH-error cases ---
    try:
        conn = _get_duck_conn()
        if params:
            result = conn.execute(sql, params).fetchall()
        else:
            result = conn.execute(sql).fetchall()
        if not result:
            return []
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        log.warning("KG query failed (both paths): %s — %s", sql[:200], e)
        return []


# ---------------------------------------------------------------------------
# kg_search
# ---------------------------------------------------------------------------

@register_skill("kg_search")
def kg_search(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    Search the knowledge graph for entities and observations matching a query.

    Uses SQL LIKE/ILIKE for Tier 1 (no embeddings yet). Will use vector
    similarity when Tier 2 embeddings are populated.

    Args:
        query: Search text (matched against name, qualified_name, description).
        entity_type: Optional filter: 'connection', 'schema', 'table', 'column'.
        limit: Max results (default 20).

    Returns:
        JSON string with matching entities and observations.
    """
    results = {"entities": [], "observations": []}

    like_pattern = _esc(query)
    type_filter = ""
    if entity_type:
        type_filter = f"AND entity_type = '{_esc(entity_type)}'"

    entity_sql = f"""
        SELECT entity_id, entity_type, name, qualified_name, description,
               properties_json, source_connection, tier
        FROM kg_entities
        WHERE (name ILIKE '%{like_pattern}%'
               OR qualified_name ILIKE '%{like_pattern}%'
               OR description ILIKE '%{like_pattern}%')
        {type_filter}
        ORDER BY
            CASE entity_type
                WHEN 'table' THEN 1
                WHEN 'column' THEN 2
                WHEN 'schema' THEN 3
                WHEN 'connection' THEN 4
                ELSE 5
            END,
            name
        LIMIT {int(limit)}
    """
    results["entities"] = _query(entity_sql)

    obs_sql = f"""
        SELECT observation_id, entity_id, level, category, content, confidence, tier
        FROM kg_observations
        WHERE content ILIKE '%{like_pattern}%'
        ORDER BY confidence DESC
        LIMIT {int(limit)}
    """
    results["observations"] = _query(obs_sql)

    return json.dumps(results, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_context
# ---------------------------------------------------------------------------

@register_skill("kg_context")
def kg_context(
    name: str,
    include_observations: bool = True,
    include_related: bool = True,
    depth: int = 1,
) -> str:
    """
    Get everything known about a named entity (table, column, connection, etc.).

    Retrieves the entity, its properties, observations, and immediate
    graph neighbors. This is the primary tool for enriching SQL generation
    with accumulated knowledge.

    Args:
        name: Entity name or qualified_name (e.g., 'customers' or 'postgres.public.customers').
        include_observations: Include observations about this entity (default True).
        include_related: Include related entities via edges (default True).
        depth: How many hops to traverse for related entities (default 1).

    Returns:
        JSON string with entity details, observations, and related entities.
    """
    result: Dict[str, Any] = {
        "entity": None,
        "children": [],
        "observations": [],
        "related": [],
    }

    safe_name = _esc(name)

    # Find the entity — match name, qualified_name, or entity_id
    entity_sql = f"""
        SELECT entity_id, entity_type, name, qualified_name, description,
               properties_json, source_connection, tier
        FROM kg_entities
        WHERE name = '{safe_name}'
           OR qualified_name = '{safe_name}'
           OR entity_id = 'table::{safe_name}'
           OR entity_id = 'col::{safe_name}'
           OR entity_id = 'conn::{safe_name}'
           OR entity_id = 'schema::{safe_name}'
        ORDER BY
            CASE entity_type
                WHEN 'table' THEN 1
                WHEN 'schema' THEN 2
                WHEN 'column' THEN 3
                WHEN 'connection' THEN 4
                ELSE 5
            END
        LIMIT 1
    """
    entities = _query(entity_sql)
    if not entities:
        return json.dumps({"error": f"Entity '{name}' not found"}, indent=2)

    entity = entities[0]
    result["entity"] = entity
    entity_id = _esc(entity["entity_id"])

    # Get children (entities this one contains)
    children_sql = f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               e.description, e.properties_json
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.target_id
        WHERE ed.source_id = '{entity_id}' AND ed.rel_type = 'contains'
        ORDER BY e.name
    """
    result["children"] = _query(children_sql)

    # Get observations — for tables/schemas/connections, also include
    # observations from child entities that reference this entity in
    # their entity_ids_json array (e.g., column observations that tag
    # their parent table).
    if include_observations:
        obs_sql = f"""
            SELECT observation_id, entity_id, level, category, content,
                   confidence, tier
            FROM kg_observations
            WHERE (entity_id = '{entity_id}'
                   OR entity_ids_json LIKE '%{entity_id}%')
              AND superseded_by IS NULL
            ORDER BY confidence DESC, created_at DESC
        """
        result["observations"] = _query(obs_sql)

    # Get related entities (non-containment edges)
    if include_related:
        related_sql = f"""
            SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
                   ed.rel_type, ed.confidence, ed.evidence
            FROM kg_edges ed
            JOIN kg_entities e ON e.entity_id = ed.target_id
            WHERE ed.source_id = '{entity_id}' AND ed.rel_type != 'contains'
            UNION ALL
            SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
                   ed.rel_type, ed.confidence, ed.evidence
            FROM kg_edges ed
            JOIN kg_entities e ON e.entity_id = ed.source_id
            WHERE ed.target_id = '{entity_id}' AND ed.rel_type != 'contains'
            ORDER BY confidence DESC
        """
        result["related"] = _query(related_sql)

    return json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_related
# ---------------------------------------------------------------------------

@register_skill("kg_related")
def kg_related(
    name: str,
    rel_type: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Find entities related to a named entity via graph edges.

    Args:
        name: Entity name or qualified_name.
        rel_type: Optional filter for relationship type (contains, likely_fk, same_name, ...).
        limit: Max results.

    Returns:
        JSON list of related entities with relationship info.
    """
    safe_name = _esc(name)

    # Resolve entity_id
    entity_sql = f"""
        SELECT entity_id FROM kg_entities
        WHERE name = '{safe_name}'
           OR qualified_name = '{safe_name}'
           OR entity_id = 'table::{safe_name}'
        LIMIT 1
    """
    entities = _query(entity_sql)
    if not entities:
        return json.dumps({"error": f"Entity '{name}' not found"})

    eid = _esc(entities[0]["entity_id"])

    rel_filter = ""
    if rel_type:
        rel_filter = f"AND ed.rel_type = '{_esc(rel_type)}'"

    sql = f"""
        SELECT
            CASE WHEN ed.source_id = '{eid}' THEN 'outgoing' ELSE 'incoming' END AS direction,
            ed.rel_type,
            ed.confidence,
            ed.evidence,
            CASE WHEN ed.source_id = '{eid}' THEN e_tgt.entity_id ELSE e_src.entity_id END AS related_id,
            CASE WHEN ed.source_id = '{eid}' THEN e_tgt.name ELSE e_src.name END AS related_name,
            CASE WHEN ed.source_id = '{eid}' THEN e_tgt.qualified_name ELSE e_src.qualified_name END AS related_qname,
            CASE WHEN ed.source_id = '{eid}' THEN e_tgt.entity_type ELSE e_src.entity_type END AS related_type
        FROM kg_edges ed
        LEFT JOIN kg_entities e_src ON e_src.entity_id = ed.source_id
        LEFT JOIN kg_entities e_tgt ON e_tgt.entity_id = ed.target_id
        WHERE (ed.source_id = '{eid}' OR ed.target_id = '{eid}')
        {rel_filter}
        ORDER BY ed.confidence DESC
        LIMIT {int(limit)}
    """

    return json.dumps(_query(sql), default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_observe
# ---------------------------------------------------------------------------

@register_skill("kg_observe")
def kg_observe(
    entity_name: str,
    content: str,
    category: str = "general",
    confidence: float = 0.8,
    tier: int = 2,
    _session_id: str = "",
    **kwargs,
) -> str:
    """
    Add an observation about an entity. Agents can call this during
    normal work to contribute knowledge to the graph.

    Args:
        entity_name: Name or qualified_name of the entity.
        content: The observation text.
        category: Category (cardinality, pattern, relationship, quality, domain, general).
        confidence: Confidence score 0-1.
        tier: Observation tier (default 2 for agent-contributed).

    Returns:
        JSON with the created observation ID.
    """
    db = _get_db()
    safe_name = _esc(entity_name)

    # Resolve entity
    entities = _query(
        f"SELECT entity_id, entity_type FROM kg_entities "
        f"WHERE name = '{safe_name}' OR qualified_name = '{safe_name}' LIMIT 1"
    )
    if not entities:
        return json.dumps({"error": f"Entity '{entity_name}' not found"})

    entity = entities[0]
    obs_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db.insert_rows("kg_observations", [{
        "observation_id": obs_id,
        "entity_id": entity["entity_id"],
        "entity_ids_json": json.dumps([entity["entity_id"]]),
        "level": entity["entity_type"],
        "tier": tier,
        "category": category,
        "content": content,
        "confidence": confidence,
        "embedding": None,
        "embedding_model": None,
        "superseded_by": None,
        "dream_session_id": _session_id or None,
        "created_at": now,
    }])

    return json.dumps({"observation_id": obs_id, "entity_id": entity["entity_id"]})


# ---------------------------------------------------------------------------
# kg_stats
# ---------------------------------------------------------------------------

@register_skill("kg_stats")
def kg_stats() -> str:
    """
    Get knowledge graph statistics.

    Returns:
        JSON with entity counts, edge counts, observation counts by tier.
    """
    stats: Dict[str, Any] = {}

    # Entity counts by type
    rows = _query("SELECT entity_type, COUNT(*) as cnt FROM kg_entities GROUP BY entity_type ORDER BY cnt DESC")
    stats["entities_by_type"] = {r["entity_type"]: r["cnt"] for r in rows}
    stats["total_entities"] = sum(stats["entities_by_type"].values())

    # Edge counts by type
    rows = _query("SELECT rel_type, COUNT(*) as cnt FROM kg_edges GROUP BY rel_type ORDER BY cnt DESC")
    stats["edges_by_type"] = {r["rel_type"]: r["cnt"] for r in rows}
    stats["total_edges"] = sum(stats["edges_by_type"].values())

    # Observation counts by tier
    rows = _query("SELECT tier, COUNT(*) as cnt FROM kg_observations GROUP BY tier ORDER BY tier")
    stats["observations_by_tier"] = {f"tier_{r['tier']}": r["cnt"] for r in rows}
    stats["total_observations"] = sum(stats["observations_by_tier"].values())

    # Latest dream session
    rows = _query("""
        SELECT session_id, tier, status, summary, started_at, completed_at
        FROM kg_dream_sessions
        ORDER BY started_at DESC
        LIMIT 1
    """)
    stats["latest_dream_session"] = rows[0] if rows else None

    return json.dumps(stats, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_dream
# ---------------------------------------------------------------------------

@register_skill("kg_dream")
def kg_dream(
    max_entities: int = 0,
    model_tier: str = "standard",
    dry_run: bool = False,
) -> str:
    """
    Run Tier 2 LLM enrichment over the knowledge graph ("dreaming").

    Finds entities (tables first) that lack Tier 2 observations, calls
    an LLM with rich schema context + real sample data, and writes back
    improved descriptions, domain tags, and semantic observations.

    Args:
        max_entities: Max entities to enrich (0 = all, default).
        model_tier: LLM tier — "fast", "standard", "quality" (default "standard").
        dry_run: If True, show what would be enriched without calling the LLM.

    Returns:
        JSON summary with counts, cost, and timing.
    """
    from .dreamer import dream_tier2
    result = dream_tier2(
        max_entities=int(max_entities),
        model_tier=model_tier,
        dry_run=bool(dry_run),
    )
    return json.dumps(result, default=str, indent=2)
