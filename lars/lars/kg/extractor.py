"""
Tier 1 deterministic KG extractor.

Reads crawl YAML from sql_connections/samples/ and produces:
- Entities (connection, schema, table, column)
- Edges (containment hierarchy, likely FK, same-name columns)
- Observations (cardinality patterns, data quality signals)

All Tier 1 operations are deterministic — no LLM calls.
Re-running is idempotent: entities upsert by entity_id.
"""

import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity ID construction (deterministic, globally unique)
# ---------------------------------------------------------------------------

def _eid(entity_type: str, *parts: str) -> str:
    """Build a deterministic entity ID: {type}::{dot.separated.path}"""
    path = ".".join(p for p in parts if p)
    return f"{entity_type}::{path}"


def _edge_id(source_id: str, rel_type: str, target_id: str) -> str:
    """Build a deterministic edge ID."""
    return f"{source_id}|{rel_type}|{target_id}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _props(d: dict) -> str:
    """Serialize a dict as JSON for properties_json columns."""
    return json.dumps(d, default=str, ensure_ascii=False)


_FK_SUFFIX_RE = re.compile(r"^(.+?)_(?:id|key|fk|ref|code)$", re.IGNORECASE)
_ID_EXACT_RE = re.compile(r"^id$", re.IGNORECASE)


def _normalize_name(name: str) -> str:
    """Lowercase + strip for comparison."""
    return (name or "").strip().lower()


def _infer_fk_table_stem(col_name: str) -> Optional[str]:
    """
    Heuristic: 'customer_id' → 'customer', 'order_ref' → 'order'.
    Returns None if the column name doesn't match FK patterns.
    """
    m = _FK_SUFFIX_RE.match(col_name)
    if m:
        return _normalize_name(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

class KGExtractResult:
    """Holds the extraction output for a single crawl pass."""

    __slots__ = ("entities", "edges", "observations",
                 "entities_added", "entities_updated", "edges_added", "observations_added")

    def __init__(self):
        self.entities: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.entities_added = 0
        self.entities_updated = 0
        self.edges_added = 0
        self.observations_added = 0


def _extract_column_observations(
    col: dict,
    col_entity_id: str,
    table_entity_id: str,
    row_count: Optional[int],
    dream_session_id: str,
    now: datetime,
) -> List[Dict[str, Any]]:
    """Generate Tier 1 observations for a single column."""
    obs = []
    meta = col.get("metadata", {})
    col_name = col.get("name", "")
    col_type = col.get("type", "")
    distinct = meta.get("distinct_count")
    dist = meta.get("value_distribution", [])

    if distinct is None:
        return obs

    # --- Cardinality pattern ---
    if row_count and row_count > 0:
        ratio = distinct / row_count
        if distinct <= 2 and row_count > 10:
            category = "boolean_like"
            content = (
                f"Column '{col_name}' has only {distinct} distinct value(s) "
                f"across {row_count} rows — likely a boolean/flag."
            )
            if dist:
                vals = [str(d.get("value")) for d in dist[:5]]
                content += f" Values: {', '.join(vals)}."
            obs.append(_make_obs(
                col_entity_id, [col_entity_id, table_entity_id],
                "column", "cardinality", content, 0.95,
                dream_session_id, now,
            ))
        elif distinct <= 20 and row_count >= 20:
            category = "low_cardinality"
            content = (
                f"Column '{col_name}' is low-cardinality ({distinct} distinct / "
                f"{row_count} rows) — likely a categorical/enum field."
            )
            if dist:
                vals = [str(d.get("value")) for d in dist[:5]]
                content += f" Top values: {', '.join(vals)}."
            obs.append(_make_obs(
                col_entity_id, [col_entity_id, table_entity_id],
                "column", "cardinality", content, 0.9,
                dream_session_id, now,
            ))
        elif ratio > 0.95 and row_count > 10:
            content = (
                f"Column '{col_name}' is near-unique ({distinct} distinct / "
                f"{row_count} rows, {ratio:.1%}) — likely an identifier or key."
            )
            obs.append(_make_obs(
                col_entity_id, [col_entity_id, table_entity_id],
                "column", "cardinality", content, 0.85,
                dream_session_id, now,
            ))

    # --- Nullability signal ---
    nullable = col.get("nullable", True)
    if not nullable:
        obs.append(_make_obs(
            col_entity_id, [col_entity_id, table_entity_id],
            "column", "constraint", f"Column '{col_name}' is NOT NULL (required).",
            1.0, dream_session_id, now,
        ))

    # --- Range observation for numeric/date ---
    min_val = meta.get("min")
    max_val = meta.get("max")
    if min_val is not None and max_val is not None:
        obs.append(_make_obs(
            col_entity_id, [col_entity_id, table_entity_id],
            "column", "range",
            f"Column '{col_name}' ranges from {min_val} to {max_val}.",
            1.0, dream_session_id, now,
        ))

    return obs


def _obs_id(entity_id: str, category: str, content: str) -> str:
    """Deterministic observation ID from entity + category + content.

    This ensures that re-running Tier 1 extraction produces the same
    observation_ids, so the dedup view collapses duplicates across
    crawl runs instead of accumulating them.
    """
    import hashlib
    key = f"{entity_id}|{category}|{content}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _make_obs(
    entity_id: str,
    entity_ids: List[str],
    level: str,
    category: str,
    content: str,
    confidence: float,
    dream_session_id: str,
    now: datetime,
) -> Dict[str, Any]:
    return {
        "observation_id": _obs_id(entity_id, category, content),
        "entity_id": entity_id,
        "entity_ids_json": json.dumps(entity_ids),
        "level": level,
        "tier": 1,
        "category": category,
        "content": content,
        "confidence": confidence,
        "embedding": None,
        "embedding_model": None,
        "superseded_by": None,
        "dream_session_id": dream_session_id,
        "created_at": now,
    }


