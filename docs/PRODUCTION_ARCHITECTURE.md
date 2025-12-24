# Windlass Production Architecture Assessment

## Executive Summary

Windlass is architecturally sound for production deployment using a **stateless worker pattern** with **ClickHouse as the central coordinator**. The design avoids the complexity of master/worker coordination, task queues, and distributed state management by treating each cascade as a self-contained execution that runs start-to-finish on a single worker.

**Overall Readiness: 8/10** - Solid foundation with a few targeted fixes needed.

---

## Architecture Overview

```
                    ┌─────────────┐
                    │   Load      │
                    │  Balancer   │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Worker A │    │ Worker B │    │ Worker C │
    │ Flask+UI │    │ Flask+UI │    │ Flask+UI │
    │          │    │          │    │          │
    │ Cascade1 │    │ Cascade3 │    │ Cascade5 │
    │ Cascade2 │    │ Cascade4 │    │ ...      │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
         └───────────────┴───────────────┘
                         ▼
              ┌─────────────────────┐
              │     ClickHouse      │
              │   (shared state)    │
              └─────────────────────┘
```

### Core Principles

1. **No Master Node**: Load balancer distributes requests; no central coordinator
2. **Database as Server**: ClickHouse is the single source of truth for all state
3. **Stateless Workers**: Each worker is identical and interchangeable
4. **Self-Contained Cascades**: A cascade runs start-to-finish on one worker (no handoff)
5. **Horizontal Scaling**: Add workers behind load balancer as needed

---

## What Works Well

### ClickHouse as Central Coordinator ✅

The strongest part of the architecture:

| Data | Storage | Access |
|------|---------|--------|
| Execution logs | `unified_logs` table | Any worker can query |
| Session state | `session_states` table | Heartbeat-based coordination |
| Checkpoints | `checkpoints` table | Resume from any worker |
| Cost tracking | Async updates | Centralized analytics |

**Key Files:**
- `windlass/unified_logs.py` - Immediate writes to ClickHouse
- `windlass/session_state.py` - Session coordination via DB
- `windlass/checkpoints.py` - Checkpoint persistence

### Stateless Worker Pattern ✅

- `WindlassRunner` reads cascade config and executes
- No persistent state required between requests
- API keys from environment variables
- `WINDLASS_ROOT` centralizes all paths
- Session IDs flow explicitly through execution

### In-Memory Echo (Per-Cascade) ✅

The `Echo` object storing session state is intentionally in-memory:

```python
# windlass/echo.py
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Echo] = {}
```

**This is correct because:**
- Echo lives for cascade execution lifetime only
- No cross-worker handoff needed (cascade runs on one worker)
- Historical state persists to ClickHouse for queries
- Memory is freed when cascade completes

### Browser Sessions (Per-Cascade) ✅

Rabbitize browser sessions are worker-local:

```python
# windlass/browser_manager.py
class BrowserSessionManager:
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
```

**This is correct because:**
- Browser spawns for cascade, runs, exits
- No need for distributed browser pool
- Each worker manages its own browser lifecycle
- Subprocess cleanup happens on cascade completion

### Session-Scoped DuckDB ✅

Temp tables for Data Cascades are worker-local:

```python
# windlass/sql_tools/session_db.py
db_path = os.path.join(session_db_dir, f"{session_id}.duckdb")
```

**This is correct because:**
- Temp tables (`_phase_name`) scoped to single cascade
- Cascade runs on one worker, so local file is fine
- Cleanup on cascade completion

### Dashboard Backend IS a Worker ✅

The existing Flask backend already implements the worker pattern:

```python
# dashboard/backend/app.py
@app.route('/api/run-cascade', methods=['POST'])
def run_cascade():
    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()
    return jsonify({'success': True, 'session_id': session_id})
```

- REST API for cascade submission
- Multiple concurrent cascades via threading
- All writes to shared ClickHouse

---

## Current Issues (Requires Work)

### 1. SSE EventBus is In-Memory 🔴 **BLOCKING**

**File:** `windlass/events.py`

```python
class EventBus:
    def __init__(self):
        self._subscribers: List[Queue] = []  # IN-MEMORY ONLY
```

**Problem:** SSE real-time updates (`/api/events/stream`) only work if user's SSE connection hits the same worker running the cascade.

**Impact:** Load balancer breaks real-time UI updates.

**Status:** In progress - replacing with smart polling.

