# CLAUDE.md - Windlass UI

This file provides guidance for working with the Windlass UI codebase.

## Project Overview

**Windlass UI** is a sleek dark mode cascade explorer and analytics dashboard for the Windlass agent framework. It provides real-time visualization of cascade executions, cost tracking, and performance metrics.

**Key Philosophy**: Metrics-driven, visually informative, space-conscious design that shows cascade complexity at a glance.

---

## Quick Start

### Running the UI

```bash
cd extras/ui
./start.sh
```

**Opens at:** `http://localhost:3000`
**Backend API:** `http://localhost:5001`

### Manual Start

```bash
# Terminal 1: Backend
cd extras/ui/backend
python app.py

# Terminal 2: Frontend
cd extras/ui/frontend
npm install  # First time only
npm start
```

---

## Architecture

### Tech Stack

**Backend:**
- Flask - Web server
- DuckDB - Analytics queries on Parquet/JSONL
- Flask-CORS - Cross-origin support
- Server-Sent Events (SSE) - Real-time updates

**Frontend:**
- React - UI framework
- @iconify/react - Icon library (Material Design Icons)
- CSS Modules - Component styling
- Fetch API - Data loading
- EventSource - SSE client

**Data Sources:**
- `logs/echoes/*.parquet` - Structured analytics data
- `logs/echoes_jsonl/*.jsonl` - Real-time JSON logs
- `graphs/*.json` - Execution structure
- `windlass/examples/*.json` - Cascade definitions

---

## Design System

### Color Palette (Dark Mode + Bright Pastels)

```css
--bg-pure-black: #0a0a0a;        /* Background */
--bg-dark-gray: #121212;         /* Cards/rows */
--text-primary: #e0e0e0;         /* Primary text */
--text-dim: #666;                /* Dimmed text */

--purple-pastel: #a78bfa;        /* Accents, hovers */
--blue-pastel: #60a5fa;          /* Stats, headers, wards */
--green-pastel: #34d399;         /* Cost, success, completed */
--yellow-pastel: #fbbf24;        /* Running, soundings */
--pink-pastel: #f472b6;          /* Metrics, tools */
--red-pastel: #f87171;           /* Errors */
--orange-pastel: #fb923c;        /* Reforge */
```

### Typography

- **Headers**: 2rem, gradient purple→blue
- **Phase names**: 0.9rem, white
- **Costs**: Adaptive precision, green
- **Metrics**: Bold, colored pastels
- **Code/snippets**: Monaco, Courier New (monospace)

---

## Two-Screen Flow

### Screen 1: Cascades (Definitions)

**Purpose:** Explore all cascade definitions with aggregated metrics

**Features:**
- All cascade JSON files from `examples/` directory
- Phase bars showing structure
- Aggregated metrics:
  - Total runs (across all executions)
  - Total cost (sum of all runs)
  - Avg/min/max execution time
- Dimmed appearance for cascades never run (0 runs)
- Click cascade → navigate to instances

**Layout:**
```
┌────────────────────────────────────────────────────┐
│ Cascades              42 defs  125 runs  $5.67     │
├────────────────────────────────────────────────────┤
│ blog_flow                                   $1.23  │
│ Generate posts                   15 runs  45.6s    │
│ ├─ research (6 msgs)    ████ $0.45                │
│ ├─ generate (12 msgs)   ████████ $0.78            │
│ └─ review (4 msgs)      ██ $0.12                  │
└────────────────────────────────────────────────────┘
```

### Screen 2: Instances (Execution History)

**Purpose:** View all runs of a specific cascade with detailed metrics

**Features:**
- All execution instances of selected cascade
- Phase-by-phase status (green/yellow/red/gray)
- Per-instance metrics (duration, cost, models used)
- Input parameters display
- Re-run button (pre-fills inputs)
- Freeze button (create test snapshot)
- Final output display
- Real-time updates via SSE

**Layout:**
```
┌────────────────────────────────────────────────────┐
│ ← Back  blog_flow        15 instances  [▶ Run]    │
├────────────────────────────────────────────────────┤
│ session_abc123 (8 msgs)                     45.2s │
│ 2025-12-03 10:30        [🔧 Re-run]        $0.045 │
│ 🤖 claude-sonnet                                   │
│ INPUTS:                                            │
│ topic: "AI trends"                                 │
│                                                     │
│ ├─ research    ████ $0.015  ✓  [🔱3→2]           │
│ ├─ generate    ████████ $0.020  ✓  [⚖2/3] [🔧1] │
│ └─ review      ██ $0.010  ✓                       │
│                                                     │
│ FINAL OUTPUT:                                      │
│ Here is the blog post about AI trends...          │
│                                      [❄ Freeze]    │
└────────────────────────────────────────────────────┘
```

