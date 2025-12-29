# ExploreView Implementation Plan

**Goal**: Recreate ResearchCockpit functionality in clean AppShell architecture as the new ExploreView

**Date**: 2025-12-26
**Status**: Planning Phase

---

## Executive Summary

ResearchCockpit is a **2000-line, feature-rich research interface** with live execution visualization. We'll recreate it as **ExploreView** using:

- ✅ New component system (Button, Card, Badge)
- ✅ AppShell design language (data-dense, cyan accents)
- ✅ Extracted reusable components
- ✅ Modern React patterns (hooks, memoization)
- ✅ **CheckpointRenderer** for inline checkpoint display

**Estimated Scope**: 6 new files, 3 extracted components, ~1200 lines total (40% reduction)

---

## Phase 1: Component Extraction (Pre-work)

Extract 3 inline components from ResearchCockpit to make them reusable.

### 1A. Extract ExpandableCheckpoint

**Current**: Lines 1511-1710 in ResearchCockpit.js (200 lines)
**New File**: `src/components/ExpandableCheckpoint.jsx`
**CSS**: Extract from ResearchCockpit.css lines 353-551 → `ExpandableCheckpoint.css`

**Purpose**: Collapsible checkpoint card with full UI replay and branching

**Props**:
```typescript
{
  checkpoint: CheckpointObject,    // Full checkpoint data
  index: number,                   // Position in timeline
  sessionId: string,               // Current session
  savedSessionData?: object,       // Optional saved session context
  onBranch?: (index, response) => void,  // Branch callback
  variant?: 'default' | 'compact'  // Display mode
}
```

**Features**:
- Collapsed: Number badge + summary + timestamp + type + save button
- Expanded: Full CheckpointRenderer (reusing our new universal component!)
- Branch mode: Intercepts form submit, calls onBranch instead of normal submit
- Save as artifact: Button with loading states

**Updates from Old Version**:
- ✅ Use CheckpointRenderer instead of HTMLSection directly
- ✅ Use AppShell Button component for save button
- ✅ Use AppShell Badge for number/type indicators
- ✅ Cyan accent borders instead of purple

### 1B. Extract CascadeContextHeader

**Current**: Lines 1716-1805 in ResearchCockpit.js (90 lines)
**New File**: `src/components/CascadeContextHeader.jsx`
**CSS**: Extract from ResearchCockpit.css lines 842-988 → `CascadeContextHeader.css`

**Purpose**: Sticky header showing cascade inputs and latest checkpoint feedback

**Props**:
```typescript
{
  cascadeInputs: object,           // Initial cascade parameters
  checkpointHistory: Checkpoint[], // All checkpoints in session
  cascadeId: string,               // Cascade identifier
  savedSessionData?: object        // Optional saved session data
}
```

**Features**:
- Displays initial cascade inputs in collapsible section
- Shows latest responded checkpoint feedback
- Sticky positioning at top of scrollable area
- Chevron animation for expand/collapse

**Updates from Old Version**:
- ✅ Use AppShell Button for toggle (if we make it interactive)
- ✅ Cyan accent for input labels
- ✅ Data-dense spacing

### 1C. Extract GhostMessage

**Current**: Lines 1812-2062 in ResearchCockpit.js (250 lines)
**New File**: `src/components/GhostMessage.jsx`
**CSS**: Extract from ResearchCockpit.css lines 608-841 → `GhostMessage.css`

**Purpose**: Translucent live activity card showing LLM's work-in-progress

**Props**:
```typescript
{
  ghost: {
    type: 'tool_call' | 'tool_result' | 'thinking',
    tool?: string,              // Tool name
    content: string,            // Message content
    arguments?: object,         // Tool arguments
    result?: any,               // Tool result
    timestamp: string,          // ISO timestamp
    id: string,                 // Unique identifier
    createdAt: number,          // Unix timestamp
    exiting?: boolean,          // Exit animation flag
    exitStartedAt?: number      // Exit animation start
  }
}
```

**Features**:
- Icon selection by type (tool, result, thinking)
- Content parsing (JSON code blocks, markdown, data grids)
- Tool call formatting with collapsible arguments
- Auto-cleanup animation (slide-out-left after 20s)
- Truncation for long content (200 chars with "show more")

