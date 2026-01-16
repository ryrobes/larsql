# Soundings Explorer Enhancement Plan

## Overview

This plan details the enhancements needed to properly display **Reforge refinements** and **Mutation prompts** in the Soundings Explorer UI. The goal is to give users visibility into:

1. How each sounding/reforge attempt was prompted (especially when mutations are applied)
2. The full reforge refinement flow with honing prompts and winner selection
3. Which mutation strategy was used and how it affected the prompt

---

## Current State Analysis

### What's Already Working

| Feature | Status | Location |
|---------|--------|----------|
| Sounding cards with cost/duration/winner | ✅ Working | `SoundingsExplorer.js:236-380` |
| Reforge section (collapsible) | ✅ Working | `SoundingsExplorer.js:396-590` |
| Refinement cards (similar to soundings) | ✅ Working | `SoundingsExplorer.js:432-570` |
| Honing prompt display | ✅ Working | `SoundingsExplorer.js:424-428` |
| Winner path with reforge trail | ✅ Working | `SoundingsExplorer.js:597-626` |
| Pareto frontier chart | ✅ Working | `SoundingsExplorer.js:213-231` |

### What's Missing

| Feature | Issue | Impact |
|---------|-------|--------|
| Mutation fields in SQL query | `mutation_applied`, `mutation_type`, `mutation_template` not queried | Can't display prompt variations |
| Prompt display in UI | No UI to show the actual prompt sent to LLM | Users can't see what was asked |
| Mutation type badges | No visual indicator of which mutation strategy was used | Hard to compare approaches |
| Prompt diff view | Can't compare original vs mutated prompt | Hard to understand mutation effect |
| Full request context | `full_request_json` not utilized | Missing conversation context |

### Data Available in Unified Logs

These fields are already being captured but not displayed:

```sql
-- Available in unified_logs schema
mutation_applied      -- The actual prompt/variation text applied
mutation_type         -- 'rewrite', 'augment', 'approach', or NULL (baseline)
mutation_template     -- For rewrite: instruction given to LLM to generate mutation
full_request_json     -- Complete request with message history
```

---

## Implementation Plan

### Phase 1: Backend API Enhancement (Priority: HIGH)

**Goal:** Add mutation fields to the soundings-tree API response

**File:** `backend/app.py` - `/api/soundings-tree/<session_id>` endpoint

#### 1.1 Update SQL Queries

Add mutation fields to both LiveStore and Parquet queries:

```python
# Line ~1851 (LiveStore query) and ~1880 (Parquet query)
# ADD these columns:
mutation_applied,
mutation_type,
mutation_template,
full_request_json
```

#### 1.2 Update Data Structures

Add mutation data to sounding/refinement objects:

```python
# In the sounding initialization (~line 2049)
phases_dict[phase_name]['soundings'][sounding_idx] = {
    'index': sounding_idx,
    # ... existing fields ...
    'mutation_applied': None,      # NEW
    'mutation_type': None,         # NEW
    'mutation_template': None,     # NEW
    'prompt': None,                # NEW - extracted from full_request_json
}

# Same for refinements (~line 1951)
```

#### 1.3 Extract Prompt from full_request_json

```python
# Parse the full request to extract the actual prompt sent
if pd.notna(row['full_request_json']):
    try:
        full_request = json.loads(row['full_request_json'])
        messages = full_request.get('messages', [])
        # Get the system prompt (usually first message)
        system_prompt = next((m['content'] for m in messages if m.get('role') == 'system'), None)
        sounding['prompt'] = system_prompt
    except:
        pass
```

**Estimated effort:** 2-3 hours

---

### Phase 2: UI - Mutation Type Indicators (Priority: HIGH)

**Goal:** Show which mutation strategy was used for each sounding/refinement

**File:** `frontend/src/components/SoundingsExplorer.js`

#### 2.1 Add Mutation Badge Component

