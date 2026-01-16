"""
Semantic SQL Operators.

Transforms semantic SQL syntax into UDF calls backed by LARS cascades.

Architecture:
    All semantic operators are "prompt sugar" - syntax that rewrites to cascade
    invocations. A cascade with `sql_function` metadata becomes a SQL-callable
    function. Built-in operators (MEANS, ABOUT, IMPLIES, etc.) are defined as
    cascade YAML files in cascades/semantic_sql/ (user-space, fully customizable).

    Three shapes:
    - SCALAR: Per-row functions (e.g., MEANS, IMPLIES, ABOUT)
    - ROW: Multi-column per-row (e.g., match_pair)
    - AGGREGATE: Collection functions (e.g., SUMMARIZE, MEANING, TOPICS)

    Resolution is inside-out like Lisp:
    - Aggregates resolve first (become CTEs)
    - Scalars resolve inline per row

Operator Syntax:

    col MEANS 'x'           → matches('x', col)
    col NOT MEANS 'x'       → NOT matches('x', col)
    col ABOUT 'x'           → score('x', col) > 0.5
    col ABOUT 'x' > 0.7     → score('x', col) > 0.7
    col NOT ABOUT 'x'       → score('x', col) <= 0.5
    col IMPLIES 'x'         → implies(col, 'x')
    col CONTRADICTS other   → contradicts(col, other)
    a ~ b                   → match_pair(a, b, 'same entity')
    ORDER BY col RELEVANCE TO 'x'      → ORDER BY score('x', col) DESC
    SEMANTIC DISTINCT col              → Dedupe by semantic similarity
    GROUP BY MEANING(col, n, 'hint')   → Cluster values semantically
    GROUP BY TOPICS(col, n)            → Extract and group by themes

Annotation hints (-- @) for model selection and prompt customization:

    -- @ use a fast and cheap model
    WHERE description MEANS 'sustainable'

    Becomes:
    WHERE matches('use a fast and cheap model - sustainable', description)

The annotation prompt is prepended to the criteria, allowing bodybuilder's
request mode to pick up model hints naturally.

Cascade Integration:
    When USE_CASCADE_FUNCTIONS is True, operators resolve through the cascade
    registry instead of direct UDF calls. This enables:
    - Full LARS observability (logging, tracing, cost tracking)
    - User-defined overrides (put your own cascade in skills/)
    - Wards, retries, multi-modal - all LARS features available
"""

import re
import logging
from typing import Optional, List, Tuple, Dict, Any, Literal
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ============================================================================
# Cascade Integration Configuration
# ============================================================================

# When True, rewriter uses cascade-based function names (e.g., cascade_matches)
# When False, uses direct UDF names (e.g., matches)
USE_CASCADE_FUNCTIONS = True

# Mapping from operator to function name (direct UDF vs cascade-backed)
OPERATOR_FUNCTIONS = {
    # Direct UDF names (current implementation)
    "direct": {
        "matches": "matches",
        "score": "score",
        "implies": "implies",
        "contradicts": "contradicts",
        "match_pair": "match_pair",
        "summarize": "summarize",
        "llm_themes_2": "llm_themes_2",
        "llm_cluster_2": "llm_cluster_2",
        "classify_single": "classify_single",
    },
    # Cascade-backed function names
    "cascade": {
        "matches": "cascade_matches",
        "score": "cascade_score",
        "implies": "cascade_implies",
        "contradicts": "cascade_contradicts",
        "match_pair": "cascade_match_pair",  # TODO: add cascade
        "summarize": "cascade_summarize",
        "llm_themes_2": "cascade_themes",
        "llm_cluster_2": "cascade_cluster",
        "classify_single": "cascade_classify",
    },
}


def get_function_name(operator: str) -> str:
    """Get the function name for an operator based on current configuration."""
    mode = "cascade" if USE_CASCADE_FUNCTIONS else "direct"
    return OPERATOR_FUNCTIONS[mode].get(operator, operator)


def set_use_cascade_functions(enabled: bool) -> None:
    """Enable or disable cascade-backed functions."""
    global USE_CASCADE_FUNCTIONS
    USE_CASCADE_FUNCTIONS = enabled
    log.info(f"[semantic_operators] Cascade functions {'enabled' if enabled else 'disabled'}")


# ============================================================================
# Annotation Parsing (shared with llm_agg_rewriter)
# ============================================================================

@dataclass
class SemanticAnnotation:
    """Parsed annotation for a semantic operator."""
    prompt: Optional[str] = None          # Custom prompt/instructions/model hints
    model: Optional[str] = None           # Explicit model override
    threshold: Optional[float] = None     # Score threshold for ABOUT
    parallel: Optional[int] = None        # Reserved for future parallelism (currently ignored)
    batch_size: Optional[int] = None      # Reserved for future parallelism (currently ignored)
    parallel_scope: str = "operator"      # "operator" (default) or "query" (all operators)
    start_pos: int = 0                    # Start position in query
    end_pos: int = 0                      # End position in query
    line_start: int = 0                   # Line number where annotation starts
    line_end: int = 0                     # Line number where annotation ends
    takes: Optional[Dict[str, Any]] = None  # Takes config for cascade-level sampling


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

            # Check for standalone keywords first (no colon)
            content_lower = content.lower()
            if content_lower in ('parallel', 'parallel execution'):
                # -- @ parallel (without value)
                import os
                current_annotation.parallel = os.cpu_count() or 8
            # Check for key: value pattern
            elif ':' in content and not content.startswith('http'):
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
                elif key == 'parallel':
                    try:
                        # If value is empty or "true", use CPU count as default
                        if not value or value.lower() in ('true', 'yes'):
                            import os
                            current_annotation.parallel = os.cpu_count() or 8
                        else:
                            current_annotation.parallel = int(value)
                    except ValueError:
                        import os
                        current_annotation.parallel = os.cpu_count() or 8
                elif key == 'batch_size':
                    try:
                        current_annotation.batch_size = int(value)
                    except ValueError:
                        pass
                elif key == 'parallel_scope':
                    if value.lower() in ('query', 'operator'):
                        current_annotation.parallel_scope = value.lower()
                elif key == 'prompt':
                    prompt_lines.append(value)
                elif key.startswith('takes.'):
                    # Takes config for cascade-level sampling
                    # e.g., takes.factor: 3, takes.evaluator: ..., takes.mode: aggregate
                    if current_annotation.takes is None:
                        current_annotation.takes = {}
                    subkey = key[11:]  # Remove 'takes.' prefix
                    # Parse value type
                    if subkey in ('factor', 'max_parallel', 'reforge'):
                        try:
                            current_annotation.takes[subkey] = int(value)
                        except ValueError:
                            current_annotation.takes[subkey] = value
                    elif subkey == 'mutate':
                        current_annotation.takes[subkey] = value.lower() in ('true', 'yes', '1')
                    else:
                        # evaluator, mode, evaluator_model, etc.
                        current_annotation.takes[subkey] = value
                elif key == 'models':
                    # Shorthand for multi-model takes
                    # models: [claude-sonnet, gpt-4o, gemini-pro]
                    if current_annotation.takes is None:
                        current_annotation.takes = {}
                    # Parse as list (JSON or comma-separated)
                    try:
                        import json
                        models = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        # Try comma-separated
                        models = [m.strip() for m in value.strip('[]').split(',')]
                    current_annotation.takes['multi_model'] = models
                    # Set factor to match number of models if not explicitly set
                    if 'factor' not in current_annotation.takes:
                        current_annotation.takes['factor'] = len(models)
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
# Natural Language Annotations (-- @@)
# ============================================================================

@dataclass
class NLAnnotation:
    """Natural language annotation for LLM interpretation."""
    hints: str                           # Concatenated NL hints
    scope: Literal["global", "local"]    # global = top of query
    target_line: Optional[int] = None    # Line number (for local scope)
    start_pos: int = 0
    end_pos: int = 0


def _has_nl_annotations(query: str) -> bool:
    """Check if query contains -- @@ annotations (but not -- @@@)."""
    return bool(re.search(r'--\s*@@(?!@)', query))


