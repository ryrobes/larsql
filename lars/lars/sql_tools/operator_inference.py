"""
Operator Pattern Inference System.

Automatically converts cascade operator templates into structured pattern matching specs.

Key Innovation: Instead of hardcoding operator patterns in Python, we INFER them from
the template syntax that cascades already declare in their `operators` field.

Template Syntax:
    {{ name }}      - Capture a value (expression or string based on context)
    '{{ name }}'    - Capture a string (quoted)
    Literal text    - Keyword to match

Examples:
    "{{ text }} MEANS {{ criterion }}"
    → Infix binary: capture text, match "MEANS", capture criterion (string)

    "{{ text }} ALIGNS WITH {{ narrative }}"
    → Infix binary with multi-word keyword

    "SUMMARIZE({{ col }}, '{{ prompt }}')"
    → Function call: first arg is expression, second is string

    "{{ a }} ~ {{ b }}"
    → Infix symbol operator

This module handles 99% of operators. The 1% that need complex patterns
(SEMANTIC_CASE...END with repeating WHEN...THEN) use explicit block_operator config.
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

log = logging.getLogger(__name__)


# ============================================================================
# Template Parsing Data Structures
# ============================================================================

@dataclass
class TemplatePart:
    """A piece of a template pattern."""
    text: str                  # The actual text
    is_capture: bool           # True if this is {{ name }}
    is_quoted: bool = False    # True if capture is quoted '{{ name }}'
    name: Optional[str] = None # Variable name (for captures)


# ============================================================================
# Template Parser
# ============================================================================

# Pattern to match {{ variable_name }} with optional surrounding quotes
CAPTURE_PATTERN = re.compile(r"('?)\{\{\s*(\w+)\s*\}\}('?)")


def parse_operator_template(template: str) -> List[TemplatePart]:
    """
    Parse an operator template into structured parts.

    Converts template syntax into a list of captures and keywords.

    Args:
        template: Template string like "{{ text }} MEANS {{ criterion }}"

    Returns:
        List of TemplatePart objects

    Examples:
        >>> parse_operator_template("{{ text }} MEANS '{{ criterion }}'")
        [
            TemplatePart(text="{{ text }}", is_capture=True, name="text"),
            TemplatePart(text=" MEANS ", is_capture=False),
            TemplatePart(text="'{{ criterion }}'", is_capture=True, is_quoted=True, name="criterion"),
        ]
    """
    parts = []
    pos = 0

    for match in CAPTURE_PATTERN.finditer(template):
        # Add any literal text before this capture
        if match.start() > pos:
            literal_text = template[pos:match.start()]
            if literal_text:  # Skip empty strings
                parts.append(TemplatePart(
                    text=literal_text,
                    is_capture=False
                ))

        # Add the capture
        before_quote = match.group(1)
        var_name = match.group(2)
        after_quote = match.group(3)

        is_quoted = bool(before_quote and after_quote)

        parts.append(TemplatePart(
            text=match.group(0),
            is_capture=True,
            is_quoted=is_quoted,
            name=var_name
        ))

        pos = match.end()

    # Add any remaining literal text
    if pos < len(template):
        literal_text = template[pos:]
        if literal_text:
            parts.append(TemplatePart(
                text=literal_text,
                is_capture=False
            ))

    return parts


def infer_block_operator(template: str, func_name: str) -> Dict[str, Any]:
    """
    Infer a BlockOperatorSpec-compatible dict from a template pattern.

    Converts cascade operator templates into structured pattern specs that
    the block_operators.py system can use for matching and rewriting.

    Args:
        template: Operator template like "{{ text }} MEANS {{ criterion }}"
        func_name: SQL function name to call (e.g., "semantic_means")

    Returns:
        Dict with keys matching BlockOperatorSpec fields:
        - name: Function name
        - inline: True for infix/inline patterns, False for function calls
        - structure: List of capture/keyword elements
        - output_template: Jinja2 template for generating function call
        - start_keyword: None for inline patterns
        - end_keyword: None for inline patterns

    Examples:
        >>> infer_block_operator("{{ text }} MEANS {{ criterion }}", "semantic_means")
        {
            'name': 'semantic_means',
            'inline': True,
            'structure': [
                {'capture': 'text', 'as': 'expression'},
                {'keyword': 'MEANS'},
                {'capture': 'criterion', 'as': 'string'},
            ],
            'output_template': 'semantic_means({{ text }}, {{ criterion }})',
            'start_keyword': None,
            'end_keyword': None,
        }
    """
    parts = parse_operator_template(template)

    if not parts:
        raise ValueError(f"Empty template: {template}")

    # Determine if this is a function-style pattern
    # Function patterns start with identifier followed by (
    is_function = False
    first_non_ws = template.lstrip()
    if re.match(r'^\w+\s*\(', first_non_ws):
        is_function = True

    # Build structure list
    structure = []
    captures = []  # Track capture names for output template

    for part in parts:
        if part.is_capture:
            # Determine capture type
            capture_type = "string" if part.is_quoted else "expression"

            structure.append({
                "capture": part.name,
                "as": capture_type
            })
            captures.append(part.name)
        else:
            # Literal text = keyword
            keyword_text = part.text.strip()
            if keyword_text:  # Skip pure whitespace
                # Multi-word keywords stay as single element
                structure.append({
                    "keyword": keyword_text
                })

    # Build output template
    # Format: function_name({{ capture1 }}, {{ capture2 }}, ...)
    args = ", ".join(f"{{{{ {c} }}}}" for c in captures)
    output_template = f"{func_name}({args})"

    spec = {
        'name': func_name,
        'inline': not is_function,  # Infix operators are inline
        'structure': structure,
        'output_template': output_template,
        'start_keyword': None,      # Inline patterns don't have block start/end
        'end_keyword': None,
        'returns': 'VARCHAR',       # Default, can be overridden by cascade
    }

    log.debug(f"Inferred operator spec from template '{template}': inline={spec['inline']}, {len(structure)} elements")

    return spec


def infer_operators_from_cascade(cascade_path: str, sql_function_entry) -> List[Dict[str, Any]]:
    """
    Generate all inferred operator specs from a cascade's operators field.

    A single cascade can have multiple operator syntax variations:
        operators:
          - "{{ text }} MEANS {{ criterion }}"      # Infix
          - "{{ text }} ~ {{ criterion }}"          # Symbol infix
          - "MEANS({{ text }}, {{ criterion }})"    # Function call

    Each template generates a separate spec, all calling the same function.

    Args:
        cascade_path: Path to cascade file (for error messages)
        sql_function_entry: SQLFunctionEntry from registry

    Returns:
        List of inferred operator spec dicts
    """
    specs = []
    func_name = sql_function_entry.name

    for template in sql_function_entry.operators:
        try:
            spec = infer_block_operator(template, func_name)

            # Override return type from cascade config
            spec['returns'] = sql_function_entry.returns
            spec['cascade_path'] = cascade_path

            specs.append(spec)

        except Exception as e:
            log.warning(f"Failed to infer operator from template '{template}' in {cascade_path}: {e}")

    return specs


# ============================================================================
# Pattern Analysis Utilities
# ============================================================================

def get_operator_priority(spec: Dict[str, Any]) -> int:
    """
    Determine rewrite priority for an operator spec.

    Order of operations (highest to lowest priority):
    1. Block structures (SEMANTIC_CASE...END) - Must be processed first
    2. Dimension patterns (GROUP BY topics(...)) - Context-sensitive
    3. Multi-word infix (ALIGNS WITH) - Longer keywords first
    4. Single-word infix (MEANS)
    5. Symbol infix (~)
    6. Function calls (SUMMARIZE(...))

    This ensures we match the most specific patterns first and don't
    accidentally match substrings of longer keywords.

    Args:
        spec: Operator spec dict

    Returns:
        Integer priority (higher = process first)
    """
    # Block operators have explicit start/end keywords
    if spec.get('start_keyword'):
        return 100

    # Dimension operators are context-sensitive (GROUP BY only)
    # These will be handled by dimension_rewriter.py separately
    # So we can give them low priority here
    if spec.get('shape') == 'DIMENSION':
        return 90

    # Inline operators: prioritize by keyword length
    if spec.get('inline'):
        # Find keywords in structure
        keywords = [
            elem.get('keyword', '')
            for elem in spec.get('structure', [])
            if 'keyword' in elem
        ]

        if keywords:
            # Longest keyword first (multi-word beats single-word)
            max_length = max(len(kw.split()) for kw in keywords)
            return 50 + max_length

    # Function calls have lowest priority
    return 10


def classify_operator_type(spec: Dict[str, Any]) -> str:
    """
    Classify an operator spec by type.

    Returns:
        One of: "block", "dimension", "infix", "function"
    """
    if spec.get('start_keyword'):
        return "block"

    if spec.get('shape') == 'DIMENSION':
        return "dimension"

    if spec.get('inline'):
        return "infix"

    return "function"


# ============================================================================
# Validation
# ============================================================================

def validate_inferred_spec(spec: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate that an inferred spec is well-formed.

    Args:
        spec: Inferred operator spec dict

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Must have name
    if not spec.get('name'):
        return False, "Missing 'name' field"

    # Must have structure
    structure = spec.get('structure')
    if not structure or not isinstance(structure, list):
        return False, "Missing or invalid 'structure' field"

    # Must have at least one capture
    captures = [elem for elem in structure if 'capture' in elem]
    if not captures:
        return False, "No captures defined in structure"

    # Must have output template
    if not spec.get('output_template'):
        return False, "Missing 'output_template' field"

    # Inline field must be boolean
    if 'inline' not in spec:
        return False, "Missing 'inline' field"

    return True, None


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Example 1: Infix binary operator
    spec1 = infer_block_operator("{{ text }} MEANS {{ criterion }}", "semantic_means")
    print("Infix operator:", spec1)

    # Example 2: Multi-word infix
    spec2 = infer_block_operator("{{ text }} ALIGNS WITH {{ narrative }}", "semantic_aligns")
    print("\nMulti-word infix:", spec2)

    # Example 3: Function call
    spec3 = infer_block_operator("SUMMARIZE({{ col }}, '{{ prompt }}')", "llm_summarize")
    print("\nFunction call:", spec3)

    # Example 4: Symbol operator
    spec4 = infer_block_operator("{{ a }} ~ {{ b }}", "semantic_means")
    print("\nSymbol operator:", spec4)
