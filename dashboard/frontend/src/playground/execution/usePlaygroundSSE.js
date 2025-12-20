import { useEffect, useRef, useCallback } from 'react';
import usePlaygroundStore from '../stores/playgroundStore';

/**
 * usePlaygroundSSE - Hook for real-time cascade execution events
 *
 * Connects to the SSE endpoint and updates playground nodes with execution results.
 * Only processes events matching the current sessionId.
 *
 * Handles race condition: events may arrive before sessionId is known.
 * Solution: buffer recent events and process them when sessionId becomes available.
 */
export function usePlaygroundSSE() {
  const eventSourceRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const eventBufferRef = useRef([]); // Buffer events until sessionId is known
  const processedSessionsRef = useRef(new Set()); // Track processed sessions to avoid duplicates

  const sessionId = usePlaygroundStore((state) => state.sessionId);
  const executionStatus = usePlaygroundStore((state) => state.executionStatus);

  // Get handlers directly from store (stable references)
  const handlePhaseComplete = usePlaygroundStore((state) => state.handlePhaseComplete);
  const handleCascadeComplete = usePlaygroundStore((state) => state.handleCascadeComplete);
  const handleCascadeError = usePlaygroundStore((state) => state.handleCascadeError);
  const updateNodeData = usePlaygroundStore((state) => state.updateNodeData);

  // Process a single event (extracted for reuse)
  const handleEvent = useCallback((event, targetSessionId) => {
    const data = event.data || {};

    switch (event.type) {
      case 'cascade_start':
        console.log('[Playground SSE] Cascade started:', event.session_id);
        break;

      case 'phase_start':
        console.log('[Playground SSE] Phase start:', data.phase_name);
        updateNodeData(data.phase_name, { status: 'running' });
        break;

      case 'phase_complete':
        console.log('[Playground SSE] Phase complete:', data.phase_name, 'result:', data.result);
        console.log('[Playground SSE] Images in result:', data.result?.images);
        handlePhaseComplete(data.phase_name, data.result || {});
        break;

      case 'cascade_complete':
        handleCascadeComplete();
        break;

      case 'cascade_error':
        handleCascadeError(data.error || 'Unknown error');
        break;

      case 'cost_update':
        // Cost data arrives asynchronously after phase completion
        if (data.phase_name && data.cost !== undefined) {
          console.log('[Playground SSE] Cost update:', data.phase_name, 'cost:', data.cost);
          updateNodeData(data.phase_name, { cost: data.cost });
        }
        break;

      default:
        // Don't log heartbeats
        if (event.type !== 'heartbeat') {
          console.log('[Playground SSE] Event:', event.type);
        }
    }
  }, [handlePhaseComplete, handleCascadeComplete, handleCascadeError, updateNodeData]);

  // Process buffered events when sessionId becomes known
  useEffect(() => {
    if (!sessionId) {
      return;
    }

    // Check if already processed this session
    if (processedSessionsRef.current.has(sessionId)) {
      console.log('[Playground SSE] Session already processed:', sessionId);
      return;
    }

    // Process any buffered events for this session
    const matchingEvents = eventBufferRef.current.filter(e => e.session_id === sessionId);
    console.log(`[Playground SSE] SessionId set: ${sessionId}, buffered events: ${eventBufferRef.current.length}, matching: ${matchingEvents.length}`);

    if (matchingEvents.length > 0) {
      console.log(`[Playground SSE] Processing ${matchingEvents.length} buffered events for session:`, sessionId);
      matchingEvents.forEach(event => {
        console.log('[Playground SSE] Processing buffered event:', event.type, event.data);
        handleEvent(event, sessionId);
      });
    }

    // Mark this session as processed (for buffer replay, not for new events)
    processedSessionsRef.current.add(sessionId);

    // Clear old events from buffer (keep only for current session)
    eventBufferRef.current = eventBufferRef.current.filter(e => e.session_id === sessionId);
  }, [sessionId, handleEvent]);

  const processEvent = useCallback(
    (event) => {
      // Skip heartbeats and connection events
      if (event.type === 'heartbeat') return;
      if (event.type === 'connected') return;

      // Get current sessionId from store (not from closure, to avoid stale value)
      const currentSessionId = usePlaygroundStore.getState().sessionId;

      // Debug: log all non-heartbeat events
      console.log('[Playground SSE] Event received:', event.type, 'session:', event.session_id, 'our session:', currentSessionId);

      // If sessionId not known yet, buffer the event
      if (!currentSessionId) {
        console.log('[Playground SSE] Buffering event (sessionId not yet known)');
        eventBufferRef.current.push(event);
        // Keep buffer size reasonable
        if (eventBufferRef.current.length > 100) {
          eventBufferRef.current = eventBufferRef.current.slice(-50);
        }
        return;
      }

      // Skip events for other sessions
      if (event.session_id !== currentSessionId) {
        console.log('[Playground SSE] Skipping - session mismatch');
        return;
      }

      // Process the event
      handleEvent(event, currentSessionId);
    },
    [handleEvent]
  );

  // Clear buffers when execution ends
  useEffect(() => {
    if (executionStatus !== 'running') {
      eventBufferRef.current = [];
      processedSessionsRef.current.clear();
    }
  }, [executionStatus]);

  useEffect(() => {
    // Connect as soon as execution starts - we'll filter events by sessionId
    // This fixes the race condition where events arrive before sessionId is set
    if (executionStatus !== 'running') {
      return;
    }

    const connect = () => {
      // Close existing connection
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      console.log('[Playground SSE] Connecting for session:', sessionId);

      const eventSource = new EventSource(
        'http://localhost:5001/api/events/stream'
      );

      eventSource.onopen = () => {
        console.log('[Playground SSE] Connected');
      };

      eventSource.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          processEvent(event);
        } catch (err) {
          console.error('[Playground SSE] Failed to parse event:', err);
        }
      };

      eventSource.onerror = (err) => {
        console.error('[Playground SSE] Connection error:', err);
        eventSource.close();

        // Reconnect after 2 seconds if still running
        if (usePlaygroundStore.getState().executionStatus === 'running') {
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
        console.log('[Playground SSE] Disconnecting');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [executionStatus, processEvent]);

  return {
    connected: !!eventSourceRef.current,
  };
}

export default usePlaygroundSSE;
