# Windlass UI - Cascade Explorer & Analytics Dashboard 🌊

A sleek dark mode interface for exploring cascade definitions, analyzing execution metrics, and tracking performance.

## Design Philosophy

**Very black dark mode with bright pastel accents**

- Background: Pure black (#0a0a0a)
- Text: Light gray (#e0e0e0)
- Accents: Bright pastels (purple, blue, green, yellow, pink)
- Visual focus: Thick rows with square phase blocks
- Metrics-driven: Cost and performance front and center

---

## Features

### Screen 1: Cascades (Definitions)

**Shows all cascade definitions** (not run instances):

- **Thick rows** with cascade name, description, metadata
- **Square phase blocks** - dark with colored outlines:
  - Green: Default phase
  - Yellow: Has soundings (🔱)
  - Blue: Has wards (🛡️)
  - Purple text: Model override
- **Aggregated metrics**:
  - Run count (how many times executed)
  - Total cost (across all runs)
  - Min/max/avg execution times
- **Large cost figure** on the far right
- **Scrollable** list of all cascades
- **Click cascade → navigate to instances**

### Screen 2: Instances (Runs)

**Shows all execution instances** of a selected cascade:

- **Same thick row format** but for individual runs
- **Phase blocks colored by status**:
  - Green: Completed successfully
  - Yellow: Running (with pulse animation)
  - Red: Error
  - Gray: Pending (not reached)
- **Output snippets** inside each phase block
- **Model tags** showing which model(s) were used
- **Per-run metrics**:
  - Duration
  - Cost
  - Models used
- **Click back → return to cascades**

---

## Quick Start

### 1. Start Backend

```bash
cd extras/ui/backend
python app.py
```

**Backend will be available at:** `http://localhost:5001`

### 2. Start Frontend

```bash
cd extras/ui/frontend
npm install  # First time only
npm start
```

**UI will open at:** `http://localhost:3000`

### 3. Run Some Cascades

```bash
# In another terminal
cd /home/ryanr/repos/windlass

# Run a few cascades to populate data
windlass windlass/examples/simple_flow.json --input '{"data": "test1"}'
windlass windlass/examples/model_override_test.json --input '{"task": "test2"}'
```

### 4. Explore the UI

- View cascade definitions with metrics
- Click a cascade to see all instances
- See phase-level status and outputs
- Track costs and performance

---

## API Endpoints

### Backend (Flask - Port 5001)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cascade-definitions` | GET | All cascade defs with aggregated metrics |
| `/api/cascade-instances/:id` | GET | All instances of a specific cascade |
| `/api/session/:session_id` | GET | Detailed session data |
| `/api/graphs/:session_id` | GET | Execution graph JSON |
| `/api/events/stream` | GET | SSE for real-time updates |

### Response Formats

#### Cascade Definitions

```json
[
  {
    "cascade_id": "blog_flow",
    "description": "Generate blog posts",
    "phases": [
      {
        "name": "research",
        "has_soundings": true,
        "has_wards": false,
        "model": null
      },
      {
        "name": "generate",
        "has_soundings": false,
        "has_wards": true,
        "model": "anthropic/claude-3.5-sonnet"
      }
    ],
    "metrics": {
      "run_count": 42,
      "total_cost": 1.23,
      "avg_duration_seconds": 45.6,
      "min_duration_seconds": 32.1,
      "max_duration_seconds": 78.9
    }
  }
]
```

#### Cascade Instances

```json
[
  {
    "session_id": "session_123",
    "cascade_id": "blog_flow",
    "start_time": "2025-12-02T10:30:00",
    "end_time": "2025-12-02T10:31:15",
    "duration_seconds": 75.5,
    "total_cost": 0.045,
    "models_used": ["anthropic/claude-3.5-sonnet", "x-ai/grok-4.1-fast:free"],
    "phases": [
      {
        "name": "research",
        "status": "completed",
        "output_snippet": "Found 5 relevant sources...",
        "model": "x-ai/grok-4.1-fast:free",
        "has_soundings": true
      },
      {
        "name": "generate",
        "status": "completed",
        "output_snippet": "# Blog Post Title\n\nIntroduction...",
        "model": "anthropic/claude-3.5-sonnet",
        "has_soundings": false
      }
    ]
  }
]
```

---

## Design System

### Colors (Bright Pastels on Black)

| Color | Hex | Usage |
|-------|-----|-------|
| **Pure Black** | `#0a0a0a` | Background |
| **Dark Gray** | `#121212` | Cards/rows |
| **Light Gray** | `#e0e0e0` | Primary text |
| **Purple Pastel** | `#a78bfa` | Accents, gradients |
| **Blue Pastel** | `#60a5fa` | Stats, headers |
| **Green Pastel** | `#34d399` | Cost, success |
| **Yellow Pastel** | `#fbbf24` | Running, soundings |
| **Pink Pastel** | `#f472b6` | Metrics |
| **Red Pastel** | `#f87171` | Errors |

### Typography

- **Headers**: 2.5rem, gradient (purple → blue)
- **Cascade names**: 1.2rem, white
- **Metrics**: Bold, colored pastels
- **Labels**: 0.7rem, uppercase, gray
- **Code**: Monaco, Courier New (monospace)

### Layout

- **Thick rows**: Min 100px height, 12px border-radius
- **Phase blocks**: 120px width, 80px height, 8px border-radius
- **Spacing**: 2rem padding, 0.75rem gaps
- **Hover effects**: translateY(-2px), colored glow

---

## Component Structure

```
src/
├── App.js                        # Main router
├── App.css                       # Dark theme base
├── components/
│   ├── CascadesView.js          # Cascade definitions screen
│   ├── CascadesView.css         # Cascades styling
│   ├── InstancesView.js         # Cascade instances screen
│   └── InstancesView.css        # Instances styling
└── index.css                     # Global styles
```

---

## Features Detail

### Cascades Screen

**Visual Elements:**
- Gradient header with total stats
- Scrollable list of thick cascade rows
- Phase blocks show: name, badges (🔱 soundings, 🛡️ wards), model
- Hover: Purple glow, slight lift
- Empty state with helpful message

**Metrics Shown:**
- Run count
- Average duration
- Total cost (large, green, prominent)

### Instances Screen

**Visual Elements:**
- Back button with purple accent
- Scrollable list of instance rows
- Phase blocks colored by status:
  - ✅ Green border = Completed
  - ⏳ Yellow border + pulse = Running
  - ❌ Red border = Error
  - ⚪ Gray border = Pending
- Output snippets visible inside blocks
- Model tags for multi-model runs

**Metrics Shown:**
- Duration per instance
- Cost per instance
- Models used (as tags)

---

## Development

### Prerequisites

```bash
# Backend
pip install flask flask-cors duckdb pandas pyarrow

# Frontend
cd frontend
npm install
```

### Run Development Servers

**Terminal 1 - Backend:**
```bash
cd extras/ui/backend
export WINDLASS_LOG_DIR=../../../logs
export WINDLASS_GRAPH_DIR=../../../graphs
python app.py
```

**Terminal 2 - Frontend:**
```bash
cd extras/ui/frontend
npm start
```

### Configuration

Set environment variables to point to your Windlass data:

```bash
export WINDLASS_LOG_DIR=/path/to/windlass/logs
export WINDLASS_GRAPH_DIR=/path/to/windlass/graphs
export WINDLASS_CASCADES_DIR=/path/to/windlass/examples
```

---

## Data Flow

```
Cascade Execution
    ↓
Echo Logging (Parquet + JSONL)
    ↓
Backend API (Flask + DuckDB)
    ↓
    ├─ /api/cascade-definitions
    │    ↓
    │  Cascades Screen
    │    ↓ (click cascade)
    │
    └─ /api/cascade-instances/:id
         ↓
       Instances Screen
         ↓ (click back)
       Cascades Screen
```

---

## Metrics Calculated

### Cascade Definitions

```sql
-- Aggregated across all runs
run_count = COUNT(DISTINCT session_id)
total_cost = SUM(cost) across all sessions
avg_duration = AVG(max_time - min_time) per session
min_duration = MIN(duration)
max_duration = MAX(duration)
```

### Cascade Instances

```sql
-- Per individual session
duration_seconds = MAX(timestamp) - MIN(timestamp)
total_cost = SUM(cost) for session
models_used = DISTINCT models for session
```

### Phase Status

Determined by `node_type` in echoes:
- `phase_start` → "running"
- `phase_complete` / `turn_output` → "completed"
- `error` → "error"
- Not present → "pending"

---

## Visual Examples

### Cascades Screen

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🌊 Cascades                                   42 runs    $5.67 total │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ blog_flow          [research][generate][review]        $1.23    │ │
│ │ Generate posts     ├─────┤├─────┤├─────┤   15 runs             │ │
│ │                    🔱      🛡️              45.6s avg            │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ data_pipeline      [extract][transform][load]          $3.21    │ │
│ │ ETL workflow       ├──────┤├─────────┤├────┤  27 runs          │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Instances Screen

```
┌─────────────────────────────────────────────────────────────────────┐
│ ← Back              🌊 blog_flow                     15 instances     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ session_abc123     [research][generate][review]       45.2s      │ │
│ │ 2025-12-02 10:30   ├──✓───┤├──✓───┤├──✓───┤        $0.045     │ │
│ │ 🤖 claude-sonnet   Found... # Blog... Done.                     │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ session_def456     [research][generate][review]       ⏳ 12.3s   │ │
│ │ 2025-12-02 11:15   ├──✓───┤├──⏳───┤├──⚪───┤        $0.012     │ │
│ │ 🤖 grok + claude   Found... Generating...                       │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend
- **Flask** - Web server
- **DuckDB** - Analytics queries on Parquet/JSONL
- **Flask-CORS** - Cross-origin support
- **SSE** - Real-time event streaming

### Frontend
- **React** - UI framework
- **CSS Modules** - Component styling
- **Fetch API** - Data loading
- **No router library** - Simple state-based navigation

---

## Next Steps

### Immediate (Done ✅)
- [x] Backend API for cascade definitions
- [x] Backend API for cascade instances
- [x] Cascades view component
- [x] Instances view component
- [x] Dark theme with bright pastels
- [x] Phase blocks with status colors
- [x] Metrics display
- [x] Routing between views

### Short-Term (Future)
- [ ] Real-time updates via SSE
- [ ] Search/filter cascades
- [ ] Sort by metrics (cost, runs, duration)
- [ ] Click phase block → detailed phase view
- [ ] Export metrics to CSV
- [ ] Cost breakdown charts

### Medium-Term (Future)
- [ ] Timeline view of executions
- [ ] Cost trends over time
- [ ] Model performance comparison
- [ ] Soundings visualization
- [ ] Click instance → full execution detail
- [ ] Image viewer for phase outputs

---

## File Structure

```
extras/ui/
├── backend/
│   └── app.py                    # Flask API server
│
├── frontend/
│   ├── src/
│   │   ├── App.js               # Main router
│   │   ├── App.css              # Dark theme base
│   │   └── components/
│   │       ├── CascadesView.js  # Cascade definitions screen
│   │       ├── CascadesView.css # Cascades styling
│   │       ├── InstancesView.js # Cascade instances screen
│   │       └── InstancesView.css# Instances styling
│   ├── package.json
│   └── public/
│
├── start_backend.sh              # Backend startup script
├── start.sh                      # Full stack startup
└── README.md                     # This file
```

---

## Color Palette

```css
/* Bright Pastels on Pure Black */
--bg-pure-black: #0a0a0a;
--bg-dark-gray: #121212;
--text-primary: #e0e0e0;

--purple-pastel: #a78bfa;    /* Accents, gradients */
--blue-pastel: #60a5fa;      /* Stats, headers */
--green-pastel: #34d399;     /* Cost, success */
--yellow-pastel: #fbbf24;    /* Running, soundings */
--pink-pastel: #f472b6;      /* Metrics */
--red-pastel: #f87171;       /* Errors */
```

---

## Usage Examples

### View All Cascades

1. Open `http://localhost:3000`
2. See list of all cascade definitions
3. Metrics show: runs, avg time, total cost
4. Phase blocks show structure at a glance

### Drill into Instances

1. Click any cascade row
2. See all execution instances
3. Phase blocks colored by status (green/yellow/red/gray)
4. Output snippets visible in blocks
5. Models used displayed as tags

### Track Costs

- Total cost prominently displayed (large green number)
- Cost per cascade definition (aggregated)
- Cost per instance (individual run)
- Query by model in backend

---

## Differences from debug_ui

| Feature | debug_ui | New UI |
|---------|----------|--------|
| **Focus** | Debugging | Analytics & Exploration |
| **Design** | Functional | Sleek dark mode |
| **Views** | Single list | Two screens (defs → instances) |
| **Metrics** | Minimal | Prominent (cost, time, runs) |
| **Phase display** | List | Square blocks with status |
| **Models** | Not shown | Tracked and displayed |
| **Output** | Separate panel | Inline snippets |

---

## Known Limitations

### Current State
- Requires data in `logs/echoes/` (echo logging must be enabled)
- Model field only populated after model tracking implementation
- Phase status inference from logs (not always accurate for old data)
- No authentication (local dev only)

### Future Improvements
- Add real-time SSE updates
- Add search/filter capabilities
- Add detailed session drill-down
- Add cost trend charts
- Add model comparison views

---

## Troubleshooting

### Backend Errors

**"No echoes found"**
```bash
# Make sure you have echo data
ls logs/echoes/

# Run a cascade to generate data
windlass windlass/examples/simple_flow.json --input '{}'
```

**"DuckDB query failed"**
```bash
# Check parquet files exist
ls logs/echoes/*.parquet

# Reinstall dependencies
pip install duckdb pandas pyarrow
```

### Frontend Errors

**"Cannot connect to backend"**
```bash
# Make sure backend is running
curl http://localhost:5001/api/cascade-definitions

# Check CORS settings in backend/app.py
```

**"No cascades showing"**
- Backend needs access to logs/echoes/ directory
- Run some cascades first to populate data
- Check browser console for API errors

---

## Summary

You now have a sleek dark mode Windlass UI with:

✅ **Cascades screen** - Explore all cascade definitions
✅ **Instances screen** - View execution history
✅ **Phase blocks** - Visual status indicators
✅ **Metrics focus** - Cost and performance prominent
✅ **Model tracking** - See which models used
✅ **Dark theme** - Pure black with bright pastels
✅ **Thick rows** - Easy to scan
✅ **Output snippets** - Quick preview in blocks

Navigate between cascade definitions and their instances with a clean, metrics-driven interface! 🌊✨
