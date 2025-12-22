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
- `add_prompt_lineage_table.sql` - Creates `prompt_lineage` table for tracking prompt evolution (2025-12-10)
- `add_species_stats_view.sql` - Creates `species_stats` materialized view for fast species queries (2025-12-10)
- `create_artifacts_table.sql` - Creates `artifacts` table for persistent rich UI outputs (2025-12-14)
- `create_research_sessions_table.sql` - Creates `research_sessions` table for Research Cockpit (2025-12-15)
- `create_context_cards_table.sql` - Creates `context_cards` table for auto-context system (2025-12-20)
- `create_cascade_sessions_table.sql` - Creates `cascade_sessions` table for storing full cascade definitions per run (2025-12-22)
- `add_checkpoint_types.sql` - Adds checkpoint type tracking columns (2025-12-13)
- `add_checkpoint_summary.sql` - Adds checkpoint summary column (2025-12-16)
- `add_model_requested_column.sql` - Adds `model_requested` column (2025-12-10)
- `add_reasoning_columns.sql` - Adds extended thinking columns (2025-12-19)
- `add_ui_sql_log_columns.sql` - Adds UI query tracking columns (2025-12-20)

## Notes

- Migrations use `IF NOT EXISTS` / `IF EXISTS` clauses for idempotency
- Safe to run multiple times
- No data loss - only adds columns/tables with safe defaults
- Migrations auto-run when db_adapter initializes
