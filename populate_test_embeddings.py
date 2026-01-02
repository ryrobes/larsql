#!/usr/bin/env python3
"""
Quick script to populate embeddings for testing VECTOR_SEARCH.

This generates embeddings for all rows in a table and stores them
in rvbbit_embeddings for semantic search.

Usage:
    python populate_test_embeddings.py

This will:
1. Connect to the PostgreSQL server
2. Fetch all products
3. Generate embeddings for each
4. Store in ClickHouse rvbbit_embeddings table
5. VECTOR_SEARCH will then work!
"""

import os
os.environ['RVBBIT_ROOT'] = '/home/ryanr/repos/rvbbit'

import rvbbit
from rvbbit.traits.embedding_storage import agent_embed, clickhouse_store_embedding

print("="*70)
print("Populating Embeddings for VECTOR_SEARCH Testing")
print("="*70)

# Sample data (same as in quickstart.sql)
products = [
    (1, 'Bamboo Toothbrush', 'Eco-friendly bamboo toothbrush made from sustainable materials. Biodegradable and compostable.'),
    (2, 'Organic Cotton T-Shirt', 'Fair trade certified organic cotton t-shirt. Soft, breathable, and ethically made.'),
    (3, 'Stainless Steel Water Bottle', 'Reusable insulated water bottle. Keeps drinks cold for 24 hours. BPA-free.'),
    (4, 'Solar Phone Charger', 'Portable solar-powered charger. Perfect for camping and emergencies.'),
    (5, 'Recycled Notebook', 'Notebook made from 100% recycled paper. Vegan leather cover.'),
]

print(f"\n📦 Processing {len(products)} products...\n")

for product_id, name, description in products:
    print(f"  Processing: {name}...")

    try:
        # Generate embedding
        result = agent_embed(text=description)
        embedding = result['embedding']

        # Store in ClickHouse
        clickhouse_store_embedding(
            source_table='products',
            source_id=str(product_id),
            text=description,
            embedding=embedding,
            model=result['model']
        )

        print(f"    ✅ Stored embedding ({result['dim']} dims)")

    except Exception as e:
        print(f"    ❌ Failed: {e}")

print("\n" + "="*70)
print("✅ Embeddings populated!")
print("="*70)

# Verify in ClickHouse
from rvbbit.db_adapter import get_db_adapter

db = get_db_adapter()
count = db.query("SELECT COUNT(*) as cnt FROM rvbbit_embeddings WHERE source_table = 'products'")[0]['cnt']

print(f"\n📊 Verification:")
print(f"   Embeddings in rvbbit_embeddings: {count}")

if count == len(products):
    print(f"   ✅ All {count} products embedded!")
else:
    print(f"   ⚠️  Expected {len(products)}, got {count}")

print("\n🚀 Now you can use VECTOR_SEARCH:")
print("   SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 5);")
print("\nConnect via:")
print("   psql postgresql://localhost:15432/default")
