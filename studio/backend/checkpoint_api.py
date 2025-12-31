"""
API endpoints for Human-in-the-Loop (HITL) Checkpoint management.

Provides REST API for:
- Listing pending checkpoints
- Getting checkpoint details
- Responding to checkpoints
- Cancelling checkpoints
- Signaling audibles (real-time feedback injection)
"""
import json
import os
import re
import sys
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request

# Add parent directory to path to import rvbbit
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_RVBBIT_DIR = os.path.join(_REPO_ROOT, "rvbbit")
if _RVBBIT_DIR not in sys.path:
    sys.path.insert(0, _RVBBIT_DIR)

try:
    from rvbbit.checkpoints import get_checkpoint_manager, CheckpointStatus
except ImportError as e:
    print(f"Warning: Could not import rvbbit checkpoint modules: {e}")
    get_checkpoint_manager = None
    CheckpointStatus = None

# Note: Checkpoint caching removed - CheckpointManager singleton handles all state

checkpoint_bp = Blueprint('checkpoints', __name__)

# Store annotated screenshots for checkpoints (in-memory, keyed by checkpoint_id)
_annotated_screenshots = {}  # checkpoint_id -> {"url": ..., "path": ..., "timestamp": ...}

# ========== AUDIBLE SIGNAL STORAGE ==========
# Simple in-memory storage for audible signals
# The runner polls this to check if an audible was requested
# This is session-specific to support multiple concurrent cascades

_audible_signals = {}  # session_id -> {"signaled": True/False, "timestamp": datetime}
_audible_lock = threading.Lock()


def signal_audible_for_session(session_id: str) -> bool:
    """
    Signal that an audible should be triggered for a session.

    Args:
        session_id: The session to signal

    Returns:
        True if signal was set, False if already signaled
    """
    with _audible_lock:
        existing = _audible_signals.get(session_id, {})
        if existing.get("signaled"):
            return False  # Already signaled

        _audible_signals[session_id] = {
            "signaled": True,
            "timestamp": datetime.now().isoformat()
        }
        return True


def check_audible_signal(session_id: str) -> bool:
    """
    Check if an audible signal is pending for a session.

    Args:
        session_id: The session to check

    Returns:
        True if a signal is pending
    """
    with _audible_lock:
        signal = _audible_signals.get(session_id, {})
        return signal.get("signaled", False)


def clear_audible_signal(session_id: str):
    """
    Clear the audible signal for a session.

    Args:
        session_id: The session to clear
    """
    with _audible_lock:
        if session_id in _audible_signals:
            _audible_signals[session_id]["signaled"] = False


def get_audible_status(session_id: str) -> dict:
    """
    Get the audible signal status for a session.

    Args:
        session_id: The session to check

    Returns:
        Status dict with signaled, timestamp, etc.
    """
    with _audible_lock:
        return _audible_signals.get(session_id, {"signaled": False})


# Get IMAGE_DIR from environment or default
_DEFAULT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../.."))
RVBBIT_ROOT = os.path.abspath(os.getenv("RVBBIT_ROOT", _DEFAULT_ROOT))
IMAGE_DIR = os.path.abspath(os.getenv("RVBBIT_IMAGE_DIR", os.path.join(RVBBIT_ROOT, "images")))


