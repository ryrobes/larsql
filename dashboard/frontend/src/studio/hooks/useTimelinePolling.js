import React, { useState, useEffect, useRef, useCallback } from 'react';
import { derivePhaseState } from '../utils/derivePhaseState';

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
const COST_BACKFILL_LOOKBACK_MS = 30000; // Look back 30s for cost updates

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

  //console.log('[useTimelinePolling] sessionId:', sessionId, 'isRunning:', isRunning);

  // Poll function
  const poll = useCallback(async () => {
    if (!sessionId) {
      console.log('[TimelinePolling] No sessionId, skipping poll');
      return;
    }

    console.log('[TimelinePolling] Polling session:', sessionId, 'cursor:', cursorRef.current);

    try {
      // Use a lookback window instead of strict cursor to catch cost updates on existing rows
      // Calculate timestamp 30s ago to catch backfilled cost data
      const now = new Date();
      const lookbackTime = new Date(now.getTime() - COST_BACKFILL_LOOKBACK_MS);
      const lookbackTimestamp = lookbackTime.toISOString().replace('T', ' ').replace('Z', '').split('.')[0];

      // Use the older of cursorRef or lookbackTimestamp to catch updates
      const effectiveCursor = cursorRef.current < lookbackTimestamp ? cursorRef.current : lookbackTimestamp;
      const isLookback = effectiveCursor !== cursorRef.current;

      if (isLookback && Math.random() < 0.1) { // Log 10% of lookbacks to avoid spam
        console.log('[TimelinePolling] Using lookback window to catch cost updates', { cursor: cursorRef.current, lookback: lookbackTimestamp });
      }

      const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=${encodeURIComponent(effectiveCursor)}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      console.log('[TimelinePolling] Fetched', data.rows?.length || 0, 'rows for session:', sessionId);

      if (data.error) {
        throw new Error(data.error);
      }

      // Handle duplicates intelligently: update existing rows if data changed (e.g., cost backfilled)
      const newRows = [];
      const updatedMessageIds = new Set();

      for (const row of (data.rows || [])) {
        if (seenIdsRef.current.has(row.message_id)) {
          // Already seen this message_id - check if cost was backfilled
          if (row.cost && row.cost > 0) {
            updatedMessageIds.add(row.message_id);
          }
          // Skip adding to newRows, but track for potential update
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
              // Find the new version of this row
              const newVersion = (data.rows || []).find(r => r.message_id === existingRow.message_id);
              if (newVersion && newVersion.cost && (!existingRow.cost || existingRow.cost === 0)) {
                console.log('[TimelinePolling] Backfilling cost for message', existingRow.message_id, 'from', existingRow.cost, 'to', newVersion.cost);
                return { ...existingRow, cost: newVersion.cost };
              }
            }
            return existingRow;
          });

          return [...updated, ...newRows];
        });

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
    //console.log('[useTimelinePolling] Start/stop check:', { sessionId, isRunning });

    if (!sessionId || !isRunning) {
      //console.log('[useTimelinePolling] Stopping polling (no session or not running)');
      setIsPolling(false);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      return;
    }

    //console.log('[useTimelinePolling] Starting polling for session:', sessionId);
    setIsPolling(true);

    // Initial poll
    poll();

    // Set up interval
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    //console.log('[useTimelinePolling] Poll interval set (every', POLL_INTERVAL_MS, 'ms)');

    return () => {
      //console.log('[useTimelinePolling] Cleanup: stopping poll interval');
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
