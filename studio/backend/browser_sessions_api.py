"""
API endpoints for Rabbitize Browser Sessions

Provides REST API for:
- Listing browser sessions (from rabbitize-runs/)
- Getting session details (screenshots, video, commands, DOM)
- Serving media files (screenshots, videos)
- MJPEG stream proxy for live sessions
- Flow management (save, load, test, register as tool)
- Rabbitize server lifecycle management (auto-start, health check, proxy)
"""
import json
import os
import sys
import time
import glob
import subprocess
import threading
import requests
import socket
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, Response, stream_with_context
from datetime import datetime

# Add parent directory to path to import rvbbit
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up 2 levels: backend -> dashboard, then add windlass package
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_RVBBIT_DIR = os.path.join(_REPO_ROOT, "rvbbit")
if _RVBBIT_DIR not in sys.path:
    sys.path.insert(0, _RVBBIT_DIR)

try:
    from rvbbit.config import get_config
    from rvbbit.session_registry import get_session_registry, SessionRegistry
except ImportError as e:
    print(f"Warning: Could not import windlass modules: {e}")
    get_config = None
    get_session_registry = None
    SessionRegistry = None

browser_sessions_bp = Blueprint('browser_sessions', __name__)

# =============================================================================
# Rabbitize Session Manager - Multi-session support with dynamic ports
# =============================================================================

RABBITIZE_BASE_PORT = 13100  # Start allocating from this port
RABBITIZE_MAX_SESSIONS = 10  # Maximum concurrent sessions

# Session registry: session_id -> session_info
_sessions = {}
_sessions_lock = threading.Lock()


def _get_rabbitize_dir() -> Path:
    """Get the rabbitize directory path."""
    return Path(_REPO_ROOT) / "rabbitize"


def _is_port_in_use(port: int) -> bool:
    """Check if a port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def _find_available_port() -> int:
    """Find the next available port for a Rabbitize instance."""
    for port in range(RABBITIZE_BASE_PORT, RABBITIZE_BASE_PORT + RABBITIZE_MAX_SESSIONS):
        if not _is_port_in_use(port):
            return port
    return None


def _is_session_healthy(port: int) -> bool:
    """Check if a Rabbitize session is responding."""
    try:
        resp = requests.get(f"http://localhost:{port}/health", timeout=2)
        return resp.status_code == 200
    except:
        return False


def _get_session_status(port: int) -> dict:
    """Get detailed status from a Rabbitize session."""
    try:
        resp = requests.get(f"http://localhost:{port}/status", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except:
        return None


def _create_session(session_id: str = None) -> dict:
    """Create a new Rabbitize session on a dynamic port."""
    with _sessions_lock:
        # Generate session ID if not provided
        if not session_id:
            session_id = f"session_{int(time.time() * 1000)}"

        # Check if session already exists
        if session_id in _sessions:
            session = _sessions[session_id]
            if _is_session_healthy(session["port"]):
                return {
                    "success": True,
                    "session_id": session_id,
                    "port": session["port"],
                    "already_exists": True
                }
            else:
                # Session exists but dead, clean it up
                _cleanup_session(session_id)

        # Find available port
        port = _find_available_port()
        if not port:
            return {"success": False, "error": "No available ports. Kill some sessions first."}

        rabbitize_dir = _get_rabbitize_dir()
        if not rabbitize_dir.exists():
            return {"success": False, "error": f"Rabbitize directory not found: {rabbitize_dir}"}

        if not (rabbitize_dir / "node_modules").exists():
            return {"success": False, "error": "Rabbitize node_modules not found. Run: cd rabbitize && npm install"}

        try:
            # Start Rabbitize server on the allocated port
            # Use _REPO_ROOT as cwd so rabbitize-runs/ is created at project root
            # (consistent with browser_manager.py which also uses config.root_dir)
            process = subprocess.Popen(
                ["node", "rabbitize/src/index.js", "--port", str(port)],
                cwd=str(_REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )

            # Wait for server to be ready (up to 30 seconds)
            for _ in range(60):
                time.sleep(0.5)
                if _is_session_healthy(port):
                    _sessions[session_id] = {
                        "session_id": session_id,
                        "port": port,
                        "process": process,
                        "pid": process.pid,
                        "started_at": datetime.now().isoformat(),
                        "browser_session": None  # Will be set when URL is loaded
                    }

                    # Register with unified session registry
                    if get_session_registry:
                        try:
                            registry = get_session_registry(_REPO_ROOT)
                            registry.register(
                                session_id=session_id,
                                port=port,
                                pid=process.pid,
                                source='ui'
                            )
                        except Exception as e:
                            print(f"Warning: Failed to register session with registry: {e}")

                    return {
                        "success": True,
                        "session_id": session_id,
                        "port": port,
                        "pid": process.pid
                    }
                # Check if process died
                if process.poll() is not None:
                    stderr = process.stderr.read().decode() if process.stderr else ""
                    return {"success": False, "error": f"Rabbitize process exited: {stderr[:500]}"}

            # Timeout - kill the process
            process.terminate()
            return {"success": False, "error": "Rabbitize server failed to start within 30 seconds"}

        except Exception as e:
            return {"success": False, "error": f"Failed to start Rabbitize: {str(e)}"}


def _cleanup_session(session_id: str) -> None:
    """Clean up a session (internal, called with lock held)."""
    if session_id in _sessions:
        session = _sessions[session_id]
        process = session.get("process")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass
        del _sessions[session_id]

        # Unregister from unified session registry
        if get_session_registry:
            try:
                registry = get_session_registry(_REPO_ROOT)
                registry.unregister(session_id)
            except Exception as e:
                print(f"Warning: Failed to unregister session from registry: {e}")


def _kill_session(session_id: str) -> dict:
    """Kill a specific session."""
    with _sessions_lock:
        if session_id not in _sessions:
            return {"success": False, "error": f"Session not found: {session_id}"}

        _cleanup_session(session_id)
        return {"success": True, "message": f"Session {session_id} killed"}


def _kill_all_sessions() -> dict:
    """Kill all active sessions."""
    with _sessions_lock:
        killed = list(_sessions.keys())
        for session_id in killed:
            _cleanup_session(session_id)
        return {"success": True, "killed": killed, "count": len(killed)}


def _list_sessions() -> list:
    """List all active sessions with their status."""
    with _sessions_lock:
        result = []
        dead_sessions = []

        for session_id, session in _sessions.items():
            port = session["port"]
            healthy = _is_session_healthy(port)

            if not healthy:
                dead_sessions.append(session_id)
                continue

            status = _get_session_status(port)
            current_state = status.get("currentState") if status else None

            # Get latest screenshot if there's an active browser session
            latest_screenshot = None
            browser_session_path = None
            if current_state and status.get("hasSession"):
                client_id = current_state.get("clientId", "unknown")
                test_id = current_state.get("testId", "unknown")
                # Get the browser session ID from the status
                browser_session_id = current_state.get("sessionId") or session.get("browser_session_id")
                if browser_session_id:
                    browser_session_path = f"{client_id}/{test_id}/{browser_session_id}"
                    # Find latest screenshot
                    screenshots_dir = _get_rabbitize_runs_dir() / client_id / test_id / browser_session_id / "screenshots"
                    if screenshots_dir.exists():
                        screenshots = sorted([f for f in screenshots_dir.glob("*.jpg")
                                            if not f.stem.endswith('_thumb') and not f.stem.endswith('_zoom')],
                                           key=lambda x: x.stat().st_mtime, reverse=True)
                        if screenshots:
                            latest_screenshot = str(screenshots[0].relative_to(_get_rabbitize_runs_dir()))

            result.append({
                "session_id": session_id,
                "port": port,
                "pid": session.get("pid"),
                "started_at": session.get("started_at"),
                "healthy": healthy,
                "has_browser_session": status.get("hasSession", False) if status else False,
                "browser_session_path": browser_session_path,
                "latest_screenshot": latest_screenshot,
                "current_url": current_state.get("initialUrl") if current_state else None,
                "phase": current_state.get("phase") if current_state else None,
                "is_processing": current_state.get("isProcessing", False) if current_state else False,
                "queue_length": current_state.get("queueLength", 0) if current_state else 0,
                "seconds_running": current_state.get("secondsRunning", 0) if current_state else 0,
            })

        # Clean up dead sessions
        for session_id in dead_sessions:
            _cleanup_session(session_id)

        return result


def _get_session(session_id: str) -> dict:
    """Get a specific session's info."""
    with _sessions_lock:
        if session_id not in _sessions:
            return None
        session = _sessions[session_id]
        return {
            "session_id": session_id,
            "port": session["port"],
            "pid": session.get("pid"),
            "started_at": session.get("started_at")
        }


