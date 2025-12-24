import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import usePlaygroundStore from '../stores/playgroundStore';

/**
 * useSessionStream - Smart polling hook for session execution logs
 *
 * Replaces fragmented SSE events with a single polling approach that:
 * 1. Fetches all log rows since last cursor from /api/playground/session-stream
 * 2. Accumulates logs in memory
 * 3. Derives all UI state (soundings, winner, output) from the logs
 *
 * This approach is more reliable than SSE because:
 * - No missed events (rows are persisted)
 * - Single source of truth (database)
 * - Easy to debug (just look at logs)
 * - UI is "dumb" - just renders what the DB has figured out
 */

const POLL_INTERVAL_MS = 750;
const POLL_AFTER_COMPLETE_MS = 10000; // Continue polling 10s after completion for final cost data

/**
 * Check if content is meaningful LLM output (not just a status message)
 */
function isMeaningfulContent(content) {
  if (!content) return false;
  if (typeof content !== 'string') return false;

  const trimmed = content.trim();
  if (trimmed.length < 30) return false; // Too short to be real LLM content

  // Skip status/system messages
  const statusPatterns = [
    /^"?Phase \w+ completed"?$/i,
    /^"?Starting cascade/i,
    /^"?Cascade:/i,
    /^"?Phase:/i,
    /^"?Soundings:/i,
    /^"?Turn \d+"?$/i,
    /^"?Selected best of/i,
    /^"?Selected refinement/i,
    /^"?Completed"?$/i,
    /^"?Reforge step \d+/i,
    /^"?🔨 Reforge Step/i,
    /^"?🏆 Step \d+ Winner/i,
    /^"?## Input Data:/i,
    /^"?Original intent:/i,
    /^"?\w+_phase"?$/i, // Phase names
  ];

  for (const pattern of statusPatterns) {
    if (pattern.test(trimmed)) return false;
  }

  return true;
}

/**
 * Parse content_json - it may be JSON-encoded string
 */
function parseContent(content) {
  if (!content) return '';
  if (typeof content !== 'string') return String(content);

  // Try to parse if it looks like a JSON string (with escaped quotes)
  let parsed = content;
  if (content.startsWith('"') && content.endsWith('"')) {
    try {
      parsed = JSON.parse(content);
    } catch {
      // Not valid JSON, use as-is
    }
  }

  return parsed;
}

/**
 * Derive phase state from accumulated log rows
 *
 * This function extracts:
 * - Overall phase status (idle/running/completed/error)
 * - Soundings progress (which are running, complete, failed)
 * - Winner index (if evaluator has picked one)
 * - Sounding outputs (content from each sounding)
 * - Reforge state (current step, outputs)
 * - Final output (winner's content or aggregate result)
 * - Cost and duration
 *
 * @param {Array} logs - All accumulated log rows for the session
 * @param {string} phaseName - The phase name to derive state for
 * @returns {Object} Derived phase state
 */
