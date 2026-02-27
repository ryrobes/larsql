"""
KG embedding for semantic search.

Two embedding targets:

1. **Entity embeddings** (embed_kg_entities) — builds a "search document"
   for each table entity from its description, columns, and observations,
   then embeds and stores the vector on kg_entities.embedding.

2. **Observation embeddings** (embed_kg_observations) — embeds each
   observation's content text and stores on kg_observations.embedding.
   Powers the 2-stage kg_search: first find relevant tables, then
   vector-rank observations within those tables by query similarity.

Both are Tier 2.5: run after dreaming, make the KG searchable via
cosine similarity.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search document builder
# ---------------------------------------------------------------------------

_MAX_OBS_PER_DOC = 12  # cap observations in the search doc


def _build_search_doc(
    entity: Dict[str, Any],
    children: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
) -> str:
    """Build a search document for a table entity.

    The document is designed for embedding-based retrieval: it should
    contain all the terms and concepts a user might search for when
    looking for this table.

    Format:
        Table: qualified_name (row_count rows)
        description
        Domain: tag1, tag2
        Columns: col1 (TYPE), col2 (TYPE), ...
        Observations:
        - observation text
        - ...
    """
    lines: List[str] = []

    # Header + description
    props = {}
    try:
        props = json.loads(entity.get("properties_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    qname = entity.get("qualified_name", entity.get("name", "?"))
    row_count = props.get("row_count")
    header = f"Table: {qname}"
    if row_count:
        header += f" ({row_count:,} rows)"
    lines.append(header)

    desc = entity.get("description", "")
    if desc:
        lines.append(desc)

    # Domain tags (from observations)
    for obs in observations:
        if obs.get("category") == "domain" and "Domain tags:" in (obs.get("content") or ""):
            lines.append(obs["content"])
            break

    # Columns — compact schema
    if children:
        col_parts = []
        for child in children[:30]:  # cap for very wide tables
            cp = {}
            try:
                cp = json.loads(child.get("properties_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            dtype = cp.get("data_type", "")
            col_parts.append(f"{child['name']} ({dtype})" if dtype else child["name"])
        lines.append(f"Columns: {', '.join(col_parts)}")

    # Observations (skip domain tags since we already added them)
    non_domain = [o for o in observations if o.get("category") != "domain"]
    if non_domain:
        lines.append("Observations:")
        for obs in non_domain[:_MAX_OBS_PER_DOC]:
            lines.append(f"- {obs.get('content', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------

def embed_kg_entities(
    max_entities: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Embed KG table entities for semantic search.

    For each table entity, builds a search document from its description,
    column schema, and observations, then embeds it using the configured
    embedding model.

    Args:
        max_entities: 0 = all, >0 = cap.
        force: If True, re-embed even if already embedded.

    Returns:
        Summary dict with counts.
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

    from ..config import get_config
    from ..db_adapter import get_db_adapter
    from ..rag.indexer import embed_texts

    from .skills import _query as kg_query

    console = Console()
    cfg = get_config()
    db = get_db_adapter()
    embed_model = cfg.default_embed_model

    if not embed_model:
        console.print("[yellow]No embedding model configured — skipping KG embedding[/yellow]")
        return {"embedded": 0, "error": "no embedding model configured"}

    # Find table entities that need embedding
    where_clause = "1=1" if force else "(e.embedding IS NULL OR e.embedding_model != '{model}')".format(
        model=embed_model.replace("'", "''")
    )
    limit_clause = f"LIMIT {max_entities}" if max_entities > 0 else ""
    candidates = kg_query(f"""
        SELECT e.entity_id, e.entity_type, e.name, e.qualified_name,
               e.description, e.properties_json, e.source_connection
        FROM kg_entities e
        WHERE e.entity_type = 'table'
          AND {where_clause}
        ORDER BY e.name
        {limit_clause}
    """)

    if not candidates:
        console.print("[dim]  ✓ All table entities already embedded[/dim]")
        return {"embedded": 0, "skipped": True}

    # Build search documents
    t0 = time.monotonic()
    entity_ids: List[str] = []
    search_docs: List[str] = []
    entities_data: List[Dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Building search docs", total=len(candidates))

        for entity in candidates:
            eid = entity["entity_id"]
            eid_safe = eid.replace("'", "''")

            # Get children (columns)
            children = kg_query(f"""
                SELECT e.entity_id, e.name, e.properties_json
                FROM kg_edges ed
                JOIN kg_entities e ON e.entity_id = ed.target_id
                WHERE ed.source_id = '{eid_safe}' AND ed.rel_type = 'contains'
                  AND e.entity_type = 'column'
                ORDER BY e.name
            """)

            # Get observations (Tier 1 + 2)
            observations = kg_query(f"""
                SELECT category, content, confidence, tier
                FROM kg_observations
                WHERE (entity_id = '{eid_safe}'
                       OR entity_ids_json LIKE '%{eid_safe}%')
                  AND superseded_by IS NULL
                ORDER BY tier DESC, confidence DESC
            """)

            doc = _build_search_doc(entity, children, observations)
            entity_ids.append(eid)
            search_docs.append(doc)
            entities_data.append(entity)
            progress.advance(task)

    # Batch embed
    console.print(f"[bold cyan]Embedding {len(search_docs)} search documents...[/bold cyan]")
    try:
        result = embed_texts(
            texts=search_docs,
            model=embed_model,
            session_id="kg_embedding",
            cell_name="kg_embed",
            cascade_id="kg_system",
        )
        embeddings = result.get("embeddings", [])
        embed_dim = result.get("dim", 0)
    except Exception as e:
        console.print(f"[red]Embedding failed: {e}[/red]")
        return {"embedded": 0, "error": str(e)}

    if len(embeddings) != len(entity_ids):
        console.print(f"[red]Embedding count mismatch: {len(embeddings)} vs {len(entity_ids)} entities[/red]")
        return {"embedded": 0, "error": "embedding count mismatch"}

    # Persist embeddings
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    for i, (eid, embedding) in enumerate(zip(entity_ids, embeddings)):
        entity = entities_data[i]
        db.insert_rows("kg_entities", [{
            "entity_id": eid,
            "entity_type": entity["entity_type"],
            "name": entity["name"],
            "qualified_name": entity["qualified_name"],
            "description": entity.get("description"),
            "properties_json": entity.get("properties_json"),
            "source_connection": entity.get("source_connection"),
            "embedding": [float(x) for x in embedding],
            "embedding_model": embed_model,
            "tier": entity.get("tier", 2),
            "discovered_at": now,
            "updated_at": now,
        }])

    elapsed = time.monotonic() - t0

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Entities embedded", str(len(entity_ids)))
    table.add_row("Embedding model", embed_model)
    table.add_row("Dimensions", str(embed_dim))
    table.add_row("Time", f"{elapsed:.1f}s")
    console.print(Panel(table, title="[bold cyan]🔮 KG Embedding Summary", border_style="cyan", expand=False))

    return {
        "embedded": len(entity_ids),
        "model": embed_model,
        "dim": embed_dim,
        "elapsed_seconds": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Observation embedding pipeline
# ---------------------------------------------------------------------------

def embed_kg_observations(
    max_observations: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Embed KG observation content for observation-level semantic search.

    For each observation where embedding IS NULL, embeds the raw content
    text using the configured embedding model and stores the vector back
    on kg_observations.embedding.

    These observation embeddings power Stage 2 of kg_search: after
    entity-level search finds relevant tables, observation embeddings
    let us vector-rank each table's observations against the query
    to surface only the most relevant insights.

    Args:
        max_observations: 0 = all, >0 = cap.
        force: If True, re-embed even if already embedded.

    Returns:
        Summary dict with counts.
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

    from ..config import get_config
    from ..db_adapter import get_db_adapter
    from ..rag.indexer import embed_texts_parallel

    from .skills import _query as kg_query

    console = Console()
    cfg = get_config()
    db = get_db_adapter()
    embed_model = cfg.default_embed_model

    if not embed_model:
        console.print("[yellow]No embedding model configured — skipping observation embedding[/yellow]")
        return {"embedded": 0, "error": "no embedding model configured"}

    # Find observations that need embedding
    safe_model = embed_model.replace("'", "''")
    where_clause = "1=1" if force else f"(embedding IS NULL OR embedding_model != '{safe_model}')"
    limit_clause = f"LIMIT {max_observations}" if max_observations > 0 else ""

    candidates = kg_query(f"""
        SELECT observation_id, entity_id, entity_ids_json, level, tier,
               category, content, confidence, superseded_by, dream_session_id
        FROM kg_observations
        WHERE superseded_by IS NULL
          AND {where_clause}
        ORDER BY tier DESC, confidence DESC
        {limit_clause}
    """)

    if not candidates:
        console.print("[dim]  ✓ All observations already embedded[/dim]")
        return {"embedded": 0, "skipped": True}

    # Build embedding texts — just the raw content
    t0 = time.monotonic()
    observation_ids: List[str] = []
    observation_texts: List[str] = []
    observations_data: List[Dict[str, Any]] = []

    for obs in candidates:
        content = (obs.get("content") or "").strip()
        if not content:
            continue
        observation_ids.append(obs["observation_id"])
        observation_texts.append(content)
        observations_data.append(obs)

    if not observation_texts:
        console.print("[dim]  ✓ No observations with content to embed[/dim]")
        return {"embedded": 0, "skipped": True}

    # Batch embed using parallel pipeline
    console.print(f"[bold cyan]Embedding {len(observation_texts)} observations...[/bold cyan]")
    try:
        result = embed_texts_parallel(
            texts=observation_texts,
            model=embed_model,
            session_id="kg_embedding",
            cell_name="kg_embed_observations",
            cascade_id="kg_system",
        )
        embeddings = result.get("embeddings", [])
        embed_dim = result.get("dim", 0)
    except Exception as e:
        console.print(f"[red]Observation embedding failed: {e}[/red]")
        return {"embedded": 0, "error": str(e)}

    if len(embeddings) != len(observation_ids):
        console.print(f"[red]Embedding count mismatch: {len(embeddings)} vs {len(observation_ids)} observations[/red]")
        return {"embedded": 0, "error": "embedding count mismatch"}

    # Persist embeddings
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    for i, (obs_id, embedding) in enumerate(zip(observation_ids, embeddings)):
        obs = observations_data[i]
        db.insert_rows("kg_observations", [{
            "observation_id": obs_id,
            "entity_id": obs.get("entity_id"),
            "entity_ids_json": obs.get("entity_ids_json"),
            "level": obs.get("level"),
            "tier": obs.get("tier"),
            "category": obs.get("category"),
            "content": obs.get("content"),
            "confidence": obs.get("confidence"),
            "embedding": [float(x) for x in embedding],
            "embedding_model": embed_model,
            "superseded_by": obs.get("superseded_by"),
            "dream_session_id": obs.get("dream_session_id"),
            "created_at": now,
        }])

    elapsed = time.monotonic() - t0

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Observations embedded", str(len(observation_ids)))
    table.add_row("Embedding model", embed_model)
    table.add_row("Dimensions", str(embed_dim))
    table.add_row("Time", f"{elapsed:.1f}s")
    console.print(Panel(table, title="[bold cyan]🔮 KG Observation Embedding Summary", border_style="cyan", expand=False))

    return {
        "embedded": len(observation_ids),
        "model": embed_model,
        "dim": embed_dim,
        "elapsed_seconds": round(elapsed, 2),
    }
