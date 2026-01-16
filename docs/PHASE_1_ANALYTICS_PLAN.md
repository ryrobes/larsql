# Phase 1: Context-Aware Analytics (Quick Wins)

**Date:** 2025-12-27
**Timeline:** 1-2 days
**Dependencies:** ✅ Phase 0 complete (genus_hash + species_hash working)

---

## Goal

Replace **naive global averages** with **context-aware comparisons** that account for input variation, providing statistically significant anomaly detection.

---

## What We're Building

### The Problem Today
```
Session A: 10 rows    → $0.01 cost
Session B: 10,000 rows → $0.12 cost
Global average: $0.065

❌ Session B looks "expensive" (+85% vs avg)
✅ But it's actually NORMAL for large inputs!
```

### The Solution (Phase 1)
```
Session A: 10 rows    → $0.01 cost
  ├─ Input category: "small"
  ├─ Cluster avg: $0.012
  ├─ Z-score: -0.2 (normal)
  └─ Status: ✅ Normal

Session B: 10,000 rows → $0.12 cost
  ├─ Input category: "large"
  ├─ Cluster avg: $0.11
  ├─ Z-score: 0.9 (normal)
  └─ Status: ✅ Normal

Session C: 50 rows → $0.25 cost
  ├─ Input category: "small"
  ├─ Cluster avg: $0.012
  ├─ Z-score: 3.8 (extreme outlier!)
  └─ Status: 🔴 ANOMALY
```

---

## Deliverables

### 1. Database Table: `cascade_analytics`

**Purpose:** Pre-compute context-aware insights for each cascade execution

**Key Fields:**

#### **Identity & Context**
- `session_id`, `cascade_id`, `genus_hash`, `created_at`
- `input_complexity_score` (0-1 float)
- `input_category` ('tiny', 'small', 'medium', 'large', 'huge')
- `input_fingerprint` (hash of input structure)

#### **Raw Metrics** (from unified_logs aggregation)
- `total_cost`, `total_duration_ms`
- `total_tokens_in`, `total_tokens_out`
- `message_count`, `cell_count`, `error_count`

#### **Context-Aware Baselines**
- `global_avg_cost` - All runs of this cascade
- `cluster_avg_cost` - Same input_category runs
- `cluster_stddev_cost` - For Z-score calculation
- `genus_avg_cost` - Same genus_hash runs (most specific!)

#### **Anomaly Scores** (Statistical!)
- `cost_z_score` - (cost - cluster_avg) / cluster_stddev
- `duration_z_score` - Similar for duration
- `is_cost_outlier` - |z_score| > 2 (top/bottom 5%)
- `is_duration_outlier` - Similar flag

#### **Efficiency Metrics**
- `cost_per_message` - total_cost / message_count
- `cost_per_token` - total_cost / total_tokens
- `tokens_per_message` - Avg tokens per LLM call

#### **Temporal Context**
- `hour_of_day` (0-23)
- `day_of_week` (0-6)
- `is_weekend` (boolean)

**Full schema:** ~40 columns (see ANALYTICS_SYSTEM_DESIGN.md for complete SQL)

---

### 2. Analytics Worker: `lars/analytics_worker.py`

**Purpose:** Post-cascade analysis job that computes all metrics

**Main Function:**
```python
def analyze_cascade_execution(session_id: str) -> Dict:
    """
    Analyze completed cascade and insert into cascade_analytics.

    Steps:
    1. Fetch session data from unified_logs + cascade_sessions
    2. Compute input complexity (char count, token estimate, nesting depth)
    3. Query baselines (global, cluster, genus)
    4. Calculate Z-scores (statistical anomaly detection)
    5. Compute efficiency metrics
    6. Extract model mix, temporal context
    7. INSERT into cascade_analytics
    8. Return anomaly alerts if detected
    """
```

**Key Functions:**

#### **`_compute_input_complexity(input_data_json)`**
Analyzes input to categorize sessions:
```python
Factors:
  - Character count (size)
  - Estimated tokens (char_count / 4)
  - JSON nesting depth (complexity)
  - Array sizes (data volume)

Returns:
  {
    'score': 0.45,  # 0-1 composite score
    'category': 'medium',  # tiny/small/medium/large/huge
    'fingerprint': 'abc123',  # Hash of input structure
    'char_count': 2500,
    'estimated_tokens': 625
  }
```

**Clustering:**
- tiny: <500 chars
- small: 500-2000 chars
- medium: 2000-6000 chars
- large: 6000-20000 chars
- huge: 20000+ chars

