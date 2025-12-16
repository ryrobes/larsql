# Temporal Research Sessions 🕰️

**Git for LLM Conversations - Save, Resume, and Branch Research Sessions**

Research Sessions add temporal versioning to the Research Cockpit, enabling you to:
- 💾 **Save** sessions at any point
- ⏯️ **Resume** from where you left off (future)
- 🌳 **Branch** from any checkpoint to explore alternate paths (future)
- 📚 **Browse** previous research sessions
- 🔄 **Compare** different research approaches

---

## Architecture

### Data Model

Each saved research session captures:

```json
{
  "id": "research_session_abc123",
  "original_session_id": "research_1734283894714",
  "cascade_id": "research_cockpit_demo",

  // User-facing metadata
  "title": "Quantum Computing Deep Dive",
  "description": "Explored quantum algorithms, hardware, applications",
  "tags": ["quantum", "physics", "computing"],
  "status": "completed",  // or "paused"

  // Timestamps
  "created_at": "2024-12-15T14:30:00",
  "frozen_at": "2024-12-15T14:45:00",

  // Complete context for resumption
  "context_snapshot": {
    "state": {...},      // Echo state variables
    "history": [...],    // Full message history
    "lineage": {...}     // Execution lineage
  },

  // All interactions (branch points)
  "checkpoints_data": [
    {
      "id": "cp_123",
      "phase_name": "research_loop",
      "phase_output": "What is quantum entanglement?",
      "response": {"query": "How does quantum computing work?"},
      "can_branch_from": true,  // Future: create alternate timeline from here
      "responded_at": "2024-12-15T14:32:00"
    },
    // ... more checkpoints
  ],

  // Raw execution log
  "entries_snapshot": [...],  // Full unified_logs entries

  // Visual artifacts
  "mermaid_graph": "graph TD\n  A-->B...",
  "screenshots": ["path1.png", "path2.png"],

  // Computed metrics
  "metrics": {
    "total_cost": 0.0234,
    "total_turns": 7,
    "total_input_tokens": 12345,
    "total_output_tokens": 8901,
    "duration_seconds": 125,
    "phases_visited": ["research_loop"],
    "tools_used": ["web_search", "create_chart", "run_code"]
  },

  // Branching metadata (future)
  "parent_session_id": null,  // If branched from another session
  "branch_point_checkpoint_id": null  // Which checkpoint was the branch point
}
```

### Database Schema

**Table:** `research_sessions`

See: `windlass/migrations/create_research_sessions_table.sql`

**Indexes:**
- Primary: `(cascade_id, frozen_at, id)`
- Enables fast filtering by cascade and time-sorted browsing

---

## Usage

### From the UI

#### 1. Save Current Session

While in Research Cockpit:
1. Click **"Save Session"** button in header (green, next to "New Session")
2. Enter optional title, description, tags
3. Session is frozen and saved

#### 2. Browse Previous Sessions

In the sidebar (bottom section):
1. Click **"Previous Sessions (N)"** to expand
2. See list of saved sessions for this cascade
3. Click any session to load it (navigates to `#/cockpit/{session_id}`)

Each session card shows:
- Title
- Description
- Cost, turns, duration
- Tags
- Save date

#### 3. View Saved Session

Navigate to a saved session:
- Read-only view of the frozen conversation
- See full Mermaid graph
- See all metrics and timeline
- (Future: Resume or branch button)

### From Cascades

Add to your cascade's tackle:

```yaml
phases:
  - name: research_complete
    tackle:
      - save_research_session
    instructions: |
      Research is complete. Save this session for future reference.

      Use save_research_session with:
      - title: Generated from the initial query
      - description: Summary of what was researched
      - tags: Relevant topic tags
```

Example tool call:
```python
save_research_session(
    title="Quantum Computing Research",
    description="Explored quantum algorithms, hardware, and applications",
    tags=["quantum", "computing", "physics"]
)
```

---

## API Endpoints

### GET /api/research-sessions

List saved sessions with optional filtering.

**Query params:**
- `cascade_id` (optional): Filter by cascade
- `limit` (optional, default 20): Max results

**Response:**
```json
{
  "sessions": [
    {
      "id": "research_session_...",
      "title": "...",
      "description": "...",
      "total_cost": 0.0234,
      "total_turns": 7,
      "frozen_at": "...",
      "tags": [...]
    }
  ],
  "count": 10
}
```

