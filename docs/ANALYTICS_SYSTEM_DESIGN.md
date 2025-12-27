# RVBBIT Post-Cascade Analytics System Design

**Author:** Claude Sonnet 4.5
**Date:** 2025-12-27
**Status:** Design Proposal

---

## Executive Summary

Design for a **context-aware, post-cascade analytics system** that pre-computes actionable insights, anomaly scores, and trend data for UI consumption. Replaces naive global averages with sophisticated, nuanced comparisons that account for input variation, temporal patterns, and statistical significance.

---

## Core Philosophy

**"Compare apples to apples, oranges to oranges"**

Current problem: Comparing a 10-row analysis to a 10,000-row analysis and calling one "expensive" because it's above the average.

Solution: Context-aware baselines using:
- **Species hash** - Same prompt template + config
- **Input clustering** - Similar input complexity
- **Temporal cohorts** - Recent vs historical
- **Statistical significance** - Z-scores, not just percentages

---

## Table Design: `cascade_analytics`

### Purpose
Pre-computed insights for each cascade execution, calculated AFTER cascade completes.

### Schema

```sql
CREATE TABLE IF NOT EXISTS cascade_analytics (
    -- Identity
    session_id String,
    cascade_id String,
    created_at DateTime DEFAULT now(),

    -- Context Fingerprinting
    species_hash_primary Nullable(String),  -- Species hash of final/main cell
    input_complexity_score Float32,         -- 0-1 score (char count, token estimate)
    input_category LowCardinality(String),  -- 'tiny', 'small', 'medium', 'large', 'huge'
    input_fingerprint String,               -- Hash of input structure (keys, types)

    -- Execution Metrics (raw data)
    total_cost Float64,
    total_duration_ms Float64,
    total_tokens_in UInt32,
    total_tokens_out UInt32,
    message_count UInt16,
    cell_count UInt8,
    error_count UInt8,
    candidate_count UInt8,                  -- Total candidates used
    reforge_depth UInt8,                    -- Max reforge iterations

    -- Baseline Comparisons (context-aware)
    -- Global baselines (all historical runs for this cascade)
    global_avg_cost Float64,
    global_avg_duration Float64,
    global_avg_tokens Float64,

    -- Cluster baselines (same input_category)
    cluster_avg_cost Float64,
    cluster_avg_duration Float64,
    cluster_avg_tokens Float64,
    cluster_stddev_cost Float64,           -- For Z-score calculation
    cluster_stddev_duration Float64,

    -- Species baselines (same species_hash, same inputs)
    species_avg_cost Nullable(Float64),
    species_avg_duration Nullable(Float64),
    species_run_count UInt16,              -- Sample size for significance

    -- Anomaly Scores (statistical)
    cost_z_score Float32,                  -- (cost - cluster_avg) / cluster_stddev
    duration_z_score Float32,
    tokens_z_score Float32,

    -- Anomaly Flags
    is_cost_outlier Bool,                  -- |z_score| > 2
    is_duration_outlier Bool,
    is_tokens_outlier Bool,
    is_error_outlier Bool,                 -- Errors when historical error rate is <5%

    -- Efficiency Metrics
    cost_per_message Float32,              -- total_cost / message_count
    cost_per_output_token Float32,         -- total_cost / tokens_out
    duration_per_message Float32,          -- duration_ms / message_count
    tokens_per_message Float32,            -- total_tokens / message_count

    -- Model Mix
    models_used Array(String),             -- Unique models in this run
    primary_model String,                  -- Most-used model
    model_switches UInt8,                  -- Count of model changes

    -- Temporal Context
    hour_of_day UInt8,                     -- 0-23 (for time-of-day patterns)
    day_of_week UInt8,                     -- 0-6 (for weekly patterns)
    is_weekend Bool,

    -- Regression Detection
    vs_recent_avg_cost Float32,            -- % change vs last 10 runs (same species)
    vs_recent_avg_duration Float32,
    is_regression Bool,                    -- True if cost +20% OR duration +30%
    regression_severity LowCardinality(String), -- 'none', 'minor', 'major', 'critical'

    -- Quality Metrics (if evaluator used)
    evaluator_score Nullable(Float32),     -- 0-1 score from evaluator
    winner_candidate_index Nullable(UInt8),
    winner_cost Nullable(Float64),
    loser_avg_cost Nullable(Float64),

    -- Predictions (ML-based, optional)
    predicted_cost Nullable(Float64),      -- From regression model: f(input_size, cascade_id)
    prediction_error Nullable(Float32),    -- (actual - predicted) / predicted

    -- Parent/Child Context
    parent_session_id Nullable(String),
    depth UInt8,
    child_session_count UInt8,             -- Count of sub-cascades
    child_total_cost Float64,              -- Summed cost of children

    -- Caller Context
    caller_id String,
    origin LowCardinality(String),         -- Extracted from invocation_metadata: 'sql', 'cli', 'ui'

    -- Metadata
    analyzed_at DateTime DEFAULT now(),
    analysis_version UInt8 DEFAULT 1       -- Schema version for backwards compat
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at, session_id)
PARTITION BY toYYYYMM(created_at);  -- Monthly partitions for fast time-range queries

-- Indexes for fast queries
ALTER TABLE cascade_analytics ADD INDEX idx_species species_hash_primary TYPE bloom_filter GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX idx_input_category input_category TYPE set GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX idx_outlier is_cost_outlier TYPE set GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX idx_regression is_regression TYPE set GRANULARITY 1;
```