---

## Phase Bar Visualization System

### Unified Complexity Encoding

The phase bars use a **unified visual language** for all 4 types of internal complexity:

1. **Soundings** (Tree of Thought) - Parallel attempts
2. **Reforge** - Sequential refinement
3. **Retries** (`max_attempts`) - Validation retry loops
4. **Turns** (`max_turns`) - Multi-turn conversations

### Bar Anatomy

```
phase_name (12 messages)    ▓3▓2✓▓3  $0.045  ✓  [🔱3→2 ⚖3] [🔧5]
                            ↑  ↑ ↑           ↑      ↑      ↑
                            │  │ │           │      │      └─ 5 tool calls
                            │  │ │           │      └──────── 3 turns each
                            │  │ │           └───────────────  Phase cost
                            │  │ └─ Sounding 2: 3 turns
                            │  └─── Sounding 1: 2 turns (winner, bright)
                            └────── Sounding 0: 3 turns

                            ●●  ← Pink tool dots (bottom-right)
```

### Segment Encoding

**Width:** Proportional to cost (relative to total)
**Brightness:**
- Winner: 140% brightness, saturated
- Loser: 35% opacity, desaturated

**Overlays:**
- **Number (top-left)**: Turn count (if > 1)
- **Cost (center)**: Dollar amount (if segment > 15% wide)
- **Dots (bottom-right)**: Pink = tool calls

**Borders:** 2px solid black between segments

### Badge Format

| Badge | Meaning |
|-------|---------|
| `[🔱5]` | 5 soundings (definition) |
| `[🔱5→3]` | 5 soundings, #3 won (instance) |
| `[🔨3]` | 3 reforge steps |
| `[⚖2/5]` | 2 turns used, 5 max |
| `[🛡️4]` | 4 wards |
| `[🔧3]` | 3 tool calls |
| `[Light/Medium/Heavy]` | Complexity weight |

### Hover Tooltips

Hover any segment to see cost breakdown:
```
┌──────────────────────┐
│ Sounding 2 (Winner)  │
│ Total: $0.01693      │
├──────────────────────┤
│ Turn 1:  $0.00543    │
│ Turn 2:  $0.00621    │
│ Turn 3:  $0.00529    │
└──────────────────────┘
```

### Weight Calculation

```javascript
weight = 1 (base)
  + soundings_factor × 3
  + reforge_steps × 5
  + ward_count × 2
  + max_turns (if > 1)
  + 5 (if loop_until)
```

**Color by weight:**
- Green: Light (< 10)
- Yellow: Medium (10-20)
- Red: Heavy (> 20)

---

## Component Structure

```
frontend/src/
├── App.js                      # Main router, SSE connection
├── App.css                     # Dark theme base
├── components/
│   ├── CascadesView.js        # Cascade definitions screen
│   ├── CascadesView.css       # Cascades styling
│   ├── InstancesView.js       # Cascade instances screen
│   ├── InstancesView.css      # Instances styling
│   ├── PhaseBar.js            # Unified phase visualization
│   ├── PhaseBar.css           # Phase bar styling
│   ├── RunCascadeModal.js     # Run cascade dialog
│   ├── RunCascadeModal.css    # Modal styling
│   ├── FreezeTestModal.js     # Freeze snapshot dialog
│   ├── Toast.js               # Toast notifications
│   └── Toast.css              # Toast styling
└── index.css                   # Global styles

backend/
└── app.py                      # Flask API + DuckDB queries
```

---

## Backend API Endpoints

### GET /api/cascade-definitions

Returns all cascade definitions with aggregated metrics.

**Response:**
```json
[
  {
    "cascade_id": "blog_flow",
    "description": "Generate blog posts",
    "cascade_file": "/path/to/file.json",
    "phases": [
      {
        "name": "research",
        "instructions": "Analyze topic...",
        "soundings_factor": 3,
        "reforge_steps": null,
        "ward_count": 0,
        "max_turns": 1,
        "has_loop_until": false,
        "model": null,
        "avg_cost": 0.0123,
        "avg_duration": 3.2
      }
    ],
    "inputs_schema": {"topic": "Blog topic"},
    "metrics": {
      "run_count": 15,
      "total_cost": 1.23,
      "avg_duration_seconds": 45.6,
      "min_duration_seconds": 32.1,
      "max_duration_seconds": 78.9
    }
  }
]
```

