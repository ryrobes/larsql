# Copyright 2024 Marimo. All rights reserved.
# DEV FORK ADDITION: Stream kernel messages for external tool integration.
# Enable with MARIMO_DEV_MODE=1 environment variable.
"""
DEV ONLY: SSE endpoint for streaming kernel messages to external tools.

This enables tools like React-based canvases to receive real-time updates
about cell outputs, status changes, UI element values, and dependency graphs.

Usage:
    MARIMO_DEV_MODE=1 marimo edit notebook.py

Then connect to:
    GET /api/dev/stream          - SSE stream of all kernel messages
    GET /api/dev/state           - Current session state snapshot
    GET /api/dev/cell/{cell_id}  - Render single cell as embeddable HTML (for iframes)
    GET /api/dev/sessions        - List active sessions
"""

from __future__ import annotations

import asyncio
import glob
import html as html_module
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from marimo._messaging.cell_output import CellOutput, CellChannel
from marimo._messaging.ops import (
    CellOp,
    Variables,
    VariableValues,
    deserialize_kernel_message,
)
from marimo._messaging.types import KernelMessage
from marimo._server.api.deps import AppState
from marimo._server.export.exporter import get_html_contents
from marimo._server.notebook import read_css_file
from marimo._server.router import APIRouter
from marimo._server.templates.templates import json_script
from marimo._utils.paths import marimo_package_path
from marimo._version import __version__

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()


@lru_cache(maxsize=1)
def _get_css_files() -> list[str]:
    """
    Discover CSS files from marimo's compiled static assets.

    Returns paths like 'assets/index-B1hpQt_d.css' that can be loaded via the server.
    We cache this since the files don't change during a session.
    """
    static_dir = marimo_package_path() / "_static" / "assets"

    if not static_dir.exists():
        return []

    # Find all CSS files - prioritize key ones for output rendering
    priority_patterns = ["index-", "Output-", "cells-"]
    priority_files: list[str] = []
    other_files: list[str] = []

    for css_file in static_dir.glob("*.css"):
        relative_path = f"assets/{css_file.name}"
        is_priority = any(p in css_file.name for p in priority_patterns)
        if is_priority:
            priority_files.append(relative_path)
        else:
            other_files.append(relative_path)

    # Return priority files first, then others
    return priority_files + other_files


def is_dev_mode() -> bool:
    """Check if dev mode is enabled via environment variable."""
    return os.environ.get("MARIMO_DEV_MODE", "").lower() in ("1", "true", "yes")


# CORS headers for dev endpoints (allow all origins in dev mode)
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Marimo-Session-Id, Accept",
    "Access-Control-Expose-Headers": "Content-Type",
}


def cors_json_response(data: dict, status_code: int = 200) -> JSONResponse:
    """Create a JSONResponse with CORS headers."""
    return JSONResponse(data, status_code=status_code, headers=CORS_HEADERS)


async def cors_options_handler(request: "Request") -> Response:
    """Handle CORS preflight OPTIONS request."""
    return Response(status_code=204, headers=CORS_HEADERS)


# Register OPTIONS handlers for CORS preflight requests
# These must be registered before the GET handlers
router.add_route("/state", cors_options_handler, methods=["OPTIONS"])
router.add_route("/stream", cors_options_handler, methods=["OPTIONS"])
router.add_route("/sessions", cors_options_handler, methods=["OPTIONS"])
router.add_route("/cell/{cell_id}", cors_options_handler, methods=["OPTIONS"])


def serialize_cell_op(cell_op: Any) -> dict[str, Any]:
    """Serialize a CellOp to a JSON-friendly dict."""
    result: dict[str, Any] = {
        "cell_id": cell_op.cell_id,
        "status": cell_op.status,
        "stale_inputs": cell_op.stale_inputs,
        "timestamp": cell_op.timestamp,
    }

    if cell_op.output:
        output_data = cell_op.output.data
        # Handle different data types
        if isinstance(output_data, (list, dict)):
            # Errors or complex data - serialize as-is
            try:
                json.dumps(output_data)  # Test if serializable
            except (TypeError, ValueError):
                output_data = str(output_data)

        result["output"] = {
            "channel": cell_op.output.channel.value if hasattr(cell_op.output.channel, 'value') else str(cell_op.output.channel),
            "mimetype": cell_op.output.mimetype,
            "data": output_data,
            "timestamp": cell_op.output.timestamp,
        }

    if cell_op.console:
        console_list = cell_op.console if isinstance(cell_op.console, list) else [cell_op.console]
        result["console"] = [
            {
                "channel": c.channel.value if hasattr(c.channel, 'value') else str(c.channel),
                "mimetype": c.mimetype,
                "data": c.data,
            }
            for c in console_list
        ]

    return result


