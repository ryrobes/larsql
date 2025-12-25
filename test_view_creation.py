#!/usr/bin/env python3
"""
Test if view creation works in a fresh DuckDB session.
This simulates what happens when RVBBIT creates catalog views.
"""

import duckdb
import sys

def test_view_creation():
    print("="*70)
    print("TESTING VIEW CREATION IN DUCKDB")
    print("="*70)

    # Create in-memory DuckDB (same as session_db does)
    conn = duckdb.connect(':memory:')

    try:
        # Step 1: Create pg_catalog schema
        print("\n[1] Creating pg_catalog schema...")
        conn.execute("CREATE SCHEMA IF NOT EXISTS pg_catalog")
        print("✅ pg_catalog schema created")

        # Step 2: Verify schema exists
        print("\n[2] Verifying pg_catalog schema exists...")
        result = conn.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'pg_catalog'").fetchall()
        if result:
            print(f"✅ pg_catalog schema found: {result}")
        else:
            print("❌ pg_catalog schema NOT found!")
            return False

        # Step 3: Create simple test view
        print("\n[3] Creating simple test view in pg_catalog...")
        conn.execute("""
            CREATE OR REPLACE VIEW pg_catalog.test_simple AS
            SELECT 'hello' as message, 123 as number
        """)
        print("✅ Test view created")

        # Step 4: Query the test view
        print("\n[4] Querying test view...")
        result = conn.execute("SELECT * FROM pg_catalog.test_simple").fetchall()
        print(f"✅ Test view result: {result}")

        # Step 5: Create pg_namespace view (the real one)
        print("\n[5] Creating pg_namespace view...")
        conn.execute("""
            CREATE OR REPLACE VIEW pg_catalog.pg_namespace AS
            SELECT 'main' as nspname, 0 as oid
            UNION ALL
            SELECT 'pg_catalog' as nspname, 0 as oid
            UNION ALL
            SELECT 'information_schema' as nspname, 0 as oid
            UNION ALL
            SELECT 'public' as nspname, 0 as oid
        """)
        print("✅ pg_namespace view created")

        # Step 6: Query pg_namespace
        print("\n[6] Querying pg_namespace...")
        result = conn.execute("SELECT * FROM pg_catalog.pg_namespace ORDER BY nspname").fetchall()
        print(f"✅ pg_namespace result ({len(result)} rows):")
        for row in result:
            print(f"   - {row}")

        if len(result) == 0:
            print("❌ ERROR: pg_namespace returned 0 rows!")
            print("This should NEVER happen - the query has hardcoded values!")
            return False

        # Step 7: Test with information_schema.tables
        print("\n[7] Creating test table...")
        conn.execute("CREATE TABLE test_users (id INTEGER, name VARCHAR)")
        print("✅ Test table created")

        print("\n[8] Checking information_schema.tables...")
        result = conn.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name = 'test_users'
        """).fetchall()
        print(f"✅ Found test table: {result}")

        # Step 9: Create pg_namespace with information_schema query
        print("\n[9] Creating full pg_namespace view...")
        conn.execute("""
            CREATE OR REPLACE VIEW pg_catalog.pg_namespace AS
            SELECT 'main' as nspname, 0 as oid
            UNION ALL
            SELECT 'pg_catalog' as nspname, 0 as oid
            UNION ALL
            SELECT 'information_schema' as nspname, 0 as oid
            UNION ALL
            SELECT 'public' as nspname, 0 as oid
            UNION ALL
            SELECT DISTINCT
                table_schema as nspname,
                0 as oid
            FROM information_schema.tables
            WHERE table_schema NOT IN ('main', 'pg_catalog', 'information_schema', 'public')
        """)
        print("✅ Full pg_namespace view created")

        print("\n[10] Querying full pg_namespace...")
        result = conn.execute("SELECT * FROM pg_catalog.pg_namespace ORDER BY nspname").fetchall()
        print(f"✅ Full pg_namespace result ({len(result)} rows):")
        for row in result:
            print(f"   - {row}")

        # Success!
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\nConclusion: View creation works fine in DuckDB.")
        print("The issue must be:")
        print("1. Views are being created but you're querying wrong schema")
        print("2. Server logs show view creation failed")
        print("3. DBeaver is caching old schema metadata")
        print("="*70)

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = test_view_creation()
    sys.exit(0 if success else 1)
