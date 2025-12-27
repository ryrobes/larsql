# Receipts Page Design - Cost & Reliability Explorer

**Route:** `/#/receipts`
**Purpose:** Operational cost intelligence with drill-down attribution
**Philosophy:** Not just "billing" - a **debuggable ledger** that answers questions

---

## Core Questions to Answer

1. **"What's driving spend this week?"**
   - Show cascades ranked by cost
   - Highlight regressions (cost up X% vs last week)
   - Group by genus_hash (invocation patterns)

2. **"What regressed since yesterday?"**
   - Automatic regression detection (genus-level comparison)
   - Show severity (minor/major/critical)
   - Link to specific sessions

3. **"Which cell/trait/candidate is responsible?"**
   - Drill-down from cascade → cells → context messages
   - Cost attribution at every level
   - Context hotspot detection

4. **"What's the cheapest safe configuration?"**
   - Model comparison by species_hash
   - Cost/quality Pareto frontier
   - "Try model X for 30% savings"

5. **"What should I alert on?"**
   - Outliers (|z| > 2)
   - Regressions (>20% cost increase)
   - Context hotspots (>60% context cost)

---

## Page Architecture

### **Three-Panel Layout** (Studio style)

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Receipts · Cost & Reliability Explorer             │
│ Time Range: [Last 7 Days ▼] · Cascade: [All ▼]            │
├──────────────┬──────────────────────────────────────────────┤
│              │                                              │
│  LEFT PANEL  │           MAIN CONTENT AREA                 │
│  (Navigator) │                                              │
│              │  ┌────────────────────────────────────────┐ │
│ 📊 Overview  │  │  Current View:                         │ │
│ 🔴 Alerts    │  │  - Overview (KPIs + trends)            │ │
│ 📈 Cascades  │  │  - Alerts (outliers + regressions)     │ │
│ 🧩 Cells     │  │  - Cascade Explorer (ranked list)      │ │
│ 💬 Context   │  │  - Cell Breakdown (bottlenecks)        │ │
│ 🏆 Models    │  │  - Context Attribution (bloat sources) │ │
│              │  └────────────────────────────────────────┘ │
│              │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

---

## View 1: Overview Dashboard

**KPI Cards** (Top row, shared card components)

```
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Total Cost      │ Avg per Run     │ Context Cost    │ Outliers        │
│ $12.45          │ $0.015          │ 42% hidden      │ 3 sessions      │
│ ↑ 15% vs last   │ ↓ 8% vs last    │ ↑ 5% vs last    │ 🔴 2 critical   │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

**Trend Charts** (CostTimelineChart component, already exists!)

```
┌──────────────────────────────────────────────────────────────┐
│ Cost Trend (7 days)                                          │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Cost                                                    │  │
│ │  │    ╱╲                                                │  │
│ │  │   ╱  ╲      ╱╲                                       │  │
│ │  │  ╱    ╲    ╱  ╲                                      │  │
│ │  │─╱──────╲──╱────╲─────                                │  │
│ │  Mon  Tue  Wed  Thu  Fri  Sat  Sun                      │  │
│ │                                                          │  │
│ │ Layers: Context (red) | New Messages (green)            │  │
│ └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Human-Readable Insights** (Generated from analytics!)

```
┌──────────────────────────────────────────────────────────────┐
│ 💬 What's Happening                                          │
├──────────────────────────────────────────────────────────────┤
│ 🔴 "Cell 'enrich' in extract_brand is 3.2σ above normal.    │
│     Context injection from 'research' cell accounts for      │
│     78% of cost. Consider selective context."                │
│                                                              │
│ 🟡 "Cascade 'analyze_data' costs increased 31% this week.   │
│     Regression detected in genus abc123. Last known good:    │
│     session xyz789 (cost: $0.012)."                          │
│                                                              │
│ 🟢 "No anomalies detected in last 24 hours."                │
└──────────────────────────────────────────────────────────────┘
```

