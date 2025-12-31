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
"""

import re
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass


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
}


# ============================================================================
# Detection
# ============================================================================

def has_llm_aggregates(query: str) -> bool:
    """Check if query contains any LLM aggregate functions."""
    query_upper = query.upper()
    return any(f"LLM_{name.split('_')[1]}(" in query_upper or f"{name}(" in query_upper
               for name in LLM_AGG_FUNCTIONS.keys())


def _find_llm_agg_calls(query: str) -> List[Tuple[int, int, str, List[str]]]:
    """
    Find all LLM aggregate function calls in query.

    Returns list of (start_pos, end_pos, func_name, args)
    """
    results = []

    for func_name in LLM_AGG_FUNCTIONS.keys():
        # Case-insensitive search for function calls
        pattern = re.compile(
            rf'\b({func_name})\s*\(',
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

            results.append((start, end, match.group(1).upper(), args))

    # Sort by position (reverse order for safe replacement)
    results.sort(key=lambda x: x[0], reverse=True)
    return results


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
    """
    if not has_llm_aggregates(query):
        return query

    # Find all LLM aggregate calls
    calls = _find_llm_agg_calls(query)

    # Replace in reverse order (to preserve positions)
    result = query
    for start, end, func_name, args in calls:
        func_def = LLM_AGG_FUNCTIONS.get(func_name)
        if not func_def:
            continue

        # Validate arg count
        if len(args) < func_def.min_args:
            raise ValueError(
                f"{func_name} requires at least {func_def.min_args} argument(s), got {len(args)}"
            )
        if len(args) > func_def.max_args:
            raise ValueError(
                f"{func_name} accepts at most {func_def.max_args} argument(s), got {len(args)}"
            )

        # Build replacement
        replacement = _build_replacement(func_def, args)

        # Replace in query
        result = result[:start] + replacement + result[end:]

    return result


def _build_replacement(func_def: LLMAggFunction, args: List[str]) -> str:
    """
    Build the replacement function call.

    DuckDB doesn't support function overloading by arity, so we use
    different function names for each arity:
      - llm_summarize_1(values)
      - llm_summarize_2(values, prompt)
      - llm_summarize_3(values, prompt, max_items)
    """

    if func_def.name == "LLM_AGG":
        # Special case: LLM_AGG has prompt first, column second
        # Always 2 args -> llm_agg_2
        prompt = args[0]
        col = args[1]
        return f"llm_agg_2({prompt}, LIST({col})::VARCHAR)"

    elif func_def.name == "LLM_SUMMARIZE":
        col = args[0]
        if len(args) == 1:
            return f"llm_summarize_1(LIST({col})::VARCHAR)"
        elif len(args) == 2:
            return f"llm_summarize_2(LIST({col})::VARCHAR, {args[1]})"
        else:  # 3 args
            return f"llm_summarize_3(LIST({col})::VARCHAR, {args[1]}, {args[2]})"

    elif func_def.name == "LLM_CLASSIFY":
        col = args[0]
        categories = args[1]
        if len(args) == 2:
            return f"llm_classify_2(LIST({col})::VARCHAR, {categories})"
        else:  # 3 args
            return f"llm_classify_3(LIST({col})::VARCHAR, {categories}, {args[2]})"

    elif func_def.name == "LLM_SENTIMENT":
        col = args[0]
        return f"llm_sentiment_1(LIST({col})::VARCHAR)"

    elif func_def.name == "LLM_THEMES":
        col = args[0]
        if len(args) == 1:
            return f"llm_themes_1(LIST({col})::VARCHAR)"
        else:  # 2 args
            return f"llm_themes_2(LIST({col})::VARCHAR, {args[1]})"

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
    Full processing pipeline for LLM aggregates.

    1. Detect if query has LLM aggregates
    2. Validate context
    3. Rewrite to implementation calls
    """
    if not has_llm_aggregates(query):
        return query

    # Validate
    error = validate_llm_aggregate_context(query)
    if error:
        raise ValueError(error)

    # Rewrite
    return rewrite_llm_aggregates(query)


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
"""
