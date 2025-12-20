# Playground Phase Node Implementation Plan

## Overview

Add a new "Agent" category to the Image Playground palette with an "LLM Phase" node that embeds arbitrary cascade phases via a Monaco YAML editor. This transforms the playground from an image-only pipeline builder into a full visual cascade editor.

---

## Key Concepts

### What This Enables

1. **Prompt Enhancement Pipeline**
   ```
   [Prompt] → [LLM: Enhance] → [FLUX Generator]
              "Make more descriptive"
   ```

2. **Multi-Step Text Processing**
   ```
   [Prompt] → [LLM: Research] → [LLM: Summarize] → [LLM: Format]
   ```

3. **Hybrid Image+Text Workflows**
   ```
   [Prompt] → [FLUX] → [LLM: Describe] → [Upscaler]
                       "What do you see?"    (uses description)
   ```

4. **Image Analysis**
   ```
   [FLUX] → [LLM: Analyze] → [LLM: Critique] → ...
            (vision model)
   ```

### Design Philosophy

- **YAML-first**: The node IS a Monaco editor for phase YAML. Full cascade power.
- **Dynamic inputs**: Parse `{{ input.X }}` from YAML to create input handles automatically.
- **Smart cascade generation**: Detect source node type (prompt vs phase) and wire context injection automatically.
- **No new handle types**: Use existing `text` (green) and `image` (purple) handles. Handle complexity in cascade generation.

---

## Technical Design

### PhaseNode Handles

**Inputs (left side):**
- `image-in` (purple) - For vision models analyzing images
- Dynamic `text-in-X` (green) - One per `{{ input.X }}` discovered in YAML

**Output (right side):**
- `text-out` (green) - The phase's text output

### Input Discovery

Parse YAML instructions for Jinja2 input references:

```javascript
const INPUT_PATTERN = /\{\{\s*input\.(\w+)(?:\s*\|[^}]*)?\s*\}\}/g;

function discoverInputs(yamlString) {
  const matches = yamlString.matchAll(INPUT_PATTERN);
  return [...new Set([...matches].map(m => m[1]))];
}

// Example:
// "Enhance: {{ input.prompt }}" → ["prompt"]
// "{{ input.style }} - {{ input.subject }}" → ["style", "subject"]
```

### Cascade Generation Logic

When generating cascade YAML, handle connections based on source node type:

```javascript
// For image nodes receiving text input
const textEdge = edges.find(e => e.target === node.id && e.targetHandle === 'text-in');
const sourceNode = nodeMap.get(textEdge.source);

if (sourceNode.type === 'prompt') {
  // Standard cascade input
  phase.instructions = `{{ input.${getNodeName(sourceNode)} }}`;
} else if (sourceNode.type === 'phase') {
  // Phase output via context injection
  phase.context = {
    from: [{ phase: getNodeName(sourceNode), include: ["output"] }]
  };
  phase.instructions = `{{ outputs.${getNodeName(sourceNode)} }}`;
}
```

For phase→phase connections, add `context.from` to downstream phase so it sees upstream output in conversation context.

### Node UI Layout

```
┌─────────────────────────────────────┐
│ ⚙️ enhance_prompt            [idle] │  ← Header: name + status
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ name: enhance_prompt           │ │
│ │ instructions: |                │ │
│ │   Enhance this prompt for      │ │  ← Monaco YAML editor
│ │   image gen: {{ input.txt }}   │ │
│ │ model: gpt-4o-mini             │ │
│ │ rules:                         │ │
│ │   max_turns: 1                 │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ Output: "A vibrant cyberpunk..."    │  ← Output preview (after execution)
└─────────────────────────────────────┘

Left handles:                         Right handle:
  ○ image-in (purple, top)             ○ text-out (green)
  ○ txt (green, dynamic)
```

### Default Phase Template

```yaml
name: llm_transform
instructions: |
  {{ input.prompt }}
model: google/gemini-2.5-flash-lite
rules:
  max_turns: 1
```

---

## Implementation Phases

### Phase 1: Palette & Basic Node

**Files to modify/create:**
- `dashboard/frontend/src/playground/palette/palette.json` - Add Agent category
- `dashboard/frontend/src/playground/canvas/nodes/PhaseNode.js` - New component
- `dashboard/frontend/src/playground/canvas/nodes/PhaseNode.css` - Styling
- `dashboard/frontend/src/playground/canvas/PlaygroundCanvas.js` - Register node type
- `dashboard/frontend/src/playground/stores/playgroundStore.js` - Add phase node support

**Tasks:**
1. Add "Agent" category to palette.json with "LLM Phase" item (cyan/teal color, gear icon)
2. Create PhaseNode component with:
   - Monaco editor for YAML (dark theme, yaml language)
   - Header showing phase name and status
   - Resizable via existing useNodeResize hook
   - Static `text-out` handle on right
