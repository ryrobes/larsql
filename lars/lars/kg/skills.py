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
# kg_search — 2-stage vector-powered semantic schema discovery
# ---------------------------------------------------------------------------

def _embed_query(query: str) -> tuple:
    """Embed a search query once, returning (vector, dim) or (None, 0).

    Reused by both entity search (Stage 1) and observation search
    (Stage 2) so we only pay the embedding API cost once per query.
    """
    from ..config import get_config
    from ..rag.indexer import embed_texts

    cfg = get_config()
    embed_model = cfg.default_embed_model
    if not embed_model:
        log.warning("kg_search: no embedding model configured")
        return None, 0

    try:
        result = embed_texts(
            texts=[query],
            model=embed_model,
            session_id="kg_search",
            cell_name="kg_search_query",
            cascade_id="kg_system",
        )
        vec = result.get("embeddings", [[]])[0]
        dim = result.get("dim", 0)
        return (vec, dim) if vec else (None, 0)
    except Exception as e:
        log.warning("kg_search: query embedding failed (%s: %s)", type(e).__name__, e)
        return None, 0


def _kg_vector_search(
    query: str,
    k: int = 10,
    query_vec: Optional[List[float]] = None,
    embed_dim: int = 0,
) -> List[Dict[str, Any]]:
    """Stage 1: Vector similarity search over KG entity embeddings.

    Finds the top-k table entities by cosine similarity to the query.

    If query_vec is provided, uses it directly (avoids re-embedding).
    Otherwise embeds the query internally for backward compatibility.

    Returns ranked list of entity dicts with match_score.
    """
    # All embedding checks use DuckDB directly — embeddings are stored in
    # parquet and array_cosine_similarity is a DuckDB function.  Going
    # through _query() can hit ClickHouse where embeddings may be NULL.
    conn = _get_duck_conn()

    # Check if any entities have embeddings
    try:
        check = conn.execute("SELECT COUNT(*) as cnt FROM kg_entities WHERE embedding IS NOT NULL").fetchone()
        cnt = check[0] if check else 0
    except Exception as e:
        log.warning("kg_search: entity embedding check failed: %s", e)
        cnt = 0
    if cnt == 0:
        log.warning("kg_search: no embedded entities found (cnt=0 in DuckDB)")
        return []

    # Get embedding dimension from first embedded entity
    try:
        dim_row = conn.execute("SELECT array_length(embedding, 1) as dim FROM kg_entities WHERE embedding IS NOT NULL LIMIT 1").fetchone()
        dim = dim_row[0] if dim_row else 0
    except Exception as e:
        log.warning("kg_search: entity dim check failed: %s", e)
        dim = 0
    if not dim:
        return []

    # Use provided vector or embed the query
    if query_vec is None:
        query_vec, dim = _embed_query(query)
        if not query_vec:
            return []

    # Cosine similarity search in DuckDB
    try:
        rows = conn.execute(
            f"""
            SELECT
                entity_id, entity_type, name, qualified_name,
                description, properties_json, source_connection, tier,
                array_cosine_similarity(
                    embedding::FLOAT[{dim}],
                    ?::FLOAT[{dim}]
                ) AS match_score
            FROM kg_entities
            WHERE embedding IS NOT NULL
            ORDER BY match_score DESC
            LIMIT ?
            """,
            [[float(x) for x in query_vec], k],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        log.warning("kg_search: DuckDB vector query failed (%s: %s)", type(e).__name__, e)
        return []


def _kg_lexical_search(query: str, k: int = 10) -> List[Dict[str, Any]]:
    """Fallback word-level search when vector search unavailable.

    Splits the query into words and matches ANY word against entity
    name, qualified_name, description, **or observation content**.
    Results are scored by fraction of query words matched.
    """
    words = [w for w in query.split() if len(w) >= 2]
    if not words:
        return []

    # Build per-word ILIKE conditions — check entity fields + observations
    word_clauses = []
    score_parts = []
    for w in words[:8]:  # cap to avoid SQL explosion
        safe = _esc(w)
        condition = (
            f"(e.name ILIKE '%{safe}%' OR e.qualified_name ILIKE '%{safe}%' "
            f"OR e.description ILIKE '%{safe}%' OR obs_agg.obs_text ILIKE '%{safe}%')"
        )
        word_clauses.append(condition)
        score_parts.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")

    where = " OR ".join(word_clauses)
    score_expr = " + ".join(score_parts)

    return _query(f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               e.description, e.properties_json, e.source_connection, e.tier,
               ({score_expr}) * 1.0 / {len(words)} AS match_score
        FROM kg_entities e
        LEFT JOIN (
            SELECT entity_id, STRING_AGG(content, ' ') AS obs_text
            FROM kg_observations
            WHERE superseded_by IS NULL
            GROUP BY entity_id
        ) obs_agg ON obs_agg.entity_id = e.entity_id
        WHERE e.entity_type = 'table'
          AND ({where})
        ORDER BY match_score DESC, e.name
        LIMIT {int(k)}
    """)


def _kg_observation_vector_search(
    query_vec: List[float],
    entity_ids: List[str],
    top_k_per_entity: int = 15,
    embed_dim: int = 0,
) -> Dict[str, List[Dict[str, Any]]]:
    """Stage 2: Vector-rank observations within matched entities.

    For each entity_id, finds the observations most relevant to the
    query via cosine similarity on observation embeddings.  Uses a
    single DuckDB query with a window function to rank per-entity.

    Args:
        query_vec: Pre-computed query embedding.
        entity_ids: Entity IDs to search observations within.
        top_k_per_entity: Max observations per entity.
        embed_dim: Embedding dimension.

    Returns:
        Dict mapping entity_id → sorted list of observation dicts
        (with obs_match_score), or empty dict on failure.
    """
    if not query_vec or not entity_ids:
        return {}

    # All embedding checks use DuckDB directly — embeddings are stored in
    # parquet and array_cosine_similarity is a DuckDB function.  Going
    # through _query() can hit ClickHouse where embeddings may be NULL.
    conn = _get_duck_conn()

    # Check if any observations have embeddings
    try:
        check = conn.execute("SELECT COUNT(*) as cnt FROM kg_observations WHERE embedding IS NOT NULL").fetchone()
        obs_embed_cnt = check[0] if check else 0
    except Exception as e:
        log.warning("kg_search: observation embedding check failed: %s", e)
        obs_embed_cnt = 0
    if obs_embed_cnt == 0:
        log.info("kg_search: no embedded observations (cnt=0 in DuckDB) — falling back to tier/confidence ranking")
        return {}

    # Get observation embedding dimension
    if not embed_dim:
        try:
            dim_row = conn.execute("SELECT array_length(embedding, 1) as dim FROM kg_observations WHERE embedding IS NOT NULL LIMIT 1").fetchone()
            embed_dim = dim_row[0] if dim_row else 0
        except Exception as e:
            log.warning("kg_search: observation dim check failed: %s", e)
            embed_dim = 0
        if not embed_dim:
            return {}

    log.debug("kg_search: Stage 2 — %d embedded observations available, searching within %d entities", obs_embed_cnt, len(entity_ids))

    # Build entity_id IN-list
    eid_list = ", ".join(f"'{_esc(eid)}'" for eid in entity_ids)

    try:
        rows = conn.execute(
            f"""
            WITH scored AS (
                SELECT
                    observation_id, entity_id, category, content,
                    confidence, tier, contract_type,
                    array_cosine_similarity(
                        embedding::FLOAT[{embed_dim}],
                        ?::FLOAT[{embed_dim}]
                    ) AS obs_match_score
                FROM kg_observations
                WHERE embedding IS NOT NULL
                  AND superseded_by IS NULL
                  AND entity_id IN ({eid_list})
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY entity_id
                    ORDER BY obs_match_score DESC
                ) AS rn
                FROM scored
            )
            SELECT observation_id, entity_id, category, content,
                   confidence, tier, obs_match_score, contract_type
            FROM ranked
            WHERE rn <= {int(top_k_per_entity)}
            ORDER BY entity_id, obs_match_score DESC
            """,
            [[float(x) for x in query_vec]],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        obs_rows = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        log.warning("kg_search: observation vector search failed (%s: %s)", type(e).__name__, e)
        return {}

    # Group by entity_id
    result: Dict[str, List[Dict[str, Any]]] = {}
    for row in obs_rows:
        eid = row["entity_id"]
        if eid not in result:
            result[eid] = []
        result[eid].append(row)

    return result


# ---------------------------------------------------------------------------
# Stage 3: Fast-model observation filter/summary
# ---------------------------------------------------------------------------

_FILTER_SYSTEM_PROMPT = """\
You are a data analyst assistant. Given a user's search query and a list of \
observations about a database table, select and summarize ONLY the observations \
that are relevant to the query.

Return a JSON object with a single key "observations" containing an array of \
strings. Each string should be a concise observation (1-2 sentences max). \
Include ONLY observations that help answer or contextualize the query. \
Drop irrelevant ones entirely.

If ALL observations are relevant, include them all but condense each to its \
essence. If NONE are relevant, return {"observations": []}.

Return ONLY valid JSON, no markdown fences or commentary.\
"""


def _parse_filter_response(content: str) -> Optional[List[str]]:
    """Parse the fast model's JSON response for filtered observations."""
    text = content.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "observations" in data:
            return [str(o) for o in data["observations"] if o]
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _fast_model_filter_observations(
    query: str,
    table_name: str,
    observations: List[Dict[str, Any]],
    table_description: str = "",
) -> List[str]:
    """Stage 3: Use a fast model to filter/summarize observations.

    Takes the top-N vector-matched observations for a single table,
    sends them to the fast model with the original query, and returns
    a compact filtered list of observation text lines.

    On failure, returns the original observations unfiltered (graceful
    degradation).

    Args:
        query: The original user search query.
        table_name: Qualified table name for context.
        observations: List of observation dicts (from Stage 2 vector search).
        table_description: Optional table description for context.

    Returns:
        List of observation text lines (filtered/summarized).
    """
    if not observations:
        return []

    from ..agent import Agent
    from ..models import get_model_for_tier

    # Build the prompt
    obs_block = "\n".join(
        f"- [{o.get('category', 'general')}] {o.get('content', '')} "
        f"(similarity: {o.get('obs_match_score', 0):.3f})"
        for o in observations
    )

    desc_line = f"\nDescription: {table_description}" if table_description else ""
    user_prompt = (
        f"Query: {query}\n\n"
        f"Table: {table_name}{desc_line}\n\n"
        f"Observations (ranked by relevance to query):\n{obs_block}\n\n"
        f"Select and condense the observations most relevant to the query."
    )

    try:
        model_name = get_model_for_tier("fast")
        agent = Agent(model=model_name, system_prompt=_FILTER_SYSTEM_PROMPT)
        response = agent.run(input_message=user_prompt)

        parsed = _parse_filter_response(response.get("content", ""))
        if parsed is not None:
            log.debug(
                "kg_search: fast filter %s: %d → %d observations",
                table_name, len(observations), len(parsed),
            )
            return parsed
        log.debug("kg_search: fast filter returned unparseable response for %s", table_name)
    except Exception as e:
        log.warning("kg_search: fast model filter failed for %s (%s) — using unfiltered", table_name, e)

    # Fallback: return vector-ranked observations as-is
    return [f"[{o.get('category', 'general')}] {o.get('content', '')}" for o in observations]


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def _assemble_table_context(
    entity: Dict[str, Any],
    pre_ranked_observations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a compact context package for one table entity.

    Returns everything needed to write SQL against this table, optimised
    for token-efficiency so it can be returned as a tool result without
    blowing out the provider context window.

    Args:
        entity: Entity dict from search results.
        pre_ranked_observations: If provided, use these observation lines
            directly instead of querying the DB. Comes from Stage 2+3
            (vector-ranked and optionally fast-model-filtered).
    """
    eid = _esc(entity["entity_id"])

    # Parse properties
    props = {}
    try:
        props = json.loads(entity.get("properties_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Columns – compact "name TYPE (stats)" lines ──────────────────
    children = _query(f"""
        SELECT e.name, e.properties_json
        FROM kg_edges ed
        JOIN kg_entities e ON e.entity_id = ed.target_id
        WHERE ed.source_id = '{eid}' AND ed.rel_type = 'contains'
          AND e.entity_type = 'column'
        ORDER BY e.name
    """)
    col_lines = []
    for child in children:
        cp = {}
        try:
            cp = json.loads(child.get("properties_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        dtype = cp.get("data_type", "?")
        parts = [f"{child['name']} {dtype}"]
        if cp.get("nullable") is False:
            parts.append("NOT NULL")
        dc = cp.get("distinct_count")
        if dc is not None:
            parts.append(f"{dc} distinct")
        tv = cp.get("top_values")
        if tv:
            vals = [str(v["value"]) for v in tv[:3]]
            parts.append(f"e.g. {', '.join(vals)}")
        col_lines.append(" | ".join(parts))

    # ── Observations ────────────────────────────────────────────────
    contracts = []
    if pre_ranked_observations is not None:
        # Stage 2+3 provided relevance-ranked (and optionally filtered)
        # observation lines — use them directly.
        obs_lines = pre_ranked_observations

        # Also fetch contracts for this entity (evidence-backed observations)
        contract_rows = _query(f"""
            SELECT category, content, evidence_sql, evidence_hash,
                   contract_type, confidence, tier
            FROM kg_observations
            WHERE (entity_id = '{eid}' OR entity_ids_json LIKE '%{eid}%')
              AND superseded_by IS NULL
              AND evidence_sql IS NOT NULL
              AND contract_type IS NOT NULL
            ORDER BY
                CASE contract_type
                    WHEN 'invariant' THEN 1
                    WHEN 'trend' THEN 2
                    WHEN 'snapshot' THEN 3
                END,
                confidence DESC
            LIMIT 10
        """)
        for c in contract_rows:
            contracts.append({
                "content": (c.get("content") or "")[:200],
                "contract_type": c.get("contract_type"),
                "evidence_sql": c.get("evidence_sql"),
                "verified": c.get("evidence_hash") is not None,
            })
    else:
        # Fallback: grab top 8 by tier/confidence (lexical path or
        # when observation embeddings aren't available yet).
        observations = _query(f"""
            SELECT category, content, confidence, tier,
                   evidence_sql, evidence_hash, contract_type
            FROM kg_observations
            WHERE (entity_id = '{eid}' OR entity_ids_json LIKE '%{eid}%')
              AND superseded_by IS NULL
            ORDER BY tier DESC, confidence DESC
            LIMIT 8
        """)
        obs_lines = []
        for o in observations:
            text = (o.get("content") or "")[:200]
            obs_lines.append(f"[{o['category']}] {text}")
            # Collect contracts
            if o.get("evidence_sql") and o.get("contract_type"):
                contracts.append({
                    "content": text,
                    "contract_type": o.get("contract_type"),
                    "evidence_sql": o.get("evidence_sql"),
                    "verified": o.get("evidence_hash") is not None,
                })

    # ── Join hints (from FK edges and same-name columns) ────────────
    join_rows = _query(f"""
        SELECT
            ed.rel_type,
            ed.confidence,
            ed.evidence,
            src_e.name AS source_col,
            src_e.qualified_name AS source_col_qname,
            tgt_e.name AS target_name,
            tgt_e.qualified_name AS target_qname,
            tgt_e.entity_type AS target_type
        FROM kg_edges ed
        JOIN kg_entities src_e ON src_e.entity_id = ed.source_id
        JOIN kg_entities tgt_e ON tgt_e.entity_id = ed.target_id
        WHERE (ed.source_id IN (
                SELECT e2.entity_id FROM kg_edges ed2
                JOIN kg_entities e2 ON e2.entity_id = ed2.target_id
                WHERE ed2.source_id = '{eid}' AND ed2.rel_type = 'contains'
                  AND e2.entity_type = 'column'
              )
              OR ed.source_id = '{eid}')
          AND ed.rel_type IN ('likely_fk', 'same_name')
        ORDER BY ed.confidence DESC
        LIMIT 10
    """)
    joins = []
    for j in join_rows:
        if j.get("rel_type") == "likely_fk":
            joins.append({
                "type": "fk",
                "from_column": j.get("source_col"),
                "to_table": j.get("target_qname"),
                "confidence": round(float(j.get("confidence", 0)), 2),
                "evidence": j.get("evidence"),
            })
        elif j.get("rel_type") == "same_name" and j.get("target_type") == "column":
            # same_name is column-to-column, resolve target's parent table
            target_qname = j.get("target_qname", "")
            parts = target_qname.rsplit(".", 1)
            target_table = parts[0] if len(parts) > 1 else target_qname
            joins.append({
                "type": "same_column",
                "column": j.get("source_col"),
                "also_in": target_table,
                "confidence": round(float(j.get("confidence", 0)), 2),
            })

    # ── Breach observations (Tier 3) ─────────────────────────────────
    breach_rows = _query(f"""
        SELECT content, confidence, created_at
        FROM kg_observations
        WHERE (entity_id = '{eid}' OR entity_ids_json LIKE '%{eid}%')
          AND category = 'breach'
          AND superseded_by IS NULL
        ORDER BY created_at DESC
        LIMIT 5
    """)
    breaches = []
    for b in breach_rows:
        breaches.append((b.get("content") or "")[:300])

    # ── Description ──────────────────────────────────────────────────
    desc = entity.get("description") or ""

    result = {
        "qualified_name": entity.get("qualified_name"),
        "sql_table_ref": props.get("sql_table_ref", entity.get("qualified_name")),
        "connection": entity.get("source_connection"),
        "description": desc,
        "row_count": props.get("row_count"),
        "match_score": round(float(entity.get("match_score", 0)), 4),
        "columns": col_lines,
        "observations": obs_lines,
        "_entity_id": entity.get("entity_id"),  # internal: used by investigation
    }

    # Only include contracts/breaches/joins if they exist (keeps output clean)
    if contracts:
        result["contracts"] = contracts
    if breaches:
        result["breaches"] = breaches
    if joins:
        result["joins"] = joins

    return result


# ---------------------------------------------------------------------------
# Cascade cell functions (called by builtin_cascades/kg_search.yaml)
# ---------------------------------------------------------------------------

def _kg_search_vector_stages(
    query: str,
    k: int = 5,
    obs_per_table: int = 15,
) -> Dict[str, Any]:
    """Cascade cell 1: Embed query + Stage 1 entity search + Stage 2 observation ranking.

    Called as ``tool: python:lars.kg.skills._kg_search_vector_stages``
    from the kg_search cascade.  Returns structured intermediate data
    that feeds both the LLM filter cell (prompt text) and the assembly
    cell (entity + observation dicts).
    """
    k, obs_per_table = int(k), int(obs_per_table)

    query_vec, embed_dim = _embed_query(query)
    log.info("kg_search: query_vec=%s, embed_dim=%d", "OK" if query_vec else "NONE", embed_dim)

    # ── Stage 1: Entity search ───────────────────────────────────────
    if query_vec:
        matches = _kg_vector_search(query, k=k, query_vec=query_vec, embed_dim=embed_dim)
        search_mode = "vector"
    else:
        matches = []
        search_mode = "lexical"

    if not matches:
        if search_mode == "vector":
            log.info("kg_search: vector returned 0 — trying lexical")
        matches = _kg_lexical_search(query, k=k)
        search_mode = "lexical"

    log.info("kg_search: Stage 1 → %s, %d matches", search_mode, len(matches))

    # ── Stage 2: Observation vector ranking ──────────────────────────
    obs_by_entity: Dict[str, List[Dict[str, Any]]] = {}
    stage2_status = "skipped"
    if query_vec and matches:
        entity_ids = [m["entity_id"] for m in matches]
        obs_by_entity = _kg_observation_vector_search(
            query_vec=query_vec,
            entity_ids=entity_ids,
            top_k_per_entity=obs_per_table,
            embed_dim=embed_dim,
        )
        if obs_by_entity:
            total_obs = sum(len(v) for v in obs_by_entity.values())
            stage2_status = f"ranked ({total_obs} obs across {len(obs_by_entity)} tables)"
        else:
            stage2_status = "empty (fallback to tier/confidence)"
    elif not query_vec:
        stage2_status = "skipped (no query vector)"

    log.info("kg_search: Stage 2 → %s", stage2_status)

    # ── Format prompt block for LLM filter cell ──────────────────────
    filter_blocks = []
    for entity in matches:
        eid = entity["entity_id"]
        ranked_obs = obs_by_entity.get(eid, [])
        if not ranked_obs:
            continue
        obs_lines = "\n".join(
            f"- [{o.get('category', 'general')}] {o.get('content', '')} "
            f"(similarity: {o.get('obs_match_score', 0):.3f})"
            for o in ranked_obs
        )
        desc = entity.get("description") or ""
        block = (
            f"## Table: {entity.get('qualified_name', '')} "
            f"(entity_id: {eid})\n"
            f"Description: {desc}\n"
            f"Observations:\n{obs_lines}"
        )
        filter_blocks.append(block)

    if filter_blocks:
        tables_for_filtering = (
            "Tables with ranked observations to filter:\n\n"
            + "\n\n".join(filter_blocks)
        )
    else:
        tables_for_filtering = (
            'No ranked observations available. Return {"tables": []}.'
        )

    # ── Serialize entities for assembly cell ──────────────────────────
    entities_ser = []
    for e in matches:
        entities_ser.append({
            "entity_id": e.get("entity_id"),
            "entity_type": e.get("entity_type"),
            "name": e.get("name"),
            "qualified_name": e.get("qualified_name"),
            "description": e.get("description"),
            "properties_json": e.get("properties_json"),
            "source_connection": e.get("source_connection"),
            "tier": e.get("tier"),
            "match_score": float(e.get("match_score", 0)),
        })

    obs_ser: Dict[str, List[Dict[str, Any]]] = {}
    for eid, obs_list in obs_by_entity.items():
        obs_ser[eid] = [
            {
                "category": o.get("category", "general"),
                "content": o.get("content", ""),
                "obs_match_score": float(o.get("obs_match_score", 0)),
                "contract_type": o.get("contract_type"),
            }
            for o in obs_list
        ]

    return {
        "search_mode": search_mode,
        "query_vec_ok": query_vec is not None,
        "stage2_status": stage2_status,
        "entities": entities_ser,
        "obs_by_entity": obs_ser,
        "has_ranked_obs": bool(obs_by_entity),
        "tables_for_filtering": tables_for_filtering,
    }


def _kg_search_assemble(
    vector_data_json: str,
    filtered_json: str = "",
    query: str = "",
) -> str:
    """Cascade cell 3: Merge vector search results with LLM-filtered observations.

    Called as ``tool: python:lars.kg.skills._kg_search_assemble``
    from the kg_search cascade.  Returns the final kg_search JSON
    response string.
    """
    # ── Parse vector data ────────────────────────────────────────────
    if isinstance(vector_data_json, dict):
        vd = vector_data_json
    else:
        vd = json.loads(vector_data_json)

    search_mode = vd.get("search_mode", "vector")
    entities = vd.get("entities", [])
    obs_by_entity = vd.get("obs_by_entity", {})

    # ── Parse LLM-filtered observations ──────────────────────────────
    # NativeEnvironment may deliver filtered_json as a Python dict (when
    # the LLM output looks like a valid Python literal) OR as a plain
    # JSON string.  Handle both.
    filtered_tables: Dict[str, List[str]] = {}
    if filtered_json:
        data = None
        if isinstance(filtered_json, dict):
            # NativeEnvironment already parsed to dict
            data = filtered_json
        elif isinstance(filtered_json, list):
            # Unlikely but handle list wrapper
            data = {"tables": filtered_json}
        else:
            text = str(filtered_json).strip()
            # Strip markdown fences
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                log.warning("kg_search: assembly could not parse filtered observations: %s", text[:200])

        if data and isinstance(data, dict):
            for t in data.get("tables", []):
                eid = t.get("entity_id", "")
                obs = t.get("observations", [])
                if eid:
                    filtered_tables[eid] = [str(o) for o in obs]

    # ── Assemble per-entity context ──────────────────────────────────
    tables = []
    obs_path_counts = {"fast_filter": 0, "vector_ranked": 0, "tier_fallback": 0}

    for entity in entities:
        eid = entity["entity_id"]

        if eid in filtered_tables:
            # Use LLM-filtered observations
            ctx = _assemble_table_context(
                entity, pre_ranked_observations=filtered_tables[eid],
            )
            obs_path_counts["fast_filter"] += 1
        elif eid in obs_by_entity and obs_by_entity[eid]:
            # Use vector-ranked observations (LLM filter didn't cover this table)
            obs_lines = [
                f"[{o.get('category', 'general')}] {o.get('content', '')}"
                for o in obs_by_entity[eid]
            ]
            ctx = _assemble_table_context(entity, pre_ranked_observations=obs_lines)
            obs_path_counts["vector_ranked"] += 1
        else:
            # Fallback: tier/confidence from DB
            ctx = _assemble_table_context(entity)
            obs_path_counts["tier_fallback"] += 1

        tables.append(ctx)

    # ── Determine stage statuses for _meta ────────────────────────────
    if obs_path_counts["fast_filter"]:
        stage3_status = f"filtered {obs_path_counts['fast_filter']} tables"
    elif obs_path_counts["vector_ranked"]:
        stage3_status = "vector-ranked only"
    else:
        stage3_status = "tier/confidence fallback"

    log.info(
        "kg_search: Assembly → %s | paths: %s",
        stage3_status, obs_path_counts,
    )

    return json.dumps({
        "query": query,
        "source": f"kg:{search_mode}",
        "table_count": len(tables),
        "tables": tables,
        "_meta": {
            "stages": {
                "embed_query": "ok" if vd.get("query_vec_ok") else "failed",
                "entity_search": search_mode,
                "entity_matches": len(entities),
                "obs_ranking": vd.get("stage2_status", "unknown"),
                "fast_filter": stage3_status,
            },
            "obs_paths": obs_path_counts,
            "execution": "cascade",
        },
    }, default=str, indent=2)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Async search investigation
# ---------------------------------------------------------------------------

_INVESTIGATE_SYSTEM_PROMPT = """\
You are a data investigation analyst. Given a search query and rich context \
about a database table (schema, observations, contract status, and live SQL \
query results), synthesize a clear, actionable summary.

Your goal: Answer the user's implicit question based on the evidence. Be \
specific — cite actual values, counts, dates, and patterns from the SQL results.

Format your response as JSON:
{
  "synthesis": "A 2-4 sentence summary answering what this data tells us about the search query. Be specific with numbers and dates.",
  "key_findings": ["finding 1", "finding 2", ...],
  "evidence_queries": [
    {"sql": "the query that was run", "finding": "what it revealed"}
  ]
}

Return ONLY valid JSON, no markdown fences or commentary.\
"""


def _run_evidence_sql(table_context: Dict[str, Any]) -> List[Dict[str, str]]:
    """Run evidence SQL from contracts/breaches + standard queries.

    Returns list of {"sql": ..., "result": ...} dicts.
    """
    from ..sql_tools.tools import safe_sql_run

    sql_table_ref = table_context.get("sql_table_ref", table_context.get("qualified_name", ""))
    connection = table_context.get("connection", "")
    if not sql_table_ref or not connection:
        return []

    evidence_results = []
    seen_sql = set()

    # Collect evidence SQL from contracts
    for contract in table_context.get("contracts", []):
        sql = contract.get("evidence_sql")
        if sql and sql not in seen_sql:
            seen_sql.add(sql)

    # Standard exploratory queries
    standard_queries = [
        f"SELECT COUNT(*) as total_rows FROM {sql_table_ref}",
        f"SELECT * FROM {sql_table_ref} ORDER BY created_at DESC LIMIT 10",
    ]
    for sq in standard_queries:
        if sq not in seen_sql:
            seen_sql.add(sq)

    # Budget: ~8000 "cells" (row × col) total across all queries.
    # Per-query: adaptive row limit based on column count.
    # Narrow tables (2-3 cols) get up to 50 rows, wide tables (20+) get 5 minimum.
    CELL_BUDGET_PER_QUERY = 800   # max cells per single query result
    CHAR_BUDGET_PER_CELL = 200    # max chars per cell value
    MIN_ROWS = 5
    MAX_ROWS = 50

    for sql in list(seen_sql)[:10]:
        try:
            result_json = safe_sql_run(
                sql=sql,
                connection=connection,
                row_limit=MAX_ROWS,
                text_max_chars=CHAR_BUDGET_PER_CELL,
            )
            result = json.loads(result_json)
            if result.get("error"):
                evidence_results.append({"sql": sql, "result": f"ERROR: {result['error']}"})
            else:
                rows = result.get("results", [])
                cols = result.get("columns", [])
                if rows and cols:
                    # Adaptive row limit: budget ÷ columns, clamped
                    num_cols = len(cols)
                    row_limit = max(MIN_ROWS, min(MAX_ROWS, CELL_BUDGET_PER_QUERY // max(num_cols, 1)))
                    # Also scale cell char limit: narrow = generous, wide = tighter
                    cell_chars = max(60, min(CHAR_BUDGET_PER_CELL, 1200 // max(num_cols, 1)))

                    lines = []
                    lines.append(" | ".join(cols))
                    for row in rows[:row_limit]:
                        lines.append(" | ".join(str(row.get(c, ""))[:cell_chars] for c in cols))
                    evidence_results.append({"sql": sql, "result": "\n".join(lines)})
                else:
                    evidence_results.append({"sql": sql, "result": "(no rows)"})
        except Exception as e:
            evidence_results.append({"sql": sql, "result": f"ERROR: {e}"})

    return evidence_results


def _investigate_table(
    search_id: str,
    investigation_id: str,
    query: str,
    table_context: Dict[str, Any],
) -> None:
    """Investigate a single table: run evidence SQL, call LLM, write results."""
    from ..agent import Agent
    from ..models import get_model_for_tier

    db = _get_db()
    now = datetime.now(timezone.utc)

    # Update status to running
    db.insert_rows("kg_search_investigations", [{
        "investigation_id": investigation_id,
        "search_id": search_id,
        "entity_id": table_context.get("_entity_id", ""),
        "qualified_name": table_context.get("qualified_name", ""),
        "query": query,
        "status": "running",
        "synthesis": None,
        "evidence_queries": None,
        "model_used": None,
        "cost_usd": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": now,
        "completed_at": None,
        "created_at": now,
    }])

    try:
        # Run evidence SQL
        evidence = _run_evidence_sql(table_context)

        # Build prompt
        obs_block = "\n".join(f"- {o}" for o in table_context.get("observations", []))
        breach_block = "\n".join(f"- {b}" for b in table_context.get("breaches", []))
        col_block = "\n".join(f"- {c}" for c in table_context.get("columns", []))

        evidence_block = ""
        for ev in evidence:
            evidence_block += f"\nQuery: {ev['sql']}\nResult:\n{ev['result']}\n"

        user_prompt = (
            f'Search query: "{query}"\n\n'
            f"Table: {table_context.get('qualified_name', '')}\n"
            f"Description: {table_context.get('description', '')}\n"
            f"Row count: {table_context.get('row_count', 'unknown')}\n\n"
            f"Columns:\n{col_block}\n\n"
            f"Observations:\n{obs_block or '(none)'}\n\n"
            f"Contract breaches:\n{breach_block or '(none)'}\n\n"
            f"--- Live SQL Evidence ---\n{evidence_block or '(none)'}\n\n"
            f'Based on all this evidence, what does this table tell us about "{query}"?'
        )

        model_name = get_model_for_tier("standard")
        agent = Agent(model=model_name, system_prompt=_INVESTIGATE_SYSTEM_PROMPT)
        response = agent.run(input_message=user_prompt)

        content = response.get("content", "")
        cost = response.get("cost", 0) or 0
        tokens_in = response.get("tokens_in", 0) or 0
        tokens_out = response.get("tokens_out", 0) or 0

        # Parse response
        synthesis = ""
        key_findings = []
        evidence_queries_parsed = []

        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
            synthesis = data.get("synthesis", text)
            key_findings = data.get("key_findings", [])
            evidence_queries_parsed = data.get("evidence_queries", [])
        except (json.JSONDecodeError, TypeError):
            # If not valid JSON, use raw content as synthesis
            synthesis = content

        # Merge pre-run evidence with LLM-cited evidence
        all_evidence = []
        for ev in evidence:
            all_evidence.append({"sql": ev["sql"], "finding": ev.get("result", "")[:500]})
        for eq in evidence_queries_parsed:
            if eq.get("sql") not in {e["sql"] for e in all_evidence}:
                all_evidence.append(eq)

        # Write completed result
        db.insert_rows("kg_search_investigations", [{
            "investigation_id": investigation_id,
            "search_id": search_id,
            "entity_id": table_context.get("_entity_id", ""),
            "qualified_name": table_context.get("qualified_name", ""),
            "query": query,
            "status": "completed",
            "synthesis": synthesis,
            "evidence_queries": json.dumps({
                "key_findings": key_findings,
                "evidence": all_evidence,
            }, default=str),
            "model_used": model_name,
            "cost_usd": cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "started_at": now,
            "completed_at": datetime.now(timezone.utc),
            "created_at": now,
        }])

        log.info("kg_investigate: completed %s for search %s (cost=$%.4f)",
                 table_context.get("qualified_name", ""), search_id, cost)

    except Exception as e:
        log.warning("kg_investigate: failed for %s: %s",
                    table_context.get("qualified_name", ""), e)
        try:
            db.insert_rows("kg_search_investigations", [{
                "investigation_id": investigation_id,
                "search_id": search_id,
                "entity_id": table_context.get("_entity_id", ""),
                "qualified_name": table_context.get("qualified_name", ""),
                "query": query,
                "status": "failed",
                "synthesis": f"Investigation failed: {e}",
                "evidence_queries": None,
                "model_used": None,
                "cost_usd": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "started_at": now,
                "completed_at": datetime.now(timezone.utc),
                "created_at": now,
            }])
        except Exception:
            pass


def _launch_investigation(search_id: str, query: str, tables_data: List[Dict[str, Any]]) -> None:
    """Fire off async investigation for top search results.

    Runs in a daemon thread with a ThreadPoolExecutor for parallelism.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    # Limit to top 5 tables by match_score
    top_tables = sorted(tables_data, key=lambda t: t.get("match_score", 0), reverse=True)[:5]
    if not top_tables:
        return

    def _run():
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                for table in top_tables:
                    inv_id = uuid.uuid4().hex[:16]
                    futures.append(executor.submit(
                        _investigate_table, search_id, inv_id, query, table,
                    ))
                # Wait for all to complete
                for f in futures:
                    try:
                        f.result(timeout=120)
                    except Exception as e:
                        log.warning("kg_investigate: thread error: %s", e)
            log.info("kg_investigate: all investigations complete for search %s", search_id)
        except Exception as e:
            log.warning("kg_investigate: launcher error: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    log.info("kg_investigate: launched background investigation for search %s (%d tables)",
             search_id, len(top_tables))


# ---------------------------------------------------------------------------
# kg_search_investigation — polling skill
# ---------------------------------------------------------------------------

@register_skill("kg_search_investigation")
def kg_search_investigation(search_id: str) -> str:
    """
    Poll investigation results for a kg_search search_id.

    Returns the status and synthesis for each table that was investigated.
    Use this to check if async investigations have completed.

    Args:
        search_id: The search_id returned by kg_search.

    Returns:
        JSON with investigations array and all_complete flag.
    """
    rows = _query(f"""
        SELECT investigation_id, entity_id, qualified_name, query,
               status, synthesis, evidence_queries, model_used,
               cost_usd, started_at, completed_at
        FROM kg_search_investigations
        WHERE search_id = '{_esc(search_id)}'
        ORDER BY created_at
    """)
    return json.dumps({
        "search_id": search_id,
        "investigations": rows,
        "all_complete": all(r["status"] in ("completed", "failed") for r in rows) if rows else False,
    }, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_search — skill entry point (invokes cascade or direct fallback)
# ---------------------------------------------------------------------------

@register_skill("kg_search")
def kg_search(
    query: str,
    k: int = 5,
    obs_per_table: int = 15,
    use_fast_filter: bool = True,
) -> str:
    """
    Semantic search for relevant database tables (2-stage with observation ranking).

    Stage 1: Finds the top-k tables by vector similarity on entity embeddings.
    Stage 2: For each table, vector-ranks its observations against the query
             to surface only the most relevant insights.
    Stage 3 (optional): A fast model filters and condenses the observations
             based on the query, removing noise.

    Falls back gracefully: no observation embeddings → tier/confidence ranking,
    no entity embeddings → lexical word-match, fast model fails → unfiltered.

    This is the primary schema discovery tool.  One call gives you all the
    context you need — no follow-up search required.

    Args:
        query: Natural language description of what data you're looking for.
               e.g. "profitable furniture orders", "customer locations",
               "tables with date ranges and revenue data"
        k: Number of tables to return (default 5).
        obs_per_table: Max observations to vector-rank per table (default 15).
        use_fast_filter: Run fast-model filter on observations (default True).

    Returns:
        JSON object with:
        - query: The search query used
        - source: Search method used (kg:vector, kg:lexical)
        - table_count: Number of tables returned
        - tables: Array of matching tables, each with:
            - qualified_name: Full table path
            - sql_table_ref: Use this in SQL FROM clauses
            - connection: Database connection name
            - description: Semantic description of the table
            - row_count: Number of rows
            - match_score: Similarity score (higher = better match)
            - columns: Compact column schema lines
            - observations: Relevance-ranked insights about the data
    """
    k, obs_per_table = int(k), int(obs_per_table)
    search_id = uuid.uuid4().hex[:12]

    def _inject_search_id_and_investigate(result_str: str) -> str:
        """Add search_id to result JSON and launch async investigation."""
        try:
            data = json.loads(result_str)
            data["search_id"] = search_id

            # Launch async investigation with entity_ids attached to table contexts
            tables = data.get("tables", [])
            # Attach _entity_id from entity search for internal use
            _launch_investigation(search_id, query, tables)

            return json.dumps(data, default=str, indent=2)
        except (json.JSONDecodeError, TypeError):
            return result_str

    # ── Cascade path: full 3-stage pipeline with tracked LLM filter ──
    if use_fast_filter:
        try:
            import os
            from ..runner import run_cascade

            cascade_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "builtin_cascades", "kg_search.yaml",
            )
            log.info("kg_search: launching cascade from %s", cascade_path)

            result = run_cascade(
                config_path=cascade_path,
                input_data={
                    "query": query,
                    "k": k,
                    "obs_per_table": obs_per_table,
                },
                session_id=f"kg_search_{uuid.uuid4().hex[:8]}",
            )

            # Extract final cell output from cascade lineage
            if result and result.get("lineage"):
                final = result["lineage"][-1].get("output")
                if final:
                    log.info("kg_search: cascade completed (%d cells)", len(result["lineage"]))
                    raw = final if isinstance(final, str) else json.dumps(
                        final, default=str, indent=2,
                    )
                    return _inject_search_id_and_investigate(raw)

            log.warning("kg_search: cascade returned no output — falling back to direct")
            if result:
                log.warning("kg_search: cascade result keys=%s, lineage_len=%d, errors=%s",
                            list(result.keys()),
                            len(result.get("lineage", [])),
                            result.get("errors", []))
        except Exception as e:
            import sys, traceback
            tb = traceback.format_exc()
            log.warning("kg_search: cascade failed — falling back to direct\n%s", tb)
            # Also print to stderr so it's visible from CLI even without logging
            print(f"[kg_search] cascade failed, falling back to direct: {e}", file=sys.stderr)
            print(tb, file=sys.stderr)

    # ── Direct path: stages 1+2 only (no LLM filter) ────────────────
    vector_data = _kg_search_vector_stages(query, k=k, obs_per_table=obs_per_table)
    raw = _kg_search_assemble(json.dumps(vector_data, default=str), None, query)
    return _inject_search_id_and_investigate(raw)


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
    force: bool = False,
    fresh: bool = False,
    parallel: int = 3,
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
        force: Re-enrich all entities, even those with existing Tier 2 observations.
        fresh: Delete all existing Tier 2 observations before dreaming (clean slate).
        parallel: Number of parallel LLM calls (default: 3).

    Returns:
        JSON summary with counts, cost, and timing.
    """
    from .dreamer import dream_tier2
    result = dream_tier2(
        max_entities=int(max_entities),
        model_tier=model_tier,
        dry_run=bool(dry_run),
        force=bool(force),
        fresh=bool(fresh),
        parallel=int(parallel),
    )
    return json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_embed
# ---------------------------------------------------------------------------

@register_skill("kg_embed")
def kg_embed(
    force: bool = False,
    max_entities: int = 0,
    max_observations: int = 0,
) -> str:
    """
    Embed KG entities and observations for semantic search (Tier 2.5).

    Embeds two targets:
    1. **Entity search documents** — built from each table's description,
       column schema, and observations. Powers Stage 1 of kg_search
       (finding relevant tables).
    2. **Observation content** — embeds each observation's text individually.
       Powers Stage 2 of kg_search (ranking observations by query relevance
       within matched tables).

    Normally runs automatically after dreaming. Use this to manually
    trigger re-embedding (e.g., after adding observations or changing
    the embedding model).

    Args:
        force: If True, re-embed all even if already embedded.
        max_entities: 0 = all (default), >0 = cap for entities.
        max_observations: 0 = all (default), >0 = cap for observations.

    Returns:
        JSON summary with entity and observation embedding counts.
    """
    from .embedder import embed_kg_entities, embed_kg_observations

    entity_result = embed_kg_entities(
        max_entities=int(max_entities),
        force=bool(force),
    )
    obs_result = embed_kg_observations(
        max_observations=int(max_observations),
        force=bool(force),
    )

    return json.dumps({
        "entities": entity_result,
        "observations": obs_result,
    }, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_validate
# ---------------------------------------------------------------------------

@register_skill("kg_validate")
def kg_validate(
    contract_types: str = "",
    max_observations: int = 0,
    investigate: bool = True,
    model_tier: str = "fast",
    dry_run: bool = False,
) -> str:
    """
    Validate observation contracts by re-running evidence SQL.

    Finds observations with evidence_sql and evidence_hash, re-runs
    the queries, and detects changes.  For invariant and trend breaches,
    runs an LLM investigation to explain what changed and why it matters.

    This is the "semantic CDC" — not just what changed, but what it MEANS.

    Args:
        contract_types: Comma-separated types to check (default: all).
            Options: "invariant", "trend", "snapshot"
        max_observations: Max observations to validate (0 = all, default).
        investigate: Run LLM investigation on breaches (default True).
        model_tier: Model tier for investigation — "fast" or "standard".
        dry_run: If True, detect breaches but don't write findings.

    Returns:
        JSON summary with breach counts, findings, and costs.
    """
    from .validator import validate_contracts

    types_list = None
    if contract_types:
        types_list = [t.strip() for t in contract_types.split(",") if t.strip()]

    result = validate_contracts(
        contract_types=types_list,
        max_observations=int(max_observations),
        investigate=bool(investigate),
        model_tier=model_tier,
        dry_run=bool(dry_run),
    )
    return json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_fingerprint
# ---------------------------------------------------------------------------

@register_skill("kg_fingerprint")
def kg_fingerprint(
    max_tables: int = 0,
    connections: str = "",
    force: bool = False,
) -> str:
    """
    Generate dimensional fingerprint observations for tables.

    Creates evidence-backed observations that capture the exact state
    of each table's dimensions — row counts, distinct value sets for
    low-cardinality columns, date ranges, NULL patterns, and recent
    activity.

    These are the observations that catch "a new student was added"
    or "a new status value appeared." No LLM needed — purely SQL.

    Run after crawl, before dreaming. Very fast and cheap.

    Args:
        max_tables: Max tables to fingerprint (0 = all, default).
        connections: Comma-separated connection names (default: all).
        force: Regenerate even if fingerprints already exist.

    Returns:
        JSON summary with counts.
    """
    from .fingerprinter import fingerprint_tables

    conn_list = None
    if connections:
        conn_list = [c.strip() for c in connections.split(",") if c.strip()]

    result = fingerprint_tables(
        max_tables=int(max_tables),
        connections=conn_list,
        force=bool(force),
    )
    return json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# kg_progress
# ---------------------------------------------------------------------------

@register_skill("kg_progress")
def kg_progress(session_id: str = "", run_type: str = "") -> str:
    """
    Get the latest progress for KG runs (dream, validate, embed).

    Shows what's currently running or the most recent completed run.
    Designed for UI polling — lightweight query against kg_run_progress.

    Args:
        session_id: Specific session to check (default: latest).
        run_type: Filter by run type — "dream", "validate", "embed" (default: any).

    Returns:
        JSON with current step, total, status, and running counts.
    """
    filters = ["1=1"]
    if session_id:
        filters.append(f"session_id = '{_esc(session_id)}'")
    if run_type:
        filters.append(f"run_type = '{_esc(run_type)}'")

    where = " AND ".join(filters)

    # Get the latest progress row (most recent update)
    rows = _query(f"""
        SELECT session_id, run_type, status, entity_name,
               step, total_steps, observations_so_far,
               breaches_so_far, errors_so_far, cost_so_far,
               detail_json, updated_at
        FROM kg_run_progress
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT 1
    """)

    if not rows:
        return json.dumps({"status": "idle", "message": "No runs found"})

    row = rows[0]
    result = {
        "session_id": row.get("session_id"),
        "run_type": row.get("run_type"),
        "status": row.get("status"),
        "entity_name": row.get("entity_name"),
        "step": row.get("step", 0),
        "total_steps": row.get("total_steps", 0),
        "percent": round(
            (row.get("step", 0) / row["total_steps"] * 100)
            if row.get("total_steps") else 0, 1
        ),
        "observations": row.get("observations_so_far", 0),
        "breaches": row.get("breaches_so_far", 0),
        "errors": row.get("errors_so_far", 0),
        "cost_usd": row.get("cost_so_far", 0),
        "updated_at": row.get("updated_at"),
    }

    if row.get("detail_json"):
        try:
            result["detail"] = json.loads(row["detail_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    return json.dumps(result, default=str, indent=2)
