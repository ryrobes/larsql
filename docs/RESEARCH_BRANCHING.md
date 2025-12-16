# Research Branching 🌳

**Git-style timeline branching for research sessions with visual lineage**

Create alternate research timelines by re-submitting checkpoints with different responses. Each branch is a full cascade execution with backfilled context.

---

## How It Works

### The Core Concept

Every checkpoint is a **potential branch point**. When you:
1. Load a saved research session
2. Expand a checkpoint from the timeline
3. Submit the form with a **different response**

→ A new branch is automatically created!

### What Happens Behind the Scenes

```
Parent Session: research_123
├─ Checkpoint 1: "What is quantum computing?"
├─ Checkpoint 2: "How do algorithms work?"  ← You are here
│  └─ Response: {"query": "Tell me about Shor's algorithm"}
│
User expands checkpoint #2, submits different response:
    {"query": "Actually, focus on quantum cryptography"}
    ↓
Backend:
  1. Loads parent session: research_123
  2. Gets all entries up to checkpoint #2 timestamp
  3. Creates new Echo with pre-populated:
     - history: All messages up to checkpoint #2
     - state: All state variables from parent
     - parent_session_id: research_123 (linked!)
  4. Injects new response into state
  5. Launches cascade with session_id: research_1734567890
     - Regular cascade execution
     - Auto-saves with parent link
    ↓
New Branch Session: research_1734567890
├─ (Inherited context from parent)
├─ Checkpoint 2b: "Actually, focus on quantum cryptography"
├─ Checkpoint 3: LLM researches cryptography...
└─ Checkpoint 4: Continue exploring...

Result:
  Parent (research_123) → Branch (research_1734567890)
  Auto-saved with parent_session_id and branch_point_checkpoint_id
```

---

## Visual Experience

### Timeline View

When you load a saved session, you see:

```
┌─────────────────────────────────────────┐
│ 📜 Saved Research Session               │
│ "Quantum Computing Deep Dive"           │
│ $0.0234 • 7 turns                       │
├─────────────────────────────────────────┤
│                                         │
│ ┌─ 1 ──────────────────────────────┐   │
│ │ ● What is quantum computing?     │ ▼ │ ← Click to expand
│ └──────────────────────────────────────┘ │
│     ┌─ ORIGINAL UI ────────────────┐   │
│     │ [Full HTMX iframe with       │   │
│     │  charts, tables, etc.]       │   │
│     │                              │   │
│     │ 🌿 Submit to create branch ← │   │ ← Hint!
│     └──────────────────────────────────┘ │
│     ┌─ YOUR RESPONSE ─────────────┐    │
│     │ {"query": "How do           │   │
│     │  algorithms work?"}          │   │
│     └──────────────────────────────────┘ │
│                                         │
│ ┌─ 2 ──────────────────────────────┐   │
│ │ ● How do quantum algorithms      │   │
│ │   work?                          │ ▼ │
│ └──────────────────────────────────────┘ │
│     [Click to expand and branch...]     │
│                                         │
└─────────────────────────────────────────┘
```

### Sidebar Tree Visualization

When branches exist, sidebar shows **D3 tree** instead of execution graph:

```
┌─ SIDEBAR ──────────────────┐
│ 🌳 Research Tree           │
│ 3 sessions                 │
├────────────────────────────┤
│                            │
│   Root Session             │
│   ● ─────────┐            │
│              ├─ ● Branch A │ ← Purple (current path)
│              │   $0.02     │
│              │             │
│              └─ ● Branch B │ ← Green (completed)
│                  $0.03     │
│                            │
│ Click any node to navigate │
└────────────────────────────┘
```

**Visual Indicators:**
- **Purple path** - Current session lineage (highlighted)
- **Green nodes** - Completed branches
- **Yellow nodes** - Active branches
- **Thick lines** - Current path
- **Thin lines** - Other branches
- **Pulsing** - Current node

---

## Usage

### Create a Branch