**Fix Options:**
1. **Smart polling** (in progress) - UI polls ClickHouse directly
2. **Sticky sessions** - Load balancer routes user to same worker
3. **Redis Pub/Sub** - Shared event bus (adds infrastructure)

### 2. Audible Signals are In-Memory 🟡 **MEDIUM**

**File:** `dashboard/backend/checkpoint_api.py`

```python
_audible_signals = {}  # session_id -> signal state
_audible_lock = threading.Lock()
```

**Problem:** Real-time feedback injection for browser automation is instance-local.

**Impact:** If cascade runs on Worker A and signal sent to Worker B, signal not received.

**Fix Options:**
1. Store in ClickHouse (simple, slight latency)
2. Store in Redis (faster, adds infrastructure)
3. Sticky sessions (route signals to cascade's worker)

### 3. Single Query Lock Bottleneck 🟡 **MEDIUM**

**File:** `windlass/db_adapter.py`

```python
def query(self, query: str):
    with self._query_lock:  # ALL queries serialize here
        result = self.client.query(query)
```

**Problem:** All ClickHouse queries on a worker go through one lock.

**Impact:** Under high concurrency (many cascades per worker), queries serialize.

**Mitigation:** Likely not a real bottleneck - ClickHouse INSERTs are fast, cascades spend 95%+ time waiting on LLM APIs.

**Fix (if needed):** Connection pooling instead of single connection.

### 4. No Automatic Session Cleanup 🟡 **LOW**

**Problem:** Session artifacts accumulate without cleanup:
- DuckDB files in `session_dbs/`
- Images in `images/`
- Audio in `audio/`
- Browser artifacts in `rabbitize-runs/`

**Fix:** Add TTL-based cleanup job or cleanup on cascade completion.

### 5. Orphan Recovery is Manual 🟡 **LOW**

**File:** `windlass/session_state.py`

Heartbeat-based zombie detection exists (60s lease), but recovery requires manual intervention.

**Current State:**
- Sessions without heartbeat marked as `ORPHANED`
- Checkpoints exist for resume
- No automatic pickup by other workers

**Fix (if needed):** Worker polls for orphaned sessions with checkpoints, resumes automatically.

---

## Resource Considerations

### Cascades Per Worker

Each concurrent cascade uses:

| Resource | Usage | Notes |
|----------|-------|-------|
| Memory | ~50-100MB | Echo, DuckDB conn, message history |
| CPU | Minimal | Mostly waiting on LLM API |
| Threads | 2 | Main + heartbeat |
| Browser | 1 subprocess | Only if rabbitize used |
| DB connections | Shared | Single ClickHouse connection per worker |

**Practical Limit:** 20-50 concurrent cascades per worker before memory pressure. LLM API rate limits hit first.

### Bottleneck Analysis

```
LLM API call:     ~1-30 seconds (dominant)
ClickHouse write: ~1-10ms
DuckDB query:     ~1-100ms
Browser action:   ~100ms-5s
```

The `_query_lock` is not a real bottleneck because:
1. ClickHouse writes are fast
2. 95%+ of cascade time is LLM API waiting
3. Lock contention only matters if many cascades write simultaneously

---

## Deployment Strategy

### Quick Start with Docker Compose

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your OPENROUTER_API_KEY

# 2. Start (Windlass + ClickHouse)
docker compose up

# 3. Access UI at http://localhost:5001
```

### Deployment Tiers

| Tier | Command | What You Get |
|------|---------|--------------|
| **Default** | `docker compose up` | Windlass + ClickHouse |
| **Full** | `docker compose --profile full up` | + Elasticsearch + Kibana |
| **BYOI** | `WINDLASS_CLICKHOUSE_HOST=xxx docker compose up windlass` | Just Windlass (you provide ClickHouse) |
| **Scale** | `docker compose up --scale windlass=3` | Multiple workers |

### Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: Python + Node.js + Rabbitize + Frontend |
| `docker-compose.yml` | Tiered deployment with profiles |
| `.env.example` | Environment configuration template |
| `.dockerignore` | Build optimization |

### Environment Variables

See `.env.example` for full list. Key variables:

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-xxx

# ClickHouse (defaults work for bundled instance)
WINDLASS_CLICKHOUSE_HOST=clickhouse  # or your-clickhouse.example.com
WINDLASS_CLICKHOUSE_PORT=9000

# Optional
WINDLASS_DEFAULT_MODEL=google/gemini-2.5-flash-lite
HF_TOKEN=hf_xxx                      # HuggingFace Harbor
ELEVENLABS_API_KEY=xxx               # TTS
```

### Kubernetes Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: windlass
spec:
  replicas: 3
  selector:
    matchLabels:
      app: windlass
  template:
    spec:
      containers:
      - name: windlass
        image: windlass:latest
        ports:
        - containerPort: 5001
        env:
        - name: OPENROUTER_API_KEY
          valueFrom:
            secretKeyRef:
              name: windlass-secrets
              key: openrouter-api-key
        - name: WINDLASS_CLICKHOUSE_HOST
          value: "clickhouse.database.svc.cluster.local"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
---
apiVersion: v1
kind: Service
metadata:
  name: windlass
spec:
  selector:
    app: windlass
  ports:
  - port: 80
    targetPort: 5001
```

---

## When You'd Need More Infrastructure

### Task Queue (Celery/RQ)

**Not needed now.** Would need if:
- Scheduled/cron cascades (alternative: ClickHouse table + polling)
- Complex retry with backoff (alternative: client retry)
- Work stealing on worker death (alternative: checkpoint resume)
- Cascade dependencies (alternative: client orchestration)

### Message Broker (Redis/Kafka)

**Not needed now.** Would need if:
- Real-time cross-worker events (alternative: polling)
- Pub/sub for multiple UI subscribers (alternative: each polls ClickHouse)
- High-frequency event streaming (not current use case)

### Distributed Cache (Redis/Memcached)

**Not needed now.** Would need if:
- Session state shared across workers (not needed - cascades don't migrate)
- High-frequency reads of same data (ClickHouse handles this)
- Rate limiting coordination (API provider handles this)

### Shared Filesystem (NFS/EFS)

**Maybe needed.** Consider if:
- Images/audio need to be served from any worker
- Large file artifacts need persistence beyond cascade lifetime

**Alternative:** Store artifacts in S3/GCS, return URLs instead of paths.

---

## Summary Scorecard

| Area | Score | Status | Notes |
|------|-------|--------|-------|
| ClickHouse as hub | 9/10 | ✅ Ready | Excellent design choice |
| Stateless workers | 9/10 | ✅ Ready | Self-contained cascades |
| Concurrent cascades | 8/10 | ✅ Ready | Threading works, query lock is fine |
| Real-time UI | 6/10 | 🔄 In Progress | SSE → polling migration |
| Audible signals | 6/10 | 🟡 Needs Fix | Instance-local storage |
| Session cleanup | 5/10 | 🟡 Needs Fix | No automatic cleanup |
| Orphan recovery | 5/10 | 🟡 Optional | Manual but functional |
| Configuration | 9/10 | ✅ Ready | Clean env-var based |
| Docker readiness | 9/10 | ✅ Ready | Dockerfile + docker-compose.yml |

---

## Recommended Next Steps

### Phase 1: Production-Ready (Current Sprint)

1. **Complete SSE → Polling Migration**
   - Remove `/api/events/stream` dependency
   - UI polls ClickHouse via existing endpoints

2. **Fix Audible Signals**
   - Move `_audible_signals` to ClickHouse table
   - Simple: `INSERT/SELECT` with session_id key

3. **Add Health Endpoint**
   - Add `/api/health` endpoint to Flask app
   - Check ClickHouse connectivity
   - Return worker status for load balancer probes

### Phase 2: Hardening (Next Sprint)

4. **Session Cleanup**
   - Cleanup job or cascade-completion hook
   - Remove old DuckDB files, images, audio

5. **Health Endpoints**
   - `/health` for load balancer
   - `/ready` for Kubernetes probes

6. **Metrics**
   - Concurrent cascade count
   - ClickHouse query latency
   - Memory usage per worker

### Phase 3: Scale (When Needed)

7. **Connection Pooling** (if query lock becomes bottleneck)
8. **Scheduled Cascades** (ClickHouse table + polling)
9. **S3 Artifacts** (if shared filesystem needed)

---

## Conclusion

The "database is the server" architecture is the right choice. By avoiding centralized coordination, task queues, and distributed state, Windlass achieves:

- **Simplicity**: Fewer moving parts, easier to debug
- **Resilience**: No single point of failure (except ClickHouse, which can be clustered)
- **Scalability**: Add workers behind load balancer
- **Cost**: No Redis/Kafka/etc. infrastructure

The remaining work is tactical (SSE removal, audible signals, Docker image) rather than architectural. The foundation is solid.