### GET /api/research-sessions/{id}

Get full session data including context for resumption.

**Response:**
```json
{
  "id": "research_session_...",
  "context_snapshot": {...},  // Parsed JSON
  "checkpoints_data": [...],  // Parsed JSON
  "entries_snapshot": [...],  // Parsed JSON
  "mermaid_graph": "graph TD...",
  // ... all fields
}
```

### POST /api/research-sessions/save

Save a research session from the UI.

**Body:**
```json
{
  "session_id": "research_123",
  "title": "Optional title",
  "description": "Optional description",
  "tags": ["tag1", "tag2"]
}
```

**Response:**
```json
{
  "saved": true,
  "research_session_id": "research_session_...",
  "title": "...",
  "checkpoints_count": 5,
  "total_cost": 0.0234
}
```

---

## Future Capabilities

### Resumption (Not Yet Implemented)

```
Load saved session → Restore Echo context → Continue cascade from last checkpoint
```

Implementation plan:
1. Load `context_snapshot` into new Echo instance
2. Load `entries_snapshot` to rebuild history
3. Find last checkpoint in cascade
4. Continue execution from there

### Branching (Not Yet Implemented)

```
Load session → Pick checkpoint → Create branch → Explore alternate path
```

Each checkpoint is marked with `can_branch_from: true` if it was responded to.

**Use cases:**
- "What if I had asked a different question?"
- Compare multiple research paths
- A/B test different prompts
- Create research trees (not linear timelines)

**Implementation plan:**
1. UI: Click "Branch from here" on any checkpoint
2. Backend: Create new session with:
   - `parent_session_id`: Original session
   - `branch_point_checkpoint_id`: Checkpoint to branch from
   - Context loaded up to that checkpoint
3. Continue with different response

**Visualization:**
```
Original Timeline:
  Q1 → A1 → Q2 → A2 → Q3 → A3
                    ↓
                  Branch A:
                    Q2' → A2' → Q3' → A3'
                    ↓
                  Branch B:
                    Q2'' → A2'' → ...
```

### Multi-User Collaboration (Not Yet Implemented)

Multiple users connected to same research session:
- Real-time updates via SSE
- See others' questions/responses
- Collaborative research dashboard

---

## Data Captured for Future Features

The system already captures all data needed for:

✅ **Resumption:**
- `context_snapshot` - Full Echo state
- `entries_snapshot` - Complete execution log
- Last checkpoint location

✅ **Branching:**
- `checkpoints_data` with `can_branch_from` flags
- `branch_point_checkpoint_id` field ready
- Parent/child relationship via `parent_session_id`

✅ **Replay:**
- Full execution trace in `entries_snapshot`
- All tool calls and responses
- Timing information

✅ **Analysis:**
- Tools used
- Phases visited
- Cost breakdown
- Token usage
- Duration metrics

✅ **Search:**
- Title, description, tags
- Full-text search in checkpoints (future index)

---

## Comparison to Other Systems

| Feature | Windlass Research Sessions | ChatGPT Threads | Claude Projects | Perplexity |
|---------|---------------------------|-----------------|-----------------|------------|
| **Save Sessions** | ✅ Full context | ✅ Basic | ✅ Basic | ❌ No |
| **Resume from Checkpoint** | 🚧 Planned | ❌ No | ❌ No | ❌ No |
| **Branch at Any Point** | 🚧 Planned | ❌ No | ❌ No | ❌ No |
| **Execution Graph** | ✅ Mermaid | ❌ No | ❌ No | ❌ No |
| **Cost Tracking** | ✅ Per-turn | ❌ No | ❌ No | ❌ No |
| **Tool Call History** | ✅ Full | ⚠️ Partial | ⚠️ Partial | ⚠️ Partial |
| **Orchestration Visibility** | ✅ Full | ❌ No | ❌ No | ❌ No |
| **Declarative Workflows** | ✅ YAML | ❌ No | ❌ No | ❌ No |
| **Self-Hosted** | ✅ Yes | ❌ No | ❌ No | ❌ No |

---

## Technical Implementation

### Frontend Components

**ResearchCockpit.js** (`dashboard/frontend/src/components/`)
- Save Session button in header
- Prompts for title/description/tags
- POSTs to `/api/research-sessions/save`

