# Image Playground: Visual Image Workflow Editor

## Overview

Image Playground is a visual, node-based editor for building image generation and composition workflows in Windlass. It takes inspiration from ComfyUI's node graph approach but stays true to Windlass's declarative philosophy—the visual editor generates standard cascade YAML files that can be run headlessly.

**Core insight**: Image generation workflows are inherently visual and exploratory. Users want to:
- Try multiple variations (soundings) and pick favorites
- Decompose images into layers and selectively recombine them
- Compose multiple generated images into final outputs
- Iterate step-by-step, inspecting results before continuing

The Image Playground makes this workflow natural while keeping everything as standard Windlass primitives under the hood.

---

## Design Philosophy

### Everything Is The Graph

There are no separate panels, modals, or contexts. The React Flow canvas IS the entire interface:

- **Prompts** are edited inline in nodes
- **Images** are displayed as nodes (ImagePortNodes)
- **Composition** happens by dragging ImagePortNodes onto a ComposeNode backdrop
- **Browsing** is just zooming out to see all generated images

This is Bret Victor's "direct manipulation" principle: the image IS where it is. Move the node, move the layer.

### No Special Cases

Every node follows the same pattern as any Windlass phase:
- Takes inputs (text prompts, images, parameters)
- Produces outputs in standard format: `{"content": "...", "images": [...]}`
- Can be wired to downstream nodes

The ComposeNode is not special—it's just a backdrop that detects which ImagePortNodes are inside its bounds.

### Cascades As Source Of Truth

The visual graph generates a standard cascade YAML file. The graph state is embedded as metadata (`_playground` key) that the runner ignores. This keeps everything self-contained:
- One file to save, share, version control
- Can run headlessly via CLI without the UI
- Can open in playground to continue editing

---

## Architecture

### Two-Pane Layout

```
┌─────────┬──────────────────────────────────────────────────────────────┐
│ PALETTE │                          CANVAS                              │
│         │                                                              │
│ [FLUX]  │  [prompt] ──▶ [FLUX] ──▶ [img_0] ════════════╗              │
│ [SDXL]  │                                              ║              │
│ [Decomp]│                          ┌───────────────────╨──────────┐   │
│ [Upscl] │                          │ ComposeNode    1024×768      │   │
│ [Compos]│                          │                              │   │
│         │  [img_x] ════════════════║▶  ┌─────────┐               │   │
│         │                          │   │ img_0   │               │   │
│         │                          │   └─────────┘   ┌───────┐   │   │
│         │                          │                 │ img_x │   │   │
│         │                          │                 └───────┘   │   │
│         │                          │                              │   │
│         │                          └──────────────┬───────────────┘   │
│         │                                         │                    │
│         │                                    [composed]                │
│         │                                         │                    │
│         │                                    [Upscale] ──▶ [final]    │
└─────────┴──────────────────────────────────────────────────────────────┘
```

**Left pane**: Palette of draggable node types
**Center/Right**: React Flow canvas where everything happens

### The Breakthrough: React Flow IS The Compositor

Instead of embedding a separate composition library (like Konva) inside a node, we use React Flow itself as the composition engine:

```
Traditional approach:
┌─────────────────────────────────────┐
│ ComposeNode                         │
│ ┌─────────────────────────────────┐ │
│ │      Konva Canvas               │ │
│ │   (separate drag/resize system) │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘

Our approach:
┌─────────────────────────────────────┐
│ ComposeNode (just a backdrop)       │
│                                     │
│   [img_0]  ← These are REAL React   │
│        [img_2]    Flow nodes,       │
│                   just positioned   │
│             [img_5]  inside the     │
│                      backdrop       │
└─────────────────────────────────────┘
```

**The ComposeNode is literally just an empty rectangle.** It defines the canvas bounds. ImagePortNodes dragged inside it become layers—their React Flow position IS their layer position.

**What we get for free from React Flow:**
- Drag nodes ✓
- Resize nodes (with `@reactflow/node-resizer`) ✓
- Position tracking ✓
- Z-index control ✓
- Zoom/pan ✓
- Selection ✓
- Minimap ✓
- Undo/redo (with zustand) ✓

**What we need to build:**
- Bounds detection (~20 lines)
- Chrome hiding when inside compose (conditional render)
- Layer order tracking (array in ComposeNode data)
- Opacity/blend controls (small UI on ImagePortNode)

---

## Node Types

### Unified Node Model

