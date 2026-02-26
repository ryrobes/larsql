from __future__ import annotations

import pytest

from lars.db_adapter import DuckDBAdapter, reset_adapter
from lars.lars_db import reset_lars_db


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_adapter()
    reset_lars_db()
    yield
    reset_adapter()
    reset_lars_db()


def test_insert_rows_normalizes_once_for_primary_and_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))

    adapter = DuckDBAdapter()
    captured: dict[str, object] = {}

    def fake_write(table, rows, **kwargs):
        captured["duck_table"] = table
        captured["duck_rows"] = [dict(r) for r in rows]
        captured["duck_kwargs"] = dict(kwargs)
        return "ok"

    def fake_shadow(table, rows):
        captured["shadow_table"] = table
        captured["shadow_rows"] = [dict(r) for r in rows]

    monkeypatch.setattr(adapter._db, "write", fake_write)
    monkeypatch.setattr(adapter, "_shadow_write_rows", fake_shadow)

    adapter.insert_rows(
        "unified_logs_base",
        [{"trace_id": "trace-1", "role": "assistant", "content_json": "{}"}],
        log_query=False,
    )

    assert captured["duck_table"] == "unified_logs_base"
    assert captured["shadow_table"] == "unified_logs_base"
    assert captured["duck_rows"] == captured["shadow_rows"]

    row = captured["duck_rows"][0]
    assert row["trace_id"] == "trace-1"
    assert row["message_id"]
    assert row["timestamp"] is not None
    assert captured["duck_kwargs"]["rows_already_normalized"] is True


def test_insert_rows_refuses_duck_disabled_without_alternate_sink(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_DUCK_PRIMARY_WRITE_ENABLED", "0")
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_ENABLED", "0")

    adapter = DuckDBAdapter()
    write_called = {"value": False}

    def fake_write(_table, _rows, **_kwargs):
        write_called["value"] = True
        return "ok"

    monkeypatch.setattr(adapter._db, "write", fake_write)
    monkeypatch.setattr(adapter, "_get_clickhouse_shadow_writer", lambda: None)

    with pytest.raises(RuntimeError, match="no alternate sink"):
        adapter.insert_rows(
            "unified_logs_base",
            [{"trace_id": "trace-2", "role": "assistant"}],
            log_query=False,
        )

    assert write_called["value"] is False


def test_insert_rows_supports_per_table_duck_disable_with_shadow_sink(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))
    monkeypatch.setenv("LARS_DUCK_PRIMARY_WRITE_ENABLED", "1")
    monkeypatch.setenv("LARS_DUCK_PRIMARY_WRITE_DISABLED_TABLES", "unified_logs_base")

    adapter = DuckDBAdapter()
    write_called = {"value": False}
    shadow_called = {"value": False}

    class FakeWriter:
        tables = {"unified_logs_base"}

    def fake_write(_table, _rows, **_kwargs):
        write_called["value"] = True
        return "ok"

    def fake_shadow(_table, rows):
        shadow_called["value"] = True
        assert rows
        assert rows[0]["message_id"]
        assert rows[0]["timestamp"] is not None

    monkeypatch.setattr(adapter._db, "write", fake_write)
    monkeypatch.setattr(adapter, "_get_clickhouse_shadow_writer", lambda: FakeWriter())
    monkeypatch.setattr(adapter, "_shadow_write_rows", fake_shadow)

    adapter.insert_rows(
        "unified_logs_base",
        [{"trace_id": "trace-3", "role": "assistant"}],
        log_query=False,
    )

    assert write_called["value"] is False
    assert shadow_called["value"] is True


def test_mirror_rows_to_shadow_supports_clear_flush_and_batching(tmp_path, monkeypatch):
    monkeypatch.setenv("LARS_ROOT", str(tmp_path))

    adapter = DuckDBAdapter()
    calls: list[tuple[str, object]] = []

    class FakeWriter:
        enabled = True

        def allows_table(self, table):
            return table == "rag_vector_chunks"

        def flush_now(self):
            calls.append(("flush", None))

        def truncate_table(self, table):
            calls.append(("truncate", table))
            return True

        def enqueue(self, table, rows):
            calls.append(("enqueue", (table, [dict(r) for r in rows])))

    monkeypatch.setattr(adapter, "_get_clickhouse_shadow_writer", lambda: FakeWriter())

    report = adapter.mirror_rows_to_shadow(
        "rag_vector_chunks",
        [
            {"chunk_id": "a", "embedding": [0.1]},
            {"chunk_id": "b", "embedding": [0.2]},
        ],
        clear_table=True,
        flush=True,
        batch_rows=1,
        normalize_rows=False,
    )

    assert report["enabled"] is True
    assert report["rows_enqueued"] == 2
    assert calls[0] == ("flush", None)
    assert calls[1] == ("truncate", "rag_vector_chunks")
    assert calls[2][0] == "enqueue"
    assert calls[3][0] == "enqueue"
    assert calls[-1] == ("flush", None)
