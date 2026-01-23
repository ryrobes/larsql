"""
Tests for the chart pipeline operators.

Tests the chart specification generation, styling, and rendering pipeline:
- TO_PLOTLY / TO_VEGALITE: Data → Spec (LLM)
- ADD_STYLES: Spec → Themed Spec (deterministic)
- RENDER: Spec → Image (deterministic)
- STYLIZE: Image → Styled Image (LLM)
"""

import base64
import json
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from lars.chart_tools import (
    CHART_THEMES,
    wrap_spec,
    detect_chart_library,
    apply_chart_styles,
    render_spec_to_image,
    wrap_stylized_image,
    select_final_output,
    merge_config_with_data,
    generate_chart_sql,
    expand_data_driven_chart,
)


# =============================================================================
# Helper Functions (must be defined before use in decorators)
# =============================================================================

def _vegalite_available() -> bool:
    """Check if vl-convert-python is available."""
    try:
        import vl_convert  # noqa: F401
        return True
    except ImportError:
        return False


def _plotly_available() -> bool:
    """Check if plotly and kaleido are available."""
    try:
        import plotly  # noqa: F401
        import kaleido  # noqa: F401
        return True
    except ImportError:
        return False


def _matplotlib_available() -> bool:
    """Check if matplotlib is available."""
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def sample_data():
    """Sample data for chart generation."""
    return [
        {"month": "Jan", "revenue": 1000, "category": "A"},
        {"month": "Feb", "revenue": 1500, "category": "A"},
        {"month": "Mar", "revenue": 1200, "category": "B"},
        {"month": "Apr", "revenue": 1800, "category": "B"},
    ]


@pytest.fixture
def plotly_spec():
    """Sample Plotly specification."""
    return {
        "data": [
            {
                "type": "bar",
                "x": ["Jan", "Feb", "Mar", "Apr"],
                "y": [1000, 1500, 1200, 1800],
                "name": "Revenue"
            }
        ],
        "layout": {
            "title": {"text": "Monthly Revenue"}
        }
    }


@pytest.fixture
def vegalite_spec():
    """Sample Vega-Lite specification."""
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {
            "values": [
                {"month": "Jan", "revenue": 1000},
                {"month": "Feb", "revenue": 1500},
                {"month": "Mar", "revenue": 1200},
            ]
        },
        "mark": "bar",
        "encoding": {
            "x": {"field": "month", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"}
        }
    }


@pytest.fixture
def matplotlib_code():
    """Sample matplotlib code."""
    return """
import matplotlib.pyplot as plt
data = [1000, 1500, 1200, 1800]
months = ['Jan', 'Feb', 'Mar', 'Apr']
plt.bar(months, data)
plt.title('Monthly Revenue')
fig = plt.gcf()
"""


# =============================================================================
# Test wrap_spec
# =============================================================================

class TestWrapSpec:
    """Tests for the wrap_spec function."""

    def test_wrap_plotly_spec(self, plotly_spec):
        """Should wrap Plotly spec with correct metadata."""
        result = wrap_spec(plotly_spec, "plotly")

        assert "data" in result
        assert len(result["data"]) == 1
        assert result["data"][0]["spec"] == plotly_spec
        assert result["data"][0]["format"] == "plotly"

    def test_wrap_vegalite_spec(self, vegalite_spec):
        """Should wrap Vega-Lite spec with correct metadata."""
        result = wrap_spec(vegalite_spec, "vega-lite")

        assert result["data"][0]["format"] == "vega-lite"
        assert "$schema" in result["data"][0]["spec"]

    def test_wrap_matplotlib_code(self, matplotlib_code):
        """Should wrap matplotlib code string."""
        result = wrap_spec(matplotlib_code, "matplotlib")

        assert result["data"][0]["format"] == "matplotlib"
        assert isinstance(result["data"][0]["spec"], str)
        assert "plt.bar" in result["data"][0]["spec"]


# =============================================================================
# Test detect_chart_library
# =============================================================================