**LiveOrchestrationSidebar.js**
- Fetches previous sessions from `/api/research-sessions?cascade_id=...`
- Displays collapsible list
- Click to navigate to saved session
- Auto-refreshes when new sessions saved

### Backend

**app.py** (`dashboard/backend/`)
- `GET /api/research-sessions` - List with filtering
- `GET /api/research-sessions/{id}` - Get full session data
- `POST /api/research-sessions/save` - Save current session

**research_sessions.py** (`windlass/windlass/eddies/`)
- `save_research_session()` - Tool for cascades to save
- `list_research_sessions()` - Tool to query saved sessions
- `get_research_session()` - Tool to load session data

### Database

**Table:** `research_sessions`
**Location:** ClickHouse or Parquet (auto-detected)

**Migration:** `windlass/migrations/create_research_sessions_table.sql`

**Run migration:**
```bash
cat windlass/migrations/create_research_sessions_table.sql | clickhouse-client --host localhost
```

---

## Example Workflow

### 1. Research Session

```
User: Launch research_cockpit_demo
  ↓
Q1: "What is quantum computing?"
  → LLM researches, uses web_search, creates charts
  → Shows answer with visualizations
  ↓
Q2: "How do quantum algorithms work?"
  → LLM researches, uses run_code for examples
  → Shows code + explanations
  ↓
Q3: "What are real-world applications?"
  → LLM uses sql_query for case studies
  → Shows data tables + charts
  ↓
User: Click "Save Session"
  → Title: "Quantum Computing Deep Dive"
  → Tags: ["quantum", "computing", "algorithms"]
  → Saved with full context
```

### 2. Browse Later

```
User: Open Research Cockpit
  → Sidebar shows "Previous Sessions (1)"
  → Expand to see:
    - Quantum Computing Deep Dive
    - $0.0234 • 7 turns • 5m
    - 12/15/2024
  → Click to load (read-only view)
```

### 3. Resume (Future)

```
Load saved session
  → See full timeline
  → Click "Resume from last checkpoint"
  → Cascade continues with full context
  → Ask new questions!
```

### 4. Branch (Future)

```
Load saved session
  → See timeline with all checkpoints
  → Click checkpoint #2: "How do quantum algorithms work?"
  → Click "Branch from here"
  → Ask different question: "What about quantum cryptography?"
  → New timeline branches from checkpoint #2
  → Compare both paths side-by-side
```

---

## Use Cases

### 1. Long Research Projects
- Save progress after each session
- Resume days/weeks later with full context
- Build up knowledge over time

### 2. Comparative Research
- Research topic A → Save
- Research topic B → Save
- Compare approaches, costs, results

### 3. Teaching/Demos
- Save exemplar research sessions
- Share with others
- Replay successful research patterns

### 4. Debugging
- Save failing research session
- Analyze execution graph
- Identify where it went wrong
- Branch to try different approach

### 5. Cost Optimization
- Save multiple research sessions
- Compare costs for different cascades
- Optimize tool selection strategies

---

## Next Steps

### Immediate (Already Works)

✅ Save sessions with metadata
✅ Browse previous sessions in sidebar
✅ Load saved sessions (read-only)
✅ View execution graphs
✅ See full metrics

### Short-term (Next to Implement)

🚧 Resume from last checkpoint
🚧 Edit session title/tags after saving
🚧 Delete saved sessions
🚧 Export session as markdown report

### Medium-term (Future Features)

🔮 Branch from any checkpoint
🔮 Compare branch outcomes
🔮 Merge branches (combine learnings)
🔮 Session templates (save cascade + inputs)
🔮 Collaborative sessions (multi-user)

### Long-term (Research Ideas)

💭 Automatic session summarization (LLM-generated)
💭 Session search (semantic search across all research)
💭 Research graphs (visualize relationships between sessions)
💭 Session diff (compare two research sessions)
💭 Time-travel debugging (replay with different tools/models)

---

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Database Schema | ✅ Complete | `windlass/migrations/create_research_sessions_table.sql` |
| Backend API | ✅ Complete | `dashboard/backend/app.py` (lines 4247-4582) |
| Python Tools | ✅ Complete | `windlass/windlass/eddies/research_sessions.py` |
| Save Button | ✅ Complete | `ResearchCockpit.js` header |
| Sessions Browser | ✅ Complete | `LiveOrchestrationSidebar.js` (collapsible) |
| Resumption Logic | ⏳ Planned | Future work |
| Branching UI | ⏳ Planned | Future work |

