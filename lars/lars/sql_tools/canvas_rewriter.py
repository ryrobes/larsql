"""
Canvas Rewriter - Transforms CANVAS/PANEL/GRID syntax into standard SQL.

Transforms:
    WITH
      team1 AS (SELECT * FROM employees),
      metrics1 AS (SELECT * FROM metrics)
    SELECT * FROM CANVAS(
      PANEL('Team', 1, 1, team1),
      PANEL('Metrics', 2, 1, metrics1)
    ) WITH GRID(2, 1)

Into:
    WITH
      team1 AS (SELECT * FROM employees),
      metrics1 AS (SELECT * FROM metrics),
      _canvas_panel_0 AS (SELECT json_group_array(to_json(t)) as _content FROM team1 t),
      _canvas_panel_1 AS (SELECT json_group_array(to_json(t)) as _content FROM metrics1 t),
      _canvas_panels AS (
        SELECT 'Team' as name, (SELECT _content FROM _canvas_panel_0) as content, 1 as col, 1 as row, 1 as colspan, 1 as rowspan
        UNION ALL
        SELECT 'Metrics', (SELECT _content FROM _canvas_panel_1), 2, 1, 1, 1
      )
    SELECT * FROM _canvas_panels THEN RENDER_CANVAS(2, 1)
"""

import re
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class PanelDef:
    """Parsed PANEL() definition."""
    name: str
    col: int
    row: int
    cte_ref: str
    colspan: int = 1
    rowspan: int = 1


@dataclass
class CanvasDef:
    """Parsed CANVAS definition."""
    panels: List[PanelDef]
    grid_cols: int
    grid_rows: int


def has_canvas_syntax(sql: str) -> bool:
    """Check if SQL contains CANVAS(...) WITH GRID(...) syntax."""
    # Case-insensitive check for CANVAS( and GRID(
    sql_upper = sql.upper()
    return 'CANVAS(' in sql_upper and 'GRID(' in sql_upper


def rewrite_canvas_syntax(sql: str, _duckdb_conn=None) -> str:
    """
    Rewrite CANVAS/PANEL/GRID syntax to standard SQL with RENDER_CANVAS pipeline.

    Args:
        sql: SQL query potentially containing CANVAS syntax
        duckdb_conn: Optional DuckDB connection (for future use)

    Returns:
        Rewritten SQL query
    """
    if not has_canvas_syntax(sql):
        return sql

    # Parse the canvas definition
    canvas_def = _parse_canvas_syntax(sql)
    if not canvas_def:
        return sql

    # Find the SELECT * FROM CANVAS position
    canvas_match = re.search(r'(?i)SELECT\s+\*\s+FROM\s+CANVAS\s*\(', sql)
    if not canvas_match:
        return sql

    # Extract everything before SELECT * FROM CANVAS
    before_canvas = sql[:canvas_match.start()]

    # Find the WITH clause - look for WITH keyword
    with_match = re.search(r'(?i)\bWITH\b', before_canvas)
    if not with_match:
        # No WITH clause
        with_prefix = ""
        leading_part = before_canvas
    else:
        # Extract from WITH to the end of the last CTE
        # We need to find where the CTEs end (last closing paren before SELECT)
        # Work backwards from canvas_match to find the last ')'
        cte_section = before_canvas[with_match.start():]

        # Remove trailing comments and whitespace to find where CTEs actually end
        cte_section_stripped = cte_section.rstrip()

        # Remove trailing comments line by line
        lines = cte_section_stripped.split('\n')
        while lines and (lines[-1].strip().startswith('--') or lines[-1].strip() == ''):
            lines.pop()

        cte_section_clean = '\n'.join(lines)
        with_prefix = cte_section_clean + ",\n"

        # Get any leading content before WITH (like leading comments)
        leading_part = before_canvas[:with_match.start()]

    # Build the rewritten query
    rewritten = _build_rewritten_query(canvas_def, with_prefix)

    # Prepend any leading content
    return leading_part + rewritten


def _parse_canvas_syntax(sql: str) -> Optional[CanvasDef]:
    """
    Parse CANVAS(PANEL(...), ...) WITH GRID(cols, rows) syntax.

    Returns CanvasDef with parsed panels and grid dimensions.
    """
    # Find CANVAS(...) WITH GRID(...) pattern
    # This regex captures the content inside CANVAS() and GRID()
    pattern = r'''(?ix)
        SELECT\s+\*\s+FROM\s+
        CANVAS\s*\(\s*
        (.*?)                    # PANEL definitions (captured)
        \s*\)\s+
        WITH\s+GRID\s*\(\s*
        (\d+)\s*,\s*(\d+)       # Grid columns and rows
        \s*\)
    '''

    match = re.search(pattern, sql, re.DOTALL)
    if not match:
        return None

    panels_str = match.group(1)
    grid_cols = int(match.group(2))
    grid_rows = int(match.group(3))

    # Parse individual PANEL() calls
    panels = _parse_panels(panels_str)
    if not panels:
        return None

    return CanvasDef(
        panels=panels,
        grid_cols=grid_cols,
        grid_rows=grid_rows
    )


