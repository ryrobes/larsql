from __future__ import annotations

from lars.clickhouse_shadow_writer import ClickHouseShadowWriter
from lars.lars_db import SYSTEM_TABLES


def _base_env(monkeypatch):
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_ENABLED", "0")
    monkeypatch.setenv("LARS_CLICKHOUSE_HOST", "127.0.0.1")
    monkeypatch.setenv("LARS_CLICKHOUSE_PORT", "19123")
    monkeypatch.setenv("LARS_CLICKHOUSE_DATABASE", "lars")
    monkeypatch.setenv("LARS_CLICKHOUSE_USER", "rvbbit")
    monkeypatch.setenv("LARS_CLICKHOUSE_PASSWORD", "rvbbit_local_dev")


def test_shadow_writer_default_tables(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("LARS_CH_SHADOW_WRITE_TABLES", raising=False)

    writer = ClickHouseShadowWriter()
    assert writer.enabled is False
    assert writer.allows_table("unified_logs_base")
    assert writer.allows_table("costs")
    assert writer.allows_table("session_state") is False
    assert writer.stats()["write_all_tables"] is False


def test_shadow_writer_wildcard_enables_all_tables(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")

    writer = ClickHouseShadowWriter()
    assert writer.stats()["write_all_tables"] is True
    assert writer.allows_table("unified_logs_base")
    assert writer.allows_table("costs")
    assert writer.allows_table("some_future_table")
    assert "unified_logs_base" in writer.tables
    assert "costs" in writer.tables
    assert set(SYSTEM_TABLES.keys()).issubset(writer.tables)


def test_shadow_writer_wildcard_with_explicit_tables(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*,custom_table")

    writer = ClickHouseShadowWriter()
    assert writer.stats()["write_all_tables"] is True
    assert writer.allows_table("custom_table")
    assert "custom_table" in writer.tables


def test_shadow_writer_upsert_defaults_to_dedup_tables(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")
    monkeypatch.delenv("LARS_CH_SHADOW_UPSERT_TABLES", raising=False)
    monkeypatch.delenv("LARS_CH_SHADOW_USE_UPSERT_FOR_DEDUP", raising=False)

    writer = ClickHouseShadowWriter()
    assert writer.stats()["upsert_enabled_for_dedup"] is True
    assert writer._uses_upsert("session_state") is True
    assert writer._uses_upsert("cascade_sessions") is True
    assert writer._uses_upsert("take_winners") is True
    assert writer._uses_upsert("costs") is True
    assert writer._uses_upsert("unified_logs_base") is False


def test_shadow_writer_upsert_can_be_disabled(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")
    monkeypatch.setenv("LARS_CH_SHADOW_USE_UPSERT_FOR_DEDUP", "0")

    writer = ClickHouseShadowWriter()
    assert writer.stats()["upsert_enabled_for_dedup"] is False
    assert writer._uses_upsert("session_state") is False
    assert writer._uses_upsert("costs") is False


def test_shadow_writer_upsert_table_ddl_enables_nullable_key(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")

    writer = ClickHouseShadowWriter()
    statements = []

    class FakeClient:
        def execute(self, sql):
            statements.append(sql)
            return []

    monkeypatch.setattr(writer, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(
        writer,
        "_table_schema",
        lambda table, sample_rows: [("session_id", "VARCHAR"), ("updated_at", "TIMESTAMP")],
    )

    writer._ensure_table("session_state")
    assert statements, "expected CREATE TABLE statement"
    ddl = next(
        (sql for sql in statements if "create table if not exists `lars`.`session_state`" in sql.lower()),
        "",
    )
    assert ddl, "expected session_state CREATE TABLE statement"
    assert "ORDER BY (`session_id`)" in ddl
    assert "SETTINGS allow_nullable_key = 1" in ddl


def test_shadow_writer_non_upsert_table_ddl_has_no_nullable_key_setting(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")

    writer = ClickHouseShadowWriter()
    statements = []

    class FakeClient:
        def execute(self, sql):
            statements.append(sql)
            return []

    monkeypatch.setattr(writer, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(
        writer,
        "_table_schema",
        lambda table, sample_rows: [("id", "VARCHAR"), ("timestamp", "TIMESTAMP")],
    )

    # Prevent support-object bootstrap from appending unrelated DDL.
    monkeypatch.setattr(writer, "_ensure_support_objects", lambda _client: None)

    writer._ensure_table("unified_logs_base")
    assert statements, "expected CREATE TABLE statement"
    ddl = next(
        (sql for sql in statements if "create table if not exists `lars`.`unified_logs_base`" in sql.lower()),
        "",
    )
    assert ddl, "expected unified_logs_base CREATE TABLE statement"
    assert "ORDER BY tuple()" in ddl
    assert "allow_nullable_key" not in ddl


def test_shadow_writer_creates_unified_logs_view_after_base_and_costs(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")

    writer = ClickHouseShadowWriter()
    statements = []

    class FakeClient:
        def execute(self, sql):
            statements.append(sql)
            return []

    monkeypatch.setattr(writer, "_get_client", lambda: FakeClient())

    def fake_schema(table, _sample_rows):
        if table == "unified_logs_base":
            return [
                ("trace_id", "VARCHAR"),
                ("cost", "DOUBLE"),
                ("tokens_in", "INTEGER"),
                ("tokens_out", "INTEGER"),
                ("tokens_reasoning", "INTEGER"),
                ("session_id", "VARCHAR"),
            ]
        if table == "costs":
            return [
                ("trace_id", "VARCHAR"),
                ("cost", "DOUBLE"),
                ("tokens_in", "INTEGER"),
                ("tokens_out", "INTEGER"),
                ("tokens_reasoning", "INTEGER"),
                ("timestamp", "TIMESTAMP"),
            ]
        return [("id", "VARCHAR")]

    monkeypatch.setattr(writer, "_table_schema", fake_schema)

    writer._ensure_table("unified_logs_base")
    writer._ensure_table("costs")

    view_ddls = [sql for sql in statements if "view" in sql.lower() and "unified_logs" in sql.lower()]
    assert view_ddls, "expected unified_logs view DDL"
    assert any("left join" in sql.lower() for sql in view_ddls)
    assert any("coalesce" in sql.lower() for sql in view_ddls)


def test_shadow_writer_creates_training_views_when_dependencies_exist(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LARS_CH_SHADOW_WRITE_TABLES", "*")

    writer = ClickHouseShadowWriter()
    statements = []

    class FakeClient:
        def execute(self, sql):
            statements.append(sql)
            if sql.lower().startswith("describe table"):
                # Return no columns to keep reconciliation path simple in this test.
                return []
            return []

    monkeypatch.setattr(writer, "_get_client", lambda: FakeClient())

    def fake_schema(table, _sample_rows):
        if table == "unified_logs_base":
            return [
                ("trace_id", "VARCHAR"),
                ("content_json", "VARCHAR"),
                ("full_request_json", "VARCHAR"),
                ("role", "VARCHAR"),
                ("cascade_id", "VARCHAR"),
                ("cell_name", "VARCHAR"),
                ("session_id", "VARCHAR"),
                ("timestamp", "TIMESTAMP"),
                ("node_type", "VARCHAR"),
                ("caller_id", "VARCHAR"),
                ("cost", "DOUBLE"),
                ("tokens_in", "INTEGER"),
                ("tokens_out", "INTEGER"),
                ("tokens_reasoning", "INTEGER"),
                ("duration_ms", "DOUBLE"),
                ("model", "VARCHAR"),
                ("content_type", "VARCHAR"),
                ("metadata_json", "VARCHAR"),
                ("candidate_index", "INTEGER"),
                ("timestamp_iso", "VARCHAR"),
                ("parent_id", "VARCHAR"),
            ]
        if table == "costs":
            return [
                ("trace_id", "VARCHAR"),
                ("cost", "DOUBLE"),
                ("tokens_in", "INTEGER"),
                ("tokens_out", "INTEGER"),
                ("tokens_reasoning", "INTEGER"),
                ("timestamp", "TIMESTAMP"),
            ]
        if table == "training_annotations":
            return [
                ("trace_id", "VARCHAR"),
                ("trainable", "BOOLEAN"),
                ("verified", "BOOLEAN"),
                ("confidence", "FLOAT"),
                ("rating", "VARCHAR"),
                ("notes", "VARCHAR"),
                ("tags", "VARCHAR[]"),
                ("annotated_at", "TIMESTAMP"),
                ("annotated_by", "VARCHAR"),
            ]
        return [("id", "VARCHAR")]

    monkeypatch.setattr(writer, "_table_schema", fake_schema)

    writer._ensure_table("unified_logs_base")
    writer._ensure_table("costs")

    lowered = [sql.lower() for sql in statements]
    assert any("create table if not exists `lars`.`training_annotations`" in sql for sql in lowered)
    assert any("create or replace view `lars`.`training_examples_mv`" in sql for sql in lowered)
    assert any("create or replace view `lars`.`training_examples_with_annotations`" in sql for sql in lowered)
    assert any("create or replace view `lars`.`training_stats_by_cascade`" in sql for sql in lowered)
