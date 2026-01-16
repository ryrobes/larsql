"""
Alice TUI Dashboard Generator for LARS Cascade Visualization

Generates declarative Alice YAML dashboards from LARS cascade definitions,
enabling real-time TUI monitoring of cascade execution.

Usage:
    from lars.alice_generator import generate_alice_yaml
    yaml_content = generate_alice_yaml("examples/my_cascade.yaml", session_id="live_001")
"""

import json
import random
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


def get_random_background_image() -> Optional[str]:
    """Get a random background image from the tui directory."""
    tui_dir = Path(__file__).parent / "tui"
    jpg_files = list(tui_dir.glob("*.jpg")) + list(tui_dir.glob("*.png"))
    if jpg_files:
        return str(random.choice(jpg_files))
    return None


@dataclass
class CellPosition:
    """Position of a cell in the visualization grid."""
    x: int
    y: int
    width: int = 38
    height: int = 12
    column: int = 0
    row: int = 0


@dataclass
class CellInfo:
    """Extracted cell information for visualization."""
    name: str
    is_deterministic: bool
    has_takes: bool
    take_factor: int
    handoffs: List[str]
    skills: List[str]
    position: Optional[CellPosition] = None


def load_cascade(path: str) -> Dict[str, Any]:
    """Load cascade definition from JSON or YAML file."""
    path = Path(path)
    with open(path) as f:
        if path.suffix in ['.yaml', '.yml']:
            return yaml.safe_load(f)
        else:
            return json.load(f)


def extract_cells(cascade: Dict[str, Any]) -> List[CellInfo]:
    """Extract cell information from cascade definition."""
    cells = []
    for cell_def in cascade.get('cells', []):
        name = cell_def.get('name', 'unnamed')

        # Determine cell type
        is_deterministic = cell_def.get('tool') is not None

        # Check for takes
        takes = cell_def.get('takes', {})
        has_takes = takes is not None and bool(takes)
        take_factor = 1
        if has_takes:
            factor = takes.get('factor', 1)
            if isinstance(factor, int):
                take_factor = factor
            else:
                take_factor = 3  # Default for dynamic factor

        # Extract handoffs
        handoffs_raw = cell_def.get('handoffs', [])
        handoffs = []
        for h in handoffs_raw:
            if isinstance(h, str):
                handoffs.append(h)
            elif isinstance(h, dict) and 'target' in h:
                handoffs.append(h['target'])

        # Extract skills
        skills_raw = cell_def.get('skills', [])
        if isinstance(skills_raw, list):
            skills = skills_raw
        elif skills_raw == 'manifest':
            skills = ['manifest']
        else:
            skills = []

        cells.append(CellInfo(
            name=name,
            is_deterministic=is_deterministic,
            has_takes=has_takes,
            take_factor=take_factor,
            handoffs=handoffs,
            skills=skills
        ))

    return cells


def compute_layout(cells: List[CellInfo]) -> List[CellInfo]:
    """
    Compute grid positions for cells using topological layout.

    Places cells in columns based on their dependencies:
    - Cells with no incoming edges go in column 0
    - Other cells go in column = max(predecessor columns) + 1
    """
    if not cells:
        return cells

    # Build dependency graph
    cell_map = {c.name: c for c in cells}
    incoming = defaultdict(set)  # cell -> set of predecessors
    outgoing = defaultdict(set)  # cell -> set of successors

    for cell in cells:
        for handoff in cell.handoffs:
            if handoff in cell_map:
                incoming[handoff].add(cell.name)
                outgoing[cell.name].add(handoff)

    # Compute column for each cell (longest path from a root)
    columns = {}

    def get_column(name: str, visited: set) -> int:
        if name in columns:
            return columns[name]
        if name in visited:
            return 0  # Cycle detected, break it
        visited.add(name)

        if not incoming[name]:
            columns[name] = 0
        else:
            max_pred = max(get_column(pred, visited) for pred in incoming[name])
            columns[name] = max_pred + 1

        return columns[name]

    for cell in cells:
        get_column(cell.name, set())

    # Group cells by column
    by_column = defaultdict(list)
    for cell in cells:
        col = columns.get(cell.name, 0)
        by_column[col].append(cell)

    # Assign positions
    # Grid settings
    start_x = 10
    start_y = 8
    cell_width = 38
    cell_height = 12
    h_spacing = 8  # Horizontal gap between cells
    v_spacing = 3  # Vertical gap between cells

    for col_idx in sorted(by_column.keys()):
        col_cells = by_column[col_idx]
        x = start_x + col_idx * (cell_width + h_spacing)

        for row_idx, cell in enumerate(col_cells):
            y = start_y + row_idx * (cell_height + v_spacing)
            cell.position = CellPosition(
                x=x,
                y=y,
                width=cell_width,
                height=cell_height,
                column=col_idx,
                row=row_idx
            )

    return cells


