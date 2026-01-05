#!/usr/bin/env python3
"""
Test that BACKGROUND and ANALYZE directives handle newlines properly.
"""

from rvbbit.sql_tools.sql_directives import parse_sql_directives

print("=" * 80)
print("DIRECTIVE NEWLINE HANDLING TEST")
print("=" * 80)

test_cases = [
    # BACKGROUND with space
    ("BACKGROUND SELECT * FROM t", "BACKGROUND", "SELECT * FROM t"),

    # BACKGROUND with newline
    ("BACKGROUND\nSELECT * FROM t", "BACKGROUND", "SELECT * FROM t"),

    # BACKGROUND with multiple newlines and spaces
    ("BACKGROUND\n\n  SELECT * FROM t", "BACKGROUND", "SELECT * FROM t"),

    # BACKGROUND with tabs
    ("BACKGROUND\t\tSELECT * FROM t", "BACKGROUND", "SELECT * FROM t"),

    # ANALYZE with space
    ("ANALYZE 'why?' SELECT * FROM t", "ANALYZE", "SELECT * FROM t"),

    # ANALYZE with newline after keyword
    ("ANALYZE\n'why?' SELECT * FROM t", "ANALYZE", "SELECT * FROM t"),

    # ANALYZE with newline after prompt
    ("ANALYZE 'why?'\nSELECT * FROM t", "ANALYZE", "SELECT * FROM t"),

    # ANALYZE with newlines everywhere
    ("ANALYZE\n'why?'\n\nSELECT * FROM t", "ANALYZE", "SELECT * FROM t"),
]

passed = 0
failed = 0

for i, (input_sql, expected_type, expected_inner) in enumerate(test_cases, 1):
    print(f"\n[Test {i}]")
    print(f"Input (repr): {input_sql!r}")

    directive, inner_sql = parse_sql_directives(input_sql)

    if directive and directive.directive_type == expected_type:
        inner_sql_stripped = inner_sql.strip()
        expected_stripped = expected_inner.strip()

        if expected_stripped in inner_sql_stripped:
            print(f"✅ PASS")
            print(f"   Type: {directive.directive_type}")
            print(f"   Inner: {inner_sql_stripped[:50]}...")
            if directive.prompt:
                print(f"   Prompt: {directive.prompt}")
            passed += 1
        else:
            print(f"❌ FAIL - Inner SQL mismatch")
            print(f"   Expected: {expected_stripped}")
            print(f"   Got: {inner_sql_stripped}")
            failed += 1
    else:
        print(f"❌ FAIL - Directive not detected")
        print(f"   Expected: {expected_type}")
        print(f"   Got: {directive.directive_type if directive else 'None'}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)
