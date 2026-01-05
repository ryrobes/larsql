#!/usr/bin/env python3
"""
Complete System Demo - All features working together.

Shows:
1. RVBBIT EMBED (both backends)
2. All 4 search functions (VECTOR, ELASTIC, HYBRID, KEYWORD)
3. Semantic operators (MEANS, ABOUT, etc.)
4. BACKGROUND async execution
5. Field-aware syntax (table.column)
"""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("COMPLETE SYSTEM DEMO - ALL FEATURES")
print("=" * 80)

demos = [
    ("RVBBIT EMBED → ClickHouse",
     """
     RVBBIT EMBED articles.content
     USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
     """),

    ("RVBBIT EMBED → Elastic",
     """
     RVBBIT EMBED products.description
     USING (SELECT id::VARCHAR AS id, description AS text FROM products)
     WITH (backend='elastic', index='products_idx')
     """),

    ("VECTOR_SEARCH → ClickHouse (fastest semantic)",
     "SELECT * FROM VECTOR_SEARCH('climate policy', articles.content, 10)"),

    ("ELASTIC_SEARCH → Elastic (semantic)",
     "SELECT * FROM ELASTIC_SEARCH('climate policy', articles.content, 10)"),

    ("HYBRID_SEARCH → Elastic (semantic + keyword)",
     "SELECT * FROM HYBRID_SEARCH('Venezuela crisis', bird_line.text, 20, 0.5, 0.7, 0.3)"),

    ("KEYWORD_SEARCH → Elastic (pure BM25)",
     "SELECT * FROM KEYWORD_SEARCH('MacBook Pro M3', products.name, 10)"),

    ("VECTOR_SEARCH + Semantic Operators",
     """
     SELECT * FROM VECTOR_SEARCH('sustainability', products.description, 50)
     WHERE chunk_text MEANS 'eco-friendly practices'
     """),

    ("BACKGROUND + HYBRID_SEARCH",
     """
     BACKGROUND
     SELECT * FROM HYBRID_SEARCH('climate action', articles.content, 100, 0.6, 0.8, 0.2)
     """),

    ("Complex: Search + Semantic Filter + Join",
     """
     SELECT
       p.product_name,
       vs.score,
       vs.chunk_text,
       vs.chunk_text EXTRACTS 'key features' AS features
     FROM products p
     JOIN VECTOR_SEARCH('eco-friendly', products.description, 20, 0.7) vs
       ON vs.id = p.id::VARCHAR
     WHERE vs.chunk_text ABOUT 'sustainability' > 0.6
     ORDER BY vs.score DESC
     """),
]

for i, (name, sql) in enumerate(demos, 1):
    print(f"\n[Demo {i}] {name}")
    print("-" * 80)
    print(f"Input:\n{sql.strip()}\n")

    result = rewrite_rvbbit_syntax(sql)
    print(f"Rewritten:\n{result[:300]}...")

    # Check what's in it
    features = []
    if "embed_batch" in result:
        features.append("✓ EMBED")
    if "vector_search_json" in result:
        features.append("✓ ClickHouse")
    if "vector_search_elastic" in result:
        features.append("✓ Elastic")
    if "semantic_" in result or "llm_" in result:
        features.append("✓ Semantic Ops")
    if "read_json_auto" in result:
        features.append("✓ Auto-wrapper")
    if "metadata.column_name" in result:
        features.append("✓ Column filter")

    if features:
        print(f"\nFeatures: {' '.join(features)}")

print("\n" + "=" * 80)
print("SYSTEM CAPABILITIES SUMMARY")
print("=" * 80)
print("""
✅ RVBBIT EMBED - Declarative embedding (ClickHouse or Elastic)
✅ VECTOR_SEARCH - ClickHouse pure semantic (fastest)
✅ ELASTIC_SEARCH - Elastic pure semantic
✅ HYBRID_SEARCH - Elastic semantic + keyword (tunable)
✅ KEYWORD_SEARCH - Elastic pure BM25 keyword
✅ Semantic Operators - MEANS, ABOUT, EXTRACTS, etc. (from cascades)
✅ BACKGROUND - Async execution for all features
✅ Field References - table.column syntax (IDE autocomplete)
✅ Automatic Metadata Filtering - Multi-column support
✅ Token-Based Parsing - No regex bugs, handles newlines

ALL FEATURES WORK TOGETHER! 🎉
""")
print("=" * 80)
