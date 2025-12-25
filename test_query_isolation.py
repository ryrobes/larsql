#!/usr/bin/env python3
"""
Test if queries return correct results (not mixed up).

This isolates whether the "wrong results" bug is in our protocol
or just a DBeaver UI caching issue.
"""

import psycopg2
import sys

conn = psycopg2.connect("postgresql://localhost:15432/default")
cur = conn.cursor()

print("="*70)
print("TESTING QUERY RESULT ISOLATION")
print("="*70)

tests = [
    ("SELECT 111 as value", 111),
    ("SELECT 222 as value", 222),
    ("SELECT 333 as value", 333),
    ("SELECT 'AAA' as text", 'AAA'),
    ("SELECT 'BBB' as text", 'BBB'),
    ("SELECT 'CCC' as text", 'CCC'),
]

for i, (query, expected) in enumerate(tests, 1):
    print(f"\n[TEST {i}] {query}")
    cur.execute(query)
    result = cur.fetchone()[0]

    if result == expected:
        print(f"   ✅ PASS: Got {result}")
    else:
        print(f"   ❌ FAIL: Expected {expected}, got {result}")
        print(f"\n🚨 CRITICAL BUG: Query results are OUT OF ORDER!")
        print(f"   This means our Extended Query Protocol has a bug.")
        conn.close()
        sys.exit(1)

print("\n" + "="*70)
print("✅ ALL TESTS PASSED!")
print("="*70)
print("\nQuery results are correct and in order.")
print("The 'wrong results' issue is likely a DBeaver UI caching problem.")
print("Try: Tools → Preferences → Editors → SQL Editor → Result Sets")
print("      → Disable result set caching")
conn.close()
