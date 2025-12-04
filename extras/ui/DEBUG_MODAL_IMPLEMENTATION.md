# Debug Modal Implementation

## Overview

Added a debug modal to the Windlass UI instances screen that displays ALL messages for a cascade execution in a linear, chat-like format grouped by phase.

## Features

### 1. Complete Message History
- Shows **all** entries from the session (user messages, agent responses, tool calls/results, system messages, cost updates)
- Linear timeline view (chronological order)
- Grouped visually by phase for easy navigation

### 2. Visual Grouping by Phase
- Each phase is a collapsible section with:
  - Phase name
  - Sounding index (if applicable)
  - Total cost for that phase
- Phase headers are sticky for easy scrolling

### 3. Entry Details
- **Icon** - Visual indicator for entry type (user, agent, tool, system, cost, etc.)
- **Type** - Node type (agent, tool_call, tool_result, user, system, cost_update, etc.)
- **Timestamp** - Time of entry
- **Cost** - Individual cost per entry (if applicable)
- **Content** - Full message body with special formatting for different types

### 4. Special Content Formatting

**Tool Calls:**
- Shows tool name prominently
- Displays arguments in formatted code block

**Tool Results:**
- Shows tool name + "result"
- Displays output in code block (truncated to 500 chars)

**Cost Updates:**
- Large cost amount display
- Token counts (input/output)

**Regular Messages:**
- Attempts to pretty-print JSON
- Falls back to raw string display

### 5. Footer Stats
- Total entry count
- Total phase count
- Total cost across entire session

## Usage

1. Navigate to instances view for any cascade
2. Click the **Debug** button (pink, bug icon) on any instance
3. Modal opens showing complete session data
4. Scroll through phases and messages
5. Click outside or X to close

## UI Design

**Color Scheme:**
- Matches Windlass dark mode theme
- Entry types color-coded:
  - User: Blue (#60a5fa)
  - Agent: Purple (#a78bfa)
  - Tools: Pink (#f472b6)
  - System: Gray (#666)
  - Phase events: Green (#34d399)
  - Errors: Red (#f87171)
  - Costs: Green (#34d399)

**Layout:**
- Full-screen modal (90% width, 85% height)
- Sticky phase headers
- Scrollable body
- Fixed header and footer

## Files Added

1. **`frontend/src/components/DebugModal.js`**
   - Main modal component
   - Fetches session data from `/api/session/:session_id`
   - Groups entries by phase
   - Renders different entry types with appropriate formatting

2. **`frontend/src/components/DebugModal.css`**
   - Complete styling for modal
   - Phase grouping styles
   - Entry row styles with type-based colors
   - Special content formatting (code blocks, tool displays)

## Files Modified

1. **`frontend/src/components/InstancesView.js`**
   - Added `debugSessionId` state
   - Added Debug button to instance metrics
   - Renders DebugModal when session selected

2. **`frontend/src/components/InstancesView.css`**
   - Added `.debug-button` styles (pink themed)

## API Endpoint Used

**`GET /api/session/:session_id`**
- Already existed in backend
- Returns all entries for a session from JSONL (preferred) or Parquet
- Response format:
  ```json
  {
    "session_id": "ui_run_abc123",
    "entries": [
      {
        "node_type": "agent",
        "content": "...",
        "phase_name": "generate",
        "timestamp": 1234567890,
        "cost": 0.0123,
        "sounding_index": 0,
        "is_winner": true,
        "metadata": {...}
      }
    ],
    "source": "jsonl"
  }
  ```

## Data Flow

```
User clicks "Debug" button
    ↓
DebugModal opens with session_id
    ↓
Fetches GET /api/session/{session_id}
    ↓
Backend reads JSONL file (or Parquet fallback)
    ↓
Returns all entries chronologically
    ↓
Frontend groups by phase_name
    ↓
Renders phase groups with entries
    ↓
User scrolls through complete message history
```

## Benefits for Debugging

1. **Complete visibility** - See every message, tool call, and cost update
2. **Phase context** - Understand flow through cascade phases
3. **Cost tracking** - See exactly where costs occurred
4. **Tool debugging** - See tool calls and results in detail
5. **Timeline view** - Chronological order shows execution flow
6. **Sounding debugging** - See sounding index for parallel attempts

## Future Enhancements

Possible improvements:
- [ ] Filter by node_type (show only tool calls, or only costs, etc.)
- [ ] Search/filter within messages
- [ ] Expand/collapse individual phases
- [ ] Copy individual messages to clipboard
- [ ] Export session data as JSON
- [ ] Diff view between two sessions
- [ ] Highlight winning sounding attempts
- [ ] Show request/response pairs linked together
