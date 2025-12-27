# Receipts Page - Implementation Guide

**Status:** Backend Complete, Frontend Needed
**Estimated Effort:** 2-3 days for MVP
**Route:** `/#/receipts`

---

## Executive Summary

Build a **Cost & Reliability Explorer** page that transforms pre-computed analytics data into actionable operational intelligence. Not just "billing" - a **debuggable ledger** that answers critical questions like "What's driving spend?", "What regressed?", and "Where should I optimize?"

---

## The Problem We're Solving

### Traditional Cost Tracking is Broken

**Other LLM frameworks show:**
- "Total cost this week: $45.23" ❌ (so what?)
- "Cascade X costs $0.15" ❌ (is that good or bad?)
- Context costs are invisible ❌ (60-80% of spend is hidden!)

**What's missing:**
- **Context:** Is $0.15 normal for this input size?
- **Attribution:** Which cell is expensive? Which message bloats context?
- **Trends:** Did cost increase? By how much? Why?
- **Actions:** What should I do about it?

### RVBBIT's Unique Capabilities

**We have data no one else has:**
1. **Context attribution** - Track which messages were injected into each LLM call
2. **Statistical baselines** - Compare to cluster (same input size) not global average
3. **Granular drill-down** - Cascade → Cell → Context Message
4. **Hash taxonomy** - genus_hash (cascade invocation) + species_hash (cell config)

**The Receipts page surfaces this as actionable intelligence.**

---

## What's Already Built (Backend)

### 1. Analytics Tables (All Pre-Computed)

#### **CASCADE_ANALYTICS** (~60 records)
Whole cascade metrics with context-aware baselines.

**Key Columns:**
```sql
-- Identity
session_id, cascade_id, genus_hash, created_at

-- Metrics
total_cost, total_duration_ms, message_count, cell_count

-- Baselines (context-aware!)
global_avg_cost          -- All runs of this cascade
cluster_avg_cost         -- Same input size category
genus_avg_cost           -- Same genus_hash (exact invocation)
cluster_stddev_cost      -- For Z-scores

-- Anomaly Detection
cost_z_score             -- (cost - cluster_avg) / cluster_stddev
is_cost_outlier          -- |z| > 2 (top/bottom 5%)

-- Context Attribution (UNIQUE!)
total_context_cost_estimated    -- Cost from context injection
total_new_cost_estimated        -- Cost from new messages
context_cost_pct                -- % of cost that's hidden context
cells_with_context              -- How many cells have context
avg_cell_context_pct            -- Average context % across cells
max_cell_context_pct            -- Peak context hotspot

-- Efficiency
cost_per_message, cost_per_token, input_category, input_complexity_score
```

#### **CELL_ANALYTICS** (~10 records)
Per-cell metrics with bottleneck detection.

**Key Columns:**
```sql
-- Identity
session_id, cascade_id, cell_name, species_hash, cell_index

-- Metrics
cell_cost, cell_duration_ms, cell_tokens

-- Attribution
cell_cost_pct                   -- % of total cascade cost
cell_duration_pct               -- % of total cascade duration

-- Baselines
species_avg_cost                -- Same cell config (species_hash)
species_stddev_cost             -- For Z-scores

-- Anomaly Detection
cost_z_score, is_cost_outlier

-- Context Attribution (UNIQUE!)
context_cost_estimated          -- Cost from injected context
new_message_cost_estimated      -- Cost from THIS cell's work
context_cost_pct                -- % of cell cost that's context
context_depth_avg               -- Avg messages in context
```

#### **CELL_CONTEXT_BREAKDOWN** (~20 records)
Per-message granular attribution.

**Key Columns:**
```sql
-- Which cell are we analyzing?
session_id, cell_name, cell_index

-- Which message bloats it?
context_message_hash            -- content_hash of bloat source
context_message_cell            -- Which cell produced it
context_message_tokens          -- How many tokens
context_message_cost_estimated  -- Estimated cost impact
context_message_pct             -- % of cell cost from THIS message
```

