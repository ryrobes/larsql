#!/usr/bin/env python3
"""
Inspect a cascade session database to see what tables it contains.

Usage:
    python3 inspect_session_db.py cascade_test
"""

import sys
import duckdb
from pathlib import Path

def inspect_session_db(session_id):
    """Inspect a session database file."""

    db_path = Path('session_dbs') / f'{session_id}.duckdb'

    if not db_path.exists():
        print(f"❌ ERROR: {db_path} does not exist!")
        print(f"\nAvailable session DBs:")
        for f in Path('session_dbs').glob('*.duckdb'):
            print(f"  - {f.stem}")
        return

    print("="*70)
    print(f"INSPECTING SESSION DATABASE: {session_id}")
    print("="*70)
    print(f"File: {db_path}")
    print(f"Size: {db_path.stat().st_size / 1024:.1f} KB")
    print()

    # Connect directly to the file
    conn = duckdb.connect(str(db_path), read_only=True)

    # Check what databases are attached
    print("[1] Attached databases:")
    result = conn.execute("SELECT database_name, path FROM duckdb_databases()").fetchall()
    for db, path in result:
        print(f"  - {db}: {path or '(in-memory)'}")

    # Check what tables exist
    print("\n[2] Tables in this database:")
    result = conn.execute("""
        SELECT database_name, schema_name, table_name, estimated_size
        FROM duckdb_tables()
        ORDER BY database_name, schema_name, table_name
    """).fetchall()

    if len(result) == 0:
        print("  ❌ NO TABLES FOUND!")
        print("  This database file is empty or has no user tables.")
    else:
        for db, schema, table, size in result:
            print(f"  - {db}.{schema}.{table} ({size} rows)")

    # Check via information_schema too
    print("\n[3] Via information_schema.tables:")
    result = conn.execute("""
        SELECT table_catalog, table_schema, table_name
        FROM information_schema.tables
        ORDER BY table_catalog, table_schema, table_name
    """).fetchall()

    if len(result) == 0:
        print("  ❌ NO TABLES in information_schema!")
    else:
        for catalog, schema, table in result:
            print(f"  - {catalog}.{schema}.{table}")

    # Sample first table if any exist
    print("\n[4] Sample data from first table:")
    tables = conn.execute("SELECT database_name, schema_name, table_name FROM duckdb_tables() LIMIT 1").fetchall()
    if tables:
        db, schema, table = tables[0]
        full_name = f'"{db}"."{schema}"."{table}"'
        try:
            result = conn.execute(f"SELECT * FROM {full_name} LIMIT 3").fetchdf()
            print(f"  Table: {full_name}")
            print(result.to_string(index=False))
        except Exception as e:
            print(f"  ❌ Could not query: {e}")
    else:
        print("  No tables to sample!")

    conn.close()

    print("\n" + "="*70)
    print("SUMMARY:")
    print("="*70)
    if len(result) > 0:
        print("✅ This database has tables and should be queryable when ATTACH'd")
    else:
        print("❌ This database is EMPTY - no tables to discover!")
        print("   It might have been created but never used by a cascade.")
    print("="*70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_session_db.py <session_id>")
        print("\nExample:")
        print("  python3 inspect_session_db.py cascade_test")
        print("  python3 inspect_session_db.py agile-cardinal-490cb1")
        sys.exit(1)

    inspect_session_db(sys.argv[1])
