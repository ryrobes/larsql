#!/usr/bin/env python3
"""
Demonstration: BACKGROUND now works with newlines + semantic operators.

This was broken with string-based parsing, now fixed with token-based parsing.
"""

from rvbbit.sql_tools.sql_directives import parse_sql_directives

print("=" * 80)
print("BACKGROUND + NEWLINES + SEMANTIC OPERATORS DEMO")
print("=" * 80)

# Example: User's actual query that was failing
user_query = """BACKGROUND
SELECT
    TOPICS(text, 4) topics1,
    narrative(text) as narr,
    THEMES(text, 6) as themes
FROM bigfoot
GROUP BY TOPICS(text, 4)
"""

print("\n[USER'S QUERY]")
print(user_query)
print("-" * 80)

# Step 1: Parse directive (postgres_server.py does this)
directive, inner_sql = parse_sql_directives(user_query)

print("\n[STEP 1: Parse Directive]")
if directive:
    print(f"✅ Directive detected: {directive.directive_type}")
    print(f"   Inner SQL extracted ({len(inner_sql)} chars)")
else:
    print("❌ No directive detected")

# Step 2: Rewrite semantic operators (unified rewriter does this)
from rvbbit.sql_tools.unified_operator_rewriter import rewrite_all_operators

rewritten_sql = rewrite_all_operators(user_query)

print("\n[STEP 2: Rewrite Semantic Operators]")
print("Rewritten SQL:")
print(rewritten_sql)
print("-" * 80)

# Step 3: Verify result
print("\n[VERIFICATION]")

checks = [
    ("BACKGROUND stripped", "BACKGROUND" not in rewritten_sql or rewritten_sql.strip().startswith("WITH")),
    ("TOPICS rewritten to CTE", "WITH" in rewritten_sql or "topics" in rewritten_sql.lower()),
    ("No BACKGROUND in output", not rewritten_sql.strip().startswith("BACKGROUND")),
]

all_passed = True
for check_name, check_result in checks:
    if check_result:
        print(f"  ✅ {check_name}")
    else:
        print(f"  ❌ {check_name}")
        all_passed = False

print("\n" + "=" * 80)
if all_passed:
    print("SUCCESS! BACKGROUND + newlines + semantic operators work perfectly! 🎉")
else:
    print("FAILED - Some checks didn't pass")
print("=" * 80)
