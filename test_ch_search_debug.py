#!/usr/bin/env python3
"""Debug what ClickHouse search generates."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

user_query = "SELECT * FROM VECTOR_SEARCH('climate', bird_line.text, 10)"

print("User Query:")
print(user_query)
print("\n" + "=" * 80)
print("Rewritten SQL:")
print("=" * 80)

result = rewrite_rvbbit_syntax(user_query)
print(result)

print("\n" + "=" * 80)
print("Analysis:")
print("=" * 80)

if "SELECT * FROM read_json_auto" in result:
    print("✅ Has 'SELECT * FROM read_json_auto(...)' - should return table")
elif "read_json_auto" in result:
    print("⚠️  Has read_json_auto but not in FROM clause properly")
    print("   Might be: SELECT read_json_auto(...) instead of SELECT * FROM read_json_auto(...)")
else:
    print("❌ No read_json_auto at all")

# Check if it's wrapped properly
import re
if re.search(r'SELECT \* FROM read_json_auto\(vector_search_json_\d+', result):
    print("✅ Properly formatted: SELECT * FROM read_json_auto(vector_search_json_*)")
else:
    print("❌ Not properly formatted")

print("\nExpected format:")
print("  SELECT * FROM read_json_auto(vector_search_json_3(...))")
print("\nThis should return a table with columns: id, text, similarity, distance")