**Example Data:**
```
Cell 'summarize':
  Context message 0afee76 from 'summarize' (user): 484 tokens, $0.000743 (104% of cell!)
```

### 2. Backend API (Ready to Use)

**File:** `dashboard/backend/receipts_api.py`

**Endpoints:**

#### GET `/api/receipts/overview?days=7`
Returns KPIs, trends, and human-readable insights.

**Response:**
```json
{
  "kpis": {
    "session_count": 45,
    "total_cost": 12.45,
    "avg_cost": 0.015,
    "avg_context_pct": 42.3,
    "outlier_count": 3
  },
  "trends": {
    "cost_change_pct": 15.2,
    "context_change_pct": 5.1
  },
  "insights": [
    {
      "severity": "critical",
      "type": "outlier",
      "message": "Cascade 'extract_brand' in cell 'enrich' is 3.2σ above normal. Cost: $0.0145 vs cluster avg $0.0042. This is unusual for medium inputs.",
      "action": {"type": "view_session", "cascade_id": "extract_brand"}
    }
  ]
}
```

#### GET `/api/receipts/alerts?days=7&severity=all&type=all`
Returns anomalies, regressions, context hotspots.

**Response:**
```json
{
  "alerts": [
    {
      "severity": "critical",
      "type": "cost_outlier",
      "cascade_id": "extract_brand",
      "session_id": "abc123",
      "z_score": 3.5,
      "message": "Cascade 'extract_brand' cost is 3.5σ above normal",
      "action": "investigate_session",
      "timestamp": "2025-12-27T10:30:00"
    },
    {
      "severity": "major",
      "type": "context_hotspot",
      "cascade_id": "analyze_data",
      "cell_name": "enrich",
      "context_pct": 78.5,
      "message": "Cell 'enrich' has 78% context overhead",
      "action": "view_context_breakdown"
    }
  ]
}
```

### 3. Insight Generator

**Function:** `_generate_insights(db, days)` in `receipts_api.py`

Generates human-readable sentences from analytics:
- Cost outliers with Z-score context
- Context hotspots with savings potential
- Regressions (when implemented)

**Example output:**
```
🔴 "Cell 'enrich' in extract_brand is 3.2σ above normal.
    Cost: $0.0145 vs cluster avg $0.0042.
    This is unusual for medium inputs."

🟡 "Cell 'summarize' spends 78% on context injection.
    Context overhead: $0.0089.
    Consider selective context to save 78%."
```

---

## What Needs to Be Built (Frontend)

### File Structure

```
dashboard/frontend/src/views/receipts/
├── ReceiptsView.jsx         # Main page component
├── ReceiptsView.css         # Styling (Studio aesthetic)
├── components/
│   ├── OverviewPanel.jsx    # KPIs + trends + insights
│   ├── AlertsPanel.jsx      # Anomaly table
│   ├── KPICard.jsx          # Reusable metric card
│   └── InsightCard.jsx      # Human-readable insight display
└── index.js                 # Exports
```

### Required Components

#### 1. **ReceiptsView.jsx** (Main Shell)

**Purpose:** Three-panel layout matching Studio aesthetic