def resolve_image_paths_to_urls(ui_spec, session_id):
    """
    Recursively resolve file paths to API URLs in a UI spec.

    Transforms:
    - Absolute paths like /path/to/images/session_id/cell/image_0.png
    - Relative paths like cell/image_0.png

    To API URLs like /api/images/session_id/cell/image_0.png
    """
    if not ui_spec or not isinstance(ui_spec, dict):
        return ui_spec

    # Deep copy to avoid modifying original
    spec = json.loads(json.dumps(ui_spec))

    def resolve_path(path):
        """Convert a file path to an API URL."""
        if not path or not isinstance(path, str):
            return path

        # Skip if already a URL
        if path.startswith('/api/') or path.startswith('http://') or path.startswith('https://'):
            return path

        # Skip base64 data URLs
        if path.startswith('data:'):
            return path

        # If it's an absolute path, extract the relative part after session_id
        if os.path.isabs(path):
            # Look for session_id in the path
            # Pattern: .../images/{session_id}/...
            match = re.search(rf'{re.escape(session_id)}[/\\](.+)$', path)
            if match:
                rel_path = match.group(1).replace('\\', '/')
                return f'/api/images/{session_id}/{rel_path}'
            # If session_id not found, try to use the last two path components
            parts = path.replace('\\', '/').split('/')
            if len(parts) >= 2:
                rel_path = '/'.join(parts[-2:])
                return f'/api/images/{session_id}/{rel_path}'

        # Relative path - just prepend the API prefix
        return f'/api/images/{session_id}/{path}'

    def process_section(section):
        """Process a single section, resolving image paths."""
        if not isinstance(section, dict):
            return section

        section_type = section.get('type')

        # Handle image sections
        if section_type == 'image':
            if 'src' in section:
                section['src'] = resolve_path(section['src'])
            if 'url' in section:
                section['url'] = resolve_path(section['url'])

        # Handle card_grid sections with images in items
        if section_type == 'card_grid' and 'items' in section:
            for item in section.get('items', []):
                if isinstance(item, dict) and 'image' in item:
                    item['image'] = resolve_path(item['image'])

        # Handle comparison sections with images
        if section_type == 'comparison' and 'items' in section:
            for item in section.get('items', []):
                if isinstance(item, dict) and 'image' in item:
                    item['image'] = resolve_path(item['image'])

        # Handle nested sections (accordion, tabs)
        if section_type == 'accordion' and 'items' in section:
            for item in section.get('items', []):
                if isinstance(item, dict) and 'content' in item:
                    if isinstance(item['content'], dict):
                        item['content'] = process_section(item['content'])
                    elif isinstance(item['content'], list):
                        item['content'] = [process_section(s) for s in item['content']]

        if section_type == 'tabs' and 'tabs' in section:
            for tab in section.get('tabs', []):
                if isinstance(tab, dict) and 'content' in tab:
                    if isinstance(tab['content'], dict):
                        tab['content'] = process_section(tab['content'])
                    elif isinstance(tab['content'], list):
                        tab['content'] = [process_section(s) for s in tab['content']]

        return section

    # Process main sections
    if 'sections' in spec:
        spec['sections'] = [process_section(s) for s in spec.get('sections', [])]

    # Process layout columns
    if 'columns' in spec:
        for col in spec.get('columns', []):
            if isinstance(col, dict) and 'sections' in col:
                col['sections'] = [process_section(s) for s in col.get('sections', [])]

    # Handle legacy image field (for simple UI specs)
    if 'image' in spec:
        spec['image'] = resolve_path(spec['image'])

    # Handle images array at top level
    if 'images' in spec and isinstance(spec['images'], list):
        spec['images'] = [resolve_path(img) if isinstance(img, str) else img for img in spec['images']]

    return spec