```jsx
// New component for mutation type indicator
function MutationBadge({ mutationType, mutationApplied }) {
  if (!mutationType) return null;

  const config = {
    'rewrite': { icon: 'mdi:auto-fix', color: '#c586c0', label: 'Rewritten' },
    'augment': { icon: 'mdi:text-box-plus', color: '#4ec9b0', label: 'Augmented' },
    'approach': { icon: 'mdi:head-cog', color: '#dcdcaa', label: 'Approach' },
  };

  const cfg = config[mutationType] || { icon: 'mdi:help', color: '#888', label: mutationType };

  return (
    <span
      className="mutation-badge"
      title={mutationApplied?.substring(0, 200) || 'No mutation details'}
      style={{ background: cfg.color }}
    >
      <Icon icon={cfg.icon} width="12" />
      {cfg.label}
    </span>
  );
}
```

#### 2.2 Add Badge to Sounding Cards

In the card header (after model badge):

```jsx
{sounding.mutation_type && (
  <MutationBadge
    mutationType={sounding.mutation_type}
    mutationApplied={sounding.mutation_applied}
  />
)}
```

#### 2.3 Add to Refinement Cards

Same pattern for reforge refinement cards.

**Estimated effort:** 1-2 hours

---

### Phase 3: UI - Prompt Viewer (Priority: HIGH)

**Goal:** Allow users to see the actual prompt sent to each sounding/refinement

**File:** `frontend/src/components/SoundingsExplorer.js`

#### 3.1 Add Expandable Prompt Section

In the expanded detail view of each sounding card:

```jsx
{isExpanded && (
  <div className="expanded-detail">
    {/* NEW: Prompt Section - shown FIRST */}
    {sounding.prompt && (
      <div className="detail-section prompt-section">
        <h4>
          <Icon icon="mdi:message-text" width="16" />
          Prompt
          {sounding.mutation_type && (
            <MutationBadge
              mutationType={sounding.mutation_type}
              mutationApplied={sounding.mutation_applied}
            />
          )}
        </h4>
        <div className="prompt-content">
          <ReactMarkdown>{sounding.prompt}</ReactMarkdown>
        </div>

        {/* Show mutation details if applicable */}
        {sounding.mutation_applied && sounding.mutation_type === 'rewrite' && (
          <div className="mutation-details">
            <h5>Mutation Instruction</h5>
            <pre className="mutation-template">{sounding.mutation_template}</pre>
          </div>
        )}
      </div>
    )}

    {/* Existing sections: Images, Output, Tool Calls, Error */}
    ...
  </div>
)}
```

#### 3.2 CSS Styling

```css
.prompt-section {
  border-left: 3px solid #a78bfa;
  padding-left: 12px;
  margin-bottom: 16px;
}

.prompt-content {
  background: rgba(0, 0, 0, 0.3);
  padding: 12px;
  border-radius: 6px;
  max-height: 300px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.5;
}

.mutation-details {
  margin-top: 12px;
  padding: 8px;
  background: rgba(197, 134, 192, 0.1);
  border-radius: 4px;
}

.mutation-template {
  font-size: 11px;
  color: #c586c0;
  white-space: pre-wrap;
}
```

**Estimated effort:** 2-3 hours

---

### Phase 4: Enhanced Reforge Visualization (Priority: MEDIUM)

**Goal:** Make the reforge flow more visually clear and intuitive

#### 4.1 Reforge Flow Diagram

Add a mini-flow diagram showing the refinement progression:

```
[Initial Winner S2]
       ↓
[Reforge Step 1] → R0, R1* (winner)
       ↓
[Reforge Step 2] → R0*, R1 (winner marked)
       ↓
[Final Output]
```

#### 4.2 Side-by-Side Comparison Mode

Allow comparing two soundings/refinements side-by-side:

```jsx
function ComparisonView({ left, right }) {
  return (
    <div className="comparison-container">
      <div className="comparison-pane left">
        <h4>{left.label}</h4>
        <div className="prompt-content">{left.prompt}</div>
        <div className="output-content">{left.output}</div>
      </div>
      <div className="comparison-pane right">
        <h4>{right.label}</h4>
        <div className="prompt-content">{right.prompt}</div>
        <div className="output-content">{right.output}</div>
      </div>
    </div>
  );
}
```

#### 4.3 Winner Progression Highlight

Show how the "winner" evolves through reforge steps:

- Initial soundings → Winner S2
- Reforge Step 1 → R1 refines S2's output
- Reforge Step 2 → R0 refines R1's output
- Highlight the "golden path" through the tree

**Estimated effort:** 4-6 hours

---

### Phase 5: Mutation Analytics (Priority: LOW)