#### **`_compute_baselines(cascade_id, input_category, genus_hash)`**
Fetches historical data for comparison:
```python
Returns:
  {
    'global': {  # All runs of this cascade
      'avg_cost': 0.05,
      'avg_duration': 1200,
      'run_count': 150
    },
    'cluster': {  # Same input_category
      'avg_cost': 0.04,
      'stddev_cost': 0.01,  # For Z-score!
      'run_count': 45
    },
    'genus': {  # Same genus_hash (most specific!)
      'avg_cost': 0.039,
      'run_count': 12
    }
  }
```

#### **`_calculate_z_scores(session_data, baselines)`**
Statistical anomaly detection:
```python
Z-score = (value - mean) / stddev

Interpretation:
  |z| < 1: Normal (68% of data)
  |z| 1-2: Unusual (27% of data)
  |z| > 2: Outlier (5% of data)
  |z| > 3: Extreme (0.3% of data)

Returns:
  {
    'cost': 2.4,      # 2.4σ above cluster mean
    'duration': -0.3,  # 0.3σ below (faster)
    'tokens': 0.8
  }
```

---

### 3. Integration: Trigger from runner.py

**Location:** After output save completes (line ~4476)

```python
# Trigger analytics worker (async, non-blocking)
try:
    from .analytics_worker import analyze_cascade_execution
    import threading

    def run_analytics():
        try:
            analyze_cascade_execution(self.session_id)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Analytics worker failed: {e}")

    # Run in background thread (don't block cascade completion)
    analytics_thread = threading.Thread(target=run_analytics, daemon=True)
    analytics_thread.start()

except Exception:
    pass  # Analytics failure doesn't affect cascade
```

---

### 4. API Endpoint: `/api/analytics/session/{session_id}`

**Response:**
```json
{
  "session_id": "abc123",
  "cascade_id": "extract_brand",
  "genus_hash": "fd2dc2ae",

  "input": {
    "category": "medium",
    "complexity_score": 0.45,
    "char_count": 2500,
    "estimated_tokens": 625
  },

  "metrics": {
    "total_cost": 0.045,
    "total_duration_ms": 1500,
    "message_count": 8,
    "cell_count": 3
  },

  "baselines": {
    "global_avg_cost": 0.052,
    "cluster_avg_cost": 0.041,  // Same input category
    "genus_avg_cost": 0.039     // Same genus (most specific!)
  },

  "anomaly_scores": {
    "cost_z_score": 0.4,
    "duration_z_score": -0.3,
    "is_cost_outlier": false,
    "is_duration_outlier": false
  },

  "efficiency": {
    "cost_per_message": 0.005625,
    "cost_per_token": 0.000018,
    "tokens_per_message": 312
  },

  "temporal": {
    "hour_of_day": 14,
    "day_of_week": 3,
    "is_weekend": false
  }
}
```

---

### 5. Console UI Enhancements

**New Columns/Features:**

#### **Anomaly Badge**
```jsx
{row.is_cost_outlier && (
  <Tooltip label={`Cost is ${row.cost_z_score.toFixed(1)}σ from cluster average`}>
    <span className={`anomaly-badge ${row.cost_z_score > 0 ? 'high' : 'low'}`}>
      {row.cost_z_score > 0 ? '🔴 HIGH' : '🟢 LOW'}
    </span>
  </Tooltip>
)}
```

#### **Input Category Badge**
```jsx
<span className={`input-category-badge ${row.input_category}`}>
  {row.input_category}
</span>
```

#### **Smarter Cost Column**
```jsx
// Instead of: "+20% vs avg"
// Show: "Z=0.8 (normal for medium inputs)"

<Tooltip label={`
  Cluster avg: $${row.cluster_avg_cost}
  Your cost: $${row.total_cost}
  Z-score: ${row.cost_z_score.toFixed(1)}
`}>
  <span className={row.is_cost_outlier ? 'cost-outlier' : 'cost-normal'}>
    ${row.total_cost.toFixed(6)}
  </span>
</Tooltip>
```

---

## Implementation Steps

### Step 1: Create `cascade_analytics` Table (Migration)

**File:** `lars/migrations/create_cascade_analytics_table.sql`

