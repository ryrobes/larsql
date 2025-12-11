"""
RAG (Retrieval Augmented Generation) indexer tests.

This test requires:
- ClickHouse database (WINDLASS_CLICKHOUSE_HOST)

Skip with: pytest -m "not integration"
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from windlass.cascade import RagConfig  # noqa: E402
from windlass.rag.indexer import ensure_rag_index  # noqa: E402
from windlass.rag.store import list_sources, read_chunk, search_chunks  # noqa: E402


@pytest.fixture(autouse=True)
def deterministic_embeddings(monkeypatch):
    # Force deterministic embeddings for offline, repeatable tests.
    monkeypatch.setenv("WINDLASS_EMBED_BACKEND", "deterministic")
    yield


@pytest.mark.integration
@pytest.mark.requires_clickhouse
def test_rag_index_and_search(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    (docs_dir / "first.md").write_text(
        "Blue skies ahead.\nThis is a short note about the color blue and optimism.\n", encoding="utf-8"
    )
    (docs_dir / "second.txt").write_text(
        "Red sunsets are beautiful.\nSometimes they signal clear weather tomorrow.\n", encoding="utf-8"
    )

    rag_conf = RagConfig(directory=str(docs_dir))

    # Initial index build
    ctx = ensure_rag_index(rag_conf, cascade_path=None, session_id="rag_test")

    # Note: manifest_path/chunks_path are deprecated in ClickHouse implementation
    # (data is stored in tables, not files). Check rag_id and stats instead.
    assert ctx.rag_id is not None, "Expected valid rag_id"
    assert ctx.directory == str(docs_dir), "Expected directory to match"
    assert ctx.stats["indexed_files"] == 2

    # Search
    results = search_chunks(ctx, "blue skies", k=3)
    assert results, "Expected at least one search result"
    assert results[0]["source"].endswith("first.md")

    # Read chunk
    chunk = read_chunk(ctx, results[0]["chunk_id"])
    assert "Blue skies" in chunk["text"]
    assert chunk["lines"][0] >= 1

    # Sources list
    sources = list_sources(ctx)
    assert len(sources) == 2

    # Incremental run should skip unchanged files
    ctx_second = ensure_rag_index(rag_conf, cascade_path=None, session_id="rag_test")
    assert ctx_second.stats["indexed_files"] == 0
    assert ctx_second.stats["skipped_files"] >= 2
