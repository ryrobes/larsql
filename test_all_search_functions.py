#!/usr/bin/env python3
"""
Comprehensive test showing all 4 search functions.

Backend routing:
- VECTOR_SEARCH   → ClickHouse (pure semantic, fastest)
- ELASTIC_SEARCH  → Elastic (pure semantic)
- HYBRID_SEARCH   → Elastic (semantic + keyword mix)
- KEYWORD_SEARCH  → Elastic (pure BM25 keyword)
"""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("ALL 4 SEARCH FUNCTIONS - BACKEND ROUTING TEST")
print("=" * 80)

test_cases = [
    ("VECTOR_SEARCH → ClickHouse (pure semantic, fastest)",
     "SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10)",
     "read_json_auto", "vector_search_json_3", "ClickHouse"),

    ("ELASTIC_SEARCH → Elastic (pure semantic)",
     "SELECT * FROM ELASTIC_SEARCH('climate change', articles.content, 10)",
     "vector_search_elastic_7", "1.0, 0.0", "Elastic"),

    ("HYBRID_SEARCH → Elastic (semantic + keyword)",
     "SELECT * FROM HYBRID_SEARCH('climate change', articles.content, 10, 0.5, 0.7, 0.3)",
     "vector_search_elastic_7", "0.7, 0.3", "Elastic"),

    ("KEYWORD_SEARCH → Elastic (pure BM25)",
     "SELECT * FROM KEYWORD_SEARCH('climate change', articles.content, 10)",
     "vector_search_elastic_7", "0.0, 1.0", "Elastic"),
]

print("\n" + "=" * 80)
print("BACKEND ROUTING")
print("=" * 80)

for test_name, sql, expected_func, expected_detail, backend in test_cases:
    print(f"\n{test_name}")
    print(f"SQL: {sql[:70]}...")

    result = rewrite_rvbbit_syntax(sql)

    if expected_func in result and expected_detail in result:
        print(f"✅ Routes to {backend}: {expected_func}(...)")
    else:
        print(f"❌ FAIL")
        print(f"   Expected: {expected_func} with {expected_detail}")
        print(f"   Got: {result[:150]}")

# Show comparison
print("\n" + "=" * 80)
print("COMPARISON: Same Query, Different Backends")
print("=" * 80)

query = "climate change policy"
field = "articles.content"

comparison_queries = [
    ("VECTOR (CH, fastest)", f"SELECT * FROM VECTOR_SEARCH('{query}', {field}, 10)"),
    ("ELASTIC (ES, pure semantic)", f"SELECT * FROM ELASTIC_SEARCH('{query}', {field}, 10)"),
    ("HYBRID (ES, 70/30)", f"SELECT * FROM HYBRID_SEARCH('{query}', {field}, 10, 0.5, 0.7, 0.3)"),
    ("KEYWORD (ES, BM25)", f"SELECT * FROM KEYWORD_SEARCH('{query}', {field}, 10)"),
]

for name, sql in comparison_queries:
    print(f"\n{name}:")
    result = rewrite_rvbbit_syntax(sql)
    # Extract function name
    if "vector_search_json" in result:
        print(f"  → vector_search_json_* (ClickHouse)")
    elif "vector_search_elastic" in result:
        # Extract weights
        import re
        weights_match = re.search(r'(\d+\.\d+),\s*(\d+\.\d+)\)', result)
        if weights_match:
            sem = weights_match.group(1)
            kw = weights_match.group(2)
            print(f"  → vector_search_elastic_* (Elastic: {float(sem)*100:.0f}% semantic, {float(kw)*100:.0f}% keyword)")

print("\n" + "=" * 80)
print("Use Case Guide:")
print("=" * 80)
print("""
VECTOR_SEARCH:   Fast pure semantic (ClickHouse)
                 → "Find conceptually similar content"

ELASTIC_SEARCH:  Elastic pure semantic
                 → "Find similar, but need Elastic features"

HYBRID_SEARCH:   Semantic + keyword balance
                 → "Find similar concepts AND exact term matches"

KEYWORD_SEARCH:  Pure BM25 keyword matching
                 → "Find exact terms (product codes, names, etc.)"
""")

print("=" * 80)