**From Saved Session:**
1. Open Research Cockpit
2. Go to "Saved Sessions" tab
3. Click any saved session
4. Expand any checkpoint in the timeline
5. **Change the input** in the form
6. Submit → 🌿 Branch created!

**What You See:**
- Alert: "🌿 Branch created! New session: research_..."
- Automatically navigates to new branch
- Sidebar updates to show tree with 2 nodes

### Navigate Between Branches

**Option 1: Sidebar Tree**
- Scroll to "Research Tree" in sidebar
- Click any node → navigate instantly

**Option 2: Saved Sessions List**
- Expand "Saved Sessions" in sidebar
- See all branches listed
- Click to navigate

**Option 3: Picker Modal**
- Open Research Cockpit
- "Saved Sessions" tab
- See parent + all branches
- Click any to load

---

## Data Model

### Research Session Record

```sql
research_sessions:
  id: research_session_abc123
  original_session_id: research_1734567890  -- The live session ID
  cascade_id: research_cockpit_demo

  -- BRANCHING METADATA
  parent_session_id: research_123           -- Link to parent!
  branch_point_checkpoint_id: checkpoint_xyz -- Where it forked

  -- FULL CONTEXT (for reconstruction)
  entries_snapshot: [...]  -- All log entries up to branch point + new ones
  checkpoints_data: [...]  -- All checkpoints
  context_snapshot: {...}  -- Echo state
```

### Tree Query

```sql
-- Get all branches of a session
SELECT * FROM research_sessions
WHERE parent_session_id = 'research_original'

-- Get full tree (recursive)
WITH RECURSIVE tree AS (
    SELECT * FROM research_sessions WHERE id = 'research_session_root'
    UNION ALL
    SELECT rs.* FROM research_sessions rs
    JOIN tree ON rs.parent_session_id = tree.original_session_id
)
SELECT * FROM tree
```

---

## Architecture

### Backend Components

**1. `branching.py`** (`windlass/windlass/eddies/branching.py`)
- `restore_echo_from_branch_point()` - Creates Echo with history up to branch
- `launch_branch_cascade()` - Starts new cascade with pre-populated context

**2. `event_hooks.py`** (updated)
- `ResearchSessionAutoSaveHooks._save_or_update_session()` - Captures parent/branch metadata
- Detects Echo.parent_session_id automatically

**3. Backend API** (`app.py`)
- `POST /api/research-sessions/branch` - Create branch from checkpoint
- `GET /api/research-sessions/tree/{session_id}` - Get tree structure

### Frontend Components

**1. `ResearchCockpit.js`** (updated)
- Fetches savedSessionData with full checkpoints
- `handleCreateBranch()` - Calls branch API
- `ExpandableCheckpoint` - Renders expandable timeline

**2. `HTMLSection.js`** (updated)
- Intercepts form submissions when `isSavedCheckpoint=true`
- Calls `onBranchSubmit()` instead of checkpoint API
- Shows "🌿 Submit to create branch" hint

**3. `ResearchTreeVisualization.js`** (new)
- D3 tree layout
- Highlights current path (purple)
- Click nodes to navigate
- Shows cost/turns per node

**4. `LiveOrchestrationSidebar.js`** (updated)
- Detects if session has branches
- Shows tree instead of execution graph when branches exist
- Auto-updates as branches are created

---

## Example Flow

### Session 1: Original Research

```
research_1734567890 (original)
├─ ① "What is quantum computing?"
├─ ② "How do algorithms work?"
└─ ③ "Real-world applications?"

Auto-saved as: research_session_original
```

### Branch A: Cryptography Focus

