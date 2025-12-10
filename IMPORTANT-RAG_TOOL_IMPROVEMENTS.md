# RAG Tool Improvements: Token-Efficient Retrieval

## Problem Statement

RAG (Retrieval Augmented Generation) queries can bring in massive amounts of context:

1. **Unbounded retrieval** - Top-K results with large chunks = token explosion
2. **One-size-fits-all chunking** - Schema files need different treatment than prose
3. **No token awareness** - Agent can't predict or control token usage
4. **SQL schemas are special** - Can't summarize column definitions without breaking queries

Unlike SQL where we can refine queries with `WHERE`/`LIMIT`, RAG's whole point is retrieving unknown context. But we need control without losing the answer.

## Solution Overview

A **layered approach** that maintains completeness where needed while controlling tokens:

1. **Token budget parameter** - Predictable, declarative token control
2. **Compact mode for SQL schemas** - Lightweight discovery, full details on demand
3. **Optimized chunk sizes** - Different strategies for schemas vs prose
4. **Dual-tool pattern** - Bounded (default) + deep (opt-in), consistent with SQL tools

---

## Current Architecture Analysis

### Chunking Configuration

```python
# cascade.py - RagConfig defaults
chunk_chars: int = 1200    # ~300-400 tokens
chunk_overlap: int = 200   # ~50 tokens
```

### Existing Progressive Disclosure

The current implementation already has a two-stage pattern:

```python
# rag_search returns snippets (400 chars)
results.append({
    "chunk_id": row["chunk_id"],
    "source": row["rel_path"],
    "score": float(row["score"]),
    "snippet": row["text"][:400].strip(),  # Truncated!
})

# rag_read_chunk returns full content
def rag_read_chunk(chunk_id: str) -> str:
    """Fetch the full text of a chunk by chunk_id."""
```

**This is good!** We're enhancing it, not replacing it.

### Two RAG Use Cases

| Use Case | Truncation OK? | Why |
|----------|----------------|-----|
| **General RAG** (docs, code, notes) | Yes | Snippets sufficient for relevance |
| **SQL Schema RAG** | **No** | Column names/types must be exact |

---

## Implementation Plan

### 1. Token Budget for General RAG

Add token awareness to `rag_search` with predictable budget control.

#### File: `windlass/windlass/rag/tools.py`

