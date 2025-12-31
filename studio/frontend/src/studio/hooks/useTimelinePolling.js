import React, { useState, useEffect, useRef, useCallback } from 'react';
import { deriveCellState } from '../utils/deriveCellState';

/**
 * useTimelinePolling - Poll session execution logs for Timeline builder
 *
 * Reuses the generic /api/playground/session-stream endpoint to fetch
 * all execution data. Derives cell states from accumulated logs.
 *
 * Replaces fragmented SSE with simple polling:
 * - Single source of truth (DB)
 * - No missed events
 * - Complete execution data (candidates, reforge, wards, tools)
 * - Self-healing (refresh works mid-execution)
 *
 * Polls every 750ms while running, stops 10s after completion.
 */

const POLL_INTERVAL_MS = 750;
const POLL_AFTER_COMPLETE_MS = 10000;
const COST_BACKFILL_LOOKBACK_MS = 30000; // Look back 30s for cost updates

/**
 * useTimelinePolling hook
 *
 * @param {string} sessionId - Session to poll
 * @param {boolean} isRunning - Whether execution is active
 * @param {boolean} isReplayMode - True if viewing historical session (default: false)
 * @returns {Object} { logs, cellStates, isPolling, error }
 */
export function useTimelinePolling(sessionId, isRunning, isReplayMode = false) {
  const [logs, setLogs] = useState([]);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [sessionStatus, setSessionStatus] = useState(null);  // 'running', 'completed', 'error', 'cancelled', 'orphaned'
  const [sessionStatusFor, setSessionStatusFor] = useState(null);  // Which session the status is for
  const [sessionError, setSessionError] = useState(null);    // Error message if status == 'error'
  const [totalCost, setTotalCost] = useState(0);
  const [childSessions, setChildSessions] = useState({});    // Child sub-cascades spawned by this session
  const [cascadeAnalytics, setCascadeAnalytics] = useState(null);  // Pre-computed cascade-level analytics
  const [cellAnalytics, setCellAnalytics] = useState({});    // Pre-computed per-cell analytics

  const cursorRef = useRef('1970-01-01 00:00:00');
  const pollIntervalRef = useRef(null);
  const completeTimeoutRef = useRef(null);
  const seenIdsRef = useRef(new Set());
  const prevSessionRef = useRef(null);

  //console.log('[useTimelinePolling] sessionId:', sessionId, 'isRunning:', isRunning);

  // Poll function
  const poll = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    try {
      // Different strategies for replay vs live mode
      let url;

      if (isReplayMode) {
        // REPLAY MODE: Fetch all data once (full replacement)
        url = `http://localhost:5050/api/playground/session-stream/${sessionId}?after=1970-01-01 00:00:00`;
      } else {
        // LIVE MODE: Incremental updates using cursor
        const now = new Date();
        const lookbackTime = new Date(now.getTime() - COST_BACKFILL_LOOKBACK_MS);
        const lookbackTimestamp = lookbackTime.toISOString().replace('T', ' ').replace('Z', '').split('.')[0];
        const effectiveCursor = cursorRef.current < lookbackTimestamp ? cursorRef.current : lookbackTimestamp;

        url = `http://localhost:5050/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(effectiveCursor)}`;
      }

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Filter to only this session and its direct children (no other sessions!)
      const validRows = (data.rows || []).filter(row => {
        return row.session_id === sessionId ||
               row.parent_session_id === sessionId ||
               row.session_id?.startsWith(`${sessionId}_`);
      });

      if (isReplayMode) {
        // REPLAY: Replace entire logs array
        setLogs(validRows);
      } else {
        // LIVE: Incremental append with deduplication
        const newRows = [];
        const updatedMessageIds = new Set();

        for (const row of validRows) {
          if (!row.message_id) {
            // No message_id (some system messages) - skip to avoid duplicates
            // These are typically cell_start/cell_complete events already in logs
            continue;
          }

          if (seenIdsRef.current.has(row.message_id)) {
            // Already seen - check if cost/tokens were backfilled
            if (row.cost && row.cost > 0) {
              updatedMessageIds.add(row.message_id);
            }
          } else {
            // Brand new row
            seenIdsRef.current.add(row.message_id);
            newRows.push(row);
          }
        }

        // Update logs: add new rows AND update existing rows with backfilled cost
        if (newRows.length > 0 || updatedMessageIds.size > 0) {
          setLogs(prev => {
            if (updatedMessageIds.size === 0) {
              // No updates, just append new rows
              return [...prev, ...newRows];
            }

            // Update existing rows with backfilled data
            const updated = prev.map(existingRow => {
              if (updatedMessageIds.has(existingRow.message_id)) {
                const newVersion = validRows.find(r => r.message_id === existingRow.message_id);
                if (newVersion) {
                  // Merge all fields from new version (preserves context_hashes, etc.)
                  return { ...existingRow, ...newVersion };
                }
              }
              return existingRow;
            });

            return [...updated, ...newRows];
          });
        }

        cursorRef.current = data.cursor || cursorRef.current;
      }

      // Only update session complete if it changed
      if (data.session_complete && !sessionComplete) {
        setSessionComplete(true);
      }

      // Update session status from authoritative session_state table
      if (data.session_status !== undefined) {
        setSessionStatus(data.session_status);
        setSessionStatusFor(sessionId);  // Track which session this status is for
      }
      if (data.session_error !== undefined) {
        setSessionError(data.session_error);
      }

      // Update total cost if present
      if (data.total_cost !== undefined) {
        setTotalCost(data.total_cost);
      }

      // Update child sessions if present
      if (data.child_sessions) {
        setChildSessions(prev => {
          const updated = { ...prev };
          data.child_sessions.forEach(child => {
            updated[child.session_id] = child;
          });
          return updated;
        });
      }

      // Update cascade analytics (pre-computed session-level metrics)
      if (data.cascade_analytics) {
        console.log('[useTimelinePolling] Received cascade_analytics:', data.cascade_analytics);
        setCascadeAnalytics(data.cascade_analytics);
      }

      // Update cell analytics (pre-computed per-cell metrics)
      if (data.cell_analytics && Object.keys(data.cell_analytics).length > 0) {
        console.log('[useTimelinePolling] Received cell_analytics:', Object.keys(data.cell_analytics), data.cell_analytics);
        setCellAnalytics(data.cell_analytics);
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
  }, [sessionId, isReplayMode]);

  // Reset when session changes
  useEffect(() => {
    if (sessionId !== prevSessionRef.current) {
      console.log('[useTimelinePolling] Session changed:', prevSessionRef.current, '→', sessionId, '- CLEARING ALL DATA');

      // Clear any active polling interval FIRST to prevent race
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }

      // Then clear all state IMMEDIATELY
      setLogs([]);
      setIsPolling(false);
      setSessionComplete(false);
      setSessionStatus(null);  // CRITICAL: Clear stale status
      setSessionStatusFor(null);  // Clear which session the status is for
      setSessionError(null);
      setTotalCost(0);
      setChildSessions({});
      setCascadeAnalytics(null);  // Clear cascade analytics
      setCellAnalytics({});  // Clear cell analytics
      cursorRef.current = '1970-01-01 00:00:00';
      seenIdsRef.current.clear();
      prevSessionRef.current = sessionId;

      // Force a re-render by updating state synchronously
      console.log('[useTimelinePolling] Cleared sessionStatus to prevent stale terminal state');
    }
  }, [sessionId]);

  // Start/stop polling based on execution state
  useEffect(() => {
    console.log('[useTimelinePolling] Start/stop check:', {
      sessionId,
      isRunning,
      hasInterval: !!pollIntervalRef.current
    });

    if (!sessionId || !isRunning) {
      console.log('[useTimelinePolling] Stopping polling (no session or not running)');
      setIsPolling(false);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      return;
    }

    console.log('[useTimelinePolling] Starting polling for session:', sessionId, 'isReplayMode:', isReplayMode);
    setIsPolling(true);

    // Initial poll
    poll();

    // Set up interval
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    console.log('[useTimelinePolling] Poll interval set (every', POLL_INTERVAL_MS, 'ms)');

    return () => {
      console.log('[useTimelinePolling] Cleanup: stopping poll interval for session:', sessionId);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [sessionId, isRunning, poll, isReplayMode]);

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

  // Derive cell states from logs (memoized to prevent infinite loops)
  const cellStates = React.useMemo(() => {
    const states = {};
    if (logs.length > 0) {
      // Get unique cell names
      const cellNames = [...new Set(logs.map(r => r.cell_name).filter(Boolean))];

      for (const cellName of cellNames) {
        states[cellName] = deriveCellState(logs, cellName);
      }
    }
    return states;
  }, [logs]); // Only recompute when logs actually change

  return {
    logs,              // Raw log rows (for debugging)
    cellStates,        // Derived state by cell name (memoized!)
    isPolling,         // Currently polling
    sessionComplete,   // Session finished (from logs or session_state)
    sessionStatus,     // Authoritative status: 'running', 'completed', 'error', 'cancelled', 'orphaned'
    sessionStatusFor,  // Which session the status belongs to (prevents stale status bugs)
    sessionError,      // Error message if sessionStatus == 'error'
    totalCost,         // Accumulated session cost
    childSessions,     // Child sub-cascades spawned by this session
    cascadeAnalytics,  // Pre-computed cascade-level analytics (context%, outliers, etc.)
    cellAnalytics,     // Pre-computed per-cell analytics (bottlenecks, comparisons)
    error,             // Polling error
  };
}

export default useTimelinePolling;
