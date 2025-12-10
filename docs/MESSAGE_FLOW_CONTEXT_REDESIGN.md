# MessageFlow Context Visualization Redesign

## Problem Statement

In complex cascade executions with 400+ messages, debugging context is extremely difficult:
- **"Who saw what?"** - Which messages were in the LLM's context window for a given call?
- **"Who said what?"** - Tracing the origin and propagation of content through the system
- **"Why did it respond this way?"** - Understanding the exact context that influenced a response
- **"Where did context bloat?"** - Identifying unnecessary repetition or context accumulation

The current MessageFlow implementation shows `full_request.messages` but provides no **lineage tracking**, **cross-referencing**, or **visual context analysis**.

## Solution: Hash-Based Context Tracking

We now have two powerful fields in every logged message:

| Field | Description | Example |
|-------|-------------|---------|
| `content_hash` | 16-char SHA256 of `role:content` | `"a1b2c3d4e5f67890"` |
| `context_hashes` | Ordered array of hashes for all messages in `full_request.messages` | `["abc...", "def...", "ghi..."]` |

These enable:
1. **Direct lineage queries** - Find exact messages that were in any call's context
2. **Reverse lookups** - Find all messages that "saw" a particular message
3. **Context diffing** - See what changed between sequential LLM calls
4. **Matrix visualization** - Heatmap showing context composition across all messages

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MessageFlowView                               │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ Timeline     │  │ Context      │  │ Cross-Reference         │   │
│  │ View         │  │ Matrix       │  │ Panel                   │   │
│  │ (existing)   │  │ (new)        │  │ (new)                   │   │
│  └──────────────┘  └──────────────┘  └─────────────────────────┘   │
│         │                 │                    │                    │
│         └─────────────────┼────────────────────┘                    │
│                           │                                         │
│                   ┌───────▼───────┐                                 │
│                   │ Shared State  │                                 │
│                   │ - hoveredHash │                                 │
│                   │ - selectedMsg │                                 │
│                   │ - hashIndex   │                                 │
│                   └───────────────┘                                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Backend API     │
                    │ /message-flow/:id │
                    │ + hash fields     │
                    │ + context-matrix  │
                    └───────────────────┘
```

---

## Phase 1: Backend Foundation

### 1.1 Add Hash Fields to API Response

**File**: `dashboard/backend/message_flow_api.py`

Modify the SQL query (line ~129) to include hash fields:

```sql
SELECT
    ...,
    content_hash,
    context_hashes
FROM unified_logs
WHERE session_id = '{session_id}'
ORDER BY timestamp
```

Add to message dict construction (line ~208):

```python
msg = {
    ...existing fields...,
    'content_hash': row.content_hash,
    'context_hashes': row.context_hashes or [],  # Array from ClickHouse
}
```

### 1.2 Add Hash Index to Response

Build a lookup index for frontend use:

```python
# After building all messages
hash_index = {}
for i, msg in enumerate(messages):
    h = msg.get('content_hash')
    if h:
        if h not in hash_index:
            hash_index[h] = []
        hash_index[h].append({
            'index': i,
            'timestamp': msg['timestamp'],
            'role': msg['role'],
            'phase_name': msg['phase_name']
        })

# Add to response
return jsonify({
    ...existing response...,
    'hash_index': hash_index,  # Map of content_hash -> [message indices]
})
```

### 1.3 Add Context Matrix Endpoint

New endpoint for efficient matrix data:

```python
@message_flow_bp.route('/api/context-matrix/<session_id>', methods=['GET'])
def get_context_matrix(session_id):
    """
    Returns sparse matrix data for context visualization.

    Response:
    {
        "messages": [{"index": 0, "hash": "abc", "role": "system", ...}, ...],
        "unique_hashes": ["hash1", "hash2", ...],  # Y-axis
        "matrix": [
            {"msg_idx": 5, "context_idx": 0},  # Message 5 has hash at index 0
            {"msg_idx": 5, "context_idx": 1},
            ...
        ]
    }
    """
```

---

## Phase 2: Basic UI Integration

### 2.1 Display Content Hash on Message Cards

**File**: `dashboard/frontend/src/components/MessageFlowView.js`

Add a small hash badge to each message header:

```jsx
// In renderMessage function, add to message-header
{msg.content_hash && (
  <span
    className="content-hash-badge"
    title={`Hash: ${msg.content_hash}\nContext: ${msg.context_hashes?.length || 0} messages`}
    onClick={(e) => {
      e.stopPropagation();
      navigator.clipboard.writeText(msg.content_hash);
    }}
  >
    #{msg.content_hash.slice(0, 6)}
  </span>
)}
```

### 2.2 Hover Context Highlighting

Add state and handlers for context highlighting:

```jsx
const [hoveredContextHashes, setHoveredContextHashes] = useState(new Set());
const [highlightMode, setHighlightMode] = useState('ancestors'); // 'ancestors' | 'descendants' | 'both'