All nodes are instances of a single configurable component, differentiated by their palette definition:

| Category | Examples | Provider | Inputs | Outputs |
|----------|----------|----------|--------|---------|
| Generator | FLUX.1, SDXL | OpenRouter | prompt | 1 image |
| Transformer | img2img, inpaint | OpenRouter | prompt + image | 1 image |
| HF Tool | Decompose, Upscale | Harbor (Gradio) | varies | 1 or N images |
| Utility | Compose | Local | spatial containment | 1 image |
| Input | Prompt | None | text | text |

HF tools are generic—the decompose model isn't special, it's just configured as an HF Space tool that happens to output multiple images.

### ImagePortNode

When a node produces images, it spawns **ImagePortNode** children—one per output:

```
┌──────────────┐
│   FLUX.1     │
│   Generate   │
└──────┬───────┘
       │ produces 1 image
       ▼
   ┌───────┐
   │ img_0 │  ← ImagePortNode (displays thumbnail)
   └───┬───┘
       │ can wire to downstream OR drag into compose
       ▼
```

For multi-output nodes (decompose, soundings), multiple ImagePortNodes spawn:

```
┌──────────────┐
│  Decompose   │
└──────┬───────┘
   ┌───┴───┐
   ▼   ▼   ▼
┌───┐┌───┐┌───┐
│ 0 ││ 1 ││ 2 │  ← Each independently wirable or composable
└───┘└───┘└───┘
```

### ImagePortNode Behavior

The ImagePortNode renders differently based on whether it's inside a ComposeNode:

```jsx
const ImagePortNode = ({ id, data, xPos, yPos }) => {
  const composeNodes = useNodes().filter(n => n.type === 'compose');
  const parentCompose = composeNodes.find(c =>
    isInsideBounds({ x: xPos, y: yPos }, c)
  );

  if (parentCompose) {
    // LAYER MODE: no handles, show resize + composition controls
    return (
      <div className="image-layer">
        <img src={data.thumbnail} />
        <NodeResizer />
        <div className="layer-controls">
          <input type="range" value={data.opacity ?? 1} />
          <select value={data.blendMode ?? 'normal'}>
            <option value="normal">Normal</option>
            <option value="multiply">Multiply</option>
            <option value="screen">Screen</option>
          </select>
        </div>
      </div>
    );
  }

  // NORMAL MODE: source handle for wiring
  return (
    <div className="image-port">
      <img src={data.thumbnail} />
      <Handle type="source" position="bottom" />
    </div>
  );
};
```

### ComposeNode

The ComposeNode is remarkably simple—just a resizable backdrop:

```jsx
const ComposeNode = ({ id, data }) => {
  const layersInside = useLayersInBounds(id);

  return (
    <div
      className="compose-backdrop"
      style={{
        width: data.displayWidth || 400,
        height: data.displayHeight || 300,
        backgroundColor: data.background || 'rgba(0,0,0,0.05)',
        border: '2px dashed #666'
      }}
    >
      {/* Output dimensions label */}
      <div className="canvas-size">
        {data.outputWidth || 1024} × {data.outputHeight || 768}
      </div>

      {/* Layer order controls */}
      <div className="layer-stack">
        {layersInside.map((layer, i) => (
          <div key={layer.id} className="layer-chip">
            <span>{layer.data.sourceName}</span>
            <button onClick={() => moveLayer(layer.id, 'up')}>↑</button>
            <button onClick={() => moveLayer(layer.id, 'down')}>↓</button>
          </div>
        ))}
      </div>

      {/* Output handle */}
      <Handle type="source" position="bottom" id="output" />
      <NodeResizer />
    </div>
  );
};
```

The layers (ImagePortNodes) are **not children** of this component—they're separate React Flow nodes that happen to be positioned within these bounds.

### Soundings On Any Node

Any image-producing node can enable soundings (parallel variations):

```
┌──────────────┐
│   FLUX.1     │
│ ☑ Variations │  ← Checkbox + slider
│   Factor: 4  │
└──────┬───────┘
   ┌───┴───┐
   ▼ ▼ ▼ ▼
  [0][1][2][3]  ← 4 ImagePortNodes spawn
```

Under the hood, this generates a phase with `soundings: { factor: 4, mode: "all" }`.

---

## Containment-Based Composition

### How It Works

An ImagePortNode becomes a "layer" when its position is inside a ComposeNode's bounds:

