"""
LLM Aggregate Functions for SQL.

These enable GROUP BY analytics with LLM-powered aggregation:

    SELECT
      category,
      COUNT(*) as count,
      LLM_SUMMARIZE(review_text) as summary,
      LLM_SENTIMENT(review_text) as sentiment
    FROM reviews
    GROUP BY category;

Implementation Strategy:
- Query rewriter detects LLM_* aggregate functions
- Rewrites to collect values with LIST() or STRING_AGG()
- Calls scalar helper functions that process the collected values

This gives us aggregate semantics without needing true DuckDB aggregate UDFs.
"""

import json
import hashlib
import re
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


def _call_llm(
    prompt: str,
    model: str = None,
    max_tokens: int = 500
) -> str:
    """
    Call LLM via bodybuilder's request mode.

    Always uses request mode which goes through the full bodybuilder pipeline
    including planning, logging, and cost tracking. The planner handles both
    explicit model names and hints like "cheap", "fast", "Claude".

    Args:
        prompt: The request for the LLM (can include model hints)
        model: Ignored - model selection is handled by prompt content
        max_tokens: Ignored - handled by bodybuilder

    Returns:
        LLM response text, or "ERROR: ..." on failure
    """
    from ..traits.bodybuilder import bodybuilder
    from ..session_naming import generate_woodland_id
    from rich.console import Console

    console = Console()

    # Generate session info
    woodland_id = generate_woodland_id()
    session_id = f"sql-agg-{woodland_id}"
    cell_name = f"agg_{woodland_id[:8]}"

    # Build request - add instruction to return only the result
    request = f"{prompt}\n\nReturn ONLY the result, no explanation or markdown."

    prompt_preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
    console.print(f"[dim]🔧 sql_agg[/dim] [cyan]{session_id}[/cyan] [dim]|[/dim] {prompt_preview}")

    try:
        response = bodybuilder(
            request=request,
            _session_id=session_id,
            _cell_name=cell_name,
            _cascade_id="sql_aggregate",
        )

        if response.get("_route") == "error":
            error_msg = response.get("error", "Unknown error")
            console.print(f"[red]✗ sql_agg error:[/red] {error_msg[:50]}")
            return f"ERROR: {error_msg[:100]}"

        result = response.get("result") or response.get("content") or ""
        result = result.strip()

        # Log success
        model_used = response.get("model", "unknown")
        result_preview = result[:50] + "..." if len(result) > 50 else result
        console.print(f"[green]✓[/green] [dim]{model_used}[/dim] → {result_preview}")

        return result

    except Exception as e:
        console.print(f"[red]✗ sql_agg exception:[/red] {str(e)[:50]}")
        return f"ERROR: {str(e)[:100]}"


# Backwards compat alias
_call_llm_direct = _call_llm


def _sanitize_text(text: str) -> str:
    """
    Sanitize text for LLM consumption.

    Removes/replaces characters that can break JSON parsing or confuse LLMs:
    - Control characters
    - Null bytes
    - Excessive whitespace
    - Non-printable characters
    """
    if not text:
        return ""

    # Remove null bytes
    text = text.replace('\x00', '')

    # Remove other control characters except newline/tab
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Replace multiple whitespace with single space (except newlines)
    text = re.sub(r'[^\S\n]+', ' ', text)

    # Replace multiple newlines with double newline
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def _sanitize_values(values: List[str]) -> List[str]:
    """Sanitize a list of text values."""
    return [_sanitize_text(str(v)) for v in values if v is not None]


# ============================================================================
# Aggregate Cache (separate from scalar UDF cache)
# ============================================================================

_agg_cache: Dict[str, Tuple[str, float, Optional[float]]] = {}


def _agg_cache_key(func_name: str, prompt: str, values_hash: str) -> str:
    """Create cache key for aggregate result."""
    cache_str = f"{func_name}|{prompt}|{values_hash}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _hash_values(values: List[str]) -> str:
    """Hash a list of values for cache key."""
    combined = "|||".join(sorted(str(v) for v in values))
    return hashlib.md5(combined.encode()).hexdigest()[:16]


