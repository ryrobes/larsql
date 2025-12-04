# UI Schema Fix - Old Column Names

## Problem

The UI backend was querying old echoes schema column names that don't exist in the unified logs:

- `metadata` → should be `metadata_json`
- `content` → should be `content_json`
- `tool_calls` → should be `tool_calls_json` (though not queried in SQL)

This caused errors like:
```
Binder Error: Referenced column "metadata" not found in FROM clause!
Candidate bindings: "metadata_json", ...
```

## Schema Differences

**Old Echoes Schema:**
- `metadata` - dict/struct
- `content` - string/struct
- `tool_calls` - list/struct
- `image_paths` - list

**New Unified Schema:**
- `metadata_json` - JSON string
- `content_json` - JSON string
- `tool_calls_json` - JSON string
- `images_json` - JSON string

## Fixes Applied

### 1. Line 315-318: Cost query with metadata

**Before:**
```sql
CAST(json_extract_string(metadata, '$.cost') AS DOUBLE)
...
WHERE ... json_extract_string(metadata, '$.cost') IS NOT NULL
```

**After:**
```sql
CAST(json_extract_string(metadata_json, '$.cost') AS DOUBLE)
...
WHERE ... json_extract_string(metadata_json, '$.cost') IS NOT NULL
```

### 2. Line 652: Output content query

**Before:**
```sql
SELECT content
FROM logs
WHERE session_id = ? AND (node_type = 'turn_output' OR node_type = 'agent')
```

**After:**
```sql
SELECT content_json
FROM logs
WHERE session_id = ? AND (node_type = 'turn_output' OR node_type = 'agent')
```

### 3. Line 700: Error content query

**Before:**
```sql
SELECT phase_name, content
FROM logs
WHERE session_id = ? AND node_type = 'error'
```

**After:**
```sql
SELECT phase_name, content_json
FROM logs
WHERE session_id = ? AND node_type = 'error'
```

## Testing

```bash
cd extras/ui/backend
python3 << 'EOF'
from app import get_db_connection
conn = get_db_connection()

# Test metadata_json query
query = """
SELECT SUM(COALESCE(cost, CAST(json_extract_string(metadata_json, '$.cost') AS DOUBLE))) as total_cost
FROM logs
WHERE cost IS NOT NULL OR json_extract_string(metadata_json, '$.cost') IS NOT NULL
"""
result = conn.execute(query).fetchone()
print(f"✅ Metadata query works: ${result[0]}")

# Test content_json query
query2 = "SELECT content_json FROM logs WHERE node_type = 'agent' LIMIT 1"
result2 = conn.execute(query2).fetchone()
print(f"✅ Content_json query works")

conn.close()
