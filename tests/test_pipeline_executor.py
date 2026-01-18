"""
Tests for the pipeline executor.

Tests the execution of PIPELINE cascades on DataFrames.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from lars.sql_tools.pipeline_parser import PipelineStage
from lars.sql_tools.pipeline_executor import (
    PipelineExecutionError,
    PipelineContext,
    _serialize_dataframe,
    _deserialize_result,
    execute_pipeline_stages,
    execute_pipeline_with_into,
    LARGE_TABLE_THRESHOLD,
)


class TestSerializeDataframe:
    """Test DataFrame serialization for cascade input."""

    def test_small_dataframe_inline(self):
        """Small DataFrames should be serialized inline as JSON."""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "value": [100, 200, 300]
        })
        context = PipelineContext(
            stage_index=0,
            total_stages=1,
            previous_stage=None,
            original_query="SELECT * FROM test",
            session_id="test-session",
            caller_id=None,
        )

        result = _serialize_dataframe(df, context)

        assert "_table" in result
        assert isinstance(result["_table"], list)
        assert len(result["_table"]) == 3
        assert result["_table_columns"] == ["id", "name", "value"]
        assert result["_table_row_count"] == 3
        assert "_table_path" not in result

    def test_large_dataframe_to_parquet(self):
        """Large DataFrames should be written to parquet files."""
        # Create a DataFrame larger than threshold
        df = pd.DataFrame({
            "id": range(LARGE_TABLE_THRESHOLD + 100),
            "value": range(LARGE_TABLE_THRESHOLD + 100),
        })
        context = PipelineContext(
            stage_index=0,
            total_stages=1,
            previous_stage=None,
            original_query="SELECT * FROM large",
            session_id="test-large",
            caller_id=None,
        )

        result = _serialize_dataframe(df, context)

        assert "_table_path" in result
        assert result["_table_path"].endswith(".parquet")
        assert Path(result["_table_path"]).exists()
        assert result["_table_row_count"] == LARGE_TABLE_THRESHOLD + 100

        # Cleanup
        Path(result["_table_path"]).unlink()

    def test_pipeline_context_included(self):
        """Pipeline context should be included in serialization."""
        df = pd.DataFrame({"x": [1, 2]})
        context = PipelineContext(
            stage_index=2,
            total_stages=5,
            previous_stage="ANALYZE",
            original_query="SELECT * FROM test",
            session_id="ctx-test",
            caller_id="caller-123",
        )

        result = _serialize_dataframe(df, context)

        assert "_pipeline_context" in result
        ctx = result["_pipeline_context"]
        assert ctx["stage_index"] == 2
        assert ctx["total_stages"] == 5
        assert ctx["previous_stage"] == "ANALYZE"
        assert ctx["original_query"] == "SELECT * FROM test"


class TestDeserializeResult:
    """Test deserialization of cascade output back to DataFrame."""

    def test_list_of_records(self):
        """List of dicts should become DataFrame rows."""
        result = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        original = pd.DataFrame({"x": [1]})

        df = _deserialize_result(result, original)

        assert len(df) == 2
        assert list(df.columns) == ["id", "name"]
        assert df.iloc[0]["name"] == "Alice"

    def test_dict_with_data_key(self):
        """Dict with 'data' key should extract the data."""
        result = {
            "analysis": "Some analysis",
            "data": [
                {"id": 1, "score": 0.9},
                {"id": 2, "score": 0.7},
            ]
        }
        original = pd.DataFrame({"x": [1]})

        df = _deserialize_result(result, original)

        assert len(df) == 2
        assert "score" in df.columns

    def test_dict_with_rows_key(self):
        """Dict with 'rows' key should extract the rows."""
        result = {
            "rows": [{"a": 1}, {"a": 2}]
        }
        original = pd.DataFrame({"x": [1]})

        df = _deserialize_result(result, original)

        assert len(df) == 2
        assert list(df.columns) == ["a"]

    def test_json_string(self):
        """JSON string should be parsed."""
        result = json.dumps([{"id": 1}, {"id": 2}])
        original = pd.DataFrame({"x": [1]})

        df = _deserialize_result(result, original)

        assert len(df) == 2

    def test_parquet_path(self):
        """Path to parquet file should be read."""
        # Create temp parquet file
        temp_df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            temp_df.to_parquet(f.name)
            temp_path = f.name

        original = pd.DataFrame({"x": [1]})

        df = _deserialize_result(temp_path, original)

        assert len(df) == 3
        assert list(df.columns) == ["col1", "col2"]

        # Cleanup
        Path(temp_path).unlink()

    def test_none_returns_original(self):
        """None result should return original DataFrame."""
        original = pd.DataFrame({"x": [1, 2, 3]})

        df = _deserialize_result(None, original)

        assert df is original

    def test_empty_list_returns_original(self):
        """Empty list should return original DataFrame."""
        original = pd.DataFrame({"x": [1, 2, 3]})

        df = _deserialize_result([], original)

        assert df is original


class TestExecutePipelineStages:
    """Test pipeline stage execution."""

    def test_unknown_stage_raises_error(self):
        """Unknown pipeline stage should raise PipelineExecutionError."""
        stages = [PipelineStage(name="NONEXISTENT", args=[], original_text="NONEXISTENT")]
        df = pd.DataFrame({"x": [1, 2, 3]})

        with pytest.raises(PipelineExecutionError) as exc_info:
            execute_pipeline_stages(
                stages=stages,
                initial_df=df,
                session_id="test",
            )

        assert exc_info.value.stage_name == "NONEXISTENT"
        assert exc_info.value.stage_index == 0
        assert "Unknown pipeline stage" in str(exc_info.value.inner_error)

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_single_stage_execution(self, mock_register, mock_runner_cls):
        """Single stage should execute cascade and return transformed data."""
        # Mock cascade execution
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "outputs": {
                "analyze": {
                    "data": [{"id": 1, "score": 0.9}, {"id": 2, "score": 0.8}]
                }
            }
        }
        mock_runner_cls.return_value = mock_runner

        # Mock registry to return a valid entry with sql_function args
        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {
            "args": [
                {"name": "prompt", "type": "VARCHAR"},
                {"name": "_table", "type": "TABLE"},
            ]
        }

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="ANALYZE", args=["test prompt"], original_text="ANALYZE")]
            df = pd.DataFrame({"x": [1, 2, 3]})

            result = execute_pipeline_stages(
                stages=stages,
                initial_df=df,
                session_id="test-session",
            )

            # Verify runner was called
            assert mock_runner.run.called
            call_args = mock_runner.run.call_args
            assert "prompt" in call_args.kwargs["input_data"]
            assert call_args.kwargs["input_data"]["prompt"] == "test prompt"

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_multiple_stages_chain(self, mock_register, mock_runner_cls):
        """Multiple stages should chain data through each stage."""
        # Track call count
        call_count = [0]

        def mock_run(input_data):
            call_count[0] += 1
            # Return transformed data based on stage
            if call_count[0] == 1:
                return {"outputs": {"cell": {"data": [{"x": 10}, {"x": 20}]}}}
            else:
                return {"outputs": {"cell": {"data": [{"x": 100}]}}}

        mock_runner = MagicMock()
        mock_runner.run.side_effect = mock_run
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {
            "args": [
                {"name": "prompt", "type": "VARCHAR"},
                {"name": "_table", "type": "TABLE"},
            ]
        }

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [
                PipelineStage(name="FILTER", args=["first"], original_text="FILTER"),
                PipelineStage(name="ENRICH", args=["second"], original_text="ENRICH"),
            ]
            df = pd.DataFrame({"x": [1, 2, 3]})

            result = execute_pipeline_stages(
                stages=stages,
                initial_df=df,
                session_id="test-chain",
            )

            # Both stages should have been called
            assert call_count[0] == 2


class TestExecutePipelineWithInto:
    """Test pipeline execution with INTO table creation."""

    @patch("lars.sql_tools.pipeline_executor.execute_pipeline_stages")
    def test_into_creates_table(self, mock_execute):
        """INTO clause should create table in DuckDB."""
        # Mock pipeline execution
        result_df = pd.DataFrame({"result": [1, 2, 3]})
        mock_execute.return_value = result_df

        # Mock DuckDB connection
        mock_conn = MagicMock()

        stages = [PipelineStage(name="ANALYZE", args=["test"], original_text="ANALYZE")]
        initial_df = pd.DataFrame({"x": [1, 2, 3]})

        final_df = execute_pipeline_with_into(
            stages=stages,
            initial_df=initial_df,
            into_table="my_results",
            duckdb_conn=mock_conn,
            session_id="test",
        )

        # Verify table creation
        mock_conn.register.assert_called_once()
        mock_conn.execute.assert_called_once()
        assert "my_results" in mock_conn.execute.call_args[0][0]
        mock_conn.unregister.assert_called_once()

    @patch("lars.sql_tools.pipeline_executor.execute_pipeline_stages")
    def test_no_into_skips_table(self, mock_execute):
        """No INTO clause should skip table creation."""
        result_df = pd.DataFrame({"result": [1, 2, 3]})
        mock_execute.return_value = result_df

        mock_conn = MagicMock()

        stages = [PipelineStage(name="ANALYZE", args=["test"], original_text="ANALYZE")]
        initial_df = pd.DataFrame({"x": [1, 2, 3]})

        final_df = execute_pipeline_with_into(
            stages=stages,
            initial_df=initial_df,
            into_table=None,
            duckdb_conn=mock_conn,
            session_id="test",
        )

        # Should not create table
        mock_conn.execute.assert_not_called()


class TestPipelineExecutionError:
    """Test the PipelineExecutionError exception."""

    def test_error_string_format(self):
        """Error should format with stage info."""
        inner = ValueError("Something went wrong")
        error = PipelineExecutionError(
            stage_name="ANALYZE",
            stage_index=2,
            inner_error=inner,
        )

        error_str = str(error)
        assert "ANALYZE" in error_str
        assert "2" in error_str
        assert "Something went wrong" in error_str

    def test_error_attributes(self):
        """Error should have accessible attributes."""
        inner = RuntimeError("Test error")
        error = PipelineExecutionError(
            stage_name="FILTER",
            stage_index=1,
            inner_error=inner,
        )

        assert error.stage_name == "FILTER"
        assert error.stage_index == 1
        assert error.inner_error is inner


class TestPerStageInto:
    """Test per-stage INTO table creation."""

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    @patch("lars.sql_tools.pipeline_executor._save_to_table")
    def test_base_into_table(self, mock_save, mock_register, mock_runner_cls):
        """base_into_table should save initial DataFrame before pipeline stages."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = {"outputs": {"cell": {"data": [{"x": 10}]}}}
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {"args": [{"name": "_table", "type": "TABLE"}]}

        mock_conn = MagicMock()

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="FILTER", args=[], original_text="FILTER")]
            initial_df = pd.DataFrame({"x": [1, 2, 3]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table=None,
                duckdb_conn=mock_conn,
                session_id="test",
                base_into_table="raw_data",
            )

            # Verify base table was saved first
            calls = mock_save.call_args_list
            assert len(calls) >= 1
            first_call = calls[0]
            assert first_call[0][2] == "raw_data"  # table name

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    @patch("lars.sql_tools.pipeline_executor._save_to_table")
    def test_stage_into_table(self, mock_save, mock_register, mock_runner_cls):
        """Stage with into_table should save result after execution."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = {"outputs": {"cell": {"data": [{"x": 10}]}}}
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {"args": [{"name": "_table", "type": "TABLE"}]}

        mock_conn = MagicMock()

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [
                PipelineStage(name="FILTER", args=[], original_text="FILTER", into_table="filtered_data")
            ]
            initial_df = pd.DataFrame({"x": [1, 2, 3]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table=None,
                duckdb_conn=mock_conn,
                session_id="test",
            )

            # Verify stage result was saved
            calls = mock_save.call_args_list
            assert len(calls) == 1
            assert calls[0][0][2] == "filtered_data"

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    @patch("lars.sql_tools.pipeline_executor._save_to_table")
    def test_multiple_stage_intos(self, mock_save, mock_register, mock_runner_cls):
        """Multiple stages with INTO should each save their results."""
        call_count = [0]

        def mock_run(input_data):
            call_count[0] += 1
            return {"outputs": {"cell": {"data": [{"x": call_count[0] * 10}]}}}

        mock_runner = MagicMock()
        mock_runner.run.side_effect = mock_run
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {"args": [{"name": "_table", "type": "TABLE"}]}

        mock_conn = MagicMock()

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [
                PipelineStage(name="FILTER", args=[], original_text="FILTER", into_table="step1"),
                PipelineStage(name="ENRICH", args=[], original_text="ENRICH", into_table="step2"),
            ]
            initial_df = pd.DataFrame({"x": [1, 2, 3]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table=None,
                duckdb_conn=mock_conn,
                session_id="test",
                base_into_table="base",
            )

            # Verify all three tables were saved (base + 2 stages)
            calls = mock_save.call_args_list
            assert len(calls) == 3
            table_names = [call[0][2] for call in calls]
            assert table_names == ["base", "step1", "step2"]

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    @patch("lars.sql_tools.pipeline_executor._save_to_table")
    def test_mixed_into_stages(self, mock_save, mock_register, mock_runner_cls):
        """Only stages with into_table should save, others skip."""
        call_count = [0]

        def mock_run(input_data):
            call_count[0] += 1
            return {"outputs": {"cell": {"data": [{"x": call_count[0]}]}}}

        mock_runner = MagicMock()
        mock_runner.run.side_effect = mock_run
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {"args": [{"name": "_table", "type": "TABLE"}]}

        mock_conn = MagicMock()

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [
                PipelineStage(name="FILTER", args=[], original_text="FILTER"),  # No INTO
                PipelineStage(name="ENRICH", args=[], original_text="ENRICH", into_table="enriched"),
                PipelineStage(name="ANALYZE", args=[], original_text="ANALYZE"),  # No INTO
            ]
            initial_df = pd.DataFrame({"x": [1, 2, 3]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table=None,
                duckdb_conn=mock_conn,
                session_id="test",
            )

            # Only one stage had INTO
            calls = mock_save.call_args_list
            assert len(calls) == 1
            assert calls[0][0][2] == "enriched"
