"""
Sextant API - Prompt optimization and analysis endpoints

Endpoints:
- GET /api/sextant/cascades - List cascades with optimization potential
- GET /api/sextant/analyze/<cascade_id> - Analyze a cascade's candidates
- GET /api/sextant/winner-loser-analysis/<cascade_id>/<cell_name> - Winners vs losers with LLM synopsis
- GET /api/sextant/suggestions/<cascade_id> - Get/generate improvement suggestions
- POST /api/sextant/apply - Apply a suggestion to a cascade file
- GET /api/sextant/patterns/<cascade_id>/<cell_name> - Token-level pattern analysis
- GET /api/sextant/evolution/<session_id> - Prompt evolution/phylogeny visualization data
- GET /api/sextant/species/<session_id> - Species hash and related training sessions
"""

import os
import sys
import json
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add rvbbit to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from rvbbit.db_adapter import get_db
from rvbbit.config import get_config

sextant_bp = Blueprint('sextant', __name__, url_prefix='/api/sextant')


@sextant_bp.route('/cascades', methods=['GET'])
def list_cascades_with_candidates():
    """
    List all cascades that have candidate data available for analysis.

    Returns cascades sorted by analysis potential (run count, winner diversity).
    """
    db = get_db()

    try:
        # Find cascades with candidates data
        query = """
            SELECT
                cascade_id,
                COUNT(DISTINCT session_id) as session_count,
                COUNT(DISTINCT cell_name) as cell_count,
                SUM(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as winner_count,
                COUNT(DISTINCT candidate_index) as candidate_diversity,
                MIN(timestamp) as first_run,
                MAX(timestamp) as last_run,
                SUM(CASE WHEN role = 'assistant' THEN cost ELSE 0 END) as total_cost
            FROM unified_logs
            WHERE candidate_index IS NOT NULL
              AND cascade_id IS NOT NULL
              AND cascade_id != ''
            GROUP BY cascade_id
            HAVING COUNT(DISTINCT session_id) >= 1
            ORDER BY session_count DESC
            LIMIT 50
        """

        result = db.query(query, output_format='dict')

        cascades = []
        for row in result:
            cascades.append({
                'cascade_id': row['cascade_id'],
                'session_count': row['session_count'],
                'cell_count': row['cell_count'],
                'winner_count': row['winner_count'],
                'candidate_diversity': row['candidate_diversity'],
                'first_run': str(row['first_run']) if row['first_run'] else None,
                'last_run': str(row['last_run']) if row['last_run'] else None,
                'total_cost': float(row['total_cost']) if row['total_cost'] else 0,
                'analysis_ready': row['session_count'] >= 5 and row['winner_count'] >= 3,
            })

        return jsonify({'cascades': cascades})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/species/<cascade_id>/<cell_name>', methods=['GET'])
def list_species(cascade_id, cell_name):
    """
    List distinct species (cell template DNA hashes) for a cascade/cell.

    Species represents the "DNA" of the prompt template - the instructions,
    candidates config, and rules that define how prompts are generated.

    Returns:
    - species: List of species with counts and metadata
    - warning: Set if multiple species detected (mixed-spec comparison warning)
    """
    db = get_db()

    try:
        # Get distinct species with counts and cost data
        # Join with agent rows to get actual costs
        species_query = f"""
            SELECT
                sa.species_hash,
                COUNT(DISTINCT sa.session_id) as session_count,
                SUM(CASE WHEN sa.is_winner = true THEN 1 ELSE 0 END) as winner_count,
                COUNT(*) as total_attempts,
                MIN(sa.timestamp) as first_seen,
                MAX(sa.timestamp) as last_seen,
                SUM(CASE WHEN agent.role = 'assistant' THEN agent.cost ELSE 0 END) as total_cost
            FROM unified_logs sa
            LEFT JOIN unified_logs agent ON
                agent.session_id = sa.session_id
                AND agent.candidate_index = sa.candidate_index
                AND agent.role = 'assistant'
            WHERE sa.cascade_id = '{cascade_id}'
              AND sa.cell_name = '{cell_name}'
              AND sa.node_type IN ('candidate_attempt', 'cascade_candidate_attempt')
              AND sa.species_hash IS NOT NULL
            GROUP BY sa.species_hash
            ORDER BY session_count DESC
        """

        result = db.query(species_query, output_format='dict')

        # For each species, fetch a sample to get the input/instructions
        def get_species_sample(species_hash):
            """Get sample input data for a species to help identify it."""
            sample_query = f"""
                SELECT
                    cell_json,
                    metadata_json,
                    content_json
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND species_hash = '{species_hash}'
                  AND node_type IN ('candidate_attempt', 'cascade_candidate_attempt')
                LIMIT 1
            """
            sample = db.query(sample_query, output_format='dict')
            if not sample:
                return None, None

            row = sample[0]
            input_preview = None
            instructions_preview = None

            # Try to extract instructions from cell_json (the cell config)
            if row.get('cell_json'):
                try:
                    cell_data = json.loads(row['cell_json']) if isinstance(row['cell_json'], str) else row['cell_json']
                    if isinstance(cell_data, dict):
                        instr = cell_data.get('instructions', '')
                        if instr:
                            # Truncate but try to get meaningful first line
                            lines = instr.strip().split('\n')
                            first_line = lines[0][:80]
                            instructions_preview = first_line + ('...' if len(lines) > 1 or len(lines[0]) > 80 else '')
                except:
                    pass

            # Fallback: try metadata_json for instructions
            if not instructions_preview and row.get('metadata_json'):
                try:
                    meta = json.loads(row['metadata_json']) if isinstance(row['metadata_json'], str) else row['metadata_json']
                    if isinstance(meta, dict):
                        instr = meta.get('instructions', '')
                        if instr:
                            lines = instr.strip().split('\n')
                            first_line = lines[0][:80]
                            instructions_preview = first_line + ('...' if len(lines) > 1 or len(lines[0]) > 80 else '')
                except:
                    pass

            # Try to extract input preview from metadata (often contains input data)
            if row.get('metadata_json'):
                try:
                    meta = json.loads(row['metadata_json']) if isinstance(row['metadata_json'], str) else row['metadata_json']
                    if isinstance(meta, dict):
                        # Look for common input fields
                        input_data = meta.get('input') or meta.get('inputs') or meta.get('context')
                        if input_data:
                            if isinstance(input_data, dict):
                                preview_parts = []
                                for k, v in list(input_data.items())[:3]:
                                    val_str = str(v)[:50] + '...' if len(str(v)) > 50 else str(v)
                                    preview_parts.append(f"{k}: {val_str}")
                                input_preview = " | ".join(preview_parts)
                            elif isinstance(input_data, str):
                                input_preview = input_data[:100] + ('...' if len(input_data) > 100 else '')
                except:
                    pass

            return input_preview, instructions_preview

        species = []
        for row in result:
            # Win rate = winners / sessions (not winners / attempts)
            # Each session has exactly 1 winner, so session_count = max possible wins
            session_count = row['session_count']
            winner_count = row['winner_count']
            win_rate = round(winner_count / session_count * 100, 1) if session_count > 0 else 0

            # Get identifying information for this species
            input_preview, instructions_preview = get_species_sample(row['species_hash'])

            total_cost = float(row.get('total_cost', 0)) if row.get('total_cost') else 0
            avg_cost = total_cost / session_count if session_count > 0 else 0

            species.append({
                'species_hash': row['species_hash'],
                'session_count': session_count,
                'winner_count': winner_count,
                'total_attempts': row['total_attempts'],
                'total_cost': total_cost,
                'avg_cost': round(avg_cost, 6),
                'win_rate': win_rate,
                'input_preview': input_preview,
                'instructions_preview': instructions_preview,
                'first_seen': str(row['first_seen']) if row['first_seen'] else None,
                'last_seen': str(row['last_seen']) if row['last_seen'] else None,
            })

        # Generate warning if multiple species
        warning = None
        if len(species) > 1:
            warning = f"Multiple species detected ({len(species)}). Select a single species for accurate comparison."

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'species': species,
            'species_count': len(species),
            'warning': warning,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/analyze/<cascade_id>', methods=['GET'])
