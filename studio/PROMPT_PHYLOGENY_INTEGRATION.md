# Prompt Phylogeny Feature - Integration Guide

## ✅ What's Been Built

### 1. Backend API (`../dashboard/backend/sextant_api.py`)
**Endpoint**: `GET /api/sextant/evolution/<session_id>`

**Features**:
- Fetches all soundings for the same species (species_hash) as the given session
- Groups by sessions (generations)
- Returns React Flow compatible nodes and edges
- **Time-aware**: Shows evolution AS OF the session's timestamp by default
- Optional `include_future` param to show what came after (grayed out)
- Full metadata: cascade_id, phase_name, species_hash, session_count, etc.

**Query params**:
- `as_of`: 'session' (default), 'latest', or ISO timestamp
- `include_future`: true/false (show runs after this session)
- `phase_name`: optional phase filter

### 2. Frontend Component (`../dashboard/frontend/src/components/PromptPhylogeny.js`)
**Features**:
- React Flow visualization with custom PromptNode components
- Tournament bracket style layout (left → right = time progression)
- Winner path highlighting (green animated edges)
- Current session highlighting (blue border, 📍 marker)
- Future runs (if enabled) shown grayed out with dashed borders
- Node details: prompt preview, mutation type/template, model, winner status
- Click to expand full prompt in node
- Minimap, zoom/pan controls
- Legend showing icons and path meanings

**Styling** (`PromptPhylogeny.css`):
- Professional card-based nodes
- Color coding: green=winner, blue=current, purple/yellow/blue=mutation types
- Animated winner paths with glow effect
- Responsive, scrollable canvas
- Loading/error/empty states

## 🔧 Integration Steps

### Step 1: Add to SoundingsExplorer

**File**: `../dashboard/frontend/src/components/SoundingsExplorer.js`

**1.1 Import the component** (top of file):
```javascript
import PromptPhylogeny from './PromptPhylogeny';
```

**1.2 Add state** (around line 145):
```javascript
const [phylogenyExpanded, setPhylogenyExpanded] = useState(false);
```

**1.3 Add button to header** (around line 310, in `.header-right`):
```javascript
<div className="header-right">
  <button
    className="phylogeny-toggle-button"
    onClick={() => setPhylogenyExpanded(!phylogenyExpanded)}
    title="View prompt evolution across runs"
  >
    <Icon icon="mdi:family-tree" width="20" />
    <span>Evolution</span>
  </button>
  <span className="total-cost">Total: {formatCost(totalCost)}</span>
  <button className="close-button" onClick={onClose}>
    <Icon icon="mdi:close" width="24" />
  </button>
</div>
```

**1.4 Add phylogeny panel** (after `.phase-timeline`, before closing `.explorer-content`):
```javascript
{/* Prompt Phylogeny Panel */}
{phylogenyExpanded && (
  <div className="phylogeny-panel">
    <div className="phylogeny-panel-header">
      <h3>Prompt Evolution</h3>
      <button
        className="collapse-button"
        onClick={() => setPhylogenyExpanded(false)}
        title="Collapse"
      >
        <Icon icon="mdi:chevron-down" width="20" />
      </button>
    </div>
    <div className="phylogeny-panel-content">
      <PromptPhylogeny sessionId={sessionId} />
    </div>
  </div>
)}
```

### Step 2: Add Styles to SoundingsExplorer.css

```css
/* Phylogeny Toggle Button */
.phylogeny-toggle-button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.phylogeny-toggle-button:hover {
  background: #2563eb;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(59, 130, 246, 0.3);
}

/* Phylogeny Panel */
.phylogeny-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60vh;
  background: white;
  border-top: 2px solid #e5e7eb;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  display: flex;
  flex-direction: column;
}

.phylogeny-panel-header {
  padding: 12px 20px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f9fafb;
}

.phylogeny-panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.collapse-button {
  background: none;
  border: none;
  cursor: pointer;
  color: #6b7280;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}

.collapse-button:hover {
  background: #e5e7eb;
  color: #111827;
}

.phylogeny-panel-content {
  flex: 1;
  overflow: hidden;
}
```

### Step 3: Install React Flow

```bash
cd dashboard/frontend
npm install reactflow
```

### Step 4: Test

```bash
# Start dashboard
cd dashboard
./start.sh

# Open browser to session with soundings
# Click "Evolution" button in Soundings Explorer header
# Should see phylogeny visualization
```

## 🎯 Features & UX

### User Journey