**Complex Parsing Logic**:
- Extracts JSON from markdown code blocks
- Renders SQL results as data grids
- Formats tool arguments as JSON
- Handles nested objects and arrays

**Updates from Old Version**:
- ✅ Keep translucent styling (unique to live activity)
- ✅ Update colors to cyan accents
- ✅ Make font sizes data-dense (11px)
- ⚠️ Consider simplifying data grid rendering (could use a DataTable component)

---

## Phase 2: ExploreView Architecture

### File Structure

```
src/views/explore/
├── ExploreView.jsx                 # Main component (300 lines)
├── ExploreView.css                 # Layout + theme (200 lines)
├── components/
│   ├── CascadePicker.jsx           # Reuse existing or simplify (50 lines)
│   ├── SessionTimeline.jsx         # Checkpoint timeline (150 lines)
│   └── SessionControls.jsx         # Start/stop/save controls (80 lines)
└── hooks/
    ├── useSessionStream.js         # SSE + state management (200 lines)
    └── useGhostMessages.js         # Ghost lifecycle (100 lines)

src/components/
├── ExpandableCheckpoint.jsx        # Extracted (200 lines)
├── ExpandableCheckpoint.css        # Extracted (150 lines)
├── CascadeContextHeader.jsx        # Extracted (90 lines)
├── CascadeContextHeader.css        # Extracted (80 lines)
├── GhostMessage.jsx                # Extracted (250 lines)
├── GhostMessage.css                # Extracted (150 lines)
└── LiveOrchestrationSidebar.js     # Existing (keep as-is)
```

**Total New Code**: ~1800 lines (vs 4400 in old system = 60% reduction!)

### Layout Design