# Legacy compatibility - single default session
def _ensure_rabbitize_running() -> dict:
    """Ensure at least one Rabbitize session exists (legacy compatibility)."""
    sessions = _list_sessions()
    if sessions:
        # Return the first healthy session
        return {
            "success": True,
            "running": True,
            "session_id": sessions[0]["session_id"],
            "port": sessions[0]["port"]
        }

    # Create a default session
    result = _create_session("default")
    if result.get("success"):
        return {
            "success": True,
            "running": True,
            "started": True,
            "session_id": result["session_id"],
            "port": result["port"]
        }
    return result


def _get_rabbitize_runs_dir() -> Path:
    """Get the rabbitize-runs directory path."""
    if get_config:
        config = get_config()
        return Path(config.root_dir) / "rabbitize-runs"
    return Path(_REPO_ROOT) / "rabbitize-runs"


def _get_flows_dir() -> Path:
    """Get the flows directory for saved automation flows."""
    if get_config:
        config = get_config()
        return Path(config.root_dir) / "flows"
    return Path(_REPO_ROOT) / "flows"


def _parse_session_dir(session_path: Path) -> dict:
    """Parse a session directory and extract metadata."""
    session_id = session_path.name

    # Read status.json if it exists
    status_file = session_path / "status.json"
    status_data = {}
    if status_file.exists():
        try:
            with open(status_file) as f:
                status_data = json.load(f)
        except:
            pass

    # Read commands.json if it exists
    commands_file = session_path / "commands.json"
    commands = []
    if commands_file.exists():
        try:
            with open(commands_file) as f:
                commands = json.load(f)
        except:
            pass

    # Read metrics.json if it exists (can be dict or list)
    metrics_file = session_path / "metrics.json"
    metrics = {}
    metrics_raw = None
    if metrics_file.exists():
        try:
            with open(metrics_file) as f:
                metrics_raw = json.load(f)
            # Handle both dict and list formats
            if isinstance(metrics_raw, dict):
                metrics = metrics_raw
            elif isinstance(metrics_raw, list) and len(metrics_raw) > 0:
                # List format - extract total duration from timestamps
                first_ts = metrics_raw[0].get('timestamp', 0)
                last_ts = metrics_raw[-1].get('timestamp', 0)
                metrics = {"total_duration_ms": last_ts - first_ts}
        except:
            pass

    # Count screenshots (exclude _thumb and _zoom variants)
    screenshots_dir = session_path / "screenshots"
    screenshot_count = 0
    screenshot_files = []
    if screenshots_dir.exists():
        all_screenshots = sorted(screenshots_dir.glob("*.jpg"))
        # Filter out _thumb and _zoom variants for main count
        screenshot_files = [f for f in all_screenshots
                           if not f.stem.endswith('_thumb') and not f.stem.endswith('_zoom')]
        screenshot_count = len(screenshot_files)

    # Get thumbnail (last main screenshot, prefer _zoom variant if exists)
    thumbnail = None
    if screenshot_files:
        last_screenshot = screenshot_files[-1]
        zoom_variant = last_screenshot.parent / f"{last_screenshot.stem}_zoom.jpg"
        if zoom_variant.exists():
            thumbnail = str(zoom_variant.relative_to(_get_rabbitize_runs_dir()))
        else:
            thumbnail = str(last_screenshot.relative_to(_get_rabbitize_runs_dir()))

    # Check for video (look in video/ subdirectory)
    video_dir = session_path / "video"
    has_video = False
    video_size = 0
    video_filename = None
    if video_dir.exists() and video_dir.is_dir():
        # Look for webm or mp4 files, prefer session.webm/mp4
        video_files = list(video_dir.glob("*.webm")) + list(video_dir.glob("*.mp4"))
        if video_files:
            # Prefer session.webm or session.mp4
            preferred = [f for f in video_files if f.stem == 'session']
            video_file = preferred[0] if preferred else video_files[0]
            has_video = True
            video_size = video_file.stat().st_size
            video_filename = video_file.name

    # Get DOM snapshots count
    dom_snapshots_dir = session_path / "dom_snapshots"
    dom_snapshot_count = 0
    if dom_snapshots_dir.exists():
        dom_snapshot_count = len(list(dom_snapshots_dir.glob("*.md")))

    # Get timestamps from directory
    created_at = datetime.fromtimestamp(session_path.stat().st_ctime).isoformat()
    modified_at = datetime.fromtimestamp(session_path.stat().st_mtime).isoformat()

    # Extract client_id and test_id from path
    # Structure: rabbitize-runs/{client_id}/{test_id}/{session_id}
    parts = session_path.parts
    runs_idx = parts.index("rabbitize-runs") if "rabbitize-runs" in parts else -1
    client_id = parts[runs_idx + 1] if runs_idx >= 0 and len(parts) > runs_idx + 1 else "unknown"
    test_id = parts[runs_idx + 2] if runs_idx >= 0 and len(parts) > runs_idx + 2 else "unknown"

    return {
        "session_id": session_id,
        "client_id": client_id,
        "test_id": test_id,
        "path": str(session_path.relative_to(_get_rabbitize_runs_dir())),
        "status": status_data.get("status", "unknown"),
        "initial_url": status_data.get("initialUrl", status_data.get("url", "")),
        "final_url": status_data.get("finalUrl", ""),
        "command_count": len(commands),
        "screenshot_count": screenshot_count,
        "dom_snapshot_count": dom_snapshot_count,
        "has_video": has_video,
        "video": video_filename,
        "video_size": video_size,
        "thumbnail": thumbnail,
        "duration_ms": metrics.get("total_duration_ms", 0),
        "created_at": created_at,
        "modified_at": modified_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Session Listing & Details
# ─────────────────────────────────────────────────────────────────────────────

@browser_sessions_bp.route('/api/browser-sessions', methods=['GET'])
def list_browser_sessions():
    """
    List all browser sessions from rabbitize-runs/.

    Query params:
    - client_id: Filter by client
    - test_id: Filter by test
    - limit: Max results (default 50)
    - offset: Pagination offset

    Returns list of session metadata.
    """
    runs_dir = _get_rabbitize_runs_dir()

    if not runs_dir.exists():
        return jsonify({"sessions": [], "count": 0, "message": "No browser sessions found"})

    client_id_filter = request.args.get('client_id')
    test_id_filter = request.args.get('test_id')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))

    sessions = []

    # Walk the directory structure: rabbitize-runs/{client_id}/{test_id}/{session_id}
    for client_dir in runs_dir.iterdir():
        if not client_dir.is_dir():
            continue
        if client_id_filter and client_dir.name != client_id_filter:
            continue

        for test_dir in client_dir.iterdir():
            if not test_dir.is_dir():
                continue
            if test_id_filter and test_dir.name != test_id_filter:
                continue

            for session_dir in test_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                try:
                    session_info = _parse_session_dir(session_dir)
                    sessions.append(session_info)
                except Exception as e:
                    print(f"Error parsing session {session_dir}: {e}")
                    continue

    # Sort by modified time (newest first)
    sessions.sort(key=lambda x: x["modified_at"], reverse=True)

    # Apply pagination
    total_count = len(sessions)
    sessions = sessions[offset:offset + limit]

    return jsonify({
        "sessions": sessions,
        "count": total_count,
        "limit": limit,
        "offset": offset
    })


