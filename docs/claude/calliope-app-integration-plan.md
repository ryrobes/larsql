# Calliope + App API Integration Plan

## Executive Summary

Rework Calliope's preview panel to use the App API (`/apps/{cascade_id}/`) instead of the current manual checkpoint polling and custom rendering approach. This eliminates the "semi-hack" of parsing Python repr from logs and provides a native, styled app experience.

---

## Current State Analysis

### The "Semi-Hack" Problem

**Current Calliope Implementation** (CalliopeView.jsx):

1. **Python Repr Parsing** (lines 172-427):
   - `cascade_write` returns a Python dict
   - Tool wrapper stringifies it as: `Tool Result (cascade_write):\n{str(result)}`
   - Frontend uses regex to extract and convert Python repr to JSON
   - Fragile: `/'cascade_id':\s*'([^']+)'/` patterns for nested structures

2. **Custom Spawned Cascade Rendering** (lines 1094-1209):
   - Polls `/api/checkpoints?session_id=spawnedSessionId`
   - Renders checkpoints via `CheckpointRenderer` component
   - Tracks cell status by parsing spawned session logs
   - Auto-sends feedback to Calliope when complete

3. **Graph Visualization** (lines 367-400):
   - Extracts graph nodes/edges from parsed cascade_write results
   - Builds `builtCells` array from either `result.graph.nodes` or `result.cells`
   - Renders via `CascadeSpecGraph` component

### New App API Capabilities

**Apps API** (apps_api.py):

- **URL Structure**: `/apps/{cascade_id}/{session_id}/{cell}`
- **Features**:
  - Automatic input forms from `inputs_schema`
  - Basecoat styling with Tailwind CSS
  - HTMX polling for real-time updates
  - Checkpoint integration via `get_pending_checkpoint()`
  - State persistence via `AppSession`
  - Jinja2 template helpers (`submit_button`, `tabs`, etc.)

**Key Advantage**: Any cascade with `hitl:` cells automatically becomes an app.

---

## Integration Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      CalliopeView                               │
├────────────────────┬────────────────────────────────────────────┤
│                    │                                            │
│   Chat Panel       │            Preview Panel                   │
│   (unchanged)      │  ┌──────────────────────────────────────┐  │
│                    │  │       Graph (CascadeSpecGraph)       │  │
│  - Calliope msgs   │  │           (from cascade_write)       │  │
│  - request_decision│  └──────────────────────────────────────┘  │
│  - Tool activity   │  ┌──────────────────────────────────────┐  │
│                    │  │       Live App Preview               │  │
│                    │  │   ┌──────────────────────────────┐   │  │
│                    │  │   │                              │   │  │
│                    │  │   │  <iframe src="/apps/...">    │   │  │
│                    │  │   │                              │   │  │
│                    │  │   └──────────────────────────────┘   │  │
│                    │  │   (Native App API rendering)         │  │
│                    │  └──────────────────────────────────────┘  │
└────────────────────┴────────────────────────────────────────────┘
```

### Key Changes

#### 1. Replace Custom Checkpoint Rendering with App Iframe

**Before** (current):
```jsx
// Poll for spawned checkpoint
useEffect(() => {
  const pollSpawnedSession = async () => {
    const cpRes = await fetch(`http://localhost:5050/api/checkpoints?session_id=${spawnedSessionId}`);
    // ... manual checkpoint handling
  };
  const interval = setInterval(pollSpawnedSession, 1000);
}, [spawnedSessionId]);

// Render checkpoint manually
<CheckpointRenderer
  checkpoint={spawnedCheckpoint}
  onSubmit={handleSpawnedResponse}
  variant="inline"
/>
```

**After** (proposed):
```jsx
// Simply embed the App API URL
<iframe
  src={`http://localhost:5050/apps/${builtCascade.cascade_id}/${spawnedSessionId}/`}
  className="spawned-app-iframe"
  title={`${builtCascade.cascade_id} Preview`}
/>
```

**Benefits**:
- No manual checkpoint polling in Calliope
- App API handles all state management, routing, styling
- Native Basecoat/Tailwind styling
- HTMX integration works out of the box

#### 2. Improve cascade_write Tool Output

The Python repr parsing can be simplified by having `cascade_write` return cleaner output:

**Option A: JSON-serializable return** (backend change):
```python
# cascade_builder.py
def cascade_write(...):
    # ... existing logic ...
    return json.dumps({
        "cascade_id": cascade_id,
        "path": str(cascade_path),
        "cells": cells_summary,
        "graph": graph_data,
        # ...
    })
