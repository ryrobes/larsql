#!/usr/bin/env python3
"""Test that SUMMARIZE accepts extra args now."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

queries = [
    "SELECT SUMMARIZE(col) FROM t",
    "SELECT SUMMARIZE(col, 'custom prompt') FROM t",
    "SELECT SUMMARIZE(col, 'custom prompt', 50) FROM t",
]

for sql in queries:
    print(f"\nInput:  {sql}")
    try:
        rewritten = rewrite_rvbbit_syntax(sql)
        print(f"Output: {rewritten}")
    except Exception as e:
        print(f"ERROR:  {e}")
