# Quick Start: Execution Graph JSON ⚡

## What You Asked For ✅

> "When building a UI, I want the relationship data from visualizer.py but don't want to parse mermaid files or recreate the logic from DB blobs"

**Solution:** Mermaid generation now **automatically** writes 2 companion JSON files with full execution structure!

---

## How It Works 🔧

Every time a mermaid file is generated (automatically as cascades run), you get **3 files**:

```
graphs/
├── session_123.mmd                # Mermaid diagram (existing)
├── session_123.json               # Execution graph (NEW!)
└── session_123_reactflow.json     # React Flow format (NEW!)
```

**No code changes needed** - happens automatically!

---

## Test It Right Now 🚀

```bash
cd /home/ryanr/repos/windlass
python test_execution_graph.py
```

**This will:**
1. Run a cascade
2. Show generated JSON files
3. Display structure (nodes, edges, phases)
4. Show example queries

---

## File Contents 📊

### Execution Graph (`session_123.json`)

```json
{
  "nodes": [
    {
      "trace_id": "abc-123",          // DB lookup key!
      "node_type": "phase",
      "parent_id": "parent-trace",
      "phase_name": "generate",
      "sounding_index": null,
      "is_winner": null,
      "metadata": {...}
    }
  ],

  "edges": [
    {
      "source": "trace-1",
      "target": "trace-2",
      "edge_type": "parent_child"
    }
  ],

  "phases": [...],        // Phase order
  "soundings": {...},     // Soundings by phase
  "summary": {...}        // Stats
}
```

### React Flow (`session_123_reactflow.json`)

```json
{
  "nodes": [
    {
      "id": "trace-id",
      "type": "phaseNode",        // Custom node types!
      "position": {"x": 0, "y": 0},
      "data": {
        "trace_id": "...",        // All metadata
        "node_type": "...",
        "phase_name": "...",
        ...
      }
    }
  ],

  "edges": [
    {
      "source": "trace-1",
      "target": "trace-2",
      "type": "winner",           // Pre-styled!
      "animated": true,
      "style": {"stroke": "#00ff00"}
    }
  ]
}
```

---

## Using in Your UI 💻

### Load Graph

```javascript
const graph = await fetch(`/api/graphs/${sessionId}.json`)
  .then(r => r.json());
```

### Query Nodes

```javascript
// Find phases
const phases = graph.nodes.filter(n => n.node_type === 'phase');

// Find soundings
const soundings = graph.nodes.filter(n => n.sounding_index !== null);

// Find winners
const winners = soundings.filter(n => n.is_winner);

// Lookup by trace_id
const node = graph.nodes.find(n => n.trace_id === traceId);
```

### Use with Echo Data

```javascript
// Get node from graph
const node = graph.nodes.find(n => n.trace_id === 'abc-123');

// Query echo data with trace_id
const echo = await fetch(`/api/echoes/trace/${node.trace_id}`)
  .then(r => r.json());

// Combine
const enriched = {
  ...node,
  full_content: echo.content,
  duration_ms: echo.duration_ms,
  tokens: {in: echo.tokens_in, out: echo.tokens_out}
};
```

### React Flow

```jsx
import ReactFlow from 'reactflow';

function Graph({ sessionId }) {
  const [data, setData] = useState({ nodes: [], edges: [] });

  useEffect(() => {
    fetch(`/api/graphs/${sessionId}_reactflow.json`)
      .then(r => r.json())
      .then(setData);
  }, [sessionId]);

  return <ReactFlow nodes={data.nodes} edges={data.edges} />;
}
```

---

## Real-Time Updates 📡

Graph JSON updates as mermaid regenerates:

```javascript
// Poll for updates
setInterval(() => {
  loadExecutionGraph(sessionId);
}, 1000);

// Or use SSE
const es = new EventSource('/api/events/stream');
es.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.type === 'phase_complete') {
    loadExecutionGraph(event.session_id);
  }
};
```

---

## Benefits ✨

### No More...
- ❌ Parsing mermaid syntax
- ❌ Reconstructing relationships from DB
- ❌ Duplicating visualizer logic

### Instead...
- ✅ **Load JSON** - structured data
- ✅ **Trace IDs** - easy DB lookups
- ✅ **Pre-computed** - relationships figured out
- ✅ **Two formats** - general + React Flow
- ✅ **Auto-updates** - real-time as cascade runs

---

## File Locations 📂

```
graphs/
├── session_001.mmd                 # Mermaid
├── session_001.json                # Graph (NEW!)
├── session_001_reactflow.json      # React Flow (NEW!)
│
├── session_002.mmd
├── session_002.json                # Automatically generated!
└── session_002_reactflow.json      # Automatically generated!
```

---

## Quick Reference 📋

**Load graph:**
```javascript
const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());
```

**Find phases:**
```javascript
const phases = graph.nodes.filter(n => n.node_type === 'phase');
```

**Lookup trace_id:**
```javascript
const node = graph.nodes.find(n => n.trace_id === traceId);
```

**Use in React Flow:**
```jsx
<ReactFlow nodes={rfData.nodes} edges={rfData.edges} />
```

---

## Next Steps 🎯

1. **Run test:** `python test_execution_graph.py`
2. **Check files:** `ls -la graphs/`
3. **Load JSON:** Try queries from examples above
4. **Build UI:** Use React Flow or custom viz

All the relationship data you need, with trace_ids for easy DB lookups! 🎉

See `EXECUTION_GRAPH_JSON.md` for complete documentation.