```

**Option B: Structured result with content-type** (runner change):
```python
# Return dict with __json__ marker for proper serialization
return {
    "__json__": True,
    "cascade_id": cascade_id,
    # ...
}
```

**Option C: Keep parsing but simplify** (minimal change):
- Keep current format but add JSON fallback in frontend
- cascade_write can optionally return both formats

#### 3. State Synchronization

For Calliope to know the spawned app's progress:

**Option A: Backend Events** (cleanest):
- Add SSE endpoint for cross-session events
- Spawned app posts events that Calliope session receives
- Example: `POST /api/sessions/{calliopeSession}/events`

**Option B: Polling Session Status** (simpler):
```jsx
// Poll spawned session status (already partly implemented)
useEffect(() => {
  const checkStatus = async () => {
    const res = await fetch(`http://localhost:5050/api/playground/session-stream/${spawnedSessionId}?after=1970-01-01`);
    const data = await res.json();
    if (data.session_status === 'completed' || data.session_status === 'error') {
      // Send feedback to Calliope
      handleAutoFeedback(data);
    }
  };
  const interval = setInterval(checkStatus, 2000);
}, [spawnedSessionId]);
```

**Option C: iframe postMessage** (elegant):
- App API injects postMessage on session complete
- Calliope listens for messages from iframe
```javascript
// In App API HTML template
<script>
  window.parent.postMessage({
    type: 'rvbbit_app_complete',
    session_id: '{{ session_id }}',
    status: '{{ status }}'
  }, '*');
</script>

// In CalliopeView
window.addEventListener('message', (event) => {
  if (event.data?.type === 'rvbbit_app_complete') {
    handleAutoFeedback(event.data);
  }
});
```

---

## Implementation Plan

### Phase 1: App Iframe Integration (Core Change)

**Files to Modify**:

1. **CalliopeView.jsx**:
   - Replace spawned checkpoint panel with iframe
   - Remove `spawnedCheckpoint` polling logic
   - Keep session status polling for feedback
   - Add postMessage listener for iframe events

2. **CalliopeView.css**:
   - Add iframe styling (full height, no border)
   - Handle loading/error states

**Approximate Changes**:
- Remove: ~150 lines (checkpoint polling, rendering)
- Add: ~50 lines (iframe, postMessage handling)

### Phase 2: Backend Enhancements

**Files to Modify**:

1. **apps_api.py**:
   - Add postMessage script to `APP_SHELL_TEMPLATE`
   - Post events: `session_start`, `cell_transition`, `session_complete`, `session_error`
   - Include cell name and state in messages

2. **cascade_builder.py** (optional):
   - Return JSON-serializable output
   - Or keep current format with better structure

### Phase 3: Enhanced Preview Features

**New Features**:

1. **App Control Bar**:
   - Restart button (create new session)
   - Full-screen mode
   - Open in new tab link
   - Current cell indicator

2. **Graph-App Synchronization**:
   - Highlight current cell in graph based on iframe messages
   - Show execution path

3. **Inputs Modal**:
   - If cascade has `inputs_schema`, show form before starting
   - Pre-fill from Calliope conversation context

---

## Detailed Implementation

### Step 1: Create App Preview Component

**New File**: `studio/frontend/src/components/AppPreview.jsx`

```jsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './AppPreview.css';

