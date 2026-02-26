from contextlib import contextmanager

from lars import db_adapter
from lars.sql_tools import sql_duckdb_index as idx
import yaml


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _sql, _args):
        return _FakeExecuteResult(self._rows)


@contextmanager
def _fake_reader(rows):
    yield _FakeConn(rows)


def test_search_sql_index_caches_query_embeddings(monkeypatch):
    with idx._query_embed_cache_lock:
        idx._query_embed_cache.clear()

    embed_calls = {"n": 0}

    def _fake_embed_texts(**kwargs):
        embed_calls["n"] += 1
        return {"embeddings": [[0.1, 0.2, 0.3]], "dim": 3, "model": kwargs.get("model")}

    rows = [("doc1", 0, "demo/users.yaml", 1, 10, "users table", 0.1)]

    monkeypatch.setattr(idx, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(idx, "_reader_connection", lambda: _fake_reader(rows))

    first = idx.search_sql_index(
        rag_id="rag1",
        embed_model="test-model",
        query="users email",
        k=5,
        score_threshold=0.0,
        index_embedding_dim=3,
    )
    second = idx.search_sql_index(
        rag_id="rag1",
        embed_model="test-model",
        query="users email",
        k=5,
        score_threshold=0.0,
        index_embedding_dim=3,
    )

    assert embed_calls["n"] == 1
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["doc_id"] == "doc1"


def test_search_sql_index_falls_back_to_lexical_when_embedding_fails(monkeypatch):
    with idx._query_embed_cache_lock:
        idx._query_embed_cache.clear()

    sentinel = [{"chunk_id": "docx_0", "doc_id": "docx", "source": "x.yaml", "lines": [1, 1], "score": 0.5, "snippet": "x"}]

    monkeypatch.setattr(idx, "embed_texts", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("rate limit")))
    monkeypatch.setattr(idx, "_lexical_search_sql_index", lambda **kwargs: sentinel)

    result = idx.search_sql_index(
        rag_id="rag1",
        embed_model="test-model",
        query="users email",
        k=5,
        score_threshold=0.3,
        index_embedding_dim=3,
    )

    assert result == sentinel


def test_sql_index_shadow_snapshot_mapping(monkeypatch):
    captured: list[dict] = []

    monkeypatch.setattr(
        db_adapter,
        "get_shadow_write_stats",
        lambda: {"enabled": True, "write_all_tables": True, "tables": []},
    )

    def _fake_mirror_rows_to_shadow(**kwargs):
        captured.append(kwargs)
        return {"enabled": True, "rows_enqueued": len(kwargs.get("rows") or [])}

    monkeypatch.setattr(db_adapter, "mirror_rows_to_shadow", _fake_mirror_rows_to_shadow)

    idx._mirror_sql_index_snapshot_to_shadow(
        rag_id="rag_x",
        model_used="embed-model",
        embedding_dim=3,
        abs_samples="/tmp/samples",
        chunk_rows=[
            (
                "c1",
                "rag_x",
                "d1",
                0,
                "hello",
                [0.1, 0.2, 0.3],
                "demo/users.yaml",
                1,
                4,
                0,
                24,
                "fh1",
                "embed-model",
                3,
                12345,
            )
        ],
        manifest_rows=[
            ("rag_x", "d1", "demo/users.yaml", "fh1", 99, 1700000000, 1),
        ],
        updated_at_ms=12345,
    )

    assert [call["table"] for call in captured] == [
        "sql_rag_chunks",
        "sql_rag_manifests",
        "sql_rag_meta",
    ]
    assert captured[0]["clear_table"] is True
    assert captured[0]["rows"][0]["chunk_id"] == "c1"
    assert captured[1]["rows"][0]["doc_id"] == "d1"
    assert captured[2]["rows"][0]["rag_id"] == "rag_x"


def test_text_for_indexing_strips_table_heavy_payloads(tmp_path):
    table_yaml = """
table_name: users
schema: public
database: demo
columns:
  - name: bio
    type: VARCHAR
    metadata:
      distinct_count: 3
      value_distribution:
        - value: very long text blob
          count: 2
sample_columns: [id, bio]
sample_rows:
  - [1, "sample"]
"""

    out = idx._text_for_indexing(tmp_path / "users.yaml", table_yaml)
    parsed = yaml.safe_load(out)

    assert "sample_rows" not in parsed
    assert "sample_columns" not in parsed
    assert "value_distribution" not in parsed["columns"][0]["metadata"]


def test_text_for_indexing_strips_field_sample_values_but_keeps_range(tmp_path):
    field_yaml = """
source_table: demo.users
fields:
  - field: bio
    type: VARCHAR
    description: "Field 'bio' in table demo.users. Type: VARCHAR. Sample values: lorem ipsum, dolor sit amet. Range: a to z."
"""

    out = idx._text_for_indexing(tmp_path / "users_fields.yaml", field_yaml)
    parsed = yaml.safe_load(out)
    desc = parsed["fields"][0]["description"]

    assert "Sample values:" not in desc
    assert "Range: a to z." in desc
