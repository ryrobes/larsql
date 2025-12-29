# Horizontal Cascade Timeline - Experimental UI

## What We Built

**A DAW-style horizontal cascade builder** as an alternative to the vertical notebook UI.

**Access**: SQL Query IDE → Click "**Timeline**" mode toggle (third button)

---

## Visual Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CONTROL BAR: [cascade_name] • Description...  │ 3/5 │ [Save] [Run All] │
├─────────────────────────────────────────────────────────────────────────┤
│ TIMELINE STRIP: (horizontal scroll ← →)                                 │
│                                                                          │
│   ┌───────┐   ┌───────┐   ┌───────┐   ┌───────┐                       │
│   │🤖 LLM │ → │ 🗂️ SQL  │ → │🤖 LLM │ → │✓ Done │  [+ Add]             │
│   │gen    │   │ trans │   │class  │   │valid  │                       │
│   │ 5.2s  │   │120ms  │   │⚡run  │   │○ pend │                       │
│   └───────┘   └───────┘   └───────┘   └───────┘                       │
│        ↑ Selected                                                        │
├─────────────────────────────────────────────────────────────────────────┤
│ DETAIL PANEL: (bottom, shows selected phase)                            │
│                                                                          │
│  [transform #2]     [Code] [Output]          [Run] [Delete] [×]        │
│  ───────────────────────────────────────────────────────────────────── │
│  │ SELECT * FROM _generate WHERE confidence > 0.8                    │  │
│  ───────────────────────────────────────────────────────────────────── │
│  │ ✓ 42 rows • 120ms                                                 │  │
│  │ [Table preview...]                                                 │  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Why Horizontal?

1. **Better for widescreen** (16:9 monitors, everyone has these now)
2. **More room for config/diagrams** (vertical space freed up)
3. **Natural left→right flow** (reading direction)
4. **Breaks "notebook" metaphor** (not competing with Jupyter)
5. **DAW analogy** (music production, video editing = familiar)

---

## Key Components

### 1. `CascadeTimeline.jsx` - Main Container
- Top control bar (title, description, run/save buttons)
- Horizontal scrolling timeline strip
- Phase cards laid out left→right with arrows
- Manages phase selection state

### 2. `PhaseCard.jsx` - Compact Phase Card
- **200px wide** × 120px tall
- Shows: type icon, name, status, stats (duration/rows), badges
- Click to select → opens in detail panel below
- Color-coded border by status (running=amber, success=green, error=red)

### 3. `PhaseDetailPanel.jsx` - Bottom Detail Panel
- **Tabbed interface**: Code | Config | Output
- **Code tab**: Monaco editor (full screen width, ~60% height)
- **Output tab**: AG Grid for tables, Monaco for JSON
- **Config tab**: LLM settings (TODO - placeholder for now)
- Run/delete actions

---

## New Files Created

```
dashboard/frontend/src/sql-query/notebook/
├── CascadeTimeline.jsx         # 🆕 Main horizontal layout
├── CascadeTimeline.css         # 🆕 DAW-style CSS
├── PhaseCard.jsx               # 🆕 Compact cards (200px wide)
├── PhaseCard.css               # 🆕 Status colors + hover states
├── PhaseDetailPanel.jsx        # 🆕 Bottom panel with tabs
└── PhaseDetailPanel.css        # 🆕 Detail panel styling
```

**Modified**:
- `SqlQueryPage.js` - Added third "Timeline" mode toggle
- `SqlQueryPage.css` - Added `.sql-query-timeline-area`

---

## Comparison: Notebook vs Timeline

| | Notebook | Timeline |
|-|----------|----------|
| **Scroll** | ↕ Vertical | ← → Horizontal |
| **Cards** | Full-width, stacked | 200px compact, side-by-side |
| **Code** | Inline in each cell | Bottom detail panel (selected) |
| **Output** | Inline below cell | Bottom panel, "Output" tab |
| **Flow** | List view | Timeline with arrows |
| **Best for** | Data wrangling (SQL/Python) | LLM cascades + routing |

---

## User Flow

1. Click **"Timeline"** toggle (top center, next to "Query" and "Notebook")
2. See all phases as compact cards, scroll left/right
3. **Click a card** to select it
4. **Bottom panel opens** showing Code/Output tabs
5. Edit code in Monaco editor (full-width)
6. **Run** via button in detail panel or click ▶ on card
7. **View output** in Output tab (table or JSON)
8. **Add phases** via "+ Add Phase" button (end of timeline)
9. **Delete** via trash icon in detail panel

---

## Design Highlights

### Colors (Status-based)
- **Running**: `#fbbf24` (amber) with pulse animation
- **Success**: `#34d399` (emerald)
- **Error**: `#f87171` (red)
- **Stale**: `#64748b` (slate, dashed border)
- **Selected**: `#2dd4bf` (teal glowing ring)

### Phase Cards
- Compact: 200px × 120px (fits ~5 on screen)
- Hover: Slight lift + shadow
- Selection: Teal border + glow
- Index badge: Top-right corner (#1, #2, #3...)

### Timeline Strip
- Height: 180px (including padding)
- Custom scrollbar (horizontal)
- Arrows between cards (→)
- Add button at end

---

## What's Working

✅ Horizontal phase layout
✅ Phase selection (click to expand)
✅ Detail panel with tabs
✅ Code editing (Monaco)
✅ Output rendering (AG Grid + JSON)
✅ Run individual phases
✅ Add new phases (SQL/Python/JS/Clj/LLM)
✅ Delete phases
✅ Status indicators (running/success/error)
✅ Cached badges
✅ Auto-fix badges

---

## TODO (Next Steps)

### High Priority
- [ ] **Config tab UI for LLM phases**
  - Soundings factor slider
  - Model dropdown (multi-model selection)
  - Handoffs phase selector
  - Wards configuration
  - Output schema editor

- [ ] **Mermaid diagram overlay**
  - Toggle button to show/hide
  - Generated from phase handoffs
  - Highlight active phase
  - Click nodes to select phases

- [ ] **Drag-and-drop reordering**
  - Use @dnd-kit (already imported)
  - Drag card left/right to reorder
  - Visual drop zone indicators

### Medium Priority
- [ ] **Soundings visualization**
  - Borrow stacked deck from playground
  - Show below selected phase card
  - Click to expand/compare attempts

- [ ] **Handoffs arrows**
  - Draw arrows in timeline strip
  - Show branching visually
  - Highlight on hover

- [ ] **Tool palette sidebar**
  - Browse all registered tackle
  - Drag-and-drop to add tools
  - Search/filter by category

### Low Priority
- [ ] Multi-cascade view (multiple tracks)
- [ ] Zoom controls (timeline compression)
- [ ] Minimap overview
- [ ] Keyboard shortcuts (arrow keys)
- [ ] Virtualization for 100+ phases

---

## Philosophy: Everything Is a Cascade

This UI handles **all cascade types** with one unified mental model:

1. **Data tools**: SQL → Python → SQL (save as tool)
2. **LLM prompts**: Soundings, wards, reforge
3. **Hybrid**: Mix data + LLM seamlessly
4. **HITL**: Decision points with generative UI
5. **Routing**: Branching via handoffs

**No separate builders** - just phases with different "lenses":
- SQL phase → Code editor with connection selector
- LLM phase → Config panel with soundings/wards
- HITL phase → Decision UI preview

**Progressive disclosure**:
- Beginner: SQL → Python (horizontal notebook)
- Intermediate: Add LLM phase (basic prompt)
- Advanced: Configure soundings, reforge, wards (full Windlass power)

---

## Terminology Shift

**Avoid "notebook"** - We're not competing with Jupyter.

**Better framings**:
- "Cascade Builder" (generic, accurate)
- "Flow Designer" (emphasizes orchestration)
- "Timeline Editor" (DAW analogy)
- "Phase Composer" (musical metaphor)

---

## Testing the UI

1. Start the dashboard:
   ```bash
   cd dashboard
   python backend/app.py  # Terminal 1

   cd dashboard/frontend
   npm start              # Terminal 2
   ```

2. Navigate to SQL Query IDE

3. Click **"Timeline"** toggle (third button, next to "Notebook")

4. Build a cascade:
   - Click "+ Add Phase"
   - Choose SQL or Python
   - Edit code in bottom panel
   - Run and see output
   - Add more phases
   - Try selecting different phases

---

## Design Inspiration

**DAW timelines**:
- Logic Pro X (horizontal tracks with regions)
- Premiere Pro (video clips on timeline)
- Ableton Live (session view)

**Cascade/workflow builders**:
- GitHub Actions (YAML + visual)
- n8n.io (node automation)
- Zapier (step builder)

**Our differentiation**:
- **Code-first** (not low-code drag-drop)
- **Linear flow primary** (branching is advanced)
- **Multiple views** of same YAML (timeline, YAML raw, diagram)
- **Cascade composition** (save as tool → use in bigger cascade)

---

## Status

**Version**: Experimental prototype (v0.1)
**Stability**: Alpha - core functionality works, lots of TODOs
**Access**: SQL Query IDE → "Timeline" mode
**Recommended use**: Explore the layout, provide feedback

**Feedback welcome**: How does the horizontal flow feel? Is 200px card width right? What features are critical?

---

## Files to Reference

- `CascadeTimeline.jsx` - Main layout component
- `PhaseCard.jsx` - Compact horizontal cards
- `PhaseDetailPanel.jsx` - Bottom panel with tabs
- `SqlQueryPage.js` - Mode toggle integration (line ~105-111)

**CSS**:
- `CascadeTimeline.css` - Timeline strip + control bar
- `PhaseCard.css` - Card styling + status colors
- `PhaseDetailPanel.css` - Detail panel tabs + layout
