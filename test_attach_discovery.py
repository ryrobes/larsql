#!/usr/bin/env python3
"""
Test DuckDB's ATTACH system and how to enumerate attached databases.

This explores how we can expose ATTACH'd databases as PostgreSQL schemas.
"""

import duckdb

conn = duckdb.connect(':memory:')

print("="*70)
print("TESTING DUCKDB ATTACH DISCOVERY")
print("="*70)

# Create some test tables in main database
print("\n[1] Creating test tables in main database...")
conn.execute("CREATE TABLE main_table1 (id INTEGER, name VARCHAR)")
conn.execute("CREATE TABLE main_table2 (id INTEGER, value DOUBLE)")
print("✅ Created 2 tables in main database")

# ATTACH an in-memory SQLite-style database
print("\n[2] ATTACH'ing additional database...")
conn.execute("ATTACH ':memory:' AS attached_db")
conn.execute("CREATE TABLE attached_db.attached_table (id INTEGER, data VARCHAR)")
print("✅ Attached database 'attached_db' with 1 table")

# List all databases
print("\n[3] Listing all databases with duckdb_databases()...")
result = conn.execute("SELECT * FROM duckdb_databases()").fetchdf()
print(f"✅ Found {len(result)} databases:")
print(result.to_string(index=False))

# List all schemas
print("\n[4] Listing all schemas from information_schema...")
result = conn.execute("""
    SELECT DISTINCT table_catalog, table_schema
    FROM information_schema.tables
    ORDER BY table_catalog, table_schema
""").fetchdf()
print(f"✅ Found {len(result)} schema(s):")
print(result.to_string(index=False))

# List tables across all databases
print("\n[5] Listing all tables with duckdb_tables()...")
result = conn.execute("""
    SELECT database_name, schema_name, table_name
    FROM duckdb_tables()
    ORDER BY database_name, schema_name, table_name
""").fetchdf()
print(f"✅ Found {len(result)} table(s):")
print(result.to_string(index=False))

# Check if we can query attached database tables
print("\n[6] Querying attached database table...")
result = conn.execute("SELECT * FROM attached_db.attached_table").fetchdf()
print(f"✅ Query worked! ({len(result)} rows)")

# Check how attached databases appear in pg_catalog
print("\n[7] Checking pg_catalog.pg_database...")
result = conn.execute("SELECT * FROM pg_catalog.pg_database").fetchdf()
print(f"✅ pg_catalog.pg_database has {len(result)} database(s):")
if len(result) > 0:
    print(result[['datname']].to_string(index=False))

# Check how attached tables appear in pg_catalog.pg_class
print("\n[8] Checking pg_catalog.pg_class...")
result = conn.execute("""
    SELECT relname, relnamespace
    FROM pg_catalog.pg_class
    WHERE relkind = 'r'
    ORDER BY relname
""").fetchdf()
print(f"✅ pg_catalog.pg_class has {len(result)} table(s):")
print(result.to_string(index=False))

# Summary
print("\n" + "="*70)
print("FINDINGS:")
print("="*70)
print("\n✅ duckdb_databases() - Lists all attached databases")
print("✅ duckdb_tables() - Lists tables across ALL databases")
print("✅ information_schema.tables - Shows tables from all databases")
print("\n💡 RECOMMENDATION:")
print("   Use duckdb_databases() to enumerate attached databases")
print("   Map each database as a PostgreSQL 'schema'")
print("   DBeaver will show: main, attached_db_1, attached_db_2, etc.")
print("="*70)

conn.close()
