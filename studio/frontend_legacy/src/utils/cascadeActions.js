/**
 * Shared cascade action utilities
 *
 * Reusable functions for cascade lifecycle management across views.
 */

/**
 * Cancel a running cascade
 *
 * @param {string} sessionId - Session to cancel
 * @param {string} reason - Optional cancellation reason
 * @param {boolean} force - If true, force-cancel even if process is running (default: auto-detect zombies)
 * @returns {Promise<Object>} { success: boolean, forced?: boolean, error?: string }
 */
export async function cancelCascade(sessionId, reason = 'User requested cancellation', force = false) {
  if (!sessionId) {
    return { success: false, error: 'No session ID provided' };
  }

  try {
    console.log('[cancelCascade] Requesting cancellation for:', sessionId, { force });

    const res = await fetch('http://localhost:5050/api/cancel-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        reason: reason,
        force: force
      })
    });

    const data = await res.json();

    if (!res.ok || data.error) {
      console.error('[cancelCascade] Failed:', data.error);
      return { success: false, error: data.error || `HTTP ${res.status}` };
    }

    console.log('[cancelCascade] Success:', data);
    return {
      success: true,
      forced: data.forced || false,
      data
    };

  } catch (err) {
    console.error('[cancelCascade] Exception:', err);
    return { success: false, error: err.message };
  }
}

/**
 * Start a new cascade
 *
 * @param {string} cascadePath - Path to cascade file
 * @param {Object} inputs - Input values
 * @param {string} sessionId - Optional session ID
 * @returns {Promise<Object>} { success: boolean, session_id?: string, error?: string }
 */
export async function startCascade(cascadePath, inputs = {}, sessionId = null) {
  try {
    console.log('[startCascade] Starting:', cascadePath, 'with inputs:', inputs);

    const body = {
      cascade_path: cascadePath,
      inputs: inputs
    };

    if (sessionId) {
      body.session_id = sessionId;
    }

    const res = await fetch('http://localhost:5050/api/run-cascade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    const data = await res.json();

    if (!res.ok || data.error) {
      console.error('[startCascade] Failed:', data.error);
      return { success: false, error: data.error || `HTTP ${res.status}` };
    }

    console.log('[startCascade] Success, session:', data.session_id);
    return { success: true, session_id: data.session_id, data };

  } catch (err) {
    console.error('[startCascade] Exception:', err);
    return { success: false, error: err.message };
  }
}

/**
 * Check if a session can be cancelled
 *
 * @param {string} sessionStatus - Current session status
 * @returns {boolean} True if cancellation is possible
 */
export function canCancelSession(sessionStatus) {
  // Can cancel if not already in a terminal state
  return sessionStatus && !['completed', 'cancelled', 'error'].includes(sessionStatus);
}