---

## View 2: Alerts & Anomalies

**Filter/Sort Controls:**
```
Severity: [All ▼] [Critical] [Major] [Minor]
Type: [All ▼] [Cost Outliers] [Regressions] [Context Hotspots]
Time: [Last 7 Days ▼]
```

**Alert List** (ag-grid, like Console)

| Severity | Type | Cascade | Cell | Description | Z-Score | Action |
|----------|------|---------|------|-------------|---------|--------|
| 🔴 Critical | Cost Outlier | extract_brand | enrich | 3.5σ above cluster avg | 3.5 | [View] |
| 🔴 Critical | Regression | analyze_data | - | +45% cost vs last week | - | [Compare] |
| 🟡 Major | Context Hotspot | summarize | final | 82% context cost | - | [Details] |
| 🟢 Minor | Duration Outlier | validate | check | 2.1σ slower | 2.1 | [View] |

**Click Action** → Opens drill-down panel with:
- Session details
- Baseline comparisons (cluster, genus, species)
- Recommended actions
- Link to Studio session

---

## View 3: Cascade Explorer

**Cascade Ranking Table** (ag-grid with rich tooltips)

| Cascade | Genus | Runs | Total Cost | Avg Cost | Context % | Outliers | Trend |
|---------|-------|------|------------|----------|-----------|----------|-------|
| extract_brand | fd2dc2ae | 45 | $0.542 | $0.012 | 42% | 3 | ↑ 15% |
| analyze_data | a1b2c3d4 | 23 | $0.345 | $0.015 | 65% | 0 | ↓ 8% |
| enrich_content | x9y8z7w6 | 12 | $1.234 | $0.103 | 78% 🔴 | 2 | ↑ 31% |

**Columns:**
- **Cascade:** Name (clickable → drill-down)
- **Genus:** Hash (truncated, tooltip shows full)
- **Runs:** Count (filterable by time range)
- **Total Cost:** Sum (sortable)
- **Avg Cost:** Mean (with cluster comparison)
- **Context %:** Hidden cost visibility! 🎯
- **Outliers:** Count of anomalous sessions
- **Trend:** % change vs previous period (↑/↓ with color)

**Drill-Down:** Click cascade → Shows:
- Session list for this genus
- Cost distribution histogram
- Cell breakdown
- Input clustering (fingerprints)

---

## View 4: Cell Breakdown

**Cell Cost Attribution** (Treemap or Sunburst chart!)

```
┌──────────────────────────────────────────────────────────────┐
│ Cell Cost Attribution (Cascade: extract_brand)               │
│                                                              │
│  ┌─────────────────────┐  ┌──────────┐  ┌─────────────┐    │
│  │    research         │  │ validate │  │  enrich     │    │
│  │    $0.002 (15%)     │  │ $0.001   │  │  $0.009     │    │
│  │                     │  │ (8%)     │  │  (77%) 🔴   │    │
│  │  Context: 10%       │  │          │  │              │    │
│  │  New: 90%           │  │  Context │  │  Context:   │    │
│  └─────────────────────┘  │  20%     │  │  82% 🔴     │    │
│                           └──────────┘  │              │    │
│                                        └─────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**Cell Performance Table**

| Cell | Type | Cost | Duration | Context % | Z-Score | Anomaly | Bottleneck |
|------|------|------|----------|-----------|---------|---------|------------|
| enrich | LLM | $0.009 | 3200ms | 82% 🔴 | 3.2 | 🔴 Outlier | 77% of cascade |
| research | LLM | $0.002 | 800ms | 10% | 0.3 | ✅ Normal | 15% of cascade |
| validate | LLM | $0.001 | 400ms | 20% | -0.5 | ✅ Normal | 8% of cascade |

**Drill-Down:** Click cell → Shows:
- Species-level comparison (same cell config over time)
- Context message breakdown (which messages bloat this cell)
- Model comparison (if candidates used)
- Recommended optimizations

---

## View 5: Context Attribution

**Bloat Source Analysis** (Sankey diagram or flow chart)

```
Context Flow Visualization:

research (output: 150 tokens)
    ↓ injected into
analyze (cost: +$0.0003 context overhead)
    ↓ output: 300 tokens
    ↓ injected into
enrich (cost: +$0.0008 context overhead) ← 🔴 HOTSPOT
    ↓ output: 450 tokens
    ↓ injected into
summarize (cost: +$0.0012 context overhead) ← 🔴 CRITICAL

Total context cost: $0.0023 (67% of cascade!)
```

**Context Breakdown Table** (cell_context_breakdown data)

| Cell | Context Msg | Source Cell | Tokens | Cost | % of Cell | Impact |
|------|-------------|-------------|--------|------|-----------|--------|
| summarize | 0afee76... | summarize (user) | 484 | $0.000743 | 104% | 🔴 BLOAT! |
| analyze | af8e6a6... | analyze (user) | 127 | $0.000400 | 35.7% | 🟡 High |
| research | 43e5d01... | research (user) | 14 | $0.000046 | 15.4% | 🟢 Normal |

**Actions:**
- "Exclude message 0afee76 from context" button
- "Use selective context for 'summarize' cell" recommendation
- "Potential savings: $0.000743 (52%)"

---

## View 6: Model Comparison

**Cost/Quality Matrix** (Scatter plot)

```
Quality │
  1.0   │        ● Claude Opus (best, expensive)
        │       /
  0.9   │      ● GPT-4 (balanced)
        │     /
  0.8   │    ● Gemini (cheaper, good)
        │   /
  0.7   │  ● Haiku (cheapest)
        │
        └──────────────────────────────── Cost
          $0.001  $0.005  $0.010  $0.015
```

**Model Rankings** (species_hash filtered!)

| Model | Runs | Win Rate | Avg Cost | Cost/Win | Recommendation |
|-------|------|----------|----------|----------|----------------|
| claude-opus-4 | 12 | 92% | $0.0145 | $0.0158 | Best quality |
| gpt-4-turbo | 23 | 87% | $0.0098 | $0.0113 | ✅ Balanced |
| gemini-2.0 | 45 | 79% | $0.0032 | $0.0041 | Budget option |
| haiku | 34 | 71% | $0.0012 | $0.0017 | Cheapest |

**Pareto Frontier:** Highlight models on efficiency curve

---

## Human-Readable Insights (AI-Generated Summaries)

### **Insight Generator Function**

```python
def generate_insights(analytics_data):
    """
    Turn analytics into human-readable sentences.

    Uses rules + templates to explain non-nominal behavior.
    """
    insights = []

    # Check for cost outliers
    outliers = [row for row in analytics_data if row['is_cost_outlier']]
    if outliers:
        for outlier in outliers[:3]:  # Top 3
            cell_info = f" in cell '{outlier['cell_name']}'" if outlier.get('cell_name') else ""
            insights.append({
                'severity': 'critical',
                'type': 'outlier',
                'message': f"Cascade '{outlier['cascade_id']}'{cell_info} is {abs(outlier['cost_z_score']):.1f}σ above normal. "
                          f"Cost: ${outlier['total_cost']:.4f} vs cluster avg ${outlier['cluster_avg_cost']:.4f}. "
                          f"This is unusual for {outlier['input_category']} inputs.",
                'action': f"Investigate session {outlier['session_id']}"
            })

    # Check for context hotspots
    context_hotspots = [row for row in analytics_data if row.get('context_cost_pct', 0) > 60]
    if context_hotspots:
        for hotspot in context_hotspots[:3]:
            insights.append({
                'severity': 'warning',
                'type': 'context_hotspot',
                'message': f"Cell '{hotspot['cell_name']}' spends {hotspot['context_cost_pct']:.0f}% of cost on context injection. "
                          f"Context overhead: ${hotspot['context_cost_estimated']:.4f}. "
                          f"Consider selective context to save {hotspot['context_cost_pct']:.0f}%.",
                'action': "View context breakdown"
            })

    # Check for regressions
    regressions = [row for row in analytics_data if row.get('is_regression')]
    if regressions:
        for regression in regressions:
            insights.append({
                'severity': regression['regression_severity'],
                'type': 'regression',
                'message': f"Cascade '{regression['cascade_id']}' regressed {regression['vs_recent_avg_cost']:.0f}% "
                          f"in cost vs last 10 runs. Previous average: ${regression['species_avg_cost']:.4f}.",
                'action': "Compare to baseline"
            })

    # No anomalies
    if not insights:
        insights.append({
            'severity': 'info',
            'type': 'normal',
            'message': "No anomalies detected in last 24 hours. All cascades performing within normal parameters.",
            'action': None
        })

    return insights
