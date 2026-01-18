"""
Integration tests for the pipeline system.

These tests verify the full pipeline flow from SQL parsing through
cascade execution. Some tests require LLM access and are marked accordingly.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import duckdb
import pandas as pd
import pytest

from lars.sql_tools.pipeline_parser import parse_pipeline_syntax, has_pipeline_syntax
from lars.sql_tools.pipeline_executor import (
    execute_pipeline_stages,
    execute_pipeline_with_into,
    PipelineExecutionError,
)
from lars.semantic_sql.registry import (
    get_pipeline_cascade,
    list_pipeline_cascades,
    initialize_registry,
)


class TestRegistryIntegration:
    """Test that PIPELINE cascades are properly registered."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Ensure registry is initialized with latest cascades."""
        initialize_registry(force=True)

    def test_analyze_cascade_registered(self):
        """ANALYZE pipeline cascade should be registered."""
        entry = get_pipeline_cascade("ANALYZE")
        assert entry is not None
        assert entry.shape == "PIPELINE"
        assert "analyze_pipeline" in entry.cascade_path

    def test_filter_cascade_registered(self):
        """FILTER pipeline cascade should be registered."""
        entry = get_pipeline_cascade("FILTER")
        assert entry is not None
        assert entry.shape == "PIPELINE"

    def test_enrich_cascade_registered(self):
        """ENRICH pipeline cascade should be registered."""
        entry = get_pipeline_cascade("ENRICH")
        assert entry is not None
        assert entry.shape == "PIPELINE"

    def test_speak_cascade_registered(self):
        """SPEAK pipeline cascade should be registered."""
        entry = get_pipeline_cascade("SPEAK")
        assert entry is not None
        assert entry.shape == "PIPELINE"

    def test_list_pipeline_cascades(self):
        """Should list all PIPELINE cascades."""
        pipelines = list_pipeline_cascades()
        assert len(pipelines) >= 4
        assert "ANALYZE" in pipelines
        assert "FILTER" in pipelines
        assert "ENRICH" in pipelines
        assert "SPEAK" in pipelines

    def test_non_pipeline_not_returned(self):
        """get_pipeline_cascade should return None for non-PIPELINE shapes."""
        # MEANS is a SCALAR shape, not PIPELINE
        entry = get_pipeline_cascade("semantic_matches")
        assert entry is None


class TestParserIntegration:
    """Test parsing of realistic SQL with pipeline syntax."""

    def test_parse_with_joins(self):
        """Parse complex query with joins."""
        sql = """
        SELECT
            p.product_id,
            p.name,
            c.category_name,
            SUM(s.quantity) as total_sold
        FROM products p
        JOIN categories c ON p.category_id = c.id
        JOIN sales s ON s.product_id = p.product_id
        WHERE s.sale_date >= '2024-01-01'
        GROUP BY p.product_id, p.name, c.category_name
        HAVING SUM(s.quantity) > 100
        ORDER BY total_sold DESC
        LIMIT 20
        THEN ANALYZE 'Which products are trending and why?'
        INTO trending_products
        """

        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "JOIN categories" in result.base_sql
        assert "HAVING SUM" in result.base_sql
        assert "LIMIT 20" in result.base_sql
        assert len(result.stages) == 1
        assert result.stages[0].name == "ANALYZE"
        assert result.into_table == "trending_products"

    def test_parse_with_cte(self):
        """Parse query with Common Table Expressions."""
        sql = """
        WITH monthly_sales AS (
            SELECT
                DATE_TRUNC('month', sale_date) as month,
                SUM(amount) as revenue
            FROM sales
            GROUP BY 1
        )
        SELECT * FROM monthly_sales
        WHERE revenue > 10000
        THEN ANALYZE 'What is the revenue trend?'
        THEN ENRICH 'add month-over-month growth rate'
        """

        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "WITH monthly_sales AS" in result.base_sql
        assert len(result.stages) == 2
        assert result.stages[0].name == "ANALYZE"
        assert result.stages[1].name == "ENRICH"

    def test_parse_with_window_functions(self):
        """Parse query with window functions."""
        sql = """
        SELECT
            product_id,
            sale_date,
            amount,
            SUM(amount) OVER (PARTITION BY product_id ORDER BY sale_date) as running_total,
            LAG(amount, 1) OVER (PARTITION BY product_id ORDER BY sale_date) as prev_amount
        FROM sales
        THEN FILTER('only show increasing sales')
        """

        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "OVER (PARTITION BY" in result.base_sql
        assert "LAG(amount" in result.base_sql
        assert len(result.stages) == 1


