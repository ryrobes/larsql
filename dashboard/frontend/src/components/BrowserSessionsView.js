import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './BrowserSessionsView.css';

/**
 * BrowserSessionsView - Gallery of browser automation sessions
 *
 * Shows all Rabbitize browser sessions from rabbitize-runs/.
 * Each session card shows thumbnail, command count, duration, video status.
 */
function BrowserSessionsView({ onBack, onSelectSession, onOpenFlowBuilder, onOpenFlowRegistry, onOpenLiveSessions }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // grid or list
  const [sortBy, setSortBy] = useState('modified_at'); // modified_at, created_at, command_count, duration_ms

  // Fetch sessions
  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:5001/api/browser-sessions');
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setSessions(data.sessions || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  // Filter sessions by search query
  const filteredSessions = sessions.filter(session => {
    if (!searchQuery) return true;

    const query = searchQuery.toLowerCase();
    return (
      session.session_id?.toLowerCase().includes(query) ||
      session.initial_url?.toLowerCase().includes(query) ||
      session.client_id?.toLowerCase().includes(query) ||
      session.test_id?.toLowerCase().includes(query)
    );
  });

  // Sort sessions
  const sortedSessions = [...filteredSessions].sort((a, b) => {
    switch (sortBy) {
      case 'command_count':
        return b.command_count - a.command_count;
      case 'duration_ms':
        return b.duration_ms - a.duration_ms;
      case 'created_at':
        return new Date(b.created_at) - new Date(a.created_at);
      case 'modified_at':
      default:
        return new Date(b.modified_at) - new Date(a.modified_at);
    }
  });

  // Stats
  const totalCommands = sessions.reduce((sum, s) => sum + s.command_count, 0);
  const totalVideos = sessions.filter(s => s.has_video).length;
  const totalScreenshots = sessions.reduce((sum, s) => sum + s.screenshot_count, 0);

  // Format duration
  const formatDuration = (ms) => {
    if (!ms) return '-';
    const seconds = Math.floor(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  // Format timestamp
  const formatTime = (isoString) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffHours = diffMs / (1000 * 60 * 60);

    if (diffHours < 24) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (diffHours < 48) {
      return 'Yesterday';
    } else {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
  };

  // Handle session click
  const handleSessionClick = (session) => {
    if (onSelectSession) {
      onSelectSession(session.path);
    }
  };

  // Handle delete
  const handleDelete = async (e, session) => {
    e.stopPropagation();
    if (!window.confirm(`Delete session "${session.session_id}"?\n\nThis will remove all screenshots, video, and metadata.`)) {
      return;
    }

    try {
      const response = await fetch(`http://localhost:5001/api/browser-sessions/${session.path}`, {
        method: 'DELETE'
      });
      const data = await response.json();

      if (data.error) {
        alert(`Error: ${data.error}`);
      } else {
        fetchSessions();
      }
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  };

  return (
    <div className="browser-sessions-container">
      {/* Header */}
      <header className="browser-sessions-header">
        <div className="header-left">
          <img
            src="/windlass-transparent-square.png"
            alt="Windlass"
            className="brand-logo"
            onClick={() => window.location.hash = ''}
          />
          <div className="header-title">
            <h1>
              <Icon icon="mdi:web" width="28" />
              Browser Sessions
            </h1>
            <span className="subtitle">Visual Browser Automation</span>
          </div>
        </div>

        <div className="header-stats">
          <span className="stat-item">
            <Icon icon="mdi:folder-multiple" width="18" />
            {sessions.length} sessions
          </span>
          <span className="stat-item">
            <Icon icon="mdi:cursor-default-click" width="18" />
            {totalCommands} commands
          </span>
          <span className="stat-item">
            <Icon icon="mdi:video" width="18" />
            {totalVideos} videos
          </span>
          <span className="stat-item">
            <Icon icon="mdi:camera" width="18" />
            {totalScreenshots} screenshots
          </span>
        </div>

        <div className="header-right">
          {onOpenLiveSessions && (
            <button className="live-sessions-btn" onClick={onOpenLiveSessions}>
              <Icon icon="mdi:monitor-multiple" width="20" />
              Live Sessions
            </button>
          )}
          {onOpenFlowRegistry && (
            <button className="flow-registry-btn" onClick={onOpenFlowRegistry}>
              <Icon icon="mdi:sitemap" width="20" />
              Flow Registry
            </button>
          )}
          {onOpenFlowBuilder && (
            <button className="flow-builder-btn" onClick={onOpenFlowBuilder}>
              <Icon icon="mdi:plus" width="20" />
              Flow Builder
            </button>
          )}
          {onBack && (
            <button className="back-btn" onClick={onBack}>
              <Icon icon="mdi:arrow-left" width="20" />
              Back
            </button>
          )}
        </div>
      </header>

      {/* Toolbar */}
      <div className="browser-sessions-toolbar">
        <div className="search-bar">
          <Icon icon="mdi:magnify" width="20" />
          <input
            type="text"
            placeholder="Search sessions by ID, URL, client, test..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="toolbar-controls">
          <div className="sort-control">
            <label>Sort by:</label>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="modified_at">Recent</option>
              <option value="created_at">Created</option>
              <option value="command_count">Commands</option>
              <option value="duration_ms">Duration</option>
            </select>
          </div>

          <div className="view-toggle">
            <button
              className={viewMode === 'grid' ? 'active' : ''}
              onClick={() => setViewMode('grid')}
              title="Grid view"
            >
              <Icon icon="mdi:view-grid" width="20" />
            </button>
            <button
              className={viewMode === 'list' ? 'active' : ''}
              onClick={() => setViewMode('list')}
              title="List view"
            >
              <Icon icon="mdi:view-list" width="20" />
            </button>
          </div>

          <button className="refresh-btn" onClick={fetchSessions} title="Refresh">
            <Icon icon="mdi:refresh" width="20" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="browser-sessions-content">
        {loading && (
          <div className="loading-state">
            <Icon icon="mdi:loading" width="48" className="spin" />
            <span>Loading sessions...</span>
          </div>
        )}

        {error && (
          <div className="error-state">
            <Icon icon="mdi:alert-circle" width="48" />
            <span>Error: {error}</span>
            <button onClick={fetchSessions}>Retry</button>
          </div>
        )}

        {!loading && !error && sortedSessions.length === 0 && (
          <div className="empty-state">
            <Icon icon="mdi:web-off" width="64" />
            <h3>No Browser Sessions</h3>
            <p>
              {searchQuery
                ? 'No sessions match your search query.'
                : 'Run a cascade with browser automation to see sessions here.'}
            </p>
            {onOpenFlowBuilder && (
              <button className="flow-builder-btn" onClick={onOpenFlowBuilder}>
                <Icon icon="mdi:plus" width="20" />
                Open Flow Builder
              </button>
            )}
          </div>
        )}

        {!loading && !error && sortedSessions.length > 0 && (
          <div className={`sessions-${viewMode}`}>
            {sortedSessions.map(session => (
              <div
                key={session.path}
                className="session-card"
                onClick={() => handleSessionClick(session)}
              >
                {/* Thumbnail */}
                <div className="session-thumbnail">
                  {session.thumbnail ? (
                    <img
                      src={`http://localhost:5001/api/browser-media/${session.thumbnail}`}
                      alt={session.session_id}
                      loading="lazy"
                    />
                  ) : (
                    <div className="no-thumbnail">
                      <Icon icon="mdi:web" width="48" />
                    </div>
                  )}

                  {/* Video badge */}
                  {session.has_video && (
                    <div className="video-badge">
                      <Icon icon="mdi:video" width="16" />
                    </div>
                  )}

                  {/* Duration overlay */}
                  {session.duration_ms > 0 && (
                    <div className="duration-badge">
                      {formatDuration(session.duration_ms)}
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="session-info">
                  <h3 className="session-id">{session.session_id}</h3>

                  {session.initial_url && (
                    <div className="session-url" title={session.initial_url}>
                      <Icon icon="mdi:link" width="14" />
                      {new URL(session.initial_url).hostname}
                    </div>
                  )}

                  <div className="session-meta">
                    <span className="meta-item" title="Commands">
                      <Icon icon="mdi:cursor-default-click" width="14" />
                      {session.command_count}
                    </span>
                    <span className="meta-item" title="Screenshots">
                      <Icon icon="mdi:camera" width="14" />
                      {session.screenshot_count}
                    </span>
                    <span className="meta-item" title="DOM Snapshots">
                      <Icon icon="mdi:code-tags" width="14" />
                      {session.dom_snapshot_count}
                    </span>
                    <span className="meta-item time" title={session.modified_at}>
                      <Icon icon="mdi:clock-outline" width="14" />
                      {formatTime(session.modified_at)}
                    </span>
                  </div>

                  {/* Client/Test IDs */}
                  <div className="session-path">
                    <span className="path-part client">{session.client_id}</span>
                    <span className="path-sep">/</span>
                    <span className="path-part test">{session.test_id}</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="session-actions">
                  <button
                    className="action-btn delete"
                    onClick={(e) => handleDelete(e, session)}
                    title="Delete session"
                  >
                    <Icon icon="mdi:delete" width="18" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default BrowserSessionsView;