def generate_cell_status_block(cell: CellInfo, cascade_id: str, session_id: Optional[str]) -> Dict[str, Any]:
    """Generate a hidden block that polls status for a specific cell."""
    cell_name = cell.name

    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    sql_query = f"SELECT MAX(CASE WHEN role='cell_complete' THEN 1 ELSE 0 END) as completed, MAX(CASE WHEN role='cell_start' THEN 1 ELSE 0 END) as started, round(COALESCE(SUM(cost), 0), 4) as cost FROM all_data WHERE {session_filter} AND cell_name = '{cell_name}'"

    return {
        'block_id': f'status_{cell_name}',
        'type': 'continuous',
        'visible': False,
        'command': f'while true; do\nlars sql query "{sql_query}" --format json 2>/dev/null || echo \'[{{"completed": 0, "started": 0, "cost": 0}}]\'\nsleep 1\ndone',
        'x': 0,
        'y': 0,
        'width': 1,
        'height': 1,
        'data_extraction': {
            'patterns': [
                {'type': 'extract_number', 'prefix': '"completed":', 'metric': 'completed'},
                {'type': 'extract_number', 'prefix': '"started":', 'metric': 'started'},
                {'type': 'extract_number', 'prefix': '"cost":', 'metric': 'cost'},
            ]
        }
    }


def generate_cell_block(cell: CellInfo, session_var: str = "{session_id}") -> Dict[str, Any]:
    """Generate Alice block definition for a single cell."""
    pos = cell.position or CellPosition(x=10, y=10)
    cell_name = cell.name

    # Determine type label based on cell type
    if cell.is_deterministic:
        type_label = "TOOL"
    elif cell.has_takes:
        type_label = f"LLM x{cell.take_factor}"
    else:
        type_label = "LLM"

    # Build status reference for Alice templates
    status_ref = f"status_{cell_name}"

    # Use Alice's ternary conditional for dynamic status display
    # IMPORTANT: Nested ternaries use parentheses within a SINGLE {{...}}, not nested {{...}}
    # Syntax: {{condition ? true_val : (nested_condition ? nested_true : nested_false)}}
    status_line = "Status: {{" + status_ref + ".completed == 1 ? '[green]Complete[/green]' : (" + status_ref + ".started == 1 ? '[yellow]Running...[/yellow]' : '[dim]Pending[/dim]')}}"
    cost_line = "Cost: ${{" + status_ref + ".cost}}"

    content = [
        f"[bold cyan]{cell_name}[/bold cyan]",
        f"[dim]{type_label}[/dim]",
        "",
        status_line,
        cost_line,
    ]

    if cell.skills:
        skills_str = ", ".join(cell.skills[:3])
        if len(cell.skills) > 3:
            skills_str += "..."
        content.append(f"[dim]Skills: {skills_str}[/dim]")

    # Use gradient color based on completion status for overlay
    overlay_color = "{{gradient(" + status_ref + ".completed, 0, 1, '#2c3e50', '#27ae60')}}"

    # Use ternary for border color: green if complete, yellow if running, dim gray if pending
    border_color = "{{" + status_ref + ".completed == 1 ? '#27ae60' : (" + status_ref + ".started == 1 ? '#f39c12' : '#3c3c5c')}}"

    block = {
        'block_id': f'cell_{cell_name}',
        'type': 'panel',
        'x': pos.x,
        'y': pos.y,
        'width': pos.width,
        'height': pos.height,
        'content': content,
        'block_map': {
            'title': f'{cell_name}',
            'overlay_color': overlay_color,
            'border_color': border_color,
            'darken_factor': 0.6,
            'blend_opacity': 0.3,
            'border': True,
            'padding': 1
        }
    }

    # Add parent_of for handoff connections
    if cell.handoffs:
        block['parent_of'] = [f'cell_{h}' for h in cell.handoffs]
        block['connection_style'] = {
            'line_style': 'solid',
            'color': 'cyan',
            'opacity': 0.4
        }

    return block