```javascript
function isInsideBounds(nodePosition, composeNode) {
  const bounds = {
    left: composeNode.position.x,
    top: composeNode.position.y,
    right: composeNode.position.x + (composeNode.width || 400),
    bottom: composeNode.position.y + (composeNode.height || 300)
  };

  return (
    nodePosition.x >= bounds.left &&
    nodePosition.x <= bounds.right &&
    nodePosition.y >= bounds.top &&
    nodePosition.y <= bounds.bottom
  );
}
```

### Position Transposition

The ComposeNode has two sizes:
- **Display size**: How big it appears on screen (e.g., 400×300)
- **Output size**: The actual output resolution (e.g., 1024×768)

When generating the cascade, positions are scaled:

```javascript
// ComposeNode displays at 400×300, outputs at 1024×768
const scaleX = outputWidth / displayWidth;  // 2.56
const scaleY = outputHeight / displayHeight; // 2.56

// ImagePortNode at display position (150, 100)
// becomes output position (384, 256)
```

### Layer Order

React Flow nodes have `zIndex`. The ComposeNode stores layer order in its data:

```javascript
// ComposeNode data
{
  layerOrder: ["img_0", "img_2", "img_5"]  // Bottom to top
}

// Applied when rendering
nodes = nodes.map(n => {
  const orderIndex = composeNode.data.layerOrder.indexOf(n.id);
  if (orderIndex !== -1) {
    return { ...n, zIndex: 100 + orderIndex };
  }
  return n;
});
```

### Edges Still Show Provenance

When you drag an ImagePortNode into a ComposeNode, the edge from its source still exists:

```
[FLUX] ────▶ [img_0] ════════════╗
                                 ║
                    ┌────────────╨─────────────┐
                    │ ComposeNode              │
                    │                          │
                    │    ┌─────────┐          │
                    │    │ img_0   │          │
                    │    └─────────┘          │
                    └────────────┬─────────────┘
                                 │
                            [composed]
```

The edge shows where the image came from. Containment determines composition.

---

## Node Palette

### Palette Schema

```typescript
interface PaletteItem {
  id: string;
  name: string;
  category: "generator" | "transformer" | "tool" | "utility";

  // Provider (exactly one)
  openrouter?: {
    model: string;
  };
  harbor?: {
    space: string;
    apiName: string;
  };
  local?: {
    tool: string;
  };

  // I/O schema
  inputs: {
    prompt?: boolean;
    image?: boolean;
    images?: boolean;
    params?: ParamDef[];
  };
  outputs: {
    mode: "single" | "multiple" | "dynamic";
    count?: number;
  };

  // UI
  icon: string;
  color: string;
}
```

### Initial Palette (MVP)

```json
{
  "palette": [
    {
      "id": "flux_schnell",
      "name": "FLUX.1 Schnell",
      "category": "generator",
      "openrouter": { "model": "black-forest-labs/FLUX-1-schnell" },
      "inputs": { "prompt": true },
      "outputs": { "mode": "single" },
      "icon": "⚡",
      "color": "#7c3aed"
    },
    {
      "id": "flux_dev",
      "name": "FLUX.1 Dev",
      "category": "generator",
      "openrouter": { "model": "black-forest-labs/FLUX-1-dev" },
      "inputs": { "prompt": true },
      "outputs": { "mode": "single" },
      "icon": "🎨",
      "color": "#7c3aed"
    },
    {
      "id": "sdxl_lightning",
      "name": "SDXL Lightning",
      "category": "generator",
      "openrouter": { "model": "bytedance/sdxl-lightning-4step" },
      "inputs": { "prompt": true },
      "outputs": { "mode": "single" },
      "icon": "⚡",
      "color": "#f59e0b"
    },
    {
      "id": "layer_decompose",
      "name": "Layer Decompose",
      "category": "tool",
      "harbor": { "space": "ryanr/layer-decompose", "apiName": "/predict" },
      "inputs": { "image": true },
      "outputs": { "mode": "dynamic" },
      "icon": "📚",
      "color": "#ec4899"
    },
    {
      "id": "upscale_esrgan",
      "name": "Real-ESRGAN 4x",
      "category": "tool",
      "harbor": { "space": "xinntao/Real-ESRGAN", "apiName": "/predict" },
      "inputs": { "image": true },
      "outputs": { "mode": "single" },
      "icon": "🔍",
      "color": "#06b6d4"
    },
    {
      "id": "compose",
      "name": "Compose",
      "category": "utility",
      "local": { "tool": "image_compose" },
      "inputs": { "images": true },
      "outputs": { "mode": "single" },
      "icon": "🎭",
      "color": "#8b5cf6"
    }
  ]
}
```

