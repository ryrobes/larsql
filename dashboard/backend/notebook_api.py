"""
Notebook API - Endpoints for the Data Cascade Notebook feature

Provides REST API for:
- Listing available notebooks (data cascades)
- Loading/saving notebooks
- Running notebooks and individual cells
"""
import os
import sys
import json
import uuid
import yaml
import math
import tempfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add windlass to path for imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../.."))
_WINDLASS_DIR = os.path.join(_REPO_ROOT, "windlass")
if _WINDLASS_DIR not in sys.path:
    sys.path.insert(0, _WINDLASS_DIR)

try:
    from windlass import run_cascade
    from windlass.config import get_config
    from windlass.eddies.data_tools import sql_data, python_data
    from windlass.sql_tools.session_db import get_session_db, cleanup_session_db
    from windlass.agent import Agent
    from windlass.unified_logs import log_unified
except ImportError as e:
    print(f"Warning: Could not import windlass modules: {e}")
    run_cascade = None
    get_config = None
    sql_data = None
    python_data = None
    Agent = None
    log_unified = None

notebook_bp = Blueprint('notebook', __name__, url_prefix='/api/notebook')

# Default paths
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
WINDLASS_ROOT = os.path.abspath(os.getenv("WINDLASS_ROOT", _DEFAULT_ROOT))
TACKLE_DIR = os.path.join(WINDLASS_ROOT, "tackle")
CASCADES_DIR = os.path.join(WINDLASS_ROOT, "cascades")
EXAMPLES_DIR = os.path.join(WINDLASS_ROOT, "examples")
PLAYGROUND_SCRATCHPAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'playground_scratchpad'))


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


# Default prompts for auto-fix
DEFAULT_AUTO_FIX_PROMPTS = {
    "sql_data": """Fix this SQL query that failed with an error.

Error: {error}

Original query:
```sql
{original_code}
```

Return ONLY the corrected SQL query. No explanations, no markdown code blocks, just the raw SQL.""",

    "python_data": """Fix this Python code that failed with an error.

Error: {error}

Original code:
```python
{original_code}
```

The code should set a `result` variable with the output (DataFrame, dict, or scalar).
Available: `data.phase_name` for prior phase outputs, `pd` (pandas), `np` (numpy).

Return ONLY the corrected Python code. No explanations, no markdown code blocks, just the raw code."""
}


