# Execution Graph JSON Export 📊

## What You Asked For ✅

> "I want that relationship data from the visualizer but don't want to parse mermaid files or recreate the logic from DB blobs"

**Solution:** Every time a mermaid file is generated, we **also** write structured JSON files with the execution graph. All trace_ids included for easy DB lookups!

---

## How It Works 🔧

### Automatic Generation

When `generate_mermaid()` is called (which happens automatically as cascades run), it now creates **3 files**:

```
graphs/
├── session_123.mmd                # Mermaid diagram (existing)
├── session_123.json               # Execution graph (NEW!)
└── session_123_reactflow.json     # React Flow format (NEW!)
```

**No code changes needed** - happens automatically whenever mermaid is generated!

---

## File Formats 📁

### 1. Execution Graph JSON (`session_123.json`)

General-purpose structured data with trace_ids for DB lookups.

```json
{
  "session_id": "session_123",
  "generated_at": null,

  "nodes": [
    {
      "trace_id": "abc-123-def",
      "node_type": "phase",
      "role": "system",
      "parent_id": "parent-trace-id",
      "depth": 0,

      "phase_name": "generate",
      "cascade_id": "blog_flow",

      "sounding_index": null,
      "is_winner": null,
      "reforge_step": null,

      "content_preview": "Phase: generate...",

      "metadata": {
        "has_soundings": false,
        "handoffs": ["review"]
      }
    },
    {
      "trace_id": "sounding-001",
      "node_type": "sounding_attempt",
      "parent_id": "soundings-parent",
      "sounding_index": 0,
      "is_winner": true,
      "phase_name": "generate",
      "content_preview": "Generated output..."
    }
  ],

  "edges": [
    {
      "source": "parent-trace-id",
      "target": "abc-123-def",
      "edge_type": "parent_child"
    },
    {
      "source": "abc-123-def",
      "target": "next-phase-id",
      "edge_type": "phase_sequence"
    }
  ],

  "phases": [
    {
      "phase": "generate",
      "trace_id": "abc-123-def",
      "output_preview": "Generated content..."
    }
  ],

  "soundings": {
    "generate": [
      {
        "trace_id": "sounding-001",
        "sounding_index": 0,
        "is_winner": true,
        "reforge_step": null
      },
      {
        "trace_id": "sounding-002",
        "sounding_index": 1,
        "is_winner": false,
        "reforge_step": null
      }
    ]
  },

  "summary": {
    "total_nodes": 45,
    "total_edges": 44,
    "total_phases": 3,
    "has_soundings": true,
    "has_sub_cascades": false
  }
}
```

### 2. React Flow JSON (`session_123_reactflow.json`)

Ready to drop into React Flow component. Includes node positions, types, and edge styling.

```json
{
  "nodes": [
    {
      "id": "abc-123-def",
      "type": "phaseNode",
      "position": {"x": 0, "y": 0},
      "data": {
        "label": "generate",
        "trace_id": "abc-123-def",
        "node_type": "phase",
        "role": "system",
        "phase_name": "generate",
        "cascade_id": "blog_flow",
        "sounding_index": null,
        "is_winner": null,
        "metadata": {...}
      },
      "parentNode": "cascade-id",
      "extent": "parent"
    }
  ],

  "edges": [
    {
      "id": "e_parent_child",
      "source": "parent-id",
      "target": "child-id",
      "type": "default",
      "animated": false,
      "style": {"stroke": "#1c7ed6", "strokeWidth": 2},
      "data": {"edge_type": "parent_child"}
    },
    {
      "id": "e_winner",
      "source": "sounding-parent",
      "target": "winner-trace",
      "type": "winner",
      "animated": true,
      "style": {"stroke": "#00ff00", "strokeWidth": 3},
      "data": {"edge_type": "parent_child"}
    }
  ],

  "meta": {
    "session_id": "session_123",
    "total_nodes": 45,
    "total_edges": 44
  }
}
```

---

## React Flow Node Types 🎨

The React Flow JSON uses custom node types you can style:

| Type | Used For | Style Suggestion |
|------|----------|------------------|
| `phaseNode` | Phases | Blue boxes |
| `cascadeNode` | Cascade container | Large gray container |
| `soundingNode` | Sounding attempts | Yellow boxes (winners green) |
| `reforgeNode` | Reforge steps | Orange boxes |
| `toolNode` | Tool executions | Red boxes |
| `default` | Everything else | Default styling |

### React Flow Edge Types

