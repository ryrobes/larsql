class _FakeSock:
    def __init__(self):
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def test_pgwire_bind_accepts_float_like_integer_text():
    """
    Regression test: some clients send text parameters like "4.0" while also
    specifying an integer OID (e.g., 23). PGwire should coerce this to int
    instead of raising ValueError.
    """
    from lars.server.postgres_protocol import BindComplete
    from lars.server.postgres_server import ClientConnection

    sock = _FakeSock()
    conn = ClientConnection(sock, ("127.0.0.1", 0))

    stmt_name = "stmt"
    conn.prepared_statements[stmt_name] = {
        "query": "SELECT $1",
        "original_query": "SELECT $1",
        "param_types": [23],  # INTEGER
        "param_count": 1,
    }

    conn._handle_bind(
        {
            "portal_name": "",
            "statement_name": stmt_name,
            "param_formats": [],
            "param_values": [b"4.0"],
            "result_formats": [],
        }
    )

    assert conn.portals[""]["params"] == [4]
    assert sock.sent == [BindComplete.encode()]