```python
import json
from typing import Optional

from .context import get_current_rag_context
from .store import list_sources, read_chunk, search_chunks

# Rough estimate: 1 token ≈ 4 chars for English text
CHARS_PER_TOKEN = 4

def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return len(text) // CHARS_PER_TOKEN


def _require_context():
    ctx = get_current_rag_context()
    if not ctx:
        raise ValueError("No active RAG context. Add a `rag` block to the phase to enable RAG tools.")
    return ctx


def rag_search(
    query: str,
    k: int = 10,
    token_budget: int = 3000,
    return_full: bool = False,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None
) -> str:
    """
    Semantic search over the indexed directory with token budget control.

    Returns top matching chunks that fit within the token budget.
    By default returns snippets (400 chars); set return_full=True for complete content.

    Use rag_read_chunk(chunk_id) to fetch full content of specific chunks.
    Use rag_search_deep() if you need all results without budget limits.

    Args:
        query: Natural language search query
        k: Maximum candidates to consider (default: 10)
        token_budget: Maximum total tokens to return (default: 3000)
        return_full: Return full chunk content instead of snippets (default: False)
        score_threshold: Minimum similarity score filter (optional)
        doc_filter: Filter by document path pattern (optional)

    Returns:
        JSON with matching chunks and token usage metadata:
        {
          "results": [...],
          "tokens_used": 2800,
          "token_budget": 3000,
          "chunks_returned": 4,
          "chunks_available": 8,
          "truncated": true,
          "note": "Returned 4 of 8 matching chunks within budget. Use rag_read_chunk() for full content."
        }
    """
    ctx = _require_context()

    # Get candidates (fetch more than k to have options)
    candidates = search_chunks(
        ctx, query,
        k=k,
        score_threshold=score_threshold,
        doc_filter=doc_filter
    )

    if not candidates:
        return json.dumps({
            "rag_id": ctx.rag_id,
            "directory": ctx.directory,
            "results": [],
            "tokens_used": 0,
            "token_budget": token_budget,
            "chunks_returned": 0,
            "chunks_available": 0,
            "message": "No matches found. Try a broader query or different keywords."
        })

    # Build results within token budget
    results = []
    tokens_used = 0
    chunks_available = len(candidates)

    for candidate in candidates:
        # Determine content to include
        if return_full:
            # Fetch full chunk content
            try:
                full_chunk = read_chunk(ctx, candidate["chunk_id"])
                content = full_chunk["text"]
            except Exception:
                content = candidate.get("snippet", "")
        else:
            # Use snippet (already truncated to 400 chars in search_chunks)
            content = candidate.get("snippet", "")

        # Estimate tokens for this result
        # Include metadata overhead (~50 tokens for JSON structure)
        result_tokens = _estimate_tokens(content) + 50

        # Check budget
        if tokens_used + result_tokens > token_budget and results:
            # Budget exhausted, stop adding
            break

        # Add to results
        result = {
            "chunk_id": candidate["chunk_id"],
            "doc_id": candidate["doc_id"],
            "source": candidate["source"],
            "lines": candidate["lines"],
            "score": candidate["score"],
            "tokens": result_tokens - 50,  # Content tokens only
        }

        if return_full:
            result["content"] = content
        else:
            result["snippet"] = content

        results.append(result)
        tokens_used += result_tokens

    # Build response
    truncated = len(results) < chunks_available
    payload = {
        "rag_id": ctx.rag_id,
        "directory": ctx.directory,
        "results": results,
        "tokens_used": tokens_used,
        "token_budget": token_budget,
        "chunks_returned": len(results),
        "chunks_available": chunks_available,
        "truncated": truncated,
    }

    if truncated:
        payload["note"] = (
            f"Returned {len(results)} of {chunks_available} matching chunks within budget. "
            "Use rag_read_chunk(chunk_id) for full content, or rag_search_deep() for all results."
        )

    return json.dumps(payload)


def rag_search_deep(
    query: str,
    k: int = 20,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None
) -> str:
    """
    Deep semantic search WITHOUT token budget limits. Returns full chunk content.

    ⚠️  WARNING: Large results will consume many tokens. Use with caution.

    Prefer rag_search() for exploratory queries. Only use this when you
    explicitly need comprehensive results for thorough analysis.

    Args:
        query: Natural language search query
        k: Maximum results to return (default: 20)
        score_threshold: Minimum similarity score filter (optional)
        doc_filter: Filter by document path pattern (optional)

    Returns:
        JSON with full chunk content for all matches
    """
    ctx = _require_context()

    candidates = search_chunks(
        ctx, query,
        k=k,
        score_threshold=score_threshold,
        doc_filter=doc_filter
    )

    results = []
    total_tokens = 0

    for candidate in candidates:
        try:
            full_chunk = read_chunk(ctx, candidate["chunk_id"])
            content = full_chunk["text"]
        except Exception:
            content = candidate.get("snippet", "")

        content_tokens = _estimate_tokens(content)
        total_tokens += content_tokens

        results.append({
            "chunk_id": candidate["chunk_id"],
            "doc_id": candidate["doc_id"],
            "source": candidate["source"],
            "lines": candidate["lines"],
            "score": candidate["score"],
            "tokens": content_tokens,
            "content": content,
        })

    return json.dumps({
        "rag_id": ctx.rag_id,
        "directory": ctx.directory,
        "results": results,
        "total_tokens": total_tokens,
        "chunks_returned": len(results),
        "warning": "Deep search returns full content. Consider rag_search() with token budget for efficiency."
    })


def rag_read_chunk(chunk_id: str) -> str:
    """
    Fetch the full text of a chunk by chunk_id along with source metadata.

    Use this after rag_search() to get complete content for specific chunks.
    """
    ctx = _require_context()
    try:
        chunk = read_chunk(ctx, chunk_id)
        # Add token estimate
        chunk["tokens"] = _estimate_tokens(chunk.get("text", ""))
        return json.dumps(chunk)
    except Exception as e:
        sources = list_sources(ctx)
        return json.dumps({
            "error": str(e),
            "rag_id": ctx.rag_id,
            "directory": ctx.directory,
            "hint": "Call rag_search and use a chunk_id from the search results.",
            "available_documents": [s["rel_path"] for s in sources][:10]
        })


def rag_list_sources() -> str:
    """
    List available documents in the RAG index with basic metadata.
    """
    ctx = _require_context()
    sources = list_sources(ctx)
    return json.dumps({
        "rag_id": ctx.rag_id,
        "directory": ctx.directory,
        "document_count": len(sources),
        "documents": sources
    })
```