export function derivePhaseState(logs, phaseName) {
  const emptyState = {
    status: 'idle',
    soundingsProgress: [],
    winnerIndex: null,
    currentReforgeStep: 0,
    totalReforgeSteps: 0,
    soundingsOutputs: {},
    reforgeOutputs: {},
    liveLog: [],        // Scrolling log during execution
    finalOutput: '',    // Clean final output after completion
    output: '',         // For backwards compat - will be liveLog or finalOutput based on status
    lastStatusMessage: '', // Latest short status message for footer display
    cost: 0,
    duration: 0,
    error: null,
  };

  if (!logs || logs.length === 0 || !phaseName) {
    return emptyState;
  }

  // Filter logs for this phase
  const phaseLogs = logs.filter(r => r.phase_name === phaseName);

  if (phaseLogs.length === 0) {
    return emptyState;
  }

  // Derive status from role values
  let status = 'idle';
  let error = null;
  let winnerIndex = null;
  let soundingsWinnerOutput = '';
  let reforgeWinnerOutput = '';
  let totalCost = 0;
  let totalDuration = 0;
  let isComplete = false;

  // Track soundings
  const soundingsProgress = [];
  const soundingsOutputs = {};

  // Track reforge - key by step, store full content
  const reforgeOutputs = {};
  const reforgeWinnerByStep = {};
  let maxReforgeStep = 0;
  let currentReforgeStep = 0;

  // Live log - accumulate meaningful messages for scrolling display
  const liveLog = [];
  // Track short status messages for footer
  let lastStatusMessage = '';

  for (const row of phaseLogs) {
    const role = row.role;
    const sidx = row.sounding_index;
    const rstep = row.reforge_step;
    const rawContent = row.content_json;
    const content = parseContent(rawContent);

    // Accumulate cost
    if (row.cost) {
      totalCost += parseFloat(row.cost) || 0;
    }

    // Accumulate duration
    if (row.duration_ms) {
      totalDuration += parseFloat(row.duration_ms) || 0;
    }

    // Phase start
    if (role === 'phase_start') {
      status = 'running';
    }

    // Track sounding index presence (to know we have soundings)
    const hasSoundingIndex = sidx !== null && sidx !== undefined;
    const hasReforgeStep = rstep !== null && rstep !== undefined;

    // Add meaningful content to live log
    if (isMeaningfulContent(content)) {
      let label = '';
      if (hasReforgeStep) {
        label = `R${rstep}`;
        if (hasSoundingIndex) label += `.${sidx}`;
      } else if (hasSoundingIndex) {
        label = `S${sidx}`;
      }
      if (row.is_winner) label += '★';

      liveLog.push({
        id: row.message_id,
        label,
        content,
        isWinner: row.is_winner === true || row.is_winner === 1,
        soundingIndex: hasSoundingIndex ? parseInt(sidx, 10) : null,
        reforgeStep: hasReforgeStep ? parseInt(rstep, 10) : null,
      });
    } else if (content && typeof content === 'string' && content.trim().length > 0) {
      // Short status message - capture for footer display
      const trimmed = content.trim().replace(/^"|"$/g, ''); // Remove surrounding quotes
      if (trimmed.length > 0 && trimmed.length < 100) {
        lastStatusMessage = trimmed;
      }
    }

    if (hasSoundingIndex && !hasReforgeStep) {
      const idx = parseInt(sidx, 10);
      if (!isNaN(idx)) {
        // Initialize sounding progress if not exists
        let sounding = soundingsProgress.find(s => s.index === idx);
        if (!sounding) {
          sounding = { index: idx, status: 'running', output: null };
          soundingsProgress.push(sounding);
        }

        // Capture output from assistant role (the actual LLM response)
        // Only update if new content is longer - keep the fullest content we've seen
        if (role === 'assistant' && isMeaningfulContent(content)) {
          sounding.status = 'complete';
          const existingOutput = soundingsOutputs[idx];
          if (!existingOutput || content.length > existingOutput.length) {
            sounding.output = content;
            soundingsOutputs[idx] = content;
          }
        }

        // Also capture from sounding_attempt if it has meaningful content
        if (role === 'sounding_attempt' && isMeaningfulContent(content)) {
          sounding.status = 'complete';
          const existingOutput = soundingsOutputs[idx];
          if (!existingOutput || content.length > existingOutput.length) {
            sounding.output = content;
            soundingsOutputs[idx] = content;
          }
        }

        // Winner selection for soundings
        if (row.is_winner === true || row.is_winner === 1) {
          winnerIndex = idx;
          sounding.status = 'winner';
          // Use the longest content we have for this sounding
          const candidateContent = isMeaningfulContent(content) ? content : soundingsOutputs[idx];
          if (candidateContent && (!soundingsWinnerOutput || candidateContent.length > soundingsWinnerOutput.length)) {
            soundingsWinnerOutput = candidateContent;
          }
        }
      }
    }

    // Reforge step handling
    if (hasReforgeStep) {
      const step = parseInt(rstep, 10);
      if (!isNaN(step)) {
        if (step > maxReforgeStep) {
          maxReforgeStep = step;
        }
        currentReforgeStep = step;

        // Store reforge outputs keyed by step (flat, not nested by sounding)
        // Each step can have multiple attempts, we store them all
        // Only update if new content is longer - keep the fullest content
        if ((role === 'assistant' || role === 'reforge_attempt') && isMeaningfulContent(content)) {
          const reforgeIdx = hasSoundingIndex ? parseInt(sidx, 10) : 0;
          if (!reforgeOutputs[step]) {
            reforgeOutputs[step] = {};
          }
          const existingContent = reforgeOutputs[step][reforgeIdx];
          if (!existingContent || content.length > existingContent.length) {
            reforgeOutputs[step][reforgeIdx] = content;
          }
        }

        // Reforge winner - this is the winning attempt for this step
        if ((row.is_winner === true || row.is_winner === 1) && role !== 'reforge_winner') {
          const reforgeIdx = hasSoundingIndex ? parseInt(sidx, 10) : 0;
          reforgeWinnerByStep[step] = reforgeIdx;
          // Use the longest content we have for this reforge step
          const candidateContent = isMeaningfulContent(content) ? content : reforgeOutputs[step]?.[reforgeIdx];
          if (candidateContent && (!reforgeWinnerOutput || candidateContent.length > reforgeWinnerOutput.length)) {
            reforgeWinnerOutput = candidateContent;
          }
        }
      }
    }

    // Evaluator role (soundings evaluation)
    if (role === 'evaluator' || role === 'evaluator_result') {
      if (status !== 'completed' && status !== 'error') {
        status = 'evaluating';
      }
      // Try to extract winner from content if it contains structured output
      if (content && typeof content === 'string') {
        const winnerMatch = content.match(/winner[:\s]+(\d+)/i);
        if (winnerMatch) {
          const extractedWinner = parseInt(winnerMatch[1], 10);
          // Evaluator uses 1-indexed, convert to 0-indexed
          winnerIndex = extractedWinner > 0 ? extractedWinner - 1 : extractedWinner;
        }
      }
    }

    // Soundings result (after evaluator picks winner)
    if (role === 'soundings_result') {
      if (winnerIndex !== null && soundingsOutputs[winnerIndex]) {
        soundingsWinnerOutput = soundingsOutputs[winnerIndex];
      }
    }

    // Reforge evaluation
    if (role === 'reforge_evaluation' || role === 'reforge_evaluator') {
      if (status !== 'completed' && status !== 'error') {
        status = 'reforge_running';
      }
    }

    // Phase complete - mark as complete but DON'T use status message as output
    if (role === 'phase_complete') {
      isComplete = true;
    }

    // Cascade complete
    if (role === 'cascade_complete') {
      isComplete = true;
    }

    // Error - detect from role
    if (role === 'error' || role === 'cascade_error' || role === 'eddy_error') {
      status = 'error';
      error = content || 'Unknown error';
    }
  }

  // Determine final status based on what we found
  if (status !== 'error') {
    if (isComplete) {
      status = 'completed';
    } else if (maxReforgeStep > 0) {
      // Check if all reforge steps have winners
      const hasAllReforgeWinners = Object.keys(reforgeWinnerByStep).length >= maxReforgeStep;
      if (hasAllReforgeWinners) {
        status = 'completed';
      } else {
        status = 'reforge_running';
      }
    } else if (winnerIndex !== null && soundingsProgress.length > 0) {
      status = 'winner_selected';
    } else if (soundingsProgress.length > 0) {
      const allComplete = soundingsProgress.every(s => s.status === 'complete' || s.status === 'winner');
      if (allComplete) {
        status = 'evaluating';
      } else {
        status = 'soundings_running';
      }
    }
  }

  // Determine final output - priority:
  // 1. Last reforge winner output (if reforge was used)
  // 2. Soundings winner output
  // 3. Winner's stored output from soundingsOutputs
  // 4. Last assistant message with meaningful content
  // 5. Longest content from liveLog as final fallback
  let finalOutput = '';

  if (reforgeWinnerOutput) {
    finalOutput = reforgeWinnerOutput;
  } else if (soundingsWinnerOutput) {
    finalOutput = soundingsWinnerOutput;
  } else if (winnerIndex !== null && soundingsOutputs[winnerIndex]) {
    finalOutput = soundingsOutputs[winnerIndex];
  } else {
    // Get last assistant message with meaningful content
    const assistantMessages = phaseLogs
      .filter(r => r.role === 'assistant')
      .map(r => parseContent(r.content_json))
      .filter(c => isMeaningfulContent(c));

    if (assistantMessages.length > 0) {
      // Use the longest assistant message (more likely to be complete)
      finalOutput = assistantMessages.reduce((longest, curr) =>
        curr.length > longest.length ? curr : longest, '');
    }
  }

  // Ultimate fallback: use the longest content from liveLog
  if (!finalOutput && liveLog.length > 0) {
    const longestEntry = liveLog.reduce((longest, curr) =>
      (curr.content?.length || 0) > (longest.content?.length || 0) ? curr : longest, liveLog[0]);
    if (longestEntry?.content) {
      finalOutput = longestEntry.content;
    }
  }

  // Sort soundings by index
  soundingsProgress.sort((a, b) => a.index - b.index);

  // Mark winner in soundings progress
  if (winnerIndex !== null) {
    const winner = soundingsProgress.find(s => s.index === winnerIndex);
    if (winner) {
      winner.status = 'winner';
    }
  }

  // Flatten reforge outputs for card display: step -> winner content
  const flatReforgeOutputs = {};
  for (const [step, attempts] of Object.entries(reforgeOutputs)) {
    const stepNum = parseInt(step, 10);
    const winnerIdx = reforgeWinnerByStep[stepNum];
    if (winnerIdx !== undefined && attempts[winnerIdx]) {
      flatReforgeOutputs[stepNum] = attempts[winnerIdx];
    } else {
      // No winner yet, show first attempt
      const firstKey = Object.keys(attempts)[0];
      if (firstKey !== undefined) {
        flatReforgeOutputs[stepNum] = attempts[firstKey];
      }
    }
  }

  // Output: during running states show nothing (PhaseCard will use liveLog)
  // After completion, show finalOutput
  const output = status === 'completed' ? finalOutput : '';

  // Clear status message when phase is complete
  const statusMessage = status === 'completed' ? '' : lastStatusMessage;

  return {
    status,
    soundingsProgress,
    winnerIndex,
    currentReforgeStep,
    totalReforgeSteps: maxReforgeStep,
    soundingsOutputs,
    reforgeOutputs: flatReforgeOutputs, // Flattened for card display
    liveLog,
    finalOutput,
    output,
    lastStatusMessage: statusMessage,
    cost: Math.round(totalCost * 1000000) / 1000000, // Round to 6 decimals
    duration: Math.round(totalDuration),
    error,
  };
}

