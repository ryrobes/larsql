"""
Semantic SQL Operators.

Transforms semantic SQL syntax into UDF calls:

    col MEANS 'x'           → matches('x', col)
    col ABOUT 'x'           → score('x', col) > 0.5
    col ABOUT 'x' > 0.7     → score('x', col) > 0.7
    a ~ b                   → match_pair(a, b, 'same entity')
    a ~ b AS 'relationship' → match_pair(a, b, 'relationship')
    ORDER BY col RELEVANCE TO 'x'  → ORDER BY score('x', col) DESC
    SEMANTIC JOIN t ON a ~ b       → CROSS JOIN t WHERE match_pair(a, b, ...)

Supports annotation hints (-- @) for model selection and prompt customization:

    -- @ use a fast and cheap model
    WHERE description MEANS 'sustainable'

    Becomes:
    WHERE matches('use a fast and cheap model - sustainable', description)

The annotation prompt is prepended to the criteria, allowing bodybuilder's
request mode to pick up model hints naturally.
"""

import re
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass


# ============================================================================
# Annotation Parsing (shared with llm_agg_rewriter)
# ============================================================================

@dataclass
class SemanticAnnotation:
    """Parsed annotation for a semantic operator."""
    prompt: Optional[str] = None          # Custom prompt/instructions/model hints
    model: Optional[str] = None           # Explicit model override
    threshold: Optional[float] = None     # Score threshold for ABOUT
    start_pos: int = 0                    # Start position in query
    end_pos: int = 0                      # End position in query
    line_start: int = 0                   # Line number where annotation starts
    line_end: int = 0                     # Line number where annotation ends


def _parse_annotations(query: str) -> List[Tuple[int, int, SemanticAnnotation]]:
    """
    Parse all -- @ annotations from query.

    Returns list of (end_line, end_pos, annotation) tuples.

    Supports:
        -- @ Free-form prompt text (model hints like "use a fast model")
        -- @ More prompt text (consecutive lines merge)
        -- @ model: anthropic/claude-haiku
        -- @ threshold: 0.7
    """
    annotations = []
    lines = query.split('\n')

    current_annotation = None
    current_pos = 0
    prompt_lines = []

    for line_num, line in enumerate(lines):
        line_start = current_pos
        line_end = current_pos + len(line)

        stripped = line.strip()
        if stripped.startswith('-- @'):
            content = stripped[4:].strip()

            if current_annotation is None:
                current_annotation = SemanticAnnotation(
                    start_pos=line_start,
                    line_start=line_num
                )
                prompt_lines = []

            # Check for key: value pattern
            if ':' in content and not content.startswith('http'):
                key, _, value = content.partition(':')
                key = key.strip().lower()
                value = value.strip()

                if key == 'model':
                    current_annotation.model = value
                elif key == 'threshold':
                    try:
                        current_annotation.threshold = float(value)
                    except ValueError:
                        pass
                elif key == 'prompt':
                    prompt_lines.append(value)
                else:
                    # Unknown key or natural language with colon
                    prompt_lines.append(content)
            else:
                # No colon (or URL), it's prompt text
                prompt_lines.append(content)

            current_annotation.end_pos = line_end
            current_annotation.line_end = line_num

        else:
            # Not an annotation line
            if current_annotation is not None:
                if prompt_lines:
                    current_annotation.prompt = ' '.join(prompt_lines)
                annotations.append((line_num, current_annotation.end_pos, current_annotation))
                current_annotation = None
                prompt_lines = []

        current_pos = line_end + 1  # +1 for newline

    # Handle annotation at end of query
    if current_annotation is not None:
        if prompt_lines:
            current_annotation.prompt = ' '.join(prompt_lines)
        annotations.append((len(lines), current_annotation.end_pos, current_annotation))

    return annotations


def _find_annotation_for_line(
    annotations: List[Tuple[int, int, SemanticAnnotation]],
    target_line: int
) -> Optional[SemanticAnnotation]:
    """
    Find annotation that applies to a given line.

    An annotation applies if it ends on the line immediately before the target.
    """
    for end_line, end_pos, annotation in annotations:
        # Annotation applies if it ends right before target line
        if end_line == target_line:
            return annotation
    return None


# ============================================================================
# Semantic Operator Detection
# ============================================================================

