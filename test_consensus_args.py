#!/usr/bin/env python3
"""Test that CONSENSUS accepts 2 args after fix."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

test_cases = [
    ("SELECT CONSENSUS(text) FROM t",
     "llm_consensus_1"),  # 1-arg version

    ("SELECT CONSENSUS(text, 'what is common?') FROM t",
     "llm_consensus_2"),  # 2-arg version
]

for sql, expected in test_cases:
    print(f"\nInput:  {sql}")
    rewritten = rewrite_rvbbit_syntax(sql)
    print(f"Output: {rewritten}")
    if expected in rewritten:
        print(f"✅ Contains {expected}")
    else:
        print(f"❌ Missing {expected}")