const handleMessageHover = (msg, isEntering) => {
  if (!isEntering) {
    setHoveredContextHashes(new Set());
    return;
  }

  if (highlightMode === 'ancestors' || highlightMode === 'both') {
    // Highlight messages that were in this message's context
    setHoveredContextHashes(new Set(msg.context_hashes || []));
  }

  if (highlightMode === 'descendants' || highlightMode === 'both') {
    // Highlight messages that had this message in their context
    const descendants = data.all_messages
      .filter(m => m.context_hashes?.includes(msg.content_hash))
      .map(m => m.content_hash);
    setHoveredContextHashes(prev => new Set([...prev, ...descendants]));
  }
};

// In message className
className={`message ${hoveredContextHashes.has(msg.content_hash) ? 'context-highlighted' : ''}`}
```

### 2.3 Context Highlight Toggle

Add UI control for highlight mode:

```jsx
<div className="context-highlight-controls">
  <span>Hover shows:</span>
  <button
    className={highlightMode === 'ancestors' ? 'active' : ''}
    onClick={() => setHighlightMode('ancestors')}
    title="Show messages that were in hovered message's context"
  >
    ← Ancestors
  </button>
  <button
    className={highlightMode === 'descendants' ? 'active' : ''}
    onClick={() => setHighlightMode('descendants')}
    title="Show messages that saw the hovered message"
  >
    Descendants →
  </button>
  <button
    className={highlightMode === 'both' ? 'active' : ''}
    onClick={() => setHighlightMode('both')}
  >
    Both ↔
  </button>
</div>
```

---

## Phase 3: Context Matrix View (The Heatmap)

### 3.1 Concept

```
                    Messages (chronological) →
                    M1  M2  M3  M4  M5  M6  M7  M8  M9  M10 ...
                   ─────────────────────────────────────────────
    Context      │  ■   ■   ■   ■   ■   ■   ■   ■   ■   ■  │ System prompt (always present)
    Hashes       │      ■   ■   ■   ■   ■                  │ User input 1
    (unique)     │          ■   ■   ■   ■   ■   ■          │ Assistant response 1
        ↓        │              ■   ■   ■   ■   ■   ■      │ Tool result 1
                 │                      ■   ■   ■   ■   ■  │ User input 2
                 │                          ■   ■   ■   ■  │ Assistant response 2
                 │                              ■          │ Tool call (transient)
                 │                                  ■   ■  │ User input 3
                   ─────────────────────────────────────────────