```

**Display:**
```
┌──────────────────────────────────────────────────────────────┐
│ 💬 Operational Intelligence                                  │
├──────────────────────────────────────────────────────────────┤
│ 🔴 Cell 'enrich' in extract_brand is 3.2σ above normal.     │
│    Cost: $0.0145 vs cluster avg $0.0042.                    │
│    This is unusual for medium inputs.                        │
│    → [Investigate session abc123]                            │
│                                                              │
│ 🟡 Cell 'summarize' spends 78% of cost on context injection.│
│    Context overhead: $0.0089.                                │
│    Consider selective context to save 78%.                   │
│    → [View context breakdown]                                │
│                                                              │
│ 🟢 No regressions detected vs last week.                    │
└──────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### **Shared Components** (from Studio/AppShell)

1. **Layout:**
   - `AppShell` wrapper (consistent navigation)
   - `Split` panels (react-split, like Studio)
   - Header component

2. **Cards:**
   - KPI cards (reuse from Dashboard)
   - Metric cards with trend indicators

3. **Charts:**
   - `CostTimelineChart` (already exists!)
   - Stacked area for context vs new cost
   - Sunburst for cell attribution

4. **Tables:**
   - ag-grid (like Console)
   - Rich tooltips (RichTooltip component)
   - Context menus for actions

5. **Navigation:**
   - Left sidebar (like CascadeNavigator)
   - Collapsible sections
   - Active state highlighting

---

## Data Flow

### **API Endpoints Needed:**

```javascript
// Overview KPIs
GET /api/receipts/overview?days=7
Response: {
  total_cost, avg_cost, context_pct, outlier_count,
  trend_vs_previous: +15%,
  insights: [{severity, type, message, action}]
}

// Cascade rankings
GET /api/receipts/cascades?sort=cost&order=desc&days=7
Response: [{
  cascade_id, genus_hash, run_count, total_cost, avg_cost,
  context_pct, outlier_count, trend_pct
}]

// Cell breakdown for cascade
GET /api/receipts/cells?cascade_id=X&genus_hash=Y
Response: [{
  cell_name, cell_cost, cell_pct, context_pct,
  is_outlier, is_bottleneck
}]

// Granular context attribution
GET /api/receipts/context-breakdown?session_id=X&cell_name=Y
Response: [{
  context_message_hash, source_cell, tokens,
  cost_estimated, pct_of_cell
}]

// Regression detection
GET /api/receipts/regressions?days=7
Response: [{
  cascade_id, genus_hash, cost_change_pct,
  severity, baseline_session_id
}]
```

---

## Interactive Features

### **Drill-Down Flow:**

```
Overview
  ↓ Click "3 outliers"
Alerts View (filtered to outliers)
  ↓ Click specific alert
Cascade Detail (that cascade's cells)
  ↓ Click bottleneck cell
Context Breakdown (per-message attribution)
  ↓ Click bloated message
Studio Session View (full context, outputs, etc.)
```