class TestDetectChartLibrary:
    """Tests for the detect_chart_library function."""

    def test_detect_vegalite_by_schema(self, vegalite_spec):
        """Should detect Vega-Lite by $schema."""
        assert detect_chart_library(vegalite_spec) == "vega-lite"

    def test_detect_vegalite_by_mark(self):
        """Should detect Vega-Lite by mark/encoding."""
        spec = {"mark": "bar", "encoding": {"x": {}, "y": {}}}
        assert detect_chart_library(spec) == "vega-lite"

    def test_detect_vegalite_by_layer(self):
        """Should detect Vega-Lite by layer composition."""
        spec = {"layer": [{"mark": "line"}, {"mark": "point"}]}
        assert detect_chart_library(spec) == "vega-lite"

    def test_detect_plotly_by_data_array(self, plotly_spec):
        """Should detect Plotly by data array with traces."""
        assert detect_chart_library(plotly_spec) == "plotly"

    def test_detect_plotly_by_trace_type(self):
        """Should detect Plotly by trace type field."""
        spec = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}]}
        assert detect_chart_library(spec) == "plotly"

    def test_detect_matplotlib_by_string(self, matplotlib_code):
        """Should detect matplotlib when spec is a string."""
        assert detect_chart_library(matplotlib_code) == "matplotlib"

    def test_default_to_plotly(self):
        """Should default to Plotly for ambiguous specs."""
        spec = {"unknown": "structure"}
        assert detect_chart_library(spec) == "plotly"


# =============================================================================
# Test apply_chart_styles
# =============================================================================

