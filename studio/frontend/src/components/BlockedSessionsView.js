import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import VideoSpinner from './VideoSpinner';
import DynamicUI from './DynamicUI';
import MessageWithInlineCheckpoint from './MessageWithInlineCheckpoint';
import Header from './Header';
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
const BlockedSessionCard = React.memo(function BlockedSessionCard({ session, signals, onFireSignal, onCancelSession, onViewSession, onRefresh }) {
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
      const listRes = await fetch(`http://localhost:5050/api/checkpoints?session_id=${session.session_id}`);
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
      const detailRes = await fetch(`http://localhost:5050/api/checkpoints/${pending.id}`);
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
  // If session has multiple checkpoints (parallel soundings), use the first one
  useEffect(() => {
    if (isHITLBlocked) {
      // Check if session already has checkpoints array from parent
      if (session.checkpoints && session.checkpoints.length > 0) {
        // Use first checkpoint (or we could show all)
        setCheckpoint(session.checkpoints[0]);
        setCheckpointLoading(false);
      } else {
        fetchCheckpoint();
      }
    }
  }, [isHITLBlocked, fetchCheckpoint, session.checkpoints]);

  // Handle checkpoint response submission
  const handleSubmitResponse = async (values) => {
    if (!checkpoint?.id) return;

    setSubmitting(true);
    try {
      const response = await fetch(`http://localhost:5050/api/checkpoints/${checkpoint.id}/respond`, {
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

          {/* Show all checkpoints for parallel soundings */}
          {session.checkpoints && session.checkpoints.length > 1 && (
            <div className="multiple-checkpoints-notice">
              <Icon icon="mdi:source-fork" width="16" />
              <span>{session.checkpoints.length} parallel sounding decisions</span>
            </div>
          )}

          {session.checkpoints && session.checkpoints.map((cp, idx) => (
            <div key={cp.id} className="checkpoint-instance">
              {cp.ui_spec && (
                <div className="checkpoint-ui-full">
                  {/* Sounding badge if this checkpoint is from a sounding */}
                  {cp.ui_spec._meta?.candidate_index !== undefined && cp.ui_spec._meta.candidate_index !== null && (
                    <div className="checkpoint-sounding-badge">
                      <Icon icon="mdi:source-fork" width="16" />
                      <span>Sounding {cp.ui_spec._meta.candidate_index}</span>
                    </div>
                  )}

                  {/* Check if UI has HTML sections - render inline with message */}
                  {(() => {
                    const hasHTMLSection = cp.ui_spec.sections?.some(s => s.type === 'html');

                    if (hasHTMLSection) {
                      // Inline rendering: message + HTMX form in natural flow
                      return (
                        <MessageWithInlineCheckpoint
                          checkpoint={cp}
                          onSubmit={handleSubmitResponse}
                          isLoading={submitting}
                          checkpointId={cp.id}
                          sessionId={session.session_id}
                        />
                      );
                    } else {
                      // Traditional DSL UI (card_grid, choice, text_input, etc.)
                      return (
                        <DynamicUI
                          spec={cp.ui_spec}
                          onSubmit={handleSubmitResponse}
                          isLoading={submitting}
                          phaseOutput={cp.phase_output}
                          checkpointId={cp.id}
                          sessionId={session.session_id}
                        />
                      );
                    }
                  })()}
                </div>
              )}
            </div>
          ))}

          {/* Fallback: single checkpoint from state (old behavior) */}
          {!session.checkpoints && checkpoint && checkpoint.ui_spec && (
            <div className="checkpoint-ui-full">
              {/* Sounding badge if this checkpoint is from a sounding */}
              {checkpoint.ui_spec._meta?.candidate_index !== undefined && checkpoint.ui_spec._meta.candidate_index !== null && (
                <div className="checkpoint-sounding-badge">
                  <Icon icon="mdi:source-fork" width="16" />
                  <span>Sounding {checkpoint.ui_spec._meta.candidate_index}</span>
                </div>
              )}

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
}, (prevProps, nextProps) => {
  // Custom comparison: only re-render if session checkpoint IDs changed
  const prevCheckpointIds = prevProps.session.checkpoints?.map(cp => cp.id).join(',') || '';
  const nextCheckpointIds = nextProps.session.checkpoints?.map(cp => cp.id).join(',') || '';
  return prevCheckpointIds === nextCheckpointIds;
});

/**
 * Main Blocked Sessions View
 */
function BlockedSessionsView({ onBack, onSelectInstance, onMessageFlow, onSextant, onWorkshop, onPlayground, onTools, onSearch, onArtifacts, onBlocked, blockedCount = 0, sseConnected = false }) {
  const [blockedSessions, setBlockedSessions] = useState([]);
  const [waitingSignals, setWaitingSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [showResearchCockpit, setShowResearchCockpit] = useState(false); // Filter toggle for research cockpit checkpoints
  const [hiddenResearchCount, setHiddenResearchCount] = useState(0); // Count of hidden research checkpoints

  // Fetch blocked sessions and waiting signals
  const fetchData = useCallback(async () => {
    try {
      const [checkpointsRes, signalsRes] = await Promise.all([
        fetch('http://localhost:5050/api/checkpoints'),  // Get pending checkpoints directly
        fetch('http://localhost:5050/api/signals/waiting')
      ]);

      const checkpointsData = await checkpointsRes.json();
      const signalsData = await signalsRes.json();

      if (checkpointsData.error) {
        setError(checkpointsData.error);
        return;
      }

      // Debug logging
      console.log('[BlockedSessionsView] Fetched checkpoints:', checkpointsData.checkpoints?.length || 0);

      // Filter out research cockpit checkpoints unless toggle is enabled
      // Research sessions have session_id starting with "research_"
      // They have dedicated inline UI in the Research Cockpit and shouldn't clutter this view
      let checkpointsToShow = checkpointsData.checkpoints || [];

      // Count research cockpit checkpoints (session_id starts with "research_")
      const researchCockpitCheckpoints = checkpointsToShow.filter(cp =>
        cp.session_id?.startsWith('research_')
      );

      // Track hidden count for the toggle badge
      setHiddenResearchCount(researchCockpitCheckpoints.length);

      if (!showResearchCockpit && researchCockpitCheckpoints.length > 0) {
        // Filter out research cockpit checkpoints by session_id prefix
        checkpointsToShow = checkpointsToShow.filter(cp =>
          !cp.session_id?.startsWith('research_')
        );
        console.log(`[BlockedSessionsView] Filtered out ${researchCockpitCheckpoints.length} research cockpit checkpoints (toggle off)`);
      }

      // Build sessions from pending checkpoints (group by session_id)
      const sessionMap = {};
      checkpointsToShow.forEach(cp => {
        console.log('[BlockedSessionsView] Processing checkpoint:', cp.id, 'session:', cp.session_id);

        const sid = cp.session_id;
        if (!sessionMap[sid]) {
          sessionMap[sid] = {
            session_id: sid,
            cascade_id: cp.cascade_id,
            current_phase: cp.cell_name,
            blocked_type: cp.checkpoint_type,
            blocked_on: cp.id,
            timeout_at: cp.timeout_at,
            created_at: cp.created_at,
            checkpoints: []
          };
        }
        sessionMap[sid].checkpoints.push(cp);
      });

      const sessions = Object.values(sessionMap);
      console.log('[BlockedSessionsView] Built sessions from checkpoints:', sessions.length);
      sessions.forEach(s => {
        console.log(`  - ${s.session_id}: ${s.checkpoints.length} checkpoints`);
      });

      // Only update state if data actually changed (prevents iframe recreation)
      setBlockedSessions(prevSessions => {
        // Check if checkpoint IDs changed
        const prevIds = new Set(prevSessions.flatMap(s => s.checkpoints?.map(cp => cp.id) || []));
        const newIds = new Set(sessions.flatMap(s => s.checkpoints?.map(cp => cp.id) || []));

        const idsMatch = prevIds.size === newIds.size && [...prevIds].every(id => newIds.has(id));

        if (idsMatch && prevSessions.length === sessions.length) {
          console.log('[BlockedSessionsView] Data unchanged, keeping existing state');
          return prevSessions; // Don't update - prevents iframe recreation
        }

        console.log('[BlockedSessionsView] Data changed, updating state');
        return sessions;
      });

      setWaitingSignals(signalsData.signals || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [showResearchCockpit]); // Re-fetch when filter toggle changes

  useEffect(() => {
    fetchData();
    // Poll every 5 seconds
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Fire a signal
  const handleFireSignal = async (signal, payload) => {
    const response = await fetch(`http://localhost:5050/api/signals/fire-by-id/${signal.signal_id}`, {
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

  // Cancel a session by cancelling all its checkpoints
  const handleCancelSession = async (sessionId) => {
    try {
      // Find this session to get its checkpoints
      const session = blockedSessions.find(s => s.session_id === sessionId);

      if (session && session.checkpoints && session.checkpoints.length > 0) {
        // Cancel all checkpoints for this session
        console.log(`[BlockedSessionsView] Cancelling ${session.checkpoints.length} checkpoints for session ${sessionId}`);

        await Promise.all(
          session.checkpoints.map(cp =>
            fetch(`http://localhost:5050/api/checkpoints/${cp.id}/cancel`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                reason: 'Cancelled from Blocked Sessions view'
              })
            })
          )
        );

        console.log(`[BlockedSessionsView] Cancelled all checkpoints for ${sessionId}`);
      } else {
        // Fallback: try session-level cancel (for signal-blocked sessions)
        const response = await fetch(`http://localhost:5050/api/sessions/${sessionId}/cancel`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            reason: 'Cancelled from Blocked Sessions view',
            force: true
          })
        });

        const data = await response.json();
        if (data.error) {
          console.error('Failed to cancel session:', data.error);
        }
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
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:pause-circle-outline" width="28" style={{ marginRight: '8px' }} />
            <span className="header-stat">Blocked Sessions</span>
            {blockedSessions.length > 0 && (
              <>
                <span className="header-divider">·</span>
                <span className="header-stat">{blockedSessions.length} <span className="stat-dim">waiting</span></span>
              </>
            )}
          </>
        }
        customButtons={
          <>
            {/* Only show toggle if there are research checkpoints */}
            {hiddenResearchCount > 0 && (
              <button
                onClick={() => setShowResearchCockpit(!showResearchCockpit)}
                title={showResearchCockpit ? "Hide Research Cockpit checkpoints" : "Show Research Cockpit checkpoints"}
                style={{
                  padding: '8px 14px',
                  background: showResearchCockpit
                    ? 'linear-gradient(135deg, rgba(167, 139, 250, 0.2), rgba(139, 92, 246, 0.2))'
                    : 'linear-gradient(135deg, rgba(107, 114, 128, 0.15), rgba(75, 85, 99, 0.15))',
                  border: showResearchCockpit ? '1px solid rgba(167, 139, 250, 0.4)' : '1px solid rgba(107, 114, 128, 0.3)',
                  borderRadius: '8px',
                  color: showResearchCockpit ? '#a78bfa' : '#9ca3af',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '0.85rem',
                  fontWeight: '500',
                  marginRight: '8px'
                }}>
                <Icon icon={showResearchCockpit ? "mdi:eye" : "mdi:eye-off"} width="18" />
                Research
                {!showResearchCockpit && (
                  <span style={{
                    background: 'rgba(167, 139, 250, 0.3)',
                    color: '#a78bfa',
                    padding: '2px 6px',
                    borderRadius: '10px',
                    fontSize: '0.75rem',
                    fontWeight: '600'
                  }}>
                    +{hiddenResearchCount}
                  </span>
                )}
              </button>
            )}

            <button className="refresh-btn" onClick={fetchData} title="Refresh" style={{
              padding: '8px 14px',
              background: 'linear-gradient(135deg, rgba(74, 158, 221, 0.15), rgba(94, 234, 212, 0.15))',
              border: '1px solid rgba(74, 158, 221, 0.3)',
              borderRadius: '8px',
              color: '#4A9EDD',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.85rem',
              fontWeight: '500'
            }}>
              <Icon icon="mdi:refresh" width="18" />
              Refresh
            </button>
          </>
        }
        onMessageFlow={onMessageFlow}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onPlayground={onPlayground}
        onTools={onTools}
        onSearch={onSearch}
        onArtifacts={onArtifacts}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

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
