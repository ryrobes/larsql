"""
DuckPGQ property graph view over KG tables.

Registers a DuckDB property graph named 'lars_kg' that enables
graph pattern matching queries like:

    SELECT * FROM GRAPH_TABLE(lars_kg
        MATCH (a:Entity)-[r:Edge]->(b:Entity)
        WHERE a.name = 'customers'
        COLUMNS (a.entity_id, r.rel_type, b.entity_id AS target, b.name AS target_name)
    )
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# The SQL to create the property graph over KG tables.
# Expects kg_entities and kg_edges views to already be registered.
CREATE_PROPERTY_GRAPH_SQL = """
CREATE OR REPLACE PROPERTY GRAPH lars_kg
VERTEX TABLES (
    kg_entities
        LABEL Entity
        PROPERTIES (entity_id, entity_type, name, qualified_name, description,
                    properties_json, source_connection, tier)
)
EDGE TABLES (
    kg_edges
        SOURCE KEY (source_id) REFERENCES kg_entities (entity_id)
        DESTINATION KEY (target_id) REFERENCES kg_entities (entity_id)
        LABEL Edge
        PROPERTIES (edge_id, rel_type, confidence, evidence, properties_json, tier)
);
"""


def ensure_kg_property_graph(conn) -> bool:
    """
    Create/replace the lars_kg property graph on the given DuckDB connection.

    Args:
        conn: A DuckDB connection with kg_entities and kg_edges views registered.

    Returns:
        True if created successfully, False on error.
    """
    try:
        conn.execute(CREATE_PROPERTY_GRAPH_SQL)
        return True
    except Exception as e:
        log.warning("Failed to create lars_kg property graph: %s", e)
        return False


def kg_path_query(
    conn,
    source_name: str,
    target_name: str,
    max_hops: int = 4,
) -> list:
    """
    Find paths between two entities using graph pattern matching.

    Args:
        conn: DuckDB connection with lars_kg property graph.
        source_name: Name or qualified_name of source entity.
        target_name: Name or qualified_name of target entity.
        max_hops: Maximum path length (default 4).

    Returns:
        List of path dicts.
    """
    # Use iterative CTE approach since DuckPGQ variable-length paths
    # have limited support. For now, try direct 1-hop and 2-hop.
    results = []
    for hops in range(1, min(max_hops, 4) + 1):
        match_pattern = _build_match_pattern(hops)
        columns = _build_columns(hops)
        sql = f"""
            SELECT * FROM GRAPH_TABLE(lars_kg
                MATCH {match_pattern}
                WHERE a.name = ? OR a.qualified_name = ?
                  AND z.name = ? OR z.qualified_name = ?
                COLUMNS ({columns})
            ) LIMIT 50
        """
        try:
            rows = conn.execute(sql, [source_name, source_name,
                                       target_name, target_name]).fetchall()
            if rows:
                desc = [d[0] for d in conn.description]
                results.extend([dict(zip(desc, row)) for row in rows])
        except Exception:
            # DuckPGQ may not support this pattern length
            break

    return results


def _build_match_pattern(hops: int) -> str:
    if hops == 1:
        return "(a:Entity)-[r1:Edge]->(z:Entity)"
    if hops == 2:
        return "(a:Entity)-[r1:Edge]->(b:Entity)-[r2:Edge]->(z:Entity)"
    if hops == 3:
        return "(a:Entity)-[r1:Edge]->(b:Entity)-[r2:Edge]->(c:Entity)-[r3:Edge]->(z:Entity)"
    return "(a:Entity)-[r1:Edge]->(b:Entity)-[r2:Edge]->(c:Entity)-[r3:Edge]->(d:Entity)-[r4:Edge]->(z:Entity)"


def _build_columns(hops: int) -> str:
    cols = ["a.entity_id AS source_id", "a.name AS source_name"]
    for i in range(1, hops + 1):
        cols.append(f"r{i}.rel_type AS rel_{i}")
    if hops >= 2:
        cols.append("b.name AS hop_1")
    if hops >= 3:
        cols.append("c.name AS hop_2")
    if hops >= 4:
        cols.append("d.name AS hop_3")
    cols.extend(["z.entity_id AS target_id", "z.name AS target_name"])
    return ", ".join(cols)