class TestApplyChartStyles:
    """Tests for the apply_chart_styles function."""

    def test_apply_dark_theme_to_plotly(self, plotly_spec):
        """Should apply dark theme to Plotly spec."""
        result = apply_chart_styles(plotly_spec, "plotly", theme="dark")

        assert "data" in result
        styled = result["data"][0]["spec"]
        # Matches UI: PlotlyPanel.jsx darkLayout
        assert styled["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"  # transparent
        assert styled["layout"]["plot_bgcolor"] == "rgba(0,0,0,0)"   # transparent
        assert styled["layout"]["font"]["color"] == "#cbd5e1"  # slate-300
        assert result["data"][0]["theme"] == "dark"

    def test_apply_light_theme_to_plotly(self, plotly_spec):
        """Should apply light theme to Plotly spec."""
        result = apply_chart_styles(plotly_spec, "plotly", theme="light")

        styled = result["data"][0]["spec"]
        assert styled["layout"]["paper_bgcolor"] == "#ffffff"
        assert styled["layout"]["template"] == "plotly_white"

    def test_apply_dark_theme_to_vegalite(self, vegalite_spec):
        """Should apply dark theme to Vega-Lite spec."""
        result = apply_chart_styles(vegalite_spec, "vega-lite", theme="dark")

        styled = result["data"][0]["spec"]
        # Matches UI: VegaLitePanel.jsx darkConfig
        assert styled["config"]["background"] == "transparent"
        assert styled["config"]["axis"]["gridColor"] == "#1e293b"  # slate-800
        assert styled["config"]["axis"]["labelColor"] == "#94a3b8"  # slate-400

    def test_apply_midnight_theme(self, plotly_spec):
        """Should apply midnight theme."""
        result = apply_chart_styles(plotly_spec, "plotly", theme="midnight")

        styled = result["data"][0]["spec"]
        assert styled["layout"]["paper_bgcolor"] == "#0d1117"
        assert result["data"][0]["theme"] == "midnight"

    def test_apply_custom_theme(self, plotly_spec):
        """Should apply custom theme from JSON."""
        custom = json.dumps({
            "plotly": {
                "paper_bgcolor": "#ff0000",
                "font": {"color": "#00ff00"}
            }
        })
        result = apply_chart_styles(plotly_spec, "plotly", custom=custom)

        styled = result["data"][0]["spec"]
        assert styled["layout"]["paper_bgcolor"] == "#ff0000"
        assert styled["layout"]["font"]["color"] == "#00ff00"

    def test_apply_theme_to_matplotlib(self, matplotlib_code):
        """Should prepend style.use() to matplotlib code."""
        result = apply_chart_styles(matplotlib_code, "matplotlib", theme="dark")

        styled = result["data"][0]["spec"]
        assert "plt.style.use('dark_background')" in styled
        assert "plt.bar" in styled

    def test_auto_theme_uses_env_var(self, plotly_spec, monkeypatch):
        """Should use LARS_CHART_THEME env var for auto theme."""
        monkeypatch.setenv("LARS_CHART_THEME", "midnight")
        result = apply_chart_styles(plotly_spec, "plotly", theme="auto")

        styled = result["data"][0]["spec"]
        assert styled["layout"]["paper_bgcolor"] == "#0d1117"

    def test_extract_spec_from_table(self, plotly_spec):
        """Should extract spec from _table if spec is None."""
        table = [{"spec": plotly_spec, "format": "plotly"}]
        result = apply_chart_styles(spec=None, library="auto", theme="dark", _table=table)

        assert result["data"][0]["format"] == "plotly"
        assert "paper_bgcolor" in result["data"][0]["spec"]["layout"]

    def test_preserves_existing_layout(self, plotly_spec):
        """Should preserve existing layout properties."""
        result = apply_chart_styles(plotly_spec, "plotly", theme="dark")

        styled = result["data"][0]["spec"]
        # Original title should be preserved
        assert styled["layout"]["title"]["text"] == "Monthly Revenue"


# =============================================================================
# Test render_spec_to_image
# =============================================================================

class TestRenderSpecToImage:
    """Tests for the render_spec_to_image function."""

    @pytest.mark.skipif(
        not _vegalite_available(),
        reason="vl-convert-python not installed"
    )
    def test_render_vegalite(self, vegalite_spec):
        """Should render Vega-Lite spec to PNG."""
        result = render_spec_to_image(vegalite_spec, "vega-lite", width=400, height=300)

        assert "data" in result
        assert len(result["data"]) == 1
        assert result["data"][0]["format"] == "image-base64"
        assert result["data"][0]["library"] == "vega-lite"
        assert result["data"][0]["image"].startswith("data:image/png;base64,")

        # Verify it's valid base64
        b64_data = result["data"][0]["image"].split(",")[1]
        img_bytes = base64.b64decode(b64_data)
        assert len(img_bytes) > 0
        # PNG magic bytes
        assert img_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    @pytest.mark.skipif(
        not _plotly_available(),
        reason="plotly/kaleido not installed"
    )
    def test_render_plotly(self, plotly_spec):
        """Should render Plotly spec to PNG."""
        result = render_spec_to_image(plotly_spec, "plotly", width=400, height=300)

        assert result["data"][0]["format"] == "image-base64"
        assert result["data"][0]["library"] == "plotly"
        assert result["data"][0]["image"].startswith("data:image/png;base64,")

    @pytest.mark.skipif(
        not _matplotlib_available(),
        reason="matplotlib not installed"
    )
    def test_render_matplotlib(self, matplotlib_code):
        """Should execute matplotlib code and render to PNG."""
        result = render_spec_to_image(matplotlib_code, "matplotlib", width=400, height=300)

        assert result["data"][0]["format"] == "image-base64"
        assert result["data"][0]["library"] == "matplotlib"
        assert result["data"][0]["image"].startswith("data:image/png;base64,")

    def test_auto_detect_library(self, vegalite_spec):
        """Should auto-detect library from spec."""
        with patch("lars.chart_tools._render_vegalite") as mock_render:
            mock_render.return_value = b'\x89PNG\r\n\x1a\n'
            result = render_spec_to_image(vegalite_spec, "auto")
            mock_render.assert_called_once()

    def test_extract_spec_from_table(self, plotly_spec):
        """Should extract spec from _table if spec is None."""
        table = [{"spec": plotly_spec, "library": "plotly"}]

        with patch("lars.chart_tools._render_plotly") as mock_render:
            mock_render.return_value = b'\x89PNG\r\n\x1a\n'
            result = render_spec_to_image(spec=None, _table=table)
            mock_render.assert_called_once()

    def test_unknown_library_raises(self):
        """Should raise error for unknown library."""
        with pytest.raises(ValueError, match="Unknown chart library"):
            render_spec_to_image({"data": []}, "unknown_lib")


# =============================================================================
# Test wrap_stylized_image
# =============================================================================

class TestWrapStylizedImage:
    """Tests for the wrap_stylized_image function."""

    def test_wrap_with_data_url(self):
        """Should preserve data URL format."""
        image = "data:image/png;base64,iVBORw0KGgo="
        result = wrap_stylized_image(image, "watercolor", fidelity=0.9)

        assert result["data"][0]["image"] == image
        assert result["data"][0]["format"] == "image-base64"
        assert result["data"][0]["style_prompt"] == "watercolor"
        assert result["data"][0]["fidelity"] == 0.9

    def test_wrap_raw_base64(self):
        """Should convert raw base64 to data URL."""
        raw_b64 = "iVBORw0KGgo="
        result = wrap_stylized_image(raw_b64, "sketch")

        assert result["data"][0]["image"].startswith("data:image/png;base64,")
        assert result["data"][0]["image"].endswith(raw_b64)

    def test_includes_source_image(self):
        """Should include source image if provided."""
        result = wrap_stylized_image(
            "data:image/png;base64,abc",
            "neon",
            source_image="data:image/png;base64,original"
        )

        assert result["data"][0]["source_image"] == "data:image/png;base64,original"


# =============================================================================
# Test select_final_output
# =============================================================================

class TestSelectFinalOutput:
    """Tests for the select_final_output function."""

    def test_prefers_stylized(self):
        """Should prefer stylized over base."""
        result = select_final_output(
            stylized="stylized_image",
            base="base_image",
            spec={"test": "spec"}
        )

        assert result["data"][0]["source"] == "stylized"
        assert "stylized_image" in result["data"][0]["image"]

    def test_falls_back_to_base(self):
        """Should fall back to base if no stylized."""
        result = select_final_output(
            stylized=None,
            base="base_image",
            spec={"test": "spec"}
        )

        assert result["data"][0]["source"] == "rendered"
        assert "base_image" in result["data"][0]["image"]

    def test_falls_back_to_spec(self):
        """Should fall back to spec if no images."""
        result = select_final_output(
            stylized=None,
            base=None,
            spec={"test": "spec"},
            library="plotly"
        )

        assert result["data"][0]["format"] == "plotly"
        assert result["data"][0]["spec"] == {"test": "spec"}

    def test_returns_error_if_nothing(self):
        """Should return error if nothing available."""
        result = select_final_output()

        assert result["data"][0]["format"] == "error"


# =============================================================================
# Test Theme Definitions
# =============================================================================

class TestChartThemes:
    """Tests for the CHART_THEMES definitions."""

    def test_all_themes_have_required_keys(self):
        """All themes should have plotly, vega-lite, matplotlib configs."""
        for theme_name, theme in CHART_THEMES.items():
            assert "plotly" in theme, f"{theme_name} missing plotly config"
            assert "vega-lite" in theme, f"{theme_name} missing vega-lite config"
            assert "matplotlib" in theme, f"{theme_name} missing matplotlib config"

    def test_dark_theme_has_dark_colors(self):
        """Dark theme should have appropriately dark colors or transparent background."""
        dark = CHART_THEMES["dark"]
        # Check background colors are dark or transparent
        plotly_bg = dark["plotly"]["paper_bgcolor"]
        vegalite_bg = dark["vega-lite"]["background"]
        assert plotly_bg.startswith("#1") or plotly_bg.startswith("#0") or "rgba" in plotly_bg or plotly_bg == "transparent"
        assert vegalite_bg.startswith("#1") or vegalite_bg.startswith("#0") or vegalite_bg == "transparent"

    def test_light_theme_has_light_colors(self):
        """Light theme should have appropriately light colors."""
        light = CHART_THEMES["light"]
        assert light["plotly"]["paper_bgcolor"] in ("#ffffff", "#fff")
        assert light["vega-lite"]["background"] in ("#ffffff", "#fff")


# =============================================================================
# Integration Tests with Mocked Runner
# =============================================================================

class TestPipelineIntegration:
    """Integration tests for the chart pipeline with mocked LLM."""

    @patch("lars.runner.LARSRunner")
    @patch("lars._register_all_skills")
    def test_to_plotly_pipeline_structure(self, mock_register, mock_runner_cls, sample_data):
        """TO_PLOTLY pipeline should call cascade with correct inputs."""
        from lars.sql_tools.pipeline_parser import PipelineStage
        from lars.sql_tools.pipeline_executor import execute_pipeline_stages

        # Mock cascade execution
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "outputs": {
                "wrap_output": {
                    "data": [{
                        "spec": {"data": [{"type": "bar"}]},
                        "library": "plotly",
                        "format": "chart-spec"
                    }]
                }
            }
        }
        mock_runner_cls.return_value = mock_runner

        # Mock registry
        mock_entry = MagicMock()
        mock_entry.cascade_path = "to_plotly_pipeline.cascade.yaml"
        mock_entry.sql_function = {
            "args": [
                {"name": "prompt", "type": "VARCHAR"},
                {"name": "_table", "type": "TABLE"},
            ]
        }

        with patch("lars.semantic_sql.registry.get_pipeline_cascade", return_value=mock_entry):
            stages = [PipelineStage(name="TO_PLOTLY", args=["bar chart"], original_text="TO_PLOTLY")]
            df = pd.DataFrame(sample_data)

            result = execute_pipeline_stages(
                stages=stages,
                initial_df=df,
                session_id="test-session",
            )

            # Verify runner was called with prompt
            assert mock_runner.run.called
            call_args = mock_runner.run.call_args
            assert call_args.kwargs["input_data"]["prompt"] == "bar chart"


