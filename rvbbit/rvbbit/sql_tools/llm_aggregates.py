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


def _call_llm_direct(
    prompt: str,
    model: str = None,
    max_tokens: int = 500
) -> str:
    """
    Call LLM via bodybuilder's direct body mode (bypasses planner).

    This still goes through bodybuilder for cost tracking and logging,
    but skips the planner step that tries to parse the request as JSON.
    """
    from ..traits.bodybuilder import bodybuilder
    from ..session_naming import generate_woodland_id
    from ..config import get_config

    config = get_config()

    # Use default model if not specified
    if not model:
        model = config.default_model

    # Generate session info
    woodland_id = generate_woodland_id()
    session_id = f"sql-agg-{woodland_id}"

    # Build explicit body (bypasses planner)
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0
    }

    try:
        response = bodybuilder(
            body=body,  # Direct mode - no planner!
            _session_id=session_id,
            _cell_name=f"agg_{woodland_id[:8]}",
            _cascade_id="sql_aggregate",
        )

        if response.get("_route") == "error":
            return f"ERROR: {response.get('error', 'Unknown error')[:100]}"

        return response.get("result") or response.get("content") or ""

    except Exception as e:
        return f"ERROR: {str(e)[:100]}"


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