---

## Backend Analysis Process

### Architecture

```
Cascade Completes
      ↓
RVBBITRunner.run()
      ↓ (after status update)
  ┌───────────────────────────────────┐
  │  Trigger Analytics Worker         │
  │  (async, non-blocking)            │
  └─────────────┬─────────────────────┘
                ↓
  ┌───────────────────────────────────┐
  │  analytics_worker.py              │
  │  analyze_cascade_execution()      │
  └─────────────┬─────────────────────┘
                │
                ├─→ Fetch Session Data (unified_logs, cascade_sessions)
                ├─→ Compute Input Complexity
                ├─→ Query Historical Baselines
                ├─→ Calculate Z-scores & Anomaly Flags
                ├─→ Detect Regressions (time-series)
                ├─→ Extract Model Mix & Efficiency Metrics
                ├─→ Predict Cost (optional ML model)
                ├─→ INSERT into cascade_analytics
                └─→ (Optional) Trigger Alerts if anomaly detected
```

### Implementation File: `rvbbit/analytics_worker.py`

```python
"""
Post-Cascade Analytics Worker

Runs AFTER each cascade execution to pre-compute context-aware insights,
anomaly detection, and statistical comparisons for UI consumption.

Triggered from runner.py after cascade completes.
"""

import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from .db_adapter import get_db
from .utils import compute_species_hash

def analyze_cascade_execution(session_id: str) -> Dict:
    """
    Main entry point: Analyze completed cascade and insert into cascade_analytics.

    Returns:
        Dict with analysis results + any anomalies/alerts detected
    """
    db = get_db()

    # Step 1: Fetch session data
    session_data = _fetch_session_data(session_id)

    # Step 2: Compute input complexity
    input_metrics = _compute_input_complexity(session_data['input_data'])

    # Step 3: Get species hash (from most common in execution)
    species_hash = _get_primary_species_hash(session_id)

    # Step 4: Query baselines (global, cluster, species)
    baselines = _compute_baselines(
        cascade_id=session_data['cascade_id'],
        input_category=input_metrics['category'],
        species_hash=species_hash
    )

    # Step 5: Calculate Z-scores
    z_scores = _calculate_z_scores(session_data, baselines)

    # Step 6: Regression detection
    regression = _detect_regression(species_hash, session_data)

    # Step 7: Efficiency metrics
    efficiency = _compute_efficiency_metrics(session_data)

    # Step 8: Model mix analysis
    models = _analyze_model_usage(session_id)

    # Step 9: Optional ML prediction
    prediction = _predict_cost(session_data, input_metrics)

    # Step 10: Build analytics record
    analytics_row = {
        'session_id': session_id,
        'cascade_id': session_data['cascade_id'],
        'created_at': session_data['started_at'],

        # Context
        'species_hash_primary': species_hash,
        'input_complexity_score': input_metrics['score'],
        'input_category': input_metrics['category'],
        'input_fingerprint': input_metrics['fingerprint'],

        # Raw metrics
        'total_cost': session_data['total_cost'],
        'total_duration_ms': session_data['total_duration_ms'],
        'total_tokens_in': session_data['total_tokens_in'],
        'total_tokens_out': session_data['total_tokens_out'],
        'message_count': session_data['message_count'],
        'cell_count': session_data['cell_count'],
        'error_count': session_data['error_count'],

        # Baselines
        'global_avg_cost': baselines['global']['avg_cost'],
        'global_avg_duration': baselines['global']['avg_duration'],
        'cluster_avg_cost': baselines['cluster']['avg_cost'],
        'cluster_stddev_cost': baselines['cluster']['stddev_cost'],
        'species_avg_cost': baselines['species']['avg_cost'],
        'species_run_count': baselines['species']['run_count'],

        # Anomaly scores
        'cost_z_score': z_scores['cost'],
        'duration_z_score': z_scores['duration'],
        'is_cost_outlier': abs(z_scores['cost']) > 2,
        'is_duration_outlier': abs(z_scores['duration']) > 2,

        # Efficiency
        'cost_per_message': efficiency['cost_per_message'],
        'cost_per_output_token': efficiency['cost_per_token'],
        'duration_per_message': efficiency['duration_per_message'],

        # Models
        'models_used': models['models'],
        'primary_model': models['primary'],
        'model_switches': models['switches'],

        # Temporal
        'hour_of_day': session_data['started_at'].hour,
        'day_of_week': session_data['started_at'].weekday(),
        'is_weekend': session_data['started_at'].weekday() >= 5,

        # Regression
        'vs_recent_avg_cost': regression['cost_change_pct'],
        'vs_recent_avg_duration': regression['duration_change_pct'],
        'is_regression': regression['is_regression'],
        'regression_severity': regression['severity'],

        # Prediction
        'predicted_cost': prediction.get('predicted_cost'),
        'prediction_error': prediction.get('error'),

        # Hierarchy
        'parent_session_id': session_data['parent_session_id'],
        'depth': session_data['depth'],
        'child_session_count': session_data['child_count'],
        'child_total_cost': session_data['child_cost'],

        # Caller
        'caller_id': session_data['caller_id'],
        'origin': session_data['origin'],
    }

    # Step 11: Insert into cascade_analytics
    db.insert_rows('cascade_analytics', [analytics_row])

    # Step 12: Optional alerts
    alerts = _check_for_alerts(analytics_row)

    return {
        'success': True,
        'session_id': session_id,
        'anomalies': alerts,
        'z_scores': z_scores,
        'regression_detected': regression['is_regression'],
    }


def _compute_input_complexity(input_data_json: str) -> Dict:
    """
    Score input complexity for clustering similar sessions.

    Factors:
    - Character count (raw size)
    - Estimated token count (char_count / 4)
    - JSON depth (nested structure complexity)
    - Array sizes (data volume)

    Returns:
        {
            'score': float (0-1),
            'category': str ('tiny', 'small', 'medium', 'large', 'huge'),
            'fingerprint': str (hash of input structure),
            'char_count': int,
            'estimated_tokens': int,
        }
    """
    if not input_data_json:
        return {
            'score': 0.0,
            'category': 'tiny',
            'fingerprint': 'empty',
            'char_count': 0,
            'estimated_tokens': 0,
        }

    # Parse input
    try:
        input_obj = json.loads(input_data_json) if isinstance(input_data_json, str) else input_data_json
    except:
        input_obj = {}

    # Metrics
    char_count = len(input_data_json)
    estimated_tokens = char_count // 4  # Rough estimate

    # JSON depth (measures nesting)
    def max_depth(obj, current=0):
        if not isinstance(obj, (dict, list)):
            return current
        if isinstance(obj, dict):
            return max([max_depth(v, current + 1) for v in obj.values()] or [current])
        return max([max_depth(item, current + 1) for item in obj] or [current])

    depth = max_depth(input_obj)

    # Array size (data volume)
    def count_array_items(obj):
        if isinstance(obj, list):
            return len(obj) + sum(count_array_items(item) for item in obj)
        elif isinstance(obj, dict):
            return sum(count_array_items(v) for v in obj.values())
        return 0

    array_items = count_array_items(input_obj)

    # Compute complexity score (0-1)
    # Weighted combination of factors
    score = min(1.0, (
        (char_count / 10000) * 0.4 +      # 40% weight on size
        (estimated_tokens / 2500) * 0.3 + # 30% weight on tokens
        (depth / 10) * 0.15 +              # 15% weight on nesting
        (array_items / 1000) * 0.15        # 15% weight on data volume
    ))

    # Category buckets
    if score < 0.1:
        category = 'tiny'
    elif score < 0.3:
        category = 'small'
    elif score < 0.6:
        category = 'medium'
    elif score < 0.85:
        category = 'large'
    else:
        category = 'huge'

    # Input fingerprint: hash of input structure (keys + types)
    def get_structure(obj):
        if isinstance(obj, dict):
            return {k: get_structure(v) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            return ['array', len(obj)]
        else:
            return type(obj).__name__

    structure = get_structure(input_obj)
    fingerprint = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()[:16]

    return {
        'score': score,
        'category': category,
        'fingerprint': fingerprint,
        'char_count': char_count,
        'estimated_tokens': estimated_tokens,
    }


def _compute_baselines(cascade_id: str, input_category: str, species_hash: Optional[str]) -> Dict:
    """
    Compute context-aware baselines for comparison.

    Three tiers:
    1. Global: All historical runs for this cascade
    2. Cluster: Runs with same input_category
    3. Species: Runs with same species_hash (most specific)

    Returns nested dict with avg/stddev for cost, duration, tokens.
    """
    db = get_db()

    # Global baseline (all runs for this cascade)
    global_query = f"""
        SELECT
            AVG(total_cost) as avg_cost,
            AVG(total_duration_ms) as avg_duration,
            AVG(total_tokens_in + total_tokens_out) as avg_tokens,
            COUNT(*) as run_count
        FROM cascade_analytics
        WHERE cascade_id = %(cascade_id)s
    """

    global_result = db.query(global_query, {'cascade_id': cascade_id})
    global_baseline = global_result[0] if global_result else {}

    # Cluster baseline (same input category)
    cluster_query = f"""
        SELECT
            AVG(total_cost) as avg_cost,
            stddevPop(total_cost) as stddev_cost,
            AVG(total_duration_ms) as avg_duration,
            stddevPop(total_duration_ms) as stddev_duration,
            AVG(total_tokens_in + total_tokens_out) as avg_tokens,
            stddevPop(total_tokens_in + total_tokens_out) as stddev_tokens,
            COUNT(*) as run_count
        FROM cascade_analytics
        WHERE cascade_id = %(cascade_id)s
          AND input_category = %(input_category)s
    """

    cluster_result = db.query(cluster_query, {
        'cascade_id': cascade_id,
        'input_category': input_category
    })
    cluster_baseline = cluster_result[0] if cluster_result else {}

    # Species baseline (same species_hash - most specific)
    species_baseline = {}
    if species_hash:
        species_query = f"""
            SELECT
                AVG(total_cost) as avg_cost,
                AVG(total_duration_ms) as avg_duration,
                COUNT(*) as run_count
            FROM cascade_analytics
            WHERE species_hash_primary = %(species_hash)s
        """

        species_result = db.query(species_query, {'species_hash': species_hash})
        species_baseline = species_result[0] if species_result else {}

    return {
        'global': global_baseline,
        'cluster': cluster_baseline,
        'species': species_baseline,
    }


def _calculate_z_scores(session_data: Dict, baselines: Dict) -> Dict:
    """
    Calculate Z-scores for anomaly detection.

    Z-score = (value - mean) / stddev

    Interpretation:
    - |z| < 1: Normal (within 1 standard deviation)
    - |z| 1-2: Unusual
    - |z| > 2: Outlier (top/bottom 5%)
    - |z| > 3: Extreme outlier (top/bottom 0.3%)
    """
    cluster = baselines['cluster']

    # Safe division (avoid div by zero)
    def safe_z(value, mean, stddev):
        if stddev is None or stddev == 0:
            return 0.0
        return (value - (mean or 0)) / stddev

    return {
        'cost': safe_z(
            session_data['total_cost'],
            cluster.get('avg_cost'),
            cluster.get('stddev_cost')
        ),
        'duration': safe_z(
            session_data['total_duration_ms'],
            cluster.get('avg_duration'),
            cluster.get('stddev_duration')
        ),
        'tokens': safe_z(
            session_data['total_tokens'],
            cluster.get('avg_tokens'),
            cluster.get('stddev_tokens')
        ),
    }


def _detect_regression(species_hash: Optional[str], session_data: Dict) -> Dict:
    """
    Compare recent runs (last 10) to historical runs (previous 10-20).

    Detects if metrics have degraded significantly.

    Returns:
        {
            'cost_change_pct': float,
            'duration_change_pct': float,
            'is_regression': bool,
            'severity': str ('none', 'minor', 'major', 'critical'),
        }
    """
    if not species_hash:
        return {
            'cost_change_pct': 0,
            'duration_change_pct': 0,
            'is_regression': False,
            'severity': 'none',
        }

    db = get_db()

    # Get last 20 runs for this species (excluding current session)
    query = f"""
        SELECT
            total_cost,
            total_duration_ms,
            created_at
        FROM cascade_analytics
        WHERE species_hash_primary = %(species_hash)s
          AND session_id != %(session_id)s
        ORDER BY created_at DESC
        LIMIT 20
    """

    history = db.query(query, {
        'species_hash': species_hash,
        'session_id': session_data['session_id']
    })

    if len(history) < 10:
        # Not enough data for regression detection
        return {'cost_change_pct': 0, 'duration_change_pct': 0, 'is_regression': False, 'severity': 'none'}

    # Split into recent (last 10) and historical (previous 10)
    recent = history[:10]
    historical = history[10:20] if len(history) >= 20 else history[10:]

    # Compute averages
    recent_avg_cost = sum(r['total_cost'] for r in recent) / len(recent)
    recent_avg_duration = sum(r['total_duration_ms'] for r in recent) / len(recent)

    if historical:
        historical_avg_cost = sum(h['total_cost'] for h in historical) / len(historical)
        historical_avg_duration = sum(h['total_duration_ms'] for h in historical) / len(historical)
    else:
        historical_avg_cost = recent_avg_cost
        historical_avg_duration = recent_avg_duration

    # Calculate % changes
    cost_change_pct = ((recent_avg_cost - historical_avg_cost) / historical_avg_cost * 100
                       if historical_avg_cost > 0 else 0)
    duration_change_pct = ((recent_avg_duration - historical_avg_duration) / historical_avg_duration * 100
                           if historical_avg_duration > 0 else 0)

    # Determine if regression (cost +20% OR duration +30%)
    is_regression = cost_change_pct > 20 or duration_change_pct > 30

    # Severity classification
    if not is_regression:
        severity = 'none'
    elif cost_change_pct > 50 or duration_change_pct > 50:
        severity = 'critical'
    elif cost_change_pct > 35 or duration_change_pct > 40:
        severity = 'major'
    else:
        severity = 'minor'

    return {
        'cost_change_pct': cost_change_pct,
        'duration_change_pct': duration_change_pct,
        'is_regression': is_regression,
        'severity': severity,
    }


def _check_for_alerts(analytics_row: Dict) -> List[Dict]:
    """
    Check if any alerts should be triggered based on analytics.

    Returns list of alert dicts for potential notification system.
    """
    alerts = []

    # Critical cost outlier
    if analytics_row['cost_z_score'] > 3:
        alerts.append({
            'type': 'cost_spike',
            'severity': 'critical',
            'message': f"Cost is {analytics_row['cost_z_score']:.1f}σ above normal!",
            'session_id': analytics_row['session_id'],
        })

    # Regression detected
    if analytics_row['is_regression']:
        alerts.append({
            'type': 'regression',
            'severity': analytics_row['regression_severity'],
            'message': f"Performance degradation: cost +{analytics_row['vs_recent_avg_cost']:.0f}%",
            'session_id': analytics_row['session_id'],
        })

    # Prediction error (actual >> predicted)
    if analytics_row.get('prediction_error') and analytics_row['prediction_error'] > 1.5:
        alerts.append({
            'type': 'prediction_miss',
            'severity': 'warning',
            'message': f"Cost {analytics_row['prediction_error']:.0%} higher than predicted",
            'session_id': analytics_row['session_id'],
        })

    return alerts
```

