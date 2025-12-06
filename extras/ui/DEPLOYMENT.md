# Deployment Guide - Debug UI

## Development (Flask built-in server)

**Single-threaded, simple:**
```bash
cd extras/ui/backend
python app.py
```

Uses shared chDB session (faster queries, no overhead).

## Production Options

### Option 1: Gunicorn with Multiple Workers (Recommended)

**Multi-process, best performance:**
```bash
# Use stateless mode (no shared chDB session)
export WINDLASS_CHDB_SHARED_SESSION=false

gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

**How it works:**
- Each worker process creates a new chDB session per query
- No file locking issues
- Slightly slower per-query (session creation overhead)
- But handles concurrent requests in parallel

**Performance:**
- ~10-20ms overhead per query for session creation
- Worth it for handling 4+ concurrent users

### Option 2: Gunicorn with Gevent (Alternative)

**Single-process with async I/O:**
```bash
# Can use shared session (single process)
export WINDLASS_CHDB_SHARED_SESSION=true

gunicorn -k gevent -w 1 --worker-connections 1000 -b 0.0.0.0:5001 app:app
```

**How it works:**
- One Python process with cooperative multitasking
- Can use shared chDB session (faster queries)
- Handles 1000 concurrent connections via event loop
- But queries are still sequential (not parallel)

**Good for:**
- Many concurrent users with light queries
- SSE connections (event stream)

### Option 3: Upgrade to ClickHouse Server (Best for Scale)

**For serious production use:**
```bash
# Start ClickHouse server
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# Configure Windlass
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost

# Use any gunicorn configuration (no session issues!)
gunicorn -w 8 -b 0.0.0.0:5001 app:app
```

**Benefits:**
- No file locking issues at all
- Truly parallel queries
- Better query optimizer
- Handles massive datasets
- Multiple UIs can connect simultaneously

## Environment Variables

### chDB Configuration

- `WINDLASS_CHDB_SHARED_SESSION` (default: `false`)
  - `true`: Use persistent session (faster but single-worker only)
  - `false`: Create session per query (slower but multi-worker safe)

### ClickHouse Server Configuration

- `WINDLASS_USE_CLICKHOUSE_SERVER` (default: `false`)
- `WINDLASS_CLICKHOUSE_HOST` (default: `localhost`)
- `WINDLASS_CLICKHOUSE_PORT` (default: `9000`)
- `WINDLASS_CLICKHOUSE_DATABASE` (default: `windlass`)

## Performance Comparison

| Mode | Concurrency | Query Speed | Setup |
|------|-------------|-------------|-------|
| Flask dev server | 1 request at a time | Fast (shared session) | Zero config |
| Gunicorn (stateless chDB) | 4+ workers | Medium (+10-20ms overhead) | Just works |
| Gunicorn (gevent) | 1000 connections | Fast (shared session) | Requires gevent |
| ClickHouse server | Unlimited | Fastest | Requires Docker |

## Troubleshooting

### Error: "Invalid or closed connection" with gunicorn

**Cause:** Using shared chDB session with multiple workers.

**Fix:**
```bash
export WINDLASS_CHDB_SHARED_SESSION=false
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

### Error: "Could not acquire lock on database"

**Cause:** Multiple gunicorn workers trying to use shared chDB session.

**Fix:** Same as above - use stateless mode.

### Slow queries with gunicorn

**Cause:** Creating new chDB session per query adds ~10-20ms overhead.

**Options:**
1. Use gevent worker (single process, shared session):
   ```bash
   export WINDLASS_CHDB_SHARED_SESSION=true
   gunicorn -k gevent -w 1 --worker-connections 1000 -b 0.0.0.0:5001 app:app
   ```

2. Upgrade to ClickHouse server (best performance):
   ```bash
   export WINDLASS_USE_CLICKHOUSE_SERVER=true
   gunicorn -w 8 -b 0.0.0.0:5001 app:app
   ```

## Recommended Setup by Use Case

### Solo developer (you right now)
```bash
# Just use Flask dev server
cd extras/ui/backend
python app.py
```

### Team of 2-5 developers
```bash
# Gunicorn with stateless chDB
export WINDLASS_CHDB_SHARED_SESSION=false
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

### Production monitoring dashboard
```bash
# ClickHouse server + multiple workers
export WINDLASS_USE_CLICKHOUSE_SERVER=true
gunicorn -w 8 -b 0.0.0.0:5001 app:app
```

## Example systemd Service

```ini
[Unit]
Description=Windlass Debug UI
After=network.target

[Service]
Type=notify
User=windlass
WorkingDirectory=/opt/windlass/extras/ui/backend
Environment="WINDLASS_ROOT=/opt/windlass"
Environment="WINDLASS_CHDB_SHARED_SESSION=false"
ExecStart=/opt/windlass/venv/bin/gunicorn -w 4 -b 0.0.0.0:5001 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Save as `/etc/systemd/system/windlass-ui.service`, then:
```bash
sudo systemctl enable windlass-ui
sudo systemctl start windlass-ui
```