def generate_session_resolver_block(cascade_id: str, session_id: Optional[str], refresh_interval: float = 1.0) -> Dict[str, Any]:
    """Generate a block that resolves the current session to monitor."""

    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        # Static session ID - just echo it
        command = f'while true; do echo \'{{"session_id": "{session_id}", "cascade_id": "{cascade_id}"}}\'; sleep {refresh_interval}; done'
    else:
        # Dynamic - find latest session for this cascade
        command = f'''while true; do
lars sql query "SELECT session_id, cascade_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1" --format json 2>/dev/null || echo '[{{"session_id": "", "cascade_id": ""}}]'
sleep {refresh_interval}
done'''

    return {
        'block_id': 'session_resolver',
        'type': 'continuous',
        'visible': False,
        'command': command,
        'x': 0,
        'y': 0,
        'width': 1,
        'height': 1,
        'data_extraction': {
            'patterns': [
                {
                    'type': 'extract_string',
                    'prefix': '"session_id":"',
                    'suffix': '"',
                    'metric': 'session_id'
                }
            ]
        }
    }


def generate_polling_block(cascade_id: str, session_id: Optional[str], refresh_interval: float = 0.5) -> Dict[str, Any]:
    """Generate the continuous block that polls execution state."""

    # Determine session filter
    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        # Use subquery to get latest session for this cascade
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    # SQL query to get cell execution state (single line to avoid escaping issues)
    sql_query = f"SELECT cell_name, MAX(CASE WHEN node_type='cell_complete' OR role='cell_complete' THEN 1 ELSE 0 END) as completed, MAX(CASE WHEN node_type='cell_start' OR role='cell_start' THEN 1 ELSE 0 END) as started, round(COALESCE(SUM(cost), 0), 4) as cost, COALESCE(SUM(total_tokens), 0) as tokens FROM all_data WHERE {session_filter} GROUP BY cell_name"

    return {
        'block_id': 'execution_state',
        'type': 'continuous',
        'visible': False,
        'command': f'while true; do\nlars sql query "{sql_query}" --format json 2>/dev/null || echo \'[]\'\nsleep {refresh_interval}\ndone',
        'x': 0,
        'y': 0,
        'width': 1,
        'height': 1,
        'data_extraction': {
            'patterns': [
                {
                    'type': 'structured',
                    'format': 'json',
                    'path': '$',
                    'store_as': 'cells'
                }
            ]
        }
    }


def generate_log_block(cascade_id: str, session_id: Optional[str], x: int, y: int, width: int, height: int) -> Dict[str, Any]:
    """Generate the execution log viewer block."""

    # Determine session filter
    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    # Use substring(toString()) instead of formatDateTime to avoid % escaping issues
    sql_query = f"SELECT substring(toString(timestamp), 12, 8) as time, cell_name, role, substring(content, 1, 60) as preview FROM all_data WHERE {session_filter} AND role IN ('cell_start', 'cell_complete', 'assistant', 'tool') ORDER BY timestamp DESC LIMIT 15"

    return {
        'block_id': 'execution_log',
        'type': 'continuous',
        'command': f'while true; do\nlars sql query "{sql_query}" --format table 2>/dev/null || echo \'Waiting for data...\'\nsleep 0.5\ndone',
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'block_map': {
            'title': 'Execution Log',
            'overlay_color': '#1a1a2e',
            'darken_factor': 0.7,
            'blend_opacity': 0.4,
            'border': False,
            'padding': 1
        }
    }


def generate_metrics_block(cascade_id: str, session_id: Optional[str], x: int, y: int, width: int, height: int) -> Dict[str, Any]:
    """Generate the metrics summary panel."""

    # Determine session filter
    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    sql_query = f"SELECT round(COALESCE(SUM(cost), 0), 4) as total_cost, COALESCE(SUM(total_tokens), 0) as total_tokens, COUNT(DISTINCT cell_name) as cells_touched, COUNT(DISTINCT trace_id) as total_messages FROM all_data WHERE {session_filter}"

    return {
        'block_id': 'metrics_fetcher',
        'type': 'continuous',
        'visible': False,
        'command': f'while true; do\nlars sql query "{sql_query}" --format json 2>/dev/null || echo \'[{{}}]\'\nsleep 1\ndone',
        'x': 0,
        'y': 0,
        'width': 1,
        'height': 1,
        'data_extraction': {
            'patterns': [
                {
                    'type': 'extract_number',
                    'prefix': '"total_cost":',
                    'metric': 'total_cost'
                },
                {
                    'type': 'extract_number',
                    'prefix': '"total_tokens":',
                    'metric': 'total_tokens'
                },
                {
                    'type': 'extract_number',
                    'prefix': '"cells_touched":',
                    'metric': 'cells_touched'
                },
                {
                    'type': 'extract_number',
                    'prefix': '"total_messages":',
                    'metric': 'total_messages'
                }
            ]
        }
    }