### GET /api/cascade-instances/:cascade_id

Returns all execution instances for a specific cascade.

**Response:**
```json
[
  {
    "session_id": "ui_run_abc123",
    "cascade_id": "blog_flow",
    "start_time": "2025-12-03T10:30:00",
    "end_time": "2025-12-03T10:31:15",
    "duration_seconds": 75.5,
    "total_cost": 0.045,
    "models_used": ["anthropic/claude-3.5-sonnet"],
    "input_data": {"topic": "AI trends"},
    "final_output": "Here is the blog post...",
    "phases": [
      {
        "name": "research",
        "status": "completed",
        "output_snippet": "Found 5 sources...",
        "error_message": null,
        "model": "x-ai/grok-4.1-fast:free",
        "sounding_total": 3,
        "sounding_winner": 1,
        "sounding_attempts": [
          {
            "index": 0,
            "is_winner": false,
            "cost": 0.012,
            "turns": [
              {"turn": 0, "cost": 0.012}
            ]
          },
          {
            "index": 1,
            "is_winner": true,
            "cost": 0.015,
            "turns": [
              {"turn": 0, "cost": 0.008},
              {"turn": 1, "cost": 0.007}
            ]
          }
        ],
        "max_turns": 1,
        "max_turns_actual": 2,
        "turn_costs": [],
        "tool_calls": ["web_search"],
        "message_count": 8,
        "avg_cost": 0.015,
        "avg_duration": 3.2
      }
    ]
  }
]
```

### POST /api/run-cascade

Execute a cascade with inputs.

**Request:**
```json
{
  "cascade_path": "/path/to/cascade.json",
  "inputs": {"topic": "AI trends"},
  "session_id": "optional_custom_id"
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "ui_run_abc123",
  "message": "Cascade started in background"
}
```

### POST /api/test/freeze

Create a test snapshot from execution.

**Request:**
```json
{
  "session_id": "ui_run_abc123",
  "snapshot_name": "blog_flow_works",
  "description": "Tests blog generation workflow"
}
```

### GET /api/events/stream

Server-Sent Events for real-time updates.

**Events:**
- `connected` - Connection established
- `cascade_start` - Cascade execution begins
- `phase_start` - Phase begins
- `phase_complete` - Phase completes
- `cascade_complete` - Cascade finishes
- `cascade_error` - Cascade fails
- `heartbeat` - Keep-alive (every 5 seconds)

---

## Data Flow

```
Cascade Execution
    ↓
Echo Logging (Parquet + JSONL)
    ↓
Backend Queries (DuckDB + JSONL parsing)
    ↓
    ├─ GET /api/cascade-definitions
    │    ↓
    │  Cascades Screen
    │    ↓ (click cascade)
    │
    └─ GET /api/cascade-instances/:id
         ↓
       Instances Screen
         ↓ (hover segment)
       Tooltip (turn/cost breakdown)
```

---

## Phase Bar Component

### PhaseBar.js

The core visualization component that renders phases with complexity indicators.

**Props:**
```javascript
{
  phase: {
    name: "generate",
    avg_cost: 0.045,
    avg_duration: 5.1,
    message_count: 12,

    // Soundings
    sounding_total: 3,
    sounding_winner: 1,
    sounding_attempts: [
      {index: 0, is_winner: false, cost: 0.012, turns: [...]},
      {index: 1, is_winner: true, cost: 0.018, turns: [...]},
      {index: 2, is_winner: false, cost: 0.015, turns: [...]}
    ],

    // Turns/retries
    max_turns: 3,
    turn_costs: [{turn: 0, cost: 0.012}, ...],

    // Tool calls
    tool_calls: ["run_code", "set_state"],

    // Status (instances only)
    status: "completed",  // completed, running, error, pending
    output_snippet: "Output preview...",
    error_message: "Error details..."
  },
  maxCost: 0.1,  // For relative bar width
  status: null,  // or "completed", "running", etc.
  onClick: () => {}
}
```

**Rendering Logic:**

1. **Bar Width**: `(phase.avg_cost / maxCost) × 100%` (minimum 5%)
2. **Bar Color**:
   - Instance: Status-based (green/yellow/red/gray)
   - Definition: Weight-based (green/yellow/red)
3. **Segments**:
   - If `sounding_attempts` → render sounding segments
   - Else if `turn_costs.length > 1` → render retry segments
   - Else if `soundings_factor > 1` → simple dividers
4. **Overlays**:
   - Turn count badge (top-left)
   - Cost display (center, if segment > 15% wide)
   - Tool dots (bottom-right)

