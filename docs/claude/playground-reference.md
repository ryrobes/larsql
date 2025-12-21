# Playground Canvas Reference

**Visual Node-Based Editor for Building Image Generation Workflows**

The Playground Canvas is a React Flow-based visual editor for building and executing Windlass cascades. It transforms abstract YAML configurations into an interactive, CCG-inspired visual experience with stacked deck soundings, two-sided phase cards, and real-time execution feedback.

## Overview

The Playground enables users to:
- **Build cascades visually** using drag-and-drop node composition
- **Execute workflows** with real-time state updates via SSE
- **Inspect configurations** by flipping cards to reveal YAML editors
- **Visualize soundings** with "stacked deck" fan-out animations
- **Save/load cascades** from the tackle/ or cascades/ directories

**Location**: `dashboard/frontend/src/playground/`

**Access**: `http://localhost:5001/playground`

## Core Concepts

### Two-Sided Phase Cards

Every phase in the Playground is represented as a **two-sided card** with a 3D flip animation:

**Front (Execution Side)**:
- Shows phase output (images, text, status)
- Real-time execution state (pending, running, complete, error)
- Cost/token metrics
- Sounding results (if configured)

**Back (Configuration Side)**:
- Monaco YAML editor with syntax highlighting
- Full phase configuration (instructions, tackle, model, soundings, etc.)
- Live editing with validation
- Save to update the cascade

**Flipping**: Click the flip icon or use keyboard shortcuts to toggle between sides.

### Stacked Deck UI (Soundings Visualization)

When a phase has soundings configured, it displays as a **stacked deck of cards**:

**Visual Metaphor**: Inspired by collectible card games (CCG) without being overtly game-like:
- **Stacked appearance**: Multiple cards layered with subtle offset
- **Fan-out animation**: Click to reveal all sounding attempts
- **Rarity frames**: Border colors based on phase complexity/cost
  - Common (gray): Simple phases, cheap models
  - Uncommon (green): Moderate complexity
  - Rare (blue): Complex phases, expensive models
  - Legendary (gold): Multi-reforge, vision feedback loops
- **Model element badges**: Color-coded borders by provider
  - Anthropic (purple): Claude models
  - OpenAI (teal): GPT models
  - Google (multi-color): Gemini models
  - Meta (blue): Llama models

**Interaction**:
1. **Collapsed state**: Deck shows stack (top card visible)
2. **Click deck**: Cards fan out to reveal all soundings
3. **Click card**: Select specific sounding to view details
4. **Winner badge**: Gold star on evaluator-chosen winner

**Design Reference**: `docs/plans/stacked-deck-soundings-ui.md`

### Node Types

#### 1. Prompt Nodes

**Purpose**: Define text inputs for phases (prompts, instructions, data).

**Visual**:
- Rectangular shape
- Light background
- Mono-spaced font for text
- Resizable text area

**Configuration**:
```yaml
type: prompt
content: |
  Generate an image of a sunset over mountains
  with vibrant colors and dramatic lighting.
```

**Connections**: Output port connects to Phase Card input ports.

#### 2. Phase Cards (Image Generator Nodes)

**Purpose**: Execute Windlass phases that produce images or other outputs.

**Visual**:
- Card-shaped (rounded corners, shadow)
- Two-sided (front/back flip animation)
- Rarity frame border (based on configuration complexity)
- Model badge in corner
- Stacked appearance if soundings configured

**Configuration**:
```yaml
type: phase
name: "generate_image"
instructions: "{{ input.prompt }}"
tackle:
  - "image_gen"
model: "openai/dall-e-3"
soundings:
  factor: 3
  evaluator_instructions: "Pick the most visually striking image"
```

**Connections**:
- Input ports: Receive prompts or data from other nodes
- Output ports: Send results to downstream phases
- Handoff ports: Route to next phases (colored by target phase)

## Features

### Cascade Introspection

**Load any existing cascade** and the Playground will automatically:
- Discover input dependencies from `{{ input.X }}` templates
- Create prompt nodes for each input variable
- Generate phase cards for each phase
- Wire connections based on handoffs and data flow
- Position nodes with auto-layout (Dagre algorithm)

**Example**:
```yaml
# Original cascade
cascade_id: "image_workflow"
inputs_schema:
  style_prompt: "Art style description"
  subject: "Subject to generate"
phases:
  - name: "generate"
    instructions: "Create {{ input.subject }} in {{ input.style_prompt }} style"
    tackle: ["image_gen"]
```