def _parse_nl_annotations(query: str) -> List[Tuple[int, NLAnnotation]]:
    """
    Parse all -- @@ annotations from query.

    Returns list of (target_line, NLAnnotation) tuples.

    Rules:
    - -- @@ at top of query (before any SQL) = global scope
    - -- @@ before a specific line = local scope for that line
    - Multiple consecutive -- @@ lines are concatenated
    """
    annotations = []
    lines = query.split('\n')

    current_hints = []
    current_start = 0
    current_pos = 0
    in_nl_annotation = False
    first_sql_seen = False

    for line_num, line in enumerate(lines):
        line_start = current_pos
        line_end = current_pos + len(line)
        stripped = line.strip()

        # Check for -- @@ (exactly two @, not three or more)
        if stripped.startswith('-- @@') and not stripped.startswith('-- @@@'):
            content = stripped[5:].strip()  # After "-- @@"

            if not in_nl_annotation:
                current_start = line_start
                current_hints = []
                in_nl_annotation = True

            if content:  # Only add non-empty hints
                current_hints.append(content)

        elif stripped and not stripped.startswith('--'):
            # This is a SQL line (non-comment, non-empty)
            if in_nl_annotation:
                # Determine scope: global if no SQL seen yet, local otherwise
                scope: Literal["global", "local"] = "global" if not first_sql_seen else "local"
                target_line = line_num if scope == "local" else None

                annotations.append((
                    line_num,
                    NLAnnotation(
                        hints=' '.join(current_hints),
                        scope=scope,
                        target_line=target_line,
                        start_pos=current_start,
                        end_pos=line_end - len(line)
                    )
                ))

                in_nl_annotation = False
                current_hints = []

            first_sql_seen = True

        current_pos = line_end + 1  # +1 for newline

    # Handle annotation at end of query (no SQL after)
    if in_nl_annotation and current_hints:
        # Treat as global if no SQL seen, otherwise orphaned (still add it)
        scope = "global" if not first_sql_seen else "local"
        annotations.append((
            len(lines) - 1,
            NLAnnotation(
                hints=' '.join(current_hints),
                scope=scope,
                target_line=None,
                start_pos=current_start,
                end_pos=current_pos
            )
        ))

    return annotations


def _strip_nl_annotation_lines(query: str) -> str:
    """Remove -- @@ lines from query after processing."""
    lines = query.split('\n')
    filtered = [
        line for line in lines
        if not (line.strip().startswith('-- @@') and not line.strip().startswith('-- @@@'))
    ]
    return '\n'.join(filtered)


