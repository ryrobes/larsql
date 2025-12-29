# ExploreView Implementation Plan v2

**Goal**: Create clean Perplexity-style research interface using AppShell architecture

**Key Changes from v1**:
- ❌ **NO SSE** - Use Studio's polling pattern instead
- ✅ **Iteration 1 only** - Core loop, defer timeline/branching
- ✅ **Framer Motion** - Smooth animations throughout
- ✅ **Extensibility hooks** - Easy to add timeline/branching later
- ✅ **Simple flexbox** - No complex Split components

---

## Architecture: Polling-Based (Like Studio)

### The Studio Pattern (No SSE!)

**How Studio Works** (`studio/hooks/useTimelinePolling.js`):

1. **Cursor-based polling**: `GET /api/playground/session-stream/{sessionId}?after={cursor}`
2. **Returns**: All logs since cursor timestamp
3. **Deduplication**: Track seen message IDs in ref
4. **Smart append**: Only add new rows to state array
5. **Cost backfilling**: Look back 30s to catch late-arriving cost data
6. **Poll interval**: 750ms (fast, responsive)
7. **Auto-stop**: Stop polling 10s after completion

**Benefits**:
- ✅ Single source of truth (database)
- ✅ No missed events (unlike SSE disconnect)
- ✅ Self-healing (refresh mid-execution works)
- ✅ Complete data (candidates, reforge, wards)
- ✅ Simpler code (no event bus, no reconnection logic)

### Adapted for ExploreView

We'll create **`useExplorePolling`** hook that:
- Polls session logs (like Studio)
- Derives ghost messages from logs
- Fetches checkpoint status
- Tracks orchestration state
- Returns clean data for rendering

---

## Iteration 1: MVP Scope

### Core Features ONLY

**IN SCOPE** ✅:
1. **Live cascade execution** with ghost messages
2. **Inline checkpoint rendering** (using CheckpointRenderer)
3. **Orchestration sidebar** (live stats, status orb, cost)
4. **Start new cascades** (CascadePicker modal)
5. **End running cascade** button
6. **Perplexity-style loop** (LLM → UI → Response → Continue)

**OUT OF SCOPE** ⏸️ (Design for extensibility):
7. Timeline/history (responded checkpoints) - **Hooks in place, UI later**
8. Branching - **API exists, just don't wire up UI**
9. Save to artifacts - **Button slot reserved, implement later**
10. Narration playback - **Hook ready, just don't call it**
11. Research tree - **Sidebar slot reserved**
12. Previous sessions - **Sidebar slot reserved**

### Components Needed

**Extract from ResearchCockpit** (3 components):
1. ✅ **GhostMessage** - Live activity cards
2. ⏸️ **ExpandableCheckpoint** - Defer (for timeline/branching)
3. ⏸️ **CascadeContextHeader** - Defer (for timeline view)

**Reuse Existing**:
1. ✅ **CheckpointRenderer** - For current pending checkpoint
2. ✅ **LiveOrchestrationSidebar** - Adapt for polling (no SSE amplitude)
3. ✅ **CascadePicker** - Already works
4. ✅ **Button, Badge, Card** - AppShell components

**Create New**:
1. ✅ **useExplorePolling** - Hook for data fetching (polling)
2. ✅ **ExploreView** - Main component
3. ✅ **ExploreView.css** - Layout + theme

---

## File Structure (Simplified)

```
src/views/explore/
├── ExploreView.jsx                 # Main component (~250 lines)
├── ExploreView.css                 # Layout + theme (~150 lines)
└── hooks/
    └── useExplorePolling.js        # Polling hook (~200 lines)

src/components/
├── GhostMessage.jsx                # Extracted (~200 lines)
├── GhostMessage.css                # Styling (~120 lines)
├── LiveOrchestrationSidebar.js     # Adapt for polling (minor tweaks)
└── ... (CheckpointRenderer, etc. already exist)
```

**Total New Code**: ~750 lines (vs 4400 = **83% reduction!**)

---

## Detailed Implementation Plan

### Step 1: Extract GhostMessage Component

**File**: `src/components/GhostMessage.jsx`
**Lines**: ~200
**Purpose**: Translucent cards showing LLM's work-in-progress

**Features**:
- Icon by type (tool_call, tool_result, thinking)
- Content parsing (JSON from code blocks)
- Tool argument formatting
- Exit animation (slide-out-left)
- Truncation (200 chars max)