**Playground generates**:
- Prompt node: `style_prompt`
- Prompt node: `subject`
- Phase card: `generate` (connected to both prompts)

### Real-Time Execution

**Server-Sent Events (SSE)** provide live updates during cascade execution:

**Event Types**:
- `phase_start`: Phase begins executing
- `phase_complete`: Phase finishes (includes outputs)
- `phase_error`: Phase fails (includes error details)
- `sounding_start`: Individual sounding begins
- `sounding_complete`: Sounding finishes (includes outputs)
- `evaluator_complete`: Evaluator picks winner

**UI Updates**:
- Card state changes: pending → running → complete/error
- Progress indicators: Spinner during execution
- Output rendering: Images appear as soon as available
- Cost tracking: Cumulative session cost updates in header
- Logs panel: Real-time log streaming

### Monaco Code Editor Integration

**Both sides** of phase cards use Monaco (VS Code's editor):

**Front side** (when viewing code outputs):
- Syntax highlighting for JSON, YAML, Python, etc.
- Read-only mode for execution results

**Back side** (configuration editor):
- Full YAML syntax highlighting
- Auto-completion for Windlass schema
- Error squiggles for invalid YAML
- Ctrl+S to save changes

### Cascade Browser Modal

**Access**: Click "Load Cascade" button in header

**Features**:
- Browse `tackle/` and `cascades/` directories
- Search/filter by name or description
- Preview cascade YAML before loading
- Load into canvas with one click

**Implementation**: `dashboard/frontend/src/playground/CascadeBrowserModal.js`

### Save As Dialog

**Access**: Click "Save" or "Save As" button in header

**Features**:
- Choose save location: `tackle/` (reusable tools) or `cascades/` (user workflows)
- Rename cascade
- Add/edit description
- Overwrite protection (confirms before replacing)

**Cascade Metadata**:
The playground adds metadata to saved cascades:

```yaml
cascade_id: "my_workflow"
description: "Generated via Playground"
_metadata:
  created_in_playground: true
  created_at: "2024-01-15T10:30:00Z"
  last_modified: "2024-01-15T14:20:00Z"
  node_positions:  # Preserves visual layout
    generate_image:
      x: 250
      y: 100
```

## Component Architecture

**Location**: `dashboard/frontend/src/playground/`

### Main Components

#### PlaygroundPage.js

**Purpose**: Top-level page container

**Responsibilities**:
- Initialize React Flow canvas
- Load cascade data
- Manage execution state
- Handle SSE connections
- Coordinate header/canvas/panels

**Size**: 403 lines

**Key State**:
```javascript
const [nodes, setNodes] = useState([]);
const [edges, setEdges] = useState([]);
const [cascade, setCascade] = useState(null);
const [isExecuting, setIsExecuting] = useState(false);
const [sessionId, setSessionId] = useState(null);
```

#### PhaseCard.js

**Purpose**: Two-sided phase card component with stacked deck UI

**Responsibilities**:
- Render card front (outputs) and back (YAML editor)
- Handle flip animations (3D transform)
- Display soundings as stacked deck
- Fan-out animation for soundings
- Execution state visualization
- Cost/token metrics display

**Size**: 35,443 bytes (largest component - handles complex visual logic)

**Key Features**:
```javascript
// Flip state
const [isFlipped, setIsFlipped] = useState(false);

// Soundings
const [isFannedOut, setIsFannedOut] = useState(false);
const soundings = phaseData?.soundings || [];

// Execution state
const executionState = phaseData?.state; // 'pending' | 'running' | 'complete' | 'error'
```

**Rarity Calculation**:
```javascript
function calculateRarity(phase) {
  let score = 0;

  // Soundings
  if (phase.soundings) score += phase.soundings.factor * 2;

  // Reforge
  if (phase.soundings?.reforge?.steps) {
    score += phase.soundings.reforge.steps * 3;
  }

  // Wards
  if (phase.wards) score += 5;

  // Expensive model
  const expensiveModels = ['claude-opus', 'gpt-4', 'o1-preview'];
  if (expensiveModels.some(m => phase.model?.includes(m))) {
    score += 10;
  }

  // Thresholds
  if (score >= 20) return 'legendary';
  if (score >= 10) return 'rare';
  if (score >= 5) return 'uncommon';
  return 'common';
}
```

**Model Badge Colors**:
```javascript
const modelColors = {
  'anthropic': '#8B5CF6',  // Purple
  'openai': '#10B981',     // Teal
  'google': 'linear-gradient(90deg, #4285F4, #34A853, #FBBC04, #EA4335)',
  'meta': '#0668E1',       // Blue
  'x-ai': '#1DA1F2',       // Twitter blue (for Grok)
  'default': '#6B7280'     // Gray
};
```

#### playgroundStore.js

**Purpose**: Zustand store for global playground state

**Responsibilities**:
- Manage nodes/edges
- Track execution state
- Handle cascade CRUD operations
- Coordinate SSE events

**Key Actions**:
```javascript
const usePlaygroundStore = create((set, get) => ({
  nodes: [],
  edges: [],
  cascade: null,

  // Load cascade into canvas
  loadCascade: async (cascadeId) => { /* ... */ },

  // Execute cascade
  executeCascade: async (input) => { /* ... */ },

  // Update phase state from SSE
  updatePhaseState: (phaseName, state) => { /* ... */ },

  // Save cascade to file
  saveCascade: async (location) => { /* ... */ },
}));
```

### Supporting Components

**PromptNode.js**: Renders input prompt nodes

**ConnectionEdge.js**: Custom edge with handoff colors

**ExecutionPanel.js**: Bottom panel showing logs and outputs

**CascadeBrowserModal.js**: Modal for loading cascades

**SaveAsDialog.js**: Modal for saving cascades

## Visual Design System

### CSS Classes

**Rarity Frames** (`PhaseCard.module.css`):

```css
.card-common {
  border: 2px solid #9CA3AF;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.card-uncommon {
  border: 2px solid #10B981;
  box-shadow: 0 4px 6px rgba(16, 185, 129, 0.3);
}

.card-rare {
  border: 2px solid #3B82F6;
  box-shadow: 0 4px 6px rgba(59, 130, 246, 0.4);
}

.card-legendary {
  border: 2px solid #F59E0B;
  box-shadow: 0 6px 12px rgba(245, 158, 11, 0.5);
  animation: legendary-glow 2s ease-in-out infinite;
}

@keyframes legendary-glow {
  0%, 100% { box-shadow: 0 6px 12px rgba(245, 158, 11, 0.5); }
  50% { box-shadow: 0 8px 16px rgba(245, 158, 11, 0.7); }
}
```

**Stacked Deck Effect**:

```css
.card-stack {
  position: relative;
}

.card-stack::before,
.card-stack::after {
  content: '';
  position: absolute;
  width: 100%;
  height: 100%;
  background: inherit;
  border: inherit;
  border-radius: inherit;
  z-index: -1;
}

.card-stack::before {
  transform: translate(-4px, 4px) scale(0.98);
  opacity: 0.7;
}

.card-stack::after {
  transform: translate(-8px, 8px) scale(0.96);
  opacity: 0.4;
}
```

**Flip Animation**:

```css
.card-container {
  perspective: 1000px;
}

.card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.6s;
  transform-style: preserve-3d;
}

.card-container.flipped .card-inner {
  transform: rotateY(180deg);
}

.card-front,
.card-back {
  position: absolute;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
}

.card-back {
  transform: rotateY(180deg);
}
```

**Fan-Out Animation**:

```javascript
// Calculate positions for fanned-out cards
const fanOutPositions = soundings.map((_, index) => {
  const totalCards = soundings.length;
  const angleSpread = 30; // degrees
  const angle = (index - totalCards / 2) * (angleSpread / totalCards);
  const radius = 150; // pixels

  return {
    transform: `
      translateX(${Math.sin(angle * Math.PI / 180) * radius}px)
      translateY(${Math.cos(angle * Math.PI / 180) * radius - radius}px)
      rotate(${angle}deg)
    `,
    transition: `transform 0.3s ease-out ${index * 0.05}s`
  };
});
```

## API Integration

### Backend Endpoints

**Playground API** (`dashboard/backend/app.py`):

#### GET `/api/playground/cascades`

List all available cascades from `tackle/` and `cascades/`.

**Response**:
```json
{
  "cascades": [
    {
      "id": "image_workflow",
      "name": "Image Generation Workflow",
      "description": "Multi-stage image generation with soundings",
      "location": "cascades",
      "path": "/path/to/cascades/image_workflow.yaml",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

#### GET `/api/playground/cascade/:id`

Load specific cascade YAML.

**Response**:
```json
{
  "cascade_id": "image_workflow",
  "phases": [...],
  "_metadata": {...}
}
```

#### POST `/api/playground/cascade`

Save new or updated cascade.

**Request**:
```json
{
  "cascade": {...},
  "location": "cascades",  // or "tackle"
  "overwrite": false
}
```

#### POST `/api/playground/execute`

Execute cascade with input.

**Request**:
```json
{
  "cascade_id": "image_workflow",
  "input": {
    "style_prompt": "cyberpunk",
    "subject": "city skyline"
  },
  "session_id": "optional_session_123"
}
```

**Response**:
```json
{
  "session_id": "session_abc123",
  "status": "started"
}
```

**SSE Stream**: Client receives events on `/api/events/session_abc123`

#### GET `/api/playground/session/:id/state`

Get current execution state.

**Response**:
```json
{
  "session_id": "session_abc123",
  "status": "running",
  "current_phase": "generate_image",
  "phases": {
    "generate_image": {
      "state": "running",
      "attempts": 2,
      "cost": 0.045
    }
  },
  "outputs": {...}
}
```

### SSE Event Stream

**Endpoint**: `/api/events/:session_id`

**Event Format**:
```
event: phase_start
data: {"phase_name": "generate_image", "timestamp": "2024-01-15T10:00:00Z"}

event: phase_complete
data: {"phase_name": "generate_image", "output": {...}, "cost": 0.023}

event: sounding_complete
data: {"phase_name": "generate_image", "sounding_index": 0, "output": {...}}

event: evaluator_complete
data: {"phase_name": "generate_image", "winner_index": 1}
```

**Client Handling**:
```javascript
const eventSource = new EventSource(`/api/events/${sessionId}`);

eventSource.addEventListener('phase_start', (event) => {
  const data = JSON.parse(event.data);
  updatePhaseState(data.phase_name, 'running');
});

eventSource.addEventListener('phase_complete', (event) => {
  const data = JSON.parse(event.data);
  updatePhaseState(data.phase_name, 'complete');
  updatePhaseOutput(data.phase_name, data.output);
});
```

## Advanced Features

### Auto-Layout Algorithm

**Library**: Dagre (hierarchical graph layout)

The Playground automatically positions nodes when loading a cascade:

```javascript
import dagre from 'dagre';

function autoLayout(nodes, edges) {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: 'LR',  // Left-to-right flow
    nodesep: 100,   // Horizontal spacing
    ranksep: 200,   // Vertical spacing
  });

  // Add nodes
  nodes.forEach(node => {
    graph.setNode(node.id, {
      width: node.type === 'phase' ? 300 : 200,
      height: node.type === 'phase' ? 400 : 100,
    });
  });

  // Add edges
  edges.forEach(edge => {
    graph.setEdge(edge.source, edge.target);
  });

  // Compute layout
  dagre.layout(graph);

  // Apply positions
  return nodes.map(node => ({
    ...node,
    position: graph.node(node.id),
  }));
}
```

### Minimap & Controls

**React Flow built-in features**:

```javascript
import { MiniMap, Controls, Background } from 'reactflow';