**Goal:** Help users understand which mutation strategies work best

#### 5.1 Mutation Statistics Panel

```jsx
function MutationStats({ phases }) {
  // Aggregate mutation performance
  const stats = {
    baseline: { wins: 0, total: 0, avgCost: 0 },
    rewrite: { wins: 0, total: 0, avgCost: 0 },
    augment: { wins: 0, total: 0, avgCost: 0 },
    approach: { wins: 0, total: 0, avgCost: 0 },
  };

  // Calculate win rates and costs per mutation type
  // ...

  return (
    <div className="mutation-stats">
      <h4>Mutation Performance</h4>
      {Object.entries(stats).map(([type, data]) => (
        <div key={type} className="stat-row">
          <span className="type">{type || 'baseline'}</span>
          <span className="win-rate">{data.total > 0 ? (data.wins/data.total*100).toFixed(0) : 0}%</span>
          <span className="avg-cost">{formatCost(data.avgCost)}</span>
        </div>
      ))}
    </div>
  );
}
```

#### 5.2 Prompt Diff Viewer

For rewrite mutations, show a diff between original and mutated:

```jsx
import { diffWords } from 'diff';

function PromptDiff({ original, mutated }) {
  const diff = diffWords(original, mutated);

  return (
    <div className="prompt-diff">
      {diff.map((part, i) => (
        <span
          key={i}
          className={part.added ? 'added' : part.removed ? 'removed' : ''}
        >
          {part.value}
        </span>
      ))}
    </div>
  );
}
```

**Estimated effort:** 4-6 hours

---

## Implementation Order

| Phase | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| Phase 1: Backend API | HIGH | 2-3h | None |
| Phase 2: Mutation Badges | HIGH | 1-2h | Phase 1 |
| Phase 3: Prompt Viewer | HIGH | 2-3h | Phase 1 |
| Phase 4: Enhanced Reforge | MEDIUM | 4-6h | Phases 1-3 |
| Phase 5: Analytics | LOW | 4-6h | Phases 1-3 |

**Total estimated effort:** 13-20 hours

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                      LARS RUNNER                             │
│  - Applies mutations (rewrite/augment/approach)                  │
│  - Logs: mutation_applied, mutation_type, mutation_template      │
│  - Logs: full_request_json with complete prompt context          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    UNIFIED LOGS (Parquet/ClickHouse)             │
│  - Stores all mutation fields                                    │
│  - full_request_json contains complete message history           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND API (Flask)                           │
│  /api/soundings-tree/<session_id>                                │
│  - Query mutation_applied, mutation_type, mutation_template      │ ← Phase 1
│  - Extract prompt from full_request_json                         │
│  - Return enriched sounding/refinement objects                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SOUNDINGS EXPLORER (React)                       │
│  - Display mutation badges on cards                              │ ← Phase 2
│  - Show expandable prompt section                                │ ← Phase 3
│  - Enhanced reforge visualization                                │ ← Phase 4
│  - Mutation analytics panel                                      │ ← Phase 5
└─────────────────────────────────────────────────────────────────┘
```

---

## Testing Checklist

- [ ] Run a cascade with `mutate: true` and `mutation_mode: "rewrite"`
- [ ] Verify mutation fields appear in API response
- [ ] Verify mutation badges display correctly
- [ ] Verify prompt viewer shows mutated prompt
- [ ] Run a cascade with reforge enabled
- [ ] Verify reforge steps display with honing prompts
- [ ] Verify winner progression is clear
- [ ] Test with multi-model soundings + Pareto
- [ ] Test real-time updates via SSE

---

## Example Test Cascades

```bash
# Test mutation visibility
lars examples/soundings_rewrite_flow.json --input '{"topic": "AI safety"}'

# Test reforge with mutations
lars examples/reforge_dashboard_metrics.json --input '{"data": "test"}'

# Test multi-model with Pareto
lars examples/multi_model_pareto.json --input '{"question": "test"}'
```

---

## Notes

- The baseline sounding (index 0) should have `mutation_type: null` - this is the "control"
- Rewrite mutations cost extra (LLM call to generate the rewrite)
- Augment and approach mutations are free (just text prepending/appending)
- The prompt viewer should truncate very long prompts with "Show more" option
- Consider adding a "Copy prompt" button for debugging