---

## Cost Tracking

### How Costs Are Logged

**Agent makes LLM call:**
1. `track_request()` called with trace_id, phase_name, cascade_id, sounding_index
2. Async worker waits ~5 seconds for OpenRouter API
3. Fetches cost from OpenRouter
4. Logs `cost_update` entry with:
   - Same trace_id as agent call
   - `phase_name`, `cascade_id`, `sounding_index` from queue
   - Actual cost and token counts

**Cost data structure:**
```json
{
  "node_type": "cost_update",
  "trace_id": "abc-123",
  "phase_name": "generate",
  "cascade_id": "blog_flow",
  "sounding_index": 1,
  "cost": 0.01234,
  "tokens_in": 523,
  "tokens_out": 234
}
```

### Cost Aggregation

**Phase-level:**
```sql
SELECT phase_name, SUM(cost)
FROM echoes
WHERE session_id = ? AND phase_name IS NOT NULL AND cost > 0
GROUP BY phase_name
```

**Cascade-level:**
```sql
SELECT cascade_id, session_id, SUM(cost)
FROM echoes
WHERE cost > 0
GROUP BY cascade_id, session_id
```

**Sounding-level:**
```sql
SELECT phase_name, sounding_index, SUM(cost)
FROM echoes
WHERE session_id = ? AND sounding_index IS NOT NULL AND cost > 0
GROUP BY phase_name, sounding_index
```

### Cost Display (Adaptive Precision)

```javascript
if (cost < 0.00001) return `$${(cost * 1000000).toFixed(2)}µ`;  // $12.34µ
if (cost < 0.0001) return `$${(cost * 1000).toFixed(3)}‰`;      // $1.234‰
if (cost < 0.001) return `$${cost.toFixed(6)}`;                 // $0.000123
if (cost < 0.01) return `$${cost.toFixed(5)}`;                  // $0.01234
if (cost < 0.1) return `$${cost.toFixed(4)}`;                   // $0.0123
if (cost < 1) return `$${cost.toFixed(3)}`;                     // $0.123
if (cost < 10) return `$${cost.toFixed(2)}`;                    // $1.23
return `$${cost.toFixed(2)}`;                                   // $12.34
```

---

## Real-Time Updates (SSE)

### Connection Setup (App.js)

```javascript
useEffect(() => {
  const eventSource = new EventSource('http://localhost:5001/api/events/stream');

  eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);

    switch (event.type) {
      case 'cascade_start':
        setRunningCascades(prev => new Set([...prev, event.data.cascade_id]));
        setRunningSessions(prev => new Set([...prev, event.session_id]));
        setRefreshTrigger(prev => prev + 1);
        break;

      case 'phase_complete':
      case 'tool_call':
        setRefreshTrigger(prev => prev + 1);
        break;

      case 'cascade_complete':
        setRunningCascades(prev => {
          const newSet = new Set(prev);
          newSet.delete(event.data.cascade_id);
          return newSet;
        });
        setRefreshTrigger(prev => prev + 1);
        break;
    }
  };

  return () => eventSource.close();
}, []);
```

### Running State Indicators

**Cascade row (definitions):**
- Yellow pulsing border
- "Running..." text indicator

**Instance row:**
- Yellow pulsing border
- "Running" badge next to session ID

**Phase bar (instances):**
- Yellow bar with shimmer animation
- Status: "running"

---

## Data Sources Priority

### JSONL First (Real-Time Data)

For instances, the backend reads JSONL first:
- Input data
- Phase costs
- Turn breakdown
- Tool calls
- Message counts

**Why:** JSONL is written immediately, Parquet buffers (10 entries)

### Parquet Fallback (Historical Data)

For cascade definitions and older data:
- DuckDB queries on Parquet files
- Aggregations across all sessions
- Fast analytics

---

## Common Development Tasks

### Adding a New Badge

1. **Backend**: Add data to phase object
2. **Frontend**: Update `ComplexityBadges()` function
3. **CSS**: Add badge styling (`.complexity-badge.yourtype`)

### Adding a New Metric

1. **Backend**: Query from echoes table
2. **Add to phases_map** in instance query
3. **Frontend**: Display in PhaseBar header or badges

### Changing Colors

Edit color variables in component CSS files:
- `CascadesView.css`
- `InstancesView.css`
- `PhaseBar.css`

### Debugging Data Issues