---

## Files Created

**Backend:**
- `windlass/migrations/create_research_sessions_table.sql` - Schema
- `windlass/windlass/eddies/research_sessions.py` - Tools (save, list, get)
- `dashboard/backend/app.py` - API endpoints (3 new routes)

**Frontend:**
- `LiveOrchestrationSidebar.js` - Previous sessions browser (added to existing)
- `ResearchCockpit.js` - Save button + handler (added to existing)

**Registration:**
- `windlass/windlass/__init__.py` - Registered 3 new tools

---

## Design Philosophy

### Temporal Versioning

Traditional chat interfaces are **ephemeral** - once you close the tab, context is lost.

Research Sessions make them **persistent and branchable**:
- Every session is saveable
- Every checkpoint is a potential branch point
- Full execution context preserved
- Timeline can fork into multiple explorations

### Bret Victor's "Seeing Spaces"

> "A tool should let you see what you're doing as you're doing it."

Research Sessions extend this to **time**:
- See past sessions in sidebar
- See current execution in main view
- See future possibilities (branch points)

### Git-like Mental Model

```
main timeline:
  commit A (checkpoint 1)
  commit B (checkpoint 2)  ← save as "quantum_research_v1"
  commit C (checkpoint 3)

branch from checkpoint 2:
  commit B
  commit D (different question)
  commit E (different path)  ← save as "quantum_research_v2_crypto"

compare:
  diff v1 vs v2
  merge learnings from both
```

---

## Technical Notes

### Context Snapshot

The `context_snapshot` preserves:
- **State:** All `set_state()` variables
- **History:** Full conversation (user + assistant + tool calls)
- **Lineage:** Execution tree metadata

This is enough to reconstruct the Echo and continue.

### Checkpoint Metadata

Each checkpoint stores:
- Original question/prompt
- User's response
- UI spec (for replay)
- Timestamp
- `can_branch_from` flag (true if completed)

### Entry Snapshot

Full unified_logs entries provide:
- Tool calls and results
- Cost per turn
- Token usage
- Timing data
- Model used

This enables:
- Replay with different model
- Cost analysis
- Performance optimization

---

## Future: Resumption Protocol

```python
# Load saved session
session = get_research_session("research_session_abc123")

# Restore Echo context
echo = Echo(session_id=new_session_id)
echo.state = session['context_snapshot']['state']
echo.history = session['context_snapshot']['history']
echo.lineage = session['context_snapshot']['lineage']

# Find last checkpoint
last_checkpoint = session['checkpoints_data'][-1]
last_phase = last_checkpoint['phase_name']

# Resume cascade from that phase
run_cascade(
    cascade_path=session['cascade_file'],
    inputs={},  # Already in state
    session_id=new_session_id,
    resume_from_phase=last_phase,
    initial_echo=echo
)
```

---

## Future: Branching Protocol

```python
# Load session and pick branch point
session = get_research_session("research_session_abc123")
branch_checkpoint = session['checkpoints_data'][2]  # Branch from 3rd checkpoint

# Rebuild context up to that point
echo = Echo(session_id=f"research_{uuid4()}_branch")

# Replay history up to branch point
for entry in session['entries_snapshot']:
    if entry['timestamp'] <= branch_checkpoint['created_at']:
        # Add to history
        echo.add_history(entry)

# Continue with different response
new_response = {"query": "Different question"}

# Run cascade from branch point
run_cascade(
    cascade_path=session['cascade_file'],
    inputs={},
    session_id=echo.session_id,
    resume_from_phase=branch_checkpoint['phase_name'],
    initial_echo=echo,
    override_next_response=new_response,
    parent_session_id=session['id'],
    branch_point=branch_checkpoint['id']
)
```

---

## Credits

**Inspired by:**
- **Git** - Temporal versioning with branches
- **Bret Victor** - "Seeing Spaces" talk
- **Obsidian** - Local-first knowledge graphs
- **Notion** - Page history and branching

**Novel contributions:**
- Temporal versioning for LLM conversations
- Checkpoint-based branching
- Full orchestration context preservation
- Declarative resume/branch semantics

---

**Version your research. Branch your thinking. 🌳**
