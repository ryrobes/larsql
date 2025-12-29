# ExploreView Implementation Guide

**Status**: Ready for Implementation
**Created**: 2025-12-26
**Estimated Time**: 5-6 hours
**Complexity**: Medium-High

---

## Table of Contents

1. [Context & Purpose](#context--purpose)
2. [Current State](#current-state)
3. [Goals & Requirements](#goals--requirements)
4. [Architecture Overview](#architecture-overview)
5. [Component Specifications](#component-specifications)
6. [Implementation Steps](#implementation-steps)
7. [Extension Points (Future Features)](#extension-points-future-features)
8. [Critical Gotchas & Lessons Learned](#critical-gotchas--lessons-learned)
9. [Testing Plan](#testing-plan)
10. [Success Criteria](#success-criteria)

---

## Context & Purpose

### What Are We Building?

**ExploreView** is a **Perplexity-style interactive research interface** for RVBBIT cascades. It provides a **clean, real-time view of LLM execution** where:

- The LLM communicates **only** through `request_decision` tool calls
- Each decision creates rich UI (text, buttons, charts, forms)
- User responds inline
- Cascade continues with the response
- All activity visible in real-time (tool calls, thinking, costs)

**Think**: Perplexity's search interface, but you **see the orchestration** - what tools are being called, what models are thinking, how much it costs, and all decision points.

### Why Replace ResearchCockpit?

**Current ResearchCockpit** (`dashboard/frontend/src/components/ResearchCockpit.js`):
- ❌ **2,064 lines** of tangled React code
- ❌ **1,009 lines** of CSS with old purple theme
- ❌ **Complex SSE** event handling with reconnection loops
- ❌ **Inline components** (3 sub-components totaling 540 lines inside one file)
- ❌ **Ad-hoc patterns** (pre-dates AppShell design system)
- ✅ Works, but messy and hard to maintain

**New ExploreView** will be:
- ✅ **~750 lines total** (83% reduction!)
- ✅ **AppShell design system** (pure black, cyan accents, data-dense)
- ✅ **Polling-based** (no SSE complexity)
- ✅ **Modular components** (extracted and reusable)
- ✅ **Framer Motion** animations throughout
- ✅ **Extension points** for timeline, branching, narration

### What Problem Does This Solve?

**User Story**: "As a user running research cascades, I want to see the LLM's work in real-time and interact with decision points inline, without switching between pages or dealing with clunky modal interruptions."

**Core Loop** (Perplexity-style):
1. User asks a question / starts cascade
2. LLM researches (tool calls visible as "ghost messages")
3. LLM creates rich UI via `request_decision` (chart, form, buttons)
4. User responds inline
5. LLM continues with response
6. Loop repeats until complete

---

## Current State

### What Exists Today

**Working Systems**:
1. ✅ **Universal Checkpoint System**:
   - `CheckpointRenderer` - Renders DSL or HTMX anywhere
   - `CheckpointModal` - Modal overlay
   - `InterruptsView` - Split-panel dedicated page
   - All tested and working!

2. ✅ **`request_decision` Tool** (Backend):
   - Two modes: DSL (card grids) or HTMX (custom HTML)
   - System extras: Notes, Screenshot
   - Returns structured response
   - **CRITICAL FIX APPLIED**: Cross-process cache reload (cascades resume immediately)

3. ✅ **LiveOrchestrationSidebar** Component:
   - Status orb with animations
   - Cost ticker
   - Session stats
   - Phase timeline
   - Research tree integration
   - 548 lines, fully functional

4. ✅ **Studio's Polling Pattern** (`studio/hooks/useTimelinePolling.js`):
   - Cursor-based incremental updates
   - Deduplication via ref
   - 750ms poll interval
   - Auto-stops after completion
   - NO SSE - pure HTTP polling

**Placeholder View**:
- `src/views/explore/ExploreView.jsx` - Currently just a placeholder (24 lines)

### What Needs Building

**Missing Pieces** for Iteration 1 MVP:
1. ❌ `GhostMessage` component - **CREATED** ✅ (needs wiring)
2. ❌ `useExplorePolling` hook - Adapt Studio's pattern
3. ❌ Simplified sidebar or adapt existing LiveOrchestrationSidebar
4. ❌ ExploreView main component - Layout + data flow
5. ❌ ExploreView.css - AppShell theme styling

---

## Goals & Requirements

### Iteration 1: MVP Scope

**IN SCOPE** (Must Have):
1. ✅ **Live cascade execution** with visible tool calls
2. ✅ **Ghost messages** - Translucent cards showing LLM activity
3. ✅ **Inline checkpoint rendering** - Current pending checkpoint at bottom
4. ✅ **Perplexity loop** - Submit → Continue seamlessly
5. ✅ **Orchestration sidebar** - Live stats (phase, cost, status)
6. ✅ **Start new cascades** - CascadePicker modal
7. ✅ **End cascade** button - Cancel running execution
8. ✅ **Empty states** - Idle, running, completed
9. ✅ **AppShell theme** - Pure black, cyan accents, data-dense
10. ✅ **Framer Motion** animations - Smooth ghost appear/disappear

**OUT OF SCOPE** (Iteration 2+):
- ⏸️ **Timeline/history** - Responded checkpoints (design hooks in place)
- ⏸️ **Branching** - Re-submit historical checkpoints (API exists, don't wire UI)
- ⏸️ **Save to artifacts** - Individual checkpoint saves (slot reserved)
- ⏸️ **Narration playback** - TTS audio with word highlighting (hook ready)
- ⏸️ **Research tree** - Branch visualization (sidebar slot reserved)
- ⏸️ **Previous sessions** - Browse history (sidebar slot reserved)
- ⏸️ **Context header** - Sticky inputs display (extract component later)

### Non-Functional Requirements

**Performance**:
- Poll every 750ms (Studio's interval)
- Deduplicate logs client-side
- Ghost messages: Keep last 10, auto-remove after 30s
- Smooth 60fps animations (Framer Motion)

**Maintainability**:
- < 500 lines in main component
- Clear separation of concerns (hooks, components, utils)
- TypeScript-ready (prop shapes documented)

**Extensibility**:
- Comment `// EXTENSION POINT: Timeline` where features can be added
- Keep hook return values extensible (add fields without breaking)
- Use composition over inheritance

---

## Architecture Overview

### The Polling Pattern (No SSE!)

**Why No SSE?**
- SSE has reconnection complexity
- Missed events on disconnect
- Event bus management overhead
- Studio proved polling works better

**How Polling Works** (Studio's pattern):

```
Every 750ms:
  ↓
GET /api/playground/session-stream/{sessionId}?after={cursor}
  ↓
Returns: {
  rows: [...],        // Logs since cursor
  cursor: "2025-12-26 10:30:15.123",  // New cursor
  session_status: "running",
  total_cost: 0.00123,
  session_complete: false
}
  ↓
Deduplicate by message_id (use ref, not state)
  ↓
Append new rows to logs array
  ↓
Derive UI state:
  - Ghost messages (last 10 tool calls/results)
  - Orchestration state (phase, model, cost, status)
  - Checkpoint polling (separate call)
  ↓
Update state → React re-renders
  ↓
Update cursor ref for next poll
```

**Benefits**:
- Single source of truth (database)
- Self-healing (refresh works mid-execution)
- Complete data (no missed events)
- Simpler code (no event bus)

### Component Hierarchy

```
ExploreView
├── CascadePicker (modal, if no session)
└── Layout (two-column flexbox)
    ├── Main Column (flex: 1, scrollable)
    │   └── Main Content (padding: 16px)
    │       ├── GhostMessage (x N, animated)
    │       ├── [EXTENSION: ExpandableCheckpoint timeline]
    │       ├── CheckpointRenderer (current pending)
    │       └── Empty State
    │
    └── Sidebar (width: 320px, fixed)
        └── LiveOrchestrationSidebar
            ├── Status orb
            ├── Cost ticker
            ├── Session stats
            ├── [EXTENSION: Phase timeline]
            ├── [EXTENSION: Research tree]
            ├── [EXTENSION: Previous sessions]
            └── END button
```

**No Split components** - Simple flexbox for MVP

### Data Flow

```
useExplorePolling(sessionId)
  ├─ Poll session logs (750ms)
  ├─ Poll checkpoints (750ms)
  └─ Derive state from logs
      ↓
      ├─ logs: LogRow[]
      ├─ ghostMessages: Ghost[]
      ├─ checkpoint: Checkpoint | null
      ├─ orchestrationState: {...}
      └─ sessionStatus: 'running' | 'completed'
          ↓
          ExploreView renders
            ├─ GhostMessage (map ghostMessages)
            ├─ CheckpointRenderer (if checkpoint)
            └─ LiveOrchestrationSidebar (orchestrationState)
                ↓
                User responds to checkpoint
                  ↓
                  POST /api/checkpoints/{id}/respond
                    ↓
                    Polling detects response (within 0.5s)
                      ↓
                      Checkpoint state updates
                        ↓
                        Cascade continues
                          ↓
                          New ghost messages appear
```

---

## Component Specifications

### 1. GhostMessage Component

**Status**: ✅ **CREATED** (`src/components/GhostMessage.jsx`)

**Purpose**: Translucent card showing LLM's live activity (tool calls, results, thinking)

**Props**:
```typescript
{
  ghost: {
    id: string,                    // Unique identifier (message_id)
    type: 'tool_call' | 'tool_result' | 'thinking',
    tool?: string,                 // Tool name (for tool_call/result)
    content: string,               // Message content or result
    arguments?: object,            // Parsed tool arguments
    result?: any,                  // Tool result data
    timestamp: string,             // ISO timestamp
  }
}
```

**Styling**:
- Background: `rgba(0, 0, 0, 0.6)`
- Opacity: 0.85
- Border-left: 2px solid (cyan/green/purple by type)
- Font: 11px monospace
- Padding: 10px 12px (compact)

**Lifecycle** (managed by parent):
- Parent adds ghost to array
- Parent sets timeout for 30s
- Parent removes ghost (Framer Motion handles exit animation)

**Current Implementation**:
- ✅ Icon by type
- ✅ Timestamp display
- ✅ Content truncation (200 chars)
- ✅ JSON parsing (collapsible details)
- ⏸️ Data grid rendering (TODO for Iteration 2 - keep simple for now)

**Example Usage**:
```jsx
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

### 2. useExplorePolling Hook

**Status**: ❌ **TO CREATE** (`src/views/explore/hooks/useExplorePolling.js`)

**Purpose**: Poll session data and derive UI state (NO SSE!)

**API**:
```typescript
useExplorePolling(sessionId: string) => {
  // Core data
  logs: LogRow[],                  // All session logs (incremental)
  checkpoint: Checkpoint | null,   // Current pending checkpoint

  // Derived state
  ghostMessages: Ghost[],          // Last 10 tool calls/results
  orchestrationState: {
    currentPhase: string,
    currentModel: string,
    totalCost: number,
    status: 'idle' | 'thinking' | 'tool_running' | 'waiting_human',
    phaseHistory: Phase[],         // Last 5 phases
    turnCount: number
  },

  // Session metadata
  sessionStatus: 'running' | 'completed' | 'error' | 'cancelled',
  sessionError: string | null,
  totalCost: number,

  // State
  isPolling: boolean,
  error: string | null,

  // Actions
  refresh: () => void,
  clearGhosts: () => void
}
```

**Implementation Pattern** (adapt from `studio/hooks/useTimelinePolling.js`):

```javascript
import { useState, useEffect, useRef, useCallback } from 'react';

const POLL_INTERVAL = 750;        // 750ms (Studio's interval)
const GHOST_TIMEOUT = 30000;      // 30s before auto-remove
const GHOST_MAX_COUNT = 10;       // Keep last 10 only

export default function useExplorePolling(sessionId) {
  // State
  const [logs, setLogs] = useState([]);
  const [checkpoint, setCheckpoint] = useState(null);
  const [ghostMessages, setGhostMessages] = useState([]);
  const [orchestrationState, setOrchestrationState] = useState({
    currentPhase: null,
    currentModel: null,
    totalCost: 0,
    status: 'idle',
    phaseHistory: [],
    turnCount: 0
  });
  const [sessionStatus, setSessionStatus] = useState(null);
  const [totalCost, setTotalCost] = useState(0);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);

  // Refs (prevent re-render loops)
  const cursorRef = useRef('1970-01-01 00:00:00');
  const seenIdsRef = useRef(new Set());
  const ghostTimeoutsRef = useRef(new Map());

  // Poll session logs
  const pollSessionLogs = useCallback(async () => {
    if (!sessionId) return;

    try {
      setIsPolling(true);

      // Use Studio's endpoint
      const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(cursorRef.current)}`;
      const res = await fetch(url);
      const data = await res.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Deduplicate and append new logs
      const newRows = [];
      for (const row of data.rows || []) {
        if (row.message_id && !seenIdsRef.current.has(row.message_id)) {
          seenIdsRef.current.add(row.message_id);
          newRows.push(row);
        }
      }

      if (newRows.length > 0) {
        setLogs(prev => [...prev, ...newRows]);
        cursorRef.current = data.cursor || cursorRef.current;

        // Derive ghost messages from new logs
        deriveGhostMessages(newRows);

        // Update orchestration state
        updateOrchestrationState(newRows, data);
      }

      // Update session metadata
      if (data.session_status) setSessionStatus(data.session_status);
      if (data.total_cost !== undefined) setTotalCost(data.total_cost);

      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsPolling(false);
    }
  }, [sessionId]);

  // Poll checkpoints (separate from logs)
  const pollCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}`);
      const data = await res.json();

      if (!data.error && data.checkpoints && data.checkpoints.length > 0) {
        const pending = data.checkpoints.find(cp => cp.status === 'pending');
        setCheckpoint(pending || null);
      } else {
        setCheckpoint(null);
      }
    } catch (err) {
      console.error('[useExplorePolling] Checkpoint poll error:', err);
    }
  }, [sessionId]);

  // Derive ghost messages from new logs
  const deriveGhostMessages = useCallback((newLogs) => {
    const newGhosts = [];

    for (const log of newLogs) {
      // Tool calls
      if (log.tool_name && log.role === 'assistant') {
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_call',
          tool: log.tool_name,
          content: log.content,
          arguments: null, // Parse from content if needed
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }

      // Tool results
      if (log.role === 'tool') {
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_result',
          tool: log.tool_name,
          result: log.content,
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }
    }

    if (newGhosts.length > 0) {
      setGhostMessages(prev => {
        const combined = [...prev, ...newGhosts];
        // Keep last 10 only
        return combined.slice(-GHOST_MAX_COUNT);
      });

      // Setup auto-removal timeouts
      newGhosts.forEach(ghost => {
        const timeoutId = setTimeout(() => {
          setGhostMessages(prev => prev.filter(g => g.id !== ghost.id));
          ghostTimeoutsRef.current.delete(ghost.id);
        }, GHOST_TIMEOUT);

        ghostTimeoutsRef.current.set(ghost.id, timeoutId);
      });
    }
  }, []);

  // Update orchestration state from logs
  const updateOrchestrationState = useCallback((newLogs, apiData) => {
    setOrchestrationState(prev => {
      // Find latest phase
      const phaseStart = newLogs.reverse().find(log =>
        log.event_type === 'phase_start' || log.phase_name
      );

      return {
        ...prev,
        currentPhase: phaseStart?.phase_name || prev.currentPhase,
        currentModel: phaseStart?.model || prev.currentModel,
        totalCost: apiData.total_cost || prev.totalCost,
        status: determineStatus(newLogs, checkpoint),
        // Can enhance with phaseHistory, turnCount later
      };
    });
  }, [checkpoint]);

  // Determine status from recent activity
  const determineStatus = (logs, currentCheckpoint) => {
    if (currentCheckpoint) return 'waiting_human';

    const recentLogs = logs.slice(-5);
    if (recentLogs.some(l => l.role === 'tool')) return 'tool_running';
    if (recentLogs.some(l => l.role === 'assistant')) return 'thinking';

    return 'idle';
  };

  // Setup polling intervals
  useEffect(() => {
    if (!sessionId) return;

    // Initial fetch
    pollSessionLogs();
    pollCheckpoint();

    // Poll at interval
    const logsInterval = setInterval(pollSessionLogs, POLL_INTERVAL);
    const checkpointInterval = setInterval(pollCheckpoint, POLL_INTERVAL);

    return () => {
      clearInterval(logsInterval);
      clearInterval(checkpointInterval);

      // Cleanup ghost timeouts
      ghostTimeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
      ghostTimeoutsRef.current.clear();
    };
  }, [sessionId, pollSessionLogs, pollCheckpoint]);

  // Auto-stop polling 10s after completion
  useEffect(() => {
    if (sessionStatus === 'completed' && sessionId) {
      const timeout = setTimeout(() => {
        console.log('[useExplorePolling] Session completed, stopping polls');
        // Could add a flag here to stop polling
      }, 10000);

      return () => clearTimeout(timeout);
    }
  }, [sessionStatus, sessionId]);

  return {
    logs,
    checkpoint,
    ghostMessages,
    orchestrationState,
    sessionStatus,
    totalCost,
    isPolling,
    error,
    refresh: () => {
      pollSessionLogs();
      pollCheckpoint();
    },
    clearGhosts: () => {
      setGhostMessages([]);
      ghostTimeoutsRef.current.forEach(t => clearTimeout(t));
      ghostTimeoutsRef.current.clear();
    }
  };
}
```

**~200 lines**

**Key Differences from Studio**:
- ✅ Adds ghost message derivation
- ✅ Adds checkpoint polling
- ✅ Simpler orchestration state (no candidates, reforge)
- ✅ Auto-cleanup for ghosts

### 3. Simplified Orchestration Sidebar (Option A - Recommended)

**Status**: ❌ **TO CREATE** (`src/views/explore/components/SimpleSidebar.jsx`)

**Purpose**: Lightweight version of LiveOrchestrationSidebar for MVP

**Why Simplify?**
- LiveOrchestrationSidebar is 548 lines with complex animations
- Many features not needed for MVP (research tree, previous sessions, narration orb)
- Can add features incrementally

**Features** (MVP):
- ✅ Session ID display
- ✅ Cascade name
- ✅ Current phase
- ✅ Current model
- ✅ Total cost (large, prominent)
- ✅ Status indicator (colored dot + text)
- ✅ END button (if running)

**NOT Included** (can add later):
- ⏸️ Animated status orb with orbiting dots
- ⏸️ Narration amplitude glow
- ⏸️ Phase timeline (last 5 phases)
- ⏸️ Research tree
- ⏸️ Previous sessions browser
- ⏸️ Token stats

**Implementation**:
```jsx
import React from 'react';
import { Icon } from '@iconify/react';
import { Button, Badge } from '../../../components';
import './SimpleSidebar.css';

const SimpleSidebar = ({
  sessionId,
  cascadeId,
  orchestrationState,
  totalCost,
  sessionStatus,
  onEnd
}) => {
  const statusConfig = {
    thinking: { color: 'cyan', icon: 'mdi:brain', label: 'Thinking' },
    tool_running: { color: 'green', icon: 'mdi:hammer-wrench', label: 'Using Tools' },
    waiting_human: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Waiting' },
    idle: { color: 'gray', icon: 'mdi:circle', label: 'Idle' },
  };

  const currentStatus = statusConfig[orchestrationState.status] || statusConfig.idle;

  return (
    <div className="simple-sidebar">
      {/* Status Section */}
      <div className="sidebar-section">
        <div className="sidebar-label">Status</div>
        <div className="status-display">
          <Badge
            variant="status"
            color={currentStatus.color}
            icon={currentStatus.icon}
            pulse={sessionStatus === 'running'}
          >
            {currentStatus.label}
          </Badge>
        </div>
      </div>

      {/* Cost Section */}
      <div className="sidebar-section">
        <div className="sidebar-label">Total Cost</div>
        <div className="cost-display">
          ${totalCost.toFixed(4)}
        </div>
      </div>

      {/* Session Info */}
      <div className="sidebar-section">
        <div className="sidebar-label">Session</div>
        <div className="session-info">
          <div className="info-row">
            <span className="info-label">Cascade</span>
            <span className="info-value">{cascadeId || 'Unknown'}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Phase</span>
            <span className="info-value">{orchestrationState.currentPhase || '-'}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Model</span>
            <span className="info-value">
              {orchestrationState.currentModel?.split('/').pop() || '-'}
            </span>
          </div>
        </div>
      </div>

      {/* EXTENSION POINT: Phase Timeline */}
      {/* {orchestrationState.phaseHistory && (
        <div className="sidebar-section">
          <div className="sidebar-label">Recent Phases</div>
          <PhaseTimeline phases={orchestrationState.phaseHistory} />
        </div>
      )} */}

      {/* EXTENSION POINT: Research Tree */}
      {/* <CompactResearchTree sessionId={sessionId} currentSessionId={sessionId} /> */}

      {/* Actions */}
      {sessionStatus === 'running' && onEnd && (
        <div className="sidebar-actions">
          <Button
            variant="danger"
            size="sm"
            icon="mdi:stop-circle"
            onClick={onEnd}
          >
            End Cascade
          </Button>
        </div>
      )}
    </div>
  );
};

export default SimpleSidebar;
```

**~100 lines**

**Styling** (`SimpleSidebar.css`):
```css
.simple-sidebar {
  width: 320px;
  height: 100%;
  background: var(--color-bg-primary);
  border-left: 1px solid var(--color-border-dim);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  overflow-y: auto;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.cost-display {
  font-size: 28px;
  font-weight: var(--font-weight-bold);
  color: var(--color-accent-green);
  font-family: var(--font-mono);
}

.session-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-sm);
}

.info-label {
  color: var(--color-text-muted);
}

.info-value {
  color: var(--color-text-primary);
  font-family: var(--font-mono);
  font-weight: var(--font-weight-medium);
}

.sidebar-actions {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-dim);
}
```

**Alternative**: Use existing `LiveOrchestrationSidebar` and pass minimal props
- Make `narrationAmplitude` default to 0
- Hide sections we don't need yet
- ~10 line changes to existing component

**Recommendation**: Create SimpleSidebar for MVP (cleaner), upgrade to full LiveOrchestrationSidebar in Iteration 2

### 4. ExploreView Main Component

**Status**: ❌ **TO CREATE** (`src/views/explore/ExploreView.jsx`)

**Purpose**: Main view component with Perplexity-style loop

**Props** (from AppShell):
```typescript
{
  params: {
    session?: string,  // URL param: ?session=xyz
    cascade?: string,  // URL param: ?cascade=file.yaml
  },
  navigate: (view: string, params?: object) => void
}
```

**State** (minimal - hook does heavy lifting):
```javascript
const [showPicker, setShowPicker] = useState(!sessionId);
// Everything else from useExplorePolling hook!
```

**Implementation Skeleton**:
```jsx
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import { Button, Badge, useToast } from '../../components';
import CheckpointRenderer from '../../components/CheckpointRenderer';
import GhostMessage from '../../components/GhostMessage';
import SimpleSidebar from './components/SimpleSidebar';
import CascadePicker from '../../components/CascadePicker';
import useExplorePolling from './hooks/useExplorePolling';
import './ExploreView.css';

const ExploreView = ({ params, navigate }) => {
  const sessionId = params.session || params.id;
  const [showPicker, setShowPicker] = useState(!sessionId);
  const { showToast } = useToast();

  // Poll for all data (NO SSE!)
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
    if (!checkpoint) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response })
      });

      const data = await res.json();

      if (data.error) {
        showToast('error', `Failed: ${data.error}`);
        return;
      }

      showToast('success', 'Response submitted');
      // Polling will detect and update automatically

    } catch (err) {
      showToast('error', `Error: ${err.message}`);
    }
  };

  const handleStartCascade = async (cascadeFile, inputs) => {
    try {
      const res = await fetch('http://localhost:5001/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_file: cascadeFile,
          inputs: inputs,
          // Auto-assign session ID
        })
      });

      const data = await res.json();

      if (data.error) {
        showToast('error', data.error);
        return;
      }

      // Navigate to new session
      navigate(`explore?session=${data.session_id}`);
      setShowPicker(false);
      showToast('success', 'Cascade started');

    } catch (err) {
      showToast('error', `Failed to start: ${err.message}`);
    }
  };

  const handleEndCascade = async () => {
    if (!window.confirm('Stop this cascade?')) return;

    try {
      await fetch('http://localhost:5001/api/cancel-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });

      showToast('success', 'Cascade cancelled');

    } catch (err) {
      showToast('error', `Failed to cancel: ${err.message}`);
    }
  };

  // Show picker if no session
  if (showPicker || !sessionId) {
    return (
      <div className="explore-view">
        <div className="explore-picker-overlay">
          <CascadePicker
            onSelect={handleStartCascade}
            onCancel={() => navigate('studio')}
          />
        </div>
      </div>
    );
  }

  // Loading state
  if (isPolling && logs.length === 0) {
    return (
      <div className="explore-view-loading">
        <Icon icon="mdi:loading" className="spinning" width="32" />
        <p>Loading session...</p>
      </div>
    );
  }

  return (
    <div className="explore-view">
      {/* Two-column layout */}
      <div className="explore-layout">

        {/* Main Column */}
        <div className="explore-main-column">
          <div className="explore-main-content">

            {/* EXTENSION POINT: Context Header (sticky, shows inputs) */}
            {/* <CascadeContextHeader cascadeInputs={...} checkpointHistory={...} /> */}

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

            {/* EXTENSION POINT: Timeline of Responded Checkpoints */}
            {/* {checkpointHistory
                .filter(cp => cp.status === 'responded')
                .map((cp, idx) => (
                  <ExpandableCheckpoint
                    key={cp.id}
                    checkpoint={cp}
                    index={idx}
                    sessionId={sessionId}
                  />
                ))}
            */}

            {/* Current Pending Checkpoint */}
            {checkpoint && (
              <motion.div
                className="current-checkpoint"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <div className="checkpoint-label">
                  <Icon icon="mdi:hand-back-right" width="16" />
                  <span>Human Input Required</span>
                </div>
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
                  icon={sessionStatus === 'completed' ? 'mdi:check-circle' : 'mdi:compass'}
                  width="64"
                  className={sessionStatus === 'running' ? 'spinning-slow' : ''}
                />
                <h2>
                  {sessionStatus === 'running' && 'Cascade Active'}
                  {sessionStatus === 'completed' && 'Cascade Complete'}
                  {!sessionStatus && 'Waiting for Activity'}
                </h2>
                <p>
                  {sessionStatus === 'running' && 'Activity will appear here as the cascade executes.'}
                  {sessionStatus === 'completed' && 'All done! Start a new cascade to continue.'}
                  {!sessionStatus && 'Start a cascade to begin.'}
                </p>
                {sessionStatus === 'completed' && (
                  <Button
                    variant="primary"
                    icon="mdi:plus"
                    onClick={() => setShowPicker(true)}
                  >
                    New Cascade
                  </Button>
                )}
              </div>
            )}

          </div>
        </div>

        {/* Sidebar */}
        <SimpleSidebar
          sessionId={sessionId}
          cascadeId={orchestrationState.cascadeId || cascadeId}
          orchestrationState={orchestrationState}
          totalCost={totalCost}
          sessionStatus={sessionStatus}
          onEnd={handleEndCascade}
        />

      </div>

      {/* EXTENSION POINT: Narration Caption */}
      {/* {isNarrating && (
        <NarrationCaption
          text={narrationText}
          duration={narrationDuration}
          amplitude={narrationAmplitude}
        />
      )} */}
    </div>
  );
};

