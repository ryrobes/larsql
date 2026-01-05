#!/usr/bin/env python3
"""Debug why vector_search_elastic is being caught by aggregate rewriter."""

from rvbbit.sql_tools.llm_agg_rewriter import _find_llm_agg_calls

sql = "SELECT * FROM vector_search_elastic('climate', 'articles', 10, 0.0, 1.0, 0.0)"

print("SQL:", sql)
print("\nFinding aggregate calls...")

calls = _find_llm_agg_calls(sql)

print(f"Found {len(calls)} calls:")
for start, end, func_name, args in calls:
    print(f"  Function: {func_name}")
    print(f"  Args: {args}")
    print(f"  Position: {start}-{end}")
