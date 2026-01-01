"""
LLM Aggregate Query Rewriter.

Transforms LLM aggregate function syntax into executable SQL.

Input:
    SELECT
      category,
      LLM_SUMMARIZE(review_text) as summary,
      LLM_SENTIMENT(review_text) as sentiment
    FROM reviews
    GROUP BY category;

Output:
    SELECT
      category,
      llm_summarize_impl(LIST(review_text)::VARCHAR) as summary,
      llm_sentiment_impl(LIST(review_text)::VARCHAR) as sentiment
    FROM reviews
    GROUP BY category;

The key insight: We don't need true DuckDB aggregate UDFs. We use LIST()
to collect values, cast to VARCHAR (JSON), and call our scalar implementation
functions. This gives us aggregate semantics with minimal complexity.

Annotation Syntax:
    -- @ instructions for the next LLM function
    -- @ model: anthropic/claude-haiku
    -- @ max_tokens: 100
    SUMMARIZE(review_text) as summary

Annotations use `-- @` prefix and apply to the NEXT LLM function in the query.
Lines with `:` are key-value options, lines without are prompt text.
"""

import re
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field


# ============================================================================
# Supported Aggregate Functions
# ============================================================================

@dataclass
class LLMAggFunction:
    """Definition of an LLM aggregate function."""
    name: str                    # SQL name (e.g., "LLM_SUMMARIZE")
    impl_name: str               # Implementation function name
    min_args: int                # Minimum arguments
    max_args: int                # Maximum arguments
    return_type: str             # SQL return type
    arg_template: str            # Template for impl call args


