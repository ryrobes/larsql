"""
Windlass Debug UI Backend - Flask server for observability
"""
import os
import json
import glob
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, request, Response, stream_with_context
from flask_cors import CORS
import duckdb
from queue import Empty
from execution_tree import ExecutionTreeBuilder, build_react_flow_nodes

app = Flask(__name__)
CORS(app)

# Configuration - reads from environment or uses defaults
LOG_DIR = os.getenv("WINDLASS_LOG_DIR", "./logs")
GRAPH_DIR = os.getenv("WINDLASS_GRAPH_DIR", "./graphs")
STATE_DIR = os.getenv("WINDLASS_STATE_DIR", "./states")
IMAGE_DIR = os.getenv("WINDLASS_IMAGE_DIR", "./images")

def get_db_connection():
    """Create a DuckDB connection to query logs"""
    conn = duckdb.connect(database=':memory:')

    # Find all parquet files in logs directory
    parquet_files = glob.glob(f"{LOG_DIR}/**/*.parquet", recursive=True)

    if parquet_files:
        # Create a view of all log files
        files_str = "', '".join(parquet_files)
        conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'])")

    return conn

@app.route('/api/cascades', methods=['GET'])
def get_cascades():
    """Get all cascades with their current status"""
    try:
        conn = get_db_connection()

        # Query to get unique cascades (by session_id)
        query = """
        WITH session_info AS (
            SELECT
                session_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as last_update,
                COUNT(*) as event_count,
                COUNT(CASE WHEN role = 'error' THEN 1 END) as error_count
            FROM logs
            GROUP BY session_id
        )
        SELECT
            session_id,
            start_time,
            last_update,
            event_count,
            error_count
        FROM session_info
        ORDER BY last_update DESC
        LIMIT 100
        """

        result = conn.execute(query).fetchall()

        cascades = []
        for row in result:
            session_id, start_time, last_update, event_count, error_count = row

            # Determine status based on activity
            # If last update was more than 60 seconds ago, assume completed
            # If there are errors, mark as failed
            # Otherwise, check if still running
            time_since_update = datetime.now().timestamp() - last_update

            if error_count > 0:
                status = 'failed'
            elif time_since_update < 60:
                status = 'running'
            else:
                status = 'completed'

            cascades.append({
                'session_id': session_id,
                'cascade_id': session_id[:8] + '...',  # Use truncated session_id as cascade_id
                'status': status,
                'last_update': datetime.fromtimestamp(last_update).isoformat(),
                'event_count': event_count,
                'error_count': error_count
            })

        conn.close()
        return jsonify(cascades)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get recent log entries"""
    try:
        conn = get_db_connection()

        query = """
        SELECT
            timestamp,
            session_id,
            role,
            content,
            metadata
        FROM logs
        ORDER BY timestamp DESC
        LIMIT 1000
        """

        result = conn.execute(query).fetchall()

        logs = []
        for row in result:
            timestamp, session_id, role, content, metadata_str = row

            # Try to parse metadata
            try:
                metadata = json.loads(metadata_str) if metadata_str and metadata_str != '{}' else {}
            except:
                metadata = {}

            logs.append({
                'timestamp': datetime.fromtimestamp(timestamp).isoformat(),
                'session_id': session_id,
                'event_type': role,  # role is actually the event type
                'message': content,
                'metadata': metadata,
                'phase_name': metadata.get('phase_name', None),
                'sounding_index': metadata.get('sounding_index', None),
                'reforge_step': metadata.get('reforge_step', None),
                'is_winner': metadata.get('is_winner', None)
            })

        conn.close()
        return jsonify(logs)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/<session_id>', methods=['GET'])
def get_session_logs(session_id):
    """Get logs for a specific session"""
    try:
        conn = get_db_connection()

        query = f"""
        SELECT
            timestamp,
            role,
            content,
            metadata
        FROM logs
        WHERE session_id = '{session_id}'
        ORDER BY timestamp ASC
        """

        result = conn.execute(query).fetchall()

        logs = []
        for row in result:
            timestamp, role, content, metadata_str = row

            # Try to parse metadata
            try:
                metadata = json.loads(metadata_str) if metadata_str and metadata_str != '{}' else {}
            except:
                metadata = {}

            logs.append({
                'timestamp': datetime.fromtimestamp(timestamp).isoformat(),
                'event_type': role,
                'message': content,
                'metadata': metadata,
                'phase_name': metadata.get('phase_name', None),
                'sounding_index': metadata.get('sounding_index', None),
                'reforge_step': metadata.get('reforge_step', None),
                'is_winner': metadata.get('is_winner', None)
            })

        conn.close()
        return jsonify(logs)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/graph/<session_id>', methods=['GET'])
def get_graph(session_id):
    """Get Mermaid graph for a session"""
    try:
        # Look for the graph file
        graph_pattern = f"{GRAPH_DIR}/**/{session_id}.mmd"
        graph_files = glob.glob(graph_pattern, recursive=True)

        if not graph_files:
            return jsonify({'error': 'Graph not found'}), 404

        # Read the most recent graph file
        graph_file = graph_files[0]
        with open(graph_file, 'r') as f:
            content = f.read()

        # Get file modification time
        mtime = os.path.getmtime(graph_file)

        return jsonify({
            'content': content,
            'last_modified': datetime.fromtimestamp(mtime).isoformat(),
            'path': graph_file
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/graphs', methods=['GET'])
def get_all_graphs():
    """Get all available Mermaid graphs"""
    try:
        graph_files = glob.glob(f"{GRAPH_DIR}/**/*.mmd", recursive=True)

        graphs = []
        for graph_file in graph_files:
            session_id = Path(graph_file).stem
            mtime = os.path.getmtime(graph_file)

            graphs.append({
                'session_id': session_id,
                'path': graph_file,
                'last_modified': datetime.fromtimestamp(mtime).isoformat()
            })

        return jsonify(graphs)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cascade-files', methods=['GET'])
def get_cascade_files():
    """Get all available cascade JSON files"""
    try:
        # Look for cascade files in common directories
        cascade_dirs = [
            os.path.join(os.getcwd(), 'examples'),
            os.path.join(os.getcwd(), 'cascades'),
            os.path.join(os.getcwd(), 'windlass', 'examples'),
            '/home/ryanr/repos/windlass/windlass/examples'
        ]

        cascade_files = []

        for cascade_dir in cascade_dirs:
            if os.path.exists(cascade_dir):
                json_files = glob.glob(f"{cascade_dir}/**/*.json", recursive=True)
                for json_file in json_files:
                    try:
                        with open(json_file, 'r') as f:
                            data = json.load(f)
                            if 'cascade_id' in data:  # Validate it's a cascade file
                                cascade_files.append({
                                    'path': json_file,
                                    'name': os.path.basename(json_file),
                                    'cascade_id': data.get('cascade_id'),
                                    'description': data.get('description', ''),
                                    'inputs_schema': data.get('inputs_schema', {})
                                })
                    except:
                        continue

        return jsonify(cascade_files)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/run-cascade', methods=['POST'])
def run_cascade():
    """Run a cascade with given inputs"""
    try:
        data = json.loads(request.data)
        cascade_path = data.get('cascade_path')
        inputs = data.get('inputs', {})

        if not cascade_path or not os.path.exists(cascade_path):
            return jsonify({'error': 'Invalid cascade path'}), 400

        # Import subprocess to run windlass CLI
        import subprocess
        import uuid

        # Generate a unique session ID
        session_id = f"debug_ui_{uuid.uuid4().hex[:8]}"

        # Determine the working directory - use the parent of the cascade file
        # This ensures relative paths in the cascade work correctly
        cascade_dir = os.path.dirname(os.path.abspath(cascade_path))

        # Try to find the windlass project root
        # Look for common markers like pyproject.toml, setup.py, or windlass directory
        current = cascade_dir
        project_root = None
        while current != '/':
            if any(os.path.exists(os.path.join(current, marker))
                   for marker in ['pyproject.toml', 'setup.py', 'windlass']):
                project_root = current
                break
            current = os.path.dirname(current)

        # Default to cascade directory if no project root found
        working_dir = project_root or cascade_dir

        # Build the command
        cmd = [
            'windlass',
            cascade_path,
            '--input', json.dumps(inputs),
            '--session', session_id
        ]

        # Copy current environment and ensure Windlass env vars are passed
        env = os.environ.copy()

        # Run in background with correct working directory and environment
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_dir,
            env=env
        )

        return jsonify({
            'success': True,
            'session_id': session_id,
            'working_dir': working_dir,
            'message': f'Cascade started with session ID: {session_id}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/stream')
def event_stream():
    """Server-Sent Events endpoint for real-time cascade updates"""
    def generate():
        # Import the event bus from windlass (installed in venv)
        try:
            from windlass.events import get_event_bus

            bus = get_event_bus()
            queue = bus.subscribe()

            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': datetime.now().isoformat()})}\n\n"

            try:
                while True:
                    # Wait for events with timeout
                    try:
                        event = queue.get(timeout=30)

                        # Convert event to dict and send as SSE
                        data = json.dumps(event.to_dict())
                        yield f"data: {data}\n\n"

                    except Empty:
                        # Send heartbeat to keep connection alive
                        yield f": heartbeat\n\n"

            finally:
                bus.unsubscribe(queue)

        except Exception as e:
            # Any error - send to client
            import traceback
            error_detail = traceback.format_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'detail': error_detail})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

@app.route('/api/execution-tree/<session_id>', methods=['GET'])
def get_execution_tree(session_id):
    """Get structured execution tree for a session"""
    try:
        builder = ExecutionTreeBuilder(LOG_DIR)
        tree = builder.build_tree(session_id)

        # Optionally convert to react-flow format
        format_type = request.args.get('format', 'tree')

        if format_type == 'react-flow':
            graph = build_react_flow_nodes(tree)
            return jsonify(graph)
        else:
            return jsonify(tree)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/freeze', methods=['POST'])
def freeze_snapshot():
    """Freeze a session as a test snapshot"""
    try:
        data = json.loads(request.data)
        session_id = data.get('session_id')
        snapshot_name = data.get('snapshot_name')
        description = data.get('description', '')

        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400

        if not snapshot_name:
            return jsonify({'error': 'snapshot_name is required'}), 400

        # Import and use SnapshotCapture
        import sys
        import os

        # Add windlass to path if not already there
        windlass_path = os.path.join(os.path.dirname(__file__), '../../../windlass')
        if os.path.exists(windlass_path) and windlass_path not in sys.path:
            sys.path.insert(0, windlass_path)

        from windlass.testing import SnapshotCapture

        # Change to windlass package directory before creating snapshot
        # (so tests/cascade_snapshots/ is in the right place)
        original_cwd = os.getcwd()

        # Navigate to windlass package directory (windlass/windlass/)
        windlass_package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../windlass'))
        os.chdir(windlass_package_dir)

        try:
            # Create snapshot with correct log directory
            capturer = SnapshotCapture(log_dir=LOG_DIR)
            snapshot_file = capturer.freeze(session_id, snapshot_name, description)
        finally:
            # Restore original directory
            os.chdir(original_cwd)

        return jsonify({
            'success': True,
            'snapshot_name': snapshot_name,
            'snapshot_file': str(snapshot_file),
            'message': f'Test snapshot created: {snapshot_name}'
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/list', methods=['GET'])
def list_snapshots():
    """List all test snapshots"""
    try:
        import sys
        import os

        # Add windlass to path
        windlass_path = os.path.join(os.path.dirname(__file__), '../../../windlass')
        if os.path.exists(windlass_path) and windlass_path not in sys.path:
            sys.path.insert(0, windlass_path)

        from pathlib import Path

        snapshot_dir = Path("tests/cascade_snapshots")

        if not snapshot_dir.exists():
            return jsonify({'snapshots': []})

        snapshots = []
        for snapshot_file in sorted(snapshot_dir.glob("*.json")):
            with open(snapshot_file) as f:
                snapshot = json.load(f)

            snapshots.append({
                'name': snapshot['snapshot_name'],
                'description': snapshot.get('description', ''),
                'cascade_file': snapshot.get('cascade_file', ''),
                'phases': [p['name'] for p in snapshot['execution']['phases']],
                'captured_at': snapshot['captured_at']
            })

        return jsonify({'snapshots': snapshots})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'log_dir': LOG_DIR,
        'graph_dir': GRAPH_DIR,
        'state_dir': STATE_DIR,
        'image_dir': IMAGE_DIR
    })

if __name__ == '__main__':
    print(f"Windlass Debug UI Backend starting...")
    print(f"  LOG_DIR: {LOG_DIR}")
    print(f"  GRAPH_DIR: {GRAPH_DIR}")
    print(f"  STATE_DIR: {STATE_DIR}")
    print(f"  IMAGE_DIR: {IMAGE_DIR}")
    print(f"  Server running on http://localhost:5001")

    app.run(debug=True, host='0.0.0.0', port=5001)