**Props**:
```typescript
{
  ghost: {
    id: string,
    type: 'tool_call' | 'tool_result' | 'thinking',
    tool?: string,
    content: string,
    arguments?: object,
    result?: any,
    timestamp: string,
    exiting?: boolean
  }
}
```

**Styling** (AppShell theme):
- Background: `rgba(0, 0, 0, 0.6)`
- Border-left: 2px solid (cyan for tool, green for result, purple for thinking)
- Opacity: 0.85
- Font: 11px monospace
- Exit animation: `slideOutLeft` 600ms

**Framer Motion Integration**:
```jsx
import { motion, AnimatePresence } from 'framer-motion';

<AnimatePresence>
  {ghostMessages.map(ghost => (
    <motion.div
      key={ghost.id}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 0.85, x: 0 }}
      exit={{ opacity: 0, x: -100 }}
      transition={{ duration: 0.3 }}
    >
      <GhostMessage ghost={ghost} />
    </motion.div>
  ))}
</AnimatePresence>
```

### Step 2: Create useExplorePolling Hook

**File**: `src/views/explore/hooks/useExplorePolling.js`
**Lines**: ~200 (adapting Studio's useTimelinePolling)
**Purpose**: Poll session data and derive UI state

**Features**:
- Cursor-based incremental polling
- Deduplication via seen IDs ref
- Ghost message extraction from logs
- Checkpoint status polling
- Orchestration state derivation
- Auto-stop after completion

**Returns**:
```javascript
{
  // Core data
  logs: LogRow[],              // All session logs
  checkpoint: Checkpoint | null,  // Current pending checkpoint

  // Derived state
  ghostMessages: Ghost[],      // Last 5 tool calls/results
  orchestrationState: {
    currentPhase: string,
    currentModel: string,
    totalCost: number,
    status: 'idle' | 'thinking' | 'waiting_human',
    phaseHistory: Phase[]
  },

  // Session metadata
  sessionStatus: 'running' | 'completed' | 'error',
  totalCost: number,
  isPolling: boolean,
  error: string | null,

  // Actions
  refresh: () => void
}
```

**Polling Logic** (adapted from Studio):
```javascript
const poll = useCallback(async () => {
  if (!sessionId) return;

  try {
    // Fetch logs since cursor
    const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(cursorRef.current)}`;
    const res = await fetch(url);
    const data = await res.json();

    // Deduplicate and append
    const newRows = [];
    for (const row of data.rows || []) {
      if (row.message_id && !seenIdsRef.current.has(row.message_id)) {
        seenIdsRef.current.add(row.message_id);
        newRows.push(row);
      }
    }

    if (newRows.length > 0) {
      setLogs(prev => [...prev, ...newRows]);
      cursorRef.current = data.cursor;
    }

    // Derive ghost messages from new logs
    updateGhostMessages(newRows);

    // Update session status
    setSessionStatus(data.session_status);
    setTotalCost(data.total_cost || 0);

    // Fetch checkpoint status
    await fetchCheckpoint();

  } catch (err) {
    setError(err.message);
  }
}, [sessionId]);

// Poll every 750ms
useEffect(() => {
  const interval = setInterval(poll, 750);
  return () => clearInterval(interval);
}, [poll]);
```

**Ghost Message Derivation**:
```javascript
function updateGhostMessages(newLogs) {
  // Extract tool calls and results from logs
  const ghosts = [];

  for (const log of newLogs.slice(-10)) { // Last 10 logs only
    if (log.tool_name) {
      ghosts.push({
        id: log.message_id,
        type: 'tool_call',
        tool: log.tool_name,
        content: log.content,
        arguments: parseToolArgs(log.content),
        timestamp: log.timestamp
      });
    }

    if (log.role === 'tool') {
      ghosts.push({
        id: log.message_id,
        type: 'tool_result',
        tool: log.tool_name,
        result: log.content,
        timestamp: log.timestamp
      });
    }
  }

  setGhostMessages(ghosts);
}
```

### Step 3: Adapt LiveOrchestrationSidebar

**Current**: Expects `narrationAmplitude` prop for status orb glow

**Changes**:
- Make `narrationAmplitude` **optional** (default: 0)
- If no narration, orb glow uses orchestration status instead:
  - `thinking` → pulsing cyan
  - `tool_running` → pulsing green
  - `waiting_human` → pulsing yellow
  - `idle` → dim gray

**File**: `src/components/LiveOrchestrationSidebar.js`
**Changes**: 5-10 lines (add default props, conditional glow logic)

**Example**:
```javascript
const LiveOrchestrationSidebar = ({
  sessionId,
  cascadeId,
  orchestrationState,
  sessionData,
  roundEvents,
  narrationAmplitude = 0,  // Default to 0
  onEnd
}) => {
  // Use narrationAmplitude if available, otherwise derive from status
  const effectiveGlow = narrationAmplitude > 0
    ? narrationAmplitude
    : getGlowForStatus(orchestrationState.status);

  // ... rest unchanged
};