# ============================================================================
# Core Aggregate Implementations
# ============================================================================

def llm_summarize_impl(
    values_json: str,
    prompt: Optional[str] = None,
    max_items: int = 200,
    strategy: str = "direct",
    separator: str = "\n---\n",
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Summarize a collection of text values into a single summary.

    This is the workhorse behind LLM_SUMMARIZE() aggregate.

    Args:
        values_json: JSON array of text values (from LIST() in SQL)
        prompt: Custom prompt (default: generic summarization)
        max_items: Maximum items to include (samples if exceeded)
        strategy: "direct" (one call), "map_reduce" (hierarchical), "sample" (random sample)
        separator: Separator between items in prompt
        model: Model override
        use_cache: Whether to cache results

    Returns:
        Summary text

    Example SQL (after rewriting):
        SELECT llm_summarize_impl(
            LIST(review_text)::VARCHAR,
            'Summarize customer feedback, highlighting common themes:'
        ) as summary
        FROM reviews
        GROUP BY category
    """
    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        # If not valid JSON, treat as single value
        values = [values_json]

    # Sanitize and filter out nulls and empty strings
    values = _sanitize_values(values)
    values = [v for v in values if v]  # Remove empty after sanitization

    if not values:
        return "No data to summarize."

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("summarize", prompt or "default", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    # Default prompt
    if not prompt:
        prompt = "Summarize the following items into a concise summary that captures the key themes and patterns:"

    # Handle large collections
    if len(values) > max_items:
        if strategy == "sample":
            import random
            values = random.sample(values, max_items)
        elif strategy == "map_reduce":
            return _map_reduce_summarize(values, prompt, model)
        else:
            # Default: take first max_items with note
            values = values[:max_items]
            prompt = f"{prompt}\n\n(Note: Showing {max_items} of {len(values)} total items)"

    # Combine values
    combined_text = separator.join(f"- {v}" for v in values)

    # Build full prompt
    full_prompt = f"{prompt}\n\n{combined_text}\n\nSummary:"

    # Call LLM via bodybuilder with explicit body (bypasses planner)
    result = _call_llm_direct(full_prompt, model=model, max_tokens=500)

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_classify_impl(
    values_json: str,
    categories: str,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Classify a collection of values into one of the given categories.

    Useful for determining overall sentiment, category, or label for a group.

    Args:
        values_json: JSON array of text values
        categories: Comma-separated list of valid categories
        prompt: Custom classification prompt
        model: Model override
        use_cache: Whether to cache results

    Returns:
        One of the category labels

    Example SQL:
        SELECT llm_classify_impl(
            LIST(review_text)::VARCHAR,
            'positive,negative,mixed,neutral'
        ) as overall_sentiment
        FROM reviews
        GROUP BY product_id
    """
    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "unknown"

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("classify", f"{categories}|{prompt or ''}", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    # Sample if too many
    if len(values) > 100:
        import random
        values = random.sample(values, 100)

    # Build prompt
    if not prompt:
        prompt = f"Based on the following items, classify the overall group into exactly one of these categories: {categories}"
    else:
        prompt = f"{prompt}\n\nValid categories: {categories}"

    combined_text = "\n".join(f"- {v}" for v in values[:50])  # Limit for context

    full_prompt = f"""{prompt}

Items:
{combined_text}

Respond with ONLY the category name, nothing else."""

    result = _call_llm_direct(full_prompt, model=model, max_tokens=50)

    # Clean up result - should be just the category
    result = result.strip().lower()

    # Validate against categories
    valid_cats = [c.strip().lower() for c in categories.split(',')]
    if result not in valid_cats:
        # Try to find best match
        for cat in valid_cats:
            if cat in result:
                result = cat
                break

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_sentiment_impl(
    values_json: str,
    model: Optional[str] = None,
    use_cache: bool = True
) -> float:
    """
    Calculate average sentiment score for a collection of texts.

    Returns a float between -1.0 (very negative) and 1.0 (very positive).

    Args:
        values_json: JSON array of text values
        model: Model override
        use_cache: Whether to cache results

    Returns:
        Sentiment score as float

    Example SQL:
        SELECT llm_sentiment_impl(LIST(review_text)::VARCHAR) as sentiment_score
        FROM reviews
        GROUP BY product_id
    """

    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return 0.0

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("sentiment", "", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            try:
                return float(cached)
            except:
                pass

    # Sample if too many
    if len(values) > 50:
        import random
        values = random.sample(values, 50)

    combined_text = "\n".join(f"- {v}" for v in values)

    prompt = f"""Analyze the overall sentiment of these items on a scale from -1.0 (very negative) to 1.0 (very positive).

Items:
{combined_text}

Respond with ONLY a decimal number between -1.0 and 1.0, nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=20)

    # Parse result
    try:
        score = float(result.strip())
        score = max(-1.0, min(1.0, score))  # Clamp to valid range
    except ValueError:
        score = 0.0

    if use_cache:
        _cache_set(_agg_cache, cache_key, str(score), ttl=None)

    return score


def llm_themes_impl(
    values_json: str,
    max_themes: int = 5,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Extract common themes/topics from a collection of texts.

    Returns JSON array of theme strings.

    Args:
        values_json: JSON array of text values
        max_themes: Maximum number of themes to extract
        prompt: Custom prompt
        model: Model override
        use_cache: Whether to cache results

    Returns:
        JSON array of themes (as string)

    Example SQL:
        SELECT llm_themes_impl(LIST(review_text)::VARCHAR, 5) as themes
        FROM reviews
        GROUP BY product_id
    """

    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "[]"

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("themes", str(max_themes), values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    # Sample if too many
    if len(values) > 100:
        import random
        values = random.sample(values, 100)

    combined_text = "\n".join(f"- {v}" for v in values[:50])

    if not prompt:
        prompt = f"Extract the {max_themes} most common themes or topics from these items."

    full_prompt = f"""{prompt}

Items:
{combined_text}

Respond with a JSON array of {max_themes} theme strings, like: ["theme1", "theme2", "theme3"]
Return ONLY the JSON array, nothing else."""

    result = _call_llm_direct(full_prompt, model=model, max_tokens=200)

    # Clean up - ensure it's valid JSON array
    result = result.strip()
    if not result.startswith('['):
        # Try to extract JSON array from response
        import re
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            result = match.group(0)
        else:
            result = '[]'

    # Validate JSON
    try:
        json.loads(result)
    except json.JSONDecodeError:
        result = '[]'

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_agg_impl(
    prompt: str,
    values_json: str,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Generic LLM aggregate with custom prompt.

    The most flexible aggregate - you provide the prompt, it processes the group.

    Args:
        prompt: Custom prompt describing what to do with the values
        values_json: JSON array of text values
        model: Model override
        use_cache: Whether to cache results

    Returns:
        LLM response

    Example SQL:
        SELECT llm_agg_impl(
            'What are the top 3 complaints?',
            LIST(review_text)::VARCHAR
        ) as complaints
        FROM reviews
        GROUP BY product_id
    """

    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "No data available."

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("custom", prompt, values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    # Sample if too many
    if len(values) > 100:
        import random
        values = random.sample(values, 100)

    combined_text = "\n".join(f"- {v}" for v in values)

    full_prompt = f"""{prompt}

Data ({len(values)} items):
{combined_text}"""

    result = _call_llm_direct(full_prompt, model=model, max_tokens=500)

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


# ============================================================================
# Scalar LLM Functions (per-row, not aggregates)
# ============================================================================

def llm_matches_impl(
    criteria: str,
    text: str,
    model: str = None,
    use_cache: bool = True
) -> bool:
    """
    Check if text matches semantic criteria. Returns boolean.

    Use in WHERE clauses for semantic filtering:

        SELECT * FROM products
        WHERE llm_matches('is eco-friendly or sustainable', description);

    Args:
        criteria: What to check for (e.g., "mentions quality issues")
        text: The text to evaluate
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if text matches criteria, False otherwise
    """
    if not text or not text.strip():
        return False

    text = _sanitize_text(str(text))
    criteria = _sanitize_text(str(criteria))

    if not text or not criteria:
        return False

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        cache_key = _agg_cache_key("matches", criteria, text[:200])
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached.lower() == "true"

    prompt = f"""Does the following text match this criteria: "{criteria}"?

Text: {text[:2000]}

Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=10)
    result_lower = result.strip().lower()

    # Parse yes/no
    is_match = result_lower in ("yes", "true", "1", "y")

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, "true" if is_match else "false", ttl=None)

    return is_match


def llm_score_impl(
    criteria: str,
    text: str,
    model: str = None,
    use_cache: bool = True
) -> float:
    """
    Score how well text matches semantic criteria. Returns 0.0-1.0.

    Use for ranking or threshold filtering:

        SELECT *, llm_score('relevance to sustainability', description) as score
        FROM products
        WHERE llm_score('relevance to sustainability', description) > 0.7
        ORDER BY score DESC;

    Args:
        criteria: What to score against (e.g., "relevance to machine learning")
        text: The text to evaluate
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        Float between 0.0 (no match) and 1.0 (perfect match)
    """
    if not text or not text.strip():
        return 0.0

    text = _sanitize_text(str(text))
    criteria = _sanitize_text(str(criteria))

    if not text or not criteria:
        return 0.0

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        cache_key = _agg_cache_key("score", criteria, text[:200])
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            try:
                return float(cached)
            except ValueError:
                pass

    prompt = f"""Score how well the following text matches this criteria: "{criteria}"

Text: {text[:2000]}

Return ONLY a decimal number between 0.0 (no match) and 1.0 (perfect match), nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=10)

    # Parse score
    try:
        score = float(result.strip())
        score = max(0.0, min(1.0, score))  # Clamp to valid range
    except ValueError:
        score = 0.0

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, str(score), ttl=None)

    return score


def llm_match_pair_impl(
    left: str,
    right: str,
    relationship: str = "same entity",
    model: str = None,
    use_cache: bool = True
) -> bool:
    """
    Check if two values have the specified relationship. Perfect for fuzzy JOINs.

    Use for entity matching, deduplication, and fuzzy joins:

        SELECT c.*, s.*
        FROM customers c, suppliers s
        WHERE match_pair(c.company_name, s.vendor_name, 'same company')
        LIMIT 100;

    Args:
        left: First value (e.g., customer name)
        right: Second value (e.g., supplier name)
        relationship: What relationship to check (default: "same entity")
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if the values have the specified relationship
    """
    if not left or not right:
        return False

    left = _sanitize_text(str(left))
    right = _sanitize_text(str(right))

    if not left or not right:
        return False

    # Check cache - order-independent key (sorted)
    if use_cache:
        from .udf import _cache_get, _cache_set
        # Make cache key order-independent for symmetric relationships
        pair_key = "|".join(sorted([left[:100], right[:100]]))
        cache_key = _agg_cache_key("match_pair", relationship, pair_key)
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached.lower() == "true"

    prompt = f"""Do these two values refer to the {relationship}?

Value 1: {left[:500]}
Value 2: {right[:500]}

Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm(prompt, model=model)
    result_lower = result.strip().lower()

    # Parse yes/no
    is_match = result_lower in ("yes", "true", "1", "y")

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, "true" if is_match else "false", ttl=None)

    return is_match


def llm_match_template_impl(
    template: str,
    *args,
    model: str = None,
    use_cache: bool = True
) -> bool:
    """
    Check if values match using a custom template. Most flexible option.

    Use for complex matching conditions:

        SELECT c.*, s.*
        FROM customers c, suppliers s
        WHERE match_template(
            '{0} (customer) and {1} (supplier) are the same company',
            c.company_name,
            s.vendor_name
        )
        LIMIT 100;

    Args:
        template: Template string with {0}, {1}, etc. placeholders
        *args: Values to substitute into template
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if the LLM determines the statement is true
    """
    if not template:
        return False

    # Substitute args into template
    try:
        filled = template.format(*[_sanitize_text(str(a))[:500] for a in args])
    except (IndexError, KeyError) as e:
        return False

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        cache_key = _agg_cache_key("match_template", template[:50], filled[:200])
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached.lower() == "true"

    prompt = f"""Is the following statement true?

"{filled}"

Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm(prompt, model=model)
    result_lower = result.strip().lower()

    # Parse yes/no
    is_match = result_lower in ("yes", "true", "1", "y")

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, "true" if is_match else "false", ttl=None)

    return is_match


# ============================================================================
# Map-Reduce for Large Collections
# ============================================================================

def _map_reduce_summarize(
    values: List[str],
    prompt: str,
    model: Optional[str] = None,
    chunk_size: int = 50,
    max_workers: int = 4
) -> str:
    """
    Hierarchical summarization for large value collections.

    1. Split into chunks
    2. Summarize each chunk in parallel
    3. Summarize the summaries

    This handles cases where you have thousands of items that won't fit
    in a single context window.
    """

    # Split into chunks
    chunks = [values[i:i + chunk_size] for i in range(0, len(values), chunk_size)]

    # Phase 1: Summarize each chunk in parallel
    partial_summaries = []

    def summarize_chunk(chunk_values: List[str]) -> str:
        combined = "\n".join(f"- {v}" for v in chunk_values)
        return _call_llm_direct(
            f"Briefly summarize these items:\n{combined}",
            model=model,
            max_tokens=200
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(summarize_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            try:
                partial_summaries.append(future.result())
            except Exception as e:
                partial_summaries.append(f"(Error summarizing chunk: {e})")

    # Phase 2: Summarize the summaries
    if len(partial_summaries) == 1:
        return partial_summaries[0]

    combined_summaries = "\n\n".join(
        f"Batch {i+1}: {s}" for i, s in enumerate(partial_summaries)
    )

    final_prompt = f"""{prompt}

Partial summaries from {len(chunks)} batches:
{combined_summaries}

Synthesize these into a single coherent summary:"""

    return _call_llm_direct(final_prompt, model=model, max_tokens=500)


# ============================================================================
# UDF Registration
# ============================================================================

def register_llm_aggregates(connection, config: Dict[str, Any] = None):
    """
    Register LLM aggregate helper functions as DuckDB UDFs.

    These are the implementation functions that the rewritten SQL calls.
    The actual aggregate syntax (LLM_SUMMARIZE, etc.) is handled by
    the query rewriter, which transforms them to use these scalar UDFs
    with LIST() collection.

    Note: DuckDB doesn't support Python default arguments, so we register
    multiple wrapper functions for each arity (1-arg, 2-arg, etc.)
    """
    import duckdb
    import logging

    config = config or {}
    log = logging.getLogger(__name__)

    # ========== LLM_SUMMARIZE ==========
    # Different function names for each arity (DuckDB doesn't support overloading)

    def summarize_1(values_json: str) -> str:
        return llm_summarize_impl(values_json)

    def summarize_2(values_json: str, prompt: str) -> str:
        return llm_summarize_impl(values_json, prompt=prompt)

    def summarize_3(values_json: str, prompt: str, max_items: int) -> str:
        return llm_summarize_impl(values_json, prompt=prompt, max_items=max_items)

    for name, func in [
        ("llm_summarize_1", summarize_1),    # 1 arg
        ("llm_summarize_2", summarize_2),    # 2 args
        ("llm_summarize_3", summarize_3),    # 3 args
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_CLASSIFY ==========
    # Different function names for each arity

    def classify_2(values_json: str, categories: str) -> str:
        return llm_classify_impl(values_json, categories)

    def classify_3(values_json: str, categories: str, prompt: str) -> str:
        return llm_classify_impl(values_json, categories, prompt=prompt)

    for name, func in [
        ("llm_classify_2", classify_2),    # 2 args
        ("llm_classify_3", classify_3),    # 3 args
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_SENTIMENT ==========
    # Always 1 arg

    def sentiment_1(values_json: str) -> float:
        return llm_sentiment_impl(values_json)

    try:
        connection.create_function("llm_sentiment_1", sentiment_1, return_type="DOUBLE")
    except Exception as e:
        log.warning(f"Could not register llm_sentiment_1: {e}")

    # ========== LLM_THEMES ==========
    # Different function names for each arity

    def themes_1(values_json: str) -> str:
        return llm_themes_impl(values_json)

    def themes_2(values_json: str, max_themes: int) -> str:
        return llm_themes_impl(values_json, max_themes=max_themes)

    for name, func in [
        ("llm_themes_1", themes_1),    # 1 arg
        ("llm_themes_2", themes_2),    # 2 args
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_AGG ==========
    # Always 2 args

    def agg_2(prompt: str, values_json: str) -> str:
        return llm_agg_impl(prompt, values_json)

    try:
        connection.create_function("llm_agg_2", agg_2, return_type="VARCHAR")
    except Exception as e:
        log.warning(f"Could not register llm_agg_2: {e}")

    # ========== SCALAR LLM FUNCTIONS ==========
    # These go directly to DuckDB (no rewriter), so we register both
    # canonical (llm_*) and short (matches, score) names

    # LLM_MATCHES / MATCHES - semantic boolean filter
    def matches_2(criteria: str, text: str) -> bool:
        return llm_matches_impl(criteria, text)

    for name in ["llm_matches", "matches"]:
        try:
            connection.create_function(name, matches_2, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # LLM_SCORE / SCORE - semantic scoring (0.0-1.0)
    def score_2(criteria: str, text: str) -> float:
        return llm_score_impl(criteria, text)

    for name in ["llm_score", "score"]:
        try:
            connection.create_function(name, score_2, return_type="DOUBLE")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== MATCH_PAIR - for fuzzy JOINs ==========
    # match_pair(left, right) or match_pair(left, right, relationship)

    def match_pair_2(left: str, right: str) -> bool:
        return llm_match_pair_impl(left, right)

    def match_pair_3(left: str, right: str, relationship: str) -> bool:
        return llm_match_pair_impl(left, right, relationship)

    for name, func in [
        ("match_pair", match_pair_3),      # 3-arg version (with relationship)
        ("llm_match_pair", match_pair_3),  # Alias
    ]:
        try:
            connection.create_function(name, func, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # Also register 2-arg version with default relationship
    try:
        connection.create_function("match_pair_2", match_pair_2, return_type="BOOLEAN")
    except Exception as e:
        log.warning(f"Could not register match_pair_2: {e}")

    # ========== MATCH_TEMPLATE - flexible templated matching ==========
    # match_template(template, arg1, arg2, ...)

    def match_template_2(template: str, arg1: str) -> bool:
        return llm_match_template_impl(template, arg1)

    def match_template_3(template: str, arg1: str, arg2: str) -> bool:
        return llm_match_template_impl(template, arg1, arg2)

    def match_template_4(template: str, arg1: str, arg2: str, arg3: str) -> bool:
        return llm_match_template_impl(template, arg1, arg2, arg3)

    for name, func in [
        ("match_template_2", match_template_2),
        ("match_template_3", match_template_3),
        ("match_template", match_template_3),      # Default to 3-arg (template + 2 values)
        ("llm_match_template", match_template_3),  # Alias
        ("match_template_4", match_template_4),
    ]:
        try:
            connection.create_function(name, func, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")


def clear_agg_cache():
    """Clear the aggregate result cache."""
    global _agg_cache
    _agg_cache.clear()


def get_agg_cache_stats() -> Dict[str, Any]:
    """Get aggregate cache statistics."""
    return {
        "cached_entries": len(_agg_cache),
        "functions": ["llm_summarize", "llm_classify", "llm_sentiment", "llm_themes", "llm_agg"]
    }
