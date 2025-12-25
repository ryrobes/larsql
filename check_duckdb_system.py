#!/usr/bin/env python3
"""
Check what DuckDB system tables are available.
This helps diagnose why information_schema.tables might be broken.
"""

import duckdb
import sys

def check_duckdb():
    print("="*70)
    print("DUCKDB SYSTEM TABLE DIAGNOSTIC")
    print("="*70)

    conn = duckdb.connect(':memory:')

    # Check DuckDB version
    print("\n[1] DuckDB Version:")
    version = conn.execute("SELECT version()").fetchone()[0]
    print(f"    {version}")

    # Create a test table
    print("\n[2] Creating test table...")
    conn.execute("CREATE TABLE test_table (id INTEGER, name VARCHAR)")
    conn.execute("INSERT INTO test_table VALUES (1, 'Alice'), (2, 'Bob')")
    print("    ✓ Test table created with 2 rows")

    # Check duckdb_tables()
    print("\n[3] Testing duckdb_tables():")
    try:
        result = conn.execute("SELECT * FROM duckdb_tables()").fetchdf()
        print(f"    ✓ duckdb_tables() works! Found {len(result)} tables")
        print(f"    Columns: {list(result.columns)}")
        print(f"\n    Data:")
        for idx, row in result.iterrows():
            print(f"      - {row['schema_name']}.{row['table_name']} ({row.get('table_type', 'N/A')})")
    except Exception as e:
        print(f"    ✗ duckdb_tables() failed: {e}")

    # Check information_schema.tables
    print("\n[4] Testing information_schema.tables:")
    try:
        result = conn.execute("SELECT * FROM information_schema.tables").fetchdf()
        print(f"    ✓ information_schema.tables works! Found {len(result)} tables")
        print(f"    Columns: {list(result.columns)}")

        if len(result) > 0:
            print(f"\n    Data:")
            for idx, row in result.iterrows():
                schema = row.get('table_schema', row.get('schema_name', '?'))
                name = row.get('table_name', '?')
                ttype = row.get('table_type', '?')
                print(f"      - {schema}.{name} ({ttype})")
        else:
            print("    ⚠️  WARNING: information_schema.tables returned 0 rows!")
            print("    This means information_schema is not working correctly!")
    except Exception as e:
        print(f"    ✗ information_schema.tables failed: {e}")

    # Check information_schema.columns
    print("\n[5] Testing information_schema.columns:")
    try:
        result = conn.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'test_table'
            ORDER BY ordinal_position
        """).fetchdf()
        print(f"    ✓ information_schema.columns works! Found {len(result)} columns")
        for idx, row in result.iterrows():
            print(f"      - {row['column_name']}: {row['data_type']}")
    except Exception as e:
        print(f"    ✗ information_schema.columns failed: {e}")

    # Check what columns information_schema.tables has
    print("\n[6] Checking information_schema.tables structure:")
    try:
        result = conn.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'information_schema' AND table_name = 'tables'
            ORDER BY ordinal_position
        """).fetchdf()
        print(f"    ✓ Found {len(result)} columns in information_schema.tables:")
        for idx, row in result.iterrows():
            print(f"      - {row['column_name']}: {row['data_type']}")
    except Exception as e:
        print(f"    ✗ Failed to get structure: {e}")

    # Summary
    print("\n" + "="*70)
    print("RECOMMENDATION:")
    print("="*70)

    try:
        duckdb_works = len(conn.execute("SELECT * FROM duckdb_tables()").fetchdf()) > 0
        info_schema_works = len(conn.execute("SELECT * FROM information_schema.tables").fetchdf()) > 0

        if info_schema_works:
            print("✅ Use information_schema.tables (standard SQL)")
        elif duckdb_works:
            print("⚠️  Use duckdb_tables() instead (information_schema is broken)")
            print("    We need to rewrite pg_catalog views to use duckdb_tables()")
        else:
            print("❌ Both information_schema AND duckdb_tables() are broken!")
            print("    This DuckDB version might be too old")
    except:
        print("❌ Unable to determine - check errors above")

    print("="*70)

    conn.close()

if __name__ == "__main__":
    check_duckdb()
