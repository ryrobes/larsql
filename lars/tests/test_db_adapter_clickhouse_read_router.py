from __future__ import annotations

import pytest

from lars.db_adapter import DuckDBAdapter, reset_adapter, query_source_context
from lars.lars_db import reset_lars_db


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_adapter()
    reset_lars_db()
    yield
    reset_adapter()
    reset_lars_db()


def _set_ui_source():
    token = query_source_context.set("ui_backend")
    return token


def test_clickhouse_read_router_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.delenv("LARS_CH_READ_ENABLED", raising=False)

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(_sql, _output_format):
        calls["ch"] += 1
        return [{"source": "ch"}]

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT * FROM unified_logs_base LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "duck"}]
    assert calls["duck"] == 1
    assert calls["ch"] == 0


def test_clickhouse_read_router_routes_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs_base,costs")

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(_sql, _output_format):
        calls["ch"] += 1
        return [{"source": "ch"}]

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)
    monkeypatch.setattr(adapter, "_should_compare_clickhouse_query", lambda: False)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT * FROM unified_logs_base LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "ch"}]
    assert calls["duck"] == 0
    assert calls["ch"] == 1


def test_clickhouse_read_router_fallbacks_to_duck_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs_base")
    monkeypatch.setenv("LARS_CH_READ_FALLBACK_TO_DUCK", "1")

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(_sql, _output_format):
        calls["ch"] += 1
        raise RuntimeError("ch unavailable")

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT * FROM unified_logs_base LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "duck"}]
    assert calls["ch"] == 1
    assert calls["duck"] == 1


def test_clickhouse_read_router_raises_when_fallback_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs_base")
    monkeypatch.setenv("LARS_CH_READ_FALLBACK_TO_DUCK", "0")

    adapter = DuckDBAdapter()

    def fake_ch_query(_sql, _output_format):
        raise RuntimeError("ch hard failure")

    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)

    token = _set_ui_source()
    try:
        with pytest.raises(RuntimeError, match="ch hard failure"):
            adapter.query("SELECT * FROM unified_logs_base LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)


def test_clickhouse_read_router_preserves_unified_logs_view_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs,costs")

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}
    captured = {"sql": None}

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(sql, _output_format):
        calls["ch"] += 1
        captured["sql"] = sql
        return [{"source": "ch"}]

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)
    monkeypatch.setattr(adapter, "_should_compare_clickhouse_query", lambda: False)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT trace_id FROM unified_logs LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "ch"}]
    assert calls["duck"] == 0
    assert calls["ch"] == 1
    ch_sql = (captured["sql"] or "").lower()
    assert "from unified_logs" in ch_sql
    assert "from unified_logs_base" not in ch_sql


def test_clickhouse_read_router_rewrites_lars_system_logs_to_unified_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    # lars_system.logs is canonicalized to unified_logs.
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs")

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}
    captured = {"sql": None}

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(sql, _output_format):
        calls["ch"] += 1
        captured["sql"] = sql
        return [{"source": "ch"}]

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)
    monkeypatch.setattr(adapter, "_should_compare_clickhouse_query", lambda: False)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT * FROM lars_system.logs LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "ch"}]
    assert calls["duck"] == 0
    assert calls["ch"] == 1
    ch_sql = (captured["sql"] or "").lower()
    assert "from unified_logs" in ch_sql


def test_clickhouse_read_router_retries_on_empty_before_returning(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs_base")
    monkeypatch.setenv("LARS_CH_READ_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("LARS_CH_READ_RETRY_ON_EMPTY", "1")
    monkeypatch.setenv("LARS_CH_READ_RETRY_SLEEP_SECONDS", "0")

    adapter = DuckDBAdapter()
    calls = {"duck": 0, "ch": 0}
    sequence = [[], [{"source": "ch"}]]

    def fake_duck_query(_sql, output_format="dict"):
        calls["duck"] += 1
        return [{"source": "duck"}]

    def fake_ch_query(_sql, _output_format):
        calls["ch"] += 1
        return sequence.pop(0) if sequence else [{"source": "ch"}]

    monkeypatch.setattr(adapter._db, "query", fake_duck_query)
    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)
    monkeypatch.setattr(adapter, "_should_compare_clickhouse_query", lambda: False)

    token = _set_ui_source()
    try:
        result = adapter.query("SELECT * FROM unified_logs_base LIMIT 1", log_query=False)
    finally:
        query_source_context.reset(token)

    assert result == [{"source": "ch"}]
    assert calls["ch"] == 2
    assert calls["duck"] == 0


def test_clickhouse_strict_mode_disables_shadow_ui_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs")
    monkeypatch.setenv("LARS_CH_READ_FALLBACK_TO_DUCK", "0")

    adapter = DuckDBAdapter()
    assert adapter._shadow_ui_reads_enabled is False


def test_clickhouse_read_router_translates_duck_sql_for_ch(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_CH_READ_ENABLED", "1")
    monkeypatch.setenv("LARS_CH_READ_QUERY_SOURCES", "ui_backend")
    monkeypatch.setenv("LARS_CH_READ_TABLES", "unified_logs,session_state")
    monkeypatch.setenv("LARS_CH_READ_FALLBACK_TO_DUCK", "0")

    adapter = DuckDBAdapter()
    captured = {"sql": None}

    def fake_ch_query(sql, _output_format):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(adapter, "_query_clickhouse", fake_ch_query)
    monkeypatch.setattr(adapter, "_should_compare_clickhouse_query", lambda: False)

    token = _set_ui_source()
    try:
        adapter.query(
            (
                "SELECT epoch(MIN(timestamp)) AS t1, epoch(MAX(timestamp)) AS t2 "
                "FROM unified_logs "
                "WHERE prefix(session_id, 'abc') AND epoch_ms(timestamp) > 0 "
                "UNION ALL "
                "SELECT epoch(now()) AS t1, 0 AS t2 FROM session_state FINAL LIMIT 1"
            ),
            log_query=False,
        )
    finally:
        query_source_context.reset(token)

    sql = (captured["sql"] or "").lower()
    assert "final" not in sql
    assert "prefix(" not in sql
    assert "epoch_ms(" not in sql
    assert "epoch(" not in sql
    assert " as varchar" not in sql
    assert "startswith(" in sql
    assert "tounixtimestamp(" in sql
