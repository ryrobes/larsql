import rvbbit.server.postgres_server as pg_server


class _DummySock:
    def sendall(self, _data: bytes) -> None:
        return


def test_rewrite_missing_table_joins_skips_joins_inside_block_comments():
    """
    DataGrip catalog SQL can contain commented-out JOINs like:
        ... /* left join pg_catalog.pg_am am on ... */ ...

    The missing-join rewriter must not match and remove the JOIN inside the block
    comment (otherwise it can delete the closing '*/' and create an unterminated
    comment that DuckDB refuses to parse).
    """
    client = pg_server.ClientConnection(_DummySock(), ("127.0.0.1", 0))
    client.session_id = "test_session"

    query = """
        select ind_head.indexrelid index_id,
               amcanorder can_order
        from pg_catalog.pg_index ind_head
        join pg_catalog.pg_class ind_stor on ind_stor.oid = ind_head.indexrelid
        cross join pg_indexam_has_property(ind_stor.relam, 'can_order') amcanorder /* left join pg_catalog.pg_am am on ind_stor.relam = am.oid*/
        left join pg_catalog.pg_opclass opc on opc.oid = ind_head.indclass[1]
        where ind_stor.relnamespace = 1
    """

    rewritten = client._rewrite_missing_table_joins(query)

    # The pg_am join is inside a block comment and must remain untouched/balanced.
    assert rewritten.count("/*") == rewritten.count("*/") == 1
    assert "left join pg_catalog.pg_am am on ind_stor.relam = am.oid*/" in rewritten.lower()

