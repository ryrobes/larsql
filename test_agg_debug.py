#!/usr/bin/env python3
"""Debug aggregate function lookup."""

from rvbbit.sql_tools.llm_agg_rewriter import _find_llm_agg_calls, _resolve_alias
from rvbbit.sql_tools.aggregate_registry import get_llm_agg_functions_compat, get_aggregate_aliases

sql = "SELECT SUMMARIZE(title) FROM t"

print("Step 1: Find calls")
calls = _find_llm_agg_calls(sql)
print(f"Found {len(calls)} calls:")
for start, end, func_name, args in calls:
    print(f"  {func_name} with args {args}")

print("\nStep 2: Resolve alias")
resolved = _resolve_alias("SUMMARIZE")
print(f"SUMMARIZE resolves to: {resolved}")

print("\nStep 3: Get compat registry")
funcs, aliases = get_llm_agg_functions_compat()
print(f"Functions dict keys: {list(funcs.keys())}")
print(f"Aliases dict: {aliases}")

print("\nStep 4: Lookup function")
if calls:
    func_name = calls[0][2]
    print(f"Looking up: {func_name.upper()}")
    func_def = funcs.get(func_name.upper())
    print(f"Found: {func_def}")