# =============================================================================
# Test merge_config_with_data (Fungible Chart Output)
# =============================================================================

class TestMergeConfigWithData:
    """Tests for the merge_config_with_data function.

    This function enables fungible chart queries by returning data rows
    with format and config columns instead of materialized specs.
    """

    def test_basic_merge(self, sample_data):
        """Should merge config with all data rows."""
        config = {"type": "bar", "x": "month", "y": "revenue"}
        result = merge_config_with_data("plotly", config, sample_data)

        assert "data" in result
        assert len(result["data"]) == len(sample_data)

        # Each row should have format, config, and original data
        for row in result["data"]:
            assert row["format"] == "plotly"
            assert row["config"] == config
            assert "month" in row
            assert "revenue" in row
            assert "category" in row

    def test_vegalite_format(self, sample_data):
        """Should work with vega-lite format."""
        config = {"mark": "line", "x": "month", "y": "revenue"}
        result = merge_config_with_data("vega-lite", config, sample_data)

        assert result["data"][0]["format"] == "vega-lite"
        assert result["data"][0]["config"] == config

    def test_config_from_json_string(self, sample_data):
        """Should parse JSON string config."""
        config_str = '{"type": "pie", "values": "revenue", "labels": "month"}'
        result = merge_config_with_data("plotly", config_str, sample_data)

        assert result["data"][0]["config"]["type"] == "pie"
        assert result["data"][0]["config"]["values"] == "revenue"

    def test_empty_data(self):
        """Should handle empty data gracefully."""
        config = {"type": "bar", "x": "a", "y": "b"}
        result = merge_config_with_data("plotly", config, [])

        assert "data" in result
        assert len(result["data"]) == 1  # Single row with just format/config
        assert result["data"][0]["format"] == "plotly"
        assert result["data"][0]["config"] == config

    def test_uses_table_fallback(self, sample_data):
        """Should fall back to _table parameter if table is None."""
        config = {"type": "scatter", "x": "month", "y": "revenue"}
        result = merge_config_with_data("plotly", config, None, _table=sample_data)

        assert len(result["data"]) == len(sample_data)
        assert result["data"][0]["month"] == "Jan"

    def test_preserves_all_data_columns(self, sample_data):
        """Should preserve all original data columns."""
        config = {"type": "bar"}
        result = merge_config_with_data("plotly", config, sample_data)

        first_row = result["data"][0]
        # Should have format, config, plus all original columns
        assert set(first_row.keys()) == {"format", "config", "month", "revenue", "category"}

    def test_config_same_for_all_rows(self, sample_data):
        """Config should be the same object reference for all rows."""
        config = {"type": "bar", "x": "month", "y": "revenue"}
        result = merge_config_with_data("plotly", config, sample_data)

        # All rows should have identical config
        configs = [row["config"] for row in result["data"]]
        assert all(c == configs[0] for c in configs)

    def test_data_values_preserved(self, sample_data):
        """Should preserve original data values exactly."""
        config = {"type": "bar"}
        result = merge_config_with_data("plotly", config, sample_data)

        # Check each row's data matches original
        for i, row in enumerate(result["data"]):
            assert row["month"] == sample_data[i]["month"]
            assert row["revenue"] == sample_data[i]["revenue"]
            assert row["category"] == sample_data[i]["category"]