const AppPreview = ({
  cascadeId,
  sessionId,
  onSessionComplete,
  onCellChange,
  onError,
}) => {
  const iframeRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [currentCell, setCurrentCell] = useState(null);

  // Listen for postMessage from iframe
  useEffect(() => {
    const handleMessage = (event) => {
      if (!event.data?.type?.startsWith('rvbbit_')) return;

      switch (event.data.type) {
        case 'rvbbit_cell_change':
          setCurrentCell(event.data.cell_name);
          onCellChange?.(event.data.cell_name);
          break;
        case 'rvbbit_session_complete':
          onSessionComplete?.(event.data);
          break;
        case 'rvbbit_session_error':
          onError?.(event.data);
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [onSessionComplete, onCellChange, onError]);

  const appUrl = `http://localhost:5050/apps/${cascadeId}/${sessionId}/`;

  return (
    <div className="app-preview">
      <div className="app-preview-header">
        <Icon icon="mdi:play-circle" width="16" />
        <span>Live Preview</span>
        {currentCell && (
          <span className="current-cell">{currentCell}</span>
        )}
        <div className="app-preview-actions">
          <a href={appUrl} target="_blank" rel="noopener noreferrer">
            <Icon icon="mdi:open-in-new" width="14" />
          </a>
        </div>
      </div>
      <div className="app-preview-content">
        {isLoading && (
          <div className="app-loading">
            <Icon icon="mdi:loading" className="spinning" width="24" />
            <span>Starting app...</span>
          </div>
        )}
        <iframe
          ref={iframeRef}
          src={appUrl}
          title={`${cascadeId} Preview`}
          onLoad={() => setIsLoading(false)}
          onError={() => onError?.({ message: 'Failed to load app' })}
        />
      </div>
    </div>
  );
};

export default AppPreview;
```

### Step 2: Update Apps API with postMessage

**apps_api.py** - Add to `APP_SHELL_TEMPLATE`:

```python
APP_SHELL_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <!-- ... existing head ... -->
    <script>
      // RVBBIT App Events - Communicate with parent window
      window.RVBBIT_APP = {
        sessionId: '{{ session_id }}',
        cascadeId: '{{ cascade_id }}',

        postEvent: function(type, data) {
          if (window.parent !== window) {
            window.parent.postMessage({
              type: 'rvbbit_' + type,
              session_id: this.sessionId,
              cascade_id: this.cascadeId,
              ...data
            }, '*');
          }
        },

        onCellChange: function(cellName) {
          this.postEvent('cell_change', { cell_name: cellName });
        },

        onComplete: function() {
          this.postEvent('session_complete', { status: 'completed' });
        },

        onError: function(error) {
          this.postEvent('session_error', { error: error });
        }
      };

      // Auto-post cell change on page load
      document.addEventListener('DOMContentLoaded', function() {
        RVBBIT_APP.onCellChange('{{ cell_name }}');
      });
    </script>
</head>
<!-- ... rest of template ... -->
'''
```

### Step 3: Update CalliopeView.jsx

**Key changes**:

```jsx
// Import new component
import AppPreview from '../../components/AppPreview';

// Replace spawned checkpoint panel (around line 1094-1209)
{spawnedSessionId && builtCascade && (
  <AppPreview
    cascadeId={builtCascade.cascade_id}
    sessionId={spawnedSessionId}
    onSessionComplete={(data) => {
      // Send feedback to Calliope
      if (calliopeCheckpoint) {
        handleCalliopeResponse({
          spawned_status: data.status,
          feedback: 'Test completed'
        });
      }
    }}
    onCellChange={(cellName) => {
      // Update graph highlighting
      setCellStatus(prev => ({
        ...prev,
        [cellName]: 'current'
      }));
    }}
    onError={(error) => {
      showToast(`App error: ${error.message}`, { type: 'error' });
    }}
  />
)}

// Remove:
// - spawnedCheckpoint state
// - spawnedCheckpointFromPolling
// - Complex checkpoint polling useEffect
// - CheckpointRenderer for spawned session
```

---

## Migration Checklist

### Phase 1 (Essential)
- [ ] Create `AppPreview.jsx` component
- [ ] Add postMessage script to `APP_SHELL_TEMPLATE`
- [ ] Update CalliopeView to use AppPreview
- [ ] Remove manual checkpoint polling for spawned sessions
- [ ] Test end-to-end: Calliope → cascade_write → spawn → preview

### Phase 2 (Enhancement)
- [ ] Add control bar to AppPreview (restart, fullscreen, open in tab)
- [ ] Graph cell highlighting from iframe events
- [ ] Handle `inputs_schema` modal before app start
- [ ] Improve loading/error states

### Phase 3 (Polish)
- [ ] Simplify cascade_write output format (optional)
- [ ] Add SSE events for real-time cell transitions
- [ ] Session persistence for preview (don't lose on refresh)
- [ ] Mobile responsive layout

---

## Testing Scenarios

1. **Basic Flow**:
   - Start Calliope, describe an app
   - Verify cascade_write creates file
   - Verify graph visualization updates
   - Spawn cascade, verify iframe loads
   - Interact with app, verify cell transitions
   - Complete app, verify feedback to Calliope

2. **Error Handling**:
   - Test with invalid YAML
   - Test with missing handoffs
   - Test with tool cell errors
   - Verify error propagation to Calliope

3. **State Persistence**:
   - Add expense in expense tracker
   - Navigate between screens
   - Verify state accumulates correctly
   - Test page refresh behavior

4. **Cross-Session Communication**:
   - Verify postMessage events fire correctly
   - Verify Calliope receives feedback
   - Test timeout scenarios

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| iframe security (CORS) | Low | Medium | Same origin, no CORS issues |
| postMessage reliability | Low | Medium | Fallback to status polling |
| App API stability | Low | High | Already production-tested with expense_tracker |
| State sync complexity | Medium | Medium | Keep polling fallback initially |
| Breaking existing flows | Medium | High | Feature flag for rollout |

---

## Timeline Estimate

- **Phase 1**: 4-6 hours (core iframe integration)
- **Phase 2**: 2-4 hours (enhancements)
- **Phase 3**: 2-4 hours (polish)

**Total**: 8-14 hours of development work

---

## Files to Modify Summary

| File | Changes |
|------|---------|
| `studio/frontend/src/components/AppPreview.jsx` | **NEW** - Iframe wrapper component |
| `studio/frontend/src/components/AppPreview.css` | **NEW** - Styling |
| `studio/frontend/src/views/calliope/CalliopeView.jsx` | Replace checkpoint panel with AppPreview |
| `studio/backend/apps_api.py` | Add postMessage events to template |
| `rvbbit/rvbbit/traits/cascade_builder.py` | (Optional) JSON output format |
