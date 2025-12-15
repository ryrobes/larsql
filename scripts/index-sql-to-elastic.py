#!/usr/bin/env python
"""
Index SQL schemas from ClickHouse RAG into Elasticsearch for hybrid search.

This migrates SQL schema metadata to Elasticsearch where:
- Structured documents (not chunked text)
- Hybrid search (BM25 keyword + vector similarity)
- Controlled field selection (exclude huge sample_rows from results)
"""
import json
import sys
import os
from datetime import datetime

# Add windlass to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from windlass.db_adapter import get_db
from windlass.elastic import get_elastic_client, create_sql_schema_index, bulk_index_sql_schemas
from windlass.sql_tools.config import load_discovery_metadata
from windlass.config import get_config


def load_sql_schemas_from_clickhouse():
    """Load SQL schema metadata from ClickHouse RAG index."""
    print("Loading SQL schemas from ClickHouse...")

    # Get SQL discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        print("No SQL discovery metadata found. Run: windlass sql chart")
        return []

    print(f"  RAG ID: {meta.rag_id}")
    print(f"  Embed model: {meta.embed_model}")
    print(f"  Databases: {meta.databases_indexed}")

    # Get all chunks from the SQL RAG index
    db = get_db()
    chunks_query = f"""
        SELECT
            doc_id,
            rel_path,
            text,
            embedding,
            embedding_model
        FROM rag_chunks
        WHERE rag_id = '{meta.rag_id}'
        ORDER BY doc_id
    """

    chunks = db.query(chunks_query)
    print(f"  Found {len(chunks)} chunks\n")

    # Load the actual SQL metadata JSON files
    cfg = get_config()
    samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    schemas = []
    for chunk in chunks:
        # The doc_id is the JSON filename stem
        json_path = os.path.join(samples_dir, f"{chunk['doc_id']}.json")

        if not os.path.exists(json_path):
            print(f"  ⚠ Skipping {chunk['doc_id']} - JSON file not found")
            continue

        try:
            with open(json_path, 'r') as f:
                table_data = json.load(f)

            # Prepare Elasticsearch document
            doc = {
                "qualified_name": table_data.get('qualified_name', chunk['doc_id']),
                "database": table_data.get('database', ''),
                "schema": table_data.get('schema', ''),
                "table_name": table_data.get('table_name', ''),
                "description": table_data.get('description', ''),
                "row_count": table_data.get('row_count', 0),
                "table_type": table_data.get('table_type', 'TABLE'),
                "columns": table_data.get('columns', []),
                "sample_rows": table_data.get('sample_rows', []),  # Included but will be excluded from search results
                "embedding": chunk['embedding'],  # Vector from ClickHouse
                "embedding_model": chunk['embedding_model'],
                "indexed_at": datetime.now().isoformat()
            }

            schemas.append(doc)

        except Exception as e:
            print(f"  ⚠ Failed to load {chunk['doc_id']}: {e}")
            continue

    return schemas


def main():
    print("=" * 60)
    print("Indexing SQL Schemas into Elasticsearch")
    print("=" * 60)
    print()

    # Test Elasticsearch connection
    try:
        es = get_elastic_client()
        health = es.cluster.health()
        print(f"✓ Connected to Elasticsearch")
        print(f"  Status: {health['status']}")
        print()
    except Exception as e:
        print(f"✗ Cannot connect to Elasticsearch: {e}")
        print()
        print("Start Elasticsearch with: ./scripts/start-elasticsearch.sh")
        return 1

    # Create index
    print("Creating index with mapping...")
    try:
        index_name = create_sql_schema_index()
        print(f"✓ Created index: {index_name}")
        print()
    except Exception as e:
        print(f"✗ Failed to create index: {e}")
        return 1

    # Load schemas from ClickHouse
    schemas = load_sql_schemas_from_clickhouse()
    if not schemas:
        print("No schemas to index")
        return 1

    print(f"Indexing {len(schemas)} SQL schemas...")
    try:
        count = bulk_index_sql_schemas(schemas)
        print(f"✓ Indexed {count} schemas")
        print()
    except Exception as e:
        print(f"✗ Bulk indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Verify
    from windlass.elastic import get_index_stats
    stats = get_index_stats()
    print("Index Statistics:")
    print(f"  Documents: {stats.get('doc_count', 0)}")
    print(f"  Size: {stats.get('size_bytes', 0) / 1024 / 1024:.2f} MB")
    print()

    print("=" * 60)
    print("✓ Indexing complete!")
    print()
    print("Test search:")
    print("  curl http://localhost:9200/windlass_sql_schemas/_search?pretty")
    print()
    print("Next: Try SQL search in dashboard UI")
    print("  http://localhost:5550/#/search/sql")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
