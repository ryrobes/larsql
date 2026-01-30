from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture
def chdb_db(tmp_path):
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


def test_session_state_row_to_state_parses_datetime_strings(chdb_db):
    """
    SessionState rows can come back as strings in CHDB mode; ensure we don't crash
    when serializing for the Studio API.
    """
    import json

    from lars.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=True)
    # Clear any previous state inside this ephemeral CHDB.
    try:
        chdb_db.execute("TRUNCATE TABLE session_state", log_query=False)
    except Exception:
        pass

    dt = datetime(2026, 1, 30, 12, 34, 56, 460735)
    row = {
        "session_id": "s1",
        "cascade_id": "c1",
        "status": SessionStatus.RUNNING.value,
        "heartbeat_at": dt,
        "started_at": dt,
        "updated_at": dt,
        "metadata_json": json.dumps({}),
    }
    chdb_db.insert_rows("session_state", [row], log_query=False)

    sessions = manager.list_sessions(limit=10)
    assert sessions
    payload = sessions[0].to_dict()
    assert isinstance(payload["heartbeat_at"], str)