```sql
CREATE TABLE IF NOT EXISTS cascade_analytics (
    -- Identity
    session_id String,
    cascade_id String,
    genus_hash String,
    created_at DateTime DEFAULT now(),

    -- Input Context
    input_complexity_score Float32,
    input_category LowCardinality(String),  -- 'tiny','small','medium','large','huge'
    input_fingerprint String,

    -- Raw Metrics
    total_cost Float64,
    total_duration_ms Float64,
    total_tokens_in UInt32,
    total_tokens_out UInt32,
    message_count UInt16,
    cell_count UInt8,
    error_count UInt8,

    -- Baselines (context-aware!)
    global_avg_cost Float64,
    global_avg_duration Float64,
    cluster_avg_cost Float64,
    cluster_stddev_cost Float64,  -- For Z-score
    cluster_avg_duration Float64,
    cluster_stddev_duration Float64,
    genus_avg_cost Nullable(Float64),
    genus_run_count UInt16,

    -- Anomaly Scores (statistical!)
    cost_z_score Float32,
    duration_z_score Float32,
    tokens_z_score Float32,
    is_cost_outlier Bool,
    is_duration_outlier Bool,

    -- Efficiency
    cost_per_message Float32,
    cost_per_token Float32,
    tokens_per_message Float32,

    -- Temporal
    hour_of_day UInt8,
    day_of_week UInt8,
    is_weekend Bool,

    -- Metadata
    analyzed_at DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at, session_id)
PARTITION BY toYYYYMM(created_at);

-- Indexes
ALTER TABLE cascade_analytics ADD INDEX idx_genus genus_hash TYPE bloom_filter GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX idx_category input_category TYPE set GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX idx_outlier is_cost_outlier TYPE set GRANULARITY 1;
```

---

### Step 2: Implement Analytics Worker

**File:** `lars/analytics_worker.py` (new file, ~400 lines)

**Core Functions:**
1. `analyze_cascade_execution(session_id)` - Main entry point
2. `_fetch_session_data(session_id)` - Aggregate from unified_logs
3. `_compute_input_complexity(input_data)` - Category + score
4. `_compute_baselines(...)` - Query historical data
5. `_calculate_z_scores(...)` - Statistical anomaly detection
6. `_compute_efficiency_metrics(...)` - Per-message/token costs

---

### Step 3: Trigger from Runner

**File:** `lars/runner.py` (after line 4476, after output save)

```python
# Trigger analytics worker (async, non-blocking)
try:
    from .analytics_worker import analyze_cascade_execution
    import threading

    def run_analytics():
        try:
            analyze_cascade_execution(self.session_id)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Analytics worker failed: {e}")

    # Background thread (don't block cascade return)
    analytics_thread = threading.Thread(target=run_analytics, daemon=True)
    analytics_thread.start()

except Exception:
    pass  # Analytics is optional
```

---

### Step 4: Backend API Endpoint

**File:** `dashboard/backend/analytics_api.py` (new)

```python
from flask import Blueprint, jsonify, request

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/api/analytics/session/<session_id>', methods=['GET'])
def get_session_analytics(session_id):
    """Get pre-computed analytics for a session."""
    db = get_db()

    result = db.query("""
        SELECT * FROM cascade_analytics
        WHERE session_id = %(session_id)s
    """, {'session_id': session_id})

    if not result:
        return jsonify({'error': 'No analytics found'}), 404

    return jsonify(result[0])
```

Register in `app.py`:
```python
from analytics_api import analytics_bp
app.register_blueprint(analytics_bp)
```

---

### Step 5: Console UI Enhancements

**File:** `dashboard/frontend/src/views/console/ConsoleView.jsx`

**Add Columns:**

#### **Input Category Column**
```javascript
{
  field: 'input_category',
  headerName: 'Input Size',
  width: 100,
  cellRenderer: (params) => {
    const colors = {
      tiny: '#64748b',
      small: '#60a5fa',
      medium: '#fbbf24',
      large: '#f87171',
      huge: '#ff006e'
    };
    const color = colors[params.value] || '#64748b';

    return (
      <span style={{
        color,
        fontSize: '10px',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.5px'
      }}>
        {params.value || '-'}
      </span>
    );
  }
}
```

#### **Anomaly Badge Column**
```javascript
{
  field: 'is_cost_outlier',
  headerName: 'Anomaly',
  width: 90,
  cellRenderer: (params) => {
    const z_score = params.data.cost_z_score;

    if (!z_score || Math.abs(z_score) < 1) {
      return <span style={{ color: '#34d399' }}>✓</span>;
    }

    if (Math.abs(z_score) > 2) {
      return (
        <Tooltip label={`Z-score: ${z_score.toFixed(1)}σ`}>
          <span style={{ color: '#ff006e', fontWeight: 600 }}>
            {z_score > 0 ? '🔴 HIGH' : '🟢 LOW'}
          </span>
        </Tooltip>
      );
    }

    return (
      <span style={{ color: '#fbbf24' }}>
        ⚠ {z_score.toFixed(1)}σ
      </span>
    );
  }
}
```