def has_semantic_operators(query: str) -> bool:
    """Check if query contains any semantic SQL operators."""
    query_upper = query.upper()

    # Check for semantic operators
    patterns = [
        r'\bMEANS\s+\'',           # col MEANS 'x'
        r'\bABOUT\s+\'',           # col ABOUT 'x'
        r'\w+\s*~\s*\w+',          # a ~ b (tilde operator)
        r'\bSEMANTIC\s+JOIN\b',    # SEMANTIC JOIN
        r'\bRELEVANCE\s+TO\s+\'',  # ORDER BY col RELEVANCE TO 'x'
        r'\bSEMANTIC\s+DISTINCT\b', # SEMANTIC DISTINCT
    ]

    for pattern in patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return True

    return False


# ============================================================================
# Rewriting Functions
# ============================================================================

def rewrite_semantic_operators(query: str) -> str:
    """
    Rewrite semantic SQL operators to UDF calls.

    Preserves annotations by injecting prompt text into the criteria string,
    allowing bodybuilder to pick up model hints.

    IMPORTANT: Only removes annotations that are actually used for semantic operators.
    Annotations before LLM aggregate functions (SUMMARIZE, THEMES, etc.) are preserved
    for the LLM aggregate rewriter to consume.

    Args:
        query: SQL query with semantic operators

    Returns:
        Rewritten SQL with UDF calls
    """
    if not has_semantic_operators(query):
        return query

    # Parse annotations first (we need line numbers)
    annotations = _parse_annotations(query)

    # Track which annotations were used (by line range)
    used_annotation_lines = set()

    # Split into lines for line-by-line processing
    lines = query.split('\n')
    result_lines = []

    for line_num, line in enumerate(lines):
        stripped = line.strip()

        # Check if this line is a pure annotation line
        if stripped.startswith('-- @'):
            # Check if the NEXT non-annotation line has a semantic operator
            # If so, we'll consume this annotation; otherwise preserve it
            next_code_line_num = _find_next_code_line(lines, line_num + 1)
            if next_code_line_num is not None:
                next_line = lines[next_code_line_num]
                if _has_semantic_operator_in_line(next_line):
                    # This annotation will be consumed by semantic operator rewrite
                    used_annotation_lines.add(line_num)
                    continue  # Skip this annotation line

            # Preserve annotation for other rewriters (LLM aggregates, etc.)
            result_lines.append(line)
            continue

        # Find annotation for this line (only if it has semantic operators)
        annotation = None
        if _has_semantic_operator_in_line(line):
            annotation = _find_annotation_for_line(annotations, line_num)

        # Apply rewrites to this line
        rewritten_line = _rewrite_line(line, annotation)
        result_lines.append(rewritten_line)

    result = '\n'.join(result_lines)

    # Post-processing: Fix double WHERE clauses that can occur with multi-line
    # SEMANTIC JOIN followed by WHERE on a separate line
    result = _fix_double_where(result)

    return result


def _find_next_code_line(lines: list, start: int) -> Optional[int]:
    """Find the next non-annotation, non-empty line number."""
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith('-- @') and not stripped.startswith('--'):
            return i
    return None


def _has_semantic_operator_in_line(line: str) -> bool:
    """Check if a line contains any semantic operator."""
    patterns = [
        r'\bMEANS\s+\'',           # col MEANS 'x'
        r'\bABOUT\s+\'',           # col ABOUT 'x'
        r'\w+\s*~\s*\w+',          # a ~ b (but not in comments)
        r'\bSEMANTIC\s+JOIN\b',    # SEMANTIC JOIN
        r'\bRELEVANCE\s+TO\s+\'',  # RELEVANCE TO 'x'
    ]

    # Ignore if line is a comment
    if line.strip().startswith('--'):
        return False

    for pattern in patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _fix_double_where(query: str) -> str:
    """
    Fix double WHERE clauses in a query.

    When SEMANTIC JOIN is on one line and WHERE is on a subsequent line,
    we end up with two WHERE keywords. This function merges them with AND.

    Example:
        CROSS JOIN t WHERE match_pair(...)
        WHERE price > 100

    Becomes:
        CROSS JOIN t WHERE match_pair(...)
        AND price > 100
    """
    # Count WHERE occurrences
    where_count = len(re.findall(r'\bWHERE\b', query, re.IGNORECASE))

    if where_count <= 1:
        return query

    # Find all WHERE positions
    where_positions = [(m.start(), m.end()) for m in re.finditer(r'\bWHERE\b', query, re.IGNORECASE)]

    if len(where_positions) < 2:
        return query

    # Replace all but the first WHERE with AND
    # Work backwards to preserve positions
    result = query
    for start, end in reversed(where_positions[1:]):
        result = result[:start] + 'AND' + result[end:]

    return result