def extract_from_crawl_yaml(samples_dir: str) -> KGExtractResult:
    """
    Walk sql_connections/samples/ and extract Tier 1 KG data.

    Returns a KGExtractResult with entities, edges, and observations
    ready to be written via db_adapter.insert_rows().
    """
    result = KGExtractResult()
    now = _now()
    dream_session_id = str(uuid.uuid4())

    samples_path = Path(samples_dir)
    if not samples_path.exists():
        log.warning("KG extract: samples dir %s does not exist", samples_dir)
        return result

    # Track entities for cross-table analysis
    seen_entities: set = set()
    # column_name → [(col_entity_id, table_entity_id, conn_name, schema_name, table_name)]
    col_name_index: Dict[str, List[Tuple[str, str, str, str, str]]] = defaultdict(list)
    # normalized_table_name → table_entity_id (for FK heuristics)
    table_name_index: Dict[str, str] = {}
    # Track table stems (singular/plural) for FK matching
    table_stem_index: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Pass 1: Walk YAML files, extract entities + containment edges
    # ------------------------------------------------------------------
    yaml_files = sorted(samples_path.rglob("*.yaml"))
    # Filter out field index files and metadata
    yaml_files = [
        f for f in yaml_files
        if not f.name.endswith("_fields.yaml")
        and f.name != "discovery_metadata.yaml"
    ]

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as fh:
                table_meta = yaml.safe_load(fh)
        except Exception as e:
            log.warning("KG extract: failed to parse %s: %s", yaml_file, e)
            continue

        if not table_meta or not isinstance(table_meta, dict):
            continue

        conn_name = table_meta.get("database", "")
        schema_name = table_meta.get("schema", "") or ""
        table_name = table_meta.get("table_name", "")
        row_count = table_meta.get("row_count")
        columns = table_meta.get("columns", [])
        sql_table_ref = table_meta.get("sql_table_ref", "")

        if not conn_name or not table_name:
            continue

        # Normalize schema: skip if same as connection name
        if _normalize_name(schema_name) == _normalize_name(conn_name):
            schema_name = ""

        # --- Connection entity ---
        conn_eid = _eid("conn", conn_name)
        if conn_eid not in seen_entities:
            result.entities.append({
                "entity_id": conn_eid,
                "entity_type": "connection",
                "name": conn_name,
                "qualified_name": conn_name,
                "description": f"Database connection '{conn_name}'.",
                "properties_json": _props({}),
                "source_connection": conn_name,
                "embedding": None,
                "embedding_model": None,
                "tier": 1,
                "discovered_at": now,
                "updated_at": now,
            })
            seen_entities.add(conn_eid)
            result.entities_added += 1

        # --- Schema entity (if present) ---
        parent_eid = conn_eid
        if schema_name:
            schema_eid = _eid("schema", conn_name, schema_name)
            if schema_eid not in seen_entities:
                result.entities.append({
                    "entity_id": schema_eid,
                    "entity_type": "schema",
                    "name": schema_name,
                    "qualified_name": f"{conn_name}.{schema_name}",
                    "description": f"Schema '{schema_name}' in connection '{conn_name}'.",
                    "properties_json": _props({}),
                    "source_connection": conn_name,
                    "embedding": None,
                    "embedding_model": None,
                    "tier": 1,
                    "discovered_at": now,
                    "updated_at": now,
                })
                seen_entities.add(schema_eid)
                result.entities_added += 1

                # Edge: connection → schema
                eid = _edge_id(conn_eid, "contains", schema_eid)
                result.edges.append({
                    "edge_id": eid,
                    "source_id": conn_eid,
                    "target_id": schema_eid,
                    "rel_type": "contains",
                    "confidence": 1.0,
                    "evidence": "schema discovery",
                    "properties_json": None,
                    "tier": 1,
                    "created_at": now,
                })
                result.edges_added += 1

            parent_eid = schema_eid

        # --- Table entity ---
        if schema_name:
            table_qname = f"{conn_name}.{schema_name}.{table_name}"
            table_eid = _eid("table", conn_name, schema_name, table_name)
        else:
            table_qname = f"{conn_name}.{table_name}"
            table_eid = _eid("table", conn_name, table_name)

        table_props = {"row_count": row_count, "column_count": len(columns)}
        if sql_table_ref:
            table_props["sql_table_ref"] = sql_table_ref

        result.entities.append({
            "entity_id": table_eid,
            "entity_type": "table",
            "name": table_name,
            "qualified_name": table_qname,
            "description": (
                f"Table '{table_name}' with {len(columns)} columns"
                + (f" and {row_count:,} rows" if row_count else "")
                + "."
            ),
            "properties_json": _props(table_props),
            "source_connection": conn_name,
            "embedding": None,
            "embedding_model": None,
            "tier": 1,
            "discovered_at": now,
            "updated_at": now,
        })
        seen_entities.add(table_eid)
        result.entities_added += 1

        # Index table name for FK heuristics
        norm_tname = _normalize_name(table_name)
        table_name_index[norm_tname] = table_eid
        # Also index singular form (naive: strip trailing 's')
        if norm_tname.endswith("s") and len(norm_tname) > 2:
            table_stem_index[norm_tname[:-1]] = table_eid
        table_stem_index[norm_tname] = table_eid

        # Edge: parent → table
        eid = _edge_id(parent_eid, "contains", table_eid)
        result.edges.append({
            "edge_id": eid,
            "source_id": parent_eid,
            "target_id": table_eid,
            "rel_type": "contains",
            "confidence": 1.0,
            "evidence": "schema discovery",
            "properties_json": None,
            "tier": 1,
            "created_at": now,
        })
        result.edges_added += 1

        # --- Column entities ---
        for col in columns:
            col_name = col.get("name", "")
            if not col_name:
                continue

            col_meta = col.get("metadata", {})
            if schema_name:
                col_qname = f"{conn_name}.{schema_name}.{table_name}.{col_name}"
                col_eid = _eid("col", conn_name, schema_name, table_name, col_name)
            else:
                col_qname = f"{conn_name}.{table_name}.{col_name}"
                col_eid = _eid("col", conn_name, table_name, col_name)

            col_props: Dict[str, Any] = {
                "data_type": col.get("type", ""),
                "nullable": col.get("nullable", True),
            }
            if col_meta.get("distinct_count") is not None:
                col_props["distinct_count"] = col_meta["distinct_count"]
            if col_meta.get("min") is not None:
                col_props["min"] = col_meta["min"]
            if col_meta.get("max") is not None:
                col_props["max"] = col_meta["max"]
            dist = col_meta.get("value_distribution", [])
            if dist:
                col_props["top_values"] = [
                    {"value": d.get("value"), "count": d.get("count"), "pct": d.get("percentage")}
                    for d in dist[:5]
                ]

            col_type_str = col.get("type", "")
            desc_parts = [f"Column '{col_name}' ({col_type_str}) in {table_qname}."]
            if col_meta.get("distinct_count") is not None:
                desc_parts.append(f"{col_meta['distinct_count']} distinct values.")
            if row_count:
                desc_parts.append(f"Table has {row_count:,} rows.")

            result.entities.append({
                "entity_id": col_eid,
                "entity_type": "column",
                "name": col_name,
                "qualified_name": col_qname,
                "description": " ".join(desc_parts),
                "properties_json": _props(col_props),
                "source_connection": conn_name,
                "embedding": None,
                "embedding_model": None,
                "tier": 1,
                "discovered_at": now,
                "updated_at": now,
            })
            seen_entities.add(col_eid)
            result.entities_added += 1

            # Edge: table → column
            eid = _edge_id(table_eid, "contains", col_eid)
            result.edges.append({
                "edge_id": eid,
                "source_id": table_eid,
                "target_id": col_eid,
                "rel_type": "contains",
                "confidence": 1.0,
                "evidence": "schema discovery",
                "properties_json": _props({"ordinal": columns.index(col)}),
                "tier": 1,
                "created_at": now,
            })
            result.edges_added += 1

            # Index for cross-table analysis
            col_name_index[_normalize_name(col_name)].append(
                (col_eid, table_eid, conn_name, schema_name, table_name)
            )

            # Column observations
            col_obs = _extract_column_observations(
                col, col_eid, table_eid, row_count, dream_session_id, now
            )
            result.observations.extend(col_obs)
            result.observations_added += len(col_obs)

    # ------------------------------------------------------------------
    # Pass 2: Cross-table relationship inference
    # ------------------------------------------------------------------

    # 2a: Same-name columns across different tables
    for col_name_norm, occurrences in col_name_index.items():
        if len(occurrences) < 2:
            continue
        # Skip very generic names
        if col_name_norm in {"id", "name", "type", "status", "created_at",
                             "updated_at", "description", "metadata", "value",
                             "key", "data", "timestamp", "date", "label",
                             "title", "deleted_at", "is_active", "is_deleted"}:
            continue
        # Create same_name edges between all pairs (within reason)
        if len(occurrences) > 10:
            # Too many — probably a generic name we missed
            continue
        for i, (eid_a, tbl_a, conn_a, _, tname_a) in enumerate(occurrences):
            for eid_b, tbl_b, conn_b, _, tname_b in occurrences[i + 1:]:
                if tbl_a == tbl_b:
                    continue
                edge = _edge_id(eid_a, "same_name", eid_b)
                cross_conn = conn_a != conn_b
                result.edges.append({
                    "edge_id": edge,
                    "source_id": eid_a,
                    "target_id": eid_b,
                    "rel_type": "same_name",
                    "confidence": 0.5 if cross_conn else 0.7,
                    "evidence": f"same column name '{col_name_norm}' across tables",
                    "properties_json": _props({"cross_connection": cross_conn}),
                    "tier": 1,
                    "created_at": now,
                })
                result.edges_added += 1

    # 2b: Likely FK via naming convention (customer_id → customers table)
    for col_name_norm, occurrences in col_name_index.items():
        fk_stem = _infer_fk_table_stem(col_name_norm)
        if not fk_stem:
            continue
        target_table_eid = table_stem_index.get(fk_stem)
        if not target_table_eid:
            continue
        for col_eid, table_eid, _, _, _ in occurrences:
            # Don't create FK edge to self table
            if table_eid == target_table_eid:
                continue
            edge = _edge_id(col_eid, "likely_fk", target_table_eid)
            result.edges.append({
                "edge_id": edge,
                "source_id": col_eid,
                "target_id": target_table_eid,
                "rel_type": "likely_fk",
                "confidence": 0.7,
                "evidence": f"column '{col_name_norm}' matches table name pattern",
                "properties_json": _props({"inferred_stem": fk_stem}),
                "tier": 1,
                "created_at": now,
            })
            result.edges_added += 1

    return result


