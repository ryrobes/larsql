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
except ImportError as e:
    print(f"Warning: Could not import windlass modules: {e}")
    run_cascade = None
    get_config = None
    sql_data = None
    python_data = None

notebook_bp = Blueprint('notebook', __name__, url_prefix='/api/notebook')

# Default paths
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
WINDLASS_ROOT = os.path.abspath(os.getenv("WINDLASS_ROOT", _DEFAULT_ROOT))
TACKLE_DIR = os.path.join(WINDLASS_ROOT, "tackle")
CASCADES_DIR = os.path.join(WINDLASS_ROOT, "cascades")
EXAMPLES_DIR = os.path.join(WINDLASS_ROOT, "examples")


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
            (EXAMPLES_DIR, 'examples/')
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
    Run a single notebook cell.

    Request body:
        - cell: Cell definition (phase object)
        - inputs: Input values for the notebook
        - prior_outputs: Outputs from prior cells
        - session_id: Session ID for temp table persistence

    Returns:
        JSON with cell execution result
    """
    try:
        data = request.json
        cell = data.get('cell')
        inputs = data.get('inputs', {})
        prior_outputs = data.get('prior_outputs', {})
        session_id = data.get('session_id') or f"cell_{uuid.uuid4().hex[:8]}"

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

        # Execute the appropriate tool
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

        return jsonify(sanitize_for_json(result))

    except Exception as e:
        import traceback
        return jsonify({
            '_route': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