def _rewrite_line(line: str, annotation: Optional[SemanticAnnotation]) -> str:
    """Rewrite semantic operators in a single line."""
    result = line

    # Build annotation prefix for criteria injection
    annotation_prefix = ""
    if annotation and annotation.prompt:
        annotation_prefix = annotation.prompt + " - "
    elif annotation and annotation.model:
        annotation_prefix = f"Use {annotation.model} - "

    # Get threshold from annotation or use default
    default_threshold = 0.5
    if annotation and annotation.threshold is not None:
        default_threshold = annotation.threshold

    # ORDER MATTERS: Process compound operators before simple ones

    # 1. Rewrite: SEMANTIC JOIN (must be before ~ so we can match the full pattern)
    result = _rewrite_semantic_join(result, annotation_prefix)

    # 2. Rewrite: ORDER BY col RELEVANCE TO 'query'  →  ORDER BY score('query', col) DESC
    result = _rewrite_relevance_to(result, annotation_prefix)

    # 3. Rewrite: col MEANS 'criteria'  →  matches('criteria', col)
    result = _rewrite_means(result, annotation_prefix)

    # 4. Rewrite: col ABOUT 'criteria' [> threshold]  →  score('criteria', col) > threshold
    result = _rewrite_about(result, annotation_prefix, default_threshold)

    # 5. Rewrite: a ~ b [AS 'relationship']  →  match_pair(a, b, 'relationship')
    # Must be LAST since other patterns may contain ~
    result = _rewrite_tilde(result, annotation_prefix)

    return result


def _rewrite_means(line: str, annotation_prefix: str) -> str:
    """
    Rewrite MEANS operator.

    col MEANS 'sustainable'  →  matches('sustainable', col)

    With annotation:
    -- @ use a fast model
    col MEANS 'sustainable'  →  matches('use a fast model - sustainable', col)
    """
    # Pattern: identifier MEANS 'string'
    # Captures: (column_expr) MEANS '(criteria)'
    pattern = r'(\w+(?:\.\w+)?)\s+MEANS\s+\'([^\']+)\''

    def replacer(match):
        col = match.group(1)
        criteria = match.group(2)
        # Inject annotation prefix into criteria
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        return f"matches('{full_criteria}', {col})"

    return re.sub(pattern, replacer, line, flags=re.IGNORECASE)


def _rewrite_about(line: str, annotation_prefix: str, default_threshold: float) -> str:
    """
    Rewrite ABOUT operator.

    col ABOUT 'topic'         →  score('topic', col) > 0.5
    col ABOUT 'topic' > 0.7   →  score('topic', col) > 0.7

    With annotation:
    -- @ threshold: 0.8
    col ABOUT 'topic'  →  score('topic', col) > 0.8
    """
    # Pattern with explicit threshold: col ABOUT 'x' > 0.7
    pattern_with_threshold = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'\s*(>|>=|<|<=)\s*([\d.]+)'

    def replacer_with_threshold(match):
        col = match.group(1)
        criteria = match.group(2)
        operator = match.group(3)
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        return f"score('{full_criteria}', {col}) {operator} {threshold}"

    result = re.sub(pattern_with_threshold, replacer_with_threshold, line, flags=re.IGNORECASE)

    # Pattern without threshold: col ABOUT 'x' (uses default)
    pattern_simple = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'(?!\s*[><])'

    def replacer_simple(match):
        col = match.group(1)
        criteria = match.group(2)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        return f"score('{full_criteria}', {col}) > {default_threshold}"

    result = re.sub(pattern_simple, replacer_simple, result, flags=re.IGNORECASE)

    return result


def _rewrite_tilde(line: str, annotation_prefix: str) -> str:
    """
    Rewrite tilde (~) operator for semantic equality.

    a.company ~ b.vendor                    →  match_pair(a.company, b.vendor, 'same entity')
    a.company ~ b.vendor AS 'same business' →  match_pair(a.company, b.vendor, 'same business')

    With annotation:
    -- @ use a fast model
    a ~ b  →  match_pair(a, b, 'use a fast model - same entity')
    """
    # Pattern with AS: a ~ b AS 'relationship'
    pattern_with_as = r'(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)\s+AS\s+\'([^\']+)\''

    def replacer_with_as(match):
        left = match.group(1)
        right = match.group(2)
        relationship = match.group(3)
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        return f"match_pair({left}, {right}, '{full_relationship}')"

    result = re.sub(pattern_with_as, replacer_with_as, line, flags=re.IGNORECASE)

    # Pattern simple: a ~ b (no AS)
    # Be careful not to match ~= or other operators
    pattern_simple = r'(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)(?!\s+AS\b)(?![=])'

    def replacer_simple(match):
        left = match.group(1)
        right = match.group(2)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        return f"match_pair({left}, {right}, '{full_relationship}')"

    result = re.sub(pattern_simple, replacer_simple, result, flags=re.IGNORECASE)

    return result


