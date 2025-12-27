"""
Post-Cascade Analytics Worker

Runs AFTER each cascade execution to pre-compute context-aware insights,
anomaly detection, and statistical comparisons for UI consumption.

Key Features:
- Input complexity clustering (compare apples to apples)
- Statistical anomaly detection (Z-scores, not just percentages)
- Multi-tier baselines (global, cluster, genus)
- Efficiency metrics (cost per message, cost per token)

Triggered from runner.py after cascade completes (async, non-blocking).
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _wait_for_cost_data(session_id: str, db, max_wait_seconds: int = 10) -> Optional[Dict]:
    """
    Wait for cost data to be populated in unified_logs before analyzing.

    OpenRouter API calls take 3-4 seconds to return cost data. The cost update
    worker runs in background and UPDATEs unified_logs after the API response.

    This function polls until:
    1. Cost data appears (total_cost > 0), OR
    2. Max wait time is reached, OR
    3. Session has no LLM calls (deterministic-only cascades have cost=0)

    Args:
        session_id: Session to wait for
        db: Database connection
        max_wait_seconds: Maximum time to wait (default: 10s)

    Returns:
        Session data dict with cost populated, or None if session not found
    """
    import time

    poll_interval = 0.5  # Poll every 500ms
    max_polls = int(max_wait_seconds / poll_interval)

    for poll_count in range(max_polls):
        # Fetch current session data
        session_data = _fetch_session_data(session_id, db)

        if not session_data:
            # Session doesn't exist at all
            return None

        # Check if cost data is available
        total_cost = session_data.get('total_cost', 0)

        # Check if this session has LLM calls and whether they're free models
        llm_check_query = f"""
            SELECT
                COUNT(*) as llm_count,
                countIf(endsWith(model, ':free')) as free_model_count
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND role = 'assistant'
              AND model IS NOT NULL
        """

        llm_result = db.query(llm_check_query)
        has_llm_calls = llm_result and llm_result[0]['llm_count'] > 0
        all_free_models = llm_result and llm_result[0]['llm_count'] == llm_result[0]['free_model_count']

        # Cost is ready if:
        # 1. We have cost > 0 (LLM calls were made and cost updated), OR
        # 2. No LLM calls expected (deterministic-only cascade), OR
        # 3. All LLM calls use free models (cost=0 is correct)
        if total_cost > 0:
            # Cost data is ready!
            logger.debug(f"Cost data ready for {session_id} after {poll_count * poll_interval:.1f}s: ${total_cost:.6f}")
            return session_data

        if not has_llm_calls:
            # No LLM calls = no cost expected (deterministic-only cascade)
            logger.debug(f"No LLM calls for {session_id}, cost=0 is expected (deterministic cascade)")
            return session_data

        if all_free_models and poll_count >= 2:
            # All free models, cost=0 is correct (wait at least 1s to be sure)
            logger.debug(f"All free models for {session_id}, cost=0 is expected")
            return session_data

        # Cost not ready yet, wait and retry
        if poll_count < max_polls - 1:  # Don't sleep on last iteration
            time.sleep(poll_interval)

    # Max wait reached - return data anyway (better than nothing)
    # The cost might still be 0, but we don't want to block indefinitely
    logger.warning(f"Cost data not ready for {session_id} after {max_wait_seconds}s, proceeding anyway")
    return session_data


def analyze_cascade_execution(session_id: str) -> Dict:
    """
    Main entry point: Analyze completed cascade and insert into cascade_analytics.

    Args:
        session_id: Cascade session to analyze

    Returns:
        Dict with analysis results + any anomalies detected
    """
    try:
        from .db_adapter import get_db
        import time

        db = get_db()

        # CRITICAL: Wait for cost data to be populated in unified_logs
        # OpenRouter API calls take 3-4 seconds, so we poll until cost is available
        session_data = _wait_for_cost_data(session_id, db, max_wait_seconds=10)

        if not session_data:
            logger.debug(f"No session data found for {session_id} after waiting for cost")
            return {'success': False, 'error': 'session_not_found'}

        # Step 2: Compute input complexity
        input_metrics = _compute_input_complexity(session_data.get('input_data'))

        # Step 3: Query baselines (global, cluster, genus)
        baselines = _compute_baselines(
            db=db,
            cascade_id=session_data['cascade_id'],
            input_category=input_metrics['category'],
            genus_hash=session_data.get('genus_hash')
        )

        # Step 4: Calculate Z-scores (anomaly detection)
        z_scores = _calculate_z_scores(session_data, baselines)

        # Step 5: Compute efficiency metrics
        efficiency = _compute_efficiency_metrics(session_data)

        # Step 6: Analyze model usage
        models = _analyze_model_usage(session_id, db)

        # Step 7: Extract temporal context
        temporal = _extract_temporal_context(session_data['created_at'])

        # Step 8: Build analytics record
        analytics_row = {
            'session_id': session_id,
            'cascade_id': session_data['cascade_id'],
            'genus_hash': session_data.get('genus_hash', ''),
            'created_at': session_data['created_at'],

            # Input context
            'input_complexity_score': input_metrics['score'],
            'input_category': input_metrics['category'],
            'input_fingerprint': input_metrics['fingerprint'],
            'input_char_count': input_metrics['char_count'],
            'input_estimated_tokens': input_metrics['estimated_tokens'],

            # Raw metrics
            'total_cost': session_data['total_cost'],
            'total_duration_ms': session_data['total_duration_ms'],
            'total_tokens_in': session_data['total_tokens_in'],
            'total_tokens_out': session_data['total_tokens_out'],
            'total_tokens': session_data['total_tokens'],
            'message_count': session_data['message_count'],
            'cell_count': session_data['cell_count'],
            'error_count': session_data['error_count'],
            'candidate_count': session_data.get('candidate_count', 0),
            'winner_candidate_index': session_data.get('winner_candidate_index'),

            # Baselines
            'global_avg_cost': baselines['global'].get('avg_cost', 0),
            'global_avg_duration': baselines['global'].get('avg_duration', 0),
            'global_avg_tokens': baselines['global'].get('avg_tokens', 0),
            'global_run_count': baselines['global'].get('run_count', 0),

            'cluster_avg_cost': baselines['cluster'].get('avg_cost', 0),
            'cluster_stddev_cost': baselines['cluster'].get('stddev_cost', 0),
            'cluster_avg_duration': baselines['cluster'].get('avg_duration', 0),
            'cluster_stddev_duration': baselines['cluster'].get('stddev_duration', 0),
            'cluster_avg_tokens': baselines['cluster'].get('avg_tokens', 0),
            'cluster_stddev_tokens': baselines['cluster'].get('stddev_tokens', 0),
            'cluster_run_count': baselines['cluster'].get('run_count', 0),

            'genus_avg_cost': baselines['genus'].get('avg_cost'),
            'genus_avg_duration': baselines['genus'].get('avg_duration'),
            'genus_run_count': baselines['genus'].get('run_count', 0),

            # Anomaly scores
            'cost_z_score': z_scores['cost'],
            'duration_z_score': z_scores['duration'],
            'tokens_z_score': z_scores['tokens'],
            'is_cost_outlier': abs(z_scores['cost']) > 2,
            'is_duration_outlier': abs(z_scores['duration']) > 2,
            'is_tokens_outlier': abs(z_scores['tokens']) > 2,

            # Efficiency
            'cost_per_message': efficiency['cost_per_message'],
            'cost_per_token': efficiency['cost_per_token'],
            'duration_per_message': efficiency['duration_per_message'],
            'tokens_per_message': efficiency['tokens_per_message'],

            # Models
            'models_used': models['models'],
            'primary_model': models['primary'],
            'model_switches': models['switches'],

            # Temporal
            'hour_of_day': temporal['hour'],
            'day_of_week': temporal['day'],
            'is_weekend': temporal['is_weekend'],
        }

        # Step 10: Analyze individual cells (cell-level analytics)
        # Returns both anomalies and context metrics for cascade rollup
        cell_result = _analyze_cells(
            session_id=session_id,
            db=db,
            cascade_id=session_data['cascade_id'],
            genus_hash=session_data.get('genus_hash', ''),
            cascade_total_cost=session_data['total_cost'],
            cascade_total_duration=session_data['total_duration_ms']
        )

        cell_anomalies = cell_result.get('anomalies', [])
        cascade_context_metrics = cell_result.get('cascade_context_metrics', {})

        # Add cascade-level context attribution to analytics_row
        analytics_row.update({
            'total_context_tokens': cascade_context_metrics.get('total_context_tokens', 0),
            'total_new_tokens': cascade_context_metrics.get('total_new_tokens', 0),
            'total_context_cost_estimated': cascade_context_metrics.get('total_context_cost', 0),
            'total_new_cost_estimated': cascade_context_metrics.get('total_new_cost', 0),
            'context_cost_pct': cascade_context_metrics.get('context_pct', 0),
            'cells_with_context': cascade_context_metrics.get('cells_with_context', 0),
            'avg_cell_context_pct': cascade_context_metrics.get('avg_cell_context_pct', 0),
            'max_cell_context_pct': cascade_context_metrics.get('max_cell_context_pct', 0),
        })

        # Step 9: Insert into cascade_analytics (after adding context metrics)
        db.insert_rows(
            'cascade_analytics',
            [analytics_row],
            columns=list(analytics_row.keys())
        )

        # Step 11: Check for anomalies (cascade + cell level)
        anomalies = []
        if analytics_row['is_cost_outlier']:
            anomalies.append(f"Cascade cost outlier: {z_scores['cost']:.1f}σ")
        if analytics_row['is_duration_outlier']:
            anomalies.append(f"Cascade duration outlier: {z_scores['duration']:.1f}σ")

        # Add cell-level anomalies
        anomalies.extend(cell_anomalies)

        # Count cells with context for relevance analysis reporting
        import os
        cells_with_context = cascade_context_metrics.get('cells_with_context', 0)
        relevance_enabled = os.getenv('RVBBIT_ENABLE_RELEVANCE_ANALYSIS', 'true').lower() == 'true'

        logger.info(f"[Analytics] {session_id}: {len(cell_result.get('cell_rows', []))} cells analyzed, "
                   f"{cells_with_context} with context (relevance analysis: {'enabled' if relevance_enabled else 'disabled'})")

        return {
            'success': True,
            'session_id': session_id,
            'anomalies': anomalies,
            'z_scores': z_scores,
            'cell_anomalies': cell_anomalies,
            'cells_with_context': cells_with_context,
        }

    except Exception as e:
        import traceback
        logger.error(f"Analytics worker failed for {session_id}: {e}")
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e),
            'session_id': session_id
        }


def _fetch_session_data(session_id: str, db) -> Optional[Dict]:
    """
    Fetch session data from unified_logs and cascade_sessions.

    Aggregates:
    - Total cost, duration, tokens from unified_logs
    - Message count, cell count, error count
    - Input data, genus_hash from cascade_sessions
    - Created timestamp

    Returns:
        Dict with session metrics, or None if session not found
    """
    try:
        # Aggregate metrics from unified_logs
        # Use wall time (first event to last event) for accurate duration
        metrics_query = f"""
            SELECT
                SUM(cost) as total_cost,
                dateDiff('millisecond', min(timestamp), max(timestamp)) as total_duration_ms,
                SUM(tokens_in) as total_tokens_in,
                SUM(tokens_out) as total_tokens_out,
                COUNT(*) as message_count,
                COUNT(DISTINCT cell_name) as cell_count,
                countIf(node_type LIKE '%%error%%') as error_count,
                uniqExactIf(candidate_index, candidate_index IS NOT NULL) as candidate_count,
                anyIf(candidate_index, is_winner = 1) as winner_candidate_index
            FROM unified_logs
            WHERE session_id = '{session_id}'
        """

        metrics_result = db.query(metrics_query)

        if not metrics_result or not metrics_result[0]:
            return None

        metrics = metrics_result[0]

        # Get cascade context from cascade_sessions
        session_query = f"""
            SELECT
                cascade_id,
                input_data,
                genus_hash,
                created_at
            FROM cascade_sessions
            WHERE session_id = '{session_id}'
        """

        session_result = db.query(session_query)

        if not session_result or not session_result[0]:
            return None

        session_info = session_result[0]

        # Combine data
        return {
            'session_id': session_id,
            'cascade_id': session_info['cascade_id'],
            'genus_hash': session_info.get('genus_hash', ''),
            'created_at': session_info['created_at'],
            'input_data': session_info.get('input_data', ''),

            # Aggregated metrics
            'total_cost': float(metrics.get('total_cost', 0) or 0),
            'total_duration_ms': float(metrics.get('total_duration_ms', 0) or 0),
            'total_tokens_in': int(metrics.get('total_tokens_in', 0) or 0),
            'total_tokens_out': int(metrics.get('total_tokens_out', 0) or 0),
            'total_tokens': int(metrics.get('total_tokens_in', 0) or 0) + int(metrics.get('total_tokens_out', 0) or 0),
            'message_count': int(metrics.get('message_count', 0) or 0),
            'cell_count': int(metrics.get('cell_count', 0) or 0),
            'error_count': int(metrics.get('error_count', 0) or 0),
            'candidate_count': int(metrics.get('candidate_count', 0) or 0),
            'winner_candidate_index': metrics.get('winner_candidate_index'),
        }

    except Exception as e:
        logger.error(f"Failed to fetch session data for {session_id}: {e}")
        return None


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
    if not input_data_json or not input_data_json.strip():
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
    estimated_tokens = char_count // 4  # Rough estimate (1 token ≈ 4 chars)

    # JSON depth (measures nesting complexity)
    def max_depth(obj, current=0):
        if not isinstance(obj, (dict, list)):
            return current
        if isinstance(obj, dict):
            return max([max_depth(obj[k], current + 1) for k in obj.keys()] or [current])
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

    # Category buckets (for clustering)
    if score < 0.1:
        category = 'tiny'       # < 1000 chars
    elif score < 0.3:
        category = 'small'      # 1000-3000 chars
    elif score < 0.6:
        category = 'medium'     # 3000-6000 chars
    elif score < 0.85:
        category = 'large'      # 6000-8500 chars
    else:
        category = 'huge'       # 8500+ chars

    # Input fingerprint: hash of input structure (keys + types + size buckets)
    # This allows clustering similar inputs by both structure AND size
    def get_structure(obj):
        if isinstance(obj, dict):
            return {k: get_structure(obj[k]) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            # Include array length bucket
            length_bucket = (
                'tiny' if len(obj) < 10 else
                'small' if len(obj) < 100 else
                'medium' if len(obj) < 1000 else
                'large'
            )
            return ['array', length_bucket]
        elif isinstance(obj, str):
            # Include string length bucket for clustering different-sized inputs
            length_bucket = (
                'tiny' if len(obj) < 20 else
                'small' if len(obj) < 100 else
                'medium' if len(obj) < 500 else
                'large'
            )
            return ['str', length_bucket]
        elif isinstance(obj, (int, float)):
            # Include number magnitude bucket
            abs_val = abs(obj)
            magnitude = (
                'tiny' if abs_val < 10 else
                'small' if abs_val < 1000 else
                'medium' if abs_val < 1000000 else
                'large'
            )
            return [type(obj).__name__, magnitude]
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


def _compute_baselines(db, cascade_id: str, input_category: str, genus_hash: Optional[str]) -> Dict:
    """
    Compute context-aware baselines for comparison.

    Three tiers:
    1. Global: All historical runs for this cascade
    2. Cluster: Runs with same input_category (apples to apples!)
    3. Genus: Runs with same genus_hash (most specific!)

    Returns nested dict with avg/stddev for cost, duration, tokens.
    """
    baselines = {
        'global': {},
        'cluster': {},
        'genus': {},
    }

    try:
        # Global baseline (all runs for this cascade)
        global_query = f"""
            SELECT
                if(isNaN(AVG(total_cost)), 0, AVG(total_cost)) as avg_cost,
                if(isNaN(AVG(total_duration_ms)), 0, AVG(total_duration_ms)) as avg_duration,
                if(isNaN(AVG(total_tokens)), 0, AVG(total_tokens)) as avg_tokens,
                COUNT(*) as run_count
            FROM cascade_analytics
            WHERE cascade_id = '{cascade_id}'
        """

        global_result = db.query(global_query)

        if global_result and global_result[0]:
            baselines['global'] = {
                'avg_cost': float(global_result[0].get('avg_cost', 0) or 0),
                'avg_duration': float(global_result[0].get('avg_duration', 0) or 0),
                'avg_tokens': float(global_result[0].get('avg_tokens', 0) or 0),
                'run_count': int(global_result[0].get('run_count', 0) or 0),
            }

    except Exception as e:
        logger.debug(f"Could not compute global baseline: {e}")

    try:
        # Cluster baseline (same input category)
        cluster_query = f"""
            SELECT
                if(isNaN(AVG(total_cost)), 0, AVG(total_cost)) as avg_cost,
                if(isNaN(stddevPop(total_cost)), 0, stddevPop(total_cost)) as stddev_cost,
                if(isNaN(AVG(total_duration_ms)), 0, AVG(total_duration_ms)) as avg_duration,
                if(isNaN(stddevPop(total_duration_ms)), 0, stddevPop(total_duration_ms)) as stddev_duration,
                if(isNaN(AVG(total_tokens)), 0, AVG(total_tokens)) as avg_tokens,
                if(isNaN(stddevPop(total_tokens)), 0, stddevPop(total_tokens)) as stddev_tokens,
                COUNT(*) as run_count
            FROM cascade_analytics
            WHERE cascade_id = '{cascade_id}'
              AND input_category = '{input_category}'
        """

        cluster_result = db.query(cluster_query)

        if cluster_result and cluster_result[0]:
            baselines['cluster'] = {
                'avg_cost': float(cluster_result[0].get('avg_cost', 0) or 0),
                'stddev_cost': float(cluster_result[0].get('stddev_cost', 0) or 0),
                'avg_duration': float(cluster_result[0].get('avg_duration', 0) or 0),
                'stddev_duration': float(cluster_result[0].get('stddev_duration', 0) or 0),
                'avg_tokens': float(cluster_result[0].get('avg_tokens', 0) or 0),
                'stddev_tokens': float(cluster_result[0].get('stddev_tokens', 0) or 0),
                'run_count': int(cluster_result[0].get('run_count', 0) or 0),
            }

    except Exception as e:
        logger.debug(f"Could not compute cluster baseline: {e}")

    try:
        # Genus baseline (same genus_hash - most specific!)
        if genus_hash and genus_hash != '':
            genus_query = f"""
                SELECT
                    if(isNaN(AVG(total_cost)), 0, AVG(total_cost)) as avg_cost,
                    if(isNaN(AVG(total_duration_ms)), 0, AVG(total_duration_ms)) as avg_duration,
                    COUNT(*) as run_count
                FROM cascade_analytics
                WHERE genus_hash = '{genus_hash}'
            """

            genus_result = db.query(genus_query)

            if genus_result and genus_result[0]:
                baselines['genus'] = {
                    'avg_cost': float(genus_result[0].get('avg_cost', 0) or 0),
                    'avg_duration': float(genus_result[0].get('avg_duration', 0) or 0),
                    'run_count': int(genus_result[0].get('run_count', 0) or 0),
                }

    except Exception as e:
        logger.debug(f"Could not compute genus baseline: {e}")

    return baselines


def _calculate_z_scores(session_data: Dict, baselines: Dict) -> Dict:
    """
    Calculate Z-scores for anomaly detection.

    Z-score = (value - mean) / stddev

    Interpretation:
    - |z| < 1: Normal (within 1 standard deviation, ~68% of data)
    - |z| 1-2: Unusual (between 1-2σ, ~27% of data)
    - |z| > 2: Outlier (beyond 2σ, ~5% of data)
    - |z| > 3: Extreme outlier (beyond 3σ, ~0.3% of data)

    Returns Z-scores for cost, duration, tokens.
    """
    cluster = baselines.get('cluster', {})

    # Safe division (avoid div by zero and NaN)
    def safe_z(value, mean, stddev):
        # Handle None/NaN inputs
        if value is None or (isinstance(value, float) and str(value) == 'nan'):
            return 0.0
        if mean is None or (isinstance(mean, float) and str(mean) == 'nan'):
            return 0.0
        if stddev is None or (isinstance(stddev, float) and str(stddev) == 'nan'):
            return 0.0

        # Handle zero or very small stddev (no variance = no outliers)
        if stddev < 0.0001:
            return 0.0

        # Calculate Z-score
        z_score = float((value - mean) / stddev)

        # Final NaN check (in case calculation produced NaN)
        if str(z_score) == 'nan':
            return 0.0

        return z_score

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


def _compute_efficiency_metrics(session_data: Dict) -> Dict:
    """
    Compute per-unit efficiency metrics.

    Returns:
        {
            'cost_per_message': float,
            'cost_per_token': float,
            'duration_per_message': float,
            'tokens_per_message': float,
        }
    """
    message_count = session_data.get('message_count', 0)
    total_tokens = session_data.get('total_tokens', 0)

    return {
        'cost_per_message': (
            session_data['total_cost'] / message_count
            if message_count > 0 else 0
        ),
        'cost_per_token': (
            session_data['total_cost'] / total_tokens
            if total_tokens > 0 else 0
        ),
        'duration_per_message': (
            session_data['total_duration_ms'] / message_count
            if message_count > 0 else 0
        ),
        'tokens_per_message': (
            total_tokens / message_count
            if message_count > 0 else 0
        ),
    }


def _analyze_model_usage(session_id: str, db) -> Dict:
    """
    Analyze which models were used in this cascade.

    Returns:
        {
            'models': List[str],  # Unique models
            'primary': str,       # Most-used model
            'switches': int,      # Count of model changes
        }
    """
    try:
        query = f"""
            SELECT
                model,
                COUNT(*) as usage_count
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND model IS NOT NULL
              AND role = 'assistant'  -- Only LLM responses
            GROUP BY model
            ORDER BY usage_count DESC
        """

        result = db.query(query)

        if not result:
            return {
                'models': [],
                'primary': 'unknown',
                'switches': 0,
            }

        models = [row['model'] for row in result]
        primary = models[0] if models else 'unknown'

        # Count model switches (transitions between different models)
        switch_query = f"""
            SELECT
                COUNT(*) - 1 as switches
            FROM (
                SELECT
                    model,
                    lagInFrame(model, 1) OVER (ORDER BY timestamp) as prev_model
                FROM unified_logs
                WHERE session_id = '{session_id}'
                  AND model IS NOT NULL
                  AND role = 'assistant'
            )
            WHERE model != prev_model
        """

        switch_result = db.query(switch_query)
        switches = int(switch_result[0]['switches']) if switch_result else 0

        return {
            'models': models,
            'primary': primary,
            'switches': max(0, switches),  # Ensure non-negative
        }

    except Exception as e:
        logger.debug(f"Could not analyze model usage: {e}")
        return {
            'models': [],
            'primary': 'unknown',
            'switches': 0,
        }


def _extract_temporal_context(created_at) -> Dict:
    """
    Extract temporal context for time-of-day pattern analysis.

    Returns:
        {
            'hour': int (0-23),
            'day': int (0-6, Monday=0),
            'is_weekend': bool,
        }
    """
    try:
        # Handle both datetime objects and strings
        if isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        else:
            dt = created_at

        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return {
            'hour': dt.hour,
            'day': dt.weekday(),  # Monday=0, Sunday=6
            'is_weekend': dt.weekday() >= 5,  # Saturday=5, Sunday=6
        }

    except Exception as e:
        logger.debug(f"Could not extract temporal context: {e}")
        return {
            'hour': 0,
            'day': 0,
            'is_weekend': False,
        }

def _analyze_cells(session_id: str, db, cascade_id: str, genus_hash: str,
                   cascade_total_cost: float, cascade_total_duration: float) -> List[str]:
    """
    Analyze individual cells and insert into cell_analytics.

    Metrics don't roll up naturally from cells to cascade, so we track both:
    - cascade_analytics: Whole cascade performance
    - cell_analytics: Individual cell performance (bottleneck detection!)

    Returns:
        List of cell-level anomaly messages
    """
    try:
        # Get list of cells executed in this session with their metrics
        cell_query = f"""
            SELECT
                cell_name,
                any(species_hash) as species_hash,
                COUNT(DISTINCT CASE WHEN role = 'assistant' THEN model END) as model_count,
                any(model) as primary_model,
                SUM(cost) as cell_cost,
                dateDiff('millisecond', min(timestamp), max(timestamp)) as cell_duration_ms,
                SUM(tokens_in) as tokens_in,
                SUM(tokens_out) as tokens_out,
                COUNT(*) as message_count,
                COUNT(DISTINCT turn_number) as turn_count,
                uniqExactIf(candidate_index, candidate_index IS NOT NULL) as candidate_count,
                countIf(node_type LIKE '%%error%%') > 0 as error_occurred
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name IS NOT NULL
            GROUP BY cell_name
            ORDER BY min(timestamp)
        """

        cell_results = db.query(cell_query)

        if not cell_results:
            return []

        cell_rows = []
        cell_anomalies = []
        total_cells = len(cell_results)

        for idx, cell in enumerate(cell_results):
            cell_name = cell['cell_name']
            species_hash = cell['species_hash'] or ''

            # Calculate contribution percentages (handle None values from incomplete/error cells)
            cell_cost = cell.get('cell_cost') or 0
            cell_duration = cell.get('cell_duration_ms') or 0
            cell_cost_pct = (cell_cost / cascade_total_cost * 100) if cascade_total_cost > 0 and cell_cost else 0
            cell_duration_pct = (cell_duration / cascade_total_duration * 100) if cascade_total_duration > 0 and cell_duration else 0

            # Analyze context attribution (RVBBIT's unique capability!)
            context_attr = _analyze_context_attribution(session_id, cell_name, db)

            # Query baselines for THIS CELL
            cell_baselines = _compute_cell_baselines(
                db, cascade_id, cell_name, species_hash
            )

            # Calculate cell-level Z-scores
            cell_z_scores = _calculate_cell_z_scores(cell, cell_baselines)

            # Efficiency metrics
            turn_count = cell['turn_count'] or 1
            cell_tokens = (cell['tokens_in'] or 0) + (cell['tokens_out'] or 0)

            cell_row = {
                'session_id': session_id,
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'species_hash': species_hash,
                'genus_hash': genus_hash,
                'created_at': datetime.now(timezone.utc),

                # Cell type detection
                'cell_type': 'llm' if cell['model_count'] > 0 else 'deterministic',
                'tool': None,  # Would need to query phase_config
                'model': cell.get('primary_model'),

                # Raw metrics
                'cell_cost': float(cell['cell_cost'] or 0),
                'cell_duration_ms': float(cell['cell_duration_ms'] or 0),
                'cell_tokens_in': int(cell['tokens_in'] or 0),
                'cell_tokens_out': int(cell['tokens_out'] or 0),
                'cell_tokens': cell_tokens,
                'message_count': int(cell['message_count'] or 0),
                'turn_count': int(turn_count),
                'candidate_count': int(cell['candidate_count'] or 0),
                'error_occurred': bool(cell['error_occurred']),

                # Baselines
                'global_cell_avg_cost': cell_baselines['global'].get('avg_cost', 0),
                'global_cell_avg_duration': cell_baselines['global'].get('avg_duration', 0),
                'global_cell_run_count': cell_baselines['global'].get('run_count', 0),

                'species_avg_cost': cell_baselines['species'].get('avg_cost', 0),
                'species_stddev_cost': cell_baselines['species'].get('stddev_cost', 0),
                'species_avg_duration': cell_baselines['species'].get('avg_duration', 0),
                'species_stddev_duration': cell_baselines['species'].get('stddev_duration', 0),
                'species_run_count': cell_baselines['species'].get('run_count', 0),

                # Anomaly scores
                'cost_z_score': cell_z_scores['cost'],
                'duration_z_score': cell_z_scores['duration'],
                'is_cost_outlier': abs(cell_z_scores['cost']) > 2,
                'is_duration_outlier': abs(cell_z_scores['duration']) > 2,

                # Efficiency (handle None values)
                'cost_per_turn': float((cell['cell_cost'] or 0) / turn_count if turn_count > 0 else 0),
                'cost_per_token': float((cell['cell_cost'] or 0) / cell_tokens if cell_tokens > 0 else 0),
                'tokens_per_turn': float(cell_tokens / turn_count if turn_count > 0 else 0),
                'duration_per_turn': float((cell['cell_duration_ms'] or 0) / turn_count if turn_count > 0 else 0),

                # Cascade context
                'cascade_total_cost': cascade_total_cost,
                'cascade_total_duration': cascade_total_duration,
                'cell_cost_pct': cell_cost_pct,
                'cell_duration_pct': cell_duration_pct,

                # Position
                'cell_index': idx,
                'is_first_cell': idx == 0,
                'is_last_cell': idx == total_cells - 1,

                # Context attribution (RVBBIT's unique insight!)
                'context_token_count': context_attr['context_tokens'],
                'new_message_tokens': context_attr['new_tokens'],
                'context_message_count': context_attr['context_messages'],
                'has_context': context_attr['has_context'],
                'context_depth_avg': context_attr['context_depth_avg'],
                'context_depth_max': context_attr['context_depth_max'],
                'context_cost_estimated': context_attr['context_cost_estimated'],
                'new_message_cost_estimated': context_attr['new_cost_estimated'],
                'context_cost_pct': context_attr['context_pct'],
            }

            cell_rows.append(cell_row)

            # Create granular context breakdown (per-message attribution)
            if context_attr['has_context']:
                _create_context_breakdown(
                    session_id=session_id,
                    cell_name=cell_name,
                    cell_index=idx,
                    cascade_id=cascade_id,
                    total_cell_cost=cell['cell_cost'] or 0,
                    db=db
                )

            # Check for cell-level anomalies
            if cell_row['is_cost_outlier']:
                cell_anomalies.append(f"Cell '{cell_name}' cost outlier: {cell_z_scores['cost']:.1f}σ")
            if cell_row['is_duration_outlier']:
                cell_anomalies.append(f"Cell '{cell_name}' duration outlier: {cell_z_scores['duration']:.1f}σ")

        # Insert all cell analytics
        if cell_rows:
            db.insert_rows(
                'cell_analytics',
                cell_rows,
                columns=list(cell_rows[0].keys())
            )

        # Aggregate context metrics across all cells for cascade rollup
        cascade_context_metrics = {}
        if cell_rows:
            total_context_tokens = sum(row['context_token_count'] for row in cell_rows)
            total_new_tokens = sum(row['new_message_tokens'] for row in cell_rows)
            total_context_cost = sum(row['context_cost_estimated'] for row in cell_rows)
            total_new_cost = sum(row['new_message_cost_estimated'] for row in cell_rows)
            cells_with_context = sum(1 for row in cell_rows if row['has_context'])

            # Calculate cascade-level context percentage
            total_tokens = total_context_tokens + total_new_tokens
            cascade_context_pct = (total_context_tokens / total_tokens * 100) if total_tokens > 0 else 0

            # Average and max context % across cells
            cell_context_pcts = [row['context_cost_pct'] for row in cell_rows if row['has_context']]
            avg_cell_context_pct = (sum(cell_context_pcts) / len(cell_context_pcts)) if cell_context_pcts else 0
            max_cell_context_pct = max(cell_context_pcts) if cell_context_pcts else 0

            cascade_context_metrics = {
                'total_context_tokens': total_context_tokens,
                'total_new_tokens': total_new_tokens,
                'total_context_cost': total_context_cost,
                'total_new_cost': total_new_cost,
                'context_pct': cascade_context_pct,
                'cells_with_context': cells_with_context,
                'avg_cell_context_pct': avg_cell_context_pct,
                'max_cell_context_pct': max_cell_context_pct,
            }

        return {
            'anomalies': cell_anomalies,
            'cascade_context_metrics': cascade_context_metrics,
        }

    except Exception as e:
        logger.error(f"Cell analytics failed for {session_id}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'anomalies': [],
            'cascade_context_metrics': {},
        }


def _compute_cell_baselines(db, cascade_id: str, cell_name: str, species_hash: str) -> Dict:
    """
    Compute baselines for a specific cell.

    Two tiers:
    1. Global: All historical runs of this cell (in this cascade)
    2. Species: Runs with same species_hash (exact cell config)
    """
    baselines = {
        'global': {},
        'species': {},
    }

    try:
        # Global baseline (all runs of this cell)
        global_query = f"""
            SELECT
                if(isNaN(AVG(cell_cost)), 0, AVG(cell_cost)) as avg_cost,
                if(isNaN(AVG(cell_duration_ms)), 0, AVG(cell_duration_ms)) as avg_duration,
                COUNT(*) as run_count
            FROM cell_analytics
            WHERE cascade_id = '{cascade_id}'
              AND cell_name = '{cell_name}'
        """

        global_result = db.query(global_query)

        if global_result and global_result[0]:
            baselines['global'] = {
                'avg_cost': float(global_result[0].get('avg_cost', 0) or 0),
                'avg_duration': float(global_result[0].get('avg_duration', 0) or 0),
                'run_count': int(global_result[0].get('run_count', 0) or 0),
            }

    except Exception as e:
        logger.debug(f"Could not compute global cell baseline: {e}")

    try:
        # Species baseline (same species_hash - exact config)
        if species_hash and species_hash != '':
            species_query = f"""
                SELECT
                    if(isNaN(AVG(cell_cost)), 0, AVG(cell_cost)) as avg_cost,
                    if(isNaN(stddevPop(cell_cost)), 0, stddevPop(cell_cost)) as stddev_cost,
                    if(isNaN(AVG(cell_duration_ms)), 0, AVG(cell_duration_ms)) as avg_duration,
                    if(isNaN(stddevPop(cell_duration_ms)), 0, stddevPop(cell_duration_ms)) as stddev_duration,
                    COUNT(*) as run_count
                FROM cell_analytics
                WHERE species_hash = '{species_hash}'
            """

            species_result = db.query(species_query)

            if species_result and species_result[0]:
                baselines['species'] = {
                    'avg_cost': float(species_result[0].get('avg_cost', 0) or 0),
                    'stddev_cost': float(species_result[0].get('stddev_cost', 0) or 0),
                    'avg_duration': float(species_result[0].get('avg_duration', 0) or 0),
                    'stddev_duration': float(species_result[0].get('stddev_duration', 0) or 0),
                    'run_count': int(species_result[0].get('run_count', 0) or 0),
                }

    except Exception as e:
        logger.debug(f"Could not compute species cell baseline: {e}")

    return baselines


def _calculate_cell_z_scores(cell_data: Dict, baselines: Dict) -> Dict:
    """
    Calculate Z-scores for cell-level anomaly detection.

    Uses species baseline (most specific) if available, else global.
    """
    # Prefer species baseline (exact config match)
    if baselines.get('species') and baselines['species'].get('run_count', 0) > 2:
        baseline = baselines['species']
    else:
        baseline = baselines.get('global', {})

    # Safe Z-score calculation (same logic as cascade-level)
    def safe_z(value, mean, stddev):
        if value is None or (isinstance(value, float) and str(value) == 'nan'):
            return 0.0
        if mean is None or (isinstance(mean, float) and str(mean) == 'nan'):
            return 0.0
        if stddev is None or (isinstance(stddev, float) and str(stddev) == 'nan'):
            return 0.0
        if stddev < 0.0001:
            return 0.0

        z_score = float((value - mean) / stddev)

        if str(z_score) == 'nan':
            return 0.0

        return z_score

    return {
        'cost': safe_z(
            cell_data.get('cell_cost', 0),
            baseline.get('avg_cost'),
            baseline.get('stddev_cost')
        ),
        'duration': safe_z(
            cell_data.get('cell_duration_ms', 0),
            baseline.get('avg_duration'),
            baseline.get('stddev_duration')
        ),
    }


def _analyze_context_attribution(session_id: str, cell_name: str, db) -> Dict:
    """
    Decompose cell cost into context vs new message costs.

    Uses RVBBIT's unique context_hashes tracking to calculate token/cost
    attribution for context injection.

    Strategy:
    Since context messages (user prompts) don't have token counts, we use
    a heuristic: estimate context contribution by comparing first cell to later cells.
    - First cell: tokens_in = new prompt only
    - Later cells: tokens_in = context + new prompt

    This is CRITICAL for understanding hidden costs:
    - Context injection often accounts for 60-80% of LLM costs
    - Appears as "expensive cell" but is actually "heavy context"
    - Enables targeted optimization (selective context, not more efficient prompts)

    Returns:
        {
            'context_tokens': int,
            'new_tokens': int,
            'context_messages': int,
            'context_cost_estimated': float,
            'new_cost_estimated': float,
            'context_pct': float,
            'context_depth_avg': float,
            'context_depth_max': int,
            'has_context': bool,
        }
    """
    try:
        # Get LLM messages for this cell
        messages_query = f"""
            SELECT
                tokens_in,
                tokens_out,
                cost,
                length(context_hashes) as context_depth
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND role = 'assistant'
              AND model IS NOT NULL
        """

        messages = db.query(messages_query)

        if not messages or len(messages) == 0:
            # No LLM messages in this cell
            return {
                'context_tokens': 0,
                'new_tokens': 0,
                'context_messages': 0,
                'context_cost_estimated': 0,
                'new_cost_estimated': 0,
                'context_pct': 0,
                'context_depth_avg': 0,
                'context_depth_max': 0,
                'has_context': False,
            }

        # Get first cell's tokens_in as baseline (no context, pure prompt)
        first_cell_query = f"""
            SELECT AVG(tokens_in) as avg_tokens_in
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND role = 'assistant'
              AND model IS NOT NULL
              AND length(context_hashes) = 0
            LIMIT 1
        """

        first_cell = db.query(first_cell_query)
        baseline_tokens_in = first_cell[0]['avg_tokens_in'] if first_cell and first_cell[0]['avg_tokens_in'] else 0

        # Aggregate this cell's data
        total_tokens_in = sum(msg['tokens_in'] or 0 for msg in messages)
        total_tokens_out = sum(msg['tokens_out'] or 0 for msg in messages)
        total_cost = sum(msg['cost'] or 0 for msg in messages)
        context_depths = [msg['context_depth'] for msg in messages if msg['context_depth']]

        # Calculate context vs new tokens
        # Context tokens = extra tokens_in compared to baseline (first cell with no context)
        # New work tokens = tokens_out (what THIS cell generated)
        num_messages = len(messages)
        estimated_context_tokens = max(0, total_tokens_in - (baseline_tokens_in * num_messages))
        new_work_tokens = total_tokens_out  # Output tokens = actual new content

        # Estimate cost attribution
        # Context cost = cost of processing injected context (input overhead)
        # New work cost = cost of generating new content (actual work)
        total_tokens = total_tokens_in + total_tokens_out

        if total_tokens > 0:
            # Context cost = proportion of tokens that are context overhead
            context_cost_pct = (estimated_context_tokens / total_tokens) * 100
            context_cost_estimated = (estimated_context_tokens / total_tokens) * total_cost

            # New work cost = cost of generating output
            new_work_cost_pct = (new_work_tokens / total_tokens) * 100
            new_work_cost_estimated = (new_work_tokens / total_tokens) * total_cost
        else:
            context_cost_pct = 0
            context_cost_estimated = 0
            new_work_cost_estimated = total_cost

        # Context depth statistics
        context_depth_avg = sum(context_depths) / len(context_depths) if context_depths else 0
        context_depth_max = max(context_depths) if context_depths else 0
        has_context = any(msg['context_depth'] > 0 for msg in messages)

        return {
            'context_tokens': int(estimated_context_tokens),
            'new_tokens': int(new_work_tokens),  # Use new_work_tokens (tokens_out)
            'context_messages': int(context_depth_avg) if context_depth_avg else 0,
            'context_cost_estimated': context_cost_estimated,
            'new_cost_estimated': new_work_cost_estimated,  # Use new_work_cost
            'context_pct': context_cost_pct,
            'context_depth_avg': context_depth_avg,
            'context_depth_max': context_depth_max,
            'has_context': has_context,
        }

    except Exception as e:
        logger.debug(f"Could not analyze context attribution for {cell_name}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'context_tokens': 0,
            'new_tokens': 0,
            'context_messages': 0,
            'context_cost_estimated': 0,
            'new_cost_estimated': 0,
            'context_pct': 0,
            'context_depth_avg': 0,
            'context_depth_max': 0,
            'has_context': False,
        }


def _analyze_context_relevance(session_id: str, cascade_id: str, cell_name: str,
                                messages: list, db) -> None:
    """
    Analyze context message relevance using a cheap LLM.

    Calls traits/analyze_context_relevance.yaml to score each context message
    based on how much it contributed to the generated output.

    Updates cell_context_breakdown with relevance_score and relevance_reasoning.

    Cost: ~$0.0001 per cell (using gemini-flash-lite)
    """
    try:
        from .runner import RVBBITRunner
        import json as json_module

        # Get the assistant output for this cell
        # Prefer the winner candidate, or the last message if no winner marked
        output_query = f"""
            SELECT content_json, content_hash
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND role = 'assistant'
              AND model IS NOT NULL
            ORDER BY is_winner DESC, timestamp DESC
            LIMIT 1
        """

        output_result = db.query(output_query)
        if not output_result:
            logger.debug(f"No assistant output found for {cell_name}, skipping relevance analysis")
            return

        output_content = output_result[0]['content_json']

        # Get all context messages that were found in breakdown
        # Query to get the unique context hashes for this cell
        context_hashes_query = f"""
            SELECT DISTINCT context_message_hash
            FROM cell_context_breakdown
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
        """

        hash_results = db.query(context_hashes_query)
        if not hash_results:
            return

        # Fetch content for each context message
        context_messages = []
        for row in hash_results:
            ctx_hash = row['context_message_hash']

            # Look up the actual content AND role
            content_query = f"""
                SELECT content_json, tokens_in, tokens_out, role
                FROM unified_logs
                WHERE session_id = '{session_id}'
                  AND content_hash = '{ctx_hash}'
                LIMIT 1
            """

            content_result = db.query(content_query)
            if content_result:
                ctx_content = content_result[0]['content_json']
                ctx_tokens = (content_result[0]['tokens_in'] or 0) + (content_result[0]['tokens_out'] or 0)
                ctx_role = content_result[0]['role']

                # Get the cost from breakdown table
                cost_query = f"""
                    SELECT context_message_cost_estimated
                    FROM cell_context_breakdown
                    WHERE session_id = '{session_id}'
                      AND cell_name = '{cell_name}'
                      AND context_message_hash = '{ctx_hash}'
                    LIMIT 1
                """
                cost_result = db.query(cost_query)
                ctx_cost = cost_result[0]['context_message_cost_estimated'] if cost_result else 0

                context_messages.append({
                    'hash': ctx_hash,
                    'content': ctx_content or '',
                    'tokens': ctx_tokens,
                    'cost': ctx_cost,
                    'role': ctx_role,  # Include role so LLM knows which are system messages
                })

        if not context_messages:
            return

        # Run the relevance analysis cascade
        analysis_session_id = f"{session_id}_relevance_{cell_name}"

        logger.info(f"Analyzing relevance for {len(context_messages)} context messages in {cell_name}")

        runner = RVBBITRunner(
            config_path='traits/analyze_context_relevance.yaml',
            session_id=analysis_session_id,
            depth=1  # Mark as sub-cascade
        )

        result = runner.run(input_data={
            'output_content': output_content,
            'context_messages': context_messages,
        })

        if not result:
            logger.warning(f"Relevance analysis returned no result for {cell_name}")
            return

        # Extract output from result (check multiple possible locations)
        output_text = None

        # Try lineage first (where outputs are stored)
        if result.get('lineage'):
            for entry in reversed(result['lineage']):
                if isinstance(entry, dict) and 'output' in entry:
                    output_text = entry['output']
                    break

        # Fallback to history
        if not output_text and result.get('history'):
            for msg in reversed(result['history']):
                if isinstance(msg, dict) and msg.get('role') == 'assistant':
                    output_text = msg.get('content_json') or msg.get('content')
                    if output_text:
                        break

        if not output_text:
            logger.warning(f"Relevance analysis completed but no output found for {cell_name}")
            logger.debug(f"Result keys: {result.keys()}")
            return

        logger.debug(f"[Relevance] Got output for {cell_name}, length={len(str(output_text))}")

        # Parse the JSON response
        # Strip markdown code fences if present (LLMs often wrap JSON in ```json ... ```)
        if isinstance(output_text, str):
            output_text = output_text.strip()
        else:
            # If already parsed as JSON (from content_json), stringify it
            output_text = json_module.dumps(output_text) if isinstance(output_text, (dict, list)) else str(output_text)

        # Remove markdown fences
        if output_text.startswith('```'):
            # Find the end of first line (language identifier like "json")
            first_newline = output_text.find('\n')
            if first_newline > 0:
                output_text = output_text[first_newline + 1:]
            # Remove trailing fence
            if output_text.endswith('```'):
                output_text = output_text[:-3].strip()

        try:
            relevance_scores = json_module.loads(output_text)

            # Handle case where LLM returns single object instead of array (common with 1 context message)
            if isinstance(relevance_scores, dict):
                logger.debug(f"LLM returned single object instead of array, wrapping it")
                relevance_scores = [relevance_scores]

            if not isinstance(relevance_scores, list):
                logger.warning(f"Relevance analysis returned unexpected type {type(relevance_scores)} for {cell_name}")
                return

        except json_module.JSONDecodeError as e:
            logger.warning(f"Could not parse relevance analysis JSON for {cell_name}: {e}")
            logger.debug(f"Raw output (first 300 chars): {output_text[:300]}")
            return

        # Get the analysis cost from the meta-analysis session
        cost_query = f"""
            SELECT SUM(cost) as total_cost
            FROM unified_logs
            WHERE session_id = '{analysis_session_id}'
        """
        cost_result = db.query(cost_query)
        analysis_cost = float(cost_result[0]['total_cost']) if cost_result and cost_result[0]['total_cost'] else 0

        # Update each context breakdown row with relevance scores
        current_time = datetime.now(timezone.utc)

        logger.debug(f"[Relevance] Parsed {len(relevance_scores)} scores from LLM output")

        updated_count = 0
        for score_data in relevance_scores:
            ctx_hash = score_data.get('hash', '')
            score = score_data.get('score', 0)
            reason = score_data.get('reason', '')

            logger.debug(f"[Relevance]   Updating hash={ctx_hash} score={score}")

            # Match by hash prefix (analysis returns 8 chars, DB has full hash)
            update_query = f"""
                ALTER TABLE cell_context_breakdown
                UPDATE
                    relevance_score = {score},
                    relevance_reasoning = '{reason.replace("'", "''")}',
                    relevance_analysis_cost = {analysis_cost / len(relevance_scores)},
                    relevance_analyzed_at = toDateTime('{current_time.strftime('%Y-%m-%d %H:%M:%S')}'),
                    relevance_analysis_session = '{analysis_session_id}'
                WHERE session_id = '{session_id}'
                  AND cell_name = '{cell_name}'
                  AND startsWith(context_message_hash, '{ctx_hash[:8]}')
            """

            try:
                db.query(update_query)
                updated_count += 1
            except Exception as e:
                logger.warning(f"[Relevance] Failed to update hash {ctx_hash}: {e}")

        # Verify updates worked
        verify_query = f"""
            SELECT COUNT(*) as count
            FROM cell_context_breakdown
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND relevance_score IS NOT NULL
        """
        verify_result = db.query(verify_query)
        actual_count = verify_result[0]['count'] if verify_result else 0

        logger.info(f"[Relevance] ✓ {cell_name}: scored {len(relevance_scores)} messages, updated {actual_count} rows, cost=${analysis_cost:.6f}, session={analysis_session_id}")

    except Exception as e:
        logger.warning(f"Relevance analysis failed for {cell_name}: {e}")
        import traceback
        traceback.print_exc()


def _create_context_breakdown(session_id: str, cell_name: str, cell_index: int,
                               cascade_id: str, total_cell_cost: float, db) -> None:
    """
    Create granular per-message context breakdown for this cell.

    This enables pinpointing WHICH specific messages are causing context bloat:
    - "Message ABC123 from 'research' cell contributes 200 tokens (42% of cost)"
    - "Removing message DEF456 saves $0.000300"

    Inserts rows into cell_context_breakdown table.
    """
    try:
        # Get messages with context for this cell
        messages_query = f"""
            SELECT
                message_id,
                content_hash,
                context_hashes,
                tokens_in,
                tokens_out,
                cost,
                model_requested,
                candidate_index
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND role = 'assistant'
              AND model IS NOT NULL
              AND length(context_hashes) > 0
        """

        messages = db.query(messages_query)

        if not messages:
            return

        breakdown_rows = []

        for msg in messages:
            context_hashes = msg['context_hashes'] or []
            
            if not context_hashes:
                continue

            # Query details for each context message
            for ctx_idx, ctx_hash in enumerate(context_hashes):
                # Look up the context message
                ctx_lookup_query = f"""
                    SELECT
                        cell_name as source_cell,
                        role,
                        tokens_in,
                        tokens_out,
                        estimated_tokens
                    FROM unified_logs
                    WHERE session_id = '{session_id}'
                      AND content_hash = '{ctx_hash}'
                    LIMIT 1
                """

                ctx_msg = db.query(ctx_lookup_query)

                if not ctx_msg:
                    continue

                ctx_info = ctx_msg[0]

                # Get token count (prefer actual tokens, fallback to estimated)
                ctx_tokens = (
                    (ctx_info['tokens_in'] or 0) + (ctx_info['tokens_out'] or 0)
                ) or (ctx_info['estimated_tokens'] or 0)

                # Calculate accurate cost using model pricing
                # When a context message is injected, ALL its tokens become INPUT tokens in the new message
                model_requested = msg.get('model_requested')
                ctx_msg_cost = 0

                if model_requested and ctx_tokens > 0:
                    # Look up model pricing using model_requested (base model name)
                    pricing_query = f"""
                        SELECT prompt_price, completion_price
                        FROM openrouter_models
                        WHERE model_id = '{model_requested}'
                        LIMIT 1
                    """
                    try:
                        pricing_result = db.query(pricing_query)

                        if pricing_result and pricing_result[0].get('prompt_price'):
                            prompt_price = float(pricing_result[0]['prompt_price'])
                            # Context tokens are all input tokens in the new message
                            ctx_msg_cost = ctx_tokens * prompt_price
                            logger.debug(f"Context cost for {ctx_hash[:8]}: {ctx_tokens} tokens * ${prompt_price:.10f} = ${ctx_msg_cost:.8f}")
                        else:
                            # Fallback to proportional estimation if no pricing data
                            total_msg_tokens = (msg['tokens_in'] or 0) + (msg['tokens_out'] or 0)
                            if total_msg_tokens > 0 and msg['cost']:
                                ctx_msg_cost = (ctx_tokens / total_msg_tokens) * msg['cost']
                                logger.debug(f"No pricing for {model_requested}, using proportional: {ctx_tokens}/{total_msg_tokens} * ${msg['cost']:.8f} = ${ctx_msg_cost:.8f}")
                    except Exception as e:
                        logger.debug(f"Failed to look up pricing for {model_requested}: {e}")
                        # Fallback to proportional estimation
                        total_msg_tokens = (msg['tokens_in'] or 0) + (msg['tokens_out'] or 0)
                        if total_msg_tokens > 0 and msg['cost']:
                            ctx_msg_cost = (ctx_tokens / total_msg_tokens) * msg['cost']

                # Calculate percentage
                ctx_msg_pct = (ctx_msg_cost / total_cell_cost * 100) if total_cell_cost > 0 else 0

                # Sanity check: log if percentage exceeds 100% (shouldn't happen with accurate pricing)
                if ctx_msg_pct > 100:
                    logger.warning(f"Context message {ctx_hash[:8]} has {ctx_msg_pct:.1f}% of cell cost (${ctx_msg_cost:.8f} / ${total_cell_cost:.8f}) for model {model_requested}. Check pricing data.")

                breakdown_rows.append({
                    'session_id': session_id,
                    'cascade_id': cascade_id,
                    'cell_name': cell_name,
                    'cell_index': cell_index,
                    'model_requested': model_requested or '',  # Default to empty string for ClickHouse
                    'candidate_index': msg.get('candidate_index'),
                    'context_message_hash': ctx_hash,
                    'context_message_cell': ctx_info['source_cell'] or 'unknown',
                    'context_message_role': ctx_info['role'] or 'unknown',
                    'context_message_index': ctx_idx,
                    'context_message_tokens': ctx_tokens,
                    'context_message_cost_estimated': ctx_msg_cost,
                    'context_message_pct': ctx_msg_pct,
                    'total_context_messages': len(context_hashes),
                    'total_context_tokens': sum((m['tokens_in'] or 0) + (m['tokens_out'] or 0) for m in messages),
                    'total_cell_cost': total_cell_cost,
                    'created_at': datetime.now(timezone.utc),
                })

        # Insert breakdown rows
        if breakdown_rows:
            db.insert_rows(
                'cell_context_breakdown',
                breakdown_rows,
                columns=list(breakdown_rows[0].keys())
            )

            # Optional: Run relevance analysis (enabled by default, opt-out with RVBBIT_ENABLE_RELEVANCE_ANALYSIS=false)
            import os
            if os.getenv('RVBBIT_ENABLE_RELEVANCE_ANALYSIS', 'true').lower() == 'true':
                # CRITICAL: Don't analyze relevance analyzer itself (prevents infinite recursion!)
                if '_relevance_' in session_id or cascade_id == 'analyze_context_relevance':
                    logger.debug(f"Skipping relevance analysis for meta-analysis session {session_id}")
                else:
                    # Check if already analyzed (avoid duplicate runs)
                    check_query = f"""
                        SELECT COUNT(*) as analyzed_count
                        FROM cell_context_breakdown
                        WHERE session_id = '{session_id}'
                          AND cell_name = '{cell_name}'
                          AND relevance_score IS NOT NULL
                        LIMIT 1
                    """
                    check_result = db.query(check_query)
                    already_analyzed = check_result and check_result[0]['analyzed_count'] > 0

                    if already_analyzed:
                        logger.debug(f"Skipping relevance analysis for {cell_name} (already analyzed)")
                    else:
                        logger.info(f"[Relevance] Analyzing {cell_name} in {session_id} ({len(breakdown_rows)} context messages)")
                        _analyze_context_relevance(
                            session_id=session_id,
                            cascade_id=cascade_id,
                            cell_name=cell_name,
                            messages=messages,
                            db=db
                        )

    except Exception as e:
        logger.debug(f"Could not create context breakdown for {cell_name}: {e}")
        import traceback
        traceback.print_exc()
