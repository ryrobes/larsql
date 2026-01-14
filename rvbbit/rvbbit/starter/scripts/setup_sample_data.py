#!/usr/bin/env python3
"""
Setup RVBBIT Sample Database

Creates a DuckDB database with sample data for testing RVBBIT features.
Run this script after initializing your workspace with `rvbbit init`.

Usage:
    python scripts/setup_sample_data.py

After running:
    rvbbit sql crawl       # Index the schema
    rvbbit sql query "SELECT * FROM sample_data.customers"
"""

import sys
from pathlib import Path


def main():
    # Find workspace root (look for .rvbbit marker or use cwd)
    workspace = Path.cwd()
    if not (workspace / '.rvbbit').exists():
        print("Warning: Not in an initialized RVBBIT workspace.")
        print("Run 'rvbbit init .' first, or continue anyway.")
        response = input("Continue? [y/N]: ").strip().lower()
        if response != 'y':
            sys.exit(0)

    # Check for DuckDB
    try:
        import duckdb
    except ImportError:
        print("Error: DuckDB not installed.")
        print("Install with: pip install duckdb")
        sys.exit(1)

    # Paths
    data_dir = workspace / 'data'
    db_path = data_dir / 'sample.duckdb'
    sql_path = data_dir / 'create_sample_db.sql'

    # Create data directory if needed
    data_dir.mkdir(parents=True, exist_ok=True)

    # Check if SQL script exists
    if not sql_path.exists():
        print(f"Error: SQL script not found at {sql_path}")
        print("Make sure you have the starter files from 'rvbbit init'.")
        sys.exit(1)

    # Check if database already exists
    if db_path.exists():
        print(f"Database already exists at {db_path}")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)
        db_path.unlink()

    # Create database
    print(f"Creating sample database at {db_path}...")

    try:
        conn = duckdb.connect(str(db_path))
        with open(sql_path, 'r') as f:
            sql = f.read()
        conn.execute(sql)
        conn.close()
        print("✓ Sample database created successfully!")
        print()
        print("Next steps:")
        print("  1. Run: rvbbit sql crawl")
        print("  2. Query: rvbbit sql query 'SELECT * FROM sample_data.customers'")
        print("  3. Start Studio: rvbbit serve studio")
        print()
    except Exception as e:
        print(f"Error creating database: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