**Structure:**
```jsx
import React, { useState, useEffect } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import OverviewPanel from './components/OverviewPanel';
import AlertsPanel from './components/AlertsPanel';
import './ReceiptsView.css';

function ReceiptsView() {
  const [activeView, setActiveView] = useState('overview');
  const [timeRange, setTimeRange] = useState(7); // days
  const [overviewData, setOverviewData] = useState(null);
  const [alertsData, setAlertsData] = useState([]);

  // Fetch overview data
  useEffect(() => {
    fetch(`http://localhost:5001/api/receipts/overview?days=${timeRange}`)
      .then(res => res.json())
      .then(data => setOverviewData(data));
  }, [timeRange]);

  // Fetch alerts data
  useEffect(() => {
    fetch(`http://localhost:5001/api/receipts/alerts?days=${timeRange}`)
      .then(res => res.json())
      .then(data => setAlertsData(data.alerts || []));
  }, [timeRange]);

  return (
    <div className="receipts-view">
      {/* Header */}
      <div className="receipts-header">
        <div className="receipts-title">
          <Icon icon="mdi:receipt-text" width="24" />
          <h1>Receipts</h1>
          <span className="receipts-subtitle">Cost & Reliability Explorer</span>
        </div>

        <div className="receipts-controls">
          {/* Time range selector */}
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
            className="time-range-select"
          >
            <option value={1}>Last 24 Hours</option>
            <option value={7}>Last 7 Days</option>
            <option value={30}>Last 30 Days</option>
          </select>
        </div>
      </div>

      {/* Three-panel layout */}
      <Split
        className="receipts-split"
        sizes={[20, 80]}
        minSize={[180, 400]}
        gutterSize={6}
        direction="horizontal"
      >
        {/* Left Navigator */}
        <div className="receipts-navigator">
          <div className="nav-section">
            <button
              className={`nav-item ${activeView === 'overview' ? 'active' : ''}`}
              onClick={() => setActiveView('overview')}
            >
              <Icon icon="mdi:view-dashboard" width="16" />
              <span>Overview</span>
            </button>
            <button
              className={`nav-item ${activeView === 'alerts' ? 'active' : ''}`}
              onClick={() => setActiveView('alerts')}
            >
              <Icon icon="mdi:alert-circle" width="16" />
              <span>Alerts</span>
              {alertsData.length > 0 && (
                <span className="nav-badge">{alertsData.length}</span>
              )}
            </button>
          </div>
        </div>

        {/* Main Content Area */}
        <div className="receipts-content">
          {activeView === 'overview' && overviewData && (
            <OverviewPanel data={overviewData} />
          )}
          {activeView === 'alerts' && (
            <AlertsPanel alerts={alertsData} />
          )}
        </div>
      </Split>
    </div>
  );
}

export default ReceiptsView;
```

#### 2. **OverviewPanel.jsx** (KPIs + Insights)

**Purpose:** Show high-level metrics and human-readable insights

**Structure:**
```jsx
import React from 'react';
import { Icon } from '@iconify/react';
import KPICard from './KPICard';
import InsightCard from './InsightCard';

