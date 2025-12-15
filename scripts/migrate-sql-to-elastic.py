#!/usr/bin/env python
"""
Migrate existing SQL schema data from ClickHouse to Elasticsearch.

This reads:
- JSON files from sql_connections/samples/
- Embeddings from ClickHouse rag_chunks table
- Combines them into Elasticsearch documents
"""
import json
import sys
import os
import glob
import math
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from windlass.config import get_config
from windlass.db_adapter import get_db
from windlass.sql_tools.config import load_discovery_metadata
from windlass.elastic import get_elastic_client, create_sql_schema_index, bulk_index_sql_schemas


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


def main():
    print("=" * 70)
    print("Migrating SQL Schemas: ClickHouse → Elasticsearch")
    print("=" * 70)
    print()

    # Get SQL discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        print("✗ No SQL discovery metadata found")
        print("  Run: windlass sql chart")
        return 1

    print(f"✓ Found SQL discovery metadata")
    print(f"  RAG ID: {meta.rag_id}")
    print(f"  Databases: {', '.join(meta.databases_indexed)}")
    print()

    # Load embeddings from ClickHouse
    print("Loading embeddings from ClickHouse...")
    db = get_db()
    embeddings_query = f"""
        SELECT
            rel_path,
            argMax(embedding, chunk_index) as embedding,
            argMax(embedding_model, chunk_index) as embedding_model
        FROM rag_chunks
        WHERE rag_id = '{meta.rag_id}'
        GROUP BY rel_path
    """
    embeddings_data = db.query(embeddings_query)
    print(f"✓ Loaded {len(embeddings_data)} embeddings")
    print()

    # Create embedding lookup by file path
    # rel_path looks like: "local_postgres/acc/academic_applications.json"
    embedding_map = {row['rel_path']: row for row in embeddings_data}

    # Load JSON files
    cfg = get_config()
    samples_dir = os.path.join(cfg.root_dir, 'sql_connections', 'samples')
    json_pattern = os.path.join(samples_dir, '**/*.json')
    json_files = glob.glob(json_pattern, recursive=True)

    print(f"Loading {len(json_files)} JSON schema files...")

    documents = []
    matched = 0
    unmatched = 0

    for json_path in json_files:
        try:
            # Get relative path from samples_dir
            rel_path = os.path.relpath(json_path, samples_dir)

            # Load table metadata
            with open(json_path, 'r') as f:
                table_meta = json.load(f)

            # Sanitize NaN values that Elasticsearch doesn't accept
            table_meta = sanitize_for_json(table_meta)

            # Build qualified name
            if table_meta.get('schema') and table_meta['schema'] != table_meta['database']:
                qualified_name = f"{table_meta['database']}.{table_meta['schema']}.{table_meta['table_name']}"
            else:
                qualified_name = f"{table_meta['database']}.{table_meta['table_name']}"

            # Find matching embedding
            embedding = None
            embedding_model = None

            if rel_path in embedding_map:
                emb_data = embedding_map[rel_path]
                embedding = emb_data['embedding']
                embedding_model = emb_data['embedding_model']
                matched += 1
            else:
                # Try alternative path formats
                for emb_path in embedding_map.keys():
                    if table_meta['table_name'] in emb_path:
                        emb_data = embedding_map[emb_path]
                        embedding = emb_data['embedding']
                        embedding_model = emb_data['embedding_model']
                        matched += 1
                        break

            if embedding is None:
                unmatched += 1
                print(f"  ⚠ No embedding for {rel_path}")

            # Prepare document
            doc = {
                'qualified_name': qualified_name,
                'database': table_meta['database'],
                'schema': table_meta.get('schema', ''),
                'table_name': table_meta['table_name'],
                'description': table_meta.get('description', ''),
                'row_count': table_meta.get('row_count', 0),
                'table_type': table_meta.get('table_type', 'TABLE'),
                'columns': table_meta.get('columns', []),
                'sample_rows': table_meta.get('sample_rows', []),
                'indexed_at': datetime.now().isoformat()
            }

            # Only add embedding if it exists (Elasticsearch will use text-only search)
            if embedding is not None:
                doc['embedding'] = embedding
                doc['embedding_model'] = embedding_model

            documents.append(doc)

        except Exception as e:
            print(f"  ✗ Failed to load {json_path}: {e}")

    print()
    print(f"✓ Prepared {len(documents)} documents")
    print(f"  Matched embeddings: {matched}")
    print(f"  Missing embeddings: {unmatched}")
    print()

    # Connect to Elasticsearch
    try:
        es = get_elastic_client()
        if not es.ping():
            print("✗ Cannot connect to Elasticsearch")
            print("  Start with: ./scripts/start-elasticsearch.sh")
            return 1
        print("✓ Connected to Elasticsearch")
    except Exception as e:
        print(f"✗ Elasticsearch error: {e}")
        return 1

    # Ensure index exists
    if not es.indices.exists(index='windlass_sql_schemas'):
        print("Creating index...")
        create_sql_schema_index()

    # Bulk index
    print(f"Bulk indexing {len(documents)} documents...")
    try:
        indexed_count = bulk_index_sql_schemas(documents)
        print(f"✓ Indexed {indexed_count} documents")

        if indexed_count < len(documents):
            failed_count = len(documents) - indexed_count
            print(f"⚠ {failed_count} documents failed to index")

            # Try to find which ones failed by checking what's in the index
            from elasticsearch import Elasticsearch
            es = Elasticsearch(['http://localhost:9200'])
            indexed_ids = set()

            # Get all IDs in index
            all_docs = es.search(index='windlass_sql_schemas', body={'size': 200, '_source': False})
            for hit in all_docs['hits']['hits']:
                indexed_ids.add(hit['_id'])

            # Find missing
            expected_ids = {doc['qualified_name'] for doc in documents}
            missing = expected_ids - indexed_ids

            if missing:
                print(f"\\nMissing documents:")
                for doc_id in list(missing)[:10]:
                    print(f"  - {doc_id}")

    except Exception as e:
        print(f"✗ Bulk indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Refresh and verify
    es.indices.refresh(index='windlass_sql_schemas')
    count = es.count(index='windlass_sql_schemas')
    print()
    print(f"✓ Verification: {count['count']} documents in Elasticsearch")
    print()
    print("=" * 70)
    print("✓ Migration complete!")
    print()
    print("Test in UI: http://localhost:5550/#/search/ragtest")
    print("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