<ReactFlow nodes={nodes} edges={edges}>
  <MiniMap />
  <Controls />
  <Background variant="dots" />
</ReactFlow>
```

**Minimap**: Small overview in corner (click to navigate)
**Controls**: Zoom in/out, fit view, lock/unlock
**Background**: Dot grid or line grid

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Space` | Toggle play/pause execution |
| `F` | Flip selected card |
| `Delete` | Delete selected nodes/edges |
| `Ctrl+S` | Save cascade |
| `Ctrl+O` | Open cascade browser |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `+` / `-` | Zoom in/out |
| `0` | Fit view |

## Example Workflows

### Simple Image Generation

```yaml
cascade_id: "simple_image_gen"
inputs_schema:
  prompt: "Image description"

phases:
  - name: "generate"
    instructions: "Generate: {{ input.prompt }}"
    tackle: ["image_gen"]
    model: "openai/dall-e-3"
```

**Playground Visualization**:
- 1 prompt node: "prompt"
- 1 phase card: "generate" (connected to prompt)
- Common rarity (simple configuration)

### Multi-Stage with Soundings

```yaml
cascade_id: "multi_stage_image"
inputs_schema:
  concept: "Base concept"
  style: "Art style"

phases:
  - name: "ideation"
    instructions: "Brainstorm {{ input.concept }} in {{ input.style }}"
    tackle: ["think"]
    handoffs: ["generate"]

  - name: "generate"
    instructions: "Generate image based on: {{ outputs.ideation }}"
    tackle: ["image_gen"]
    soundings:
      factor: 5
      evaluator_instructions: "Pick most creative and well-executed"
    model: "openai/dall-e-3"
```