### 2. Compact Mode for SQL Schema Search

Add lightweight schema discovery mode to `sql_search`.

#### File: `windlass/windlass/sql_tools/tools.py`

```python
def sql_search(
    query: str,
    k: int = 10,
    score_threshold: Optional[float] = 0.3,
    compact: bool = False,
    include_samples: bool = True,
    include_distributions: bool = True
) -> str:
    """
    Search SQL schema metadata using semantic search.

    Finds relevant tables and columns across all configured databases.
    Returns table metadata including column info, distributions, and sample values.

    Modes:
    - Default: Full metadata (columns, samples, distributions)
    - compact=True: Minimal schema (table names, column names + types only)

    Use compact mode for initial discovery, then fetch specific tables with full details.

    Args:
        query: Natural language description of what to find
        k: Number of results to return (default: 10)
        score_threshold: Minimum similarity score (default: 0.3)
        compact: Return minimal schema info only (default: False)
        include_samples: Include sample rows (default: True, ignored if compact=True)
        include_distributions: Include value distributions (default: True, ignored if compact=True)

    Returns:
        JSON with matching tables and their metadata
    """
    # Load discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        return json.dumps({
            "error": "No SQL schema index found. Run: windlass sql chart",
            "hint": "The discovery process charts all databases and builds a searchable index."
        })

    # Get RAG context (existing code)
    cfg = get_config()
    samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    rag_base = os.path.join(cfg.data_dir, "rag", meta.rag_id)
    manifest_path = os.path.join(rag_base, "manifest.parquet")
    chunks_path = os.path.join(rag_base, "chunks.parquet")
    meta_path = os.path.join(rag_base, "meta.json")

    if not os.path.exists(manifest_path):
        return json.dumps({
            "error": f"RAG index files not found for rag_id: {meta.rag_id}",
            "hint": "Run: windlass sql chart"
        })

    rag_ctx = RagContext(
        rag_id=meta.rag_id,
        directory=samples_dir,
        manifest_path=manifest_path,
        chunks_path=chunks_path,
        meta_path=meta_path,
        embed_model=meta.embed_model,
        stats={},
        session_id=None,
        cascade_id=None,
        phase_name=None,
        trace_id=None,
        parent_id=None
    )

    # Search
    results = search_chunks(
        rag_ctx=rag_ctx,
        query=query,
        k=k,
        score_threshold=score_threshold
    )

    if not results:
        return json.dumps({
            "query": query,
            "message": "No matching tables found. Try a broader query or different keywords.",
            "rag_id": meta.rag_id,
            "databases_available": meta.databases_indexed
        })

    # Parse results
    tables = []
    seen_tables = set()

    for result in results:
        full_path = os.path.join(samples_dir, result['source'])

        if full_path in seen_tables:
            continue
        seen_tables.add(full_path)

        try:
            with open(full_path) as f:
                table_meta = json.load(f)

                # Build qualified table name
                if table_meta['schema'] and table_meta['schema'] != table_meta['database']:
                    qualified_name = f"{table_meta['database']}.{table_meta['schema']}.{table_meta['table_name']}"
                else:
                    qualified_name = f"{table_meta['database']}.{table_meta['table_name']}"

                if compact:
                    # Compact mode: minimal schema info
                    tables.append({
                        "qualified_name": qualified_name,
                        "database": table_meta['database'],
                        "table_name": table_meta['table_name'],
                        "row_count": table_meta['row_count'],
                        "column_count": len(table_meta['columns']),
                        "columns": [
                            {"name": c["name"], "type": c["type"]}
                            for c in table_meta['columns']
                        ],
                        "match_score": result['score']
                    })
                else:
                    # Full mode: all metadata
                    columns = table_meta['columns']

                    # Optionally strip distributions
                    if not include_distributions:
                        columns = [
                            {k: v for k, v in c.items() if k != 'distribution'}
                            for c in columns
                        ]

                    table_entry = {
                        "qualified_name": qualified_name,
                        "database": table_meta['database'],
                        "schema": table_meta['schema'],
                        "table_name": table_meta['table_name'],
                        "row_count": table_meta['row_count'],
                        "columns": columns,
                        "match_score": result['score']
                    }

                    # Optionally include samples
                    if include_samples:
                        table_entry["sample_rows"] = table_meta['sample_rows'][:5]

                    tables.append(table_entry)

        except Exception as e:
            print(f"Warning: Failed to load {full_path}: {e}")

    # Estimate tokens for response
    response_str = json.dumps(tables, default=str)
    estimated_tokens = len(response_str) // 4

    return json.dumps({
        "query": query,
        "rag_id": meta.rag_id,
        "mode": "compact" if compact else "full",
        "total_results": len(tables),
        "estimated_tokens": estimated_tokens,
        "tables": tables,
        "hint": "Use compact=True for lightweight discovery" if not compact and estimated_tokens > 2000 else None
    }, indent=2, default=str)


def sql_search_compact(query: str, k: int = 10) -> str:
    """
    Lightweight SQL schema search - returns only table/column names and types.

    Use this for initial discovery. Follow up with sql_search() for full details
    on specific tables.

    Args:
        query: Natural language description of what to find
        k: Number of results to return (default: 10)

    Returns:
        JSON with minimal table schemas (names, column names + types)
    """
    return sql_search(query, k=k, compact=True, include_samples=False, include_distributions=False)
```