def analyze_cascade(cascade_id):
    """
    Analyze a cascade's candidate patterns.

    Returns per-cell analysis with:
    - Win rate by MODEL (the causal factor, not arbitrary candidate index)
    - Win rate by MUTATION TYPE (when mutations are used)
    - Cost/quality metrics per model
    - Detected patterns in winning responses
    """
    db = get_db()
    min_runs = request.args.get('min_runs', 3, type=int)

    try:
        # Get cells with candidates for this cascade
        cells_query = f"""
            SELECT
                cell_name,
                COUNT(DISTINCT session_id) as session_count,
                SUM(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as winner_count
            FROM unified_logs
            WHERE cascade_id = '{cascade_id}'
              AND candidate_index IS NOT NULL
              AND cell_name IS NOT NULL
              AND node_type = 'candidate_attempt'
            GROUP BY cell_name
            ORDER BY session_count DESC
        """

        cells_result = db.query(cells_query, output_format='dict')

        cells = []
        for cell in cells_result:
            cell_name = cell['cell_name']

            # Get MODEL breakdown (the meaningful dimension!)
            model_query = f"""
                SELECT
                    model,
                    SUM(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as wins,
                    COUNT(*) as attempts,
                    AVG(CASE WHEN cost > 0 THEN cost ELSE NULL END) as avg_cost,
                    AVG(CASE WHEN duration_ms > 0 THEN duration_ms ELSE NULL END) as avg_duration
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                  AND model IS NOT NULL
                GROUP BY model
                ORDER BY wins DESC
            """

            model_result = db.query(model_query, output_format='dict')

            # Get MUTATION TYPE breakdown (when mutations are used)
            mutation_query = f"""
                SELECT
                    COALESCE(mutation_type, 'baseline') as mutation_type,
                    SUM(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as wins,
                    COUNT(*) as attempts
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                GROUP BY mutation_type
                ORDER BY wins DESC
            """

            mutation_result = db.query(mutation_query, output_format='dict')

            # Calculate total competitions
            total_wins = cell['winner_count']

            # Find best model
            best_model = None
            best_win_rate = 0
            for m in model_result:
                if m['attempts'] >= 2:  # Need at least 2 attempts for meaningful rate
                    rate = (m['wins'] / m['attempts'] * 100) if m['attempts'] > 0 else 0
                    if rate > best_win_rate:
                        best_win_rate = rate
                        best_model = m

            # Get sample winning content for pattern extraction
            sample_query = f"""
                SELECT content_json
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND is_winner = true
                  AND node_type = 'candidate_attempt'
                LIMIT 5
            """
            samples = db.query(sample_query, output_format='dict')

            # Simple pattern extraction
            patterns = extract_patterns([s.get('content_json', '') for s in samples])

            # Check if this is multi-model or single-model
            unique_models = len(model_result)
            has_mutations = any(m['mutation_type'] != 'baseline' for m in mutation_result)

            cells.append({
                'cell_name': cell_name,
                'session_count': cell['session_count'],
                'total_competitions': total_wins,
                'unique_models': unique_models,
                'has_mutations': has_mutations,
                # MODEL performance (the key insight!)
                'models': [{
                    'model': m['model'],
                    'model_short': m['model'].split('/')[-1] if m['model'] else 'unknown',
                    'wins': m['wins'],
                    'attempts': m['attempts'],
                    'win_rate': (m['wins'] / m['attempts'] * 100) if m['attempts'] > 0 else 0,
                    'avg_cost': float(m['avg_cost']) if m['avg_cost'] else 0,
                    'avg_duration': float(m['avg_duration']) if m['avg_duration'] else 0,
                } for m in model_result],
                # MUTATION performance (when relevant)
                'mutations': [{
                    'type': m['mutation_type'],
                    'wins': m['wins'],
                    'attempts': m['attempts'],
                    'win_rate': (m['wins'] / m['attempts'] * 100) if m['attempts'] > 0 else 0,
                } for m in mutation_result] if has_mutations else [],
                # Best performer
                'best_model': best_model['model'].split('/')[-1] if best_model and best_model['model'] else None,
                'best_model_full': best_model['model'] if best_model else None,
                'best_win_rate': best_win_rate,
                'patterns': patterns,
                'analysis_ready': total_wins >= min_runs,
                'confidence': 'high' if best_win_rate >= 70 else 'medium' if best_win_rate >= 50 else 'low',
            })

        return jsonify({
            'cascade_id': cascade_id,
            'cells': cells,
            'total_cells': len(cells),
            'analysis_ready_cells': sum(1 for p in cells if p['analysis_ready']),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/winner-loser-analysis/<cascade_id>/<cell_name>', methods=['GET'])
def winner_loser_analysis(cascade_id, cell_name):
    """
    Compare winning vs losing PROMPTS and generate LLM synopsis.

    REFOCUSED: This now analyzes PROMPTS (inputs) not responses (outputs).
    The response quality is just a signal - what matters is the prompt that caused it.

    Query params:
    - limit: Max prompts per category (default 5)
    - skip_llm: Skip LLM synopsis generation
    - species_hash: Filter to specific species (prompt template DNA)

    Returns:
    - Top N winning prompts with content preview
    - Top N losing prompts with content preview
    - LLM-generated synopsis analyzing PROMPT patterns
    - species_info: Species metadata and warnings
    """
    db = get_db()
    limit = request.args.get('limit', 5, type=int)
    skip_llm = request.args.get('skip_llm', 'false').lower() == 'true'
    species_filter = request.args.get('species_hash', None)

    try:
        import json as json_mod

        # Helper to extract prompt text from full_request_json
        def extract_prompt_text(full_request_json):
            if not full_request_json:
                return ""
            try:
                req = json_mod.loads(full_request_json)
                messages = req.get('messages', [])
                prompt_parts = []
                for m in messages:
                    if m.get('role') == 'user':
                        prompt_parts.append(m.get('content', ''))
                    elif m.get('role') == 'system':
                        prompt_parts.append(f"[SYSTEM]: {m.get('content', '')}")
                return '\n\n'.join(prompt_parts)
            except:
                return ""

        # Build species filter clause
        species_clause = f"AND species_hash = '{species_filter}'" if species_filter else ""
        species_clause_a = f"AND a.species_hash = '{species_filter}'" if species_filter else ""

        # Get winning PROMPTS (join agent rows with candidate_attempt for is_winner)
        winners_query = f"""
            SELECT
                a.trace_id,
                a.session_id,
                a.candidate_index,
                a.model,
                a.full_request_json,
                a.cost,
                a.duration_ms,
                s.mutation_type AS mutation_type,
                s.species_hash AS species_hash,
                a.timestamp
            FROM unified_logs a
            INNER JOIN (
                SELECT candidate_index, is_winner, session_id, mutation_type, species_hash
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                  AND is_winner = true
                  {species_clause}
            ) s ON a.candidate_index = s.candidate_index AND a.session_id = s.session_id
            WHERE a.cascade_id = '{cascade_id}'
              AND a.cell_name = '{cell_name}'
              AND a.node_type = 'agent'
              AND a.candidate_index IS NOT NULL
              AND a.full_request_json IS NOT NULL
            ORDER BY a.timestamp DESC
            LIMIT {limit}
        """
        winners_result = db.query(winners_query, output_format='dict')

        if not winners_result:
            return jsonify({
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'winners': [],
                'losers': [],
                'synopsis': None,
                'message': 'No winning prompts found for this cell'
            })

        # Get losing PROMPTS from same sessions
        session_ids = list(set(w['session_id'] for w in winners_result))
        session_list = ", ".join(f"'{s}'" for s in session_ids)

        losers_query = f"""
            SELECT
                a.trace_id,
                a.session_id,
                a.candidate_index,
                a.model,
                a.full_request_json,
                a.cost,
                a.duration_ms,
                s.mutation_type AS mutation_type,
                s.species_hash AS species_hash,
                a.timestamp
            FROM unified_logs a
            INNER JOIN (
                SELECT candidate_index, is_winner, session_id, mutation_type, species_hash
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                  AND (is_winner = false OR is_winner IS NULL)
                  {species_clause}
            ) s ON a.candidate_index = s.candidate_index AND a.session_id = s.session_id
            WHERE a.cascade_id = '{cascade_id}'
              AND a.cell_name = '{cell_name}'
              AND a.node_type = 'agent'
              AND a.candidate_index IS NOT NULL
              AND a.full_request_json IS NOT NULL
              AND a.session_id IN ({session_list})
            ORDER BY a.timestamp DESC
            LIMIT {limit}
        """
        losers_result = db.query(losers_query, output_format='dict')

        # Format winners (now showing PROMPTS)
        winners = []
        for row in winners_result:
            prompt = extract_prompt_text(row.get('full_request_json', ''))
            winners.append({
                'trace_id': row['trace_id'],
                'session_id': row['session_id'],
                'candidate_index': row['candidate_index'],
                'model': row['model'],
                'model_short': row['model'].split('/')[-1] if row['model'] else 'unknown',
                'prompt_preview': prompt[:500] + '...' if len(prompt) > 500 else prompt,
                'prompt_full': prompt,
                'cost': float(row['cost']) if row['cost'] else 0,
                'duration_ms': float(row['duration_ms']) if row['duration_ms'] else 0,
                'mutation_type': row.get('mutation_type'),
                'timestamp': str(row['timestamp']),
            })

        # Format losers (now showing PROMPTS)
        losers = []
        for row in losers_result:
            prompt = extract_prompt_text(row.get('full_request_json', ''))
            losers.append({
                'trace_id': row['trace_id'],
                'session_id': row['session_id'],
                'candidate_index': row['candidate_index'],
                'model': row['model'],
                'model_short': row['model'].split('/')[-1] if row['model'] else 'unknown',
                'prompt_preview': prompt[:500] + '...' if len(prompt) > 500 else prompt,
                'prompt_full': prompt,
                'cost': float(row['cost']) if row['cost'] else 0,
                'duration_ms': float(row['duration_ms']) if row['duration_ms'] else 0,
                'mutation_type': row.get('mutation_type'),
                'timestamp': str(row['timestamp']),
            })

        # Generate LLM synopsis analyzing PROMPTS (unless skip_llm=true)
        synopsis = None
        if not skip_llm and winners and losers:
            synopsis = generate_prompt_synopsis(winners, losers, cascade_id, cell_name)

        # Compute cost analysis
        winner_costs = [w['cost'] for w in winners if w['cost'] > 0]
        loser_costs = [l['cost'] for l in losers if l['cost'] > 0]

        avg_winner_cost = sum(winner_costs) / len(winner_costs) if winner_costs else 0
        avg_loser_cost = sum(loser_costs) / len(loser_costs) if loser_costs else 0
        cost_premium_pct = ((avg_winner_cost - avg_loser_cost) / avg_loser_cost * 100) if avg_loser_cost > 0 else 0

        cost_analysis = {
            'avg_winner_cost': round(avg_winner_cost, 6),
            'avg_loser_cost': round(avg_loser_cost, 6),
            'cost_premium_pct': round(cost_premium_pct, 1),
            'total_winner_cost': round(sum(winner_costs), 6),
            'total_loser_cost': round(sum(loser_costs), 6),
        }

        # Collect species info from results
        all_species = set()
        for row in winners_result:
            if row.get('species_hash'):
                all_species.add(row['species_hash'])
        for row in losers_result:
            if row.get('species_hash'):
                all_species.add(row['species_hash'])

        species_info = {
            'species_hash': species_filter,  # Active filter (or None)
            'detected_species': list(all_species),
            'species_count': len(all_species),
            'warning': None
        }
        if len(all_species) > 1 and not species_filter:
            species_info['warning'] = f"Data contains {len(all_species)} different species (prompt templates). Comparing prompts from different templates may give misleading results. Use ?species_hash=X to filter."

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'winners': winners,
            'losers': losers,
            'synopsis': synopsis,
            'winner_count': len(winners),
            'loser_count': len(losers),
            'cost_analysis': cost_analysis,
            'species_info': species_info,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def extract_content_text(content_json) -> str:
    """Extract readable text from content_json field."""
    if not content_json:
        return ''

    if isinstance(content_json, str):
        try:
            content = json.loads(content_json)
        except:
            return content_json
    else:
        content = content_json

    # Handle various content formats
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        # Try common keys
        if 'content' in content:
            return str(content['content'])
        if 'text' in content:
            return str(content['text'])
        if 'message' in content:
            return str(content['message'])
        return json.dumps(content, indent=2)
    elif isinstance(content, list):
        # Join list items
        return '\n'.join(str(item) for item in content)
    else:
        return str(content)


def generate_prompt_synopsis(winners: list, losers: list, cascade_id: str, cell_name: str) -> dict:
    """
    Use LLM to analyze what makes WINNING PROMPTS succeed.

    REFOCUSED: Analyzes PROMPTS (inputs) not responses (outputs).
    The goal is prompt optimization - understanding what prompt patterns lead to winning.

    Returns structured synopsis with patterns and actionable suggestions.
    """
    from rvbbit.agent import Agent
    from rvbbit.config import get_config
    from rvbbit.unified_logs import log_unified
    import uuid

    config = get_config()

    # Format winning PROMPTS
    winners_text = "\n\n---\n\n".join([
        f"WINNING PROMPT {i+1} (model: {w['model_short']}, mutation: {w.get('mutation_type', 'none')}):\n{w['prompt_full'][:2000]}"
        for i, w in enumerate(winners)
    ])

    # Format losing PROMPTS
    losers_text = "\n\n---\n\n".join([
        f"LOSING PROMPT {i+1} (model: {l['model_short']}, mutation: {l.get('mutation_type', 'none')}):\n{l['prompt_full'][:2000]}"
        for i, l in enumerate(losers)
    ])

    system_prompt = "You are a prompt engineering expert analyzing what makes prompts succeed. Respond only with valid JSON."

    analysis_prompt = f"""You are analyzing INPUT PROMPTS to understand what makes them produce winning outputs.

CONTEXT: These are the prompts sent to LLMs in the "{cell_name}" cell of cascade "{cascade_id}".
An evaluator judged the outputs - WINNING PROMPTS produced better outputs than LOSING PROMPTS.
Your job is to identify what in the PROMPT WORDING caused better outputs.

WINNING PROMPTS (these produced outputs selected as best):
{winners_text}

LOSING PROMPTS (these produced outputs not selected):
{losers_text}

Analyze the PROMPT WORDING and provide your analysis in this exact JSON format:
{{
    "winner_patterns": ["pattern 1", "pattern 2", "pattern 3"],
    "loser_patterns": ["pattern 1", "pattern 2", "pattern 3"],
    "key_difference": "One sentence describing the most important prompt difference",
    "suggestion": "A specific prompt modification to apply to the base prompt",
    "confidence": 0.85
}}

Guidelines:
- winner_patterns: 3-5 specific PROMPT WORDING patterns in winning prompts (e.g., "uses 'evocative' adjective", "includes step-by-step instruction")
- loser_patterns: 3-5 PROMPT WORDING patterns in losing prompts
- key_difference: What's different about HOW the prompt is WORDED (not about outputs!)
- suggestion: A concrete change to PROMPT WORDING (e.g., "Replace 'be creative' with 'be evocative and dramatic'")
- confidence: 0.0-1.0 based on how clear the prompt patterns are

IMPORTANT: Focus on PROMPT WORDING differences, not output quality. What words/phrases/structure in the prompt correlate with success?

Respond ONLY with the JSON object, no other text."""

    try:
        # Use a fast model for analysis
        analysis_model = config.default_model  # Use configured default

        # Generate tracking IDs for logging
        session_id = f'sextant_analysis_{cascade_id}_{cell_name}'
        trace_id = f'sextant_{uuid.uuid4().hex[:12]}'

        # Create agent with proper interface - must pass base_url and api_key for OpenRouter
        agent = Agent(
            model=analysis_model,
            system_prompt=system_prompt,
            base_url=config.provider_base_url,
            api_key=config.provider_api_key,
        )

        # Run the analysis
        response = agent.run(input_message=analysis_prompt)

        # Log to unified_logs so this call is tracked for cost analysis
        log_unified(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=None,
            node_type="sextant_analysis",
            role="assistant",
            depth=0,
            cell_name="winner_loser_analysis",
            cascade_id="sextant",
            model=response.get('model', analysis_model),
            provider=response.get('provider'),
            request_id=response.get('id'),
            content=response.get('content', ''),
            metadata={
                'analyzed_cascade': cascade_id,
                'analyzed_cell': cell_name,
                'winner_count': len(winners),
                'loser_count': len(losers),
            },
            tokens_in=response.get('tokens_in'),
            tokens_out=response.get('tokens_out'),
            cost=response.get('cost'),
        )

        # Parse the JSON response
        response_text = response.get('content', '')

        # Try to extract JSON from response
        try:
            # Handle potential markdown code blocks
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0]
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0]

            synopsis = json.loads(response_text.strip())

            # Validate structure
            required_keys = ['winner_patterns', 'loser_patterns', 'key_difference', 'suggestion', 'confidence']
            if all(k in synopsis for k in required_keys):
                return synopsis
            else:
                # Return with defaults for missing keys
                return {
                    'winner_patterns': synopsis.get('winner_patterns', ['Analysis incomplete']),
                    'loser_patterns': synopsis.get('loser_patterns', ['Analysis incomplete']),
                    'key_difference': synopsis.get('key_difference', 'Could not determine'),
                    'suggestion': synopsis.get('suggestion', 'No suggestion available'),
                    'confidence': synopsis.get('confidence', 0.5),
                }

        except json.JSONDecodeError:
            # Return raw analysis if JSON parsing fails
            return {
                'winner_patterns': ['Could not parse structured patterns'],
                'loser_patterns': ['Could not parse structured patterns'],
                'key_difference': response_text[:500] if response_text else 'Analysis failed',
                'suggestion': 'Review the raw analysis above',
                'confidence': 0.3,
                'raw_response': response_text,
            }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            'winner_patterns': ['Analysis error'],
            'loser_patterns': ['Analysis error'],
            'key_difference': f'Error during analysis: {str(e)}',
            'suggestion': 'Try again or check API configuration',
            'confidence': 0.0,
            'error': str(e),
        }


