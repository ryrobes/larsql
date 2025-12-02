# Windlass Debug UI

Real-time development UI for monitoring Windlass cascade execution with SSE event streaming, execution tree visualization, and React Flow integration.

## Features

✅ **Real-time SSE Updates** - Server-Sent Events, no polling required  
✅ **Cascade List** - View all sessions with status indicators  
✅ **Interactive Mermaid Graphs** - Zoomable/pannable with soundings & reforge support  
✅ **Live Event Logs** - Stream all lifecycle events  
✅ **Run Cascades** - Execute from UI with input parameters  
✅ **Execution Tree API** - Structured data for complex visualization  
✅ **React Flow Integration** - Advanced graph rendering support  

## Quick Start

```bash
# Terminal 1: Start backend
cd /home/ryanr/repos/windlass/extras/debug_ui
./start_backend.sh

# Terminal 2: Start frontend  
cd /home/ryanr/repos/windlass/extras/debug_ui/frontend
npm start

# Open http://localhost:3000
```

## API Endpoints

```
GET  /api/cascades                              # List all sessions
GET  /api/logs/<session_id>                     # Event logs
GET  /api/graph/<session_id>                    # Mermaid graph
GET  /api/execution-tree/<session_id>           # Hierarchical tree (JSON)
GET  /api/execution-tree/<session_id>?format=react-flow  # React Flow format
GET  /api/events/stream                         # SSE event stream
POST /api/run-cascade                           # Execute cascade
```

## Documentation

- **CLAUDE.md** - Complete Windlass framework documentation with SSE/hooks
- **VISUALIZATION_GUIDE.md** - React Flow patterns for soundings/reforges/parallel execution
- **backend/execution_tree.py** - Execution tree builder for complex visualizations

## SSE Event Types

- `cascade_start`, `cascade_complete`, `cascade_error`
- `phase_start`, `phase_complete`  
- `turn_start`
- `tool_call`, `tool_result`

See CLAUDE.md section 5 for integration examples.
