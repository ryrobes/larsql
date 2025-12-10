# Database Migrations

This directory contains SQL migration scripts for upgrading existing Windlass databases.

## Applying Migrations

### Using ClickHouse Client

If you're using ClickHouse server (not chDB), you can apply migrations using the clickhouse-client:

```bash
# Connect to your ClickHouse instance
clickhouse-client --host localhost --port 9000

# Run the migration
SOURCE /path/to/windlass/migrations/add_callouts_columns.sql;
```

### Using windlass CLI

You can also apply migrations using the windlass SQL command:

```bash
# Apply migration line by line
cat windlass/migrations/add_callouts_columns.sql | grep -v "^--" | windlass sql -
```

### Using Python

```python
from windlass.db_adapter import get_db

db = get_db()

# Read and execute migration
with open('windlass/migrations/add_callouts_columns.sql') as f:
    sql = f.read()
    # Split by semicolons and execute each statement
    for statement in sql.split(';'):
        statement = statement.strip()
        if statement and not statement.startswith('--'):
            db.execute(statement)
```

## Available Migrations

- `add_callouts_columns.sql` - Adds `is_callout` and `callout_name` columns for semantic message tagging (2025-12-09)
- `add_species_hash_column.sql` - Adds `species_hash` column for prompt evolution tracking in Sextant (2025-12-10)
- `add_prompt_lineage_table.sql` - Creates `prompt_lineage` table for tracking prompt evolution (2025-12-10, Phase 3)
- `add_species_stats_view.sql` - Creates `species_stats` materialized view for fast species queries (2025-12-10, Phase 3)

## Notes

- Migrations use `IF NOT EXISTS` / `IF EXISTS` clauses for idempotency
- Safe to run multiple times
- No data loss - only adds columns with safe defaults
