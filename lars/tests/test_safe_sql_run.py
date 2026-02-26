import json
from types import SimpleNamespace

from lars.sql_tools import tools


class _FakeCursor:
    def __init__(self, columns, rows):
        self.description = [(c, None, None, None, None, None, None) for c in columns]
        self._rows = rows
        self._index = 0

    def fetchmany(self, n):
        chunk = self._rows[self._index:self._index + n]
        self._index += len(chunk)
        return chunk


class _FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Recorder:
    sql = None
    connection = None


def _patch_connections(monkeypatch, names=("demo",)):
    monkeypatch.setattr(
        tools,
        "load_sql_connections",
        lambda: {name: SimpleNamespace(type="csv_folder") for name in names},
    )


def _patch_pgwire_success(monkeypatch, *, columns, rows, executed_sql=None):
    def _fake_execute_sql_via_pgwire_pipeline(*, sql, connection):
        _Recorder.sql = sql
        _Recorder.connection = connection
        conn = _FakeConn()
        cursor = _FakeCursor(columns, rows)
        return conn, cursor, executed_sql if executed_sql is not None else sql.rstrip(";"), connection

    monkeypatch.setattr(tools, "_execute_sql_via_pgwire_pipeline", _fake_execute_sql_via_pgwire_pipeline)


def _patch_pgwire_error(monkeypatch, message):
    def _fake_execute_sql_via_pgwire_pipeline(*, sql, connection):
        raise RuntimeError(message)

    monkeypatch.setattr(tools, "_execute_sql_via_pgwire_pipeline", _fake_execute_sql_via_pgwire_pipeline)


def test_safe_sql_run_truncates_rows_and_text(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_success(
        monkeypatch,
        columns=["id", "category", "text"],
        rows=[(i, f"group_{i % 3}", "x" * 500) for i in range(20)],
    )

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT * FROM demo.table;",
            connection="demo",
            row_limit=15,
            text_max_chars=400,
            stats_mode="sample",
        )
    )

    assert response["row_count"] == 15
    assert response["preview"]["is_truncated"] is True
    assert response["preview"]["truncated_cell_count"] == 15
    assert response["total_row_count"] is None
    assert response["total_row_count_known"] is False
    assert response["stats"]["mode"] == "sample"
    assert response["stats"]["column_cardinality"]["id"] == 15
    assert response["stats"]["column_cardinality"]["category"] == 3
    assert len(response["results"][0]["text"]) == 403  # 400 + '...'
    assert _Recorder.sql == "SELECT * FROM demo.table;"
    assert _Recorder.connection == "demo"


def test_safe_sql_run_full_mode_counts_total_rows(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_success(
        monkeypatch,
        columns=["id", "value"],
        rows=[(i, i * 10) for i in range(23)],
    )

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT id, value FROM demo.table",
            connection="demo",
            row_limit=10,
            text_max_chars=100,
            stats_mode="full",
        )
    )

    assert response["row_count"] == 10
    assert response["preview"]["is_truncated"] is True
    assert response["total_row_count"] == 23
    assert response["total_row_count_known"] is True
    assert response["stats"]["mode"] == "full"


def test_safe_sql_run_non_truncated_result_reports_exact_count(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_success(
        monkeypatch,
        columns=["id", "text"],
        rows=[(1, "a"), (2, "b"), (3, "c")],
    )

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT id, text FROM demo.small_table",
            connection="demo",
            row_limit=15,
            text_max_chars=100,
            stats_mode="sample",
        )
    )

    assert response["preview"]["is_truncated"] is False
    assert response["total_row_count"] == 3
    assert response["total_row_count_known"] is True
    assert response["preview"]["truncated_cell_count"] == 0


def test_limited_sql_run_alias(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_success(
        monkeypatch,
        columns=["id"],
        rows=[(1,), (2,), (3,)],
    )

    response = json.loads(
        tools.limited_sql_run(
            sql="SELECT id FROM demo.table",
            connection="demo",
            row_limit=2,
            text_max_chars=100,
            stats_mode="sample",
        )
    )

    assert response["row_count"] == 2
    assert response["preview"]["is_truncated"] is True


def test_safe_sql_run_invalid_stats_mode(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_success(monkeypatch, columns=["id"], rows=[(1,)])

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT id FROM demo.table",
            connection="demo",
            stats_mode="bad-mode",
        )
    )

    assert "error" in response
    assert "Invalid stats_mode" in response["error"]


def test_safe_sql_run_returns_clear_sql_error_payload(monkeypatch):
    _patch_connections(monkeypatch)
    _patch_pgwire_error(monkeypatch, "Binder Error: Referenced column 'missing_col' not found")

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT missing_col FROM demo.table",
            connection="demo",
        )
    )

    assert response["status"] == "error"
    assert response["error_type"] == "RuntimeError"
    assert response["phase"] == "execute"
    assert response["error"] == "Binder Error: Referenced column 'missing_col' not found"
    assert response["error_message"] == "Binder Error: Referenced column 'missing_col' not found"
    assert "Fix the SQL" in response["action"]


def test_safe_sql_run_without_connection_uses_raw_sql_pipeline(monkeypatch):
    _patch_connections(monkeypatch, names=("demo", "other"))
    _patch_pgwire_success(
        monkeypatch,
        columns=["id"],
        rows=[(1,), (2,)],
    )

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT id FROM demo.table",
            row_limit=10,
            text_max_chars=100,
            stats_mode="sample",
        )
    )

    assert response["row_count"] == 2
    assert response["connection"] is None
    assert _Recorder.connection is None


def test_safe_sql_run_explicit_unknown_connection_still_errors(monkeypatch):
    _patch_connections(monkeypatch, names=("demo",))
    _patch_pgwire_success(monkeypatch, columns=["id"], rows=[(1,)])

    response = json.loads(
        tools.safe_sql_run(
            sql="SELECT id FROM demo.table",
            connection="missing",
        )
    )

    assert response["status"] == "error"
    assert response["error_type"] == "ConnectionNotFound"
    assert "missing" in response["error"]
