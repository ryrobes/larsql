# Execution Flow Visualization Plan

## Overview
Extend CascadeFlowModal to show real execution data (running & completed cascades), accessible from the Instances page.

## Current State
- CascadeFlowModal already has `executionData` prop structure but it's unused
- PhaseNode has execution state rendering (status, cost, duration, isOnPath, etc.)
- PhaseInnerDiagram has execution data for soundings winners, ward results
- ClickHouse unified_logs has all the data we need

## Data Structure Needed

```javascript
executionData = {
  // Execution path
  executedPath: ['phase1', 'phase2', 'phase3'],
  executedHandoffs: { 'phase1': 'phase2', 'phase2': 'phase3' },

  // Per-phase execution data
  phases: {
    'phase_name': {
      status: 'completed' | 'running' | 'error' | 'pending',
      cost: 0.0012,
      duration: 2.5,           // seconds
      turnCount: 3,
      soundingWinner: 2,       // index of winning sounding
      details: {
        soundings: {
          winnerIndex: 2,
          attempts: [
            { status: 'completed', preview: 'First 50 chars...', cost: 0.0004 },
            { status: 'completed', preview: 'First 50 chars...', cost: 0.0003 },
            { status: 'completed', preview: 'First 50 chars...', cost: 0.0005 }
          ]
        },
        reforge: {
          reforgeSteps: [
            { winnerIndex: 0 },
            { winnerIndex: 1 }
          ]
        },
        wards: {
          'pre_0': { valid: true, reason: 'passed' },
          'post_0': { valid: false, reason: 'Length check failed' }
        }
      }
    }
  },

  // Summary
  summary: {
    phaseCount: 3,
    totalCost: 0.0045,
    totalDuration: 8.2,
    status: 'completed' | 'running' | 'error'
  }
}
```

## Implementation Steps

### Phase 1: Backend API (app.py)

**New endpoint: `/api/session/:session_id/execution-flow`**

```python
@app.route('/api/session/<session_id>/execution-flow', methods=['GET'])
def get_session_execution_flow(session_id):
    """
    Get execution data for flow visualization.
    Returns structured data for CascadeFlowModal overlay.
    """
```

**Query unified_logs for:**
1. All records for session_id ordered by timestamp
2. Group by phase_name to get per-phase metrics
3. Extract sounding data from trace_id patterns and sounding_index
4. Get winning_sounding_index for each phase
5. Calculate costs and durations
6. Determine execution path from phase order

**Key columns to query:**
- `phase_name` - Which phase
- `node_type` - Type of event (message, phase_start, phase_complete, etc.)
- `sounding_index` - Which sounding attempt (0, 1, 2...)
- `is_winner` - If this was the winning sounding
- `winning_sounding_index` - Index of the winner
- `reforge_step` - Which reforge iteration
- `cost`, `duration_ms` - Performance metrics
- `content_json` - For generating previews

### Phase 2: Frontend - Instance Flow Button

**Update InstanceGridView.js:**
1. Add `onVisualize` prop
2. Add Flow button to ActionsRenderer (before soundings button)
3. Pass session_id and cascade_id to handler

```javascript
<button
  className="action-btn flow"
  onClick={(e) => {
    e.stopPropagation();
    onVisualize && onVisualize(instance.session_id, instance.cascade_id);
  }}
  title="View execution flow"
>
  <Icon icon="ph:tree-structure" width="14" />
</button>
```

**Update InstancesView.js:**
1. Add state for flow modal: `flowModalSession`, `flowModalData`
2. Add handler to fetch execution data and open modal
3. Render CascadeFlowModal when flowModalSession is set

### Phase 3: Fetch Execution Data

**Create helper function or hook:**

```javascript
async function fetchExecutionFlow(sessionId, cascadeId) {
  // Fetch cascade spec (already have this)
  const cascadeResponse = await fetch(`/api/cascade-definitions`);
  const cascades = await cascadeResponse.json();
  const cascade = cascades.find(c => c.cascade_id === cascadeId);

  // Fetch execution data
  const execResponse = await fetch(`/api/session/${sessionId}/execution-flow`);
  const executionData = await execResponse.json();

  return { cascade, executionData };
}
```

### Phase 4: Real-time Updates (for running cascades)

**Connect to SSE when modal is open for running session:**

```javascript
useEffect(() => {
  if (!isRunning || !sessionId) return;

  const eventSource = new EventSource('/api/events/stream');

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.session_id === sessionId) {
      // Update executionData based on event type
      if (data.type === 'phase_complete') {
        updatePhaseStatus(data.phase_name, 'completed', data);
      } else if (data.type === 'phase_start') {
        updatePhaseStatus(data.phase_name, 'running', data);
      }
      // etc.
    }
  };

  return () => eventSource.close();
}, [sessionId, isRunning]);
```

### Phase 5: Enhanced Visualization

**Update CascadeFlowModal for execution view:**
1. Show running phase with pulse animation (already supported)
2. Highlight executed path with green edges (already supported)
3. Show costs accumulating in real-time
4. Show current phase progress

**Update PhaseInnerDiagram for execution data:**
1. Show which sounding won (green highlight)
2. Show ward pass/fail status
3. Show reforge step winners

## File Changes Summary

| File | Changes |
|------|---------|
| `backend/app.py` | Add `/api/session/:id/execution-flow` endpoint |
| `InstanceGridView.js` | Add Flow button, `onVisualize` prop |
| `InstancesView.js` | Add modal state, fetch handler, render modal |
| `CascadeFlowModal.js` | Verify execution data rendering works |
| `CascadeFlowModal.css` | Add Flow button styles |

## Testing Cascades

Use these cascades to test the feature:
- Simple cascade without soundings (basic execution path)
- Cascade with soundings (show winner selection)
- Cascade with reforge (show refinement steps)
- Running cascade (test real-time updates)
- Failed cascade (test error state rendering)

## Query Example

```sql
SELECT
  phase_name,
  node_type,
  sounding_index,
  is_winner,
  winning_sounding_index,
  reforge_step,
  cost,
  duration_ms,
  SUBSTRING(content_json, 1, 100) as content_preview,
  timestamp
FROM unified_logs
WHERE session_id = ?
ORDER BY timestamp ASC
```
