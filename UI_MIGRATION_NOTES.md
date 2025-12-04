# UI Migration to Unified Logs - Notes

## Issues Fixed

### 1. "Struct remap" Error
**Problem:** DuckDB was trying to union old echoes schema (with `content`, `metadata`, `tool_calls` as direct types) with new unified schema (with `content_json`, `metadata_json`, `tool_calls_json` as JSON strings).

**Solution:** Updated `get_db_connection()` to:
- Try multiple locations for data/ directory
- Load ONLY unified logs if found (don't mix with old echoes)
- Fall back to old echoes ONLY if unified logs don't exist
- Added debug logging to show which source is being used

### 2. Data Directory Path Issues
**Problem:** `unified_logs.py` was using `./data` which is relative to working directory, causing data to be written to different locations depending on where windlass was run from.

**Solution:**
- Added `data_dir` field to `config.py` (respects `WINDLASS_DATA_DIR` env var)
- Updated `unified_logs.py` to use `config.data_dir` instead of hardcoded `./data`
- Consolidated existing data files to `/home/ryanr/repos/windlass/data/`
- UI backend updated to check multiple possible paths

### 3. Schema Differences

**Old Echoes Schema (25 columns):**
- `content` - Direct string/struct
- `metadata` - Direct dict/struct
- `tool_calls` - Direct list/struct
- `image_paths` - List of strings
- `image_count` - Integer

**New Unified Schema (36 columns):**
- `content_json` - JSON string
- `metadata_json` - JSON string
- `tool_calls_json` - JSON string
- `images_json` - JSON array string
- `cascade_json` - Complete cascade config as JSON
- `phase_json` - Complete phase config as JSON
- `full_request_json` - Complete request with history
- `full_response_json` - Complete LLM response
- `timestamp_iso` - ISO 8601 timestamp
- `total_tokens` - Sum of tokens_in + tokens_out
- `model`, `provider` - Unwrapped from response
- `attempt_number`, `turn_number` - Special indexes
- `parent_session_id`, `parent_message_id` - Sub-cascade tracking

## Configuration

### Environment Variables

```bash
# Data directory (unified logs location)
export WINDLASS_DATA_DIR=/path/to/data  # Default: ./data

# Old directories (still used for graphs, state, images)
export WINDLASS_LOG_DIR=/path/to/logs   # Default: ./logs (old echoes fallback)
export WINDLASS_GRAPH_DIR=/path/to/graphs
export WINDLASS_STATE_DIR=/path/to/states
export WINDLASS_IMAGE_DIR=/path/to/images
```

### UI Backend Path Resolution

The backend tries these locations in order:
1. `../../windlass/data` - From UI backend to windlass package
2. `../../../data` - Root level relative to repo root
3. `./data` - Current directory
4. `../../data` - Root level relative to UI
5. Fallback to `logs/echoes/*.parquet` if no unified logs found

## Data Migration

### Current State
- ✅ Unified logs: `/home/ryanr/repos/windlass/data/*.parquet` (4 files, 27 rows)
- ⚠️  Old echoes: `/home/ryanr/repos/windlass/logs/echoes/*.parquet` (many files, old schema)

### Recommendation
Once you've verified the UI works with unified logs, you can safely delete old echoes:

```bash
# Backup first (optional)
tar -czf echoes_backup_$(date +%Y%m%d).tar.gz logs/echoes/

# Delete old echoes
rm -rf logs/echoes/
rm -rf logs/echoes_jsonl/
rm -rf logs/log_*.parquet  # Old logs.py files
```

## Testing

### Verify Backend Loads Unified Logs

```bash
cd extras/ui/backend
python3 << 'EOF'
from app import get_db_connection
conn = get_db_connection()
result = conn.execute("SELECT COUNT(*) FROM logs").fetchone()
print(f"Total rows: {result[0]}")
conn.close()
EOF
```

Expected output:
```
[INFO] Loading unified logs from: ../../../data
[INFO] Found 4 unified log files
Total rows: 27
```

### Verify UI Works

1. Start backend: `cd extras/ui/backend && python app.py`
2. Start frontend: `cd extras/ui/frontend && npm start`
3. Open http://localhost:3000
4. Should see cascades: `data_analysis`, `iterative_joke`, `parent_cascade`, `sub_cascade_greeter`

## Buffering Configuration

Unified logs use buffering to reduce file count:
- Buffer size: 100 messages OR 10 seconds (whichever comes first)
- Files named: `log_{timestamp}_{count}msgs_{uuid}.parquet`
- Automatic flush on program exit (atexit handler)
- Manual flush: `from windlass.unified_logs import force_flush; force_flush()`

## Troubleshooting

### "No logs found in any location"
- Check `WINDLASS_DATA_DIR` environment variable
- Verify data directory exists: `ls -la /home/ryanr/repos/windlass/data/`
- Run a cascade to generate new unified logs

### "Struct remap" errors still appearing
- Make sure you're not mixing old and new data
- Delete old echoes or set `WINDLASS_LOG_DIR` to point elsewhere
- Check backend logs for which data source is being loaded

### UI shows old cascades only
- Backend is falling back to old echoes
- Check backend console for `[INFO]` messages
- Verify unified logs exist in expected location
- May need to restart backend after moving files

## Summary

✅ **Backend updated** to load unified logs from configurable data directory
✅ **Path resolution** handles multiple possible locations
✅ **Schema isolation** prevents mixing old and new data
✅ **Config system** supports `WINDLASS_DATA_DIR` env var
✅ **Data consolidated** to single root-level `data/` directory
✅ **Backward compatible** - falls back to old echoes if needed

The UI should now work correctly with the new unified logging system!
