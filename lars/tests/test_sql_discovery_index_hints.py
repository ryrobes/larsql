import yaml

from lars.sql_tools import discovery


def test_enrich_table_doc_adds_select_hint_for_csv():
    table_meta = {
        "table_name": "ufo_sightings",
        "schema": "csv_files",
        "database": "csv_files",
        "columns": [],
    }

    doc = discovery._enrich_table_doc_for_index(table_meta, "csv_folder")

    assert doc["sql_table_ref"] == "csv_files.ufo_sightings"
    assert doc["example_query"] == "SELECT * FROM csv_files.ufo_sightings LIMIT 5"


def test_enrich_table_doc_uses_duckdb_folder_db_name_for_ref():
    table_meta = {
        "table_name": "zollege_schools",
        "schema": "market_research",
        "database": "research_dbs",
        "columns": [],
    }

    doc = discovery._enrich_table_doc_for_index(table_meta, "duckdb_folder")

    assert doc["sql_table_ref"] == "market_research.zollege_schools"
    assert doc["example_query"] == "SELECT * FROM market_research.zollege_schools LIMIT 5"


def test_write_field_index_includes_example_query_hint(tmp_path):
    table_meta = {
        "table_name": "ufo_sightings",
        "schema": "csv_files",
        "database": "csv_files",
        "row_count": 42,
        "sql_table_ref": "csv_files.ufo_sightings",
        "example_query": "SELECT * FROM csv_files.ufo_sightings LIMIT 5",
        "columns": [
            {
                "name": "state",
                "type": "VARCHAR",
                "nullable": True,
                "metadata": {"distinct_count": 3},
            }
        ],
    }

    discovery._write_field_index(str(tmp_path), table_meta, conn_type="csv_folder")

    payload = yaml.safe_load((tmp_path / "ufo_sightings_fields.yaml").read_text(encoding="utf-8"))
    assert payload["source_table"] == "csv_files.ufo_sightings"
    assert payload["sql_table_ref"] == "csv_files.ufo_sightings"
    assert payload["example_query"] == "SELECT * FROM csv_files.ufo_sightings LIMIT 5"