export default ExploreView;
```

**~250 lines**

### 5. ExploreView Styling

**Status**: ❌ **TO CREATE** (`src/views/explore/ExploreView.css`)

**Purpose**: Layout + AppShell theme integration

**Implementation**:
```css
/* ============================================
   EXPLORE VIEW - Perplexity-style research
   ============================================ */

.explore-view {
  width: 100%;
  height: 100vh;
  background: var(--color-bg-primary);
  overflow: hidden;
}

/* Loading state */
.explore-view-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  height: 100vh;
  color: var(--color-text-muted);
}

.spinning {
  animation: spin 1s linear infinite;
}

.spinning-slow {
  animation: spin 3s linear infinite;
}

/* Picker overlay */
.explore-picker-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
}

/* ============================================
   LAYOUT - Two-column flexbox
   ============================================ */

.explore-layout {
  display: flex;
  height: 100%;
}

/* Main column (scrollable) */
.explore-main-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.explore-main-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ============================================
   CURRENT CHECKPOINT
   ============================================ */

.current-checkpoint {
  border: 1px solid var(--color-accent-yellow);
  border-radius: 6px;
  padding: 12px;
  background: rgba(251, 191, 36, 0.05);
  box-shadow: 0 0 20px rgba(251, 191, 36, 0.1);
}