def attempt_auto_fix(
    tool: str,
    original_code: str,
    error_message: str,
    auto_fix_config: dict,
    session_id: str,
    phase_name: str,
    prior_outputs: dict = None,
    inputs: dict = None
) -> dict:
    """
    Attempt to auto-fix a failed cell using LLM.

    Args:
        tool: Tool type ('sql_data' or 'python_data')
        original_code: The code that failed
        error_message: The error message
        auto_fix_config: Auto-fix configuration
        session_id: Session ID for cost tracking
        phase_name: Phase name for logging
        prior_outputs: Prior cell outputs (for python_data)
        inputs: Notebook inputs (for python_data)

    Returns:
        Result dict from successful execution, or raises exception
    """
    if not Agent:
        raise RuntimeError("Agent not available for auto-fix")

    max_attempts = auto_fix_config.get('max_attempts', 2)
    model = auto_fix_config.get('model', 'google/gemini-2.5-flash-lite')
    custom_prompt = auto_fix_config.get('prompt')

    # Get code key based on tool
    code_key = 'query' if tool == 'sql_data' else 'code'
    tool_type = 'SQL' if tool == 'sql_data' else 'Python'

    # Use custom prompt or default
    prompt_template = custom_prompt or DEFAULT_AUTO_FIX_PROMPTS.get(tool, DEFAULT_AUTO_FIX_PROMPTS['python_data'])

    last_error = error_message
    fix_attempts = []

    for attempt in range(max_attempts):
        # Build prompt
        prompt = prompt_template.format(
            error=last_error,
            original_code=original_code
        )

        try:
            # Get config for API credentials
            cfg = get_config()

            # Create agent for fix
            agent = Agent(
                model=model,
                system_prompt=f"You are a {tool_type} code fixer. Return ONLY the fixed code, no explanations.",
                base_url=cfg.provider_base_url,
                api_key=cfg.provider_api_key,
            )

            # Get fix from LLM
            fix_response = agent.run(input_message=prompt)
            fix_result = fix_response.get('content', '')

            # Clean the response (remove markdown code blocks)
            fixed_code = fix_result.strip()
            if fixed_code.startswith("```"):
                lines = fixed_code.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                fixed_code = "\n".join(lines)

            fix_attempts.append({
                'attempt': attempt + 1,
                'fixed_code_preview': fixed_code[:200] + '...' if len(fixed_code) > 200 else fixed_code,
                'model': model
            })

            # Try executing the fixed code
            if tool == 'sql_data':
                result = sql_data(
                    query=fixed_code,
                    materialize=True,
                    _phase_name=phase_name,
                    _session_id=session_id
                )
            elif tool == 'python_data':
                result = python_data(
                    code=fixed_code,
                    _outputs=prior_outputs or {},
                    _state={},
                    _input=inputs or {},
                    _phase_name=phase_name,
                    _session_id=session_id
                )

            # Success! Add fix info to result
            result['_auto_fixed'] = True
            result['_fix_attempts'] = fix_attempts
            result['_fixed_code'] = fixed_code

            # Log success
            if log_unified:
                log_unified(
                    session_id=session_id,
                    node_type="auto_fix_success",
                    role="system",
                    cascade_id="notebook",
                    phase_name=phase_name,
                    content=f"Auto-fix succeeded on attempt {attempt + 1}",
                    metadata={
                        'attempt': attempt + 1,
                        'model': model,
                        'original_error': error_message
                    }
                )

            return result

        except Exception as retry_error:
            last_error = str(retry_error)
            fix_attempts.append({
                'attempt': attempt + 1,
                'error': last_error,
                'model': model
            })

            # Log failure
            if log_unified:
                log_unified(
                    session_id=session_id,
                    node_type="auto_fix_failed",
                    role="system",
                    cascade_id="notebook",
                    phase_name=phase_name,
                    content=f"Auto-fix attempt {attempt + 1} failed: {last_error}",
                    metadata={
                        'attempt': attempt + 1,
                        'model': model,
                        'error': last_error
                    }
                )

    # All attempts failed
    raise Exception(f"Auto-fix failed after {max_attempts} attempts. Last error: {last_error}")


def is_data_cascade(cascade_dict):
    """Check if a cascade is a data cascade (all deterministic phases)."""
    phases = cascade_dict.get('phases', [])
    if not phases:
        return False

    data_tools = {'sql_data', 'python_data', 'set_state'}
    for phase in phases:
        tool = phase.get('tool')
        if not tool:
            # LLM-based phase (has instructions instead of tool)
            return False
        if tool not in data_tools:
            return False

    return True


def load_yaml_file(path):
    """Load a YAML file and return its content."""
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        return None


def scan_directory_for_notebooks(directory, base_path=""):
    """Scan a directory for data cascade notebooks."""
    notebooks = []

    if not os.path.exists(directory):
        return notebooks

    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)

        if os.path.isfile(item_path) and (item.endswith('.yaml') or item.endswith('.yml')):
            cascade = load_yaml_file(item_path)
            if cascade and is_data_cascade(cascade):
                rel_path = os.path.join(base_path, item) if base_path else item
                notebooks.append({
                    'cascade_id': cascade.get('cascade_id', item),
                    'description': cascade.get('description', ''),
                    'path': rel_path,
                    'full_path': item_path,
                    'inputs_schema': cascade.get('inputs_schema', {}),
                    'phase_count': len(cascade.get('phases', []))
                })
        elif os.path.isdir(item_path):
            # Recurse into subdirectories
            sub_base = os.path.join(base_path, item) if base_path else item
            notebooks.extend(scan_directory_for_notebooks(item_path, sub_base))

    return notebooks


