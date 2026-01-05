#!/usr/bin/env python3
"""Debug argument counts from registry."""

from rvbbit.sql_tools.aggregate_registry import get_llm_agg_functions_compat

funcs, aliases = get_llm_agg_functions_compat()

print("Aggregate Function Argument Counts:")
print("=" * 80)

for name, func in sorted(funcs.items()):
    print(f"{name}:")
    print(f"  min_args: {func.min_args}")
    print(f"  max_args: {func.max_args}")
    print(f"  impl_name: {func.impl_name}")
    print()