LLM_AGG_FUNCTIONS = {
    "LLM_SUMMARIZE": LLMAggFunction(
        name="LLM_SUMMARIZE",
        impl_name="llm_summarize_impl",
        min_args=1,
        max_args=3,  # (column, prompt, max_items)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_CLASSIFY": LLMAggFunction(
        name="LLM_CLASSIFY",
        impl_name="llm_classify_impl",
        min_args=2,
        max_args=3,  # (column, categories, prompt)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_SENTIMENT": LLMAggFunction(
        name="LLM_SENTIMENT",
        impl_name="llm_sentiment_impl",
        min_args=1,
        max_args=1,
        return_type="DOUBLE",
        arg_template="LIST({col})::VARCHAR"
    ),
    "LLM_THEMES": LLMAggFunction(
        name="LLM_THEMES",
        impl_name="llm_themes_impl",
        min_args=1,
        max_args=2,  # (column, max_themes)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_AGG": LLMAggFunction(
        name="LLM_AGG",
        impl_name="llm_agg_impl",
        min_args=2,
        max_args=2,  # (prompt, column)
        return_type="VARCHAR",
        arg_template="{prompt}, LIST({col})::VARCHAR"  # Note: prompt comes first
    ),
    "LLM_DEDUPE": LLMAggFunction(
        name="LLM_DEDUPE",
        impl_name="llm_dedupe_impl",
        min_args=1,
        max_args=2,  # (column, criteria)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_CLUSTER": LLMAggFunction(
        name="LLM_CLUSTER",
        impl_name="llm_cluster_impl",
        min_args=1,
        max_args=3,  # (column, num_clusters, criteria)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_CONSENSUS": LLMAggFunction(
        name="LLM_CONSENSUS",
        impl_name="llm_consensus_impl",
        min_args=1,
        max_args=2,  # (column, prompt)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
    "LLM_OUTLIERS": LLMAggFunction(
        name="LLM_OUTLIERS",
        impl_name="llm_outliers_impl",
        min_args=1,
        max_args=3,  # (column, num_outliers, criteria)
        return_type="VARCHAR",
        arg_template="LIST({col})::VARCHAR{extra_args}"
    ),
}


# Short aliases for cleaner SQL (map to canonical names)
# These are rewritten before DuckDB sees them, so reserved words don't matter
LLM_AGG_ALIASES = {
    "SUMMARIZE": "LLM_SUMMARIZE",
    "CLASSIFY": "LLM_CLASSIFY",
    "SENTIMENT": "LLM_SENTIMENT",
    "THEMES": "LLM_THEMES",
    "TOPICS": "LLM_THEMES",       # Alias for THEMES
    "DEDUPE": "LLM_DEDUPE",       # Semantic deduplication
    "CLUSTER": "LLM_CLUSTER",     # Semantic clustering
    "CONSENSUS": "LLM_CONSENSUS", # Find common ground
    "OUTLIERS": "LLM_OUTLIERS",   # Find unusual items
    # Note: AGG is intentionally omitted - too generic
}


def _resolve_alias(name: str) -> str:
    """Resolve alias to canonical function name."""
    upper = name.upper()
    return LLM_AGG_ALIASES.get(upper, upper)


# ============================================================================
# Annotation Parsing
# ============================================================================

@dataclass
class LLMAnnotation:
    """Parsed annotation for an LLM function."""
    prompt: Optional[str] = None          # Custom prompt/instructions
    model: Optional[str] = None           # Model override
    max_tokens: Optional[int] = None      # Token limit
    start_pos: int = 0                    # Start position in query
    end_pos: int = 0                      # End position in query


def _parse_annotations(query: str) -> List[Tuple[int, LLMAnnotation]]:
    """
    Parse all -- @ annotations from query.

    Returns list of (end_position, annotation) tuples.
    The end_position is where the annotation block ends, used to
    associate with the next LLM function.

    Supports:
        -- @ Free-form prompt text
        -- @ More prompt text (consecutive lines merge)
        -- @ model: anthropic/claude-haiku
        -- @ max_tokens: 100
    """
    annotations = []

    # Find all annotation comment blocks
    # Pattern: consecutive lines starting with -- @
    lines = query.split('\n')

    current_annotation = None
    current_start = 0
    current_pos = 0
    prompt_lines = []

    for line in lines:
        line_start = current_pos
        line_end = current_pos + len(line)

        # Check if this line is an annotation
        stripped = line.strip()
        if stripped.startswith('-- @'):
            # Extract content after -- @
            content = stripped[4:].strip()

            if current_annotation is None:
                current_annotation = LLMAnnotation(start_pos=line_start)
                prompt_lines = []

            # Check for key: value pattern
            if ':' in content:
                key, _, value = content.partition(':')
                key = key.strip().lower()
                value = value.strip()

                if key == 'model':
                    current_annotation.model = value
                elif key == 'max_tokens':
                    try:
                        current_annotation.max_tokens = int(value)
                    except ValueError:
                        pass
                elif key == 'prompt':
                    # Explicit prompt key
                    prompt_lines.append(value)
                else:
                    # Unknown key, treat as prompt text
                    prompt_lines.append(content)
            else:
                # No colon, it's prompt text
                prompt_lines.append(content)

            current_annotation.end_pos = line_end

        else:
            # Not an annotation line
            if current_annotation is not None:
                # Finish current annotation block
                if prompt_lines:
                    current_annotation.prompt = ' '.join(prompt_lines)
                annotations.append((current_annotation.end_pos, current_annotation))
                current_annotation = None
                prompt_lines = []

        current_pos = line_end + 1  # +1 for newline

    # Handle annotation at end of query
    if current_annotation is not None:
        if prompt_lines:
            current_annotation.prompt = ' '.join(prompt_lines)
        annotations.append((current_annotation.end_pos, current_annotation))

    return annotations


def _find_annotation_for_position(
    annotations: List[Tuple[int, LLMAnnotation]],
    func_start: int
) -> Optional[LLMAnnotation]:
    """
    Find the annotation that applies to a function at the given position.

    An annotation applies if it ends before the function starts and
    there's no other LLM function between them.
    """
    # Find the closest annotation that ends before this function
    best = None
    best_end = -1

    for end_pos, annotation in annotations:
        # Annotation must end before function starts
        if end_pos < func_start:
            # And be closer than any previous match
            if end_pos > best_end:
                best = annotation
                best_end = end_pos

    return best


# ============================================================================
# Detection
# ============================================================================

def has_llm_aggregates(query: str) -> bool:
    """Check if query contains any LLM aggregate functions or aliases."""
    query_upper = query.upper()
    # Check canonical names
    for name in LLM_AGG_FUNCTIONS.keys():
        if f"{name}(" in query_upper:
            return True
    # Check aliases
    for alias in LLM_AGG_ALIASES.keys():
        # Use word boundary to avoid matching e.g. "SUMMARIZED"
        if re.search(rf'\b{alias}\s*\(', query_upper):
            return True
    return False


def has_llm_case(query: str) -> bool:
    """Check if query contains LLM_CASE ... END syntax."""
    return bool(re.search(r'\bLLM_CASE\b', query, re.IGNORECASE))


def rewrite_llm_case(query: str) -> str:
    """
    Rewrite LLM_CASE ... END syntax to semantic_case() function calls.

    Input:
        LLM_CASE description
          WHEN SEMANTIC 'mentions sustainability' THEN 'eco'
          WHEN SEMANTIC 'mentions performance' THEN 'performance'
          ELSE 'standard'
        END

    Output:
        semantic_case_6(description,
          'mentions sustainability', 'eco',
          'mentions performance', 'performance',
          'standard'
        )
    """
    if not has_llm_case(query):
        return query

    # Pattern to match LLM_CASE ... END blocks
    # Captures: expression, WHEN clauses, optional ELSE
    llm_case_pattern = re.compile(
        r'\bLLM_CASE\s+'                     # LLM_CASE keyword
        r'(\w+(?:\.\w+)?)\s+'                # expression (column or table.column)
        r'((?:WHEN\s+SEMANTIC\s+\'[^\']*\'\s+THEN\s+\'[^\']*\'\s*)+)'  # WHEN clauses
        r'(?:ELSE\s+\'([^\']*)\'\s*)?'       # optional ELSE
        r'END',                               # END keyword
        re.IGNORECASE | re.DOTALL
    )

    def replace_llm_case(match):
        expr = match.group(1)
        when_clauses = match.group(2)
        else_value = match.group(3)

        # Parse WHEN clauses
        when_pattern = re.compile(
            r"WHEN\s+SEMANTIC\s+'([^']*)'\s+THEN\s+'([^']*)'",
            re.IGNORECASE
        )
        pairs = when_pattern.findall(when_clauses)

        if not pairs:
            return match.group(0)  # No valid WHEN clauses, leave unchanged

        # Build function arguments
        args = [expr]
        for condition, result in pairs:
            args.append(f"'{condition}'")
            args.append(f"'{result}'")

        if else_value:
            args.append(f"'{else_value}'")

        # Calculate arity for function name
        # arity = 1 (expr) + 2*conditions + (1 if else else 0)
        arity = len(args)
        func_name = f"semantic_case_{arity}"

        return f"{func_name}({', '.join(args)})"

    result = llm_case_pattern.sub(replace_llm_case, query)
    return result


def _find_llm_agg_calls(query: str) -> List[Tuple[int, int, str, List[str]]]:
    """
    Find all LLM aggregate function calls in query.

    Returns list of (start_pos, end_pos, func_name, args)
    where func_name is the CANONICAL name (aliases are resolved).
    """
    results = []

    # Build list of all names to search for (canonical + aliases)
    all_names = list(LLM_AGG_FUNCTIONS.keys()) + list(LLM_AGG_ALIASES.keys())

    for search_name in all_names:
        # Case-insensitive search for function calls
        pattern = re.compile(
            rf'\b({search_name})\s*\(',
            re.IGNORECASE
        )

        for match in pattern.finditer(query):
            start = match.start()
            func_start = match.end() - 1  # Position of opening paren

            # Find matching closing paren
            paren_depth = 0
            end = func_start
            for i, char in enumerate(query[func_start:], start=func_start):
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                    if paren_depth == 0:
                        end = i + 1
                        break

            if paren_depth != 0:
                continue  # Unbalanced parens, skip

            # Extract arguments
            args_str = query[func_start + 1:end - 1]
            args = _split_args(args_str)

            # Resolve alias to canonical name
            canonical_name = _resolve_alias(match.group(1))
            results.append((start, end, canonical_name, args))

    # Sort by position (reverse order for safe replacement)
    # Also deduplicate in case both alias and canonical matched
    seen_positions = set()
    deduped = []
    for item in sorted(results, key=lambda x: x[0], reverse=True):
        if item[0] not in seen_positions:
            seen_positions.add(item[0])
            deduped.append(item)

    return deduped


def _split_args(args_str: str) -> List[str]:
    """Split function arguments, respecting nested parens and quotes."""
    args = []
    current = []
    paren_depth = 0
    in_string = False
    string_char = None

    for char in args_str:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
        elif char == string_char and in_string:
            in_string = False
            string_char = None

        if not in_string:
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == ',' and paren_depth == 0:
                args.append(''.join(current).strip())
                current = []
                continue

        current.append(char)

    if current:
        args.append(''.join(current).strip())

    return [a for a in args if a]  # Filter empty


# ============================================================================
# Rewriting
# ============================================================================

def rewrite_llm_aggregates(query: str) -> str:
    """
    Rewrite LLM aggregate functions to implementation calls.

    Transforms:
        LLM_SUMMARIZE(review_text)
    Into:
        llm_summarize_impl(LIST(review_text)::VARCHAR)

    And:
        LLM_SUMMARIZE(review_text, 'Custom prompt')
    Into:
        llm_summarize_impl(LIST(review_text)::VARCHAR, 'Custom prompt')

    And:
        LLM_AGG('What are complaints?', review_text)
    Into:
        llm_agg_impl('What are complaints?', LIST(review_text)::VARCHAR)

    Also supports annotation syntax:
        -- @ Summarize focusing on complaints
        -- @ model: anthropic/claude-haiku
        SUMMARIZE(review_text)
    """
    if not has_llm_aggregates(query):
        return query

    # Parse annotations first
    annotations = _parse_annotations(query)

    # Find all LLM aggregate calls
    calls = _find_llm_agg_calls(query)

    # Track which annotations have been used (for cleanup)
    used_annotations = set()

    # Replace in reverse order (to preserve positions)
    result = query
    for start, end, func_name, args in calls:
        func_def = LLM_AGG_FUNCTIONS.get(func_name)
        if not func_def:
            continue

        # Find annotation for this function (if any)
        annotation = _find_annotation_for_position(annotations, start)
        if annotation:
            used_annotations.add(annotation.start_pos)

        # Validate arg count (annotation can add args, so check after merge)
        if len(args) < func_def.min_args:
            raise ValueError(
                f"{func_name} requires at least {func_def.min_args} argument(s), got {len(args)}"
            )
        if len(args) > func_def.max_args and annotation is None:
            raise ValueError(
                f"{func_name} accepts at most {func_def.max_args} argument(s), got {len(args)}"
            )

        # Build replacement (with annotation if present)
        replacement = _build_replacement(func_def, args, annotation)

        # Replace in query
        result = result[:start] + replacement + result[end:]

    # Clean up ALL annotation comments from the result
    # (They've been incorporated into function calls, so remove them)
    result = _remove_all_annotations(result)

    return result


def _remove_all_annotations(query: str) -> str:
    """Remove all -- @ annotation lines from query."""
    lines = query.split('\n')
    result_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip lines that are pure annotations
        if stripped.startswith('-- @'):
            continue
        result_lines.append(line)

    return '\n'.join(result_lines)


def _build_replacement(
    func_def: LLMAggFunction,
    args: List[str],
    annotation: Optional[LLMAnnotation] = None
) -> str:
    """
    Build the replacement function call.

    DuckDB doesn't support function overloading by arity, so we use
    different function names for each arity:
      - llm_summarize_1(values)
      - llm_summarize_2(values, prompt)
      - llm_summarize_3(values, prompt, max_items)

    If an annotation is provided, its prompt/model/max_tokens are injected
    as additional arguments.

    Model hints from annotations are prepended to prompts so bodybuilder's
    request mode can pick the appropriate model.
    """
    # Helper to quote a string for SQL
    def sql_quote(s: str) -> str:
        # Escape single quotes by doubling them
        escaped = s.replace("'", "''")
        return f"'{escaped}'"

    def build_prompt_with_model_hint(prompt: str) -> str:
        """Prepend model hint to prompt if annotation specifies a model."""
        if annotation and annotation.model:
            # Prefix with model hint for bodybuilder's planner
            # Format: "Use {model} - {actual task}"
            return f"Use {annotation.model} - {prompt}"
        return prompt

    if func_def.name == "LLM_AGG":
        # Special case: LLM_AGG has prompt first, column second
        prompt = args[0]
        col = args[1]
        # Annotation can override or enhance the prompt
        if annotation and annotation.prompt:
            # Prepend annotation to existing prompt
            existing = prompt.strip("'\"")
            combined = f"{annotation.prompt} {existing}"
            prompt = sql_quote(build_prompt_with_model_hint(combined))
        elif annotation and annotation.model:
            # Just model hint, no prompt override
            existing = prompt.strip("'\"")
            prompt = sql_quote(build_prompt_with_model_hint(existing))
        return f"llm_agg_2({prompt}, LIST({col})::VARCHAR)"

    elif func_def.name == "LLM_SUMMARIZE":
        col = args[0]
        # Determine prompt: explicit arg > annotation > none
        prompt_arg = args[1] if len(args) >= 2 else None
        if prompt_arg is None and annotation and annotation.prompt:
            prompt_arg = sql_quote(build_prompt_with_model_hint(annotation.prompt))
        elif prompt_arg is None and annotation and annotation.model:
            # Model hint but no custom prompt - use default with hint
            prompt_arg = sql_quote(build_prompt_with_model_hint("summarize these items"))

        # Determine max_items: explicit arg > annotation > none
        max_items_arg = args[2] if len(args) >= 3 else None
        if max_items_arg is None and annotation and annotation.max_tokens:
            # max_tokens in annotation maps to max_items (sample size)
            max_items_arg = str(annotation.max_tokens)

        if prompt_arg is None:
            return f"llm_summarize_1(LIST({col})::VARCHAR)"
        elif max_items_arg is None:
            return f"llm_summarize_2(LIST({col})::VARCHAR, {prompt_arg})"
        else:
            return f"llm_summarize_3(LIST({col})::VARCHAR, {prompt_arg}, {max_items_arg})"

    elif func_def.name == "LLM_CLASSIFY":
        col = args[0]
        categories = args[1]
        # Prompt is optional 3rd arg
        prompt_arg = args[2] if len(args) >= 3 else None
        if prompt_arg is None and annotation and annotation.prompt:
            prompt_arg = sql_quote(build_prompt_with_model_hint(annotation.prompt))
        elif prompt_arg is None and annotation and annotation.model:
            # Model hint but no custom prompt - use default with hint
            prompt_arg = sql_quote(build_prompt_with_model_hint("classify these items"))

        if prompt_arg is None:
            return f"llm_classify_2(LIST({col})::VARCHAR, {categories})"
        else:
            return f"llm_classify_3(LIST({col})::VARCHAR, {categories}, {prompt_arg})"

    elif func_def.name == "LLM_SENTIMENT":
        col = args[0]
        # Sentiment: if model annotation, create a prompt with hint
        if annotation and annotation.model:
            prompt_arg = sql_quote(build_prompt_with_model_hint("analyze sentiment"))
            # Need to add sentiment variant that accepts prompt...
            # For now, sentiment doesn't support custom prompts
            pass
        return f"llm_sentiment_1(LIST({col})::VARCHAR)"

    elif func_def.name == "LLM_THEMES":
        col = args[0]
        # Max themes is optional 2nd arg
        max_themes_arg = args[1] if len(args) >= 2 else None
        if max_themes_arg is None and annotation and annotation.max_tokens:
            # Use max_tokens as max_themes hint
            max_themes_arg = str(min(annotation.max_tokens, 20))  # Cap at 20 themes

        if max_themes_arg is None:
            return f"llm_themes_1(LIST({col})::VARCHAR)"
        else:
            return f"llm_themes_2(LIST({col})::VARCHAR, {max_themes_arg})"

    else:
        # Generic fallback - use arg count suffix
        col = args[0]
        total_args = len(args)
        extra_args = ", ".join(args[1:])
        if extra_args:
            extra_args = ", " + extra_args
        # impl_name already has _impl suffix, replace with _{n}
        base_name = func_def.impl_name.replace("_impl", "")
        return f"{base_name}_{total_args}(LIST({col})::VARCHAR{extra_args})"


# ============================================================================
# Validation
# ============================================================================

def validate_llm_aggregate_context(query: str) -> Optional[str]:
    """
    Validate that LLM aggregates are used in proper GROUP BY context.

    Returns error message if invalid, None if valid.
    """
    if not has_llm_aggregates(query):
        return None

    query_upper = query.upper()

    # Check for GROUP BY (required for aggregates to make sense)
    # Exception: queries on single-row tables or with LIMIT 1
    has_group_by = 'GROUP BY' in query_upper
    has_limit_1 = re.search(r'LIMIT\s+1\b', query_upper)
    has_distinct = 'SELECT DISTINCT' in query_upper

    if not has_group_by and not has_limit_1 and not has_distinct:
        # Warning but not error - might be aggregating entire table
        pass  # Allow it, just aggregate everything

    return None


# ============================================================================
# Combined Entry Point
# ============================================================================

def process_llm_aggregates(query: str) -> str:
    """
    Full processing pipeline for LLM features.

    1. Rewrite LLM_CASE ... END to semantic_case() calls
    2. Detect if query has LLM aggregates
    3. Validate context
    4. Rewrite to implementation calls
    """
    result = query

    # First: rewrite LLM_CASE syntax
    if has_llm_case(result):
        result = rewrite_llm_case(result)

    # Then: rewrite LLM aggregates
    if has_llm_aggregates(result):
        # Validate
        error = validate_llm_aggregate_context(result)
        if error:
            raise ValueError(error)
        result = rewrite_llm_aggregates(result)

    return result


# ============================================================================
# Info
# ============================================================================

def get_supported_aggregates() -> Dict[str, Dict[str, Any]]:
    """Get information about supported LLM aggregate functions."""
    return {
        name: {
            "impl": func.impl_name,
            "min_args": func.min_args,
            "max_args": func.max_args,
            "return_type": func.return_type,
            "description": _get_func_description(name)
        }
        for name, func in LLM_AGG_FUNCTIONS.items()
    }


def _get_func_description(name: str) -> str:
    """Get human-readable description of aggregate function."""
    descriptions = {
        "LLM_SUMMARIZE": "Summarize a collection of texts into a single summary",
        "LLM_CLASSIFY": "Classify a collection into one of the given categories",
        "LLM_SENTIMENT": "Calculate average sentiment score (-1.0 to 1.0)",
        "LLM_THEMES": "Extract common themes/topics as JSON array",
        "LLM_AGG": "Generic aggregate with custom prompt",
    }
    return descriptions.get(name, "LLM aggregate function")


# ============================================================================
# Examples (for documentation)
# ============================================================================

EXAMPLES = """
# LLM Aggregate Functions - Examples

## LLM_SUMMARIZE
Summarize all values in a group into a single text summary.

```sql
-- Basic usage
SELECT
  category,
  LLM_SUMMARIZE(review_text) as summary
FROM reviews
GROUP BY category;

-- With custom prompt
SELECT
  product_id,
  LLM_SUMMARIZE(review_text, 'Focus on quality issues:') as quality_summary
FROM reviews
GROUP BY product_id;

-- With max items limit
SELECT
  category,
  LLM_SUMMARIZE(review_text, 'Summarize feedback:', 50) as summary
FROM reviews
GROUP BY category;
```

## LLM_CLASSIFY
Classify a group into one of the specified categories.

```sql
-- Overall sentiment classification
SELECT
  product_id,
  LLM_CLASSIFY(review_text, 'positive,negative,mixed') as sentiment
FROM reviews
GROUP BY product_id;

-- Custom classification
SELECT
  customer_id,
  LLM_CLASSIFY(ticket_text, 'billing,technical,general,complaint', 'Classify support tickets:') as ticket_type
FROM support_tickets
GROUP BY customer_id;
```

## LLM_SENTIMENT
Calculate average sentiment score for a group.

```sql
SELECT
  product_id,
  COUNT(*) as review_count,
  LLM_SENTIMENT(review_text) as avg_sentiment
FROM reviews
GROUP BY product_id
ORDER BY avg_sentiment DESC;
```

## LLM_THEMES
Extract common themes from a group.

```sql
SELECT
  category,
  LLM_THEMES(review_text) as themes,
  LLM_THEMES(review_text, 3) as top_3_themes
FROM reviews
GROUP BY category;
```

## LLM_AGG
Generic aggregate with custom prompt - most flexible.

```sql
-- Custom analysis
SELECT
  product_id,
  LLM_AGG('What are the top 3 complaints?', review_text) as complaints,
  LLM_AGG('What features do customers love?', review_text) as loved_features
FROM reviews
GROUP BY product_id;

-- Pattern detection
SELECT
  error_code,
  LLM_AGG('Are these error messages related? What is the root cause?', error_message) as analysis
FROM error_logs
GROUP BY error_code;
```

## Combining with regular aggregates

```sql
SELECT
  category,
  COUNT(*) as review_count,
  AVG(rating) as avg_rating,
  LLM_SUMMARIZE(review_text) as summary,
  LLM_SENTIMENT(review_text) as sentiment,
  LLM_THEMES(review_text, 3) as themes
FROM reviews
GROUP BY category
HAVING COUNT(*) > 10
ORDER BY sentiment DESC;
```

## Short Aliases (cleaner SQL)

All aggregate functions have short aliases without the LLM_ prefix:

```sql
-- These are equivalent:
SELECT SUMMARIZE(review_text) FROM reviews GROUP BY category;
SELECT LLM_SUMMARIZE(review_text) FROM reviews GROUP BY category;

-- Clean, readable queries
SELECT
  category,
  SUMMARIZE(review_text) as summary,
  SENTIMENT(review_text) as mood,
  THEMES(review_text, 3) as topics
FROM reviews
GROUP BY category;
```

Available aliases:
- SUMMARIZE → LLM_SUMMARIZE
- CLASSIFY → LLM_CLASSIFY
- SENTIMENT → LLM_SENTIMENT
- THEMES → LLM_THEMES
- (LLM_AGG has no alias - use full name)

## Annotation Syntax (-- @)

Use `-- @` comments to provide instructions without cluttering function args:

```sql
-- Single-line instruction
-- @ Focus on quality complaints only
SUMMARIZE(review_text) as complaints

-- Multi-line instructions (consecutive lines merge)
-- @ Summarize customer feedback with emphasis on:
-- @ - Product quality issues
-- @ - Shipping problems
-- @ - Customer service interactions
SUMMARIZE(review_text) as summary

-- With metadata options
-- @ Focus on negative feedback only
-- @ max_tokens: 50
SUMMARIZE(review_text) as issues

-- Per-column annotations
SELECT
  category,
  -- @ Focus on complaints
  SUMMARIZE(negative_reviews) as complaints,
  -- @ Focus on praise
  SUMMARIZE(positive_reviews) as praise
FROM reviews
GROUP BY category;
```

Supported annotation options:
- Free text: Becomes the prompt/instructions (can include model hints like "use a cheap model")
- `max_tokens: N`: Limits output or sample size
- `model: provider/model-name`: Explicit model selection (e.g., `model: google/gemini-2.5-flash-lite`)

Model selection follows bodybuilder's request mode:
- Explicit `model:` annotation → uses that model directly
- Hints in prompt text like "cheap", "fast", "powerful", "Claude" → planner picks
- No hint → planner uses default model

```sql
-- Explicit model
-- @ model: google/gemini-2.5-flash-lite
SUMMARIZE(reviews) as quick_summary

-- Model hint in prompt (planner picks)
-- @ Use a cheap fast model for this basic summary
SUMMARIZE(reviews) as basic_summary

-- Powerful model hint
-- @ Use Claude for nuanced analysis
SUMMARIZE(reviews) as detailed_summary
```

Note: Explicit function arguments take precedence over annotations.

## Scalar Functions (per-row, no GROUP BY)

### MATCHES / LLM_MATCHES
Semantic boolean filter for WHERE clauses:

```sql
-- Find rows matching semantic criteria
SELECT * FROM products
WHERE matches('eco-friendly or sustainable', description);

-- Find complaints
SELECT * FROM reviews
WHERE llm_matches('mentions defects or quality issues', review_text);
```

### SCORE / LLM_SCORE
Semantic scoring (0.0-1.0) for ranking or threshold filtering:

```sql
-- Rank by relevance
SELECT title, score('machine learning related', description) as relevance
FROM articles
ORDER BY relevance DESC
LIMIT 10;

-- Filter with threshold
SELECT * FROM bigfoot
WHERE llm_score('credibility of sighting', title) > 0.7;

-- Combine scoring with aggregates
SELECT
  classification,
  SUMMARIZE(title) as summary
FROM bigfoot
WHERE score('dramatic encounter', title) > 0.5
GROUP BY classification;
```

## Fuzzy JOINs with MATCH_PAIR

### MATCH_PAIR / LLM_MATCH_PAIR
Entity matching for fuzzy joins and deduplication:

```sql
-- Basic fuzzy join: find matching companies
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE match_pair(c.company_name, s.vendor_name, 'same company')
LIMIT 100;

-- With explicit relationship
SELECT *
FROM products p1, products p2
WHERE p1.id < p2.id  -- avoid self-matches and duplicates
  AND match_pair(p1.name, p2.name, 'same product')
LIMIT 50;

-- Default relationship is "same entity"
SELECT *
FROM table1 t1, table2 t2
WHERE match_pair_2(t1.name, t2.name)  -- uses "same entity"
LIMIT 100;
```

### MATCH_TEMPLATE / LLM_MATCH_TEMPLATE
Flexible templated matching for complex conditions:

```sql
-- Custom template with placeholders
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE match_template(
  '{0} (a customer) and {1} (a supplier) represent the same business entity',
  c.company_name,
  s.vendor_name
)
LIMIT 100;

-- More complex relationships
SELECT *
FROM products p, categories c
WHERE match_template(
  'The product "{0}" belongs in the category "{1}"',
  p.description,
  c.category_name
)
LIMIT 100;
```

### Performance Tips for Fuzzy JOINs

**ALWAYS use LIMIT** - without it, you'll evaluate N×M pairs:
```sql
-- DANGEROUS: 1000 x 1000 = 1,000,000 LLM calls!
SELECT * FROM big_table1, big_table2
WHERE match_pair(t1.name, t2.name, 'same');

-- SAFE: Limit pairs evaluated
SELECT * FROM big_table1, big_table2
WHERE match_pair(t1.name, t2.name, 'same')
LIMIT 100;
```

**Use blocking for large tables** - pre-filter with cheap conditions:
```sql
-- First cheap filter, then LLM match
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE LEFT(c.company_name, 2) = LEFT(s.vendor_name, 2)  -- Blocking
  AND match_pair(c.company_name, s.vendor_name, 'same company')
LIMIT 100;
```

**Caching helps** - same pairs return cached results.

## LLM_CASE - Multi-way Semantic Classification

SQL-like syntax for semantic case/when with a SINGLE LLM call:

```sql
SELECT
  product_name,
  LLM_CASE description
    WHEN SEMANTIC 'mentions sustainability or eco-friendly' THEN 'eco'
    WHEN SEMANTIC 'mentions performance or speed' THEN 'performance'
    WHEN SEMANTIC 'mentions luxury or premium quality' THEN 'premium'
    ELSE 'standard'
  END as segment
FROM products;
```

This is rewritten to `semantic_case_N()` which makes ONE LLM call per row
that evaluates ALL conditions at once - much faster than chained `matches()`.

### Benefits over chained CASE WHEN

```sql
-- SLOW: Multiple LLM calls per row (one per WHEN until match)
SELECT
  CASE
    WHEN matches('sustainability', description) THEN 'eco'
    WHEN matches('performance', description) THEN 'performance'
    WHEN matches('luxury', description) THEN 'premium'
    ELSE 'standard'
  END as segment
FROM products;

-- FAST: Single LLM call evaluates all conditions
SELECT
  LLM_CASE description
    WHEN SEMANTIC 'sustainability' THEN 'eco'
    WHEN SEMANTIC 'performance' THEN 'performance'
    WHEN SEMANTIC 'luxury' THEN 'premium'
    ELSE 'standard'
  END as segment
FROM products;
```

### Function form (alternative)

You can also use the function directly:

```sql
SELECT
  semantic_case_8(description,
    'mentions sustainability', 'eco',
    'mentions performance', 'performance',
    'mentions luxury', 'premium',
    'standard'  -- default
  ) as segment
FROM products;
```

The number suffix indicates arity: 1 (text) + 2×conditions + optional default.
"""
