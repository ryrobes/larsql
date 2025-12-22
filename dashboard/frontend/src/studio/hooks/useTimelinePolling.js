import React, { useState, useEffect, useRef, useCallback } from 'react';

/**
 * useTimelinePolling - Poll session execution logs for Timeline builder
 *
 * Reuses the generic /api/playground/session-stream endpoint to fetch
 * all execution data. Derives phase states from accumulated logs.
 *
 * Replaces fragmented SSE with simple polling:
 * - Single source of truth (DB)
 * - No missed events
 * - Complete execution data (soundings, reforge, wards, tools)
 * - Self-healing (refresh works mid-execution)
 *
 * Polls every 750ms while running, stops 10s after completion.
 */

const POLL_INTERVAL_MS = 750;
const POLL_AFTER_COMPLETE_MS = 10000;

/**
 * Derive phase state from log rows
 *
 * Extracts:
 * - Status (pending/running/success/error)
 * - Output (result data)
 * - Duration
 * - Error message
 * - Cost (accumulated)
 * - Model (last used)
 */
function derivePhaseState(logs, phaseName) {
  const phaseLogs = logs.filter(r => r.phase_name === phaseName);

  if (phaseLogs.length === 0) {
    return { status: 'pending', result: null, error: null, duration: null, images: null, cost: null, model: null };
  }

  console.log('[derivePhaseState]', phaseName, 'has', phaseLogs.length, 'log rows');

  let status = 'pending';
  let result = null;
  let error = null;
  let duration = null;
  let images = null;
  let cost = 0;
  let model = null;

  for (const row of phaseLogs) {
    const role = row.role;

    // Phase running
    if (role === 'phase_start' || role === 'structure') {
      console.log('[derivePhaseState]', phaseName, 'Setting status to running (role:', role, ')');
      status = 'running';
    }

    // Phase complete
    if (role === 'phase_complete') {
      console.log('[derivePhaseState]', phaseName, 'Setting status to SUCCESS (found phase_complete)');
      status = 'success';
    }

    // Errors
    if (role === 'error' || row.node_type === 'error') {
      status = 'error';
      error = row.content_json || row.content || 'Unknown error';
    }

    // Extract result from tool execution (sql_data, python_data, etc.)
    if (role === 'tool' && row.content_json) {
      let toolResult = row.content_json;

      // Parse if JSON-encoded string
      if (typeof toolResult === 'string') {
        try {
          toolResult = JSON.parse(toolResult);
        } catch (e) {
          console.warn('[derivePhaseState] Failed to parse tool result JSON:', e);
        }
      }

      console.log('[derivePhaseState]', phaseName, 'Found tool result:', toolResult);
      result = toolResult;
    }

    // Extract output from LLM/assistant messages
    if (role === 'assistant' && row.content_json) {
      let content = row.content_json;
      // Parse if JSON-encoded string
      if (typeof content === 'string' && content.startsWith('"')) {
        try {
          content = JSON.parse(content);
        } catch {}
      }
      console.log('[derivePhaseState]', phaseName, 'Found LLM result:', content);
      result = content;
    }

    // Extract images from metadata_json
    if (row.metadata_json) {
      let metadata = row.metadata_json;
      // Parse if JSON-encoded string
      if (typeof metadata === 'string') {
        try {
          metadata = JSON.parse(metadata);
        } catch (e) {
          console.warn('[derivePhaseState] Failed to parse metadata_json:', e);
        }
      }

      // Check for images in metadata
      if (metadata?.images && Array.isArray(metadata.images)) {
        console.log('[derivePhaseState]', phaseName, 'Found images in metadata:', metadata.images);
        images = metadata.images;
      }
    }

    // Accumulate duration
    if (row.duration_ms) {
      duration = (duration || 0) + parseFloat(row.duration_ms);
    }

    // Accumulate cost
    if (row.cost) {
      cost += parseFloat(row.cost);
    }

    // Track model (use last non-null model seen)
    if (row.model) {
      model = row.model;
    }
  }

  console.log('[derivePhaseState]', phaseName, 'Final result:', result);

  return {
    status,
    result,
    error,
    duration: duration ? Math.round(duration) : null,
    images: images,  // Add images to state
    cost: cost > 0 ? cost : null,
    model: model,
  };
}