### 3. Optimized Chunk Sizes for SQL Schemas

Update the SQL discovery to use larger chunks that keep table definitions intact.

#### File: `windlass/windlass/sql_tools/discovery.py`

```python
def discover_all_schemas(session_id: str = None):
    """Chart all SQL schemas with optimized chunking for schema files."""

    # ... existing code ...

    # Build unified RAG index with larger chunks for JSON schema files
    console.print("[bold cyan]🔍 Building unified RAG index...[/bold cyan]")

    rag_config = RagConfig(
        directory=samples_dir,
        recursive=True,
        include=["*.json"],
        exclude=[],
        chunk_chars=6000,   # ~1500 tokens - fits most table definitions
        chunk_overlap=0      # No overlap needed for JSON files (each is a complete unit)
    )

    # ... rest of existing code ...
```

**Rationale:**
- Schema JSON files are typically 2-8KB each
- 6000 chars (~1500 tokens) keeps most tables in a single chunk
- No overlap needed - each JSON file is semantically complete
- Prevents fragmenting column definitions across chunks

### 4. Store Updates for Token Estimation

#### File: `windlass/windlass/rag/store.py`

Add token estimates to search results:

```python
CHARS_PER_TOKEN = 4

def search_chunks(
    rag_ctx: RagContext,
    query: str,
    k: int = 5,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search chunks with token estimates included."""

    # ... existing retrieval code ...

    results = []
    for _, row in df.iterrows():
        text = row["text"]
        snippet = text[:400].strip()

        results.append({
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "source": row["rel_path"],
            "lines": [int(row["start_line"]), int(row["end_line"])],
            "score": float(row["score"]),
            "snippet": snippet,
            # New: token estimates
            "snippet_tokens": len(snippet) // CHARS_PER_TOKEN,
            "full_tokens": len(text) // CHARS_PER_TOKEN,
        })
    return results
```

---

## Tool Registration

#### File: `windlass/windlass/__init__.py`

```python
from windlass.rag import (
    rag_search,
    rag_search_deep,
    rag_read_chunk,
    rag_list_sources,
)
from windlass.sql_tools.tools import (
    sql_search,
    sql_search_compact,
    run_sql,
    list_sql_connections,
)

# Register RAG tools
register_tackle("rag_search", rag_search)
register_tackle("rag_search_deep", rag_search_deep)
register_tackle("rag_read_chunk", rag_read_chunk)
register_tackle("rag_list_sources", rag_list_sources)

# Register SQL tools
register_tackle("sql_search", sql_search)
register_tackle("sql_search_compact", sql_search_compact)
register_tackle("run_sql", run_sql)
register_tackle("list_sql_connections", list_sql_connections)
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDLASS_RAG_TOKEN_BUDGET` | `3000` | Default token budget for `rag_search` |
| `WINDLASS_RAG_DEFAULT_K` | `10` | Default candidates to retrieve |
| `WINDLASS_CHARS_PER_TOKEN` | `4` | Token estimation ratio |

### Phase-Level Configuration (Future)

```json
{
  "name": "research_phase",
  "tackle": ["rag_search", "rag_read_chunk"],
  "rag": {
    "directory": "docs",
    "chunk_chars": 800
  },
  "tool_config": {
    "rag_search": {
      "token_budget": 5000,
      "k": 15
    }
  }
}
```