### Cost Display

Rather than hardcoding costs, query actual execution costs from the unified logs:

```sql
SELECT model, AVG(cost) as avg_cost
FROM all_data
WHERE cost > 0 AND model LIKE '%FLUX%'
GROUP BY model
```

OpenRouter nodes show average cost after a few executions. HF Space tools don't show cost (billed hourly/monthly, not per-call).

---

## Cascade Generation

### Embedded Metadata

The graph state is stored in a `_playground` key that the runner ignores:

```yaml
cascade_id: playground_sunset_abc123
description: "Generated from Image Playground"

# UI Metadata - ignored by WindlassRunner
_playground:
  version: 1
  viewport: { x: 0, y: 0, zoom: 1.0 }

  nodes:
    - id: "prompt_1"
      type: "prompt"
      position: { x: 100, y: 50 }
      data: { text: "sunset over mountains" }

    - id: "generate_1"
      type: "image"
      position: { x: 100, y: 180 }
      data: { paletteId: "flux_schnell" }

    - id: "compose_1"
      type: "compose"
      position: { x: 300, y: 300 }
      width: 400
      height: 300
      data:
        outputWidth: 1024
        outputHeight: 768
        background: "transparent"
        layerOrder: ["generate_1_img_0", "decompose_1_img_2"]

  edges:
    - source: "prompt_1"
      target: "generate_1"

# Executable Phases
phases:
  - name: generate_1
    instructions: "Generate: {{ input.prompt_1 }}"
    tackle: [openrouter_image_gen]
    model: "black-forest-labs/FLUX-1-schnell"
    rules: { max_turns: 1 }

  - name: compose_1
    type: deterministic
    tackle: [image_compose]
    inputs:
      canvas_size: [1024, 768]
      background: "transparent"
      layers:
        - source: "{{ outputs.generate_1.images[0] }}"
          x: 0
          y: 0
          scale: 1.0
          opacity: 1.0
          blend_mode: "normal"
```

### Composition Phase Generation

The cascade generator computes layers from spatial relationships:

```javascript
function generateComposePhase(composeNode, allNodes) {
  const bounds = getNodeBounds(composeNode);

  // Find all ImagePortNodes inside this ComposeNode
  const layers = allNodes
    .filter(n => n.type === 'imagePort' && isInsideBounds(n.position, bounds))
    .sort((a, b) => {
      const order = composeNode.data.layerOrder || [];
      return order.indexOf(a.id) - order.indexOf(b.id);
    });

  // Scale factor: display → output
  const scaleX = composeNode.data.outputWidth / bounds.width;
  const scaleY = composeNode.data.outputHeight / bounds.height;

  return {
    name: `compose_${composeNode.id}`,
    type: 'deterministic',
    tackle: ['image_compose'],
    inputs: {
      canvas_size: [
        composeNode.data.outputWidth,
        composeNode.data.outputHeight
      ],
      background: composeNode.data.background || 'transparent',
      layers: layers.map(layer => ({
        source: `{{ outputs.${layer.data.sourcePhase}.images[${layer.data.sourceIndex}] }}`,
        x: Math.round((layer.position.x - bounds.x) * scaleX),
        y: Math.round((layer.position.y - bounds.y) * scaleY),
        scale: layer.width ? (layer.width / layer.data.originalWidth) : 1.0,
        opacity: layer.data.opacity ?? 1.0,
        blend_mode: layer.data.blendMode ?? 'normal'
      }))
    }
  };
}
```

---

## The image_compose Tool

A deterministic Pillow-based tool that composites layers:

```python
# windlass/eddies/compose.py

from PIL import Image
from uuid import uuid4
from windlass import register_tackle
from windlass.config import get_config

def image_compose(
    canvas_size: list,
    layers: list,
    background: str = "transparent"
) -> dict:
    """Compose multiple images into a single layered output.

    Args:
        canvas_size: [width, height] in pixels
        layers: List of layer specs:
            - source: Path to source image
            - x, y: Position on canvas
            - scale: Scale factor (1.0 = original)
            - opacity: 0.0 to 1.0
            - blend_mode: "normal", "multiply", "screen", "overlay"
        background: Hex color or "transparent"

    Returns:
        Standard format: {"content": "...", "images": [path]}
    """
    config = get_config()
    width, height = int(canvas_size[0]), int(canvas_size[1])

    # Create canvas
    if background == "transparent":
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        canvas = Image.new("RGBA", (width, height), background)

    for layer_spec in layers:
        img = Image.open(layer_spec["source"]).convert("RGBA")

        # Scale
        scale = layer_spec.get("scale", 1.0)
        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)

        # Opacity
        opacity = layer_spec.get("opacity", 1.0)
        if opacity < 1.0:
            alpha = img.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity))
            img.putalpha(alpha)

        # Composite
        x, y = int(layer_spec.get("x", 0)), int(layer_spec.get("y", 0))
        blend_mode = layer_spec.get("blend_mode", "normal")

        if blend_mode == "normal":
            canvas.paste(img, (x, y), img)
        elif blend_mode == "multiply":
            from PIL import ImageChops
            region = canvas.crop((x, y, x + img.width, y + img.height))
            blended = ImageChops.multiply(region.convert("RGB"), img.convert("RGB"))
            blended = blended.convert("RGBA")
            blended.putalpha(img.split()[3])
            canvas.paste(blended, (x, y), blended)
        # Additional blend modes...

    output_path = f"{config.image_dir}/composed_{uuid4().hex[:8]}.png"
    canvas.save(output_path, "PNG")

    return {
        "content": f"Composed {len(layers)} layers",
        "images": [output_path]
    }

register_tackle("image_compose", image_compose)
```

---

## Stepping Execution

For interactive workflow building, users execute phases incrementally.

### UI Pattern

- **"Run to here"**: Right-click node → execute up to that node
- **"Run next"**: Execute next pending phase
- **"Run all"**: Execute to completion

### Backend Support

```python
class WindlassRunner:
    def execute_until(self, phase_name: str) -> Echo:
        """Execute up to and including named phase, then pause."""
        pass

    def continue_from(self, checkpoint_id: str) -> Echo:
        """Resume from checkpoint."""
        pass
```

### Visual Feedback

- **Completed nodes**: Solid border, thumbnails visible
- **Running nodes**: Pulsing/animated border
- **Pending nodes**: Dashed/dim border

---

## Selective Image Context

To wire a specific image from a multi-output node:

```yaml
context:
  from: [generate_1]
  images:
    mode: "indexed"
    indices: [1]  # Use image at index 1
```

Or in templates:

```yaml
instructions: "Enhance: {{ outputs.generate_1.images[1] }}"
```

---

## File Structure

```
dashboard/frontend/src/
├── playground/
│   ├── PlaygroundPage.js              # Two-pane layout
│   ├── PlaygroundPage.module.css
│   │
│   ├── palette/
│   │   ├── palette.json               # Node definitions
│   │   ├── Palette.js                 # Draggable sidebar
│   │   ├── PaletteItem.js             # Single item
│   │   └── usePaletteCosts.js         # Avg costs from DB
│   │
│   ├── canvas/
│   │   ├── PlaygroundCanvas.js        # React Flow wrapper
│   │   ├── nodes/
│   │   │   ├── ImageNode.js           # Generator/transformer/tool
│   │   │   ├── ImagePortNode.js       # Output + layer mode
│   │   │   ├── PromptNode.js          # Text input
│   │   │   └── ComposeNode.js         # Backdrop + layer order
│   │   ├── hooks/
│   │   │   ├── useContainment.js      # Detect nodes inside compose
│   │   │   └── useLayerOrder.js       # Manage z-index
│   │   ├── nodeTypes.js
│   │   └── useCanvasState.js
│   │
│   └── execution/
│       ├── cascadeGenerator.js        # Graph → YAML
│       ├── useExecution.js            # Run, step, SSE
│       └── useSessionImages.js        # Fetch images
│
windlass/windlass/
├── eddies/
│   └── compose.py                     # image_compose tool
│
├── cascade.py                         # soundings mode: "all"
│                                      # phase type: "deterministic"
│
└── runner.py                          # execute_until(), continue_from()
                                       # indexed image context
```

---

## Implementation Phases

### Phase 1: Canvas Foundation

**Goal**: React Flow canvas with basic nodes, generates and runs cascades

