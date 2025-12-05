import json
import os
from windlass.eddies.base import simple_eddy

@simple_eddy
def create_chart(title: str, data_points: str) -> str:
    """
    Creates a simple bar chart and returns it as an image.
    data_points should be comma-separated numbers.
    """
    # Lazy import matplotlib to avoid import errors when not installed
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: matplotlib is not installed. Install it with: pip install matplotlib"

    try:
        data = [float(x.strip()) for x in data_points.split(",")]
    except ValueError:
        return "Error: data_points must be comma-separated numbers."

    filename = "chart.png"
    abs_path = os.path.abspath(filename)

    plt.figure(figsize=(6, 4))
    plt.bar(range(len(data)), data, color='skyblue')
    plt.title(title)
    plt.xlabel('Items')
    plt.ylabel('Values')
    plt.savefig(abs_path)
    plt.close()

    # Return magic structure
    return json.dumps({
        "content": f"I have generated the chart '{title}' with data {data_points}.",
        "images": [abs_path]
    })


@simple_eddy
def create_vega_lite(spec_json: str, width: int = 600, height: int = 400) -> str:
    """
    Creates a visualization from a Vega-Lite JSON specification.

    Vega-Lite is a high-level grammar of interactive graphics. Provide a complete
    spec including data, mark type, and encoding channels.

    Parameters:
        spec_json: A JSON string containing the Vega-Lite specification
        width: Chart width in pixels (default: 600)
        height: Chart height in pixels (default: 400)

    Example spec for a bar chart:
    {
      "data": {"values": [
        {"category": "A", "value": 28},
        {"category": "B", "value": 55},
        {"category": "C", "value": 43}
      ]},
      "mark": "bar",
      "encoding": {
        "x": {"field": "category", "type": "nominal", "title": "Category"},
        "y": {"field": "value", "type": "quantitative", "title": "Value"},
        "color": {"field": "category", "type": "nominal"}
      }
    }

    Example spec for a line chart:
    {
      "data": {"values": [
        {"date": "2024-01", "sales": 100},
        {"date": "2024-02", "sales": 150},
        {"date": "2024-03", "sales": 130}
      ]},
      "mark": {"type": "line", "point": true},
      "encoding": {
        "x": {"field": "date", "type": "temporal", "title": "Date"},
        "y": {"field": "sales", "type": "quantitative", "title": "Sales"}
      }
    }

    Common mark types: bar, line, point, area, arc (pie), rect, text, boxplot
    Encoding types: quantitative (numbers), nominal (categories), ordinal (ordered), temporal (dates)

    For more complex charts, you can use layers, facets, and selections.
    See: https://vega.github.io/vega-lite/docs/
    """
    # Lazy imports
    try:
        import altair as alt
    except ImportError:
        return "Error: altair is not installed. Install with: pip install altair"

    try:
        import vl_convert as vlc
    except ImportError:
        return "Error: vl-convert-python is not installed. Install with: pip install vl-convert-python"

    # Parse JSON spec
    try:
        spec = json.loads(spec_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in spec_json: {e}"

    # Validate spec has minimum required fields
    if not isinstance(spec, dict):
        return "Error: spec_json must be a JSON object (dict)"

    if "data" not in spec:
        return "Error: Vega-Lite spec must include 'data' field with values or url"

    if "mark" not in spec:
        return "Error: Vega-Lite spec must include 'mark' field (e.g., 'bar', 'line', 'point')"

    filename = "chart.png"
    abs_path = os.path.abspath(filename)

    try:
        # Add width/height to spec if not already present
        if "width" not in spec:
            spec["width"] = width
        if "height" not in spec:
            spec["height"] = height

        # Convert to PNG using vl-convert
        png_data = vlc.vegalite_to_png(spec, scale=2)  # scale=2 for retina quality

        with open(abs_path, 'wb') as f:
            f.write(png_data)

        # Extract chart description from spec
        mark_type = spec.get("mark")
        if isinstance(mark_type, dict):
            mark_type = mark_type.get("type", "chart")

        return json.dumps({
            "content": f"Created Vega-Lite {mark_type} chart ({width}x{height}px)",
            "images": [abs_path]
        })

    except Exception as e:
        return f"Error rendering Vega-Lite chart: {type(e).__name__}: {e}"


@simple_eddy
def create_plotly(spec_json: str, width: int = 800, height: int = 600) -> str:
    """
    Creates a visualization from a Plotly JSON specification.

    Plotly provides rich, interactive charts with extensive customization options.
    Provide a spec with 'data' (list of traces) and optional 'layout'.

    Parameters:
        spec_json: A JSON string containing the Plotly figure specification
        width: Chart width in pixels (default: 800)
        height: Chart height in pixels (default: 600)

    Example spec for a bar chart:
    {
      "data": [{
        "type": "bar",
        "x": ["Apples", "Oranges", "Bananas"],
        "y": [10, 15, 7],
        "marker": {"color": ["red", "orange", "yellow"]}
      }],
      "layout": {
        "title": {"text": "Fruit Sales"},
        "xaxis": {"title": "Fruit"},
        "yaxis": {"title": "Quantity"}
      }
    }

    Example spec for a line chart:
    {
      "data": [{
        "type": "scatter",
        "mode": "lines+markers",
        "x": [1, 2, 3, 4, 5],
        "y": [10, 15, 13, 17, 22],
        "name": "Series A"
      }],
      "layout": {
        "title": {"text": "Trend Over Time"}
      }
    }

    Example spec for a pie chart:
    {
      "data": [{
        "type": "pie",
        "labels": ["A", "B", "C"],
        "values": [30, 50, 20],
        "hole": 0.3
      }]
    }

    Common trace types: bar, scatter, pie, heatmap, histogram, box, violin, sankey, treemap
    Scatter modes: lines, markers, lines+markers, text

    For full documentation: https://plotly.com/python/reference/
    """
    # Lazy imports
    try:
        import plotly.io as pio
        import plotly.graph_objects as go
    except ImportError:
        return "Error: plotly is not installed. Install with: pip install plotly"

    # Check for kaleido (required for static image export)
    try:
        import kaleido
    except ImportError:
        return "Error: kaleido is not installed. Install with: pip install kaleido"

    # Parse JSON spec
    try:
        spec = json.loads(spec_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in spec_json: {e}"

    # Validate spec structure
    if not isinstance(spec, dict):
        return "Error: spec_json must be a JSON object (dict)"

    if "data" not in spec:
        return "Error: Plotly spec must include 'data' field with list of traces"

    if not isinstance(spec["data"], list):
        return "Error: Plotly 'data' field must be a list of trace objects"

    if len(spec["data"]) == 0:
        return "Error: Plotly 'data' field must contain at least one trace"

    filename = "chart.png"
    abs_path = os.path.abspath(filename)

    try:
        # Create figure from spec
        fig = go.Figure(spec)

        # Update layout with dimensions
        fig.update_layout(
            width=width,
            height=height,
            template="plotly_white"  # Clean default theme
        )

        # Export to PNG
        fig.write_image(abs_path, scale=2)  # scale=2 for retina quality

        # Extract chart description
        trace_types = [t.get("type", "trace") for t in spec["data"]]
        unique_types = list(set(trace_types))
        chart_desc = ", ".join(unique_types)

        title = ""
        if "layout" in spec and isinstance(spec["layout"], dict):
            title_obj = spec["layout"].get("title", {})
            if isinstance(title_obj, str):
                title = title_obj
            elif isinstance(title_obj, dict):
                title = title_obj.get("text", "")

        content = f"Created Plotly chart ({chart_desc}) ({width}x{height}px)"
        if title:
            content = f"Created Plotly chart: '{title}' ({chart_desc}) ({width}x{height}px)"

        return json.dumps({
            "content": content,
            "images": [abs_path]
        })

    except Exception as e:
        return f"Error rendering Plotly chart: {type(e).__name__}: {e}"