import json
from pathlib import Path
from types import SimpleNamespace

from lars.sql_tools import tools


def _write_table_meta(root: Path, rel_path: str, table_meta: dict) -> None:
    full_path = root / "sql_connections" / "samples" / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(json.dumps(table_meta), encoding="utf-8")


def _patch_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(tools, "get_config", lambda: SimpleNamespace(root_dir=str(root)))
    monkeypatch.setattr(tools, "load_sql_connections", lambda: {})


def test_sql_get_table_meta_from_qualified_name_strips_heavy_fields_by_default(monkeypatch, tmp_path):
    _patch_root(monkeypatch, tmp_path)
    _write_table_meta(
        tmp_path,
        "demo/public/users.json",
        {
            "table_name": "users",
            "schema": "public",
            "database": "demo",
            "row_count": 100,
            "columns": [
                {
                    "name": "country",
                    "type": "VARCHAR",
                    "nullable": True,
                    "metadata": {
                        "distinct_count": 3,
                        "value_distribution": [
                            {"value": "US", "count": 70, "percentage": 70.0},
                        ],
                    },
                }
            ],
            "sample_columns": ["id", "country"],
            "sample_rows": [[1, "US"], [2, "CA"]],
        },
    )

    payload = json.loads(tools.sql_get_table_meta(qualified_name="demo.public.users"))

    assert payload["qualified_name"] == "demo.public.users"
    assert payload["sql_table_ref"] == "demo.public.users"
    assert payload["source"] == "demo/public/users.json"
    assert "sample_rows" not in payload
    assert "sample_columns" not in payload
    assert payload["columns"][0]["metadata"]["distinct_count"] == 3
    assert "value_distribution" not in payload["columns"][0]["metadata"]


def test_sql_get_table_meta_supports_two_part_qualified_name_and_optional_fields(monkeypatch, tmp_path):
    _patch_root(monkeypatch, tmp_path)
    _write_table_meta(
        tmp_path,
        "met_on_tour/default/shows.json",
        {
            "table_name": "shows",
            "schema": "met_on_tour",
            "database": "met_on_tour",
            "row_count": 10,
            "columns": [
                {
                    "name": "tour_name",
                    "type": "VARCHAR",
                    "nullable": True,
                    "metadata": {
                        "distinct_count": 2,
                        "value_distribution": [
                            {"value": "M72", "count": 6, "percentage": 60.0},
                            {"value": "WorldWired", "count": 4, "percentage": 40.0},
                        ],
                    },
                }
            ],
            "sample_columns": ["show_id", "tour_name"],
            "sample_rows": [["a", "M72"], ["b", "WorldWired"]],
        },
    )

    payload = json.loads(
        tools.sql_get_table_meta(
            qualified_name="met_on_tour.shows",
            include_sample_rows=True,
            include_value_distribution=True,
            sample_row_limit=1,
        )
    )

    assert payload["qualified_name"] == "met_on_tour.shows"
    assert payload["sql_table_ref"] == "met_on_tour.shows"
    assert payload["source"] == "met_on_tour/default/shows.json"
    assert payload["schema"] is None
    assert payload["sample_columns"] == ["show_id", "tour_name"]
    assert payload["sample_rows"] == [["a", "M72"]]
    assert "value_distribution" in payload["columns"][0]["metadata"]


def test_sql_get_table_meta_caps_value_distribution_when_enabled(monkeypatch, tmp_path):
    _patch_root(monkeypatch, tmp_path)
    _write_table_meta(
        tmp_path,
        "demo/public/events.json",
        {
            "table_name": "events",
            "schema": "public",
            "database": "demo",
            "row_count": 12,
            "columns": [
                {
                    "name": "event_type",
                    "type": "VARCHAR",
                    "nullable": True,
                    "metadata": {
                        "distinct_count": 8,
                        "value_distribution": [
                            {"value": "A", "count": 4, "percentage": 33.3},
                            {"value": "B", "count": 2, "percentage": 16.7},
                            {"value": "C", "count": 2, "percentage": 16.7},
                            {"value": "D", "count": 1, "percentage": 8.3},
                            {"value": "E", "count": 1, "percentage": 8.3},
                            {"value": "F", "count": 1, "percentage": 8.3},
                            {"value": "G", "count": 1, "percentage": 8.3},
                            {"value": "H", "count": 0, "percentage": 0.0},
                        ],
                    },
                }
            ],
        },
    )

    payload = json.loads(
        tools.sql_get_table_meta(
            qualified_name="demo.public.events",
            include_value_distribution=True,
        )
    )

    dist = payload["columns"][0]["metadata"]["value_distribution"]
    assert len(dist) == 5
    assert [row["value"] for row in dist] == ["A", "B", "C", "D", "E"]


def test_sql_get_table_meta_returns_ambiguous_error_for_non_unique_match(monkeypatch, tmp_path):
    _patch_root(monkeypatch, tmp_path)
    _write_table_meta(
        tmp_path,
        "demo/public/events.json",
        {
            "table_name": "events",
            "schema": "public",
            "database": "demo",
            "row_count": 10,
            "columns": [],
        },
    )
    _write_table_meta(
        tmp_path,
        "demo/analytics/events.json",
        {
            "table_name": "events",
            "schema": "analytics",
            "database": "demo",
            "row_count": 25,
            "columns": [],
        },
    )

    payload = json.loads(
        tools.sql_get_table_meta(
            database="demo",
            table_name="events",
        )
    )

    assert payload["error"] == "Ambiguous table selection"
    assert payload["candidate_count"] == 2
    assert len(payload["candidates"]) == 2


def test_sql_get_table_meta_recovers_from_incorrect_main_schema_for_csv(monkeypatch, tmp_path):
    _patch_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tools,
        "load_sql_connections",
        lambda: {"csv_files": SimpleNamespace(type="csv_folder")},
    )
    _write_table_meta(
        tmp_path,
        "csv_files/events.json",
        {
            "table_name": "events",
            "schema": "csv_files",
            "database": "csv_files",
            "row_count": 10,
            "columns": [],
        },
    )

    payload = json.loads(tools.sql_get_table_meta(qualified_name="csv_files.main.events"))

    assert payload["qualified_name"] == "csv_files.events"
    assert payload["sql_table_ref"] == "csv_files.events"
    assert payload["schema"] is None