```
User action:
  1. Load research_session_original
  2. Expand checkpoint #2
  3. Submit: "Actually, focus on cryptography"

Backend creates:
  research_1734567891 (branch)
  - parent_session_id: research_1734567890
  - branch_point_checkpoint_id: checkpoint_2
  - Pre-loaded with context from checkpoints 1-2
  - Continues from there

Timeline:
├─ (Inherited) ① "What is quantum computing?"
├─ (Inherited) ② "How do algorithms work?"
├─ ② NEW: "Focus on cryptography"  ← Branch point!
├─ ③ LLM researches quantum cryptography...
└─ ④ Continue exploring crypto...

Auto-saved as: research_session_crypto_branch
```

### Branch B: Hardware Focus

```
User action:
  1. Load research_session_original (again)
  2. Expand checkpoint #2 (again)
  3. Submit: "Tell me about quantum hardware"

Backend creates:
  research_1734567892 (another branch)
  - parent_session_id: research_1734567890 (same parent!)
  - branch_point_checkpoint_id: checkpoint_2 (same branch point!)

Timeline:
├─ (Inherited) ① "What is quantum computing?"
├─ (Inherited) ② "How do algorithms work?"
├─ ② NEW: "Tell me about quantum hardware"  ← Different branch!
├─ ③ LLM researches superconducting qubits...
└─ ④ Continue exploring hardware...

Auto-saved as: research_session_hardware_branch
```

### Visual Tree

```
      Root Session
      ● ────────┐
                ├─ ● Crypto Branch (current)
                │   $0.02 • 5 turns
                │
                └─ ● Hardware Branch
                    $0.03 • 6 turns

Purple path: Root → Crypto (highlighted)
Green nodes: Completed branches
Click to navigate between them!
```

---

## Key Features

### 1. **No Special Cascade Logic**

Branches are **just regular cascades** that:
- Start with pre-populated Echo
- Have parent_session_id metadata
- Execute normally from the loop phase

The cascade doesn't know it's a branch!

### 2. **Full Context Preservation**

Each branch inherits:
- ✅ All history up to branch point
- ✅ All state variables
- ✅ All lineage metadata
- ✅ Tool call history

Then continues independently.

### 3. **Auto-Save Captures Lineage**

When ResearchSessionAutoSaveHooks saves a branch:
- Detects Echo.parent_session_id
- Stores in research_sessions table
- Builds tree relationships automatically

### 4. **Visual Replay + Branching**

Saved checkpoints show **full HTMX UI**:
- All charts re-render
- All tables display
- All interactive content works
- Change input → create branch!

### 5. **D3 Tree Navigation**

Sidebar shows:
- Full branch structure
- Current path highlighted
- Click to switch branches
- See costs per branch

---

## Use Cases

### 1. **Comparative Research**

```
Question: "Best database for my use case?"

Original path:
  → Researches PostgreSQL → $0.02

Branch A:
  → Researches MongoDB → $0.03

Branch B:
  → Researches ClickHouse → $0.01

Compare all three! Pick the winner.
```

### 2. **Hypothesis Testing**

```
Root: "Analyze sales data"

Branch A: "Focus on Q4 trends"
Branch B: "Focus on regional differences"
Branch C: "Focus on product categories"

Each branch explores different analytical angle.
Compare insights across branches.
```

### 3. **Error Recovery**

```
Session hits error at checkpoint #3

Branch back to checkpoint #2
Try different approach
Explore alternate path that works
```

### 4. **Teaching/Demos**

```
Show students:
  "Here's what happens if you ask it THIS way"
  vs.
  "Here's what happens if you ask it THAT way"

Side-by-side comparison of research strategies.
```

---

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Echo Restoration | ✅ Complete | `windlass/eddies/branching.py` |
| Branch Endpoint | ✅ Complete | `app.py:4359` (POST /api/research-sessions/branch) |
| Tree Endpoint | ✅ Complete | `app.py:4434` (GET /api/research-sessions/tree/{id}) |
| Auto-Save Branching | ✅ Complete | `event_hooks.py` (captures parent_session_id) |
| Form Interception | ✅ Complete | `HTMLSection.js:75-113` |
| Timeline UI | ✅ Complete | `ExpandableCheckpoint` component |
| D3 Tree Viz | ✅ Complete | `ResearchTreeVisualization.js` |
| Sidebar Integration | ✅ Complete | Shows tree when branches detected |

