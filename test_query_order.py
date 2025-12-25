#!/usr/bin/env python3
"""
Test that queries return correct results (not previous query's results).
"""

import psycopg2

conn = psycopg2.connect("postgresql://localhost:15432/default")
cur = conn.cursor()

print("Testing query result order...\n")

# Query 1
print("Query 1: SELECT 111 as value")
cur.execute("SELECT 111 as value")
result = cur.fetchone()
print(f"Result: {result}")
assert result[0] == 111, f"Expected 111, got {result[0]}"
print("✅ Correct!\n")

# Query 2
print("Query 2: SELECT 222 as value")
cur.execute("SELECT 222 as value")
result = cur.fetchone()
print(f"Result: {result}")
assert result[0] == 222, f"Expected 222, got {result[0]}"
print("✅ Correct!\n")

# Query 3
print("Query 3: SELECT 333 as value")
cur.execute("SELECT 333 as value")
result = cur.fetchone()
print(f"Result: {result}")
assert result[0] == 333, f"Expected 333, got {result[0]}"
print("✅ Correct!\n")

print("🎉 All queries returned correct results!")
conn.close()