# =============================================================================
# Test generate_chart_sql (Fungible SQL Output)
# =============================================================================

class TestGenerateChartSql:
    """Tests for the generate_chart_sql function.

    This function generates reusable SQL queries that produce chart-ready
    results by wrapping the original query with format and config columns.
    """

    def test_basic_sql_generation(self):
        """Should generate wrapped SQL with format and config."""
        config = {"type": "bar", "x": "month", "y": "revenue"}
        source_sql = "SELECT month, revenue FROM sales"
        columns = ["month", "revenue"]

        result = generate_chart_sql("plotly", config, source_sql, columns)

        assert "data" in result
        assert len(result["data"]) == 1
        assert "query" in result["data"][0]

        query = result["data"][0]["query"]
        assert "'plotly' as format" in query
        assert "config" in query
        assert "month, revenue" in query
        assert "FROM (SELECT month, revenue FROM sales) AS _source" in query

    def test_vegalite_format(self):
        """Should work with vega-lite format."""
        config = {"mark": "line", "x": "date", "y": "value"}
        source_sql = "SELECT date, value FROM timeseries"
        columns = ["date", "value"]

        result = generate_chart_sql("vega-lite", config, source_sql, columns)

        query = result["data"][0]["query"]
        assert "'vega-lite' as format" in query
        assert "mark" in query

    def test_config_json_in_sql(self):
        """Should include config as JSON in the SQL."""
        config = {"type": "pie", "values": "amount", "labels": "category"}
        source_sql = "SELECT category, amount FROM data"
        columns = ["category", "amount"]

        result = generate_chart_sql("plotly", config, source_sql, columns)

        query = result["data"][0]["query"]
        # Config should be JSON-escaped in the SQL
        assert "type" in query
        assert "pie" in query
        assert "::JSON as config" in query

    def test_escapes_single_quotes_in_config(self):
        """Should escape single quotes in config for SQL safety."""
        config = {"title": "Revenue's Growth"}
        source_sql = "SELECT month, revenue FROM sales"
        columns = ["month", "revenue"]

        result = generate_chart_sql("plotly", config, source_sql, columns)

        query = result["data"][0]["query"]
        # Single quotes should be doubled for SQL
        assert "Revenue''s Growth" in query

    def test_uses_pipeline_context_fallback(self):
        """Should fall back to _pipeline_context for source SQL."""
        config = {"type": "bar"}
        pipeline_context = {"original_query": "SELECT a, b FROM fallback_table"}
        columns = ["a", "b"]

        result = generate_chart_sql(
            "plotly", config, "",  # Empty source_sql
            columns, _pipeline_context=pipeline_context
        )

        query = result["data"][0]["query"]
        assert "FROM (SELECT a, b FROM fallback_table) AS _source" in query

    def test_includes_all_columns(self):
        """Should include all specified columns in the SELECT."""
        config = {"type": "scatter"}
        source_sql = "SELECT x, y, z, color FROM points"
        columns = ["x", "y", "z", "color"]

        result = generate_chart_sql("plotly", config, source_sql, columns)

        query = result["data"][0]["query"]
        assert "x, y, z, color" in query

    def test_result_includes_metadata(self):
        """Should include format and config in result metadata."""
        config = {"type": "bar", "x": "a", "y": "b"}
        source_sql = "SELECT a, b FROM t"

        result = generate_chart_sql("plotly", config, source_sql, ["a", "b"])

        row = result["data"][0]
        assert row["format"] == "plotly"
        assert row["config"] == config

    def test_handles_complex_source_sql(self):
        """Should handle complex source SQL with JOINs and subqueries."""
        config = {"type": "line"}
        source_sql = """
            SELECT o.date, SUM(i.quantity) as total
            FROM orders o
            JOIN items i ON o.id = i.order_id
            WHERE o.status = 'completed'
            GROUP BY o.date
            ORDER BY o.date
        """
        columns = ["date", "total"]

        result = generate_chart_sql("plotly", config, source_sql, columns)

        query = result["data"][0]["query"]
        assert "FROM (" in query
        assert "JOIN items" in query
        assert ") AS _source" in query

    def test_config_from_json_string(self):
        """Should parse config if provided as JSON string."""
        config_str = '{"type": "heatmap", "x": "col1", "y": "col2", "z": "value"}'
        source_sql = "SELECT col1, col2, value FROM matrix"

        result = generate_chart_sql("plotly", config_str, source_sql, ["col1", "col2", "value"])

        row = result["data"][0]
        assert row["config"]["type"] == "heatmap"
        assert "heatmap" in row["query"]


