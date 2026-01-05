#!/usr/bin/env python3
"""Debug the rewrite order to see what's happening."""

from rvbbit.sql_tools.vector_search_rewriter import rewrite_vector_search
from rvbbit.sql_tools.llm_agg_rewriter import process_llm_aggregates, has_llm_aggregates
from rvbbit.sql_tools.unified_operator_rewriter import rewrite_all_operators

sql = "SELECT * FROM ELASTIC_SEARCH('climate', articles.content, 10)"

print("=" * 80)
print("REWRITE ORDER DEBUG")
print("=" * 80)

print(f"\n[Original]")
print(sql)

print(f"\n[Step 1: Vector search rewriter]")
step1 = rewrite_vector_search(sql)
print(step1[:200])

print(f"\n[Step 2: Check if aggregate rewriter detects it]")
has_agg = has_llm_aggregates(step1)
print(f"has_llm_aggregates: {has_agg}")

if has_agg:
    print("\n[Step 3: Aggregate rewriter (should NOT run on this)]")
    step3 = process_llm_aggregates(step1)
    print(step3[:200])
    if step1 != step3:
        print("❌ PROBLEM: Aggregate rewriter changed it!")
    else:
        print("✅ Good: Aggregate rewriter left it alone")

print(f"\n[Step 4: Full unified rewriter]")
final = rewrite_all_operators(sql)
print(final[:200])
