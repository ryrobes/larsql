# Durable State System - Queryable LLM Memory

## Overview

The `set_state` tool now persists to **ClickHouse** (`cascade_state` table), making state:
- ✅ Durable (survives cascade completion)
- ✅ Queryable (SQL access across sessions)
- ✅ Observable (live UI panel in Studio)
- ✅ Time-series (track state evolution)

## How It Works

### Before (Ephemeral)
```python
set_state("insights", "Revenue up 20%")
# Stored in Echo.state
# Lost when cascade ends
```

### After (Durable)
```python
set_state("insights", "Revenue up 20%")
# 1. Stored in Echo.state (backward compat)
# 2. Persisted to cascade_state table (ClickHouse)
# 3. Visible in Studio UI (live updates)
# 4. Queryable forever
```

## Database Schema

```sql
CREATE TABLE cascade_state (
    session_id String,
    cascade_id String,
    key String,
    value String,            -- JSON-serialized
    phase_name String,       -- Which phase set this
    created_at DateTime,
    value_type String        -- string|number|object|array|boolean|null
)
ORDER BY (cascade_id, session_id, key, created_at);
```

## Usage Patterns

### 1. Basic State Setting
```yaml
- name: analyze
  instructions: |
    Analyze data and store insights.

    Use set_state() to persist findings:
    set_state("total_revenue", 125000)
    set_state("top_category", "Electronics")
  tackle: [set_state]
```

### 2. Complex State (JSON)
```yaml
- name: synthesize
  instructions: |
    set_state("analysis", json.dumps({
      "findings": ["finding1", "finding2"],
      "confidence": 0.92,
      "recommendations": [...]
    }))
```

### 3. Incremental Processing
```yaml
- name: process_batch
  instructions: |
    # Query what was processed last time
    prior_ids = query_state(cascade_id='etl', key='processed_ids', limit=1)

    # Process only new records
    new_ids = all_ids - prior_ids

    # Update state
    set_state("processed_ids", new_ids)
    set_state("last_run", datetime.now())
```

### 4. Cross-Run Learning
```yaml
- name: improve_analysis
  instructions: |
    Query past conclusions:

    SELECT value, created_at
    FROM cascade_state
    WHERE cascade_id = 'weekly_analysis'
      AND key = 'insights'
    ORDER BY created_at DESC
    LIMIT 5

    Build on those insights without repeating work.
  tackle: [sql_data, set_state]
```

## Studio UI - Live State Panel

### Location
Left sidebar in Studio → "Session State" section

### Features
- **Live Updates**: Polls every 1s during execution
- **Type Indicators**: Badges show string/number/object/array
- **Expandable JSON**: Click to see full object/array values
- **Update History**: See how values changed over time
- **Phase Attribution**: Know which phase set each value

### UI Elements
```
Session State                            4 keys  ●

  key                                    string
  total_revenue                          analyze · 3s ago
    "125000"

  top_performers                         array
  analyze_with_soundings                 analyze · 5s ago
    [3 items]                            ▼

    Update History:
      5s ago    analyze    [...previous value...]
      2m ago    validate   [...older value...]

  insights                               object
  synthesize                             finalize · just now
    {5 keys}                             ▼

    {
      "findings": ["...", "..."],
      "confidence": 0.92
    }
```

## Query Examples

### Get Current State
```sql
-- Latest value for each key in a session
SELECT DISTINCT ON (key) key, value, phase_name
FROM cascade_state
WHERE session_id = 'clever-fox-a3f2'
ORDER BY key, created_at DESC
```

### State Evolution
```sql
-- See how insights changed over time
SELECT created_at, phase_name, value
FROM cascade_state
WHERE cascade_id = 'analysis'
  AND key = 'insights'
ORDER BY created_at DESC
LIMIT 20
```