---

## Integration Points

### 1. Trigger from runner.py

**Location:** After line 4476 (after output save completes)

```python
# Trigger analytics worker (async, non-blocking)
try:
    from .analytics_worker import analyze_cascade_execution
    import threading

    def run_analytics():
        try:
            analyze_cascade_execution(self.session_id)
        except Exception as e:
            logger.debug(f"Analytics worker failed: {e}")

    # Run in background thread (don't block cascade completion)
    analytics_thread = threading.Thread(target=run_analytics, daemon=True)
    analytics_thread.start()

except Exception:
    pass  # Analytics failure doesn't affect cascade
```

### 2. API Endpoint: `/api/analytics/session/{session_id}`

**Response:**
```json
{
  "session_id": "abc123",
  "cascade_id": "extract_brand",
  "input_category": "medium",
  "total_cost": 0.0015,
  "baselines": {
    "global_avg": 0.0012,
    "cluster_avg": 0.0014,
    "species_avg": 0.0013
  },
  "anomaly_scores": {
    "cost_z_score": 0.7,
    "duration_z_score": -0.3,
    "is_outlier": false
  },
  "efficiency": {
    "cost_per_message": 0.00015,
    "cost_per_token": 0.0000005
  },
  "regression": {
    "cost_change_pct": -5.2,
    "is_regression": false,
    "severity": "none"
  },
  "alerts": []
}
```