def _rewrite_relevance_to(line: str, annotation_prefix: str) -> str:
    """
    Rewrite RELEVANCE TO in ORDER BY.

    ORDER BY col RELEVANCE TO 'query'      →  ORDER BY score('query', col) DESC
    ORDER BY col RELEVANCE TO 'query' ASC  →  ORDER BY score('query', col) ASC

    With annotation:
    -- @ use a cheap model
    ORDER BY title RELEVANCE TO 'ML'  →  ORDER BY score('use a cheap model - ML', title) DESC
    """
    # Pattern: ORDER BY col RELEVANCE TO 'query' [ASC|DESC]
    pattern = r'ORDER\s+BY\s+(\w+(?:\.\w+)?)\s+RELEVANCE\s+TO\s+\'([^\']+)\'(?:\s+(ASC|DESC))?'

    def replacer(match):
        col = match.group(1)
        query = match.group(2)
        direction = match.group(3) or 'DESC'  # Default to DESC (highest relevance first)
        full_query = f"{annotation_prefix}{query}" if annotation_prefix else query
        return f"ORDER BY score('{full_query}', {col}) {direction}"

    return re.sub(pattern, replacer, line, flags=re.IGNORECASE)


def _rewrite_semantic_join(line: str, annotation_prefix: str) -> str:
    """
    Rewrite SEMANTIC JOIN.

    SEMANTIC JOIN t ON a.x ~ b.y  →  CROSS JOIN t WHERE match_pair(a.x, b.y, 'same entity')

    If the line already contains a WHERE clause after the SEMANTIC JOIN,
    we merge with AND instead of adding a new WHERE.

    Note: This is a line-level rewrite. Complex multi-line JOINs may need
    full SQL parsing for proper handling.
    """
    # Check if there's a WHERE clause elsewhere in the line (after potential SEMANTIC JOIN)
    # We'll use a placeholder and fix up afterward
    has_existing_where = bool(re.search(r'\bWHERE\b', line, re.IGNORECASE))

    # Pattern with alias: SEMANTIC JOIN table alias ON col1 ~ col2
    pattern_with_alias = r'SEMANTIC\s+JOIN\s+(\w+)\s+(\w+)\s+ON\s+(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)'

    def replacer_with_alias(match):
        table = match.group(1)
        alias = match.group(2)
        left = match.group(3)
        right = match.group(4)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        # Use placeholder that we'll fix up later
        return f"CROSS JOIN {table} {alias} {{{{SEMANTIC_WHERE}}}} match_pair({left}, {right}, '{full_relationship}')"

    # Pattern simple: SEMANTIC JOIN table ON col1 ~ col2
    pattern = r'SEMANTIC\s+JOIN\s+(\w+)\s+ON\s+(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)'

    def replacer(match):
        table = match.group(1)
        left = match.group(2)
        right = match.group(3)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        return f"CROSS JOIN {table} {{{{SEMANTIC_WHERE}}}} match_pair({left}, {right}, '{full_relationship}')"

    result = re.sub(pattern_with_alias, replacer_with_alias, line, flags=re.IGNORECASE)
    result = re.sub(pattern, replacer, result, flags=re.IGNORECASE)

    # Fix up the WHERE placeholder
    if '{{SEMANTIC_WHERE}}' in result:
        if has_existing_where:
            # There's an existing WHERE - our condition becomes part of it with AND
            # Replace the existing WHERE with our condition first, then AND WHERE
            result = result.replace('{{SEMANTIC_WHERE}}', 'WHERE')
            # Now find the other WHERE and change it to AND
            # This is tricky - we need to replace the SECOND WHERE with AND
            parts = result.split('WHERE', 2)  # Split into at most 3 parts
            if len(parts) == 3:
                # We have two WHEREs - merge them
                result = parts[0] + 'WHERE' + parts[1] + 'AND' + parts[2]
        else:
            # No existing WHERE - just use WHERE
            result = result.replace('{{SEMANTIC_WHERE}}', 'WHERE')

    return result


# ============================================================================
# Additional Semantic Operators (Future)
# ============================================================================

