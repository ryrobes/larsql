import React, { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import { Button, CheckpointRenderer, useToast, VideoLoader } from '../../components';
import SessionMessagesLog from '../../studio/components/SessionMessagesLog';
import ContextExplorerSidebar from '../../studio/components/ContextExplorerSidebar';
import SimpleSidebar from './components/SimpleSidebar';
import CascadePickerModal from './components/CascadePickerModal';
import useExplorePolling from './hooks/useExplorePolling';
import { cancelCascade } from '../../utils/cascadeActions';
import { ROUTES } from '../../routes.helpers';
import './ExploreView.css';

/**
 * ExploreView - Perplexity-style research interface for LARS cascades
 *
 * Features:
 * - Live "ghost messages" showing tool calls/results in real-time
 * - Inline checkpoint rendering (no modals - clean Perplexity loop)
 * - Real-time orchestration stats (cost, cell, status)
 * - Pure polling (no SSE complexity)
 *
 * Flow:
 * 1. User starts cascade (or navigates to session)
 * 2. Ghost messages appear as LLM works
 * 3. Checkpoint appears when LLM calls request_decision
 * 4. User responds inline
 * 5. Cascade continues seamlessly
 * 6. Loop repeats until complete
 */
const ExploreView = () => {
  // Get route parameters from React Router
  const { sessionId: urlSessionId } = useParams();
  const navigate = useNavigate();

  const sessionId = urlSessionId ? decodeURIComponent(urlSessionId) : null;
  const { showToast } = useToast();

  const [showPicker, setShowPicker] = useState(!sessionId);

  // Context Explorer state
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [hoveredHash, setHoveredHash] = useState(null);

  // Context explorer handlers
  const handleMessageClick = useCallback((message) => {
    // Only show context explorer for messages that have context
    if (message && message.context_hashes && message.context_hashes.length > 0) {
      setSelectedMessage(message);
    } else {
      setSelectedMessage(null);
    }
  }, []);

  const handleCloseContextExplorer = useCallback(() => {
    setSelectedMessage(null);
  }, []);

  const handleHoverHash = useCallback((hash) => {
    setHoveredHash(hash);
  }, []);

  const handleNavigateToMessage = useCallback((messageIndex) => {
    // Could scroll to message in grid - for now just console log
    console.log('[ExploreView] Navigate to message index:', messageIndex);
  }, []);

  // Auto-restore last session (with session validation) - ONLY RUN ONCE ON MOUNT
  const hasAutoRestored = React.useRef(false);

  React.useEffect(() => {
    if (sessionId || hasAutoRestored.current) return; // Already have a session or already tried

    hasAutoRestored.current = true; // Prevent re-running

    const lastSession = localStorage.getItem('explore_last_session');
    const lastSessionTime = localStorage.getItem('explore_last_session_time');

    if (!lastSession || !lastSessionTime) {
      setShowPicker(true);
      return;
    }

    const elapsed = Date.now() - parseInt(lastSessionTime, 10);
    const ONE_HOUR = 60 * 60 * 1000;

    if (elapsed >= ONE_HOUR) {
      console.log('[ExploreView] Session expired (>1h), showing picker');
      setShowPicker(true);
      return;
    }

    // Check if session is still valid (running or blocked)
    fetch(`http://localhost:5050/api/sessions?limit=100`)
      .then(r => r.json())
      .then(data => {
        const session = data.sessions?.find(s => s.session_id === lastSession);

        if (!session) {
          console.log('[ExploreView] Session not found, showing picker');
          setShowPicker(true);
          return;
        }

        // Only auto-restore if session is active
        if (session.status === 'running' || session.status === 'blocked') {
          console.log('[ExploreView] Auto-restoring active session:', lastSession);
          navigate(ROUTES.exploreWithSession(lastSession));
          setShowPicker(false);
        } else {
          console.log('[ExploreView] Session is', session.status, '- showing picker for new cascade');
          setShowPicker(true);
        }
      })
      .catch(err => {
        console.error('[ExploreView] Failed to validate session:', err);
        setShowPicker(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // ONLY run once on mount!

  // Poll for all data (NO SSE!)
  // Note: ghostMessages and checkpointHistory are still maintained by the hook,
  // but we now use SessionMessagesLog which displays logs directly.
  // Checkpoints (request_decision) appear as 'render' role messages in the log.
  const {
    logs,
    checkpoint,         // Used for pending checkpoint at bottom
    orchestrationState,
    sessionStatus,
    sessionError,
    totalCost,
    cascadeId,
    toolCounts,
    // NEW: Rich analytics
    sessionStats,
    cellAnalytics,
    cascadeAnalytics,
    childSessions,
    isPolling,
    error
  } = useExplorePolling(sessionId);

  // Persist current session to localStorage
  React.useEffect(() => {
    if (sessionId) {
      localStorage.setItem('explore_last_session', sessionId);
      localStorage.setItem('explore_last_session_time', Date.now().toString());
      console.log('[ExploreView] Persisted session to localStorage:', sessionId);
    }
  }, [sessionId]);

  // Handlers
  const handleCheckpointRespond = async (response) => {
    if (!checkpoint) return;

    try {
      const res = await fetch(`http://localhost:5050/api/checkpoints/${checkpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response })
      });

      const data = await res.json();

      if (data.error) {
        showToast(`Failed: ${data.error}`, { type: 'error' });
        return;
      }

      showToast('Response submitted', { type: 'success' });
      // Polling will detect and update automatically

    } catch (err) {
      showToast(`Error: ${err.message}`, { type: 'error' });
    }
  };

  const handleStartCascade = async (cascadePath, inputs, existingSessionId = null) => {
    // Handle resume case (existingSessionId provided)
    if (existingSessionId) {
      navigate(ROUTES.exploreWithSession(existingSessionId));
      setShowPicker(false);
      showToast('Resumed session', { type: 'success' });
      return;
    }

    // Handle new cascade case
    try {
      const res = await fetch('http://localhost:5050/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_path: cascadePath,  // Fixed: use cascade_path not cascade_file
          inputs: inputs,
          // Auto-assign session ID
        })
      });

      const data = await res.json();

      if (data.error) {
        showToast(data.error, { type: 'error' });
        return;
      }

      // Navigate to new session
      navigate(ROUTES.exploreWithSession(data.session_id));
      setShowPicker(false);
      showToast('Cascade started', { type: 'success' });

    } catch (err) {
      showToast(`Failed to start: ${err.message}`, { type: 'error' });
    }
  };

  const handleEndCascade = async () => {
    if (!window.confirm('Stop this cascade? This will cancel execution immediately.')) return;

    const result = await cancelCascade(sessionId, 'User cancelled from ExploreView', false);

    if (result.success) {
      const message = result.forced
        ? 'Session terminated (was zombie/dead)'
        : 'Cancellation requested';
      showToast(message, { type: 'success' });

      // If forced, immediately update local state
      if (result.forced) {
        // Trigger a refresh to get updated status
        setTimeout(() => {
          window.location.reload();
        }, 1000);
      }
    } else {
      showToast(`Failed to cancel: ${result.error}`, { type: 'error' });
    }
  };

  // Show empty state if no session (modal will open)
  if (!sessionId) {
    return (
      <div className="explore-view">
        <CascadePickerModal
          isOpen={showPicker}
          onClose={() => navigate(ROUTES.STUDIO)}
          onStart={handleStartCascade}
        />
        <div className="explore-empty-state">
          <Icon icon="mdi:compass" width="64" />
          <h2>No Session Selected</h2>
          <p>Select a cascade to start exploring</p>
          <Button variant="primary" icon="mdi:plus" onClick={() => setShowPicker(true)}>
            Start Cascade
          </Button>
        </div>
      </div>
    );
  }

  // Loading state
  if (isPolling && logs.length === 0) {
    return (
      <VideoLoader size="large" message="Loading session..." />
    );
  }

  // Error state
  if (error) {
    return (
      <div className="explore-view-error">
        <Icon icon="mdi:alert-circle" width="32" />
        <h3>Error loading session</h3>
        <p>{error}</p>
        <Button variant="secondary" onClick={() => navigate(ROUTES.STUDIO)}>
          Back to Studio
        </Button>
      </div>
    );
  }

  return (
    <div className="explore-view">
      {/* Cascade Picker Modal */}
      <CascadePickerModal
        isOpen={showPicker}
        onClose={() => setShowPicker(false)}
        onStart={handleStartCascade}
      />

      {/* Header with New Cascade button (always visible) */}
      <div className="explore-header">
        <div className="explore-header-left">
          <Icon icon="mdi:compass" width="24" />
          <h1>Explore</h1>
        </div>
        <Button
          variant="primary"
          size="sm"
          icon="mdi:plus-circle"
          onClick={() => {
            // Force clear and show picker
            localStorage.removeItem('explore_last_session');
            localStorage.removeItem('explore_last_session_time');
            setShowPicker(true);
          }}
        >
          New Cascade
        </Button>
      </div>

      {/* Two-column layout (three columns when context explorer is open) */}
      <div className={`explore-layout ${selectedMessage ? 'with-context-explorer' : ''}`}>

        {/* Context Explorer Sidebar (left) - appears when message with context is selected */}
        <AnimatePresence>
          {selectedMessage && (
            <motion.div
              className="explore-context-sidebar"
              initial={{ opacity: 0, x: -320, width: 0 }}
              animate={{ opacity: 1, x: 0, width: 360 }}
              exit={{ opacity: 0, x: -320, width: 0 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            >
              <ContextExplorerSidebar
                selectedMessage={selectedMessage}
                allLogs={logs}
                hoveredHash={hoveredHash}
                onHoverHash={handleHoverHash}
                onClose={handleCloseContextExplorer}
                onNavigateToMessage={handleNavigateToMessage}
                cascadeAnalytics={cascadeAnalytics}
                cellAnalytics={cellAnalytics}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Main Column */}
        <div className="explore-main-column">
          <div className="explore-main-content">

            {/* Message Log - AG Grid with full message history and HITL rendering */}
            <div className="explore-messages-log">
              <SessionMessagesLog
                logs={logs}
                currentSessionId={sessionId}
                showFilters={false}  // Cleaner explore UI
                showCellColumn={true}
                compact={true}
                className="explore-session-log"
                shouldPollBudget={false}  // Budget shown in sidebar
                // Context Explorer integration
                onMessageClick={handleMessageClick}
                hoveredHash={hoveredHash}
                onHoverHash={handleHoverHash}
                externalSelectedMessage={selectedMessage}
              />
            </div>

            {/* Current Pending Checkpoint */}
            {checkpoint && (
              <motion.div
                className="current-checkpoint"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <div className="checkpoint-label">
                  <Icon icon="mdi:hand-back-right" width="16" />
                  <span>Human Input Required</span>
                </div>
                <CheckpointRenderer
                  checkpoint={checkpoint}
                  onSubmit={handleCheckpointRespond}
                  variant="inline"
                  showCellOutput={true}
                />
              </motion.div>
            )}

            {/* Empty State */}
            {!checkpoint && logs.length === 0 && (
              <div className="explore-empty">
                <Icon
                  icon={sessionStatus === 'completed' ? 'mdi:check-circle' : 'mdi:compass'}
                  width="64"
                  className={sessionStatus === 'running' ? 'spinning-slow' : ''}
                />
                <h2>
                  {sessionStatus === 'running' && 'Cascade Active'}
                  {sessionStatus === 'completed' && 'Cascade Complete'}
                  {sessionStatus === 'error' && 'Cascade Error'}
                  {sessionStatus === 'cancelled' && 'Cascade Cancelled'}
                  {!sessionStatus && 'Waiting for Activity'}
                </h2>
                <p>
                  {sessionStatus === 'running' && 'Activity will appear here as the cascade executes.'}
                  {sessionStatus === 'completed' && 'All done! Start a new cascade to continue.'}
                  {sessionStatus === 'error' && sessionError}
                  {sessionStatus === 'cancelled' && 'This cascade was cancelled.'}
                  {!sessionStatus && 'Start a cascade to begin.'}
                </p>
                {(sessionStatus === 'completed' || sessionStatus === 'cancelled' || sessionStatus === 'error') && (
                  <Button
                    variant="primary"
                    icon="mdi:plus"
                    onClick={() => {
                      // Clear localStorage to prevent auto-restore
                      localStorage.removeItem('explore_last_session');
                      localStorage.removeItem('explore_last_session_time');
                      setShowPicker(true);
                    }}
                  >
                    New Cascade
                  </Button>
                )}
              </div>
            )}

          </div>
        </div>

        {/* Sidebar */}
        <SimpleSidebar
          sessionId={sessionId}
          cascadeId={cascadeId}
          orchestrationState={orchestrationState}
          totalCost={totalCost}
          sessionStatus={sessionStatus}
          toolCounts={toolCounts}
          // NEW: Rich analytics
          sessionStats={sessionStats}
          cellAnalytics={cellAnalytics}
          cascadeAnalytics={cascadeAnalytics}
          childSessions={childSessions}
          onEnd={handleEndCascade}
          onNewCascade={() => setShowPicker(true)}
        />

      </div>

      {/* EXTENSION POINT: Narration Caption */}
      {/* {isNarrating && (
        <NarrationCaption
          text={narrationText}
          duration={narrationDuration}
          amplitude={narrationAmplitude}
        />
      )} */}
    </div>
  );
};

export default ExploreView;