Legend:
■ = This content_hash was in this message's context_hashes
Vertical stripe = Message persists in context for many calls
Diagonal pattern = Normal context accumulation
Gap = Context was truncated/reset
```

### 3.2 Component Structure

**File**: `dashboard/frontend/src/components/ContextMatrixView.js`

```jsx
function ContextMatrixView({ data, onMessageSelect, onHashSelect }) {
  const canvasRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredCell, setHoveredCell] = useState(null);

  // Build matrix data
  const matrixData = useMemo(() => {
    const llmCalls = data.all_messages.filter(m => m.context_hashes?.length > 0);
    const uniqueHashes = [...new Set(
      llmCalls.flatMap(m => m.context_hashes)
    )];

    // Create hash -> first appearance index for sorting
    const hashFirstSeen = {};
    llmCalls.forEach((msg, msgIdx) => {
      msg.context_hashes?.forEach(h => {
        if (!(h in hashFirstSeen)) {
          hashFirstSeen[h] = msgIdx;
        }
      });
    });

    // Sort hashes by first appearance (oldest first at top)
    uniqueHashes.sort((a, b) => hashFirstSeen[a] - hashFirstSeen[b]);

    // Build sparse matrix
    const cells = [];
    llmCalls.forEach((msg, msgIdx) => {
      msg.context_hashes?.forEach(h => {
        const hashIdx = uniqueHashes.indexOf(h);
        cells.push({ msgIdx, hashIdx, hash: h });
      });
    });

    return { llmCalls, uniqueHashes, cells };
  }, [data]);

  // Render to canvas for performance
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const cellSize = 4 * zoom;

    // Clear
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw cells
    matrixData.cells.forEach(({ msgIdx, hashIdx, hash }) => {
      const x = msgIdx * cellSize + pan.x;
      const y = hashIdx * cellSize + pan.y;

      // Color by message role
      const msg = matrixData.llmCalls[msgIdx];
      ctx.fillStyle = getRoleColor(msg.role);
      ctx.fillRect(x, y, cellSize - 1, cellSize - 1);
    });

    // Highlight hovered row/column
    if (hoveredCell) {
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 2;
      // Highlight column (message)
      ctx.strokeRect(hoveredCell.msgIdx * cellSize + pan.x, 0, cellSize, canvas.height);
      // Highlight row (hash)
      ctx.strokeRect(0, hoveredCell.hashIdx * cellSize + pan.y, canvas.width, cellSize);
    }
  }, [matrixData, zoom, pan, hoveredCell]);

  return (
    <div className="context-matrix-container">
      <div className="matrix-controls">
        <button onClick={() => setZoom(z => Math.min(z * 1.5, 10))}>Zoom In</button>
        <button onClick={() => setZoom(z => Math.max(z / 1.5, 0.5))}>Zoom Out</button>
        <span>Messages: {matrixData.llmCalls.length}</span>
        <span>Unique contexts: {matrixData.uniqueHashes.length}</span>
      </div>

      <canvas
        ref={canvasRef}
        width={800}
        height={600}
        onMouseMove={handleMouseMove}
        onClick={handleClick}
      />

      {hoveredCell && (
        <div className="matrix-tooltip">
          <div>Message #{hoveredCell.msgIdx}: {matrixData.llmCalls[hoveredCell.msgIdx]?.role}</div>
          <div>Hash: {hoveredCell.hash?.slice(0, 8)}...</div>
        </div>
      )}
    </div>
  );
}
```

### 3.3 Matrix Interaction Features

1. **Hover**: Show tooltip with message details and hash info
2. **Click row**: Highlight all messages containing that hash in timeline
3. **Click column**: Scroll to that message in timeline view
4. **Click cell**: Show the specific message that contributed that context
5. **Brush select**: Select a region to filter timeline to those messages

### 3.4 Color Coding

```javascript
const getRoleColor = (role, nodeType) => {
  const colors = {
    'system': '#a78bfa',      // Purple - system prompts
    'user': '#60a5fa',        // Blue - user input
    'assistant': '#34d399',   // Green - assistant responses
    'tool': '#fbbf24',        // Yellow - tool results
  };
  return colors[role] || '#666666';
};
```

---

## Phase 4: Cross-Reference Panel

### 4.1 Component Design

**File**: `dashboard/frontend/src/components/ContextCrossRefPanel.js`

```jsx
function ContextCrossRefPanel({ selectedMessage, allMessages, hashIndex, onNavigate }) {
  if (!selectedMessage) {
    return <div className="cross-ref-panel empty">Select a message to see context relationships</div>;
  }

  // Find ancestors (messages in this message's context)
  const ancestors = (selectedMessage.context_hashes || [])
    .map(hash => ({
      hash,
      messages: hashIndex[hash] || []
    }))
    .filter(a => a.messages.length > 0);

  // Find descendants (messages that have this message in their context)
  const descendants = allMessages
    .filter(m => m.context_hashes?.includes(selectedMessage.content_hash))
    .map(m => ({
      index: allMessages.indexOf(m),
      hash: m.content_hash,
      role: m.role,
      phase: m.phase_name,
      timestamp: m.timestamp
    }));

  return (
    <div className="cross-ref-panel">
      <div className="selected-message-info">
        <h4>Selected Message</h4>
        <div className="hash-display">
          <Icon icon="mdi:fingerprint" />
          {selectedMessage.content_hash}
        </div>
        <div className="meta">
          {selectedMessage.role} | {selectedMessage.phase_name} | Turn {selectedMessage.turn_number}
        </div>
      </div>

      <div className="ancestors-section">
        <h4>
          <Icon icon="mdi:arrow-up-bold" />
          In Context ({ancestors.length} messages)
        </h4>
        <div className="context-list">
          {ancestors.map((a, i) => (
            <div
              key={i}
              className="context-item"
              onClick={() => onNavigate(a.messages[0]?.index)}
            >
              <span className="context-index">[{i}]</span>
              <span className="context-hash">#{a.hash.slice(0, 6)}</span>
              <span className="context-role">{a.messages[0]?.role}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="descendants-section">
        <h4>
          <Icon icon="mdi:arrow-down-bold" />
          Seen By ({descendants.length} messages)
        </h4>
        <div className="context-list">
          {descendants.map((d, i) => (
            <div
              key={i}
              className="context-item"
              onClick={() => onNavigate(d.index)}
            >
              <span className="context-index">M{d.index}</span>
              <span className="context-role">{d.role}</span>
              <span className="context-phase">{d.phase}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

---

## Phase 5: Full Request Linking

### 5.1 Enhanced Full Request Display

When showing `full_request.messages`, compute hashes and link to actual messages:

```jsx
// Utility function (can also be done backend-side)
const computeContentHash = (role, content) => {
  // Simple hash for frontend - or fetch pre-computed from backend
  const str = `${role}:${typeof content === 'string' ? content : JSON.stringify(content)}`;
  // Use a simple hash or lookup from hashIndex
  return hashIndex[str] || null;
};

// In the full_request rendering section
{msg.full_request.messages.map((llmMsg, i) => {
  // Find matching logged message by position in context_hashes
  const contextHash = msg.context_hashes?.[i];
  const linkedMessages = contextHash ? hashIndex[contextHash] : [];
  const linkedMessage = linkedMessages?.[0];

  return (
    <div
      key={i}
      className={`llm-message ${llmMsg.role} ${linkedMessage ? 'linked' : 'unlinked'}`}
      onClick={() => linkedMessage && scrollToMessage(linkedMessage.index)}
    >
      <div className="llm-message-header">
        <span className="llm-index">[{i}]</span>
        <span className="llm-role">{llmMsg.role}</span>
        {linkedMessage && (
          <span className="linked-badge" title="Click to navigate to source message">
            <Icon icon="mdi:link" /> M{linkedMessage.index}
          </span>
        )}
        {contextHash && (
          <span className="hash-badge">#{contextHash.slice(0, 6)}</span>
        )}
      </div>
      <div className="llm-message-content">
        {typeof llmMsg.content === 'string'
          ? llmMsg.content.slice(0, 500)
          : JSON.stringify(llmMsg.content).slice(0, 500)}
        {(llmMsg.content?.length || JSON.stringify(llmMsg.content).length) > 500 && '...'}
      </div>
    </div>
  );
})}
```

---

## Phase 6: Context Stats & Analytics

### 6.1 Stats Panel Component

```jsx
function ContextStatsPanel({ data }) {
  const stats = useMemo(() => {
    const llmCalls = data.all_messages.filter(m => m.context_hashes?.length > 0);
    const allHashes = llmCalls.flatMap(m => m.context_hashes || []);
    const uniqueHashes = new Set(allHashes);

    // Hash frequency (most referenced messages)
    const hashFreq = {};
    allHashes.forEach(h => { hashFreq[h] = (hashFreq[h] || 0) + 1; });
    const topHashes = Object.entries(hashFreq)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10);

    // Context size over time
    const contextSizes = llmCalls.map((m, i) => ({
      index: i,
      size: m.context_hashes?.length || 0,
      phase: m.phase_name
    }));

    const avgContextSize = contextSizes.reduce((s, c) => s + c.size, 0) / contextSizes.length;
    const maxContextSize = Math.max(...contextSizes.map(c => c.size));

    return {
      totalMessages: data.all_messages.length,
      llmCalls: llmCalls.length,
      uniqueContextMessages: uniqueHashes.size,
      avgContextSize: avgContextSize.toFixed(1),
      maxContextSize,
      topHashes,
      contextSizes
    };
  }, [data]);

  return (
    <div className="context-stats-panel">
      <div className="stats-grid">
        <div className="stat">
          <span className="stat-value">{stats.totalMessages}</span>
          <span className="stat-label">Total Messages</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.llmCalls}</span>
          <span className="stat-label">LLM Calls</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.uniqueContextMessages}</span>
          <span className="stat-label">Unique Context Items</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.avgContextSize}</span>
          <span className="stat-label">Avg Context Size</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.maxContextSize}</span>
          <span className="stat-label">Max Context Size</span>
        </div>
      </div>

      <div className="top-referenced">
        <h4>Most Referenced Messages</h4>
        {stats.topHashes.map(([hash, count], i) => {
          const msg = data.hash_index?.[hash]?.[0];
          return (
            <div key={hash} className="top-hash-item">
              <span className="rank">#{i + 1}</span>
              <span className="hash">#{hash.slice(0, 8)}</span>
              <span className="count">{count}x</span>
              <span className="role">{msg?.role}</span>
            </div>
          );
        })}
      </div>

      <div className="context-growth-chart">
        <h4>Context Size Over Time</h4>
        {/* Mini sparkline or chart showing context size growth */}
        <ContextGrowthChart data={stats.contextSizes} />
      </div>
    </div>
  );
}
```

---

## Implementation Order

### Sprint 1: Foundation (Backend + Basic UI)
- [ ] **1.1** Add `content_hash`, `context_hashes` to API query
- [ ] **1.2** Add `hash_index` map to API response
- [ ] **2.1** Display hash badge on message cards
- [ ] **2.2** Implement hover context highlighting
- [ ] **2.3** Add highlight mode toggle (ancestors/descendants/both)

### Sprint 2: Context Matrix
- [ ] **3.1** Create `ContextMatrixView` component
- [ ] **3.2** Canvas-based rendering for performance
- [ ] **3.3** Add zoom/pan controls
- [ ] **3.4** Implement cell hover tooltips
- [ ] **3.5** Add click-to-navigate from matrix to timeline

### Sprint 3: Cross-Reference & Linking
- [ ] **4.1** Create `ContextCrossRefPanel` component
- [ ] **4.2** Show ancestors (context messages) list
- [ ] **4.3** Show descendants (who saw this) list
- [ ] **5.1** Link `full_request.messages` to logged messages
- [ ] **5.2** Add navigation from full_request to source

### Sprint 4: Analytics & Polish
- [ ] **6.1** Create `ContextStatsPanel` component
- [ ] **6.2** Add context growth chart
- [ ] **6.3** Show most-referenced messages
- [ ] **6.4** Add keyboard shortcuts for navigation
- [ ] **6.5** Performance optimization for 400+ message sessions

---

## CSS Additions

```css
/* Context highlighting */
.message.context-highlighted {
  background: rgba(251, 191, 36, 0.15) !important;
  border-left: 3px solid #fbbf24 !important;
}

.message.context-highlighted::before {
  content: '◀';
  position: absolute;
  left: -20px;
  color: #fbbf24;
}

/* Hash badge */
.content-hash-badge {
  font-family: monospace;
  font-size: 10px;
  background: #333;
  padding: 2px 6px;
  border-radius: 3px;
  color: #888;
  cursor: pointer;
}

.content-hash-badge:hover {
  background: #444;
  color: #fff;
}

/* Context matrix */
.context-matrix-container {
  background: #121212;
  border-radius: 8px;
  padding: 16px;
}

.matrix-tooltip {
  position: absolute;
  background: #1e1e1e;
  border: 1px solid #333;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  pointer-events: none;
  z-index: 1000;
}

/* Cross-reference panel */
.cross-ref-panel {
  background: #121212;
  border-radius: 8px;
  padding: 16px;
  max-height: 400px;
  overflow-y: auto;
}

.context-item {
  display: flex;
  gap: 8px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 4px;
}

.context-item:hover {
  background: #1e1e1e;
}

.linked-badge {
  color: #34d399;
  cursor: pointer;
}

.linked-badge:hover {
  text-decoration: underline;
}
```

---

## Future Enhancements

1. **Context Diff View**: Side-by-side comparison of two LLM calls showing added/removed context
2. **Context Search**: Search for messages by content and see everywhere they appear in context
3. **Context Replay**: Step through execution showing context at each LLM call
4. **Context Export**: Export context lineage as JSON/Mermaid for external analysis
5. **Anomaly Detection**: Highlight unusual context patterns (sudden growth, unexpected removals)
6. **Context Compression Analysis**: Show where context could be deduplicated/summarized

---

## File Changes Summary

| File | Changes |
|------|---------|
| `dashboard/backend/message_flow_api.py` | Add hash fields to query, add hash_index, new matrix endpoint |
| `dashboard/frontend/src/components/MessageFlowView.js` | Hash badges, hover highlighting, integrate new panels |
| `dashboard/frontend/src/components/ContextMatrixView.js` | **NEW** - Heatmap visualization |
| `dashboard/frontend/src/components/ContextCrossRefPanel.js` | **NEW** - Cross-reference panel |
| `dashboard/frontend/src/components/ContextStatsPanel.js` | **NEW** - Analytics panel |
| `dashboard/frontend/src/components/MessageFlowView.css` | New styles for context features |
