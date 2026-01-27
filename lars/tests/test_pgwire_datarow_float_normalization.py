import struct


def _decode_single_text_field(data_row_msg: bytes) -> str:
    """
    Minimal decoder for one-column DataRow messages emitted by DataRow.encode().
    Returns the field as UTF-8 text.
    """
    assert data_row_msg[:1] == b"D"
    length = struct.unpack("!I", data_row_msg[1:5])[0]
    payload = data_row_msg[5:5 + (length - 4)]
    (field_count,) = struct.unpack("!H", payload[:2])
    assert field_count == 1
    (field_len,) = struct.unpack("!I", payload[2:6])
    return payload[6:6 + field_len].decode("utf-8")


def test_datarow_encodes_integral_floats_without_decimal():
    from lars.server.postgres_protocol import DataRow

    msg = DataRow.encode([5.0])
    assert _decode_single_text_field(msg) == "5"


def test_datarow_preserves_non_integral_floats():
    from lars.server.postgres_protocol import DataRow

    msg = DataRow.encode([5.25])
    assert _decode_single_text_field(msg) == "5.25"

