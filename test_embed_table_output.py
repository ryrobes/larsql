#!/usr/bin/env python3
"""Test that RVBBIT EMBED returns a nice table, not JSON."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("RVBBIT EMBED - TABLE OUTPUT TEST")
print("=" * 80)

test_cases = [
    ("ClickHouse EMBED",
     """
     RVBBIT EMBED bird_line.text
     USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 10)
     """),

    ("Elastic EMBED",
     """
     RVBBIT EMBED products.description
     USING (SELECT id::VARCHAR AS id, description AS text FROM products)
     WITH (backend='elastic', index='products_idx')
     """),
]

for test_name, sql in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql.strip()[:60]}...")

    result = rewrite_rvbbit_syntax(sql)
    print(f"\nRewritten SQL:\n{result}\n")

    # Check for table output wrapper
    checks = [
        ("Wrapped in read_json_auto", "read_json_auto" in result),
        ("Array wrapper", "[" in result and "]" in result),
        ("SELECT * FROM", "SELECT * FROM" in result),
        ("Not just 'AS result'", "AS result" not in result or "FROM" in result),
    ]

    all_good = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"{status} {check_name}")
        if not check_result:
            all_good = False

    if all_good:
        print("\n✅ Will render as table in SQL clients!")
    else:
        print("\n❌ May still render as JSON")

print("\n" + "=" * 80)
print("Example Output in SQL Client:")
print("=" * 80)
print("""
Instead of:
┌─────────────────────────────────────────────┐
│ result                                      │
├─────────────────────────────────────────────┤
│ {"rows_embedded": 10, "batches": 1, ...}   │  ← JSON blob
└─────────────────────────────────────────────┘

You'll see:
┌────────────────┬──────────┬────────────────────┬──────────┐
│ rows_embedded  │ batches  │ duration_seconds   │ backend  │
├────────────────┼──────────┼────────────────────┼──────────┤
│ 10             │ 1        │ 2.3               │ clickhou │  ← Nice table!
└────────────────┴──────────┴────────────────────┴──────────┘
""")
print("=" * 80)