@sextant_bp.route('/suggestions/<cascade_id>', methods=['GET'])
def get_suggestions(cascade_id):
    """
    Generate improvement suggestions for a cascade.

    Uses the SoundingAnalyzer to generate actual prompt improvements.
    """
    from rvbbit.analyzer import SoundingAnalyzer, analyze_and_suggest

    cell_name = request.args.get('cell')
    min_runs = request.args.get('min_runs', 5, type=int)
    generate = request.args.get('generate', 'false').lower() == 'true'

    try:
        analyzer = SoundingAnalyzer()

        # Basic analysis first
        analysis = analyzer.analyze_cascade(cascade_id, min_runs=min_runs, min_confidence=0.4)

        if not analysis['suggestions']:
            return jsonify({
                'cascade_id': cascade_id,
                'suggestions': [],
                'message': 'No suggestions available (not enough data or no clear winners)',
            })

        # If generate=true, actually call LLM to generate improved prompts
        if generate:
            # Try to find the cascade file
            config = get_config()
            cascade_file = find_cascade_file(cascade_id, config)

            if cascade_file:
                full_analysis = analyze_and_suggest(cascade_file, cell_name=cell_name, min_runs=min_runs)
                analysis = full_analysis

        # Format suggestions for UI
        suggestions = []
        for s in analysis['suggestions']:
            suggestion = {
                'cell': s['cell'],
                'dominant_candidate': s.get('dominant_candidate'),
                'win_rate': s['win_rate'],
                'wins': s['wins'],
                'total_attempts': s.get('total_attempts', 0),
                'confidence': s.get('confidence', 'medium'),
                'patterns': s.get('patterns', []),
                'metrics': s.get('metrics', {}),
            }

            # Add generated suggestion if available
            if 'current_instruction' in s:
                suggestion['current_instruction'] = s['current_instruction']
            if 'suggested_instruction' in s:
                suggestion['suggested_instruction'] = s['suggested_instruction']
            if 'impact' in s:
                suggestion['impact'] = s['impact']

            suggestions.append(suggestion)

        return jsonify({
            'cascade_id': cascade_id,
            'total_runs': analysis.get('total_runs', 0),
            'analyzed_at': analysis.get('analyzed_at'),
            'suggestions': suggestions,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/apply', methods=['POST'])
def apply_suggestion():
    """
    Apply a suggestion to a cascade file.

    Body: {
        cascade_id: string,
        cell_name: string,
        new_instruction: string,
        auto_commit: boolean (optional)
    }
    """
    from rvbbit.analyzer import PromptSuggestionManager

    data = request.json or {}
    cascade_id = data.get('cascade_id')
    cell_name = data.get('cell_name')
    new_instruction = data.get('new_instruction')
    auto_commit = data.get('auto_commit', False)

    if not all([cascade_id, cell_name, new_instruction]):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        config = get_config()
        cascade_file = find_cascade_file(cascade_id, config)

        if not cascade_file:
            return jsonify({'error': f'Cascade file not found for {cascade_id}'}), 404

        manager = PromptSuggestionManager()
        success = manager.apply_suggestion(
            cascade_file=cascade_file,
            cell_name=cell_name,
            new_instruction=new_instruction,
            auto_commit=auto_commit
        )

        if success:
            return jsonify({
                'success': True,
                'cascade_file': cascade_file,
                'cell_name': cell_name,
                'auto_committed': auto_commit,
            })
        else:
            return jsonify({'error': 'Failed to apply suggestion'}), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/winning-samples/<cascade_id>/<cell_name>', methods=['GET'])
def get_winning_samples(cascade_id, cell_name):
    """
    Get sample winning outputs for a specific cell.

    Useful for understanding WHY certain candidates win.
    Note: is_winner is marked on candidate_attempt rows, not assistant rows.
    Now supports species_hash filtering for apples-to-apples comparison.
    """
    db = get_db()
    limit = request.args.get('limit', 5, type=int)
    species_filter = request.args.get('species_hash', None)

    try:
        species_clause = f"AND species_hash = '{species_filter}'" if species_filter else ""

        query = f"""
            SELECT
                session_id,
                candidate_index,
                content_json,
                cost,
                duration_ms,
                model,
                species_hash,
                timestamp
            FROM unified_logs
            WHERE cascade_id = '{cascade_id}'
              AND cell_name = '{cell_name}'
              AND is_winner = true
              AND node_type = 'candidate_attempt'
              {species_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """

        result = db.query(query, output_format='dict')

        samples = []
        for row in result:
            content = row.get('content_json', '')
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except:
                    pass

            samples.append({
                'session_id': row['session_id'],
                'candidate_index': row['candidate_index'],
                'content': content if isinstance(content, str) else json.dumps(content, indent=2)[:2000],
                'cost': float(row['cost']) if row['cost'] else 0,
                'duration_ms': float(row['duration_ms']) if row['duration_ms'] else 0,
                'model': row['model'],
                'timestamp': str(row['timestamp']),
            })

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'samples': samples,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/embedding-hotspots/<cascade_id>/<cell_name>', methods=['GET'])
def embedding_hotspots(cascade_id, cell_name):
    """
    Compute PROMPT embedding hotspots - where winning vs losing PROMPTS cluster.

    REFOCUSED: Now analyzes PROMPTS (inputs) not responses (outputs).
    Shows which prompt patterns cluster together and which correlate with winning.

    Returns:
    - Hotspot regions with heat scores (positive = winner-dense, negative = loser-dense)
    - 2D visualization coordinates (PCA projection)
    - Sample prompts from each region
    """
    db = get_db()
    n_regions = request.args.get('n_regions', 5, type=int)
    min_samples = request.args.get('min_samples', 4, type=int)
    species_filter = request.args.get('species_hash', None)

    try:
        import numpy as np
        import json as json_mod
        from rvbbit.agent import Agent
        from rvbbit.config import get_config

        config = get_config()

        # Build species filter clause for subquery
        species_clause_sub = f"AND species_hash = '{species_filter}'" if species_filter else ""
        species_clause_main = f"AND a.species_hash = '{species_filter}'" if species_filter else ""

        # Helper to extract prompt text from full_request_json
        def extract_prompt_text(full_request_json):
            if not full_request_json:
                return ""
            try:
                req = json_mod.loads(full_request_json)
                messages = req.get('messages', [])
                prompt_parts = []
                for m in messages:
                    if m.get('role') == 'user':
                        prompt_parts.append(m.get('content', ''))
                    elif m.get('role') == 'system':
                        prompt_parts.append(f"[SYSTEM]: {m.get('content', '')}")
                return '\n\n'.join(prompt_parts)
            except:
                return ""

        # Get PROMPTS from agent rows, joined with candidate_attempt for is_winner
        # Include cost for cost analysis
        query = f"""
            SELECT
                a.trace_id,
                a.session_id,
                a.candidate_index,
                a.full_request_json,
                a.model,
                a.cost,
                a.species_hash,
                s.is_winner AS is_winner
            FROM unified_logs a
            INNER JOIN (
                SELECT candidate_index, is_winner, session_id
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                  {species_clause_sub}
            ) s ON a.candidate_index = s.candidate_index AND a.session_id = s.session_id
            WHERE a.cascade_id = '{cascade_id}'
              AND a.cell_name = '{cell_name}'
              AND a.node_type = 'agent'
              AND a.candidate_index IS NOT NULL
              AND a.full_request_json IS NOT NULL
              AND length(a.full_request_json) > 10
              {species_clause_main}
            ORDER BY a.timestamp DESC
            LIMIT 100
        """
        results = db.query(query, output_format='dict')

        if len(results) < min_samples:
            return jsonify({
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'error': f'Not enough prompts found (found {len(results)}, need {min_samples})',
                'hotspots': [],
                'visualization': None
            })

        # Extract prompts and filter valid ones
        prompts_data = []
        for row in results:
            prompt_text = extract_prompt_text(row.get('full_request_json'))
            if prompt_text and row.get('is_winner') is not None:
                prompts_data.append({
                    'trace_id': row['trace_id'],
                    'candidate_index': row['candidate_index'],
                    'is_winner': bool(row.get('is_winner')),
                    'prompt': prompt_text[:1000],  # Limit for embedding
                    'model': row.get('model', '').split('/')[-1] if row.get('model') else 'unknown',
                    'cost': float(row.get('cost') or 0),
                })

        if len(prompts_data) < min_samples:
            return jsonify({
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'error': f'Not enough valid prompts (found {len(prompts_data)})',
                'hotspots': [],
                'visualization': None
            })

        # Embed all prompts
        prompt_texts = [p['prompt'] for p in prompts_data]

        embed_result = Agent.embed(
            texts=prompt_texts,
            model=config.default_embed_model,
            session_id=f'sextant_hotspots_{cascade_id}',
            cascade_id='sextant',
            cell_name='embedding_hotspots',
        )

        embeddings = np.array(embed_result['embeddings'])

        # Add embeddings to points
        points = []
        for i, p in enumerate(prompts_data):
            points.append({
                'trace_id': p['trace_id'],
                'candidate_index': p['candidate_index'],
                'is_winner': p['is_winner'],
                'prompt': p['prompt'][:500],
                'model': p['model'],
                'cost': p['cost'],
                'embedding': embeddings[i]
            })

        if len(points) < min_samples:
            return jsonify({
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'error': f'Not enough valid embeddings (found {len(points)})',
                'hotspots': [],
                'visualization': None
            })

        # Stack embeddings for clustering
        embeddings = np.vstack([p['embedding'] for p in points])

        # Use PCA for dimensionality reduction (faster than t-SNE for real-time)
        from sklearn.decomposition import PCA
        from sklearn.cluster import KMeans

        # 2D projection for visualization
        pca_2d = PCA(n_components=2)
        coords_2d = pca_2d.fit_transform(embeddings)

        # Reduce to fewer dimensions for clustering (speeds up K-means)
        n_components = min(50, embeddings.shape[1], len(points) - 1)
        pca_cluster = PCA(n_components=n_components)
        embeddings_reduced = pca_cluster.fit_transform(embeddings)

        # Cluster
        n_clusters = min(n_regions, len(points) // 2)  # At least 2 points per cluster
        if n_clusters < 2:
            n_clusters = 2

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings_reduced)

        # Compute hotspots
        hotspots = []
        for i in range(n_clusters):
            cluster_points = [p for p, l in zip(points, labels) if l == i]
            if not cluster_points:
                continue

            winner_count = sum(1 for p in cluster_points if p['is_winner'])
            loser_count = len(cluster_points) - winner_count
            total = len(cluster_points)

            winner_density = winner_count / total
            loser_density = loser_count / total
            heat = winner_density - loser_density  # -1 to +1

            # Find centroid point (closest to cluster center)
            cluster_coords = np.array([coords_2d[j] for j, l in enumerate(labels) if l == i])
            cluster_center = cluster_coords.mean(axis=0)

            # Sample prompts from cluster
            sample_prompts = [p['prompt'][:150] for p in cluster_points[:3]]

            hotspots.append({
                'region_id': i,
                'size': total,
                'winner_count': winner_count,
                'loser_count': loser_count,
                'winner_density': round(winner_density, 3),
                'loser_density': round(loser_density, 3),
                'heat': round(heat, 3),
                'center_x': float(cluster_center[0]),
                'center_y': float(cluster_center[1]),
                'sample_prompts': sample_prompts,
                'models': list(set(p['model'] for p in cluster_points)),
            })

        # Sort by heat (hottest first)
        hotspots = sorted(hotspots, key=lambda h: h['heat'], reverse=True)

        # Build visualization data
        viz_points = []
        for i, (p, coord, label) in enumerate(zip(points, coords_2d, labels)):
            viz_points.append({
                'x': float(coord[0]),
                'y': float(coord[1]),
                'is_winner': p['is_winner'],
                'cluster': int(label),
                'model': p['model'],
                'candidate_index': p.get('candidate_index'),
                'prompt_preview': p['prompt'][:100],
                'cost': p['cost'],
            })

        # Compute cost analysis
        winner_costs = [p['cost'] for p in points if p['is_winner']]
        loser_costs = [p['cost'] for p in points if not p['is_winner']]

        avg_winner_cost = sum(winner_costs) / len(winner_costs) if winner_costs else 0
        avg_loser_cost = sum(loser_costs) / len(loser_costs) if loser_costs else 0
        cost_premium_pct = ((avg_winner_cost - avg_loser_cost) / avg_loser_cost * 100) if avg_loser_cost > 0 else 0

        cost_analysis = {
            'avg_winner_cost': round(avg_winner_cost, 6),
            'avg_loser_cost': round(avg_loser_cost, 6),
            'cost_premium_pct': round(cost_premium_pct, 1),
            'total_winner_cost': round(sum(winner_costs), 6),
            'total_loser_cost': round(sum(loser_costs), 6),
            'max_cost': round(max(p['cost'] for p in points), 6) if points else 0,
            'min_cost': round(min(p['cost'] for p in points), 6) if points else 0,
        }

        # Generate interpretation
        hot_regions = [h for h in hotspots if h['heat'] > 0.3]
        cold_regions = [h for h in hotspots if h['heat'] < -0.3]

        interpretation = None
        if hot_regions and cold_regions:
            interpretation = f"Found {len(hot_regions)} winner-dense regions and {len(cold_regions)} loser-dense regions. "
            if hot_regions[0]['sample_prompts']:
                interpretation += f"Winning prompts cluster around: '{hot_regions[0]['sample_prompts'][0][:50]}...'"

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'hotspots': hotspots,
            'visualization': {
                'type': '2d_pca',
                'points': viz_points,
                'explained_variance': float(sum(pca_2d.explained_variance_ratio_)),
            },
            'summary': {
                'total_points': len(points),
                'winner_count': sum(1 for p in points if p['is_winner']),
                'loser_count': sum(1 for p in points if not p['is_winner']),
                'n_clusters': n_clusters,
            },
            'cost_analysis': cost_analysis,
            'interpretation': interpretation,
        })

    except ImportError as e:
        return jsonify({
            'error': f'Missing dependency: {str(e)}. Install with: pip install scikit-learn',
            'hotspots': [],
            'visualization': None
        }), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/text-heatmap/<cascade_id>/<cell_name>', methods=['GET'])