### 3. Console UI Enhancements

**New Badges:**
```jsx
// Anomaly badge
{row.is_cost_outlier && (
  <Tooltip label={`Cost is ${row.cost_z_score.toFixed(1)}σ from normal`}>
    <span className="anomaly-badge">
      {row.cost_z_score > 0 ? '🔴 HIGH' : '🟢 LOW'}
    </span>
  </Tooltip>
)}

// Regression warning
{row.is_regression && (
  <Tooltip label={`Regression detected: +${row.vs_recent_avg_cost}% cost vs recent`}>
    <Icon icon="mdi:trending-up" color="#ff006e" />
  </Tooltip>
)}
```

**New Columns:**
- **Anomaly** - 🔴/🟡/🟢 badge with Z-score tooltip
- **vs Recent** - +15% / -8% compared to last 10 runs
- **Input Type** - tiny/small/medium/large badge

---

## Advanced Features (Future)

### Pareto Frontier Analysis

Find candidates that are Pareto optimal:

```sql
WITH candidates AS (
    SELECT
        cascade_id,
        cell_name,
        model,
        AVG(cost) as avg_cost,
        AVG(evaluator_score) as avg_quality
    FROM unified_logs
    WHERE node_type = 'sounding_attempt'
      AND species_hash = ?
    GROUP BY cascade_id, cell_name, model
)
SELECT
    c1.model,
    c1.avg_cost,
    c1.avg_quality,
    -- Is this Pareto optimal?
    NOT EXISTS (
        SELECT 1 FROM candidates c2
        WHERE c2.model != c1.model
          AND c2.avg_cost <= c1.avg_cost
          AND c2.avg_quality >= c1.avg_quality
          AND (c2.avg_cost < c1.avg_cost OR c2.avg_quality > c1.avg_quality)
    ) as is_pareto
FROM candidates c1
ORDER BY avg_cost, avg_quality DESC
```

