from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def chdb_db(tmp_path: Path):
    """
    Provide a CHDB-backed LARS DB adapter using a per-test storage path.

    This avoids requiring a running ClickHouse server for basic persistence tests.
    """
    from lars.config import get_config
    from lars.db_adapter import get_db_adapter, reset_adapter, shutdown_async_loggers

    cfg = get_config()
    old_mode = getattr(cfg, "db_mode", "auto")
    old_path = getattr(cfg, "chdb_path", "")

    cfg.db_mode = "chdb"
    cfg.chdb_path = str(tmp_path / "lars_test.chdb")

    reset_adapter()
    db = get_db_adapter()

    try:
        yield db
    finally:
        # Best-effort cleanup so other tests/processes can reuse CHDB without lock conflicts.
        try:
            shutdown_async_loggers()
        except Exception:
            pass
        try:
            if hasattr(db, "client") and hasattr(db.client, "disconnect"):
                db.client.disconnect()
        except Exception:
            pass
        reset_adapter()
        cfg.db_mode = old_mode
        cfg.chdb_path = old_path


def test_chdb_adapter_basic_ops(chdb_db):
    assert getattr(chdb_db, "backend", None) == "chdb"

    chdb_db.execute(
        "CREATE TABLE IF NOT EXISTS test_chdb_basic (a UInt32, b String) "
        "ENGINE = MergeTree() ORDER BY a",
        log_query=False,
    )
    chdb_db.insert_rows("test_chdb_basic", [{"a": 1, "b": "x"}], log_query=False)

    rows = chdb_db.query(
        "SELECT b FROM test_chdb_basic WHERE a = %(a)s",
        {"a": 1},
        log_query=False,
    )
    assert rows == [{"b": "x"}]


def test_chdb_housekeeping_runs(chdb_db):
    from lars.db_adapter import ensure_housekeeping
    from lars.config import get_config

    ensure_housekeeping()

    cfg = get_config()
    rows = chdb_db.query(
        "SELECT count() AS cnt FROM system.tables WHERE database = %(db)s",
        {"db": cfg.clickhouse_database},
        log_query=False,
    )
    assert rows and int(rows[0]["cnt"]) > 0


def test_chdb_json_each_row_datetime_types(chdb_db):
    """
    CHDB JSONEachRow is strict about DateTime parsing (no fractional seconds).

    Ensure our CHDB insert paths:
    - truncate microseconds for DateTime
    - preserve microseconds for DateTime64
    """
    from datetime import datetime

    import pandas as pd

    chdb_db.execute(
        "CREATE TABLE IF NOT EXISTS test_chdb_dt ("
        "x UInt32, "
        "created_at DateTime, "
        "created_at64 DateTime64(6)"
        ") ENGINE = MergeTree() ORDER BY x",
        log_query=False,
    )

    dt = datetime(2026, 1, 30, 12, 34, 56, 460735)

    # insert_rows path
    chdb_db.insert_rows(
        "test_chdb_dt",
        [{"x": 1, "created_at": dt, "created_at64": dt}],
        columns=["x", "created_at", "created_at64"],
        log_query=False,
    )

    # insert_dataframe path
    df = pd.DataFrame([{"x": 2, "created_at": dt, "created_at64": dt}])
    chdb_db.insert_dataframe("test_chdb_dt", df, log_query=False)

    rows = chdb_db.query(
        "SELECT x, toString(created_at) AS created_at, toString(created_at64) AS created_at64 "
        "FROM test_chdb_dt ORDER BY x",
        log_query=False,
    )
    assert [int(r["x"]) for r in rows] == [1, 2]
    assert "." not in rows[0]["created_at"]
    assert "." in rows[0]["created_at64"]