### Cross-Session Analytics
```sql
-- Average confidence scores across all runs
SELECT
  AVG(JSONExtractFloat(value, 'confidence')) as avg_confidence,
  COUNT(*) as run_count
FROM cascade_state
WHERE cascade_id = 'sentiment_analysis'
  AND key = 'results'
  AND value_type = 'object'
```

### Find Sessions with Specific State
```sql
-- Find runs where revenue exceeded threshold
SELECT session_id, created_at, value
FROM cascade_state
WHERE cascade_id = 'sales_pipeline'
  AND key = 'total_revenue'
  AND CAST(value AS INTEGER) > 100000
ORDER BY created_at DESC
```

## Benefits

### 1. Observable Execution
See state being built in real-time as cascade runs.

### 2. Debugging
Inspect exact state when something went wrong.

### 3. LLM Memory
Query past state to inform current decisions:
```python
"Based on the last 5 runs (query cascade_state),
 the top category is consistently Electronics.
 Focus analysis there."
```

### 4. A/B Testing
```sql
SELECT
  JSONExtractString(cs.input_data, 'variant'),
  AVG(JSONExtractFloat(st.value, 'conversion_rate'))
FROM cascade_sessions cs
JOIN cascade_state st ON cs.session_id = st.session_id
WHERE st.key = 'metrics'
GROUP BY variant
```

### 5. State Diffing
```sql
-- Compare state between two sessions
SELECT
  a.key,
  a.value as session_a_value,
  b.value as session_b_value
FROM cascade_state a
JOIN cascade_state b
  ON a.key = b.key
WHERE a.session_id = 'clever-fox-a3f2'
  AND b.session_id = 'brave-owl-x7b9'
```

## Implementation Files

### Migration
- `windlass/migrations/create_cascade_state_table.sql` - Table schema

### Core
- `windlass/eddies/state_tools.py` - Modified `set_state` to persist

### Backend API
- `dashboard/backend/studio_api.py` - `GET /api/studio/session-state/<session_id>`

### Frontend
- `dashboard/frontend/src/studio/notebook/SessionStatePanel.jsx` - UI component
- `dashboard/frontend/src/studio/notebook/SessionStatePanel.css` - Styling
- `dashboard/frontend/src/studio/notebook/CascadeNavigator.js` - Integration

## Migration Status

✅ **Applied**: `create_cascade_state_table.sql`

All future `set_state()` calls automatically persist to ClickHouse.

## Testing

### 1. Run a Cascade with State
```bash
windlass run examples/comprehensive_test_cascade.yaml --input '{"analysis_type": "sales"}'
```

### 2. Query State
```python
from windlass.db_adapter import get_db

db = get_db()
rows = db.query("""
    SELECT key, value, phase_name, created_at
    FROM cascade_state
    WHERE session_id = 'your-session-id'
    ORDER BY created_at DESC
""")

for row in rows:
    print(f"{row['key']}: {row['value']} (from {row['phase_name']})")
```

### 3. View in Studio
1. Run cascade in Studio
2. Watch "Session State" panel populate in real-time
3. Click to expand complex values
4. See update history

## Backward Compatibility

- ✅ Old cascades work without changes
- ✅ Echo.state still works
- ✅ No breaking changes
- ✅ Table creation is idempotent
- ✅ Fails gracefully if table doesn't exist

## Performance

- **Writes**: Fire-and-forget (don't block cascade)
- **Reads**: Indexed by (cascade_id, session_id, key)
- **Storage**: ~100 bytes per state entry (minimal)
- **Concurrency**: ClickHouse handles concurrent reads during writes

## Future Enhancements

### 1. State Snapshots
Export all state for a session as JSON file.

### 2. State Restore
Load state from previous run to continue where you left off.

### 3. State Validators
Validate state shape/values before persisting.

### 4. State Triggers
Execute actions when state reaches certain values.

### 5. State Subscriptions
Real-time notifications when specific keys update.

---

**State is now a first-class, queryable artifact** of cascade execution! 🗄️