def text_heatmap(cascade_id, cell_name):
    """
    FLIR-style heat vision for text - show which parts of responses correlate with winning.

    Process:
    1. Compute winner centroid (avg embedding of all winners)
    2. Compute loser centroid (avg embedding of all losers)
    3. For a sample response, break into sentences
    4. Embed each sentence, compute heat = sim_to_winner - sim_to_loser
    5. Return text with per-sentence heat scores for rendering

    Query params:
    - trace_id: Specific response to analyze (optional, defaults to first winner)
    - chunk_size: Approximate chars per chunk (default 150)
    """
    db = get_db()
    trace_id = request.args.get('trace_id')
    chunk_size = request.args.get('chunk_size', 150, type=int)

    try:
        import numpy as np
        from rvbbit.agent import Agent
        from rvbbit.config import get_config

        config = get_config()

        # Step 1: Get all winners and losers with embeddings
        query = f"""
            SELECT
                trace_id,
                is_winner,
                content_embedding,
                content_json,
                model
            FROM unified_logs
            WHERE cascade_id = '{cascade_id}'
              AND cell_name = '{cell_name}'
              AND node_type = 'candidate_attempt'
              AND length(content_embedding) > 0
            ORDER BY timestamp DESC
            LIMIT 200
        """
        results = db.query(query, output_format='dict')

        if len(results) < 4:
            return jsonify({
                'error': f'Not enough samples (found {len(results)}, need at least 4)',
                'cascade_id': cascade_id,
                'cell_name': cell_name,
            })

        # Separate winners and losers
        winners = [r for r in results if r.get('is_winner')]
        losers = [r for r in results if not r.get('is_winner')]

        if not winners or not losers:
            return jsonify({
                'error': 'Need both winners and losers for comparison',
                'winner_count': len(winners),
                'loser_count': len(losers),
            })

        # Step 2: Compute centroids
        winner_embeddings = np.array([r['content_embedding'] for r in winners])
        loser_embeddings = np.array([r['content_embedding'] for r in losers])

        winner_centroid = winner_embeddings.mean(axis=0)
        loser_centroid = loser_embeddings.mean(axis=0)

        # Normalize centroids for cosine similarity
        winner_centroid = winner_centroid / (np.linalg.norm(winner_centroid) + 1e-9)
        loser_centroid = loser_centroid / (np.linalg.norm(loser_centroid) + 1e-9)

        # Step 3: Get the target response to analyze
        if trace_id:
            target = next((r for r in results if r['trace_id'] == trace_id), None)
            if not target:
                return jsonify({'error': f'Response {trace_id} not found'})
        else:
            # Default to first winner for interesting visualization
            target = winners[0] if winners else results[0]

        target_content = extract_content_text(target.get('content_json', ''))
        target_is_winner = target.get('is_winner', False)
        target_model = target.get('model', '').split('/')[-1] if target.get('model') else 'unknown'

        # Step 4: Chunk the text into sentences/segments
        chunks = chunk_text_smart(target_content, chunk_size)

        if not chunks:
            return jsonify({
                'error': 'No text content to analyze',
                'trace_id': target['trace_id'],
            })

        # Step 5: Embed each chunk
        chunk_texts = [c['text'] for c in chunks]

        # Use Agent.embed for tracked embedding calls
        embed_result = Agent.embed(
            texts=chunk_texts,
            model=config.default_embed_model,
            session_id=f'sextant_heatmap_{cascade_id}',
            cascade_id='sextant',
            cell_name='text_heatmap',
        )

        chunk_embeddings = np.array(embed_result['embeddings'])

        # Step 6: Compute heat for each chunk
        heatmap_chunks = []
        for i, chunk in enumerate(chunks):
            emb = chunk_embeddings[i]
            emb_norm = emb / (np.linalg.norm(emb) + 1e-9)

            # Cosine similarity to each centroid
            sim_to_winner = float(np.dot(emb_norm, winner_centroid))
            sim_to_loser = float(np.dot(emb_norm, loser_centroid))

            # Heat: positive = winner-like, negative = loser-like
            heat = sim_to_winner - sim_to_loser

            heatmap_chunks.append({
                'text': chunk['text'],
                'start': chunk['start'],
                'end': chunk['end'],
                'heat': round(heat, 4),
                'sim_to_winner': round(sim_to_winner, 4),
                'sim_to_loser': round(sim_to_loser, 4),
            })

        # Compute overall stats
        heats = [c['heat'] for c in heatmap_chunks]
        avg_heat = sum(heats) / len(heats) if heats else 0
        max_heat = max(heats) if heats else 0
        min_heat = min(heats) if heats else 0

        # Find hottest and coldest chunks
        sorted_by_heat = sorted(heatmap_chunks, key=lambda x: x['heat'], reverse=True)
        hottest = sorted_by_heat[:3] if len(sorted_by_heat) >= 3 else sorted_by_heat
        coldest = sorted_by_heat[-3:] if len(sorted_by_heat) >= 3 else []

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'trace_id': target['trace_id'],
            'is_winner': target_is_winner,
            'model': target_model,
            'full_text': target_content,
            'chunks': heatmap_chunks,
            'stats': {
                'chunk_count': len(heatmap_chunks),
                'avg_heat': round(avg_heat, 4),
                'max_heat': round(max_heat, 4),
                'min_heat': round(min_heat, 4),
                'winner_count': len(winners),
                'loser_count': len(losers),
            },
            'insights': {
                'hottest_chunks': [{'text': c['text'][:100], 'heat': c['heat']} for c in hottest],
                'coldest_chunks': [{'text': c['text'][:100], 'heat': c['heat']} for c in coldest],
            },
            'available_responses': [
                {
                    'trace_id': r['trace_id'],
                    'is_winner': r.get('is_winner', False),
                    'model': r.get('model', '').split('/')[-1] if r.get('model') else 'unknown',
                    'preview': extract_content_text(r.get('content_json', ''))[:80],
                }
                for r in results[:20]
            ],
        })

    except ImportError as e:
        return jsonify({'error': f'Missing dependency: {str(e)}'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def extract_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> dict:
    """
    Extract n-grams from text for pattern analysis.

    Returns dict with:
    - bigrams: 2-word phrases
    - trigrams: 3-word phrases
    - quadgrams: 4-word phrases
    - all_ngrams: combined set for easy lookup

    These are MUCH more useful than large chunks for pattern detection:
    - "step by step" appearing in 85% of winners vs 12% of losers = actionable insight
    - Users can copy/paste winning phrases directly
    - No embedding cost - just string operations
    """
    import re

    if not text:
        return {'bigrams': [], 'trigrams': [], 'quadgrams': [], 'all_ngrams': set()}

    # Tokenize: lowercase, split on whitespace/punctuation, filter short words
    text_lower = text.lower()
    # Keep alphanumeric and basic punctuation that's meaningful
    words = re.findall(r'\b[a-z][a-z0-9]*(?:\'[a-z]+)?\b', text_lower)

    # Filter very short/common words for cleaner patterns
    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                 'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                 'as', 'into', 'through', 'during', 'before', 'after', 'above',
                 'below', 'between', 'under', 'again', 'further', 'then', 'once',
                 'and', 'but', 'or', 'nor', 'so', 'yet', 'both', 'either', 'neither',
                 'not', 'only', 'own', 'same', 'than', 'too', 'very', 'just',
                 'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
                 'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my',
                 'your', 'his', 'our', 'their', 'what', 'which', 'who', 'whom'}

    # For n-grams, we keep all words but filter stopword-only n-grams later

    result = {
        'bigrams': [],
        'trigrams': [],
        'quadgrams': [],
        'all_ngrams': set(),
    }

    # Extract n-grams
    for n in range(min_n, max_n + 1):
        ngrams = []
        for i in range(len(words) - n + 1):
            gram_words = words[i:i+n]
            # Skip if ALL words are stopwords (but allow mixed)
            if all(w in stopwords for w in gram_words):
                continue
            # Skip if any word is too short (likely noise)
            if any(len(w) < 2 for w in gram_words):
                continue
            gram = ' '.join(gram_words)
            ngrams.append(gram)
            result['all_ngrams'].add(gram)

        if n == 2:
            result['bigrams'] = ngrams
        elif n == 3:
            result['trigrams'] = ngrams
        elif n == 4:
            result['quadgrams'] = ngrams

    return result


def compute_ngram_heat(winner_ngrams_list: list, loser_ngrams_list: list,
                       min_occurrences: int = 2) -> list:
    """
    Compute heat scores for n-grams based on winner vs loser frequency.

    Heat = winner_freq - loser_freq
    - High heat (>0): pattern appears more in winners (keep it!)
    - Low heat (<0): pattern appears more in losers (avoid it!)

    Returns list of {ngram, heat, winner_freq, loser_freq, winner_count, loser_count}
    sorted by absolute heat (most distinctive patterns first).
    """
    from collections import Counter

    # Count occurrences in winners and losers
    winner_counts = Counter()
    loser_counts = Counter()

    for ngrams in winner_ngrams_list:
        # Use set to count each prompt once (not multiple times per prompt)
        for gram in set(ngrams):
            winner_counts[gram] += 1

    for ngrams in loser_ngrams_list:
        for gram in set(ngrams):
            loser_counts[gram] += 1

    # Get all unique n-grams
    all_grams = set(winner_counts.keys()) | set(loser_counts.keys())

    n_winners = len(winner_ngrams_list)
    n_losers = len(loser_ngrams_list)

    patterns = []
    for gram in all_grams:
        w_count = winner_counts.get(gram, 0)
        l_count = loser_counts.get(gram, 0)

        # Skip rare patterns
        if w_count + l_count < min_occurrences:
            continue

        winner_freq = w_count / n_winners if n_winners > 0 else 0
        loser_freq = l_count / n_losers if n_losers > 0 else 0
        heat = winner_freq - loser_freq

        patterns.append({
            'ngram': gram,
            'heat': round(heat, 3),
            'winner_freq': round(winner_freq, 3),
            'loser_freq': round(loser_freq, 3),
            'winner_count': w_count,
            'loser_count': l_count,
            'total_count': w_count + l_count,
        })

    # Sort by absolute heat (most distinctive first)
    patterns.sort(key=lambda x: abs(x['heat']), reverse=True)

    return patterns


def chunk_text_smart(text: str, target_size: int = 150) -> list:
    """
    Break text into chunks, preferring sentence boundaries.

    Returns list of {'text': str, 'start': int, 'end': int}
    """
    import re

    if not text:
        return []

    # Split by sentence boundaries
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z])|(?<=\n)\s*(?=\S)'
    sentences = re.split(sentence_pattern, text)

    chunks = []
    current_chunk = ""
    current_start = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If adding this sentence would exceed target, save current chunk
        if current_chunk and len(current_chunk) + len(sentence) > target_size:
            chunks.append({
                'text': current_chunk.strip(),
                'start': current_start,
                'end': current_start + len(current_chunk),
            })
            current_start = current_start + len(current_chunk)
            current_chunk = ""

        current_chunk += (" " if current_chunk else "") + sentence

        # If current chunk is big enough, save it
        if len(current_chunk) >= target_size:
            chunks.append({
                'text': current_chunk.strip(),
                'start': current_start,
                'end': current_start + len(current_chunk),
            })
            current_start = current_start + len(current_chunk)
            current_chunk = ""

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            'text': current_chunk.strip(),
            'start': current_start,
            'end': current_start + len(current_chunk),
        })

    return chunks