.checkpoint-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-accent-yellow);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ============================================
   EMPTY STATE
   ============================================ */

.explore-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  min-height: 400px;
  color: var(--color-text-muted);
  text-align: center;
}

.explore-empty h2 {
  margin: 0;
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.explore-empty p {
  margin: 0;
  font-size: var(--font-size-md);
  max-width: 400px;
}

/* ============================================
   SCROLLBAR
   ============================================ */

.explore-main-content::-webkit-scrollbar {
  width: 6px;
}

.explore-main-content::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.4);
}

.explore-main-content::-webkit-scrollbar-thumb {
  background: rgba(0, 229, 255, 0.3);
  border-radius: 3px;
}

.explore-main-content::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 229, 255, 0.5);
}

/* ============================================
   ANIMATIONS
   ============================================ */

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ============================================
   RESPONSIVE
   ============================================ */

@media (max-width: 1024px) {
  .explore-layout {
    flex-direction: column;
  }

  .simple-sidebar,
  .explore-main-column {
    width: 100%;
  }
}
```

**~150 lines**

---

## Implementation Steps (Detailed)

### Phase 1: Create Core Infrastructure

**Step 1.1** - Create useExplorePolling Hook (90 min)
- File: `src/views/explore/hooks/useExplorePolling.js`
- Copy pattern from `studio/hooks/useTimelinePolling.js`
- Add ghost message derivation
- Add checkpoint polling
- Add orchestration state derivation
- Test: Console.log all return values

**Step 1.2** - Create SimpleSidebar Component (45 min)
- File: `src/views/explore/components/SimpleSidebar.jsx`
- File: `src/views/explore/components/SimpleSidebar.css`
- Or: Adapt existing LiveOrchestrationSidebar (15 min)
- Test: Renders with mock data

**Step 1.3** - Export Components (5 min)
- Add GhostMessage to `components/index.js` ✅ (already done)
- Test: Import works

### Phase 2: Build ExploreView

**Step 2.1** - Create Layout (60 min)
- File: `src/views/explore/ExploreView.jsx`
- File: `src/views/explore/ExploreView.css`
- Two-column flexbox
- Import all components
- Wire up useExplorePolling hook
- Test: Renders empty state

**Step 2.2** - Add Ghost Messages (30 min)
- Map ghostMessages from hook
- Wrap with Framer Motion AnimatePresence
- Test: Mock ghost appears/disappears

**Step 2.3** - Add Checkpoint Rendering (30 min)
- Render current checkpoint with CheckpointRenderer
- Wire up submit handler
- Test: Mock checkpoint renders

**Step 2.4** - Add CascadePicker (20 min)
- Show modal when no session
- Handle cascade start
- Navigate to new session
- Test: Can start new cascade

### Phase 3: Testing & Polish

**Step 3.1** - Integration Test (45 min)
- Run real cascade: `rvbbit run examples/htmx_demo.yaml --input '{"task": "..."}'`
- Navigate to `/#/explore?session=test_explore`
- Verify:
  - Ghost messages appear for tool calls
  - Checkpoint renders when LLM calls request_decision
  - Can respond inline
  - Cascade continues after response
  - Sidebar shows live stats
  - Empty state after completion

