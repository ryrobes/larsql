# Windlass Execution Visualization Guide

## Problem

Complex execution patterns don't map to linear flowcharts:

1. **Soundings** - Multiple parallel attempts, only winner continues
2. **Reforges** - Iterative refinement of winner through N steps
3. **Retry loops** - Same phase executed multiple times
4. **Sub-cascades** - Nested execution trees
5. **Async cascades** - Fire-and-forget background tasks

## Data Available

The parquet logs contain all the metadata needed:

```python
{
    'phase_name': 'generate_code',
    'sounding_index': 1,        # Which parallel attempt (0, 1, 2, ...)
    'is_winner': True,          # Did this sounding win?
    'reforge_step': 0,          # Which refinement iteration (0=initial, 1+=refined)
    'trace_id': 'abc123',       # Unique execution ID
    'parent_trace_id': 'xyz789' # For nesting
}
```

## Recommended Approach: React Flow

**Library**: [React Flow](https://reactflow.dev/)

**Why**:
- Custom node types (phase, sounding, reforge, sub-cascade)
- Visual grouping/nesting
- Interactive (zoom, pan, click to inspect)
- Automatic layout algorithms available
- Can show/hide branches

### Node Types

```typescript
// 1. Simple Phase Node
{
  id: 'phase_0',
  type: 'phaseNode',
  data: { label: 'Parse Input', event_count: 12 },
  position: { x: 0, y: 0 }
}

// 2. Soundings Group Node
{
  id: 'phase_1_soundings',
  type: 'soundingsGroup',
  data: {
    label: 'Generate Code (3 attempts)',
    winner_index: 1
  },
  position: { x: 300, y: 0 },
  style: { width: 400, height: 300 }  // Contains children
}

// 3. Individual Sounding Node (child of group)
{
  id: 'phase_1_sounding_1',
  type: 'soundingNode',
  data: {
    index: 1,
    is_winner: true,
    event_count: 45
  },
  parentNode: 'phase_1_soundings',  // Nested inside group
  position: { x: 50, y: 0 }
}

// 4. Reforge Node
{
  id: 'phase_1_reforge_2_sounding_0',
  type: 'reforgeNode',
  data: {
    step: 2,
    index: 0,
    is_winner: true,
    event_count: 23
  },
  position: { x: 900, y: -50 }
}
```

### Edge Types

```typescript
// Winner path (highlighted)
{
  id: 'e_winner',
  source: 'phase_1_sounding_1',
  target: 'phase_2',
  animated: true,
  style: { stroke: '#00ff00', strokeWidth: 3 },
  label: 'winner'
}

// Failed attempt (dimmed)
{
  id: 'e_failed',
  source: 'phase_1_sounding_0',
  target: 'phase_1_soundings',
  style: { stroke: '#666', strokeWidth: 1, opacity: 0.3 }
}

// Reforge refinement
{
  id: 'e_reforge',
  source: 'phase_1_reforge_1_sounding_1',
  target: 'phase_1_reforge_2',
  animated: true,
  label: 'refine',
  style: { stroke: '#ff9800', strokeWidth: 2 }
}
```

## Visual Layout Patterns

### 1. Soundings (Parallel Attempts)

```
    ┌─────────────────────────────┐
    │ Generate Code (Soundings)   │
    │ ┌───────┐  ┌───────┐        │
    │ │Attempt│  │Attempt│ Winner │
    │ │   0   │  │   1   ├────────┼──────> Next Phase
    │ └───────┘  └───────┘        │
    │ ┌───────┐                   │
    │ │Attempt│                   │
    │ │   2   │                   │
    │ └───────┘                   │
    └─────────────────────────────┘
```

**Layout**:
- Group box containing all soundings
- Vertical swim lanes for each attempt
- Winner highlighted with green border + continues flow
- Losers dimmed/grayed out

### 2. Reforge (Iterative Refinement)

```
Step 0 (Initial)     Step 1 (Refine)     Step 2 (Refine)
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ ┌─────┐     │      │ ┌─────┐     │      │ ┌─────┐     │
│ │  0  │     │      │ │  0  │     │      │ │  0  │     │
│ └─────┘     │      │ └─────┘     │      │ └─────┘     │
│ ┌─────┐     │      │ ┌─────┐     │      │ ┌─────┐     │
│ │  1  ├─────┼──────┼>│  0  ├─────┼──────┼>│  1  │Winner│──>
│ └─────┘     │      │ └─────┘     │      │ └─────┘     │
│ ┌─────┐     │      │ ┌─────┐     │      │             │
│ │  2  │     │      │ │  1  │     │      │             │
│ └─────┘     │      │ └─────┘     │      │             │
└─────────────┘      └─────────────┘      └─────────────┘
```

**Layout**:
- Horizontal progression (left to right = time)
- Each step is a group containing soundings
- Winner of each step feeds into next step
- Arrows show refinement flow

### 3. Retry Loops

```
        ┌─────────────┐
    ┌───┤ API Call    │
    │   │ (Attempt 1) │
    │   └──────┬──────┘
    │          │ Error
    │   ┌──────▼──────┐
    ├───┤ API Call    │
    │   │ (Attempt 2) │
    │   └──────┬──────┘
    │          │ Error
    │   ┌──────▼──────┐
    └───┤ API Call    │
        │ (Attempt 3) │──> Success
        └─────────────┘
```

**Layout**:
- Vertical stack of attempts
- Curved back-edges for retries
- Last successful attempt continues forward

## Implementation Strategy

### Phase 1: Data Structure (✅ Done)

```python
# GET /api/execution-tree/<session_id>
{
  'session_id': 'xxx',
  'phases': [
    {
      'name': 'phase1',
      'type': 'soundings',
      'soundings': [
        {'index': 0, 'is_winner': False, 'events': [...]},
        {'index': 1, 'is_winner': True, 'events': [...]},
        {'index': 2, 'is_winner': False, 'events': [...]}
      ],
      'winner_index': 1
    }
  ]
}
```

### Phase 2: React Flow Integration

```bash
npm install reactflow
```

```tsx
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background
} from 'reactflow';

// Custom node components
const PhaseNode = ({ data }) => (
  <div className="phase-node">
    <h4>{data.label}</h4>
    <span>{data.event_count} events</span>
  </div>
);

const SoundingNode = ({ data }) => (
  <div className={`sounding-node ${data.is_winner ? 'winner' : 'loser'}`}>
    <span>Attempt {data.index}</span>
    {data.is_winner && <span className="badge">Winner</span>}
  </div>
);

const nodeTypes = {
  phaseNode: PhaseNode,
  soundingNode: SoundingNode,
  soundingsGroup: SoundingsGroupNode,
  reforgeNode: ReforgeNode,
};

function ExecutionGraph({ sessionId }) {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);

  useEffect(() => {
    fetch(`/api/execution-tree/${sessionId}?format=react-flow`)
      .then(res => res.json())
      .then(data => {
        setNodes(data.nodes);
        setEdges(data.edges);
      });
  }, [sessionId]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
    >
      <Background />
      <Controls />
    </ReactFlow>
  );
}
```

### Phase 3: Custom Layouts

Use automatic layout algorithms for complex graphs:

```bash
npm install dagre  # For hierarchical layout
```

```typescript
import dagre from 'dagre';

function getLayoutedElements(nodes, edges) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR' }); // Left-to-right

  nodes.forEach(node => {
    dagreGraph.setNode(node.id, { width: 200, height: 100 });
  });

  edges.forEach(edge => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map(node => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x,
        y: nodeWithPosition.y
      }
    };
  });

  return { nodes: layoutedNodes, edges };
}
```

## Alternative: D3 Force Graph

For truly complex cascades with many branches:

```typescript
import ForceGraph2D from 'react-force-graph-2d';

<ForceGraph2D
  graphData={graphData}
  nodeLabel="label"
  nodeAutoColorBy="type"
  linkDirectionalArrowLength={3.5}
  linkDirectionalArrowRelPos={1}
  nodeCanvasObject={(node, ctx, globalScale) => {
    // Custom node rendering
    if (node.is_winner) {
      ctx.fillStyle = '#00ff00';
      ctx.beginPath();
      ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI);
      ctx.fill();
    }
  }}
/>
```

## Interaction Patterns

1. **Click node** → Show event details panel
2. **Hover sounding** → Highlight winner path
3. **Toggle failed branches** → Show/hide non-winner soundings
4. **Zoom to phase** → Focus on specific phase group
5. **Minimap** → Navigate large execution graphs

## Summary

**Best practices:**
- ✅ Use React Flow for interactive, zoomable canvas
- ✅ Group soundings/reforges visually with containers
- ✅ Highlight winner paths (green, animated)
- ✅ Dim failed attempts (gray, low opacity)
- ✅ Show temporal ordering (left-to-right or top-to-bottom)
- ✅ Use custom node types for each execution pattern
- ✅ Provide minimap for large graphs
- ✅ Click nodes to inspect events

The data is already structured in the parquet logs - you just need to query it intelligently and render it with proper visual grouping!
