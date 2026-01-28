"""
Calliope API - Kit management and generation endpoints

Provides REST API for managing Calliope kits (micro-apps) and
triggering the app builder cascade.
"""
import os
import sys
import json
import base64
import tempfile
from pathlib import Path
from flask import Blueprint, request, jsonify

# Ensure lars package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from lars.calliope.kit_manager import KitManager, get_starters_dir
from lars.config import LARS_ROOT

calliope_bp = Blueprint('calliope', __name__, url_prefix='/api/calliope')

# Singleton kit manager instance
_kit_manager = None


def get_kit_manager() -> KitManager:
    """Get or create the kit manager singleton."""
    global _kit_manager
    if _kit_manager is None:
        _kit_manager = KitManager(lars_root=LARS_ROOT)
    return _kit_manager


# ============================================================================
# Kit CRUD
# ============================================================================

@calliope_bp.route('/kit', methods=['POST'])
def create_kit():
    """
    Create a new kit from template.

    Body: { template: 'basic' }
    Returns: { kit_id, template, status }
    """
    try:
        data = request.get_json(force=True) or {}
        template = data.get('template', 'basic')

        manager = get_kit_manager()
        kit_id = manager.create_kit(template=template)

        return jsonify({
            'kit_id': kit_id,
            'template': template,
            'status': 'created',
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@calliope_bp.route('/kit', methods=['GET'])
def list_kits():
    """
    List all kits.

    Returns: { kits: [{kit_id, template, status, port, ...}] }
    """
    try:
        manager = get_kit_manager()
        kits = manager.list_kits()

        return jsonify({'kits': kits})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@calliope_bp.route('/kit/<kit_id>', methods=['GET'])
def get_kit(kit_id: str):
    """
    Get kit details.

    Returns: { kit_id, template, status, port, ... }
    """
    try:
        manager = get_kit_manager()
        kit = manager.get_kit(kit_id)

        return jsonify(kit)

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@calliope_bp.route('/kit/<kit_id>', methods=['DELETE'])
def delete_kit(kit_id: str):
    """
    Delete a kit.

    Query params: force=true to delete running kit
    Returns: { success: true }
    """
    try:
        force = request.args.get('force', '').lower() == 'true'

        manager = get_kit_manager()
        manager.delete_kit(kit_id, force=force)

        return jsonify({'success': True})

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 409  # Conflict - kit is running
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Kit Lifecycle
# ============================================================================

@calliope_bp.route('/kit/<kit_id>/start', methods=['POST'])
def start_kit(kit_id: str):
    """
    Start a kit server.

    Body: { port?: number }
    Returns: { kit_id, port, status, pid }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        port = data.get('port')

        manager = get_kit_manager()
        result = manager.start_kit(kit_id, port=port)

        return jsonify(result)

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@calliope_bp.route('/kit/<kit_id>/stop', methods=['POST'])
def stop_kit(kit_id: str):
    """
    Stop a kit server.

    Returns: { kit_id, status }
    """
    try:
        manager = get_kit_manager()
        result = manager.stop_kit(kit_id)

        return jsonify(result)

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Kit Files
# ============================================================================

@calliope_bp.route('/kit/<kit_id>/files', methods=['GET'])
def list_kit_files(kit_id: str):
    """
    List files in a kit.

    Returns: { files: [{path, type, ext}] }
    """
    try:
        manager = get_kit_manager()
        files = manager.get_kit_files(kit_id)

        return jsonify({'files': files})

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@calliope_bp.route('/kit/<kit_id>/files/<path:file_path>', methods=['GET'])
def read_kit_file(kit_id: str, file_path: str):
    """
    Read a file from a kit.

    Returns: { content: string }
    """
    try:
        manager = get_kit_manager()
        content = manager.read_kit_file(kit_id, file_path)

        return jsonify({'content': content})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Generation (Cascade Trigger)
# ============================================================================

@calliope_bp.route('/kit/<kit_id>/generate', methods=['POST'])
def generate(kit_id: str):
    """
    Run the app builder cascade to modify a kit.

    Body: {
        request: string,           // User's verbal description
        annotated_screenshot?: string,  // Base64 PNG with drawings
        include_files?: boolean    // Include current file contents
    }

    Returns: { success: true, session_id: string }
    """
    try:
        data = request.get_json(force=True) or {}
        user_request = data.get('request', '')
        annotated_screenshot = data.get('annotated_screenshot')
        include_files = data.get('include_files', True)

        if not user_request:
            return jsonify({'error': 'request is required'}), 400

        manager = get_kit_manager()

        # Verify kit exists
        kit = manager.get_kit(kit_id)
        kit_path = manager.kits_dir / kit_id

        # Prepare cascade inputs
        cascade_inputs = {
            'request': user_request,
            'kit_id': kit_id,
            'kit_path': str(kit_path),
            'port': kit.get('port'),  # For visual validation
            'annotated_screenshot': None,  # Will be set below if provided
        }

        # Include annotated screenshot if provided
        if annotated_screenshot:
            # Save to temp file for vision model
            if annotated_screenshot.startswith('data:'):
                # Strip data URL prefix
                annotated_screenshot = annotated_screenshot.split(',', 1)[1]

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(base64.b64decode(annotated_screenshot))
                cascade_inputs['annotated_screenshot'] = f.name

        # Include current file contents
        if include_files:
            files = []
            key_files = ['app.py', 'static/app.js', 'static/index.html', 'static/styles.css']

            for file_path in key_files:
                try:
                    content = manager.read_kit_file(kit_id, file_path)
                    files.append({
                        'path': file_path,
                        'ext': Path(file_path).suffix,
                        'content': content,
                    })
                except FileNotFoundError:
                    pass

            # Also include component files
            try:
                all_files = manager.get_kit_files(kit_id)
                for f in all_files:
                    if f['path'].startswith('static/components/') and f['path'].endswith('.js'):
                        try:
                            content = manager.read_kit_file(kit_id, f['path'])
                            files.append({
                                'path': f['path'],
                                'ext': '.js',
                                'content': content,
                            })
                        except FileNotFoundError:
                            pass
            except Exception:
                pass

            cascade_inputs['files'] = files

        # Load patterns and instructions from starter (based on kit's template)
        try:
            starters_dir = get_starters_dir()
            template = kit.get('template', 'basic')

            # Load PATTERNS.md
            patterns_path = starters_dir / template / 'PATTERNS.md'
            if patterns_path.exists():
                cascade_inputs['patterns'] = patterns_path.read_text()
            else:
                cascade_inputs['patterns'] = ''

            # Load INSTRUCTIONS.md (framework-specific instructions)
            instructions_path = starters_dir / template / 'INSTRUCTIONS.md'
            if instructions_path.exists():
                cascade_inputs['instructions'] = instructions_path.read_text()
            else:
                cascade_inputs['instructions'] = ''
        except Exception:
            cascade_inputs['patterns'] = ''
            cascade_inputs['instructions'] = ''

        # Run the cascade
        # Import from lars (not lars.runner) to ensure skills are registered first
        from lars import run_cascade
        from lars.session_naming import generate_woodland_id

        session_id = f"calliope-{generate_woodland_id()}"

        # Find the cascade
        from lars.config import get_builtin_cascades_dir
        cascade_path = Path(get_builtin_cascades_dir()) / 'calliope_app_builder.yaml'

        if not cascade_path.exists():
            # Cascade not yet created - for now, just return success
            # TODO: Create the actual cascade
            return jsonify({
                'success': True,
                'session_id': session_id,
                'message': 'Cascade not yet implemented - kit files unchanged',
            })

        # Run cascade from kit directory so relative paths work
        original_cwd = os.getcwd()
        try:
            os.chdir(kit_path)
            result = run_cascade(
                str(cascade_path),
                input_data=cascade_inputs,
                session_id=session_id,
            )
        finally:
            os.chdir(original_cwd)

        return jsonify({
            'success': True,
            'session_id': session_id,
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Templates
# ============================================================================

@calliope_bp.route('/session/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id: str):
    """
    Get recent messages for a Calliope session (for progress toasts).

    Query params:
        after: ISO timestamp to fetch messages after (default: 5 seconds ago)

    Returns: { messages: [{timestamp, cell_name, content, node_type}] }
    """
    try:
        from lars.db_adapter import get_db
        from datetime import datetime, timedelta, timezone

        after = request.args.get('after')
        if not after:
            # Default to 5 seconds ago
            after = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S')

        db = get_db()

        # Query unified_logs for this session's recent activity
        # Focus on tool calls and assistant messages that indicate progress
        query = f"""
            SELECT
                timestamp,
                cell_name,
                node_type,
                CASE
                    WHEN node_type = 'tool_call' THEN
                        JSONExtractString(tool_calls_json, 'name')
                    WHEN role = 'assistant' AND length(content_json) < 200 THEN
                        content_json
                    ELSE NULL
                END as content
            FROM unified_logs
            WHERE (session_id = '{session_id}' OR caller_id = '{session_id}')
              AND timestamp > '{after}'
              AND (node_type = 'tool_call' OR (role = 'assistant' AND content_json IS NOT NULL))
            ORDER BY timestamp DESC
            LIMIT 10
        """

        rows = db.execute(query) or []
        messages = []
        for row in rows:
            content = row.get('content')
            if content:
                # Clean up content for display
                if content.startswith('"') and content.endswith('"'):
                    content = content[1:-1]
                if len(content) > 100:
                    content = content[:100] + '...'

                messages.append({
                    'timestamp': str(row.get('timestamp')),
                    'cell_name': row.get('cell_name'),
                    'node_type': row.get('node_type'),
                    'content': content,
                })

        return jsonify({'messages': messages})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'messages': []}), 500


@calliope_bp.route('/templates', methods=['GET'])
def list_templates():
    """
    List available kit templates.

    Returns: { templates: [{id, name, description}] }
    """
    try:
        starters_dir = get_starters_dir()

        templates = []
        for path in starters_dir.iterdir():
            if path.is_dir() and not path.name.startswith('.'):
                # Read template metadata if exists
                metadata_path = path / 'template.yaml'
                if metadata_path.exists():
                    import yaml
                    with open(metadata_path) as f:
                        metadata = yaml.safe_load(f) or {}
                else:
                    metadata = {}

                templates.append({
                    'id': path.name,
                    'name': metadata.get('name', path.name.title()),
                    'description': metadata.get('description', f'{path.name} template'),
                })

        return jsonify({'templates': templates})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