def build_cell_dependencies(variables_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Convert variable-based dependency graph to cell-based dependency map.

    Returns:
    {
        "<cell_id>": {
            "inputs": ["var1", "var2"],      # Variables this cell uses (consumes)
            "outputs": ["var3"],              # Variables this cell declares (produces)
            "upstream": ["cell1", "cell2"],   # Cells that must run before this one
            "downstream": ["cell3"]           # Cells that depend on this one
        }
    }
    """
    cell_deps: dict[str, dict[str, Any]] = {}

    # First pass: collect inputs and outputs for each cell
    for var_info in variables_list:
        var_name = var_info["name"]
        declared_by = var_info["declared_by"]
        used_by = var_info["used_by"]

        # Record outputs (variables declared by each cell)
        for cell_id in declared_by:
            if cell_id not in cell_deps:
                cell_deps[cell_id] = {"inputs": [], "outputs": [], "upstream": set(), "downstream": set()}
            cell_deps[cell_id]["outputs"].append(var_name)

        # Record inputs (variables used by each cell)
        for cell_id in used_by:
            if cell_id not in cell_deps:
                cell_deps[cell_id] = {"inputs": [], "outputs": [], "upstream": set(), "downstream": set()}
            cell_deps[cell_id]["inputs"].append(var_name)

            # Also record cell-to-cell dependencies
            # This cell depends on all cells that declare this variable
            for declaring_cell in declared_by:
                if declaring_cell != cell_id:  # Don't self-reference
                    cell_deps[cell_id]["upstream"].add(declaring_cell)
                    # And the declaring cell has this cell as downstream
                    if declaring_cell not in cell_deps:
                        cell_deps[declaring_cell] = {"inputs": [], "outputs": [], "upstream": set(), "downstream": set()}
                    cell_deps[declaring_cell]["downstream"].add(cell_id)

    # Convert sets to sorted lists for JSON serialization
    for cell_id in cell_deps:
        cell_deps[cell_id]["upstream"] = sorted(cell_deps[cell_id]["upstream"])
        cell_deps[cell_id]["downstream"] = sorted(cell_deps[cell_id]["downstream"])

    return cell_deps


def get_session_snapshot(session: Any) -> dict[str, Any]:
    """
    Extract current state from session view.

    Returns a complete snapshot including:
    - cells: All cell operations (outputs, status, console)
    - ui_values: Current values of all UI elements
    - variables: Dependency graph (who declares/uses what)
    - cell_dependencies: Cell-to-cell dependency map (upstream/downstream)
    - cell_order: Notebook order of cells
    - last_executed_code: Most recent code for each cell
    """
    view = session.session_view

    def _infer_dtype(val: Any) -> str:
        """Best-effort string type for variable values."""
        try:
            import pandas as pd
            if isinstance(val, pd.DataFrame):
                return "dataframe"
            if isinstance(val, pd.Series):
                return "series"
        except Exception:
            pass

        try:
            import polars as pl  # type: ignore
            if isinstance(val, pl.DataFrame):
                return "dataframe"
            if isinstance(val, pl.Series):
                return "series"
        except Exception:
            pass

        if isinstance(val, (list, tuple, set)):
            return "list"
        if isinstance(val, dict):
            return "dict"
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, int):
            return "int"
        if isinstance(val, float):
            return "float"
        if isinstance(val, str):
            return "string"
        # Fallback to class name
        return val.__class__.__name__ if val is not None else "unknown"

    # Serialize all cell operations
    cells: dict[str, Any] = {}
    for cell_id, cell_op in view.cell_operations.items():
        cells[cell_id] = serialize_cell_op(cell_op)

    # Serialize variable declarations (dependency graph)
    variables: list[dict[str, Any]] = []
    if view.variable_operations and view.variable_operations.variables:
        for var in view.variable_operations.variables:
            variables.append({
                "name": var.name,
                "declared_by": list(var.declared_by),
                "used_by": list(var.used_by),
            })

    # Serialize variable values
    variable_values: list[dict[str, Any]] = []
    variable_types: dict[str, str] = {}
    for name, var_val in view.variable_values.items():
        # Prefer Marimo's reported datatype, fallback to best-effort inference
        dtype = var_val.datatype or _infer_dtype(var_val.value)
        variable_types[name] = dtype
        variable_values.append({
            "name": var_val.name,
            "value": var_val.value,
            "datatype": dtype,
        })

    # Serialize UI values (handle non-JSON-serializable values)
    ui_values: dict[str, Any] = {}
    for k, v in view.ui_values.items():
        try:
            json.dumps(v)  # Test if serializable
            ui_values[k] = v
        except (TypeError, ValueError):
            ui_values[k] = str(v)

    # Build cell-to-cell dependency map from variables
    cell_dependencies = build_cell_dependencies(variables)

    return {
        "type": "snapshot",
        "cells": cells,
        "ui_values": ui_values,
        "variables": variables,
        "variable_values": variable_values,
        "variable_types": variable_types,
        "cell_dependencies": cell_dependencies,
        "cell_order": list(view.cell_ids.cell_ids) if view.cell_ids else [],
        "last_executed_code": dict(view.last_executed_code),
        "last_execution_time": dict(view.last_execution_time),
    }


def _convert_cell_output_to_session_format(cell_op: Any) -> list[dict[str, Any]]:
    """
    Convert a CellOp's output to the session snapshot format expected by marimo's frontend.

    The frontend expects outputs in this format:
    [{"type": "data", "data": {"mimetype": "data"}}]
    """
    outputs = []

    if cell_op.output:
        output_data = cell_op.output.data
        mimetype = cell_op.output.mimetype

        # Handle different mimetypes
        if isinstance(output_data, (list, dict)):
            try:
                json.dumps(output_data)  # Test if serializable
            except (TypeError, ValueError):
                output_data = str(output_data)

        outputs.append({
            "type": "data",
            "data": {mimetype: output_data},
        })

    return outputs


def _convert_cell_console_to_session_format(cell_op: Any) -> list[dict[str, Any]]:
    """Convert console outputs to session snapshot format."""
    console = []

    if cell_op.console:
        console_list = cell_op.console if isinstance(cell_op.console, list) else [cell_op.console]
        for c in console_list:
            channel = c.channel.value if hasattr(c.channel, 'value') else str(c.channel)
            console.append({
                "type": "data",
                "channel": channel,
                "data": {c.mimetype: c.data},
            })

    return console


def _convert_relative_to_absolute_paths(html: str, base_url: str = "") -> str:
    """
    Convert relative asset paths in HTML to absolute paths.

    The index.html template uses relative paths like './assets/...' which
    resolve incorrectly when served from nested endpoints like /api/dev/cell/{id}.

    This converts:
    - href="./assets/..." -> href="/assets/..."
    - src="./assets/..." -> src="/assets/..."
    - href="./" -> href="/"
    - etc.
    """
    # Ensure base_url doesn't have trailing slash for consistent replacement
    prefix = base_url.rstrip('/') if base_url else ''

    # Replace relative paths with absolute paths
    # Handle ./assets/ pattern (most common)
    html = html.replace('href="./assets/', f'href="{prefix}/assets/')
    html = html.replace("href='./assets/", f"href='{prefix}/assets/")
    html = html.replace('src="./assets/', f'src="{prefix}/assets/')
    html = html.replace("src='./assets/", f"src='{prefix}/assets/")

    # Handle ./ pattern for root-relative paths
    html = html.replace('href="./"', f'href="{prefix}/"')
    html = html.replace("href='./'", f"href='{prefix}/'")

    # Handle modulepreload and other link types
    html = re.sub(
        r'(href|src)="\./',
        rf'\1="{prefix}/',
        html
    )
    html = re.sub(
        r"(href|src)='\./",
        rf"\1='{prefix}/",
        html
    )

    return html


def _strip_modulepreload_links(html: str) -> str:
    """
    Remove modulepreload links to reduce parallel request count.

    Marimo's index.html includes 350+ modulepreload hints which cause
    ERR_INSUFFICIENT_RESOURCES when loading multiple iframes. The main
    index.js will lazy-load what it needs; preloading isn't critical
    for single-cell rendering.

    We keep:
    - The main script src (index-*.js)
    - CSS stylesheets
    - Font preloads
    - Image preloads

    We remove:
    - rel="modulepreload" links (bulk of the 350+ requests)
    """
    # Remove lines containing rel="modulepreload"
    # This regex matches the entire <link rel="modulepreload" ...> tag
    html = re.sub(
        r'<link\s+rel="modulepreload"[^>]*>\s*',
        '',
        html,
        flags=re.IGNORECASE
    )
    return html


def _parse_marimo_web_component(html_data: str) -> tuple[str, str]:
    """
    Parse marimo web components from HTML and convert to native rendering.

    Returns (output_html, extra_scripts) tuple.

    Handles:
    - <marimo-plotly data-figure='...'> → Plotly.js
    - <marimo-vega data-spec='...'> → Vega-Embed
    - <marimo-table ...> → Native HTML table
    - Other components → pass through as-is
    """
    from html import unescape

    output_html = html_data
    extra_scripts = ""

    def extract_data_attr(html: str, attr_name: str) -> str | None:
        """Extract a data-* attribute value from HTML, handling both single and double quotes."""
        import sys

        # Method 1: Single quotes with non-greedy capture up to next quote
        match = re.search(rf"data-{attr_name}='([^']*)'", html, re.DOTALL)
        if match:
            result = match.group(1)
            print(f"[EXTRACT_ATTR DEBUG] Found data-{attr_name} (method 1, single quotes): {len(result)} chars", file=sys.stderr)
            return result

        # Method 2: Double quotes
        match = re.search(rf'data-{attr_name}="([^"]*)"', html, re.DOTALL)
        if match:
            result = match.group(1)
            print(f"[EXTRACT_ATTR DEBUG] Found data-{attr_name} (method 2, double quotes): {len(result)} chars", file=sys.stderr)
            return result

        # Method 3: More robust - find attribute start and scan for matching quote
        # This handles cases where there might be escaped quotes inside
        pattern = rf"data-{attr_name}=(['\"])"
        start_match = re.search(pattern, html)
        if start_match:
            quote_char = start_match.group(1)
            start_pos = start_match.end()
            # Find the matching closing quote (not preceded by &#)
            depth = 0
            pos = start_pos
            while pos < len(html):
                if html[pos] == quote_char and (pos == start_pos or html[pos-1:pos+1] != f"&#{quote_char}"):
                    # Found closing quote
                    result = html[start_pos:pos]
                    print(f"[EXTRACT_ATTR DEBUG] Found data-{attr_name} (method 3, robust scan): {len(result)} chars", file=sys.stderr)
                    return result
                pos += 1

        print(f"[EXTRACT_ATTR DEBUG] Could NOT find data-{attr_name} in HTML", file=sys.stderr)
        return None

    def decode_marimo_json(encoded: str) -> Any:
        """Decode JSON from marimo's HTML-escaped format."""
        decoded = unescape(encoded)
        # Handle marimo's manual escapes for backslashes and dollar signs
        decoded = decoded.replace("&#92;", "\\").replace("&#36;", "$")
        return json.loads(decoded)

    # Check for marimo-plotly component (attribute may appear anywhere in tag)
    if "<marimo-plotly" in html_data:
        figure_data = extract_data_attr(html_data, "figure")
        config_data = extract_data_attr(html_data, "config")
        if figure_data:
            try:
                plotly_figure = decode_marimo_json(figure_data)
                plotly_config = {}
                if config_data:
                    try:
                        plotly_config = decode_marimo_json(config_data)
                    except Exception:
                        pass  # Use empty config if parsing fails

                # The figure has structure: {data: [...], layout: {...}, frames?: [...]}
                # We need to properly extract and merge with defaults like marimo does
                output_html = '<div id="plotly-chart" style="width:100%;min-height:400px;"></div>'
                extra_scripts = f'''
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
        (function() {{
            const figure = {json.dumps(plotly_figure)};
            const userConfig = {json.dumps(plotly_config)};

            // Extract data, layout, and frames from figure
            const data = figure.data || [];
            const frames = figure.frames || null;

            // Apply layout defaults like marimo does (PlotlyPlugin.tsx initialLayout)
            // Enable autosize if width is not specified
            const shouldAutoSize = figure.layout?.width === undefined;
            const layout = {{
                autosize: shouldAutoSize,
                height: 540,
                // Spread user's layout on top of defaults
                ...figure.layout,
                // Ensure paper and plot backgrounds are transparent for dark theme
                paper_bgcolor: figure.layout?.paper_bgcolor || 'rgba(0,0,0,0)',
                plot_bgcolor: figure.layout?.plot_bgcolor || 'rgba(0,0,0,0)',
            }};

            // Merge config with defaults
            const config = {{
                displaylogo: false,
                responsive: true,
                ...userConfig
            }};

            // Create the plot
            Plotly.newPlot('plotly-chart', data, layout, config).then(function(gd) {{
                // If we have frames, add them for animations
                if (frames && frames.length > 0) {{
                    Plotly.addFrames(gd, frames);
                }}
            }});
        }})();
    </script>'''
                return output_html, extra_scripts
            except (json.JSONDecodeError, Exception) as e:
                output_html = f'<pre style="color: #fb7185;">Error parsing Plotly data: {html_module.escape(str(e))}</pre>'
                return output_html, extra_scripts

    # Check for marimo-vega component
    if "<marimo-vega" in html_data:
        spec_data = extract_data_attr(html_data, "spec")
        if spec_data:
            try:
                vega_data = decode_marimo_json(spec_data)
                output_html = '<div id="vega-chart"></div>'
                extra_scripts = f'''
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
    <script>
        vegaEmbed('#vega-chart', {json.dumps(vega_data)}, {{actions: false, theme: 'dark'}});
    </script>'''
                return output_html, extra_scripts
            except (json.JSONDecodeError, Exception) as e:
                output_html = f'<pre style="color: #fb7185;">Error parsing Vega data: {html_module.escape(str(e))}</pre>'
                return output_html, extra_scripts

    # Check for marimo-table component (pandas dataframes)
    if "<marimo-table" in html_data:
        def extract_attr(html: str, attr_name: str) -> str | None:
            """Extract a data-* attribute value, handling single/double quotes."""
            # Try single quotes first, then double quotes
            for quote in ["'", '"']:
                pattern = f"data-{attr_name}={quote}"
                start_idx = html.find(pattern)
                if start_idx != -1:
                    value_start = start_idx + len(pattern)
                    # Find closing quote
                    end_idx = html.find(quote, value_start)
                    if end_idx != -1:
                        return html[value_start:end_idx]
            return None

        # Extract table attributes
        data_str = extract_attr(html_data, "data")
        lazy_str = extract_attr(html_data, "lazy")
        field_types_str = extract_attr(html_data, "field-types")
        row_headers_str = extract_attr(html_data, "row-headers")
        total_rows_str = extract_attr(html_data, "total-rows")
        total_cols_str = extract_attr(html_data, "total-columns")

        # Decode lazy attribute first to understand what mode we're in
        is_lazy = False
        if lazy_str:
            try:
                is_lazy = decode_marimo_json(lazy_str) == True
            except Exception:
                pass

        # Internal marimo columns to hide from display
        INTERNAL_COLUMNS = {'_marimo_row_id', '_marimo_selected'}

        # Get column names from field-types or row-headers
        columns: list[str] = []
        if field_types_str:
            try:
                field_types = decode_marimo_json(field_types_str)
                if isinstance(field_types, dict):
                    columns = [c for c in field_types.keys() if c not in INTERNAL_COLUMNS]
            except Exception:
                pass
        elif row_headers_str:
            try:
                row_headers = decode_marimo_json(row_headers_str)
                if isinstance(row_headers, list):
                    columns = [c for c in row_headers if c not in INTERNAL_COLUMNS]
            except Exception:
                pass

        # Parse total rows for display
        total_rows_display = "?"
        total_cols_display = "?"
        if total_rows_str:
            try:
                total_rows_display = decode_marimo_json(total_rows_str)
                if total_rows_display == "too_many":
                    total_rows_display = "1M+"
            except Exception:
                pass
        if total_cols_str:
            try:
                total_cols_display = decode_marimo_json(total_cols_str)
            except Exception:
                pass

        rows = None
        if data_str:
            try:
                rows = decode_marimo_json(data_str)

                # Handle double-encoding: if result is a string, try to decode again
                if isinstance(rows, str):
                    try:
                        rows = json.loads(rows)
                    except Exception:
                        rows = None  # Second decode failed
            except Exception:
                rows = None

            if rows is not None:
                # If still no columns, try to infer from first row
                if not columns and rows and isinstance(rows, list) and len(rows) > 0:
                    first_row = rows[0]
                    if isinstance(first_row, dict):
                        columns = [c for c in first_row.keys() if c not in INTERNAL_COLUMNS]

                # Also detect lazy if data is empty but we have non-zero total-rows
                if not is_lazy and isinstance(rows, list) and len(rows) == 0:
                    if total_rows_str:
                        try:
                            tr = decode_marimo_json(total_rows_str)
                            if tr == "too_many" or (isinstance(tr, int) and tr > 0):
                                is_lazy = True
                        except Exception:
                            pass

                # Handle lazy loading case - data is empty or a string URL
                if is_lazy or isinstance(rows, str) or (isinstance(rows, list) and len(rows) == 0):
                    # Get column names for display
                    col_names_html = ""
                    if columns:
                        col_preview = columns[:8]  # Show first 8 columns
                        col_names_html = '<div style="margin-top:8px;font-size:10px;color:#64748b;">'
                        col_names_html += ', '.join(f'<span style="color:#94a3b8;">{html_module.escape(c)}</span>' for c in col_preview)
                        if len(columns) > 8:
                            col_names_html += f' <span style="opacity:0.6;">+{len(columns)-8} more</span>'
                        col_names_html += '</div>'

                    lazy_html = f'''
                    <div style="padding:16px;color:#94a3b8;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                            <span style="font-size:16px;">📊</span>
                            <span style="font-size:13px;font-weight:500;color:#f1f5f9;">DataFrame Preview</span>
                        </div>
                        <div style="display:flex;gap:16px;font-size:11px;margin-bottom:4px;">
                            <span><span style="color:#64748b;">Rows:</span> <span style="color:#34d399;">{total_rows_display}</span></span>
                            <span><span style="color:#64748b;">Cols:</span> <span style="color:#60a5fa;">{total_cols_display}</span></span>
                        </div>
                        {col_names_html}
                        <div style="margin-top:10px;font-size:9px;color:#475569;">
                            ⚡ Lazy-loaded • Full data in Marimo editor
                        </div>
                    </div>'''
                    return lazy_html, extra_scripts

                # We have actual data - build HTML table
                if isinstance(rows, list) and len(rows) > 0:
                    table_html = '<table class="marimo-table" style="width:100%;border-collapse:collapse;font-size:12px;">'

                    # Header row
                    if columns:
                        table_html += '<thead><tr>'
                        for col_name in columns:
                            table_html += f'<th style="padding:8px;border-bottom:1px solid #334155;text-align:left;color:#94a3b8;">{html_module.escape(str(col_name))}</th>'
                        table_html += '</tr></thead>'

                    # Data rows
                    table_html += '<tbody>'
                    for row in rows[:50]:  # Limit to 50 rows
                        table_html += '<tr>'
                        if isinstance(row, dict):
                            if columns:
                                for col_name in columns:
                                    val = row.get(col_name, "")
                                    table_html += f'<td style="padding:6px 8px;border-bottom:1px solid #1e293b;">{html_module.escape(str(val))}</td>'
                            else:
                                # No columns list - iterate dict but skip internal keys
                                for key, val in row.items():
                                    if key not in INTERNAL_COLUMNS:
                                        table_html += f'<td style="padding:6px 8px;border-bottom:1px solid #1e293b;">{html_module.escape(str(val))}</td>'
                        elif isinstance(row, (list, tuple)):
                            for val in row:
                                table_html += f'<td style="padding:6px 8px;border-bottom:1px solid #1e293b;">{html_module.escape(str(val))}</td>'
                        table_html += '</tr>'
                    table_html += '</tbody></table>'

                    if len(rows) > 50:
                        table_html += f'<div style="color:#64748b;font-size:11px;margin-top:4px;">Showing 50 of {len(rows)} rows</div>'

                    return table_html, extra_scripts

        # Fallback: show a simple preview card if we couldn't render the table
        fallback_html = f'''
        <div style="padding:16px;color:#94a3b8;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="font-size:16px;">📊</span>
                <span style="font-size:13px;font-weight:500;color:#f1f5f9;">DataFrame</span>
            </div>
            <div style="display:flex;gap:16px;font-size:11px;margin-bottom:4px;">
                <span><span style="color:#64748b;">Rows:</span> <span style="color:#34d399;">{total_rows_display}</span></span>
                <span><span style="color:#64748b;">Cols:</span> <span style="color:#60a5fa;">{total_cols_display}</span></span>
            </div>
            <div style="margin-top:10px;font-size:9px;color:#475569;">
                View full data in Marimo editor
            </div>
        </div>'''
        return fallback_html, extra_scripts

    # Check for raw HTML tables (not marimo components)
    if "<table" in html_data.lower():
        # Add table styling
        extra_scripts = '''
    <style>
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th { padding: 8px; border-bottom: 1px solid #334155; text-align: left; color: #94a3b8; background: #1e293b; }
        td { padding: 6px 8px; border-bottom: 1px solid #1e293b; }
        tr:hover { background: rgba(255,255,255,0.03); }
    </style>'''
        return html_data, extra_scripts

    # For other marimo components or plain HTML, pass through
    return html_data, extra_scripts


def get_single_cell_html_static(
    cell_id: str,
    cell_op: Any,
    session_id: str,
    base_url: str = "",
    custom_css: Optional[str] = None,
) -> str:
    """
    Generate a STATIC HTML page for rendering a single cell's output.

    This does NOT use marimo's React app - it renders the output directly
    with appropriate CSS and JS for each output type. This avoids WebSocket
    sync issues that cause the React app to clear outputs.

    Supports:
    - Markdown/HTML (text/html, text/markdown)
    - Marimo web components (marimo-plotly, marimo-table, etc.)
    - Charts (application/vnd.plotly.v1+json, application/vnd.vegalite.v5+json)
    - Plain text, JSON
    - Images (base64, SVG)
    - LaTeX/KaTeX

    For interactive marimo UI elements (sliders, etc.), this renders them
    as read-only HTML - full interactivity would require the React app.
    """
    # Dynamically discover CSS files from marimo's static assets
    css_files = _get_css_files()
    prefix = base_url.rstrip('/') if base_url else ''
    css_links = "\n    ".join(
        f'<link rel="stylesheet" crossorigin href="{prefix}/{css_file}">'
        for css_file in css_files
    )

    # Add custom CSS if provided (from app_config.css_file or display.custom_css)
    custom_css_block = ""
    if custom_css:
        custom_css_block = f"\n    <style title='marimo-custom'>{custom_css}</style>"

    # Extract output data
    output_html = ""
    extra_scripts = ""
    mimetype = ""
    data = None

    if cell_op.output:
        mimetype = cell_op.output.mimetype
        data = cell_op.output.data

        # Handle different mimetypes
        if mimetype == "application/vnd.plotly.v1+json":
            # Plotly chart - render with Plotly.js
            plotly_figure = data if isinstance(data, dict) else json.loads(data)
            output_html = '<div id="plotly-chart" style="width:100%;min-height:400px;"></div>'
            extra_scripts = f'''
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
        (function() {{
            const figure = {json.dumps(plotly_figure)};

            // Extract data, layout, and frames from figure
            const data = figure.data || [];
            const frames = figure.frames || null;

            // Apply layout defaults like marimo does
            const shouldAutoSize = figure.layout?.width === undefined;
            const layout = {{
                autosize: shouldAutoSize,
                height: 540,
                ...figure.layout,
                paper_bgcolor: figure.layout?.paper_bgcolor || 'rgba(0,0,0,0)',
                plot_bgcolor: figure.layout?.plot_bgcolor || 'rgba(0,0,0,0)',
            }};

            const config = {{
                displaylogo: false,
                responsive: true,
            }};

            Plotly.newPlot('plotly-chart', data, layout, config).then(function(gd) {{
                if (frames && frames.length > 0) {{
                    Plotly.addFrames(gd, frames);
                }}
            }});
        }})();
    </script>'''

        elif mimetype in ("application/vnd.vegalite.v5+json", "application/vnd.vegalite.v4+json"):
            # Vega-Lite chart - render with Vega-Embed
            vega_data = data if isinstance(data, dict) else json.loads(data)
            output_html = '<div id="vega-chart"></div>'
            extra_scripts = f'''
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
    <script>
        vegaEmbed('#vega-chart', {json.dumps(vega_data)}, {{actions: false, theme: 'dark'}});
    </script>'''

        elif mimetype in ("text/html", "text/markdown"):
            # HTML content - check for marimo web components and parse them
            output_html, extra_scripts = _parse_marimo_web_component(str(data))

        elif mimetype == "text/latex":
            # LaTeX - render with KaTeX
            output_html = f'<div class="latex-output">{data}</div>'
            extra_scripts = '''
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
    <script>
        document.querySelectorAll('.latex-output').forEach(el => {
            katex.render(el.textContent, el, {throwOnError: false, displayMode: true});
        });
    </script>'''

        elif mimetype == "text/plain":
            output_html = f"<pre>{html_module.escape(str(data))}</pre>"

        elif mimetype == "application/json":
            try:
                formatted = json.dumps(json.loads(str(data)) if isinstance(data, str) else data, indent=2)
                output_html = f"<pre>{html_module.escape(formatted)}</pre>"
            except (json.JSONDecodeError, TypeError):
                output_html = f"<pre>{html_module.escape(str(data))}</pre>"

        elif mimetype == "image/svg+xml":
            output_html = str(data)

        elif mimetype.startswith("image/"):
            # Base64 image
            output_html = f'<img src="{data}" alt="Cell output" style="max-width: 100%;">'

        else:
            # Unknown mimetype - show as preformatted text
            output_html = f"<pre>{html_module.escape(str(data))}</pre>"
    else:
        # No output yet - show a helpful placeholder based on status
        status_msg = cell_op.status or "idle"
        if status_msg == "running":
            output_html = '''
            <div style="display: flex; align-items: center; justify-content: center; min-height: 60px; color: #a78bfa;">
                <svg class="spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" stroke-opacity="0.3"/>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
                </svg>
                <span style="margin-left: 8px; font-size: 13px;">Running...</span>
            </div>
            <style>@keyframes spin { to { transform: rotate(360deg); } } .spin { animation: spin 1s linear infinite; }</style>'''
        elif status_msg == "queued":
            output_html = '''
            <div style="display: flex; align-items: center; justify-content: center; min-height: 60px; color: #3b82f6;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M12 6v6l4 2"/>
                </svg>
                <span style="margin-left: 8px; font-size: 13px;">Queued</span>
            </div>'''
        else:
            output_html = '''
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60px; color: #64748b;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.6">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <path d="M9 9h6M9 12h6M9 15h4"/>
                </svg>
                <span style="margin-top: 6px; font-size: 12px;">No output yet</span>
                <span style="font-size: 10px; opacity: 0.7; margin-top: 2px;">Run cell to see results</span>
            </div>'''

    status = cell_op.status or "idle"

    # DEBUG: Hidden - set to empty string to disable debug overlay
    debug_info = ""

    return f'''<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cell {cell_id[:8]}</title>

    <!-- Marimo CSS for proper styling -->
    {css_links}
    {custom_css_block}

    <!-- Fallback fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Mono:wght@400;500;700&family=PT+Sans:wght@400;700&display=swap" rel="stylesheet">

    <style>
        html, body {{
            margin: 0;
            padding: 0;
            min-height: 100%;
            background: transparent !important;
            color: #e2e8f0;
            font-family: 'PT Sans', sans-serif;
        }}
        body {{
            padding: 8px 12px;
        }}

        /* Status indicator */
        .cell-status {{
            position: absolute;
            top: 4px;
            right: 4px;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            opacity: 0.8;
        }}
        .cell-status.idle {{ background: #22d3ee; }}
        .cell-status.running {{ background: #a78bfa; animation: pulse 1s infinite; }}
        .cell-status.queued {{ background: #3b82f6; }}
        .cell-status.stale {{ background: #eab308; }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 0.8; }}
            50% {{ opacity: 0.3; }}
        }}

        /* Output container */
        .cell-output {{
            position: relative;
            min-height: 20px;
        }}

        /* Prose/markdown styles */
        .prose, .markdown {{
            color: #e2e8f0;
            line-height: 1.75;
            font-size: 14px;
        }}
        .prose h1 {{ font-size: 2em; font-weight: 700; margin: 0.67em 0; }}
        .prose h2 {{ font-size: 1.5em; font-weight: 600; margin: 0.83em 0; }}
        .prose h3 {{ font-size: 1.17em; font-weight: 600; margin: 1em 0; }}
        .prose p {{ margin: 1em 0; }}
        .prose strong {{ font-weight: 700; }}
        .prose em {{ font-style: italic; }}
        .prose code {{
            background: rgba(255, 255, 255, 0.1);
            padding: 0.2em 0.4em;
            border-radius: 4px;
            font-family: 'Fira Mono', monospace;
            font-size: 0.9em;
        }}
        .prose pre {{
            background: rgba(0, 0, 0, 0.3);
            padding: 1em;
            border-radius: 6px;
            overflow-x: auto;
        }}
        .prose a {{ color: #60a5fa; text-decoration: underline; }}
        .prose ul, .prose ol {{ padding-left: 1.5em; margin: 1em 0; }}
        .prose li {{ margin: 0.5em 0; }}
        .prose blockquote {{
            border-left: 4px solid #3b82f6;
            padding-left: 1em;
            margin: 1em 0;
            color: #94a3b8;
        }}

        /* Plain pre */
        pre {{
            background: rgba(0, 0, 0, 0.3);
            padding: 1em;
            border-radius: 6px;
            overflow-x: auto;
            font-family: 'Fira Mono', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}

        /* Chart containers */
        #plotly-chart, #vega-chart {{
            background: transparent;
        }}

        /* Hide scrollbars */
        body::-webkit-scrollbar {{ display: none; }}
        body {{ -ms-overflow-style: none; scrollbar-width: none; }}
    </style>
</head>
<body data-marimo-session-id="{session_id}" data-marimo-cell-id="{cell_id}">
    {debug_info}
    <div class="cell-output">
        <div class="cell-status {status}"></div>
        <div id="output">
            {output_html}
        </div>
    </div>
    {extra_scripts}
    <script>
        // Auto-resize iframe
        function notifyParentOfHeight() {{
            const height = document.body.scrollHeight;
            window.parent.postMessage({{
                type: 'marimo-cell-resize',
                cellId: "{cell_id}",
                height: height
            }}, '*');
        }}
        const resizeObserver = new ResizeObserver(notifyParentOfHeight);
        resizeObserver.observe(document.body);
        setTimeout(notifyParentOfHeight, 50);
        setTimeout(notifyParentOfHeight, 200);
        setTimeout(notifyParentOfHeight, 500);
    </script>
</body>
</html>'''


def get_cell_html_page_fallback(
    cell_id: str,
    cell_op: Any,
    session_id: str,
    base_url: str = "",
) -> str:
    """
    Fallback HTML page for when the full JS bundle can't be loaded.

    Renders basic HTML/text content with CSS styling.
    """
    output_html = ""
    status = cell_op.status or "idle"

    if cell_op.output:
        mimetype = cell_op.output.mimetype
        data = cell_op.output.data

        if mimetype in ("text/html", "text/markdown", "text/latex"):
            output_html = str(data)
        elif mimetype == "text/plain":
            output_html = f"<pre>{html_module.escape(str(data))}</pre>"
        elif mimetype.startswith("image/"):
            output_html = f'<img src="{data}" alt="Cell output" style="max-width: 100%;">'
        else:
            output_html = f"<pre>{html_module.escape(str(data))}</pre>"

    return get_cell_html_page(
        cell_id=cell_id,
        output_html=output_html,
        session_id=session_id,
        base_url=base_url,
        status=status,
    )


def get_cell_html_page(
    cell_id: str,
    output_html: str,
    session_id: str,
    base_url: str = "",
    status: str = "idle",
) -> str:
    """
    Generate a minimal HTML page that renders a single cell's output.

    This is a lightweight standalone page designed for embedding in iframes.
    It loads Marimo's CSS (but not the full React app) so that HTML content
    renders with proper styling including prose/markdown typography classes.

    For interactive UI elements (sliders, etc.), a more sophisticated
    approach would be needed to hydrate those components.
    """
    # Dynamically discover CSS files from marimo's static assets
    # Use absolute paths from root to avoid relative path issues in iframes
    css_files = _get_css_files()
    # base_url may be empty or '/'; ensure we don't get double slashes
    prefix = base_url.rstrip('/') if base_url else ''
    css_links = "\n    ".join(
        f'<link rel="stylesheet" crossorigin href="{prefix}/{css_file}">'
        for css_file in css_files
    )

    return f'''<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cell {cell_id}</title>

    <!-- Load Marimo's compiled CSS for proper styling (prose, markdown, etc.) -->
    {css_links}

    <!-- Fallback fonts if not loaded from marimo's CSS -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Mono:wght@400;500;700&family=PT+Sans:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css" crossorigin="anonymous">

    <style>
        /* Override styles for iframe embedding context */
        html, body {{
            margin: 0;
            padding: 0;
            min-height: 100%;
            background: transparent !important;
            /* Inherit dark mode from the html.dark class */
        }}
        body {{
            padding: 8px 12px;
        }}

        /* Cell container */
        .marimo-cell-container {{
            position: relative;
        }}

        /* Status indicator */
        .marimo-cell-status {{
            position: absolute;
            top: 0;
            right: 0;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            opacity: 0.8;
            z-index: 10;
        }}
        .marimo-cell-status.idle {{
            background: #22d3ee;
        }}
        .marimo-cell-status.running {{
            background: #a78bfa;
            animation: pulse 1s infinite;
        }}
        .marimo-cell-status.queued {{
            background: #3b82f6;
        }}
        .marimo-cell-status.stale {{
            background: #eab308;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 0.8; }}
            50% {{ opacity: 0.3; }}
        }}

        /* Output area */
        .marimo-cell-output {{
            min-height: 20px;
        }}

        /* Essential prose/markdown styles (fallback if CSS files don't load) */
        .prose {{
            color: #e2e8f0;
            line-height: 1.75;
            font-size: 14px;
        }}
        .prose.contents {{
            display: contents;
        }}
        .prose h1 {{
            font-size: 2em;
            font-weight: 700;
            margin: 0.67em 0;
        }}
        .prose h2 {{
            font-size: 1.5em;
            font-weight: 600;
            margin: 0.83em 0;
        }}
        .prose h3 {{
            font-size: 1.17em;
            font-weight: 600;
            margin: 1em 0;
        }}
        .prose p, .prose .paragraph {{
            margin: 1em 0;
        }}
        .prose strong {{
            font-weight: 700;
        }}
        .prose em {{
            font-style: italic;
        }}
        .prose code {{
            background: rgba(255, 255, 255, 0.1);
            padding: 0.2em 0.4em;
            border-radius: 4px;
            font-family: 'Fira Mono', monospace;
            font-size: 0.9em;
        }}
        .prose pre {{
            background: rgba(0, 0, 0, 0.3);
            padding: 1em;
            border-radius: 6px;
            overflow-x: auto;
        }}
        .prose a {{
            color: #60a5fa;
            text-decoration: underline;
        }}
        .prose ul, .prose ol {{
            padding-left: 1.5em;
            margin: 1em 0;
        }}
        .prose li {{
            margin: 0.5em 0;
        }}
        .prose blockquote {{
            border-left: 4px solid #3b82f6;
            padding-left: 1em;
            margin: 1em 0;
            color: #94a3b8;
        }}

        /* Code highlighting */
        .codehilite {{
            background: rgba(0, 0, 0, 0.3);
            border-radius: 6px;
            padding: 1em;
            overflow-x: auto;
        }}

        /* KaTeX/LaTeX support */
        marimo-tex {{
            display: inline;
        }}

        /* Ensure markdown content displays correctly */
        .markdown.prose {{
            max-width: none;
        }}

        /* Hide scrollbars on body */
        body::-webkit-scrollbar {{
            display: none;
        }}
        body {{
            -ms-overflow-style: none;
            scrollbar-width: none;
        }}
    </style>
</head>
<body data-marimo-session-id="{session_id}" data-marimo-cell-id="{cell_id}">
    <div class="marimo-cell-container">
        <div class="marimo-cell-status {status}"></div>
        <div class="marimo-cell-output" id="output">
            {output_html}
        </div>
    </div>

    <script>
        // Configuration for external tools
        window.__MARIMO_CELL_EMBED__ = {{
            sessionId: "{session_id}",
            cellId: "{cell_id}",
            baseUrl: "{base_url}"
        }};

        // Auto-resize iframe to fit content
        function notifyParentOfHeight() {{
            const height = document.body.scrollHeight;
            window.parent.postMessage({{
                type: 'marimo-cell-resize',
                cellId: "{cell_id}",
                height: height
            }}, '*');
        }}

        // Observe changes and notify parent
        const resizeObserver = new ResizeObserver(() => {{
            notifyParentOfHeight();
        }});
        resizeObserver.observe(document.body);

        // Initial notification (with slight delays for rendering)
        setTimeout(notifyParentOfHeight, 50);
        setTimeout(notifyParentOfHeight, 200);

        // Listen for output updates from parent
        window.addEventListener('message', (event) => {{
            if (event.data.type === 'marimo-cell-update' && event.data.cellId === "{cell_id}") {{
                const outputEl = document.getElementById('output');
                if (event.data.html) {{
                    outputEl.innerHTML = event.data.html;
                }}

                // Update status indicator
                const statusEl = document.querySelector('.marimo-cell-status');
                if (statusEl && event.data.status) {{
                    statusEl.className = 'marimo-cell-status ' + event.data.status;
                }}

                // Re-notify of height after update
                setTimeout(notifyParentOfHeight, 50);
            }}
        }});
    </script>
</body>
</html>'''


@router.get("/cell/{cell_id}")
async def render_cell(request: Request) -> HTMLResponse:
    """
    Render a single cell's output as a standalone HTML page.

    Perfect for embedding in iframes on external canvases.
    Uses STATIC rendering (no React app, no WebSocket) to display cell outputs
    with proper styling for charts, markdown, data grids, etc.

    Query params:
        - session_id: The marimo session ID (required for iframes that can't send headers)
        - theme: 'light' or 'dark' (default: dark)

    Supports:
        - Markdown/HTML (mo.md(), HTML output)
        - Charts (Plotly, Vega-Lite/Altair)
        - Plain text, JSON
        - Images (base64, SVG)
        - LaTeX/KaTeX

    The iframe communicates with the parent via postMessage:
    - Sends 'marimo-cell-resize' when content height changes

    Note: Interactive marimo UI elements (sliders, etc.) are rendered as
    read-only HTML. Full interactivity would require the React app, which
    has WebSocket sync issues when embedded.
    """
    # Get cell_id from path params (marimo's APIRouter requires this pattern)
    cell_id = request.path_params.get("cell_id", "")

    if not is_dev_mode():
        return HTMLResponse(
            "<html><body>Dev mode not enabled. Set MARIMO_DEV_MODE=1</body></html>",
            status_code=403,
        )

    if not cell_id:
        return HTMLResponse(
            "<html><body>cell_id path parameter required</body></html>",
            status_code=400,
        )

    # Get session_id from query params (for iframes) or header
    session_id = request.query_params.get("session_id", "") or request.headers.get("Marimo-Session-Id", "")

    app_state = AppState(request)

    # Try to get session using query param session_id if header didn't work
    session = None
    if session_id:
        # Look up session by ID from the session manager
        session_manager = app_state.session_manager
        for sid, sess in session_manager.sessions.items():
            if str(sid) == session_id:
                session = sess
                break

    # Fall back to header-based lookup
    if session is None:
        session = app_state.get_current_session()

    if session is None:
        return HTMLResponse(
            "<html><body>No active session. Include session_id query param or Marimo-Session-Id header.</body></html>",
            status_code=400,
        )

    # Get the cell's current output
    view = session.session_view
    cell_op = view.cell_operations.get(cell_id)

    if cell_op is None:
        return HTMLResponse(
            f"<html><body>Cell {cell_id} not found in session.</body></html>",
            status_code=404,
        )

    # Base URL for assets
    base_url = app_state.base_url

    # Collect custom CSS from app_config and user_config
    custom_css_parts: list[str] = []

    # 1. Get CSS from notebook's app_config.css_file
    try:
        app_config = session.app_file_manager.app.config
        if app_config and app_config.css_file:
            notebook_path = session.app_file_manager.path
            css_content = read_css_file(app_config.css_file, filename=notebook_path)
            if css_content:
                custom_css_parts.append(css_content)
    except Exception:
        pass  # Ignore errors reading app config CSS

    # 2. Get CSS from user config display.custom_css
    try:
        user_config = session.config_manager.get_config()
        display_config = user_config.get("display", {})
        custom_css_paths = display_config.get("custom_css", [])
        notebook_path = session.app_file_manager.path
        for css_path in custom_css_paths:
            css_content = read_css_file(css_path, filename=notebook_path)
            if css_content:
                custom_css_parts.append(css_content)
    except Exception:
        pass  # Ignore errors reading user config CSS

    # Combine all custom CSS
    custom_css = "\n".join(custom_css_parts) if custom_css_parts else None

    # DEBUG: Log cell output info for troubleshooting
    import sys
    if cell_op.output:
        print(f"[DEV_STREAM DEBUG] cell_id={cell_id}", file=sys.stderr)
        print(f"[DEV_STREAM DEBUG] mimetype={cell_op.output.mimetype}", file=sys.stderr)
        print(f"[DEV_STREAM DEBUG] data type={type(cell_op.output.data)}", file=sys.stderr)
        data_preview = str(cell_op.output.data)[:500] if cell_op.output.data else "(None)"
        print(f"[DEV_STREAM DEBUG] data preview={data_preview}", file=sys.stderr)
    else:
        print(f"[DEV_STREAM DEBUG] cell_id={cell_id} has NO OUTPUT", file=sys.stderr)
        print(f"[DEV_STREAM DEBUG] cell_op.status={cell_op.status}", file=sys.stderr)

    # Use static rendering - no React app, no WebSocket
    # This properly displays outputs without the WS sync issues
    html_page = get_single_cell_html_static(
        cell_id=cell_id,
        cell_op=cell_op,
        session_id=session_id,
        base_url=base_url,
        custom_css=custom_css,
    )

    return HTMLResponse(html_page)


@router.get("/state")
async def get_current_state(request: Request) -> Response:
    """
    Get current session state snapshot.

    Requires Marimo-Session-Id header.

    Returns:
    {
        "type": "snapshot",
        "cells": {
            "<cell_id>": {
                "status": "idle" | "running" | "queued",
                "output": { "channel": "output", "mimetype": "text/html", "data": "..." },
                "stale_inputs": false,
                "timestamp": 1234567890.123
            }
        },
        "ui_values": { "<object_id>": <value> },
        "variables": [
            { "name": "x", "declared_by": ["cell1"], "used_by": ["cell2", "cell3"] }
        ],
        "variable_values": [
            { "name": "x", "value": "42", "datatype": "int" }
        ],
        "cell_order": ["cell1", "cell2", ...],
        "last_executed_code": { "<cell_id>": "code..." },
        "last_execution_time": { "<cell_id>": 123.45 }
    }
    """
    if not is_dev_mode():
        return cors_json_response(
            {"error": "Dev mode not enabled. Set MARIMO_DEV_MODE=1"},
            status_code=403,
        )

    app_state = AppState(request)
    session = app_state.get_current_session()

    if session is None:
        return cors_json_response(
            {"error": "No active session. Marimo-Session-Id header required."},
            status_code=400,
        )

    return cors_json_response(get_session_snapshot(session))


@router.get("/stream")
async def stream_kernel_messages(request: Request) -> StreamingResponse:
    """
    SSE endpoint that streams all kernel messages.

    Requires Marimo-Session-Id header.

    First sends a 'snapshot' event with current state, then streams live updates.

    Each message is a JSON object:
    {
        "op": "cell-op" | "variables" | "variable-values" | ...,
        "data": { ... }  // The operation payload
    }

    Message types:
    - cell-op: Cell output/status change
    - variables: Dependency graph update
    - variable-values: Variable value previews
    - completed-run: Execution finished
    - kernel-ready: Kernel initialized

    Keepalive comments sent every 30s to maintain connection.
    """
    if not is_dev_mode():
        async def error_gen():
            yield 'data: {"error": "Dev mode not enabled. Set MARIMO_DEV_MODE=1"}\n\n'

        return StreamingResponse(
            error_gen(),
            media_type="text/event-stream",
            status_code=403,
        )

    app_state = AppState(request)
    session = app_state.get_current_session()

    if session is None:
        async def error_gen():
            yield 'data: {"error": "No active session. Marimo-Session-Id header required."}\n\n'

        return StreamingResponse(
            error_gen(),
            media_type="text/event-stream",
            status_code=400,
        )

    # Create an async queue to receive messages
    message_queue: asyncio.Queue[KernelMessage] = asyncio.Queue(maxsize=1000)

    # Add ourselves as a consumer of the message distributor
    def on_message(msg: KernelMessage) -> None:
        try:
            message_queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Drop oldest if queue is full to prevent memory issues
            try:
                message_queue.get_nowait()
                message_queue.put_nowait(msg)
            except asyncio.QueueEmpty:
                pass

    disposable = session.message_distributor.add_consumer(on_message)

    async def generate():
        try:
            # First, send current state snapshot
            snapshot = get_session_snapshot(session)
            yield f"data: {json.dumps(snapshot)}\n\n"

            # Then stream live updates
            while True:
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=30.0)

                    # Deserialize to get the operation type
                    op = deserialize_kernel_message(msg)

                    # Build event data based on operation type
                    if isinstance(op, CellOp):
                        event_data = {
                            "op": "cell-op",
                            "data": serialize_cell_op(op),
                        }
                    elif isinstance(op, Variables):
                        event_data = {
                            "op": "variables",
                            "data": {
                                "variables": [
                                    {
                                        "name": v.name,
                                        "declared_by": list(v.declared_by),
                                        "used_by": list(v.used_by),
                                    }
                                    for v in op.variables
                                ]
                            },
                        }
                    elif isinstance(op, VariableValues):
                        event_data = {
                            "op": "variable-values",
                            "data": {
                                "variables": [
                                    {
                                        "name": v.name,
                                        "value": v.value,
                                        "datatype": v.datatype,
                                    }
                                    for v in op.variables
                                ]
                            },
                        }
                    else:
                        # For other ops, try to serialize the raw message
                        try:
                            raw_data = json.loads(msg.decode("utf-8"))
                            event_data = {
                                "op": getattr(op, 'name', type(op).__name__),
                                "data": raw_data,
                            }
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue

                    yield f"data: {json.dumps(event_data)}\n\n"

                except asyncio.TimeoutError:
                    # Send keepalive comment (not a data message)
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        except GeneratorExit:
            pass
        finally:
            disposable.dispose()

    # Merge CORS headers with SSE headers
    sse_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        **CORS_HEADERS,
    }

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=sse_headers,
    )


