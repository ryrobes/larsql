"""
Block Operator System for Semantic SQL.

Extends the template system to handle complex SQL patterns like:
    SEMANTIC_CASE text
        WHEN SEMANTIC 'condition' THEN 'result'
        WHEN SEMANTIC 'condition2' THEN 'result2'
        ELSE 'default'
    END

These patterns have:
- Start/end keywords (block structure)
- Repeating elements (WHEN...THEN pairs)
- Optional elements (ELSE)

The block operator is defined in cascade YAML:

    sql_function:
      name: semantic_case
      returns: VARCHAR
      block_operator:
        start: SEMANTIC_CASE
        end: END
        structure:
          - capture: text
            as: expression
          - repeat:
              min: 1
              pattern:
                - keyword: WHEN SEMANTIC
                - capture: condition
                  as: string
                - keyword: THEN
                - capture: result
                  as: string
          - optional:
              pattern:
                - keyword: ELSE
                - capture: default
                  as: string

The rewriter converts this to a function call with JSON arrays for repeated captures:
    semantic_case(text, '["c1","c2"]', '["r1","r2"]', 'default')

The cascade receives inputs:
    - text: the expression
    - conditions: JSON array of conditions
    - results: JSON array of results
    - default: optional default value
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class BlockOperatorSpec:
    """Specification for a block operator loaded from cascade YAML."""
    name: str                          # Function name
    cascade_path: str                  # Path to cascade file
    start_keyword: str                 # e.g., "SEMANTIC_CASE"
    end_keyword: str                   # e.g., "END"
    structure: List[Dict[str, Any]]    # Structure definition
    returns: str = "VARCHAR"           # Return type

    def __post_init__(self):
        # Normalize keywords to uppercase
        self.start_keyword = self.start_keyword.upper()
        self.end_keyword = self.end_keyword.upper()


@dataclass
class BlockMatch:
    """Result of matching a block operator in SQL."""
    start_pos: int                     # Token position where match starts
    end_pos: int                       # Token position where match ends
    spec: BlockOperatorSpec            # The spec that matched
    captures: Dict[str, Any]           # Captured values (scalars or arrays)
    original_sql: str                  # The original SQL text that was matched


# Global cache for block specs
_block_specs: Optional[List[BlockOperatorSpec]] = None
_block_specs_lock = None


def load_block_operator_specs(force: bool = False) -> List[BlockOperatorSpec]:
    """
    Load all block operator specs from the cascade registry.

    Scans for cascades with sql_function.block_operator config.
    """
    global _block_specs

    if _block_specs is not None and not force:
        return _block_specs

    from rvbbit.semantic_sql.registry import get_sql_function_registry

    specs = []
    registry = get_sql_function_registry()

    for fn_name, entry in registry.items():
        block_config = entry.sql_function.get('block_operator')
        if not block_config:
            continue

        try:
            spec = BlockOperatorSpec(
                name=fn_name,
                cascade_path=entry.cascade_path,
                start_keyword=block_config.get('start', ''),
                end_keyword=block_config.get('end', 'END'),
                structure=block_config.get('structure', []),
                returns=entry.returns,
            )
            specs.append(spec)
            log.debug(f"Loaded block operator: {fn_name} ({spec.start_keyword}...{spec.end_keyword})")
        except Exception as e:
            log.warning(f"Failed to load block operator {fn_name}: {e}")

    _block_specs = specs
    log.info(f"Loaded {len(specs)} block operator specs")
    return specs


def has_block_operators(sql: str) -> bool:
    """Quick check if SQL might contain any block operators."""
    global _block_specs

    # Always try to load if we have no specs
    if _block_specs is None or len(_block_specs) == 0:
        _block_specs = None  # Reset cache
        specs = load_block_operator_specs(force=True)
    else:
        specs = _block_specs

    sql_upper = sql.upper()
    result = any(spec.start_keyword in sql_upper for spec in specs)

    if result:
        log.debug(f"Block operator detected in query: {sql[:50]}...")

    return result


def rewrite_block_operators(sql: str, tokens: List[Any] = None) -> Tuple[str, bool]:
    """
    Rewrite block operators in SQL to function calls.

    Args:
        sql: The SQL query
        tokens: Optional pre-tokenized tokens (from v2 rewriter)

    Returns:
        Tuple of (rewritten_sql, was_changed)
    """
    specs = load_block_operator_specs()
    if not specs:
        log.debug("No block operator specs loaded")
        return sql, False

    # Tokenize if not provided
    if tokens is None:
        from .semantic_rewriter_v2 import _tokenize
        try:
            tokens = _tokenize(sql)
            log.debug(f"Tokenized {len(tokens)} tokens for block operator matching")
        except Exception as e:
            log.warning(f"Failed to tokenize for block operators: {e}")
            return sql, False

    changed = False
    result = sql

    # Try each spec
    for spec in specs:
        log.debug(f"Trying block spec: {spec.start_keyword}...{spec.end_keyword}")
        match = _find_block_match(result, tokens, spec)
        while match:
            # Generate replacement
            replacement = _generate_function_call(match)
            log.info(f"Rewriting block operator: {spec.name}() from {match.original_sql[:50]}...")

            # Replace in SQL
            result = result[:match.start_pos] + replacement + result[match.end_pos:]
            changed = True

            # Re-tokenize for next iteration
            try:
                from .semantic_rewriter_v2 import _tokenize
                tokens = _tokenize(result)
            except Exception:
                break

            # Look for more matches
            match = _find_block_match(result, tokens, spec)

    return result, changed


def _find_block_match(sql: str, tokens: List[Any], spec: BlockOperatorSpec) -> Optional[BlockMatch]:
    """
    Find a block operator match in the tokenized SQL.

    Uses token-aware matching to avoid matching inside strings.
    """
    # Find start keyword
    start_idx = None
    for i, tok in enumerate(tokens):
        if tok.typ in ('string', 'comment_line', 'comment_block'):
            continue
        # Check for start keyword - must be exact uppercase match (avoid matching function call)
        if tok.text.upper() == spec.start_keyword and tok.text.isupper():
            start_idx = i
            log.debug(f"Found block start keyword at token {i}: {tok.text}")
            break

    if start_idx is None:
        return None

    # Find matching END
    end_idx = None
    depth = 1  # Handle nested blocks if needed
    for i in range(start_idx + 1, len(tokens)):
        tok = tokens[i]
        if tok.typ in ('string', 'comment_line', 'comment_block'):
            continue
        if tok.text.upper() == spec.start_keyword:
            depth += 1
        elif tok.text.upper() == spec.end_keyword:
            depth -= 1
            if depth == 0:
                end_idx = i
                log.debug(f"Found block end keyword at token {i}: {tok.text}")
                break

    if end_idx is None:
        log.debug(f"END keyword '{spec.end_keyword}' not found for block starting with '{spec.start_keyword}'")
        return None

    # Calculate character positions
    char_start = sum(len(tokens[j].text) for j in range(start_idx))
    char_end = sum(len(tokens[j].text) for j in range(end_idx + 1))

    # Extract the block content (between start and end keywords)
    block_tokens = tokens[start_idx:end_idx + 1]
    block_sql = ''.join(t.text for t in block_tokens)

    # Parse the structure
    captures = _parse_block_structure(block_tokens, spec)
    if captures is None:
        log.debug(f"Structure parsing failed for block: {block_sql[:50]}...")
        return None

    return BlockMatch(
        start_pos=char_start,
        end_pos=char_end,
        spec=spec,
        captures=captures,
        original_sql=block_sql,
    )


def _parse_block_structure(tokens: List[Any], spec: BlockOperatorSpec) -> Optional[Dict[str, Any]]:
    """
    Parse the block content according to the structure definition.

    Returns captured values or None if structure doesn't match.
    """
    captures = {}
    i = 1  # Skip start keyword

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == 'ws':
        i += 1

    for element in spec.structure:
        if i >= len(tokens):
            break

        if 'keyword' in element and isinstance(element['keyword'], str):
            # Match keyword(s) at top level
            keywords = element['keyword'].upper().split()
            for kw in keywords:
                # Skip whitespace
                while i < len(tokens) and tokens[i].typ == 'ws':
                    i += 1
                if i >= len(tokens):
                    return None
                tok = tokens[i]
                if tok.typ != 'ident' or tok.text.upper() != kw:
                    return None  # Keyword not found
                i += 1

        elif 'capture' in element:
            # Capture an expression or string
            capture_name = element['capture']
            capture_type = element.get('as', 'expression')

            value, i = _capture_value(tokens, i, capture_type)
            if value is not None:
                captures[capture_name] = value

        elif 'repeat' in element:
            # Capture repeated pattern
            repeat_config = element['repeat']
            min_count = repeat_config.get('min', 1)
            pattern = repeat_config.get('pattern', [])

            # Collect all matches
            all_captures = {p['capture']: [] for p in pattern if 'capture' in p}
            count = 0

            while i < len(tokens):
                # Skip whitespace
                while i < len(tokens) and tokens[i].typ == 'ws':
                    i += 1

                # Try to match the pattern
                match_result, new_i = _match_pattern(tokens, i, pattern, spec.end_keyword)
                if match_result is None:
                    break

                # Add captured values to arrays
                for key, value in match_result.items():
                    all_captures[key].append(value)

                i = new_i
                count += 1

            if count < min_count:
                return None  # Not enough matches

            # Flatten single-value arrays to plural names
            for key, values in all_captures.items():
                # Use plural name for arrays
                plural_key = key + 's' if not key.endswith('s') else key + '_list'
                captures[plural_key] = values

        elif 'optional' in element:
            # Optional pattern
            optional_config = element['optional']
            pattern = optional_config.get('pattern', [])

            # Skip whitespace
            while i < len(tokens) and tokens[i].typ == 'ws':
                i += 1

            # Try to match
            match_result, new_i = _match_pattern(tokens, i, pattern, spec.end_keyword)
            if match_result is not None:
                captures.update(match_result)
                i = new_i

    return captures


def _capture_value(tokens: List[Any], start: int, capture_type: str) -> Tuple[Optional[str], int]:
    """
    Capture a value starting at the given token position.

    Returns (value, new_position) or (None, start) if no match.
    """
    i = start

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == 'ws':
        i += 1

    if i >= len(tokens):
        return None, start

    tok = tokens[i]

    if capture_type == 'string':
        # Expect a string literal
        if tok.typ == 'string':
            # Remove quotes
            value = tok.text[1:-1]
            return value, i + 1
        return None, start

    elif capture_type == 'expression':
        # Capture an identifier or simple expression
        if tok.typ == 'ident':
            return tok.text, i + 1
        return None, start

    return None, start


def _match_pattern(tokens: List[Any], start: int, pattern: List[Dict], end_keyword: str) -> Tuple[Optional[Dict[str, Any]], int]:
    """
    Match a pattern sequence starting at the given token position.

    Returns (captures, new_position) or (None, start) if no match.
    """
    i = start
    captures = {}

    for element in pattern:
        # Skip whitespace
        while i < len(tokens) and tokens[i].typ == 'ws':
            i += 1

        if i >= len(tokens):
            return None, start

        # Check if we've hit the end keyword
        if tokens[i].typ == 'ident' and tokens[i].text.upper() == end_keyword:
            return None, start

        if 'keyword' in element and isinstance(element['keyword'], str):
            # Match keyword(s)
            keywords = element['keyword'].upper().split()
            for kw in keywords:
                # Skip whitespace
                while i < len(tokens) and tokens[i].typ == 'ws':
                    i += 1

                if i >= len(tokens):
                    return None, start

                tok = tokens[i]
                if tok.typ != 'ident' or tok.text.upper() != kw:
                    return None, start
                i += 1

        elif 'capture' in element:
            # Capture a value
            capture_name = element['capture']
            capture_type = element.get('as', 'expression')

            value, new_i = _capture_value(tokens, i, capture_type)
            if value is None:
                return None, start

            captures[capture_name] = value
            i = new_i

    return captures, i


def _generate_function_call(match: BlockMatch) -> str:
    """
    Generate a function call from a block match.

    Converts captured arrays to JSON for the function arguments.
    """
    spec = match.spec
    captures = match.captures

    # Build argument list based on captures
    args = []

    # The structure defines the order of captures
    for element in spec.structure:
        if 'capture' in element:
            name = element['capture']
            if name in captures:
                value = captures[name]
                # Quote if it's a simple value that looks like an identifier
                if isinstance(value, str) and not value.startswith("'"):
                    args.append(value)  # Expression - don't quote
                else:
                    args.append(f"'{value}'")

        elif 'repeat' in element:
            pattern = element['repeat'].get('pattern', [])
            for p in pattern:
                if 'capture' in p:
                    name = p['capture']
                    plural = name + 's' if not name.endswith('s') else name + '_list'
                    if plural in captures:
                        # JSON encode the array
                        args.append(f"'{json.dumps(captures[plural])}'")

        elif 'optional' in element:
            pattern = element['optional'].get('pattern', [])
            for p in pattern:
                if 'capture' in p:
                    name = p['capture']
                    if name in captures:
                        args.append(f"'{captures[name]}'")
                    else:
                        args.append("NULL")  # Optional not present

    # Generate function call
    return f"{spec.name}({', '.join(args)})"


# Clear cache when registry is reloaded
def clear_block_specs_cache():
    """Clear the cached block specs."""
    global _block_specs
    _block_specs = None
