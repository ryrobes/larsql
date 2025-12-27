import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import { Button, CheckpointRenderer, GhostMessage } from '../../components';
import { useToast } from '../../stores/toastStore';
import SimpleSidebar from './components/SimpleSidebar';
import CascadePicker from '../../components/CascadePicker';
import useExplorePolling from './hooks/useExplorePolling';
import './ExploreView.css';

/**
 * ExploreView - Perplexity-style research interface for RVBBIT cascades
 *
 * Features:
 * - Live "ghost messages" showing tool calls/results in real-time
 * - Inline checkpoint rendering (no modals - clean Perplexity loop)
 * - Real-time orchestration stats (cost, phase, status)
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
const ExploreView = ({ params, navigate }) => {
  const sessionId = params?.session || params?.id;
  const [showPicker, setShowPicker] = useState(!sessionId);
  const { showToast } = useToast();

  // Poll for all data (NO SSE!)
  const {
    logs,
    checkpoint,
    ghostMessages,
    orchestrationState,
    sessionStatus,
    sessionError,
    totalCost,
    isPolling,
    error
  } = useExplorePolling(sessionId);

  // Handlers
  const handleCheckpointRespond = async (response) => {
    if (!checkpoint) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpoint.id}/respond`, {
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

  const handleStartCascade = async (cascadeFile, inputs) => {
    try {
      const res = await fetch('http://localhost:5001/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_file: cascadeFile,
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
      navigate('explore', { session: data.session_id });
      setShowPicker(false);
      showToast('Cascade started', { type: 'success' });

    } catch (err) {
      showToast(`Failed to start: ${err.message}`, { type: 'error' });
    }
  };

  const handleEndCascade = async () => {
    if (!window.confirm('Stop this cascade?')) return;

    try {
      await fetch('http://localhost:5001/api/cancel-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });

      showToast('Cascade cancelled', { type: 'success' });

    } catch (err) {
      showToast(`Failed to cancel: ${err.message}`, { type: 'error' });
    }
  };

  // Show picker if no session
  if (showPicker || !sessionId) {
    return (
      <div className="explore-view">
        <div className="explore-picker-overlay">
          <CascadePicker
            onSelect={handleStartCascade}
            onCancel={() => navigate('studio')}
          />
        </div>
      </div>
    );
  }

  // Loading state
  if (isPolling && logs.length === 0) {
    return (
      <div className="explore-view-loading">
        <Icon icon="mdi:loading" className="spinning" width="32" />
        <p>Loading session...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="explore-view-error">
        <Icon icon="mdi:alert-circle" width="32" />
        <h3>Error loading session</h3>
        <p>{error}</p>
        <Button variant="secondary" onClick={() => navigate('studio')}>
          Back to Studio
        </Button>
      </div>
    );
  }

  return (
    <div className="explore-view">
      {/* Two-column layout */}
      <div className="explore-layout">

        {/* Main Column */}
        <div className="explore-main-column">
          <div className="explore-main-content">

            {/* EXTENSION POINT: Context Header (sticky, shows inputs) */}
            {/* <CascadeContextHeader cascadeInputs={...} checkpointHistory={...} /> */}

            {/* Ghost Messages (Live Activity) */}
            <AnimatePresence>
              {ghostMessages.map(ghost => (
                <motion.div
                  key={ghost.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 0.85, x: 0 }}
                  exit={{ opacity: 0, x: -100 }}
                  transition={{ duration: 0.3 }}
                >
                  <GhostMessage ghost={ghost} />
                </motion.div>
              ))}
            </AnimatePresence>

            {/* EXTENSION POINT: Timeline of Responded Checkpoints */}
            {/* {checkpointHistory
                .filter(cp => cp.status === 'responded')
                .map((cp, idx) => (
                  <ExpandableCheckpoint
                    key={cp.id}
                    checkpoint={cp}
                    index={idx}
                    sessionId={sessionId}
                  />
                ))
            } */}

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
                  showPhaseOutput={true}
                />
              </motion.div>
            )}

            {/* Empty State */}
            {!checkpoint && ghostMessages.length === 0 && (
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
                {sessionStatus === 'completed' && (
                  <Button
                    variant="primary"
                    icon="mdi:plus"
                    onClick={() => setShowPicker(true)}
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
          cascadeId={params?.cascade || orchestrationState.cascadeId}
          orchestrationState={orchestrationState}
          totalCost={totalCost}
          sessionStatus={sessionStatus}
          onEnd={handleEndCascade}
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
