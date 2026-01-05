#!/usr/bin/env python3
"""Test aggregate registry after fresh load."""

# Force fresh load
from rvbbit.sql_tools.aggregate_registry import get_llm_agg_functions_compat
from rvbbit.semantic_sql.registry import initialize_registry

print("Forcing fresh registry load...")
initialize_registry(force=True)

funcs, aliases = get_llm_agg_functions_compat()

print("\nAggregate Functions:")
for name, func in sorted(funcs.items()):
    print(f"{name}: min={func.min_args}, max={func.max_args}, impl={func.impl_name}")

print(f"\nAliases:")
for alias, canonical in sorted(aliases.items()):
    print(f"  {alias} → {canonical}")