/**
 * useTimelinePolling hook
 *
 * @param {string} sessionId - Session to poll
 * @param {boolean} isRunning - Whether execution is active
 * @returns {Object} { phaseLogs, phaseStates, isPolling, error }
 */
export function useTimelinePolling(sessionId, isRunning) {
  const [logs, setLogs] = useState([]);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [totalCost, setTotalCost] = useState(0);

  const cursorRef = useRef('1970-01-01 00:00:00');
  const pollIntervalRef = useRef(null);
  const completeTimeoutRef = useRef(null);
  const seenIdsRef = useRef(new Set());
  const prevSessionRef = useRef(null);

  // Poll function
  const poll = useCallback(async () => {
    if (!sessionId) return;

    try {
      const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(cursorRef.current)}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Filter duplicates
      const newRows = (data.rows || []).filter(row => {
        if (seenIdsRef.current.has(row.message_id)) {
          return false;
        }
        seenIdsRef.current.add(row.message_id);
        return true;
      });

      // Only update logs if we actually got new rows
      if (newRows.length > 0) {
        setLogs(prev => [...prev, ...newRows]);
        cursorRef.current = data.cursor;
      }

      // Only update session complete if it changed
      if (data.session_complete && !sessionComplete) {
        setSessionComplete(true);
      }

      // Update total cost if present
      if (data.total_cost !== undefined) {
        setTotalCost(data.total_cost);
      }

      // Only clear error if there was one
      if (error) {
        setError(null);
      }
    } catch (err) {
      console.error('[TimelinePolling] Error:', err);
      setError(err.message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Reset when session changes
  useEffect(() => {
    if (sessionId !== prevSessionRef.current) {
      setLogs([]);
      setIsPolling(false);
      setSessionComplete(false);
      setTotalCost(0);
      cursorRef.current = '1970-01-01 00:00:00';
      seenIdsRef.current.clear();
      prevSessionRef.current = sessionId;
    }
  }, [sessionId]);

  // Start/stop polling based on execution state
  useEffect(() => {
    if (!sessionId || !isRunning) {
      setIsPolling(false);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      return;
    }

    setIsPolling(true);

    // Initial poll
    poll();

    // Set up interval
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [sessionId, isRunning, poll]);

  // Continue polling briefly after completion (for final cost data)
  useEffect(() => {
    if (sessionComplete) {
      const pollInterval = setInterval(poll, POLL_INTERVAL_MS);

      completeTimeoutRef.current = setTimeout(() => {
        clearInterval(pollInterval);
        setIsPolling(false);
      }, POLL_AFTER_COMPLETE_MS);

      return () => {
        clearInterval(pollInterval);
        if (completeTimeoutRef.current) {
          clearTimeout(completeTimeoutRef.current);
        }
      };
    }
  }, [sessionComplete, poll]);

  // Derive phase states from logs (memoized to prevent infinite loops)
  const phaseStates = React.useMemo(() => {
    const states = {};
    if (logs.length > 0) {
      // Get unique phase names
      const phaseNames = [...new Set(logs.map(r => r.phase_name).filter(Boolean))];

      for (const phaseName of phaseNames) {
        states[phaseName] = derivePhaseState(logs, phaseName);
      }
    }
    return states;
  }, [logs]); // Only recompute when logs actually change

  return {
    logs,              // Raw log rows (for debugging)
    phaseStates,       // Derived state by phase name (memoized!)
    isPolling,         // Currently polling
    sessionComplete,   // Session finished
    totalCost,         // Accumulated session cost
    error,             // Polling error
  };
}

export default useTimelinePolling;
