"""
Aggregate Function Registry - Bridge between cascades and EXPLAIN system.

Provides dynamic aggregate function metadata from cascade registry,
replacing the hardcoded LLM_AGG_FUNCTIONS and LLM_AGG_ALIASES dicts.

This allows:
- EXPLAIN queries to work with user-defined aggregates
- No hardcoded function lists
- Automatic detection of new cascades
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class AggregateFunction:
    """Metadata for an aggregate function (from cascade)."""
    name: str              # Canonical name (e.g., "llm_summarize")
    aliases: List[str]     # Short aliases (e.g., ["SUMMARIZE"])
    min_args: int          # Minimum arguments
    max_args: int          # Maximum arguments
    return_type: str       # SQL return type
    impl_name: str         # Implementation function name
    cascade_path: str      # Path to cascade file


# Cache
_aggregate_registry: Optional[Dict[str, AggregateFunction]] = None


def get_aggregate_registry(force: bool = False) -> Dict[str, AggregateFunction]:
    """
    Get all AGGREGATE-shaped functions from cascade registry.

    Returns:
        Dict mapping canonical function name → AggregateFunction
    """
    global _aggregate_registry

    if _aggregate_registry is not None and not force:
        return _aggregate_registry

    from lars.semantic_sql.registry import get_sql_function_registry

    registry = get_sql_function_registry()
    aggregates = {}

    for fn_name, entry in registry.items():
        shape = entry.sql_function.get('shape', 'SCALAR')
        if shape.upper() != 'AGGREGATE':
            continue

        # Extract argument info
        args = entry.sql_function.get('args', [])
        # Args are required unless marked optional or have default
        min_args = sum(1 for arg in args if not arg.get('optional') and not arg.get('default'))
        max_args = len(args)

        # Extract aliases from operators
        aliases = []
        for op_template in entry.operators:
            # Extract function name from template like "SUMMARIZE({{ col }})"
            import re
            match = re.match(r'^(\w+)\s*\(', op_template)
            if match:
                alias = match.group(1)
                # Don't add canonical name as alias
                if alias.lower() != fn_name.lower():
                    aliases.append(alias)

        # Implementation name (usually same as cascade name)
        impl_name = entry.sql_function.get('impl_name', fn_name + '_impl')

        agg_func = AggregateFunction(
            name=fn_name,
            aliases=aliases,
            min_args=min_args,
            max_args=max_args,
            return_type=entry.returns,
            impl_name=impl_name,
            cascade_path=entry.cascade_path,
        )

        aggregates[fn_name] = agg_func

    _aggregate_registry = aggregates
    log.debug(f"[aggregate_registry] Loaded {len(aggregates)} aggregate functions")

    return aggregates


def get_aggregate_aliases() -> Dict[str, str]:
    """
    Get mapping of alias → canonical name for aggregate functions.

    Example:
        {"SUMMARIZE": "llm_summarize", "CLASSIFY": "llm_classify"}
    """
    registry = get_aggregate_registry()
    aliases = {}

    for canonical_name, agg_func in registry.items():
        for alias in agg_func.aliases:
            aliases[alias] = canonical_name

    return aliases


def get_all_aggregate_names() -> List[str]:
    """
    Get list of ALL aggregate function names (canonical + aliases).

    Used for pattern matching in EXPLAIN queries.

    Returns:
        List of function names (uppercase)
    """
    registry = get_aggregate_registry()
    names = []

    for canonical_name, agg_func in registry.items():
        names.append(canonical_name.upper())
        for alias in agg_func.aliases:
            names.append(alias.upper())

    return names


def lookup_aggregate_function(name: str) -> Optional[AggregateFunction]:
    """
    Look up aggregate function by name (canonical or alias).

    Args:
        name: Function name (e.g., "SUMMARIZE" or "llm_summarize")

    Returns:
        AggregateFunction if found, None otherwise
    """
    registry = get_aggregate_registry()
    name_upper = name.upper()

    # Try canonical name first
    for canonical_name, agg_func in registry.items():
        if canonical_name.upper() == name_upper:
            return agg_func

    # Try aliases
    aliases = get_aggregate_aliases()
    canonical = aliases.get(name_upper)
    if canonical:
        return registry.get(canonical)

    return None


# ============================================================================
# Aggregate Function Interface
# ============================================================================
# Returns aggregate function metadata derived purely from cascade definitions.
# NO legacy mappings - uses cascade names directly.


def get_llm_agg_functions_compat() -> Tuple[Dict, Dict]:
    """
    Return aggregate function metadata derived from cascade definitions.

    FULLY DYNAMIC: No hardcoded mappings. Everything comes from cascade YAML.
    - Function names use cascade names directly (e.g., semantic_cluster)
    - Aliases come from cascade operators (e.g., MEANING → semantic_cluster)
    - Args come from cascade inputs_schema

    The rewriter generates calls like `semantic_cluster_3(...)` which
    dynamic registration handles via execute_cascade_udf().

    Returns:
        Tuple of (functions_dict, aliases_dict)
    """
    from dataclasses import dataclass as compat_dataclass

    @compat_dataclass
    class LLMAggFunctionCompat:
        name: str
        impl_name: str  # Now just the cascade name (no _impl suffix)
        min_args: int
        max_args: int
        return_type: str
        arg_template: str = "LIST({col})::VARCHAR{extra_args}"

    # Force reload to get fresh cascade data after server restart
    registry = get_aggregate_registry(force=True)

    functions = {}
    aliases = {}

    for canonical_name, agg_func in registry.items():
        # Use cascade name directly - no legacy mapping needed
        func_key = canonical_name.upper()

        compat_func = LLMAggFunctionCompat(
            name=func_key,
            impl_name=canonical_name,  # Just the cascade name, no _impl
            min_args=agg_func.min_args,
            max_args=agg_func.max_args,
            return_type=agg_func.return_type,
        )

        functions[func_key] = compat_func

        # Build aliases mapping (alias → canonical name)
        # e.g., MEANING → SEMANTIC_CLUSTER
        for alias in agg_func.aliases:
            aliases[alias.upper()] = func_key

    return functions, aliases