```
┌─────────────────────────────────────────────────────────────┐
│ ExploreView (full viewport)                                 │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────┬─────────────────────────┐  │
│ │ Main Column (flex-1)         │ Sidebar (300px fixed)   │  │
│ │                              │                         │  │
│ │ ┌─────────────────────────┐ │ LiveOrchestrationSidebar│  │
│ │ │ CascadeContextHeader    │ │ - Status orb            │  │
│ │ │ (sticky, non-scroll)    │ │ - Cost ticker           │  │
│ │ └─────────────────────────┘ │ - Session overview      │  │
│ │                              │ - Phase timeline        │  │
│ │ ┌─────────────────────────┐ │ - Research tree         │  │
│ │ │ Scrollable Content      │ │ - Previous sessions     │  │
│ │ │                         │ │ - END button            │  │
│ │ │ • GhostMessage x N      │ │                         │  │
│ │ │ • ExpandableCheckpoint  │ │                         │  │
│ │ │ • ExpandableCheckpoint  │ │                         │  │
│ │ │ • CheckpointRenderer    │ │                         │  │
│ │ │   (current pending)     │ │                         │  │
│ │ │ • Empty state           │ │                         │  │
│ │ └─────────────────────────┘ │                         │  │
│ └─────────────────────────────┴─────────────────────────┘  │
│                                                             │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ NarrationCaption (fixed bottom)                     │    │
│ └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**No nested Split components** - Simple two-column flexbox layout

---

## Phase 3: Implementation Plan

### Step 1: Extract Reusable Components ⏱️ Est: 2-3 hours

**1A. ExpandableCheckpoint** (Priority: HIGH)
- [x] Create `src/components/ExpandableCheckpoint.jsx`
- [x] Extract CSS to `ExpandableCheckpoint.css`
- [x] Replace HTMLSection with CheckpointRenderer (unified!)
- [x] Update colors to cyan accents
- [x] Add AppShell Button/Badge components
- [x] Test: Render a responded checkpoint, expand it, try branching

**1B. CascadeContextHeader** (Priority: MEDIUM)
- [x] Create `src/components/CascadeContextHeader.jsx`
- [x] Extract CSS to `CascadeContextHeader.css`
- [x] Convert to AppShell design (cyan labels, tight spacing)
- [x] Make inputs JSON pretty-printed
- [x] Test: Render with cascade inputs, verify sticky positioning

**1C. GhostMessage** (Priority: HIGH)
- [x] Create `src/components/GhostMessage.jsx`
- [x] Extract CSS to `GhostMessage.css`
- [x] Simplify data grid rendering (use simple <table> or skip)
- [x] Keep translucent style (unique to live activity)
- [x] Update icons to use Iconify
- [x] Test: Render tool_call, tool_result, thinking types

**1D. Extract Utility Functions**
- [x] Create `src/utils/artifactBuilder.js`
  - `buildArtifactHTML(bodyHTML)` - Wrap HTML with full document
- [x] Create `src/utils/ghostMessageParser.js`
  - `extractGhostMessages(entries)` - Parse session logs for ghosts
  - `parseToolCall(content)` - Extract JSON from markdown

### Step 2: Create Custom Hooks ⏱️ Est: 1-2 hours

**2A. useSessionStream** (Replaces SSE + polling logic)
- [x] Create `src/views/explore/hooks/useSessionStream.js`
- [x] Features:
  - SSE connection management
  - Session data polling
  - Checkpoint polling
  - Saved session handling
  - Ghost message lifecycle
  - Round events tracking
- [x] Returns: `{ sessionData, checkpoint, checkpointHistory, ghostMessages, roundEvents, orchestrationState, isLoading }`
- [x] Handles cleanup on unmount
- [x] Uses refs to prevent reconnection loops

**2B. useGhostMessages** (Replaces inline logic)
- [x] Create `src/views/explore/hooks/useGhostMessages.js`
- [x] Features:
  - Auto-cleanup after 20s
  - Exit animation management
  - Parsing session logs
- [x] Returns: `{ ghostMessages, addGhost, clearGhosts }`

### Step 3: Create ExploreView Sub-components ⏱️ Est: 2-3 hours

**3A. SessionTimeline**
- [x] Create `src/views/explore/components/SessionTimeline.jsx`
- [x] Features:
  - Maps checkpointHistory to ExpandableCheckpoint
  - Shows responded (collapsed) + pending (expanded)
  - Branching support
- [x] Props: `{ checkpointHistory, currentCheckpoint, onBranch, onCheckpointRespond, sessionId }`
- [x] ~150 lines

**3B. SessionControls**
- [x] Create `src/views/explore/components/SessionControls.jsx`
- [x] Features:
  - New cascade button (opens CascadePicker)
  - Save session button
  - End cascade button (if running)
  - Session stats display
- [x] Props: `{ sessionId, isRunning, onStartCascade, onEndCascade, onSaveSession }`
- [x] ~80 lines

### Step 4: Main ExploreView Component ⏱️ Est: 2-3 hours

**4A. ExploreView.jsx**
- [x] Create main component structure
- [x] Features:
  - Two-column flexbox layout (no Split component - simpler!)
  - useSessionStream hook for data
  - CascadeContextHeader (sticky)
  - GhostMessage list
  - SessionTimeline with checkpoints
  - CheckpointRenderer for current pending
  - Empty states (idle, starting, completed)
- [x] Props: `{ params, navigate }` (from AppShell router)
- [x] URL param support: `?session=<session_id>` or `?cascade=<file>`
- [x] ~300 lines

**4B. ExploreView.css**
- [x] Two-column flexbox layout
- [x] Scrollable main area pattern (fixed header + scroll content)
- [x] AppShell theme integration
- [x] Responsive breakpoints
- [x] ~200 lines

### Step 5: Integration & Polish ⏱️ Est: 1 hour

**5A. NarrationPlayer Integration**
- [x] Import useNarrationPlayer hook
- [x] Render NarrationCaption (already exists)
- [x] Pass amplitude to LiveOrchestrationSidebar
- [x] SSE event: `narration_audio` → play audio

**5B. Exports & Registration**
- [x] Export new components from `src/components/index.js`
- [x] ExploreView already registered in views/index.js
- [x] Add keyboard shortcuts (Esc to close modals, etc.)

**5C. Testing**
- [x] Run test cascade with checkpoints
- [x] Verify ghost messages appear/disappear
- [x] Test checkpoint responses (inline)
- [x] Test branching
- [x] Test save to artifacts
- [x] Test narration playback

---

## Detailed Component Specs

### ExpandableCheckpoint.jsx

**Responsibilities**:
- Display checkpoint summary when collapsed
- Render full UI when expanded
- Support branching (re-submit with different response)
- Save as artifact
- Loading/saved state management

**JSX Structure**:
```jsx
<div className="expandable-checkpoint ${expanded ? 'expanded' : 'collapsed'}">
  {/* Header - Always Visible */}
  <div className="checkpoint-header" onClick={toggleExpand}>
    <Badge variant="count" color="cyan">{index + 1}</Badge>
    <div className="checkpoint-summary">
      <h3>{checkpoint.summary || checkpoint.phase_output}</h3>
      <div className="checkpoint-meta">
        <Icon icon="mdi:clock-outline" />
        <span>{formatTime(checkpoint.created_at)}</span>
        <Badge variant="label" color="purple">{checkpoint.checkpoint_type}</Badge>
      </div>
    </div>
    <Button
      variant="ghost"
      size="sm"
      icon={isSaved ? "mdi:check" : "mdi:content-save"}
      loading={isSaving}
      onClick={handleSaveAsArtifact}
    >
      {isSaved ? 'Saved' : 'Save'}
    </Button>
  </div>

  {/* Content - Shown When Expanded */}
  {expanded && (
    <div className="checkpoint-content">
      <div className="replay-label">
        <Icon icon="mdi:replay" />
        <span>Original UI</span>
        {isSavedCheckpoint && (
          <div className="branch-hint">
            <Icon icon="mdi:source-fork" />
            <span>Resubmit to create branch</span>
          </div>
        )}
      </div>

      <CheckpointRenderer
        checkpoint={checkpoint}
        onSubmit={handleBranchOrRespond}
        variant="inline"
        showPhaseOutput={false}  // Already in header
        isSavedCheckpoint={isSavedCheckpoint}
        onBranchSubmit={onBranch}
      />

      {/* User's Response (if responded) */}
      {checkpoint.response && (
        <div className="response-section">
          <Icon icon="mdi:account" />
          <span>Your Response</span>
          <pre>{JSON.stringify(checkpoint.response, null, 2)}</pre>
        </div>
      )}
    </div>
  )}