def _parse_panels(panels_str: str) -> List[PanelDef]:
    """
    Parse PANEL() definitions from the CANVAS() content.

    Handles:
        PANEL('Name', col, row, cte_ref)
        PANEL('Name', col, row, cte_ref, colspan := 2)
        PANEL('Name', col, row, cte_ref, colspan := 2, rowspan := 2)
    """
    panels = []

    # Match PANEL(...) calls - need to handle nested parens carefully
    # Simple approach: find PANEL( and then balance parens
    panel_starts = [m.start() for m in re.finditer(r'(?i)PANEL\s*\(', panels_str)]

    for start in panel_starts:
        # Find matching closing paren
        paren_count = 0
        end = start
        in_string = False
        string_char = None

        for i, char in enumerate(panels_str[start:], start):
            if not in_string:
                if char in ('"', "'"):
                    in_string = True
                    string_char = char
                elif char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
                    if paren_count == 0:
                        end = i + 1
                        break
            else:
                if char == string_char:
                    in_string = False

        panel_call = panels_str[start:end]
        panel_def = _parse_single_panel(panel_call)
        if panel_def:
            panels.append(panel_def)

    return panels


def _parse_single_panel(panel_call: str) -> Optional[PanelDef]:
    """
    Parse a single PANEL() call.

    Examples:
        PANEL('Team', 1, 1, team1)
        PANEL('Stats', 2, 1, metrics1, colspan := 2)
    """
    # Extract content inside PANEL(...)
    match = re.match(r'(?i)PANEL\s*\(\s*(.+)\s*\)$', panel_call.strip(), re.DOTALL)
    if not match:
        return None

    content = match.group(1).strip()

    # Parse arguments - handle both positional and named
    # Split by comma, but not commas inside strings
    args = _split_args(content)

    if len(args) < 4:
        return None

    # Parse positional args
    name = _unquote(args[0].strip())
    col = int(args[1].strip())
    row = int(args[2].strip())
    cte_ref = args[3].strip()

    # Parse optional named args (colspan := N, rowspan := N)
    colspan = 1
    rowspan = 1

    for arg in args[4:]:
        arg = arg.strip()
        if ':=' in arg:
            key, value = arg.split(':=', 1)
            key = key.strip().lower()
            value = int(value.strip())
            if key == 'colspan':
                colspan = value
            elif key == 'rowspan':
                rowspan = value

    return PanelDef(
        name=name,
        col=col,
        row=row,
        cte_ref=cte_ref,
        colspan=colspan,
        rowspan=rowspan
    )


def _split_args(content: str) -> List[str]:
    """Split arguments by comma, respecting strings and parens."""
    args = []
    current = []
    paren_depth = 0
    in_string = False
    string_char = None

    for char in content:
        if not in_string:
            if char in ('"', "'"):
                in_string = True
                string_char = char
                current.append(char)
            elif char == '(':
                paren_depth += 1
                current.append(char)
            elif char == ')':
                paren_depth -= 1
                current.append(char)
            elif char == ',' and paren_depth == 0:
                args.append(''.join(current))
                current = []
            else:
                current.append(char)
        else:
            current.append(char)
            if char == string_char:
                in_string = False

    if current:
        args.append(''.join(current))

    return args


def _unquote(s: str) -> str:
    """Remove surrounding quotes from a string."""
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _build_rewritten_query(canvas_def: CanvasDef, with_prefix: str) -> str:
    """
    Build the rewritten query with JSON serialization CTEs and RENDER_CANVAS pipeline.
    """
    cte_parts = []
    panel_selects = []

    for i, panel in enumerate(canvas_def.panels):
        # Create a CTE to serialize the panel's data to JSON
        # Use to_json() for each row, then json_group_array() to collect
        cte_name = f"_canvas_panel_{i}"
        cte_parts.append(
            f"  {cte_name} AS (\n"
            f"    SELECT json_group_array(to_json(t)) as _content FROM {panel.cte_ref} t\n"
            f"  )"
        )

        # Build the SELECT for the panels union
        if i == 0:
            panel_selects.append(
                f"    SELECT '{panel.name}' as name, "
                f"(SELECT _content FROM {cte_name}) as content, "
                f"{panel.col} as col, {panel.row} as row, "
                f"{panel.colspan} as colspan, {panel.rowspan} as rowspan"
            )
        else:
            panel_selects.append(
                f"    SELECT '{panel.name}', "
                f"(SELECT _content FROM {cte_name}), "
                f"{panel.col}, {panel.row}, "
                f"{panel.colspan}, {panel.rowspan}"
            )

    # Build the _canvas_panels CTE
    panels_cte = "  _canvas_panels AS (\n" + "\n    UNION ALL\n".join(panel_selects) + "\n  )"

    # Combine everything
    all_ctes = with_prefix + ",\n".join(cte_parts) + ",\n" + panels_cte

    # If the original didn't have a WITH clause, add one
    if not with_prefix:
        all_ctes = "WITH\n" + ",\n".join(cte_parts) + ",\n" + panels_cte

    # Final query
    rewritten = (
        f"{all_ctes}\n"
        f"SELECT * FROM _canvas_panels THEN RENDER_CANVAS({canvas_def.grid_cols}, {canvas_def.grid_rows})"
    )

    return rewritten