**Step 3.2** - Fix Issues (30 min)
- Debug any polling issues
- Fix styling inconsistencies
- Test responsive layout

**Step 3.3** - Document (15 min)
- Add comments for extension points
- Update this doc with "as-built" notes
- Create usage examples

**Total**: ~5.5 hours

---

## Extension Points (Future Features)

### Timeline & History (Iteration 2)

**Design Considerations**:
- Checkpoint history already in `useExplorePolling` return value (just add fetch)
- ExpandableCheckpoint component needs extraction (200 lines from ResearchCockpit)
- CascadeContextHeader needs extraction (90 lines from ResearchCockpit)

**Where to Add** (in ExploreView.jsx):
```jsx
// After ghost messages, before current checkpoint:

{/* EXTENSION POINT: Timeline */}
{checkpointHistory
  .filter(cp => cp.status === 'responded')
  .map((cp, idx) => (
    <ExpandableCheckpoint
      key={cp.id}
      checkpoint={cp}
      index={idx}
      sessionId={sessionId}
      // onBranch prop for Iteration 3
    />
  ))}
```

**Hook Extension**:
```javascript
// In useExplorePolling.js, add:
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
```

**Components Needed**:
1. Extract `ExpandableCheckpoint` from ResearchCockpit.js lines 1511-1710
2. Extract `CascadeContextHeader` from ResearchCockpit.js lines 1716-1805
3. Update both to use AppShell theme

