# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RVBBIT Studio is a React/Flask web UI for the RVBBIT agent framework. It provides real-time visualization of cascade executions, including candidates (Tree of Thought), reforge iterations, and cost tracking.

**Tech Stack:**
- **Backend**: Flask + DuckDB (Python 3.x)
- **Frontend**: React 18 + Mermaid.js
- **Data**: ClickHouse + DuckDB for session-scoped temp tables
- **Real-time**: Smart polling with ClickHouse

## Development Commands

### Quick Start

```bash
# Using CLI (recommended)
rvbbit serve studio --dev    # Runs backend on port 5050

# Or manually:
# Terminal 1 - Backend
cd backend && python app.py   # Runs on port 5050

# Terminal 2 - Frontend
cd frontend && npm start      # Runs on port 5550 (proxies to 5050)

# Production mode (serves built frontend)
cd frontend && npm run build
rvbbit serve studio           # Runs with Gunicorn + static files
```

### Frontend

```bash
cd frontend
npm install       # Install dependencies (first time)
npm start         # Dev server with hot reload
npm run build     # Production build
npm test          # Run tests
```

### Backend

```bash
cd backend
pip install -r requirements.txt   # Install dependencies
python app.py                     # Start Flask server
```

### Environment Variables

```bash
# Point to RVBBIT data (optional - defaults to repo root)
export RVBBIT_ROOT=/path/to/rvbbit
export RVBBIT_DATA_DIR=$RVBBIT_ROOT/data      # Parquet logs
export RVBBIT_GRAPH_DIR=$RVBBIT_ROOT/graphs   # Mermaid graphs
export RVBBIT_IMAGE_DIR=$RVBBIT_ROOT/images   # Generated images

# SQL debugging
export RVBBIT_SQL_VERBOSE=true   # Log all SQL queries
```

## Architecture

### Data Flow

```
RVBBIT Cascade Execution
    ↓
SSE Events → LiveStore (in-memory DuckDB)  ← Real-time UI updates
    ↓
Parquet Files → DuckDB Cache → Flask API → React Frontend
```

### Backend (`backend/`)

| File | Purpose |
|------|---------|
| `app.py` | Flask server, API endpoints, SSE streaming, DuckDB queries |
| `live_store.py` | In-memory DuckDB for real-time session tracking during execution |
| `message_flow_api.py` | API for message flow visualization (candidates, reforge) |
| `execution_tree.py` | Build hierarchical execution trees for visualization |

**Key API Endpoints:**
- `GET /api/cascade-definitions` - All cascades with aggregated metrics
- `GET /api/cascade-instances/:id` - All runs of a specific cascade
- `GET /api/session/:session_id` - Detailed session data
- `GET /api/message-flow/:session_id` - Full message history for visualization
- `GET /api/events/stream` - SSE for real-time updates
- `POST /api/run-cascade` - Execute a cascade from the UI

### Frontend (`frontend/src/`)

| Component | Purpose |
|-----------|---------|
| `App.js` | Main router, SSE connection, global state |
| `CascadesView.js` | Grid of cascade definitions with metrics |
| `InstancesView.js` | List of runs for a selected cascade |
| `DetailView.js` | Full session detail with Mermaid graph |
| `MessageFlowView.js` | Message-level visualization of LLM interactions |
| `SoundingsExplorer.js` | Visual comparison of sounding attempts |
| `MermaidViewer.js` | Interactive Mermaid graph rendering |
| `LiveDebugLog.js` | Real-time event log during execution |

### Views Navigation

```
CascadesView (grid) → InstancesView (list) → DetailView (session)
                                          → MessageFlowView (messages)
                                          → SoundingsExplorer (compare)
```

## Design System

**Theme:** Pure black (#0a0a0a) with bright pastel accents

| Color | Hex | Usage |
|-------|-----|-------|
| Background | `#0a0a0a` | Page background |
| Cards | `#121212` | Component backgrounds |
| Purple | `#a78bfa` | Accents, gradients |
| Blue | `#60a5fa` | Stats, headers |
| Green | `#34d399` | Success, cost display |
| Yellow | `#fbbf24` | Running state, candidates |
| Red | `#f87171` | Errors |

**Cell Block Status Colors:**
- Green border: Completed
- Yellow border + pulse: Running
- Red border: Error
- Gray border: Pending

## Key Implementation Details

### Smart Polling (Real-time Updates)

The frontend uses smart/append polling instead of SSE. ClickHouse is fast enough to poll with denormalized tables and indexed keys. This approach is:
- More scalable with multiple backend workers
- Simpler to reason about (stateless requests)
- All state lives in the database

### ClickHouse Backend

With ClickHouse, writes are immediate - no buffering lag. The only delay is cost data from OpenRouter API (~5s).

### Hash-based Routing

Navigation uses URL hash for bookmarkable views:
- `/#/` → CascadesView
- `/#/cascade_id` → InstancesView
- `/#/cascade_id/session_id` → DetailView
- `/#/message_flow` → MessageFlowView

## Common Development Tasks

### Adding a New API Endpoint

1. Add route in `backend/app.py` or create new Blueprint
2. Query data using `get_db_connection()` for DuckDB access
3. Use `sanitize_for_json()` for NaN/Infinity handling
4. Return with `jsonify()`

### Adding a New Component

1. Create `ComponentName.js` and `ComponentName.css` in `frontend/src/components/`
2. Import and add to routing in `App.js`
3. Follow existing component patterns for SSE integration

### Debugging SQL Queries

```bash
# Enable verbose SQL logging
export RVBBIT_SQL_VERBOSE=true
python app.py
```

All queries are logged with timing information.
