"""
Canvas Rewriter - Transforms CANVAS/PANEL/GRID|FLOATING syntax into standard SQL.

Supports two layout modes:

GRID Layout (cell-based):
    SELECT * FROM CANVAS(
      PANEL('Team', 1, 1, team_data),
      PANEL('Wide', 2, 1, metrics, colspan := 2)
    ) WITH GRID(3, 2)

FLOATING Layout (pixel-based):
    SELECT * FROM CANVAS(
      PANEL('Chart', 50, 50, chart_data, width := 400, height := 300),
      PANEL('Info', 500, 50, info_data, width := 200, height := 150)
    ) WITH FLOATING(800, 600)

Both transform into:
    WITH
      ... (existing CTEs),
      _canvas_panel_0 AS (SELECT json_group_array(to_json(t)) as _content FROM ... t),
      _canvas_panels AS (...)
    SELECT * FROM _canvas_panels THEN RENDER_CANVAS('grid', cols, rows)
    -- or RENDER_CANVAS('floating', width, height)
"""

from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum


class LayoutType(Enum):
    GRID = "grid"
    FLOATING = "floating"


@dataclass
class PanelDef:
    """Parsed PANEL() definition."""
    name: str
    pos1: int  # col (GRID) or x (FLOATING)
    pos2: int  # row (GRID) or y (FLOATING)
    cte_ref: str
    # GRID mode
    colspan: int = 1
    rowspan: int = 1
    # FLOATING mode
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class CanvasDef:
    """Parsed CANVAS definition."""
    panels: List[PanelDef]
    layout_type: LayoutType
    # GRID: cols, rows
    # FLOATING: width, height
    dim1: int
    dim2: int


# =============================================================================
# Tokenizer - Respects strings, comments, and structure
# =============================================================================

@dataclass
class Token:
    """A token from the SQL."""
    type: str  # 'word', 'number', 'string', 'symbol', 'comment', 'whitespace'
    value: str
    start: int
    end: int


def tokenize(sql: str) -> List[Token]:
    """
    Tokenize SQL into tokens, respecting strings and comments.

    This is a simple tokenizer that handles:
    - Single and double quoted strings (with escape handling)
    - Line comments (--)
    - Block comments (/* */)
    - Words (identifiers, keywords)
    - Numbers
    - Symbols (parens, commas, operators)
    """
    tokens = []
    i = 0
    n = len(sql)

    while i < n:
        # Line comment
        if sql[i:i+2] == '--':
            start = i
            while i < n and sql[i] != '\n':
                i += 1
            tokens.append(Token('comment', sql[start:i], start, i))
            continue

        # Block comment
        if sql[i:i+2] == '/*':
            start = i
            i += 2
            while i < n - 1 and sql[i:i+2] != '*/':
                i += 1
            i += 2  # Skip */
            tokens.append(Token('comment', sql[start:i], start, i))
            continue

        # String (single or double quoted)
        if sql[i] in ('"', "'"):
            quote = sql[i]
            start = i
            i += 1
            while i < n:
                if sql[i] == quote:
                    # Check for escaped quote
                    if i + 1 < n and sql[i+1] == quote:
                        i += 2
                    else:
                        i += 1
                        break
                elif sql[i] == '\\' and i + 1 < n:
                    i += 2  # Skip escape sequence
                else:
                    i += 1
            tokens.append(Token('string', sql[start:i], start, i))
            continue

        # Whitespace
        if sql[i].isspace():
            start = i
            while i < n and sql[i].isspace():
                i += 1
            tokens.append(Token('whitespace', sql[start:i], start, i))
            continue

        # Word (identifier or keyword)
        if sql[i].isalpha() or sql[i] == '_':
            start = i
            while i < n and (sql[i].isalnum() or sql[i] == '_'):
                i += 1
            tokens.append(Token('word', sql[start:i], start, i))
            continue

        # Number
        if sql[i].isdigit():
            start = i
            while i < n and (sql[i].isdigit() or sql[i] == '.'):
                i += 1
            tokens.append(Token('number', sql[start:i], start, i))
            continue

        # := operator (special for kwargs)
        if sql[i:i+2] == ':=':
            tokens.append(Token('symbol', ':=', i, i+2))
            i += 2
            continue

        # Other symbols
        tokens.append(Token('symbol', sql[i], i, i+1))
        i += 1

    return tokens


def tokens_to_str(tokens: List[Token]) -> str:
    """Convert tokens back to string."""
    return ''.join(t.value for t in tokens)