### Branching from History (Iteration 3)

**Design Considerations**:
- Backend API already exists: `POST /api/research-sessions/branch`
- ExpandableCheckpoint already supports `onBranch` callback
- Just need to wire up handler and navigation

**Where to Add** (in ExploreView.jsx):
```jsx
const handleBranch = async (checkpointIndex, newResponse) => {
  // Ensure session is saved first
  let researchSessionId = savedSessionData?.id;
  if (!researchSessionId) {
    // Trigger auto-save
    const saveRes = await fetch('/api/research-sessions/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
    researchSessionId = (await saveRes.json()).id;
  }

  // Create branch
  const res = await fetch('/api/research-sessions/branch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      parent_research_session_id: researchSessionId,
      branch_checkpoint_index: checkpointIndex,
      new_response: newResponse
    })
  });

  const data = await res.json();
  navigate(`explore?session=${data.new_session_id}`);
  showToast('success', 'Branch created');
};

// Pass to ExpandableCheckpoint:
<ExpandableCheckpoint
  // ... existing props
  onBranch={handleBranch}  // ADD
/>
```

**No Hook Changes Needed** - Just UI wiring

### Narration Playback (Iteration 3)

**Design Considerations**:
- `useNarrationPlayer` hook already exists
- `NarrationCaption` component already exists
- Just need to detect narration events in polling

**Where to Add** (in ExploreView.jsx):
```jsx
import { useNarrationPlayer } from '../../components/NarrationPlayer';
import NarrationCaption from '../../components/NarrationCaption';

const ExploreView = ({ params, navigate }) => {
  // ADD narration
  const {
    playAudio,
    stopAudio,
    narrationAmplitude,
    isPlaying
  } = useNarrationPlayer({
    onAmplitudeChange: setNarrationAmplitude,
    onPlaybackStart: () => setIsNarrating(true),
    onPlaybackEnd: () => {
      setIsNarrating(false);
      setNarrationText('');
    }
  });

  const [isNarrating, setIsNarrating] = useState(false);
  const [narrationText, setNarrationText] = useState('');
  const [narrationDuration, setNarrationDuration] = useState(0);

  // ... existing code

  // Pass amplitude to sidebar
  <SimpleSidebar
    narrationAmplitude={narrationAmplitude}  // ADD (make prop optional with default 0)
    // ... other props
  />

  // Render caption at bottom
  {isNarrating && (
    <NarrationCaption
      text={narrationText}
      duration={narrationDuration}
      amplitude={narrationAmplitude}
    />
  )}
};
```