def _rewrite_semantic_distinct(query: str) -> str:
    """
    Rewrite SEMANTIC DISTINCT (placeholder for Phase 2).

    SELECT SEMANTIC DISTINCT company FROM t
    →
    WITH _distinct AS (SELECT DISTINCT company FROM t),
    _clustered AS (SELECT * FROM rvbbit_cluster(...))
    SELECT representative FROM _clustered WHERE is_rep = true
    """
    # TODO: Implement in Phase 2
    return query


def _rewrite_group_by_meaning(query: str) -> str:
    """
    Rewrite GROUP BY MEANING(col) (placeholder for Phase 2).

    GROUP BY MEANING(category)
    →
    Inject clustering CTE and rewrite to GROUP BY cluster_id
    """
    # TODO: Implement in Phase 2
    return query


# ============================================================================
# Info
# ============================================================================

def get_semantic_operators_info() -> Dict[str, Any]:
    """Get information about supported semantic operators."""
    return {
        'version': '0.1.0',
        'supported_operators': {
            'MEANS': {
                'syntax': "col MEANS 'criteria'",
                'rewrites_to': "matches('criteria', col)",
                'description': 'Semantic boolean match'
            },
            'ABOUT': {
                'syntax': "col ABOUT 'criteria' [> threshold]",
                'rewrites_to': "score('criteria', col) > threshold",
                'description': 'Semantic score with threshold'
            },
            '~': {
                'syntax': "a ~ b [AS 'relationship']",
                'rewrites_to': "match_pair(a, b, 'relationship')",
                'description': 'Semantic equality for JOINs'
            },
            'RELEVANCE TO': {
                'syntax': "ORDER BY col RELEVANCE TO 'query'",
                'rewrites_to': "ORDER BY score('query', col) DESC",
                'description': 'Semantic ordering'
            },
            'SEMANTIC JOIN': {
                'syntax': "SEMANTIC JOIN t ON a ~ b",
                'rewrites_to': "CROSS JOIN t WHERE match_pair(a, b, ...)",
                'description': 'Fuzzy JOIN'
            }
        },
        'annotation_support': {
            'prompt': "-- @ Free text prompt/model hints",
            'model': "-- @ model: provider/model-name",
            'threshold': "-- @ threshold: 0.7"
        }
    }


# ============================================================================
# Examples
# ============================================================================

EXAMPLES = """
# Semantic SQL Operators - Examples

## MEANS Operator (Semantic Boolean Filter)

```sql
-- Basic usage
SELECT * FROM products
WHERE description MEANS 'sustainable'

-- With annotation for model selection
-- @ use a fast and cheap model
WHERE description MEANS 'eco-friendly'

-- Equivalent to:
WHERE matches('use a fast and cheap model - eco-friendly', description)
```

## ABOUT Operator (Semantic Score Threshold)

```sql
-- Basic usage (default threshold 0.5)
SELECT * FROM articles
WHERE content ABOUT 'machine learning'

-- With explicit threshold
WHERE content ABOUT 'data science' > 0.7

-- With annotation
-- @ threshold: 0.8
-- @ use a fast model
WHERE content ABOUT 'AI research'
```

## Tilde (~) Operator (Semantic Equality)

```sql
-- Basic semantic equality
SELECT * FROM customers c, suppliers s
WHERE c.company ~ s.vendor

-- With explicit relationship
WHERE c.company_name ~ s.vendor_name AS 'same business entity'

-- In JOIN context
FROM customers c
SEMANTIC JOIN suppliers s ON c.company ~ s.vendor
```

## RELEVANCE TO (Semantic Ordering)

```sql
-- Order by semantic relevance
SELECT * FROM documents
ORDER BY content RELEVANCE TO 'quarterly earnings'

-- Ascending (least relevant first)
ORDER BY content RELEVANCE TO 'financial reports' ASC
```

## Combining Operators

```sql
SELECT
  p.name,
  p.description
FROM products p
SEMANTIC JOIN categories c ON p.category_text ~ c.name
WHERE p.description MEANS 'sustainable'
  AND p.title ABOUT 'organic' > 0.6
ORDER BY p.description RELEVANCE TO 'eco-friendly lifestyle'
LIMIT 100
```

## With Annotations

```sql
SELECT
  county,
  count(1) as incidents,
  -- @ use a fast and cheap model
  themes(title, 3) as top_themes,
  -- @ use a fast and cheap model
  avg(score('credibility of sighting', title)) as avg_cred
FROM bigfoot
-- @ use a fast and cheap model
WHERE title MEANS 'happened during the day'
  -- @ threshold: 0.3
  AND title ABOUT 'credible sighting'
GROUP BY county
```
"""
