import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
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
function SessionsView({ onBack, onAttachSession, onViewArtifacts }) {
  const [sessions, setSessions] = useState([]);
  const [orphans, setOrphans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [showOrphans, setShowOrphans] = useState(false);
  const [scanningOrphans, setScanningOrphans] = useState(false);

  const apiUrl = 'http://localhost:5001';

  const fetchSessions = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/registry/sessions`);
      const data = await response.json();
      if (data.error) {
        setError(data.error);
      } else {
        setSessions(data.sessions || []);
        setError(null);
      }
    } catch (err) {
      setError('Failed to fetch sessions');
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  const scanOrphans = async () => {
    setScanningOrphans(true);
    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/registry/orphans`);
      const data = await response.json();
      setOrphans(data.orphans || []);
      setShowOrphans(true);
    } catch (err) {
      console.error('Failed to scan orphans:', err);
    } finally {
      setScanningOrphans(false);
    }
  };

  const adoptOrphan = async (port) => {
    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/registry/orphans/${port}`, {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        // Refresh sessions and orphans
        fetchSessions();
        scanOrphans();
      }
    } catch (err) {
      console.error('Failed to adopt orphan:', err);
    }
  };

  const killSession = async (sessionId, e) => {
    if (e) e.stopPropagation();
    if (!window.confirm(`Kill session ${sessionId}?`)) return;

    try {
      await fetch(`${apiUrl}/api/rabbitize/registry/sessions/${sessionId}`, {
        method: 'DELETE'
      });
      fetchSessions();
      if (selectedSession?.session_id === sessionId) {
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
        <div className="sessions-header">
          <button className="back-button" onClick={onBack}>
            <Icon icon="mdi:arrow-left" width="20" />
            Back
          </button>
          <h1>
            <Icon icon="mdi:monitor-multiple" width="28" />
            Active Browser Sessions
          </h1>
        </div>
        <div className="loading-state">
          <Icon icon="mdi:loading" width="32" className="spin" />
          <span>Loading sessions...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="sessions-view">
      <div className="sessions-header">
        <button className="back-button" onClick={onBack}>
          <Icon icon="mdi:arrow-left" width="20" />
          Back
        </button>
        <h1>
          <Icon icon="mdi:monitor-multiple" width="28" />
          Active Browser Sessions
          <span className="session-count">{sessions.length}</span>
        </h1>
        <div className="header-actions">
          <button
            className="scan-orphans-button"
            onClick={scanOrphans}
            disabled={scanningOrphans}
          >
            <Icon icon={scanningOrphans ? "mdi:loading" : "mdi:radar"} width="18" className={scanningOrphans ? 'spin' : ''} />
            Scan for Orphans
          </button>
          <button
            className="refresh-button"
            onClick={fetchSessions}
          >
            <Icon icon="mdi:refresh" width="18" />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <Icon icon="mdi:alert-circle" width="20" />
          {error}
        </div>
      )}

      {/* Orphans Section */}
      {showOrphans && orphans.length > 0 && (
        <div className="orphans-section">
          <div className="orphans-header">
            <h2>
              <Icon icon="mdi:ghost" width="20" />
              Orphan Sessions ({orphans.length})
            </h2>
            <button className="close-orphans" onClick={() => setShowOrphans(false)}>
              <Icon icon="mdi:close" width="18" />
            </button>
          </div>
          <p className="orphans-description">
            These Rabbitize instances are running but not tracked in the registry.
            They may be from cascades or previous runs.
          </p>
          <div className="orphans-list">
            {orphans.map(orphan => (
              <div key={orphan.port} className="orphan-card">
                <div className="orphan-info">
                  <span className="orphan-port">Port {orphan.port}</span>
                  <span className="orphan-pid">PID: {orphan.pid || 'Unknown'}</span>
                </div>
                <button
                  className="adopt-button"
                  onClick={() => adoptOrphan(orphan.port)}
                >
                  <Icon icon="mdi:account-plus" width="16" />
                  Adopt
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {showOrphans && orphans.length === 0 && (
        <div className="orphans-section empty">
          <Icon icon="mdi:check-circle" width="24" />
          <span>No orphan sessions found</span>
          <button className="close-orphans" onClick={() => setShowOrphans(false)}>
            <Icon icon="mdi:close" width="18" />
          </button>
        </div>
      )}

      <div className="sessions-layout">
        {/* Sessions List */}
        <div className="sessions-list">
          {sessions.length === 0 ? (
            <div className="empty-state">
              <Icon icon="mdi:monitor-off" width="48" />
              <h3>No Active Sessions</h3>
              <p>Start a browser session from FlowBuilder or run a cascade with browser config.</p>
            </div>
          ) : (
            sessions.map(session => (
              <div
                key={session.session_id}
                className={`session-card ${selectedSession?.session_id === session.session_id ? 'selected' : ''} ${!session.healthy ? 'unhealthy' : ''}`}
                onClick={() => setSelectedSession(session)}
              >
                {/* Thumbnail */}
                <div className="session-thumbnail">
                  {session.latest_screenshot ? (
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
                      {session.phase_name && (
                        <span className="phase-name"> / {session.phase_name}</span>
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
                  {session.browser_session_path && onViewArtifacts && (
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
                    onClick={(e) => killSession(session.session_id, e)}
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
                  src={`${apiUrl}/api/rabbitize/stream/${selectedSession.session_id}/stream/${selectedSession.browser_session_path}`}
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
              <div className="info-row">
                <label>Started</label>
                <span>{new Date(selectedSession.started_at).toLocaleString()}</span>
              </div>
              <div className="info-row">
                <label>Duration</label>
                <span>{formatDuration(selectedSession.started_at)}</span>
              </div>
              {selectedSession.cascade_id && (
                <>
                  <div className="info-row">
                    <label>Cascade</label>
                    <span>{selectedSession.cascade_id}</span>
                  </div>
                  <div className="info-row">
                    <label>Phase</label>
                    <span>{selectedSession.phase_name || '-'}</span>
                  </div>
                  <div className="info-row">
                    <label>Windlass Session</label>
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
              {onAttachSession && selectedSession.healthy && (
                <button
                  className="primary-action"
                  onClick={() => onAttachSession(selectedSession)}
                >
                  <Icon icon="mdi:connection" width="18" />
                  Attach in FlowBuilder
                </button>
              )}
              {selectedSession.browser_session_path && onViewArtifacts && (
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
                onClick={() => killSession(selectedSession.session_id)}
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