**Hook Extension** (detect narration in logs):
```javascript
// In useExplorePolling.js, check for narration events:
for (const log of newLogs) {
  if (log.event_type === 'narration_audio') {
    // Trigger playback via callback
    onNarrationDetected?.({
      audioPath: log.audio_path,
      text: log.narration_text,
      duration: log.duration
    });
  }
}

// Update return value:
return {
  // ... existing
  onNarrationDetected: callbackRef.current  // ADD
};

// In ExploreView, set callback:
useEffect(() => {
  pollingHook.onNarrationDetected = ({ audioPath, text, duration }) => {
    playAudio(audioPath);
    setNarrationText(text);
    setNarrationDuration(duration);
  };
}, [playAudio]);
```

**Sidebar Extension** (for narration glow):
```javascript
// In SimpleSidebar.jsx, add status orb with narration glow
// OR upgrade to full LiveOrchestrationSidebar which already has this
```

### Save to Artifacts (Iteration 2+)

**Design Considerations**:
- Already implemented in ExpandableCheckpoint
- Backend API: `POST /api/artifacts/create`
- Just needs UI button

**Where to Add**:
```jsx
// In current checkpoint section:
<div className="checkpoint-actions">
  <Button
    variant="ghost"
    size="sm"
    icon={saved ? "mdi:check" : "mdi:content-save"}
    loading={saving}
    onClick={handleSaveCurrentCheckpoint}
  >
    {saved ? 'Saved' : 'Save as Artifact'}
  </Button>
</div>
```

**Handler**:
```javascript
const handleSaveCurrentCheckpoint = async () => {
  // Extract HTML from checkpoint ui_spec
  const htmlSection = checkpoint.ui_spec.sections?.find(s => s.type === 'html');
  const htmlContent = buildArtifactHTML(htmlSection?.content || checkpoint.phase_output);

  await fetch('/api/artifacts/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      cascade_id: checkpoint.cascade_id,
      cell_name: checkpoint.cell_name,
      title: checkpoint.summary || checkpoint.phase_output?.substring(0, 50),
      artifact_type: 'decision',
      html_content: htmlContent,
      tags: ['checkpoint', checkpoint.checkpoint_type]
    })
  });

  showToast('success', 'Saved to artifacts');
  setSaved(true);
};
```

**Utility Function** (extract from ResearchCockpit):
```javascript
// src/utils/artifactBuilder.js
export function buildArtifactHTML(bodyHTML) {
  const baseCSS = `/* AppShell theme CSS */`;
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>${baseCSS}</style>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head>
<body>${bodyHTML}</body>
</html>`;
}
```

---

## Critical Gotchas & Lessons Learned

### 1. Cross-Process Cache Staleness (CRITICAL!)

**Problem**: Backend server (Flask) and cascade process (CLI) are **separate Python processes** with separate CheckpointManager singletons.

**Symptom**: User submits checkpoint → marked "responded" in DB → but cascade still waiting/times out

**Root Cause**:
- Backend updates its cache → database ✅
- Cascade polls its stale cache → never sees update ❌

**Solution Applied** (`rvbbit/checkpoints.py:537-546`):
```python
# In wait_for_response() polling loop:
if self.use_db:
    checkpoint = self._load_checkpoint(checkpoint_id)  # Force DB reload
    if checkpoint:
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint  # Update local cache
else:
    checkpoint = self.get_checkpoint(checkpoint_id)  # Cache only
```

**Verification**: Cascade resumes within 0.5 seconds of submit ✅

**For ExploreView**: This fix is already in place. Checkpoint responses will work automatically.

### 2. Infinite Render Loops with Polling

**Problem**: Polling hook updates state → triggers re-render → useEffect runs → new poll → updates state → loop!

**Solution**: Use **refs for cursor and seen IDs**:
```javascript
const cursorRef = useRef('1970-01-01 00:00:00');  // NOT STATE!
const seenIdsRef = useRef(new Set());              // NOT STATE!

// In poll function:
cursorRef.current = data.cursor;  // Update ref, not state
seenIdsRef.current.add(row.message_id);  // Add to ref
```

**For ExploreView**: Follow Studio's pattern exactly - refs for cursors, state for UI data only

### 3. SSE Reconnection Loops

**Problem** (OLD SYSTEM): Adding state to SSE useEffect dependencies causes constant reconnect

**Solution** (NEW SYSTEM): **Don't use SSE!** Use polling instead.

**For ExploreView**: No SSE at all. Pure polling. No event bus. No reconnection logic.

### 4. HTMX Template Variables in Nested Contexts

**Problem**: Template literals inside template literals break JavaScript

**Bad**:
```javascript
const html = `<script>
  const url = \`http://localhost:5001/api/checkpoints/${checkpointId}/respond\`;
</script>`;
// ❌ Syntax error - nested backticks
```

**Good**:
```javascript
const html = `<script>
  const url = 'http://localhost:5001/api/checkpoints/' + checkpointId + '/respond';
</script>`;
// ✅ String concatenation
```

**For ExploreView**: Already fixed in HTMLSection.js. CheckpointRenderer handles this.

### 5. Framer Motion Performance

**Problem**: AnimatePresence with large lists can lag

**Solution**:
- Limit ghost messages to 10 max
- Use `layout={false}` if layout animations cause jank
- Stagger animations for multiple items

**Example**:
```jsx
<AnimatePresence>
  {ghostMessages.map((ghost, idx) => (
    <motion.div
      key={ghost.id}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 0.85, x: 0 }}
      exit={{ opacity: 0, x: -100 }}
      transition={{
        duration: 0.3,
        delay: idx * 0.05  // Stagger by 50ms
      }}
    >
      <GhostMessage ghost={ghost} />
    </motion.div>
  ))}
</AnimatePresence>
```

**For ExploreView**: Keep ghost count ≤ 10, use stagger for smoothness

### 6. React State Updates During Render

**Problem**: Can't call setState during render phase

**Symptom**: "Cannot update a component while rendering a different component" warning

**Solution**: Use useEffect for derived state:
```javascript
// BAD
const ghostsToRemove = ghosts.filter(g => g.age > 30000);
setGhosts(prev => prev.filter(g => !ghostsToRemove.includes(g)));  // ❌ During render!

// GOOD
useEffect(() => {
  const interval = setInterval(() => {
    setGhosts(prev => prev.filter(g => Date.now() - g.createdAt < 30000));
  }, 1000);
  return () => clearInterval(interval);
}, []);
```

**For ExploreView**: All ghost cleanup in useEffect intervals, not during render

### 7. Checkpoint Response Handler Must Match API Exactly

**API Expects**:
```json
{
  "response": {...}  // ← Nested under "response" key!
}
```

**Bad**:
```javascript
body: JSON.stringify(response)  // ❌ Missing wrapper
```

**Good**:
```javascript
body: JSON.stringify({ response })  // ✅ Correct format
```

**For ExploreView**: Already correct in CheckpointRenderer. Just call `onSubmit(response)`.

### 8. LiveOrchestrationSidebar Prop Requirements

**Current Props** (from ResearchCockpit):
```javascript
<LiveOrchestrationSidebar
  sessionId={sessionId}
  cascadeId={cascadeId}
  orchestrationState={orchestrationState}
  sessionData={sessionData}      // Needs: {total_cost, ...}
  roundEvents={roundEvents}       // Array of {type, tool, timestamp}
  narrationAmplitude={0}          // 0-1 range (0 for no narration)
  onEnd={handleEndCascade}
