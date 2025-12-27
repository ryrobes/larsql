import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './BrowserSessionDetail.css';

/**
 * BrowserSessionDetail - Detailed view of a single browser automation session
 *
 * Shows:
 * - Session metadata (client, test, session IDs, URL, duration, status)
 * - Screenshot gallery with timeline
 * - Video player
 * - Command history with timing visualization
 * - DOM snapshots viewer
 */
function BrowserSessionDetail({ sessionPath, onBack }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('screenshots'); // screenshots, video, commands, dom
  const [selectedScreenshot, setSelectedScreenshot] = useState(null);
  const [selectedDom, setSelectedDom] = useState(null);

  // Fetch session details
  const fetchSession = useCallback(async () => {
    if (!sessionPath) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`http://localhost:5001/api/browser-sessions/${sessionPath}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setSession(data);
        // Set default selected screenshot to first one
        if (data.screenshots?.length > 0) {
          setSelectedScreenshot(prev => prev || data.screenshots[0]);
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [sessionPath]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

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
    return new Date(isoString).toLocaleString();
  };

  // Get command type color
  const getCommandColor = (commandType) => {
    // commandType can be the full command string or just the type
    const type = commandType?.includes(' ') ? commandType.split(' ')[0] : commandType || '';
    const colors = {
      ':click': '#f0f',
      ':type': '#0f0',
      ':navigate': '#00f',
      ':scroll': '#f60',
      ':wait': '#666',
      ':screenshot': '#c0f',
      ':key': '#0f0',
      ':keypress': '#0f0',
      ':move-mouse': '#0ff',
      ':drag': '#ff0',
      ':hover': '#6ff',
      ':select': '#9cf',
      ':extract-page': '#9cf',
    };
    return colors[type] || '#888';
  };

  if (loading) {
    return (
      <div className="browser-session-detail">
        <div className="loading-state">
          <Icon icon="mdi:loading" width="48" className="spin" />
          <span>Loading session...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="browser-session-detail">
        <div className="error-state">
          <Icon icon="mdi:alert-circle" width="48" />
          <span>Error: {error}</span>
          <button onClick={fetchSession}>Retry</button>
        </div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="browser-session-detail">
        <div className="empty-state">
          <Icon icon="mdi:web-off" width="64" />
          <h3>Session Not Found</h3>
          <button onClick={onBack}>Back to Sessions</button>
        </div>
      </div>
    );
  }

  return (
    <div className="browser-session-detail">
      {/* Header */}
      <header className="session-detail-header">
        <div className="header-left">
          <button className="back-btn" onClick={onBack}>
            <Icon icon="mdi:arrow-left" width="20" />
            Back
          </button>
          <div className="header-title">
            <h1>{session.session_id}</h1>
            <div className="session-path-breadcrumb">
              <span className="path-part client">{session.client_id}</span>
              <Icon icon="mdi:chevron-right" width="16" />
              <span className="path-part test">{session.test_id}</span>
            </div>
          </div>
        </div>

        <div className="header-stats">
          {session.initial_url && (
            <a
              href={session.initial_url}
              target="_blank"
              rel="noopener noreferrer"
              className="url-link"
            >
              <Icon icon="mdi:link" width="16" />
              {new URL(session.initial_url).hostname}
            </a>
          )}
          <span className="stat">
            <Icon icon="mdi:cursor-default-click" width="18" />
            {session.command_count} commands
          </span>
          <span className="stat">
            <Icon icon="mdi:clock" width="18" />
            {formatDuration(session.duration_ms)}
          </span>
          <span className={`status ${session.status || 'unknown'}`}>
            {session.status === 'active' && <Icon icon="mdi:circle" width="12" className="pulse" />}
            {session.status || 'Unknown'}
          </span>
        </div>
      </header>

      {/* Content */}
      <div className="session-detail-content">
        {/* Sidebar - Session Info */}
        <aside className="session-sidebar">
          <div className="info-card">
            <h3>Session Info</h3>
            <div className="info-grid">
              <div className="info-item">
                <span className="label">Session ID</span>
                <span className="value">{session.session_id}</span>
              </div>
              <div className="info-item">
                <span className="label">Client</span>
                <span className="value">{session.client_id}</span>
              </div>
              <div className="info-item">
                <span className="label">Test</span>
                <span className="value">{session.test_id}</span>
              </div>
              <div className="info-item">
                <span className="label">Created</span>
                <span className="value">{formatTime(session.created_at)}</span>
              </div>
              <div className="info-item">
                <span className="label">Modified</span>
                <span className="value">{formatTime(session.modified_at)}</span>
              </div>
              <div className="info-item">
                <span className="label">Duration</span>
                <span className="value">{formatDuration(session.duration_ms)}</span>
              </div>
            </div>
          </div>

          <div className="info-card">
            <h3>Artifacts</h3>
            <div className="artifact-counts">
              <div className="artifact-item">
                <Icon icon="mdi:camera" width="20" />
                <span>{session.screenshots?.length || 0} Screenshots</span>
              </div>
              <div className="artifact-item">
                <Icon icon="mdi:code-tags" width="20" />
                <span>{session.dom_snapshots?.length || 0} DOM Snapshots</span>
              </div>
              <div className="artifact-item">
                <Icon icon="mdi:video" width="20" />
                <span>{session.video ? 'Video Available' : 'No Video'}</span>
              </div>
              <div className="artifact-item">
                <Icon icon="mdi:file-document" width="20" />
                <span>{session.metadata ? 'Metadata' : 'No Metadata'}</span>
              </div>
            </div>
          </div>

          {session.initial_url && (
            <div className="info-card">
              <h3>Initial URL</h3>
              <a
                href={session.initial_url}
                target="_blank"
                rel="noopener noreferrer"
                className="full-url"
              >
                {session.initial_url}
              </a>
            </div>
          )}
        </aside>

        {/* Main Content Area */}
        <main className="session-main">
          {/* Tabs */}
          <div className="tabs">
            <button
              className={activeTab === 'screenshots' ? 'active' : ''}
              onClick={() => setActiveTab('screenshots')}
            >
              <Icon icon="mdi:camera" width="18" />
              Screenshots ({session.screenshots?.length || 0})
            </button>
            <button
              className={activeTab === 'video' ? 'active' : ''}
              onClick={() => setActiveTab('video')}
              disabled={!session.video}
            >
              <Icon icon="mdi:video" width="18" />
              Video
            </button>
            <button
              className={activeTab === 'commands' ? 'active' : ''}
              onClick={() => setActiveTab('commands')}
            >
              <Icon icon="mdi:console" width="18" />
              Commands ({session.command_count || 0})
            </button>
            <button
              className={activeTab === 'dom' ? 'active' : ''}
              onClick={() => setActiveTab('dom')}
              disabled={!session.dom_snapshots?.length}
            >
              <Icon icon="mdi:code-tags" width="18" />
              DOM ({session.dom_snapshots?.length || 0})
            </button>
          </div>

          {/* Tab Content */}
          <div className="tab-content">
            {/* Screenshots Tab */}
            {activeTab === 'screenshots' && (
              <div className="screenshots-panel">
                {session.screenshots?.length > 0 ? (
                  <>
                    {/* Main preview */}
                    <div className="screenshot-preview">
                      {selectedScreenshot ? (
                        <img
                          src={`http://localhost:5001/api/browser-media/${session.path}/screenshots/${selectedScreenshot.filename || selectedScreenshot}`}
                          alt={selectedScreenshot.filename || selectedScreenshot}
                        />
                      ) : (
                        <div className="no-selection">
                          <Icon icon="mdi:image" width="64" />
                          <p>Select a screenshot</p>
                        </div>
                      )}
                    </div>

                    {/* Thumbnail strip */}
                    <div className="screenshot-strip">
                      {session.screenshots.map((screenshot, index) => {
                        const filename = screenshot.filename || screenshot;
                        // Use zoom/thumbnail variant for the thumbnail strip if available
                        const thumbFilename = screenshot.thumbnail || filename;
                        const isSelected = selectedScreenshot?.filename === filename || selectedScreenshot === filename;
                        return (
                          <button
                            type="button"
                            key={filename}
                            className={`thumbnail ${isSelected ? 'active' : ''}`}
                            onClick={(e) => {
                              e.preventDefault();
                              setSelectedScreenshot(screenshot);
                            }}
                          >
                            <img
                              src={`http://localhost:5001/api/browser-media/${session.path}/screenshots/${thumbFilename}`}
                              alt={`Screenshot ${index + 1}`}
                              loading="lazy"
                            />
                            <span className="index">{index + 1}</span>
                          </button>
                        );
                      })}
                    </div>
                  </>
                ) : (
                  <div className="empty-tab">
                    <Icon icon="mdi:camera-off" width="64" />
                    <p>No screenshots available</p>
                  </div>
                )}
              </div>
            )}

            {/* Video Tab */}
            {activeTab === 'video' && (
              <div className="video-panel">
                {session.video ? (
                  <video
                    controls
                    src={`http://localhost:5001/api/browser-media/${session.path}/video/${session.video}`}
                    className="video-player"
                  />
                ) : session.has_video ? (
                  <video
                    controls
                    src={`http://localhost:5001/api/browser-media/${session.path}/video/session.webm`}
                    className="video-player"
                  />
                ) : (
                  <div className="empty-tab">
                    <Icon icon="mdi:video-off" width="64" />
                    <p>No video available</p>
                  </div>
                )}
              </div>
            )}

            {/* Commands Tab */}
            {activeTab === 'commands' && (() => {
              // Commands can be in session.commands or session.metadata.commands
              const commands = session.commands || session.metadata?.commands || [];

              // Helper to get command string from cmd.command (can be array or string)
              const getCommandStr = (cmd) => {
                if (!cmd?.command) return '';
                if (Array.isArray(cmd.command)) return cmd.command.join(' ');
                return cmd.command;
              };

              // Helper to get command type (first part)
              const getCommandType = (cmd) => {
                if (!cmd?.command) return '';
                if (Array.isArray(cmd.command)) return cmd.command[0] || '';
                return cmd.command.split(' ')[0] || '';
              };

              // Helper to get command args (rest)
              const getCommandArgs = (cmd) => {
                if (!cmd?.command) return '';
                if (Array.isArray(cmd.command)) return cmd.command.slice(1).join(' ');
                return cmd.command.split(' ').slice(1).join(' ');
              };

              return (
                <div className="commands-panel">
                  {commands.length > 0 ? (
                    <>
                      {/* Timing chart */}
                      <div className="timing-chart">
                        {commands.map((cmd, index) => {
                          const duration = cmd.duration || 100;
                          const maxDuration = Math.max(...commands.map(c => c.duration || 100));
                          const width = Math.max(5, (duration / maxDuration) * 100);
                          return (
                            <div
                              key={index}
                              className="timing-bar"
                              style={{
                                width: `${width}%`,
                                backgroundColor: getCommandColor(getCommandType(cmd))
                              }}
                              title={`${getCommandStr(cmd)} (${duration}ms)`}
                            >
                              <span className="timing-label">{getCommandType(cmd)}</span>
                            </div>
                          );
                        })}
                      </div>

                      {/* Command list */}
                      <div className="command-list">
                        {commands.map((cmd, index) => (
                          <div key={index} className="command-item">
                            <span className="command-index">{index + 1}</span>
                            <span
                              className="command-type"
                              style={{ color: getCommandColor(getCommandType(cmd)) }}
                            >
                              {getCommandType(cmd)}
                            </span>
                            <span className="command-args">
                              {getCommandArgs(cmd)}
                            </span>
                            <span className="command-duration">
                              {cmd.duration ? `${cmd.duration}ms` : '-'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="empty-tab">
                      <Icon icon="mdi:console" width="64" />
                      <p>No command data available</p>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* DOM Tab */}
            {activeTab === 'dom' && (
              <div className="dom-panel">
                {session.dom_snapshots?.length > 0 ? (
                  <>
                    {/* DOM snapshot selector */}
                    <div className="dom-selector">
                      <select
                        value={selectedDom || ''}
                        onChange={(e) => setSelectedDom(e.target.value)}
                      >
                        <option value="">Select a DOM snapshot</option>
                        {session.dom_snapshots.map((dom, index) => {
                          const filename = dom.filename || dom;
                          return (
                            <option key={filename} value={filename}>
                              Snapshot {index + 1}: {filename}
                            </option>
                          );
                        })}
                      </select>
                    </div>

                    {/* DOM preview */}
                    <div className="dom-preview">
                      {selectedDom ? (
                        <DomSnapshotViewer
                          url={`http://localhost:5001/api/browser-media/${session.path}/dom_snapshots/${selectedDom}`}
                        />
                      ) : (
                        <div className="no-selection">
                          <Icon icon="mdi:code-tags" width="64" />
                          <p>Select a DOM snapshot</p>
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="empty-tab">
                    <Icon icon="mdi:code-tags" width="64" />
                    <p>No DOM snapshots available</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

/**
 * DomSnapshotViewer - Loads and displays DOM snapshot HTML
 */
function DomSnapshotViewer({ url }) {
  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchDom = async () => {
      setLoading(true);
      try {
        const response = await fetch(url);
        const text = await response.text();
        setContent(text);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchDom();
  }, [url]);

  if (loading) {
    return <div className="dom-loading">Loading DOM snapshot...</div>;
  }

  if (error) {
    return <div className="dom-error">Error loading snapshot: {error}</div>;
  }

  return (
    <pre className="dom-content">
      {content}
    </pre>
  );
}

export default BrowserSessionDetail;