# =============================================================================
# Test expand_data_driven_chart (Config + Data -> Full Spec)
# =============================================================================

class TestExpandDataDrivenChart:
    """Tests for the expand_data_driven_chart function.

    This function expands the data-driven format (format + config + data columns)
    into a full Plotly or Vega-Lite specification for rendering.
    """

    def test_plotly_bar_chart(self, sample_data):
        """Should expand Plotly bar chart config into full spec."""
        rows = [
            {"format": "plotly", "config": {"type": "bar", "x": "month", "y": "revenue"}, **row}
            for row in sample_data
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "plotly"
        assert "data" in spec
        assert len(spec["data"]) == 1
        assert spec["data"][0]["type"] == "bar"
        assert spec["data"][0]["x"] == ["Jan", "Feb", "Mar", "Apr"]
        assert spec["data"][0]["y"] == [1000, 1500, 1200, 1800]

    def test_plotly_pie_chart(self):
        """Should expand Plotly pie chart config."""
        rows = [
            {"format": "plotly", "config": {"type": "pie", "values": "amount", "labels": "category"}, "category": "A", "amount": 100},
            {"format": "plotly", "config": {"type": "pie", "values": "amount", "labels": "category"}, "category": "B", "amount": 200},
            {"format": "plotly", "config": {"type": "pie", "values": "amount", "labels": "category"}, "category": "C", "amount": 150},
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "plotly"
        assert spec["data"][0]["type"] == "pie"
        assert spec["data"][0]["values"] == [100, 200, 150]
        assert spec["data"][0]["labels"] == ["A", "B", "C"]

    def test_plotly_line_chart(self):
        """Should expand Plotly line chart with scatter mode."""
        rows = [
            {"format": "plotly", "config": {"type": "line", "x": "date", "y": "value"}, "date": "2024-01", "value": 10},
            {"format": "plotly", "config": {"type": "line", "x": "date", "y": "value"}, "date": "2024-02", "value": 15},
        ]

        spec, library = expand_data_driven_chart(rows)

        assert spec["data"][0]["type"] == "scatter"
        assert spec["data"][0]["mode"] == "lines"
        assert spec["data"][0]["x"] == ["2024-01", "2024-02"]

    def test_plotly_scatter_chart(self):
        """Should expand Plotly scatter chart with markers mode."""
        rows = [
            {"format": "plotly", "config": {"type": "scatter", "x": "x", "y": "y"}, "x": 1, "y": 2},
            {"format": "plotly", "config": {"type": "scatter", "x": "x", "y": "y"}, "x": 3, "y": 4},
        ]

        spec, library = expand_data_driven_chart(rows)

        assert spec["data"][0]["type"] == "scatter"
        assert spec["data"][0]["mode"] == "markers"

    def test_plotly_grouped_chart(self, sample_data):
        """Should expand Plotly grouped chart into multiple traces."""
        rows = [
            {"format": "plotly", "config": {"type": "bar", "x": "month", "y": "revenue", "color": "category"}, **row}
            for row in sample_data
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "plotly"
        # Should have 2 traces (one for each category A and B)
        assert len(spec["data"]) == 2
        trace_names = {trace["name"] for trace in spec["data"]}
        assert trace_names == {"A", "B"}

    def test_plotly_with_title(self, sample_data):
        """Should include title in layout."""
        rows = [
            {"format": "plotly", "config": {"type": "bar", "x": "month", "y": "revenue", "title": "Revenue Chart"}, **row}
            for row in sample_data
        ]

        spec, _ = expand_data_driven_chart(rows)

        assert spec["layout"]["title"]["text"] == "Revenue Chart"

    def test_vegalite_shorthand_bar_chart(self, sample_data):
        """Should expand Vega-Lite shorthand config into full spec."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "bar", "x": "month", "y": "revenue"}, **row}
            for row in sample_data
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "vega-lite"
        assert "$schema" in spec
        assert spec["mark"] == "bar"
        assert spec["encoding"]["x"]["field"] == "month"
        assert spec["encoding"]["y"]["field"] == "revenue"
        # Data should be embedded
        assert "data" in spec
        assert len(spec["data"]["values"]) == len(sample_data)

    def test_vegalite_with_full_encoding(self, sample_data):
        """Should preserve full encoding if already specified."""
        config = {
            "mark": "point",
            "encoding": {
                "x": {"field": "month", "type": "ordinal"},
                "y": {"field": "revenue", "type": "quantitative", "scale": {"zero": False}}
            }
        }
        rows = [
            {"format": "vega-lite", "config": config, **row}
            for row in sample_data
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "vega-lite"
        assert spec["encoding"]["y"]["scale"]["zero"] is False

    def test_vegalite_pie_chart(self):
        """Should expand Vega-Lite arc/pie chart."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "arc", "theta": "value", "color": "category"}, "category": "A", "value": 30},
            {"format": "vega-lite", "config": {"mark": "arc", "theta": "value", "color": "category"}, "category": "B", "value": 70},
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "vega-lite"
        assert spec["mark"]["type"] == "arc"
        assert spec["encoding"]["theta"]["field"] == "value"
        assert spec["encoding"]["color"]["field"] == "category"

    def test_vegalite_with_title(self, sample_data):
        """Should include title in Vega-Lite spec."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "line", "x": "month", "y": "revenue", "title": "Trend"}, **row}
            for row in sample_data
        ]

        spec, _ = expand_data_driven_chart(rows)

        assert spec["title"] == "Trend"

    def test_vegalite_infers_types(self):
        """Should infer quantitative type for numeric columns."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "point", "x": "num", "y": "val"}, "num": 1.5, "val": 10},
            {"format": "vega-lite", "config": {"mark": "point", "x": "num", "y": "val"}, "num": 2.5, "val": 20},
        ]

        spec, _ = expand_data_driven_chart(rows)

        assert spec["encoding"]["x"]["type"] == "quantitative"
        assert spec["encoding"]["y"]["type"] == "quantitative"

    def test_config_from_json_string(self, sample_data):
        """Should parse config if it's a JSON string."""
        config_str = '{"type": "bar", "x": "month", "y": "revenue"}'
        rows = [
            {"format": "plotly", "config": config_str, **row}
            for row in sample_data
        ]

        spec, library = expand_data_driven_chart(rows)

        assert library == "plotly"
        assert spec["data"][0]["type"] == "bar"

    def test_empty_rows_raises(self):
        """Should raise error for empty rows."""
        with pytest.raises(ValueError, match="No rows provided"):
            expand_data_driven_chart([])

    def test_missing_config_raises(self):
        """Should raise error if config is missing."""
        rows = [{"format": "plotly", "month": "Jan", "revenue": 100}]

        with pytest.raises(ValueError, match="No config found"):
            expand_data_driven_chart(rows)

    def test_unknown_format_raises(self):
        """Should raise error for unknown format."""
        rows = [{"format": "unknown_lib", "config": {"x": "a"}, "a": 1}]

        with pytest.raises(ValueError, match="Unknown chart format"):
            expand_data_driven_chart(rows)

    def test_extracts_only_data_columns(self, sample_data):
        """Should exclude format and config from data columns."""
        rows = [
            {"format": "plotly", "config": {"type": "bar", "x": "month", "y": "revenue"}, **row}
            for row in sample_data
        ]

        spec, _ = expand_data_driven_chart(rows)

        # The data should not include format or config
        # This is tested implicitly - if format/config were included,
        # they'd show up in x or y arrays
        assert spec["data"][0]["x"] == ["Jan", "Feb", "Mar", "Apr"]
        assert "plotly" not in spec["data"][0]["x"]

    def test_vegalite_with_color_encoding(self, sample_data):
        """Should include color encoding in Vega-Lite spec."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "point", "x": "month", "y": "revenue", "color": "category"}, **row}
            for row in sample_data
        ]

        spec, _ = expand_data_driven_chart(rows)

        assert "color" in spec["encoding"]
        assert spec["encoding"]["color"]["field"] == "category"

    def test_vegalite_with_size_encoding(self):
        """Should include size encoding in Vega-Lite spec."""
        rows = [
            {"format": "vega-lite", "config": {"mark": "circle", "x": "a", "y": "b", "size": "c"}, "a": 1, "b": 2, "c": 10},
        ]

        spec, _ = expand_data_driven_chart(rows)

        assert "size" in spec["encoding"]
        assert spec["encoding"]["size"]["field"] == "c"