/>
```

**If Using SimpleSidebar Instead**:
```javascript
<SimpleSidebar
  sessionId={sessionId}
  cascadeId={cascadeId}
  orchestrationState={orchestrationState}
  totalCost={totalCost}
  sessionStatus={sessionStatus}
  onEnd={handleEndCascade}
/>
```

**For ExploreView**: Decision point - use existing (548 lines, complex) or create simple (100 lines, clean)?

**Recommendation**: Start with SimpleSidebar, upgrade to LiveOrchestrationSidebar in Iteration 2

---

## Testing Plan

### Unit Tests

**1. GhostMessage Component**:
```javascript
// Test: Renders tool_call type
<GhostMessage ghost={{
  id: '123',
  type: 'tool_call',
  tool: 'web_search',
  content: '{"query": "test"}',
  timestamp: new Date().toISOString()
}} />

// Verify: Icon, title, timestamp, parsed args
```

**2. useExplorePolling Hook**:
```javascript
// Test: Polling starts and stops
const { logs, ghostMessages } = useExplorePolling('test_session');

// Mock API response
// Verify: Logs appended, ghosts derived, no duplicates
```

**3. SimpleSidebar Component**:
```javascript
// Test: Renders with mock state
<SimpleSidebar
  sessionId="test"
  cascadeId="my_cascade"
  orchestrationState={{ status: 'thinking', totalCost: 0.005 }}
  totalCost={0.005}
  sessionStatus="running"
/>

