# Phase Bar Design - Visual Weight & Cost Breakdown 📊

## New Design: Horizontal Stacked Bars

Replaces square blocks with **information-dense horizontal bars** that show:
- Phase "weight" (complexity)
- Cost breakdown per phase
- Duration metrics
- Complexity indicators (soundings, reforge, loops, wards)
- Status (for instances)

---

## Visual Mockup

### Cascade Definitions View

```
┌─────────────────────────────────────────────────────────────┐
│ blog_flow                                            $1.23  │
│ Generate blog posts                          15 runs  45.6s │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ research    ████████ $0.45  3.2s  [🔱5] [Light]           │
│             ↑ 36% width (relative to max cost)              │
│                                                              │
│ generate    ████████████████ $0.78  5.1s  [🔱3] [🔨2] [⚖5] [Heavy] │
│             ↑ 63% width, orange gradient (heavy)            │
│                                                              │
│ review      ████ $0.12  1.1s  [🛡️2] [Light]               │
│             ↑ 10% width, green gradient (light)             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Features:**
- Bar width = relative cost (% of max phase cost)
- Bar color intensity = complexity weight
  - Green: Light (weight < 10)
  - Yellow: Medium (weight 10-20)
  - Red: Heavy (weight > 20)
- Badges show complexity factors
- Cost and duration inline

### Instance View (with status)

```
┌─────────────────────────────────────────────────────────────┐
│ session_abc123           Running  12.3s  $0.45              │
│ 2025-12-02 10:30:15      🤖 claude-sonnet                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ research    ████████ $0.15  1.2s  ✓  [🔱5]                │
│             ↑ Green bar (completed)                          │
│                                                              │
│ generate    ████████████ $0.30  ⏳  [🔱3] [🔨2]           │
│             ↑ Yellow pulsing bar (running)                   │
│             "Generating blog post content..."               │
│                                                              │
│ review      ──── $0.00  ⚪  [🛡️2]                          │
│             ↑ Gray dashed (pending)                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Status Colors:**
- ✓ Green: Completed
- ⏳ Yellow (shimmer): Running
- ✗ Red: Error
- ⚪ Gray dashed: Pending

---

## Complexity Weight Calculation

```javascript
weight = 1 (base)
  + soundings_factor × 3
  + reforge_steps × 5
  + ward_count × 2
  + max_turns (if > 1)
  + 5 (if has loop_until)
```

**Examples:**
- Simple phase: `weight = 1` (Light)
- With soundings (3): `weight = 1 + 9 = 10` (Medium)
- Soundings (5) + reforge (2): `weight = 1 + 15 + 10 = 26` (Heavy)
- Complex: Soundings (5) + reforge (3) + wards (2) + loop (5): `weight = 1 + 15 + 15 + 4 + 5 = 40` (Very Heavy)

---

## Badge System

| Badge | Icon | Color | Meaning |
|-------|------|-------|---------|
| [🔱5] | `mdi:sign-direction` | Yellow | 5 soundings (Tree of Thought) |
| [🔨3] | `mdi:hammer` | Orange | 3 reforge steps (refinement) |
| [🛡️2] | `mdi:shield` | Blue | 2 wards (validation) |
| [⚖5] | `mdi:repeat` | Purple | 5 max turns (retry loop) |
| [Light/Medium/Heavy] | - | Gray | Overall weight |

---

## Bar Anatomy

```
┌────────────────────────────────────────────────────────┐
│ phase_name          $0.45  3.2s  [badges]              │  ← Header
├────────────────────────────────────────────────────────┤
│ ████████████████████                                   │  ← Bar (width = cost %)
│ ↑ Gradient fill with segments for soundings            │
├────────────────────────────────────────────────────────┤
│ [🔱5] [🔨2] [Heavy]  "output snippet..."              │  ← Badges + snippet
└────────────────────────────────────────────────────────┘
```

**Bar Segments (for soundings):**
- Visual dividers show factor
- If soundings=5, bar has 5 segments
- Helps visualize parallel work

---

## Color Gradients

### Weight-Based (Cascade Definitions)

```css
Light:  rgba(52, 211, 153, 0.2) → rgba(52, 211, 153, 0.4)  /* Green */
Medium: rgba(251, 191, 36, 0.3) → rgba(251, 191, 36, 0.6)  /* Yellow */
Heavy:  rgba(248, 113, 113, 0.3) → rgba(248, 113, 113, 0.6) /* Red */
```

### Status-Based (Instances)

```css
Completed: rgba(52, 211, 153, 0.3) → rgba(52, 211, 153, 0.7)  /* Green */
Running:   rgba(251, 191, 36, 0.3) → rgba(251, 191, 36, 0.7)  /* Yellow + shimmer */
Error:     rgba(248, 113, 113, 0.3) → rgba(248, 113, 113, 0.7) /* Red */
Pending:   rgba(75, 85, 99, 0.2) → rgba(75, 85, 99, 0.3)      /* Gray + dashed */
```