@router.get("/sessions")
async def list_sessions(request: Request) -> Response:
    """
    List all active sessions (for debugging/discovery).

    Returns:
    {
        "sessions": [
            {
                "session_id": "...",
                "file": "notebook.py",
                "mode": "edit"
            }
        ]
    }
    """
    if not is_dev_mode():
        return cors_json_response(
            {"error": "Dev mode not enabled. Set MARIMO_DEV_MODE=1"},
            status_code=403,
        )

    app_state = AppState(request)
    session_manager = app_state.session_manager

    sessions: list[dict[str, Any]] = []
    for session_id, session in session_manager.sessions.items():
        sessions.append({
            "session_id": str(session_id),
            "file": session.app_file_manager.filename,
            "mode": session.kernel_manager.mode.value,
        })

    return cors_json_response({"sessions": sessions})


@router.get("/cell/{cell_id}/health")
async def cell_health(request: Request) -> Response:
    """
    Health check endpoint for embedded cell iframes.

    Marimo's frontend checks this endpoint to verify the server is reachable
    before attempting to establish WebSocket connections.

    Returns a simple "ok" status to indicate the cell endpoint is healthy.
    """
    # Get cell_id from path params (marimo's APIRouter requires this pattern)
    cell_id = request.path_params.get("cell_id", "")

    if not is_dev_mode():
        return cors_json_response(
            {"error": "Dev mode not enabled. Set MARIMO_DEV_MODE=1"},
            status_code=403,
        )

    # Return a simple health status
    # The frontend just needs to know the server is reachable
    return cors_json_response({
        "status": "ok",
        "cell_id": cell_id,
    })


