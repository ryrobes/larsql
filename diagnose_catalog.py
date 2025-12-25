#!/usr/bin/env python3
"""
Diagnostic script to check catalog view creation.
This connects to RVBBIT and checks if pg_catalog views are working.
"""

import psycopg2
import sys

def diagnose():
    print("\n" + "="*70)
    print("RVBBIT SCHEMA INTROSPECTION DIAGNOSTIC")
    print("="*70)

    try:
        print("\n[1] Connecting to RVBBIT...")
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="default",
            user="rvbbit"
        )
        cur = conn.cursor()
        print("✅ Connected successfully!")

        # Test 1: Check what schemas exist
        print("\n[2] Checking available schemas...")
        try:
            cur.execute("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name")
            schemas = cur.fetchall()
            print(f"✅ Found {len(schemas)} schemas:")
            for (schema,) in schemas:
                print(f"   - {schema}")
        except Exception as e:
            print(f"❌ Failed to list schemas: {e}")

        # Test 2: Check if pg_catalog schema exists
        print("\n[3] Checking if pg_catalog schema exists...")
        try:
            cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = 'pg_catalog'")
            count = cur.fetchone()[0]
            if count > 0:
                print(f"✅ pg_catalog schema exists!")
            else:
                print(f"❌ pg_catalog schema NOT found!")
        except Exception as e:
            print(f"❌ Error checking pg_catalog: {e}")

        # Test 3: Check if pg_tables view exists
        print("\n[4] Checking if pg_catalog.pg_tables exists...")
        try:
            cur.execute("SELECT COUNT(*) FROM pg_catalog.pg_tables")
            count = cur.fetchone()[0]
            print(f"✅ pg_catalog.pg_tables exists! ({count} tables)")
        except Exception as e:
            print(f"❌ pg_catalog.pg_tables NOT found: {e}")

        # Test 4: Create a test table
        print("\n[5] Creating test table...")
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS diagnostic_test (
                    id INTEGER,
                    name VARCHAR,
                    value DOUBLE
                )
            """)
            print("✅ Test table created!")
        except Exception as e:
            print(f"❌ Failed to create table: {e}")

        # Test 5: Check if table appears in SHOW TABLES
        print("\n[6] Checking SHOW TABLES...")
        try:
            cur.execute("SHOW TABLES")
            tables = cur.fetchall()
            print(f"✅ SHOW TABLES returned {len(tables)} tables:")
            for row in tables:
                print(f"   - {row}")
        except Exception as e:
            print(f"❌ SHOW TABLES failed: {e}")

        # Test 6: Check if table appears in information_schema.tables
        print("\n[7] Checking information_schema.tables...")
        try:
            cur.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_name
            """)
            tables = cur.fetchall()
            print(f"✅ information_schema.tables returned {len(tables)} tables:")
            for schema, table in tables:
                print(f"   - {schema}.{table}")
        except Exception as e:
            print(f"❌ information_schema.tables failed: {e}")

        # Test 7: Check if table appears in pg_catalog.pg_tables
        print("\n[8] Checking pg_catalog.pg_tables...")
        try:
            cur.execute("""
                SELECT schemaname, tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
                ORDER BY tablename
            """)
            tables = cur.fetchall()
            print(f"✅ pg_catalog.pg_tables returned {len(tables)} tables:")
            for schema, table in tables:
                print(f"   - {schema}.{table}")
        except Exception as e:
            print(f"❌ pg_catalog.pg_tables failed: {e}")
            import traceback
            traceback.print_exc()

        # Test 8: Check columns
        print("\n[9] Checking information_schema.columns...")
        try:
            cur.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'diagnostic_test'
                ORDER BY ordinal_position
            """)
            columns = cur.fetchall()
            print(f"✅ Found {len(columns)} columns in diagnostic_test:")
            for table, col, dtype in columns:
                print(f"   - {col}: {dtype}")
        except Exception as e:
            print(f"❌ Failed to get columns: {e}")

        # Test 9: Check pg_namespace
        print("\n[10] Checking pg_catalog.pg_namespace...")
        try:
            cur.execute("SELECT nspname FROM pg_catalog.pg_namespace ORDER BY nspname")
            namespaces = cur.fetchall()
            print(f"✅ pg_catalog.pg_namespace returned {len(namespaces)} namespaces:")
            for (ns,) in namespaces:
                print(f"   - {ns}")
        except Exception as e:
            print(f"❌ pg_catalog.pg_namespace failed: {e}")

        # Test 10: Check if views are actually created
        print("\n[11] Listing all tables/views in pg_catalog schema...")
        try:
            cur.execute("""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = 'pg_catalog'
                ORDER BY table_name
            """)
            catalog_objects = cur.fetchall()
            print(f"✅ Found {len(catalog_objects)} objects in pg_catalog:")
            for name, otype in catalog_objects:
                print(f"   - {name} ({otype})")
        except Exception as e:
            print(f"❌ Failed to list pg_catalog objects: {e}")

        # Summary
        print("\n" + "="*70)
        print("DIAGNOSTIC COMPLETE")
        print("="*70)
        print("\nIf pg_catalog views exist but DBeaver doesn't show tables:")
        print("1. Try refreshing DBeaver connection (right-click → Refresh)")
        print("2. Check DBeaver's 'Database Navigator' preferences")
        print("3. Try disconnecting and reconnecting")
        print("4. Check DBeaver logs for errors")
        print("\nIf pg_catalog views DON'T exist:")
        print("1. Check RVBBIT server logs for errors during view creation")
        print("2. The _create_pg_catalog_views() method may have failed silently")
        print("="*70)

        conn.close()

    except psycopg2.OperationalError as e:
        print(f"\n❌ Connection failed: {e}")
        print("\n💡 Make sure RVBBIT server is running:")
        print("   rvbbit server --port 5432")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    diagnose()