---

## Usage Examples

### Example 1: Token-Budgeted RAG Search

```json
{
  "cascade_id": "research_assistant",
  "phases": [
    {
      "name": "find_info",
      "instructions": "Find information about {{ input.topic }} in the documentation.",
      "tackle": ["rag_search", "rag_read_chunk"],
      "rag": {"directory": "docs"}
    }
  ]
}
```

Agent interaction:
```
Agent: rag_search("authentication flow", token_budget=2000)

Response:
{
  "results": [
    {"chunk_id": "abc_0", "source": "auth.md", "score": 0.92, "snippet": "...", "tokens": 95},
    {"chunk_id": "abc_1", "source": "auth.md", "score": 0.87, "snippet": "...", "tokens": 98},
    {"chunk_id": "def_0", "source": "security.md", "score": 0.81, "snippet": "...", "tokens": 102}
  ],
  "tokens_used": 445,
  "token_budget": 2000,
  "chunks_returned": 3,
  "chunks_available": 7,
  "truncated": true,
  "note": "Returned 3 of 7 matching chunks within budget. Use rag_read_chunk() for full content."
}

Agent: rag_read_chunk("abc_0")  // Get full content of most relevant chunk
```

### Example 2: SQL Schema Discovery (Compact → Full)

```json
{
  "cascade_id": "sql_analyst",
  "phases": [
    {
      "name": "discover_tables",
      "instructions": "Find tables related to {{ input.topic }} and write a query.",
      "tackle": ["sql_search_compact", "sql_search", "run_sql"]
    }
  ]
}
```

Agent interaction:
```
Agent: sql_search_compact("user purchase history")

Response:
{
  "mode": "compact",
  "tables": [
    {
      "qualified_name": "prod.public.orders",
      "row_count": 50000,
      "column_count": 12,
      "columns": [
        {"name": "id", "type": "INTEGER"},
        {"name": "user_id", "type": "INTEGER"},
        {"name": "total", "type": "DECIMAL"},
        ...
      ]
    }
  ],
  "estimated_tokens": 180
}

// Agent found what it needs, now get full details
Agent: sql_search("orders table", k=1, include_samples=True)

Response:
{
  "mode": "full",
  "tables": [
    {
      "qualified_name": "prod.public.orders",
      "columns": [...full details with distributions...],
      "sample_rows": [...]
    }
  ]
}
```

### Example 3: Deep Search (When Needed)

```json
{
  "name": "comprehensive_analysis",
  "instructions": "Analyze ALL references to {{ input.term }} in the codebase.",
  "tackle": ["rag_search_deep"]
}
```

Agent explicitly chooses deep search when comprehensive coverage matters more than token efficiency.

---

## Tool Summary

| Tool | Token Control | Use Case |
|------|---------------|----------|
| `rag_search` | Budget-limited (default: 3000) | Standard RAG queries |
| `rag_search_deep` | Unlimited | Comprehensive analysis |
| `rag_read_chunk` | Single chunk | Fetch full content after search |
| `rag_list_sources` | Minimal | Document inventory |
| `sql_search` | Full metadata | Schema details for query writing |
| `sql_search_compact` | Minimal | Initial schema discovery |

---

## Chunk Size Recommendations

### General RAG (Prose, Docs, Notes)

```python
RagConfig(
    chunk_chars=800,      # ~200 tokens - better precision
    chunk_overlap=150     # ~40 tokens - context continuity
)
```

**Why smaller:** Prose benefits from precise matching. Smaller chunks improve retrieval relevance.

### Code RAG

```python
RagConfig(
    chunk_chars=1200,     # ~300 tokens - preserve function context
    chunk_overlap=200     # ~50 tokens - overlap for continuity
)
```

**Why medium:** Code needs enough context to understand function/class boundaries.

### SQL Schema RAG

```python
RagConfig(
    chunk_chars=6000,     # ~1500 tokens - keep tables intact
    chunk_overlap=0       # No overlap - JSON files are complete units
)
```

**Why larger:** Schema files must not be fragmented. A table with 30 columns needs to stay together.

---

## Testing Plan

### Unit Tests

```python
# tests/test_rag_improvements.py

def test_token_budget_limits_results():
    """Verify token budget truncates results."""
    # Setup: index with known content
    result = rag_search("test query", token_budget=500)
    data = json.loads(result)

    assert data["tokens_used"] <= 500
    assert data["truncated"] == True
    assert "note" in data


def test_token_budget_returns_all_if_fits():
    """Verify all results returned if within budget."""
    result = rag_search("test query", token_budget=10000)
    data = json.loads(result)

    assert data["truncated"] == False
    assert data["chunks_returned"] == data["chunks_available"]


def test_compact_mode_minimal_schema():
    """Verify compact mode returns minimal fields."""
    result = sql_search_compact("users")
    data = json.loads(result)

    table = data["tables"][0]
    assert "columns" in table
    assert "sample_rows" not in table
    assert all("distribution" not in c for c in table["columns"])


def test_full_mode_includes_samples():
    """Verify full mode includes sample rows."""
    result = sql_search("users", compact=False)
    data = json.loads(result)

    table = data["tables"][0]
    assert "sample_rows" in table


def test_deep_search_no_budget():
    """Verify deep search returns all results."""
    result = rag_search_deep("test query", k=50)
    data = json.loads(result)

    assert "warning" in data
    assert "total_tokens" in data


def test_token_estimates_included():
    """Verify token estimates in search results."""
    result = rag_search("test query")
    data = json.loads(result)

    for r in data["results"]:
        assert "tokens" in r
        assert isinstance(r["tokens"], int)
```

### Integration Tests

```python
def test_schema_chunk_integrity():
    """Verify SQL schema files are not fragmented across chunks."""
    # After indexing with chunk_chars=6000
    # Each table JSON should be in a single chunk

    from windlass.rag.store import search_chunks

    results = search_chunks(ctx, "bigfoot_sightings", k=5)

    # All results for same table should have same chunk_id prefix
    table_chunks = [r for r in results if "bigfoot" in r["source"]]
    assert len(table_chunks) == 1, "Table should be in single chunk"
```

---

## Migration Notes

### Breaking Changes

1. **`rag_search` signature changed** - New parameters: `token_budget`, `return_full`
   - Default behavior similar but now includes token metadata
   - Existing cascades should work without changes

2. **SQL schema re-indexing recommended**
   - Run `windlass sql chart` after upgrade to get larger chunks
   - Old indexes will work but may have fragmented schemas

### Backward Compatibility

- Default `token_budget=3000` is generous enough for most use cases
- `rag_search_deep` provides escape hatch for unlimited retrieval
- `sql_search` still works without `compact` parameter

---

## Observability

### Logging Token Usage

All RAG operations log token estimates:

```sql
-- Query RAG token usage by session
SELECT
    session_id,
    phase_name,
    JSONExtractInt(content_json, 'tokens_used') as tokens_used,
    JSONExtractInt(content_json, 'token_budget') as budget,
    JSONExtractBool(content_json, 'truncated') as was_truncated
FROM unified_logs
WHERE JSONHas(content_json, 'token_budget')
ORDER BY timestamp DESC
```

### Metrics

Track over time:
- Average tokens_used vs token_budget (are defaults appropriate?)
- Truncation rate (are agents hitting limits often?)
- `rag_search_deep` usage (are agents needing to escape budget?)

---

## Future Enhancements

### Phase 2: Reranking Integration

```python
def rag_search(
    query: str,
    k: int = 10,
    token_budget: int = 3000,
    rerank: bool = False,        # Future: use cross-encoder
    rerank_model: str = "cohere" # Future: reranking backend
) -> str:
```

Retrieve k=50, rerank with cross-encoder, return top 5 within budget.

### Phase 3: Semantic Chunking

Replace fixed-size chunking with semantic boundaries:
- Split on paragraph/section breaks
- Keep code functions intact
- Preserve markdown headers with content

### Phase 4: Adaptive Budget

Dynamic budget based on context window remaining:
```python
def rag_search(query: str, use_remaining_budget: bool = False):
    """Auto-calculate budget from remaining context window."""
```

---

## Summary

| Before | After |
|--------|-------|
| Fixed top-K, no token awareness | Token budget with predictable limits |
| One-size-fits-all chunking | Optimized per content type |
| Single search mode | Bounded (default) + deep (opt-in) |
| Full SQL schemas always | Compact mode for discovery |
| No token estimates | Tokens included in all responses |

**Key Principle:** Control tokens without losing completeness where it matters (schemas), while providing escape hatches (deep search) for when thoroughness trumps efficiency.
