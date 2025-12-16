import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import mermaid from 'mermaid';
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
 * This is the "orchestration observatory" - you SEE what Windlass is doing
 */
function LiveOrchestrationSidebar({
  sessionId,
  cascadeId,
  orchestrationState,
  sessionData
}) {
  const [costAnimation, setCostAnimation] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [mermaidContent, setMermaidContent] = useState(null);
  const [mermaidCollapsed, setMermaidCollapsed] = useState(false);
  const [previousSessions, setPreviousSessions] = useState([]);
  const [sessionsCollapsed, setSessionsCollapsed] = useState(true);
  const mermaidRef = React.useRef(null);

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

  // Fetch and render Mermaid graph
  const fetchMermaid = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/mermaid/${sessionId}`);
      const data = await res.json();

      if (!data.error && data.mermaid) {
        setMermaidContent(data.mermaid);
      }
    } catch (err) {
      console.error('[LiveOrchestrationSidebar] Failed to fetch mermaid:', err);
    }
  }, [sessionId]);

  // Initialize mermaid
  useEffect(() => {
    mermaid.initialize({
      startOnLoad: true,
      theme: 'dark',
      securityLevel: 'loose',
      fontFamily: 'IBM Plex Mono, monospace',
      themeVariables: {
        primaryTextColor: '#000',
        secondaryTextColor: '#000',
        tertiaryTextColor: '#000',
        textColor: '#000',
        nodeTextColor: '#000',
        labelTextColor: '#000',
      }
    });
  }, []);

  // Fetch mermaid on mount and when session updates
  useEffect(() => {
    if (sessionId) {
      fetchMermaid();

      // Refresh mermaid periodically
      const interval = setInterval(fetchMermaid, 3000);
      return () => clearInterval(interval);
    }
  }, [sessionId, fetchMermaid]);

  // Render mermaid when content changes
  useEffect(() => {
    if (!mermaidContent || !mermaidRef.current) return;

    const renderMermaid = async () => {
      try {
        // Add color to classDef if not present
        let modifiedContent = mermaidContent.replace(
          /classDef\s+(\w+)\s+([^;]+);/g,
          (match, className, styles) => {
            if (!styles.includes('color:')) {
              return `classDef ${className} ${styles},color:#000;`;
            }
            return match;
          }
        );

        mermaidRef.current.innerHTML = modifiedContent;
        const { svg } = await mermaid.render(`mermaid-sidebar-${sessionId}`, modifiedContent);
        mermaidRef.current.innerHTML = svg;
      } catch (err) {
        console.error('[LiveOrchestrationSidebar] Mermaid render error:', err);
        mermaidRef.current.innerHTML = '<div style="color: #ef4444; font-size: 0.75rem;">Graph render error</div>';
      }
    };

    renderMermaid();
  }, [mermaidContent, sessionId]);

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

  // Debug logging
  useEffect(() => {
    console.log('[LiveOrchestrationSidebar] State update:', {
      status: orchestrationState.status,
      currentPhase: orchestrationState.currentPhase,
      totalCost: orchestrationState.totalCost,
      turnCount: orchestrationState.turnCount,
      currentModel: orchestrationState.currentModel
    });
  }, [orchestrationState]);

  useEffect(() => {
    console.log('[LiveOrchestrationSidebar] Session data update:', {
      totalCost: sessionData?.total_cost,
      phaseCosts: sessionData?.phase_costs,
      inputTokens: sessionData?.total_input_tokens,
      outputTokens: sessionData?.total_output_tokens
    });
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
      {sessionId && sessionId.startsWith('research_') && (
        <div className="auto-save-indicator">
          <Icon icon="mdi:content-save-check" width="14" />
          <span>Auto-saving</span>
        </div>
      )}

      {/* Status Header */}
      <div className="sidebar-section status-section">
        <div
          className={`status-indicator-large ${currentStatus.pulse ? 'pulse' : ''}`}
          style={{ borderColor: currentStatus.color }}
        >
          <Icon
            icon={currentStatus.icon}
            width="32"
            style={{ color: currentStatus.color }}
            className={currentStatus.pulse ? 'spinning' : ''}
          />
        </div>
        <div className="status-label" style={{ color: currentStatus.color }}>
          {currentStatus.label}
        </div>
        {orchestrationState.lastToolCall && orchestrationState.status === 'tool_running' && (
          <div className="tool-call-badge">
            <Icon icon="mdi:tools" width="14" />
            {orchestrationState.lastToolCall}
          </div>
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

      {/* Current Phase */}
      <div className="sidebar-section phase-section">
        <div className="section-header">
          <Icon icon="mdi:hexagon" width="18" />
          <span>Current Phase</span>
        </div>
        {orchestrationState.currentPhase ? (
          <div className="phase-display">
            <div className="phase-name">{orchestrationState.currentPhase}</div>
            {sessionData?.model && (
              <div className="model-badge">
                <Icon icon="mdi:robot" width="14" />
                {sessionData.model.split('/').pop()}
              </div>
            )}
          </div>
        ) : (
          <div className="phase-empty">No active phase</div>
        )}
      </div>

      {/* Turn Counter */}
      <div className="sidebar-section turns-section">
        <div className="section-header">
          <Icon icon="mdi:counter" width="18" />
          <span>Turns</span>
        </div>
        <div className="turn-counter">
          <div className={`turn-number ${(orchestrationState.turnCount || 0) === 0 ? 'zero' : ''}`}>
            {orchestrationState.turnCount || 0}
          </div>
          <div className="turn-label">
            {(orchestrationState.turnCount || 0) === 0 ? 'waiting...' : 'iterations'}
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
      {sessionData?.total_input_tokens && (
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

      {/* Session Info */}
      <div className="sidebar-section session-info-section">
        <div className="section-header">
          <Icon icon="mdi:information" width="18" />
          <span>Session</span>
        </div>
        <div className="session-details">
          <div className="session-detail-item">
            <span className="detail-label">ID</span>
            <span className="detail-value mono">{sessionId?.slice(0, 12)}...</span>
          </div>
          {sessionData?.created_at && (
            <div className="session-detail-item">
              <span className="detail-label">Started</span>
              <span className="detail-value">
                {new Date(sessionData.created_at).toLocaleTimeString()}
              </span>
            </div>
          )}
          {sessionData?.duration_seconds && (
            <div className="session-detail-item">
              <span className="detail-label">Duration</span>
              <span className="detail-value">
                {Math.floor(sessionData.duration_seconds / 60)}m {Math.floor(sessionData.duration_seconds % 60)}s
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Execution Graph */}
      {mermaidContent && (
        <div className="sidebar-section graph-section">
          <div
            className="section-header clickable"
            onClick={() => setMermaidCollapsed(!mermaidCollapsed)}
            style={{ cursor: 'pointer' }}
          >
            <Icon icon="mdi:graph" width="18" />
            <span>Execution Graph</span>
            <Icon
              icon={mermaidCollapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'}
              width="18"
              style={{ marginLeft: 'auto' }}
            />
          </div>
          {!mermaidCollapsed && (
            <div className="mermaid-container-sidebar">
              <div
                ref={mermaidRef}
                className="mermaid-content"
              />
            </div>
          )}
        </div>
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