@router.websocket("/cell/{cell_id}/ws")
async def cell_websocket_idle(websocket: Any) -> None:
    """
    Idle WebSocket endpoint for embedded cell iframes.

    Marimo's frontend expects a WebSocket connection for real-time updates.
    For embedded read-only cells, we accept the connection but just keep
    it idle - no messages sent or received. This prevents error spam from
    the frontend trying to reconnect to a rejecting endpoint.

    The cell content is already rendered from the session snapshot in the
    mount_config, so no real-time updates are needed for static views.
    """
    from starlette.websockets import WebSocket

    ws: WebSocket = websocket

    if not is_dev_mode():
        await ws.close(code=1008, reason="Dev mode not enabled")
        return

    try:
        await ws.accept()

        # Just keep the connection alive but idle
        # The frontend will see it as "connected" and won't spam reconnects
        while True:
            try:
                # Wait for messages but don't do anything with them
                # Use a long timeout to keep connection alive
                message = await asyncio.wait_for(ws.receive(), timeout=30.0)

                # If client sends close, break the loop
                if message.get("type") == "websocket.disconnect":
                    break

            except asyncio.TimeoutError:
                # Send a ping/keepalive by just continuing
                # The connection stays alive
                continue

    except Exception:
        # Connection closed or errored, just exit quietly
        pass


# Register OPTIONS handlers for CORS preflight requests
# Using add_route directly since APIRouter doesn't have an options() method
async def _cell_health_options(request: Request) -> Response:
    """Handle CORS preflight for cell health endpoint."""
    return Response(content="", headers=CORS_HEADERS)


router.add_route("/cell/{cell_id}/health", _cell_health_options, methods=["OPTIONS"])