---

## Technical Details

### Echo Restoration

```python
def restore_echo_from_branch_point(parent_session, branch_checkpoint_index):
    # Get all entries before branch point
    branch_checkpoint = parent_session['checkpoints_data'][branch_checkpoint_index]
    branch_timestamp = branch_checkpoint['created_at']

    entries_before = [e for e in entries if e['timestamp'] <= branch_timestamp]

    # Create Echo with parent link
    echo = Echo(
        session_id=f"research_{timestamp}",
        initial_state=parent_session['context_snapshot']['state'],
        parent_session_id=parent_session['original_session_id']  # Link!
    )

    # Populate history
    for entry in entries_before:
        if entry['role'] in ['user', 'assistant', 'system']:
            echo.history.append(entry)

    return echo, new_session_id, branch_checkpoint_id
```

### Branch Detection

Forms in saved checkpoints have special handling:

```javascript
// HTMLSection.js
if (isSavedCheckpoint && onBranchSubmit) {
    iframe.addEventListener('submit', (e) => {
        // Extract form data
        const response = extractFormData(e.target);

        // Don't submit to checkpoint API
        // Instead, create branch!
        onBranchSubmit(response);

        e.preventDefault();
    });
}
```

### Tree Query

```sql
-- Find all sessions in a tree
SELECT * FROM research_sessions
WHERE original_session_id = 'root_id'
   OR parent_session_id = 'root_id'
   OR parent_session_id IN (
       SELECT original_session_id
       FROM research_sessions
       WHERE parent_session_id = 'root_id'
   )
```

Builds hierarchical structure for D3 rendering.

---

## D3 Tree Visualization

### Layout

- **Horizontal tree** (root on left, branches on right)
- **Nodes**: Circles colored by status
  - Purple: Current session (pulsing)
  - Purple path: Ancestors of current
  - Green: Completed branches
  - Yellow: Active branches
- **Edges**: Lines between parent/child
  - Thick purple: Current path
  - Thin gray: Other branches
- **Labels**: Session title + cost/turns

### Interactions

- **Click node** → Navigate to that session
- **Hover node** → Tooltip with details
- **Current node** → Pulsing glow effect

### Smart Display

Only shows when:
- Session has parent (is a branch)
- Session has children (has branches)

