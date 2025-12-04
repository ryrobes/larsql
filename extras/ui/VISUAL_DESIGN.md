# Windlass UI - Visual Design Mockup 🎨

## Color Palette: Pure Black + Bright Pastels

```
Pure Black (#0a0a0a)  ████████████
Dark Gray  (#121212)  ████████████  (cards)
Light Gray (#e0e0e0)  ████████████  (text)

Purple Pastel (#a78bfa) 🟪  (accents, hovers)
Blue Pastel   (#60a5fa) 🔵  (stats, headers)
Green Pastel  (#34d399) 🟢  (cost, success)
Yellow Pastel (#fbbf24) 🟡  (running, soundings)
Pink Pastel   (#f472b6) 🩷  (metrics)
Red Pastel    (#f87171) 🔴  (errors)
```

---

## Screen 1: Cascades (Definitions)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 🌊 Cascades                                   42    125    $5.67    ┃
┃    (gradient purple→blue)                   defs   runs   total    ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ blog_flow                 [research] [generate] [review]  $1.23 │ ┃
┃ │ Generate blog posts       ├───🔱──┤ ├───🛡️──┤ ├──────┤    │ ┃
┃ │                           green     blue      green           │ ┃
┃ │                                               15 runs  45.6s avg │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃   ↑ Hover: Purple glow, lifts up                                    ┃
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ data_pipeline            [extract] [transform] [load]     $3.21 │ ┃
┃ │ ETL workflow             ├──────┤ ├────────┤ ├────┤            │ ┃
┃ │                          green    green      green               │ ┃
┃ │                                               27 runs  123.4s avg │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ model_override_test      [fast] [detailed] [default]      $0.42 │ ┃
┃ │ Multi-model cascade      ├───┤ ├──────┤ ├──────┤              │ ┃
┃ │                          green green    green                    │ ┃
┃ │                          🤖grok 🤖claude                        │ ┃
┃ │                                                8 runs   32.1s avg │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Color Legend:
- Rows: Dark gray (#121212) on pure black
- Phase blocks: Pure black with colored 2px borders
  - Green (#34d399): Default phase
  - Yellow (#fbbf24): Has soundings 🔱
  - Blue (#60a5fa): Has wards 🛡️
- Model names: Purple text (#a78bfa)
- Metrics: Pink (#f472b6)
- Cost: Large green (#34d399)
- Hover: Purple glow (#a78bfa)
```

---

## Screen 2: Instances (Runs)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ← Back       🌊 blog_flow                      15 instances   $1.23  ┃
┃ (purple)     (gradient blue→green)                                   ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ session_abc123          [research] [generate] [review]    45.2s │ ┃
┃ │ 2025-12-02 10:30:15     ├───✓───┤ ├───✓───┤ ├───✓───┤  $0.045  │ ┃
┃ │ 🤖 claude-sonnet        green     green     green                │ ┃
┃ │                         Found 5   # Blog    Done.                │ ┃
┃ │                         sources   Post      ✓                    │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ session_def456          [research] [generate] [review]    12.3s │ ┃
┃ │ 2025-12-02 11:15:42     ├───✓───┤ ├───⏳──┤ ├───⚪──┤  $0.012  │ ┃
┃ │ 🤖 grok + claude        green     yellow    gray                 │ ┃
┃ │                         Found 3   Generat-  (pending)            │ ┃
┃ │                         sources   ing...    ●                    │ ┃
┃ │                                   (pulse)                         │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃                                                                       ┃
┃ ┌─────────────────────────────────────────────────────────────────┐ ┃
┃ │ session_ghi789          [research] [generate] [review]    67.8s │ ┃
┃ │ 2025-12-01 08:22:11     ├───✓───┤ ├───✗───┤ ├───⚪──┤  $0.023  │ ┃
┃ │ 🤖 claude-sonnet        green     red       gray                 │ ┃
┃ │                         Found 2   Error:    (skipped)            │ ┃
┃ │                         sources   timeout   ●                    │ ┃
┃ └─────────────────────────────────────────────────────────────────┘ ┃
┃                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Status Colors:
- ✓ Green border (#34d399): Completed
- ⏳ Yellow border (#fbbf24): Running (with pulse animation)
- ✗ Red border (#f87171): Error
- ⚪ Gray border (#4b5563): Pending/skipped
- Small colored dot (●) in bottom-right corner
```

---

## Phase Block Anatomy

### Cascade Definitions (Screen 1)

```
┌────────────────┐
│  research      │  ← Phase name (white)
│                │
│  🤖 grok-4     │  ← Model (purple) - if override
│                │
│      🔱        │  ← Badge (top-right) - soundings/wards
└────────────────┘
  ↑ Border: 2px colored (green/yellow/blue)
```

### Cascade Instances (Screen 2)

```
┌────────────────┐
│  generate      │  ← Phase name (white)
│                │
│  # Blog Post   │  ← Output snippet (gray, monospace)
│  Title...      │
│                │
│  🤖 claude     │  ← Model used (purple)
│              ● │  ← Status dot (colored)
└────────────────┘
  ↑ Border: 2px status color (green/yellow/red/gray)
```

---

## Hover States

### Cascade Row Hover

```
Before:                          After (hover):
┌─────────────────────┐         ┌─────────────────────┐
│ Dark gray (#121212) │   →     │ Darker (#161616)    │
│ Border (#1f1f1f)    │         │ Border: Purple      │
│                     │         │ Lifted 2px up       │
│                     │         │ Purple glow         │
└─────────────────────┘         └─────────────────────┘
```

### Phase Block Hover

```
Before:                          After (hover):
┌──────┐                        ┌──────┐
│ 100% │                  →     │ 105% │ (scaled up)
│      │                        │ Bg brighter
└──────┘                        └──────┘
```

---

## Animations

### Running Phase (Yellow Border)

```
@keyframes pulse {
  0%   { opacity: 1.0, glow: 0px }
  50%  { opacity: 0.8, glow: 8px }
  100% { opacity: 1.0, glow: 0px }
}
```

**Visual effect:** Yellow border pulses with expanding glow

### Loading Spinner

```
Circular spinner:
- Border: Dark gray (#1a1a1a)
- Top: Bright blue (#a78bfa)
- Rotation: 1s linear infinite
```

---

## Typography Scale

| Element | Size | Weight | Color |
|---------|------|--------|-------|
| Screen title | 2.5rem | 700 | Gradient (purple→blue) |
| Cascade name | 1.2rem | 600 | White (#f0f0f0) |
| Phase name | 0.85rem | 600 | Light gray (#e0e0e0) |
| Metric value | 1.8rem | 700 | Colored pastel |
| Metric label | 0.7rem | 400 | Dark gray (#666) |
| Description | 0.85rem | 400 | Gray (#888) |
| Output snippet | 0.7rem | 400 | Gray (#888) monospace |
| Model tag | 0.65-0.7rem | 400 | Purple (#a78bfa) |

---

## Layout Breakdown

### Cascades Row

```
┌───────────────────────────────────────────────────────────────┐
│ [Info 250px] [Phase Blocks (flex 1)] [Metrics 220px]         │
│                                                                │
│ blog_flow    [research][generate][review]    15 runs   $1.23 │
│ Description  ├───────┤├────────┤├───────┤    45.6s avg      │
│                                                                │
└───────────────────────────────────────────────────────────────┘
   ↑            ↑                                ↑
   Fixed width  Flexible (scrolls if needed)     Fixed width
```

### Instances Row

```
┌───────────────────────────────────────────────────────────────┐
│ [Info 280px] [Phase Blocks (flex 1)] [Metrics 160px]         │
│                                                                │
│ session_123  [research][generate][review]          45.2s      │
│ 2025-12-02   ├───✓───┤├───✓───┤├───✓───┤         $0.045     │
│ 🤖 claude    Found...  # Blog   Done.                        │
│                                                                │
└───────────────────────────────────────────────────────────────┘
   ↑            ↑                                ↑
   280px        Flexible                         160px
```

---

## Responsive Breakpoints

### Desktop (> 1200px)
- Full layout as shown
- All metrics visible
- Phase blocks side-by-side

### Tablet (768px - 1200px)
- Rows wrap to multi-line
- Info on top row
- Phases + metrics on bottom row

### Mobile (< 768px)
- Stack vertically
- Phase blocks scroll horizontally
- Metrics stack

---

## State Indicators

### Phase Status (Instances View)

| Status | Border | Background | Dot | Animation |
|--------|--------|------------|-----|-----------|
| **Completed** | Green (#34d399) | Pure black | Green | None |
| **Running** | Yellow (#fbbf24) | Pure black | Yellow | Pulse (2s) |
| **Error** | Red (#f87171) | Pure black | Red | None |
| **Pending** | Gray (#4b5563) | Pure black | Gray | None (50% opacity) |

### Badges

| Badge | Meaning | Color |
|-------|---------|-------|
| 🔱 | Has soundings | Yellow border |
| 🛡️ | Has wards | Blue border |
| 🤖 | Model override | Purple text |

---

## Interactive Elements

### Buttons

**Back Button:**
```
┌───────────┐              Hover:
│ ← Back    │              ┌───────────┐
│ #1a1a1a   │      →       │ ← Back    │
│ border    │              │ Purple!   │
│ purple    │              │ Moves ←   │
└───────────┘              └───────────┘
```

### Cascade Row (Clickable)

```
Default:                     Hover:                      Click:
┌─────────┐                 ┌─────────┐                 Navigate to
│ #121212 │                 │ #161616 │                 Instances
│ border  │        →        │ Purple  │        →        screen with
│ #1f1f1f │                 │ Glow    │                 cascade_id
└─────────┘                 └─────────┘
                            Lift -2px
```

---

## Information Density

### Cascades Screen - High Level

**What you see at a glance:**
- All cascade definitions (20-30 visible)
- Phase count and types (visual blocks)
- Usage patterns (run count)
- Cost impact (large, prominent)
- Performance (avg time)

**Goal:** Find your cascades, understand usage/cost

### Instances Screen - Detailed

**What you see at a glance:**
- All runs of one cascade (50-100 visible)
- Execution status (colored phases)
- Individual run costs
- Output previews
- Models used per run

**Goal:** Debug runs, compare instances, track status

---

## Empty States

### No Cascades

```
┌─────────────────────────────────┐
│                                 │
│      No cascades found          │
│                                 │
│  Run a cascade to see it here   │
│                                 │
└─────────────────────────────────┘
   (centered, gray text)
```

### No Instances

```
┌─────────────────────────────────┐
│                                 │
│   No instances for this cascade │
│                                 │
│  This cascade hasn't been run   │
│                                 │
└─────────────────────────────────┘
```

---

## Scrolling Behavior

### Cascades Screen
- Vertical scroll for cascade rows
- Horizontal scroll within phase blocks (if many phases)
- Header stays fixed (future enhancement)

### Instances Screen
- Vertical scroll for instance rows
- Horizontal scroll within phase blocks
- Back button always visible

---

## Real-Time Updates (Future)

### SSE Integration

**When cascade starts:**
- New row appears in Instances view
- Phases show "pending" status

**When phase completes:**
- Phase block changes from yellow → green
- Output snippet appears
- Metrics update

**When cascade completes:**
- All phases green
- Final cost displayed
- Cascades view metrics update (run count +1)

---

## Gradients

### Header Text

```css
background: linear-gradient(135deg, #a78bfa 0%, #60a5fa 100%);
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
```

**Effect:** Purple → Blue gradient on titles

### Future: Metric Trends

```css
/* Cost increasing */
background: linear-gradient(90deg, #34d399 0%, #fbbf24 100%);

/* Cost decreasing */
background: linear-gradient(90deg, #fbbf24 0%, #34d399 100%);
```

---

## Accessibility

### Contrast Ratios
- White on black: 21:1 (AAA)
- Pastels on black: 7:1+ (AA)
- Gray labels: 4.5:1 (AA)

### Interactive Elements
- All clickable areas > 44px height
- Clear hover states
- Keyboard navigation (future)

### Screen Readers
- Semantic HTML
- ARIA labels on metrics
- Alt text for icons (future)

---

## Performance

### Optimizations
- Virtual scrolling for 100+ cascades (future)
- Debounced search/filter (future)
- Memoized row components
- Lazy load phase details

### Data Loading
- Fetch on mount
- No auto-refresh by default (future: opt-in)
- SSE for real-time (future)

---

## Summary

A **metrics-focused, visually striking** interface for exploring Windlass cascades:

✅ **Pure black background** - sleek, professional
✅ **Bright pastel accents** - easy to scan, beautiful
✅ **Thick rows** - information-dense but clean
✅ **Phase blocks** - visual status at a glance
✅ **Cost prominent** - large, green, unmissable
✅ **Model tracking** - see what's being used
✅ **Two-screen flow** - definitions → instances

Built for **rapid exploration** and **cost analysis** of cascade executions. 🚀