# ---------------------------------------------------------------------------
# Public API: extract + persist
# ---------------------------------------------------------------------------

def extract_kg_from_crawl(
    samples_dir: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run Tier 1 KG extraction from crawl YAML and persist to system tables.

    Args:
        samples_dir: Path to sql_connections/samples/. Auto-detected if None.
        session_id: Optional dream session ID. Auto-generated if None.

    Returns:
        Summary dict with counts.
    """
    from ..config import get_config
    from ..db_adapter import get_db_adapter

    cfg = get_config()
    if samples_dir is None:
        samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    dream_session_id = session_id or str(uuid.uuid4())
    now = _now()

    # Record dream session start
    db = get_db_adapter()
    db.insert_rows("kg_dream_sessions", [{
        "session_id": dream_session_id,
        "tier": 1,
        "scope": samples_dir,
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

    try:
        result = extract_from_crawl_yaml(samples_dir)

        # Persist in batches
        if result.entities:
            db.insert_rows("kg_entities", result.entities)
        if result.edges:
            db.insert_rows("kg_edges", result.edges)
        if result.observations:
            db.insert_rows("kg_observations", result.observations)

        elapsed = time.monotonic() - t0
        summary = (
            f"Tier 1 extraction: {result.entities_added} entities, "
            f"{result.edges_added} edges, {result.observations_added} observations "
            f"in {elapsed:.1f}s"
        )

        # Update dream session
        db.insert_rows("kg_dream_sessions", [{
            "session_id": dream_session_id,
            "tier": 1,
            "scope": samples_dir,
            "status": "completed",
            "entities_added": result.entities_added,
            "entities_updated": result.entities_updated,
            "edges_added": result.edges_added,
            "observations_added": result.observations_added,
            "summary": summary,
            "started_at": now,
            "completed_at": _now(),
        }])

        log.info("KG Tier 1: %s", summary)
        return {
            "session_id": dream_session_id,
            "entities_added": result.entities_added,
            "entities_updated": result.entities_updated,
            "edges_added": result.edges_added,
            "observations_added": result.observations_added,
            "elapsed_seconds": round(elapsed, 2),
            "summary": summary,
        }

    except Exception as e:
        db.insert_rows("kg_dream_sessions", [{
            "session_id": dream_session_id,
            "tier": 1,
            "scope": samples_dir,
            "status": "failed",
            "entities_added": 0,
            "entities_updated": 0,
            "edges_added": 0,
            "observations_added": 0,
            "summary": f"Failed: {e}",
            "started_at": now,
            "completed_at": _now(),
        }])
        raise