### N-gram Winner Patterns

Extract winning phrases from prompt lineage:

```python
def extract_winning_ngrams(species_hash):
    db = get_db()

    # Get winner and loser prompts
    query = f"""
        SELECT
            full_prompt_text,
            is_winner
        FROM prompt_lineage
        WHERE species_hash = %(species_hash)s
          AND generation = 0  -- Only base prompts (mutations may inherit patterns)
    """

    prompts = db.query(query, {'species_hash': species_hash})

    # Tokenize and count n-grams
    from collections import Counter

    winner_ngrams = Counter()
    loser_ngrams = Counter()

    for p in prompts:
        ngrams = extract_ngrams(p['full_prompt_text'], n=3)  # Trigrams

        if p['is_winner']:
            winner_ngrams.update(ngrams)
        else:
            loser_ngrams.update(ngrams)

    # Compute lift (winner_freq - loser_freq)
    patterns = []
    for ngram in set(winner_ngrams.keys()) | set(loser_ngrams.keys()):
        winner_freq = winner_ngrams[ngram] / len([p for p in prompts if p['is_winner']])
        loser_freq = loser_ngrams[ngram] / len([p for p in prompts if not p['is_winner']])
        lift = winner_freq - loser_freq

        if lift > 0.15:  # Appears in 15% more winners
            patterns.append({
                'ngram': ngram,
                'lift': lift,
                'winner_count': winner_ngrams[ngram],
                'recommendation': f"Try adding '{ngram}' to your prompt"
            })

    return sorted(patterns, key=lambda x: -x['lift'])
```