</div>
```

**Styling Notes**:
- Collapsed: 1px cyan border, dark background
- Expanded: Cyan border glow, expanded content area
- Hover: Subtle cyan highlight
- Number badge: Cyan circle
- Save button: Ghost variant, changes to green check when saved

### CascadeContextHeader.jsx

**Responsibilities**:
- Display initial cascade inputs (sticky context)
- Show latest checkpoint feedback
- Collapsible to save space

**JSX Structure**:
```jsx
<div className="cascade-context-header">
  {/* Initial Inputs */}
  <div className="context-section">
    <div className="section-header" onClick={toggleInputs}>
      <Icon icon="mdi:code-json" />
      <span>Initial Inputs</span>
      <Icon icon={inputsCollapsed ? "mdi:chevron-down" : "mdi:chevron-up"} />
    </div>
    {!inputsCollapsed && (
      <pre className="context-json">
        {JSON.stringify(cascadeInputs, null, 2)}
      </pre>
    )}
  </div>

  {/* Latest Feedback */}
  {latestCheckpoint?.response && (
    <div className="context-section">
      <div className="section-header">
        <Icon icon="mdi:comment-check" />
        <span>Latest Feedback</span>
      </div>
      <div className="feedback-content">
        <Badge variant="label" color="green">
          {latestCheckpoint.response.selected}
        </Badge>
        {latestCheckpoint.response.notes && (
          <p>{latestCheckpoint.response.notes}</p>
        )}
      </div>
    </div>
  )}