**Playground Visualization**:
- 2 prompt nodes: "concept", "style"
- 1 phase card: "ideation" (common rarity)
- 1 phase card: "generate" (rare rarity, stacked deck with 5 cards)
- Connection from ideation → generate (handoff edge)

### Reforge Loop with Vision Feedback

```yaml
cascade_id: "iterative_refinement"
inputs_schema:
  prompt: "Initial concept"

phases:
  - name: "generate_and_refine"
    instructions: "Generate and iteratively improve: {{ input.prompt }}"
    tackle: ["image_gen", "vision_critique"]
    soundings:
      factor: 3
      evaluator_instructions: "Pick best initial attempt"
      reforge:
        steps: 3
        honing_prompt: "Improve based on vision feedback"
    model: "openai/dall-e-3"
```

**Playground Visualization**:
- 1 prompt node: "prompt"
- 1 phase card: "generate_and_refine" (legendary rarity due to reforge)
- Stacked deck appearance
- During execution: Shows reforge iterations with updated images

## Performance Considerations

### Bundle Size

The PhaseCard component is very large (35KB). Consider:
- Code splitting: Lazy load component
- Tree shaking: Remove unused React Flow features
- Memoization: Prevent unnecessary re-renders

**Optimization**:
```javascript
import { lazy, Suspense } from 'react';

const PhaseCard = lazy(() => import('./PhaseCard'));

<Suspense fallback={<CardSkeleton />}>
  <PhaseCard {...props} />
</Suspense>
```