1. **Open Soundings Explorer** for any session
2. **Click "Evolution" button** in header (new blue button with tree icon)
3. **Panel slides up** from bottom (60% viewport height)
4. **See evolution tree**:
   - Left → Right = time progression
   - Each column = one run (generation)
   - Green paths = winner lineage
   - Blue highlight = current session (where you are)
   - Gray/dashed = future runs (if toggle enabled)

5. **Interact**:
   - Click nodes to expand full prompt
   - Pan/zoom canvas
   - Toggle "Show future runs" to see what came after
   - Use minimap to navigate large trees

### Time-Travel Feature (ALREADY IMPLEMENTED!)

When viewing an old session, the tree shows:
- **Default view**: Evolution as it was AT THAT TIME
- **Optional**: Show future runs (grayed out) with checkbox

Example:
- You're viewing session from 2 weeks ago
- Tree shows 5 generations that existed then
- Click "Show future runs" → see 10 more generations added since (dimmed)

This lets you see "what the prompt knew at that moment" vs "how it evolved after".

## 📊 Data Requirements

### Backend
- ✅ `unified_logs` table with `species_hash`, `mutation_applied`, `mutation_type`, `mutation_template`, `is_winner`
- ✅ Sessions grouped by `species_hash` for apples-to-apples comparison
- ✅ Timestamp filtering for time-travel

### What Makes This Work
- **Species hash** = fingerprint of phase config
- Same species across runs = comparable evolution
- Winner metadata enables "royal lineage" highlighting
- Mutation metadata shows HOW prompts changed

## 🚀 Next Steps (Optional Enhancements)

### 1. Diff View (Phase 2)
- Click two nodes → show side-by-side diff
- Highlight what changed between generations

### 2. Search/Filter (Phase 2)
- Search prompt text
- Filter by mutation type
- Jump to specific generation

### 3. Export (Phase 2)
- Export as PNG/SVG for docs
- Share link to specific tree
- Embed in README

### 4. Analytics Overlay (Phase 2)
- Color by quality score
- Show cost per node
- Convergence metrics

## 🎨 Visual Design

```
┌─────────────────────────────────────────────────────────┐
│ Soundings Explorer                     [Evolution] [×]  │ ← New button!
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Phase Timeline (existing content)                      │
│  ...                                                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
            ↓ Click "Evolution"
┌─────────────────────────────────────────────────────────┐
│ Prompt Evolution                                 [▼]    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Gen 1      Gen 2      Gen 3      Gen 4                │
│  ┌────┐    ┌────┐    ┌────┐    ┌────┐                 │
│  │ 👑 │───→│    │───→│ 👑 │───→│📍  │                 │
│  └────┘    └────┘    └────┘    └────┘                 │
│    │         │                                          │
│  ┌────┐    ┌────┐                                      │
│  │    │───→│    │                                      │
│  └────┘    └────┘                                      │
│                                                          │
│  [MiniMap] [+] [-]  Legend: 👑 Winner 📍 You           │
└─────────────────────────────────────────────────────────┘
```

## 🧪 Testing Checklist

- [ ] Backend endpoint returns data for test session
- [ ] React Flow renders nodes correctly
- [ ] Winner paths are green and animated
- [ ] Current session is highlighted blue
- [ ] Click node expands/collapses prompt
- [ ] Future runs toggle works
- [ ] Minimap shows tree overview
- [ ] Pan/zoom works smoothly
- [ ] Empty state shows when no data
- [ ] Loading spinner during fetch
- [ ] Error handling when endpoint fails

## 📝 Documentation Updates Needed

1. **User Guide**: Add section on using Phylogeny view
2. **Architecture Docs**: Explain species-based evolution tracking
3. **API Docs**: Document `/api/sextant/evolution` endpoint
4. **Screenshots**: Add to README showing evolution tree

## 🎉 Impact

**Before**: Users couldn't see how prompts evolved across runs
**After**: Beautiful visual timeline showing:
- What won in past runs
- How mutations built on winners
- Convergence patterns over time
- Your current position in the evolution

**Aligns with Lars Philosophy**:
- ✅ Self-Testing: Evolution captured automatically
- ✅ Self-Optimizing: Visual feedback on what works
- ✅ Explicit: Full observability of learning process
- ✅ Species-Based: Fair apples-to-apples comparisons

---

**Status**: Backend + Frontend components complete, integration pending.
**Estimated time to integrate**: 30-45 minutes
**Dependencies**: `reactflow` npm package