@notebook_bp.route('/list', methods=['GET'])
def list_notebooks():
    """
    List all available data cascade notebooks.

    Scans tackle/, cascades/, and examples/ directories for YAML files
    that only contain deterministic phases (sql_data, python_data).

    Returns:
        JSON with list of notebooks and their metadata
    """
    try:
        notebooks = []

        # Scan directories
        for base_dir, prefix in [
            (TACKLE_DIR, 'tackle/'),
            (CASCADES_DIR, 'cascades/'),
            (EXAMPLES_DIR, 'examples/'),
            (PLAYGROUND_SCRATCHPAD_DIR, 'playground/'),
        ]:
            found = scan_directory_for_notebooks(base_dir, prefix.rstrip('/'))
            notebooks.extend(found)

        return jsonify({
            'notebooks': notebooks,
            'count': len(notebooks)
        })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'notebooks': []
        }), 500


@notebook_bp.route('/load', methods=['GET'])
def load_notebook():
    """
    Load a notebook by path.

    Args:
        path: Relative path to the notebook (e.g., 'tackle/my_notebook.yaml')

    Returns:
        JSON with notebook content
    """
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({'error': 'Path is required'}), 400

        # Resolve full path
        full_path = os.path.join(WINDLASS_ROOT, path)

        if not os.path.exists(full_path):
            return jsonify({'error': f'Notebook not found: {path}'}), 404

        cascade = load_yaml_file(full_path)
        if not cascade:
            return jsonify({'error': 'Failed to parse YAML'}), 400

        return jsonify({
            'notebook': cascade,
            'path': path
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notebook_bp.route('/save', methods=['POST'])
def save_notebook():
    """
    Save a notebook to a file.

    Request body:
        - path: Relative path to save (e.g., 'tackle/my_notebook.yaml')
        - notebook: Notebook content (cascade definition)

    Returns:
        JSON with success status
    """
    try:
        data = request.json
        path = data.get('path')
        notebook = data.get('notebook')

        if not path:
            return jsonify({'error': 'Path is required'}), 400

        if not notebook:
            return jsonify({'error': 'Notebook content is required'}), 400

        # Resolve full path
        full_path = os.path.join(WINDLASS_ROOT, path)

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write YAML
        with open(full_path, 'w') as f:
            yaml.dump(notebook, f, default_flow_style=False, sort_keys=False)

        return jsonify({
            'success': True,
            'path': path
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notebook_bp.route('/run', methods=['POST'])
def run_notebook():
    """
    Run a complete notebook (data cascade).

    Request body:
        - notebook: Notebook content (cascade definition)
        - inputs: Input values for the notebook

    Returns:
        JSON with execution results for each phase
    """
    try:
        data = request.json
        notebook = data.get('notebook')
        inputs = data.get('inputs', {})

        if not notebook:
            return jsonify({'error': 'Notebook content is required'}), 400

        # Generate session ID
        session_id = f"notebook_{uuid.uuid4().hex[:8]}"

        # Write notebook to temp file
        temp_dir = os.path.join(_THIS_DIR, 'workshop_temp')
        os.makedirs(temp_dir, exist_ok=True)

        temp_path = os.path.join(temp_dir, f'{session_id}.yaml')
        with open(temp_path, 'w') as f:
            yaml.dump(notebook, f, default_flow_style=False, sort_keys=False)

        try:
            # Run the cascade
            result = run_cascade(temp_path, inputs, session_id=session_id)

            # Extract phase results from lineage
            phases = {}
            for entry in result.get('lineage', []):
                phase_name = entry.get('phase')
                output = entry.get('output')
                duration = entry.get('duration_ms')

                # Skip routing messages (strings)
                if isinstance(output, dict):
                    phases[phase_name] = {
                        'result': sanitize_for_json(output),
                        'duration_ms': duration,
                        'error': output.get('error') if output.get('_route') == 'error' else None
                    }

            return jsonify({
                'session_id': session_id,
                'phases': phases,
                'final_output': sanitize_for_json(result.get('state', {}).get(f'output_{notebook["phases"][-1]["name"]}')),
                'has_errors': result.get('has_errors', False)
            })

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@notebook_bp.route('/run-cell', methods=['POST'])
def run_cell():
    """
    Run a single notebook cell with optional auto-fix.

    Request body:
        - cell: Cell definition (phase object)
        - inputs: Input values for the notebook
        - prior_outputs: Outputs from prior cells
        - session_id: Session ID for temp table persistence
        - auto_fix: Optional auto-fix config {enabled, max_attempts, model, prompt}

    Returns:
        JSON with cell execution result
    """
    try:
        data = request.json
        cell = data.get('cell')
        inputs = data.get('inputs', {})
        prior_outputs = data.get('prior_outputs', {})
        session_id = data.get('session_id') or f"cell_{uuid.uuid4().hex[:8]}"
        auto_fix_config = data.get('auto_fix', {})

        if not cell:
            return jsonify({'error': 'Cell definition is required'}), 400

        tool = cell.get('tool')
        cell_inputs = cell.get('inputs', {})
        phase_name = cell.get('name', 'cell')

        # Render Jinja2 templates in cell inputs
        from jinja2 import Template
        rendered_inputs = {}
        render_context = {'input': inputs, 'state': {}, 'outputs': prior_outputs}

        for key, value in cell_inputs.items():
            if isinstance(value, str):
                try:
                    template = Template(value)
                    rendered_inputs[key] = template.render(**render_context)
                except Exception:
                    rendered_inputs[key] = value
            else:
                rendered_inputs[key] = value

        # Get original code for potential auto-fix
        original_code = rendered_inputs.get('query') if tool == 'sql_data' else rendered_inputs.get('code', '')

        # Execute the appropriate tool
        execution_error = None
        result = None

        try:
            if tool == 'sql_data':
                result = sql_data(
                    query=rendered_inputs.get('query', ''),
                    connection=rendered_inputs.get('connection'),
                    limit=rendered_inputs.get('limit', 10000),
                    materialize=True,
                    _phase_name=phase_name,
                    _session_id=session_id
                )
            elif tool == 'python_data':
                result = python_data(
                    code=rendered_inputs.get('code', ''),
                    _outputs=prior_outputs,
                    _state={},
                    _input=inputs,
                    _phase_name=phase_name,
                    _session_id=session_id
                )
            else:
                return jsonify({'error': f'Unknown tool: {tool}'}), 400

        except Exception as e:
            execution_error = str(e)

        # Check if result indicates an error (tools may return error dict instead of raising)
        if result and (result.get('error') or result.get('_route') == 'error'):
            execution_error = result.get('error', 'Unknown error')
            result = None  # Clear result so we attempt fix

        # If execution failed and auto-fix is enabled, try to fix
        if execution_error and auto_fix_config.get('enabled', False):
            try:
                result = attempt_auto_fix(
                    tool=tool,
                    original_code=original_code,
                    error_message=str(execution_error),
                    auto_fix_config=auto_fix_config,
                    session_id=session_id,
                    phase_name=phase_name,
                    prior_outputs=prior_outputs,
                    inputs=inputs
                )
                # Auto-fix succeeded
                return jsonify(sanitize_for_json(result))

            except Exception as fix_error:
                # Auto-fix also failed - return original error with fix attempts info
                import traceback
                return jsonify({
                    '_route': 'error',
                    'error': str(execution_error),
                    'auto_fix_error': str(fix_error),
                    'traceback': traceback.format_exc()
                }), 500

        # If there was an error and no auto-fix, raise it
        if execution_error:
            raise execution_error

        return jsonify(sanitize_for_json(result))

    except Exception as e:
        import traceback
        return jsonify({
            '_route': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@notebook_bp.route('/cleanup-session', methods=['POST'])
def cleanup_session():
    """
    Clean up a notebook session's temporary DuckDB database.

    Request body:
        - session_id: Session ID to clean up

    Returns:
        JSON with success status
    """
    try:
        data = request.json
        session_id = data.get('session_id')

        if session_id:
            cleanup_session_db(session_id, delete_file=True)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