def _interpret_nl_annotations(
    query: str,
    nl_annotations: List[Tuple[int, NLAnnotation]],
    session_id: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Invoke the interpreter cascade for each NL annotation.

    Returns dict mapping scope key to interpreted config:
    - "global" for global scope annotations
    - f"line_{N}" for local scope annotations

    This is the LLM invocation point - only called if _has_nl_annotations() is True.
    """
    from ..semantic_sql.executor import _run_cascade_sync, _extract_cascade_output
    from ..session_naming import generate_woodland_id
    import json

    results = {}

    for target_line, annotation in nl_annotations:
        # Generate session ID for interpreter
        woodland_id = generate_woodland_id()
        interp_session = f"nl_interp_{woodland_id}"

        # Run interpreter cascade
        try:
            log.info(f"[nl_annotation] Interpreting: '{annotation.hints}' (scope={annotation.scope})")

            result = _run_cascade_sync(
                "cascades/internal/nl_annotation_interpreter.cascade.yaml",
                interp_session,
                {
                    "sql_query": query,
                    "hints": annotation.hints,
                    "scope": annotation.scope
                }
            )

            # Extract output from cascade result
            output = _extract_cascade_output(result)

            # Parse JSON if string
            if isinstance(output, str):
                output = output.strip()
                # Strip markdown code fences if present
                if output.startswith('```'):
                    lines = output.split('\n')
                    # Remove first line (```json) and last line (```)
                    json_lines = [l for l in lines[1:] if not l.strip().startswith('```')]
                    output = '\n'.join(json_lines)
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    log.warning(f"[nl_annotation] Failed to parse interpreter output as JSON: {output}")
                    output = {}

            # Validate output structure
            output = _validate_nl_config(output) if isinstance(output, dict) else {}

            # Store by scope
            key = "global" if annotation.scope == "global" else f"line_{target_line}"
            results[key] = output

            log.info(f"[nl_annotation] Interpreted config for {key}: {output}")

        except Exception as e:
            log.warning(f"[nl_annotation] Failed to interpret annotation: {e}")
            # Continue - don't break query execution for interpreter failures

    return results


def _validate_nl_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize NL-interpreted config."""
    validated = {}

    takes = config.get("takes", {})
    if takes and isinstance(takes, dict):
        validated["takes"] = {}

        if "factor" in takes:
            factor = takes["factor"]
            if isinstance(factor, int) and 1 <= factor <= 20:
                validated["takes"]["factor"] = factor

        if "max_parallel" in takes:
            mp = takes["max_parallel"]
            if isinstance(mp, int) and 1 <= mp <= 10:
                validated["takes"]["max_parallel"] = mp

        if "mode" in takes and takes["mode"] in ("evaluate", "aggregate"):
            validated["takes"]["mode"] = takes["mode"]

        if "evaluator_instructions" in takes and isinstance(takes["evaluator_instructions"], str):
            validated["takes"]["evaluator"] = takes["evaluator_instructions"]

        if "mutate" in takes and isinstance(takes["mutate"], bool):
            validated["takes"]["mutate"] = takes["mutate"]

        if "model_override" in takes and isinstance(takes["model_override"], str):
            validated["takes"]["model_override"] = takes["model_override"]

        if "multi_model" in takes and isinstance(takes["multi_model"], list):
            validated["takes"]["multi_model"] = takes["multi_model"]

    if "model" in config and isinstance(config["model"], str):
        validated["model"] = config["model"]

    if "threshold" in config:
        t = config["threshold"]
        if isinstance(t, (int, float)) and 0 <= t <= 1:
            validated["threshold"] = float(t)

    return validated


def _merge_nl_overrides(
    annotations: List[Tuple[int, int, SemanticAnnotation]],
    nl_overrides: Dict[str, Dict[str, Any]]
) -> List[Tuple[int, int, SemanticAnnotation]]:
    """
    Merge NL-interpreted overrides into existing annotations.

    For global scope: Apply to first annotation or create new one.
    For local scope: Match to annotation by line number.
    """
    if not nl_overrides:
        return annotations

    # Handle global overrides
    global_config = nl_overrides.get("global", {})
    if global_config:
        if annotations:
            # Merge into first annotation
            ann = annotations[0][2]
            _apply_nl_config_to_annotation(ann, global_config)
        else:
            # Create synthetic annotation for global scope
            ann = SemanticAnnotation()
            _apply_nl_config_to_annotation(ann, global_config)
            annotations.insert(0, (0, 0, ann))

    # Handle local overrides
    for key, config in nl_overrides.items():
        if key.startswith("line_"):
            target_line = int(key[5:])
            # Find or create annotation for this line
            matched = False
            for _idx, (line_num, _end_pos, ann) in enumerate(annotations):
                if line_num == target_line:
                    _apply_nl_config_to_annotation(ann, config)
                    matched = True
                    break

            if not matched:
                ann = SemanticAnnotation(line_end=target_line)
                _apply_nl_config_to_annotation(ann, config)
                annotations.append((target_line, 0, ann))

    return annotations


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge override into base dict. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _apply_nl_config_to_annotation(ann: SemanticAnnotation, config: Dict[str, Any]) -> None:
    """
    Apply NL-interpreted config to a SemanticAnnotation.

    Handles two formats:

    1. New structured format (from NL interpreter with full DSL knowledge):
       {
         "cascade_overrides": {
           "takes": {"factor": 3, ...},
           "token_budget": {...},
           "narrator": {...}
         },
         "cell_overrides": {
           "default": {"model": "...", "rules": {...}, "wards": {...}},
           "specific_cell": {"model": "..."}
         }
       }

    2. Legacy flat format (backwards compatibility):
       {"model": "...", "threshold": 0.7, "takes": {"factor": 3}}

    The annotation.takes field stores the full override config for injection
    into the cascade via __LARS_TAKES:{...}__ prefix.
    """
    # Detect format: new structured vs legacy flat
    is_new_format = 'cascade_overrides' in config or 'cell_overrides' in config

    if is_new_format:
        # New structured format - store entire config for cascade injection
        if ann.takes is None:
            ann.takes = {}

        # Deep merge the override structure
        ann.takes = _deep_merge_dict(ann.takes, config)

        # Also extract model for the annotation-level model hint (used by some rewriters)
        cell_overrides = config.get('cell_overrides', {})
        default_model = cell_overrides.get('default', {}).get('model')
        if default_model:
            ann.model = default_model

        # Threshold from cascade_overrides (if present)
        cascade_overrides = config.get('cascade_overrides', {})
        if 'threshold' in cascade_overrides:
            ann.threshold = cascade_overrides['threshold']

    else:
        # Legacy flat format for backwards compatibility
        # Model override (from top-level or takes.model_override)
        if config.get("model"):
            ann.model = config["model"]

        # Threshold
        if config.get("threshold") is not None:
            ann.threshold = config["threshold"]

        # Takes config
        takes_config = config.get("takes", {})
        if takes_config:
            if ann.takes is None:
                ann.takes = {}

            # Map NL fields to takes config
            if takes_config.get("factor"):
                ann.takes["factor"] = takes_config["factor"]
            if takes_config.get("max_parallel"):
                ann.takes["max_parallel"] = takes_config["max_parallel"]
            if takes_config.get("mode"):
                ann.takes["mode"] = takes_config["mode"]
            if takes_config.get("evaluator"):
                ann.takes["evaluator"] = takes_config["evaluator"]
            if takes_config.get("mutate") is not None:
                ann.takes["mutate"] = takes_config["mutate"]
            if takes_config.get("model_override"):
                # Model override from takes goes to annotation model
                ann.model = takes_config["model_override"]
            if takes_config.get("multi_model"):
                ann.takes["multi_model"] = takes_config["multi_model"]


# ============================================================================
# Semantic Operator Detection
# ============================================================================

def has_semantic_operators(query: str) -> bool:
    """
    Check if query contains any semantic SQL operators.

    Dynamically checks against operators loaded from cascade registry.
    Operators are discovered from cascades/semantic_sql/*.cascade.yaml
    and skills/semantic_sql/*.cascade.yaml on server startup.

    This means user-created cascades automatically work without code changes!
    """
    # Use dynamic pattern detection
    from .dynamic_operators import has_any_semantic_operator
    return has_any_semantic_operator(query)


# ============================================================================
# Rewriting Functions
# ============================================================================

def rewrite_semantic_operators(query: str, session_id: Optional[str] = None) -> str:
    """
    Rewrite semantic SQL operators to UDF calls.

    Preserves annotations by injecting prompt text into the criteria string,
    allowing bodybuilder to pick up model hints.

    Supports two annotation syntaxes:
    - -- @ key: value  (keyword-based, parsed directly)
    - -- @@ natural language hint  (LLM-interpreted at runtime)

    IMPORTANT: Only removes annotations that are actually used for semantic operators.
    Annotations before LLM aggregate functions (SUMMARIZE, THEMES, etc.) are preserved
    for the LLM aggregate rewriter to consume.

    Args:
        query: SQL query with semantic operators
        session_id: Optional session ID for logging/tracing

    Returns:
        Rewritten SQL with UDF calls
    """
    # Check for semantic operators OR skill syntax
    query_lower = query.lower()
    has_skill = 'skill(' in query_lower or 'skill::' in query_lower or re.search(r'\bskill\s+\w+', query_lower)
    if not has_semantic_operators(query) and not has_skill:
        return query

    # =========================================================================
    # Natural Language Annotations (-- @@)
    # =========================================================================
    # If query contains -- @@ annotations, invoke LLM interpreter to convert
    # natural language hints into structured cascade configuration overrides.
    # This happens ONCE per query, before any operator rewriting.
    nl_overrides = {}
    if _has_nl_annotations(query):
        nl_annotations = _parse_nl_annotations(query)
        if nl_annotations:
            log.info(f"[nl_annotation] Found {len(nl_annotations)} NL annotation(s), invoking interpreter...")
            nl_overrides = _interpret_nl_annotations(query, nl_annotations, session_id)
            # Strip -- @@ lines from query (they've been processed)
            query = _strip_nl_annotation_lines(query)

    # Rewrite skill::name() syntax first (before other rewrites)
    query = _rewrite_skill_namespace_syntax(query)

    # Rewrite SKILL name ... END block syntax
    query = _rewrite_skill_block_syntax(query)

    # Parse keyword-based annotations (-- @)
    annotations = _parse_annotations(query)

    # Merge NL-interpreted overrides into annotations
    if nl_overrides:
        annotations = _merge_nl_overrides(annotations, nl_overrides)

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

    # Get annotation prefix for query-level rewrites
    # Use the first annotation if present
    annotation_prefix = ""
    if annotations:
        first_annotation = annotations[0][2]  # (line_num, end_pos, annotation)
        if first_annotation.prompt:
            annotation_prefix = first_annotation.prompt + " - "
        # Inject takes prefix if present (for cascade-level sampling)
        if first_annotation.takes:
            import json
            takes_prefix = f"__LARS_TAKES:{json.dumps(first_annotation.takes)}__"
            annotation_prefix = takes_prefix + annotation_prefix
            print(f"[semantic_operators] 💉 Injecting takes prefix for query-level rewrite: {takes_prefix}")

    # Query-level rewrites (these transform the entire query structure)
    #
    # NOTE: EMBED(...) and VECTOR_SEARCH(...) sugar has been removed in favor of
    # explicit function calls:
    #   - semantic_embed(text)
    #   - semantic_embed_with_storage(text, model, source_table, column_name, source_id)
    #   - read_json_auto(vector_search_json_N(...))
    #
    # Structural helpers can be reintroduced later once we have robust SQL parsing.

    # SEMANTIC DISTINCT: SELECT SEMANTIC DISTINCT col FROM table
    result = _rewrite_semantic_distinct(result, annotation_prefix)

    # GROUP BY MEANING(col): Cluster values semantically
    result = _rewrite_group_by_meaning(result, annotation_prefix)

    # GROUP BY TOPICS(col, n): Group by extracted themes
    result = _rewrite_group_by_topics(result, annotation_prefix)

    # SKILL(): Universal skill caller - wrap in read_json_auto for table output
    result = _rewrite_skill_function(result)

    return result


def _find_next_code_line(lines: list, start: int) -> Optional[int]:
    """Find the next non-annotation, non-empty line number."""
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith('-- @') and not stripped.startswith('--'):
            return i
    return None


def _has_semantic_operator_in_line(line: str) -> bool:
    """
    Check if a line contains any semantic operator.

    Dynamically checks against operators loaded from cascade registry.
    """
    # Ignore if line is a comment
    if line.strip().startswith('--'):
        return False

    from .dynamic_operators import has_semantic_operator_in_line as dynamic_check
    return dynamic_check(line)


def _fix_double_where(query: str) -> str:
    """
    Fix double WHERE clauses in a query (CTE-aware).

    When SEMANTIC JOIN is on one line and WHERE is on a subsequent line,
    we end up with two WHERE keywords in the SAME query scope.
    This function merges them with AND.

    IMPORTANT: This should only fix WHERE clauses in the same scope,
    not across different CTEs or subqueries!

    Example (needs fix):
        CROSS JOIN t WHERE match_pair(...)
        WHERE price > 100
    Becomes:
        CROSS JOIN t WHERE match_pair(...)
        AND price > 100

    Example (DON'T fix):
        WITH cte AS (SELECT * FROM t WHERE x = 1)
        SELECT * FROM cte WHERE y = 2
    Should stay unchanged (different scopes)!
    """
    # Skip fix if query has WITH clause (CTEs have their own scopes)
    if re.search(r'^\s*WITH\s+', query, re.IGNORECASE):
        return query

    # Skip fix if query has subqueries or UNION (different scopes)
    # Use case-insensitive check!
    query_upper = query.upper()
    select_count = query_upper.count('SELECT')
    where_count_check = len(re.findall(r'\bWHERE\b', query, re.IGNORECASE))

    # Debug: log for pg_class queries
    if 'PG_CLASS' in query_upper and 'RELNAMESPACE' in query_upper:
        print(f"[DEBUG] _fix_double_where: SELECT count={select_count}, WHERE count={where_count_check}")
        if select_count > 1:
            print(f"[DEBUG] _fix_double_where: SKIPPING (multiple SELECTs)")

    if select_count > 1:
        return query

    # Also skip if query has UNION (each UNION part is its own scope)
    if 'UNION' in query_upper:
        return query

    # Count WHERE occurrences in simple queries only
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


def _rewrite_dynamic_infix_operators(
    line: str,
    annotation_prefix: str
) -> str:
    """
    Generic rewriter for ALL infix operators using cascade registry.

    Handles operators like:
        col OPERATOR 'value' → sql_function_name(col, 'value')
        col OPERATOR other_col → sql_function_name(col, other_col)

    Automatically works with user-created cascades!

    This replaces per-operator hardcoded expression rewrites with a single
    registry-driven implementation.

    Args:
        line: SQL line to rewrite
        annotation_prefix: Annotation prefix to inject into criteria

    Returns:
        Rewritten line with UDF calls
    """
    from .dynamic_operators import get_operator_patterns_cached

    try:
        from lars.semantic_sql.registry import get_sql_function_registry
    except ImportError:
        # Registry not available - return line unchanged
        return line

    result = line
    patterns_cache = get_operator_patterns_cached()
    registry = get_sql_function_registry()

    # Process each infix operator found by dynamic detection
    # Sort by length (descending) to handle multi-word operators first
    # e.g., "ALIGNS WITH" before "ALIGNS"
    infix_operators = sorted(patterns_cache.get('infix', set()), key=len, reverse=True)

    # Skip operators now handled by v2 (token-aware rewriter).
    # v2 runs first and handles these safely without matching inside string literals.
    v2_handled = {"ABOUT", "NOT ABOUT"}

    for operator_keyword in infix_operators:
        if operator_keyword.upper() in v2_handled:
            continue
        # Find SQL function for this operator
        matching_funcs = [
            (name, entry) for name, entry in registry.items()
            if any(operator_keyword.upper() in op.upper() for op in entry.operators)
        ]

        if not matching_funcs:
            continue

        func_name, entry = matching_funcs[0]
        returns_upper = str(getattr(entry, "returns", "") or "").upper()

        # Check if this is a word-based operator or symbol operator
        is_word_operator = operator_keyword.replace('_', '').replace(' ', '').isalnum()

        if is_word_operator:
            # Word-based operator (MEANS, ABOUT, ALIGNS, ASK, etc.)
            # Pattern: col OPERATOR 'value' or col OPERATOR other_col
            # Use word boundaries to avoid false matches
            # Also support optional infix NOT for boolean-returning operators:
            #   col NOT OPERATOR 'value'  -> NOT func(col, 'value')
            pattern = rf'(\w+(?:\.\w+)?)\s+(?:(NOT)\s+)?{re.escape(operator_keyword)}\s+(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'
        else:
            # Symbol operator (~, !~, etc.)
            # Pattern: col OPERATOR 'value' or col OPERATOR other_col
            # Also support optional leading ! for boolean-returning operators:
            #   col !~ other  -> NOT func(col, other)   (if "~" is defined)
            pattern = rf'(\w+(?:\.\w+)?)\s*(?P<bang>!)?\s*{re.escape(operator_keyword)}\s*(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'

        def replace_operator(match):
            col = match.group(1)
            not_kw = (match.group(2) if is_word_operator else None)
            bang = (match.group("bang") if not is_word_operator else None)
            value = match.group(3) if is_word_operator else match.group(2)

            is_negated = bool(not_kw) or bool(bang)
            if is_negated and returns_upper != "BOOLEAN":
                # Don't attempt to negate non-boolean operators.
                return match.group(0)

            # Inject annotation prefix if the value is a quoted string
            if annotation_prefix and value.startswith(("'", '"')):
                quote = value[0]
                inner = value[1:-1]
                value = f"{quote}{annotation_prefix}{inner}{quote}"

            # Generate function call with correct argument order
            # First arg is always the text column, second is the criterion/value
            expr = f"{func_name}({col}, {value})"
            return f"NOT {expr}" if is_negated else expr

        old_result = result
        result = re.sub(pattern, replace_operator, result, flags=re.IGNORECASE)

        if result != old_result:
            log.debug(f"[dynamic_rewrite] {operator_keyword}: {old_result.strip()[:60]}... → {result.strip()[:60]}...")

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
    # Inject takes prefix if present (for cascade-level sampling)
    if annotation and annotation.takes:
        import json
        takes_prefix = f"__LARS_TAKES:{json.dumps(annotation.takes)}__"
        annotation_prefix = takes_prefix + annotation_prefix
        print(f"[semantic_operators] 💉 Injecting takes prefix for line-level rewrite: {takes_prefix}")

    # Get threshold from annotation or use default
    default_threshold = 0.5
    if annotation and annotation.threshold is not None:
        default_threshold = annotation.threshold

    # ===== Context-sensitive rewrites (kept in legacy for now) =====
    # These handle patterns that need query/statement context or custom semantics:
    # - ABOUT with threshold comparisons (> 0.7, etc.) and NOT ABOUT inversion
    # - RELEVANCE TO in ORDER BY context (+ NOT variant)
    # - SEMANTIC JOIN (multi-keyword transformation)
    #
    # Expression-level operators (MEANS, NOT MEANS, ~, !~, IMPLIES, CONTRADICTS, ASK, ALIGNS, ...)
    # are handled by v2 (token-aware) and/or the dynamic infix rewriter below.

    # 1. Rewrite: SEMANTIC JOIN (complex multi-keyword transformation)
    result = _rewrite_semantic_join(result, annotation_prefix)

    # 2. Rewrite: ORDER BY col NOT RELEVANCE TO 'query'
    # Special: ORDER BY context + negation
    result = _rewrite_not_relevance_to(result, annotation_prefix)

    # 3. Rewrite: ORDER BY col RELEVANCE TO 'query'
    # Special: ORDER BY context
    result = _rewrite_relevance_to(result, annotation_prefix)

    # 4. Rewrite: col NOT ABOUT 'criteria' → score('criteria', col) <= threshold
    # Special: Negation + threshold inversion
    result = _rewrite_not_about(result, annotation_prefix, default_threshold)

    # 5. Rewrite: col ABOUT 'criteria' [> threshold]
    # Special: Threshold comparison operators
    result = _rewrite_about(result, annotation_prefix, default_threshold)

    # ===== PHASE 2: GENERIC DYNAMIC REWRITING (NEW!) =====
    # Run this AFTER the special-case rewrites above so we don’t break:
    # - ABOUT default thresholds
    # - ORDER BY ... RELEVANCE TO ...
    # - Other context-sensitive patterns
    #
    # This enables ASK, ALIGNS WITH, EXTRACTS, SOUNDS_LIKE and any user-created
    # infix operators to work without additional hardcoding.
    result = _rewrite_dynamic_infix_operators(result, annotation_prefix)

    return result


def _rewrite_about(line: str, annotation_prefix: str, default_threshold: float) -> str:
    """
    Rewrite ABOUT operator.

    col ABOUT 'topic'         →  score('topic', col) > 0.5
    col ABOUT 'topic' > 0.7   →  score('topic', col) > 0.7

    With annotation:
    -- @ threshold: 0.8
    col ABOUT 'topic'  →  score('topic', col) > 0.8
    """
    fn_name = get_function_name("score")

    # Pattern with explicit threshold: col ABOUT 'x' > 0.7
    pattern_with_threshold = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'\s*(>|>=|<|<=)\s*([\d.]+)'

    def replacer_with_threshold(match):
        col = match.group(1)
        criteria = match.group(2)
        operator = match.group(3)
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') {operator} {threshold}"

    result = re.sub(pattern_with_threshold, replacer_with_threshold, line, flags=re.IGNORECASE)

    # Pattern without threshold: col ABOUT 'x' (uses default)
    pattern_simple = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'(?!\s*[><])'

    def replacer_simple(match):
        col = match.group(1)
        criteria = match.group(2)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') > {default_threshold}"

    result = re.sub(pattern_simple, replacer_simple, result, flags=re.IGNORECASE)

    return result


def _rewrite_not_about(line: str, annotation_prefix: str, default_threshold: float) -> str:
    """
    Rewrite NOT ABOUT operator (inverts threshold comparison).

    col NOT ABOUT 'topic'         →  score('topic', col) <= 0.5
    col NOT ABOUT 'topic' > 0.7   →  score('topic', col) <= 0.7

    The threshold from the query is used as the cutoff for exclusion.
    """
    fn_name = get_function_name("score")

    # Pattern with explicit threshold: col NOT ABOUT 'x' > 0.7
    # Note: The > threshold in NOT ABOUT means "exclude anything scoring above this"
    pattern_with_threshold = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'\s*(>|>=)\s*([\d.]+)'

    def replacer_with_threshold(match):
        col = match.group(1)
        criteria = match.group(2)
        # For NOT ABOUT with >, we invert: NOT ABOUT 'x' > 0.7 means score <= 0.7
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') <= {threshold}"

    result = re.sub(pattern_with_threshold, replacer_with_threshold, line, flags=re.IGNORECASE)

    # Pattern with < threshold: col NOT ABOUT 'x' < 0.3
    # This means "exclude anything scoring below 0.3" → score >= 0.3
    pattern_with_lt = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'\s*(<|<=)\s*([\d.]+)'

    def replacer_with_lt(match):
        col = match.group(1)
        criteria = match.group(2)
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') >= {threshold}"

    result = re.sub(pattern_with_lt, replacer_with_lt, result, flags=re.IGNORECASE)

    # Pattern without threshold: col NOT ABOUT 'x' (uses inverted default)
    pattern_simple = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'(?!\s*[><])'

    def replacer_simple(match):
        col = match.group(1)
        criteria = match.group(2)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') <= {default_threshold}"

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
    fn_name = get_function_name("score")

    # Pattern: ORDER BY col RELEVANCE TO 'query' [ASC|DESC]
    pattern = r'ORDER\s+BY\s+(\w+(?:\.\w+)?)\s+RELEVANCE\s+TO\s+\'([^\']+)\'(?:\s+(ASC|DESC))?'

    def replacer(match):
        col = match.group(1)
        query = match.group(2)
        direction = match.group(3) or 'DESC'  # Default to DESC (highest relevance first)
        full_query = f"{annotation_prefix}{query}" if annotation_prefix else query
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"ORDER BY {fn_name}({col}, '{full_query}') {direction}"

    return re.sub(pattern, replacer, line, flags=re.IGNORECASE)


def _rewrite_not_relevance_to(line: str, annotation_prefix: str) -> str:
    """
    Rewrite NOT RELEVANCE TO in ORDER BY (inverts to ASC).

    ORDER BY col NOT RELEVANCE TO 'query'      →  ORDER BY score('query', col) ASC
    ORDER BY col NOT RELEVANCE TO 'query' DESC →  ORDER BY score('query', col) DESC

    NOT RELEVANCE TO defaults to ASC (least relevant first), which is useful
    for filtering out irrelevant results or finding outliers.
    """
    fn_name = get_function_name("score")

    # Pattern: ORDER BY col NOT RELEVANCE TO 'query' [ASC|DESC]
    pattern = r'ORDER\s+BY\s+(\w+(?:\.\w+)?)\s+NOT\s+RELEVANCE\s+TO\s+\'([^\']+)\'(?:\s+(ASC|DESC))?'

    def replacer(match):
        col = match.group(1)
        query = match.group(2)
        direction = match.group(3) or 'ASC'  # Default to ASC (least relevant first for NOT)
        full_query = f"{annotation_prefix}{query}" if annotation_prefix else query
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"ORDER BY {fn_name}({col}, '{full_query}') {direction}"

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
    fn_name = get_function_name("match_pair")

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
        return f"CROSS JOIN {table} {alias} {{{{SEMANTIC_WHERE}}}} {fn_name}({left}, {right}, '{full_relationship}')"

    # Pattern simple: SEMANTIC JOIN table ON col1 ~ col2
    pattern = r'SEMANTIC\s+JOIN\s+(\w+)\s+ON\s+(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)'

    def replacer(match):
        table = match.group(1)
        left = match.group(2)
        right = match.group(3)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        return f"CROSS JOIN {table} {{{{SEMANTIC_WHERE}}}} {fn_name}({left}, {right}, '{full_relationship}')"

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

def _rewrite_semantic_distinct(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite SEMANTIC DISTINCT to use LLM deduplication.

    SELECT SEMANTIC DISTINCT company FROM suppliers
    →
    WITH _distinct_vals AS (
        SELECT to_json(LIST(company)) as _vals FROM (SELECT DISTINCT company FROM suppliers) _src
    ),
    _deduped AS (
        SELECT dedupe_2(_vals, 'same entity') as _json FROM _distinct_vals
    )
    SELECT unnest(from_json(_json, '["VARCHAR"]')) as value FROM _deduped

    With criteria:
    SELECT SEMANTIC DISTINCT company AS 'same business' FROM suppliers
    →
    Uses dedupe(..., 'same business')

    Also supports subqueries:
    SELECT SEMANTIC DISTINCT county FROM (SELECT * FROM bigfoot LIMIT 100)

    Key: Uses to_json(LIST()) to produce proper JSON format ["a","b"] instead of
    DuckDB's list format [a, b] which isn't valid JSON.
    """
    # Pattern: SELECT SEMANTIC DISTINCT col [AS 'criteria'] FROM (table_or_subquery)
    # Match either a simple table name OR a parenthesized subquery
    pattern = r"SELECT\s+SEMANTIC\s+DISTINCT\s+(\w+(?:\.\w+)?)\s*(?:AS\s+'([^']+)')?\s+FROM\s+(\([^)]+\)|\w+)"

    def replacer(match):
        col = match.group(1)
        criteria = match.group(2) or "same entity"
        source = match.group(3)  # Could be table name or (subquery)

        if annotation_prefix:
            criteria = f"{annotation_prefix}{criteria}"

        # Use CTE to properly aggregate, call dedupe, then unnest JSON array
        # Key insight: LIST()::VARCHAR produces DuckDB list format [a, b, c]
        # but dedupe_2 expects JSON format ["a", "b", "c"]
        # Use to_json(LIST()) to get proper JSON array
        return f"""WITH _distinct_vals AS (
    SELECT to_json(LIST({col})) as _vals FROM (SELECT DISTINCT {col} FROM {source}) _src
),
_deduped AS (
    SELECT dedupe_2(_vals, '{criteria}') as _json FROM _distinct_vals
)
SELECT unnest(from_json(_json, '["VARCHAR"]')) as value FROM _deduped"""

    return re.sub(pattern, replacer, query, flags=re.IGNORECASE)


def _rewrite_group_by_meaning(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite GROUP BY MEANING(col) to use semantic clustering.

    SELECT category, COUNT(*) FROM products GROUP BY MEANING(category)
    →
    SELECT _semantic_cluster as category, COUNT(*)
    FROM (
        SELECT *, meaning(category, (SELECT LIST(category)::VARCHAR FROM products)) as _semantic_cluster
        FROM products
    ) _clustered
    GROUP BY _semantic_cluster

    With number of clusters:
    GROUP BY MEANING(category, 5)

    With criteria:
    GROUP BY MEANING(category, 5, 'product type')
    """
    # Pattern: GROUP BY MEANING(col) or MEANING(col, n) or MEANING(col, n, 'criteria')
    pattern = r"GROUP\s+BY\s+MEANING\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*(\d+))?\s*(?:,\s*'([^']+)')?\s*\)"

    match = re.search(pattern, query, flags=re.IGNORECASE)
    if not match:
        return query

    col = match.group(1)
    num_clusters = match.group(2)
    criteria = match.group(3)

    if annotation_prefix and criteria:
        criteria = f"{annotation_prefix}{criteria}"
    elif annotation_prefix:
        criteria = annotation_prefix.rstrip(" -")

    # Find the FROM clause - could be table name or subquery
    # Match FROM followed by either (subquery) or table_name
    from_match = re.search(r"FROM\s+(\([^)]+\)|(\w+))", query, flags=re.IGNORECASE)
    if not from_match:
        return query

    source = from_match.group(1)  # Could be (subquery) or table_name
    is_subquery = source.startswith('(')

    # Build the meaning function call
    # Use to_json(LIST()) to get proper JSON format instead of DuckDB list format
    if num_clusters and criteria:
        meaning_call = f"meaning_4({col}, (SELECT to_json(LIST({col})) FROM {source}), {num_clusters}, '{criteria}')"
    elif num_clusters:
        meaning_call = f"meaning_3({col}, (SELECT to_json(LIST({col})) FROM {source}), {num_clusters})"
    elif criteria:
        meaning_call = f"meaning_4({col}, (SELECT to_json(LIST({col})) FROM {source}), NULL, '{criteria}')"
    else:
        meaning_call = f"meaning({col}, (SELECT to_json(LIST({col})) FROM {source}))"

    # Find SELECT columns and replace MEANING(...) expressions with _semantic_cluster
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, flags=re.IGNORECASE | re.DOTALL)
    if not select_match:
        return query

    select_cols = select_match.group(1)

    # Replace MEANING(col, ...) expressions with _semantic_cluster
    # Must handle: MEANING(col), MEANING(col, n), MEANING(col, n, 'criteria')
    # And preserve any AS alias: MEANING(col, n, 'criteria') as encounter_type
    meaning_in_select = rf"MEANING\s*\(\s*{re.escape(col)}\s*(?:,\s*\d+)?\s*(?:,\s*'[^']*')?\s*\)"
    new_select_cols = re.sub(meaning_in_select, '_semantic_cluster', select_cols, flags=re.IGNORECASE)

    # Also replace bare column references (not inside function calls)
    # Use negative lookbehind for '(' and negative lookahead for '(' to avoid function args
    # This handles: SELECT col, COUNT(*) → SELECT _semantic_cluster AS col, COUNT(*)
    bare_col_pattern = rf'(?<!\()\b{re.escape(col)}\b(?!\s*\()'
    # Only replace if it's a standalone column (not already replaced by MEANING rewrite)
    if f'_semantic_cluster' not in new_select_cols or re.search(bare_col_pattern, new_select_cols):
        # Check if there are any bare column references left (not inside function calls)
        # Simple heuristic: if the column appears before a comma or 'as' (case insensitive)
        # but NOT after an open paren, it's a bare reference
        new_select_cols = re.sub(
            rf'(?<![(\w]){re.escape(col)}(?=\s*(?:,|$|\bas\b))',
            f'_semantic_cluster AS {col}',
            new_select_cols,
            flags=re.IGNORECASE
        )

    # Build CTE-based rewrite (cleaner than nested subqueries)
    # 1. Create clustered source with semantic cluster column
    # 2. Select from clustered, group by cluster
    new_query = f"""WITH _clustered AS (
    SELECT *, {meaning_call} as _semantic_cluster
    FROM {source}
)
SELECT {new_select_cols}
FROM _clustered
GROUP BY _semantic_cluster"""

    # Preserve ORDER BY if present (only at the end of query, not in subquery)
    # Look for ORDER BY after the GROUP BY clause
    after_groupby = re.search(r"GROUP\s+BY\s+MEANING\s*\([^)]+\)\s*(ORDER\s+BY\s+.+?)(?:;|$)", query, flags=re.IGNORECASE | re.DOTALL)
    if after_groupby:
        order_clause = after_groupby.group(1).strip()
        new_query = f"{new_query}\n{order_clause}"

    return new_query


def _rewrite_group_by_topics(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite GROUP BY TOPICS(col, n) to extract topics and classify rows.

    SELECT title, COUNT(*) FROM articles GROUP BY TOPICS(content, 3)
    →
    WITH _topics_json AS (
        SELECT llm_themes_2(to_json(LIST(content)), 3) as _topics
        FROM articles
    ),
    _classified AS (
        SELECT *, classify_single(content, (SELECT _topics FROM _topics_json)) as _topic
        FROM articles
    )
    SELECT _topic, COUNT(*)
    FROM _classified
    GROUP BY _topic

    The approach:
    1. Extract N topics from ALL text values using llm_themes aggregate
    2. For each row, classify it into ONE of those topics
    3. Group by the assigned topic

    Also supports subqueries:
    SELECT col, COUNT(*) FROM (SELECT * FROM t LIMIT 100) GROUP BY TOPICS(col, 3)
    """
    # Pattern: GROUP BY TOPICS(col, n) or TOPICS(col)
    pattern = r"GROUP\s+BY\s+TOPICS\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*(\d+))?\s*\)"

    match = re.search(pattern, query, flags=re.IGNORECASE)
    if not match:
        return query

    col = match.group(1)
    num_topics = match.group(2) or "5"

    # Find the FROM clause - could be table name or subquery
    # Match FROM followed by either (subquery) or table_name
    from_match = re.search(r"FROM\s+(\([^)]+\)|(\w+))", query, flags=re.IGNORECASE)
    if not from_match:
        return query

    source = from_match.group(1)  # Could be (subquery) or table_name

    # Find SELECT columns and replace the grouped column with _topic AS original_name
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, flags=re.IGNORECASE | re.DOTALL)
    if not select_match:
        return query

    select_cols = select_match.group(1)
    # Replace column reference with topic, aliased back to original column name
    new_select_cols = re.sub(rf'\b{col}\b', f'_topic AS {col}', select_cols)

    # Build CTE-based rewrite
    # 1. Extract topics from all values using llm_themes_2 aggregate
    # 2. Classify each row into one of those topics
    # 3. Group by the assigned topic
    new_query = f"""WITH _topics_json AS (
    SELECT llm_themes_2(to_json(LIST({col})), {num_topics}) as _topics
    FROM {source}
),
_classified AS (
    SELECT *, classify_single({col}, (SELECT _topics FROM _topics_json)) as _topic
    FROM {source}
)
SELECT {new_select_cols}
FROM _classified
GROUP BY _topic"""

    return new_query


# ============================================================================
# Info
# ============================================================================

def get_semantic_operators_info() -> Dict[str, Any]:
    """Get information about supported semantic operators."""
    return {
        'version': '0.4.0',
        'supported_operators': {
            'MEANS': {
                'syntax': "col MEANS 'criteria'",
                'rewrites_to': "matches('criteria', col)",
                'description': 'Semantic boolean match'
            },
            'NOT MEANS': {
                'syntax': "col NOT MEANS 'criteria'",
                'rewrites_to': "NOT matches('criteria', col)",
                'description': 'Negated semantic boolean match'
            },
            'ABOUT': {
                'syntax': "col ABOUT 'criteria' [> threshold]",
                'rewrites_to': "score('criteria', col) > threshold",
                'description': 'Semantic score with threshold'
            },
            'NOT ABOUT': {
                'syntax': "col NOT ABOUT 'criteria' [> threshold]",
                'rewrites_to': "score('criteria', col) <= threshold",
                'description': 'Negated semantic score (excludes matches above threshold)'
            },
            '~': {
                'syntax': "a ~ b [AS 'relationship']",
                'rewrites_to': "match_pair(a, b, 'relationship')",
                'description': 'Semantic equality for JOINs'
            },
            '!~': {
                'syntax': "a !~ b [AS 'relationship']",
                'rewrites_to': "NOT match_pair(a, b, 'relationship')",
                'description': 'Negated semantic equality'
            },
            'RELEVANCE TO': {
                'syntax': "ORDER BY col RELEVANCE TO 'query'",
                'rewrites_to': "ORDER BY score('query', col) DESC",
                'description': 'Semantic ordering (most relevant first)'
            },
            'NOT RELEVANCE TO': {
                'syntax': "ORDER BY col NOT RELEVANCE TO 'query'",
                'rewrites_to': "ORDER BY score('query', col) ASC",
                'description': 'Inverted semantic ordering (least relevant first)'
            },
            'SEMANTIC JOIN': {
                'syntax': "SEMANTIC JOIN t ON a ~ b",
                'rewrites_to': "CROSS JOIN t WHERE match_pair(a, b, ...)",
                'description': 'Fuzzy JOIN'
            },
            'SEMANTIC DISTINCT': {
                'syntax': "SELECT SEMANTIC DISTINCT col [AS 'criteria'] FROM table",
                'rewrites_to': "SELECT unnest(dedupe(LIST(col), 'criteria'))",
                'description': 'Deduplicate by semantic similarity'
            },
            'GROUP BY MEANING': {
                'syntax': "GROUP BY MEANING(col[, n][, 'criteria'])",
                'rewrites_to': "GROUP BY meaning(col, all_values[, n][, 'criteria'])",
                'description': 'Group by semantic clusters'
            },
            'GROUP BY TOPICS': {
                'syntax': "GROUP BY TOPICS(col[, n])",
                'rewrites_to': "GROUP BY unnest(themes(col, n))",
                'description': 'Group by extracted themes/topics'
            },
            'IMPLIES': {
                'syntax': "a IMPLIES b / a IMPLIES 'conclusion'",
                'rewrites_to': "implies(a, b)",
                'description': 'Check if statement a implies statement b'
            },
            'CONTRADICTS': {
                'syntax': "a CONTRADICTS b / a CONTRADICTS 'statement'",
                'rewrites_to': "contradicts(a, b)",
                'description': 'Check if statements contradict each other'
            },
            'skill()': {
                'syntax': "skill('tool_name', json_object('arg', value))",
                'rewrites_to': "read_json_auto(skill(...))",
                'description': 'Call any registered skill/tool and return as table'
            },
            'skill::': {
                'syntax': "skill::tool_name(args)",
                'rewrites_to': "skill('tool_name', json_object(...))",
                'description': 'Namespace syntax sugar for skill() calls'
            },
            'skill:: with dot accessor': {
                'syntax': "skill::tool(x).field / skill::tool(x)[0] / skill::tool(x).a[0].b",
                'rewrites_to': "json_extract_string(skill_json(...), '$.field')",
                'description': 'Extract scalar value from skill result using JSON path (uses skill_json which returns content directly)'
            }
        },
        'annotation_support': {
            'prompt': "-- @ Free text prompt/model hints",
            'model': "-- @ model: provider/model-name",
            'threshold': "-- @ threshold: 0.7"
        }
    }


# ============================================================================
# Skill Syntax Sugar Rewriters
# ============================================================================

def _get_skill_params(skill_name: str) -> List[str]:
    """
    Get parameter names for a skill by introspecting its signature.

    Returns list of parameter names (excluding internal _params).
    Returns empty list if skill not found or introspection fails.
    """
    try:
        # Ensure skills are registered before looking them up
        # This is needed because SQL rewriting happens before cascade execution
        from .. import _register_all_skills
        _register_all_skills()

        from ..skill_registry import get_skill
        import inspect

        skill_func = get_skill(skill_name)
        if not skill_func:
            return []

        sig = inspect.signature(skill_func)
        params = []
        for name, param in sig.parameters.items():
            if not name.startswith('_'):  # Skip internal params
                params.append(name)
        return params
    except Exception:
        return []


def _rewrite_skill_namespace_syntax(query: str) -> str:
    """
    Rewrite skill::name() namespace syntax to skill() function calls.

    Supports:
    - Positional args: skill::say('Hello') → skill('say', json_object('text', 'Hello'))
    - Named args: skill::say(text := 'Hello') → skill('say', json_object('text', 'Hello'))
    - Mixed: skill::tool('first', other := 'val') → skill('tool', json_object('param1', 'first', 'other', 'val'))
    - No args: skill::list_skills() → skill('list_skills', '{}')
    - Dot accessor: skill::local_sentiment(title).label → json_extract_string(skill(...), '$.label')
    - Array accessor: skill::tool(x)[0] → json_extract_string(skill(...), '$[0]')
    - Chained: skill::tool(x).results[0].name → json_extract_string(skill(...), '$.results[0].name')

    The rewriter introspects skill signatures to map positional args to param names.
    When an accessor chain is present, the result is a scalar extraction rather than
    a table (no read_json_auto wrapper needed).
    """
    # Quick check - if no skill:: in query, skip
    if 'skill::' not in query.lower():
        return query

    def parse_accessor_chain(sql: str, start_pos: int) -> Tuple[int, str]:
        """
        Parse accessor chain starting at start_pos (after the closing paren).

        Handles:
        - .field → $.field
        - [0] → $[0]
        - .results[0].name → $.results[0].name

        Returns (end_pos, json_path) where json_path starts with '$'.
        If no accessor found, returns (start_pos, '').
        """
        pos = start_pos
        path_parts = []

        while pos < len(sql):
            ch = sql[pos]

            if ch == '.':
                # Dot accessor - parse field name
                pos += 1
                field_start = pos
                while pos < len(sql) and (sql[pos].isalnum() or sql[pos] == '_'):
                    pos += 1
                if pos > field_start:
                    field_name = sql[field_start:pos]
                    path_parts.append(f'.{field_name}')
                else:
                    # Dot not followed by identifier - stop parsing
                    pos -= 1  # Back up before the dot
                    break

            elif ch == '[':
                # Array accessor - parse index or key
                pos += 1
                bracket_content = []
                in_string = False
                string_char = None

                while pos < len(sql):
                    c = sql[pos]
                    if not in_string:
                        if c == ']':
                            pos += 1
                            break
                        elif c in ('"', "'"):
                            in_string = True
                            string_char = c
                            bracket_content.append(c)
                        else:
                            bracket_content.append(c)
                    else:
                        bracket_content.append(c)
                        if c == string_char:
                            # Check for escaped quote
                            if pos + 1 < len(sql) and sql[pos + 1] == string_char:
                                bracket_content.append(sql[pos + 1])
                                pos += 1
                            else:
                                in_string = False
                    pos += 1

                if bracket_content:
                    path_parts.append(f'[{"".join(bracket_content)}]')
            else:
                # Not an accessor character - stop parsing
                break

        if path_parts:
            return (pos, '$' + ''.join(path_parts))
        return (start_pos, '')

    def parse_skill_call(sql: str, start_pos: int) -> Optional[Tuple[int, str, str, str]]:
        """
        Parse a skill::name(...) call starting at start_pos.

        Returns (end_pos, skill_name, json_object_expr, accessor_path) or None if parse fails.
        accessor_path is a JSON path like '$.label' or '' if no accessor.
        """
        # Match skill::name pattern
        match = re.match(r'skill::(\w+)\s*\(', sql[start_pos:], re.IGNORECASE)
        if not match:
            return None

        skill_name = match.group(1)
        paren_start = start_pos + match.end() - 1  # Position of (

        # Find matching closing paren
        paren_count = 1
        pos = paren_start + 1
        while pos < len(sql) and paren_count > 0:
            if sql[pos] == '(':
                paren_count += 1
            elif sql[pos] == ')':
                paren_count -= 1
            elif sql[pos] == "'" and paren_count > 0:
                # Skip string literal
                pos += 1
                while pos < len(sql) and sql[pos] != "'":
                    if sql[pos] == "'" and pos + 1 < len(sql) and sql[pos + 1] == "'":
                        pos += 2  # Escaped quote
                    else:
                        pos += 1
            pos += 1

        if paren_count != 0:
            return None

        # Extract args string (between parens)
        args_str = sql[paren_start + 1:pos - 1].strip()
        end_pos = pos

        # Parse args into json_object expression
        json_obj_expr = _parse_skill_args(skill_name, args_str)

        # Check for accessor chain after the closing paren
        accessor_end, accessor_path = parse_accessor_chain(sql, end_pos)
        if accessor_path:
            end_pos = accessor_end

        return (end_pos, skill_name, json_obj_expr, accessor_path)

    def _parse_skill_args(skill_name: str, args_str: str) -> str:
        """
        Parse skill arguments and generate json_object() expression.

        Handles:
        - Empty: '' → '{}'
        - Positional: 'value' → json_object('param1', 'value')
        - Named: 'param := value' → json_object('param', value)
        - Mixed: 'val1, param2 := val2' → json_object('param1', val1, 'param2', val2)
        """
        if not args_str:
            return "'{}'"

        # Get skill's parameter names for positional mapping
        param_names = _get_skill_params(skill_name)

        # Parse arguments (handle nested parens and strings)
        args = _split_args(args_str)

        if not args:
            return "'{}'"

        # Build json_object arguments
        json_parts = []
        positional_idx = 0

        for arg in args:
            arg = arg.strip()

            # Check for named parameter (param := value or param => value)
            named_match = re.match(r'(\w+)\s*(?::=|=>)\s*(.+)$', arg, re.DOTALL)

            if named_match:
                param_name = named_match.group(1)
                value = named_match.group(2).strip()
                json_parts.append(f"'{param_name}'")
                json_parts.append(value)
            else:
                # Positional argument - map to param name
                if positional_idx < len(param_names):
                    param_name = param_names[positional_idx]
                else:
                    param_name = f"arg{positional_idx + 1}"
                json_parts.append(f"'{param_name}'")
                json_parts.append(arg)
                positional_idx += 1

        if not json_parts:
            return "'{}'"

        return f"json_object({', '.join(json_parts)})"

    def _split_args(args_str: str) -> List[str]:
        """Split argument string by commas, respecting nested parens and strings."""
        args = []
        current = []
        paren_depth = 0
        in_string = False
        i = 0

        while i < len(args_str):
            ch = args_str[i]

            if ch == "'" and not in_string:
                in_string = True
                current.append(ch)
            elif ch == "'" and in_string:
                # Check for escaped quote
                if i + 1 < len(args_str) and args_str[i + 1] == "'":
                    current.append("''")
                    i += 1
                else:
                    in_string = False
                    current.append(ch)
            elif in_string:
                current.append(ch)
            elif ch == '(':
                paren_depth += 1
                current.append(ch)
            elif ch == ')':
                paren_depth -= 1
                current.append(ch)
            elif ch == ',' and paren_depth == 0:
                args.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)

            i += 1

        if current:
            args.append(''.join(current).strip())

        return args

    # Find and replace all skill::name() patterns
    result = []
    last_end = 0

    # Find all occurrences of skill::
    pattern = re.compile(r'skill::', re.IGNORECASE)

    for match in pattern.finditer(query):
        start = match.start()

        # Try to parse the full skill::name(...) call
        parsed = parse_skill_call(query, start)

        if parsed:
            end_pos, skill_name, json_obj_expr, accessor_path = parsed

            # Add everything before this match
            result.append(query[last_end:start])

            # Generate the rewritten expression
            if accessor_path:
                # Scalar extraction mode - use skill_json() which returns JSON content directly
                # (skill() returns a file path for read_json_auto, which doesn't work with json_extract_string)
                skill_call = f"skill_json('{skill_name}', {json_obj_expr})"
                result.append(f"json_extract_string({skill_call}, '{accessor_path}')")
            else:
                # Table mode - use skill() which returns file path (read_json_auto added later by _rewrite_skill_function)
                skill_call = f"skill('{skill_name}', {json_obj_expr})"
                result.append(skill_call)

            last_end = end_pos

    # Add remaining content
    result.append(query[last_end:])

    return ''.join(result)


def _rewrite_skill_block_syntax(query: str) -> str:
    """
    Rewrite SKILL name ... END block syntax to skill() function calls.

    Supports multi-line parameter specification:
        SELECT * FROM SKILL say
          text = 'Hello from SQL'
          voice_id = 'abc123'
        END

    Becomes:
        SELECT * FROM skill('say', json_object('text', 'Hello from SQL', 'voice_id', 'abc123'))

    Also supports single-line:
        SELECT * FROM SKILL list_skills END
    """
    # Quick check - if no SKILL keyword, skip
    if 'SKILL ' not in query.upper():
        return query

    # Pattern to match SKILL name ... END blocks
    # SKILL followed by skill name, then params until END
    pattern = re.compile(
        r'\bSKILL\s+(\w+)\s*(.*?)\s*\bEND\b',
        re.IGNORECASE | re.DOTALL
    )

    def parse_block_params(params_str: str) -> str:
        """Parse param = value lines into json_object() expression."""
        params_str = params_str.strip()
        if not params_str:
            return "'{}'"

        # Split by lines or by param = value pattern
        # Handle both:
        #   text = 'Hello'
        #   count = 5
        # And:
        #   text = 'Hello', count = 5

        json_parts = []

        # Pattern for param = value (value can be string, number, or expression)
        param_pattern = re.compile(
            r"(\w+)\s*=\s*("
            r"'(?:[^']|'')*'"  # Single-quoted string
            r"|\"(?:[^\"]|\"\")*\""  # Double-quoted string
            r"|\d+(?:\.\d+)?"  # Number
            r"|[^\s,\n]+"  # Other expression (until whitespace/comma/newline)
            r")",
            re.MULTILINE
        )

        for match in param_pattern.finditer(params_str):
            param_name = match.group(1)
            value = match.group(2)
            json_parts.append(f"'{param_name}'")
            json_parts.append(value)

        if not json_parts:
            return "'{}'"

        return f"json_object({', '.join(json_parts)})"

    def replacer(match):
        skill_name = match.group(1)
        params_str = match.group(2)

        json_obj_expr = parse_block_params(params_str)
        return f"skill('{skill_name}', {json_obj_expr})"

    return pattern.sub(replacer, query)


def _rewrite_skill_function(query: str) -> str:
    """
    Rewrite skill() function calls to wrap in read_json_auto() for table output.

    The skill() function is a universal caller for any registered skill/tool.
    It returns JSON that needs read_json_auto() to become a table.

    SQL Usage:
        SELECT * FROM skill('say', json_object('text', 'Hello world'))

    Becomes:
        SELECT * FROM read_json_auto(skill('say', json_object('text', 'Hello world')))

    With LATERAL:
        SELECT t.id, r.* FROM messages t, LATERAL skill('say', json_object('text', t.content)) r

    Becomes:
        SELECT t.id, r.* FROM messages t, LATERAL read_json_auto(skill('say', json_object('text', t.content))) r

    The function detects skill() in FROM clauses and wraps appropriately.
    Does NOT wrap if:
    - Already inside read_json_auto()
    - Already inside json_extract_string() (scalar extraction via dot accessor)
    """
    # Quick check - if no skill( in query, skip
    if 'skill(' not in query.lower():
        return query

    # Find all positions where we have FROM/LATERAL/JOIN/comma followed by skill(
    # and wrap with read_json_auto() if not already wrapped
    pattern = re.compile(
        r'((?:FROM|LATERAL|JOIN)\s+|,\s*)(skill\s*\()',
        re.IGNORECASE
    )

    result = []
    last_end = 0

    for match in pattern.finditer(query):
        start = match.start()
        prefix = match.group(1)

        # Check if already wrapped (look back for read_json_auto or json_extract_string)
        lookback = query[max(0, start - 25):start].lower()
        if 'read_json_auto(' in lookback or 'json_extract_string(' in lookback:
            continue

        # Find the matching closing paren for skill(
        paren_count = 1
        pos = match.end()

        while pos < len(query) and paren_count > 0:
            if query[pos] == '(':
                paren_count += 1
            elif query[pos] == ')':
                paren_count -= 1
            pos += 1

        if paren_count != 0:
            # Unbalanced - skip
            continue

        # pos now points just after the closing )
        skill_call = query[match.start(2):pos]

        # Add everything before this match
        result.append(query[last_end:match.start()])
        # Add the wrapped version
        result.append(f"{prefix}read_json_auto({skill_call})")
        last_end = pos

    # Add remaining content
    result.append(query[last_end:])
    return ''.join(result)


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

## Negation Operators

```sql
-- NOT MEANS: Exclude semantic matches
SELECT * FROM products
WHERE description NOT MEANS 'contains plastic'

-- NOT ABOUT: Exclude content scoring above threshold
SELECT * FROM articles
WHERE content NOT ABOUT 'politics' > 0.3

-- !~: Negated semantic equality (not the same entity)
SELECT * FROM transactions t1, transactions t2
WHERE t1.merchant !~ t2.merchant
  AND t1.amount = t2.amount

-- NOT RELEVANCE TO: Order by least relevant first (find outliers)
SELECT * FROM support_tickets
ORDER BY description NOT RELEVANCE TO 'common issues'
LIMIT 10
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

## skill:: Namespace Syntax

```sql
-- Table mode: returns all columns as a table
SELECT * FROM skill::sql_search('bigfoot sightings')

-- With named parameters
SELECT * FROM skill::sql_search(query := 'bigfoot', use_smart := true)
```

## skill:: Dot Accessor (Scalar Extraction)

```sql
-- Extract single field from skill result
SELECT
  title,
  skill::local_sentiment(title).label as sentiment,
  skill::local_sentiment(title).score as confidence
FROM articles

-- Array index accessor
SELECT skill::list_tables(schema := 'public')[0] as first_table

-- Chained accessor for nested results
SELECT skill::api_call(endpoint := '/users').data[0].name as first_user

-- Use in WHERE clause
SELECT * FROM products
WHERE skill::local_sentiment(description).label = 'POSITIVE'

-- Combine with other semantic operators
SELECT
  title,
  skill::local_sentiment(title).label as sentiment
FROM articles
WHERE title MEANS 'technology news'
ORDER BY title RELEVANCE TO 'AI breakthroughs'
```
"""