#### **Enhanced Cost Column**
```javascript
{
  field: 'total_cost',
  headerName: 'Cost',
  width: 120,
  valueFormatter: (params) => {
    const cost = params.value || 0;
    return cost > 0 ? `$${cost.toFixed(6)}` : '-';
  },
  cellStyle: (params) => {
    const isOutlier = params.data.is_cost_outlier;
    return {
      color: isOutlier ? '#ff006e' : '#34d399',
      fontFamily: 'var(--font-mono)',
      fontWeight: isOutlier ? 600 : 400
    };
  },
  tooltipValueGetter: (params) => {
    const z = params.data.cost_z_score;
    const cluster = params.data.cluster_avg_cost;
    const category = params.data.input_category;

    if (!z) return `$${params.value?.toFixed(6)}`;

    return `Cost: $${params.value?.toFixed(6)}
Z-score: ${z.toFixed(1)}σ
Cluster avg (${category}): $${cluster?.toFixed(6)}
Status: ${Math.abs(z) > 2 ? 'OUTLIER' : Math.abs(z) > 1 ? 'Unusual' : 'Normal'}`;
  }
}
```

---

## Expected Impact

### Before Phase 1
```sql
-- Console query (naive)
SELECT
    session_id,
    total_cost,
    (total_cost - cascade_avg) / cascade_avg * 100 as pct_diff
FROM sessions
```

**Shows:** `"+20% vs avg"` (meaningless without context!)

### After Phase 1
```sql
-- Console query (context-aware)
SELECT
    session_id,
    total_cost,
    input_category,
    cost_z_score,
    is_cost_outlier,
    cluster_avg_cost
FROM cascade_analytics
```

**Shows:**
- Input category (small/medium/large)
- Z-score (statistical significance)
- Cluster-specific comparison
- Outlier flag

**Result:**
- "Normal for medium inputs" vs "3σ outlier - investigate!"
- Actionable insights instead of noise

---

## Testing Plan

### Test 1: Input Complexity Clustering
```bash
# Run cascades with different input sizes
lars run examples/extract_brand.yaml --input '{"product": "iPhone"}' --session test_small
lars run examples/extract_brand.yaml --input '{"product": "..."x10000}' --session test_large

# Check clustering
SELECT
    session_id,
    input_category,
    input_complexity_score,
    total_cost,
    cluster_avg_cost,
    cost_z_score
FROM cascade_analytics
WHERE session_id IN ('test_small', 'test_large')
```

**Expected:**
- test_small → category='small', cluster_avg ~$0.01
- test_large → category='large', cluster_avg ~$0.20
- Different baselines for each!

### Test 2: Anomaly Detection
```bash
# Force an expensive run (use expensive model or long prompt)
lars run examples/test.yaml --session test_expensive

# Check if flagged as outlier
SELECT
    session_id,
    cost_z_score,
    is_cost_outlier
FROM cascade_analytics
WHERE session_id = 'test_expensive'
```

**Expected:** If cost > 2σ above cluster avg, flagged as outlier

### Test 3: Console UI
```
Open Console → Should see:
  - Input Size column (tiny/small/medium/large)
  - Anomaly badges (🔴/🟡/✅)
  - Enhanced tooltips with Z-scores
```

---

## Timeline

### Day 1: Backend
- [ ] Create cascade_analytics table (migration)
- [ ] Implement analytics_worker.py
  - [ ] _compute_input_complexity()
  - [ ] _compute_baselines()
  - [ ] _calculate_z_scores()
  - [ ] _compute_efficiency_metrics()
  - [ ] analyze_cascade_execution()
- [ ] Add trigger to runner.py
- [ ] Test with sample cascades

### Day 2: Frontend + API
- [ ] Create analytics_api.py
- [ ] Update Console UI columns
- [ ] Add anomaly badges
- [ ] Enhanced tooltips with Z-scores
- [ ] Test in browser

---

## Success Criteria

✅ **cascade_analytics table** populated for all new runs
✅ **Input clustering** working (sessions grouped by size)
✅ **Z-scores** calculated correctly
✅ **Outliers flagged** automatically (|z| > 2)
✅ **Console UI** shows anomaly badges
✅ **Tooltips** explain why something is an outlier

---

## What's NOT in Phase 1

These come later:
- ❌ Regression detection (Phase 2)
- ❌ N-gram pattern mining (Phase 2)
- ❌ Time-series forecasting (Phase 3)
- ❌ Pareto optimization (Phase 4)
- ❌ Automated alerts/notifications (Phase 3)

Phase 1 focuses on **context-aware baselines** and **statistical anomaly detection** - the foundation for everything else.

---

## Ready to Implement?

Phase 1 gives you:
1. Smart comparisons (apples to apples)
2. Statistical significance (Z-scores)
3. Automatic outlier detection
4. Input complexity clustering

Want me to start building? We can do:
- **Option A:** Full implementation (all steps)
- **Option B:** Just the table + worker (backend only)
- **Option C:** Just the table + basic worker (minimal version)

What's your preference? 🚀