# =============================================================================
# Parser - Uses tokens to find and parse CANVAS structure
# =============================================================================

def has_canvas_syntax(sql: str) -> bool:
    """Check if SQL contains CANVAS(...) WITH GRID|FLOATING(...) syntax."""
    sql_upper = sql.upper()
    has_canvas = 'CANVAS(' in sql_upper or 'CANVAS (' in sql_upper
    has_layout = 'GRID(' in sql_upper or 'GRID (' in sql_upper or \
                 'FLOATING(' in sql_upper or 'FLOATING (' in sql_upper
    return has_canvas and has_layout


def rewrite_canvas_syntax(sql: str, _duckdb_conn=None) -> str:
    """
    Rewrite CANVAS/PANEL/GRID|FLOATING syntax to standard SQL with RENDER_CANVAS pipeline.

    Args:
        sql: SQL query potentially containing CANVAS syntax
        _duckdb_conn: Optional DuckDB connection (unused, for API compatibility)

    Returns:
        Rewritten SQL query
    """
    if not has_canvas_syntax(sql):
        return sql

    # Tokenize
    tokens = tokenize(sql)

    # Find CANVAS structure
    canvas_info = _find_canvas_structure(tokens)
    if not canvas_info:
        return sql

    canvas_start, _canvas_end, canvas_content_tokens, layout_type, dim1, dim2 = canvas_info

    # Parse panels from the canvas content
    panels = _parse_panels_from_tokens(canvas_content_tokens)
    if not panels:
        return sql

    # Validate panels for layout type
    if layout_type == LayoutType.FLOATING:
        for panel in panels:
            if panel.width is None or panel.height is None:
                # FLOATING requires width and height
                raise ValueError(f"Panel '{panel.name}' in FLOATING layout requires width and height")

    canvas_def = CanvasDef(
        panels=panels,
        layout_type=layout_type,
        dim1=dim1,
        dim2=dim2
    )

    # Extract parts of the original query
    before_canvas = sql[:canvas_start]

    # Find WITH clause in before_canvas
    with_prefix, leading_part = _extract_with_clause(before_canvas)

    # Build rewritten query
    rewritten = _build_rewritten_query(canvas_def, with_prefix)

    return leading_part + rewritten


def _find_canvas_structure(tokens: List[Token]) -> Optional[Tuple[int, int, List[Token], LayoutType, int, int]]:
    """
    Find the CANVAS(...) WITH GRID|FLOATING(...) structure in tokens.

    Returns:
        (canvas_start, canvas_end, content_tokens, layout_type, dim1, dim2) or None
    """
    # Find SELECT * FROM CANVAS pattern
    i = 0
    n = len(tokens)

    while i < n:
        # Skip non-word tokens
        if tokens[i].type != 'word':
            i += 1
            continue

        # Look for SELECT
        if tokens[i].value.upper() != 'SELECT':
            i += 1
            continue

        select_start = tokens[i].start
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for *
        if tokens[i].type != 'symbol' or tokens[i].value != '*':
            continue
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for FROM
        if tokens[i].type != 'word' or tokens[i].value.upper() != 'FROM':
            continue
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for CANVAS
        if tokens[i].type != 'word' or tokens[i].value.upper() != 'CANVAS':
            continue
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for opening paren
        if tokens[i].type != 'symbol' or tokens[i].value != '(':
            continue

        # Found CANVAS( - now find matching close paren
        canvas_content_start = i + 1
        paren_depth = 1
        i += 1

        while i < n and paren_depth > 0:
            if tokens[i].type == 'symbol':
                if tokens[i].value == '(':
                    paren_depth += 1
                elif tokens[i].value == ')':
                    paren_depth -= 1
            i += 1

        if paren_depth != 0:
            # Unbalanced parens
            continue

        canvas_content_end = i - 1
        canvas_content_tokens = tokens[canvas_content_start:canvas_content_end]

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for WITH
        if tokens[i].type != 'word' or tokens[i].value.upper() != 'WITH':
            continue
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for GRID or FLOATING
        if tokens[i].type != 'word':
            continue

        layout_word = tokens[i].value.upper()
        if layout_word == 'GRID':
            layout_type = LayoutType.GRID
        elif layout_word == 'FLOATING':
            layout_type = LayoutType.FLOATING
        else:
            continue
        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for opening paren
        if tokens[i].type != 'symbol' or tokens[i].value != '(':
            continue
        i += 1

        # Parse dimensions (two numbers separated by comma)
        dims = []
        while i < n and len(dims) < 2:
            if tokens[i].type == 'number':
                dims.append(int(float(tokens[i].value)))
            elif tokens[i].type == 'symbol' and tokens[i].value == ')':
                break
            i += 1

        if len(dims) != 2:
            continue

        # Find closing paren
        while i < n and not (tokens[i].type == 'symbol' and tokens[i].value == ')'):
            i += 1

        if i >= n:
            break

        canvas_end = tokens[i].end

        return (select_start, canvas_end, canvas_content_tokens, layout_type, dims[0], dims[1])

    return None


