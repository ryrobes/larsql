import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './LiveSessionsPanel.css';

/**
 * LiveSessionsPanel - Shows all active Rabbitize browser sessions
 *
 * Features:
 * - Auto-refreshes session list
 * - Shows latest screenshot for each session
 * - Kill individual sessions
 * - View session stream
 * - Shows processing status
 */
function LiveSessionsPanel({ onSelectSession, currentSessionId, compact = false }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const apiUrl = 'http://localhost:5050';

  const fetchSessions = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/sessions`);
      const data = await response.json();
      setSessions(data.sessions || []);
      setError(null);
    } catch (err) {
      setError('Failed to fetch sessions');
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  // Auto-refresh every 3 seconds
  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 3000);
    return () => clearInterval(interval);
  }, [fetchSessions]);

  const killSession = async (sessionId, e) => {
    e.stopPropagation();
    if (!window.confirm(`Kill session ${sessionId}?`)) return;

    try {
      await fetch(`${apiUrl}/api/rabbitize/sessions/${sessionId}`, {
        method: 'DELETE'
      });
      fetchSessions();
    } catch (err) {
      console.error('Failed to kill session:', err);
    }
  };

  const killAllSessions = async () => {
    if (!window.confirm('Kill ALL sessions?')) return;

    try {
      await fetch(`${apiUrl}/api/rabbitize/sessions`, {
        method: 'DELETE'
      });
      fetchSessions();
    } catch (err) {
      console.error('Failed to kill sessions:', err);
    }
  };

  const formatDuration = (seconds) => {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  };

  if (loading && sessions.length === 0) {
    return (
      <div className={`live-sessions-panel ${compact ? 'compact' : ''}`}>
        <div className="panel-header">
          <h3>
            <Icon icon="mdi:monitor-multiple" width="18" />
            Live Sessions
          </h3>
        </div>
        <div className="loading-state">
          <Icon icon="mdi:loading" width="24" className="spin" />
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className={`live-sessions-panel ${compact ? 'compact' : ''}`}>
      <div className="panel-header">
        <h3>
          <Icon icon="mdi:monitor-multiple" width="18" />
          Live Sessions ({sessions.length})
        </h3>
        <div className="header-actions">
          <button
            className="refresh-btn"
            onClick={fetchSessions}
            title="Refresh"
          >
            <Icon icon="mdi:refresh" width="16" />
          </button>
          {sessions.length > 0 && (
            <button
              className="kill-all-btn"
              onClick={killAllSessions}
              title="Kill all sessions"
            >
              <Icon icon="mdi:close-circle-multiple" width="16" />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="error-message">
          <Icon icon="mdi:alert" width="16" />
          {error}
        </div>
      )}

      <div className="sessions-list">
        {sessions.length === 0 ? (
          <div className="empty-state">
            <Icon icon="mdi:monitor-off" width="32" />
            <p>No active sessions</p>
            <span>Start a session from Flow Builder or a cascade</span>
          </div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.session_id}
              className={`session-card ${session.session_id === currentSessionId ? 'current' : ''} ${session.is_processing ? 'processing' : ''}`}
              onClick={() => onSelectSession && onSelectSession(session)}
            >
              <div className="session-thumbnail">
                {session.latest_screenshot ? (
                  <img
                    src={`${apiUrl}/api/browser-sessions/media/${session.latest_screenshot}`}
                    alt="Session screenshot"
                    onError={(e) => {
                      e.target.style.display = 'none';
                      e.target.nextSibling.style.display = 'flex';
                    }}
                  />
                ) : null}
                <div className="thumbnail-placeholder" style={{ display: session.latest_screenshot ? 'none' : 'flex' }}>
                  <Icon icon="mdi:monitor" width="24" />
                </div>
                {session.is_processing && (
                  <div className="processing-indicator">
                    <Icon icon="mdi:loading" width="16" className="spin" />
                  </div>
                )}
              </div>

              <div className="session-info">
                <div className="session-id" title={session.session_id}>
                  {session.session_id.length > 20
                    ? session.session_id.substring(0, 20) + '...'
                    : session.session_id}
                </div>
                <div className="session-details">
                  <span className="port">:{session.port}</span>
                  <span className="status">
                    <Icon
                      icon={session.has_browser_session ? 'mdi:circle' : 'mdi:circle-outline'}
                      width="8"
                      className={session.has_browser_session ? 'active' : 'idle'}
                    />
                    {session.cell || 'idle'}
                  </span>
                </div>
                {session.current_url && (
                  <div className="session-url" title={session.current_url}>
                    {new URL(session.current_url).hostname}
                  </div>
                )}
                <div className="session-meta">
                  <span className="duration">
                    <Icon icon="mdi:timer-outline" width="12" />
                    {formatDuration(session.seconds_running)}
                  </span>
                  {session.queue_length > 0 && (
                    <span className="queue">
                      <Icon icon="mdi:playlist-play" width="12" />
                      {session.queue_length}
                    </span>
                  )}
                </div>
              </div>

              <div className="session-actions">
                <button
                  className="action-btn view"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (session.browser_session_path) {
                      window.open(`#/browser/${session.browser_session_path}`, '_blank');
                    }
                  }}
                  title="View session"
                  disabled={!session.browser_session_path}
                >
                  <Icon icon="mdi:eye" width="14" />
                </button>
                <button
                  className="action-btn kill"
                  onClick={(e) => killSession(session.session_id, e)}
                  title="Kill session"
                >
                  <Icon icon="mdi:close" width="14" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default LiveSessionsPanel;