1. Check JSONL files: `cat logs/echoes_jsonl/session_id.jsonl | jq`
2. Check backend console for `[DEBUG]` messages
3. Check browser console for component logs
4. Verify DuckDB queries with `union_by_name=true`

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app.py` | Flask API, DuckDB queries, SSE |
| `App.js` | Routing, SSE, state management |
| `CascadesView.js` | Cascade definitions list |
| `InstancesView.js` | Instance execution list |
| `PhaseBar.js` | **Core visualization component** |
| `PhaseBar.css` | Segment styling, tooltips, indicators |
| `Toast.js` | Notification system |

---

## Environment Variables

```bash
export WINDLASS_LOG_DIR=/path/to/logs
export WINDLASS_GRAPH_DIR=/path/to/graphs
export WINDLASS_STATE_DIR=/path/to/states
export WINDLASS_IMAGE_DIR=/path/to/images
export WINDLASS_CASCADES_DIR=/path/to/examples
```

---

## Important Implementation Details

### Cost Data Availability

- Costs arrive **5 seconds after** agent call (OpenRouter API delay)
- Use JSONL for real-time (immediate writes)
- Parquet buffers 10 entries before flushing
- Always query JSONL first for instances

### Sounding Context Propagation

- `current_phase_sounding_index` tracked in runner
- Passed to `log_message()` and `track_request()`
- Cost updates inherit sounding_index
- Enables per-sounding cost tracking

### Schema Consistency

- Use `union_by_name=true` in DuckDB queries
- Handle null columns gracefully
- JSONL has full schema, Parquet may vary
- Always COALESCE or use CASE for safety

### Tooltip State

- `hoveredSegment` holds current hover data
- Different structure for soundings vs retries
- `is_retry` flag distinguishes types
- Tooltip renders based on data structure

---

## Styling Conventions

### Segment States

```css
.segment.winner {
  opacity: 1;
  filter: brightness(1.4) saturate(1.2);
  box-shadow: inset 0 0 10px rgba(255, 255, 255, 0.4);
}

.segment.loser {
  opacity: 0.35;
  filter: brightness(0.5) saturate(0.7);
}
```

### Animations

- **Pulsing border**: Running cascades/instances (2s ease-in-out)
- **Shimmer**: Running phase bars (2s ease-in-out)
- **Tooltip fade-in**: 0.2s ease-out
- **Hover lift**: translateY(-2px)

### Responsive Breakpoints

- Desktop: >1200px (full layout)
- Tablet: 768-1200px (rows wrap)
- Mobile: <768px (stack vertically)

---

## Troubleshooting

### Costs Not Showing

1. Check if costs exist: `grep cost_update logs/echoes_jsonl/session_id.jsonl`
2. Verify phase_name populated: `jq '.phase_name' ...`
3. Check backend debug: `[DEBUG] Phase costs for ...`
4. Wait 5-10 seconds for async cost worker

### Duplicate Soundings

- Backend query might not be deduplicating
- Frontend dedupes by index: `new Map(...).values()`
- Check GROUP BY in sounding query

### Schema Errors

- Add `union_by_name=true` to `read_parquet()`
- Use `TRY_CAST()` for JSON extraction
- Avoid complex JOINs on heterogeneous schemas

### SSE Not Connecting

1. Check backend running: `curl http://localhost:5001/api/events/stream`
2. Check browser console for connection errors
3. Verify EventPublishingHooks enabled in runner
4. Check CORS settings

---

## Future Enhancements

### Planned Features

- [ ] Drill-down: Click segment → sounding detail modal
- [ ] Search/filter cascades
- [ ] Sort by metrics (cost, runs, duration)
- [ ] Cost trend sparklines
- [ ] Model performance comparison
- [ ] Reforge visualization
- [ ] Click instance → full execution detail
- [ ] Image viewer for phase outputs
- [ ] Export metrics to CSV

### Framework Improvements Needed

- [ ] API error retry using max_attempts
- [ ] Per-sounding duration tracking
- [ ] Reforge attempt tracking (similar to soundings)
- [ ] Per-tool cost attribution

---

## Summary

Windlass UI provides a **metrics-focused, visually rich** interface for exploring cascade executions:

✅ **Dark mode** with bright pastel accents
✅ **Phase bars** with cost-proportional segments
✅ **Unified visualization** for all complexity types
✅ **Real-time updates** via SSE
✅ **Per-sounding/retry cost tracking**
✅ **Tool call indicators**
✅ **Message counts**
✅ **Hover tooltips** with turn breakdowns
✅ **Input display + re-run**
✅ **Final output preview**
✅ **Freeze as test**

The UI makes cascade complexity **visible and actionable** at every level. 🌊✨
