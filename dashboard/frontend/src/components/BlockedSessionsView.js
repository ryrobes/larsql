import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import VideoSpinner from './VideoSpinner';
import DynamicUI from './DynamicUI';
import MessageWithInlineCheckpoint from './MessageWithInlineCheckpoint';
import './BlockedSessionsView.css';

/**
 * Modal for firing a signal with optional payload
 */
function SignalFireModal({ signal, onClose, onFire }) {
  const [payload, setPayload] = useState('{}');
  const [payloadError, setPayloadError] = useState(null);
  const [sending, setSending] = useState(false);

  const handleFire = async () => {
    // Validate JSON
    let parsedPayload = null;
    if (payload.trim()) {
      try {
        parsedPayload = JSON.parse(payload);
        setPayloadError(null);
      } catch (e) {
        setPayloadError('Invalid JSON: ' + e.message);
        return;
      }
    }

    setSending(true);
    try {
      await onFire(signal, parsedPayload);
      onClose();
    } catch (err) {
      setPayloadError(err.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="signal-fire-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Fire Signal: {signal.signal_name}</h3>
          <button className="close-btn" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        <div className="modal-body">
          <div className="signal-info">
            <div className="info-row">
              <span className="label">Session:</span>
              <span className="value mono">{signal.session_id}</span>
            </div>
            <div className="info-row">
              <span className="label">Cascade:</span>
              <span className="value">{signal.cascade_id}</span>
            </div>
            {signal.description && (
              <div className="info-row">
                <span className="label">Description:</span>
                <span className="value">{signal.description}</span>
              </div>
            )}
          </div>

          <div className="payload-section">
            <label>Payload (JSON, optional):</label>
            <textarea
              value={payload}
              onChange={e => setPayload(e.target.value)}
              placeholder='{"key": "value"}'
              rows={5}
              className={payloadError ? 'error' : ''}
            />
            {payloadError && <div className="error-message">{payloadError}</div>}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={sending}>
            Cancel
          </button>
          <button className="btn-primary fire" onClick={handleFire} disabled={sending}>
            {sending ? (
              <>
                <Icon icon="mdi:loading" className="spinning" width="16" />
                Firing...
              </>
            ) : (
              <>
                <Icon icon="mdi:flash" width="16" />
                Fire Signal
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Card for displaying a blocked session with inline checkpoint UI
 * For HITL/decision sessions, the UI is always expanded and shown in full
 */
function BlockedSessionCard({ session, signals, onFireSignal, onCancelSession, onViewSession, onRefresh }) {
  const isSignalBlocked = session.blocked_type === 'signal';
  const isHITLBlocked = session.blocked_type === 'hitl' || session.blocked_type === 'approval' || session.blocked_type === 'decision';

  // State for checkpoint UI - always expanded for HITL sessions
  const [checkpoint, setCheckpoint] = useState(null);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Find matching signal if blocked on signal
  const matchingSignal = isSignalBlocked && signals.find(s =>
    s.session_id === session.session_id &&
    s.signal_name === session.blocked_on
  );

  // Calculate waiting time
  const waitingSeconds = matchingSignal?.waiting_seconds ||
    (session.heartbeat_at ? (Date.now() / 1000 - new Date(session.heartbeat_at).getTime() / 1000) : 0);

  const formatWaitTime = (seconds) => {
    if (!seconds || seconds < 0) return '0s';
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  };

  const formatTimeRemaining = (seconds) => {
    if (!seconds || seconds <= 0) return 'expired';
    if (seconds < 60) return `${Math.floor(seconds)}s left`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m left`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m left`;
  };

  const blockedTypeIcon = {
    'signal': 'mdi:clock-alert-outline',
    'hitl': 'mdi:account-clock',
    'approval': 'mdi:check-decagram',
    'decision': 'mdi:help-circle-outline',
    'sensor': 'mdi:radar',
    'checkpoint': 'mdi:flag-checkered'
  }[session.blocked_type] || 'mdi:pause-circle';

  // Fetch checkpoint data
  const fetchCheckpoint = useCallback(async () => {
    if (!session.session_id) return;

    setCheckpointLoading(true);
    setCheckpointError(null);

    try {
      // First get the list of checkpoints for this session
      const listRes = await fetch(`http://localhost:5001/api/checkpoints?session_id=${session.session_id}`);
      const listData = await listRes.json();

      if (listData.error) {
        throw new Error(listData.error);
      }

      // Get the first pending checkpoint
      const pending = listData.checkpoints?.find(cp => cp.status === 'pending');
      if (!pending) {
        setCheckpointError('No pending checkpoint found');
        return;
      }

      // Fetch full checkpoint details
      const detailRes = await fetch(`http://localhost:5001/api/checkpoints/${pending.id}`);
      const detailData = await detailRes.json();

      if (detailData.error) {
        throw new Error(detailData.error);
      }

      setCheckpoint(detailData);
    } catch (err) {
      setCheckpointError(err.message);
    } finally {
      setCheckpointLoading(false);
    }
  }, [session.session_id]);

  // Auto-fetch checkpoint on mount for HITL sessions
  useEffect(() => {
    if (isHITLBlocked) {
      fetchCheckpoint();
    }
  }, [isHITLBlocked, fetchCheckpoint]);

  // Handle checkpoint response submission
  const handleSubmitResponse = async (values) => {
    if (!checkpoint?.id) return;

    setSubmitting(true);
    try {
      const response = await fetch(`http://localhost:5001/api/checkpoints/${checkpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: values })
      });

      const data = await response.json();
      if (data.error) {
        throw new Error(data.error);
      }

      // Success - clear checkpoint and refresh
      setCheckpoint(null);
      if (onRefresh) {
        onRefresh();
      }
    } catch (err) {
      setCheckpointError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`blocked-session-card ${session.blocked_type} ${isHITLBlocked ? 'expanded' : ''}`}>
      <div className="card-header">
        <div className="session-info">
          <Icon icon={blockedTypeIcon} width="18" className="type-icon" />
          <span className="session-id" onClick={() => onViewSession(session.session_id)}>
            {session.session_id}
          </span>
        </div>
        <div className="cascade-info">
          <span className="cascade-id">{session.cascade_id}</span>
          {session.current_phase && (
            <span className="phase-name">@ {session.current_phase}</span>
          )}
        </div>
        <div className="header-actions">
          <div className="timing-info-compact">
            <Icon icon="mdi:clock-outline" width="14" />
            <span>{formatWaitTime(waitingSeconds)}</span>
          </div>
          <button
            className="btn-action cancel"
            onClick={() => onCancelSession(session.session_id)}
            title="Cancel this blocked session"
          >
            <Icon icon="mdi:close-circle" width="16" />
          </button>
        </div>
      </div>

      {/* Full checkpoint UI - always visible for HITL sessions */}
      {isHITLBlocked && (
        <div className="checkpoint-full-container">
          {checkpointLoading && (
            <div className="checkpoint-loading">
              <Icon icon="mdi:loading" className="spinning" width="24" />
              <span>Loading decision interface...</span>
            </div>
          )}

          {checkpointError && (
            <div className="checkpoint-error">
              <Icon icon="mdi:alert-circle" width="18" />
              <span>{checkpointError}</span>
              <button onClick={fetchCheckpoint} className="retry-btn">
                <Icon icon="mdi:refresh" width="16" />
                Retry
              </button>
            </div>
          )}

          {checkpoint && checkpoint.ui_spec && (
            <div className="checkpoint-ui-full">
              {/* Check if UI has HTML sections - render inline with message */}
              {(() => {
                const hasHTMLSection = checkpoint.ui_spec.sections?.some(s => s.type === 'html');

                if (hasHTMLSection) {
                  // Inline rendering: message + HTMX form in natural flow
                  return (
                    <MessageWithInlineCheckpoint
                      checkpoint={checkpoint}
                      onSubmit={handleSubmitResponse}
                      isLoading={submitting}
                      checkpointId={checkpoint.id}
                      sessionId={session.session_id}
                    />
                  );
                } else {
                  // Traditional DSL UI (card_grid, choice, text_input, etc.)
                  return (
                    <DynamicUI
                      spec={checkpoint.ui_spec}
                      onSubmit={handleSubmitResponse}
                      isLoading={submitting}
                      phaseOutput={checkpoint.phase_output}
                      checkpointId={checkpoint.id}
                      sessionId={session.session_id}
                    />
                  );
                }
              })()}
            </div>
          )}

          {checkpoint && !checkpoint.ui_spec && (
            <div className="checkpoint-no-ui">
              <p>This checkpoint has no UI specification.</p>
              <button
                className="btn-action respond"
                onClick={() => handleSubmitResponse({ acknowledged: true })}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Acknowledge & Continue'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Signal blocked - show compact info and fire button */}
      {isSignalBlocked && (
        <div className="card-body">
          <div className="blocked-on">
            <span className="blocked-label">Waiting for signal:</span>
            <span className="blocked-value">{session.blocked_on || 'unknown'}</span>
          </div>

          {session.blocked_description && (
            <div className="description">{session.blocked_description}</div>
          )}

          <div className="timing-info">
            <div className="waiting-time">
              <Icon icon="mdi:clock-outline" width="14" />
              <span>{formatWaitTime(waitingSeconds)} waiting</span>
            </div>
            {matchingSignal?.timeout_remaining_seconds !== undefined && (
              <div className={`timeout ${matchingSignal.timeout_remaining_seconds < 300 ? 'warning' : ''}`}>
                <Icon icon="mdi:timer-sand" width="14" />
                <span>{formatTimeRemaining(matchingSignal.timeout_remaining_seconds)}</span>
              </div>
            )}
          </div>

          <div className="card-actions">
            {matchingSignal && (
              <button
                className="btn-action fire"
                onClick={() => onFireSignal(matchingSignal)}
                title="Fire this signal to unblock the cascade"
              >
                <Icon icon="mdi:flash" width="16" />
                Fire Signal
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Main Blocked Sessions View
 */
function BlockedSessionsView({ onBack, onSelectInstance }) {
  const [blockedSessions, setBlockedSessions] = useState([]);
  const [waitingSignals, setWaitingSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSignal, setSelectedSignal] = useState(null);

  // Fetch blocked sessions and waiting signals
  const fetchData = useCallback(async () => {
    try {
      const [sessionsRes, signalsRes] = await Promise.all([
        fetch('http://localhost:5001/api/sessions/blocked'),
        fetch('http://localhost:5001/api/signals/waiting')
      ]);

      const sessionsData = await sessionsRes.json();
      const signalsData = await signalsRes.json();

      if (sessionsData.error) {
        setError(sessionsData.error);
        return;
      }

      setBlockedSessions(sessionsData.sessions || []);
      setWaitingSignals(signalsData.signals || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Poll every 5 seconds
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Fire a signal
  const handleFireSignal = async (signal, payload) => {
    const response = await fetch(`http://localhost:5001/api/signals/fire-by-id/${signal.signal_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        payload: payload,
        source: 'ui'
      })
    });

    const data = await response.json();
    if (data.error) {
      throw new Error(data.error);
    }

    // Refresh data
    await fetchData();
  };

  // Cancel a session
  const handleCancelSession = async (sessionId) => {
    try {
      const response = await fetch(`http://localhost:5001/api/sessions/${sessionId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: 'Cancelled from Blocked Sessions view',
          force: true // Force cancel since it's blocked
        })
      });

      const data = await response.json();
      if (data.error) {
        console.error('Failed to cancel session:', data.error);
      }

      // Refresh data
      await fetchData();
    } catch (err) {
      console.error('Failed to cancel session:', err);
    }
  };

  // View a session
  const handleViewSession = (sessionId) => {
    if (onSelectInstance) {
      onSelectInstance(sessionId);
    }
  };

  // Group sessions by blocked type
  const sessionsByType = blockedSessions.reduce((acc, session) => {
    const type = session.blocked_type || 'other';
    if (!acc[type]) acc[type] = [];
    acc[type].push(session);
    return acc;
  }, {});

  const typeLabels = {
    'signal': { label: 'Waiting for Signals', icon: 'mdi:clock-alert-outline' },
    'hitl': { label: 'Waiting for Human Input', icon: 'mdi:account-clock' },
    'approval': { label: 'Waiting for Approval', icon: 'mdi:check-decagram' },
    'decision': { label: 'Awaiting Decision', icon: 'mdi:help-circle-outline' },
    'sensor': { label: 'Waiting for Sensor', icon: 'mdi:radar' },
    'checkpoint': { label: 'At Checkpoint', icon: 'mdi:flag-checkered' },
    'other': { label: 'Other Blocked', icon: 'mdi:pause-circle' }
  };

  if (loading) {
    return (
      <div className="blocked-sessions-container">
        <div className="loading">
          <VideoSpinner message="Loading blocked sessions..." size={400} opacity={0.6} />
        </div>
      </div>
    );
  }

  return (
    <div className="blocked-sessions-container">
      <header className="blocked-header">
        <div className="header-left">
          <button className="back-btn" onClick={onBack} title="Back">
            <Icon icon="mdi:arrow-left" width="20" />
          </button>
          <h1>
            <Icon icon="mdi:pause-circle-outline" width="28" />
            Blocked Sessions
          </h1>
          <span className="count-badge">{blockedSessions.length}</span>
        </div>
        <div className="header-right">
          <button className="refresh-btn" onClick={fetchData} title="Refresh">
            <Icon icon="mdi:refresh" width="20" />
          </button>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
        </div>
      )}

      {blockedSessions.length === 0 ? (
        <div className="empty-state">
          <Icon icon="mdi:check-circle-outline" width="64" />
          <h2>No Blocked Sessions</h2>
          <p>All cascades are running smoothly. No sessions are waiting for signals or human input.</p>
        </div>
      ) : (
        <div className="blocked-groups">
          {Object.entries(sessionsByType).map(([type, sessions]) => {
            const typeInfo = typeLabels[type] || typeLabels.other;
            return (
              <div key={type} className={`blocked-group ${type}`}>
                <div className="group-header">
                  <Icon icon={typeInfo.icon} width="20" />
                  <h2>{typeInfo.label}</h2>
                  <span className="group-count">{sessions.length}</span>
                </div>
                <div className="group-sessions">
                  {sessions.map(session => (
                    <BlockedSessionCard
                      key={session.session_id}
                      session={session}
                      signals={waitingSignals}
                      onFireSignal={setSelectedSignal}
                      onCancelSession={handleCancelSession}
                      onViewSession={handleViewSession}
                      onRefresh={fetchData}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Signal Fire Modal */}
      {selectedSignal && (
        <SignalFireModal
          signal={selectedSignal}
          onClose={() => setSelectedSignal(null)}
          onFire={handleFireSignal}
        />
      )}
    </div>
  );
}

export default BlockedSessionsView;
