import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import './SessionsView.css';

/**
 * SessionsView - Unified view of all active browser sessions
 *
 * Shows sessions from:
 * - UI (FlowBuilder)
 * - Cascades with browser config
 * - CLI tools
 * - Adopted orphans
 *
 * Features:
 * - Real-time MJPEG stream preview
 * - Kill sessions
 * - Attach to session (restore to FlowBuilder)
 * - View session artifacts
 * - Discover orphan sessions
 */
function SessionsView({
  onBack,
  onAttachSession,
  onViewArtifacts,
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onStudio,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
  sseConnected
}) {
  const [sessions, setSessions] = useState([]);
  const [discoveredSessions, setDiscoveredSessions] = useState([]); // Unregistered sessions found by scanning
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [scanningForSessions, setScanningForSessions] = useState(false);
  const [streamErrors, setStreamErrors] = useState({}); // Track which streams have failed

  const apiUrl = 'http://localhost:5050';

  // Convert orphan data from backend to session-like format
  const convertOrphanToSession = (orphan) => {
    const status = orphan.status || {};
    const currentState = status.currentState || {};

    // Try to get browser_session_path from multiple possible locations
    // 1. Direct sessionPath from status (most reliable)
    // 2. Build from currentState components
    // 3. Fallback: try the runs directory structure
    let browserSessionPath = status.sessionPath || null;

    if (!browserSessionPath && currentState.sessionId) {
      const clientId = currentState.clientId || 'default';
      const testId = currentState.testId || 'default';
      browserSessionPath = `${clientId}/${testId}/${currentState.sessionId}`;
    }

    // Get URL from various possible fields
    const currentUrl = currentState.initialUrl || currentState.url || status.url || null;

    return {
      session_id: `discovered_${orphan.port}`,
      port: orphan.port,
      pid: orphan.pid,
      source: 'discovered',
      healthy: true, // If we found it, it's responding
      started_at: null, // Unknown
      current_url: currentUrl,
      browser_session_path: browserSessionPath,
      has_browser_session: status.hasSession !== false, // Default to true if we found it
      is_discovered: true, // Flag to show adopt button
      // Include raw data for debugging
      _orphan_data: orphan
    };
  };

  // Check if a session can show a live stream
  const canShowLiveStream = (session) => {
    return session.healthy &&
           session.browser_session_path &&
           session.port &&
           !streamErrors[session.session_id];
  };

  // Handle stream error - fall back to static screenshot
  const handleStreamError = (sessionId) => {
    setStreamErrors(prev => ({ ...prev, [sessionId]: true }));
  };

  // Clear stream error when sessions refresh (session might be working again)
  const clearStreamErrors = () => {
    setStreamErrors({});
  };

  // Fetch both registered sessions AND discover unregistered ones
  const fetchSessions = useCallback(async () => {
    try {
      // Fetch registered sessions
      const registeredResponse = await fetch(`${apiUrl}/api/rabbitize/registry/sessions`);
      const registeredData = await registeredResponse.json();

      if (registeredData.error) {
        setError(registeredData.error);
      } else {
        setSessions(registeredData.sessions || []);
        setError(null);
      }

      // Also discover unregistered sessions (auto-discovery)
      try {
        const orphanResponse = await fetch(`${apiUrl}/api/rabbitize/registry/orphans`);
        const orphanData = await orphanResponse.json();
        const orphans = orphanData.orphans || [];

        // Convert orphans to session-like format
        const discovered = orphans.map(convertOrphanToSession);
        setDiscoveredSessions(discovered);
      } catch (orphanErr) {
        console.warn('Could not scan for unregistered sessions:', orphanErr);
        // Don't fail the whole fetch if orphan discovery fails
      }
    } catch (err) {
      setError('Failed to fetch sessions');
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  // Manual rescan (same as fetch but shows loading state)
  const manualRescan = async () => {
    setScanningForSessions(true);
    await fetchSessions();
    setScanningForSessions(false);
  };

  // Adopt a discovered session into the registry
  const adoptSession = async (session, e) => {
    if (e) e.stopPropagation();

    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/registry/orphans/${session.port}`, {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        // Remove from discovered, refresh registered sessions
        setDiscoveredSessions(prev => prev.filter(s => s.port !== session.port));
        fetchSessions();
      }
    } catch (err) {
      console.error('Failed to adopt session:', err);
    }
  };

  // Combined list of all sessions (registered + discovered)
  const allSessions = [...sessions, ...discoveredSessions];

  const killSession = async (session, e) => {
    if (e) e.stopPropagation();
    const displayId = session.is_discovered ? `Port ${session.port}` : session.session_id;
    if (!window.confirm(`Kill session ${displayId}?`)) return;

    try {
      if (session.is_discovered) {
        // For discovered sessions, call /end on the Rabbitize server directly
        // Then remove from discovered list
        try {
          await fetch(`http://localhost:${session.port}/end`, { method: 'POST' });
        } catch (endErr) {
          // Server might already be shutting down
          console.warn('End request failed (server may be stopping):', endErr);
        }
        setDiscoveredSessions(prev => prev.filter(s => s.port !== session.port));
      } else {
        // For registered sessions, use the registry API
        await fetch(`${apiUrl}/api/rabbitize/registry/sessions/${session.session_id}`, {
          method: 'DELETE'
        });
        fetchSessions();
      }

      if (selectedSession?.session_id === session.session_id) {
        setSelectedSession(null);
      }
    } catch (err) {
      console.error('Failed to kill session:', err);
    }
  };

  // Auto-refresh every 3 seconds
  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 3000);
    return () => clearInterval(interval);
  }, [fetchSessions]);

  const formatDuration = (startedAt) => {
    if (!startedAt) return '-';
    const start = new Date(startedAt);
    const now = new Date();
    const seconds = Math.floor((now - start) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  };

  const getSourceIcon = (source) => {
    switch (source) {
      case 'ui': return 'mdi:monitor';
      case 'cascade': return 'mdi:sitemap';
      case 'runner': return 'mdi:play-circle';
      case 'cli': return 'mdi:console';
      case 'adopted': return 'mdi:account-plus';
      case 'discovered': return 'mdi:magnify';
      default: return 'mdi:help-circle';
    }
  };

  const getSourceColor = (source) => {
    switch (source) {
      case 'ui': return '#4A9EDD';
      case 'cascade': return '#5EEAD4';
      case 'runner': return '#5EEAD4';
      case 'cli': return '#D9A553';
      case 'adopted': return '#a78bfa';
      case 'discovered': return '#f87171';
      default: return '#888';
    }
  };

  if (loading && sessions.length === 0) {
    return (
      <div className="sessions-view">
        <Header
          onBack={onBack}
          backLabel="Back"
          centerContent={
            <>
              <Icon icon="mdi:monitor-multiple" width="24" />
              <span className="header-stat">Active Browser Sessions</span>
            </>
          }
          onMessageFlow={onMessageFlow}
          onCockpit={onCockpit}
          onSextant={onSextant}
          onWorkshop={onWorkshop}
          onPlayground={onPlayground}
          onTools={onTools}
          onSearch={onSearch}
          onStudio={onStudio}
          onArtifacts={onArtifacts}
          onBrowser={onBrowser}
          onSessions={onSessions}
          onBlocked={onBlocked}
          blockedCount={blockedCount}
          sseConnected={sseConnected}
        />
        <div className="loading-state">
          <Icon icon="mdi:loading" width="32" className="spin" />
          <span>Loading sessions...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="sessions-view">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:monitor-multiple" width="24" />
            <span className="header-stat">Active Browser Sessions</span>
            <span className="header-divider">·</span>
            <span className="header-stat">{allSessions.length} <span className="stat-dim">sessions</span></span>
            {discoveredSessions.length > 0 && (
              <>
                <span className="header-divider">·</span>
                <span className="header-stat stat-dim" title="Unregistered sessions found">
                  +{discoveredSessions.length} discovered
                </span>
              </>
            )}
          </>
        }
        customButtons={
          <button
            className="refresh-button"
            onClick={() => { clearStreamErrors(); manualRescan(); }}
            disabled={scanningForSessions}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              background: 'linear-gradient(135deg, rgba(74, 158, 221, 0.1), rgba(94, 234, 212, 0.1))',
              border: '1px solid rgba(74, 158, 221, 0.25)',
              borderRadius: '8px',
              color: '#4A9EDD',
              fontSize: '0.85rem',
              fontWeight: '500',
              cursor: scanningForSessions ? 'wait' : 'pointer',
              opacity: scanningForSessions ? 0.7 : 1,
            }}
          >
            <Icon icon={scanningForSessions ? "mdi:loading" : "mdi:refresh"} width="18" className={scanningForSessions ? 'spin' : ''} />
            Refresh
          </button>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onPlayground={onPlayground}
        onTools={onTools}
        onSearch={onSearch}
        onStudio={onStudio}
        onArtifacts={onArtifacts}
        onBrowser={onBrowser}
        onSessions={onSessions}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {error && (
        <div className="error-banner">
          <Icon icon="mdi:alert-circle" width="20" />
          {error}
        </div>
      )}

      <div className="sessions-layout">
        {/* Sessions List */}
        <div className="sessions-list">
          {allSessions.length === 0 ? (
            <div className="empty-state">
              <Icon icon="mdi:monitor-off" width="48" />
              <h3>No Active Sessions</h3>
              <p>Start a browser session from FlowBuilder, run a cascade with browser config, or click "Discover Sessions" to find running instances.</p>
            </div>
          ) : (
            allSessions.map(session => (
              <div
                key={session.session_id}
                className={`session-card ${selectedSession?.session_id === session.session_id ? 'selected' : ''} ${!session.healthy ? 'unhealthy' : ''} ${session.is_discovered ? 'discovered' : ''}`}
                onClick={() => setSelectedSession(session)}
              >
                {/* Thumbnail - Live MJPEG stream or static screenshot */}
                <div className={`session-thumbnail ${canShowLiveStream(session) ? 'live' : ''}`}>
                  {canShowLiveStream(session) ? (
                    <>
                      <img
                        src={`http://localhost:${session.port}/stream/${session.browser_session_path}`}
                        alt="Live stream"
                        onError={() => handleStreamError(session.session_id)}
                      />
                      <div className="live-badge">
                        <span className="live-dot" />
                        LIVE
                      </div>
                    </>
                  ) : session.latest_screenshot ? (
                    <img
                      src={`${apiUrl}/api/browser-media/${session.latest_screenshot}`}
                      alt="Session preview"
                      loading="lazy"
                    />
                  ) : (
                    <div className="no-screenshot">
                      <Icon icon="mdi:image-off" width="32" />
                    </div>
                  )}
                  {session.is_processing && (
                    <div className="processing-indicator">
                      <Icon icon="mdi:loading" width="16" className="spin" />
                    </div>
                  )}
                </div>

                {/* Session Info */}
                <div className="session-info">
                  <div className="session-header-row">
                    <span className="session-id" title={session.session_id}>
                      {session.session_id.length > 24
                        ? session.session_id.substring(0, 24) + '...'
                        : session.session_id}
                    </span>
                    <span
                      className="session-source"
                      style={{ color: getSourceColor(session.source) }}
                      title={`Source: ${session.source}`}
                    >
                      <Icon icon={getSourceIcon(session.source)} width="14" />
                      {session.source}
                    </span>
                  </div>

                  {/* Cascade context if applicable */}
                  {session.cascade_id && (
                    <div className="cascade-context">
                      <Icon icon="mdi:sitemap" width="12" />
                      <span className="cascade-id">{session.cascade_id}</span>
                      {session.cell_name && (
                        <span className="cell-name"> / {session.cell_name}</span>
                      )}
                    </div>
                  )}

                  <div className="session-meta">
                    <span className="meta-item">
                      <Icon icon="mdi:ethernet" width="14" />
                      :{session.port}
                    </span>
                    <span className="meta-item">
                      <Icon icon="mdi:clock-outline" width="14" />
                      {formatDuration(session.started_at)}
                    </span>
                    {session.queue_length > 0 && (
                      <span className="meta-item queue">
                        <Icon icon="mdi:playlist-play" width="14" />
                        {session.queue_length} queued
                      </span>
                    )}
                  </div>

                  {session.current_url && (
                    <div className="session-url" title={session.current_url}>
                      <Icon icon="mdi:link" width="12" />
                      {new URL(session.current_url).hostname}
                    </div>
                  )}

                  <div className="session-status">
                    <span className={`health-indicator ${session.healthy ? 'healthy' : 'unhealthy'}`}>
                      <Icon icon={session.healthy ? 'mdi:check-circle' : 'mdi:alert-circle'} width="14" />
                      {session.healthy ? 'Healthy' : 'Unhealthy'}
                    </span>
                    {session.has_browser_session && (
                      <span className="browser-active">
                        <Icon icon="mdi:web" width="14" />
                        Browser Active
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="session-actions">
                  {/* Adopt button for discovered (unregistered) sessions */}
                  {session.is_discovered && (
                    <button
                      className="action-button adopt"
                      onClick={(e) => adoptSession(session, e)}
                      title="Add to registry for persistent tracking"
                    >
                      <Icon icon="mdi:plus-circle" width="18" />
                    </button>
                  )}
                  {onAttachSession && session.healthy && (
                    <button
                      className="action-button attach"
                      onClick={(e) => {
                        e.stopPropagation();
                        onAttachSession(session);
                      }}
                      title="Attach in FlowBuilder"
                    >
                      <Icon icon="mdi:connection" width="18" />
                    </button>
                  )}
                  {session.browser_session_path && onViewArtifacts && !session.is_discovered && (
                    <button
                      className="action-button view"
                      onClick={(e) => {
                        e.stopPropagation();
                        onViewArtifacts(session.browser_session_path);
                      }}
                      title="View Artifacts"
                    >
                      <Icon icon="mdi:folder-open" width="18" />
                    </button>
                  )}
                  <button
                    className="action-button kill"
                    onClick={(e) => killSession(session, e)}
                    title="Kill Session"
                  >
                    <Icon icon="mdi:close-circle" width="18" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Session Detail Panel */}
        {selectedSession && (
          <div className="session-detail-panel">
            <div className="detail-header">
              <h2>Session Details</h2>
              <button className="close-detail" onClick={() => setSelectedSession(null)}>
                <Icon icon="mdi:close" width="20" />
              </button>
            </div>

            {/* Live Stream Preview */}
            <div className="stream-preview">
              {selectedSession.healthy && selectedSession.browser_session_path ? (
                <img
                  src={`http://localhost:${selectedSession.port}/stream/${selectedSession.browser_session_path}`}
                  alt="Live stream"
                  className="mjpeg-stream"
                  onError={(e) => {
                    e.target.style.display = 'none';
                  }}
                />
              ) : selectedSession.latest_screenshot ? (
                <img
                  src={`${apiUrl}/api/browser-media/${selectedSession.latest_screenshot}`}
                  alt="Latest screenshot"
                  className="static-preview"
                />
              ) : (
                <div className="no-preview">
                  <Icon icon="mdi:video-off" width="48" />
                  <span>No preview available</span>
                </div>
              )}
            </div>

            {/* Detail Info */}
            <div className="detail-info">
              <div className="info-row">
                <label>Session ID</label>
                <span className="monospace">{selectedSession.session_id}</span>
              </div>
              <div className="info-row">
                <label>Source</label>
                <span style={{ color: getSourceColor(selectedSession.source) }}>
                  <Icon icon={getSourceIcon(selectedSession.source)} width="16" />
                  {selectedSession.source}
                </span>
              </div>
              <div className="info-row">
                <label>Port</label>
                <span className="monospace">{selectedSession.port}</span>
              </div>
              <div className="info-row">
                <label>PID</label>
                <span className="monospace">{selectedSession.pid || '-'}</span>
              </div>
              {selectedSession.started_at && (
                <>
                  <div className="info-row">
                    <label>Started</label>
                    <span>{new Date(selectedSession.started_at).toLocaleString()}</span>
                  </div>
                  <div className="info-row">
                    <label>Duration</label>
                    <span>{formatDuration(selectedSession.started_at)}</span>
                  </div>
                </>
              )}
              {selectedSession.cascade_id && (
                <>
                  <div className="info-row">
                    <label>Cascade</label>
                    <span>{selectedSession.cascade_id}</span>
                  </div>
                  <div className="info-row">
                    <label>Cell</label>
                    <span>{selectedSession.cell_name || '-'}</span>
                  </div>
                  <div className="info-row">
                    <label>RVBBIT Session</label>
                    <span className="monospace">{selectedSession.windlass_session_id || '-'}</span>
                  </div>
                </>
              )}
              {selectedSession.current_url && (
                <div className="info-row">
                  <label>Current URL</label>
                  <a href={selectedSession.current_url} target="_blank" rel="noopener noreferrer">
                    {selectedSession.current_url}
                  </a>
                </div>
              )}
            </div>

            {/* Detail Actions */}
            <div className="detail-actions">
              {/* Adopt button for discovered sessions */}
              {selectedSession.is_discovered && (
                <button
                  className="adopt-action"
                  onClick={() => adoptSession(selectedSession)}
                >
                  <Icon icon="mdi:plus-circle" width="18" />
                  Add to Registry
                </button>
              )}
              {onAttachSession && selectedSession.healthy && (
                <button
                  className="primary-action"
                  onClick={() => onAttachSession(selectedSession)}
                >
                  <Icon icon="mdi:connection" width="18" />
                  Attach in FlowBuilder
                </button>
              )}
              {selectedSession.browser_session_path && onViewArtifacts && !selectedSession.is_discovered && (
                <button
                  className="secondary-action"
                  onClick={() => onViewArtifacts(selectedSession.browser_session_path)}
                >
                  <Icon icon="mdi:folder-open" width="18" />
                  View Artifacts
                </button>
              )}
              <button
                className="danger-action"
                onClick={() => killSession(selectedSession)}
              >
                <Icon icon="mdi:close-circle" width="18" />
                Kill Session
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default SessionsView;