</div>
```

**Styling Notes**:
- Sticky position: top of scroll container
- Dark background with cyan border-bottom
- Collapsible sections with smooth transitions
- Compact JSON display (10px font, monospace)

### GhostMessage.jsx

**Responsibilities**:
- Display live LLM activity (tool calls, results, thinking)
- Auto-cleanup after 20s
- Parse and format content
- Exit animation

**JSX Structure**:
```jsx
<div className={`ghost-message ghost-${ghost.type} ${ghost.exiting ? 'ghost-exiting' : ''}`}>
  <div className="ghost-header">
    <Icon icon={getIconForType(ghost.type)} />
    <span className="ghost-title">{getTitleForType(ghost)}</span>
    <span className="ghost-time">{formatTimestamp(ghost.timestamp)}</span>
  </div>

  <div className="ghost-content">
    {ghost.type === 'tool_call' && (
      <>
        <div className="tool-name">{ghost.tool}</div>
        {ghost.arguments && (
          <details className="tool-args">
            <summary>Arguments</summary>
            <pre>{JSON.stringify(ghost.arguments, null, 2)}</pre>
          </details>
        )}
      </>
    )}

    {ghost.type === 'tool_result' && (
      <div className="tool-result">
        {parseToolResult(ghost.result)}
      </div>
    )}

    {ghost.type === 'thinking' && (
      <div className="thinking-content">
        {truncate(ghost.content, 200)}
      </div>
    )}
  </div>
</div>
```

**Styling Notes**:
- Translucent background (opacity: 0.85)
- Left border color by type (cyan for tool, green for result, purple for thinking)
- Exit animation: `slideOutLeft` over 600ms
- Compact 11px font size

---

## Phase 4: Custom Hooks

### useSessionStream.js

**Purpose**: Encapsulate all real-time data fetching and SSE logic

**Features**:
- SSE connection with automatic reconnection
- Session data polling (1s interval)
- Checkpoint data polling (1s interval)
- Saved session detection (2s interval)
- Ghost message extraction from session logs
- Round event tracking
- Orchestration state updates

**Returns**:
```javascript
{
  // Core data
  sessionData: object | null,
  checkpoint: Checkpoint | null,
  checkpointHistory: Checkpoint[],
  savedSessionData: object | null,
  isSavedSession: boolean,

  // Live activity
  ghostMessages: Ghost[],
  roundEvents: Event[],
  orchestrationState: {
    currentPhase: string,
    currentModel: string,
    totalCost: number,
    turnCount: number,
    status: 'idle' | 'thinking' | 'tool_running' | 'waiting_human',
    lastToolCall: string,
    phaseHistory: Phase[]
  },

  // State
  isLoading: boolean,
  error: string | null,

  // Actions
  refresh: () => void,
  clearGhosts: () => void
}
```

**Implementation Pattern**:
```javascript
export default function useSessionStream(sessionId) {
  const [sessionData, setSessionData] = useState(null);
  const [checkpoint, setCheckpoint] = useState(null);
  // ... other state

  // Refs to prevent SSE reconnection loops
  const checkpointRef = useRef(null);
  const sessionDataRef = useRef(null);

  // SSE setup
  useEffect(() => {
    if (!sessionId) return;

    const eventSource = new EventSource('/api/events/stream');

    eventSource.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.session_id !== sessionId) return;

      handleEvent(event);
    };

    return () => eventSource.close();
  }, [sessionId]);

  // Polling
  useEffect(() => {
    const interval = setInterval(fetchSessionData, 1000);
    return () => clearInterval(interval);
  }, [sessionId]);

  return { sessionData, checkpoint, ... };
}
```

### useGhostMessages.js

**Purpose**: Manage ghost message lifecycle and auto-cleanup

**Features**:
- Add ghost messages
- Auto-cleanup after 20 seconds
- Exit animation state management
- Parsing session logs to extract ghosts

**Returns**:
```javascript
{
  ghostMessages: Ghost[],
  addGhost: (ghost: Ghost) => void,
  clearGhosts: () => void,
  extractFromSessionLogs: (entries: LogEntry[]) => void
}
```

**Implementation**:
```javascript
export default function useGhostMessages() {
  const [ghosts, setGhosts] = useState([]);

  // Auto-cleanup
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setGhosts(prev => {
        // Mark old ones as exiting
        const updated = prev.map(g => {
          if (!g.exiting && now - g.createdAt >= 20000) {
            return { ...g, exiting: true, exitStartedAt: now };
          }
          return g;
        });

        // Remove fully exited ones
        return updated.filter(g =>
          !g.exiting || (now - g.exitStartedAt < 600)
        );
      });
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  const addGhost = useCallback((ghost) => {
    setGhosts(prev => [...prev, { ...ghost, createdAt: Date.now() }]);
  }, []);

  return { ghostMessages: ghosts, addGhost, clearGhosts: () => setGhosts([]) };
}
```

---

## Phase 5: Main ExploreView Component

### ExploreView.jsx Structure

```javascript
import React, { useState, useEffect } from 'react';
import { Button, Badge } from '../../components';
import CheckpointRenderer from '../../components/CheckpointRenderer';
import ExpandableCheckpoint from '../../components/ExpandableCheckpoint';
import CascadeContextHeader from '../../components/CascadeContextHeader';
import GhostMessage from '../../components/GhostMessage';
import LiveOrchestrationSidebar from '../../components/LiveOrchestrationSidebar';
import { useNarrationPlayer } from '../../components/NarrationPlayer';
import NarrationCaption from '../../components/NarrationCaption';
import CascadePicker from '../../components/CascadePicker';
import useSessionStream from './hooks/useSessionStream';
import './ExploreView.css';

