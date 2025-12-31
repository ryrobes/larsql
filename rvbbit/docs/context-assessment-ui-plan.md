# Context Assessment UI Plan

> A "Bret Victor-style" explorable explanation of context management decisions for the RVBBIT Studio Receipts page.

## Table of Contents

1. [Overview](#overview)
2. [Data Sources](#data-sources)
3. [UI Components](#ui-components)
4. [API Endpoints](#api-endpoints)
5. [Implementation Phases](#implementation-phases)
6. [Phase 1: Foundation](#phase-1-foundation)
7. [Phase 2: Matrix Enhancement](#phase-2-matrix-enhancement)
8. [Phase 3: Interactive Explorers](#phase-3-interactive-explorers)
9. [SQL Queries Reference](#sql-queries-reference)
10. [Component Architecture](#component-architecture)

---

## Overview

### Goals

The Context Assessment tab provides a visual, interactive interface for understanding and optimizing context management in RVBBIT cascades. Users can:

1. **See** the current context structure across cells and turns
2. **Understand** why each message was included/excluded
3. **Explore** what-if scenarios by scrubbing parameters
4. **Discover** optimization opportunities through shadow assessments
5. **Apply** recommended configurations to reduce costs

### Design Philosophy

Following Bret Victor's principles of "explorable explanations":

- **Direct manipulation**: Sliders and controls that immediately affect visualizations
- **Immediate feedback**: Changes propagate visually in real-time
- **Show relationships**: Visual connections between cause and effect
- **Multiple representations**: Same data shown as matrix, timeline, scatter plot, etc.
- **Scrubbing**: Continuous parameter adjustment to see gradual effects

---

## Data Sources

### Primary Tables

| Table | Type | Description | Row Count Per Session |
|-------|------|-------------|----------------------|
| `context_shadow_assessments` | Inter-phase | Per-message evaluation across strategies & budgets | ~100-500 (messages × budgets) |
| `intra_context_shadow_assessments` | Intra-phase | Config scenario evaluation per turn | ~60 per turn × turns |
| `cell_context_breakdown` | Actual | Context usage with LLM-analyzed relevance | ~10-50 per session |
| `unified_logs` | Actual | Full message history with context_hashes | ~50-500 per session |

### Inter-Phase Shadow Assessment Metrics

```
context_shadow_assessments
├── Identity
│   ├── session_id, cascade_id, target_cell
│   └── source_cell, content_hash, message_index
│
├── Strategy Scores (0-100)
│   ├── heuristic_score    # Keyword/recency-based (cheap, fast)
│   ├── semantic_score     # Embedding similarity (moderate cost)
│   ├── llm_selected       # Cheap LLM decision (bool)
│   └── composite_score    # Weighted blend of all
│
├── Rankings (1 = most relevant)
│   ├── rank_heuristic     # Position by heuristic
│   ├── rank_semantic      # Position by semantic
│   └── rank_composite     # Position by composite
│
├── Budget Analysis (per token_budget level)
│   ├── token_budget                    # 5k, 10k, 15k, 20k, 30k, 50k, 100k
│   ├── cumulative_tokens_at_rank_*     # Running total at this rank
│   ├── would_include_heuristic         # Bool: fits in budget by heuristic?
│   ├── would_include_semantic          # Bool: fits in budget by semantic?
│   ├── would_include_llm               # Bool: LLM said yes?
│   └── would_include_hybrid            # Bool: hybrid strategy?
│
└── Comparison
    ├── actual_included     # Was this message actually included?
    └── differs_from_actual # Would shadow config change inclusion?
```

### Intra-Phase Shadow Assessment Metrics

```
intra_context_shadow_assessments
├── Identity
│   ├── session_id, cascade_id, cell_name
│   ├── candidate_index    # NULL if not in soundings, else 0, 1, 2...
│   └── turn_number        # Turn within cell (0-indexed)
│
├── Config Scenario (60 combinations)
│   ├── config_window           # [3, 5, 7, 10, 15] - full fidelity turns
│   ├── config_mask_after       # [2, 3, 5, 7] - when to mask tool results
│   ├── config_min_masked_size  # [100, 200, 500] - min chars to mask
│   ├── config_compress_loops   # Bool
│   ├── config_preserve_reasoning # Bool
│   └── config_preserve_errors  # Bool
│
├── Metrics
│   ├── tokens_before       # Before compression
│   ├── tokens_after        # After compression
│   ├── tokens_saved        # tokens_before - tokens_after
│   ├── compression_ratio   # tokens_after / tokens_before
│   ├── messages_masked     # Count
│   ├── messages_preserved  # Count
│   └── messages_truncated  # Count
│
├── Per-Message Breakdown (JSON)
│   └── message_breakdown   # [{msg_index, role, original_tokens, action, result_tokens, reason}]
│
└── Comparison
    ├── actual_config_enabled   # Was intra-context enabled?
    ├── actual_tokens_after     # What actually happened
    └── differs_from_actual     # Would this config be different?
```

### Relevance Analysis Metrics

```
cell_context_breakdown (with relevance columns)
├── Identity
│   ├── session_id, cascade_id, cell_name
│   └── context_message_hash, context_message_cell
│
├── Cost Attribution
│   ├── context_message_tokens  # Tokens from this message
│   ├── context_message_cost    # Estimated cost
│   └── context_message_pct     # % of total cell cost
│
└── Relevance (LLM-analyzed post-hoc)
    ├── relevance_score         # 0-100: contribution to output
    ├── relevance_reasoning     # Human-readable explanation
    └── relevance_analysis_cost # Meta: cost of the analysis itself
```

---

## UI Components

### 1. Session Selector + Overview Cards

```
┌─────────────────────────────────────────────────────────────────┐
│ [Session Dropdown ▼]  [Cascade Dropdown ▼]  [Time Range ▼]     │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│ │ Inter-Phase  │ │ Intra-Phase  │ │ Relevance    │ │ Potential│ │
│ │ 12 cells     │ │ 47 turns     │ │ Avg: 67/100  │ │ Savings  │ │
│ │ assessed     │ │ 2,820 rows   │ │ 85% analyzed │ │ ~$0.42   │ │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Context Matrix+ (Enhanced)

Extended version of `ContextMatrixView` with shadow assessment overlays:

```
┌─────────────────────────────────────────────────────────────────┐
│ Context Matrix+                              [Role ▼] [Zoom ±]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│     │ LLM Call 1 │ Call 2 │ Call 3 │ Call 4 │ ...              │
│ ────┼────────────┼────────┼────────┼────────┤                   │
│ H₁  │ ████ 92    │ ████   │ ████   │ ████   │ ← High relevance │
│ H₂  │ ░░░░ 12    │ ░░░░   │ ████   │ ████   │ ← Low relevance  │
│ H₃  │            │ ████ 78│ ████   │ ████   │                   │
│ H₄  │            │        │ ┄┄┄┄ 8 │        │ ← Would exclude  │
│     │            │        │        │        │                   │
│                                                                 │
│ Legend: ████ Included (high relevance)                          │
│         ░░░░ Included (low relevance - potential waste)         │
│         ┄┄┄┄ Would be excluded at current budget                │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Inter-Phase Strategy Explorer

```
┌─────────────────────────────────────────────────────────────────┐
│ Inter-Phase Strategy Explorer                    [Cell: plan ▼] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Token Budget:  ○──────●───────────────────○  30,000 tokens      │
│                5k   10k   15k   20k   30k   50k   100k          │
│                                                                 │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Included Messages (12 of 28)              Est. Cost: $0.08 │  │
│ ├────────────────────────────────────────────────────────────┤  │
│ │ ● system: "You are a helpful..."        [██████████] 95    │  │
│ │ ● user: "Please analyze the..."         [████████░░] 82    │  │
│ │ ● assistant: "I found 3 issues..."      [███████░░░] 71    │  │
│ │ ○ tool: "SQL result: 1,234 rows..."     [███░░░░░░░] 35    │  │
│ │ ○ assistant: "Here's a summary..."      [██░░░░░░░░] 23    │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ Strategy Rankings (at 30k budget):                              │
│   Heuristic   Semantic   LLM      Composite    Actual           │
│   ┌───────┐   ┌───────┐  ┌───────┐ ┌───────┐   ┌───────┐       │
│   │ H₁ ●  │   │ H₁ ●  │  │ H₁ ●  │ │ H₁ ●  │   │ H₁ ●  │       │
│   │ H₂ ●  │   │ H₃ ●  │  │ H₂ ●  │ │ H₂ ●  │   │ H₂ ●  │       │
│   │ H₃ ●  │   │ H₂ ○  │  │ H₃ ●  │ │ H₃ ●  │   │ H₃ ●  │       │
│   │ H₄ ○  │   │ H₄ ○  │  │ H₄ ○  │ │ H₄ ○  │   │ H₄ ●  │       │
│   └───────┘   └───────┘  └───────┘ └───────┘   └───────┘       │
│                                                                 │
│   Savings vs Actual: 2,340 tokens ($0.012)                      │
│   Relevance preserved: 94% (H₄ had relevance=12)                │
└─────────────────────────────────────────────────────────────────┘
```

### 4. Intra-Phase Config Explorer

```
┌─────────────────────────────────────────────────────────────────┐
│ Intra-Phase Config Explorer                   [Cell: analyze ▼] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Config Parameters:                                              │
│   Window:      ○────●────────○  5 turns                         │
│                3    5    7   10   15                            │
│                                                                 │
│   Mask After:  ○────●────────○  3 turns                         │
│                2    3    5    7                                  │
│                                                                 │
│   Min Size:    ●─────────────○  100 chars                       │
│                100   200   500                                   │
│                                                                 │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Compression Over Time                                      │  │
│ │  Tokens                                                    │  │
│ │    ▲                                                       │  │
│ │ 4k │     ╱──────────── Before (actual)                     │  │
│ │    │   ╱                                                   │  │
│ │ 2k │ ╱    ════════════ After (shadow config)               │  │
│ │    │╱                                                      │  │
│ │  0 └─────────────────────────────────────▶ Turn            │  │
│ │       1   2   3   4   5   6   7   8   9  10                │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ Results: 4,230 → 2,180 tokens (48% savings, 0.52x compression)  │
│                                                                 │
│ Message Actions (Turn 10):                                      │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ ├─ system: "You are..."      KEEP       120 → 120 tokens   │  │
│ │ ├─ user T1: "Please..."      MASK       450 → 45 tokens    │  │
│ │ ├─ asst T1: "I found..."     KEEP*      380 → 380 tokens   │  │
│ │ ├─ tool T1: "[SQL output]"   MASK       1200 → 50 tokens   │  │
│ │ └─ ...                       * = preserved (reasoning)     │  │
│ └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 5. Config Recommendation Engine

```
┌─────────────────────────────────────────────────────────────────┐
│ 🎯 Recommended Configurations                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Based on 47 turns across 12 cells with 2,820 config scenarios:  │
│                                                                 │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ ✓ BEST OVERALL                                            │   │
│ │   window=5, mask_after=3, min_size=200                    │   │
│ │                                                           │   │
│ │   • Avg compression: 0.52x (48% savings)                  │   │
│ │   • Total tokens saved: 24,500                            │   │
│ │   • Estimated cost savings: $0.42/run                     │   │
│ │   • Relevance preserved: 91%                              │   │
│ │                                                           │   │
│ │   [Apply to Cascade]  [Copy YAML]  [View Details]         │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│ Alternatives:                                                   │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ AGGRESSIVE: w=3, m=2, s=100 │ 62% savings │ Higher risk   │   │
│ │ CONSERVATIVE: w=10, m=5, s=500 │ 28% savings │ Safer      │   │
│ └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 6. Relevance vs. Cost Scatter Plot

```
┌─────────────────────────────────────────────────────────────────┐
│ Context Value Analysis                        [Session ▼]       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Relevance │                    KEEP ZONE                       │
│  (0-100)   │    ●              ●                                │
│       80   │      ●   ●                                         │
│            │        ●                                           │
│       60   │   ●            ●                                   │
│            │                          ●                         │
│       40   │──────────────────────────────── threshold ───────  │
│            │                              │                      │
│       20   │      ○    ○     ○         │ WASTE ZONE            │
│            │   ○              ○   ○    │ High cost, low value  │
│        0   └───────────────────────────────────────────────────  │
│            0      500     1000    1500    2000    2500          │
│                        Tokens (Cost)                            │
│                                                                 │
│ ● Included  ○ Would exclude   Waste: 4 msgs, 3.2k tok, $0.08   │
└─────────────────────────────────────────────────────────────────┘
```

### 7. Candidate Context Comparison

```
┌─────────────────────────────────────────────────────────────────┐
│ Candidate Context Comparison               [Cell: evaluate ▼]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐     │
│ │ Candidate 0 🏆   │ │ Candidate 1     │ │ Candidate 2     │     │
│ ├─────────────────┤ ├─────────────────┤ ├─────────────────┤     │
│ │ Turns: 8        │ │ Turns: 12       │ │ Turns: 6        │     │
│ │ Context: 4.2k   │ │ Context: 6.8k   │ │ Context: 3.1k   │     │
│ │ Cost: $0.042    │ │ Cost: $0.068    │ │ Cost: $0.031    │     │
│ │ Best: w=5 m=3   │ │ Best: w=3 m=2   │ │ Best: w=7 m=3   │     │
│ │ Savings: 38%    │ │ Savings: 52%    │ │ Savings: 24%    │     │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘     │
│                                                                 │
│ Context Heat by Turn:                                           │
│      T1  T2  T3  T4  T5  T6  T7  T8  T9  T10 T11 T12            │
│ C0   ██  ██  ██  ██  ██  ██  ██  ██                             │
│ C1   ░░  ░░  ░░  ██  ██  ██  ██  ██  ██  ██  ██  ██             │
│ C2   ██  ██  ██  ██  ██  ██                                     │
│                                                                 │
│ ░░ Heavy (>1k tokens)  ██ Light (<1k tokens)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## API Endpoints

### Phase 1 Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/context-assessment/sessions` | GET | List sessions with shadow assessment data |
| `/api/context-assessment/overview/:session_id` | GET | Summary stats for a session |
| `/api/context-assessment/inter-phase/:session_id` | GET | Inter-phase shadow data |
| `/api/context-assessment/intra-phase/:session_id` | GET | Intra-phase config scenarios |

### Phase 2 Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/context-assessment/matrix/:session_id` | GET | Enhanced matrix data with relevance |
| `/api/context-assessment/message/:content_hash` | GET | Full message detail with shadow info |

### Phase 3 Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/context-assessment/recommendations/:cascade_id` | GET | Aggregated config recommendations |
| `/api/context-assessment/relevance-scatter/:session_id` | GET | Data for scatter plot |
| `/api/context-assessment/candidate-comparison/:session_id` | GET | Per-candidate analysis |

### Response Schemas

#### Overview Response
```json
{
  "session_id": "abc123",
  "cascade_id": "my_cascade",
  "inter_phase": {
    "cells_assessed": 12,
    "messages_assessed": 156,
    "budgets_evaluated": [5000, 10000, 15000, 20000, 30000, 50000, 100000]
  },
  "intra_phase": {
    "turns_assessed": 47,
    "configs_evaluated": 60,
    "total_rows": 2820
  },
  "relevance": {
    "messages_analyzed": 132,
    "messages_total": 156,
    "coverage_pct": 84.6,
    "avg_relevance": 67.3
  },
  "potential_savings": {
    "tokens": 24500,
    "cost_estimated": 0.42,
    "best_inter_config": {"strategy": "composite", "budget": 30000},
    "best_intra_config": {"window": 5, "mask_after": 3, "min_size": 200}
  }
}
```

#### Inter-Phase Response
```json
{
  "session_id": "abc123",
  "cells": [
    {
      "cell_name": "analyze",
      "messages": [
        {
          "content_hash": "abc123def456",
          "source_cell": "research",
          "role": "assistant",
          "tokens": 450,
          "scores": {
            "heuristic": 78,
            "semantic": 82,
            "llm_selected": true,
            "composite": 80
          },
          "ranks": {
            "heuristic": 3,
            "semantic": 2,
            "composite": 2
          },
          "budgets": {
            "5000": {"would_include": false, "cumulative_tokens": 6200},
            "10000": {"would_include": true, "cumulative_tokens": 6200},
            "15000": {"would_include": true, "cumulative_tokens": 6200}
          },
          "actual_included": true,
          "relevance_score": 72,
          "relevance_reason": "Contains key findings referenced in output",
          "preview": "Based on my analysis, I found three critical issues..."
        }
      ]
    }
  ]
}
```

#### Intra-Phase Response
```json
{
  "session_id": "abc123",
  "cells": [
    {
      "cell_name": "analyze",
      "candidate_index": null,
      "turns": [
        {
          "turn_number": 5,
          "configs": [
            {
              "window": 5,
              "mask_after": 3,
              "min_size": 200,
              "tokens_before": 4230,
              "tokens_after": 2180,
              "tokens_saved": 2050,
              "compression_ratio": 0.515,
              "messages_masked": 8,
              "messages_preserved": 12,
              "message_breakdown": [
                {"index": 0, "role": "system", "action": "keep", "before": 120, "after": 120},
                {"index": 1, "role": "user", "action": "mask", "before": 450, "after": 45},
                {"index": 2, "role": "assistant", "action": "keep", "before": 380, "after": 380, "reason": "reasoning"}
              ]
            }
          ],
          "actual_config": {
            "enabled": true,
            "window": 7,
            "mask_after": 5,
            "tokens_after": 3100
          }
        }
      ]
    }
  ]
}
```

---

## Implementation Phases

### Phase 1: Foundation (Backend + Basic UI)

**Goal**: Get data flowing and basic UI structure in place.

**Duration**: ~2-3 days

**Deliverables**:
1. Backend API endpoints for shadow assessment queries
2. "Context Assessment" tab added to ReceiptsView
3. Session/cascade selector with search
4. Overview cards showing summary stats
5. Basic data table view (before interactive visualizations)

### Phase 2: Matrix Enhancement

**Goal**: Extend the existing ContextMatrixView with shadow/relevance overlays.

**Duration**: ~2-3 days

**Deliverables**:
1. New color mode: "Relevance" (green/yellow/red gradient)
2. Shadow exclusion overlay (dashed borders for would-exclude)
3. Message detail sidebar with full context
4. Cross-component hover highlighting
5. Bidirectional linking between matrix and other views

### Phase 3: Interactive Explorers

**Goal**: Build the Bret Victor-style interactive parameter exploration.

**Duration**: ~4-5 days

**Deliverables**:
1. Inter-Phase Strategy Explorer with budget slider
2. Intra-Phase Config Explorer with parameter sliders
3. Real-time calculation updates (no server round-trip)
4. Message action breakdown tree
5. Compression timeline chart

### Phase 4: Intelligence Layer

**Goal**: Add recommendation engine and advanced visualizations.

**Duration**: ~3-4 days

**Deliverables**:
1. Config recommendation queries and UI
2. "Apply to Cascade" workflow (generates YAML)
3. Relevance vs. Cost scatter plot
4. Per-cell suggestions table

### Phase 5: Polish & Candidates

**Goal**: Handle multi-candidate scenarios and polish UX.

**Duration**: ~2-3 days

**Deliverables**:
1. Candidate comparison view
2. Turn-by-turn heat visualization
3. Export/share functionality
4. Performance optimization for large sessions
5. Keyboard navigation and accessibility

---

## Phase 1: Foundation

### 1.1 Backend API Implementation

**File**: `studio/backend/context_assessment_api.py`

```python
from flask import Blueprint, jsonify, request
from rvbbit.db_adapter import get_db

context_assessment_bp = Blueprint('context_assessment', __name__)

@context_assessment_bp.route('/api/context-assessment/sessions', methods=['GET'])
def list_sessions():
    """List sessions that have shadow assessment data."""
    db = get_db()
    days = request.args.get('days', 7, type=int)

    # Query sessions with shadow data
    query = '''
        SELECT DISTINCT
            csa.session_id,
            csa.cascade_id,
            MIN(csa.timestamp) as first_assessment,
            MAX(csa.timestamp) as last_assessment,
            COUNT(DISTINCT csa.target_cell) as cells_assessed,
            COUNT(*) as total_assessments
        FROM context_shadow_assessments csa
        WHERE csa.timestamp >= now() - INTERVAL {days} DAY
        GROUP BY csa.session_id, csa.cascade_id
        ORDER BY last_assessment DESC
        LIMIT 100
    '''.format(days=days)

    results = db.query(query)
    return jsonify({'sessions': results})


@context_assessment_bp.route('/api/context-assessment/overview/<session_id>', methods=['GET'])
def get_overview(session_id):
    """Get overview stats for a session."""
    db = get_db()

    # Inter-phase stats
    inter_query = '''
        SELECT
            COUNT(DISTINCT target_cell) as cells_assessed,
            COUNT(DISTINCT content_hash) as messages_assessed,
            COUNT(DISTINCT token_budget) as budgets_evaluated
        FROM context_shadow_assessments
        WHERE session_id = '{session_id}'
    '''.format(session_id=session_id)

    # Intra-phase stats
    intra_query = '''
        SELECT
            COUNT(DISTINCT (cell_name, turn_number)) as turns_assessed,
            COUNT(*) as total_rows
        FROM intra_context_shadow_assessments
        WHERE session_id = '{session_id}'
    '''.format(session_id=session_id)

    # Relevance stats
    relevance_query = '''
        SELECT
            COUNT(*) as messages_total,
            countIf(relevance_score IS NOT NULL) as messages_analyzed,
            AVG(relevance_score) as avg_relevance
        FROM cell_context_breakdown
        WHERE session_id = '{session_id}'
    '''.format(session_id=session_id)

    # Best configs
    best_intra_query = '''
        SELECT
            config_window,
            config_mask_after,
            config_min_masked_size,
            AVG(compression_ratio) as avg_compression,
            SUM(tokens_saved) as total_saved
        FROM intra_context_shadow_assessments
        WHERE session_id = '{session_id}'
        GROUP BY config_window, config_mask_after, config_min_masked_size
        ORDER BY total_saved DESC
        LIMIT 1
    '''.format(session_id=session_id)

    inter = db.query(inter_query)
    intra = db.query(intra_query)
    relevance = db.query(relevance_query)
    best_intra = db.query(best_intra_query)

    return jsonify({
        'session_id': session_id,
        'inter_phase': inter[0] if inter else {},
        'intra_phase': intra[0] if intra else {},
        'relevance': relevance[0] if relevance else {},
        'best_intra_config': best_intra[0] if best_intra else None
    })


@context_assessment_bp.route('/api/context-assessment/inter-phase/<session_id>', methods=['GET'])
def get_inter_phase(session_id):
    """Get inter-phase shadow assessment data."""
    db = get_db()
    cell_name = request.args.get('cell')

    where_clause = f"WHERE session_id = '{session_id}'"
    if cell_name:
        where_clause += f" AND target_cell = '{cell_name}'"

    query = f'''
        SELECT
            csa.*,
            ccb.relevance_score,
            ccb.relevance_reasoning
        FROM context_shadow_assessments csa
        LEFT JOIN cell_context_breakdown ccb ON (
            ccb.session_id = csa.session_id
            AND ccb.cell_name = csa.target_cell
            AND ccb.context_message_hash = csa.content_hash
        )
        {where_clause}
        ORDER BY csa.target_cell, csa.rank_composite
    '''

    results = db.query(query)

    # Group by cell
    cells = {}
    for row in results:
        cell = row['target_cell']
        if cell not in cells:
            cells[cell] = {'cell_name': cell, 'messages': []}
        cells[cell]['messages'].append(row)

    return jsonify({
        'session_id': session_id,
        'cells': list(cells.values())
    })


@context_assessment_bp.route('/api/context-assessment/intra-phase/<session_id>', methods=['GET'])
def get_intra_phase(session_id):
    """Get intra-phase shadow assessment data."""
    db = get_db()
    cell_name = request.args.get('cell')

    where_clause = f"WHERE session_id = '{session_id}'"
    if cell_name:
        where_clause += f" AND cell_name = '{cell_name}'"

    query = f'''
        SELECT *
        FROM intra_context_shadow_assessments
        {where_clause}
        ORDER BY cell_name, candidate_index, turn_number, config_window, config_mask_after
    '''

    results = db.query(query)

    # Group by cell -> candidate -> turn -> configs
    cells = {}
    for row in results:
        cell = row['cell_name']
        candidate = row['candidate_index']
        turn = row['turn_number']

        if cell not in cells:
            cells[cell] = {'cell_name': cell, 'candidates': {}}
        if candidate not in cells[cell]['candidates']:
            cells[cell]['candidates'][candidate] = {'candidate_index': candidate, 'turns': {}}
        if turn not in cells[cell]['candidates'][candidate]['turns']:
            cells[cell]['candidates'][candidate]['turns'][turn] = {
                'turn_number': turn,
                'configs': []
            }

        cells[cell]['candidates'][candidate]['turns'][turn]['configs'].append({
            'window': row['config_window'],
            'mask_after': row['config_mask_after'],
            'min_size': row['config_min_masked_size'],
            'tokens_before': row['tokens_before'],
            'tokens_after': row['tokens_after'],
            'tokens_saved': row['tokens_saved'],
            'compression_ratio': row['compression_ratio'],
            'messages_masked': row['messages_masked'],
            'messages_preserved': row['messages_preserved'],
            'message_breakdown': row['message_breakdown']
        })

    # Convert nested dicts to lists
    result_cells = []
    for cell_data in cells.values():
        candidates = []
        for cand_data in cell_data['candidates'].values():
            turns = list(cand_data['turns'].values())
            candidates.append({
                'candidate_index': cand_data['candidate_index'],
                'turns': sorted(turns, key=lambda t: t['turn_number'])
            })
        result_cells.append({
            'cell_name': cell_data['cell_name'],
            'candidates': sorted(candidates, key=lambda c: c['candidate_index'] or -1)
        })

    return jsonify({
        'session_id': session_id,
        'cells': result_cells
    })
```

**Register in app.py**:
```python
from context_assessment_api import context_assessment_bp
app.register_blueprint(context_assessment_bp)
```

### 1.2 Frontend Tab Addition

**File**: `studio/frontend/src/views/receipts/ReceiptsView.jsx`

Add new tab:
```jsx
// Add to imports
import ContextAssessmentPanel from './components/ContextAssessmentPanel';

// Add state for new tab data
const [assessmentData, setAssessmentData] = useState(null);

// Add to tabs section
<button
  className={`receipts-tab ${activeView === 'assessment' ? 'active' : ''}`}
  onClick={() => setActiveView('assessment')}
>
  <Icon icon="mdi:clipboard-check-outline" width={14} />
  <span>Context Assessment</span>
</button>

// Add to content area
{activeView === 'assessment' && (
  <ContextAssessmentPanel timeRange={timeRange} />
)}
```

### 1.3 Overview Component

**File**: `studio/frontend/src/views/receipts/components/ContextAssessmentPanel.jsx`

```jsx
import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './ContextAssessmentPanel.css';

const ContextAssessmentPanel = ({ timeRange }) => {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fetch sessions with shadow data
  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/sessions?days=${timeRange}`
        );
        const data = await res.json();
        setSessions(data.sessions || []);
        if (data.sessions?.length > 0 && !selectedSession) {
          setSelectedSession(data.sessions[0].session_id);
        }
      } catch (err) {
        console.error('Failed to fetch sessions:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchSessions();
  }, [timeRange]);

  // Fetch overview when session changes
  useEffect(() => {
    if (!selectedSession) return;

    const fetchOverview = async () => {
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/overview/${selectedSession}`
        );
        const data = await res.json();
        setOverview(data);
      } catch (err) {
        console.error('Failed to fetch overview:', err);
      }
    };
    fetchOverview();
  }, [selectedSession]);

  const formatNumber = (n) => n?.toLocaleString() ?? '—';
  const formatPct = (n) => n != null ? `${n.toFixed(1)}%` : '—';
  const formatCost = (n) => n != null ? `$${n.toFixed(4)}` : '—';

  if (loading) {
    return (
      <div className="context-assessment-panel loading">
        <Icon icon="mdi:loading" className="spin" width={24} />
        <span>Loading assessment data...</span>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="context-assessment-panel empty">
        <Icon icon="mdi:clipboard-off-outline" width={48} />
        <h3>No Shadow Assessment Data</h3>
        <p>Run cascades with RVBBIT_SHADOW_ASSESSMENT_ENABLED=true to collect context assessment data.</p>
      </div>
    );
  }

  return (
    <div className="context-assessment-panel">
      {/* Session Selector */}
      <div className="assessment-header">
        <div className="session-selector">
          <label>Session:</label>
          <select
            value={selectedSession || ''}
            onChange={(e) => setSelectedSession(e.target.value)}
          >
            {sessions.map(s => (
              <option key={s.session_id} value={s.session_id}>
                {s.cascade_id} / {s.session_id.slice(0, 12)}...
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Overview Cards */}
      {overview && (
        <div className="assessment-overview">
          <div className="overview-card">
            <div className="card-icon">
              <Icon icon="mdi:swap-horizontal" width={20} />
            </div>
            <div className="card-content">
              <div className="card-value">{formatNumber(overview.inter_phase?.cells_assessed)}</div>
              <div className="card-label">Inter-Phase Cells</div>
              <div className="card-detail">{formatNumber(overview.inter_phase?.messages_assessed)} messages</div>
            </div>
          </div>

          <div className="overview-card">
            <div className="card-icon">
              <Icon icon="mdi:rotate-right" width={20} />
            </div>
            <div className="card-content">
              <div className="card-value">{formatNumber(overview.intra_phase?.turns_assessed)}</div>
              <div className="card-label">Intra-Phase Turns</div>
              <div className="card-detail">{formatNumber(overview.intra_phase?.total_rows)} config rows</div>
            </div>
          </div>

          <div className="overview-card">
            <div className="card-icon">
              <Icon icon="mdi:check-circle" width={20} />
            </div>
            <div className="card-content">
              <div className="card-value">{overview.relevance?.avg_relevance?.toFixed(0) ?? '—'}</div>
              <div className="card-label">Avg Relevance</div>
              <div className="card-detail">{formatPct(overview.relevance?.coverage_pct)} analyzed</div>
            </div>
          </div>

          <div className="overview-card highlight">
            <div className="card-icon">
              <Icon icon="mdi:piggy-bank" width={20} />
            </div>
            <div className="card-content">
              <div className="card-value">{formatCost(overview.potential_savings?.cost_estimated)}</div>
              <div className="card-label">Potential Savings</div>
              <div className="card-detail">
                {overview.best_intra_config &&
                  `w=${overview.best_intra_config.config_window} m=${overview.best_intra_config.config_mask_after}`
                }
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Placeholder for Phase 2+ components */}
      <div className="assessment-content">
        <div className="coming-soon">
          <Icon icon="mdi:hammer-wrench" width={32} />
          <h4>Interactive Explorers Coming Soon</h4>
          <p>Phase 2 will add the context matrix and strategy explorer.</p>
        </div>
      </div>
    </div>
  );
};

export default ContextAssessmentPanel;
```

### 1.4 Styles

**File**: `studio/frontend/src/views/receipts/components/ContextAssessmentPanel.css`

```css
.context-assessment-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px;
  min-height: 400px;
}

.context-assessment-panel.loading,
.context-assessment-panel.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #94a3b8;
  text-align: center;
}

.context-assessment-panel.empty h3 {
  color: #e2e8f0;
  margin: 0;
}

.context-assessment-panel.empty p {
  max-width: 400px;
  font-size: 13px;
}

/* Header */
.assessment-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.session-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-selector label {
  color: #94a3b8;
  font-size: 13px;
}

.session-selector select {
  background: #1e1e24;
  border: 1px solid #2a2a32;
  border-radius: 6px;
  color: #e2e8f0;
  padding: 6px 12px;
  font-size: 13px;
  min-width: 300px;
}

.session-selector select:focus {
  outline: none;
  border-color: #00e5ff;
}

/* Overview Cards */
.assessment-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.overview-card {
  background: #121218;
  border: 1px solid #2a2a32;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  gap: 12px;
}

.overview-card.highlight {
  border-color: #00e5ff33;
  background: linear-gradient(135deg, #121218 0%, #0a1a1a 100%);
}

.card-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: #1e1e24;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #00e5ff;
}

.overview-card.highlight .card-icon {
  background: #00e5ff22;
}

.card-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-value {
  font-size: 24px;
  font-weight: 600;
  color: #e2e8f0;
}

.card-label {
  font-size: 12px;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-detail {
  font-size: 11px;
  color: #64748b;
}

/* Content Area */
.assessment-content {
  flex: 1;
  min-height: 300px;
}

.coming-soon {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: #64748b;
  text-align: center;
}

.coming-soon h4 {
  color: #94a3b8;
  margin: 0;
}

.coming-soon p {
  font-size: 13px;
}

/* Responsive */
@media (max-width: 1200px) {
  .assessment-overview {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .assessment-overview {
    grid-template-columns: 1fr;
  }
}
```

---

## Phase 2: Matrix Enhancement

### 2.1 Enhanced ContextMatrixView

Extend the existing `ContextMatrixView.jsx` to support new color modes and overlays.

**New Props**:
```jsx
<ContextMatrixView
  data={data}
  // Existing props...

  // New props for shadow/relevance
  shadowData={shadowData}           // From context_shadow_assessments
  relevanceData={relevanceData}     // From cell_context_breakdown
  colorMode="relevance"             // 'role' | 'tokens' | 'relevance' | 'shadow'
  selectedBudget={30000}            // For shadow overlay filtering
  showShadowOverlay={true}          // Show dashed borders for would-exclude
/>
```

**New Color Mode: Relevance**
```javascript
const getRelevanceColor = (score) => {
  if (score === null || score === undefined) return '#333333';
  if (score >= 70) return `rgba(52, 211, 153, ${0.4 + score/100 * 0.5})`; // Green
  if (score >= 40) return `rgba(251, 191, 36, ${0.4 + score/100 * 0.5})`;  // Yellow
  return `rgba(248, 113, 113, ${0.4 + score/100 * 0.5})`;                  // Red
};
```

**Shadow Overlay Logic**:
```javascript
// In the draw loop, after drawing the cell:
if (showShadowOverlay && shadowData) {
  const shadow = shadowData.find(s => s.content_hash === hash);
  if (shadow && !shadow[`would_include_${strategy}`]) {
    // Draw dashed border
    ctx.setLineDash([2, 2]);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, cellSize - 1, cellSize - 1);
    ctx.setLineDash([]);
  }
}
```

### 2.2 Message Detail Sidebar

**File**: `studio/frontend/src/views/receipts/components/MessageDetailSidebar.jsx`

```jsx
const MessageDetailSidebar = ({ message, shadowInfo, relevanceInfo, onClose }) => {
  return (
    <div className="message-detail-sidebar">
      <div className="sidebar-header">
        <h3>Message Detail</h3>
        <button onClick={onClose}><Icon icon="mdi:close" /></button>
      </div>

      <div className="sidebar-content">
        {/* Basic Info */}
        <section>
          <h4>Identity</h4>
          <div className="info-row">
            <span>Hash:</span>
            <code>{message.content_hash}</code>
          </div>
          <div className="info-row">
            <span>Role:</span>
            <span className={`role-badge ${message.role}`}>{message.role}</span>
          </div>
          <div className="info-row">
            <span>Source Cell:</span>
            <span>{message.cell_name}</span>
          </div>
          <div className="info-row">
            <span>Tokens:</span>
            <span>{message.estimated_tokens?.toLocaleString()}</span>
          </div>
        </section>

        {/* Shadow Assessment */}
        {shadowInfo && (
          <section>
            <h4>Shadow Assessment</h4>
            <div className="score-grid">
              <div className="score-item">
                <span className="score-label">Heuristic</span>
                <span className="score-value">{shadowInfo.heuristic_score}</span>
                <span className="score-rank">#{shadowInfo.rank_heuristic}</span>
              </div>
              <div className="score-item">
                <span className="score-label">Semantic</span>
                <span className="score-value">{shadowInfo.semantic_score}</span>
                <span className="score-rank">#{shadowInfo.rank_semantic}</span>
              </div>
              <div className="score-item">
                <span className="score-label">Composite</span>
                <span className="score-value">{shadowInfo.composite_score}</span>
                <span className="score-rank">#{shadowInfo.rank_composite}</span>
              </div>
            </div>

            <h5>Budget Inclusion</h5>
            <div className="budget-grid">
              {[5000, 10000, 15000, 20000, 30000, 50000, 100000].map(budget => (
                <div
                  key={budget}
                  className={`budget-item ${shadowInfo.budgets?.[budget]?.would_include ? 'included' : 'excluded'}`}
                >
                  {budget/1000}k
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Relevance Analysis */}
        {relevanceInfo && (
          <section>
            <h4>Relevance Analysis</h4>
            <div className="relevance-score">
              <div className="score-bar">
                <div
                  className="score-fill"
                  style={{
                    width: `${relevanceInfo.relevance_score}%`,
                    background: relevanceInfo.relevance_score >= 70 ? '#34d399'
                              : relevanceInfo.relevance_score >= 40 ? '#fbbf24'
                              : '#f87171'
                  }}
                />
              </div>
              <span className="score-number">{relevanceInfo.relevance_score}/100</span>
            </div>
            {relevanceInfo.relevance_reasoning && (
              <div className="relevance-reasoning">
                <Icon icon="mdi:lightbulb-outline" />
                <p>{relevanceInfo.relevance_reasoning}</p>
              </div>
            )}
          </section>
        )}

        {/* Content Preview */}
        <section>
          <h4>Content</h4>
          <pre className="content-preview">
            {message.content?.slice(0, 1000)}
            {message.content?.length > 1000 && '...'}
          </pre>
        </section>
      </div>
    </div>
  );
};
```

---

## Phase 3: Interactive Explorers

### 3.1 Budget Slider Component

**File**: `studio/frontend/src/components/BudgetSlider.jsx`

```jsx
import React, { useState, useCallback } from 'react';
import './BudgetSlider.css';

const BUDGET_VALUES = [5000, 10000, 15000, 20000, 30000, 50000, 100000];

const BudgetSlider = ({ value, onChange, showLabels = true }) => {
  const currentIndex = BUDGET_VALUES.indexOf(value);

  const handleChange = (e) => {
    const index = parseInt(e.target.value);
    onChange(BUDGET_VALUES[index]);
  };

  return (
    <div className="budget-slider">
      <input
        type="range"
        min={0}
        max={BUDGET_VALUES.length - 1}
        value={currentIndex}
        onChange={handleChange}
        className="slider-input"
      />
      {showLabels && (
        <div className="slider-labels">
          {BUDGET_VALUES.map((v, i) => (
            <span
              key={v}
              className={`label ${i === currentIndex ? 'active' : ''}`}
              onClick={() => onChange(v)}
            >
              {v >= 1000 ? `${v/1000}k` : v}
            </span>
          ))}
        </div>
      )}
      <div className="slider-value">
        <span className="value-number">{value.toLocaleString()}</span>
        <span className="value-unit">tokens</span>
      </div>
    </div>
  );
};
```

### 3.2 Config Sliders Component

**File**: `studio/frontend/src/components/ConfigSliders.jsx`

```jsx
import React from 'react';
import './ConfigSliders.css';

const WINDOW_VALUES = [3, 5, 7, 10, 15];
const MASK_AFTER_VALUES = [2, 3, 5, 7];
const MIN_SIZE_VALUES = [100, 200, 500];

const DiscreteSlider = ({ label, values, value, onChange }) => {
  const currentIndex = values.indexOf(value);

  return (
    <div className="discrete-slider">
      <div className="slider-header">
        <span className="slider-label">{label}</span>
        <span className="slider-value">{value}</span>
      </div>
      <div className="slider-track">
        <input
          type="range"
          min={0}
          max={values.length - 1}
          value={currentIndex}
          onChange={(e) => onChange(values[parseInt(e.target.value)])}
        />
        <div className="track-marks">
          {values.map((v, i) => (
            <span
              key={v}
              className={`mark ${i <= currentIndex ? 'filled' : ''}`}
              style={{ left: `${(i / (values.length - 1)) * 100}%` }}
            />
          ))}
        </div>
      </div>
      <div className="slider-ticks">
        {values.map(v => (
          <span key={v} className="tick">{v}</span>
        ))}
      </div>
    </div>
  );
};

const ConfigSliders = ({ config, onChange }) => {
  return (
    <div className="config-sliders">
      <DiscreteSlider
        label="Window (full fidelity turns)"
        values={WINDOW_VALUES}
        value={config.window}
        onChange={(v) => onChange({ ...config, window: v })}
      />
      <DiscreteSlider
        label="Mask After (turns before masking)"
        values={MASK_AFTER_VALUES}
        value={config.mask_after}
        onChange={(v) => onChange({ ...config, mask_after: v })}
      />
      <DiscreteSlider
        label="Min Masked Size (chars)"
        values={MIN_SIZE_VALUES}
        value={config.min_size}
        onChange={(v) => onChange({ ...config, min_size: v })}
      />
    </div>
  );
};

export default ConfigSliders;
```

### 3.3 Compression Timeline Chart

**File**: `studio/frontend/src/components/CompressionTimeline.jsx`

```jsx
import React, { useRef, useEffect } from 'react';

const CompressionTimeline = ({ turns, config }) => {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Setup
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, width, height);

    // Margins
    const margin = { top: 20, right: 20, bottom: 30, left: 50 };
    const chartWidth = width - margin.left - margin.right;
    const chartHeight = height - margin.top - margin.bottom;

    // Find matching config data for each turn
    const dataPoints = turns.map(turn => {
      const matchingConfig = turn.configs.find(c =>
        c.window === config.window &&
        c.mask_after === config.mask_after &&
        c.min_size === config.min_size
      );
      return {
        turn: turn.turn_number,
        before: matchingConfig?.tokens_before || 0,
        after: matchingConfig?.tokens_after || 0
      };
    });

    // Scales
    const maxTokens = Math.max(...dataPoints.flatMap(d => [d.before, d.after]));
    const xScale = (turn) => margin.left + (turn / (dataPoints.length - 1 || 1)) * chartWidth;
    const yScale = (tokens) => margin.top + chartHeight - (tokens / maxTokens) * chartHeight;

    // Draw "Before" line
    ctx.beginPath();
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    dataPoints.forEach((d, i) => {
      if (i === 0) ctx.moveTo(xScale(i), yScale(d.before));
      else ctx.lineTo(xScale(i), yScale(d.before));
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw "After" line
    ctx.beginPath();
    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 2;
    dataPoints.forEach((d, i) => {
      if (i === 0) ctx.moveTo(xScale(i), yScale(d.after));
      else ctx.lineTo(xScale(i), yScale(d.after));
    });
    ctx.stroke();

    // Fill area between
    ctx.beginPath();
    ctx.fillStyle = 'rgba(0, 229, 255, 0.1)';
    dataPoints.forEach((d, i) => {
      if (i === 0) ctx.moveTo(xScale(i), yScale(d.before));
      else ctx.lineTo(xScale(i), yScale(d.before));
    });
    for (let i = dataPoints.length - 1; i >= 0; i--) {
      ctx.lineTo(xScale(i), yScale(dataPoints[i].after));
    }
    ctx.closePath();
    ctx.fill();

    // Axes
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, height - margin.bottom);
    ctx.lineTo(width - margin.right, height - margin.bottom);
    ctx.stroke();

    // Labels
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Turn', width / 2, height - 5);

    ctx.save();
    ctx.translate(12, height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Tokens', 0, 0);
    ctx.restore();

  }, [turns, config]);

  return (
    <div className="compression-timeline">
      <div className="timeline-legend">
        <span className="legend-item before">── Before</span>
        <span className="legend-item after">── After (shadow)</span>
      </div>
      <canvas ref={canvasRef} style={{ width: '100%', height: 200 }} />
    </div>
  );
};

export default CompressionTimeline;
```

---

## SQL Queries Reference

### Sessions with Shadow Data
```sql
SELECT DISTINCT
    csa.session_id,
    csa.cascade_id,
    MIN(csa.timestamp) as first_assessment,
    MAX(csa.timestamp) as last_assessment,
    COUNT(DISTINCT csa.target_cell) as cells_assessed,
    COUNT(*) as total_assessments
FROM context_shadow_assessments csa
WHERE csa.timestamp >= now() - INTERVAL 7 DAY
GROUP BY csa.session_id, csa.cascade_id
ORDER BY last_assessment DESC
```

### Best Intra-Phase Config per Cascade
```sql
SELECT
    cascade_id,
    config_window,
    config_mask_after,
    config_min_masked_size,
    AVG(compression_ratio) as avg_compression,
    SUM(tokens_saved) as total_tokens_saved,
    COUNT(DISTINCT session_id) as session_count
FROM intra_context_shadow_assessments
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY cascade_id, config_window, config_mask_after, config_min_masked_size
ORDER BY cascade_id, total_tokens_saved DESC
```

### Inter-Phase Messages with Relevance
```sql
SELECT
    csa.content_hash,
    csa.source_cell,
    csa.target_cell,
    csa.role,
    csa.tokens,
    csa.heuristic_score,
    csa.semantic_score,
    csa.composite_score,
    csa.rank_composite,
    csa.would_include_composite,
    csa.actual_included,
    ccb.relevance_score,
    ccb.relevance_reasoning
FROM context_shadow_assessments csa
LEFT JOIN cell_context_breakdown ccb ON (
    ccb.session_id = csa.session_id
    AND ccb.cell_name = csa.target_cell
    AND startsWith(ccb.context_message_hash, substring(csa.content_hash, 1, 8))
)
WHERE csa.session_id = 'SESSION_ID'
  AND csa.token_budget = 30000
ORDER BY csa.target_cell, csa.rank_composite
```

### Waste Analysis (High Cost, Low Relevance)
```sql
SELECT
    session_id,
    cell_name,
    context_message_hash,
    context_message_tokens,
    context_message_cost_estimated,
    relevance_score,
    relevance_reasoning
FROM cell_context_breakdown
WHERE session_id = 'SESSION_ID'
  AND relevance_score IS NOT NULL
  AND relevance_score < 40
  AND context_message_tokens > 200
ORDER BY context_message_cost_estimated DESC
```

### Compression Comparison by Config
```sql
SELECT
    config_window,
    config_mask_after,
    config_min_masked_size,
    AVG(compression_ratio) as avg_ratio,
    AVG(tokens_saved) as avg_saved,
    MIN(compression_ratio) as best_ratio,
    MAX(compression_ratio) as worst_ratio
FROM intra_context_shadow_assessments
WHERE session_id = 'SESSION_ID'
GROUP BY config_window, config_mask_after, config_min_masked_size
ORDER BY avg_saved DESC
```

---

## Component Architecture

```
receipts/
├── ReceiptsView.jsx                    # Main view (add assessment tab)
├── components/
│   ├── OverviewPanel.jsx               # (existing)
│   ├── AlertsPanel.jsx                 # (existing)
│   ├── ContextBreakdownPanel.jsx       # (existing)
│   └── context-assessment/
│       ├── ContextAssessmentPanel.jsx  # Main assessment container
│       ├── AssessmentOverview.jsx      # Overview cards
│       ├── SessionSelector.jsx         # Session/cascade picker
│       ├── InterPhaseExplorer.jsx      # Strategy explorer with budget slider
│       ├── IntraPhaseExplorer.jsx      # Config explorer with param sliders
│       ├── EnhancedContextMatrix.jsx   # Extended matrix with overlays
│       ├── MessageDetailSidebar.jsx    # Full message info panel
│       ├── RelevanceScatter.jsx        # Value vs cost scatter plot
│       ├── ConfigRecommendations.jsx   # Best config suggestions
│       ├── CandidateComparison.jsx     # Multi-candidate view
│       └── styles/
│           ├── ContextAssessmentPanel.css
│           ├── InterPhaseExplorer.css
│           ├── IntraPhaseExplorer.css
│           └── ...

components/
├── BudgetSlider.jsx                    # Reusable budget slider
├── ConfigSliders.jsx                   # Intra-phase config sliders
├── CompressionTimeline.jsx             # Token timeline chart
├── RelevanceBar.jsx                    # 10-block relevance display
└── StrategyRankings.jsx                # Side-by-side strategy columns
```

---

## Design Tokens

### Colors

```css
:root {
  /* Relevance Colors */
  --relevance-high: #34d399;      /* Green (70-100) */
  --relevance-medium: #fbbf24;    /* Yellow (40-69) */
  --relevance-low: #f87171;       /* Red (0-39) */

  /* Shadow Overlay */
  --shadow-exclude: rgba(255, 255, 255, 0.3);
  --shadow-include: rgba(0, 229, 255, 0.2);

  /* Strategy Colors */
  --strategy-heuristic: #a78bfa;  /* Purple */
  --strategy-semantic: #60a5fa;   /* Blue */
  --strategy-llm: #34d399;        /* Green */
  --strategy-composite: #fbbf24;  /* Yellow */

  /* Config Sliders */
  --slider-track: #2a2a32;
  --slider-fill: #00e5ff;
  --slider-thumb: #ffffff;
}
```

### Typography

```css
.assessment-title { font-size: 18px; font-weight: 600; }
.assessment-subtitle { font-size: 14px; color: #94a3b8; }
.metric-value { font-size: 24px; font-weight: 600; }
.metric-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.code-hash { font-family: 'Monaco', monospace; font-size: 11px; }
```

---

## Next Steps

After completing this plan document:

1. **Review with stakeholder** - Confirm priorities and scope
2. **Create feature branch** - `feature/context-assessment-ui`
3. **Begin Phase 1** - Backend API + basic tab structure
4. **Iterate** - Get feedback after each phase before proceeding

---

*Document created: 2025-12-30*
*Last updated: 2025-12-30*
