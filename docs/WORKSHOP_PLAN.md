# Windlass Workshop Mode - Implementation Plan

## Overview

A split-pane visual IDE for building and executing Windlass cascades:
- **Left Pane:** Block-based DSL editor (Tetris/Blockly-inspired drag-and-drop)
- **Right Pane:** Horizontal execution notebook (Bret Victor-style live visualization)

**Design Philosophy:**
- Blocks that only fit where they belong (typed slots)
- Monaco inline for text fields with Jinja2 autocomplete
- DAW-style multi-rail timeline for visualizing handoff branching
- Bidirectional YAML sync (blocks ↔ YAML)
- Desktop-first, responsive to reasonable breakpoints

---

## Implementation Progress

### Phase 1: Foundation & Core Structure ✅ COMPLETE

**Completed:**
- [x] Dependencies installed: `@dnd-kit/core`, `@dnd-kit/sortable`, `zustand`, `js-yaml`, `react-split`, `immer`
- [x] Directory structure created under `workshop/`
- [x] Zustand store (`workshopStore.js`) with full cascade CRUD, YAML sync, execution tracking
- [x] `WorkshopPage.js` with resizable split pane and toolbar (new/open/save/export/run)
- [x] `BlockEditor.js` container with DnD context and collapsible palette
- [x] `CascadeCanvas.js` with header fields (cascade_id, description, memory) and placeholder slots
- [x] `PhasesRail.js` with sortable phase list and visual connectors
- [x] `PhaseBlock.js` with inline drawers (Execution, Soundings, Rules, Flow)
- [x] `BlockPalette.js` visual reference (drag-to-canvas in Phase 2)
- [x] `YamlPanel.js` with syntax highlighting and copy button
- [x] `ExecutionNotebook.js` placeholder with phase columns
- [x] Routing: `/#/workshop` route and "Workshop" button in CascadesView

**Files Created:**
```
workshop/
├── WorkshopPage.js + .css
├── stores/workshopStore.js
├── editor/
│   ├── BlockEditor.js + .css
│   ├── BlockPalette.js + .css
│   ├── CascadeCanvas.js + .css
│   ├── PhasesRail.js + .css
│   └── blocks/PhaseBlock.js + .css
├── yaml/YamlPanel.js + .css
└── notebook/ExecutionNotebook.js + .css
```

**Learnings & Refinements:**
- Drawer implementation works well inline within PhaseBlock (no need for separate drawer components)
- Phase reordering uses DnD Kit's sortable with visual connectors between phases
- YAML sync is already bidirectional in the store - YamlPanel is read-only view for now
- Instructions textarea works for MVP; Monaco upgrade deferred to Phase 3

---

## Architecture

### Component Hierarchy

