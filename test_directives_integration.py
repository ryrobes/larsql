#!/usr/bin/env python3
"""
Test BACKGROUND and ANALYZE directive integration with unified rewriter.
"""

import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("=" * 80)
print("BACKGROUND & ANALYZE DIRECTIVES TEST")
print("=" * 80)

from rvbbit.sql_tools.unified_operator_rewriter import rewrite_all_operators

test_cases = [
    # BACKGROUND without semantic ops - directive STRIPPED
    ("BACKGROUND SELECT * FROM products",
     "SELECT * FROM products",
     "BACKGROUND stripped, plain SQL"),

    # BACKGROUND with semantic operator - directive STRIPPED, operator REWRITTEN
    ("BACKGROUND SELECT * FROM t WHERE col MEANS 'sustainability'",
     "semantic_matches(col, 'sustainability')",
     "BACKGROUND stripped, MEANS rewritten"),

    # ANALYZE without semantic ops - directive STRIPPED
    ("ANALYZE 'why are sales low?' SELECT * FROM sales",
     "SELECT * FROM sales",
     "ANALYZE stripped, plain SQL"),

    # ANALYZE with semantic operator - directive STRIPPED, operator REWRITTEN
    ("ANALYZE 'what patterns exist?' SELECT * FROM t WHERE col ABOUT 'growth'",
     "semantic_score(col, 'growth')",
     "ANALYZE stripped, ABOUT rewritten"),

    # No directive - just rewrite
    ("SELECT * FROM t WHERE col MEANS 'x'",
     "semantic_matches(col, 'x')",
     "Direct rewrite without directive"),
]

passed = 0
failed = 0

for i, (input_sql, expected_contains, description) in enumerate(test_cases, 1):
    print(f"\n[Test {i}] {description}")
    print(f"Input:    {input_sql}")

    result = rewrite_all_operators(input_sql)
    print(f"Output:   {result}")

    if expected_contains in result:
        print(f"✅ PASS - Contains: {expected_contains}")
        passed += 1
    else:
        print(f"❌ FAIL - Expected to contain: {expected_contains}")
        print(f"   Got: {result}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)
