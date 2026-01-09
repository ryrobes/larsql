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
- Calls cascade-based SQL functions via the registry

The actual implementations are RVBBIT cascades in traits/semantic_sql/.
This module provides thin wrappers that execute those cascades.
"""

import json
import hashlib
import re
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================================
# Cascade Executor - Primary execution path
# ============================================================================

def _execute_cascade(
    function_name: str,
    args: Dict[str, Any],
    fallback: callable = None
) -> Any:
    """
    Execute a semantic SQL function via its cascade definition.

    This is the primary execution path. Cascades are discovered from
    RVBBIT_ROOT/traits/semantic_sql/*.cascade.yaml.

    Args:
        function_name: The SQL function name (e.g., "semantic_consensus")
        args: Arguments to pass to the cascade
        fallback: Optional fallback function if cascade not found

    Returns:
        Cascade result, or fallback result if cascade not found
    """
    try:
        from ..semantic_sql.registry import (
            get_sql_function,
            execute_sql_function_sync,
        )

        fn = get_sql_function(function_name)
        if fn:
            return execute_sql_function_sync(function_name, args)

        # Function not in registry - try fallback
        if fallback:
            return fallback(**args)

        raise ValueError(f"SQL function not found: {function_name}")

    except ImportError as e:
        # Registry not available - use fallback
        if fallback:
            return fallback(**args)
        raise ValueError(f"Cascade registry not available: {e}")
    except Exception as e:
        # Execution failed - try fallback
        if fallback:
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Cascade execution failed for {function_name}: {e}, using fallback")
            return fallback(**args)
        raise


def _call_llm(
    prompt: str,
    model: str | None = None,
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

    # Track LLM call for SQL Trail (fire-and-forget)
    try:
        from ..caller_context import get_caller_id
        from ..sql_trail import increment_llm_call
        caller_id = get_caller_id()
        if caller_id:
            increment_llm_call(caller_id)
    except Exception:
        pass  # Non-blocking

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
    - Invalid escape sequences (like backslash-quote from SQL or random backslash-x)
    - Excessive whitespace
    - Non-printable characters

    The goal is to preserve semantic meaning while removing characters that
    could break JSON parsing in the LLM response.
    """
    if not text:
        return ""

    # Remove null bytes
    text = text.replace('\x00', '')

    # Fix invalid escape sequences that break JSON parsing
    # JSON only allows: \" \\ \/ \b \f \n \r \t \uXXXX
    # Replace backslash followed by invalid escape char with just the char
    # This handles SQL escapes like \' and random \q \a etc.
    text = re.sub(r"\\(?![\"\\\/bfnrtu])", "", text)

    # Also handle doubled single quotes from SQL ('' -> ')
    text = text.replace("''", "'")

    # Remove other control characters except newline/tab
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Remove any remaining non-printable/weird unicode
    text = re.sub(r'[\x80-\x9f]', '', text)

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

    Executes via cascade: traits/semantic_sql/summarize.cascade.yaml

    Args:
        values_json: JSON array of text values (from LIST() in SQL)
        prompt: Custom prompt (default: generic summarization)
        max_items: Maximum items to include (samples if exceeded)
        strategy: "direct" (one call), "map_reduce" (hierarchical), "sample" (random sample)
        separator: Separator between items in prompt
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        Summary text

    Example SQL:
        SELECT SUMMARIZE(review_text) as summary
        FROM reviews
        GROUP BY category
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_summarize",
            {"texts": values_json, "prompt": prompt},
            fallback=lambda **kw: _llm_summarize_fallback(
                kw.get("texts", ""), kw.get("prompt", ""), max_items, strategy, separator, use_cache
            )
        )
        return result if result else "No data to summarize."
    except Exception as e:
        return _llm_summarize_fallback(values_json, prompt, max_items, strategy, separator, use_cache)


def _llm_summarize_fallback(
    values_json: str,
    prompt: Optional[str] = None,
    max_items: int = 200,
    strategy: str = "direct",
    separator: str = "\n---\n",
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "No data to summarize."

    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("summarize", prompt or "default", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    if not prompt:
        prompt = "Summarize the following items into a concise summary that captures the key themes and patterns:"

    if len(values) > max_items:
        if strategy == "sample":
            import random
            values = random.sample(values, max_items)
        elif strategy == "map_reduce":
            return _map_reduce_summarize(values, prompt)
        else:
            values = values[:max_items]
            prompt = f"{prompt}\n\n(Note: Showing {max_items} of {len(values)} total items)"

    combined_text = separator.join(f"- {v}" for v in values)
    full_prompt = f"{prompt}\n\n{combined_text}\n\nSummary:"

    result = _call_llm(full_prompt)

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
    Executes via cascade: traits/semantic_sql/classify.cascade.yaml

    Args:
        values_json: JSON array of text values
        categories: Comma-separated list of valid categories
        prompt: Custom classification prompt
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        One of the category labels

    Example SQL:
        SELECT CLASSIFY(review_text, 'positive,negative,mixed')
        FROM reviews
        GROUP BY product_id
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_classify_collection",
            {"texts": values_json, "categories": categories, "prompt": prompt},
            fallback=lambda **kw: _llm_classify_fallback(
                kw.get("texts", ""), kw.get("categories", ""), kw.get("prompt", ""), use_cache
            )
        )
        return result if result else "unknown"
    except Exception as e:
        return _llm_classify_fallback(values_json, categories, prompt, use_cache)


def _llm_classify_fallback(
    values_json: str,
    categories: str,
    prompt: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
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

    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("classify", f"{categories}|{prompt or ''}", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    if len(values) > 100:
        import random
        values = random.sample(values, 100)

    if not prompt:
        user_prompt = f"Based on the following items, classify the overall group into exactly one of these categories: {categories}"
    else:
        user_prompt = f"{prompt}\n\nValid categories: {categories}"

    combined_text = "\n".join(f"- {v}" for v in values[:50])

    full_prompt = f"""{user_prompt}

Items:
{combined_text}

Respond with ONLY the category name, nothing else."""

    result = _call_llm(full_prompt)

    result = result.strip().lower()

    valid_cats = [c.strip().lower() for c in categories.split(',')]
    if result not in valid_cats:
        for cat in valid_cats:
            if cat in result:
                result = cat
                break

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def classify_single_impl(
    text: str,
    topics_json: str,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Classify a single text into one of the given topics.

    This is a SCALAR function for classifying individual rows.

    Args:
        text: Single text to classify
        topics_json: JSON array of topic labels
        model: Model override
        use_cache: Whether to cache results

    Returns:
        The topic label that best matches the text

    Example SQL:
        SELECT classify_single_impl(observed, '["topic1", "topic2", "topic3"]') as topic
        FROM bigfoot
    """
    import hashlib

    if not text or not text.strip():
        return "unknown"

    # Parse topics
    try:
        topics = json.loads(topics_json)
        if not isinstance(topics, list):
            topics = [topics]
    except json.JSONDecodeError:
        topics = [t.strip() for t in topics_json.split(',')]

    if not topics:
        return "unknown"

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        cache_key = _agg_cache_key("classify_single", topics_json, text_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    topics_str = ", ".join(f'"{t}"' for t in topics)

    # Truncate text if too long
    text_sample = text[:1000] if len(text) > 1000 else text

    full_prompt = f"""Classify this text into exactly ONE of these topics: [{topics_str}]

Text: {text_sample}

Respond with ONLY the topic name that best matches, nothing else."""

    result = _call_llm_direct(full_prompt, model=model, max_tokens=50)

    # Clean up result
    result = result.strip().strip('"').strip("'")

    # Validate - find best match
    result_lower = result.lower()
    for topic in topics:
        if topic.lower() == result_lower or topic.lower() in result_lower:
            result = topic
            break
    else:
        # If no exact match, return first topic as fallback
        result = topics[0] if topics else "unknown"

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
    Executes via cascade: traits/semantic_sql/sentiment.cascade.yaml

    Args:
        values_json: JSON array of text values
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        Sentiment score as float

    Example SQL:
        SELECT SENTIMENT(review_text) as sentiment_score
        FROM reviews
        GROUP BY product_id
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_sentiment",
            {"texts": values_json},
            fallback=lambda **kw: _llm_sentiment_fallback(kw.get("texts", ""), use_cache)
        )
        try:
            return float(result) if result else 0.0
        except (ValueError, TypeError):
            return 0.0
    except Exception as e:
        return _llm_sentiment_fallback(values_json, use_cache)


def _llm_sentiment_fallback(
    values_json: str,
    use_cache: bool = True
) -> float:
    """Fallback implementation when cascade not available."""
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

    if len(values) > 50:
        import random
        values = random.sample(values, 50)

    combined_text = "\n".join(f"- {v}" for v in values)

    prompt = f"""Analyze the overall sentiment of these items on a scale from -1.0 (very negative) to 1.0 (very positive).

Items:
{combined_text}

Respond with ONLY a decimal number between -1.0 and 1.0, nothing else."""

    result = _call_llm(prompt)

    try:
        score = float(result.strip())
        score = max(-1.0, min(1.0, score))
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
    Executes via cascade: traits/semantic_sql/themes.cascade.yaml

    Args:
        values_json: JSON array of text values
        max_themes: Maximum number of themes to extract
        prompt: Custom prompt
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        JSON array of themes (as string)

    Example SQL:
        SELECT THEMES(review_text, 5) as themes
        FROM reviews
        GROUP BY product_id
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_themes",
            {"texts": values_json, "num_topics": max_themes, "prompt": prompt},
            fallback=lambda **kw: _llm_themes_fallback(
                kw.get("texts", ""), kw.get("num_topics", 5), kw.get("prompt", ""), use_cache
            )
        )
        return result if result else "[]"
    except Exception as e:
        return _llm_themes_fallback(values_json, max_themes, prompt, use_cache)


def _llm_themes_fallback(
    values_json: str,
    max_themes: int = 5,
    prompt: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
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

    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("themes", str(max_themes), values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    if len(values) > 100:
        import random
        values = random.sample(values, 100)

    combined_text = "\n".join(f"- {v}" for v in values[:50])

    if not prompt:
        user_prompt = f"Extract the {max_themes} most common themes or topics from these items."
    else:
        user_prompt = prompt

    full_prompt = f"""{user_prompt}

Items:
{combined_text}

Respond with a JSON array of {max_themes} theme strings, like: ["theme1", "theme2", "theme3"]
Return ONLY the JSON array, nothing else."""

    result = _call_llm(full_prompt)

    result = result.strip()
    if not result.startswith('['):
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            result = match.group(0)
        else:
            result = '[]'

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
    text: str,
    criteria: str,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """
    Check if text matches semantic criteria. Returns boolean.

    Use in WHERE clauses for semantic filtering:

        SELECT * FROM products
        WHERE llm_matches(description, 'is eco-friendly or sustainable');

    Args:
        text: The text to evaluate (FIRST parameter - matches cascade YAML)
        criteria: What to check for (e.g., "mentions quality issues") (SECOND parameter)
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if text matches criteria, False otherwise

    PHASE 3: Now routes through semantic_matches cascade for full RVBBIT features!
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

    # PHASE 3: Route through cascade instead of direct LLM call
    try:
        result = _execute_cascade(
            "semantic_matches",
            {"text": text, "criterion": criteria},
            fallback=lambda **kw: _llm_matches_fallback(
                kw.get("text", ""), kw.get("criterion", ""), model, use_cache
            )
        )

        # Parse result (cascade returns "true"/"false" string or boolean)
        if isinstance(result, bool):
            is_match = result
        else:
            result_str = str(result).strip().lower()
            is_match = result_str in ("yes", "true", "1", "y")

        # Cache result
        if use_cache:
            _cache_set(_agg_cache, cache_key, "true" if is_match else "false", ttl=None)

        return is_match

    except Exception as e:
        # Fallback to direct implementation if cascade fails
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Cascade execution failed for semantic_matches: {e}, using fallback")
        return _llm_matches_fallback(text, criteria, model, use_cache)


def _llm_matches_fallback(
    text: str,
    criteria: str,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """Fallback implementation when cascade not available."""
    prompt = f"""Does the following text match this criteria: "{criteria}"?

Text: {text[:2000]}

Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=10)
    result_lower = result.strip().lower()

    # Parse yes/no
    return result_lower in ("yes", "true", "1", "y")


def llm_score_impl(
    text: str,
    criteria: str,
    model: str | None = None,
    use_cache: bool = True
) -> float:
    """
    Score how well text matches semantic criteria. Returns 0.0-1.0.

    Use for ranking or threshold filtering:

        SELECT *, llm_score(description, 'relevance to sustainability') as score
        FROM products
        WHERE llm_score(description, 'relevance to sustainability') > 0.7
        ORDER BY score DESC;

    Args:
        text: The text to evaluate (FIRST parameter - matches cascade YAML)
        criteria: What to score against (e.g., "relevance to machine learning") (SECOND parameter)
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        Float between 0.0 (no match) and 1.0 (perfect match)

    PHASE 3: Now routes through semantic_score cascade for full RVBBIT features!
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

    # PHASE 3: Route through cascade instead of direct LLM call
    try:
        result = _execute_cascade(
            "semantic_score",
            {"text": text, "criterion": criteria},
            fallback=lambda **kw: _llm_score_fallback(
                kw.get("text", ""), kw.get("criterion", ""), model, use_cache
            )
        )

        # Parse score
        try:
            score = float(result)
            score = max(0.0, min(1.0, score))  # Clamp to valid range
        except (ValueError, TypeError):
            score = 0.0

        # Cache result
        if use_cache:
            _cache_set(_agg_cache, cache_key, str(score), ttl=None)

        return score

    except Exception as e:
        # Fallback to direct implementation if cascade fails
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Cascade execution failed for semantic_score: {e}, using fallback")
        return _llm_score_fallback(text, criteria, model, use_cache)


def _llm_score_fallback(
    text: str,
    criteria: str,
    model: str | None = None,
    use_cache: bool = True
) -> float:
    """Fallback implementation when cascade not available."""
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

    return score


def llm_match_pair_impl(
    left: str,
    right: str,
    relationship: str = "same entity",
    model: str | None = None,
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

    # Prefer cascade execution for full RVBBIT logging/tracing/caching.
    try:
        result = _execute_cascade(
            "semantic_match_pair",
            {"left": left, "right": right, "relationship": relationship},
            fallback=None,
        )
        if isinstance(result, bool):
            is_match = result
        else:
            is_match = str(result).strip().lower() in ("true", "yes", "1", "y")

        if use_cache:
            _cache_set(_agg_cache, cache_key, "true" if is_match else "false", ttl=None)
        return is_match
    except Exception:
        pass

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


def llm_implies_impl(
    premise: str,
    conclusion: str,
    context: str | None = None,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """
    Check if one statement semantically implies another.

    Use for logical inference checking:

        SELECT title, observed
        FROM bigfoot
        WHERE implies(title, 'visual contact was made')

        -- Or in WHERE clause
        WHERE title IMPLIES 'the witness saw something'

    Args:
        premise: The premise statement (if this is true...)
        conclusion: The conclusion to check (...does this follow?)
        context: Optional context to help with interpretation
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if the premise implies the conclusion

    PHASE 3: Now routes through semantic_implies cascade for full RVBBIT features!
    """
    if not premise or not conclusion:
        return False

    premise = _sanitize_text(str(premise))
    conclusion = _sanitize_text(str(conclusion))

    if not premise or not conclusion:
        return False

    # Check cache - order matters for implication
    if use_cache:
        from .udf import _cache_get, _cache_set
        cache_key = _agg_cache_key("implies", f"{premise[:100]}|{conclusion[:100]}", context or "")
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached.lower() == "true"

    # PHASE 3: Route through cascade instead of direct LLM call
    try:
        result = _execute_cascade(
            "semantic_implies",
            {"premise": premise, "conclusion": conclusion},
            fallback=lambda **kw: _llm_implies_fallback(
                kw.get("premise", ""), kw.get("conclusion", ""), context, model, use_cache
            )
        )

        # Parse result
        if isinstance(result, bool):
            is_implied = result
        else:
            result_lower = str(result).strip().lower()
            is_implied = result_lower in ("yes", "true", "1", "y")

        if use_cache:
            _cache_set(_agg_cache, cache_key, "true" if is_implied else "false", ttl=None)

        return is_implied

    except Exception as e:
        # Fallback to direct implementation if cascade fails
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Cascade execution failed for semantic_implies: {e}, using fallback")
        return _llm_implies_fallback(premise, conclusion, context, model, use_cache)


def _llm_implies_fallback(
    premise: str,
    conclusion: str,
    context: str | None = None,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """Fallback implementation when cascade not available."""
    context_str = f"\nContext: {context}" if context else ""

    prompt = f"""Does the first statement logically imply or entail the second statement?
{context_str}
Statement 1 (premise): {premise[:500]}
Statement 2 (conclusion): {conclusion[:500]}

If Statement 1 is true, would Statement 2 necessarily or very likely be true?
Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm(prompt, model=model)
    result_lower = result.strip().lower()

    return result_lower in ("yes", "true", "1", "y")


def llm_contradicts_impl(
    statement1: str,
    statement2: str,
    context: str | None = None,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """
    Check if two statements contradict each other.

    Use for finding inconsistencies:

        SELECT title, observed
        FROM bigfoot
        WHERE contradicts(title, observed)

        -- Find reports where title contradicts observation
        WHERE title CONTRADICTS observed

    Args:
        statement1: First statement
        statement2: Second statement
        context: Optional context to help with interpretation
        model: Optional model override
        use_cache: Whether to cache results (default True)

    Returns:
        True if the statements contradict each other

    PHASE 3: Now routes through semantic_contradicts cascade for full RVBBIT features!
    """
    if not statement1 or not statement2:
        return False

    statement1 = _sanitize_text(str(statement1))
    statement2 = _sanitize_text(str(statement2))

    if not statement1 or not statement2:
        return False

    # Check cache - order-independent for contradiction
    if use_cache:
        from .udf import _cache_get, _cache_set
        pair_key = "|".join(sorted([statement1[:100], statement2[:100]]))
        cache_key = _agg_cache_key("contradicts", pair_key, context or "")
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached.lower() == "true"

    # PHASE 3: Route through cascade instead of direct LLM call
    try:
        result = _execute_cascade(
            "semantic_contradicts",
            {"text_a": statement1, "text_b": statement2},
            fallback=lambda **kw: _llm_contradicts_fallback(
                kw.get("text_a", ""), kw.get("text_b", ""), context, model, use_cache
            )
        )

        # Parse result
        if isinstance(result, bool):
            is_contradiction = result
        else:
            result_lower = str(result).strip().lower()
            is_contradiction = result_lower in ("yes", "true", "1", "y")

        if use_cache:
            _cache_set(_agg_cache, cache_key, "true" if is_contradiction else "false", ttl=None)

        return is_contradiction

    except Exception as e:
        # Fallback to direct implementation if cascade fails
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Cascade execution failed for semantic_contradicts: {e}, using fallback")
        return _llm_contradicts_fallback(statement1, statement2, context, model, use_cache)


def _llm_contradicts_fallback(
    statement1: str,
    statement2: str,
    context: str | None = None,
    model: str | None = None,
    use_cache: bool = True
) -> bool:
    """Fallback implementation when cascade not available."""
    context_str = f"\nContext: {context}" if context else ""

    prompt = f"""Do these two statements contradict each other? That is, can they both be true at the same time?
{context_str}
Statement 1: {statement1[:500]}
Statement 2: {statement2[:500]}

If they contradict (cannot both be true), answer "yes".
If they are compatible (can both be true), answer "no".
Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm(prompt, model=model)
    result_lower = result.strip().lower()

    return result_lower in ("yes", "true", "1", "y")


def llm_match_template_impl(
    template: str,
    *args,
    model: str | None = None,
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

    # Prefer cascade execution for full RVBBIT logging/tracing/caching.
    try:
        result = _execute_cascade(
            "semantic_match_template",
            {"statement": filled},
            fallback=None,
        )
        if isinstance(result, bool):
            is_true = result
        else:
            is_true = str(result).strip().lower() in ("true", "yes", "1", "y")

        if use_cache:
            _cache_set(_agg_cache, cache_key, "true" if is_true else "false", ttl=None)
        return is_true
    except Exception:
        pass

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


def llm_semantic_case_impl(
    text: str,
    *args,
    model: str | None = None,
    use_cache: bool = True
) -> str:
    """
    Evaluate text against multiple semantic conditions, return first match.

    Makes a SINGLE LLM call that checks all conditions at once - much more
    efficient than chained CASE WHEN with multiple matches() calls.

    Args format: condition1, result1, condition2, result2, ..., [default]
    - Pairs of (condition, result)
    - Last unpaired arg is the default value

    Example:
        semantic_case(description,
            'mentions sustainability', 'eco',
            'mentions performance', 'performance',
            'mentions luxury', 'premium',
            'standard'  -- default
        )

    Returns the result for the FIRST matching condition, or default.
    """
    if not text or not args:
        return args[-1] if args else ""

    text = _sanitize_text(str(text))
    if not text:
        return args[-1] if args else ""

    # Parse condition/result pairs and default
    pairs = []
    default = ""

    # Check if odd number of args (last is default)
    if len(args) % 2 == 1:
        default = str(args[-1])
        pair_args = args[:-1]
    else:
        pair_args = args
        default = ""

    for i in range(0, len(pair_args), 2):
        condition = str(pair_args[i])
        result = str(pair_args[i + 1])
        pairs.append((condition, result))

    if not pairs:
        return default

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        # Cache key from text + all conditions
        conditions_key = "|".join(f"{c}:{r}" for c, r in pairs)
        cache_key = _agg_cache_key("semantic_case", conditions_key, text[:200])
        cached = _cache_get(_agg_cache, cache_key)
        if cached is not None:
            return cached

    # Build prompt - single LLM call for all conditions
    conditions_text = "\n".join(
        f'{i+1}. If text "{cond}" → return exactly: {result}'
        for i, (cond, result) in enumerate(pairs)
    )

    prompt = f"""Evaluate this text against the conditions below IN ORDER. Return the result for the FIRST matching condition.

Text: {text[:1000]}

Conditions (check in order, return first match):
{conditions_text}

Default (if no conditions match): {default or 'none'}

Return ONLY the exact result value, nothing else."""

    result = _call_llm(prompt, model=model)
    result = result.strip().strip('"\'')

    # Validate result is one of the expected values
    valid_results = [r for _, r in pairs] + ([default] if default else [])
    if result not in valid_results:
        # Try to find closest match
        result_lower = result.lower()
        for valid in valid_results:
            if valid.lower() in result_lower or result_lower in valid.lower():
                result = valid
                break
        else:
            # Fall back to default
            result = default or valid_results[0] if valid_results else ""

    # Cache result
    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


# ============================================================================
# Semantic Clustering Aggregates
# ============================================================================

def llm_dedupe_impl(
    values_json: str,
    criteria: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Deduplicate values by semantic similarity.

    Returns JSON array of unique representatives (one per semantic cluster).
    Executes via cascade: traits/semantic_sql/dedupe.cascade.yaml

    Args:
        values_json: JSON array of text values to deduplicate
        criteria: Description of what makes items "the same" (default: "same entity")
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        JSON array of deduplicated representative values

    Example SQL:
        SELECT DEDUPE(company_name) FROM suppliers
        -- Returns: ["IBM", "Microsoft", "Google"]
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_dedupe",
            {"texts": values_json, "criteria": criteria or "same entity"},
            fallback=lambda **kw: _llm_dedupe_fallback(kw.get("texts", ""), kw.get("criteria", ""), use_cache)
        )
        return result if result else "[]"
    except Exception as e:
        return _llm_dedupe_fallback(values_json, criteria, use_cache)


def _llm_dedupe_fallback(
    values_json: str,
    criteria: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
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

    if len(values) == 1:
        return json.dumps(values)

    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("dedupe", criteria or "same", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    criteria = criteria or "the same entity or concept"

    if len(values) <= 50:
        items_list = "\n".join(f"- {v}" for v in values)
        prompt = f"""Deduplicate these items by semantic similarity. Group items that represent {criteria}.
Return ONLY the unique representatives (one per group).

Items:
{items_list}

Return a JSON array of the unique representative values.
Return ONLY the JSON array, nothing else."""
        result = _call_llm(prompt)
    else:
        import random
        sampled = random.sample(values, 50)
        items_list = "\n".join(f"- {v}" for v in sampled)
        prompt = f"""Deduplicate these items by semantic similarity. Group items that represent {criteria}.
Return ONLY the unique representatives (one per group).

Items (sample of {len(values)} total):
{items_list}

Return a JSON array of the unique representative values.
Return ONLY the JSON array, nothing else."""
        result = _call_llm(prompt)

    result = result.strip()
    if not result.startswith('['):
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            result = match.group(0)
        else:
            result = json.dumps(values[:10])

    try:
        json.loads(result)
    except json.JSONDecodeError:
        result = json.dumps(values[:10])

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_cluster_impl(
    values_json: str,
    num_clusters: Optional[int] = None,
    criteria: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Cluster values by semantic similarity.

    Returns JSON object mapping each value to its cluster label.
    Executes via cascade: traits/semantic_sql/cluster.cascade.yaml

    Args:
        values_json: JSON array of text values to cluster
        num_clusters: Suggested number of clusters (auto-determined if not specified)
        criteria: Description of how to cluster (e.g., "by topic", "by sentiment")
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        JSON object: {"value1": "cluster_label1", "value2": "cluster_label2", ...}

    Example SQL:
        SELECT CLUSTER(category, 5, 'by product type') FROM products
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_cluster",
            {"values": values_json, "num_clusters": num_clusters, "criterion": criteria},
            fallback=lambda **kw: _llm_cluster_fallback(
                kw.get("values", ""), kw.get("num_clusters"), kw.get("criterion", ""), use_cache
            )
        )
        if result is None:
            return "{}"
        # Cascade may return dict or string - ensure we return JSON string
        if isinstance(result, dict):
            return json.dumps(result)
        return result
    except Exception as e:
        return _llm_cluster_fallback(values_json, num_clusters, criteria, use_cache)


def _llm_cluster_fallback(
    values_json: str,
    num_clusters: Optional[int] = None,
    criteria: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "{}"

    if len(values) == 1:
        return json.dumps({values[0]: values[0]})

    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("cluster", f"{num_clusters or 'auto'}_{criteria or 'semantic'}", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    criteria = criteria or "semantic similarity"
    cluster_hint = f"into approximately {num_clusters} groups" if num_clusters else "into natural groupings"

    working_values = values
    if len(values) > 100:
        import random
        working_values = random.sample(values, 100)

    items_list = "\n".join(f"- {v}" for v in working_values)

    prompt = f"""Cluster these items {cluster_hint} based on {criteria}.

Items:
{items_list}

Return a JSON object mapping each item to its cluster label.
Use short, descriptive cluster labels.
Example: {{"item1": "cluster_a", "item2": "cluster_a", "item3": "cluster_b"}}
Return ONLY the JSON object, nothing else."""

    result = _call_llm(prompt)

    result = result.strip()
    if not result.startswith('{'):
        match = re.search(r'\{.*?\}', result, re.DOTALL)
        if match:
            result = match.group(0)
        else:
            result = json.dumps({v: v for v in working_values})

    try:
        parsed = json.loads(result)
        if not isinstance(parsed, dict):
            result = json.dumps({v: v for v in working_values})
    except json.JSONDecodeError:
        result = json.dumps({v: v for v in working_values})

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_cluster_label_impl(
    value: str,
    all_values_json: str,
    num_clusters: Optional[int] = None,
    criteria: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Get the cluster label for a single value given all values.

    This is the scalar version used for GROUP BY MEANING().
    It clusters all values and returns the label for the specific value.

    Args:
        value: The specific value to get cluster label for
        all_values_json: JSON array of all values in the group
        num_clusters: Suggested number of clusters
        criteria: Description of how to cluster
        model: Model override
        use_cache: Whether to cache

    Returns:
        Cluster label string for the given value
    """
    clusters_json = llm_cluster_impl(all_values_json, num_clusters, criteria, model, use_cache)

    try:
        clusters = json.loads(clusters_json)
        if isinstance(clusters, dict):
            # Direct lookup
            if value in clusters:
                return clusters[value]
            # Try case-insensitive
            for k, v in clusters.items():
                if k.lower() == value.lower():
                    return v
        return value  # Fallback to original value
    except json.JSONDecodeError:
        return value


def llm_consensus_impl(
    values_json: str,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Find the consensus or common ground among a collection of texts.

    Returns a summary of what most items agree on or have in common.
    Executes via cascade: traits/semantic_sql/consensus.cascade.yaml

    Args:
        values_json: JSON array of text values
        prompt: Custom prompt for what kind of consensus to find
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        String describing the consensus view or common ground

    Example SQL:
        SELECT state, CONSENSUS(observed) as common_patterns
        FROM bigfoot
        GROUP BY state
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_consensus",
            {"texts": values_json, "prompt": prompt},
            fallback=lambda **kw: _llm_consensus_fallback(kw.get("texts", ""), kw.get("prompt", ""), use_cache)
        )
        return result if result else "No clear consensus found"
    except Exception as e:
        # Fall through to fallback
        return _llm_consensus_fallback(values_json, prompt, use_cache)


def _llm_consensus_fallback(
    values_json: str,
    prompt: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
    try:
        values = json.loads(values_json)
        if not isinstance(values, list):
            values = [values]
    except json.JSONDecodeError:
        values = [values_json]

    values = _sanitize_values(values)
    values = [v for v in values if v]

    if not values:
        return "No data to analyze"

    if len(values) == 1:
        return values[0]

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("consensus", prompt or "common", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    # Sample if too many
    working_values = values
    if len(values) > 50:
        import random
        working_values = random.sample(values, 50)

    items_list = "\n".join(f"- {v[:500]}" for v in working_values)

    if prompt:
        user_prompt = f"""Analyze these items and find: {prompt}

Items:
{items_list}

Identify what most items agree on or have in common. Focus on shared themes, patterns, or perspectives.
Return a clear summary of the consensus view."""
    else:
        user_prompt = f"""Analyze these items and find what they have in common or agree on:

Items:
{items_list}

Identify:
1. Common themes or patterns that appear across multiple items
2. Points of agreement or shared perspectives
3. The overall consensus view

Return a concise summary of what most items agree on."""

    result = _call_llm(user_prompt)

    # Clean up
    result = result.strip()
    if not result:
        result = "No clear consensus found"

    if use_cache:
        _cache_set(_agg_cache, cache_key, result, ttl=None)

    return result


def llm_outliers_impl(
    values_json: str,
    num_outliers: Optional[int] = None,
    criteria: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """
    Find outliers or unusual items in a collection.

    Returns JSON array of items that stand out from the norm.
    Executes via cascade: traits/semantic_sql/outliers.cascade.yaml

    Args:
        values_json: JSON array of text values
        num_outliers: Maximum number of outliers to return (default: 5)
        criteria: Description of what makes something unusual
        model: Model override (ignored - cascade controls model)
        use_cache: Whether to cache results

    Returns:
        JSON array of outlier items with explanations

    Example SQL:
        SELECT OUTLIERS(observed, 3) as unusual_sightings
        FROM bigfoot

        SELECT state, OUTLIERS(observed, 5, 'scientifically implausible')
        FROM bigfoot
        GROUP BY state
    """
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_outliers",
            {"texts": values_json, "num_outliers": num_outliers or 5, "criteria": criteria},
            fallback=lambda **kw: _llm_outliers_fallback(
                kw.get("texts", ""), kw.get("num_outliers"), kw.get("criteria", ""), use_cache
            )
        )
        return result if result else "[]"
    except Exception as e:
        return _llm_outliers_fallback(values_json, num_outliers, criteria, use_cache)


def _llm_outliers_fallback(
    values_json: str,
    num_outliers: Optional[int] = None,
    criteria: Optional[str] = None,
    use_cache: bool = True
) -> str:
    """Fallback implementation when cascade not available."""
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

    if len(values) <= 3:
        return "[]"

    num_outliers = num_outliers or 5
    num_outliers = min(num_outliers, len(values) // 2, 10)

    # Check cache
    if use_cache:
        from .udf import _cache_get, _cache_set
        values_hash = _hash_values(values)
        cache_key = _agg_cache_key("outliers", f"{num_outliers}_{criteria or 'unusual'}", values_hash)
        cached = _cache_get(_agg_cache, cache_key)
        if cached:
            return cached

    working_values = values
    if len(values) > 50:
        import random
        working_values = random.sample(values, 50)

    items_list = "\n".join(f"{i+1}. {v[:500]}" for i, v in enumerate(working_values))

    if criteria:
        user_prompt = f"""Find the {num_outliers} most unusual items in this list based on: {criteria}

Items:
{items_list}

For each outlier, explain WHY it stands out.
Return a JSON array of objects with "item" and "reason" keys.
Example: [{{"item": "...", "reason": "..."}}]
Return ONLY the JSON array."""
    else:
        user_prompt = f"""Find the {num_outliers} most unusual or atypical items in this list.

Items:
{items_list}

Look for items that:
- Don't fit the common pattern
- Are surprisingly different from the majority
- Contain unexpected or rare characteristics

For each outlier, explain WHY it stands out.
Return a JSON array of objects with "item" and "reason" keys.
Example: [{{"item": "...", "reason": "..."}}]
Return ONLY the JSON array."""

    result = _call_llm(user_prompt)

    result = result.strip()
    if not result.startswith('['):
        match = re.search(r'\[.*\]', result, re.DOTALL)
        if match:
            result = match.group(0)
        else:
            result = "[]"

    try:
        parsed = json.loads(result)
        if not isinstance(parsed, list):
            result = "[]"
    except json.JSONDecodeError:
        result = "[]"

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

def register_llm_aggregates(connection, config: Dict[str, Any] | None = None):
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
    # NEW: Updated to (text, criteria) order to match cascade YAMLs
    def matches_2(text: str, criteria: str) -> bool:
        return llm_matches_impl(text, criteria)

    for name in ["llm_matches", "matches"]:
        try:
            connection.create_function(name, matches_2, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # LLM_SCORE / SCORE - semantic scoring (0.0-1.0)
    # NEW: Updated to (text, criteria) order to match cascade YAMLs
    def score_2(text: str, criteria: str) -> float:
        return llm_score_impl(text, criteria)

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

    # ========== IMPLIES - logical implication ==========

    def implies_2(premise: str, conclusion: str) -> bool:
        return llm_implies_impl(premise, conclusion)

    def implies_3(premise: str, conclusion: str, context: str) -> bool:
        return llm_implies_impl(premise, conclusion, context)

    for name, func in [
        ("implies", implies_2),
        ("implies_3", implies_3),
        ("llm_implies", implies_2),
    ]:
        try:
            connection.create_function(name, func, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== CONTRADICTS - contradiction detection ==========

    def contradicts_2(stmt1: str, stmt2: str) -> bool:
        return llm_contradicts_impl(stmt1, stmt2)

    def contradicts_3(stmt1: str, stmt2: str, context: str) -> bool:
        return llm_contradicts_impl(stmt1, stmt2, context)

    for name, func in [
        ("contradicts", contradicts_2),
        ("contradicts_3", contradicts_3),
        ("llm_contradicts", contradicts_2),
    ]:
        try:
            connection.create_function(name, func, return_type="BOOLEAN")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

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

    # ========== CLASSIFY_SINGLE - classify single text into one of N topics ==========
    def classify_single_2(text: str, topics_json: str) -> str:
        return classify_single_impl(text, topics_json)

    try:
        connection.create_function("classify_single", classify_single_2, return_type="VARCHAR")
    except Exception as e:
        log.warning(f"Could not register classify_single: {e}")

    # ========== SEMANTIC_CASE - multi-way semantic classification ==========
    # semantic_case(text, cond1, result1, cond2, result2, ..., default)
    # DuckDB needs fixed arity, so we register common variants

    def semantic_case_3(text: str, cond1: str, result1: str) -> str:
        """1 condition, no default"""
        return llm_semantic_case_impl(text, cond1, result1)

    def semantic_case_4(text: str, cond1: str, result1: str, default: str) -> str:
        """1 condition + default"""
        return llm_semantic_case_impl(text, cond1, result1, default)

    def semantic_case_5(text: str, c1: str, r1: str, c2: str, r2: str) -> str:
        """2 conditions, no default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2)

    def semantic_case_6(text: str, c1: str, r1: str, c2: str, r2: str, default: str) -> str:
        """2 conditions + default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2, default)

    def semantic_case_7(text: str, c1: str, r1: str, c2: str, r2: str, c3: str, r3: str) -> str:
        """3 conditions, no default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2, c3, r3)

    def semantic_case_8(text: str, c1: str, r1: str, c2: str, r2: str, c3: str, r3: str, default: str) -> str:
        """3 conditions + default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2, c3, r3, default)

    def semantic_case_9(text: str, c1: str, r1: str, c2: str, r2: str, c3: str, r3: str, c4: str, r4: str) -> str:
        """4 conditions, no default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2, c3, r3, c4, r4)

    def semantic_case_10(text: str, c1: str, r1: str, c2: str, r2: str, c3: str, r3: str, c4: str, r4: str, default: str) -> str:
        """4 conditions + default"""
        return llm_semantic_case_impl(text, c1, r1, c2, r2, c3, r3, c4, r4, default)

    for name, func in [
        ("semantic_case_3", semantic_case_3),
        ("semantic_case_4", semantic_case_4),
        ("semantic_case_5", semantic_case_5),
        ("semantic_case_6", semantic_case_6),
        ("semantic_case_7", semantic_case_7),
        ("semantic_case_8", semantic_case_8),
        ("semantic_case_9", semantic_case_9),
        ("semantic_case_10", semantic_case_10),
        ("llm_case_3", semantic_case_3),
        ("llm_case_4", semantic_case_4),
        ("llm_case_5", semantic_case_5),
        ("llm_case_6", semantic_case_6),
        ("llm_case_7", semantic_case_7),
        ("llm_case_8", semantic_case_8),
        ("llm_case_9", semantic_case_9),
        ("llm_case_10", semantic_case_10),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_DEDUPE (Semantic Deduplication) ==========

    def dedupe_1(values_json: str) -> str:
        return llm_dedupe_impl(values_json)

    def dedupe_2(values_json: str, criteria: str) -> str:
        return llm_dedupe_impl(values_json, criteria)

    for name, func in [
        ("llm_dedupe_impl", dedupe_1),
        ("llm_dedupe_impl_2", dedupe_2),
        ("dedupe", dedupe_1),
        ("dedupe_2", dedupe_2),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_CLUSTER (Semantic Clustering) ==========

    def cluster_1(values_json: str) -> str:
        return llm_cluster_impl(values_json)

    def cluster_2(values_json: str, num_clusters: int) -> str:
        return llm_cluster_impl(values_json, num_clusters)

    def cluster_3(values_json: str, num_clusters: int, criteria: str) -> str:
        return llm_cluster_impl(values_json, num_clusters, criteria)

    for name, func in [
        ("llm_cluster_impl", cluster_1),
        ("llm_cluster_impl_2", cluster_2),
        ("llm_cluster_impl_3", cluster_3),
        ("cluster", cluster_1),
        ("cluster_2", cluster_2),
        ("cluster_3", cluster_3),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_CLUSTER_LABEL (For GROUP BY MEANING) ==========

    def cluster_label_2(value: str, all_values_json: str) -> str:
        return llm_cluster_label_impl(value, all_values_json)

    def cluster_label_3(value: str, all_values_json: str, num_clusters: int) -> str:
        return llm_cluster_label_impl(value, all_values_json, num_clusters)

    def cluster_label_4(value: str, all_values_json: str, num_clusters: int, criteria: str) -> str:
        return llm_cluster_label_impl(value, all_values_json, num_clusters, criteria)

    for name, func in [
        ("llm_cluster_label", cluster_label_2),
        ("llm_cluster_label_3", cluster_label_3),
        ("llm_cluster_label_4", cluster_label_4),
        ("meaning", cluster_label_2),
        ("meaning_3", cluster_label_3),
        ("meaning_4", cluster_label_4),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_CONSENSUS (Find Common Ground) ==========

    def consensus_1(values_json: str) -> str:
        return llm_consensus_impl(values_json)

    def consensus_2(values_json: str, prompt: str) -> str:
        return llm_consensus_impl(values_json, prompt)

    for name, func in [
        ("llm_consensus_1", consensus_1),
        ("llm_consensus_2", consensus_2),
        ("consensus", consensus_1),
        ("consensus_2", consensus_2),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")

    # ========== LLM_OUTLIERS (Find Unusual Items) ==========

    def outliers_1(values_json: str) -> str:
        return llm_outliers_impl(values_json)

    def outliers_2(values_json: str, num_outliers: int) -> str:
        return llm_outliers_impl(values_json, num_outliers)

    def outliers_3(values_json: str, num_outliers: int, criteria: str) -> str:
        return llm_outliers_impl(values_json, num_outliers, criteria)

    for name, func in [
        ("llm_outliers_1", outliers_1),
        ("llm_outliers_2", outliers_2),
        ("llm_outliers_3", outliers_3),
        ("outliers", outliers_1),
        ("outliers_2", outliers_2),
        ("outliers_3", outliers_3),
    ]:
        try:
            connection.create_function(name, func, return_type="VARCHAR")
        except Exception as e:
            log.warning(f"Could not register {name}: {e}")


def register_dimension_compute_udfs(connection):
    """
    Register dimension compute UDFs for semantic GROUP BY.

    These functions are called by the dimension rewriter's CTEs.
    They execute the dimension cascade with the values array and return
    a JSON mapping of value -> bucket.

    Each dimension cascade (e.g., topics_dimension, sentiment_dimension)
    gets a {name}_compute function registered.

    IMPORTANT: Uses the same execution path as execute_cascade_udf() for proper
    logging, caller_id propagation, SQL Trail tracking, and caching.
    """
    import json
    import logging
    from rvbbit.semantic_sql.registry import get_sql_function_registry

    log = logging.getLogger(__name__)
    print(f"[dimension_compute] v2026.01.03.A Registering dimension compute UDFs...", flush=True)

    registry = get_sql_function_registry()

    for func_name, entry in registry.items():
        # Only register compute functions for DIMENSION-shaped cascades
        sql_fn = getattr(entry, 'sql_function', {})
        if sql_fn.get('shape', '').upper() != 'DIMENSION':
            continue

        cascade_path = entry.cascade_path
        cascade_id = entry.cascade_id
        compute_name = f"{func_name}_compute"

        # Create compute function for this dimension
        # The function receives: (values_json, ...scalar_args)
        def make_compute_func(cascade_path_inner, func_name_inner, cascade_id_inner):
            def compute_func(values_json: str, *args) -> str:
                """Execute dimension cascade and return mapping JSON."""
                import sys
                import json
                import hashlib

                # Version marker - verify latest code is running
                print(f"[dimension_compute] v2026.01.03.A {func_name_inner} called", flush=True)

                # Import execution infrastructure (same as execute_cascade_udf)
                from rvbbit.session_naming import generate_woodland_id
                from rvbbit.caller_context import get_caller_id
                from rvbbit.sql_trail import register_cascade_execution, increment_cache_hit, increment_cache_miss
                from rvbbit.semantic_sql.executor import _run_cascade_sync, _extract_cascade_output
                from rvbbit.semantic_sql.registry import get_cached_result, set_cached_result

                # Get caller_id from context (set by postgres_server for SQL queries)
                caller_id = get_caller_id()

                # DEBUG: Log caller_id for dimension functions (with flush for immediate output)
                if caller_id:
                    print(f"[dimension_compute] {func_name_inner}: caller_id={caller_id}", flush=True)
                else:
                    print(f"[dimension_compute] {func_name_inner}: WARNING - caller_id is None/empty!", flush=True)
                    # Also log global registry state for debugging
                    from rvbbit.caller_context import _global_caller_registry, _registry_lock
                    with _registry_lock:
                        print(f"[dimension_compute] Global registry contents: {list(_global_caller_registry.keys())}", flush=True)

                # Parse values JSON array
                try:
                    values = json.loads(values_json) if values_json else []
                except json.JSONDecodeError:
                    log.warning(f"[dimension_compute] {func_name_inner}: Failed to parse values JSON")
                    values = []

                if not values:
                    return json.dumps({"mapping": {}})

                # Deduplicate values - no need to send duplicates to the LLM
                # The mapping is keyed by value, so duplicates are redundant
                original_count = len(values)
                unique_values = list(dict.fromkeys(values))  # Preserves order, removes duplicates
                if len(unique_values) < original_count:
                    log.debug(f"[dimension_compute] {func_name_inner}: Deduplicated {original_count} -> {len(unique_values)} unique values")
                values = unique_values

                # Get the cascade's arg definitions to map positional args
                entry_inner = registry.get(func_name_inner)
                if not entry_inner:
                    return json.dumps({"mapping": {}, "error": f"No registry entry for {func_name_inner}"})

                sql_fn_inner = getattr(entry_inner, 'sql_function', {})
                arg_defs = sql_fn_inner.get('args', [])

                # Build input dict for cascade
                # First arg (dimension_source) becomes 'texts' array
                # (Using 'texts' instead of 'values' to avoid conflict with dict.values() in Jinja)
                #
                # INDEX-BASED MAPPING OPTIMIZATION:
                # We pass use_indices=True to tell the cascade to return index-based keys
                # instead of full text keys. This dramatically reduces output token count
                # (from ~50k tokens to ~500 tokens for large text arrays).
                # After cascade returns, we reconstruct text-based keys for SQL lookup.
                cascade_input = {"texts": values, "use_indices": True}

                # Map positional args to named args (skip first which is dimension_source)
                scalar_arg_defs = [a for a in arg_defs if a.get('role') != 'dimension_source']

                for i, arg_val in enumerate(args):
                    if i < len(scalar_arg_defs):
                        arg_name = scalar_arg_defs[i]['name']
                        cascade_input[arg_name] = arg_val

                # Check cache (using same caching as other semantic functions)
                use_cache = sql_fn_inner.get('cache', True)
                if use_cache:
                    found, cached = get_cached_result(func_name_inner, cascade_input)
                    if found:
                        log.debug(f"[dimension_compute] Cache hit for {func_name_inner}")
                        if caller_id:
                            increment_cache_hit(caller_id)
                        return json.dumps(cached) if isinstance(cached, dict) else cached

                # Track cache miss
                if caller_id:
                    increment_cache_miss(caller_id)

                # Generate session ID (consistent with other semantic functions)
                woodland_id = generate_woodland_id()
                session_id = f"dim_{func_name_inner}_{woodland_id}"

                # Register cascade execution for SQL Trail
                if caller_id:
                    print(f"[dimension_compute] Registering cascade: {cascade_id_inner}, session={session_id}, caller_id={caller_id}", flush=True)
                    try:
                        register_cascade_execution(
                            caller_id=caller_id,
                            cascade_id=cascade_id_inner,
                            cascade_path=cascade_path_inner,
                            session_id=session_id,
                            inputs=cascade_input
                        )
                        print(f"[dimension_compute] Successfully registered cascade execution", flush=True)
                    except Exception as reg_e:
                        print(f"[dimension_compute] ERROR registering cascade: {reg_e}", flush=True)
                else:
                    print(f"[dimension_compute] WARNING: No caller_id for cascade {cascade_id_inner}, session={session_id}", flush=True)

                # Execute the cascade with proper caller_id propagation
                print(f"[dimension_compute] Running cascade {cascade_id_inner} with caller_id={caller_id}")
                try:
                    result = _run_cascade_sync(
                        cascade_path_inner,
                        session_id,
                        cascade_input,
                        caller_id=caller_id
                    )

                    # Check if result is None or empty
                    if result is None:
                        log.warning(f"[dimension_compute] {func_name_inner} returned None result")
                        return json.dumps({"mapping": {}, "error": "Cascade returned None"})

                    # Extract the mapping from cascade output
                    output = _extract_cascade_output(result)

                    # Handle None output
                    if output is None:
                        log.warning(f"[dimension_compute] {func_name_inner} extracted output is None. Result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
                        return json.dumps({"mapping": {}, "error": "Cascade output extraction returned None"})

                    if isinstance(output, str):
                        # Try to parse as JSON
                        try:
                            output = json.loads(output)
                        except json.JSONDecodeError:
                            log.warning(f"[dimension_compute] {func_name_inner} output not valid JSON: {output[:500]}")
                            return json.dumps({"mapping": {}, "error": "Output not valid JSON"})

                    if isinstance(output, dict):
                        # Ensure mapping key exists
                        if "mapping" not in output:
                            log.warning(f"[dimension_compute] {func_name_inner} output missing 'mapping' key: {list(output.keys())}")
                            return json.dumps({"mapping": {}, "error": f"Output missing 'mapping' key, got: {list(output.keys())}"})

                        # RECONSTRUCT TEXT-BASED KEYS FROM INDEX-BASED MAPPING
                        # The cascade returns {"mapping": {"0": "Low", "1": "High", ...}}
                        # We need to convert to {"mapping": {"original text 1": "Low", ...}}
                        # so SQL can look up by the actual text value.
                        index_mapping = output.get("mapping", {})
                        text_mapping = {}
                        reconstruction_errors = []

                        for key, value in index_mapping.items():
                            try:
                                idx = int(key)
                                if 0 <= idx < len(values):
                                    text_mapping[values[idx]] = value
                                else:
                                    reconstruction_errors.append(f"Index {idx} out of range (0-{len(values)-1})")
                            except (ValueError, TypeError):
                                # Key is not an integer - might be a text key already (backward compat)
                                # Just pass it through
                                text_mapping[key] = value

                        if reconstruction_errors:
                            log.warning(f"[dimension_compute] {func_name_inner} reconstruction errors: {reconstruction_errors[:5]}")

                        output["mapping"] = text_mapping
                        log.debug(f"[dimension_compute] {func_name_inner}: Reconstructed {len(text_mapping)} text keys from index mapping")

                        # Cache the result (with text-based keys for consistent cache hits)
                        if use_cache:
                            set_cached_result(func_name_inner, cascade_input, output)

                        return json.dumps(output)
                    else:
                        log.warning(f"[dimension_compute] {func_name_inner} output not a dict: {type(output)}")
                        return json.dumps({"mapping": {}, "error": f"Cascade did not return dict, got {type(output).__name__}"})

                except Exception as e:
                    import traceback
                    log.error(f"[dimension_compute] Error executing {func_name_inner}: {e}\n{traceback.format_exc()}")
                    return json.dumps({"mapping": {}, "error": str(e)})

            return compute_func

        compute_fn = make_compute_func(cascade_path, func_name, cascade_id)

        # Register variants for different arities
        # DuckDB does NOT support function overloading for Python UDFs, so we use
        # different function names for different arities:
        # - {name}_compute   = 1 arg (just values_json)
        # - {name}_compute_2 = 2 args (values_json + one scalar)
        # - {name}_compute_3 = 3 args (values_json + two scalars)
        # - {name}_compute_4 = 4 args (values_json + three scalars)
        #
        # The dimension rewriter must generate the correct function name based on arity.

        def make_wrapper_1(fn):
            def wrapper(v: str) -> str:
                return fn(v)
            return wrapper

        def make_wrapper_2(fn):
            def wrapper(v: str, a1) -> str:
                return fn(v, a1)
            return wrapper

        def make_wrapper_3(fn):
            def wrapper(v: str, a1, a2) -> str:
                return fn(v, a1, a2)
            return wrapper

        def make_wrapper_4(fn):
            def wrapper(v: str, a1, a2, a3) -> str:
                return fn(v, a1, a2, a3)
            return wrapper

        # Register each arity with a different function name
        wrappers = [
            (1, compute_name, make_wrapper_1(compute_fn)),           # topics_compute
            (2, f"{compute_name}_2", make_wrapper_2(compute_fn)),    # topics_compute_2
            (3, f"{compute_name}_3", make_wrapper_3(compute_fn)),    # topics_compute_3
            (4, f"{compute_name}_4", make_wrapper_4(compute_fn)),    # topics_compute_4
        ]

        registered_count = 0
        for arity, fn_name, wrapper in wrappers:
            try:
                connection.create_function(fn_name, wrapper, return_type="VARCHAR")
                log.debug(f"[dimension_compute] Registered {fn_name} (arity={arity})")
                registered_count += 1
            except Exception as e:
                log.warning(f"[dimension_compute] Could not register {fn_name}: {e}")

        if registered_count > 0:
            log.info(f"[dimension_compute] Registered {compute_name}[_2,_3,_4] for {func_name}")


def clear_agg_cache():
    """Clear the aggregate result cache (both in-memory and persistent)."""
    global _agg_cache
    _agg_cache.clear()

    # Also clear from persistent cache
    try:
        from .cache_adapter import get_cache
        from .udf import _CACHE_TYPE_AGGREGATE
        cache = get_cache()
        cache.clear(function_name=_CACHE_TYPE_AGGREGATE)
    except Exception:
        pass


def get_agg_cache_stats() -> Dict[str, Any]:
    """Get aggregate cache statistics (in-memory only, persistent stats in parent)."""
    return {
        "cached_entries": len(_agg_cache),
        "functions": ["llm_summarize", "llm_classify", "llm_sentiment", "llm_themes", "llm_agg"]
    }