@browser_sessions_bp.route('/api/browser-sessions/<path:session_path>', methods=['GET'])
def get_browser_session(session_path):
    """
    Get detailed information about a specific browser session.

    Returns full session data including commands, metrics, and file lists.
    """
    runs_dir = _get_rabbitize_runs_dir()
    session_dir = runs_dir / session_path

    if not session_dir.exists():
        return jsonify({"error": f"Session not found: {session_path}"}), 404

    # Get basic info
    session_info = _parse_session_dir(session_dir)

    # Load full commands list
    commands_file = session_dir / "commands.json"
    commands = []
    if commands_file.exists():
        try:
            with open(commands_file) as f:
                commands = json.load(f)
        except:
            pass

    # Load full metrics (can be dict or list)
    metrics_file = session_dir / "metrics.json"
    metrics = {}
    if metrics_file.exists():
        try:
            with open(metrics_file) as f:
                metrics_raw = json.load(f)
            # Handle both dict and list formats
            if isinstance(metrics_raw, dict):
                metrics = metrics_raw
            elif isinstance(metrics_raw, list):
                # Keep raw list for detailed view, add computed duration
                first_ts = metrics_raw[0].get('timestamp', 0) if metrics_raw else 0
                last_ts = metrics_raw[-1].get('timestamp', 0) if metrics_raw else 0
                metrics = {
                    "total_duration_ms": last_ts - first_ts,
                    "snapshots": metrics_raw
                }
        except:
            pass

    # List all screenshots with metadata (filter out _thumb and _zoom variants)
    screenshots_dir = session_dir / "screenshots"
    screenshots = []
    if screenshots_dir.exists():
        for img_file in sorted(screenshots_dir.glob("*.jpg")):
            # Skip _thumb and _zoom variants in main list
            if img_file.stem.endswith('_thumb') or img_file.stem.endswith('_zoom'):
                continue
            # Check for zoom variant to use as thumbnail
            zoom_variant = img_file.parent / f"{img_file.stem}_zoom.jpg"
            screenshots.append({
                "filename": img_file.name,
                "path": str(img_file.relative_to(runs_dir)),
                "size": img_file.stat().st_size,
                "modified": datetime.fromtimestamp(img_file.stat().st_mtime).isoformat(),
                "thumbnail": zoom_variant.name if zoom_variant.exists() else img_file.name
            })

    # List DOM snapshots
    dom_snapshots_dir = session_dir / "dom_snapshots"
    dom_snapshots = []
    if dom_snapshots_dir.exists():
        for md_file in sorted(dom_snapshots_dir.glob("*.md")):
            dom_snapshots.append({
                "filename": md_file.name,
                "path": str(md_file.relative_to(runs_dir)),
                "size": md_file.stat().st_size
            })

    # List DOM coords files
    dom_coords_dir = session_dir / "dom_coords"
    dom_coords = []
    if dom_coords_dir.exists():
        for json_file in sorted(dom_coords_dir.glob("*.json")):
            dom_coords.append({
                "filename": json_file.name,
                "path": str(json_file.relative_to(runs_dir)),
                "size": json_file.stat().st_size
            })

    session_info.update({
        "commands": commands,
        "metrics": metrics,
        "screenshots": screenshots,
        "dom_snapshots": dom_snapshots,
        "dom_coords": dom_coords
    })

    return jsonify(session_info)