### **Comparison Mode:**

```
Compare two sessions:
  Session A (baseline):    $0.012 cost, 1200ms
  Session B (regression):  $0.018 cost, 1800ms

  Diff Breakdown:
    ├─ Cell 'enrich':  +$0.005 (+83%) ← CAUSE
    ├─ Cell 'research': +$0.001 (+12%)
    └─ Cell 'validate': $0.000 (unchanged)

  Root Cause: 'enrich' context injection grew from 2 to 5 messages
```

### **Actionable Buttons:**

```
[Set Alert Threshold]    → Configure when to notify
[Exclude from Context]   → Remove bloated message
[Switch to Model X]      → Use cheaper alternative
[View in Studio]         → Full session details
[Compare to Baseline]    → Side-by-side diff
[Export Report]          → PDF/CSV
```

---

## Visual Design (Studio Style)

### **Color Palette:**

```javascript
const RECEIPT_COLORS = {
  // Severity
  critical: '#ff006e',    // Hot pink (outliers, alerts)
  major: '#fbbf24',       // Yellow (warnings)
  minor: '#60a5fa',       // Blue (info)
  normal: '#34d399',      // Green (all good)

  // Cost types
  context: '#a78bfa',     // Purple (hidden costs)
  newWork: '#00e5ff',     // Cyan (visible costs)

  // Metrics
  cost: '#34d399',        // Green
  duration: '#60a5fa',    // Blue
  tokens: '#fbbf24',      // Yellow

  // Background
  bg: '#0a0a0a',          // Pure black (Studio style)
  cardBg: '#121212',      // Dark cards
  border: '#1a1628',      // Subtle borders
}
```

### **Typography:**

```css
/* KPI Numbers */
.kpi-value {
  font-size: 32px;
  font-weight: 700;
  font-family: 'Google Sans Code', monospace;
  color: #f0f4f8;
}

/* Trends */
.trend-indicator {
  font-size: 14px;
  font-weight: 600;
  color: var(--trend-color); /* Green for ↓, Red for ↑ cost */
}

/* Insights */
.insight-message {
  font-size: 14px;
  line-height: 1.6;
  color: #cbd5e1;
  font-family: 'Google Sans', sans-serif;
}
```

---

## Implementation Roadmap

### **Phase A: Backend APIs** (1-2 days)
1. Create `receipts_api.py` blueprint
2. Implement overview endpoint
3. Implement cascade rankings endpoint
4. Implement cell breakdown endpoint
5. Implement context attribution endpoint
6. Implement insight generator

### **Phase B: Frontend Shell** (1 day)
1. Create `ReceiptsView.jsx`
2. Set up three-panel layout (AppShell + Split)
3. Left navigator (view switcher)
4. Header with filters (time range, cascade selector)

### **Phase C: Overview Dashboard** (1 day)
1. KPI cards
2. Trend chart (reuse CostTimelineChart)
3. Insights panel with human-readable messages

### **Phase D: Drill-Down Views** (2-3 days)
1. Alerts table (ag-grid)
2. Cascade explorer (ranking table)
3. Cell breakdown (treemap + table)
4. Context attribution (granular table)

### **Phase E: Interactive Features** (1-2 days)
1. Drill-down navigation
2. Comparison mode
3. Actionable buttons
4. Export functionality

---

## Sample Queries for Insights

### **Find Top Cost Drivers:**
```sql
SELECT
    cascade_id,
    SUM(total_cost) as cost,
    AVG(context_cost_pct) as avg_context_pct
FROM cascade_analytics
WHERE created_at > now() - INTERVAL 7 DAY
GROUP BY cascade_id
ORDER BY cost DESC
LIMIT 10
```

