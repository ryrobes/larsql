import { useEffect, useRef, useCallback } from 'react';
import useWorkshopStore from '../stores/workshopStore';

/**
 * useExecutionSSE - Hook for real-time cascade execution events
 *
 * Connects to the SSE endpoint and dispatches events to the workshop store.
 * Only processes events matching the current sessionId.
 */
export function useExecutionSSE() {
  const eventSourceRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  const sessionId = useWorkshopStore((state) => state.sessionId);
  const executionStatus = useWorkshopStore((state) => state.executionStatus);

  // Get handlers directly from store (stable references)
  const handlePhaseStart = useWorkshopStore((state) => state.handlePhaseStart);
  const handlePhaseComplete = useWorkshopStore((state) => state.handlePhaseComplete);
  const handleSoundingStart = useWorkshopStore((state) => state.handleSoundingStart);
  const handleSoundingComplete = useWorkshopStore((state) => state.handleSoundingComplete);
  const handleTurnStart = useWorkshopStore((state) => state.handleTurnStart);
  const handleToolCall = useWorkshopStore((state) => state.handleToolCall);
  const handleToolResult = useWorkshopStore((state) => state.handleToolResult);
  const handleCostUpdate = useWorkshopStore((state) => state.handleCostUpdate);
  const handleCascadeComplete = useWorkshopStore((state) => state.handleCascadeComplete);
  const handleCascadeError = useWorkshopStore((state) => state.handleCascadeError);

  const processEvent = useCallback(
    (event) => {
      // Skip heartbeats and events for other sessions
      if (event.type === 'heartbeat') return;
      if (event.type === 'connected') return;

      // Only process events for our session
      if (event.session_id !== sessionId) return;

      const data = event.data || {};

      switch (event.type) {
        case 'cascade_start':
          // Already handled when we started the cascade
          // But we can use this to confirm execution started
          console.log('[SSE] Cascade started:', event.session_id);
          break;

        case 'phase_start':
          handlePhaseStart(
            data.cell_name,
            data.candidate_index
          );
          break;

        case 'phase_complete':
          console.log('[SSE] Phase complete:', data.cell_name, 'result:', data.result);
          handlePhaseComplete(
            data.cell_name,
            data.result || {},
            data.candidate_index
          );
          break;

        case 'sounding_start':
          handleSoundingStart(
            data.cell_name,
            data.candidate_index
          );
          break;

        case 'sounding_complete':
          handleSoundingComplete(
            data.cell_name,
            data.candidate_index,
            data.output,
            data.is_winner
          );
          break;

        case 'sounding_winner':
          // Mark the winning sounding(s)
          if (data.is_aggregated && data.aggregated_indices) {
            // Aggregate mode - multiple winners
            data.aggregated_indices.forEach(idx => {
              handleSoundingComplete(data.cell_name, idx, null, true);
            });
          } else if (data.winner_index >= 0) {
            // Single winner
            handleSoundingComplete(data.cell_name, data.winner_index, data.output, true);
          }
          break;

        case 'turn_start':
          handleTurnStart(
            data.cell_name,
            data.turn_number ?? data.turn_index ?? 0,
            data.candidate_index
          );
          break;

        case 'tool_call':
          handleToolCall(
            data.cell_name,
            data.tool_name,
            data.args
          );
          break;

        case 'tool_result':
          handleToolResult(
            data.cell_name,
            data.tool_name,
            data.result_preview || data.result
          );
          break;

        case 'cost_update':
          handleCostUpdate(
            data.cost || 0,
            data.cell_name,
            data.candidate_index
          );
          break;

        case 'cascade_complete':
          handleCascadeComplete(data.result);
          break;

        case 'cascade_error':
          handleCascadeError(data.error || 'Unknown error');
          break;

        default:
          // Log unknown events for debugging
          console.log('[SSE] Unknown event type:', event.type, event);
      }
    },
    [sessionId, handlePhaseStart, handlePhaseComplete, handleSoundingStart,
     handleSoundingComplete, handleTurnStart, handleToolCall, handleToolResult,
     handleCostUpdate, handleCascadeComplete, handleCascadeError]
  );

  useEffect(() => {
    // Only connect if we have a session and are running
    if (!sessionId || executionStatus !== 'running') {
      return;
    }

    const connect = () => {
      // Close existing connection
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      console.log('[SSE] Connecting for session:', sessionId);

      const eventSource = new EventSource(
        'http://localhost:5001/api/events/stream'
      );

      eventSource.onopen = () => {
        console.log('[SSE] Connected');
      };

      eventSource.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          processEvent(event);
        } catch (err) {
          console.error('[SSE] Failed to parse event:', err);
        }
      };

      eventSource.onerror = (err) => {
        console.error('[SSE] Connection error:', err);
        eventSource.close();

        // Reconnect after 2 seconds if still running
        if (useWorkshopStore.getState().executionStatus === 'running') {
          reconnectTimeoutRef.current = setTimeout(connect, 2000);
        }
      };

      eventSourceRef.current = eventSource;
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (eventSourceRef.current) {
        console.log('[SSE] Disconnecting');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [sessionId, executionStatus, processEvent]);

  return {
    connected: !!eventSourceRef.current,
  };
}

export default useExecutionSSE;