```
WorkshopPage
├── WorkshopHeader (toolbar: open, save, export, run controls)
├── SplitPane (resizable)
│   ├── BlockEditor (left)
│   │   ├── BlockPalette (collapsible sidebar)
│   │   ├── CascadeCanvas
│   │   │   ├── CascadeHeader (cascade_id, description, memory)
│   │   │   ├── InputsSchemaSlot
│   │   │   │   └── InputParamBlock[]
│   │   │   ├── ValidatorsSlot
│   │   │   │   └── ValidatorBlock[]
│   │   │   └── PhasesRail
│   │   │       └── PhaseBlock[]
│   │   │           ├── InstructionsField (Monaco)
│   │   │           └── ConfigDrawers (collapsible)
│   │   │               ├── ExecutionDrawer
│   │   │               ├── SoundingsDrawer
│   │   │               │   └── SoundingsBlock
│   │   │               │       └── ReforgeBlock (optional)
│   │   │               ├── RulesDrawer
│   │   │               ├── ValidationDrawer
│   │   │               │   └── WardsBlock
│   │   │               │       └── WardBlock[]
│   │   │               ├── ContextDrawer
│   │   │               │   └── ContextSourceBlock[]
│   │   │               ├── FlowDrawer
│   │   │               │   └── HandoffChip[]
│   │   │               ├── HITLDrawer
│   │   │               │   └── HumanInputBlock
│   │   │               └── AdvancedDrawer
│   │   └── YamlPanel (collapsible, read-only with copy)
│   │
│   └── ExecutionNotebook (right)
│       ├── NotebookHeader (session info, cost, duration)
│       ├── RailTimeline (DAW-style horizontal scroll)
│       │   └── PhaseRail[] (one per "track", phases can branch)
│       │       └── PhaseColumn[]
│       │           ├── PhaseColumnHeader
│       │           ├── SoundingsGrid
│       │           │   └── SoundingCard[]
│       │           ├── ReforgeSection
│       │           │   └── ReforgeStepRow[]
│       │           │       └── RefinementCard[]
│       │           └── EvaluatorReasoning
│       └── DetailPanel (expanded sounding/output view)
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           WORKSHOP STATE                                 │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  cascadeState: CascadeConfig  (mirrors YAML structure exactly)   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│              ┌───────────────┼───────────────┐                          │
│              ▼               ▼               ▼                          │
│     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│     │ BlockEditor │  │  YamlPanel  │  │   Backend   │                  │
│     │  (visual)   │  │  (text)     │  │  (execute)  │                  │
│     └─────────────┘  └─────────────┘  └─────────────┘                  │
│              │               │               │                          │
│              └───────────────┴───────────────┘                          │
│                              │                                           │
│                              ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  executionState: { sessionId, phases: PhaseResult[], status }    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│                              ▼                                           │
│                    ┌─────────────────┐                                  │
│                    │ ExecutionNotebook│                                  │
│                    └─────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### State Management

Using **Zustand** for lightweight, performant state:

```typescript
// stores/workshopStore.ts
interface WorkshopStore {
  // Cascade definition (syncs with YAML)
  cascade: CascadeConfig | null;
  setCascade: (cascade: CascadeConfig) => void;
  updatePhase: (phaseIndex: number, updates: Partial<PhaseConfig>) => void;
  addPhase: (phase: PhaseConfig, afterIndex?: number) => void;
  removePhase: (phaseIndex: number) => void;
  reorderPhases: (fromIndex: number, toIndex: number) => void;

  // UI state
  selectedPhaseIndex: number | null;
  expandedDrawers: Record<string, string[]>; // phaseId -> drawer names
  yamlPanelOpen: boolean;

  // Execution state
  sessionId: string | null;
  executionStatus: 'idle' | 'running' | 'completed' | 'error';
  phaseResults: Map<string, PhaseResult>;