@sextant_bp.route('/prompt-heatmap/<cascade_id>/<cell_name>', methods=['GET'])
def prompt_heatmap(cascade_id, cell_name):
    """
    FLIR-style heat vision for INPUT PROMPTS - show which parts of prompts correlate with winning.

    This is the key insight: analyze what CAUSED winning, not the outputs.

    Process:
    1. Get all prompts that led to candidates (from full_request_json in agent rows)
    2. Build prompt-embedding → win/lose mapping
    3. Compute winner/loser prompt centroids
    4. For a sample prompt, chunk and show heat per chunk

    Query params:
    - candidate_index: Specific candidate to analyze (optional, defaults to winner)
    - chunk_size: Approximate chars per chunk (default 150)
    """
    db = get_db()
    target_candidate_idx = request.args.get('candidate_index', type=int)
    chunk_size = request.args.get('chunk_size', 150, type=int)

    try:
        import numpy as np
        import json as json_mod
        from rvbbit.agent import Agent
        from rvbbit.config import get_config

        config = get_config()

        # Step 1: Get all agent rows with prompts for this cell, joined with is_winner from candidate_attempts
        # Agent rows have the prompts but candidate_attempt rows have the is_winner flag
        query = f"""
            SELECT
                a.trace_id,
                a.candidate_index,
                a.full_request_json,
                a.model,
                a.request_embedding,
                s.is_winner AS is_winner
            FROM unified_logs a
            LEFT JOIN (
                SELECT candidate_index, is_winner, session_id
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
            ) s ON a.candidate_index = s.candidate_index AND a.session_id = s.session_id
            WHERE a.cascade_id = '{cascade_id}'
              AND a.cell_name = '{cell_name}'
              AND a.node_type = 'agent'
              AND a.candidate_index IS NOT NULL
              AND a.full_request_json IS NOT NULL
              AND length(a.full_request_json) > 10
            ORDER BY a.timestamp DESC
            LIMIT 200
        """
        results = db.query(query, output_format='dict')

        if len(results) < 3:
            return jsonify({
                'error': f'Not enough candidate prompts (found {len(results)}, need at least 3)',
                'cascade_id': cascade_id,
                'cell_name': cell_name,
            })

        # Extract prompt text from full_request_json
        def extract_prompt(full_request_json):
            if not full_request_json:
                return ""
            try:
                req = json_mod.loads(full_request_json)
                messages = req.get('messages', [])
                # Concatenate all user messages (the prompts)
                prompt_parts = []
                for m in messages:
                    if m.get('role') == 'user':
                        prompt_parts.append(m.get('content', ''))
                    elif m.get('role') == 'system':
                        prompt_parts.append(f"[SYSTEM]: {m.get('content', '')}")
                return '\n\n'.join(prompt_parts)
            except:
                return ""

        # Add extracted prompts to results
        for r in results:
            r['prompt_text'] = extract_prompt(r.get('full_request_json'))

        # Filter to only those with actual prompts
        results = [r for r in results if r['prompt_text']]

        # Separate winners and losers
        winners = [r for r in results if r.get('is_winner')]
        losers = [r for r in results if not r.get('is_winner')]

        if not winners or not losers:
            return jsonify({
                'error': 'Need both winning and losing candidates for comparison',
                'winner_count': len(winners),
                'loser_count': len(losers),
            })

        # Step 2: Embed all prompts if needed (or use request_embedding if available)
        # For now, embed fresh since request_embedding might not be populated
        all_prompts = [r['prompt_text'] for r in results]

        embed_result = Agent.embed(
            texts=all_prompts,
            model=config.default_embed_model,
            session_id=f'sextant_prompt_heatmap_{cascade_id}',
            cascade_id='sextant',
            cell_name='prompt_heatmap',
        )

        prompt_embeddings = np.array(embed_result['embeddings'])

        # Assign embeddings back to results
        for i, r in enumerate(results):
            r['embedding'] = prompt_embeddings[i]

        # Step 3: Compute centroids
        winner_embeddings = np.array([r['embedding'] for r in winners])
        loser_embeddings = np.array([r['embedding'] for r in losers])

        winner_centroid = winner_embeddings.mean(axis=0)
        loser_centroid = loser_embeddings.mean(axis=0)

        # Normalize centroids for cosine similarity
        winner_centroid = winner_centroid / (np.linalg.norm(winner_centroid) + 1e-9)
        loser_centroid = loser_centroid / (np.linalg.norm(loser_centroid) + 1e-9)

        # Step 4: Get target prompt to analyze
        if target_candidate_idx is not None:
            target = next((r for r in results if r['candidate_index'] == target_candidate_idx), None)
            if not target:
                return jsonify({'error': f'Sounding index {target_candidate_idx} not found'})
        else:
            # Default to first winner for interesting visualization
            target = winners[0] if winners else results[0]

        target_prompt = target['prompt_text']
        target_is_winner = target.get('is_winner', False)
        target_model = target.get('model', '').split('/')[-1] if target.get('model') else 'unknown'
        target_candidate_index = target.get('candidate_index')

        # Step 5: Chunk the prompt text
        chunks = chunk_text_smart(target_prompt, chunk_size)

        if not chunks:
            return jsonify({
                'error': 'No prompt content to analyze',
                'candidate_index': target_candidate_index,
            })

        # Step 6: Embed each chunk
        chunk_texts = [c['text'] for c in chunks]

        chunk_embed_result = Agent.embed(
            texts=chunk_texts,
            model=config.default_embed_model,
            session_id=f'sextant_prompt_chunks_{cascade_id}',
            cascade_id='sextant',
            cell_name='prompt_heatmap_chunks',
        )

        chunk_embeddings = np.array(chunk_embed_result['embeddings'])

        # Step 7: Compute heat for each chunk
        heatmap_chunks = []
        for i, chunk in enumerate(chunks):
            emb = chunk_embeddings[i]
            emb_norm = emb / (np.linalg.norm(emb) + 1e-9)

            # Cosine similarity to each centroid
            sim_to_winner = float(np.dot(emb_norm, winner_centroid))
            sim_to_loser = float(np.dot(emb_norm, loser_centroid))

            # Heat: positive = winner-like, negative = loser-like
            heat = sim_to_winner - sim_to_loser

            heatmap_chunks.append({
                'text': chunk['text'],
                'start': chunk['start'],
                'end': chunk['end'],
                'heat': round(heat, 4),
                'sim_to_winner': round(sim_to_winner, 4),
                'sim_to_loser': round(sim_to_loser, 4),
            })

        # Compute overall stats
        heats = [c['heat'] for c in heatmap_chunks]
        avg_heat = sum(heats) / len(heats) if heats else 0
        max_heat = max(heats) if heats else 0
        min_heat = min(heats) if heats else 0

        # Find hottest and coldest chunks
        sorted_by_heat = sorted(heatmap_chunks, key=lambda x: x['heat'], reverse=True)
        hottest = sorted_by_heat[:3] if len(sorted_by_heat) >= 3 else sorted_by_heat
        coldest = sorted_by_heat[-3:] if len(sorted_by_heat) >= 3 else []

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'candidate_index': target_candidate_index,
            'is_winner': target_is_winner,
            'model': target_model,
            'full_prompt': target_prompt,
            'chunks': heatmap_chunks,
            'stats': {
                'chunk_count': len(heatmap_chunks),
                'avg_heat': round(avg_heat, 4),
                'max_heat': round(max_heat, 4),
                'min_heat': round(min_heat, 4),
                'winner_count': len(winners),
                'loser_count': len(losers),
            },
            'insights': {
                'hottest_chunks': [{'text': c['text'][:150], 'heat': c['heat']} for c in hottest],
                'coldest_chunks': [{'text': c['text'][:150], 'heat': c['heat']} for c in coldest],
            },
            'available_prompts': [
                {
                    'candidate_index': r['candidate_index'],
                    'is_winner': r.get('is_winner', False),
                    'model': r.get('model', '').split('/')[-1] if r.get('model') else 'unknown',
                    'preview': r['prompt_text'][:80],
                }
                for r in results[:20]
            ],
        })

    except ImportError as e:
        return jsonify({'error': f'Missing dependency: {str(e)}'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/prompt-patterns/<cascade_id>/<cell_name>', methods=['GET'])
def prompt_patterns(cascade_id, cell_name):
    """
    Cross-prompt pattern analysis - the CORE of prompt optimization.

    Shows what text patterns appear across multiple winning prompts vs losing prompts.
    This is NOT about comparing to a centroid - it's about cross-prompt frequency.

    Heat = "How often does this chunk appear in OTHER winners vs losers?"
    - High heat: This pattern appears in many winners, few losers (keep it!)
    - Low heat: This pattern appears in many losers, few winners (avoid it!)

    Query params:
    - threshold: Similarity threshold for chunk matching (default 0.75)
    - chunk_size: Characters per chunk (default 120)
    - max_winners: Max winning prompts to include (default 10)
    - max_losers: Max losing prompts to include (default 10)
    - species_hash: Filter to specific species (prompt template DNA)

    Returns:
    - All winning prompts with per-chunk heat scores
    - Sample losing prompts for comparison
    - Global hot/cold patterns across all prompts
    - species_info: Species metadata and warnings
    """
    db = get_db()
    similarity_threshold = request.args.get('threshold', 0.75, type=float)
    chunk_size = request.args.get('chunk_size', 120, type=int)
    max_winners = request.args.get('max_winners', 10, type=int)
    max_losers = request.args.get('max_losers', 10, type=int)
    species_filter = request.args.get('species_hash', None)

    try:
        import numpy as np
        import json as json_mod
        from rvbbit.agent import Agent
        from rvbbit.config import get_config

        config = get_config()

        # Build species filter clause
        species_clause = f"AND species_hash = '{species_filter}'" if species_filter else ""

        # Step 1: Get all prompts (from agent rows joined with candidate_attempt for is_winner)
        # Use INNER JOIN to ensure species filtering is respected
        query = f"""
            SELECT
                a.trace_id,
                a.candidate_index,
                a.session_id,
                a.full_request_json,
                a.model,
                a.cost,
                s.is_winner AS is_winner,
                s.species_hash AS species_hash
            FROM unified_logs a
            INNER JOIN (
                SELECT candidate_index, is_winner, session_id, species_hash
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND node_type = 'candidate_attempt'
                  {species_clause}
            ) s ON a.candidate_index = s.candidate_index AND a.session_id = s.session_id
            WHERE a.cascade_id = '{cascade_id}'
              AND a.cell_name = '{cell_name}'
              AND a.node_type = 'agent'
              AND a.candidate_index IS NOT NULL
              AND a.full_request_json IS NOT NULL
              AND length(a.full_request_json) > 10
            ORDER BY a.timestamp DESC
            LIMIT 200
        """
        results = db.query(query, output_format='dict')

        if len(results) < 3:
            return jsonify({
                'error': f'Not enough prompts (found {len(results)}, need at least 3)',
                'cascade_id': cascade_id,
                'cell_name': cell_name,
            })

        # Extract prompt text from full_request_json
        def extract_prompt(full_request_json):
            if not full_request_json:
                return ""
            try:
                req = json_mod.loads(full_request_json)
                messages = req.get('messages', [])
                prompt_parts = []
                for m in messages:
                    if m.get('role') == 'user':
                        prompt_parts.append(m.get('content', ''))
                    elif m.get('role') == 'system':
                        prompt_parts.append(f"[SYSTEM]: {m.get('content', '')}")
                return '\n\n'.join(prompt_parts)
            except:
                return ""

        # Add extracted prompts
        for r in results:
            r['prompt_text'] = extract_prompt(r.get('full_request_json'))

        # Filter to those with actual prompts and known is_winner status
        results = [r for r in results if r['prompt_text'] and r.get('is_winner') is not None]

        # Separate winners and losers
        all_winners = [r for r in results if r.get('is_winner') == True]
        all_losers = [r for r in results if r.get('is_winner') == False]

        if not all_winners or not all_losers:
            return jsonify({
                'error': 'Need both winning and losing prompts for comparison',
                'winner_count': len(all_winners),
                'loser_count': len(all_losers),
            })

        # Limit for analysis
        winners = all_winners[:max_winners]
        losers = all_losers[:max_losers]
        all_prompts = winners + losers

        # Step 2: Chunk all prompts
        all_chunks = []  # [{prompt_idx, chunk_idx, text, is_winner}, ...]

        for prompt in all_prompts:
            chunks = chunk_text_smart(prompt['prompt_text'], chunk_size)
            prompt['chunks'] = chunks
            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    'prompt_idx': prompt['candidate_index'],
                    'chunk_idx': i,
                    'text': chunk['text'],
                    'start': chunk['start'],
                    'end': chunk['end'],
                    'is_winner': prompt['is_winner'],
                })

        if not all_chunks:
            return jsonify({'error': 'No text chunks found in prompts'})

        # Step 3: Embed all chunks in one batch
        chunk_texts = [c['text'] for c in all_chunks]

        embed_result = Agent.embed(
            texts=chunk_texts,
            model=config.default_embed_model,
            session_id=f'sextant_patterns_{cascade_id}',
            cascade_id='sextant',
            cell_name='prompt_patterns',
        )

        embeddings = np.array(embed_result['embeddings'])

        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / (norms + 1e-9)

        # Step 4: Compute similarity matrix (all pairs)
        similarity_matrix = normalized @ normalized.T

        # Step 5: For each chunk, compute cross-prompt heat
        winner_count = len(winners)
        loser_count = len(losers)

        # Build prompt_idx -> list of chunk indices mapping
        prompt_to_chunks = {}
        for i, c in enumerate(all_chunks):
            if c['prompt_idx'] not in prompt_to_chunks:
                prompt_to_chunks[c['prompt_idx']] = []
            prompt_to_chunks[c['prompt_idx']].append(i)

        # For each chunk, find similar chunks in OTHER prompts
        for i, chunk in enumerate(all_chunks):
            similarities = similarity_matrix[i]
            similar_prompts_winner = set()
            similar_prompts_loser = set()

            for j, sim in enumerate(similarities):
                if i == j:
                    continue  # Skip self
                other_chunk = all_chunks[j]
                if other_chunk['prompt_idx'] == chunk['prompt_idx']:
                    continue  # Skip same prompt

                if sim >= similarity_threshold:
                    if other_chunk['is_winner']:
                        similar_prompts_winner.add(other_chunk['prompt_idx'])
                    else:
                        similar_prompts_loser.add(other_chunk['prompt_idx'])

            # Compute frequencies (excluding self for same-type)
            if chunk['is_winner']:
                other_winner_count = winner_count - 1
            else:
                other_winner_count = winner_count

            chunk['similar_in_winners'] = len(similar_prompts_winner)
            chunk['similar_in_losers'] = len(similar_prompts_loser)
            chunk['winner_freq'] = len(similar_prompts_winner) / other_winner_count if other_winner_count > 0 else 0
            chunk['loser_freq'] = len(similar_prompts_loser) / loser_count if loser_count > 0 else 0
            chunk['heat'] = chunk['winner_freq'] - chunk['loser_freq']

        # Step 6: Build response with prompts and their chunks
        def format_prompt_with_chunks(prompt, all_chunks):
            prompt_chunks = [c for c in all_chunks if c['prompt_idx'] == prompt['candidate_index']]
            return {
                'candidate_index': prompt['candidate_index'],
                'session_id': prompt['session_id'],
                'model': prompt.get('model', '').split('/')[-1] if prompt.get('model') else 'unknown',
                'full_prompt': prompt['prompt_text'],
                'is_winner': prompt['is_winner'],
                'cost': float(prompt.get('cost') or 0),
                'chunks': [
                    {
                        'text': c['text'],
                        'start': c['start'],
                        'end': c['end'],
                        'heat': round(c['heat'], 3),
                        'winner_freq': round(c['winner_freq'], 3),
                        'loser_freq': round(c['loser_freq'], 3),
                        'similar_in_winners': c['similar_in_winners'],
                        'similar_in_losers': c['similar_in_losers'],
                    }
                    for c in prompt_chunks
                ],
            }

        winning_prompts = [format_prompt_with_chunks(p, all_chunks) for p in winners]
        losing_prompts = [format_prompt_with_chunks(p, all_chunks) for p in losers[:5]]  # Show fewer losers

        # Step 6b: Compute cost analysis
        winner_costs = [float(p.get('cost') or 0) for p in all_winners]
        loser_costs = [float(p.get('cost') or 0) for p in all_losers]

        avg_winner_cost = sum(winner_costs) / len(winner_costs) if winner_costs else 0
        avg_loser_cost = sum(loser_costs) / len(loser_costs) if loser_costs else 0
        total_winner_cost = sum(winner_costs)
        total_loser_cost = sum(loser_costs)

        # Cost premium: how much more do winners cost vs losers (as percentage)
        cost_premium_pct = ((avg_winner_cost - avg_loser_cost) / avg_loser_cost * 100) if avg_loser_cost > 0 else 0

        # Cost efficiency: cost per outcome
        win_rate = len(all_winners) / (len(all_winners) + len(all_losers)) if (all_winners or all_losers) else 0

        cost_analysis = {
            'avg_winner_cost': round(avg_winner_cost, 6),
            'avg_loser_cost': round(avg_loser_cost, 6),
            'total_winner_cost': round(total_winner_cost, 6),
            'total_loser_cost': round(total_loser_cost, 6),
            'cost_premium_pct': round(cost_premium_pct, 1),
            'winner_count': len(all_winners),
            'loser_count': len(all_losers),
            'win_rate_pct': round(win_rate * 100, 1),
            'min_winner_cost': round(min(winner_costs), 6) if winner_costs else 0,
            'max_winner_cost': round(max(winner_costs), 6) if winner_costs else 0,
            'min_loser_cost': round(min(loser_costs), 6) if loser_costs else 0,
            'max_loser_cost': round(max(loser_costs), 6) if loser_costs else 0,
        }

        # Step 7: Find global hot/cold patterns
        # Group chunks by text similarity and compute aggregate stats
        chunk_patterns = {}
        for c in all_chunks:
            # Use first 50 chars as pattern key (simplified)
            pattern_key = c['text'][:50].lower().strip()
            if pattern_key not in chunk_patterns:
                chunk_patterns[pattern_key] = {
                    'text': c['text'][:100],
                    'winner_appearances': 0,
                    'loser_appearances': 0,
                    'total_heat': 0,
                    'count': 0,
                }
            chunk_patterns[pattern_key]['count'] += 1
            chunk_patterns[pattern_key]['total_heat'] += c['heat']
            if c['is_winner']:
                chunk_patterns[pattern_key]['winner_appearances'] += 1
            else:
                chunk_patterns[pattern_key]['loser_appearances'] += 1

        # Sort patterns by average heat
        sorted_patterns = sorted(
            chunk_patterns.values(),
            key=lambda x: x['total_heat'] / x['count'] if x['count'] > 0 else 0,
            reverse=True
        )

        hot_patterns = [
            {
                'text': p['text'],
                'avg_heat': round(p['total_heat'] / p['count'], 3) if p['count'] > 0 else 0,
                'winner_appearances': p['winner_appearances'],
                'loser_appearances': p['loser_appearances'],
            }
            for p in sorted_patterns[:5]
            if p['count'] > 0 and (p['total_heat'] / p['count']) > 0.1
        ]

        cold_patterns = [
            {
                'text': p['text'],
                'avg_heat': round(p['total_heat'] / p['count'], 3) if p['count'] > 0 else 0,
                'winner_appearances': p['winner_appearances'],
                'loser_appearances': p['loser_appearances'],
            }
            for p in sorted_patterns[-5:]
            if p['count'] > 0 and (p['total_heat'] / p['count']) < -0.1
        ]

        # Step 8: N-gram analysis (FAST, interpretable phrase patterns)
        # This is much better than embedding-based chunks for actionable insights
        winner_ngrams_list = []
        loser_ngrams_list = []

        for prompt in all_winners:
            ngrams = extract_ngrams(prompt['prompt_text'])
            winner_ngrams_list.append(ngrams['all_ngrams'])

        for prompt in all_losers:
            ngrams = extract_ngrams(prompt['prompt_text'])
            loser_ngrams_list.append(ngrams['all_ngrams'])

        # Compute n-gram heat (winner_freq - loser_freq)
        ngram_patterns = compute_ngram_heat(winner_ngrams_list, loser_ngrams_list, min_occurrences=2)

        # Split into hot (winner-correlated) and cold (loser-correlated)
        hot_ngrams = [p for p in ngram_patterns if p['heat'] > 0][:15]
        cold_ngrams = [p for p in ngram_patterns if p['heat'] < 0][:15]

        # Collect species info from results
        all_species = set()
        for row in results:
            if row.get('species_hash'):
                all_species.add(row['species_hash'])

        species_info = {
            'species_hash': species_filter,  # Active filter (or None)
            'detected_species': list(all_species),
            'species_count': len(all_species),
            'warning': None
        }
        if len(all_species) > 1 and not species_filter:
            species_info['warning'] = f"Data contains {len(all_species)} different species (prompt templates). Comparing prompts from different templates may give misleading results. Use ?species_hash=X to filter."

        return jsonify({
            'cascade_id': cascade_id,
            'cell_name': cell_name,
            'winning_prompts': winning_prompts,
            'losing_prompts': losing_prompts,
            'global_hot_patterns': hot_patterns,
            'global_cold_patterns': cold_patterns,
            # NEW: N-gram based patterns (fast, interpretable)
            'hot_ngrams': hot_ngrams,
            'cold_ngrams': cold_ngrams,
            'cost_analysis': cost_analysis,
            'species_info': species_info,
            'stats': {
                'total_winners': len(all_winners),
                'total_losers': len(all_losers),
                'analyzed_winners': len(winners),
                'analyzed_losers': len(losers),
                'total_chunks': len(all_chunks),
                'similarity_threshold': similarity_threshold,
            },
        })

    except ImportError as e:
        return jsonify({'error': f'Missing dependency: {str(e)}'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sextant_bp.route('/embedding-search', methods=['POST'])
def embedding_search():
    """
    Find similar messages using embedding cosine similarity.

    Body: {
        query: string (text to embed and search for)
        limit: int (default 10)
        role: string (optional filter: 'assistant', 'user')
    }
    """
    from rvbbit.agent import Agent

    data = request.json or {}
    query_text = data.get('query', '')
    limit = data.get('limit', 10)
    role_filter = data.get('role')

    if not query_text:
        return jsonify({'error': 'Query text required'}), 400

    db = get_db()
    config = get_config()

    try:
        # Embed the query
        result = Agent.embed(
            texts=[query_text],
            model=config.default_embed_model,
            session_id='sextant_search',
            cascade_id='sextant_similarity_search',
        )

        query_vector = result['embeddings'][0]

        # Format vector for ClickHouse
        vector_str = '[' + ', '.join(str(x) for x in query_vector) + ']'

        # Search for similar content
        role_clause = f"AND role = '{role_filter}'" if role_filter else ""

        search_query = f"""
            SELECT
                trace_id,
                session_id,
                cascade_id,
                cell_name,
                role,
                content_json,
                cosineDistance(content_embedding, {vector_str}) as distance
            FROM unified_logs
            WHERE length(content_embedding) > 0
              {role_clause}
            ORDER BY distance ASC
            LIMIT {limit}
        """

        results = db.query(search_query, output_format='dict')

        similar = []
        for row in results:
            content = row.get('content_json', '')
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except:
                    pass

            similar.append({
                'trace_id': row['trace_id'],
                'session_id': row['session_id'],
                'cascade_id': row['cascade_id'],
                'cell_name': row['cell_name'],
                'role': row['role'],
                'content_preview': str(content)[:500] if content else '',
                'similarity': 1 - float(row['distance']),  # Convert distance to similarity
            })

        return jsonify({
            'query': query_text[:200],
            'results': similar,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# Helper functions

def find_cascade_file(cascade_id: str, config) -> str:
    """Find the cascade file path from a cascade_id."""
    # Check common locations
    search_paths = [
        config.examples_dir,
        config.cascades_dir,
        config.traits_dir,
    ]

    for search_dir in search_paths:
        # Try direct match
        direct = Path(search_dir) / f"{cascade_id}.json"
        if direct.exists():
            return str(direct)

        # Try searching subdirectories
        for path in Path(search_dir).rglob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                    if data.get('cascade_id') == cascade_id:
                        return str(path)
            except:
                continue

    return None


def extract_patterns(content_samples: list) -> list:
    """Extract common patterns from winning responses."""
    patterns = []

    if not content_samples:
        return patterns

    all_content = "\n\n".join(str(s) for s in content_samples if s)
    all_lower = all_content.lower()

    # Check for common patterns
    if "step by step" in all_lower or "step-by-step" in all_lower:
        patterns.append("Uses step-by-step reasoning")

    if "first" in all_lower and "then" in all_lower:
        patterns.append("Follows sequential approach")

    if any(word in all_lower for word in ["explore", "understand", "analyze"]):
        patterns.append("Starts with exploration")

    if any(word in all_lower for word in ["```", "code", "function"]):
        patterns.append("Includes code examples")

    if any(word in all_lower for word in ["however", "but", "although"]):
        patterns.append("Considers alternatives")

    # Length analysis
    if content_samples:
        avg_length = sum(len(str(c)) for c in content_samples) / len(content_samples)
        if avg_length < 500:
            patterns.append("Concise responses (< 500 chars)")
        elif avg_length > 2000:
            patterns.append("Detailed responses (> 2000 chars)")

    return patterns if patterns else ["No clear patterns detected"]

@sextant_bp.route('/evolution/<session_id>', methods=['GET'])
def get_prompt_evolution(session_id):
    """
    Get prompt evolution (phylogeny) for the species of the given session.

    Returns React Flow compatible graph showing how prompts evolved across
    multiple runs of the same species (cell configuration).

    Query params:
    - as_of: timestamp | 'current' (default: session timestamp - show tree as it was at that time)
    - include_future: bool (default: false - whether to show runs after this session)
    - cell_name: string (optional - filter to specific cell)

    Returns:
    {
        "nodes": [list of React Flow nodes],
        "edges": [list of React Flow edges],
        "metadata": {
            "cascade_id": str,
            "cell_name": str,
            "species_hash": str,
            "session_count": int,
            "as_of_timestamp": str,
            "current_session_generation": int
        }
    }
    """
    db = get_db()

    try:
        # Parse query params
        as_of = request.args.get('as_of', 'session')  # 'session', 'latest', or ISO timestamp
        include_future = request.args.get('include_future', 'false').lower() == 'true'
        cell_filter = request.args.get('cell_name')

        # 1. Get metadata for the current session (cascade_id, cell_name, species_hash, timestamp)
        # IMPORTANT: Pick the cell with the MOST candidate data (most candidates)
        # This ensures we show the most interesting evolution, not a random cell
        session_query = f"""
            SELECT
                cascade_id,
                cell_name,
                species_hash,
                MAX(timestamp) as timestamp,
                COUNT(DISTINCT candidate_index) as candidate_count
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND species_hash IS NOT NULL
              AND species_hash != ''
              AND cell_name IS NOT NULL
              AND candidate_index IS NOT NULL
              AND node_type = 'candidate_attempt'
            GROUP BY cascade_id, cell_name, species_hash
            ORDER BY candidate_count DESC
            LIMIT 1
        """

        session_info = db.query(session_query, output_format='dict')
        if not session_info:
            return jsonify({'error': 'Session not found or has no species_hash'}), 404

        session_info = session_info[0]
        cascade_id = session_info['cascade_id']
        cell_name = session_info['cell_name'] if not cell_filter else cell_filter
        species_hash = session_info['species_hash']
        session_timestamp = session_info['timestamp']

        # 2. Determine time filter
        if as_of == 'session':
            time_filter = f"AND timestamp <= '{session_timestamp}'"
        elif as_of == 'latest':
            time_filter = ""
        else:
            # User provided specific timestamp
            time_filter = f"AND timestamp <= '{as_of}'"

        # Optional: also get future runs (grayed out in UI)
        future_filter = ""
        if not include_future and as_of == 'session':
            # Don't include future runs
            pass
        elif as_of == 'session':
            # Include future but mark them
            future_filter = f", (timestamp > '{session_timestamp}') as is_future"

        # 3. Query all candidates for this species
        # NOTE: Cost is on agent rows, not candidate_attempt rows
        # For baseline candidates (mutation_applied IS NULL), get the actual prompt from user messages
        evolution_query = f"""
            SELECT
                sa.session_id as session_id,
                sa.candidate_index as candidate_index,
                sa.mutation_applied as mutation_applied,
                sa.mutation_type as mutation_type,
                sa.mutation_template as mutation_template,
                sa.is_winner as is_winner,
                sa.timestamp as timestamp,
                sa.model as model,
                SUM(CASE WHEN agent.role = 'assistant' THEN agent.cost ELSE 0 END) as cost,
                any(user_msg.content_json) as baseline_prompt_json
                {future_filter.replace('timestamp', 'sa.timestamp') if future_filter else ''}
            FROM unified_logs sa
            LEFT JOIN unified_logs agent ON
                agent.session_id = sa.session_id
                AND agent.candidate_index = sa.candidate_index
                AND agent.role = 'assistant'
            LEFT JOIN unified_logs user_msg ON
                user_msg.session_id = sa.session_id
                AND user_msg.candidate_index = sa.candidate_index
                AND user_msg.role = 'user'
                AND user_msg.node_type = 'user'
            WHERE sa.cascade_id = '{cascade_id}'
              AND sa.cell_name = '{cell_name}'
              AND sa.species_hash = '{species_hash}'
              AND sa.candidate_index IS NOT NULL
              AND sa.node_type = 'candidate_attempt'
              {time_filter.replace('timestamp', 'sa.timestamp') if time_filter else ''}
            GROUP BY sa.session_id, sa.candidate_index, sa.mutation_applied,
                     sa.mutation_type, sa.mutation_template, sa.is_winner,
                     sa.timestamp, sa.model
            ORDER BY sa.timestamp ASC, sa.candidate_index ASC
        """

        results = db.query(evolution_query, output_format='dict')

        if not results:
            return jsonify({
                'nodes': [],
                'edges': [],
                'metadata': {
                    'cascade_id': cascade_id,
                    'cell_name': cell_name,
                    'species_hash': species_hash,
                    'session_count': 0,
                    'as_of_timestamp': str(session_timestamp),
                    'message': 'No evolution data found'
                }
            })

        # 4. Group by sessions (generations)
        generations = {}
        for row in results:
            sess_id = row['session_id']
            if sess_id not in generations:
                generations[sess_id] = {
                    'session_id': sess_id,
                    'timestamp': row['timestamp'],
                    'candidates': [],
                    'is_future': row.get('is_future', False) if 'is_future' in row else False
                }

            # For baseline candidates (mutation_applied is NULL), use the actual baseline prompt
            # Otherwise use the mutated prompt (mutation_applied)
            if row['mutation_applied']:
                prompt_text = row['mutation_applied']
            elif row.get('baseline_prompt_json'):
                # Extract text from content_json
                prompt_text = extract_content_text(row['baseline_prompt_json'])
            else:
                prompt_text = '[Baseline - No prompt data available]'

            generations[sess_id]['candidates'].append({
                'candidate_index': row['candidate_index'],
                'prompt': prompt_text,
                'type': row['mutation_type'],
                'template': row['mutation_template'],
                'is_winner': row['is_winner'],
                'model': row['model'],
                'cost': float(row['cost']) if row.get('cost') else 0
            })

        # Sort generations by timestamp
        gen_list = sorted(generations.values(), key=lambda x: x['timestamp'])

        # 5. Find which generation the current session belongs to
        current_gen_index = next((i for i, g in enumerate(gen_list) if g['session_id'] == session_id), -1)

        # 6. Build React Flow nodes and edges
        nodes = []
        edges = []

        # Track all winners across generations (gene pool)
        gene_pool = []  # List of (gen_idx, session_id, candidate)

        for gen_idx, generation in enumerate(gen_list):
            is_current_session = generation['session_id'] == session_id
            is_future = generation.get('is_future', False)

            # Horizontal position (x) based on generation
            # Increased from 450 to 700 for better spacing with edge labels
            x = gen_idx * 700

            # Get winner(s) from this generation for connections
            winners = [s for s in generation['candidates'] if s['is_winner']]

            # Get immediate parents (previous generation winners)
            immediate_parents = []
            if gen_idx > 0:
                prev_generation = gen_list[gen_idx - 1]
                immediate_parents = [(gen_idx - 1, prev_generation['session_id'], s)
                                    for s in prev_generation['candidates'] if s['is_winner']]

            for sound_idx, candidate in enumerate(generation['candidates']):
                # Vertical position (y) based on candidate index within generation
                # Increased from 180 to 250 to accommodate taller nodes
                y = sound_idx * 250

                node_id = f"{generation['session_id']}_{candidate['candidate_index']}"

                # Build parent winners list for DNA inheritance bar
                # IMPORTANT: Only use the last N winners (active training set), not entire gene pool
                winner_limit = int(os.environ.get("RVBBIT_WINNER_HISTORY_LIMIT", "5"))
                active_gene_pool = gene_pool[-winner_limit:] if len(gene_pool) > winner_limit else gene_pool

                parent_winners = []
                for parent_gen_idx, parent_session_id, parent_candidate in active_gene_pool:
                    parent_winners.append({
                        'generation': parent_gen_idx + 1,
                        'session_id': parent_session_id,
                        'candidate_index': parent_candidate['candidate_index'],
                        'prompt_snippet': (parent_candidate['prompt'] or '')[:100]  # Increased from 30 to 100 chars
                    })

                nodes.append({
                    'id': node_id,
                    'type': 'promptNode',
                    'position': {'x': x, 'y': y},
                    'data': {
                        'generation': gen_idx + 1,
                        'candidate_index': candidate['candidate_index'],
                        'prompt': candidate['prompt'],
                        'mutation_type': candidate['type'],
                        'mutation_template': candidate['template'],
                        'is_winner': candidate['is_winner'],
                        'model': candidate['model'],
                        'cost': candidate.get('cost', 0),
                        'is_current_session': is_current_session,
                        'is_future': is_future,
                        'session_id': generation['session_id'],
                        'timestamp': str(generation['timestamp']),
                        'parent_winners': parent_winners,  # For DNA bar
                        'gene_pool_size': len(gene_pool)   # Show gene pool growth
                    }
                })

                # GENETIC LINEAGE EDGES: Connect to ALL previous winners (gene pool)
                if gen_idx > 0:
                    for parent_gen_idx, parent_session_id, parent_candidate in gene_pool:
                        source_id = f"{parent_session_id}_{parent_candidate['candidate_index']}"

                        # Check if this is an immediate parent (last generation)
                        is_immediate_parent = parent_gen_idx == gen_idx - 1

                        edge_data = {
                            'id': f"{source_id}->{node_id}",
                            'source': source_id,
                            'target': node_id,
                            'type': 'default',  # Bezier curves
                            'data': {
                                'is_immediate_parent': is_immediate_parent,
                                'parent_generation': parent_gen_idx + 1
                            }
                        }

                        if is_immediate_parent:
                            # Immediate parents: Thicker, no labels, prominent
                            edge_data.update({
                                'animated': candidate['is_winner'],
                                'style': {
                                    'stroke': '#22c55e' if candidate['is_winner'] else '#9ca3af',
                                    'strokeWidth': 4 if candidate['is_winner'] else 2.5,
                                    'opacity': 0.3 if is_future else 0.9
                                },
                                'className': 'immediate-parent-edge'
                            })
                        else:
                            # Gene pool ancestors: Visible but distinct from immediate parents
                            # Color by "age" - how many generations back
                            generations_back = gen_idx - parent_gen_idx

                            # Fade color based on age (older = more faded)
                            base_opacity = 0.5 if generations_back == 1 else (0.35 if generations_back == 2 else 0.25)

                            # Use purple/blue tint for gene pool (vs green for immediate)
                            gene_pool_color = '#8b5cf6'  # Purple for gene pool ancestry

                            edge_data.update({
                                'style': {
                                    'stroke': gene_pool_color,
                                    'strokeWidth': 2,  # Increased from 1 to 2
                                    'opacity': base_opacity if not is_future else 0.08
                                },
                                'className': 'gene-pool-edge',
                                'data': {
                                    'generations_back': generations_back
                                }
                            })

                        edges.append(edge_data)

            # Add this generation's winners to gene pool for next generation
            for winner in winners:
                gene_pool.append((gen_idx, generation['session_id'], winner))

        # 7. Mark the "active training set" (last 5 winners by timestamp)
        # This shows which winners would be used for training the NEXT generation
        winner_limit = int(os.environ.get("RVBBIT_WINNER_HISTORY_LIMIT", "5"))

        # Collect all winner nodes with their timestamps
        winner_nodes = []
        for node in nodes:
            if node['data']['is_winner'] and not node['data']['is_future']:
                winner_nodes.append({
                    'node': node,
                    'timestamp': node['data']['timestamp']
                })

        # Sort by timestamp DESC (most recent first) and take the limit
        winner_nodes.sort(key=lambda x: x['timestamp'], reverse=True)
        active_training_set = set(n['node']['id'] for n in winner_nodes[:winner_limit])

        # Mark nodes that are in the active training set
        for node in nodes:
            node['data']['in_training_set'] = node['id'] in active_training_set

        # 8. Return response
        return jsonify({
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'species_hash': species_hash,
                'session_count': len(gen_list),
                'as_of_timestamp': str(session_timestamp),
                'current_session_generation': current_gen_index + 1 if current_gen_index >= 0 else None,
                'total_candidates': len(nodes),
                'winner_count': sum(1 for n in nodes if n['data']['is_winner'])
            }
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@sextant_bp.route('/species/<session_id>', methods=['GET'])
def get_species_info(session_id):
    """
    Get species hash and related sessions for a given session.

    Returns:
    - species_hash: The species hash for this session's cells
    - related_sessions: List of other sessions with the same species
    - evolution_depth: How many generations of this species exist
    """
    db = get_db()

    try:
        # First, get the species hash(es) for this session
        species_query = f"""
            SELECT DISTINCT
                cascade_id,
                cell_name,
                species_hash
            FROM unified_logs
            WHERE session_id = '{session_id}'
            AND species_hash IS NOT NULL
            AND cell_name IS NOT NULL
        """

        species_rows = db.query(species_query, output_format='dict')

        if not species_rows:
            return jsonify({
                'error': 'No species hash found for this session',
                'session_id': session_id
            }), 404

        # Group by cell (sessions can have multiple cells with different species)
        cells_info = []

        for row in species_rows:
            cascade_id = row['cascade_id']
            cell_name = row['cell_name']
            species_hash = row['species_hash']

            # Find all related sessions with this species hash
            related_query = f"""
                SELECT
                    session_id,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen,
                    COUNT(DISTINCT candidate_index) as candidate_count,
                    SUM(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as winner_count,
                    SUM(CASE WHEN role = 'assistant' THEN cost ELSE 0 END) as total_cost
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                AND cell_name = '{cell_name}'
                AND species_hash = '{species_hash}'
                AND candidate_index IS NOT NULL
                GROUP BY session_id
                ORDER BY MIN(timestamp) ASC
            """

            related_rows = db.query(related_query, output_format='dict')

            related_sessions = []
            current_session_index = -1

            for idx, rel_row in enumerate(related_rows):
                rel_session_id = rel_row['session_id']
                first_seen = rel_row['first_seen']
                last_seen = rel_row['last_seen']
                candidate_count = rel_row['candidate_count']
                winner_count = rel_row['winner_count']
                total_cost = rel_row['total_cost'] or 0.0

                if rel_session_id == session_id:
                    current_session_index = idx

                related_sessions.append({
                    'session_id': rel_session_id,
                    'generation': idx + 1,  # 1-indexed generation number
                    'is_current': rel_session_id == session_id,
                    'first_seen': str(first_seen),
                    'last_seen': str(last_seen),
                    'candidate_count': candidate_count,
                    'winner_count': winner_count,
                    'total_cost': float(total_cost)
                })

            cells_info.append({
                'cascade_id': cascade_id,
                'cell_name': cell_name,
                'species_hash': species_hash,
                'evolution_depth': len(related_sessions),
                'current_generation': current_session_index + 1 if current_session_index >= 0 else None,
                'related_sessions': related_sessions
            })

        return jsonify({
            'session_id': session_id,
            'cells': cells_info
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@sextant_bp.route('/evolve-species', methods=['POST'])
def evolve_species():
    """
    Evolve a species by promoting a winning prompt to the baseline.
    
    Updates the cascade YAML file with the new instructions and logs
    promotion metadata for lineage tracking.
    
    Request body:
    {
        "cascade_id": str,
        "cell_name": str,
        "new_instructions": str,
        "promoted_from": {
            "session_id": str,
            "generation": int,
            "candidate_index": int,
            "old_species_hash": str
        }
    }
    
    Returns:
    {
        "success": bool,
        "cascade_file": str,
        "new_species_hash": str,
        "message": str
    }
    """
    import yaml
    from pathlib import Path
    from datetime import datetime
    import hashlib
    
    try:
        data = request.get_json()
        cascade_id = data.get('cascade_id')
        cell_name = data.get('cell_name')
        new_instructions = data.get('new_instructions')
        promoted_from = data.get('promoted_from', {})
        
        if not all([cascade_id, cell_name, new_instructions]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        config = get_config()

        # Find cascade file - search directories and match by cascade_id in file content
        search_dirs = [
            Path(config.cascades_dir),
            Path(config.examples_dir),
            Path(config.traits_dir),
        ]

        cascade_file = None

        # First try exact filename match
        for search_dir in search_dirs:
            for ext in ['.yaml', '.json']:
                exact_path = search_dir / f"{cascade_id}{ext}"
                if exact_path.exists():
                    cascade_file = exact_path
                    break
            if cascade_file:
                break

        # If not found, search all files and match by cascade_id in content
        if not cascade_file:
            for search_dir in search_dirs:
                if not search_dir.exists():
                    continue

                for file_path in search_dir.glob('*.yaml'):
                    try:
                        with open(file_path, 'r') as f:
                            content = yaml.safe_load(f)
                            if content and content.get('cascade_id') == cascade_id:
                                cascade_file = file_path
                                break
                    except:
                        continue

                if cascade_file:
                    break

                # Also check JSON files
                for file_path in search_dir.glob('*.json'):
                    try:
                        with open(file_path, 'r') as f:
                            content = json.load(f)
                            if content and content.get('cascade_id') == cascade_id:
                                cascade_file = file_path
                                break
                    except:
                        continue

                if cascade_file:
                    break

        if not cascade_file:
            return jsonify({
                'error': f'Cascade file not found for: {cascade_id}',
                'searched_dirs': [str(d) for d in search_dirs]
            }), 404
        
        # Load cascade definition
        with open(cascade_file, 'r') as f:
            if cascade_file.suffix == '.json':
                cascade_def = json.load(f)
            else:
                cascade_def = yaml.safe_load(f)
        
        # Find the cell to update
        cells = cascade_def.get('cells', [])
        cell_found = False
        
        for cell in cells:
            if cell.get('name') == cell_name:
                # Update instructions
                cell['instructions'] = new_instructions
                
                # Add promotion metadata
                if 'metadata' not in cell:
                    cell['metadata'] = {}
                
                cell['metadata']['evolved_from'] = {
                    'previous_species_hash': promoted_from.get('old_species_hash'),
                    'promoted_from_session': promoted_from.get('session_id'),
                    'promoted_from_generation': promoted_from.get('generation'),
                    'promoted_from_candidate': promoted_from.get('candidate_index'),
                    'promoted_at': datetime.utcnow().isoformat(),
                }
                
                cell_found = True
                break
        
        if not cell_found:
            return jsonify({'error': f'Cell not found: {cell_name}'}), 404
        
        # Calculate new species hash
        cell_str = json.dumps(cells[0], sort_keys=True)  # Simplified hash
        new_species_hash = hashlib.md5(cell_str.encode()).hexdigest()[:16]
        
        # Save updated cascade
        with open(cascade_file, 'w') as f:
            if cascade_file.suffix == '.json':
                json.dump(cascade_def, f, indent=2)
            else:
                yaml.dump(cascade_def, f, default_flow_style=False, sort_keys=False)
        
        return jsonify({
            'success': True,
            'cascade_file': str(cascade_file),
            'new_species_hash': new_species_hash,
            'message': f'Species evolved! New baseline set from Gen {promoted_from.get("generation")}'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