Otherwise shows execution graph (single-phase loops aren't interesting).

---

## Future Enhancements

### Branch Comparison

```
Show side-by-side:
  Branch A: Crypto approach → Total cost: $0.02
  Branch B: Hardware approach → Total cost: $0.03

Winner: Branch A (cheaper and more comprehensive)
```

### Branch Merging

```
Branches:
  A: Researched quantum algorithms
  B: Researched quantum hardware

Merge:
  LLM synthesizes both
  Creates merged understanding
  → New branch with combined knowledge
```

### Branch Metadata

Each branch could track:
- Hypothesis tested
- Success metrics
- Comparison to parent
- Recommended next branches

### Time Travel

```
Load any branch
See full timeline
Scrub through history
Create new branch at any point
```

---

## Architecture Advantages

### 1. **No Special Runner Logic**

Branches are **regular cascades**:
- Same execution path
- Same tool calls
- Same phase routing
- Just with pre-populated Echo

The cascade doesn't know it's a branch!

### 2. **Parent/Child Links**

Simple foreign key relationship:
```sql
parent_session_id → original_session_id
```

Enables:
- Tree queries
- Lineage tracking
- Breadcrumb navigation

### 3. **Full Context Capture**

Each branch saves:
- Complete entries_snapshot
- All checkpoints
- Full state
- Parent linkage

Can reconstruct **any point** in any branch!

### 4. **Zero UI Complications**

Forms just work:
- In live session → normal checkpoint response
- In saved session → automatic branch creation

User doesn't think about it!

---

## Comparison to Other Systems

| Feature | Windlass Research Branching | ChatGPT | Claude | Obsidian Canvas |
|---------|----------------------------|---------|--------|-----------------|
| **Timeline Branching** | ✅ Auto from checkpoints | ❌ No | ❌ No | ⚠️ Manual nodes |
| **Context Preservation** | ✅ Full | ❌ Lost | ⚠️ Partial | ❌ Manual |
| **Visual Lineage** | ✅ D3 tree | ❌ No | ❌ No | ✅ Canvas |
| **Click to Branch** | ✅ Re-submit form | ❌ No | ❌ No | ⚠️ Manual |
| **Cost per Branch** | ✅ Tracked | ❌ No | ❌ No | ❌ No |
| **Execution Replay** | ✅ Full HTMX | ❌ No | ⚠️ Artifacts | ❌ No |
| **Merge Branches** | 🚧 Planned | ❌ No | ❌ No | ⚠️ Manual |

---

## Files Modified/Created

**Backend:**
- `windlass/eddies/branching.py` - Echo restoration + branch launch
- `dashboard/backend/app.py` - 2 new endpoints (branch, tree)
- `windlass/event_hooks.py` - Capture parent/branch metadata

**Frontend:**
- `ResearchCockpit.js` - Branch handler + timeline UI
- `HTMLSection.js` - Form interception for branching
- `ResearchTreeVisualization.js` - D3 tree component
- `LiveOrchestrationSidebar.js` - Show tree when branches exist
- `ResearchCockpit.css` - Timeline + branch styling
- `ResearchTreeVisualization.css` - D3 tree styling

**Dependencies:**
- `package.json` - Added `d3: ^7.9.0`

---

## Setup

### Install D3

```bash
cd dashboard/frontend
npm install
```

### Restart Backend

```bash
cd dashboard/backend
python app.py
```

The backend now has branching support enabled!

---

## Test It

### 1. Create Initial Session

```bash
# Launch cascade in Research Cockpit
# Interact with 3-4 checkpoints
# Let it auto-save
```

### 2. Load Saved Session

```bash
# Open Research Cockpit
# Go to "Saved Sessions" tab
# Click your session
```

### 3. Create Branch

```bash
# Expand checkpoint #2
# Change the input text
# Submit form
# → 🌿 Alert: "Branch created!"
# → Auto-navigate to new branch
```

### 4. See Tree

```bash
# Scroll to sidebar
# See "Research Tree" section
# Purple path shows: Root → Current
# Click root to go back
# Click branch to return
```

### 5. Create More Branches

```bash
# Go back to root
# Expand checkpoint #1 (different point)
# Submit different response
# → Another branch!
# Tree now shows 3 sessions
```

---

## Next Steps

### Immediate

✅ Install d3: `cd dashboard/frontend && npm install`
✅ Restart backend
✅ Test branching!

### Short-term

- Add breadcrumb navigation ("Root > Branch A > Current")
- Show branch point in timeline ("Branched here" marker)
- Branch comparison view (side-by-side)

### Medium-term

- Branch merging (LLM synthesizes multiple branches)
- Branch diff (show what changed)
- Recommended branches (LLM suggests alternate questions)
- Branch templates (save branching strategies)

### Long-term

- Multi-user collaborative branching
- Branch voting (crowd-source best paths)
- Branch analytics (which strategies work best)
- Auto-branching (LLM creates branches to explore multiple angles)

---

## Credits

**Inspired by:**
- **Git** - Branching and merging model
- **Bret Victor** - "Seeing Spaces" - make execution visible
- **Obsidian** - Knowledge graphs and canvas
- **Quantum Many-Worlds** - Parallel timelines!

**Novel Contributions:**
- Auto-branching from form submissions
- Full visual context preservation
- D3 research tree with path highlighting
- Zero-friction branch creation
- Temporal versioning with orchestration metadata

---

**Branch your research. Explore all timelines. 🌳**
