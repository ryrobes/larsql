#!/usr/bin/env python3
"""
Diagnose why DBeaver schema browser doesn't show tables.

This simulates DBeaver's metadata queries to find where it's failing.
"""

import psycopg2
import sys

def diagnose():
    print("="*70)
    print("DBEAVER SCHEMA BROWSER DIAGNOSTIC")
    print("="*70)

    try:
        conn = psycopg2.connect(
            host="localhost",
            port=15432,
            database="default",
            user="rvbbit"
        )
        cur = conn.cursor()
        print("✅ Connected to RVBBIT\n")

        # Test 1: Can we list tables via pg_tables?
        print("[1] Testing pg_catalog.pg_tables...")
        try:
            cur.execute("""
                SELECT schemaname, tablename, tableowner
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'main'
                ORDER BY tablename
            """)
            tables = cur.fetchall()
            print(f"    ✅ Found {len(tables)} tables:")
            for schema, table, owner in tables:
                print(f"       - {schema}.{table} (owner: {owner})")
        except Exception as e:
            print(f"    ❌ FAILED: {e}")

        # Test 2: Can we list tables via pg_class?
        print("\n[2] Testing pg_catalog.pg_class...")
        try:
            cur.execute("""
                SELECT relname, relkind, relnamespace
                FROM pg_catalog.pg_class
                WHERE relkind = 'r'
                LIMIT 10
            """)
            classes = cur.fetchall()
            print(f"    ✅ Found {len(classes)} relations:")
            for name, kind, namespace in classes:
                print(f"       - {name} (kind: {kind}, namespace: {namespace})")
        except Exception as e:
            print(f"    ❌ FAILED: {e}")

        # Test 3: Can we JOIN pg_class with pg_namespace?
        print("\n[3] Testing pg_class JOIN pg_namespace...")
        try:
            cur.execute("""
                SELECT
                    c.relname as table_name,
                    n.nspname as schema_name,
                    c.relkind
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'main' AND c.relkind = 'r'
            """)
            joined = cur.fetchall()
            print(f"    ✅ Found {len(joined)} tables after JOIN:")
            for table, schema, kind in joined:
                print(f"       - {schema}.{table} (kind: {kind})")

            if len(joined) == 0:
                print("    ⚠️  WARNING: JOIN returned 0 rows!")
                print("    This means the OID join failed (c.relnamespace != n.oid)")
                print("    This is WHY DBeaver can't see your tables!")

        except Exception as e:
            print(f"    ❌ FAILED: {e}")

        # Test 4: Check OID values
        print("\n[4] Checking OID consistency...")
        try:
            cur.execute("""
                SELECT
                    'pg_class.relnamespace' as source,
                    relnamespace as oid_value
                FROM pg_catalog.pg_class
                WHERE relname = 'test_demo'
            """)
            class_oid = cur.fetchall()

            cur.execute("""
                SELECT
                    'pg_namespace.oid' as source,
                    oid as oid_value
                FROM pg_catalog.pg_namespace
                WHERE nspname = 'main'
            """)
            namespace_oid = cur.fetchall()

            print("    pg_class.relnamespace values:")
            for source, oid in class_oid:
                print(f"       {source} = {oid}")

            print("    pg_namespace.oid values:")
            for source, oid in namespace_oid:
                print(f"       {source} = {oid}")

            if class_oid and namespace_oid:
                if class_oid[0][1] == namespace_oid[0][1]:
                    print("    ✅ OIDs match! JOIN should work!")
                else:
                    print("    ❌ OIDs DON'T match! This is the problem!")
                    print(f"       pg_class.relnamespace = {class_oid[0][1]}")
                    print(f"       pg_namespace.oid = {namespace_oid[0][1]}")
                    print("    DBeaver can't find tables because JOIN fails!")

        except Exception as e:
            print(f"    ❌ FAILED: {e}")

        # Test 5: What does DBeaver's typical query return?
        print("\n[5] Testing DBeaver's typical table list query...")
        try:
            cur.execute("""
                SELECT
                    c.oid as table_oid,
                    c.relname as table_name,
                    n.nspname as schema_name,
                    c.relkind as table_type
                FROM pg_catalog.pg_class c
                LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'v', 'm')
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY n.nspname, c.relname
            """)
            result = cur.fetchall()
            print(f"    ✅ Query returned {len(result)} tables:")
            for oid, name, schema, kind in result:
                print(f"       - {schema}.{name} (oid: {oid}, type: {kind})")

            if len(result) == 0:
                print("    ❌ CRITICAL: This is DBeaver's query and it returned NOTHING!")
                print("    This is WHY the schema browser is empty!")
                print("    The JOIN is failing (n.oid = c.relnamespace doesn't match)")

        except Exception as e:
            print(f"    ❌ FAILED: {e}")

        # Summary
        print("\n" + "="*70)
        print("DIAGNOSIS:")
        print("="*70)
        print("\nMost likely cause:")
        print("- pg_class.relnamespace and pg_namespace.oid don't match")
        print("- DuckDB's built-in catalog uses real OIDs")
        print("- Our manual views used fake OID = 0")
        print("- JOIN fails → no tables in schema browser!")
        print("\nSolution:")
        print("- Let DuckDB's built-in catalog handle everything")
        print("- Don't create custom views at all")
        print("="*70)

        conn.close()

    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    diagnose()