/**
 * useSessionStream - Main hook for polling session logs
 *
 * @param {string} sessionId - The session ID to poll for
 * @returns {Object} { logs, phaseStates, isPolling, error, totalCost }
 */
export function useSessionStream(sessionId) {
  const [logs, setLogs] = useState([]);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [sessionStatus, setSessionStatus] = useState(null);  // 'running', 'completed', 'error', etc.
  const [sessionError, setSessionError] = useState(null);
  const [totalCost, setTotalCost] = useState(0);

  const cursorRef = useRef('1970-01-01 00:00:00');
  const pollIntervalRef = useRef(null);
  const completeTimeoutRef = useRef(null);
  const seenUuidsRef = useRef(new Set());

  // Get execution status and handlers from store
  const executionStatus = usePlaygroundStore((state) => state.executionStatus);
  const handleCascadeError = usePlaygroundStore((state) => state.handleCascadeError);

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

      // Filter out duplicate rows by message_id
      const newRows = (data.rows || []).filter(row => {
        if (seenUuidsRef.current.has(row.message_id)) {
          return false;
        }
        seenUuidsRef.current.add(row.message_id);
        return true;
      });

      if (newRows.length > 0) {
        setLogs(prev => [...prev, ...newRows]);
        cursorRef.current = data.cursor;
      }

      setTotalCost(prev => prev + (data.total_cost || 0));

      if (data.session_complete) {
        setSessionComplete(true);
      }

      // Update session status from authoritative session_state table
      if (data.session_status !== undefined) {
        setSessionStatus(data.session_status);

        // If session is in terminal error state, update the store
        if (data.session_status === 'error' && executionStatus === 'running') {
          console.log('[SessionStream] Session errored, updating store:', data.session_error);
          handleCascadeError(data.session_error || 'Session ended with error');
        }
      }
      if (data.session_error !== undefined) {
        setSessionError(data.session_error);
      }

      setError(null);
    } catch (err) {
      console.error('[SessionStream] Poll error:', err);
      setError(err.message);
    }
  }, [sessionId, executionStatus, handleCascadeError]);

  // Track previous sessionId to detect changes
  const prevSessionIdRef = useRef(null);

  // Start/stop polling based on execution status and session
  useEffect(() => {
    // Clear state when session changes or becomes null
    if (sessionId !== prevSessionIdRef.current) {
      setLogs([]);
      setIsPolling(false);
      setSessionComplete(false);
      setSessionStatus(null);
      setSessionError(null);
      setTotalCost(0);
      cursorRef.current = '1970-01-01 00:00:00';
      seenUuidsRef.current.clear();
      prevSessionIdRef.current = sessionId;
    }

    if (!sessionId) {
      return;
    }

    if (executionStatus === 'running' || (executionStatus === 'completed' && !sessionComplete)) {
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
    } else {
      setIsPolling(false);

      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }
  }, [sessionId, executionStatus, sessionComplete, poll]);

  // Continue polling for POLL_AFTER_COMPLETE_MS after session completes to get final cost data
  useEffect(() => {
    if (sessionComplete) {
      // Keep polling at normal interval for a bit longer
      const pollInterval = setInterval(poll, POLL_INTERVAL_MS);

      // Stop after POLL_AFTER_COMPLETE_MS
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

  // Derive phase states from logs
  const phaseStates = useMemo(() => {
    const states = {};
    const phaseNames = new Set(logs.map(r => r.phase_name).filter(Boolean));

    for (const phaseName of phaseNames) {
      states[phaseName] = derivePhaseState(logs, phaseName);
    }

    return states;
  }, [logs]);

  return {
    logs,
    phaseStates,
    isPolling,
    error,
    sessionComplete,
    sessionStatus,     // Authoritative status: 'running', 'completed', 'error', 'cancelled', 'orphaned'
    sessionError,      // Error message if sessionStatus == 'error'
    totalCost,
  };
}

export default useSessionStream;
