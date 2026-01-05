#!/usr/bin/env python3
"""Test the user's exact query."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

user_query = """
RVBBIT EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text FROM bird_line limit 10);
"""

print("User's Query:")
print(user_query)
print("\n" + "=" * 80)
print("Rewritten SQL:")
print("=" * 80)

result = rewrite_rvbbit_syntax(user_query)
print(result)

print("\n" + "=" * 80)
print("Verification:")
print("=" * 80)

checks = [
    ("embed_batch function", "embed_batch" in result),
    ("Table name 'bird_line'", "'bird_line'" in result),
    ("Column name 'text'", "'text'" in result),
    ("JSON wrapping (to_json)", "to_json" in result),
    ("JSON wrapping (list)", "list(" in result),
    ("JSON object structure", "{'id': id, 'text': text}" in result),
    ("USING query wrapped as subquery", "AS _src" in result),
]

all_good = True
for check_name, check_result in checks:
    status = "✅" if check_result else "❌"
    print(f"{status} {check_name}")
    if not check_result:
        all_good = False

if all_good:
    print("\n✅ Query should work now!")
else:
    print("\n❌ Some checks failed")