const ExploreView = ({ params, navigate }) => {
  // Extract session from URL params
  const sessionId = params.session || params.id;

  // Use custom hook for all data fetching
  const {
    sessionData,
    checkpoint,
    checkpointHistory,
    ghostMessages,
    roundEvents,
    orchestrationState,
    savedSessionData,
    isSavedSession,
    isLoading,
    refresh
  } = useSessionStream(sessionId);

  // Narration player
  const {
    narrationAmplitude,
    playAudio,
    stopAudio
  } = useNarrationPlayer();

  // UI state
  const [showPicker, setShowPicker] = useState(!sessionId);

  // Handlers
  const handleCheckpointRespond = async (checkpointId, response) => {
    await fetch(`/api/checkpoints/${checkpointId}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response })
    });
    refresh();
  };

  const handleBranch = async (checkpointIndex, newResponse) => {
    // Call branch API
    const res = await fetch('/api/research-sessions/branch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        parent_research_session_id: savedSessionData.id,
        branch_checkpoint_index: checkpointIndex,
        new_response: newResponse
      })
    });
    const data = await res.json();
    navigate(`explore?session=${data.new_session_id}`);
  };

  const handleStartCascade = async (cascadeFile, inputs) => {
    // Run cascade API
    const res = await fetch('/api/run-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cascade_file: cascadeFile,
        inputs: inputs
      })
    });
    const data = await res.json();
    navigate(`explore?session=${data.session_id}`);
    setShowPicker(false);
  };

  const handleEndCascade = async () => {
    if (!confirm('Stop this cascade?')) return;
    await fetch('/api/cancel-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
  };

  // Show picker modal if no session
  if (showPicker) {
    return (
      <div className="explore-view">
        <CascadePicker
          onSelect={handleStartCascade}
          onCancel={() => navigate('studio')}
        />
      </div>
    );
  }

  // Loading state
  if (isLoading && !sessionData) {
    return (
      <div className="explore-view-loading">
        <Icon icon="mdi:loading" className="spinning" />
        <p>Loading session...</p>
      </div>
    );
  }

  return (
    <div className="explore-view">
      <div className="explore-layout">
        {/* Main Column */}
        <div className="explore-main-column">
          {/* Context Header (Sticky) */}
          <CascadeContextHeader
            cascadeInputs={sessionData?.input_data}
            checkpointHistory={checkpointHistory}
            cascadeId={sessionData?.cascade_id}
            savedSessionData={savedSessionData}
          />

          {/* Scrollable Content */}
          <div className="explore-main-content">
            {/* Ghost Messages */}
            {ghostMessages.map(ghost => (
              <GhostMessage key={ghost.id} ghost={ghost} />
            ))}

            {/* Checkpoint Timeline */}
            {checkpointHistory
              .filter(cp => cp.status === 'responded')
              .map((cp, idx) => (
                <ExpandableCheckpoint
                  key={cp.id}
                  checkpoint={cp}
                  index={idx}
                  sessionId={sessionId}
                  savedSessionData={savedSessionData}
                  onBranch={handleBranch}
                />
              ))}

            {/* Current Pending Checkpoint */}
            {checkpoint && (
              <div className="current-checkpoint">
                <CheckpointRenderer
                  checkpoint={checkpoint}
                  onSubmit={(response) => handleCheckpointRespond(checkpoint.id, response)}
                  variant="inline"
                  showPhaseOutput={true}
                />
              </div>
            )}

            {/* Empty State */}
            {!checkpoint && checkpointHistory.length === 0 && ghostMessages.length === 0 && (
              <div className="explore-empty">
                <Icon icon="mdi:compass" width="64" />
                <h2>Session Active</h2>
                <p>Waiting for activity...</p>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <LiveOrchestrationSidebar
          sessionId={sessionId}
          cascadeId={sessionData?.cascade_id}
          orchestrationState={orchestrationState}
          sessionData={sessionData}
          roundEvents={roundEvents}
          narrationAmplitude={narrationAmplitude}
          onEnd={handleEndCascade}
        />
      </div>

      {/* Narration Caption (Fixed Bottom) */}
      {isNarrating && (
        <NarrationCaption
          text={narrationText}
          duration={narrationDuration}
          amplitude={narrationAmplitude}
        />
      )}
    </div>
  );
};
```

**~300 lines** (vs 2000 in ResearchCockpit)

---

## Design System Updates

### Colors (Match AppShell)

**Old ResearchCockpit**:
```css
--accent-purple: #a78bfa
--accent-blue: #4A9EDD
--bg-card: #1a1a1a
```

**New ExploreView** (use CSS variables from `styles/variables.css`):
```css
--color-accent-cyan: #00e5ff       /* Primary */
--color-accent-purple: #a78bfa     /* Secondary */
--color-bg-primary: #000000        /* Pure black */
--color-border-dim: rgba(0, 229, 255, 0.15)
```

### Spacing (Data-Dense)

| Element | Old | New |
|---------|-----|-----|
| Card padding | 20px | 12px |
| Section gap | 24px | 16px |
| Font size | 14px | 12px |
| Button padding | 12px 24px | 8px 16px |
| Border radius | 12px | 6px |

### Typography

- **Old**: Quicksand, 14px, regular weight
- **New**: Google Sans Code (monospace), 12px, semibold labels

---

## Reusable Components - Keep vs Extract

### KEEP AS-IS (Already Modular)

| Component | Status | Why |
|-----------|--------|-----|
| LiveOrchestrationSidebar | ✅ Keep | 548 lines, complex, works well |
| CompactResearchTree | ✅ Keep | Already extracted, tested |
| NarrationPlayer/Caption | ✅ Keep | Already modular hooks + component |
| HTMLSection | ✅ Keep | Now using CheckpointRenderer pattern |
| CascadePicker | ✅ Keep | Already modal-based |

### EXTRACT (Currently Inline)

| Component | Lines | Priority | Reason |
|-----------|-------|----------|--------|
| ExpandableCheckpoint | 200 | HIGH | Used multiple times, clear responsibility |
| CascadeContextHeader | 90 | MEDIUM | Reusable in any cascade view |
| GhostMessage | 250 | HIGH | Complex parsing, reusable for live views |

### REWRITE (Too Coupled)

| Logic | Old Approach | New Approach |
|-------|--------------|--------------|
| SSE + Polling | Inline in component | useSessionStream hook |
| Ghost lifecycle | Inline setState | useGhostMessages hook |
| Checkpoint response | Inline fetch | Shared via useSessionStream |

---

## Questions for You

### 1. Feature Prioritization

ResearchCockpit has many features. Which are **essential** vs **nice-to-have**?

**Essential** (my guess):
- ✅ Live cascade execution with ghost messages
- ✅ Inline checkpoint rendering
- ✅ Checkpoint timeline
- ✅ Orchestration sidebar
- ✅ Start new cascades

**Nice-to-Have** (can add later):
- ⚠️ Branching from historical checkpoints
- ⚠️ Save to artifacts
- ⚠️ Narration playback (TTS)
- ⚠️ Research tree visualization
- ⚠️ Previous sessions browser

### 2. Layout Preferences

**Option A**: Two-column flexbox (simpler)
```
Main (flex-1) | Sidebar (300px fixed)
```

**Option B**: Resizable split (like Studio)
```
Main (75%) | Resizable Gutter | Sidebar (25%)
```

**Recommendation**: Option A (simpler, sidebar doesn't need resizing)

### 3. LiveOrchestrationSidebar

**Keep as-is** or **simplify**?

**Keep**: 548 lines, complex animations, works well, visually distinctive
**Simplify**: Could create lighter "SessionInfoPanel" with just stats, no orb/animations

**Recommendation**: Keep as-is - it's the signature visual of ResearchCockpit

### 4. Naming

**"ExploreView"** or something more specific?

- ExploreView ← Current placeholder name
- ResearchView ← Matches functionality
- LiveCascadeView ← Descriptive
- InteractiveView ← Generic

**Recommendation**: **ExploreView** (already in routes, "explore" is intuitive)

### 5. URL Routing

How should users access it?

**Option A**: `/#/explore?session=<id>` (AppShell routing)
**Option B**: `/#/explore/<session_id>` (path-based)

**Recommendation**: Option A (consistent with Studio's `?session=` pattern)

---

## Implementation Order (Recommended)

### Iteration 1: Core Functionality (MVP)
1. Extract ExpandableCheckpoint component
2. Extract GhostMessage component
3. Create useSessionStream hook
4. Create basic ExploreView layout with:
   - GhostMessage list
   - Current checkpoint (CheckpointRenderer)
   - LiveOrchestrationSidebar (reuse existing)
5. Test with live cascade

**Deliverable**: Basic Perplexity-style loop with ghost messages + checkpoints

### Iteration 2: Timeline & History
1. Extract CascadeContextHeader
2. Add checkpoint timeline (responded checkpoints)
3. Add expand/collapse for historical checkpoints
4. Test with multi-checkpoint cascade

**Deliverable**: Full checkpoint history visualization

### Iteration 3: Advanced Features
1. Branching support
2. Save to artifacts
3. Narration playback integration
4. Previous sessions browser
5. Research tree visualization

**Deliverable**: Feature parity with old ResearchCockpit

---

## Code Reuse Strategy

### Reuse Directly (No Changes)
- LiveOrchestrationSidebar.js + .css
- CompactResearchTree.js + .css
- NarrationPlayer.js (hook)
- NarrationCaption.js + .css
- CascadePicker.js + .css

### Reuse with Styling Updates
- ExpandableCheckpoint (extract + update colors)
- CascadeContextHeader (extract + update fonts)
- GhostMessage (extract + simplify)

### Rewrite from Scratch
- Main ExploreView component (use hooks, simpler state)
- SSE handling (custom hook)
- Checkpoint response logic (unified with InterruptsView)

---

## Risk Assessment

### Low Risk
- ✅ Component extraction (clear boundaries)
- ✅ Hook creation (state isolation)
- ✅ Layout implementation (flexbox, no complex split)
- ✅ CheckpointRenderer integration (already tested)

### Medium Risk
- ⚠️ SSE event handling (complex, many event types)
- ⚠️ Ghost message parsing (JSON extraction, data grids)
- ⚠️ Amplitude animation (requestAnimationFrame loop)

### High Risk
- 🔴 Branching (complex API, state management)
- 🔴 Narration timing (audio sync, word highlighting)
- 🔴 Research tree (recursive structure, navigation)

### Mitigation
- Start with MVP (Iteration 1)
- Test each component in isolation
- Reuse existing components where possible
- Defer high-risk features to Iteration 3

---

## Success Metrics

**ExploreView is successful if**:
1. ✅ Cascades execute and display live activity
2. ✅ Ghost messages appear/disappear automatically
3. ✅ Checkpoints render inline (using CheckpointRenderer)
4. ✅ User can respond to checkpoints inline
5. ✅ Cascade continues after checkpoint response
6. ✅ Orchestration sidebar shows live stats
7. ✅ Clean codebase (< 500 lines main component)
8. ✅ Reusable components exported
9. ✅ AppShell design system throughout

**Bonus**:
- Branching works
- Narration plays back
- Previous sessions browser
- Research tree visualization

---

## Next Steps

**For Your Review**:
1. Does this plan cover all the features you want?
2. Are there features we should **remove** or **defer**?
3. Should we keep LiveOrchestrationSidebar as-is or simplify?
4. Do you want branching support in MVP or save for later?
5. Any concerns about the approach?

**Once Approved**:
- I'll start with Iteration 1 (core functionality)
- Extract ExpandableCheckpoint, GhostMessage
- Create useSessionStream hook
- Build basic ExploreView layout
- Test with live cascade

Let me know your thoughts!
