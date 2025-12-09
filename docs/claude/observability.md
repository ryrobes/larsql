# Observability Reference

This document covers Windlass's logging, events, visualization, and debug UI.

## Unified Logging System

All logging goes through a unified mega-table system (`unified_logs.py`) with automatic scaling from embedded to distributed.

### Modes

| Mode | Backend | Setup | Use Case |
|------|---------|-------|----------|
| **Development** | chDB (embedded) | Zero config | Local dev, small scale |
| **Production** | ClickHouse server | 2 env vars | Scale, distributed |

### Switching to ClickHouse Server

```bash
# Start ClickHouse
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# Enable (database and table auto-created!)
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost

# Run normally
windlass examples/simple_flow.json --input '{"data": "test"}'
```

See `CLICKHOUSE_SETUP.md` for complete guide.

### Logging Features

- **Buffered Writes**: 100 messages OR 10 seconds (whichever first)
- **Non-Blocking Cost Tracking**: Background worker fetches costs after ~3 seconds
- **Automatic Setup**: Database/table created on first run (server mode)
- **Backward Compatibility**: Old `logs.py` routes to unified system
- **Mermaid Graphs**: Real-time flowchart generation
- **Trace Hierarchy**: Parent-child relationships for nested cascades

### Unified Log Schema (34+ fields)

| Category | Fields |
|----------|--------|
| **Core IDs** | `timestamp`, `timestamp_iso`, `session_id`, `trace_id`, `parent_id`, `parent_session_id`, `parent_message_id` |
| **Classification** | `node_type`, `role`, `depth` |
| **Execution Context** | `sounding_index`, `is_winner`, `reforge_step`, `attempt_number`, `turn_number` |
| **Cascade Context** | `cascade_id`, `cascade_file`, `cascade_json`, `phase_name`, `phase_json` |
| **LLM Provider** | `model`, `request_id`, `provider` |
| **Performance** | `duration_ms`, `tokens_in`, `tokens_out`, `total_tokens`, `cost` |
| **Content (JSON)** | `content_json`, `full_request_json`, `full_response_json`, `tool_calls_json` |
| **Images** | `images_json`, `has_images`, `has_base64` |
| **Metadata** | `metadata_json` |

### Query Helpers

```python
from windlass.unified_logs import query_unified, get_session_messages, get_cascade_costs

# Query with filter
df = query_unified("session_id = 'session_123'")

# Get all messages for session
messages = get_session_messages("session_123")

# Get cost breakdown
costs = get_cascade_costs("blog_flow")

# Analyze soundings
from windlass.unified_logs import get_soundings_analysis
soundings = get_soundings_analysis("session_123", "generate")

# Advanced JSON queries (server mode)
df = query_unified("""
    JSONExtractString(tool_calls_json, '0', 'tool') = 'route_to'
    AND cost > 0.01
""")
```

---

## Real-Time Event System

Built-in event bus for real-time cascade updates via SSE.

### Event Bus

```python
from windlass.events import get_event_bus, Event

# Publish events
bus = get_event_bus()
bus.publish(Event(
    type="phase_complete",
    session_id="session_123",
    timestamp=datetime.now().isoformat(),
    data={"phase_name": "generate", "result": {...}}
))

# Subscribe to events
queue = bus.subscribe()
while True:
    event = queue.get(timeout=30)
    print(event.to_dict())
```

### Event Publishing Hooks

CLI automatically enables event hooks:

```python
from windlass.event_hooks import EventPublishingHooks

hooks = EventPublishingHooks()
run_cascade(config_path, input_data, session_id, hooks=hooks)
```

### Lifecycle Events

| Event | Description |
|-------|-------------|
| `cascade_start` | Cascade begins execution |
| `cascade_complete` | Cascade finishes successfully |
| `cascade_error` | Cascade encounters error |
| `phase_start` | Phase begins |
| `phase_complete` | Phase completes |
| `turn_start` | Agent turn starts |
| `tool_call` | Tool invoked |
| `tool_result` | Tool returns result |

### SSE Integration Example

**Backend (Flask):**
```python
from windlass.events import get_event_bus
from flask import Response, stream_with_context
import json

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()
        while True:
            event = queue.get(timeout=30)
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    return Response(stream_with_context(generate()), mimetype='text/event-stream')
```

**Frontend (React):**
```javascript
useEffect(() => {
    const eventSource = new EventSource('/api/events/stream');
    eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === 'phase_complete') {
            refreshUI(event.session_id);
        }
    };
    return () => eventSource.close();
}, []);
```

---

## Hooks System

`WindlassRunner` accepts a `hooks` parameter for injecting custom logic.

### Lifecycle Hooks

| Hook | When Called |
|------|-------------|
| `on_cascade_start` | Cascade execution begins |
| `on_cascade_complete` | Cascade completes successfully |
| `on_cascade_error` | Cascade fails |
| `on_phase_start` | Phase begins |
| `on_phase_complete` | Phase completes |
| `on_turn_start` | Turn begins |
| `on_tool_call` | Tool invoked |
| `on_tool_result` | Tool returns |