### Time-Series Forecasting

Predict next week's cost:

```python
def forecast_cost(cascade_id: str, days_ahead: int = 7) -> Dict:
    """Simple linear regression forecast."""
    db = get_db()

    # Get last 30 days of data
    query = f"""
        SELECT
            toDate(created_at) as day,
            SUM(total_cost) as daily_cost
        FROM cascade_analytics
        WHERE cascade_id = %(cascade_id)s
          AND created_at > now() - INTERVAL 30 DAY
        GROUP BY day
        ORDER BY day
    """

    data = db.query(query, {'cascade_id': cascade_id})

    # Simple linear regression: cost = a * day_index + b
    from scipy import stats
    import numpy as np

    days = np.arange(len(data))
    costs = np.array([row['daily_cost'] for row in data])

    slope, intercept, r_value, p_value, std_err = stats.linregress(days, costs)

    # Predict next N days
    future_days = np.arange(len(data), len(data) + days_ahead)
    predictions = slope * future_days + intercept

    return {
        'forecast': [
            {'day': len(data) + i, 'predicted_cost': float(p)}
            for i, p in enumerate(predictions)
        ],
        'trend': 'increasing' if slope > 0 else 'decreasing',
        'confidence': float(r_value ** 2),  # R² value
    }
```

---

## Migration Path

