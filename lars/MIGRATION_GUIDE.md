# Universal Training System - Migration Guide

**Migration file:** `lars/migrations/create_universal_training_system.sql`
**Status:** ✅ Idempotent (safe to run multiple times)

---

## Quick Start (Choose One Method)

### Method 1: Helper Script (Recommended)

```bash
./scripts/apply_training_migration.sh
```

**What it does:**
- ✅ Tests ClickHouse connection
- ✅ Applies migration to correct database
- ✅ Verifies tables created
- ✅ Provides next steps

---

### Method 2: Direct ClickHouse Client

```bash
# Default database (lars)
clickhouse-client --database lars < lars/migrations/create_universal_training_system.sql

# Custom database
clickhouse-client --database my_db < lars/migrations/create_universal_training_system.sql
```

---

### Method 3: Via LARS SQL Command

```bash
lars sql query "$(cat lars/migrations/create_universal_training_system.sql)"
```

---

## What Gets Created

**1. Table:** `training_annotations`
- Stores trainable flags for specific trace_ids
- Lightweight (only annotated traces)
- ReplacingMergeTree (updates are automatic)

**2. Materialized View:** `training_examples_mv`
- Extracts training examples from `unified_logs`
- Updates automatically as new logs arrive
- Parses user_input and assistant_output from JSON

**3. View:** `training_examples_with_annotations`
- Combines materialized view + annotations
- Used by training system for retrieval

**4. View:** `training_stats_by_cascade`
- Aggregate statistics by cascade/cell
- Used by Studio UI for KPI cards

---

## Verify Migration Worked

```bash
# Check tables exist
lars sql query "SHOW TABLES LIKE '%training%'"

# Expected output:
# - training_annotations
# - training_examples_mv
# - training_examples_with_annotations
# - training_stats_by_cascade

# Check materialized view is populating
lars sql query "SELECT COUNT(*) FROM training_examples_mv"

# Should return count > 0 if you have any cascade executions logged
```

---

## Idempotency Verification

The migration is **safe to run multiple times** because it uses:

```sql
CREATE TABLE IF NOT EXISTS training_annotations ...
CREATE INDEX IF NOT EXISTS idx_trainable ...
CREATE MATERIALIZED VIEW IF NOT EXISTS training_examples_mv ...
CREATE VIEW IF NOT EXISTS training_examples_with_annotations ...
CREATE VIEW IF NOT EXISTS training_stats_by_cascade ...
```

**All 6 statements** have `IF NOT EXISTS` - no errors on re-run!

---

## Troubleshooting

### ClickHouse not running

```bash
# Check status
sudo systemctl status clickhouse-server

# Start if needed
sudo systemctl start clickhouse-server

# Or with Docker
docker start clickhouse-server
```

### Database doesn't exist

```bash
# Create database first
clickhouse-client --query "CREATE DATABASE IF NOT EXISTS lars"

# Then run migration
clickhouse-client --database lars < lars/migrations/create_universal_training_system.sql
```

### Permission denied

```bash
# Check ClickHouse permissions
clickhouse-client --query "SELECT currentUser()"

# May need to specify user/password
clickhouse-client --user default --password '' --database lars < lars/migrations/create_universal_training_system.sql
```

### View/table already exists

**This is fine!** Migration is idempotent. The `IF NOT EXISTS` clause means:
- Existing tables/views are unchanged
- No errors thrown
- Safe to re-run anytime

---

## Post-Migration Testing

```bash
# 1. Check tables created
lars sql query "DESCRIBE training_annotations"

# 2. Insert test annotation
lars sql query "
INSERT INTO training_annotations (trace_id, trainable)
VALUES ('test-123', true)
"

# 3. Query it back
lars sql query "
SELECT * FROM training_annotations WHERE trace_id = 'test-123'
"

# 4. Check view works
lars sql query "
SELECT COUNT(*) FROM training_examples_with_annotations
"
```

---

## Next Steps After Migration

1. ✅ **Start Studio**
   ```bash
   cd studio/backend && python app.py
   cd studio/frontend && npm start
   ```

2. ✅ **Navigate to Training UI**
   - http://localhost:5550/training

3. ✅ **Generate test data**
   ```bash
   lars serve sql --port 15432
   psql postgresql://localhost:15432/default -c "
   SELECT 'test' MEANS 'example';
   "
   ```

4. ✅ **Mark as trainable in UI**
   - Click ✅ checkbox in Training grid

5. ✅ **Verify training works**
   - Re-run query
   - Look for: "📚 Injected N training examples"

---

**Date:** 2026-01-02
**Status:** ✅ Migration ready, fully idempotent
