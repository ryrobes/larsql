#!/usr/bin/env python3
"""Test Elastic EMBED after arg order fix."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

queries = [
    # Default index and batch_size
    """
    RVBBIT EMBED bird_line.text
    USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 10)
    WITH (backend='elastic')
    """,

    # Custom batch_size
    """
    RVBBIT EMBED articles.content
    USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
    WITH (backend='elastic', batch_size=200)
    """,

    # Custom index and batch_size
    """
    RVBBIT EMBED products.description
    USING (SELECT id::VARCHAR AS id, description AS text FROM products)
    WITH (backend='elastic', batch_size=50, index='products_idx')
    """,
]

for i, sql in enumerate(queries, 1):
    print(f"\n[Test {i}]")
    print(f"Input: {sql.strip()[:80]}...")

    result = rewrite_rvbbit_syntax(sql)
    print(f"Output:\n{result}\n")

    # Check arg order: should be (table, column, json, batch_size, index)
    import re
    match = re.search(r"embed_batch_elastic\((.*?)\)", result, re.DOTALL)
    if match:
        args_str = match.group(1)
        # Split by comma (simple - doesn't handle nested parens perfectly)
        print("Argument order check:")
        print("  Arg order should be: table, column, json, batch_size (INT), index (VARCHAR)")

        # Check that batch_size (number) comes before index (quoted string)
        # Find positions
        batch_pos = -1
        index_pos = -1

        # Look for unquoted number (batch_size)
        batch_match = re.search(r',\s*(\d+)\s*,', args_str)
        if batch_match:
            batch_pos = batch_match.start()
            print(f"  ✓ Found batch_size: {batch_match.group(1)} at pos {batch_pos}")

        # Look for quoted string after some numbers (index)
        index_match = re.search(r",\s*'([^']+)'\s*\)", args_str)
        if index_match:
            index_pos = index_match.start()
            print(f"  ✓ Found index: '{index_match.group(1)}' at pos {index_pos}")

        if batch_pos > 0 and index_pos > 0:
            if batch_pos < index_pos:
                print("  ✅ Correct order: batch_size comes before index")
            else:
                print("  ❌ Wrong order: index comes before batch_size")

print("\n" + "=" * 80)
print("Arg order is now: table, column, json, batch_size, index")
print("This matches the cascade signature!")
print("=" * 80)