### Step 1: Create Table
```sql
-- See full schema above
CREATE TABLE cascade_analytics (...) ENGINE = MergeTree()
```

### Step 2: Backfill Historical Data
```python
def backfill_analytics():
    """One-time job to analyze historical sessions."""
    db = get_db()

    # Get all completed sessions
    sessions = db.query("""
        SELECT DISTINCT session_id
        FROM cascade_sessions
        WHERE session_id NOT IN (SELECT session_id FROM cascade_analytics)
        ORDER BY created_at DESC
        LIMIT 1000
    """)

    for row in sessions:
        try:
            analyze_cascade_execution(row['session_id'])
        except Exception as e:
            print(f"Backfill failed for {row['session_id']}: {e}")
```

### Step 3: Integrate into Runner
Add analytics trigger to runner.py (see above)

### Step 4: Build UI Components
- Anomaly badges in Console
- Regression dashboard in Sextant
- Time-series charts with forecasts
- Winner pattern suggestions

---

## ROI Analysis

### Metrics Improved

| Current State | With Analytics System |
|---------------|----------------------|
| "Cost: $0.05 (+20% vs avg)" | "Cost: $0.05 (Z=1.2, normal for medium inputs)" |
| No regression detection | "⚠️ Cost +35% vs recent (regression detected)" |
| No pattern insights | "💡 Try 'step by step' (in 85% of winners)" |
| No anomaly alerts | "🚨 Outlier: 3.5σ above expected (investigate)" |
| No forecasting | "Projected weekly cost: $12.50 ± $2.30" |

### Developer Benefits
- **Faster debugging**: Outliers flagged automatically
- **Better optimization**: Know what works (patterns, models)
- **Prevent regressions**: Alerts when changes degrade performance
- **Cost management**: Forecasts + anomaly detection

### System Complexity
- **Medium**: ~500 lines of Python for analytics worker
- **Low maintenance**: Runs async, non-blocking
- **High value**: Unlocks sophisticated insights with existing data

---

## Conclusion

The analytics system would transform RVBBIT from **descriptive** ("this run cost $0.05") to **prescriptive** ("this run is unusually expensive for medium inputs; consider using Model X which wins 85% and costs 30% less").

**Recommended Priority:**
1. ✅ **Quick Win**: Z-scores + input clustering (1-2 days)
2. ✅ **High Value**: Regression detection (3-5 days)
3. ✅ **Game Changer**: N-gram pattern mining (1 week)
4. 🔮 **Future**: Pareto optimization + forecasting (1+ month)

Ready to implement when you are! 🚀