def test_chdb_lazy_attach_clickhouse_uses_adapter(chdb_db):
    """
    In CHDB mode, lazy_attach's ClickHouse attachment should not try to connect
    to an external ClickHouse HTTP endpoint. It should list tables via the
    LARS db_adapter (which points at CHDB) and create DuckDB views using
    clickhouse_scan_2().
    """
    import duckdb

    from lars.sql_tools.config import SqlConnectionConfig
    from lars.sql_tools.lazy_attach import LazyAttachManager
    from lars.sql_tools.udf import register_clickhouse_scan_udfs

    chdb_db.execute(
        "CREATE TABLE IF NOT EXISTS chdb_attach_test (a UInt32, b String) "
        "ENGINE = MergeTree() ORDER BY a",
        log_query=False,
    )
    chdb_db.insert_rows("chdb_attach_test", [{"a": 1, "b": "x"}], log_query=False)

    con = duckdb.connect(database=":memory:")
    register_clickhouse_scan_udfs(con)

    cfg = SqlConnectionConfig(
        connection_name="lars",
        type="clickhouse",
        database=getattr(chdb_db, "database", "lars"),
        enabled=True,
        sample_row_limit=100,
        distinct_value_threshold=50,
    )
    manager = LazyAttachManager(con, {"lars": cfg})
    manager.attach_all(type_filter="clickhouse")

    assert con.execute("SELECT b FROM lars.chdb_attach_test WHERE a = 1").fetchall() == [("x",)]


def test_chdb_database_connector_clickhouse_uses_adapter(chdb_db):
    """
    DatabaseConnector's ClickHouse attachment should also work in CHDB mode
    without an external ClickHouse HTTP endpoint.
    """
    from lars.sql_tools.config import SqlConnectionConfig
    from lars.sql_tools.connector import DatabaseConnector
    from lars.sql_tools.udf import register_clickhouse_scan_udfs

    chdb_db.execute(
        "CREATE TABLE IF NOT EXISTS chdb_attach_test2 (a UInt32, b String) "
        "ENGINE = MergeTree() ORDER BY a",
        log_query=False,
    )
    chdb_db.insert_rows("chdb_attach_test2", [{"a": 1, "b": "y"}], log_query=False)

    connector = DatabaseConnector(use_cache=False)
    register_clickhouse_scan_udfs(connector.conn)

    cfg = SqlConnectionConfig(
        connection_name="lars",
        type="clickhouse",
        database=getattr(chdb_db, "database", "lars"),
        enabled=True,
        sample_row_limit=100,
        distinct_value_threshold=50,
    )
    connector.attach(cfg)

    assert connector.conn.execute("SELECT b FROM lars.chdb_attach_test2 WHERE a = 1").fetchall() == [("y",)]


def test_chdb_relative_path_resolved_against_root_dir(tmp_path, monkeypatch):
    """
    CHDB path should resolve relative to LARS_ROOT/root_dir, not process CWD.

    Studio runs in a subprocess with a different cwd, so relative paths must stay
    stable across processes.
    """
    from lars.config import get_config
    from lars.db_adapter import get_db_adapter, reset_adapter, shutdown_async_loggers

    cfg = get_config()
    old_mode = getattr(cfg, "db_mode", "auto")
    old_root = getattr(cfg, "root_dir", "")
    old_path = getattr(cfg, "chdb_path", "")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "rel_chdb").mkdir()
    (tmp_path / "other_cwd").mkdir()

    monkeypatch.chdir(tmp_path / "other_cwd")

    cfg.db_mode = "chdb"
    cfg.root_dir = str(workspace)
    cfg.chdb_path = "./rel_chdb"

    reset_adapter()
    db = get_db_adapter()

    try:
        assert getattr(db, "backend", None) == "chdb"
        assert getattr(db, "chdb_path", None) == str(workspace / "rel_chdb")
    finally:
        try:
            shutdown_async_loggers()
        except Exception:
            pass
        try:
            if hasattr(db, "client") and hasattr(db.client, "disconnect"):
                db.client.disconnect()
        except Exception:
            pass
        reset_adapter()
        cfg.db_mode = old_mode
        cfg.root_dir = old_root
        cfg.chdb_path = old_path
