import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * useExplorePolling - Poll session data for ExploreView (Perplexity-style UI)
 *
 * Polls session logs and checkpoints at 750ms intervals (Studio's pattern).
 * Derives ghost messages and orchestration state from logs.
 *
 * NO SSE! Pure polling for simplicity:
 * - Single source of truth (database)
 * - Self-healing (refresh works mid-execution)
 * - Complete data (no missed events)
 * - Simpler code (no event bus)
 *
 * @param {string} sessionId - Session to poll
 * @returns {Object} { logs, checkpoint, ghostMessages, orchestrationState, sessionStatus, totalCost, isPolling, error, refresh, clearGhosts }
 */

const POLL_INTERVAL = 750;        // 750ms (Studio's interval)
const GHOST_TIMEOUT = 30000;      // 30s before auto-remove
const GHOST_MAX_COUNT = 10;       // Keep last 10 only

export default function useExplorePolling(sessionId) {
  // State
  const [logs, setLogs] = useState([]);
  const [checkpoint, setCheckpoint] = useState(null);
  const [ghostMessages, setGhostMessages] = useState([]);
  const [orchestrationState, setOrchestrationState] = useState({
    currentPhase: null,
    currentModel: null,
    totalCost: 0,
    status: 'idle',
    phaseHistory: [],
    turnCount: 0
  });
  const [sessionStatus, setSessionStatus] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [totalCost, setTotalCost] = useState(0);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);

  // Refs (prevent re-render loops)
  const cursorRef = useRef('1970-01-01 00:00:00');
  const seenIdsRef = useRef(new Set());
  const ghostTimeoutsRef = useRef(new Map());
  const pollIntervalRef = useRef(null);
  const checkpointIntervalRef = useRef(null);

  // Derive ghost messages from new logs
  const deriveGhostMessages = useCallback((newLogs) => {
    const newGhosts = [];

    for (const log of newLogs) {
      // Tool calls (assistant role with tool_name)
      if (log.tool_name && log.role === 'assistant') {
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_call',
          tool: log.tool_name,
          content: log.content,
          arguments: null, // Parse from content if needed
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }

      // Tool results (tool role)
      if (log.role === 'tool') {
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_result',
          tool: log.tool_name,
          result: log.content,
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }

      // Thinking messages (assistant role, no tool, substantial content)
      if (log.role === 'assistant' && !log.tool_name && log.content && log.content.length > 50) {
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'thinking',
          content: log.content,
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }
    }

    if (newGhosts.length > 0) {
      setGhostMessages(prev => {
        const combined = [...prev, ...newGhosts];
        // Keep last 10 only
        return combined.slice(-GHOST_MAX_COUNT);
      });

      // Setup auto-removal timeouts
      newGhosts.forEach(ghost => {
        const timeoutId = setTimeout(() => {
          setGhostMessages(prev => prev.filter(g => g.id !== ghost.id));
          ghostTimeoutsRef.current.delete(ghost.id);
        }, GHOST_TIMEOUT);

        ghostTimeoutsRef.current.set(ghost.id, timeoutId);
      });
    }
  }, []);

  // Update orchestration state from logs
  const updateOrchestrationState = useCallback((allLogs, apiData) => {
    // Find latest phase
    const phaseStart = [...allLogs].reverse().find(log =>
      log.event_type === 'phase_start' || log.phase_name
    );

    // Determine status from recent activity
    let status = 'idle';
    if (checkpoint) {
      status = 'waiting_human';
    } else {
      const recentLogs = allLogs.slice(-5);
      if (recentLogs.some(l => l.role === 'tool')) {
        status = 'tool_running';
      } else if (recentLogs.some(l => l.role === 'assistant')) {
        status = 'thinking';
      }
    }

    setOrchestrationState(prev => ({
      ...prev,
      currentPhase: phaseStart?.phase_name || prev.currentPhase,
      currentModel: phaseStart?.model || prev.currentModel,
      totalCost: apiData?.total_cost || prev.totalCost,
      status: status,
      // Can enhance with phaseHistory, turnCount later
    }));
  }, [checkpoint]);

  // Poll session logs
  const pollSessionLogs = useCallback(async () => {
    if (!sessionId) return;

    try {
      setIsPolling(true);

      // Use Studio's endpoint
      const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(cursorRef.current)}`;
      const res = await fetch(url);

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Deduplicate and append new logs
      const newRows = [];
      for (const row of data.rows || []) {
        if (row.message_id && !seenIdsRef.current.has(row.message_id)) {
          seenIdsRef.current.add(row.message_id);
          newRows.push(row);
        }
      }

      if (newRows.length > 0) {
        setLogs(prev => {
          const updated = [...prev, ...newRows];
          // Derive ghost messages from new logs
          deriveGhostMessages(newRows);
          // Update orchestration state
          updateOrchestrationState(updated, data);
          return updated;
        });

        cursorRef.current = data.cursor || cursorRef.current;
      }

      // Update session metadata
      if (data.session_status !== undefined) setSessionStatus(data.session_status);
      if (data.session_error !== undefined) setSessionError(data.session_error);
      if (data.total_cost !== undefined) setTotalCost(data.total_cost);

      setError(null);
    } catch (err) {
      console.error('[useExplorePolling] Session logs error:', err);
      setError(err.message);
    } finally {
      setIsPolling(false);
    }
  }, [sessionId, deriveGhostMessages, updateOrchestrationState]);

  // Poll checkpoints (separate from logs)
  const pollCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}`);

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();

      if (!data.error && data.checkpoints && data.checkpoints.length > 0) {
        const pending = data.checkpoints.find(cp => cp.status === 'pending');
        setCheckpoint(pending || null);
      } else {
        setCheckpoint(null);
      }
    } catch (err) {
      console.error('[useExplorePolling] Checkpoint poll error:', err);
    }
  }, [sessionId]);

  // Setup polling intervals
  useEffect(() => {
    if (!sessionId) {
      // Clear intervals if no session
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (checkpointIntervalRef.current) {
        clearInterval(checkpointIntervalRef.current);
        checkpointIntervalRef.current = null;
      }
      return;
    }

    console.log('[useExplorePolling] Starting polling for session:', sessionId);

    // Initial fetch
    pollSessionLogs();
    pollCheckpoint();

    // Poll at interval
    pollIntervalRef.current = setInterval(pollSessionLogs, POLL_INTERVAL);
    checkpointIntervalRef.current = setInterval(pollCheckpoint, POLL_INTERVAL);

    return () => {
      console.log('[useExplorePolling] Cleanup: stopping polls for session:', sessionId);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (checkpointIntervalRef.current) {
        clearInterval(checkpointIntervalRef.current);
        checkpointIntervalRef.current = null;
      }

      // Cleanup ghost timeouts
      ghostTimeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
      ghostTimeoutsRef.current.clear();
    };
  }, [sessionId, pollSessionLogs, pollCheckpoint]);

  // Auto-stop polling 10s after completion
  useEffect(() => {
    if (sessionStatus === 'completed' && sessionId) {
      const timeout = setTimeout(() => {
        console.log('[useExplorePolling] Session completed, stopping polls');
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        if (checkpointIntervalRef.current) {
          clearInterval(checkpointIntervalRef.current);
          checkpointIntervalRef.current = null;
        }
      }, 10000);

      return () => clearTimeout(timeout);
    }
  }, [sessionStatus, sessionId]);

  return {
    // Core data
    logs,
    checkpoint,

    // Derived state
    ghostMessages,
    orchestrationState,

    // Session metadata
    sessionStatus,
    sessionError,
    totalCost,

    // State
    isPolling,
    error,

    // Actions
    refresh: () => {
      pollSessionLogs();
      pollCheckpoint();
    },
    clearGhosts: () => {
      setGhostMessages([]);
      ghostTimeoutsRef.current.forEach(t => clearTimeout(t));
      ghostTimeoutsRef.current.clear();
    }
  };
}
