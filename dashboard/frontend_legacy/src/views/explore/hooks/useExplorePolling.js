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
    cascadeId: null,
    phaseHistory: [],
    turnCount: 0
  });
  const [sessionStatus, setSessionStatus] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [totalCost, setTotalCost] = useState(0);
  const [cascadeId, setCascadeId] = useState(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);

  // Refs (prevent re-render loops)
  const cursorRef = useRef('1970-01-01 00:00:00');
  const seenIdsRef = useRef(new Set());
  const ghostTimeoutsRef = useRef(new Map());
  const pollIntervalRef = useRef(null);
  const checkpointIntervalRef = useRef(null);
  const prevSessionRef = useRef(null);

  // Reset all state when session changes
  useEffect(() => {
    if (sessionId === prevSessionRef.current) return;

    console.log('[useExplorePolling] Session changed:', prevSessionRef.current, '→', sessionId, '- CLEARING ALL DATA');

    // Clear polling intervals first
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (checkpointIntervalRef.current) {
      clearInterval(checkpointIntervalRef.current);
      checkpointIntervalRef.current = null;
    }

    // Clear all state
    setLogs([]);
    setCheckpoint(null);
    setGhostMessages([]);
    setOrchestrationState({
      currentPhase: null,
      currentModel: null,
      totalCost: 0,
      status: 'idle',
      cascadeId: null,
      phaseHistory: [],
      turnCount: 0
    });
    setSessionStatus(null);
    setSessionError(null);
    setTotalCost(0);
    setCascadeId(null);
    setIsPolling(false);
    setError(null);

    // Clear refs
    cursorRef.current = '1970-01-01 00:00:00';
    seenIdsRef.current.clear();

    // Clear ghost timeouts
    ghostTimeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
    ghostTimeoutsRef.current.clear();

    prevSessionRef.current = sessionId;

    console.log('[useExplorePolling] State cleared, ready for new session');
  }, [sessionId]);

  // Derive ghost messages from new logs
  const deriveGhostMessages = useCallback((newLogs) => {
    console.log('[deriveGhostMessages] Processing', newLogs.length, 'new logs');
    const newGhosts = [];

    for (const log of newLogs) {
      // Parse tool calls from content_json (API returns stringified JSON)
      let toolName = null;
      let toolArgs = null;

      if (log.content_json) {
        try {
          const content = JSON.parse(log.content_json);
          if (content.tool) {
            toolName = content.tool;
            toolArgs = content.arguments || null;
          }
        } catch (e) {
          // Not JSON or different format
        }
      }

      // Also check tool_calls_json field
      if (!toolName && log.tool_calls_json) {
        try {
          const toolCalls = JSON.parse(log.tool_calls_json);
          if (Array.isArray(toolCalls) && toolCalls.length > 0) {
            toolName = toolCalls[0].function?.name || toolCalls[0].name;
            toolArgs = toolCalls[0].function?.arguments || toolCalls[0].arguments;
          }
        } catch (e) {
          // Not JSON
        }
      }

      console.log('[deriveGhostMessages] Log:', {
        role: log.role,
        toolName,
        hasContent: !!log.content_json,
        message_id: log.message_id
      });

      // Tool calls (assistant role with tool in content)
      if (toolName && log.role === 'assistant') {
        console.log('[deriveGhostMessages] Found tool_call:', toolName);
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_call',
          tool: toolName,
          content: log.content_json,
          arguments: toolArgs,
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }

      // Tool results (tool role)
      if (log.role === 'tool') {
        console.log('[deriveGhostMessages] Found tool_result:', toolName || 'unknown');
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_result',
          tool: toolName || 'tool',
          result: log.content_json,
          timestamp: log.timestamp,
          createdAt: Date.now()
        });
      }

      // Thinking messages (assistant role, no tool, substantial content)
      if (log.role === 'assistant' && !toolName && log.content_json) {
        try {
          const content = JSON.parse(log.content_json);
          const text = typeof content === 'string' ? content : JSON.stringify(content);
          if (text.length > 50) {
            console.log('[deriveGhostMessages] Found thinking message');
            newGhosts.push({
              id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
              type: 'thinking',
              content: text,
              timestamp: log.timestamp,
              createdAt: Date.now()
            });
          }
        } catch (e) {
          // Not parseable
        }
      }
    }

    console.log('[deriveGhostMessages] Created', newGhosts.length, 'new ghosts');

    if (newGhosts.length > 0) {
      setGhostMessages(prev => {
        const combined = [...prev, ...newGhosts];
        console.log('[deriveGhostMessages] Ghost messages now:', combined.length);
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
    console.log('[updateOrchestrationState] Processing', allLogs.length, 'logs');

    // Find latest log with cell/phase info
    const latestLog = [...allLogs].reverse().find(log =>
      log.cell_name || log.model
    );

    console.log('[updateOrchestrationState] Latest log:', {
      cell_name: latestLog?.cell_name,
      model: latestLog?.model,
      role: latestLog?.role
    });

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

    const newState = {
      currentPhase: latestLog?.cell_name || null,
      currentModel: latestLog?.model || null,
      totalCost: apiData?.total_cost || 0,
      status: status,
      cascadeId: apiData?.cascade_id || null,
    };

    console.log('[updateOrchestrationState] New state:', newState);
    setOrchestrationState(newState);
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
        console.log('[useExplorePolling] Got new rows:', newRows.length);
        console.log('[useExplorePolling] Sample row:', newRows[0]);

        // Update logs first
        setLogs(prev => {
          const updated = [...prev, ...newRows];
          console.log('[useExplorePolling] Total logs now:', updated.length);
          return updated;
        });

        // Then derive ghosts and state (after logs are updated)
        deriveGhostMessages(newRows);

        cursorRef.current = data.cursor || cursorRef.current;
      }

      // Always update orchestration state with latest API data
      if (data.total_cost !== undefined || data.session_status !== undefined) {
        setLogs(currentLogs => {
          updateOrchestrationState(currentLogs, data);
          return currentLogs;
        });
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

  // Fetch cascade ID and check for zombies from sessions API
  const fetchSessionMetadata = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/sessions?limit=100`);
      const data = await res.json();

      const session = data.sessions?.find(s => s.session_id === sessionId);
      if (session) {
        // Only update cascade ID if it changed
        setCascadeId(prev => {
          if (session.cascade_id && session.cascade_id !== prev) {
            console.log('[fetchSessionMetadata] Cascade ID:', session.cascade_id);
            return session.cascade_id;
          }
          return prev;
        });

        // Treat zombies and cancel_requested as cancelled (use functional setState to avoid dependency)
        setSessionStatus(prevStatus => {
          if ((session.is_zombie || session.cancel_requested) && prevStatus !== 'cancelled') {
            console.log('[fetchSessionMetadata] Session is zombie/cancelled - updating status');
            return 'cancelled';
          }
          return prevStatus;
        });
      }
    } catch (err) {
      console.error('[fetchSessionMetadata] Error:', err);
    }
  }, [sessionId]); // ONLY sessionId dependency!

  // Poll checkpoints (separate from logs)
  const pollCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}`);

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();

      console.log('[pollCheckpoint] Response:', {
        error: data.error,
        count: data.checkpoints?.length,
        checkpoints: data.checkpoints?.map(cp => ({ id: cp.id, status: cp.status }))
      });

      if (!data.error && data.checkpoints && data.checkpoints.length > 0) {
        const pending = data.checkpoints.find(cp => cp.status === 'pending');
        console.log('[pollCheckpoint] Pending checkpoint:', pending ? pending.id : 'none');
        setCheckpoint(pending || null);
      } else {
        setCheckpoint(null);
      }
    } catch (err) {
      console.error('[useExplorePolling] Checkpoint poll error:', err);
    }
  }, [sessionId]);

  // Setup polling intervals - ONLY depend on sessionId to prevent recreating intervals
  useEffect(() => {
    if (!sessionId) {
      return;
    }

    console.log('[useExplorePolling] Setting up polling for session:', sessionId);

    // Initial fetch
    // fetchSessionMetadata(); // DISABLED to debug loop
    pollSessionLogs();
    pollCheckpoint();

    // Set up intervals
    const logsInterval = setInterval(() => {
      pollSessionLogs();
    }, POLL_INTERVAL);

    const checkpointInterval = setInterval(() => {
      pollCheckpoint();
    }, POLL_INTERVAL);

    // Poll metadata less frequently (every 5s to detect zombies)
    // DISABLED TEMPORARILY to debug infinite loop
    // const metadataInterval = setInterval(() => {
    //   fetchSessionMetadata();
    // }, 5000);

    console.log('[useExplorePolling] Intervals set up');

    return () => {
      console.log('[useExplorePolling] Cleanup: clearing intervals for session:', sessionId);
      clearInterval(logsInterval);
      clearInterval(checkpointInterval);
      // clearInterval(metadataInterval); // DISABLED

      // Cleanup ghost timeouts
      ghostTimeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
      ghostTimeoutsRef.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]); // ONLY sessionId - functions called from closures

  // Auto-stop polling 10s after completion or cancellation
  useEffect(() => {
    if ((sessionStatus === 'completed' || sessionStatus === 'cancelled') && sessionId) {
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
    cascadeId,

    // State
    isPolling,
    error,

    // Actions
    refresh: () => {
      // fetchSessionMetadata(); // DISABLED
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
