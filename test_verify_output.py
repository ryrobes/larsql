#!/usr/bin/env python3
"""Verify the actual generated SQL for all search functions."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

queries = [
    "SELECT * FROM VECTOR_SEARCH('climate', bird_line.text, 10)",
    "SELECT * FROM ELASTIC_SEARCH('climate', bird_line.text, 10)",
]

for sql in queries:
    print("=" * 80)
    print(f"Input: {sql}")
    print("=" * 80)
    result = rewrite_rvbbit_syntax(sql)
    print(result)
    print("\n")