**Tasks**:
1. Create `PlaygroundPage.js` with two-pane layout
2. Implement `palette.json` with 3-4 items (FLUX, SDXL, Compose)
3. Create `Palette.js` with drag-to-add
4. Implement `ImageNode.js` (unified configurable component)
5. Implement `PromptNode.js` (inline text editing)
6. Implement `ImagePortNode.js` (thumbnail display)
7. Create `cascadeGenerator.js` (graph → YAML)
8. Wire "Run" button → execute → SSE → thumbnail updates

**Deliverable**: Build prompt → generate → view flows, execute them

### Phase 2: Composition

**Goal**: ComposeNode with containment-based layering

**Tasks**:
1. Implement `ComposeNode.js` (resizable backdrop)
2. Implement `useContainment.js` (detect nodes inside bounds)
3. Update `ImagePortNode.js` with layer mode (hide chrome, show controls)
4. Implement layer order tracking and z-index
5. Add opacity/blend controls to ImagePortNode layer mode
6. Update `cascadeGenerator.js` to emit compose phases
7. Implement `image_compose` tool in `windlass/eddies/compose.py`

**Deliverable**: Full visual composition workflow

### Phase 3: Multi-Output + Soundings

**Goal**: Nodes that produce multiple images

**Tasks**:
1. Add `mode: "all"` to soundings in `cascade.py`
2. Add soundings toggle to `ImageNode.js`
3. Dynamic ImagePortNode spawning based on output count
4. Support `outputs.mode: "dynamic"` for HF tools
5. Add indexed image context resolution in `runner.py`

**Deliverable**: Soundings on generators, decompose tools, selective routing

### Phase 4: Stepping Execution

**Goal**: Incremental execution for interactive building

**Tasks**:
1. Add `execute_until(phase)` to runner
2. Implement "Run to here" context menu
3. Visual states (completed, running, pending)
4. Checkpoint integration

**Deliverable**: Step-through workflow building

### Phase 5: Persistence + Polish

**Goal**: Save/load, UX polish

**Tasks**:
1. Save graph state in `_playground` metadata
2. Load playground from cascade file
3. Implement `usePaletteCosts.js` for dynamic costs
4. Thumbnail caching
5. Undo/redo
6. Keyboard shortcuts (delete, run, etc.)

**Deliverable**: Complete, polished image playground

---

## Technical Notes

### React Flow

React Flow is already installed. Key patterns:

```jsx
import ReactFlow, {
  useNodesState,
  useEdgesState,
  addEdge,
  Controls,
  Background,
  MiniMap
} from 'reactflow';
import { NodeResizer } from '@reactflow/node-resizer';

const nodeTypes = {
  image: ImageNode,
  imagePort: ImagePortNode,
  prompt: PromptNode,
  compose: ComposeNode,
};

function PlaygroundCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      fitView
    >
      <Controls />
      <Background />
      <MiniMap />
    </ReactFlow>
  );
}
```

### SSE Updates

Existing pattern:

```javascript
const eventSource = new EventSource(
  `/api/events/stream?session_id=${sessionId}`
);

eventSource.addEventListener('message', (e) => {
  const event = JSON.parse(e.data);
  if (event.type === 'phase_complete') {
    refreshNodeThumbnails(event.data.phase_name);
  }
});
```

### Containment Detection

```javascript
function useContainment(nodeId, position) {
  const composeNodes = useNodes().filter(n => n.type === 'compose');

  return useMemo(() => {
    for (const compose of composeNodes) {
      const bounds = {
        left: compose.position.x,
        top: compose.position.y,
        right: compose.position.x + (compose.width || 400),
        bottom: compose.position.y + (compose.height || 300)
      };

      if (
        position.x >= bounds.left &&
        position.x <= bounds.right &&
        position.y >= bounds.top &&
        position.y <= bounds.bottom
      ) {
        return compose.id;
      }
    }
    return null;
  }, [position.x, position.y, composeNodes]);
}
```

---

## Summary

Image Playground is a natural extension of Windlass for visual image workflows:

1. **Everything is the graph** - No separate panels, no context switching
2. **React Flow is the compositor** - Drag nodes into ComposeNode, position = layer position
3. **Direct manipulation** - Move the node, move the layer
4. **No special cases** - Every node uses the same patterns
5. **Cascades as source of truth** - Visual state embedded in YAML, runs headlessly

The key breakthrough is using containment (spatial positioning) rather than explicit wiring for composition. This makes the visual layout directly correspond to the output—true direct manipulation.