@checkpoint_bp.route('/api/checkpoints', methods=['GET'])
def list_checkpoints():
    """
    List checkpoints.

    Query params:
    - session_id: Optional filter by session ID
    - include_all: If true and session_id provided, return ALL checkpoints (pending + responded)
                   Default: false (returns only pending checkpoints)

    Returns:
    - List of checkpoint objects with UI specs
    """
    if not get_checkpoint_manager:
        return jsonify({"error": "Checkpoint system not available"}), 500

    session_id = request.args.get('session_id')
    include_all = request.args.get('include_all', 'false').lower() == 'true'

    try:
        cm = get_checkpoint_manager()

        # If session_id provided and include_all=true, get ALL checkpoints for timeline
        # Otherwise, get only pending checkpoints (backward compatible)
        if session_id and include_all:
            #print(f"[Checkpoint API] Fetching ALL checkpoints for session {session_id}")
            pending = cm.get_all_checkpoints(session_id)
        else:
            #print(f"[Checkpoint API] Fetching pending checkpoints, session_id filter={session_id}")
            pending = cm.get_pending_checkpoints(session_id)
        #print(f"[Checkpoint API] Found {len(pending)} pending checkpoints")

        checkpoints = []
        for cp in pending:
            # Skip if this checkpoint has corrupted data
            try:
                # Quick validation - can we access basic fields?
                _ = cp.ui_spec
                _ = cp.id
            except Exception as e:
                #print(f"[Checkpoint API] Skipping corrupted checkpoint: {e}")
                continue

            # DEBUG: Log what the raw UI spec looks like
            # print(f"[CHECKPOINT DEBUG] Raw ui_spec for {cp.id}:")
            # print(f"  Layout: {cp.ui_spec.get('layout') if cp.ui_spec else 'None'}")
            # print(f"  Title: {cp.ui_spec.get('title') if cp.ui_spec else 'None'}")
            if cp.ui_spec:
                # Log sections in top-level (vertical layout)
                if 'sections' in cp.ui_spec:
                    for i, sec in enumerate(cp.ui_spec.get('sections', [])):
                        sec_type = sec.get('type')
                        has_base64 = 'base64' in sec
                        has_src = 'src' in sec
                        has_cards = 'cards' in sec
                        has_options = 'options' in sec
                        #print(f"  Section {i}: type={sec_type}, has_base64={has_base64}, has_src={has_src}, has_cards={has_cards}, has_options={has_options}")
                        # if has_base64:
                        #     print(f"    base64 length: {len(sec.get('base64', ''))}")
                        # if has_src:
                        #     print(f"    src: {sec.get('src')}")
                        # if has_cards:
                        #     print(f"    cards count: {len(sec.get('cards', []))}")
                        # if has_options:
                        #     print(f"    options count: {len(sec.get('options', []))}")

                # Log sections in columns (two-column layout)
                if 'columns' in cp.ui_spec:
                    for col_idx, col in enumerate(cp.ui_spec.get('columns', [])):
                        print(f"  Column {col_idx}: width={col.get('width')}, sticky={col.get('sticky')}")
                        for i, sec in enumerate(col.get('sections', [])):
                            sec_type = sec.get('type')
                            has_base64 = 'base64' in sec
                            has_src = 'src' in sec
                            has_cards = 'cards' in sec
                            has_options = 'options' in sec
                            print(f"    Section {i}: type={sec_type}, has_base64={has_base64}, has_src={has_src}, has_cards={has_cards}, has_options={has_options}")
                            if has_base64:
                                print(f"      base64 length: {len(sec.get('base64', ''))}")
                            if has_src:
                                print(f"      src: {sec.get('src')}")

            # Resolve image paths to URLs in the UI spec
            resolved_ui_spec = resolve_image_paths_to_urls(cp.ui_spec, cp.session_id)

            checkpoints.append({
                "id": cp.id,
                "session_id": cp.session_id,
                "cascade_id": cp.cascade_id,
                "cell_name": cp.cell_name,
                "checkpoint_type": cp.checkpoint_type.value,
                "status": cp.status.value,
                "created_at": cp.created_at.isoformat() if cp.created_at else None,
                "timeout_at": cp.timeout_at.isoformat() if cp.timeout_at else None,
                "ui_spec": resolved_ui_spec,
                "cell_output": cp.cell_output,  # Full cell output for display
                "cell_output_preview": cp.cell_output[:500] if cp.cell_output else None,
                "response": cp.response,  # User response for display in timeline
                "summary": cp.summary,  # AI-generated summary
                "num_candidates": len(cp.candidate_outputs) if cp.candidate_outputs else None
            })

        return jsonify({
            "checkpoints": checkpoints,
            "count": len(checkpoints)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@checkpoint_bp.route('/api/checkpoints/<checkpoint_id>', methods=['GET'])
def get_checkpoint(checkpoint_id):
    """
    Get details for a specific checkpoint.

    Returns:
    - Full checkpoint object including UI spec and outputs
    """
    try:
        # First try to get from CheckpointManager (same-process case)
        cp = None
        if get_checkpoint_manager:
            cm = get_checkpoint_manager()
            cp = cm.get_checkpoint(checkpoint_id)

        if cp:
            # Found in CheckpointManager
            resolved_ui_spec = resolve_image_paths_to_urls(cp.ui_spec, cp.session_id)

            return jsonify({
                "id": cp.id,
                "session_id": cp.session_id,
                "cascade_id": cp.cascade_id,
                "cell_name": cp.cell_name,
                "checkpoint_type": cp.checkpoint_type.value,
                "status": cp.status.value,
                "created_at": cp.created_at.isoformat() if cp.created_at else None,
                "timeout_at": cp.timeout_at.isoformat() if cp.timeout_at else None,
                "responded_at": cp.responded_at.isoformat() if cp.responded_at else None,
                "ui_spec": resolved_ui_spec,
                "cell_output": cp.cell_output,
                "candidate_outputs": cp.candidate_outputs,
                "candidate_metadata": cp.candidate_metadata,
                "response": cp.response,
                "response_reasoning": cp.response_reasoning,
                "response_confidence": cp.response_confidence,
                "winner_index": cp.winner_index,
                "rankings": cp.rankings,
                "ratings": cp.ratings
            })

        return jsonify({"error": f"Checkpoint {checkpoint_id} not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@checkpoint_bp.route('/api/checkpoints/<checkpoint_id>/respond', methods=['POST'])
def respond_to_checkpoint_endpoint(checkpoint_id):
    """
    Submit a response to a checkpoint.

    With the blocking HITL model, this just records the response in the checkpoint manager.
    The cascade thread is blocked waiting for the response and will automatically continue.

    Request body:
    {
        "response": {...},           // Required: Response data (structure depends on UI type)
        "reasoning": "...",          // Optional: Explanation of choice
        "confidence": 0.95           // Optional: Confidence level (0-1)
    }

    Returns:
    - Updated checkpoint object
    """
    if not get_checkpoint_manager:
        return jsonify({"error": "Checkpoint system not available"}), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        response = data.get('response')
        if response is None:
            return jsonify({"error": "Response field required"}), 400

        reasoning = data.get('reasoning')
        confidence = data.get('confidence')

        # Check if there's an annotated screenshot for this checkpoint
        annotated_screenshot = _annotated_screenshots.pop(checkpoint_id, None)
        if annotated_screenshot:
            print(f"[Checkpoint API] Including annotated screenshot in response: {annotated_screenshot['url']}")
            # Add to response as metadata
            if isinstance(response, dict):
                response['_annotated_screenshot'] = annotated_screenshot
            else:
                # If response is not a dict, wrap it
                response = {
                    'value': response,
                    '_annotated_screenshot': annotated_screenshot
                }

        # Record the response - the blocking thread in the runner will pick it up
        cm = get_checkpoint_manager()
        cp = cm.respond_to_checkpoint(
            checkpoint_id=checkpoint_id,
            response=response,
            reasoning=reasoning,
            confidence=confidence
        )

        # Flush logger buffer to ensure data is visible
        try:
            from rvbbit.unified_logs import get_unified_logger
            logger = get_unified_logger()
            logger.flush()
            print(f"[CHECKPOINT] Flushed unified logger after checkpoint response")
        except Exception as flush_err:
            print(f"[CHECKPOINT] Warning: Could not flush logger: {flush_err}")

        # Invalidate UI cache
        try:
            from app import invalidate_cache
            invalidate_cache()
            print(f"[CHECKPOINT] Invalidated UI cache after checkpoint response")
        except Exception as cache_err:
            print(f"[CHECKPOINT] Warning: Could not invalidate cache: {cache_err}")

        return jsonify({
            "status": "responded",
            "checkpoint_id": checkpoint_id,
            "message": "Response recorded. Cascade will continue automatically.",
            "checkpoint": {
                "id": cp.id,
                "status": cp.status.value,
                "responded_at": cp.responded_at.isoformat() if cp.responded_at else None,
            }
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@checkpoint_bp.route('/api/checkpoints/<checkpoint_id>/cancel', methods=['POST'])
def cancel_checkpoint(checkpoint_id):
    """
    Cancel a pending checkpoint.

    Request body (optional):
    {
        "reason": "..."    // Optional: Cancellation reason
    }

    Returns:
    - Updated checkpoint object
    """
    if not get_checkpoint_manager:
        return jsonify({"error": "Checkpoint system not available"}), 500

    try:
        data = request.get_json() or {}
        reason = data.get('reason')

        cm = get_checkpoint_manager()
        cp = cm.cancel_checkpoint(checkpoint_id, reason)

        return jsonify({
            "id": cp.id,
            "status": cp.status.value,
            "responded_at": cp.responded_at.isoformat() if cp.responded_at else None,
            "message": f"Checkpoint {checkpoint_id} cancelled"
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== AUDIBLE API ENDPOINTS ==========

@checkpoint_bp.route('/api/audible/signal/<session_id>', methods=['POST'])
def signal_audible(session_id):
    """
    Signal that the user wants to call an audible (inject feedback mid-cell).

    The cascade runner will check this signal and create an AUDIBLE checkpoint
    at the next safe point (after current tool/turn completes).

    URL params:
    - session_id: The session to signal

    Returns:
    - Success status and whether signal was newly set
    """
    try:
        newly_set = signal_audible_for_session(session_id)

        # Publish SSE event to notify the runner
        try:
            from rvbbit.events import get_event_bus, Event
            bus = get_event_bus()
            bus.publish(Event(
                type="audible_signal",
                session_id=session_id,
                timestamp=datetime.now().isoformat(),
                data={"newly_set": newly_set}
            ))
        except Exception as sse_err:
            print(f"[AUDIBLE] Warning: Could not publish SSE event: {sse_err}")

        return jsonify({
            "status": "signaled",
            "session_id": session_id,
            "newly_set": newly_set,
            "message": "Audible signal sent. Cascade will pause at next safe point." if newly_set else "Audible already signaled for this session."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@checkpoint_bp.route('/api/audible/status/<session_id>', methods=['GET'])
def audible_status(session_id):
    """
    Check the audible signal status for a session.

    URL params:
    - session_id: The session to check

    Returns:
    - Current audible signal status
    """
    try:
        status = get_audible_status(session_id)
        return jsonify({
            "session_id": session_id,
            "signaled": status.get("signaled", False),
            "timestamp": status.get("timestamp")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@checkpoint_bp.route('/api/audible/clear/<session_id>', methods=['POST'])
def clear_audible(session_id):
    """
    Clear the audible signal for a session.

    Typically called by the runner after it has processed the signal.

    URL params:
    - session_id: The session to clear

    Returns:
    - Success status
    """
    try:
        clear_audible_signal(session_id)
        return jsonify({
            "status": "cleared",
            "session_id": session_id,
            "message": "Audible signal cleared"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== ANNOTATED SCREENSHOT API ==========

@checkpoint_bp.route('/api/checkpoints/<checkpoint_id>/annotated-screenshot', methods=['POST'])
def save_annotated_screenshot(checkpoint_id):
    """
    Save an annotated screenshot for a checkpoint.

    The frontend captures the HTMX content + annotation canvas using html2canvas
    and sends the result as a base64 data URL.

    Request body:
    {
        "image_data": "data:image/png;base64,..."  // Base64-encoded PNG
    }

    Returns:
    - Path to saved image and API URL
    """
    import base64
    from datetime import datetime

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        image_data = data.get('image_data')
        if not image_data:
            return jsonify({"error": "image_data field required"}), 400

        # Parse data URL
        if not image_data.startswith('data:image/'):
            return jsonify({"error": "Invalid image data format. Expected data:image/... URL"}), 400

        # Extract base64 data
        # Format: data:image/png;base64,<base64data>
        header, encoded = image_data.split(',', 1)
        image_bytes = base64.b64decode(encoded)

        # Get checkpoint to find session_id and cell_name
        cp = None
        if get_checkpoint_manager:
            cm = get_checkpoint_manager()
            cp = cm.get_checkpoint(checkpoint_id)

        if not cp:
            return jsonify({"error": f"Checkpoint {checkpoint_id} not found"}), 404

        # Build save path: images/{session_id}/{cell_name}/annotated_{checkpoint_id[:8]}_{timestamp}.png
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"annotated_{checkpoint_id[:8]}_{timestamp}.png"

        save_dir = os.path.join(IMAGE_DIR, cp.session_id, cp.cell_name)
        os.makedirs(save_dir, exist_ok=True)

        save_path = os.path.join(save_dir, filename)

        # Write image file
        with open(save_path, 'wb') as f:
            f.write(image_bytes)

        print(f"[Checkpoint API] Saved annotated screenshot: {save_path}")

        # Build API URL
        api_url = f"/api/images/{cp.session_id}/{cp.cell_name}/{filename}"

        # Store reference for inclusion in checkpoint response
        _annotated_screenshots[checkpoint_id] = {
            "url": api_url,
            "path": save_path,
            "filename": filename,
            "timestamp": timestamp
        }
        print(f"[Checkpoint API] Stored annotated screenshot reference for checkpoint {checkpoint_id}")

        return jsonify({
            "status": "saved",
            "checkpoint_id": checkpoint_id,
            "path": save_path,
            "url": api_url,
            "filename": filename
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