Hooks can return `HookAction.CONTINUE`, `HookAction.PAUSE`, or `HookAction.INJECT`.

### Example Usage

```python
from windlass import run_cascade
from windlass.event_hooks import EventPublishingHooks

hooks = EventPublishingHooks()
result = run_cascade("cascade.json", {"input": "data"}, hooks=hooks)

# Subscribe in another thread
from windlass.events import get_event_bus
bus = get_event_bus()
queue = bus.subscribe()

while True:
    event = queue.get()
    print(f"{event.type}: {event.data}")
```

---

## Execution Tree API

For complex visualization (soundings, reforges, parallel execution).

### Build Tree

```python
from windlass.visualizer import ExecutionTreeBuilder

builder = ExecutionTreeBuilder(log_dir="/path/to/logs")
tree = builder.build_tree(session_id)

# Returns:
{
    'session_id': 'session_123',
    'phases': [
        {
            'name': 'generate',
            'type': 'soundings',
            'soundings': [
                {'index': 0, 'is_winner': False, 'events': [...]},
                {'index': 1, 'is_winner': True, 'events': [...]},
            ],
            'winner_index': 1
        },
        {
            'name': 'optimize',
            'type': 'reforge',
            'reforge_steps': [
                {'step': 0, 'soundings': [...], 'winner_index': 1},
            ]
        }
    ]
}
```

### React Flow Integration

```python
from windlass.visualizer import build_react_flow_nodes

graph = build_react_flow_nodes(tree)

# Returns nodes and edges for React Flow
{
    'nodes': [
        {'id': 'phase_0', 'type': 'phaseNode', 'position': {'x': 0, 'y': 0}, ...},
        {'id': 'phase_1_sounding_0', 'type': 'soundingNode', ...}
    ],
    'edges': [
        {'source': 'phase_0', 'target': 'phase_1_group', 'animated': True},
        {'source': 'phase_1_sounding_1', 'target': 'phase_2', 'style': {'stroke': '#00ff00'}}
    ]
}
```

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for patterns.

---

## Debug UI

Development debug UI for real-time cascade monitoring.

### Location

`extras/debug_ui/`

### Features

- Real-time SSE updates (no polling)
- Cascade list with status (running/completed/failed)
- Interactive Mermaid graph viewer (zoomable/pannable)
- Live event logs
- Run cascades from UI with input parameters
- Execution tree API for complex visualization

### Quick Start

```bash
# Terminal 1: Backend
cd extras/debug_ui
./start_backend.sh

# Terminal 2: Frontend
cd extras/debug_ui/frontend
npm start

# Open http://localhost:3000
```

### Backend Configuration

```bash
export WINDLASS_LOG_DIR=/path/to/logs
export WINDLASS_GRAPH_DIR=/path/to/graphs
export WINDLASS_STATE_DIR=/path/to/states
export WINDLASS_IMAGE_DIR=/path/to/images
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/cascades` | List all cascade sessions |
| `GET /api/logs/<session_id>` | Get logs for session |
| `GET /api/graph/<session_id>` | Get Mermaid graph |
| `GET /api/execution-tree/<session_id>` | Get execution tree (JSON) |
| `GET /api/execution-tree/<session_id>?format=react-flow` | React Flow format |
| `GET /api/events/stream` | SSE event stream |
| `POST /api/run-cascade` | Execute cascade with inputs |

### Event Stream Format

```javascript
{
  type: 'phase_complete',
  session_id: 'session_123',
  timestamp: '2025-12-02T04:00:00',
  data: {
    phase_name: 'generate',
    result: {...}
  }
}
```

### Tech Stack

- Backend: Flask + chDB/ClickHouse + SSE
- Frontend: React + Mermaid.js
- Real-time: EventSource API

---

## Multi-Modal Vision Protocol

Images are first-class citizens with automatic persistence.

### Tool Image Protocol

If a tool returns `{"content": "...", "images": ["/path/to/file.png"]}`:

1. Runner detects `images` key
2. Reads file and encodes to Base64
3. Auto-saves to `images/{session_id}/{phase_name}/image_{N}.{ext}`
4. Injects as multi-modal user message
5. Agent sees image in next turn

### Universal Image Auto-Save

Images from ANY source are automatically saved:
- Tool outputs (via `{"images": [...]}` protocol)
- Manual injection (base64 data URLs)
- Feedback loops (validation with visual context)
- Any message format

### Directory Structure

```
images/
  {session_id}/
    {phase_name}/
      image_0.png
      image_1.png
  {session_id}_reforge1_0/
    {phase_name}/
      image_0.png
```

### Reforge Image Flow

Images automatically flow through refinement:
1. Winner's context includes images
2. Images extracted and re-encoded
3. Refinement context includes honing prompt + images
4. Each iteration can see and analyze previous images
5. All images saved with session namespacing