def generate_metrics_panel(x: int, y: int, width: int, height: int) -> Dict[str, Any]:
    """Generate the visual metrics display panel."""
    return {
        'block_id': 'metrics_panel',
        'type': 'panel',
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'content': [
            "[bold cyan]Execution Metrics[/bold cyan]",
            "",
            "Total Cost:   ${{metrics_fetcher.total_cost}}",
            "Total Tokens: {{metrics_fetcher.total_tokens}}",
            "Cells:        {{metrics_fetcher.cells_touched}}",
            "Messages:     {{metrics_fetcher.total_messages}}",
        ],
        'block_map': {
            'title': 'Metrics',
            'overlay_color': '#27ae60',
            'darken_factor': 0.6,
            'blend_opacity': 0.3,
            'border': False,
            'padding': 1
        }
    }


def generate_header_block(cascade_id: str, session_id: Optional[str], x: int, y: int, width: int) -> Dict[str, Any]:
    """Generate the header panel with cascade/session info."""

    is_latest_mode = not session_id or session_id in ('latest', '{{SESSION_ID}}', '')

    if is_latest_mode:
        # Dynamic session display from session_resolver
        session_display = "{{session_resolver.session_id}}"
        mode_indicator = " [dim](auto)[/dim]"
    else:
        session_display = session_id
        mode_indicator = ""

    return {
        'block_id': 'header',
        'type': 'panel',
        'x': x,
        'y': y,
        'width': width,
        'height': 5,
        'content': [
            f"[bold magenta]LARS Cascade Monitor[/bold magenta]",
            "",
            f"Cascade: [cyan]{cascade_id}[/cyan]",
            f"Session: [yellow]{session_display}[/yellow]{mode_indicator}",
        ],
        'block_map': {
            'title': 'LARS',
            'overlay_color': '#9b59b6',
            'darken_factor': 0.5,
            'blend_opacity': 0.4,
            'border': False,
            'padding': 1
        }
    }


def generate_cost_chart_block(cascade_id: str, session_id: Optional[str], x: int, y: int, width: int, height: int) -> Dict[str, Any]:
    """Generate a cheshire bar chart showing cost by cell."""

    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    sql_query = f"SELECT cell_name, round(SUM(cost), 4) as cost FROM all_data WHERE {session_filter} AND cell_name != '' GROUP BY cell_name ORDER BY cost DESC LIMIT 8"

    return {
        'block_id': 'cost_chart',
        'type': 'continuous',
        'command': f'while true; do\nlars sql query "{sql_query}" --format json 2>/dev/null | cheshire "SELECT cell_name as x, cost as y FROM data" bar 0 --title "Cost by Cell" 2>/dev/null || echo "Waiting for data..."\nsleep 2\ndone',
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'block_map': {
            'title': 'Cost by Cell',
            'overlay_color': '#1a1a2e',
            'darken_factor': 0.7,
            'blend_opacity': 0.4,
            'border': True,
            'padding': 1
        }
    }


def generate_timeline_chart_block(cascade_id: str, session_id: Optional[str], x: int, y: int, width: int, height: int) -> Dict[str, Any]:
    """Generate a cheshire chart showing message activity over time."""

    if session_id and session_id not in ('latest', '{{SESSION_ID}}', ''):
        session_filter = f"session_id = '{session_id}'"
    else:
        session_filter = f"session_id IN (SELECT session_id FROM all_data WHERE cascade_id = '{cascade_id}' ORDER BY timestamp DESC LIMIT 1)"

    # Count messages per second
    sql_query = f"SELECT toUnixTimestamp(timestamp) as ts, count(*) as cnt FROM all_data WHERE {session_filter} GROUP BY ts ORDER BY ts"

    return {
        'block_id': 'timeline_chart',
        'type': 'continuous',
        'command': f'while true; do\nlars sql query "{sql_query}" --format json 2>/dev/null | cheshire "SELECT ts as x, cnt as y FROM data" line 0 --title "Activity" 2>/dev/null || echo "Waiting for data..."\nsleep 2\ndone',
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'block_map': {
            'title': 'Message Timeline',
            'overlay_color': '#0f3460',
            'darken_factor': 0.7,
            'blend_opacity': 0.4,
            'border': True,
            'padding': 1
        }
    }