function OverviewPanel({ data }) {
  const { kpis, trends, insights } = data;

  return (
    <div className="overview-panel">
      {/* KPI Cards Row */}
      <div className="kpi-grid">
        <KPICard
          title="Total Cost"
          value={`$${kpis.total_cost.toFixed(4)}`}
          trend={trends.cost_change_pct}
          icon="mdi:currency-usd"
          color="#34d399"
        />
        <KPICard
          title="Avg per Run"
          value={`$${kpis.avg_cost.toFixed(6)}`}
          subtitle={`${kpis.session_count} sessions`}
          icon="mdi:chart-line"
          color="#60a5fa"
        />
        <KPICard
          title="Context Cost"
          value={`${kpis.avg_context_pct.toFixed(1)}%`}
          subtitle="hidden overhead"
          trend={trends.context_change_pct}
          icon="mdi:file-document-multiple"
          color="#a78bfa"
        />
        <KPICard
          title="Outliers"
          value={kpis.outlier_count}
          subtitle="anomalies"
          icon="mdi:alert-circle"
          color={kpis.outlier_count > 0 ? '#ff006e' : '#34d399'}
        />
      </div>

      {/* Insights Section */}
      <div className="insights-section">
        <div className="section-header">
          <Icon icon="mdi:lightbulb-on" width="18" />
          <h2>Operational Intelligence</h2>
        </div>

        <div className="insights-list">
          {insights.map((insight, idx) => (
            <InsightCard key={idx} insight={insight} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default OverviewPanel;
```

#### 3. **KPICard.jsx** (Reusable Metric Card)

**Purpose:** Display single metric with trend indicator

```jsx
import React from 'react';
import { Icon } from '@iconify/react';

function KPICard({ title, value, subtitle, trend, icon, color }) {
  const trendColor = trend > 0 ? '#ff006e' : trend < 0 ? '#34d399' : '#64748b';
  const trendIcon = trend > 0 ? 'mdi:trending-up' : 'mdi:trending-down';

  return (
    <div className="kpi-card">
      <div className="kpi-header">
        <Icon icon={icon} width="20" style={{ color }} />
        <span className="kpi-title">{title}</span>
      </div>

      <div className="kpi-value" style={{ color }}>
        {value}
      </div>

      {subtitle && (
        <div className="kpi-subtitle">{subtitle}</div>
      )}

      {trend !== undefined && trend !== 0 && (
        <div className="kpi-trend" style={{ color: trendColor }}>
          <Icon icon={trendIcon} width="14" />
          <span>{Math.abs(trend).toFixed(1)}% vs prev</span>
        </div>
      )}
    </div>
  );
}

export default KPICard;
```

#### 4. **InsightCard.jsx** (Human-Readable Insight)

**Purpose:** Display generated insight with action button

```jsx
import React from 'react';
import { Icon } from '@iconify/react';
import { useNavigationStore } from '../../stores/navigationStore';

function InsightCard({ insight }) {
  const { navigate } = useNavigationStore();

  const severityConfig = {
    critical: { icon: 'mdi:alert-circle', color: '#ff006e', label: 'CRITICAL' },
    warning: { icon: 'mdi:alert', color: '#fbbf24', label: 'WARNING' },
    major: { icon: 'mdi:alert', color: '#fbbf24', label: 'MAJOR' },
    info: { icon: 'mdi:information', color: '#60a5fa', label: 'INFO' },
  };

  const config = severityConfig[insight.severity] || severityConfig.info;

  const handleAction = () => {
    if (insight.action?.type === 'view_session') {
      // Navigate to Studio with this session
      navigate('studio', { cascade: insight.action.cascade_id });
    }
    // Add other action handlers as needed
  };

  return (
    <div className={`insight-card insight-${insight.severity}`}>
      <div className="insight-header">
        <Icon icon={config.icon} width="18" style={{ color: config.color }} />
        <span className="insight-label" style={{ color: config.color }}>
          {config.label}
        </span>
      </div>

      <div className="insight-message">
        {insight.message}
      </div>

      {insight.action && (
        <button className="insight-action" onClick={handleAction}>
          {insight.action.type === 'view_session' && 'View Session →'}
          {insight.action.type === 'view_context' && 'View Context Breakdown →'}
        </button>
      )}
    </div>
  );
}

export default InsightCard;
```

#### 5. **AlertsPanel.jsx** (Anomaly Table)

**Purpose:** Show all alerts in ag-grid table

```jsx
import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';

// Same dark theme as Console
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#000000',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0a0510',
  // ... (copy from ConsoleView)
});

function AlertsPanel({ alerts }) {
  const columnDefs = useMemo(() => [
    {
      field: 'severity',
      headerName: 'Severity',
      width: 100,
      cellRenderer: (params) => {
        const colors = {
          critical: '#ff006e',
          major: '#fbbf24',
          minor: '#60a5fa',
        };
        const color = colors[params.value] || '#64748b';
        const icons = {
          critical: 'mdi:alert-circle',
          major: 'mdi:alert',
          minor: 'mdi:information',
        };

        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Icon icon={icons[params.value]} style={{ color }} />
            <span style={{ color, fontWeight: 600, textTransform: 'uppercase', fontSize: '11px' }}>
              {params.value}
            </span>
          </div>
        );
      },
    },
    {
      field: 'type',
      headerName: 'Type',
      width: 140,
      valueFormatter: (params) => {
        const labels = {
          cost_outlier: 'Cost Outlier',
          context_hotspot: 'Context Hotspot',
          regression: 'Regression',
        };
        return labels[params.value] || params.value;
      },
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      flex: 1,
      minWidth: 150,
    },
    {
      field: 'cell_name',
      headerName: 'Cell',
      width: 120,
      valueFormatter: (params) => params.value || '-',
    },
    {
      field: 'message',
      headerName: 'Description',
      flex: 2,
      minWidth: 300,
      cellStyle: { fontSize: '12px', lineHeight: '1.4' },
    },
    {
      field: 'z_score',
      headerName: 'Z-Score',
      width: 90,
      valueFormatter: (params) => {
        return params.value ? `${params.value.toFixed(1)}σ` : '-';
      },
      cellStyle: (params) => {
        if (!params.value) return {};
        const absZ = Math.abs(params.value);
        const color = absZ > 3 ? '#ff006e' : absZ > 2 ? '#fbbf24' : '#cbd5e1';
        return { color, fontWeight: 600, fontFamily: 'var(--font-mono)' };
      },
    },
    {
      field: 'timestamp',
      headerName: 'Time',
      width: 160,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const date = new Date(params.value + 'Z');
        return date.toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
      },
    },
  ], []);

  return (
    <div className="alerts-panel">
      <div className="panel-header">
        <Icon icon="mdi:alert-circle" width="20" />
        <h2>Alerts & Anomalies</h2>
        <span className="alert-count">{alerts.length} alerts</span>
      </div>

      <div className="alerts-grid">
        <AgGridReact
          theme={darkTheme}
          rowData={alerts}
          columnDefs={columnDefs}
          domLayout="autoHeight"
          suppressCellFocus={true}
          enableCellTextSelection={true}
        />
      </div>
    </div>
  );
}

export default AlertsPanel;
```

#### 6. **ReceiptsView.css** (Studio Aesthetic)

**Purpose:** Match Studio's dark, data-dense design

```css
.receipts-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: #0a0a0a;
  color: #cbd5e1;
  overflow: hidden;
}

