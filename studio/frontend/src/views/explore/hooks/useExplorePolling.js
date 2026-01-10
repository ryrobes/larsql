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
// DISABLED: No auto-removal - keep full conversation history
// const GHOST_TIMEOUT = 30000;   // 30s before auto-remove
// const GHOST_MAX_COUNT = 10;    // Keep last 10 only

export default function useExplorePolling(sessionId) {
  // State
  const [logs, setLogs] = useState([]);
  const [checkpoint, setCheckpoint] = useState(null);
  const [checkpointHistory, setCheckpointHistory] = useState([]);  // All checkpoints for history
  const [ghostMessages, setGhostMessages] = useState([]);
  const [toolCounts, setToolCounts] = useState({});  // { tool_name: count }
  const [orchestrationState, setOrchestrationState] = useState({
    currentCell: null,
    currentModel: null,
    totalCost: 0,
    status: 'idle',
    cascadeId: null,
    cellHistory: [],
    turnCount: 0
  });
  const [sessionStatus, setSessionStatus] = useState(null);
  const [sessionError, setSessionError] = useState(null);
  const [totalCost, setTotalCost] = useState(0);
  const [cascadeId, setCascadeId] = useState(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);

  // NEW: Rich analytics state
  const [sessionStats, setSessionStats] = useState({
    messageCount: 0,
    tokensIn: 0,
    tokensOut: 0,
    durationMs: 0,
    startTime: null,
    lastActivityTime: null,
    roleCounts: {},     // { assistant: N, user: N, tool: N, ... }
    modelUsage: {},     // { 'model-name': N }
    modelCosts: {},     // { 'model-name': cost } - cumulative cost per model
    recentActivity: [], // Last 5 events [{type, tool, cell, timestamp}, ...]
  });
  const [cellAnalytics, setCellAnalytics] = useState({});  // Per-cell metrics from API
  const [cascadeAnalytics, setCascadeAnalytics] = useState(null);  // Session-level analytics
  const [childSessions, setChildSessions] = useState([]);  // Sub-cascades spawned

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
    setCheckpointHistory([]);
    setGhostMessages([]);
    setToolCounts({});
    setOrchestrationState({
      currentCell: null,
      currentModel: null,
      totalCost: 0,
      status: 'idle',
      cascadeId: null,
      cellHistory: [],
      turnCount: 0
    });
    setSessionStatus(null);
    setSessionError(null);
    setTotalCost(0);
    setCascadeId(null);
    setIsPolling(false);
    setError(null);
    // Clear new analytics state
    setSessionStats({
      messageCount: 0,
      tokensIn: 0,
      tokensOut: 0,
      durationMs: 0,
      startTime: null,
      lastActivityTime: null,
      roleCounts: {},
      modelUsage: {},
      modelCosts: {},
      recentActivity: [],
    });
    setCellAnalytics({});
    setCascadeAnalytics(null);
    setChildSessions([]);

    // Clear refs
    cursorRef.current = '1970-01-01 00:00:00';
    seenIdsRef.current.clear();

    // Clear ghost timeouts
    ghostTimeoutsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
    ghostTimeoutsRef.current.clear();

    prevSessionRef.current = sessionId;

    console.log('[useExplorePolling] State cleared, ready for new session');
  }, [sessionId]);

  // Derive ghost messages from new logs and track tool calls
  const deriveGhostMessages = useCallback((newLogs) => {
    console.log('[deriveGhostMessages] Processing', newLogs.length, 'new logs');
    const newGhosts = [];
    const newToolCounts = {};  // Accumulate counts from this batch

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

      // Also check metadata_json for tool info (some logs store it there)
      if (!toolName && log.metadata_json) {
        try {
          const metadata = JSON.parse(log.metadata_json);
          if (metadata.tool_name) {
            toolName = metadata.tool_name;
          }
        } catch (e) {
          // Not JSON
        }
      }

      console.log('[deriveGhostMessages] Log:', {
        role: log.role,
        toolName,
        node_type: log.node_type,
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
        // Count tool calls
        newToolCounts[toolName] = (newToolCounts[toolName] || 0) + 1;
      }

      // Tool results (tool role) - also count these
      if (log.role === 'tool') {
        // Try to extract tool name from the result log
        let resultToolName = toolName || 'tool';
        if (!toolName && log.metadata_json) {
          try {
            const metadata = JSON.parse(log.metadata_json);
            resultToolName = metadata.tool_name || metadata.name || 'tool';
          } catch (e) {}
        }

        console.log('[deriveGhostMessages] Found tool_result:', resultToolName);
        newGhosts.push({
          id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
          type: 'tool_result',
          tool: resultToolName,
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
            console.log('[deriveGhostMessages] Found thinking message, len:', text.length);
            newGhosts.push({
              id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
              type: 'thinking',
              content: text,
              timestamp: log.timestamp,
              createdAt: Date.now()
            });
          }
        } catch (e) {
          // Not parseable - try using raw content
          if (log.content_json.length > 50) {
            console.log('[deriveGhostMessages] Found raw thinking message');
            newGhosts.push({
              id: log.message_id || `ghost_${Date.now()}_${Math.random()}`,
              type: 'thinking',
              content: log.content_json,
              timestamp: log.timestamp,
              createdAt: Date.now()
            });
          }
        }
      }
    }

    console.log('[deriveGhostMessages] Created', newGhosts.length, 'new ghosts');

    // Update tool counts (merge with existing)
    if (Object.keys(newToolCounts).length > 0) {
      setToolCounts(prev => {
        const updated = { ...prev };
        for (const [tool, count] of Object.entries(newToolCounts)) {
          updated[tool] = (updated[tool] || 0) + count;
        }
        console.log('[deriveGhostMessages] Tool counts updated:', updated);
        return updated;
      });
    }

    if (newGhosts.length > 0) {
      setGhostMessages(prev => {
        const combined = [...prev, ...newGhosts];
        console.log('[deriveGhostMessages] Ghost messages now:', combined.length);
        // Keep all messages - no limit, no auto-removal
        return combined;
      });

      // DISABLED: No auto-removal - keep full conversation history
      // newGhosts.forEach(ghost => {
      //   const timeoutId = setTimeout(() => {
      //     setGhostMessages(prev => prev.filter(g => g.id !== ghost.id));
      //     ghostTimeoutsRef.current.delete(ghost.id);
      //   }, GHOST_TIMEOUT);
      //   ghostTimeoutsRef.current.set(ghost.id, timeoutId);
      // });
    }
  }, []);

  // NEW: Derive rich session stats from all logs
  const deriveSessionStats = useCallback((allLogs, newLogs) => {
    if (newLogs.length === 0 && allLogs.length === 0) return;

    // Accumulate stats from new logs
    let deltaTokensIn = 0;
    let deltaTokensOut = 0;
    let deltaDurationMs = 0;
    const deltaRoleCounts = {};
    const deltaModelUsage = {};
    const deltaModelCosts = {};  // Track cost per model
    const newActivity = [];

    for (const log of newLogs) {
      // Token counts
      deltaTokensIn += parseInt(log.tokens_in || 0, 10);
      deltaTokensOut += parseInt(log.tokens_out || 0, 10);
      deltaDurationMs += parseInt(log.duration_ms || 0, 10);

      // Role counts
      if (log.role) {
        deltaRoleCounts[log.role] = (deltaRoleCounts[log.role] || 0) + 1;
      }

      // Model usage and costs - use full model name as-is
      if (log.model) {
        deltaModelUsage[log.model] = (deltaModelUsage[log.model] || 0) + 1;
        // Track cost per model
        const cost = parseFloat(log.cost || 0);
        if (cost > 0) {
          deltaModelCosts[log.model] = (deltaModelCosts[log.model] || 0) + cost;
        }
      }

      // Recent activity - extract meaningful events
      if (log.role === 'tool' || (log.role === 'assistant' && log.tool_calls_json)) {
        let toolName = null;
        try {
          if (log.tool_calls_json) {
            const calls = JSON.parse(log.tool_calls_json);
            toolName = calls[0]?.function?.name || calls[0]?.name;
          }
          if (!toolName && log.metadata_json) {
            const meta = JSON.parse(log.metadata_json);
            toolName = meta.tool_name || meta.name;
          }
        } catch {}

        newActivity.push({
          type: log.role === 'tool' ? 'tool_result' : 'tool_call',
          tool: toolName || 'unknown',
          cell: log.cell_name,
          timestamp: log.timestamp,
        });
      } else if (log.role === 'render') {
        newActivity.push({
          type: 'checkpoint',
          cell: log.cell_name,
          timestamp: log.timestamp,
        });
      }
    }

    // Find start time from all logs
    const firstLog = allLogs[0];
    const lastLog = allLogs[allLogs.length - 1] || newLogs[newLogs.length - 1];

    setSessionStats(prev => {
      const updatedRoleCounts = { ...prev.roleCounts };
      for (const [role, count] of Object.entries(deltaRoleCounts)) {
        updatedRoleCounts[role] = (updatedRoleCounts[role] || 0) + count;
      }

      const updatedModelUsage = { ...prev.modelUsage };
      for (const [model, count] of Object.entries(deltaModelUsage)) {
        updatedModelUsage[model] = (updatedModelUsage[model] || 0) + count;
      }

      const updatedModelCosts = { ...prev.modelCosts };
      for (const [model, cost] of Object.entries(deltaModelCosts)) {
        updatedModelCosts[model] = (updatedModelCosts[model] || 0) + cost;
      }

      // Keep last 8 activity items
      const combinedActivity = [...prev.recentActivity, ...newActivity].slice(-8);

      return {
        messageCount: prev.messageCount + newLogs.length,
        tokensIn: prev.tokensIn + deltaTokensIn,
        tokensOut: prev.tokensOut + deltaTokensOut,
        durationMs: prev.durationMs + deltaDurationMs,
        startTime: prev.startTime || firstLog?.timestamp,
        lastActivityTime: lastLog?.timestamp || prev.lastActivityTime,
        roleCounts: updatedRoleCounts,
        modelUsage: updatedModelUsage,
        modelCosts: updatedModelCosts,
        recentActivity: combinedActivity,
      };
    });
  }, []);

  // Update orchestration state from logs
  const updateOrchestrationState = useCallback((allLogs, apiData) => {
    console.log('[updateOrchestrationState] Processing', allLogs.length, 'logs');

    // Find latest log with cell/cell info
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
      currentCell: latestLog?.cell_name || null,
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
      const url = `http://localhost:5050/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(cursorRef.current)}`;
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

          // Derive session stats with full logs context
          deriveSessionStats(updated, newRows);

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
      if (data.cascade_id) setCascadeId(data.cascade_id);

      // NEW: Capture rich analytics from API
      if (data.cascade_analytics) {
        setCascadeAnalytics(data.cascade_analytics);
      }
      if (data.cell_analytics && Object.keys(data.cell_analytics).length > 0) {
        setCellAnalytics(data.cell_analytics);
      }
      if (data.child_sessions && data.child_sessions.length > 0) {
        setChildSessions(data.child_sessions);
      }

      setError(null);
    } catch (err) {
      console.error('[useExplorePolling] Session logs error:', err);
      setError(err.message);
    } finally {
      setIsPolling(false);
    }
  }, [sessionId, deriveGhostMessages, deriveSessionStats, updateOrchestrationState]);

  // Poll checkpoints (separate from logs)
  const pollCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5050/api/checkpoints?session_id=${sessionId}`);

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
        // Store full checkpoint history (for rendering responded checkpoints)
        setCheckpointHistory(data.checkpoints);

        const pending = data.checkpoints.find(cp => cp.status === 'pending');
        console.log('[pollCheckpoint] Pending checkpoint:', pending ? pending.id : 'none');
        // Only update if checkpoint ID changed - prevents re-render that resets form state
        setCheckpoint(prev => {
          if (pending?.id !== prev?.id) {
            return pending || null;
          }
          return prev; // Keep same reference to prevent re-render
        });
      } else {
        // Only set to null if we currently have a checkpoint
        setCheckpoint(prev => prev ? null : prev);
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
    pollSessionLogs();
    pollCheckpoint();

    // Set up intervals
    const logsInterval = setInterval(() => {
      pollSessionLogs();
    }, POLL_INTERVAL);

    const checkpointInterval = setInterval(() => {
      pollCheckpoint();
    }, POLL_INTERVAL);

    console.log('[useExplorePolling] Intervals set up');

    return () => {
      console.log('[useExplorePolling] Cleanup: clearing intervals for session:', sessionId);
      clearInterval(logsInterval);
      clearInterval(checkpointInterval);

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
    checkpointHistory,  // All checkpoints (for showing responded ones in history)

    // Derived state
    ghostMessages,
    orchestrationState,
    toolCounts,  // { tool_name: count } - real-time tool call tracking

    // Session metadata
    sessionStatus,
    sessionError,
    totalCost,
    cascadeId,

    // NEW: Rich analytics
    sessionStats,     // { messageCount, tokensIn, tokensOut, roleCounts, modelUsage, recentActivity, ... }
    cellAnalytics,    // Per-cell metrics: { cell_name: { cell_cost, cell_duration_ms, ... } }
    cascadeAnalytics, // Session-level analytics: { cost_z_score, is_cost_outlier, ... }
    childSessions,    // Sub-cascades spawned: [{ session_id, parent_cell, ... }]

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
