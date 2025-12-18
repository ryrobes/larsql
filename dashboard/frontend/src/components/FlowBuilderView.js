import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import LiveSessionsPanel from './LiveSessionsPanel';
import './FlowBuilderView.css';

/**
 * FlowBuilderView - Interactive browser automation flow builder
 *
 * Features:
 * - Live MJPEG stream of browser
 * - Click overlay for coordinate capture
 * - Command palette for various actions
 * - Command history with editing
 * - Save/export flows as JSON
 */
function FlowBuilderView({ onBack, onSaveFlow }) {
  // Browser state
  const [sessionActive, setSessionActive] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [url, setUrl] = useState('');
  const [currentUrl, setCurrentUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Coordinates
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [clickPos, setClickPos] = useState(null);

  // Commands
  const [commands, setCommands] = useState([]);
  const [executing, setExecuting] = useState(false);

  // UI state
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [flowName, setFlowName] = useState('');
  const [flowDescription, setFlowDescription] = useState('');

  // Refs
  const viewportRef = useRef(null);
  const streamRef = useRef(null);

  // Dashboard backend URL (proxies to Rabbitize)
  const apiUrl = 'http://localhost:5001';

  // Session details for streaming
  const [sessionDetails, setSessionDetails] = useState(null);
  const [serverStatus, setServerStatus] = useState('unknown'); // unknown, starting, running, error
  const [dashboardSessionId, setDashboardSessionId] = useState(null); // Tracks our Rabbitize instance
  const [isAttachedSession, setIsAttachedSession] = useState(false); // True if attached from SessionsView

  // Start a new browser session
  const startSession = useCallback(async (navigateUrl) => {
    if (!navigateUrl) return;

    setLoading(true);
    setError(null);
    setServerStatus('starting');

    // Generate a unique session ID for this Flow Builder instance
    const newDashboardSessionId = `flowbuilder_${Date.now()}`;

    try {
      // Start session via dashboard proxy (auto-starts Rabbitize if needed)
      const response = await fetch(`${apiUrl}/api/rabbitize/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: navigateUrl,
          clientId: 'flow-builder',
          testId: 'interactive',
          dashboard_session_id: newDashboardSessionId
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to start session');
      }

      setServerStatus('running');
      setSessionActive(true);
      setSessionId(data.sessionId);
      setDashboardSessionId(data.dashboard_session_id || newDashboardSessionId);
      setSessionDetails({
        clientId: data.clientId,
        testId: data.testId,
        sessionId: data.sessionId,
        dashboardSessionId: data.dashboard_session_id || newDashboardSessionId,
        streamPath: `${data.clientId}/${data.testId}/${data.sessionId}`
      });
      setCurrentUrl(navigateUrl);
    } catch (err) {
      setServerStatus('error');
      if (err.message.includes('Failed to fetch')) {
        setError('Cannot connect to dashboard backend. Is it running on port 5001?');
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  // End or detach from the current session
  const endSession = useCallback(async () => {
    if (!sessionActive) return;

    // For attached sessions, just detach (don't kill the remote session)
    if (!isAttachedSession) {
      try {
        await fetch(`${apiUrl}/api/rabbitize/session/end`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dashboard_session_id: dashboardSessionId })
        });
      } catch (err) {
        console.error('Error ending session:', err);
      }
    }

    // Clear local state
    setSessionActive(false);
    setSessionId(null);
    setSessionDetails(null);
    setDashboardSessionId(null);
    setCurrentUrl('');
    setServerStatus('unknown');
    setIsAttachedSession(false);
  }, [sessionActive, apiUrl, dashboardSessionId, isAttachedSession]);

  // Build Rabbitize command array from command type and args
  const buildCommandArray = (commandType, args) => {
    // Rabbitize commands are arrays like [":click", ":at", x, y]
    switch (commandType) {
      case ':click':
        return [':click', ':at', args.x, args.y];
      case ':move-click':
        return [':move-click', ':to', args.x, args.y];
      case ':right-click':
        return [':right-click', ':at', args.x, args.y];
      case ':move-mouse':
        return [':move-mouse', ':to', args.x, args.y];
      case ':type':
        return [':type', ':text', args.text];
      case ':key':
        return [':key', args.key];
      case ':scroll':
        return [':scroll', args.direction === 'up' ? ':up' : ':down', args.amount];
      case ':wait':
        return [':wait', args.ms];
      case ':screenshot':
        return [':screenshot'];
      case ':navigate':
        return [':navigate', ':to', args.url];
      case ':back':
        return [':navigate', ':back'];
      case ':forward':
        return [':navigate', ':forward'];
      case ':reload':
        return [':reload'];
      default:
        return [commandType, ...Object.values(args)];
    }
  };

  // Execute a command
  const executeCommand = useCallback(async (commandType, args = {}) => {
    if (!sessionActive) return;

    setExecuting(true);

    try {
      // Build the command array for Rabbitize
      const commandArray = buildCommandArray(commandType, args);

      let response;

      // For attached sessions with direct port access, call Rabbitize directly
      if (sessionDetails?.port) {
        response = await fetch(`http://localhost:${sessionDetails.port}/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: commandArray })
        });
      } else {
        // Use dashboard proxy for UI-created sessions
        response = await fetch(`${apiUrl}/api/rabbitize/session/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            command: commandArray,
            dashboard_session_id: dashboardSessionId
          })
        });
      }

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Add to command history
      setCommands(prev => [...prev, {
        command: commandType,
        args,
        commandArray,
        timestamp: new Date().toISOString(),
        success: true
      }]);

      return data;
    } catch (err) {
      setError(err.message);
      setCommands(prev => [...prev, {
        command: commandType,
        args,
        timestamp: new Date().toISOString(),
        success: false,
        error: err.message
      }]);
    } finally {
      setExecuting(false);
    }
  }, [sessionActive, apiUrl, dashboardSessionId, sessionDetails]);

  // Handle URL submit
  const handleUrlSubmit = (e) => {
    e.preventDefault();
    if (url && !loading) {
      startSession(url);
    }
  };

  // Handle viewport click for coordinate capture
  // Accounts for image scaling if displayed size differs from natural size
  const handleViewportClick = (e) => {
    if (!sessionActive || !viewportRef.current || !streamRef.current) return;

    const img = streamRef.current;
    const rect = img.getBoundingClientRect();

    // Calculate position relative to displayed image
    const displayX = e.clientX - rect.left;
    const displayY = e.clientY - rect.top;

    // Scale to actual browser coordinates if image is scaled
    const scaleX = img.naturalWidth ? img.naturalWidth / rect.width : 1;
    const scaleY = img.naturalHeight ? img.naturalHeight / rect.height : 1;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    // Store both display position (for marker) and actual coords (for commands)
    setClickPos({ x, y, displayX: Math.round(displayX), displayY: Math.round(displayY) });
  };

  // Handle viewport mouse move for coordinate display
  const handleViewportMouseMove = (e) => {
    if (!viewportRef.current || !streamRef.current) return;

    const img = streamRef.current;
    const rect = img.getBoundingClientRect();

    const displayX = e.clientX - rect.left;
    const displayY = e.clientY - rect.top;

    // Scale to actual browser coordinates
    const scaleX = img.naturalWidth ? img.naturalWidth / rect.width : 1;
    const scaleY = img.naturalHeight ? img.naturalHeight / rect.height : 1;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    setMousePos({ x: Math.max(0, x), y: Math.max(0, y) });
  };

  // Command action handlers
  const handleClick = () => {
    if (clickPos) {
      executeCommand(':click', { x: clickPos.x, y: clickPos.y });
    }
  };

  const handleMoveClick = () => {
    if (clickPos) {
      executeCommand(':move-click', { x: clickPos.x, y: clickPos.y });
    }
  };

  const handleRightClick = () => {
    if (clickPos) {
      executeCommand(':right-click', { x: clickPos.x, y: clickPos.y });
    }
  };

  const handleMoveMouse = () => {
    if (clickPos) {
      executeCommand(':move-mouse', { x: clickPos.x, y: clickPos.y });
    }
  };

  const handleType = () => {
    const text = prompt('Enter text to type:');
    if (text) {
      executeCommand(':type', { text });
    }
  };

  const handleKey = () => {
    const key = prompt('Enter key (e.g., Enter, Tab, Escape):');
    if (key) {
      executeCommand(':key', { key });
    }
  };

  const handleScrollUp = () => {
    executeCommand(':scroll', { direction: 'up', amount: 300 });
  };

  const handleScrollDown = () => {
    executeCommand(':scroll', { direction: 'down', amount: 300 });
  };

  const handleWait = () => {
    const ms = prompt('Wait duration in milliseconds:', '1000');
    if (ms) {
      executeCommand(':wait', { ms: parseInt(ms, 10) });
    }
  };

  const handleScreenshot = () => {
    executeCommand(':screenshot', {});
  };

  const handleNavigate = () => {
    const newUrl = prompt('Enter URL to navigate to:', currentUrl);
    if (newUrl) {
      executeCommand(':navigate', { url: newUrl });
      setCurrentUrl(newUrl);
    }
  };

  const handleBack = () => {
    executeCommand(':back', {});
  };

  const handleForward = () => {
    executeCommand(':forward', {});
  };

  const handleRefresh = () => {
    executeCommand(':reload', {});
  };

  // Clear commands
  const clearCommands = () => {
    setCommands([]);
  };

  // Remove a command
  const removeCommand = (index) => {
    setCommands(prev => prev.filter((_, i) => i !== index));
  };

  // Save flow
  const saveFlow = async () => {
    if (!flowName) {
      alert('Please enter a flow name');
      return;
    }

    try {
      const flow = {
        name: flowName,
        description: flowDescription,
        initial_url: currentUrl,
        // Export both formats: commandArray for Rabbitize, command/args for UI display
        commands: commands.map(cmd => ({
          command: cmd.commandArray || buildCommandArray(cmd.command, cmd.args),
          displayCommand: cmd.command,
          args: cmd.args
        })),
        created_at: new Date().toISOString()
      };

      const response = await fetch('http://localhost:5001/api/browser-flows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(flow)
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setShowSaveModal(false);
      setFlowName('');
      setFlowDescription('');

      if (onSaveFlow) {
        onSaveFlow(data);
      }

      alert('Flow saved successfully!');
    } catch (err) {
      alert(`Error saving flow: ${err.message}`);
    }
  };

  // Export as JSON (Rabbitize-compatible format)
  const exportFlow = () => {
    const flow = {
      name: flowName || 'unnamed_flow',
      initial_url: currentUrl,
      // Export in Rabbitize format (array of command arrays)
      commands: commands.map(cmd => cmd.commandArray || buildCommandArray(cmd.command, cmd.args))
    };

    const blob = new Blob([JSON.stringify(flow, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${flow.name}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Format command for display
  const formatCommand = (cmd) => {
    const args = Object.entries(cmd.args || {})
      .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : v}`)
      .join(', ');
    return `${cmd.command}${args ? ` (${args})` : ''}`;
  };

  // Check for attached session on mount (from SessionsView)
  useEffect(() => {
    const attachSessionData = window.sessionStorage.getItem('attachSession');
    if (attachSessionData) {
      try {
        const session = JSON.parse(attachSessionData);
        window.sessionStorage.removeItem('attachSession');

        // Attach to the existing session
        console.log('Attaching to existing session:', session);

        setServerStatus('running');
        setSessionActive(true);
        setIsAttachedSession(true);
        setSessionId(session.session_id);
        setDashboardSessionId(session.session_id);
        setCurrentUrl(session.current_url || '');

        // First, try to get the stream path from the session data
        // Backend returns browser_session_path when enriching registry data
        const streamPath = session.browser_session_path || session.browser_session_id;

        if (streamPath) {
          const pathParts = streamPath.split('/');
          setSessionDetails({
            clientId: pathParts[0] || 'unknown',
            testId: pathParts[1] || 'unknown',
            sessionId: pathParts[2] || session.session_id,
            dashboardSessionId: session.session_id,
            streamPath: streamPath,
            port: session.port  // Store port for direct API calls
          });
        } else if (session.port) {
          // No stream path yet - fetch from Rabbitize status endpoint
          fetch(`http://localhost:${session.port}/status`)
            .then(res => res.json())
            .then(status => {
              console.log('Session status:', status);
              const currentState = status.currentState || {};
              const clientId = currentState.clientId || 'unknown';
              const testId = currentState.testId || 'unknown';
              const rabbitSessionId = currentState.sessionId;

              if (rabbitSessionId) {
                const fetchedStreamPath = `${clientId}/${testId}/${rabbitSessionId}`;
                setSessionDetails({
                  clientId,
                  testId,
                  sessionId: rabbitSessionId,
                  dashboardSessionId: session.session_id,
                  streamPath: fetchedStreamPath,
                  port: session.port
                });
                if (currentState.initialUrl) {
                  setCurrentUrl(currentState.initialUrl);
                }
              } else {
                // No active browser session on this Rabbitize server
                setSessionDetails({
                  clientId: 'attached',
                  testId: 'session',
                  sessionId: session.session_id,
                  dashboardSessionId: session.session_id,
                  port: session.port
                });
              }
            })
            .catch(err => {
              console.warn('Could not fetch session status:', err);
              // Set minimal details so we can still try to control the session
              setSessionDetails({
                clientId: 'attached',
                testId: 'session',
                sessionId: session.session_id,
                dashboardSessionId: session.session_id,
                port: session.port
              });
            });
        } else {
          // No port or stream path - very limited attachment
          setSessionDetails({
            clientId: 'attached',
            testId: 'session',
            sessionId: session.session_id,
            dashboardSessionId: session.session_id
          });
        }
      } catch (err) {
        console.error('Failed to attach to session:', err);
      }
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (sessionActive) {
        endSession();
      }
    };
  }, [sessionActive, endSession]);

  return (
    <div className="flow-builder-view">
      {/* Header */}
      <header className="flow-builder-header">
        <div className="header-left">
          <button className="back-btn" onClick={onBack}>
            <Icon icon="mdi:arrow-left" width="20" />
            Back
          </button>
          <div className="header-title">
            <h1>
              <Icon icon="mdi:code-braces-box" width="28" />
              Flow Builder
            </h1>
            <span className="subtitle">Interactive Browser Automation Designer</span>
          </div>
        </div>

        <div className="header-right">
          <span className={`session-status ${sessionActive ? 'active' : 'inactive'} ${isAttachedSession ? 'attached' : ''}`}>
            <Icon icon={sessionActive ? (isAttachedSession ? 'mdi:link' : 'mdi:circle') : 'mdi:circle-outline'} width="12" />
            {sessionActive ? (isAttachedSession ? 'Attached Session' : 'Session Active') : 'No Session'}
          </span>
          {sessionActive && (
            <button className="end-session-btn" onClick={endSession}>
              <Icon icon={isAttachedSession ? "mdi:link-off" : "mdi:stop"} width="18" />
              {isAttachedSession ? 'Detach' : 'End Session'}
            </button>
          )}
          {!sessionActive && serverStatus === 'error' && (
            <button
              className="restart-btn"
              onClick={async () => {
                setError(null);
                setServerStatus('starting');
                try {
                  const resp = await fetch(`${apiUrl}/api/rabbitize/restart`, { method: 'POST' });
                  const data = await resp.json();
                  if (data.success) {
                    setServerStatus('unknown');
                    setError(null);
                  } else {
                    setError(data.error || 'Restart failed');
                    setServerStatus('error');
                  }
                } catch (e) {
                  setError('Restart failed: ' + e.message);
                  setServerStatus('error');
                }
              }}
              title="Restart browser server"
            >
              <Icon icon="mdi:restart" width="18" />
              Restart Server
            </button>
          )}
        </div>
      </header>

      {/* Main Content */}
      <div className="flow-builder-content">
        {/* Browser Panel */}
        <div className="browser-panel">
          {/* URL Bar */}
          <form className="url-bar-form" onSubmit={handleUrlSubmit}>
            <div className="nav-buttons">
              <button
                type="button"
                className="nav-btn"
                onClick={handleBack}
                disabled={!sessionActive}
                title="Back"
              >
                <Icon icon="mdi:arrow-left" width="18" />
              </button>
              <button
                type="button"
                className="nav-btn"
                onClick={handleForward}
                disabled={!sessionActive}
                title="Forward"
              >
                <Icon icon="mdi:arrow-right" width="18" />
              </button>
              <button
                type="button"
                className="nav-btn"
                onClick={handleRefresh}
                disabled={!sessionActive}
                title="Refresh"
              >
                <Icon icon="mdi:refresh" width="18" />
              </button>
            </div>
            <div className="url-input-container">
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="Enter URL and press Enter to start..."
                className="url-input"
                disabled={loading}
              />
              {loading && <Icon icon="mdi:loading" width="20" className="spin url-loading" />}
            </div>
            <button
              type="submit"
              className="go-btn"
              disabled={!url || loading}
            >
              <Icon icon="mdi:arrow-right-circle" width="20" />
            </button>
          </form>

          {/* Browser Viewport */}
          <div
            className="browser-viewport"
            ref={viewportRef}
            onClick={handleViewportClick}
            onMouseMove={handleViewportMouseMove}
          >
            {!sessionActive ? (
              <div className="viewport-placeholder">
                <Icon icon="mdi:web" width="80" />
                <h2>Ready to Build Your Flow</h2>
                <p>Enter a URL above and press Enter to start</p>
                {serverStatus === 'starting' && (
                  <p className="hint starting">
                    <Icon icon="mdi:loading" width="16" className="spin" />
                    Starting browser session...
                  </p>
                )}
                {serverStatus === 'error' && (
                  <p className="hint error">
                    <Icon icon="mdi:alert" width="16" />
                    Failed to start. Check that node_modules is installed in rabbitize/
                  </p>
                )}
              </div>
            ) : (
              <div className="stream-container">
                <img
                  ref={streamRef}
                  src={sessionDetails?.streamPath
                    ? (sessionDetails?.port
                        ? `http://localhost:${sessionDetails.port}/stream/${sessionDetails.streamPath}`
                        : `${apiUrl}/api/rabbitize/stream/${sessionDetails.dashboardSessionId}/${sessionDetails.streamPath}`)
                    : ''}
                  alt="Browser Stream"
                  className="browser-stream"
                />
                <div className="click-overlay">
                  {clickPos && (
                    <div
                      className="position-marker"
                      style={{ left: clickPos.displayX || clickPos.x, top: clickPos.displayY || clickPos.y }}
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Coordinates Display */}
          <div className="coordinates-bar">
            <span className="coords">
              <Icon icon="mdi:crosshairs" width="16" />
              Mouse: ({mousePos.x}, {mousePos.y})
            </span>
            {clickPos && (
              <span className="coords selected">
                <Icon icon="mdi:target" width="16" />
                Selected: ({clickPos.x}, {clickPos.y})
              </span>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <aside className="flow-builder-sidebar">
          {/* Command Palette */}
          <div className="command-palette">
            <h3>
              <Icon icon="mdi:palette" width="18" />
              Command Palette
            </h3>

            {error && (
              <div className="error-message">
                <Icon icon="mdi:alert-circle" width="16" />
                {error}
                <button onClick={() => setError(null)}>
                  <Icon icon="mdi:close" width="14" />
                </button>
              </div>
            )}

            {/* Mouse Actions */}
            <div className="command-category">
              <h4>Mouse Actions</h4>
              <div className="command-buttons">
                <button onClick={handleClick} disabled={!sessionActive || !clickPos || executing}>
                  <Icon icon="mdi:cursor-default-click" width="16" />
                  Click
                </button>
                <button onClick={handleMoveClick} disabled={!sessionActive || !clickPos || executing}>
                  <Icon icon="mdi:cursor-move" width="16" />
                  Move + Click
                </button>
                <button onClick={handleRightClick} disabled={!sessionActive || !clickPos || executing}>
                  <Icon icon="mdi:cursor-default-click-outline" width="16" />
                  Right Click
                </button>
                <button onClick={handleMoveMouse} disabled={!sessionActive || !clickPos || executing}>
                  <Icon icon="mdi:cursor-move" width="16" />
                  Move Mouse
                </button>
              </div>
            </div>

            {/* Scrolling */}
            <div className="command-category">
              <h4>Scrolling</h4>
              <div className="command-buttons">
                <button onClick={handleScrollUp} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:arrow-up" width="16" />
                  Scroll Up
                </button>
                <button onClick={handleScrollDown} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:arrow-down" width="16" />
                  Scroll Down
                </button>
              </div>
            </div>

            {/* Input */}
            <div className="command-category">
              <h4>Input</h4>
              <div className="command-buttons">
                <button onClick={handleType} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:keyboard" width="16" />
                  Type Text
                </button>
                <button onClick={handleKey} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:keyboard-variant" width="16" />
                  Key Press
                </button>
              </div>
            </div>

            {/* Navigation */}
            <div className="command-category">
              <h4>Navigation</h4>
              <div className="command-buttons">
                <button onClick={handleNavigate} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:link-variant" width="16" />
                  Navigate
                </button>
              </div>
            </div>

            {/* Utility */}
            <div className="command-category">
              <h4>Utility</h4>
              <div className="command-buttons">
                <button onClick={handleWait} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:timer" width="16" />
                  Wait
                </button>
                <button onClick={handleScreenshot} disabled={!sessionActive || executing}>
                  <Icon icon="mdi:camera" width="16" />
                  Screenshot
                </button>
              </div>
            </div>
          </div>

          {/* Command History */}
          <div className="command-history">
            <div className="history-header">
              <h3>
                <Icon icon="mdi:history" width="18" />
                Commands ({commands.length})
              </h3>
              <div className="history-actions">
                <button onClick={clearCommands} disabled={commands.length === 0} title="Clear all">
                  <Icon icon="mdi:delete-sweep" width="18" />
                </button>
                <button onClick={exportFlow} disabled={commands.length === 0} title="Export JSON">
                  <Icon icon="mdi:download" width="18" />
                </button>
                <button onClick={() => setShowSaveModal(true)} disabled={commands.length === 0} title="Save flow">
                  <Icon icon="mdi:content-save" width="18" />
                </button>
              </div>
            </div>

            <div className="command-list">
              {commands.length === 0 ? (
                <div className="empty-history">
                  <Icon icon="mdi:script-text-outline" width="32" />
                  <p>No commands yet</p>
                  <span>Execute commands to build your flow</span>
                </div>
              ) : (
                commands.map((cmd, index) => (
                  <div
                    key={index}
                    className={`command-item ${cmd.success ? 'success' : 'error'}`}
                  >
                    <span className="command-index">{index + 1}</span>
                    <span className="command-text">{formatCommand(cmd)}</span>
                    <button
                      className="remove-btn"
                      onClick={() => removeCommand(index)}
                      title="Remove"
                    >
                      <Icon icon="mdi:close" width="14" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Live Sessions Panel */}
          <LiveSessionsPanel
            compact={true}
            currentSessionId={dashboardSessionId}
            onSelectSession={(session) => {
              // Could switch to viewing this session's stream
              console.log('Selected session:', session);
            }}
          />
        </aside>
      </div>

      {/* Save Modal */}
      {showSaveModal && (
        <div className="modal-overlay" onClick={() => setShowSaveModal(false)}>
          <div className="save-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>
                <Icon icon="mdi:content-save" width="24" />
                Save Flow
              </h2>
              <button className="close-btn" onClick={() => setShowSaveModal(false)}>
                <Icon icon="mdi:close" width="20" />
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Flow Name *</label>
                <input
                  type="text"
                  value={flowName}
                  onChange={(e) => setFlowName(e.target.value)}
                  placeholder="my_automation_flow"
                />
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea
                  value={flowDescription}
                  onChange={(e) => setFlowDescription(e.target.value)}
                  placeholder="Describe what this flow does..."
                  rows={3}
                />
              </div>
              <div className="form-group">
                <label>Initial URL</label>
                <input
                  type="text"
                  value={currentUrl}
                  readOnly
                  className="readonly"
                />
              </div>
              <div className="form-group">
                <label>Commands</label>
                <div className="command-preview">
                  {commands.length} command(s) will be saved
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="cancel-btn" onClick={() => setShowSaveModal(false)}>
                Cancel
              </button>
              <button className="save-btn" onClick={saveFlow} disabled={!flowName}>
                <Icon icon="mdi:check" width="18" />
                Save Flow
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default FlowBuilderView;