---

## Information Density Comparison

### Old Design (Square Blocks)

```
[research] [generate] [review]
  🔱         🛡️
```

**Shows:** Phase names, 2 badges

### New Design (Stacked Bars)

```
research    ████████ $0.45  3.2s  [🔱5] [Light]
generate    ████████████████ $0.78  5.1s  [🔱3] [🔨2] [⚖5] [Heavy]
review      ████ $0.12  1.1s  [🛡️2] [Light]
```

**Shows:**
- Phase names
- Relative cost (bar width)
- Absolute cost ($0.45)
- Duration (3.2s)
- All complexity factors with numbers
- Overall weight label
- Visual comparison at a glance

**~5x more information in same space!**

---

## Responsive Behavior

**Desktop (>1200px):**
- Full bars with all badges
- Cost and duration visible

**Tablet (768-1200px):**
- Bars stack vertically
- Abbreviated badges

**Mobile (<768px):**
- Simplified bars
- Only essential badges

---

## Interactions

**Hover:**
- Bar brightens slightly
- Background highlights
- Cursor indicates clickable

**Click:**
- Cascade row → Instances view
- Instance row → (future) Phase detail view

---

## Benefits

### Visual

✅ **Weight at a glance** - Bar length shows cost
✅ **Complexity visible** - Color intensity + badges
✅ **Compact** - Vertical stacking vs horizontal scrolling
✅ **Informative** - Cost, duration, all factors shown

### Analytical

✅ **Cost breakdown** - See which phases are expensive
✅ **Identify heavy phases** - Red bars = optimization targets
✅ **Compare instances** - Visual diff across runs
✅ **Track progress** - Running phases shimmer

### Technical

✅ **Scalable** - Works with 3 or 30 phases
✅ **Responsive** - Adapts to screen size
✅ **Accessible** - Status icons + colors
✅ **No scrolling** - Everything visible

---

## Implementation Details

### Component Structure

```
PhaseBar (reusable)
├─ phase-bar-header (name + metrics + status icon)
├─ phase-bar-track (background)
│  └─ phase-bar-fill (colored bar with segments)
└─ phase-badges (complexity indicators + output)
```

### Data Requirements

**From backend:**
```json
{
  "name": "generate",
  "avg_cost": 0.78,
  "avg_duration": 5.1,
  "soundings_factor": 3,
  "reforge_steps": 2,
  "ward_count": 4,
  "max_turns": 5,
  "has_loop_until": false,
  "model": "anthropic/claude-3.5-sonnet",
  "status": "running",
  "output_snippet": "Generating content..."
}
```

**Weight calculation:**
```javascript
1 + (3 × 3) + (2 × 5) + (4 × 2) + 5 = 33 (Heavy)
```

---

## Example Use Cases

### Cost Optimization

Looking at bars, you immediately see:
- "generate" phase is 63% of total cost → optimization target
- Has soundings (3×) and reforge (2×) → could reduce factor
- Weight = Heavy → high complexity

### Performance Analysis

```
research    ████ $0.10  8.5s   [Heavy time, low cost]
generate    ████████ $0.80  1.2s   [High cost, fast]
```

- Research is slow but cheap → maybe use faster model
- Generate is expensive but fast → worth the cost

### Debugging Failed Runs

```
research    ████████ $0.15  1.2s  ✓
generate    ████████████ $0.30  ✗  [Error: timeout]
review      ──── $0.00  ⚪
```

- Error in generate phase
- Can see it's a heavy phase (soundings + reforge)
- Review never ran (pending)

---

## Future Enhancements

### Drill-Down

Click phase bar → Phase detail modal showing:
- Sounding attempts (if has soundings)
- Reforge iterations (if has reforge)
- Ward results (pass/fail)
- Full output
- Cost breakdown

### Cost Trends

Show sparkline on bar:
```
generate    ████████ $0.78 ▁▃▅▇  [Trending up]
```

### Heatmap View

Color bars by:
- Cost (red = expensive)
- Duration (yellow = slow)
- Error rate (red = unreliable)

Toggle between views

---

## Summary

**Old:** Square blocks with limited info
**New:** Horizontal bars with:
- ✅ Relative cost (bar width)
- ✅ Absolute cost + duration
- ✅ Complexity breakdown (badges with numbers)
- ✅ Weight indicator (Light/Medium/Heavy)
- ✅ Status (for instances)
- ✅ Output snippets
- ✅ Visual "spaghetti" metric

Much more informative while being more compact! 🎨📊