### React Flow Performance

For large cascades (100+ nodes):
- Enable React Flow's built-in virtualization
- Disable animations during drag
- Use `memo()` for node components
- Debounce edge updates

### SSE Connection Management

**Best Practices**:
- Close EventSource when component unmounts
- Implement reconnection logic for network errors
- Use heartbeat to detect stale connections

```javascript
useEffect(() => {
  const eventSource = new EventSource(`/api/events/${sessionId}`);

  // Auto-reconnect on error
  eventSource.onerror = () => {
    eventSource.close();
    setTimeout(() => {
      // Reconnect after 1 second
    }, 1000);
  };

  return () => eventSource.close();
}, [sessionId]);
```

## Troubleshooting

### Common Issues

**Issue**: Cards not flipping

**Solution**: Check CSS `transform-style: preserve-3d` is applied to parent container. Ensure `backface-visibility: hidden` is set on both sides.

---

**Issue**: Stacked deck not showing

**Solution**: Verify `soundings.factor > 1` in phase config. Check CSS `::before` and `::after` pseudo-elements are rendering.

---

**Issue**: SSE events not received

**Solution**: Check browser console for CORS errors. Verify backend SSE endpoint is streaming events. Ensure EventSource URL is correct.

---

**Issue**: Auto-layout overlaps nodes

**Solution**: Adjust `nodesep` and `ranksep` in Dagre config. For complex graphs, manually position nodes and save with `_metadata.node_positions`.

## Future Enhancements

Planned features:

1. **Collaborative editing**: Multi-user canvas with operational transforms (CRDTs)
2. **Version history**: Git-like diffs for cascade changes
3. **Template gallery**: Pre-built workflow templates
4. **Custom node types**: User-defined visual components
5. **Export formats**: Export to PNG, SVG, or Mermaid diagrams
6. **Execution replay**: Scrub through execution timeline
7. **Cost optimizer**: Suggest cheaper model alternatives
8. **A/B testing**: Compare soundings side-by-side

## Related Documentation

- **Soundings**: `docs/claude/soundings-reference.md`
- **Dashboard UI**: `docs/claude/dashboard-reference.md`
- **Observability**: `docs/claude/observability.md`
- **Design Docs**: `docs/plans/stacked-deck-soundings-ui.md`, `docs/plans/image-playground.md`
