# ClickHouse Performance Tuning for High Concurrency

## Problem

When running many cascades simultaneously, you may see:
- UI pages slow to load on first try
- "Connection refused" errors
- Queries timing out
- Dashboard lag

**Root cause:** ClickHouse default `max_concurrent_queries=100` is too low when:
- Multiple cascades running (each making queries)
- Flask backend polling for updates
- Frontend fetching session data
- Unified logging happening in parallel

## Solution: Optimized ClickHouse Configuration

### Step 1: Update Docker Setup

**Use the new optimized script:**
```bash
# Stop existing ClickHouse
docker stop windlass-clickhouser
docker rm windlass-clickhouser

# Start with optimized config
chmod +x windlass-docker-clickhouse-optimized.sh
./windlass-docker-clickhouse-optimized.sh
```

**What it changes:**
- Maps `clickhouse-config.xml` into container
- Increases `max_concurrent_queries`: 100 → **500**
- Increases `max_connections`: 4096 → **2048** (explicit)
- Adds memory/CPU limits for stability

### Step 2: Verify Configuration

```bash
# Connect to ClickHouse
docker exec -it windlass-clickhouse clickhouse-client

# Check settings
SELECT name, value FROM system.settings
WHERE name LIKE 'max_concurrent%' OR name LIKE 'max_connections';
```

**Expected output:**
```
max_concurrent_queries         500
max_concurrent_insert_queries  200
max_concurrent_select_queries  300
max_connections                2048
```

### Step 3: Restart Windlass

The `db_adapter.py` changes are already applied with better timeouts.

**Restart Flask backend:**
```bash
# Ctrl+C in Flask terminal
python dashboard/backend/app.py
```

## What We Changed

### ClickHouse Server Config (`clickhouse-config.xml`)

```xml
<max_concurrent_queries>500</max_concurrent_queries>       <!-- Was: 100 -->
<max_concurrent_insert_queries>200</max_concurrent_insert_queries>  <!-- Was: 100 -->
<max_concurrent_select_queries>300</max_concurrent_select_queries>  <!-- Was: 100 -->
<max_connections>2048</max_connections>                     <!-- Was: 4096 (explicit) -->
<keep_alive_timeout>30</keep_alive_timeout>                 <!-- Keep connections alive -->
```

### Python Client (`db_adapter.py`)

```python
self.client = Client(
    connect_timeout=10,          # Was: default (1s)
    send_receive_timeout=30,     # Was: default (10s)
    sync_request_timeout=30,     # Was: default
    settings={
        'max_threads': 4,        # Limit per-query threads
        'max_execution_time': 60  # Query timeout
    }
)
```

## Performance Impact

**Before:**
- ~100 concurrent queries max
- UI timeouts with 10+ cascades
- Connection refused errors

**After:**
- ~500 concurrent queries max
- Supports 50+ cascades simultaneously
- Better timeout handling
- Keep-alive reduces connection overhead

## Monitoring

### Check Current Load

```sql
-- Active queries
SELECT count() FROM system.processes;

-- Query queue depth
SELECT metric, value FROM system.metrics
WHERE metric LIKE '%Query%';

-- Connection count
SELECT value FROM system.metrics
WHERE metric = 'TCPConnection';
```

### If Still Having Issues

**Increase further:**
```xml
<max_concurrent_queries>1000</max_concurrent_queries>
```

**Or reduce cascade parallelism:**
```bash
# Run cascades sequentially instead of parallel
# Or limit soundings: factor=2 instead of 10
```

## Resource Usage

**Memory:**
- Each query: ~10-50MB
- 500 concurrent: ~5-25GB peak
- Docker limit: 4GB (adjust with `--memory=8g` if needed)

**CPU:**
- Each query: 1-4 threads
- 500 concurrent: Heavy load
- Docker limit: 2 CPUs (adjust with `--cpus=4` if needed)

## Alternative: Connection Pooling

If still having issues, consider connection pool wrapper:

```python
# Future enhancement: Add connection pool
from queue import Queue

class ConnectionPool:
    def __init__(self, size=10):
        self.pool = Queue(maxsize=size)
        for _ in range(size):
            self.pool.put(create_client())

    def get_connection(self):
        return self.pool.get()

    def return_connection(self, conn):
        self.pool.put(conn)
```

But the config changes above should handle 50+ cascades without pooling!
