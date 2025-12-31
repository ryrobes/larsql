"""
Context Assessment API - Shadow Assessment Analysis for Receipts Page

Provides API endpoints for analyzing context shadow assessments collected during
cascade runs. These assessments help understand:
1. Inter-phase context selection (which messages from other cells are relevant)
2. Intra-phase context management (how to compress within-cell conversation)

Routes:
- /api/context-assessment/sessions - Sessions with shadow assessment data
- /api/context-assessment/overview/:session_id - Summary stats for a session
- /api/context-assessment/inter-phase/:session_id - Inter-phase shadow data
- /api/context-assessment/intra-phase/:session_id - Intra-phase config scenarios
- /api/context-assessment/recommendations/:cascade_id - Aggregated recommendations
"""

import os
import sys
import math
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

# Add rvbbit to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rvbbit.db_adapter import get_db


def safe_float(value, default=0.0):
    """Convert value to float, handling None and NaN cases."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """Convert value to int, handling None cases."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


context_assessment_bp = Blueprint('context_assessment', __name__)


@context_assessment_bp.route('/api/context-assessment/sessions', methods=['GET'])
def list_sessions():
    """
    List sessions that have shadow assessment data.

    Query params:
        days: Time range (default: 7)
        limit: Max sessions (default: 100)

    Returns:
        { sessions: [{session_id, cascade_id, first_assessment, last_assessment,
                      cells_assessed, total_assessments}] }
    """
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 100))
        db = get_db()

        # Check if tables exist
        tables_query = """
            SELECT name
            FROM system.tables
            WHERE database = currentDatabase()
            AND name IN ('context_shadow_assessments', 'intra_context_shadow_assessments')
        """
        tables = db.query(tables_query)
        table_names = [t['name'] for t in tables]

        sessions = []

        # Query inter-phase assessments if table exists
        if 'context_shadow_assessments' in table_names:
            inter_query = f"""
                SELECT
                    session_id,
                    any(cascade_id) as cascade_id,
                    MIN(timestamp) as first_assessment,
                    MAX(timestamp) as last_assessment,
                    COUNT(DISTINCT target_cell_name) as cells_assessed,
                    COUNT(*) as total_assessments,
                    'inter' as assessment_type
                FROM context_shadow_assessments
                WHERE timestamp >= now() - INTERVAL {days} DAY
                GROUP BY session_id
                ORDER BY last_assessment DESC
                LIMIT {limit}
            """
            try:
                inter_results = db.query(inter_query)
                for row in inter_results:
                    sessions.append({
                        'session_id': row['session_id'],
                        'cascade_id': row['cascade_id'],
                        'first_assessment': row['first_assessment'].isoformat() if hasattr(row['first_assessment'], 'isoformat') else str(row['first_assessment']),
                        'last_assessment': row['last_assessment'].isoformat() if hasattr(row['last_assessment'], 'isoformat') else str(row['last_assessment']),
                        'cells_assessed': safe_int(row['cells_assessed']),
                        'total_assessments': safe_int(row['total_assessments']),
                        'has_inter_phase': True,
                        'has_intra_phase': False
                    })
            except Exception as e:
                print(f"Error querying inter-phase: {e}")

        # Query intra-phase assessments if table exists
        if 'intra_context_shadow_assessments' in table_names:
            intra_query = f"""
                SELECT
                    session_id,
                    any(cascade_id) as cascade_id,
                    MIN(timestamp) as first_assessment,
                    MAX(timestamp) as last_assessment,
                    COUNT(DISTINCT cell_name) as cells_assessed,
                    COUNT(*) as total_assessments
                FROM intra_context_shadow_assessments
                WHERE timestamp >= now() - INTERVAL {days} DAY
                GROUP BY session_id
                ORDER BY last_assessment DESC
                LIMIT {limit}
            """
            try:
                intra_results = db.query(intra_query)
                # Merge with existing sessions
                session_map = {s['session_id']: s for s in sessions}
                for row in intra_results:
                    sid = row['session_id']
                    if sid in session_map:
                        session_map[sid]['has_intra_phase'] = True
                        session_map[sid]['intra_cells_assessed'] = safe_int(row['cells_assessed'])
                        session_map[sid]['intra_total_assessments'] = safe_int(row['total_assessments'])
                    else:
                        sessions.append({
                            'session_id': sid,
                            'cascade_id': row['cascade_id'],
                            'first_assessment': row['first_assessment'].isoformat() if hasattr(row['first_assessment'], 'isoformat') else str(row['first_assessment']),
                            'last_assessment': row['last_assessment'].isoformat() if hasattr(row['last_assessment'], 'isoformat') else str(row['last_assessment']),
                            'cells_assessed': safe_int(row['cells_assessed']),
                            'total_assessments': safe_int(row['total_assessments']),
                            'has_inter_phase': False,
                            'has_intra_phase': True
                        })
            except Exception as e:
                print(f"Error querying intra-phase: {e}")

        # Sort by last assessment
        sessions.sort(key=lambda x: x['last_assessment'], reverse=True)

        return jsonify({'sessions': sessions[:limit]})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/overview/<session_id>', methods=['GET'])
