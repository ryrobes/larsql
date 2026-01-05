#!/usr/bin/env python3
"""Debug aggregate detection and rewriting."""

from rvbbit.sql_tools.llm_agg_rewriter import has_llm_aggregates, process_llm_aggregates

sql = "SELECT state, SUMMARIZE(title) as summary FROM bigfoot GROUP BY state"

print(f"Query: {sql}")
print(f"Has aggregates: {has_llm_aggregates(sql)}")

try:
    rewritten = process_llm_aggregates(sql)
    print(f"Rewritten: {rewritten}")
    print(f"Changed: {rewritten != sql}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