def _parse_panels_from_tokens(tokens: List[Token]) -> List[PanelDef]:
    """
    Parse PANEL() calls from tokens.
    """
    panels = []
    i = 0
    n = len(tokens)

    while i < n:
        # Find PANEL word
        if tokens[i].type != 'word' or tokens[i].value.upper() != 'PANEL':
            i += 1
            continue

        i += 1

        # Skip whitespace
        while i < n and tokens[i].type in ('whitespace', 'comment'):
            i += 1

        if i >= n:
            break

        # Look for opening paren
        if tokens[i].type != 'symbol' or tokens[i].value != '(':
            continue

        # Extract content between parens
        paren_start = i + 1
        paren_depth = 1
        i += 1

        while i < n and paren_depth > 0:
            if tokens[i].type == 'symbol':
                if tokens[i].value == '(':
                    paren_depth += 1
                elif tokens[i].value == ')':
                    paren_depth -= 1
            i += 1

        if paren_depth != 0:
            continue

        paren_end = i - 1
        panel_tokens = tokens[paren_start:paren_end]

        # Parse the panel arguments
        panel_def = _parse_panel_args(panel_tokens)
        if panel_def:
            panels.append(panel_def)

    return panels


def _parse_panel_args(tokens: List[Token]) -> Optional[PanelDef]:
    """
    Parse arguments from PANEL(...) content tokens.

    Expected: name, pos1, pos2, cte_ref, [kwargs...]
    """
    # Split by comma at depth 0
    args = []
    current_arg_tokens = []
    paren_depth = 0

    for tok in tokens:
        if tok.type == 'symbol' and tok.value == ',' and paren_depth == 0:
            args.append(current_arg_tokens)
            current_arg_tokens = []
        else:
            if tok.type == 'symbol' and tok.value == '(':
                paren_depth += 1
            elif tok.type == 'symbol' and tok.value == ')':
                paren_depth -= 1
            current_arg_tokens.append(tok)

    if current_arg_tokens:
        args.append(current_arg_tokens)

    if len(args) < 4:
        return None

    # Extract positional args
    name = _extract_string_value(args[0])
    pos1 = _extract_number_value(args[1])
    pos2 = _extract_number_value(args[2])
    cte_ref = _extract_identifier_value(args[3])

    if name is None or pos1 is None or pos2 is None or cte_ref is None:
        return None

    # Parse kwargs
    colspan = 1
    rowspan = 1
    width = None
    height = None

    for arg_tokens in args[4:]:
        kwarg = _parse_kwarg(arg_tokens)
        if kwarg:
            key, value = kwarg
            key_lower = key.lower()
            if key_lower == 'colspan':
                colspan = int(value)
            elif key_lower == 'rowspan':
                rowspan = int(value)
            elif key_lower == 'width':
                width = int(value)
            elif key_lower == 'height':
                height = int(value)

    return PanelDef(
        name=name,
        pos1=pos1,
        pos2=pos2,
        cte_ref=cte_ref,
        colspan=colspan,
        rowspan=rowspan,
        width=width,
        height=height
    )


def _extract_string_value(tokens: List[Token]) -> Optional[str]:
    """Extract string value from tokens."""
    for tok in tokens:
        if tok.type == 'string':
            # Remove quotes
            s = tok.value
            if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
                return s[1:-1]
            return s
    return None


def _extract_number_value(tokens: List[Token]) -> Optional[int]:
    """Extract number value from tokens."""
    for tok in tokens:
        if tok.type == 'number':
            return int(float(tok.value))
    return None


def _extract_identifier_value(tokens: List[Token]) -> Optional[str]:
    """Extract identifier value from tokens."""
    # Could be a word or could include THEN pipeline
    parts = []
    for tok in tokens:
        if tok.type in ('word', 'number', 'symbol') and tok.value not in (',',):
            parts.append(tok.value)
        elif tok.type == 'whitespace' and parts:
            parts.append(' ')

    result = ''.join(parts).strip()
    return result if result else None


