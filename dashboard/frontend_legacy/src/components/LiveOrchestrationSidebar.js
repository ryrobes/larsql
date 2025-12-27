import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import CompactResearchTree from './CompactResearchTree';
import './LiveOrchestrationSidebar.css';

/**
 * LiveOrchestrationSidebar - Real-time cascade orchestration visualization
 *
 * Inspired by Bret Victor's "Inventing on Principle" - make the invisible visible
 *
 * Shows:
 * - Current phase (animated)
 * - Model being used
 * - Live cost ticker
 * - Tool calls as they happen
 * - Turn counter
 * - Token usage
 * - Phase history
 * - Status indicators (thinking, tool running, waiting)
 *
 * This is the "orchestration observatory" - you SEE what RVBBIT is doing
 */
function LiveOrchestrationSidebar({
  sessionId,
  cascadeId,
  orchestrationState,
  sessionData,
  roundEvents = [],
  narrationAmplitude = 0
}) {
  const [costAnimation, setCostAnimation] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [previousSessions, setPreviousSessions] = useState([]);
  const [sessionsCollapsed, setSessionsCollapsed] = useState(true);

  // Debug narration amplitude
  // useEffect(() => {
  //   if (narrationAmplitude > 0.01) {
  //     console.log('[LiveOrchestrationSidebar] Narration amplitude:', narrationAmplitude);
  //   }
  // }, [narrationAmplitude]);
  const [cancellingSession, setCancellingSession] = useState(false);

  // Animate cost changes
  useEffect(() => {
    if (orchestrationState.totalCost > 0) {
      setCostAnimation(true);
      const timer = setTimeout(() => setCostAnimation(false), 600);
      return () => clearTimeout(timer);
    }
  }, [orchestrationState.totalCost]);

  // Update timestamp when data changes
  useEffect(() => {
    setLastUpdate(new Date());
  }, [sessionData, orchestrationState]);

  // Fetch previous research sessions
  const fetchPreviousSessions = useCallback(async () => {
    if (!cascadeId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/research-sessions?cascade_id=${cascadeId}&limit=10`);
      const data = await res.json();

      if (!data.error) {
        setPreviousSessions(data.sessions || []);
      }
    } catch (err) {
      console.error('[LiveOrchestrationSidebar] Failed to fetch previous sessions:', err);
    }
  }, [cascadeId]);

  // Fetch previous sessions on mount and when cascade changes
  useEffect(() => {
    if (cascadeId) {
      fetchPreviousSessions();

      // Auto-refresh every 5 seconds to show newly saved sessions
      const interval = setInterval(fetchPreviousSessions, 5000);
      return () => clearInterval(interval);
    }
  }, [cascadeId, fetchPreviousSessions]);

  // Status indicator colors and icons
  const statusConfig = {
    idle: {
      color: '#6b7280',
      icon: 'mdi:pause-circle-outline',
      label: 'Idle',
      pulse: false
    },
    thinking: {
      color: '#a78bfa',
      icon: 'mdi:brain',
      label: 'Thinking',
      pulse: true
    },
    tool_running: {
      color: '#10b981',
      icon: 'mdi:wrench',
      label: 'Running Tool',
      pulse: true
    },
    waiting_human: {
      color: '#fbbf24',
      icon: 'mdi:account-clock',
      label: 'Awaiting Input',
      pulse: true
    }
  };

  const currentStatus = statusConfig[orchestrationState.status] || statusConfig.idle;

  // Handle cascade cancellation
  const handleCancelCascade = useCallback(async () => {
    if (!sessionId || cancellingSession) return;

    setCancellingSession(true);
    try {
      const res = await fetch('http://localhost:5001/api/cancel-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          reason: 'User clicked END button'
        })
      });

      const data = await res.json();

      if (data.error) {
        console.error('[LiveOrchestrationSidebar] Failed to cancel:', data.error);
      } else {
        //console.log('[LiveOrchestrationSidebar] Cancellation requested:', data);
      }
    } catch (err) {
      console.error('[LiveOrchestrationSidebar] Cancel request failed:', err);
    } finally {
      // Keep the cancelling state for a bit to show feedback
      setTimeout(() => setCancellingSession(false), 2000);
    }
  }, [sessionId, cancellingSession]);

  // Debug logging
  useEffect(() => {
    // console.log('[LiveOrchestrationSidebar] State update:', {
    //   status: orchestrationState.status,
    //   currentPhase: orchestrationState.currentPhase,
    //   totalCost: orchestrationState.totalCost,
    //   turnCount: orchestrationState.turnCount,
    //   currentModel: orchestrationState.currentModel
    // });
  }, [orchestrationState]);

  useEffect(() => {
    // console.log('[LiveOrchestrationSidebar] Session data update:', {
    //   totalCost: sessionData?.total_cost,
    //   phaseCosts: sessionData?.phase_costs,
    //   inputTokens: sessionData?.total_input_tokens,
    //   outputTokens: sessionData?.total_output_tokens
    // });
  }, [sessionData]);


  return (
    <div className="live-orchestration-sidebar">
      {/* Live Indicator + Auto-Save Badge */}
      <div className="sidebar-live-indicator">
        <div className="live-dot" />
        <span className="live-label">LIVE</span>
        <span className="live-timestamp">
          {lastUpdate.toLocaleTimeString()}
        </span>
      </div>

      {/* Auto-Save Indicator */}
      {/* {sessionId && sessionId.startsWith('research_') && (
        <div className="auto-save-indicator">
          <Icon icon="mdi:content-save-check" width="14" />
          <span>Auto-saving</span>
        </div>
      )} */}

      {/* Status Header */}
      <div className="sidebar-section status-section">
        <div className="status-orb-container">
          {/* Orbiting event circles */}
          <div className="event-orbits">
            {roundEvents.map((event, index) => {
              const eventColors = {
                tool_call: '#10b981',    // green
                tool_result: '#34d399',  // light green
                llm_request: '#a78bfa',  // purple
                llm_response: '#8b5cf6', // dark purple
              };
              const color = eventColors[event.type] || '#6b7280';
              const angle = (index * 137.5) % 360; // Golden angle for nice distribution
              const orbitRadius = 52 + (index % 3) * 8; // Varying orbit radii

              return (
                <div
                  key={event.id}
                  className="event-orbit-dot"
                  style={{
                    '--orbit-angle': `${angle}deg`,
                    '--orbit-radius': `${orbitRadius}px`,
                    '--dot-color': color,
                    '--animation-delay': `${index * 0.1}s`,
                  }}
                  title={event.tool || event.type}
                >
                  {event.type === 'tool_call' && (
                    <Icon icon="mdi:wrench" width="10" style={{ color: '#fff' }} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Main status indicator - remove pulse class when narrating to avoid box-shadow conflict */}
          <div
            className={`status-indicator-large ${narrationAmplitude > 0.02 ? '' : (currentStatus.pulse ? 'pulse' : '')}`}
            style={{
              borderColor: currentStatus.color,
              // Narration glow - remapped range for maximum variation visibility
              boxShadow: (() => {
                if (narrationAmplitude <= 0.02) return undefined;

                // Remap typical speech range (0.2-0.6) to visual range (0-1)
                // This makes variations in normal speech much more visible
                const minAmp = 0.2;
                const maxAmp = 0.6;
                const remapped = Math.max(0, Math.min(1, (narrationAmplitude - minAmp) / (maxAmp - minAmp)));

                // Apply gentle curve for even better feel (x^1.2)
                const curved = Math.pow(remapped, 1.2);

                return `
                  /* Multi-layer glow - remapped to show speech variations */
                  0 0 ${15 + curved * 100}px ${8 + curved * 50}px ${currentStatus.color}85,
                  0 0 ${25 + curved * 140}px ${12 + curved * 70}px ${currentStatus.color}65,
                  0 0 ${40 + curved * 180}px ${20 + curved * 90}px ${currentStatus.color}45,
                  0 0 ${60 + curved * 220}px ${30 + curved * 110}px ${currentStatus.color}25,
                  /* Inner glow for depth */
                  inset 0 0 ${12 + curved * 45}px ${6 + curved * 22}px ${currentStatus.color}55,
                  /* Sharp border highlight */
                  0 0 0 ${2 + curved * 4}px ${currentStatus.color}90
                `;
              })()
              // No transition here - smoothing happens in React state
            }}
          >
            <Icon
              icon={currentStatus.icon}
              width="32"
              style={{
                color: currentStatus.color,
                // Icon glows intensely with narration
                filter: narrationAmplitude > 0.05
                  ? `drop-shadow(0 0 ${8 + narrationAmplitude * 20}px ${currentStatus.color})
                     brightness(${1 + narrationAmplitude * 0.3})`
                  : undefined,
                transition: 'filter 0.05s ease-out'
              }}
              className={currentStatus.pulse ? 'spinning' : ''}
            />
          </div>
        </div>

        <div className="status-label" style={{ color: currentStatus.color }}>
          {currentStatus.label}
        </div>

        {/* Event count badge */}
        {roundEvents.length > 0 && (
          <div className="round-events-badge">
            <span className="event-count">{roundEvents.length}</span>
            <span className="event-label">
              {roundEvents.filter(e => e.type === 'tool_call').length} tools
            </span>
          </div>
        )}

        {orchestrationState.lastToolCall && orchestrationState.status === 'tool_running' && (
          <div className="tool-call-badge">
            <Icon icon="mdi:tools" width="14" />
            {orchestrationState.lastToolCall}
          </div>
        )}

        {/* END button - subtle, shows when cascade is active */}
        {orchestrationState.status !== 'idle' && (
          <button
            className={`end-cascade-btn ${cancellingSession ? 'cancelling' : ''}`}
            onClick={handleCancelCascade}
            disabled={cancellingSession}
            title="End cascade gracefully"
          >
            <Icon icon={cancellingSession ? 'mdi:loading' : 'mdi:stop-circle-outline'} width="14" className={cancellingSession ? 'spinning' : ''} />
            <span>{cancellingSession ? 'Ending...' : 'END'}</span>
          </button>
        )}
      </div>

      {/* Cost Ticker */}
      <div className="sidebar-section cost-section">
        <div className="section-header">
          <Icon icon="mdi:currency-usd" width="18" />
          <span>Total Cost</span>
        </div>
        <div className={`cost-display ${costAnimation ? 'cost-bump' : ''} ${(orchestrationState.totalCost || 0) === 0 ? 'zero' : ''}`}>
          {(orchestrationState.totalCost || 0) === 0 ? (
            <span style={{fontSize: '1rem', color: '#6b7280'}}>No cost yet...</span>
          ) : (
            `$${orchestrationState.totalCost.toFixed(4)}`
          )}
        </div>
        {sessionData?.phase_costs && (
          <div className="cost-breakdown">
            {Object.entries(sessionData.phase_costs).slice(-3).map(([phase, cost]) => (
              <div key={phase} className="cost-item">
                <span className="cost-phase">{phase}</span>
                <span className="cost-value">${cost.toFixed(4)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Session Overview - Compact combined section */}
      <div className="sidebar-section session-overview-section">
        <div className="section-header">
          <Icon icon="mdi:information" width="18" />
          <span>Session</span>
        </div>

        <div className="overview-grid">
          {/* Phase */}
          <div className="overview-item phase">
            <div className="overview-label">
              <Icon icon="mdi:hexagon" width="14" />
              <span>Phase</span>
            </div>
            <div className="overview-value phase-value">
              {orchestrationState.currentPhase || 'N/A'}
            </div>
            {sessionData?.model && (
              <div className="model-badge-compact">
                <Icon icon="mdi:robot" width="12" />
                {sessionData.model.split('/').pop()}
              </div>
            )}
          </div>

          {/* Turns */}
          <div className="overview-item turns">
            <div className="overview-label">
              <Icon icon="mdi:counter" width="14" />
              <span>Turns</span>
            </div>
            <div className={`overview-value turn-value ${(orchestrationState.turnCount || 0) === 0 ? 'zero' : ''}`}>
              {orchestrationState.turnCount || 0}
            </div>
          </div>

          {/* Messages */}
          <div className="overview-item messages">
            <div className="overview-label">
              <Icon icon="mdi:message-text" width="14" />
              <span>Messages</span>
            </div>
            <div className={`overview-value messages-value ${(sessionData?.entries?.length || 0) === 0 ? 'zero' : ''}`}>
              {sessionData?.entries?.length || 0}
            </div>
          </div>

          {/* Duration */}
          <div className="overview-item duration">
            <div className="overview-label">
              <Icon icon="mdi:clock-outline" width="14" />
              <span>Duration</span>
            </div>
            <div className={`overview-value duration-value ${(sessionData?.duration_seconds || 0) === 0 ? 'zero' : ''}`}>
              {sessionData?.duration_seconds > 0
                ? `${Math.floor(sessionData.duration_seconds / 60)}m ${Math.floor(sessionData.duration_seconds % 60)}s`
                : '0s'}
            </div>
          </div>

          {/* Session ID */}
          <div className="overview-item session-id">
            <div className="overview-label">
              <Icon icon="mdi:fingerprint" width="14" />
              <span>ID</span>
            </div>
            <div className="overview-value session-value mono">
              {sessionId?.slice(0, 12)}...
            </div>
          </div>
        </div>
      </div>

      {/* Phase History */}
      {orchestrationState.phaseHistory && orchestrationState.phaseHistory.length > 0 && (
        <div className="sidebar-section history-section">
          <div className="section-header">
            <Icon icon="mdi:timeline" width="18" />
            <span>Phase Flow</span>
          </div>
          <div className="phase-timeline">
            {orchestrationState.phaseHistory.slice(-5).map((item, idx) => (
              <div key={idx} className="phase-timeline-item">
                <div className="phase-timeline-dot" />
                <div className="phase-timeline-content">
                  <div className="phase-timeline-name">{item.phase}</div>
                  {item.model && (
                    <div className="phase-timeline-model">
                      {item.model.split('/').pop()}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Token Usage (if available) */}
      {sessionData?.total_input_tokens > 0 && (
        <div className="sidebar-section tokens-section">
          <div className="section-header">
            <Icon icon="mdi:alphabetical" width="18" />
            <span>Tokens</span>
          </div>
          <div className="token-stats">
            <div className="token-stat">
              <span className="token-label">Input</span>
              <span className="token-value">
                {sessionData.total_input_tokens?.toLocaleString() || 0}
              </span>
            </div>
            <div className="token-stat">
              <span className="token-label">Output</span>
              <span className="token-value">
                {sessionData.total_output_tokens?.toLocaleString() || 0}
              </span>
            </div>
            <div className="token-stat total">
              <span className="token-label">Total</span>
              <span className="token-value">
                {((sessionData.total_input_tokens || 0) + (sessionData.total_output_tokens || 0)).toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Research Tree - Compact indented view */}
      {sessionId && (
        <CompactResearchTree
          sessionId={sessionId}
          currentSessionId={sessionId}
        />
      )}

      {/* Previous Research Sessions */}
      {previousSessions.length > 0 && (
        <div className="sidebar-section sessions-section">
          <div
            className="section-header clickable"
            onClick={() => setSessionsCollapsed(!sessionsCollapsed)}
            style={{ cursor: 'pointer' }}
            title="Auto-saved sessions - click to browse"
          >
            <Icon icon="mdi:history" width="18" />
            <span>Saved Sessions ({previousSessions.length})</span>
            <Icon
              icon={sessionsCollapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'}
              width="18"
              style={{ marginLeft: 'auto' }}
            />
          </div>
          {!sessionsCollapsed && (
            <div className="previous-sessions-list">
              {previousSessions.map((session) => (
                <div
                  key={session.id}
                  className="session-item"
                  onClick={() => {
                    // Navigate to this session
                    window.location.hash = `#/cockpit/${session.original_session_id}`;
                  }}
                >
                  <div className="session-item-header">
                    <h4 className="session-title">
                      {session.title}
                    </h4>
                    <div className="session-date">
                      {new Date(session.frozen_at).toLocaleDateString()}
                    </div>
                  </div>
                  {session.description && (
                    <p className="session-description">
                      {session.description.substring(0, 80)}
                      {session.description.length > 80 ? '...' : ''}
                    </p>
                  )}
                  <div className="session-stats">
                    <span className="session-stat">
                      <Icon icon="mdi:currency-usd" width="12" />
                      ${session.total_cost?.toFixed(4) || '0.0000'}
                    </span>
                    <span className="session-stat">
                      <Icon icon="mdi:counter" width="12" />
                      {session.total_turns || 0} turns
                    </span>
                    <span className="session-stat">
                      <Icon icon="mdi:clock-outline" width="12" />
                      {Math.floor((session.duration_seconds || 0) / 60)}m
                    </span>
                  </div>
                  {session.tags && session.tags.length > 0 && (
                    <div className="session-tags">
                      {session.tags.slice(0, 3).map((tag, idx) => (
                        <span key={idx} className="session-tag">{tag}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Bret Victor Quote */}
      <div className="sidebar-footer">
        <div className="bret-victor-quote">
          <Icon icon="mdi:lightbulb-outline" width="16" />
          <span>"Creators need an immediate connection to what they're creating."</span>
        </div>
      </div>
    </div>
  );
}

export default LiveOrchestrationSidebar;
