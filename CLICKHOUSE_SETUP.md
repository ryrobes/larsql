# ClickHouse Server Setup Guide

Windlass now supports **automatic database and table creation** when using ClickHouse server mode. Just set environment variables and go!

## 🚀 Quick Start (Zero Configuration)

```bash
# 1. Start ClickHouse server
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# 2. Set environment variables
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost

# 3. Run windlass (database and table are created automatically!)
windlass examples/simple_flow.json --input '{"data": "test"}'
```

**That's it!** The first time Windlass runs, it will:
- ✅ Create the `windlass` database (if it doesn't exist)
- ✅ Create the `unified_logs` table (if it doesn't exist)
- ✅ Start writing logs directly to ClickHouse
- ✅ Continue reading from existing parquet files seamlessly

## 📊 What Gets Created Automatically

### Database
```sql
CREATE DATABASE windlass;
```

### Table
```sql
CREATE TABLE IF NOT EXISTS unified_logs (
    -- Core identification
    timestamp Float64,
    timestamp_iso String,
    session_id String,
    trace_id String,
    parent_id Nullable(String),
    parent_session_id Nullable(String),
    parent_message_id Nullable(String),

    -- Message classification
    node_type String,
    role Nullable(String),
    depth Int32,

    -- Execution context (soundings, reforge, wards)
    sounding_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    attempt_number Nullable(Int32),
    turn_number Nullable(Int32),

    -- Cascade context
    cascade_id Nullable(String),
    cascade_file Nullable(String),
    cascade_json Nullable(String),  -- JSON blob
    phase_name Nullable(String),
    phase_json Nullable(String),    -- JSON blob

    -- LLM provider data
    model Nullable(String),
    request_id Nullable(String),
    provider Nullable(String),

    -- Performance metrics
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),
    total_tokens Nullable(Int32),
    cost Nullable(Float64),

    -- Content (JSON blobs)
    content_json Nullable(String),
    full_request_json Nullable(String),
    full_response_json Nullable(String),
    tool_calls_json Nullable(String),

    -- Images
    images_json Nullable(String),
    has_images Bool DEFAULT false,
    has_base64 Bool DEFAULT false,

    -- Mermaid
    mermaid_content Nullable(String),

    -- Metadata
    metadata_json Nullable(String)
)
ENGINE = MergeTree()
ORDER BY (session_id, timestamp)
PARTITION BY toYYYYMM(toDateTime(timestamp))
SETTINGS index_granularity = 8192;
```

## ⚙️ Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDLASS_USE_CLICKHOUSE_SERVER` | `false` | Enable ClickHouse server mode |
| `WINDLASS_CLICKHOUSE_HOST` | `localhost` | ClickHouse server hostname |
| `WINDLASS_CLICKHOUSE_PORT` | `9000` | Native protocol port |
| `WINDLASS_CLICKHOUSE_DATABASE` | `windlass` | Database name |
| `WINDLASS_CLICKHOUSE_USER` | `default` | Username |
| `WINDLASS_CLICKHOUSE_PASSWORD` | `""` | Password (empty by default) |

### Example: Remote ClickHouse Server

```bash
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=clickhouse.production.com
export WINDLASS_CLICKHOUSE_PORT=9000
export WINDLASS_CLICKHOUSE_DATABASE=windlass_prod
export WINDLASS_CLICKHOUSE_USER=windlass_user
export WINDLASS_CLICKHOUSE_PASSWORD=secret123

# Run windlass - connects to remote server automatically
windlass examples/simple_flow.json --input '{"data": "test"}'
```

## 🔄 Migration Path

### Phase 1: Development (chDB - Embedded)
```bash
# Default - reads parquet files with chDB (embedded ClickHouse)
windlass examples/simple_flow.json --input '{"data": "test"}'

# Logs written to: /path/to/windlass/data/*.parquet
# Queries run with: chDB (no server needed)
```

### Phase 2: Production (ClickHouse Server)
```bash
# Start ClickHouse server
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# Enable server mode
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost

# Run windlass - automatic setup!
windlass examples/simple_flow.json --input '{"data": "test"}'

# Logs written to: ClickHouse server (windlass.unified_logs table)
# Queries run against: ClickHouse server
# Old parquet files: Still readable by queries!
```

### Phase 3: Scale (Distributed ClickHouse)
```bash
# Set up ClickHouse cluster (standard ClickHouse setup)
# Point windlass at any node

export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=clickhouse-node-1.cluster.com

# Same code, now distributed!
windlass examples/simple_flow.json --input '{"data": "test"}'
```

## 🎯 Hybrid Mode (Parquet + ClickHouse)

You can query **both** parquet files and ClickHouse simultaneously:

```python
from windlass.unified_logs import query_unified

# If server mode is enabled:
# 1. New logs go to ClickHouse
# 2. Queries check ClickHouse first
# 3. Old parquet files still readable via chDB

# Query across all data (parquet + ClickHouse)
df = query_unified("session_id = 'my_session'")
```

This allows gradual migration without losing historical data!

## 🧪 Testing the Setup

### Method 1: Quick Test
```bash
# Start server
docker run -d --name clickhouse-test \
  -p 9000:9000 \
  clickhouse/clickhouse-server

# Enable server mode
export WINDLASS_USE_CLICKHOUSE_SERVER=true

# Test with Python
python3 << 'EOF'
from windlass.unified_logs import log_unified, force_flush

log_unified(
    session_id="test_auto_setup",
    node_type="test",
    role="system",
    content="Testing automatic setup!"
)

force_flush()
print("✓ Message logged to ClickHouse!")
EOF

# Verify in ClickHouse
docker exec clickhouse-test clickhouse-client \
  --query "SELECT COUNT(*) FROM windlass.unified_logs"
```

### Method 2: Full Test Script
```bash
./test_clickhouse_auto_setup.sh
```

## 🔍 Verifying the Setup

### Check Database Exists
```bash
docker exec clickhouse-server clickhouse-client \
  --query "SHOW DATABASES" | grep windlass
```

### Check Table Exists
```bash
docker exec clickhouse-server clickhouse-client \
  --query "SHOW TABLES FROM windlass"
```

### Query Data
```bash
docker exec clickhouse-server clickhouse-client \
  --query "SELECT COUNT(*) as total_messages FROM windlass.unified_logs"
```

### View Recent Messages
```bash
docker exec clickhouse-server clickhouse-client \
  --query "SELECT session_id, phase_name, cost FROM windlass.unified_logs ORDER BY timestamp DESC LIMIT 10 FORMAT Vertical"
```

## 📈 Performance Considerations

### Batch Size
```python
# Default: 100 messages or 10 seconds (whichever first)
# ClickHouse loves large batches - consider increasing for high-volume:

# In unified_logs.py (if needed)
self.buffer_limit = 1000  # Larger batches
self.flush_interval = 30.0  # Less frequent flushes
```

### Partitioning
The table is partitioned by month (`toYYYYMM(toDateTime(timestamp))`):
- Efficient for time-range queries
- Easy to drop old partitions for data retention
- Parallel query execution per partition

### Indexes
Optional bloom filter indexes for common queries:
```sql
-- Run after table creation (optional, improves query performance)
ALTER TABLE windlass.unified_logs ADD INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1;
ALTER TABLE windlass.unified_logs ADD INDEX idx_phase_name phase_name TYPE bloom_filter GRANULARITY 1;
ALTER TABLE windlass.unified_logs ADD INDEX idx_is_winner is_winner TYPE set(0) GRANULARITY 1;
```

## 🛠️ Troubleshooting

### Issue: "Database already exists"
**This is fine!** Auto-creation detects existing database and skips creation.

### Issue: "Table already exists"
**This is fine!** Auto-creation detects existing table and skips creation.

### Issue: Connection refused
```bash
# Check if ClickHouse is running
docker ps | grep clickhouse

# Check logs
docker logs clickhouse-server

# Restart if needed
docker restart clickhouse-server
```

### Issue: Fallback to Parquet
If ClickHouse setup fails, Windlass gracefully falls back to parquet mode:
```
[Windlass] Warning: Could not ensure ClickHouse setup: ...
[Windlass] Continuing with parquet-only mode...
```

Check your connection settings and try again.

## 🎓 Advanced: Custom Table Schema

If you need to customize the schema, you can manually create the table before running Windlass:

```bash
docker exec -i clickhouse-server clickhouse-client << 'EOF'
CREATE DATABASE IF NOT EXISTS windlass;

CREATE TABLE IF NOT EXISTS windlass.unified_logs (
    -- Your custom schema here
    -- Must include all required fields from schema.py
    ...
) ENGINE = MergeTree()
ORDER BY (session_id, timestamp);
EOF
```

Windlass will detect the existing table and use it.

## 📚 Further Reading

- **ClickHouse Documentation**: https://clickhouse.com/docs
- **Windlass Schema**: See `windlass/schema.py`
- **Database Adapter**: See `windlass/db_adapter.py`
- **Unified Logging**: See `windlass/unified_logs.py`

## 🎉 Summary

**Before Windlass Auto-Setup:**
```bash
# Manual steps
docker exec clickhouse-server clickhouse-client --query "CREATE DATABASE windlass"
docker exec clickhouse-server clickhouse-client --query "CREATE TABLE windlass.unified_logs (...)"
# Configure connection
# Run windlass
```

**With Windlass Auto-Setup:**
```bash
# Just set env vars and go!
export WINDLASS_USE_CLICKHOUSE_SERVER=true
windlass examples/simple_flow.json --input '{"data": "test"}'
# Database and table created automatically!
```

**Zero configuration. Just works.** 🚀
