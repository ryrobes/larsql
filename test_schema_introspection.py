#!/usr/bin/env python3
"""
Test script for PostgreSQL schema introspection.

This tests that DBeaver/DataGrip can discover tables, columns, and schemas
through pg_catalog queries.

Usage:
    1. Start RVBBIT server: rvbbit server --port 5432
    2. Run this script: python test_schema_introspection.py
"""

import psycopg2
import sys

def test_catalog_queries(conn):
    """Test various catalog queries that SQL editors use."""

    cur = conn.cursor()
    tests_passed = 0
    tests_failed = 0

    print("\n" + "="*70)
    print("TESTING SCHEMA INTROSPECTION")
    print("="*70)

    # Test 1: List tables via pg_tables
    print("\n[TEST 1] List tables via pg_catalog.pg_tables")
    try:
        cur.execute("""
            SELECT schemaname, tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY tablename
        """)
        tables = cur.fetchall()
        print(f"✅ Found {len(tables)} user tables:")
        for schema, table in tables[:5]:  # Show first 5
            print(f"   - {schema}.{table}")
        if len(tables) > 5:
            print(f"   ... and {len(tables) - 5} more")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 2: List tables via information_schema
    print("\n[TEST 2] List tables via information_schema.tables")
    try:
        cur.execute("""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        print(f"✅ Found {len(tables)} tables:")
        for schema, table, ttype in tables[:5]:
            print(f"   - {schema}.{table} ({ttype})")
        if len(tables) > 5:
            print(f"   ... and {len(tables) - 5} more")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 3: List columns via pg_attribute
    print("\n[TEST 3] List columns via pg_catalog.pg_attribute")
    try:
        cur.execute("""
            SELECT attname, data_type, attnotnull
            FROM pg_catalog.pg_attribute
            WHERE table_schema = 'main'
            ORDER BY table_name, attnum
            LIMIT 10
        """)
        columns = cur.fetchall()
        print(f"✅ Found {len(columns)} columns (showing first 10):")
        for col, dtype, notnull in columns:
            nullable = "NOT NULL" if notnull else "NULLABLE"
            print(f"   - {col}: {dtype} ({nullable})")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 4: List columns via information_schema
    print("\n[TEST 4] List columns via information_schema.columns")
    try:
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'main'
            ORDER BY table_name, ordinal_position
            LIMIT 10
        """)
        columns = cur.fetchall()
        print(f"✅ Found {len(columns)} columns (showing first 10):")
        for table, col, dtype, nullable in columns:
            print(f"   - {table}.{col}: {dtype} (nullable={nullable})")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 5: List schemas via pg_namespace
    print("\n[TEST 5] List schemas via pg_catalog.pg_namespace")
    try:
        cur.execute("""
            SELECT nspname
            FROM pg_catalog.pg_namespace
            ORDER BY nspname
        """)
        schemas = cur.fetchall()
        print(f"✅ Found {len(schemas)} schemas:")
        for (schema,) in schemas:
            print(f"   - {schema}")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 6: CURRENT_DATABASE() function
    print("\n[TEST 6] CURRENT_DATABASE() function")
    try:
        cur.execute("SELECT CURRENT_DATABASE()")
        db = cur.fetchone()[0]
        print(f"✅ Current database: {db}")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 7: CURRENT_SCHEMA() function
    print("\n[TEST 7] CURRENT_SCHEMA() function")
    try:
        cur.execute("SELECT CURRENT_SCHEMA()")
        schema = cur.fetchone()[0]
        print(f"✅ Current schema: {schema}")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 8: VERSION() function
    print("\n[TEST 8] VERSION() function")
    try:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        print(f"✅ Server version: {version}")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 9: Data types via pg_type
    print("\n[TEST 9] List data types via pg_catalog.pg_type")
    try:
        cur.execute("""
            SELECT typname
            FROM pg_catalog.pg_type
            ORDER BY typname
        """)
        types = cur.fetchall()
        print(f"✅ Found {len(types)} data types:")
        for (typename,) in types[:10]:
            print(f"   - {typename}")
        if len(types) > 10:
            print(f"   ... and {len(types) - 10} more")
        tests_passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Test 10: Create a test table and verify it appears
    print("\n[TEST 10] Create table and verify it appears in catalogs")
    try:
        # Create test table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS test_introspection (
                id INTEGER,
                name VARCHAR,
                created_at TIMESTAMP
            )
        """)

        # Check it appears in pg_tables
        cur.execute("""
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE tablename = 'test_introspection'
        """)
        result = cur.fetchone()

        if result:
            print(f"✅ Table 'test_introspection' found in pg_catalog.pg_tables")

            # Check columns appear
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'test_introspection'
                ORDER BY ordinal_position
            """)
            columns = cur.fetchall()
            print(f"✅ Columns discovered:")
            for col, dtype in columns:
                print(f"   - {col}: {dtype}")

            tests_passed += 1
        else:
            print("❌ FAILED: Table not found in catalog")
            tests_failed += 1

    except Exception as e:
        print(f"❌ FAILED: {e}")
        tests_failed += 1

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"✅ Passed: {tests_passed}")
    print(f"❌ Failed: {tests_failed}")
    print(f"📊 Total:  {tests_passed + tests_failed}")
    print("="*70)

    return tests_passed, tests_failed


def main():
    """Main test function."""

    print("\n🔌 Connecting to RVBBIT PostgreSQL server...")
    print("   (Make sure 'rvbbit server' is running on port 5432)")

    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="default",
            user="rvbbit"
        )
        print("✅ Connected successfully!\n")

        # Run tests
        passed, failed = test_catalog_queries(conn)

        # Close connection
        conn.close()

        # Exit with error code if any tests failed
        if failed > 0:
            print(f"\n⚠️  {failed} test(s) failed!")
            sys.exit(1)
        else:
            print("\n🎉 All tests passed! Schema introspection is working!")
            sys.exit(0)

    except psycopg2.OperationalError as e:
        print(f"\n❌ Connection failed: {e}")
        print("\n💡 Make sure the RVBBIT server is running:")
        print("   rvbbit server --port 5432")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