def generate_alice_yaml(
    cascade_path: str,
    session_id: Optional[str] = None,
    background_image: Optional[str] = None,
    refresh_interval: float = 0.5
) -> str:
    """
    Generate a complete Alice dashboard YAML for monitoring a cascade execution.

    Args:
        cascade_path: Path to the cascade JSON/YAML file
        session_id: Session ID to monitor. Use None or "latest" to auto-detect latest session
        background_image: Optional background image path (None = random from tui/*.jpg)
        refresh_interval: How often to poll for updates (seconds)

    Returns:
        Alice-compatible YAML string
    """
    # Load and parse cascade
    cascade = load_cascade(cascade_path)
    cascade_id = cascade.get('cascade_id', Path(cascade_path).stem)

    # Determine if we're in "latest" mode
    is_latest_mode = not session_id or session_id in ('latest', '{{SESSION_ID}}', '')

    # Extract and layout cells
    cells = extract_cells(cascade)
    cells = compute_layout(cells)

    # Calculate layout bounds
    max_col = max((c.position.column for c in cells if c.position), default=0)
    max_row = max((c.position.row for c in cells if c.position), default=0)

    # Calculate positions for auxiliary panels
    cell_width = 38
    cell_height = 12
    h_spacing = 8
    v_spacing = 3
    start_x = 10
    start_y = 8

    # Right edge of cell grid
    grid_right = start_x + (max_col + 1) * (cell_width + h_spacing)
    # Bottom of cell grid
    grid_bottom = start_y + (max_row + 1) * (cell_height + v_spacing) + 2

    # Build blocks list
    blocks = []

    # Session resolver (for latest mode - finds current session)
    if is_latest_mode:
        blocks.append(generate_session_resolver_block(cascade_id, session_id, refresh_interval * 2))

    # Header at top
    header_width = min(120, grid_right - start_x)
    blocks.append(generate_header_block(cascade_id, session_id, start_x, 2, header_width))

    # Per-cell status blocks (hidden, for status polling)
    for cell in cells:
        blocks.append(generate_cell_status_block(cell, cascade_id, session_id))

    # Cell blocks (visible panels)
    for cell in cells:
        blocks.append(generate_cell_block(cell, session_id))

    # Polling block (hidden) - for overall execution state
    blocks.append(generate_polling_block(cascade_id, session_id, refresh_interval))

    # Metrics fetcher (hidden)
    blocks.append(generate_metrics_block(cascade_id, session_id, 0, 0, 1, 1))

    # Metrics panel (visible, to the right of cells)
    metrics_x = grid_right + 5
    blocks.append(generate_metrics_panel(metrics_x, 8, 35, 10))

    # Cheshire charts (below metrics panel)
    chart_width = 35
    chart_height = 12
    blocks.append(generate_cost_chart_block(cascade_id, session_id, metrics_x, 20, chart_width, chart_height))

    # Execution log (below cells)
    log_width = max(80, header_width)
    log_height = 15
    blocks.append(generate_log_block(cascade_id, session_id, start_x, grid_bottom, log_width, log_height))

    # Timeline chart (below log, next to cost chart)
    blocks.append(generate_timeline_chart_block(cascade_id, session_id, metrics_x, 33, chart_width, chart_height))

    # Build final structure
    dashboard = {
        'blocks': blocks
    }

    # Use provided background or pick random from tui/*.jpg
    if background_image:
        dashboard['background_image'] = background_image
    else:
        random_bg = get_random_background_image()
        if random_bg:
            dashboard['background_image'] = random_bg

    dashboard['background_darken'] = 0.6

    # Custom YAML representer for multiline strings
    def str_representer(dumper, data):
        if '\n' in data:
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        return dumper.represent_scalar('tag:yaml.org,2002:str', data)

    yaml.add_representer(str, str_representer)

    return yaml.dump(dashboard, default_flow_style=False, allow_unicode=True, sort_keys=False)


def generate_and_save(
    cascade_path: str,
    output_path: Optional[str] = None,
    session_id: str = "{{SESSION_ID}}",
    **kwargs
) -> str:
    """
    Generate Alice YAML and optionally save to file.

    Args:
        cascade_path: Path to cascade file
        output_path: Output file path (optional, prints to stdout if not provided)
        session_id: Session ID to monitor
        **kwargs: Additional arguments passed to generate_alice_yaml

    Returns:
        Path to generated file or the YAML content
    """
    yaml_content = generate_alice_yaml(cascade_path, session_id, **kwargs)

    if output_path:
        output = Path(output_path)
        output.write_text(yaml_content)
        return str(output)
    else:
        return yaml_content


# CLI interface when run directly
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python alice_generator.py <cascade_path> [session_id] [output_path]")
        sys.exit(1)

    cascade_path = sys.argv[1]
    session_id = sys.argv[2] if len(sys.argv) > 2 else "live_" + str(int(__import__('time').time()))
    output_path = sys.argv[3] if len(sys.argv) > 3 else None

    result = generate_and_save(cascade_path, output_path, session_id)

    if output_path:
        print(f"Generated: {result}")
    else:
        print(result)
