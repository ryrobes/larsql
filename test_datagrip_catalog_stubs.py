import duckdb
import os
from pathlib import Path
import pytest


class _DummySock:
    def sendall(self, _data: bytes) -> None:
        return


@pytest.fixture()
def _capturing_client(monkeypatch):
    import rvbbit.server.postgres_server as pg_server

    client = pg_server.ClientConnection(_DummySock(), ("127.0.0.1", 0))
    client.session_id = "test_session"
    client.database_name = "rvbbit"
    client.user_name = "rvbbit"
    client.application_name = "DataGrip"
    client.transaction_status = "I"
    client.is_persistent_db = True
    client.duckdb_conn = duckdb.connect(":memory:")
    client._duckdb_catalog_name = client.duckdb_conn.execute("select current_database()").fetchone()[0]

    captured = {}

    def fake_send_query_results(sock, result_df, transaction_status="I"):
        captured["df"] = result_df
        captured["transaction_status"] = transaction_status

    monkeypatch.setattr(pg_server, "send_query_results", fake_send_query_results)
    return client, captured


def test_datagrip_probe_current_db_schema_user(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query("select current_database(), current_schema(), current_user")
    df = captured["df"]
    assert list(df.columns) == ["current_database", "current_schema", "current_user"]
    assert df.iloc[0].tolist() == ["rvbbit", "main", "rvbbit"]


def test_datagrip_timezone_union_shape(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query(
        "select name, is_dst from pg_catalog.pg_timezone_names "
        "union distinct "
        "select abbrev as name, is_dst from pg_catalog.pg_timezone_abbrevs"
    )
    df = captured["df"]
    assert list(df.columns) == ["name", "is_dst"]
    assert set(df["name"].tolist()) >= {"UTC", "America/New_York"}


def test_datagrip_pg_user_usesuper_shape(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query("select usesuper from pg_user where usename = current_user")
    df = captured["df"]
    assert list(df.columns) == ["usesuper"]
    assert bool(df.iloc[0, 0]) is True


def test_datagrip_acl_union_empty_shape(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query(
        "select T.oid as object_id, T.spcacl as acl from pg_catalog.pg_tablespace T "
        "union all "
        "select T.oid as object_id, T.datacl as acl from pg_catalog.pg_database T"
    )
    df = captured["df"]
    assert list(df.columns) == ["object_id", "acl"]
    assert len(df) == 0


def test_datagrip_pg_auth_members_empty_shape(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query(
        "select member id, roleid role_id, admin_option "
        "from pg_catalog.pg_auth_members order by id, roleid::text"
    )
    df = captured["df"]
    assert list(df.columns) == ["id", "role_id", "admin_option"]
    assert len(df) == 0


def test_datagrip_pg_database_shape(_capturing_client):
    client, captured = _capturing_client
    client._handle_catalog_query(
        "select N.oid::bigint as id, datname as name, D.description, "
        "datistemplate as is_template, datallowconn as allow_connections, "
        "pg_catalog.pg_get_userbyid(N.datdba) as owner "
        "from pg_catalog.pg_database N "
        "left join pg_catalog.pg_shdescription D on D.objoid = N.oid "
        "order by datname"
    )
    df = captured["df"]
    assert list(df.columns) == ["id", "name", "description", "is_template", "allow_connections", "owner"]
    assert df.iloc[0]["name"] == "rvbbit"


def test_datagrip_pg_class_xmin_rewrite_lists_tables(_capturing_client):
    client, captured = _capturing_client

    client.duckdb_conn.execute("CREATE TABLE t(a INTEGER)")
    client.duckdb_conn.execute("CREATE VIEW v AS SELECT * FROM t")

    client._handle_catalog_query(
        "select c.oid::bigint as id, c.xmin as state_number, c.relname as name, "
        "c.relkind as kind, c.relforcerowsecurity as force_row_security "
        "from pg_catalog.pg_class c "
        "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'main' and c.relkind in ('r','v') "
        "order by c.relname"
    )
    df = captured["df"]
    assert list(df.columns) == ["id", "state_number", "name", "kind", "force_row_security"]
    assert {"t", "v"}.issubset(set(df["name"].tolist()))
    assert set(df["force_row_security"].tolist()) == {False}


def test_information_schema_filters_hide_attached_catalogs(_capturing_client):
    client, captured = _capturing_client

    # Attach an external DuckDB file (simulates ATTACH'd sources)
    ext_path = Path("session_dbs") / "_test_ext_attached.duckdb"
    try:
        ext_path.unlink()
    except FileNotFoundError:
        pass

    client.duckdb_conn.execute(f"ATTACH '{ext_path.as_posix()}' AS ext")
    client.duckdb_conn.execute("CREATE TABLE ext.t1(x INTEGER, y VARCHAR)")
    client._create_attached_db_views()

    # DataGrip-style information_schema query: should NOT surface attached catalog_name 'ext'
    client._handle_catalog_query(
        "select catalog_name, schema_name from information_schema.schemata order by catalog_name, schema_name"
    )
    df = captured["df"]
    assert set(df["catalog_name"].tolist()) == {"rvbbit"}
    assert "ext__main" in set(df["schema_name"].tolist())

    client._handle_catalog_query(
        "select table_catalog, table_schema, table_name, table_type "
        "from information_schema.tables order by table_schema, table_name"
    )
    df = captured["df"]
    assert set(df["table_catalog"].tolist()) == {"rvbbit"}
    # The attached base table (catalog ext) should be hidden; exposed view should be visible instead.
    assert ("ext__main" in set(df["table_schema"].tolist())) and ("t1" in set(df["table_name"].tolist()))

    # Columns for exposed view should be introspectable via information_schema.columns
    client._handle_catalog_query(
        "select table_catalog, table_schema, table_name, column_name "
        "from information_schema.columns "
        "where table_schema = 'ext__main' and table_name = 't1' "
        "order by ordinal_position"
    )
    df = captured["df"]
    assert set(df["table_catalog"].tolist()) == {"rvbbit"}
    assert df["column_name"].tolist()[:2] == ["x", "y"]

    # DataGrip can also use pg_catalog.pg_class to enumerate relations; ensure exposed view is visible
    client._handle_catalog_query(
        "select c.relname as name, c.xmin as state_number "
        "from pg_catalog.pg_class c "
        "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'ext__main' and c.relkind in ('v') "
        "order by c.relname"
    )
    df = captured["df"]
    assert list(df.columns) == ["name", "state_number"]
    assert df["name"].tolist()[:1] == ["t1"]

    # Cleanup
    client.duckdb_conn.execute("DETACH ext")
    try:
        ext_path.unlink()
    except FileNotFoundError:
        pass