@browser_sessions_bp.route('/api/browser-sessions/<path:session_path>', methods=['DELETE'])
def delete_browser_session(session_path):
    """Delete a browser session and all its artifacts."""
    import shutil

    runs_dir = _get_rabbitize_runs_dir()
    session_dir = runs_dir / session_path

    if not session_dir.exists():
        return jsonify({"error": f"Session not found: {session_path}"}), 404

    try:
        shutil.rmtree(session_dir)
        return jsonify({"success": True, "message": f"Deleted session: {session_path}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Media File Serving
# ─────────────────────────────────────────────────────────────────────────────

@browser_sessions_bp.route('/api/browser-media/<path:file_path>')
def serve_browser_media(file_path):
    """
    Serve media files (screenshots, videos) from rabbitize-runs/.

    Supports:
    - Images (jpg, png, gif)
    - Videos (webm, mp4)
    - JSON files
    - Markdown files
    """
    runs_dir = _get_rabbitize_runs_dir()
    full_path = runs_dir / file_path

    if not full_path.exists():
        return jsonify({"error": f"File not found: {file_path}"}), 404

    # Security: ensure path is within runs_dir
    try:
        full_path.resolve().relative_to(runs_dir.resolve())
    except ValueError:
        return jsonify({"error": "Invalid path"}), 403

    # Determine content type
    suffix = full_path.suffix.lower()
    content_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webm': 'video/webm',
        '.mp4': 'video/mp4',
        '.json': 'application/json',
        '.md': 'text/markdown',
    }

    content_type = content_types.get(suffix, 'application/octet-stream')

    return send_file(full_path, mimetype=content_type)


@browser_sessions_bp.route('/api/browser-sessions/<path:session_path>/dom-snapshot/<int:index>')
def get_dom_snapshot(session_path, index):
    """Get a specific DOM snapshot content."""
    runs_dir = _get_rabbitize_runs_dir()
    session_dir = runs_dir / session_path
    dom_snapshots_dir = session_dir / "dom_snapshots"

    if not dom_snapshots_dir.exists():
        return jsonify({"error": "No DOM snapshots"}), 404

    snapshots = sorted(dom_snapshots_dir.glob("*.md"))
    if index >= len(snapshots):
        return jsonify({"error": f"Snapshot index {index} out of range"}), 404

    snapshot_file = snapshots[index]
    content = snapshot_file.read_text()

    return jsonify({
        "filename": snapshot_file.name,
        "index": index,
        "total": len(snapshots),
        "content": content
    })


@browser_sessions_bp.route('/api/browser-sessions/<path:session_path>/dom-coords/<int:index>')
def get_dom_coords(session_path, index):
    """Get a specific DOM coords JSON file."""
    runs_dir = _get_rabbitize_runs_dir()
    session_dir = runs_dir / session_path
    dom_coords_dir = session_dir / "dom_coords"

    if not dom_coords_dir.exists():
        return jsonify({"error": "No DOM coords"}), 404

    coords_files = sorted(dom_coords_dir.glob("*.json"))
    if index >= len(coords_files):
        return jsonify({"error": f"Coords index {index} out of range"}), 404

    coords_file = coords_files[index]
    content = json.loads(coords_file.read_text())

    return jsonify({
        "filename": coords_file.name,
        "index": index,
        "total": len(coords_files),
        "coords": content
    })


# ─────────────────────────────────────────────────────────────────────────────
# Live Session Management (MJPEG Proxy)
# ─────────────────────────────────────────────────────────────────────────────

@browser_sessions_bp.route('/api/browser-live/sessions')
def list_live_sessions():
    """
    List currently active browser sessions.

    Queries the BrowserSessionManager for running sessions.
    """
    try:
        from rvbbit.browser_manager import get_browser_manager
        manager = get_browser_manager()

        sessions = []
        for session_id in manager.list_sessions():
            session = manager.get_session(session_id)
            if session:
                sessions.append({
                    "session_id": session_id,
                    "port": session.port,
                    "base_url": session.base_url,
                    "is_alive": session.is_alive,
                    "artifacts": {
                        "base_path": session.artifacts.base_path if session.artifacts else None,
                        "screenshots": session.artifacts.screenshots if session.artifacts else None,
                        "video": session.artifacts.video if session.artifacts else None,
                    } if session.artifacts else None,
                    "streams": {
                        "mjpeg": session.streams.mjpeg if session.streams else None,
                        "viewer": session.streams.viewer if session.streams else None,
                    } if session.streams else None
                })

        return jsonify({"sessions": sessions, "count": len(sessions)})
    except ImportError:
        return jsonify({"sessions": [], "count": 0, "message": "Browser manager not available"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-live/stream/<session_id>')
def proxy_mjpeg_stream(session_id):
    """
    Proxy the MJPEG stream from a live browser session.

    This allows the dashboard to display real-time browser view.
    """
    try:
        from rvbbit.browser_manager import get_browser_manager
        import requests

        manager = get_browser_manager()
        session = manager.get_session(session_id)

        if not session:
            return jsonify({"error": f"Session not found: {session_id}"}), 404

        if not session.is_alive:
            return jsonify({"error": "Session is not active"}), 400

        # Get the MJPEG stream URL from the Rabbitize server
        if session.streams and session.streams.mjpeg:
            stream_url = f"{session.base_url}{session.streams.mjpeg}"
        else:
            # Default stream path
            stream_url = f"{session.base_url}/stream/windlass/{session_id}/{session_id}"

        def generate():
            """Generator that proxies the MJPEG stream."""
            try:
                with requests.get(stream_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        yield chunk
            except Exception as e:
                print(f"Stream error: {e}")

        return Response(
            stream_with_context(generate()),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
    except ImportError:
        return jsonify({"error": "Browser manager not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-live/screenshot/<session_id>')
def get_live_screenshot(session_id):
    """Get the current screenshot from a live browser session."""
    try:
        from rvbbit.browser_manager import get_browser_manager

        manager = get_browser_manager()
        session = manager.get_session(session_id)

        if not session or not session.artifacts:
            return jsonify({"error": f"Session not found or no artifacts: {session_id}"}), 404

        screenshots_dir = Path(session.artifacts.screenshots)
        if not screenshots_dir.exists():
            return jsonify({"error": "No screenshots directory"}), 404

        screenshots = sorted(screenshots_dir.glob("*.jpg"), key=lambda x: x.stat().st_mtime)
        if not screenshots:
            return jsonify({"error": "No screenshots"}), 404

        latest = screenshots[-1]
        return send_file(latest, mimetype='image/jpeg')
    except ImportError:
        return jsonify({"error": "Browser manager not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Flow Management
# ─────────────────────────────────────────────────────────────────────────────

@browser_sessions_bp.route('/api/browser-flows', methods=['GET'])
def list_flows():
    """List all saved automation flows."""
    flows_dir = _get_flows_dir()

    if not flows_dir.exists():
        return jsonify({"flows": [], "count": 0})

    flows = []
    for flow_file in flows_dir.glob("*.json"):
        try:
            with open(flow_file) as f:
                flow_data = json.load(f)
                flows.append({
                    "flow_id": flow_data.get("flow_id", flow_file.stem),
                    "description": flow_data.get("description", ""),
                    "version": flow_data.get("version", "1.0.0"),
                    "initial_url": flow_data.get("initial_url", ""),
                    "step_count": len(flow_data.get("steps", [])),
                    "parameter_count": len(flow_data.get("parameters", {})),
                    "created_at": flow_data.get("created_at", ""),
                    "filename": flow_file.name
                })
        except Exception as e:
            print(f"Error parsing flow {flow_file}: {e}")
            continue

    # Sort by created_at (newest first)
    flows.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return jsonify({"flows": flows, "count": len(flows)})


@browser_sessions_bp.route('/api/browser-flows/<flow_id>', methods=['GET'])
def get_flow(flow_id):
    """Get a specific flow definition."""
    flows_dir = _get_flows_dir()
    flow_file = flows_dir / f"{flow_id}.json"

    if not flow_file.exists():
        return jsonify({"error": f"Flow not found: {flow_id}"}), 404

    try:
        with open(flow_file) as f:
            flow_data = json.load(f)
        return jsonify(flow_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-flows', methods=['POST'])
def create_flow():
    """Create a new automation flow."""
    flows_dir = _get_flows_dir()
    flows_dir.mkdir(parents=True, exist_ok=True)

    flow_data = request.get_json()
    if not flow_data:
        return jsonify({"error": "No flow data provided"}), 400

    flow_id = flow_data.get("flow_id")
    if not flow_id:
        return jsonify({"error": "flow_id is required"}), 400

    # Add timestamps
    now = datetime.utcnow().isoformat() + "Z"
    flow_data["created_at"] = flow_data.get("created_at", now)
    flow_data["updated_at"] = now

    flow_file = flows_dir / f"{flow_id}.json"

    try:
        with open(flow_file, 'w') as f:
            json.dump(flow_data, f, indent=2)
        return jsonify({"success": True, "flow_id": flow_id, "path": str(flow_file)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-flows/<flow_id>', methods=['PUT'])
def update_flow(flow_id):
    """Update an existing flow."""
    flows_dir = _get_flows_dir()
    flow_file = flows_dir / f"{flow_id}.json"

    if not flow_file.exists():
        return jsonify({"error": f"Flow not found: {flow_id}"}), 404

    flow_data = request.get_json()
    if not flow_data:
        return jsonify({"error": "No flow data provided"}), 400

    # Preserve creation time, update modified time
    try:
        with open(flow_file) as f:
            existing = json.load(f)
            flow_data["created_at"] = existing.get("created_at")
    except:
        pass

    flow_data["updated_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        with open(flow_file, 'w') as f:
            json.dump(flow_data, f, indent=2)
        return jsonify({"success": True, "flow_id": flow_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-flows/<flow_id>', methods=['DELETE'])
def delete_flow(flow_id):
    """Delete a flow."""
    flows_dir = _get_flows_dir()
    flow_file = flows_dir / f"{flow_id}.json"

    if not flow_file.exists():
        return jsonify({"error": f"Flow not found: {flow_id}"}), 404

    try:
        flow_file.unlink()
        return jsonify({"success": True, "message": f"Deleted flow: {flow_id}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_sessions_bp.route('/api/browser-flows/<flow_id>/register', methods=['POST'])
def register_flow_as_tool(flow_id):
    """
    Register a flow as a RVBBIT tackle (tool).

    This creates a dynamic tool that can be used in cascades.
    """
    flows_dir = _get_flows_dir()
    flow_file = flows_dir / f"{flow_id}.json"

    if not flow_file.exists():
        return jsonify({"error": f"Flow not found: {flow_id}"}), 404

    try:
        with open(flow_file) as f:
            flow_data = json.load(f)

        # Import the flow registration function
        from rvbbit.rabbitize_flows import register_flow_as_tackle

        tool_name = register_flow_as_tackle(flow_data)

        return jsonify({
            "success": True,
            "tool_name": tool_name,
            "message": f"Flow '{flow_id}' registered as tool '{tool_name}'"
        })
    except ImportError:
        return jsonify({"error": "Flow registration not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Rabbitize Server Management API
# =============================================================================

@browser_sessions_bp.route('/api/rabbitize/health', methods=['GET'])
def rabbitize_health():
    """Get overall Rabbitize status and list of active sessions."""
    sessions = _list_sessions()
    return jsonify({
        "sessions": sessions,
        "count": len(sessions),
        "max_sessions": RABBITIZE_MAX_SESSIONS,
        "port_range": f"{RABBITIZE_BASE_PORT}-{RABBITIZE_BASE_PORT + RABBITIZE_MAX_SESSIONS - 1}"
    })


@browser_sessions_bp.route('/api/rabbitize/sessions', methods=['GET'])
def list_rabbitize_sessions():
    """List all active Rabbitize sessions."""
    sessions = _list_sessions()
    return jsonify({"sessions": sessions, "count": len(sessions)})


@browser_sessions_bp.route('/api/rabbitize/sessions/<session_id>', methods=['DELETE'])
def kill_rabbitize_session(session_id):
    """Kill a specific Rabbitize session."""
    result = _kill_session(session_id)
    return jsonify(result), 200 if result.get("success") else 404


@browser_sessions_bp.route('/api/rabbitize/sessions', methods=['DELETE'])
def kill_all_rabbitize_sessions():
    """Kill all Rabbitize sessions."""
    result = _kill_all_sessions()
    return jsonify(result)


# =============================================================================
# Unified Session Registry Endpoints
# =============================================================================
# These endpoints work with the shared session registry that tracks sessions
# from both the UI and from RVBBIT cascades.

@browser_sessions_bp.route('/api/rabbitize/registry/sessions', methods=['GET'])
def list_registry_sessions():
    """
    List all sessions from the unified registry.

    This includes sessions created by:
    - UI (FlowBuilder, etc.)
    - Cascades with browser config
    - CLI tools

    Query params:
    - check_health: If 'true', perform health checks (default: true)
    - cleanup_dead: If 'true', remove dead sessions (default: true)
    """
    if not get_session_registry:
        return jsonify({"error": "Session registry not available"}), 500

    check_health = request.args.get('check_health', 'true').lower() == 'true'
    cleanup_dead = request.args.get('cleanup_dead', 'true').lower() == 'true'

    try:
        registry = get_session_registry(_REPO_ROOT)
        sessions = registry.list_sessions(check_health=check_health, cleanup_dead=cleanup_dead)

        # Enrich with additional status info
        result = []
        for session in sessions:
            info = session.to_dict()

            # Get current status from the Rabbitize server
            if session.healthy:
                status = registry.get_session_status(session.session_id)
                if status:
                    current_state = status.get("currentState", {})
                    info["current_url"] = current_state.get("initialUrl")
                    info["is_processing"] = current_state.get("isProcessing", False)
                    info["queue_length"] = current_state.get("queueLength", 0)
                    info["has_browser_session"] = status.get("hasSession", False)

                    # Get latest screenshot path
                    if status.get("hasSession"):
                        client_id = current_state.get("clientId", "unknown")
                        test_id = current_state.get("testId", "unknown")
                        browser_session_id = current_state.get("sessionId")
                        if browser_session_id:
                            info["browser_session_path"] = f"{client_id}/{test_id}/{browser_session_id}"
                            screenshots_dir = _get_rabbitize_runs_dir() / client_id / test_id / browser_session_id / "screenshots"
                            if screenshots_dir.exists():
                                screenshots = sorted([f for f in screenshots_dir.glob("*.jpg")
                                                    if not f.stem.endswith('_thumb') and not f.stem.endswith('_zoom')],
                                                   key=lambda x: x.stat().st_mtime, reverse=True)
                                if screenshots:
                                    info["latest_screenshot"] = str(screenshots[0].relative_to(_get_rabbitize_runs_dir()))

            result.append(info)

        return jsonify({"sessions": result, "count": len(result)})

    except Exception as e:
        return jsonify({"error": f"Failed to list sessions: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/registry/sessions/<session_id>', methods=['GET'])
def get_registry_session(session_id):
    """Get detailed info for a specific session from the registry."""
    if not get_session_registry:
        return jsonify({"error": "Session registry not available"}), 500

    try:
        registry = get_session_registry(_REPO_ROOT)
        session = registry.get(session_id)

        if not session:
            return jsonify({"error": f"Session not found: {session_id}"}), 404

        info = session.to_dict()

        # Get full status from the Rabbitize server
        status = registry.get_session_status(session_id)
        if status:
            info["rabbitize_status"] = status

        return jsonify(info)

    except Exception as e:
        return jsonify({"error": f"Failed to get session: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/registry/sessions/<session_id>', methods=['DELETE'])
def kill_registry_session(session_id):
    """
    Kill a session by ID (works for both UI and cascade sessions).

    This will:
    1. Send /end to the Rabbitize server to finalize video
    2. Kill the process
    3. Remove from registry
    """
    if not get_session_registry:
        return jsonify({"error": "Session registry not available"}), 500

    try:
        registry = get_session_registry(_REPO_ROOT)
        session = registry.get(session_id)

        if not session:
            return jsonify({"error": f"Session not found: {session_id}"}), 404

        # Try to gracefully end the Rabbitize session
        try:
            requests.post(f"http://localhost:{session.port}/end", timeout=10)
        except:
            pass

        # Kill the process
        if session.pid:
            try:
                os.kill(session.pid, 9)
            except:
                pass

        # Remove from registry
        registry.unregister(session_id)

        # Also remove from local _sessions if present
        with _sessions_lock:
            if session_id in _sessions:
                del _sessions[session_id]

        return jsonify({"success": True, "message": f"Session {session_id} killed"})

    except Exception as e:
        return jsonify({"error": f"Failed to kill session: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/registry/orphans', methods=['GET'])
def discover_orphan_sessions():
    """
    Discover Rabbitize instances running on ports that aren't in the registry.

    Useful for finding sessions started by cascades that haven't been registered,
    or from previous runs that weren't properly cleaned up.
    """
    if not get_session_registry:
        return jsonify({"error": "Session registry not available"}), 500

    try:
        registry = get_session_registry(_REPO_ROOT)
        orphans = registry.discover_orphans(port_range=(13000, 14000))

        return jsonify({"orphans": orphans, "count": len(orphans)})

    except Exception as e:
        return jsonify({"error": f"Failed to discover orphans: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/registry/orphans/<int:port>', methods=['POST'])
def adopt_orphan_session(port):
    """
    Adopt an orphan Rabbitize instance into the registry.

    This is useful for "recovering" sessions that were started by cascades
    or other processes that the UI wasn't aware of.
    """
    if not get_session_registry:
        return jsonify({"error": "Session registry not available"}), 500

    try:
        registry = get_session_registry(_REPO_ROOT)
        session = registry.adopt_orphan(port, source='adopted')

        if not session:
            return jsonify({"error": f"Could not adopt orphan on port {port}"}), 400

        return jsonify({"success": True, "session": session.to_dict()})

    except Exception as e:
        return jsonify({"error": f"Failed to adopt orphan: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/restart', methods=['POST'])
def restart_rabbitize():
    """Kill all sessions and start a fresh one."""
    _kill_all_sessions()

    # Also kill any orphaned processes on the port range
    for port in range(RABBITIZE_BASE_PORT, RABBITIZE_BASE_PORT + RABBITIZE_MAX_SESSIONS):
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split('\n'):
                    try:
                        os.kill(int(pid), 9)
                    except:
                        pass
        except:
            pass

    time.sleep(2)

    # Create a fresh default session
    create_result = _create_session("default")
    return jsonify(create_result), 200 if create_result.get("success") else 500


@browser_sessions_bp.route('/api/rabbitize/session/start', methods=['POST'])
def proxy_session_start():
    """
    Start a browser session via Rabbitize.
    Creates a new Rabbitize instance if needed.
    """
    data = request.json or {}
    dashboard_session_id = data.pop("dashboard_session_id", None)

    # Create or get a session
    if dashboard_session_id:
        session_result = _create_session(dashboard_session_id)
    else:
        session_result = _ensure_rabbitize_running()

    if not session_result.get("success"):
        return jsonify(session_result), 500

    port = session_result.get("port")
    session_id = session_result.get("session_id")

    try:
        # Forward the request to the specific Rabbitize instance
        resp = requests.post(
            f"http://localhost:{port}/start",
            json=data,
            timeout=30
        )
        result = resp.json()
        # Add our session info to the response
        result["dashboard_session_id"] = session_id
        result["dashboard_port"] = port
        return jsonify(result), resp.status_code
    except requests.exceptions.Timeout:
        return jsonify({"error": "Rabbitize request timed out", "session_id": session_id}), 504
    except Exception as e:
        return jsonify({"error": f"Failed to start session: {str(e)}", "session_id": session_id}), 500


@browser_sessions_bp.route('/api/rabbitize/session/execute', methods=['POST'])
def proxy_session_execute():
    """Execute a command in the browser session."""
    data = request.json or {}
    dashboard_session_id = data.pop("dashboard_session_id", "default")

    session = _get_session(dashboard_session_id)
    if not session:
        # Try to find any active session
        sessions = _list_sessions()
        if not sessions:
            return jsonify({"error": "No active Rabbitize sessions"}), 503
        session = sessions[0]

    port = session["port"]

    try:
        resp = requests.post(
            f"http://localhost:{port}/execute",
            json=data,
            timeout=60
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.Timeout:
        return jsonify({"error": "Command execution timed out"}), 504
    except Exception as e:
        return jsonify({"error": f"Failed to execute command: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/session/end', methods=['POST'])
def proxy_session_end():
    """End the browser session."""
    data = request.json or {}
    dashboard_session_id = data.get("dashboard_session_id", "default")

    session = _get_session(dashboard_session_id)
    if not session:
        sessions = _list_sessions()
        if not sessions:
            return jsonify({"error": "No active Rabbitize sessions"}), 503
        session = sessions[0]

    port = session["port"]

    try:
        resp = requests.post(f"http://localhost:{port}/end", timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": f"Failed to end session: {str(e)}"}), 500


@browser_sessions_bp.route('/api/rabbitize/stream/<session_id>/<path:stream_path>')
def proxy_stream(session_id, stream_path):
    """
    Proxy the MJPEG stream from a specific Rabbitize session.
    URL format: /api/rabbitize/stream/{dashboard_session_id}/{clientId}/{testId}/{sessionId}
    """
    session = _get_session(session_id)
    if not session:
        # Try to find any active session
        sessions = _list_sessions()
        if not sessions:
            return jsonify({"error": "No active Rabbitize sessions"}), 503
        session = sessions[0]

    port = session["port"]

    def generate():
        try:
            with requests.get(
                f"http://localhost:{port}/stream/{stream_path}",
                stream=True,
                timeout=None
            ) as resp:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"Stream error: {e}")

    return Response(
        stream_with_context(generate()),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )


# Legacy stream endpoint (for backwards compatibility)
@browser_sessions_bp.route('/api/rabbitize/stream-legacy/<path:stream_path>')
def proxy_stream_legacy(stream_path):
    """Legacy stream proxy - uses first available session."""
    sessions = _list_sessions()
    if not sessions:
        return jsonify({"error": "No active Rabbitize sessions"}), 503

    port = sessions[0]["port"]

    def generate():
        try:
            with requests.get(
                f"http://localhost:{port}/stream/{stream_path}",
                stream=True,
                timeout=None
            ) as resp:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"Stream error: {e}")

    return Response(
        stream_with_context(generate()),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )
