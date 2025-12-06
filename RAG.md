# Windlass RAG (Retrieval-Augmented Generation)

First-class RAG support lets any phase index a directory and expose retrieval tools automatically.

## Quick Start
- In a phase, add a `rag` block with just a directory: `"rag": {"directory": "docs"}`
- When the phase starts, Windlass builds/updates a Parquet index under `data/rag/<rag_id>/`.
- Tools are auto-injected: `rag_search`, `rag_read_chunk`, `rag_list_sources`.
- A short prompt hint is added so the agent knows to search before answering and how to cite sources.

## Defaults
- Directory resolution: relative paths are resolved against the cascade file; absolute paths are honored.
- Recursive: `false` (set `"recursive": true` to walk subfolders).
- Include globs: `["*.md","*.markdown","*.txt","*.rst","*.json","*.yaml","*.yml","*.csv","*.tsv","*.py"]`
- Exclude globs: `[".git/**","node_modules/**","__pycache__/**","*.png","*.jpg","*.jpeg","*.gif","*.bmp","*.svg","*.pdf","*.zip","*.tar","*.gz","*.parquet","*.feather"]`
- Chunking: `chunk_chars=1200`, `chunk_overlap=200`.
- Embeddings:
  - Model: `rag.embed_model` or `WINDLASS_RAG_EMBED_MODEL` (default `text-embedding-3-small`)
  - Backend: `rag.embed_backend` or `WINDLASS_RAG_EMBED_BACKEND` (`auto` | `litellm` | `deterministic`)
  - Base URL/API key: `rag.embed_base_url` / `rag.embed_api_key` (defaults to Windlass provider base/api key). Use this to point at OpenRouter, or a local Ollama endpoint.
  - Deterministic, offline embeddings: set backend to `deterministic`.

## Incremental Indexing
- Manifest and chunks are stored in Parquet: `data/rag/<rag_id>/manifest.parquet` and `chunks.parquet`.
- Unchanged files (size + mtime) are reused; only new/changed files are re-chunked/re-embedded; deleted files are dropped.
- `rag_id` is derived from directory + options so different chunk sizes/models isolate their own indices.

## Tools
- `rag_search(query, k=5, score_threshold=None, doc_filter=None)` → top chunks with scores, sources, and line ranges.
- `rag_read_chunk(chunk_id)` → full chunk text + metadata.
- `rag_list_sources()` → document list with chunk counts/sizes.
All tool results are JSON strings for easy downstream handling.

## Notes
- DuckDB-compatible Parquet layout; no SQLite fallback needed.
- If an index was built with real embeddings and litellm is unavailable later, searches will raise with a clear message rather than mixing embedding dimensions. Set the backend to deterministic if you need offline usage.
- Example cascade: `examples/rag_qa.json`.