class TestDuckDBIntegration:
    """Test integration with DuckDB for INTO clause."""

    @pytest.fixture
    def duckdb_conn(self):
        """Create an in-memory DuckDB connection."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_into_creates_table_with_mock_pipeline(self, duckdb_conn):
        """INTO clause should create a real table in DuckDB."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        # Mock the pipeline execution to return transformed data
        result_df = pd.DataFrame({
            "id": [1, 2, 3],
            "analysis": ["good", "great", "excellent"],
            "score": [0.8, 0.9, 0.95],
        })

        # Mock the internal execution path that execute_pipeline_with_into uses
        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/analyze.yaml"
        mock_entry.sql_function = {"args": [{"name": "prompt", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "lineage": [
                {
                    "cell": "analyze",
                    "output": {"data": result_df.to_dict(orient="records")}
                }
            ]
        }

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry), \
             patch("lars.runner.LARSRunner", return_value=mock_runner), \
             patch("lars._register_all_skills"):
            stages = [PipelineStage(name="ANALYZE", args=["test"], original_text="ANALYZE")]
            initial_df = pd.DataFrame({"x": [1, 2, 3]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table="analysis_results",
                duckdb_conn=duckdb_conn,
                session_id="test",
            )

        # Verify table was created
        result = duckdb_conn.execute("SELECT * FROM analysis_results").fetchdf()
        assert len(result) == 3
        assert "analysis" in result.columns
        assert "score" in result.columns

    def test_into_replaces_existing_table(self, duckdb_conn):
        """INTO should replace existing table."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        # Create initial table
        duckdb_conn.execute("CREATE TABLE my_table AS SELECT 1 as old_col")

        # Mock pipeline to return new data
        result_df = pd.DataFrame({"new_col": [1, 2, 3]})

        # Mock the internal execution path that execute_pipeline_with_into uses
        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/analyze.yaml"
        mock_entry.sql_function = {"args": [{"name": "prompt", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "lineage": [
                {
                    "cell": "analyze",
                    "output": {"data": result_df.to_dict(orient="records")}
                }
            ]
        }

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry), \
             patch("lars.runner.LARSRunner", return_value=mock_runner), \
             patch("lars._register_all_skills"):
            stages = [PipelineStage(name="ANALYZE", args=["test"], original_text="ANALYZE")]
            initial_df = pd.DataFrame({"x": [1]})

            execute_pipeline_with_into(
                stages=stages,
                initial_df=initial_df,
                into_table="my_table",
                duckdb_conn=duckdb_conn,
                session_id="test",
            )

        # Verify table was replaced
        result = duckdb_conn.execute("SELECT * FROM my_table").fetchdf()
        assert "new_col" in result.columns
        assert "old_col" not in result.columns


class TestEndToEndMocked:
    """End-to-end tests with mocked LLM calls."""

    @pytest.fixture
    def sample_data(self):
        """Sample DataFrame for testing."""
        return pd.DataFrame({
            "product": ["Widget A", "Widget B", "Gadget X"],
            "category": ["electronics", "electronics", "home"],
            "sales": [1000, 2500, 800],
            "rating": [4.5, 4.8, 4.2],
        })

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_analyze_returns_insights(self, mock_register, mock_runner_cls, sample_data):
        """ANALYZE stage should return structured insights."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        # Mock runner to return analysis
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "outputs": {
                "analyze": {
                    "answer": "Widget B is the top performer",
                    "key_findings": ["Electronics dominate", "High ratings correlate with sales"],
                    "data": [
                        {"product": "Widget B", "insight": "top seller"},
                        {"product": "Widget A", "insight": "steady performer"},
                    ]
                }
            }
        }
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/analyze.yaml"
        mock_entry.sql_function = {"args": [{"name": "prompt", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="ANALYZE", args=["What sells best?"], original_text="ANALYZE")]

            execute_pipeline_stages(
                stages=stages,
                initial_df=sample_data,
                session_id="test",
            )

            # Verify cascade was called with correct data
            call_args = mock_runner.run.call_args.kwargs["input_data"]
            assert call_args["prompt"] == "What sells best?"
            assert len(call_args["_table"]) == 3  # All rows passed

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_filter_reduces_rows(self, mock_register, mock_runner_cls, sample_data):
        """FILTER stage should return subset of rows."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        # Mock filter to return only electronics
        # Use lineage format that _extract_cascade_output expects
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "lineage": [
                {
                    "cell": "filter_rows",
                    "output": {
                        "data": [
                            {"product": "Widget A", "category": "electronics", "sales": 1000, "rating": 4.5},
                            {"product": "Widget B", "category": "electronics", "sales": 2500, "rating": 4.8},
                        ]
                    }
                }
            ]
        }
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/filter.yaml"
        mock_entry.sql_function = {"args": [{"name": "criterion", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="FILTER", args=["only electronics"], original_text="FILTER")]

            result_df = execute_pipeline_stages(
                stages=stages,
                initial_df=sample_data,
                session_id="test",
            )

            assert len(result_df) == 2

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_enrich_adds_columns(self, mock_register, mock_runner_cls, sample_data):
        """ENRICH stage should add computed columns."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        # Mock enrichment with new columns
        # Use lineage format that _extract_cascade_output expects
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "lineage": [
                {
                    "cell": "enrich_rows",
                    "output": {
                        "added_columns": ["sentiment", "recommendation"],
                        "data": [
                            {"product": "Widget A", "category": "electronics", "sales": 1000, "rating": 4.5,
                             "sentiment": "positive", "recommendation": "promote more"},
                            {"product": "Widget B", "category": "electronics", "sales": 2500, "rating": 4.8,
                             "sentiment": "very positive", "recommendation": "flagship product"},
                            {"product": "Gadget X", "category": "home", "sales": 800, "rating": 4.2,
                             "sentiment": "positive", "recommendation": "expand category"},
                        ]
                    }
                }
            ]
        }
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/enrich.yaml"
        mock_entry.sql_function = {"args": [{"name": "instructions", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="ENRICH", args=["add sentiment and recommendation"], original_text="ENRICH")]

            result_df = execute_pipeline_stages(
                stages=stages,
                initial_df=sample_data,
                session_id="test",
            )

            assert "sentiment" in result_df.columns
            assert "recommendation" in result_df.columns
            assert len(result_df) == 3

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_chained_stages(self, mock_register, mock_runner_cls, sample_data):
        """Multiple stages should chain correctly."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        call_count = [0]

        def mock_run(input_data):
            call_count[0] += 1
            if call_count[0] == 1:
                # First stage: FILTER - reduce to 2 rows
                return {
                    "outputs": {
                        "cell": {
                            "data": [
                                {"product": "Widget B", "category": "electronics", "sales": 2500},
                                {"product": "Widget A", "category": "electronics", "sales": 1000},
                            ]
                        }
                    }
                }
            else:
                # Second stage: ANALYZE - add insights
                return {
                    "outputs": {
                        "cell": {
                            "data": [
                                {"product": "Widget B", "insight": "top"},
                            ]
                        }
                    }
                }

        mock_runner = MagicMock()
        mock_runner.run.side_effect = mock_run
        mock_runner_cls.return_value = mock_runner

        mock_entry = MagicMock()
        mock_entry.cascade_path = "/path/to/cascade.yaml"
        mock_entry.sql_function = {"args": [{"name": "prompt", "type": "VARCHAR"}, {"name": "_table", "type": "TABLE"}]}

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [
                PipelineStage(name="FILTER", args=["electronics only"], original_text="FILTER"),
                PipelineStage(name="ANALYZE", args=["which is best?"], original_text="ANALYZE"),
            ]

            result_df = execute_pipeline_stages(
                stages=stages,
                initial_df=sample_data,
                session_id="test",
            )

            # Both stages were called
            assert call_count[0] == 2


@pytest.mark.requires_llm
class TestEndToEndWithLLM:
    """
    End-to-end tests that actually call LLM.

    These tests are marked with requires_llm and skipped in CI.
    Run with: pytest -m requires_llm
    """

    @pytest.fixture
    def sample_products(self):
        """Sample product data for LLM tests."""
        return pd.DataFrame({
            "name": ["Eco Bamboo Toothbrush", "Plastic Water Bottle", "Organic Cotton T-Shirt"],
            "description": [
                "Biodegradable bamboo toothbrush with charcoal bristles",
                "Standard plastic water bottle 500ml",
                "100% organic cotton t-shirt, fair trade certified",
            ],
            "price": [5.99, 1.99, 29.99],
        })

    def test_analyze_with_real_llm(self, sample_products):
        """Test ANALYZE with real LLM call."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        initialize_registry(force=True)

        stages = [PipelineStage(name="ANALYZE", args=["Which products are eco-friendly?"], original_text="ANALYZE")]

        result_df = execute_pipeline_stages(
            stages=stages,
            initial_df=sample_products,
            session_id="llm-test",
        )

        # Should return some kind of result
        assert result_df is not None
        assert len(result_df) > 0

    def test_filter_with_real_llm(self, sample_products):
        """Test FILTER with real LLM call."""
        from lars.sql_tools.pipeline_parser import PipelineStage

        initialize_registry(force=True)

        stages = [PipelineStage(name="FILTER", args=["only eco-friendly products"], original_text="FILTER")]

        result_df = execute_pipeline_stages(
            stages=stages,
            initial_df=sample_products,
            session_id="llm-test",
        )

        # Should filter to subset
        assert result_df is not None
        # Eco-friendly filter should remove plastic bottle
        assert len(result_df) <= len(sample_products)