  // Actions
  runCascade: () => Promise<void>;
  loadFromYaml: (yaml: string) => void;
  exportToYaml: () => string;
}
```

---

## Directory Structure

```
dashboard/frontend/src/
├── workshop/
│   ├── WorkshopPage.js              # Main page component
│   ├── WorkshopPage.css
│   │
│   ├── stores/
│   │   └── workshopStore.js         # Zustand store
│   │
│   ├── editor/
│   │   ├── BlockEditor.js           # Main editor container
│   │   ├── BlockEditor.css
│   │   ├── BlockPalette.js          # Draggable block templates
│   │   ├── BlockPalette.css
│   │   ├── CascadeCanvas.js         # Drop zone for cascade structure
│   │   ├── CascadeCanvas.css
│   │   │
│   │   ├── blocks/
│   │   │   ├── PhaseBlock.js        # Phase container with drawers
│   │   │   ├── PhaseBlock.css
│   │   │   ├── ValidatorBlock.js
│   │   │   ├── InputParamBlock.js
│   │   │   ├── SoundingsBlock.js
│   │   │   ├── ReforgeBlock.js
│   │   │   ├── RulesBlock.js
│   │   │   ├── WardsBlock.js
│   │   │   ├── WardBlock.js
│   │   │   ├── ContextBlock.js
│   │   │   ├── ContextSourceBlock.js
│   │   │   ├── HandoffBlock.js
│   │   │   ├── HumanInputBlock.js
│   │   │   └── index.js             # Block registry
│   │   │
│   │   ├── fields/
│   │   │   ├── MonacoField.js       # Inline Monaco wrapper
│   │   │   ├── MonacoField.css
│   │   │   ├── ModelSelect.js       # Model dropdown with search
│   │   │   ├── TackleChips.js       # Tool selection chips
│   │   │   ├── EnumSelect.js        # Generic enum dropdown
│   │   │   ├── NumberInput.js       # Styled number input
│   │   │   ├── BooleanToggle.js     # Checkbox/switch
│   │   │   └── ChipArray.js         # Generic chip array input
│   │   │
│   │   ├── drawers/
│   │   │   ├── DrawerContainer.js   # Collapsible drawer wrapper
│   │   │   ├── ExecutionDrawer.js
│   │   │   ├── SoundingsDrawer.js
│   │   │   ├── RulesDrawer.js
│   │   │   ├── ValidationDrawer.js
│   │   │   ├── ContextDrawer.js
│   │   │   ├── FlowDrawer.js
│   │   │   ├── HITLDrawer.js
│   │   │   └── AdvancedDrawer.js
│   │   │
│   │   └── dnd/
│   │       ├── DndContext.js        # DnD Kit provider setup
│   │       ├── Draggable.js         # Generic draggable wrapper
│   │       ├── Droppable.js         # Generic droppable wrapper
│   │       ├── SortableList.js      # Reorderable list (phases)
│   │       └── constraints.js       # Block type constraint logic
│   │
│   ├── yaml/
│   │   ├── YamlPanel.js             # Collapsible YAML view
│   │   ├── YamlPanel.css
│   │   ├── yamlSync.js              # Bidirectional YAML ↔ state
│   │   └── cascadeSchema.js         # JSON Schema for validation
│   │
│   ├── notebook/
│   │   ├── ExecutionNotebook.js     # Main notebook container
│   │   ├── ExecutionNotebook.css
│   │   ├── NotebookHeader.js        # Session info, controls
│   │   ├── RailTimeline.js          # DAW-style multi-rail container
│   │   ├── RailTimeline.css
│   │   ├── PhaseRail.js             # Single horizontal track
│   │   ├── PhaseColumn.js           # Phase execution results
│   │   ├── PhaseColumn.css
│   │   ├── SoundingCard.js          # Individual sounding result
│   │   ├── SoundingCard.css
│   │   ├── ReforgeSection.js        # Reforge iterations display
│   │   ├── RefinementCard.js
│   │   ├── EvaluatorReasoning.js
│   │   ├── DetailPanel.js           # Expanded view sidebar
│   │   ├── DetailPanel.css
│   │   │
│   │   └── outputs/
│   │       ├── OutputRenderer.js    # Dispatcher by output type
│   │       ├── MarkdownOutput.js
│   │       ├── ChartOutput.js
│   │       ├── TableOutput.js
│   │       ├── CodeOutput.js
│   │       └── JsonTreeOutput.js
│   │
│   └── hooks/
│       ├── useWorkshopStore.js      # Store selector hooks
│       ├── useCascadeExecution.js   # SSE subscription for execution
│       ├── useYamlSync.js           # Bidirectional sync hook
│       ├── useJinjaAutocomplete.js  # Monaco autocomplete provider
│       └── useBlockConstraints.js   # DnD constraint validation
│
└── ... (existing components)
```

---

## Implementation Phases

### Phase 1: Foundation & Core Structure
**Goal:** Basic split-pane layout, state management, phase rail

**Tasks:**
1. Create `WorkshopPage.js` with resizable split pane (use `react-split`)
2. Set up Zustand store with basic cascade state
3. Install dependencies: `@dnd-kit/core`, `@dnd-kit/sortable`, `zustand`, `js-yaml`, `react-split`
4. Create `CascadeCanvas` with header fields (cascade_id, description, memory)
5. Create `PhasesRail` - a vertical sortable list
6. Create basic `PhaseBlock` - name field + placeholder drawers
7. Wire up reorder functionality with DnD Kit

**Deliverable:** Can create empty phases, reorder them, see basic structure

### Phase 2: Block Palette & Enhanced Fields ✅ COMPLETE
**Goal:** Draggable palette blocks, enhanced field components, validation drawer

**Completed:**
- [x] BlockPalette visual structure created
- [x] Drawer collapse/expand working in PhaseBlock
- [x] ExecutionDrawer with tackle/model text inputs
- [x] RulesDrawer with max_turns, loop_until, loop_until_silent
- [x] FlowDrawer with handoffs text input
- [x] Wire palette drag → canvas drop for new phases (DnD from palette to PhasesRail)
- [x] `TackleChips` component - visual chips with autocomplete from `/api/available-tools`
- [x] `ModelSelect` component - searchable dropdown from `/api/available-models`
- [x] `ValidationDrawer` - wards configuration (pre/post/turn with validator selection)
- [x] `ContextDrawer` - context.from configuration with phase selection chips

**Files Created:**
```
workshop/editor/components/
├── TackleChips.js + .css    # Tool selection with autocomplete
└── ModelSelect.js + .css    # Searchable model dropdown
```

**Updates to PhaseBlock.js:**
- ExecutionDrawer now uses TackleChips and ModelSelect
- Added ValidationDrawer (wards: pre/post/turn with mode selection)
- Added ContextDrawer (context.from with phase chips + direct toggle)
- All 6 drawers now functional

**Updates to BlockPalette.js:**
- Palette blocks now draggable with DnD Kit
- DragOverlay shows visual feedback during drag

**Updates to BlockEditor.js:**
- DnD context moved to wrap both palette and canvas
- Handles palette drops to create phases or open drawers

**Updates to PhasesRail.js:**
- Added droppable zone with visual feedback
- Shows drop indicator when dragging phase over

**Deferred to Later:**
- Multi-model support in SoundingsDrawer (Phase 4)
- API endpoints `/api/available-tools` and `/api/available-models` (using fallback data)

**Deliverable:** Full drawer configuration with proper field components

### Phase 3: Monaco Integration & Text Fields
**Goal:** Inline Monaco editors with Jinja2 support

**Tasks:**
1. Create `MonacoField` wrapper component
2. Configure Monaco for YAML + custom Jinja2 tokenization
3. Implement autocomplete provider for `{{ input.`, `{{ outputs.`, `{{ state.`
4. Add expand-to-modal functionality for long prompts
5. Style Monaco to match theme (dark background, ocean accents)
6. Wire `instructions` field in PhaseBlock
7. Add character count / token estimate display

**Deliverable:** Rich text editing for instructions with autocomplete

### Phase 4: Nested Config Blocks
**Goal:** Soundings, Reforge, Wards, Context blocks

**Tasks:**
1. Create `SoundingsDrawer` with inline `SoundingsBlock`
2. Create `SoundingsBlock` - factor, mode, evaluator_instructions, models array
3. Create `ReforgeBlock` (nested inside SoundingsBlock) - steps, honing_prompt
4. Create `ValidationDrawer` with `WardsBlock`
5. Create `WardBlock` - validator, mode, max_attempts
6. Create `ContextDrawer` with `ContextSourceBlock`
7. Create `ContextSourceBlock` - phase select, include checkboxes
8. Implement nested DnD constraints (reforge only in soundings slot)

**Deliverable:** Full phase configuration including soundings/reforge

### Phase 5: Validators & Inputs Schema
**Goal:** Top-level cascade config blocks

**Tasks:**
1. Create `InputsSchemaSlot` with `InputParamBlock` children
2. Create `InputParamBlock` - name, description fields
3. Create `ValidatorsSlot` with `ValidatorBlock` children
4. Create `ValidatorBlock` - name, instructions (Monaco), model
5. Wire validators to `loop_until` dropdown options in RulesDrawer
6. Add cascade-level settings (token_budget, tool_caching)

**Deliverable:** Complete cascade structure editing

### Phase 6: YAML Bidirectional Sync
**Goal:** Parse existing YAML, export to YAML, live preview

**Tasks:**
1. Create `yamlSync.js` - parse YAML to state, stringify state to YAML
2. Create `YamlPanel` - collapsible Monaco in read mode
3. Add "Copy YAML" button
4. Implement file open (parse YAML file → blocks)
5. Implement file save (blocks → YAML file)
6. Add validation errors display (schema violations)
7. Handle edge cases (comments, unknown fields)

**Deliverable:** Can open existing cascades, edit, export

### Phase 7: Execution Notebook - Basic Structure
**Goal:** Horizontal scroll timeline with phase columns

**Tasks:**
1. Create `ExecutionNotebook` container with horizontal scroll
2. Create `NotebookHeader` - run button, session info, cost/duration
3. Create `PhaseColumn` - header + placeholder content
4. Connect to existing `/api/run-cascade` endpoint
5. Subscribe to SSE for real-time updates
6. Display phase status (pending, running, completed, error)
7. Implement scroll-to-phase when editor phase clicked

**Deliverable:** Can run cascade and see phase status timeline

### Phase 8: Sounding Cards & Results
**Goal:** Visualize soundings within phase columns

**Tasks:**
1. Create `SoundingCard` - compact view with cost, duration, winner badge
2. Create `SoundingsGrid` - arrange cards in rows
3. Create expanded `SoundingCard` view - prompt, output, tool calls
4. Create `ReforgeSection` - collapsible, step rows
5. Create `RefinementCard` - similar to SoundingCard
6. Create `EvaluatorReasoning` - collapsible markdown view
7. Add mutation badge display (rewrite, augment, approach)
8. Connect to `/api/soundings-tree/:session_id` endpoint

**Deliverable:** Full soundings visualization within phases

### Phase 9: DAW-Style Multi-Rail Timeline
**Goal:** Branching handoffs visualized as parallel rails

**Tasks:**
1. Analyze handoff graph to determine rail assignments
2. Create `RailTimeline` - manages multiple `PhaseRail` tracks
3. Implement rail layout algorithm:
   - Main flow stays on rail 0
   - Handoff to non-next phase → new rail above/below
   - Visual connectors between rails at handoff points
4. Style rails with track separators (like DAW lanes)
5. Add rail labels (auto-generated or from handoff descriptions)
6. Animate handoff transitions during execution

**Deliverable:** Complex cascades with branching show parallel rails

### Phase 10: Output Renderers & Detail Panel
**Goal:** Rich output visualization

**Tasks:**
1. Create `OutputRenderer` dispatcher (detect type from content)
2. Create `MarkdownOutput` - render with RichMarkdown
3. Create `ChartOutput` - display images, click to expand
4. Create `TableOutput` - SQL results with sorting/filtering
5. Create `CodeOutput` - syntax highlighted
6. Create `JsonTreeOutput` - collapsible tree
7. Create `DetailPanel` - slide-out panel for expanded view
8. Add "View in Editor" link from DetailPanel → highlight source phase

**Deliverable:** Rich visualization of all output types

### Phase 11: Polish & Integration
**Goal:** Smooth UX, error handling, edge cases

**Tasks:**
1. Add keyboard shortcuts (Cmd+S save, Cmd+R run, etc.)
2. Add undo/redo for block operations
3. Implement autosave to localStorage
4. Add loading states and skeletons
5. Handle execution errors gracefully
6. Add phase validation indicators (missing required fields)
7. Responsive breakpoints (hide palette on narrow, stack panes)
8. Add welcome state for empty workspace
9. Performance optimization (virtualize long phase lists)
10. Write component tests for critical paths

**Deliverable:** Production-ready Workshop Mode

---

## Key Technical Decisions

### DnD Kit Configuration

```javascript
// dnd/constraints.js
export const BLOCK_TYPES = {
  PHASE: 'phase',
  VALIDATOR: 'validator',
  INPUT_PARAM: 'input_param',
  SOUNDINGS: 'soundings',
  REFORGE: 'reforge',
  WARD: 'ward',
  CONTEXT_SOURCE: 'context_source',
  HANDOFF: 'handoff',
};

export const SLOT_ACCEPTS = {
  'phases-rail': [BLOCK_TYPES.PHASE],
  'validators-slot': [BLOCK_TYPES.VALIDATOR],
  'inputs-schema-slot': [BLOCK_TYPES.INPUT_PARAM],
  'soundings-slot': [BLOCK_TYPES.SOUNDINGS],
  'reforge-slot': [BLOCK_TYPES.REFORGE],
  'wards-slot': [BLOCK_TYPES.WARD],
  'context-slot': [BLOCK_TYPES.CONTEXT_SOURCE],
  'handoffs-slot': [BLOCK_TYPES.HANDOFF],
};

export function canDrop(dragType, dropSlot) {
  const accepts = SLOT_ACCEPTS[dropSlot];
  return accepts?.includes(dragType) ?? false;
}
```

### Monaco Jinja2 Tokenization

```javascript
// fields/jinjaTokenProvider.js
export const jinjaTokenProvider = {
  tokenizer: {
    root: [
      [/\{\{/, { token: 'delimiter.jinja', next: '@jinjaExpr' }],
      [/\{%/, { token: 'delimiter.jinja', next: '@jinjaTag' }],
      [/./, 'string'],
    ],
    jinjaExpr: [
      [/\}\}/, { token: 'delimiter.jinja', next: '@root' }],
      [/input\.[a-zA-Z_][a-zA-Z0-9_]*/, 'variable.input'],
      [/outputs\.[a-zA-Z_][a-zA-Z0-9_]*/, 'variable.outputs'],
      [/state\.[a-zA-Z_][a-zA-Z0-9_]*/, 'variable.state'],
      [/sounding_index|sounding_factor|is_sounding/, 'variable.sounding'],
      [/[a-zA-Z_][a-zA-Z0-9_]*/, 'identifier'],
      [/\./, 'delimiter'],
    ],
    jinjaTag: [
      [/%\}/, { token: 'delimiter.jinja', next: '@root' }],
      [/if|else|elif|endif|for|endfor/, 'keyword'],
      [/./, 'string'],
    ],
  },
};
```

### DAW Rail Layout Algorithm

```javascript
// notebook/railLayout.js
export function computeRailLayout(phases) {
  const rails = [[]]; // Start with one rail
  const phaseToRail = new Map();
  const phaseIndex = new Map(phases.map((p, i) => [p.name, i]));

  for (let i = 0; i < phases.length; i++) {
    const phase = phases[i];
    const handoffs = phase.handoffs || [];

    // Find which rail this phase should be on
    let targetRail = 0;
    if (i > 0) {
      const prevPhase = phases[i - 1];
      // If previous phase handed off to us explicitly, stay on its rail
      if (prevPhase.handoffs?.includes(phase.name)) {
        targetRail = phaseToRail.get(prevPhase.name) || 0;
      }
    }

    phaseToRail.set(phase.name, targetRail);

    // Ensure rail exists
    while (rails.length <= targetRail) {
      rails.push([]);
    }
    rails[targetRail].push(phase);

    // Handle branching handoffs (handoff to non-sequential phase)
    for (const handoff of handoffs) {
      const handoffIdx = phaseIndex.get(handoff);
      if (handoffIdx !== undefined && handoffIdx !== i + 1) {
        // This is a branch - assign to a different rail
        const branchRail = findAvailableRail(rails, handoffIdx);
        phaseToRail.set(handoff, branchRail);
      }
    }
  }

  return { rails, phaseToRail };
}

function findAvailableRail(rails, fromPosition) {
  // Find a rail that doesn't have a phase at this position
  for (let r = 0; r < rails.length; r++) {
    if (!rails[r].some((_, idx) => idx >= fromPosition)) {
      return r;
    }
  }
  // Need a new rail
  return rails.length;
}
```

### YAML Sync Edge Cases

```javascript
// yaml/yamlSync.js
import yaml from 'js-yaml';

export function parseYamlToCascade(yamlString) {
  try {
    const raw = yaml.load(yamlString);

    // Handle both .yaml and .json structures
    // Normalize field names (e.g., context.from_ → context.from)
    const cascade = normalizeFieldNames(raw);

    // Validate against schema
    const errors = validateCascadeSchema(cascade);
    if (errors.length > 0) {
      return { cascade: null, errors };
    }

    return { cascade, errors: [] };
  } catch (e) {
    return { cascade: null, errors: [e.message] };
  }
}

export function cascadeToYaml(cascade) {
  // Handle Pydantic aliases (from_ → from)
  const normalized = denormalizeForYaml(cascade);

  return yaml.dump(normalized, {
    indent: 2,
    lineWidth: 120,
    noRefs: true,
    sortKeys: false, // Preserve field order
  });
}

function normalizeFieldNames(obj) {
  if (Array.isArray(obj)) {
    return obj.map(normalizeFieldNames);
  }
  if (obj && typeof obj === 'object') {
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
      // Handle 'from' → 'from_' for context (Pydantic reserved)
      const normalizedKey = key === 'from' ? 'from_' : key;
      result[normalizedKey] = normalizeFieldNames(value);
    }
    return result;
  }
  return obj;
}
```

---

## CSS Theme Integration

Extend existing `theme.css` variables:

```css
/* workshop/WorkshopPage.css */

.workshop-page {
  background: var(--bg-main);
  height: 100vh;
  display: flex;
  flex-direction: column;
}

/* Block colors by type */
.block--phase {
  border-color: var(--ocean-primary);
}

.block--soundings {
  border-color: var(--slate-blue);
}

.block--reforge {
  border-color: var(--slate-blue-light);
}

.block--validator {
  border-color: var(--ocean-teal);
}

.block--ward {
  border-color: var(--compass-brass);
}

/* Slot drop zones */
.slot--can-drop {
  border-color: var(--success-green);
  box-shadow: 0 0 8px var(--success-green);
}

.slot--cannot-drop {
  border-color: var(--bloodaxe-red);
}

/* DAW Rails */
.rail-timeline {
  background: var(--bg-card);
}

.phase-rail {
  border-bottom: 1px solid var(--storm-cloud);
}

.phase-rail:nth-child(odd) {
  background: rgba(107, 127, 187, 0.05); /* slate-blue tint */
}

/* Phase column states */
.phase-column--pending {
  opacity: 0.5;
}

.phase-column--running {
  border-color: var(--compass-brass);
  animation: pulse 2s infinite;
}

.phase-column--completed {
  border-color: var(--success-green);
}

.phase-column--error {
  border-color: var(--bloodaxe-red);
}
```

---

## Dependencies to Add

```json
{
  "dependencies": {
    "@dnd-kit/core": "^6.1.0",
    "@dnd-kit/sortable": "^8.0.0",
    "@dnd-kit/utilities": "^3.2.2",
    "zustand": "^4.5.0",
    "js-yaml": "^4.1.0",
    "react-split": "^2.0.14",
    "immer": "^10.0.0"
  }
}
```

Note: `@monaco-editor/react` is likely already installed for existing dashboard features.

---

## API Endpoints Required

**Existing (should work as-is):**
- `POST /api/run-cascade` - Execute cascade
- `GET /api/events/stream` - SSE for execution updates
- `GET /api/soundings-tree/:session_id` - Sounding results
- `GET /api/cascade-definitions` - List available cascades

**New endpoints needed:**
- `GET /api/available-tools` - List all registered tackle for autocomplete
- `GET /api/available-models` - List available models for dropdown
- `POST /api/validate-cascade` - Server-side validation before run

---

## Testing Strategy

**Unit Tests:**
- `yamlSync.js` - Parse/stringify round-trip
- `constraints.js` - Block type validation
- `railLayout.js` - DAW layout algorithm

**Integration Tests:**
- Load existing cascade YAML → verify blocks render correctly
- Edit blocks → verify YAML updates
- Run cascade → verify notebook updates via SSE

**E2E Tests (Playwright):**
- Create new cascade from scratch
- Drag phases, reorder
- Configure soundings, run, view results

---

## Open Items / Future Enhancements

1. **Templates Gallery** - Pre-built cascade templates to start from
2. **Version History** - Git-like tracking of cascade changes
3. **Collaborative Editing** - Real-time multi-user editing (would need backend)
4. **Phase Isolation Testing** - Run single phase with mocked inputs
5. **Cost Estimation** - Preview estimated cost before running
6. **Diff View** - Compare two cascade versions or sessions
7. **Export to Python** - Generate Python code from cascade definition

---

## Success Criteria

1. Can open any existing cascade YAML and see it as blocks
2. Can create a new cascade from scratch using only blocks
3. Can configure soundings with reforge and see parallel execution
4. YAML export produces valid, runnable cascade files
5. Execution notebook updates in real-time during runs
6. DAW rails correctly visualize branching handoffs
7. Performance: <100ms response for drag/drop operations
8. Works on screens 1280px+ wide