def get_overview(session_id):
    """
    Get overview stats for a session's shadow assessments.

    Returns summary of both inter-phase and intra-phase assessments.
    """
    try:
        db = get_db()

        result = {
            'session_id': session_id,
            'inter_phase': None,
            'intra_phase': None,
            'potential_savings': None,
            'best_intra_config': None
        }

        # Inter-phase stats (only user/assistant messages)
        try:
            inter_query = f"""
                SELECT
                    any(cascade_id) as cascade_id,
                    COUNT(DISTINCT target_cell_name) as cells_assessed,
                    COUNT(DISTINCT content_hash) as messages_assessed,
                    COUNT(DISTINCT budget_total) as budgets_evaluated,
                    SUM(estimated_tokens) as total_tokens_assessed,
                    AVG(composite_score) as avg_composite_score,
                    countIf(was_actually_included AND NOT would_include_hybrid) as would_prune_count,
                    SUM(CASE WHEN was_actually_included AND NOT would_include_hybrid THEN estimated_tokens ELSE 0 END) as potential_token_savings
                FROM context_shadow_assessments
                WHERE session_id = '{session_id}'
                  AND message_role IN ('user', 'assistant')
            """
            inter_result = db.query(inter_query)
            if inter_result and inter_result[0].get('cells_assessed'):
                row = inter_result[0]
                result['cascade_id'] = row['cascade_id']
                result['inter_phase'] = {
                    'cells_assessed': safe_int(row['cells_assessed']),
                    'messages_assessed': safe_int(row['messages_assessed']),
                    'budgets_evaluated': safe_int(row['budgets_evaluated']),
                    'total_tokens_assessed': safe_int(row['total_tokens_assessed']),
                    'avg_composite_score': safe_float(row['avg_composite_score']),
                    'would_prune_count': safe_int(row['would_prune_count']),
                    'potential_token_savings': safe_int(row['potential_token_savings'])
                }
        except Exception as e:
            print(f"Inter-phase query error: {e}")

        # Intra-phase stats
        try:
            intra_query = f"""
                SELECT
                    any(cascade_id) as cascade_id,
                    COUNT(DISTINCT (cell_name, turn_number)) as turns_assessed,
                    COUNT(DISTINCT cell_name) as cells_assessed,
                    COUNT(*) as total_config_rows,
                    MAX(tokens_saved) as max_tokens_saved,
                    AVG(compression_ratio) as avg_compression_ratio
                FROM intra_context_shadow_assessments
                WHERE session_id = '{session_id}'
            """
            intra_result = db.query(intra_query)
            if intra_result and intra_result[0].get('turns_assessed'):
                row = intra_result[0]
                if not result.get('cascade_id'):
                    result['cascade_id'] = row['cascade_id']
                result['intra_phase'] = {
                    'turns_assessed': safe_int(row['turns_assessed']),
                    'cells_assessed': safe_int(row['cells_assessed']),
                    'total_config_rows': safe_int(row['total_config_rows']),
                    'max_tokens_saved': safe_int(row['max_tokens_saved']),
                    'avg_compression_ratio': safe_float(row['avg_compression_ratio'])
                }
        except Exception as e:
            print(f"Intra-phase query error: {e}")

        # Best intra config recommendation
        try:
            best_config_query = f"""
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
            """
            best_result = db.query(best_config_query)
            if best_result:
                row = best_result[0]
                result['best_intra_config'] = {
                    'window': safe_int(row['config_window']),
                    'mask_after': safe_int(row['config_mask_after']),
                    'min_size': safe_int(row['config_min_masked_size']),
                    'avg_compression': safe_float(row['avg_compression']),
                    'total_saved': safe_int(row['total_saved'])
                }
        except Exception as e:
            print(f"Best config query error: {e}")

        # Calculate potential cost savings (rough estimate: $0.001 per 1000 tokens)
        total_potential_tokens = 0
        if result['inter_phase']:
            total_potential_tokens += result['inter_phase'].get('potential_token_savings', 0)
        if result['best_intra_config']:
            total_potential_tokens += result['best_intra_config'].get('total_saved', 0)

        if total_potential_tokens > 0:
            # Rough estimate at $0.001 per 1000 tokens (avg input/output)
            result['potential_savings'] = {
                'tokens': total_potential_tokens,
                'cost_estimated': total_potential_tokens * 0.000001  # $0.001/1k
            }

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/inter-phase/<session_id>', methods=['GET'])
def get_inter_phase(session_id):
    """
    Get inter-phase shadow assessment data for a session.

    Query params:
        cell: Filter by target cell name (optional)
        budget: Filter by budget level (optional)

    Returns per-message assessment scores grouped by target cell.
    """
    try:
        db = get_db()
        cell_name = request.args.get('cell')
        budget = request.args.get('budget', type=int)

        where_clause = f"WHERE session_id = '{session_id}'"
        # Only include user and assistant messages - filter out system/tool messages
        where_clause += " AND message_role IN ('user', 'assistant')"
        if cell_name:
            where_clause += f" AND target_cell_name = '{cell_name}'"
        if budget:
            where_clause += f" AND budget_total = {budget}"

        query = f"""
            SELECT
                target_cell_name,
                target_cell_instructions,
                source_cell_name,
                content_hash,
                message_role,
                content_preview,
                estimated_tokens,
                message_turn_number,
                heuristic_score,
                heuristic_keyword_overlap,
                heuristic_recency_score,
                semantic_score,
                semantic_embedding_available,
                llm_selected,
                llm_reasoning,
                composite_score,
                would_include_heuristic,
                would_include_semantic,
                would_include_llm,
                would_include_hybrid,
                rank_heuristic,
                rank_semantic,
                rank_composite,
                total_candidates,
                budget_total,
                cumulative_tokens_at_rank,
                would_fit_budget,
                was_actually_included
            FROM context_shadow_assessments
            {where_clause}
            ORDER BY target_cell_name, rank_composite
        """

        results = db.query(query)

        # Group by target cell
        cells = {}
        for row in results:
            cell = row['target_cell_name']
            if cell not in cells:
                cells[cell] = {
                    'cell_name': cell,
                    'instructions_preview': (row['target_cell_instructions'] or '')[:200],
                    'messages': []
                }

            cells[cell]['messages'].append({
                'source_cell': row['source_cell_name'],
                'content_hash': row['content_hash'],
                'role': row['message_role'],
                'preview': row['content_preview'],
                'tokens': safe_int(row['estimated_tokens']),
                'turn_number': safe_int(row['message_turn_number']) if row['message_turn_number'] else None,
                'scores': {
                    'heuristic': safe_float(row['heuristic_score']),
                    'semantic': safe_float(row['semantic_score']) if row['semantic_embedding_available'] else None,
                    'llm_selected': bool(row['llm_selected']),
                    'composite': safe_float(row['composite_score'])
                },
                'heuristic_details': {
                    'keyword_overlap': safe_int(row['heuristic_keyword_overlap']),
                    'recency_score': safe_float(row['heuristic_recency_score'])
                },
                'llm_reasoning': row['llm_reasoning'] if row['llm_reasoning'] else None,
                'ranks': {
                    'heuristic': safe_int(row['rank_heuristic']),
                    'semantic': safe_int(row['rank_semantic']) if row['rank_semantic'] else None,
                    'composite': safe_int(row['rank_composite'])
                },
                'total_candidates': safe_int(row['total_candidates']),
                'budget': {
                    'total': safe_int(row['budget_total']),
                    'cumulative_at_rank': safe_int(row['cumulative_tokens_at_rank']),
                    'would_fit': bool(row['would_fit_budget'])
                },
                'would_include': {
                    'heuristic': bool(row['would_include_heuristic']),
                    'semantic': bool(row['would_include_semantic']),
                    'llm': bool(row['would_include_llm']),
                    'hybrid': bool(row['would_include_hybrid'])
                },
                'was_actually_included': bool(row['was_actually_included'])
            })

        return jsonify({
            'session_id': session_id,
            'cells': list(cells.values())
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/intra-phase/<session_id>', methods=['GET'])
def get_intra_phase(session_id):
    """
    Get intra-phase shadow assessment data for a session.

    Query params:
        cell: Filter by cell name (optional)
        candidate: Filter by candidate index (optional)

    Returns per-turn config scenarios grouped by cell.
    """
    try:
        db = get_db()
        cell_name = request.args.get('cell')
        candidate_idx = request.args.get('candidate', type=int)

        where_clause = f"WHERE session_id = '{session_id}'"
        if cell_name:
            where_clause += f" AND cell_name = '{cell_name}'"
        if candidate_idx is not None:
            where_clause += f" AND candidate_index = {candidate_idx}"

        query = f"""
            SELECT
                cell_name,
                candidate_index,
                turn_number,
                is_loop_retry,
                config_window,
                config_mask_after,
                config_min_masked_size,
                config_compress_loops,
                config_preserve_reasoning,
                config_preserve_errors,
                full_history_size,
                context_size,
                tokens_before,
                tokens_after,
                tokens_saved,
                compression_ratio,
                messages_masked,
                messages_preserved,
                messages_truncated,
                message_breakdown,
                tokens_vs_baseline_saved,
                tokens_vs_baseline_pct,
                actual_config_enabled,
                actual_tokens_after,
                differs_from_actual
            FROM intra_context_shadow_assessments
            {where_clause}
            ORDER BY cell_name, candidate_index NULLS FIRST, turn_number, config_window, config_mask_after
        """

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
                    'is_loop_retry': bool(row['is_loop_retry']),
                    'full_history_size': safe_int(row['full_history_size']),
                    'actual_config_enabled': bool(row['actual_config_enabled']),
                    'actual_tokens_after': safe_int(row['actual_tokens_after']) if row['actual_tokens_after'] else None,
                    'configs': []
                }

            # Parse message breakdown JSON
            try:
                import json
                breakdown = json.loads(row['message_breakdown']) if row['message_breakdown'] else []
            except:
                breakdown = []

            cells[cell]['candidates'][candidate]['turns'][turn]['configs'].append({
                'window': safe_int(row['config_window']),
                'mask_after': safe_int(row['config_mask_after']),
                'min_size': safe_int(row['config_min_masked_size']),
                'compress_loops': bool(row['config_compress_loops']),
                'preserve_reasoning': bool(row['config_preserve_reasoning']),
                'preserve_errors': bool(row['config_preserve_errors']),
                'context_size': safe_int(row['context_size']),
                'tokens_before': safe_int(row['tokens_before']),
                'tokens_after': safe_int(row['tokens_after']),
                'tokens_saved': safe_int(row['tokens_saved']),
                'compression_ratio': safe_float(row['compression_ratio']),
                'messages_masked': safe_int(row['messages_masked']),
                'messages_preserved': safe_int(row['messages_preserved']),
                'messages_truncated': safe_int(row['messages_truncated']),
                'message_breakdown': breakdown,
                'tokens_vs_baseline_saved': safe_int(row['tokens_vs_baseline_saved']),
                'tokens_vs_baseline_pct': safe_float(row['tokens_vs_baseline_pct']),
                'differs_from_actual': bool(row['differs_from_actual'])
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
                'candidates': sorted(candidates, key=lambda c: c['candidate_index'] if c['candidate_index'] is not None else -1)
            })

        return jsonify({
            'session_id': session_id,
            'cells': result_cells
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/recommendations/<cascade_id>', methods=['GET'])
def get_recommendations(cascade_id):
    """
    Get aggregated config recommendations for a cascade.

    Analyzes all sessions for this cascade to suggest optimal intra-context config.

    Query params:
        days: Time range (default: 30)
    """
    try:
        days = int(request.args.get('days', 30))
        db = get_db()

        # Best config across all sessions for this cascade
        best_configs_query = f"""
            SELECT
                config_window,
                config_mask_after,
                config_min_masked_size,
                COUNT(DISTINCT session_id) as session_count,
                AVG(compression_ratio) as avg_compression,
                SUM(tokens_saved) as total_tokens_saved,
                AVG(tokens_saved) as avg_tokens_saved,
                MIN(compression_ratio) as best_compression,
                MAX(compression_ratio) as worst_compression
            FROM intra_context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
            GROUP BY config_window, config_mask_after, config_min_masked_size
            HAVING session_count >= 2
            ORDER BY total_tokens_saved DESC
            LIMIT 10
        """

        configs = db.query(best_configs_query)

        recommendations = []
        for i, row in enumerate(configs):
            rec_type = 'best' if i == 0 else ('aggressive' if row['config_window'] <= 3 else 'conservative')
            recommendations.append({
                'rank': i + 1,
                'type': rec_type,
                'config': {
                    'window': safe_int(row['config_window']),
                    'mask_after': safe_int(row['config_mask_after']),
                    'min_size': safe_int(row['config_min_masked_size'])
                },
                'metrics': {
                    'session_count': safe_int(row['session_count']),
                    'avg_compression': safe_float(row['avg_compression']),
                    'total_tokens_saved': safe_int(row['total_tokens_saved']),
                    'avg_tokens_saved': safe_float(row['avg_tokens_saved']),
                    'best_compression': safe_float(row['best_compression']),
                    'worst_compression': safe_float(row['worst_compression'])
                },
                'yaml_snippet': f"""intra_context:
  enabled: true
  window: {safe_int(row['config_window'])}
  mask_observations_after: {safe_int(row['config_mask_after'])}
  min_masked_size: {safe_int(row['config_min_masked_size'])}"""
            })

        # Per-cell breakdown
        per_cell_query = f"""
            SELECT
                cell_name,
                AVG(tokens_before) as avg_tokens_before,
                AVG(tokens_saved) as avg_tokens_saved,
                MAX(turn_number) as max_turns,
                COUNT(DISTINCT session_id) as session_count
            FROM intra_context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
              AND config_window = 5 AND config_mask_after = 3
            GROUP BY cell_name
            ORDER BY avg_tokens_saved DESC
        """

        per_cell = db.query(per_cell_query)

        cell_insights = []
        for row in per_cell:
            cell_insights.append({
                'cell_name': row['cell_name'],
                'avg_tokens_before': safe_float(row['avg_tokens_before']),
                'avg_tokens_saved': safe_float(row['avg_tokens_saved']),
                'max_turns': safe_int(row['max_turns']),
                'session_count': safe_int(row['session_count']),
                'savings_potential': 'high' if row['avg_tokens_saved'] > 1000 else ('medium' if row['avg_tokens_saved'] > 200 else 'low')
            })

        return jsonify({
            'cascade_id': cascade_id,
            'days_analyzed': days,
            'recommendations': recommendations,
            'cell_insights': cell_insights
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/table-status', methods=['GET'])
def get_table_status():
    """
    Check if shadow assessment tables exist and have data.

    Returns table existence and row counts.
    """
    try:
        db = get_db()

        result = {
            'context_shadow_assessments': {'exists': False, 'row_count': 0},
            'intra_context_shadow_assessments': {'exists': False, 'row_count': 0}
        }

        # Check tables
        tables_query = """
            SELECT name
            FROM system.tables
            WHERE database = currentDatabase()
            AND name IN ('context_shadow_assessments', 'intra_context_shadow_assessments')
        """
        tables = db.query(tables_query)

        for t in tables:
            table_name = t['name']
            result[table_name]['exists'] = True

            # Get row count
            try:
                count_query = f"SELECT COUNT(*) as cnt FROM {table_name}"
                count_result = db.query(count_query)
                if count_result:
                    result[table_name]['row_count'] = safe_int(count_result[0]['cnt'])
            except:
                pass

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Phase 3 Endpoints: Interactive Explorers
# =============================================================================

@context_assessment_bp.route('/api/context-assessment/relevance-scatter/<session_id>', methods=['GET'])
def get_relevance_scatter(session_id):
    """
    Get data for relevance vs. cost scatter plot.

    Returns messages with their token count (cost proxy) and relevance scores
    for visualization in a scatter plot to identify "waste" (high cost, low relevance).
    """
    try:
        db = get_db()

        query = f"""
            SELECT
                content_hash,
                source_cell_name,
                target_cell_name,
                message_role,
                content_preview,
                estimated_tokens,
                composite_score,
                heuristic_score,
                semantic_score,
                llm_selected,
                was_actually_included,
                would_include_hybrid
            FROM context_shadow_assessments
            WHERE session_id = '{session_id}'
              AND message_role IN ('user', 'assistant')
            ORDER BY estimated_tokens DESC
        """

        results = db.query(query)

        messages = []
        for row in results:
            messages.append({
                'content_hash': row['content_hash'],
                'source_cell': row['source_cell_name'],
                'target_cell': row['target_cell_name'],
                'role': row['message_role'],
                'preview': row['content_preview'],
                'tokens': safe_int(row['estimated_tokens']),
                'composite_score': safe_float(row['composite_score']),
                'heuristic_score': safe_float(row['heuristic_score']),
                'semantic_score': safe_float(row['semantic_score']) if row['semantic_score'] else None,
                'llm_selected': bool(row['llm_selected']),
                'was_included': bool(row['was_actually_included']),
                'would_include': bool(row['would_include_hybrid'])
            })

        # Calculate waste metrics
        waste_messages = [m for m in messages if m['was_included'] and m['composite_score'] < 40]
        waste_tokens = sum(m['tokens'] for m in waste_messages)

        return jsonify({
            'session_id': session_id,
            'messages': messages,
            'waste_summary': {
                'count': len(waste_messages),
                'tokens': waste_tokens,
                'estimated_cost': waste_tokens * 0.000001  # Rough estimate
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/candidate-comparison/<session_id>', methods=['GET'])
def get_candidate_comparison(session_id):
    """
    Get per-candidate context analysis for sessions with multiple candidates.

    Returns context usage stats per candidate to compare their efficiency.
    """
    try:
        db = get_db()

        # Get per-candidate stats from intra-phase data
        query = f"""
            SELECT
                cell_name,
                candidate_index,
                MAX(turn_number) as max_turns,
                SUM(tokens_before) as total_tokens_before,
                -- Get best config stats for each candidate
                argMax(config_window, tokens_saved) as best_window,
                argMax(config_mask_after, tokens_saved) as best_mask_after,
                MAX(tokens_saved) as max_tokens_saved,
                AVG(compression_ratio) as avg_compression
            FROM intra_context_shadow_assessments
            WHERE session_id = '{session_id}'
            GROUP BY cell_name, candidate_index
            ORDER BY cell_name, candidate_index NULLS FIRST
        """

        results = db.query(query)

        # Group by cell
        cells = {}
        for row in results:
            cell = row['cell_name']
            if cell not in cells:
                cells[cell] = {'cell_name': cell, 'candidates': []}

            cells[cell]['candidates'].append({
                'candidate_index': row['candidate_index'],
                'max_turns': safe_int(row['max_turns']),
                'total_tokens': safe_int(row['total_tokens_before']),
                'best_config': {
                    'window': safe_int(row['best_window']),
                    'mask_after': safe_int(row['best_mask_after'])
                },
                'max_savings': safe_int(row['max_tokens_saved']),
                'avg_compression': safe_float(row['avg_compression'])
            })

        # Get turn-by-turn heatmap data
        heatmap_query = f"""
            SELECT
                cell_name,
                candidate_index,
                turn_number,
                MAX(tokens_before) as tokens
            FROM intra_context_shadow_assessments
            WHERE session_id = '{session_id}'
            GROUP BY cell_name, candidate_index, turn_number
            ORDER BY cell_name, candidate_index NULLS FIRST, turn_number
        """

        heatmap_results = db.query(heatmap_query)

        # Add heatmap data to cells
        for row in heatmap_results:
            cell = row['cell_name']
            cand_idx = row['candidate_index']
            if cell in cells:
                for cand in cells[cell]['candidates']:
                    if cand['candidate_index'] == cand_idx:
                        if 'turns_heatmap' not in cand:
                            cand['turns_heatmap'] = []
                        cand['turns_heatmap'].append({
                            'turn': safe_int(row['turn_number']),
                            'tokens': safe_int(row['tokens'])
                        })

        return jsonify({
            'session_id': session_id,
            'cells': list(cells.values())
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@context_assessment_bp.route('/api/context-assessment/budget-simulation/<session_id>', methods=['GET'])
def get_budget_simulation(session_id):
    """
    Get pre-computed data for budget slider simulation.

    Returns messages with their inclusion status at different budget levels,
    allowing the frontend to instantly show what would be included/excluded
    as the user slides the budget.
    """
    try:
        db = get_db()
        cell_name = request.args.get('cell')

        where_clause = f"WHERE session_id = '{session_id}'"
        where_clause += " AND message_role IN ('user', 'assistant')"
        if cell_name:
            where_clause += f" AND target_cell_name = '{cell_name}'"

        query = f"""
            SELECT
                target_cell_name,
                content_hash,
                source_cell_name,
                message_role,
                content_preview,
                estimated_tokens,
                composite_score,
                rank_composite,
                cumulative_tokens_at_rank,
                budget_total,
                would_fit_budget,
                would_include_hybrid,
                was_actually_included
            FROM context_shadow_assessments
            {where_clause}
            ORDER BY target_cell_name, budget_total, rank_composite
        """

        results = db.query(query)

        # Group by cell -> budget -> messages
        cells = {}
        for row in results:
            cell = row['target_cell_name']
            budget = safe_int(row['budget_total'])

            if cell not in cells:
                cells[cell] = {'cell_name': cell, 'budgets': {}}

            if budget not in cells[cell]['budgets']:
                cells[cell]['budgets'][budget] = {
                    'budget': budget,
                    'messages': [],
                    'total_tokens_if_all': 0,
                    'tokens_included': 0
                }

            msg = {
                'content_hash': row['content_hash'],
                'source_cell': row['source_cell_name'],
                'role': row['message_role'],
                'preview': row['content_preview'],
                'tokens': safe_int(row['estimated_tokens']),
                'score': safe_float(row['composite_score']),
                'rank': safe_int(row['rank_composite']),
                'cumulative_tokens': safe_int(row['cumulative_tokens_at_rank']),
                'would_fit': bool(row['would_fit_budget']),
                'would_include': bool(row['would_include_hybrid']),
                'was_included': bool(row['was_actually_included'])
            }
            cells[cell]['budgets'][budget]['messages'].append(msg)
            cells[cell]['budgets'][budget]['total_tokens_if_all'] += msg['tokens']
            if msg['would_include']:
                cells[cell]['budgets'][budget]['tokens_included'] += msg['tokens']

        # Convert to list format
        result_cells = []
        for cell_data in cells.values():
            budgets = sorted(cell_data['budgets'].values(), key=lambda b: b['budget'])
            result_cells.append({
                'cell_name': cell_data['cell_name'],
                'budgets': budgets
            })

        return jsonify({
            'session_id': session_id,
            'cells': result_cells
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



# =============================================================================
# Phase 4 Endpoints: Intelligence Layer + Multi-Run Analysis
# =============================================================================

# Approximate token costs per model ($ per 1M tokens)
MODEL_COSTS = {
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    "claude-3-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "default": {"input": 3.0, "output": 10.0}  # Conservative estimate
}


def estimate_cost(tokens, model="default", direction="input"):
    """Estimate cost in dollars for a token count."""
    rates = MODEL_COSTS.get(model, MODEL_COSTS["default"])
    rate = rates.get(direction, rates["input"])
    return (tokens / 1_000_000) * rate


@context_assessment_bp.route("/api/context-assessment/cascade-aggregate/<cascade_id>", methods=["GET"])
def get_cascade_aggregate(cascade_id):
    """
    Get aggregated context assessment across multiple runs of a cascade.

    This provides statistical confidence for recommendations by analyzing
    patterns across many sessions rather than just one.

    Query params:
        days: Number of days to look back (default: 30)
        min_sessions: Minimum sessions required for confidence (default: 5)
    """
    try:
        db = get_db()
        days = request.args.get("days", 30, type=int)
        min_sessions = request.args.get("min_sessions", 5, type=int)

        # Get session count and basic stats
        session_query = f"""
            SELECT
                COUNT(DISTINCT session_id) as session_count,
                MIN(timestamp) as first_run,
                MAX(timestamp) as last_run
            FROM context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
        """
        session_stats = db.query(session_query)
        session_count = safe_int(session_stats[0]["session_count"]) if session_stats else 0

        if session_count < min_sessions:
            return jsonify({
                "cascade_id": cascade_id,
                "session_count": session_count,
                "min_sessions": min_sessions,
                "insufficient_data": True,
                "message": f"Need at least {min_sessions} sessions for reliable analysis, found {session_count}"
            })

        # Aggregate inter-phase: which cells consistently have waste?
        cell_waste_query = f"""
            SELECT
                target_cell_name as cell_name,
                COUNT(DISTINCT session_id) as sessions_seen,
                AVG(composite_score) as avg_relevance,
                SUM(estimated_tokens) as total_tokens,
                SUM(CASE WHEN was_actually_included AND composite_score < 40 THEN estimated_tokens ELSE 0 END) as waste_tokens,
                COUNT(CASE WHEN was_actually_included AND composite_score < 40 THEN 1 END) as waste_messages,
                COUNT(*) as total_messages
            FROM context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
              AND message_role IN ('user', 'assistant')
            GROUP BY target_cell_name
            HAVING sessions_seen >= {min_sessions}
            ORDER BY waste_tokens DESC
        """
        cell_waste = db.query(cell_waste_query)

        # Aggregate intra-phase: best configs across all runs
        config_query = f"""
            SELECT
                config_window,
                config_mask_after,
                config_min_masked_size,
                COUNT(DISTINCT session_id) as sessions_seen,
                AVG(compression_ratio) as avg_compression,
                AVG(tokens_saved) as avg_tokens_saved,
                SUM(tokens_saved) as total_tokens_saved,
                stddevSamp(compression_ratio) as compression_stddev,
                MIN(compression_ratio) as min_compression,
                MAX(compression_ratio) as max_compression
            FROM intra_context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
            GROUP BY config_window, config_mask_after, config_min_masked_size
            HAVING sessions_seen >= {min_sessions}
            ORDER BY avg_tokens_saved DESC
            LIMIT 20
        """
        config_stats = db.query(config_query)

        # Best overall config
        best_config = None
        if config_stats:
            row = config_stats[0]
            best_config = {
                "window": safe_int(row["config_window"]),
                "mask_after": safe_int(row["config_mask_after"]),
                "min_size": safe_int(row["config_min_masked_size"]),
                "avg_savings_pct": round((1 - safe_float(row["avg_compression"])) * 100, 1),
                "avg_tokens_saved": safe_int(row["avg_tokens_saved"]),
                "total_tokens_saved": safe_int(row["total_tokens_saved"]),
                "consistency": round(100 - safe_float(row["compression_stddev"] or 0) * 100, 1),
                "sessions_analyzed": safe_int(row["sessions_seen"])
            }

        # Calculate total waste and potential savings
        total_waste_tokens = sum(safe_int(c["waste_tokens"]) for c in cell_waste)
        total_tokens = sum(safe_int(c["total_tokens"]) for c in cell_waste)
        waste_pct = (total_waste_tokens / total_tokens * 100) if total_tokens > 0 else 0

        # Estimate cost savings
        estimated_savings_per_run = estimate_cost(
            best_config["avg_tokens_saved"] if best_config else 0
        )

        return jsonify({
            "cascade_id": cascade_id,
            "session_count": session_count,
            "date_range": {
                "first": str(session_stats[0]["first_run"]) if session_stats else None,
                "last": str(session_stats[0]["last_run"]) if session_stats else None,
                "days": days
            },
            "inter_phase": {
                "cells": [{
                    "cell_name": c["cell_name"],
                    "sessions_seen": safe_int(c["sessions_seen"]),
                    "avg_relevance": safe_float(c["avg_relevance"]),
                    "total_tokens": safe_int(c["total_tokens"]),
                    "waste_tokens": safe_int(c["waste_tokens"]),
                    "waste_messages": safe_int(c["waste_messages"]),
                    "waste_pct": round(safe_int(c["waste_tokens"]) / max(safe_int(c["total_tokens"]), 1) * 100, 1)
                } for c in cell_waste],
                "total_waste_tokens": total_waste_tokens,
                "total_waste_pct": round(waste_pct, 1)
            },
            "intra_phase": {
                "best_config": best_config,
                "all_configs": [{
                    "window": safe_int(c["config_window"]),
                    "mask_after": safe_int(c["config_mask_after"]),
                    "min_size": safe_int(c["config_min_masked_size"]),
                    "avg_savings_pct": round((1 - safe_float(c["avg_compression"])) * 100, 1),
                    "sessions": safe_int(c["sessions_seen"])
                } for c in config_stats[:10]]
            },
            "recommendations": {
                "estimated_savings_per_run": round(estimated_savings_per_run, 4),
                "estimated_monthly_savings": round(estimated_savings_per_run * session_count, 2),
                "confidence": "high" if session_count >= 20 else "medium" if session_count >= 10 else "low"
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@context_assessment_bp.route("/api/context-assessment/waste-analysis/<session_id>", methods=["GET"])
def get_waste_analysis(session_id):
    """
    Analyze waste: messages that are included but have low relevance.

    These are optimization opportunities - can be pruned with minimal quality impact.

    Query params:
        relevance_threshold: Score below which is considered "low" (default: 40)
        min_tokens: Minimum tokens for a message to be worth analyzing (default: 100)
    """
    try:
        db = get_db()
        threshold = request.args.get("relevance_threshold", 40, type=int)
        min_tokens = request.args.get("min_tokens", 100, type=int)

        # Find waste messages (included but low relevance)
        query = f"""
            SELECT
                target_cell_name as cell_name,
                source_cell_name as source_cell,
                content_hash,
                message_role as role,
                content_preview as preview,
                estimated_tokens as tokens,
                composite_score as relevance_score,
                heuristic_score,
                semantic_score,
                was_actually_included,
                would_include_hybrid
            FROM context_shadow_assessments
            WHERE session_id = '{session_id}'
              AND message_role IN ('user', 'assistant')
              AND was_actually_included = 1
              AND composite_score < {threshold}
              AND estimated_tokens >= {min_tokens}
            ORDER BY estimated_tokens DESC
        """

        results = db.query(query)

        # Group by cell
        cells = {}
        total_waste_tokens = 0
        for row in results:
            cell = row["cell_name"]
            if cell not in cells:
                cells[cell] = {"cell_name": cell, "messages": [], "waste_tokens": 0}

            tokens = safe_int(row["tokens"])
            cells[cell]["messages"].append({
                "content_hash": row["content_hash"],
                "source_cell": row["source_cell"],
                "role": row["role"],
                "preview": row["preview"],
                "tokens": tokens,
                "relevance_score": safe_float(row["relevance_score"]),
                "heuristic_score": safe_float(row["heuristic_score"]),
                "semantic_score": safe_float(row["semantic_score"])
            })
            cells[cell]["waste_tokens"] += tokens
            total_waste_tokens += tokens

        # Estimate savings
        estimated_cost_savings = estimate_cost(total_waste_tokens)

        return jsonify({
            "session_id": session_id,
            "threshold": threshold,
            "min_tokens": min_tokens,
            "summary": {
                "total_waste_messages": len(results),
                "total_waste_tokens": total_waste_tokens,
                "estimated_cost_savings": round(estimated_cost_savings, 6),
                "cells_affected": len(cells)
            },
            "cells": sorted(cells.values(), key=lambda c: c["waste_tokens"], reverse=True),
            "recommendation": (
                f"Pruning {len(results)} low-relevance messages would save ~{total_waste_tokens:,} tokens "
                f"(~${estimated_cost_savings:.4f}) with minimal quality impact (all scored <{threshold}/100)."
            )
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@context_assessment_bp.route("/api/context-assessment/quality-recommendations/<cascade_id>", methods=["GET"])
def get_quality_recommendations(cascade_id):
    """
    Get quality-aware configuration recommendations.

    Balances token savings against potential quality impact using relevance scores.
    Provides tiered recommendations: aggressive, balanced, conservative.
    """
    try:
        db = get_db()
        days = request.args.get("days", 30, type=int)

        # Get intra-phase recommendations with quality weighting
        intra_query = f"""
            SELECT
                config_window,
                config_mask_after,
                config_min_masked_size,
                COUNT(DISTINCT session_id) as sessions,
                AVG(compression_ratio) as avg_compression,
                AVG(tokens_saved) as avg_saved,
                AVG(messages_masked) as avg_masked,
                AVG(messages_preserved) as avg_preserved
            FROM intra_context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
            GROUP BY config_window, config_mask_after, config_min_masked_size
            ORDER BY avg_saved DESC
        """
        intra_results = db.query(intra_query)

        # Categorize configs into tiers
        tiers = {
            "aggressive": None,
            "balanced": None,
            "conservative": None
        }

        for row in intra_results:
            savings_pct = (1 - safe_float(row["avg_compression"])) * 100
            window = safe_int(row["config_window"])
            mask_after = safe_int(row["config_mask_after"])

            config = {
                "window": window,
                "mask_after": mask_after,
                "min_size": safe_int(row["config_min_masked_size"]),
                "savings_pct": round(savings_pct, 1),
                "avg_tokens_saved": safe_int(row["avg_saved"]),
                "sessions": safe_int(row["sessions"]),
                "avg_masked": safe_float(row["avg_masked"]),
                "avg_preserved": safe_float(row["avg_preserved"])
            }

            # Classify: aggressive = small window, early masking
            # conservative = large window, late masking
            if window <= 3 and mask_after <= 2 and not tiers["aggressive"]:
                tiers["aggressive"] = config
            elif window >= 7 and mask_after >= 5 and not tiers["conservative"]:
                tiers["conservative"] = config
            elif 4 <= window <= 6 and 3 <= mask_after <= 4 and not tiers["balanced"]:
                tiers["balanced"] = config

        # Fill in missing tiers with best available
        if not tiers["balanced"] and intra_results:
            tiers["balanced"] = {
                "window": safe_int(intra_results[0]["config_window"]),
                "mask_after": safe_int(intra_results[0]["config_mask_after"]),
                "min_size": safe_int(intra_results[0]["config_min_masked_size"]),
                "savings_pct": round((1 - safe_float(intra_results[0]["avg_compression"])) * 100, 1),
                "avg_tokens_saved": safe_int(intra_results[0]["avg_saved"]),
                "sessions": safe_int(intra_results[0]["sessions"])
            }

        # Get inter-phase budget recommendations
        inter_query = f"""
            SELECT
                budget_total,
                AVG(composite_score) as avg_kept_relevance,
                COUNT(DISTINCT session_id) as sessions,
                SUM(CASE WHEN would_include_hybrid THEN estimated_tokens ELSE 0 END) / COUNT(DISTINCT session_id) as avg_tokens_included,
                SUM(CASE WHEN NOT would_include_hybrid THEN estimated_tokens ELSE 0 END) / COUNT(DISTINCT session_id) as avg_tokens_pruned
            FROM context_shadow_assessments
            WHERE cascade_id = '{cascade_id}'
              AND timestamp >= now() - INTERVAL {days} DAY
              AND message_role IN ('user', 'assistant')
            GROUP BY budget_total
            ORDER BY budget_total
        """
        inter_results = db.query(inter_query)

        budget_recommendations = [{
            "budget": safe_int(row["budget_total"]),
            "avg_relevance_kept": safe_float(row["avg_kept_relevance"]),
            "avg_tokens_included": safe_int(row["avg_tokens_included"]),
            "avg_tokens_pruned": safe_int(row["avg_tokens_pruned"]),
            "sessions": safe_int(row["sessions"])
        } for row in inter_results]

        return jsonify({
            "cascade_id": cascade_id,
            "days_analyzed": days,
            "intra_phase": {
                "tiers": tiers,
                "recommendation": (
                    f"Start with balanced (window={tiers['balanced']['window'] if tiers['balanced'] else '?'}, "
                    f"mask_after={tiers['balanced']['mask_after'] if tiers['balanced'] else '?'}) "
                    f"for ~{tiers['balanced']['savings_pct'] if tiers['balanced'] else '?'}% savings with minimal risk."
                ) if tiers else "Insufficient data for recommendations"
            },
            "inter_phase": {
                "budget_options": budget_recommendations,
                "recommendation": (
                    "Higher budgets preserve more context but cost more. "
                    "30k is typically a good balance for most cascades."
                )
            },
            "yaml_snippet": generate_yaml_snippet(tiers.get("balanced")) if tiers else None
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def generate_yaml_snippet(config):
    """Generate YAML config snippet for recommended settings."""
    if not config:
        return None

    return f"""# Recommended intra-context settings
intra_context:
  enabled: true
  window: {config["window"]}
  mask_observations_after: {config["mask_after"]}
  min_masked_size: {config["min_size"]}
  compress_loops: true
  preserve_reasoning: true
  preserve_errors: true"""