3. Register `phase` node type in PlaygroundCanvas
4. Add `addPhaseNode` action to store

### Phase 2: YAML Parsing & Dynamic Handles

**Tasks:**
5. On YAML change (debounced):
   - Parse with js-yaml
   - Validate: show inline error if invalid
   - Extract `name` field for header display
6. Discover `{{ input.X }}` patterns in instructions
7. Generate dynamic `text-in-X` handles based on discovered inputs
8. Update handle positions when inputs change

### Phase 3: Cascade Generation

**Modify:** `playgroundStore.js` → `generateCascade()`

**Tasks:**
9. Handle phase nodes in topological sort
10. For phase nodes:
    - Parse YAML and use as phase definition
    - Override `name` with node's custom name if set
11. For connections TO phase nodes:
    - If from prompt: maps to `{{ input.X }}` (already in YAML)
    - If from another phase: add `context.from` with `include: ["output"]`
12. For connections FROM phase nodes to image nodes:
    - Add `context.from` to image phase
    - Set instructions to `{{ outputs.${phaseName} }}`

### Phase 4: Image Input for Vision

**Tasks:**
13. Add `image-in` handle to PhaseNode (purple, top-left)
14. Update cascade generation:
    - If image node connects to phase's image-in
    - Add `context.from` with `include: ["images"]`
    - Vision models will see the image in context

### Phase 5: Execution & Output Display

**Tasks:**
15. Track phase execution status (idle/running/completed/error)
16. Display status indicator in header (same as ImageNode)
17. After completion, show output preview:
    - Truncated text (first ~100 chars)
    - Expandable or tooltip for full output
18. Store output in node data for display

### Phase 6: Validation & Polish

**Tasks:**
19. Light YAML validation:
    - Check `name` field exists
    - Check `instructions` field exists
    - Show warning icon if missing
20. Handle edge cases:
    - Empty YAML
    - Rename updates references
    - Delete node cleans up edges

---

## File Structure

```
dashboard/frontend/src/playground/
├── palette/
│   └── palette.json          # Add Agent category
├── canvas/
│   ├── PlaygroundCanvas.js   # Register phase node type
│   └── nodes/
│       ├── PhaseNode.js      # NEW - Monaco YAML editor node
│       └── PhaseNode.css     # NEW - Styling
└── stores/
    └── playgroundStore.js    # Phase node support + cascade gen updates
```

---

## Palette Configuration

Add to `palette.json`:

```json
{
  "id": "llm_phase",
  "name": "LLM Phase",
  "category": "agent",
  "nodeType": "phase",
  "icon": "mdi:cog-play",
  "color": "#06b6d4",
  "description": "Custom LLM phase with full YAML control"
}
```

Category metadata:
```json
{
  "id": "agent",
  "name": "Agent",
  "icon": "mdi:robot",
  "color": "#06b6d4"
}
```

---

## Connection Validation Updates

Update `isValidConnection` in PlaygroundCanvas.js:

```javascript
const isValidConnection = useCallback((connection) => {
  const { sourceHandle, targetHandle } = connection;

  // Extract types: 'text-out' → 'text', 'image-in' → 'image'
  const sourceType = sourceHandle?.split('-')[0];
  const targetType = targetHandle?.split('-')[0];

  // Dynamic handles like 'text-in-prompt' → 'text'
  const normalizedTarget = targetType === 'text' ? 'text' : targetType;

  // Allow: text→text, image→image
  if (sourceType && normalizedTarget) {
    return sourceType === normalizedTarget;
  }

  return true;
}, []);
```

---

## Testing Scenarios

1. **Prompt → Phase → Image**: Basic enhancement pipeline
2. **Prompt → Phase → Phase → Image**: Multi-step processing
3. **Phase with multiple inputs**: `{{ input.style }}` + `{{ input.subject }}`
4. **Image → Phase (vision)**: Analyze generated image
5. **Rename phase**: Verify cascade references update
6. **Invalid YAML**: Error display and recovery
7. **Save as Tool**: Phase nodes included correctly

---

## Future Enhancements (Not in MVP)

- **Tool phases**: Deterministic tool-calling phases
- **Sounding phases**: Multiple attempts with evaluation
- **Ward phases**: Validation gates
- **Phase templates**: Quick-add common patterns
- **Collapse/expand**: Hide YAML, show just header
- **Multiple context inputs**: Merge from several upstream phases

---

## Dependencies

- `@monaco-editor/react` - Already installed
- `js-yaml` - Already installed
- Existing `useNodeResize` hook
- Existing node styling patterns from ImageNode/PromptNode