| Type | Used For | Animated | Color |
|------|----------|----------|-------|
| `winner` | Winning soundings | Yes | Green (#00ff00) |
| `sounding` | Sounding attempts | No | Yellow (#fab005, dashed) |
| `phase` | Phase connections | No | Blue (#1c7ed6) |
| `phase_sequence` | Phase order | Yes | Blue (#1c7ed6) |
| `default` | Other | No | Default |

---

## Using the Data 💻

### Option 1: Load Execution Graph

```javascript
// Fetch execution graph
const response = await fetch(`/api/graphs/${sessionId}.json`);
const graph = await response.json();

// Find all soundings
const soundings = graph.nodes.filter(n => n.sounding_index !== null);

// Find winners
const winners = soundings.filter(n => n.is_winner === true);

// Find phases
const phases = graph.nodes.filter(n => n.node_type === 'phase');

// Lookup node in DB using trace_id
const node = graph.nodes.find(n => n.trace_id === 'abc-123');
if (node) {
  // Query echo logs
  const details = await fetch(`/api/echoes/trace/${node.trace_id}`);
}
```

### Option 2: Use React Flow Directly

```jsx
import ReactFlow from 'reactflow';
import 'reactflow/dist/style.css';

function ExecutionGraphView({ sessionId }) {
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });

  useEffect(() => {
    fetch(`/api/graphs/${sessionId}_reactflow.json`)
      .then(res => res.json())
      .then(data => setGraphData(data));
  }, [sessionId]);

  return (
    <ReactFlow
      nodes={graphData.nodes}
      edges={graphData.edges}
      fitView
    />
  );
}
```

### Option 3: Combine with Echo Data

```javascript
// Load execution graph
const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());

// Load echo data for detailed content
const echoes = await fetch(`/api/echoes/jsonl/${sessionId}`).then(r => r.json());

// Enrich nodes with echo content
graph.nodes.forEach(node => {
  const echo = echoes.find(e => e.trace_id === node.trace_id);
  if (echo) {
    node.full_content = echo.content;
    node.tool_calls = echo.tool_calls;
    node.duration_ms = echo.duration_ms;
    node.tokens = {in: echo.tokens_in, out: echo.tokens_out};
  }
});
```

---

## Example: Build a Timeline

```javascript
// Load execution graph
const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());

// Extract phases in order
const timeline = graph.phases.map(p => {
  const node = graph.nodes.find(n => n.trace_id === p.trace_id);

  return {
    phase: p.phase,
    trace_id: p.trace_id,
    has_soundings: graph.soundings[p.phase]?.length > 0,
    winner_index: graph.soundings[p.phase]?.find(s => s.is_winner)?.sounding_index,
    output: p.output_preview
  };
});

// Render timeline UI
timeline.forEach(item => {
  console.log(`Phase: ${item.phase}`);
  if (item.has_soundings) {
    console.log(`  Soundings: Winner #${item.winner_index + 1}`);
  }
  console.log(`  Output: ${item.output}`);
});
```

---

## Example: Visualize Soundings

```javascript
const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());

// Get soundings for a specific phase
const phaseSoundings = graph.soundings['generate'] || [];

// Build soundings view
const soundingsView = phaseSoundings.map(s => ({
  index: s.sounding_index,
  is_winner: s.is_winner,
  trace_id: s.trace_id,

  // Lookup full node data
  node: graph.nodes.find(n => n.trace_id === s.trace_id)
}));

// Render with winner highlighting
soundingsView.forEach(s => {
  const badge = s.is_winner ? '🏆' : '';
  console.log(`${badge} Attempt ${s.index + 1}: ${s.node.content_preview}`);
});
```

---

## Real-Time Updates 📡

Since mermaid files are regenerated as cascades run, the JSON files update too!

```javascript
// Poll for updates (or use SSE)
setInterval(async () => {
  const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());

  // Update UI with latest structure
  updateExecutionGraph(graph);
}, 1000);

// Or use Server-Sent Events
const eventSource = new EventSource('/api/events/stream');
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'phase_complete') {
    // Reload execution graph
    loadExecutionGraph(data.session_id);
  }
};
```

---

## Benefits Summary ✨

### For You
- ✅ **No mermaid parsing** - structured JSON instead
- ✅ **No DB reconstruction** - visualizer logic already done
- ✅ **Trace IDs included** - easy DB lookups
- ✅ **Real-time updates** - JSON updates with mermaid
- ✅ **Two formats** - general + React Flow ready

### For Your UI
- ✅ **Drop-in React Flow** - ready to render
- ✅ **Flexible queries** - nodes, edges, phases, soundings
- ✅ **Rich metadata** - sounding winners, reforge steps
- ✅ **Parent-child trees** - full relationship graph
- ✅ **Custom node types** - phase, cascade, sounding, tool

### For Debugging
- ✅ **Human-readable JSON** - can inspect with jq/less
- ✅ **Content previews** - truncated for quick scanning
- ✅ **Summary stats** - totals at a glance
- ✅ **Complete graph** - all nodes and edges

---

## File Locations 📂

```
graphs/
├── session_001.mmd                 # Mermaid (existing)
├── session_001.json                # Execution graph (NEW!)
├── session_001_reactflow.json      # React Flow (NEW!)
│
├── session_002.mmd
├── session_002.json
└── session_002_reactflow.json
```

All generated automatically whenever a mermaid file is written!

---

## Quick Reference 📋

### Load Execution Graph
```javascript
const graph = await fetch(`/api/graphs/${sessionId}.json`).then(r => r.json());
```

### Find Nodes by Type
```javascript
const phases = graph.nodes.filter(n => n.node_type === 'phase');
const soundings = graph.nodes.filter(n => n.sounding_index !== null);
const winners = soundings.filter(n => n.is_winner);
```

### Lookup by Trace ID
```javascript
const node = graph.nodes.find(n => n.trace_id === traceId);
```

### Get Phase Relationships
```javascript
const phaseEdges = graph.edges.filter(e => e.edge_type === 'phase_sequence');
```

### Load in React Flow
```jsx
<ReactFlow
  nodes={reactFlowData.nodes}
  edges={reactFlowData.edges}
/>
```

---

## Next Steps 🎯

1. **Test it** - Run any cascade and check `graphs/` directory
2. **Load the JSON** - Try fetching and parsing
3. **Build a visualization** - Use React Flow or custom D3
4. **Combine with echoes** - Enrich graph with full echo data

The execution structure is now available in easy-to-use JSON format, with all the relationship logic already figured out by the visualizer! 🎉
