import json
from types import SimpleNamespace

from lars.sql_tools import tools


def _fake_rag_rows() -> str:
    return json.dumps(
        [
            {
                "query": "users by country",
                "source": "rag",
                "qualified_name": "demo.public.users",
                "database": "demo",
                "schema": "public",
                "table_name": "users",
                "description": "",
                "row_count": 100,
                "match_score": 0.9,
                "columns_json": json.dumps(
                    [
                        {"name": "id", "type": "INTEGER", "nullable": False},
                        {"name": "country", "type": "VARCHAR", "nullable": True},
                    ]
                ),
            }
        ]
    )


def test_sql_search_reuses_cached_payload_for_identical_query(monkeypatch):
    tools._clear_sql_search_result_cache()
    call_count = {"n": 0}

    def _fake_meta():
        return SimpleNamespace(
            last_discovery="2026-02-24T10:00:00",
            table_count=1,
            embed_model="test-model",
            rag_id="rag-1",
        )

    def _fake_sql_rag_search(*args, **kwargs):
        call_count["n"] += 1
        return _fake_rag_rows()

    monkeypatch.setattr(tools, "_SQL_SEARCH_USE_ELASTIC", False)
    monkeypatch.setattr(tools, "_get_cached_discovery_metadata", _fake_meta)
    monkeypatch.setattr(tools, "sql_rag_search", _fake_sql_rag_search)
    monkeypatch.setattr(tools, "load_sql_connections", lambda: {"demo": SimpleNamespace(type="postgres")})

    first = tools.sql_search("users by country", k=5, smart=False)
    second = tools.sql_search("users by country", k=5, smart=False)

    assert call_count["n"] == 1
    assert first == second
    parsed = json.loads(first)
    assert isinstance(parsed, list) and len(parsed) == 1
    assert parsed[0]["qualified_name"] == "demo.public.users"
    assert parsed[0]["sql_table_ref"] == "demo.public.users"


def test_sql_search_cache_invalidates_when_discovery_version_changes(monkeypatch):
    tools._clear_sql_search_result_cache()
    call_count = {"n": 0}
    state = {"version": "2026-02-24T10:00:00"}

    def _fake_meta():
        return SimpleNamespace(
            last_discovery=state["version"],
            table_count=1,
            embed_model="test-model",
            rag_id="rag-1",
        )

    def _fake_sql_rag_search(*args, **kwargs):
        call_count["n"] += 1
        return _fake_rag_rows()

    monkeypatch.setattr(tools, "_SQL_SEARCH_USE_ELASTIC", False)
    monkeypatch.setattr(tools, "_get_cached_discovery_metadata", _fake_meta)
    monkeypatch.setattr(tools, "sql_rag_search", _fake_sql_rag_search)
    monkeypatch.setattr(tools, "load_sql_connections", lambda: {"demo": SimpleNamespace(type="postgres")})

    tools.sql_search("users by country", k=5, smart=False)
    tools.sql_search("users by country", k=5, smart=False)
    assert call_count["n"] == 1

    state["version"] = "2026-02-24T10:05:00"
    tools.sql_search("users by country", k=5, smart=False)
    assert call_count["n"] == 2


def test_sql_search_exposes_schema_less_sql_table_ref_for_csv(monkeypatch):
    tools._clear_sql_search_result_cache()

    def _fake_meta():
        return SimpleNamespace(
            last_discovery="2026-02-24T10:00:00",
            table_count=1,
            embed_model="test-model",
            rag_id="rag-1",
        )

    def _fake_sql_rag_search(*args, **kwargs):
        return json.dumps(
            [
                {
                    "query": "bigfoot",
                    "source": "rag",
                    "qualified_name": "csv_files.bigfoot_sightings",
                    "database": "csv_files",
                    "schema": "csv_files",
                    "table_name": "bigfoot_sightings",
                    "description": "",
                    "row_count": 10,
                    "match_score": 0.9,
                    "columns_json": "[]",
                }
            ]
        )

    monkeypatch.setattr(tools, "_SQL_SEARCH_USE_ELASTIC", False)
    monkeypatch.setattr(tools, "_get_cached_discovery_metadata", _fake_meta)
    monkeypatch.setattr(tools, "sql_rag_search", _fake_sql_rag_search)
    monkeypatch.setattr(tools, "load_sql_connections", lambda: {"csv_files": SimpleNamespace(type="csv_folder")})

    parsed = json.loads(tools.sql_search("bigfoot", k=5, smart=False))
    assert parsed[0]["sql_table_ref"] == "csv_files.bigfoot_sightings"
    assert parsed[0]["schema"] is None