// Verify: Cost display, status badge, END button visible
```

### Integration Tests

**Test 1: Full Cascade Loop**
```bash
# Start cascade
cd /home/ryanr/repos/rvbbit
rvbbit run examples/htmx_demo.yaml --input '{"task": "Climate tech"}' --session explore_test_001
```

**Expected Flow**:
1. Navigate to `http://localhost:3000/#/explore?session=explore_test_001`
2. See empty state → "Cascade Active"
3. Ghost messages appear (tool calls)
4. Checkpoint appears (LLM's report + buttons)
5. Submit response
6. Checkpoint disappears
7. Ghost messages for next phase
8. Cascade completes
9. Empty state → "Cascade Complete"

**Test 2: Start New Cascade from Picker**
1. Navigate to `http://localhost:3000/#/explore`
2. CascadePicker modal opens
3. Select cascade (e.g., `examples/tool_based_decisions.yaml`)
4. Enter inputs: `{"task": "Test feature"}`
5. Click "Run"
6. Navigate to new session
7. Watch cascade execute

**Test 3: Cancel Running Cascade**
1. Start cascade as above
2. Click "END" button in sidebar
3. Confirm dialog
4. Cascade stops
5. Empty state → "Cascade Complete" (or Cancelled)

**Test 4: Modal Rendering (Checkpoint Portability)**
1. Navigate to ExploreView with pending checkpoint
2. Open browser console
3. Run: `document.querySelector('.current-checkpoint')` → verify element exists
4. Checkpoint should be interactable (not in modal, just inline)

**Test 5: Ghost Message Lifecycle**
1. Watch ghost messages appear as tools are called
2. Wait 30 seconds
3. Verify oldest ghost slides out and disappears
4. Verify new ghosts continue to appear

---

## Success Criteria

**ExploreView Iteration 1 is COMPLETE when**:

### Functional Requirements ✅
1. ✅ User can navigate to `/#/explore?session=xyz`
2. ✅ Ghost messages appear as cascade executes
3. ✅ Current checkpoint renders inline when LLM calls request_decision
4. ✅ User can respond to checkpoint inline (text, buttons, forms all work)
5. ✅ Cascade continues within 0.5s of response
6. ✅ Ghosts auto-disappear after 30s
7. ✅ Empty state shows appropriate message (idle/running/complete)
8. ✅ Can start new cascade via picker
9. ✅ Can end running cascade via sidebar button

### Technical Requirements ✅
10. ✅ No SSE - pure polling at 750ms
11. ✅ Framer Motion animations (ghosts, checkpoints)
12. ✅ AppShell theme (pure black, cyan, data-dense)
13. ✅ < 500 lines in main component
14. ✅ Extension points commented for Iteration 2+
15. ✅ No console errors or warnings
16. ✅ Responsive (works down to 1024px width)

### Code Quality ✅
17. ✅ Components extracted and reusable
18. ✅ Props documented with JSDoc or inline comments
19. ✅ CSS variables used (not hardcoded colors)
20. ✅ Cleanup on unmount (intervals, timeouts, refs)

---

## File Checklist

### To Create

- [ ] `src/views/explore/hooks/useExplorePolling.js` (~200 lines)
- [ ] `src/views/explore/components/SimpleSidebar.jsx` (~100 lines)
- [ ] `src/views/explore/components/SimpleSidebar.css` (~80 lines)
- [ ] `src/views/explore/ExploreView.jsx` (~250 lines)
- [ ] `src/views/explore/ExploreView.css` (~150 lines)
- [ ] `src/utils/artifactBuilder.js` (optional, ~50 lines)

### Already Created ✅
- [x] `src/components/GhostMessage.jsx` (~120 lines)
- [x] `src/components/GhostMessage.css` (~100 lines)
- [x] `src/components/CheckpointRenderer.jsx` (~100 lines)
- [x] `src/components/CheckpointModal.jsx` (~100 lines)

### To Extract (Iteration 2)
- [ ] `src/components/ExpandableCheckpoint.jsx` (from ResearchCockpit lines 1511-1710)
- [ ] `src/components/ExpandableCheckpoint.css` (from ResearchCockpit.css)
- [ ] `src/components/CascadeContextHeader.jsx` (from ResearchCockpit lines 1716-1805)
- [ ] `src/components/CascadeContextHeader.css` (from ResearchCockpit.css)

### Existing (Keep As-Is)
- [x] `src/components/LiveOrchestrationSidebar.js` (548 lines)
- [x] `src/components/LiveOrchestrationSidebar.css` (822 lines)
- [x] `src/components/NarrationPlayer.js` (hook)
- [x] `src/components/NarrationCaption.js` + `.css`
- [x] `src/components/CascadePicker.js` + `.css`
- [x] `src/components/CompactResearchTree.js` + `.css`

---

## Quick Reference: Key APIs

### Session Data (Studio's Endpoint)

**GET** `/api/playground/session-stream/{sessionId}?after={cursor}`

**Returns**:
```json
{
  "rows": [
    {
      "message_id": "msg_abc123",
      "session_id": "test_session",
      "timestamp": "2025-12-26 10:30:15.123",
      "role": "assistant",
      "content": "...",
      "tool_name": "web_search",
      "phase_name": "research",
      "model": "anthropic/claude-sonnet-4.5",
      "cost": 0.001,
      "tokens_in": 100,
      "tokens_out": 50
    }
  ],
  "cursor": "2025-12-26 10:30:15.456",
  "session_status": "running",
  "total_cost": 0.005,
  "session_complete": false,
  "child_sessions": []
}
```

**Polling Strategy**:
- First call: `?after=1970-01-01 00:00:00` (get all)
- Subsequent: `?after={last_cursor}` (incremental)
- Update cursor ref after each successful poll

### Checkpoints

**GET** `/api/checkpoints?session_id={sessionId}`

**Returns**:
```json
{
  "checkpoints": [
    {
      "id": "cp_abc123",
      "session_id": "test_session",
      "cascade_id": "my_cascade",
      "cell_name": "approval_phase",
      "checkpoint_type": "decision",
      "status": "pending",
      "phase_output": "Question text",
      "ui_spec": {...},
      "created_at": "2025-12-26T10:30:00"
    }
  ],
  "count": 1
}
```

**With History**: `?session_id={sessionId}&include_all=true` (includes "responded")

### Checkpoint Response

**POST** `/api/checkpoints/{checkpoint_id}/respond`

**Request**:
```json
{
  "response": {
    "selected": "approve",
    "notes": "Looks good",
    "reasoning": "Data is accurate"
  }
}
```

**Response**:
```json
{
  "status": "responded",
  "message": "Response recorded. Cascade will continue automatically."
}
```

### Run Cascade

**POST** `/api/run-cascade`

**Request**:
```json
{
  "cascade_file": "examples/htmx_demo.yaml",
  "inputs": {"task": "Research topic"}
}
```

**Response**:
```json
{
  "session_id": "new_session_123",
  "cascade_id": "htmx_checkpoint_demo"
}
```

### Cancel Cascade

**POST** `/api/cancel-cascade`

**Request**:
```json
{
  "session_id": "test_session"
}
```

---

## Code Snippets Library

### Ghost Message Derivation (from logs)

```javascript
function deriveGhostMessages(newLogs) {
  const newGhosts = [];

  for (const log of newLogs) {
    // Tool calls (assistant role with tool_name)
    if (log.tool_name && log.role === 'assistant') {
      newGhosts.push({
        id: log.message_id,
        type: 'tool_call',
        tool: log.tool_name,
        content: log.content,
        timestamp: log.timestamp,
        createdAt: Date.now()
      });
    }

    // Tool results (tool role)
    if (log.role === 'tool') {
      newGhosts.push({
        id: log.message_id,
        type: 'tool_result',
        tool: log.tool_name,
        result: log.content,
        timestamp: log.timestamp,
        createdAt: Date.now()
      });
    }

    // Thinking messages (assistant role, no tool)
    if (log.role === 'assistant' && !log.tool_name && log.content?.length > 50) {
      newGhosts.push({
        id: log.message_id,
        type: 'thinking',
        content: log.content,
        timestamp: log.timestamp,
        createdAt: Date.now()
      });
    }
  }

  return newGhosts;
}
```

### Orchestration State Derivation

```javascript
function deriveOrchestrationState(logs, checkpoint) {
  // Find latest phase
  const phaseStart = logs.reverse().find(log =>
    log.event_type === 'phase_start' || log.phase_name
  );

  // Determine status
  let status = 'idle';
  if (checkpoint) {
    status = 'waiting_human';
  } else {
    const recentLogs = logs.slice(-5);
    if (recentLogs.some(l => l.role === 'tool')) status = 'tool_running';
    else if (recentLogs.some(l => l.role === 'assistant')) status = 'thinking';
  }

  return {
    currentPhase: phaseStart?.phase_name,
    currentModel: phaseStart?.model,
    status: status,
    // Can add more fields as needed
  };
}
```

### Ghost Auto-Cleanup Pattern

```javascript
// When adding new ghosts:
setGhostMessages(prev => {
  const combined = [...prev, ...newGhosts];
  return combined.slice(-GHOST_MAX_COUNT);  // Keep last 10
});

// Setup removal timers:
newGhosts.forEach(ghost => {
  const timeoutId = setTimeout(() => {
    setGhostMessages(prev => prev.filter(g => g.id !== ghost.id));
  }, GHOST_TIMEOUT);

  // Store timeout ID for cleanup
  ghostTimeoutsRef.current.set(ghost.id, timeoutId);
});

// On unmount, clear all timeouts:
useEffect(() => {
  return () => {
    ghostTimeoutsRef.current.forEach(id => clearTimeout(id));
    ghostTimeoutsRef.current.clear();
  };
}, []);
```

---

## Implementation Checklist

### Pre-Implementation (Complete)
- [x] Analyze ResearchCockpit thoroughly
- [x] Design architecture (polling-based)
- [x] Extract GhostMessage component
- [x] Create CheckpointRenderer (universal)
- [x] Fix cross-process cache bug
- [x] Test checkpoint submission end-to-end
- [x] Document plan

### Phase 1: Infrastructure
- [ ] Create `useExplorePolling` hook
- [ ] Create `SimpleSidebar` component
- [ ] Test components in isolation

### Phase 2: Build View
- [ ] Create `ExploreView.jsx` skeleton
- [ ] Create `ExploreView.css`
- [ ] Wire up polling hook
- [ ] Add Framer Motion animations
- [ ] Add CascadePicker integration

### Phase 3: Integration
- [ ] Test with live cascade
- [ ] Fix any issues
- [ ] Verify all success criteria
- [ ] Document usage

### Future Iterations
- [ ] Extract ExpandableCheckpoint
- [ ] Extract CascadeContextHeader
- [ ] Add checkpoint timeline
- [ ] Add branching support
- [ ] Add narration playback
- [ ] Upgrade to full LiveOrchestrationSidebar
- [ ] Add research tree
- [ ] Add previous sessions browser

---

## Notes for Implementation

### Start Here

1. **Create the polling hook first** - This is the foundation
2. **Test it in isolation** - Console.log all return values
3. **Then build UI** - Layout is simple once data flow works
4. **Add animations last** - Get functionality working first

### When You Get Stuck

**Check These Files**:
- `studio/hooks/useTimelinePolling.js` - Polling pattern reference
- `studio/hooks/useRunningSessions.js` - Simple polling example
- `components/ResearchCockpit.js` - Original (what we're replacing)
- `views/interrupts/InterruptsView.jsx` - CheckpointRenderer usage example

**Common Issues**:
- Infinite loops → Check refs vs state
- Checkpoints not updating → Verify polling interval setup
- Ghosts not disappearing → Check timeout cleanup in useEffect
- Animations janky → Reduce ghost count or disable layout animations

### Key Principles

1. **Refs for cursors/caches** - Never put in state
2. **State for UI data only** - logs, ghosts, checkpoint, orchestrationState
3. **Cleanup everything** - intervals, timeouts, refs on unmount
4. **Framer Motion at parent** - Wrap GhostMessage, not inside it
5. **Extension points via comments** - Mark where features go

---

## Final Notes

This plan represents a **complete rewrite** of ResearchCockpit using modern patterns:

**Old System** (ResearchCockpit):
- 2,064 lines React + 1,009 lines CSS = **3,073 lines**
- SSE event bus with reconnection complexity
- Inline components (hard to reuse)
- Ad-hoc patterns (pre-AppShell)

**New System** (ExploreView MVP):
- ~750 lines total = **75% reduction**
- Pure polling (no SSE)
- Extracted reusable components
- AppShell design system
- Framer Motion animations
- Extension points for all deferred features

**With Iteration 2+**:
- ~1,200 lines total (timeline, branching, narration)
- Still **60% smaller** than original
- Fully modular and maintainable

The plan is **ready for execution**. Start with the polling hook, then build up from there. Good luck! 🚀
