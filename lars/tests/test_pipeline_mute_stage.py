import pandas as pd


def test_pipeline_mute_returns_status_row():
    from lars.sql_tools.pipeline_executor import execute_pipeline_with_into
    from lars.sql_tools.pipeline_parser import PipelineStage

    initial_df = pd.DataFrame({"x": [1, 2]})
    stages = [PipelineStage(name="MUTE", args=[], original_text="MUTE", into_table=None)]

    out = execute_pipeline_with_into(
        stages=stages,
        initial_df=initial_df,
        into_table=None,
        duckdb_conn=None,
        session_id="test_session",
        results_db="lars_results_default",
        caller_id=None,
        original_query="SELECT ... THEN MUTE",
        base_into_table=None,
    )

    assert len(out) == 1
    assert out.iloc[0]["status"] == "ok"
    assert int(out.iloc[0]["rows"]) == 2
    assert bool(out.iloc[0]["muted"]) is True
    assert out.iloc[0]["results_db"] == "lars_results_default"
    assert out.iloc[0]["into_tables"] == "[]"


def test_pipeline_mute_reports_into_tables_from_prior_stages():
    from lars.sql_tools.pipeline_executor import execute_pipeline_with_into
    from lars.sql_tools.pipeline_parser import PipelineStage

    initial_df = pd.DataFrame({"x": [1, 2]})
    stages = [
        PipelineStage(name="PASS", args=[], original_text="PASS", into_table="employees"),
        PipelineStage(name="MUTE", args=[], original_text="MUTE", into_table=None),
    ]

    out = execute_pipeline_with_into(
        stages=stages,
        initial_df=initial_df,
        into_table=None,
        duckdb_conn=None,
        session_id="test_session",
        results_db="lars_results_default",
        caller_id=None,
        original_query="SELECT ... THEN PASS INTO employees THEN MUTE",
        base_into_table=None,
    )

    assert len(out) == 1
    assert out.iloc[0]["into_tables"] == '["employees"]'