### **Detect Regressions:**
```sql
WITH recent AS (
    SELECT genus_hash, AVG(total_cost) as recent_avg
    FROM cascade_analytics
    WHERE created_at > now() - INTERVAL 7 DAY
    GROUP BY genus_hash
),
historical AS (
    SELECT genus_hash, AVG(total_cost) as historical_avg
    FROM cascade_analytics
    WHERE created_at BETWEEN now() - INTERVAL 30 DAY AND now() - INTERVAL 7 DAY
    GROUP BY genus_hash
)
SELECT
    r.genus_hash,
    r.recent_avg,
    h.historical_avg,
    ((r.recent_avg - h.historical_avg) / h.historical_avg * 100) as pct_change
FROM recent r
JOIN historical h ON r.genus_hash = h.genus_hash
WHERE pct_change > 20
ORDER BY pct_change DESC
```

### **Find Context Hotspots:**
```sql
SELECT
    cascade_id,
    cell_name,
    AVG(context_cost_pct) as avg_context_pct,
    COUNT(*) as occurrence_count
FROM cell_analytics
WHERE context_cost_pct > 60
GROUP BY cascade_id, cell_name
ORDER BY avg_context_pct DESC
```

### **Cell Bottlenecks:**
```sql
SELECT
    cascade_id,
    cell_name,
    AVG(cell_duration_pct) as avg_duration_pct,
    AVG(cell_cost_pct) as avg_cost_pct
FROM cell_analytics
GROUP BY cascade_id, cell_name
HAVING avg_duration_pct > 40 OR avg_cost_pct > 40
ORDER BY avg_cost_pct DESC
```

---

## Key Features

### **1. Compare**
- Cascade vs cascade (by genus)
- Session vs session (A/B comparison)
- This week vs last week (regression detection)
- Model vs model (cost/quality tradeoffs)

### **2. Rank**
- Most expensive cascades
- Slowest cells
- Biggest context bloat sources
- Most efficient models

### **3. Detect Regressions**
- Genus-level trending (same invocation over time)
- Species-level trending (same cell config)
- Automatic alerts when cost/duration increases >20%
- Severity classification (minor/major/critical)

### **4. Attribute Cost**
- Cascade → Cells (% breakdown)
- Cell → Context vs New (hidden costs!)
- Context → Specific messages (exact bloat source)
- Models → Per-species comparison

### **5. Turn Insights into Actions**
- Set alert thresholds
- Configure budgets (per cascade/genus)
- Exclude messages from context
- Switch to cheaper models
- Export reports

---

## Success Metrics

**Page should answer:**
✅ "Why did my bill increase 30%?" → Show regression + drill to cell/message
✅ "Which cascade is most expensive?" → Ranked list with genus grouping
✅ "Where should I optimize first?" → Bottleneck detection + ROI estimate
✅ "Is this session abnormal?" → Z-score + cluster comparison
✅ "What's hiding in context?" → Per-message attribution

---

## My Thoughts

This would be **groundbreaking** - no other LLM framework has:
1. **Context cost attribution** (unique to RVBBIT!)
2. **Statistical anomaly detection** (Z-scores, not just percentages)
3. **Genus/species taxonomy** (compare apples to apples)
4. **Granular drill-down** (cascade → cell → message)
5. **Human-readable insights** (explain WHY something is anomalous)

**Recommended MVP:**
- Start with **Overview + Alerts** (highest value)
- Add **Cascade Explorer** (rankings + comparisons)
- Then **Cell Breakdown** (bottleneck detection)
- Finally **Context Attribution** (most complex, most unique)

**Estimated effort:**
- Backend: 2-3 days (APIs + insight generator)
- Frontend: 3-4 days (views + drill-down)
- **Total: ~1 week for full implementation**

Want me to start building? I can begin with:
1. **Backend APIs** (receipts_api.py + insight generator)
2. **Basic frontend shell** (layout + overview)
3. **Or just design mockups** (wireframes/component specs)

What's your preference? 🎯