function getGlowForStatus(status) {
  switch (status) {
    case 'thinking': return 0.6;
    case 'tool_running': return 0.8;
    case 'waiting_human': return 0.4;
    default: return 0.2;
  }
}
```

### Step 4: Create ExploreView Component

**File**: `src/views/explore/ExploreView.jsx`
**Lines**: ~250

**JSX Structure**:
```jsx
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import { Button, Badge } from '../../components';
import CheckpointRenderer from '../../components/CheckpointRenderer';
import GhostMessage from '../../components/GhostMessage';
import LiveOrchestrationSidebar from '../../components/LiveOrchestrationSidebar';
import CascadePicker from '../../components/CascadePicker';
import useExplorePolling from './hooks/useExplorePolling';
import './ExploreView.css';

const ExploreView = ({ params, navigate }) => {
  const sessionId = params.session || params.id;
  const [showPicker, setShowPicker] = useState(!sessionId);

  // Poll for session data (NO SSE!)
  const {
    logs,
    checkpoint,
    ghostMessages,
    orchestrationState,
    sessionStatus,
    totalCost,
    isPolling,
    error
  } = useExplorePolling(sessionId);

  // Handlers
  const handleCheckpointRespond = async (response) => {
    await fetch(`http://localhost:5001/api/checkpoints/${checkpoint.id}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response })
    });
    // Polling will pick up the response automatically
  };

  const handleStartCascade = async (cascadeFile, inputs) => {
    const res = await fetch('http://localhost:5001/api/run-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cascade_file: cascadeFile, inputs })
    });
    const data = await res.json();
    navigate(`explore?session=${data.session_id}`);
    setShowPicker(false);
  };

  const handleEndCascade = async () => {
    if (!confirm('Stop cascade?')) return;
    await fetch('/api/cancel-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
  };

  // Show picker if no session
  if (showPicker || !sessionId) {
    return (
      <div className="explore-view">
        <CascadePicker
          onSelect={handleStartCascade}
          onCancel={() => navigate('studio')}
        />
      </div>
    );
  }

  return (
    <div className="explore-view">
      {/* Two-column flexbox layout */}
      <div className="explore-layout">

        {/* Main Column (scrollable) */}
        <div className="explore-main-column">
          <div className="explore-main-content">

            {/* Ghost Messages (Live Activity) */}
            <AnimatePresence>
              {ghostMessages.map(ghost => (
                <motion.div
                  key={ghost.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 0.85, x: 0 }}
                  exit={{ opacity: 0, x: -100 }}
                  transition={{ duration: 0.3 }}
                >
                  <GhostMessage ghost={ghost} />
                </motion.div>
              ))}
            </AnimatePresence>

            {/* Current Pending Checkpoint (Inline) */}
            {checkpoint && (
              <motion.div
                className="current-checkpoint"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <CheckpointRenderer
                  checkpoint={checkpoint}
                  onSubmit={handleCheckpointRespond}
                  variant="inline"
                  showPhaseOutput={true}
                />
              </motion.div>
            )}

            {/* Empty State */}
            {!checkpoint && ghostMessages.length === 0 && (
              <div className="explore-empty">
                <Icon
                  icon={sessionStatus === 'running' ? 'mdi:compass' : 'mdi:check-circle'}
                  width="64"
                />
                <h2>{sessionStatus === 'completed' ? 'Cascade Complete' : 'Waiting...'}</h2>
                <p>
                  {sessionStatus === 'running' && 'Cascade is active. Activity will appear here.'}
                  {sessionStatus === 'completed' && 'All done! Start a new cascade or view history.'}
                </p>
              </div>
            )}

            {/* Placeholder for Timeline (Future) */}
            {/* {checkpointHistory.map(...)} */}

          </div>
        </div>

        {/* Sidebar (Fixed Width) */}
        <LiveOrchestrationSidebar
          sessionId={sessionId}
          cascadeId={orchestrationState.cascadeId}
          orchestrationState={orchestrationState}
          sessionData={{ total_cost: totalCost }} // Minimal for now
          roundEvents={[]} // Derive from logs if needed
          narrationAmplitude={0} // No narration in MVP
          onEnd={handleEndCascade}
        />

      </div>
    </div>
  );
};

export default ExploreView;
```

**~250 lines** total

### Step 5: Create ExploreView.css

**File**: `src/views/explore/ExploreView.css`
**Lines**: ~150

**Layout Pattern** (Pure Flexbox):
```css
.explore-view {
  width: 100%;
  height: 100vh;
  background: var(--color-bg-primary);
  overflow: hidden;
}

.explore-layout {
  display: flex;
  height: 100%;
  gap: 0; /* No gap, sidebar has border */
}

/* Main column - scrollable */
.explore-main-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--color-border-dim);
}

.explore-main-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Sidebar - fixed width */
.explore-layout > aside {
  width: 320px;
  flex-shrink: 0;
}

/* Ghost messages */
.ghost-message {
  /* Styled in GhostMessage.css */
}

/* Current checkpoint */
.current-checkpoint {
  /* CheckpointRenderer handles styling */
}

/* Empty state */
.explore-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  min-height: 400px;
  color: var(--color-text-muted);
}

/* Scrollbar */
.explore-main-content::-webkit-scrollbar {
  width: 6px;
}

.explore-main-content::-webkit-scrollbar-thumb {
  background: rgba(0, 229, 255, 0.3);
  border-radius: 3px;
}
```

---

## Ghost Message Implementation

### GhostMessage.jsx

**Full Implementation**:
```jsx
import React from 'react';
import { Icon } from '@iconify/react';
import './GhostMessage.css';

/**
 * GhostMessage - Live activity indicator
 *
 * Shows LLM's work-in-progress:
 * - Tool calls
 * - Tool results
 * - Thinking/reasoning
 *
 * Auto-cleanup after 20s via parent component logic
 */
const GhostMessage = ({ ghost }) => {
  const getIcon = () => {
    switch (ghost.type) {
      case 'tool_call':
        return 'mdi:hammer-wrench';
      case 'tool_result':
        return 'mdi:check-circle';
      case 'thinking':
        return 'mdi:brain';
      default:
        return 'mdi:message';
    }
  };

  const getTitle = () => {
    switch (ghost.type) {
      case 'tool_call':
        return `Calling ${ghost.tool || 'tool'}`;
      case 'tool_result':
        return `Result from ${ghost.tool || 'tool'}`;
      case 'thinking':
        return 'Thinking...';
      default:
        return 'Activity';
    }
  };

  const getBorderColor = () => {
    switch (ghost.type) {
      case 'tool_call':
        return 'var(--color-accent-cyan)';
      case 'tool_result':
        return 'var(--color-accent-green)';
      case 'thinking':
        return 'var(--color-accent-purple)';
      default:
        return 'var(--color-border-dim)';
    }
  };

  // Parse JSON from content
  const parseJSON = (text) => {
    try {
      // Try to extract JSON from markdown code blocks
      const match = text.match(/```(?:json)?\s*\n?({[\s\S]*?})\s*\n?```/);
      if (match) {
        return JSON.parse(match[1]);
      }
      // Try direct parse
      if (text.trim().startsWith('{')) {
        return JSON.parse(text);
      }
    } catch (e) {
      // Not JSON, return as text
    }
    return null;
  };

  // Truncate long content
  const truncate = (text, maxLength = 200) => {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  const parsedArgs = ghost.arguments ? ghost.arguments : parseJSON(ghost.content);

  return (
    <div
      className={`ghost-message ghost-${ghost.type}`}
      style={{ borderLeftColor: getBorderColor() }}
    >
      <div className="ghost-header">
        <Icon icon={getIcon()} width="14" />
        <span className="ghost-title">{getTitle()}</span>
        <span className="ghost-timestamp">
          {new Date(ghost.timestamp).toLocaleTimeString()}
        </span>
      </div>

      <div className="ghost-content">
        {ghost.type === 'tool_call' && parsedArgs && (
          <details className="ghost-args">
            <summary>Arguments</summary>
            <pre>{JSON.stringify(parsedArgs, null, 2)}</pre>
          </details>
        )}

        {ghost.type === 'tool_result' && (
          <div className="ghost-result">
            {truncate(String(ghost.result || ghost.content))}
          </div>
        )}

        {ghost.type === 'thinking' && (
          <div className="ghost-thinking">
            {truncate(ghost.content)}
          </div>
        )}
      </div>
    </div>
  );
};

export default GhostMessage;
```

### GhostMessage.css

```css
/* Ghost Message - Live activity card */
.ghost-message {
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.6);
  border-left: 2px solid;
  border-radius: 4px;
  opacity: 0.85;
  transition: opacity 0.3s ease;
}

.ghost-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: var(--font-size-xs);
}

.ghost-title {
  flex: 1;
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-semibold);
}

.ghost-timestamp {
  color: var(--color-text-dim);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
}

.ghost-content {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.ghost-args summary {
  cursor: pointer;
  color: var(--color-accent-cyan);
  font-size: var(--font-size-xs);
  margin-bottom: 4px;
}

.ghost-args pre {
  margin-top: 6px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.8);
  border: 1px solid var(--color-border-dim);
  border-radius: 4px;
  font-size: 10px;
  overflow-x: auto;
}

.ghost-result,
.ghost-thinking {
  line-height: 1.5;
  white-space: pre-wrap;
  word-wrap: break-word;
}
```

---

## Implementation Steps (Execution Plan)

### Day 1: Core Infrastructure

**Step 1.1** - Extract GhostMessage (~30 min)
- [ ] Create `src/components/GhostMessage.jsx`
- [ ] Create `src/components/GhostMessage.css`
- [ ] Export from `src/components/index.js`
- [ ] Test: Render a mock ghost message in isolation

**Step 1.2** - Create useExplorePolling hook (~60 min)
- [ ] Create `src/views/explore/hooks/useExplorePolling.js`
- [ ] Adapt Studio's polling logic
- [ ] Add ghost message derivation
- [ ] Add checkpoint polling
- [ ] Test: Console.log poll results

**Step 1.3** - Adapt LiveOrchestrationSidebar (~15 min)
- [ ] Make narrationAmplitude optional
- [ ] Add default status-based glow
- [ ] Test: Renders with default props

### Day 2: Main UI

**Step 2.1** - Create ExploreView layout (~45 min)
- [ ] Create `src/views/explore/ExploreView.jsx`
- [ ] Create `src/views/explore/ExploreView.css`
- [ ] Two-column flexbox layout
- [ ] Import all components
- [ ] Test: Renders empty state

**Step 2.2** - Wire up data flow (~30 min)
- [ ] Connect useExplorePolling hook
- [ ] Render ghost messages with Framer Motion
- [ ] Render current checkpoint with CheckpointRenderer
- [ ] Render LiveOrchestrationSidebar
- [ ] Test: View loads without errors

**Step 2.3** - Add interactions (~30 min)
- [ ] Checkpoint respond handler
- [ ] End cascade button
- [ ] CascadePicker integration
- [ ] Test: Click interactions work

### Day 3: Testing & Polish

**Step 3.1** - Integration testing (~45 min)
- [ ] Run live cascade with request_decision
- [ ] Verify ghost messages appear
- [ ] Verify checkpoint renders inline
- [ ] Submit checkpoint, verify cascade continues
- [ ] Test empty states (idle, completed)

**Step 3.2** - Styling polish (~30 min)
- [ ] Verify AppShell theme consistency
- [ ] Test responsive breakpoints
- [ ] Smooth animations
- [ ] Loading states

**Step 3.3** - Documentation (~15 min)
- [ ] Update EXPLORE_VIEW_PLAN with "as-built" notes
- [ ] Add usage examples
- [ ] Document extension points

**Total Time**: ~5 hours for Iteration 1 MVP

---

## Extension Points (For Future Iterations)

### Timeline Support (Iteration 2)

**Hook Extension**:
```javascript
// In useExplorePolling.js
export function useExplorePolling(sessionId) {
  // ... existing code

  // ADD: Fetch checkpoint history
  const [checkpointHistory, setCheckpointHistory] = useState([]);

  useEffect(() => {
    if (!sessionId) return;
    const fetchHistory = async () => {
      const res = await fetch(`/api/checkpoints?session_id=${sessionId}&include_all=true`);
      const data = await res.json();
      setCheckpointHistory(data.checkpoints || []);
    };
    fetchHistory();
    const interval = setInterval(fetchHistory, 2000);
    return () => clearInterval(interval);
  }, [sessionId]);

  return {
    // ... existing
    checkpointHistory  // ADD
  };
}
```

**Component Addition**:
```jsx
// In ExploreView.jsx, add before current checkpoint
{checkpointHistory
  .filter(cp => cp.status === 'responded')
  .map((cp, idx) => (
    <ExpandableCheckpoint
      key={cp.id}
      checkpoint={cp}
      index={idx}
      sessionId={sessionId}
      // No onBranch yet - just display
    />
  ))}
```

### Branching Support (Iteration 3)

**Add to ExpandableCheckpoint props**:
```jsx
<ExpandableCheckpoint
  // ... existing props
  onBranch={(index, newResponse) => handleBranch(index, newResponse)}  // ADD
/>
```

**Add handler to ExploreView**:
```javascript
const handleBranch = async (checkpointIndex, newResponse) => {
  const res = await fetch('/api/research-sessions/branch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      parent_research_session_id: sessionData.id,
      branch_checkpoint_index: checkpointIndex,
      new_response: newResponse
    })
  });
  const data = await res.json();
  navigate(`explore?session=${data.new_session_id}`);
};
```

### Narration Support (Iteration 3)

**Add to ExploreView**:
```jsx
import { useNarrationPlayer } from '../../components/NarrationPlayer';
import NarrationCaption from '../../components/NarrationCaption';

const ExploreView = ({ params, navigate }) => {
  // ... existing code

  // ADD narration
  const {
    playAudio,
    narrationAmplitude,
    // ...
  } = useNarrationPlayer();

  // Pass to sidebar
  <LiveOrchestrationSidebar
    narrationAmplitude={narrationAmplitude}  // Instead of 0
    // ...
  />

  // Render caption
  {isNarrating && (
    <NarrationCaption text={narrationText} duration={narrationDuration} />
  )}
};
```

**Listen for narration in polling hook**:
```javascript
// Check for narration_audio in logs
const narrationLogs = newLogs.filter(log => log.event_type === 'narration_audio');
narrationLogs.forEach(log => {
  playAudio(log.audio_path);
  setNarrationText(log.narration_text);
});
```

---

## Updated Implementation Order

### Phase 1: Extract & Create (~2 hours)
1. ✅ Extract GhostMessage component (30 min)
2. ✅ Create useExplorePolling hook (60 min)
3. ✅ Adapt LiveOrchestrationSidebar (15 min)
4. ✅ Test components in isolation (15 min)

### Phase 2: Build ExploreView (~2 hours)
1. ✅ Create ExploreView.jsx skeleton (30 min)
2. ✅ Create ExploreView.css (30 min)
3. ✅ Wire up polling hook (20 min)
4. ✅ Add Framer Motion animations (20 min)
5. ✅ Add CascadePicker integration (20 min)

### Phase 3: Test & Polish (~1 hour)
1. ✅ Run live cascade test (20 min)
2. ✅ Test checkpoint submission (15 min)
3. ✅ Fix any styling issues (15 min)
4. ✅ Document extension points (10 min)

**Total**: ~5 hours for **fully functional Perplexity-style loop**

---

## Success Criteria (MVP)

**ExploreView Iteration 1 is complete when**:
1. ✅ User navigates to `/#/explore?session=test_session`
2. ✅ Ghost messages appear as cascade executes (tool calls, results)
3. ✅ Current checkpoint renders inline (when LLM calls request_decision)
4. ✅ User can respond to checkpoint inline
5. ✅ Cascade continues after response (within 0.5s)
6. ✅ Orchestration sidebar shows live stats
7. ✅ No SSE - pure polling at 750ms
8. ✅ Framer Motion animations for ghosts and checkpoints
9. ✅ Clean code (< 500 total new lines)
10. ✅ Extension points marked with comments for future features

---

## Questions Before Starting

1. **LiveOrchestrationSidebar**: Should I create a **simplified version** or try to reuse the existing 548-line component? The existing one has complex orb animations, phase timeline, research tree slots - might be overkill for MVP.

2. **Ghost message limit**: Old system kept "last 5" and auto-removed after 20s. Should we:
   - Keep last 5 only (lean)
   - Keep all from current session (full history)
   - Auto-remove after 20s (animated)

3. **Polling endpoint**: Should I use:
   - `/api/playground/session-stream/{id}?after={cursor}` (Studio's endpoint)
   - Create new `/api/explore/session-stream/{id}` (dedicated)

4. **Start implementation now** or any other concerns?

**My Recommendations**:
1. **Create simplified sidebar** for MVP - Just status, cost, phase name (100 lines vs 548)
2. **Keep last 10, auto-remove after 30s** - Good balance
3. **Use Studio's endpoint** - Already tested, works great
4. **Start now!** 🚀
