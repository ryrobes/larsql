import duckdb
import pytest


class _DummySock:
    def sendall(self, _data: bytes) -> None:
        return


@pytest.fixture()
def _client():
    import rvbbit.server.postgres_server as pg_server

    client = pg_server.ClientConnection(_DummySock(), ("127.0.0.1", 0))
    client.session_id = "test_session"
    client.database_name = "rvbbit"
    client.user_name = "rvbbit"
    client.application_name = "DataGrip"
    client.transaction_status = "I"
    client.is_persistent_db = False
    client.duckdb_conn = duckdb.connect(":memory:")
    client._duckdb_catalog_name = client.duckdb_conn.execute("select current_database()").fetchone()[0]
    return client


def _datagrip_pg_class_union_query(with_name: bool) -> str:
    if with_name:
        cols_rel = "select T.oid as oid, relnamespace as schemaId, translate(relkind, 'rmvpfS', 'rmvrfS') as kind, relname as name"
        cols_type = "select T.oid, T.typnamespace, 'T', T.typname"
        cols_coll = "select oid, collnamespace, 'C', collname"
        cols_opr = "select oid, oprnamespace, 'O', oprname"
        cols_opc = "select oid, opcnamespace, 'c', opcname"
        cols_opf = "select oid, opfnamespace, 'F', opfname"
        cols_proc = "select oid, pronamespace, case when prokind != 'a' then 'R' else 'a' end, proname"
    else:
        cols_rel = "select T.oid as oid, relnamespace as schemaId, translate(relkind, 'rmvpfS', 'rmvrfS') as kind"
        cols_type = "select T.oid, T.typnamespace, 'T'"
        cols_coll = "select oid, collnamespace, 'C'"
        cols_opr = "select oid, oprnamespace, 'O'"
        cols_opc = "select oid, opcnamespace, 'c'"
        cols_opf = "select oid, opfnamespace, 'F'"
        cols_proc = "select oid, pronamespace, case when prokind != 'a' then 'R' else 'a' end"

    return f"""
{cols_rel}
from pg_catalog.pg_class T
where relnamespace in ( ? )
and relkind in ('r','m','v','p','f','S')
union all
{cols_type}
from pg_catalog.pg_type T
left outer join pg_catalog.pg_class C on T.typrelid = C.oid
where T.typnamespace in ( ? )
and (
  T.typtype in ('d','e') or
  C.relkind = 'c'::"char" or
  (T.typtype = 'b' and (T.typelem = 0 OR T.typcategory <> 'A')) or
  T.typtype = 'p' and not T.typisdefined
)
union all
{cols_coll}
from pg_catalog.pg_collation
where collnamespace in ( ? )
union all
{cols_opr}
from pg_catalog.pg_operator
where oprnamespace in ( ? )
union all
{cols_opc}
from pg_catalog.pg_opclass
where opcnamespace in ( ? )
union all
{cols_opf}
from pg_catalog.pg_opfamily
where opfnamespace in ( ? )
union all
{cols_proc}
from pg_catalog.pg_proc
where pronamespace in ( ? )
order by schemaId
"""


def test_datagrip_pg_class_union_browser_with_name_lists_relations(_client):
    client = _client
    client.duckdb_conn.execute("CREATE TABLE t(a INTEGER)")
    client.duckdb_conn.execute("CREATE VIEW v AS SELECT * FROM t")

    main_oid = int(
        client.duckdb_conn.execute("select oid from pg_catalog.pg_namespace where nspname = 'main'").fetchone()[0]
    )
    query = _datagrip_pg_class_union_query(with_name=True)
    df = client._build_datagrip_pg_class_table_browser_union_result(query, [main_oid] * 7)

    assert list(df.columns) == ["oid", "schemaId", "kind", "name"]
    rel = df[(df["schemaId"] == main_oid) & (df["name"].isin(["t", "v"]))][["name", "kind"]]
    assert set(map(tuple, rel.values.tolist())) >= {("t", "r"), ("v", "v")}


def test_datagrip_pg_class_union_browser_without_name_has_oids(_client):
    client = _client
    client.duckdb_conn.execute("CREATE TABLE t(a INTEGER)")

    main_oid = int(
        client.duckdb_conn.execute("select oid from pg_catalog.pg_namespace where nspname = 'main'").fetchone()[0]
    )
    t_oid = int(client.duckdb_conn.execute("select oid from pg_catalog.pg_class where relname = 't'").fetchone()[0])

    query = _datagrip_pg_class_union_query(with_name=False)
    df = client._build_datagrip_pg_class_table_browser_union_result(query, [main_oid] * 7)

    assert list(df.columns) == ["oid", "schemaId", "kind"]
    assert ((df["oid"] == t_oid) & (df["schemaId"] == main_oid)).any()

