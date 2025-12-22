# Cascade Sessions Storage - Migration Complete

## Summary

Added a new system to store full cascade definitions and inputs for each session run. This enables **perfect replay** of historical runs with their exact cascade structure and inputs.

## What Was Added

### 1. Database Table: `cascade_sessions`
**Location**: `windlass/migrations/create_cascade_sessions_table.sql`

Stores for each session:
- Raw cascade file contents (YAML/JSON as-is, no conversion)
- Input parameters passed to the run (JSON)
- Cascade ID, session ID, config path
- Parent session ID and depth (for sub-cascades)
- Timestamp

### 2. Runner Integration
**File**: `windlass/windlass/runner.py` (lines 4221-4263)

When a cascade starts (`run()` method):
- **If file path**: Reads raw file contents (preserves YAML/JSON exactly)
- **If inline dict**: Dumps to YAML (preserves all nested data)
- Serializes input parameters to JSON
- Saves both to `cascade_sessions` table
- Fails gracefully if table doesn't exist (backward compat)

**Why raw storage?** Avoids data loss from Pydantic serialization. The original YAML/JSON is stored character-for-character, ensuring perfect replay.

### 3. Backend API Update
**File**: `dashboard/backend/studio_api.py` (route `/api/studio/session-cascade/<session_id>`)

Endpoint now:
- **First**: Tries to fetch from `cascade_sessions` table (new sessions)
- **Fallback**: Reconstructs from logs (old sessions before migration)
- Returns full cascade definition + inputs OR minimal reconstructed structure

### 4. Frontend Integration
**Files**:
- `dashboard/frontend/src/studio/stores/studioCascadeStore.js` (setReplayMode)
- `dashboard/frontend/src/studio/notebook/CascadeTimeline.jsx` (polling in replay mode)

Changes:
- `setReplayMode()` now loads historical cascade definition from API
- Polling activates in replay mode to fetch historical execution data
- Replay banner shows session ID with "Exit Replay" button

## Migration Status

✅ **Migration Applied**: `create_cascade_sessions_table.sql` has been run
✅ **All migrations**: 13 total migrations successfully executed

## How It Works Now

### For New Runs (After Migration)
1. User runs a cascade with inputs
2. Runner saves full cascade definition + inputs to `cascade_sessions` table
3. User can replay any session and see:
   - Exact cascade structure (all phases with their tool configs)
   - Exact inputs that were used
   - Historical execution results

### For Old Runs (Before Migration)
- Falls back to reconstructing from logs
- Shows phase names only (no tool configs)
- Warning message explains limitation

## Testing

To test the new system:

```bash
# 1. Run a cascade with inputs
cd windlass
python -c "from windlass import run_cascade; run_cascade('examples/notebook_polyglot_showcase.yaml', {'name': 'test'}, session_id='test_replay_001')"

# 2. Query the cascade_sessions table
python -c "
from windlass.db_adapter import get_db
import json
db = get_db()
rows = db.execute('SELECT session_id, cascade_id, input_data FROM cascade_sessions WHERE session_id = ?', ['test_replay_001']).fetchall()
if rows:
    print('Session found!')
    print('Session ID:', rows[0][0])
    print('Cascade ID:', rows[0][1])
    print('Inputs:', json.loads(rows[0][2]))
"

# 3. Test replay in Studio
# - Open http://localhost:3000/#/studio
# - Expand "Recent Runs" in left sidebar
# - Click on a session
# - Should load the exact cascade definition from that run
```

## Benefits

1. **Perfect Replay**: View historical runs exactly as they were executed
2. **Versioning**: See how your cascades evolved over time
3. **Reproducibility**: Re-run with exact same definition + inputs
4. **Debugging**: Understand what the cascade looked like when an issue occurred
5. **Audit Trail**: Track all runs with their configurations

## Files Modified

```
windlass/migrations/create_cascade_sessions_table.sql  [NEW]
windlass/windlass/runner.py                            [MODIFIED - added cascade def save]
dashboard/backend/studio_api.py                        [MODIFIED - updated API endpoint]
dashboard/frontend/src/studio/stores/studioCascadeStore.js  [MODIFIED - load historical def]
dashboard/frontend/src/studio/notebook/CascadeTimeline.jsx  [MODIFIED - poll in replay]
```

## Next Steps

All future cascade runs will automatically save their full definitions. Historical replay now works perfectly for new runs!

To see it in action:
1. Run any cascade (it will auto-save to `cascade_sessions`)
2. Open Studio → Recent Runs → Click any session
3. See the full cascade structure and execution results