/* Header */
.receipts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background-color: #050508;
  border-bottom: 1px solid #1a1628;
  flex-shrink: 0;
}

.receipts-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.receipts-title h1 {
  font-size: 18px;
  font-weight: 600;
  color: #f0f4f8;
  margin: 0;
}

.receipts-subtitle {
  font-size: 13px;
  color: #64748b;
  margin-left: 8px;
}

/* Time range selector */
.time-range-select {
  background: #0a0614;
  border: 1px solid #1a1628;
  border-radius: 6px;
  color: #cbd5e1;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}

.time-range-select:hover {
  border-color: #00e5ff;
}

/* Split panels */
.receipts-split {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Navigator (left panel) */
.receipts-navigator {
  background-color: #080510;
  border-right: 1px solid #1a1628;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.nav-section {
  padding: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  width: 100%;
  text-align: left;
}

.nav-item:hover {
  background-color: rgba(255, 255, 255, 0.05);
  color: #cbd5e1;
}

.nav-item.active {
  background-color: rgba(0, 229, 255, 0.1);
  color: #00e5ff;
  border-left: 2px solid #00e5ff;
}

.nav-badge {
  margin-left: auto;
  background: #ff006e;
  color: #fff;
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

/* Content area */
.receipts-content {
  background-color: #000000;
  overflow-y: auto;
  padding: 16px;
}

/* KPI Grid */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

.kpi-card {
  background: #0a0614;
  border: 1px solid #1a1628;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kpi-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kpi-title {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.kpi-value {
  font-size: 28px;
  font-weight: 700;
  font-family: 'Google Sans Code', monospace;
  line-height: 1;
}

.kpi-subtitle {
  font-size: 11px;
  color: #475569;
}

.kpi-trend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  margin-top: auto;
}

/* Insights Section */
.insights-section {
  margin-bottom: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #1a1628;
}

.section-header h2 {
  font-size: 15px;
  font-weight: 600;
  color: #f0f4f8;
  margin: 0;
}

.insights-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Insight Card */
.insight-card {
  background: #0a0614;
  border: 1px solid #1a1628;
  border-left: 3px solid;
  border-radius: 6px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.insight-card.insight-critical {
  border-left-color: #ff006e;
  background: linear-gradient(90deg, rgba(255, 0, 110, 0.05) 0%, rgba(10, 6, 20, 1) 30%);
}

.insight-card.insight-warning,
.insight-card.insight-major {
  border-left-color: #fbbf24;
  background: linear-gradient(90deg, rgba(251, 191, 36, 0.05) 0%, rgba(10, 6, 20, 1) 30%);
}

.insight-card.insight-info {
  border-left-color: #34d399;
}

.insight-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.insight-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.insight-message {
  font-size: 13px;
  line-height: 1.5;
  color: #cbd5e1;
}

.insight-action {
  align-self: flex-start;
  background: rgba(0, 229, 255, 0.1);
  border: 1px solid rgba(0, 229, 255, 0.3);
  border-radius: 4px;
  color: #00e5ff;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.insight-action:hover {
  background: rgba(0, 229, 255, 0.2);
  border-color: rgba(0, 229, 255, 0.5);
}

/* Alerts Panel */
.alerts-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-header h2 {
  font-size: 16px;
  font-weight: 600;
  color: #f0f4f8;
  margin: 0;
}

.alert-count {
  margin-left: auto;
  font-size: 12px;
  color: #64748b;
  background: rgba(100, 116, 139, 0.2);
  padding: 4px 8px;
  border-radius: 4px;
}

.alerts-grid {
  background: #000000;
  border: 1px solid #1a1628;
  border-radius: 8px;
  overflow: hidden;
}

/* Gutter styling (like Studio) */
.receipts-split > .gutter {
  background-color: #1a1628;
  cursor: col-resize;
  transition: background-color 0.15s ease;
}

.receipts-split > .gutter:hover {
  background-color: #00e5ff;
}
```

---

## Implementation Steps

### Step 1: Backend Registration (DONE ✅)
- Created `receipts_api.py` with overview and alerts endpoints
- Registered in `app.py`
- Insight generator implemented

### Step 2: Create Frontend Files

```bash
cd dashboard/frontend/src/views/receipts

# Create main component
touch ReceiptsView.jsx
touch ReceiptsView.css
touch index.js

# Create components directory
mkdir components
cd components
touch OverviewPanel.jsx
touch AlertsPanel.jsx
touch KPICard.jsx
touch InsightCard.jsx
```

### Step 3: Copy Component Code

Copy the code from sections above into respective files.

### Step 4: Register Route

**File:** `dashboard/frontend/src/App.js`

Find the routing section and add:
```jsx
import ReceiptsView from './views/receipts/ReceiptsView';

// In routing:
{hash === '#/receipts' && (
  <ReceiptsView />
)}
```

### Step 5: Test Backend

```bash
# Start backend
cd dashboard/backend
python app.py

# Test endpoints
curl http://localhost:5001/api/receipts/overview?days=7 | jq
curl http://localhost:5001/api/receipts/alerts?days=7 | jq
```

### Step 6: Test Frontend

```bash
# Start frontend
cd dashboard/frontend
npm start

# Navigate to:
http://localhost:3000/#/receipts
```

---

## Visual Design Reference

**Match Studio's aesthetic:**
- **Background:** Pure black (#0a0a0a)
- **Cards:** Dark (#0a0614) with subtle borders (#1a1628)
- **Accent:** Cyan (#00e5ff) for interactive elements
- **Text:** Light gray (#cbd5e1) for body, white (#f0f4f8) for headers
- **Alerts:** Red (#ff006e) critical, Yellow (#fbbf24) warning, Green (#34d399) normal
- **Data density:** Tight spacing, compact cards, information-rich
- **Monospace:** 'Google Sans Code' for numbers/metrics

**From your screenshot:**
- Clean three-panel layout
- Left sidebar for navigation
- Dense information display
- Color-coded severity indicators
- Minimal padding, maximum information

---

## Expected Behavior

### On Page Load:
1. Fetch overview data (KPIs, trends, insights)
2. Display 4 KPI cards with trend indicators
3. Show 3-5 human-readable insights
4. Navigator shows "Alerts" badge if anomalies exist

### Overview View:
```
┌─────────────────────────────────────────────────────────┐
│ KPI Cards:                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│ │Total Cost│ │Avg/Run   │ │Context % │ │Outliers  │   │
│ │$12.45    │ │$0.015    │ │42%       │ │3         │   │
│ │↑ 15%     │ │↓ 8%      │ │↑ 5pp     │ │🔴        │   │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                                                         │
│ Insights:                                               │
│ 🔴 Cell 'enrich' is 3.2σ above normal...               │
│ 🟡 Cell 'summarize' has 78% context overhead...        │
│ 🟢 No regressions detected...                          │
└─────────────────────────────────────────────────────────┘
```

### Alerts View:
- ag-grid table with all anomalies
- Sorted by severity (critical → major → minor)
- Click row → Navigate to Studio session
- Filter by severity/type

---

## Success Criteria

✅ Page loads and displays KPIs from analytics data
✅ Insights panel shows human-readable summaries
✅ Alerts table shows outliers and context hotspots
✅ Navigation works (Overview ↔ Alerts)
✅ Matches Studio aesthetic (dark, dense, cyan accents)
✅ API calls work (fetch from Flask backend)

---

## Future Enhancements (Not in MVP)

**Phase 2:**
- Cascade Explorer (rankings by cost)
- Cell Breakdown (treemap visualization)
- Context Attribution drill-down
- Comparison mode (session A vs B)
- Regression detection

**Phase 3:**
- Interactive charts (cost timeline with context layers)
- Alert configuration (set thresholds)
- Export functionality
- Budget tracking

---

## Key Insights to Surface

**Example sentences the page should generate:**

1. **Cost Outliers:**
   ```
   "Cascade 'extract_brand' session abc123 cost $0.0145 (3.2σ above normal).
    Expected: $0.0042 for medium inputs.
    Investigate session for anomalies."
   ```

2. **Context Hotspots:**
   ```
   "Cell 'summarize' spends 78% on context injection ($0.0089).
    Context from 'analyze' cell bloats with 484 tokens.
    Use selective context to save 78%."
   ```

3. **Bottlenecks:**
   ```
   "Cell 'enrich' accounts for 77% of cascade cost.
    Duration: 3200ms (82% of cascade time).
    This is the bottleneck to optimize."
   ```

4. **Normal Operation:**
   ```
   "No anomalies detected. All 45 sessions in last 7 days
    performed within normal parameters."
   ```

---

## Testing Data

**Backend is already populated with real analytics data!**

Query to verify:
```bash
python -c "
from rvbbit.db_adapter import get_db
db = get_db()

print('CASCADE_ANALYTICS:', db.query('SELECT COUNT(*) as cnt FROM cascade_analytics')[0]['cnt'], 'records')
print('CELL_ANALYTICS:', db.query('SELECT COUNT(*) as cnt FROM cell_analytics')[0]['cnt'], 'records')
print('CELL_CONTEXT_BREAKDOWN:', db.query('SELECT COUNT(*) as cnt FROM cell_context_breakdown')[0]['cnt'], 'records')
"
```

Should show dozens of analytics records ready to display!

---

## Summary

**What you're building:**
A data-dense operational intelligence dashboard that:
- Shows cost/reliability KPIs with statistical context
- Generates human-readable insights (no raw data dumps!)
- Surfaces RVBBIT's unique context attribution
- Enables drill-down from cascade → cell → message
- Matches Studio's dark, information-rich aesthetic

**What's ready:**
- ✅ All backend analytics pre-computed
- ✅ API endpoints functional
- ✅ Insight generator working
- ✅ Design spec complete

**What to build:**
- React components (6 files)
- CSS styling (Studio aesthetic)
- Route registration

**Estimated time:** 4-6 hours for MVP (Overview + Alerts)

Ready to start fresh session and build the UI! 🚀
