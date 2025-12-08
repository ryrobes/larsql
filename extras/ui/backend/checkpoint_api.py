"""
API endpoints for Human-in-the-Loop (HITL) Checkpoint management.

Provides REST API for:
- Listing pending checkpoints
- Getting checkpoint details
- Responding to checkpoints
- Cancelling checkpoints
"""
import json
import os
import sys
from flask import Blueprint, jsonify, request

# Add parent directory to path to import windlass
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../.."))
_WINDLASS_DIR = os.path.join(_REPO_ROOT, "windlass")
if _WINDLASS_DIR not in sys.path:
    sys.path.insert(0, _WINDLASS_DIR)

try:
    from windlass.checkpoints import get_checkpoint_manager, CheckpointStatus
except ImportError as e:
    print(f"Warning: Could not import windlass checkpoint modules: {e}")
    get_checkpoint_manager = None
    CheckpointStatus = None

checkpoint_bp = Blueprint('checkpoints', __name__)


@checkpoint_bp.route('/api/checkpoints', methods=['GET'])
def list_checkpoints():
    """
    List all pending checkpoints.

    Query params:
    - session_id: Optional filter by session ID

    Returns:
    - List of checkpoint objects with UI specs
    """
    if not get_checkpoint_manager:
        return jsonify({"error": "Checkpoint system not available"}), 500

    session_id = request.args.get('session_id')

    try:
        cm = get_checkpoint_manager()
        pending = cm.get_pending_checkpoints(session_id)

        checkpoints = []
        for cp in pending:
            checkpoints.append({
                "id": cp.id,
                "session_id": cp.session_id,
                "cascade_id": cp.cascade_id,
                "phase_name": cp.phase_name,
                "checkpoint_type": cp.checkpoint_type.value,
                "status": cp.status.value,
                "created_at": cp.created_at.isoformat() if cp.created_at else None,
                "timeout_at": cp.timeout_at.isoformat() if cp.timeout_at else None,
                "ui_spec": cp.ui_spec,
                "phase_output_preview": cp.phase_output[:500] if cp.phase_output else None,
                "num_soundings": len(cp.sounding_outputs) if cp.sounding_outputs else None
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
    if not get_checkpoint_manager:
        return jsonify({"error": "Checkpoint system not available"}), 500

    try:
        cm = get_checkpoint_manager()
        cp = cm.get_checkpoint(checkpoint_id)

        if not cp:
            return jsonify({"error": f"Checkpoint {checkpoint_id} not found"}), 404

        return jsonify({
            "id": cp.id,
            "session_id": cp.session_id,
            "cascade_id": cp.cascade_id,
            "phase_name": cp.phase_name,
            "checkpoint_type": cp.checkpoint_type.value,
            "status": cp.status.value,
            "created_at": cp.created_at.isoformat() if cp.created_at else None,
            "timeout_at": cp.timeout_at.isoformat() if cp.timeout_at else None,
            "responded_at": cp.responded_at.isoformat() if cp.responded_at else None,
            "ui_spec": cp.ui_spec,
            "phase_output": cp.phase_output,
            "sounding_outputs": cp.sounding_outputs,
            "sounding_metadata": cp.sounding_metadata,
            "response": cp.response,
            "response_reasoning": cp.response_reasoning,
            "response_confidence": cp.response_confidence,
            "winner_index": cp.winner_index,
            "rankings": cp.rankings,
            "ratings": cp.ratings
        })

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
            from windlass.unified_logs import get_unified_logger
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