def _parse_kwarg(tokens: List[Token]) -> Optional[Tuple[str, str]]:
    """Parse a key := value kwarg from tokens."""
    key = None
    value = None
    saw_assign = False

    for tok in tokens:
        if tok.type == 'word' and key is None:
            key = tok.value
        elif tok.type == 'symbol' and tok.value == ':=':
            saw_assign = True
        elif saw_assign and tok.type == 'number':
            value = tok.value
            break

    if key and value and saw_assign:
        return (key, value)
    return None


def _extract_with_clause(before_canvas: str) -> Tuple[str, str]:
    """
    Extract WITH clause and leading content from text before CANVAS.

    Returns:
        (with_prefix, leading_part)
        - with_prefix: The WITH clause including CTEs (ends with comma for appending)
        - leading_part: Any content before the WITH clause (comments, etc.)
    """
    # Tokenize
    tokens = tokenize(before_canvas)

    # Find WITH keyword
    with_idx = None
    for i, tok in enumerate(tokens):
        if tok.type == 'word' and tok.value.upper() == 'WITH':
            with_idx = i
            break

    if with_idx is None:
        # No WITH clause
        return ("", before_canvas)

    with_start = tokens[with_idx].start

    # Get everything from WITH to end, but strip trailing whitespace/comments
    cte_section = before_canvas[with_start:]

    # Remove trailing whitespace and comments
    lines = cte_section.rstrip().split('\n')
    while lines and (lines[-1].strip().startswith('--') or lines[-1].strip() == ''):
        lines.pop()

    cte_section_clean = '\n'.join(lines)
    with_prefix = cte_section_clean + ",\n"

    # Leading content is everything before WITH
    leading_part = before_canvas[:with_start]

    return (with_prefix, leading_part)


# =============================================================================
# Query Builder
# =============================================================================

def _build_rewritten_query(canvas_def: CanvasDef, with_prefix: str) -> str:
    """
    Build the rewritten query with JSON serialization CTEs and RENDER_CANVAS pipeline.
    """
    cte_parts = []
    panel_selects = []

    is_floating = canvas_def.layout_type == LayoutType.FLOATING

    for i, panel in enumerate(canvas_def.panels):
        # Create a CTE to serialize the panel's data to JSON
        cte_name = f"_canvas_panel_{i}"
        cte_parts.append(
            f"  {cte_name} AS (\n"
            f"    SELECT json_group_array(to_json(t)) as _content FROM {panel.cte_ref} t\n"
            f"  )"
        )

        # Build the SELECT for the panels union
        if is_floating:
            # FLOATING: x, y, width, height
            if i == 0:
                panel_selects.append(
                    f"    SELECT '{panel.name}' as name, "
                    f"(SELECT _content FROM {cte_name}) as content, "
                    f"{panel.pos1} as x, {panel.pos2} as y, "
                    f"{panel.width} as width, {panel.height} as height"
                )
            else:
                panel_selects.append(
                    f"    SELECT '{panel.name}', "
                    f"(SELECT _content FROM {cte_name}), "
                    f"{panel.pos1}, {panel.pos2}, "
                    f"{panel.width}, {panel.height}"
                )
        else:
            # GRID: col, row, colspan, rowspan
            if i == 0:
                panel_selects.append(
                    f"    SELECT '{panel.name}' as name, "
                    f"(SELECT _content FROM {cte_name}) as content, "
                    f"{panel.pos1} as col, {panel.pos2} as row, "
                    f"{panel.colspan} as colspan, {panel.rowspan} as rowspan"
                )
            else:
                panel_selects.append(
                    f"    SELECT '{panel.name}', "
                    f"(SELECT _content FROM {cte_name}), "
                    f"{panel.pos1}, {panel.pos2}, "
                    f"{panel.colspan}, {panel.rowspan}"
                )

    # Build the _canvas_panels CTE
    panels_cte = "  _canvas_panels AS (\n" + "\n    UNION ALL\n".join(panel_selects) + "\n  )"

    # Combine everything
    all_ctes = with_prefix + ",\n".join(cte_parts) + ",\n" + panels_cte

    # If the original didn't have a WITH clause, add one
    if not with_prefix:
        all_ctes = "WITH\n" + ",\n".join(cte_parts) + ",\n" + panels_cte

    # Final query - pass layout type and dimensions to RENDER_CANVAS
    layout_type_str = canvas_def.layout_type.value
    rewritten = (
        f"{all_ctes}\n"
        f"SELECT * FROM _canvas_panels THEN RENDER_CANVAS('{layout_type_str}', {canvas_def.dim1}, {canvas_def.dim2})"
    )

    return rewritten
