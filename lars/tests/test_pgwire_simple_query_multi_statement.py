import duckdb


class _FakeSock:
    def __init__(self):
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def _msg_types(messages: list[bytes]) -> list[bytes]:
    return [m[:1] for m in messages if m]


def test_simple_query_multi_statement_pipeline_sends_single_ready_for_query():
    """
    Regression test: when a client sends multiple statements in a single Simple
    Query message (semicolon-delimited), pgwire must execute all statements and
    send exactly one ReadyForQuery at the end.
    """
    from lars.server.postgres_server import ClientConnection

    sock = _FakeSock()
    conn = ClientConnection(sock, ("127.0.0.1", 0))
    conn.session_id = "test_session"
    conn.duckdb_conn = duckdb.connect(":memory:")

    conn.handle_query("SELECT 1 THEN PASS; SELECT 2 THEN PASS;")

    types = _msg_types(sock.sent)
    assert types.count(b"Z") == 1
    assert types[-1] == b"Z"
    assert b"Z" not in types[:-1]
    assert types.count(b"C") == 2

