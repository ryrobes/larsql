import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './RabbitizeRecorderEditor.css';

/**
 * Rabbitize Recorder Editor (Studio-embedded version)
 *
 * Simplified browser automation recorder for embedding in PhaseDetailPanel.
 * Records user interactions with live MJPEG stream and builds batch command arrays.
 *
 * Props:
 * - phase: Current phase object (for reading initial state)
 * - onChange: (updatedPhase) => void - Called when commands change
 * - phaseName: string - Phase name (for session ID)
 */
function RabbitizeRecorderEditor({ phase, onChange, phaseName }) {
  // Extract initial state from phase (parse npx rabbitize command)
  const extractFromPhase = (phase) => {
    const command = phase?.inputs?.command || '';

    // Parse --batch-url "..."
    const urlMatch = command.match(/--batch-url\s+"([^"]+)"/);
    const initialUrl = urlMatch ? urlMatch[1] : 'https://example.com';

    // Parse --batch-commands='[...]'
    const batchMatch = command.match(/--batch-commands='(\[[\s\S]*?\])'/);
    let commands = [];

    if (batchMatch) {
      try {
        commands = JSON.parse(batchMatch[1]);
      } catch (e) {
        console.error('Failed to parse batch commands:', e);
      }
    }

    // Parse --client-id "..."
    const clientIdMatch = command.match(/--client-id\s+"([^"]+)"/);
    const clientId = clientIdMatch ? clientIdMatch[1] : 'untitled_cascade';

    // Parse --test-id "..."
    const testIdMatch = command.match(/--test-id\s+"([^"]+)"/);
    const testId = testIdMatch ? testIdMatch[1] : `${phase.name}.studio`;

    return { initialUrl, commands, clientId, testId };
  };

  const { initialUrl: extractedUrl, commands: extractedCommands, clientId: extractedClientId, testId: extractedTestId } = extractFromPhase(phase);

  // State
  const [sessionActive, setSessionActive] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [dashboardSessionId, setDashboardSessionId] = useState(null);
  const [streamPath, setStreamPath] = useState('');
  const [port, setPort] = useState(null);

  const [url, setUrl] = useState(extractedUrl);
  const [currentUrl, setCurrentUrl] = useState(extractedUrl);
  const [commands, setCommands] = useState(extractedCommands);
  const [clientId] = useState(extractedClientId); // Preserve from phase
  const [testId] = useState(extractedTestId); // Preserve from phase

  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [clickPos, setClickPos] = useState(null);

  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState(null);

  const streamRef = useRef(null);
  const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:5050';

  // Build Rabbitize command array
  const buildCommandArray = (commandType, args) => {
    switch (commandType) {
      case ':click':
        return [':click']; // Assumes mouse is already positioned
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
      case ':scroll-wheel-down':
        return [':scroll-wheel-down', args.amount];
      case ':scroll-wheel-up':
        return [':scroll-wheel-up', args.amount];
      default:
        return [commandType, ...Object.values(args)];
    }
  };

  // Update parent phase when commands change
  const updatePhaseCommands = useCallback((newCommands, newUrl) => {
    const updatedPhase = {
      ...phase,
      tool: 'linux_shell_dangerous', // Run on host, not in Docker
      inputs: {
        ...phase.inputs,
        command: `npx rabbitize \\
  --client-id "${clientId}" \\
  --test-id "${testId}" \\
  --exit-on-end true \\
  --process-video true \\
  --batch-url "${newUrl || currentUrl}" \\
  --batch-commands='${JSON.stringify(newCommands, null, 0)}'`
      }
    };

    onChange(updatedPhase);
  }, [phase, onChange, clientId, testId, currentUrl]);

  // Start recording session
  const startSession = useCallback(async (navigateUrl) => {
    if (!navigateUrl) return;

    setLoading(true);
    setError(null);

    const newDashboardSessionId = `studio_recorder_${phaseName}_${Date.now()}`;

    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: navigateUrl,
          clientId: clientId,
          testId: testId,
          dashboard_session_id: newDashboardSessionId
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to start session');
      }

      setSessionActive(true);
      setSessionId(data.sessionId);
      setDashboardSessionId(newDashboardSessionId);
      setStreamPath(`${data.clientId}/${data.testId}/${data.sessionId}`);
      setPort(data.port);
      setCurrentUrl(navigateUrl);
    } catch (err) {
      setError(err.message || 'Failed to start session');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, phaseName, clientId, testId]);

  // Stop recording session
  const stopSession = useCallback(async () => {
    if (!sessionActive) return;

    try {
      await fetch(`${apiUrl}/api/rabbitize/session/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dashboard_session_id: dashboardSessionId })
      });
    } catch (err) {
      console.error('Error ending session:', err);
    }

    setSessionActive(false);
    setSessionId(null);
    setDashboardSessionId(null);
    setPort(null);
    setStreamPath('');
  }, [sessionActive, apiUrl, dashboardSessionId]);

  // Execute command
  const executeCommand = useCallback(async (commandType, args = {}) => {
    if (!sessionActive) return;

    setExecuting(true);

    try {
      const commandArray = buildCommandArray(commandType, args);

      const url = port
        ? `http://localhost:${port}/execute`
        : `${apiUrl}/api/rabbitize/session/execute`;

      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          port
            ? { command: commandArray }
            : { command: commandArray, dashboard_session_id: dashboardSessionId }
        )
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Add to commands and update parent
      const newCommands = [...commands, commandArray];
      setCommands(newCommands);
      updatePhaseCommands(newCommands, currentUrl);

    } catch (err) {
      setError(err.message);
    } finally {
      setExecuting(false);
    }
  }, [sessionActive, apiUrl, dashboardSessionId, port, commands, currentUrl, updatePhaseCommands]);

  // Handle viewport click
  const handleViewportClick = (e) => {
    if (!sessionActive || !streamRef.current) return;

    const img = streamRef.current;
    const imgRect = img.getBoundingClientRect();

    // Get the container rect (parent of img) for marker positioning
    const container = img.parentElement;
    const containerRect = container.getBoundingClientRect();

    // With object-fit: contain, the image might be letterboxed/pillarboxed
    // Calculate the actual rendered image dimensions and position
    const naturalWidth = img.naturalWidth || imgRect.width;
    const naturalHeight = img.naturalHeight || imgRect.height;
    const naturalRatio = naturalWidth / naturalHeight;
    const displayRatio = imgRect.width / imgRect.height;

    let renderedWidth, renderedHeight, offsetX, offsetY;

    if (displayRatio > naturalRatio) {
      // Pillarboxed (black bars on sides)
      renderedHeight = imgRect.height;
      renderedWidth = naturalRatio * renderedHeight;
      offsetX = (imgRect.width - renderedWidth) / 2;
      offsetY = 0;
    } else {
      // Letterboxed (black bars on top/bottom)
      renderedWidth = imgRect.width;
      renderedHeight = renderedWidth / naturalRatio;
      offsetX = 0;
      offsetY = (imgRect.height - renderedHeight) / 2;
    }

    // Click position relative to the img element
    const imgClickX = e.clientX - imgRect.left;
    const imgClickY = e.clientY - imgRect.top;

    // Click position relative to the actual rendered image (for browser coords)
    const displayX = imgClickX - offsetX;
    const displayY = imgClickY - offsetY;

    // Scale to natural browser coordinates
    const scaleX = naturalWidth / renderedWidth;
    const scaleY = naturalHeight / renderedHeight;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    // Marker position relative to the container (for visual marker)
    const markerX = e.clientX - containerRect.left;
    const markerY = e.clientY - containerRect.top;

    setClickPos({
      x,
      y,
      displayX: Math.round(markerX),
      displayY: Math.round(markerY)
    });
  };

  // Handle viewport mouse move
  const handleViewportMouseMove = (e) => {
    if (!streamRef.current) return;

    const img = streamRef.current;
    const rect = img.getBoundingClientRect();

    // Same letterboxing calculation as click handler
    const naturalWidth = img.naturalWidth || rect.width;
    const naturalHeight = img.naturalHeight || rect.height;
    const naturalRatio = naturalWidth / naturalHeight;
    const displayRatio = rect.width / rect.height;

    let renderedWidth, renderedHeight, offsetX, offsetY;

    if (displayRatio > naturalRatio) {
      renderedHeight = rect.height;
      renderedWidth = naturalRatio * renderedHeight;
      offsetX = (rect.width - renderedWidth) / 2;
      offsetY = 0;
    } else {
      renderedWidth = rect.width;
      renderedHeight = renderedWidth / naturalRatio;
      offsetX = 0;
      offsetY = (rect.height - renderedHeight) / 2;
    }

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const displayX = mouseX - offsetX;
    const displayY = mouseY - offsetY;

    const scaleX = naturalWidth / renderedWidth;
    const scaleY = naturalHeight / renderedHeight;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    setMousePos({ x: Math.max(0, x), y: Math.max(0, y) });
  };

  // Command handlers
  const handleClick = () => {
    executeCommand(':click', {}); // No coords needed - assumes mouse is already there
  };

  const handleRightClick = () => {
    if (clickPos) executeCommand(':right-click', { x: clickPos.x, y: clickPos.y });
  };

  const handleMoveMouse = () => {
    if (clickPos) executeCommand(':move-mouse', { x: clickPos.x, y: clickPos.y });
  };

  const handleScrollDown = () => {
    executeCommand(':scroll-wheel-down', { amount: 5 });
  };

  const handleScrollUp = () => {
    executeCommand(':scroll-wheel-up', { amount: 5 });
  };

  const handleType = () => {
    const text = prompt('Enter text to type:');
    if (text) executeCommand(':type', { text });
  };

  const handleNavigate = () => {
    const newUrl = prompt('Navigate to URL:', currentUrl);
    if (newUrl) {
      executeCommand(':navigate', { url: newUrl });
      setCurrentUrl(newUrl);
    }
  };

  // Clear all commands
  const clearCommands = () => {
    setCommands([]);
    updatePhaseCommands([], currentUrl);
  };

  // Remove command
  const removeCommand = (index) => {
    const newCommands = commands.filter((_, i) => i !== index);
    setCommands(newCommands);
    updatePhaseCommands(newCommands, currentUrl);
  };

  // Undo last command
  const undoLast = () => {
    if (commands.length === 0) return;
    const newCommands = commands.slice(0, -1);
    setCommands(newCommands);
    updatePhaseCommands(newCommands, currentUrl);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (sessionActive) {
        stopSession();
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="rabbitize-recorder-editor">
      {/* Header Controls */}
      <div className="recorder-header">
        {!sessionActive ? (
          <>
            <input
              type="url"
              className="url-input"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Enter URL to start recording..."
              disabled={loading}
            />
            <button
              className="start-btn"
              onClick={() => startSession(url)}
              disabled={!url || loading}
            >
              <Icon icon={loading ? 'mdi:loading' : 'mdi:play'} width="16" className={loading ? 'spin' : ''} />
              {loading ? 'Starting...' : 'Start Recording'}
            </button>
          </>
        ) : (
          <>
            <span className="current-url">
              <Icon icon="mdi:web" width="16" />
              {currentUrl}
            </span>
            <button className="stop-btn" onClick={stopSession}>
              <Icon icon="mdi:stop" width="16" />
              Stop
            </button>
          </>
        )}
      </div>

      {error && (
        <div className="error-banner">
          <Icon icon="mdi:alert-circle" width="16" />
          {error}
          <button onClick={() => setError(null)}>
            <Icon icon="mdi:close" width="14" />
          </button>
        </div>
      )}

      {/* Main Content */}
      <div className="recorder-content">
        {/* Browser Panel */}
        <div className="browser-panel">
          <div
            className="browser-viewport"
            onClick={handleViewportClick}
            onMouseMove={handleViewportMouseMove}
          >
            {!sessionActive ? (
              <div className="viewport-placeholder">
                <Icon icon="mdi:web" width="60" />
                <h3>Ready to Record</h3>
                <p>Enter a URL above and click Start Recording</p>
              </div>
            ) : (
              <div className="stream-container">
                <img
                  ref={streamRef}
                  src={port
                    ? `http://localhost:${port}/stream/${streamPath}`
                    : `${apiUrl}/api/rabbitize/stream/${dashboardSessionId}/${streamPath}`}
                  alt="Browser Stream"
                  className="browser-stream"
                />
                {clickPos && (
                  <div
                    className="position-marker"
                    style={{
                      left: clickPos.displayX || clickPos.x,
                      top: clickPos.displayY || clickPos.y
                    }}
                  />
                )}
              </div>
            )}
          </div>

          {/* Coordinates Bar */}
          {sessionActive && (
            <div className="coordinates-bar">
              <span>
                <Icon icon="mdi:crosshairs" width="14" />
                ({mousePos.x}, {mousePos.y})
              </span>
              {clickPos && (
                <span className="selected">
                  <Icon icon="mdi:target" width="14" />
                  Selected: ({clickPos.x}, {clickPos.y})
                </span>
              )}
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="recorder-sidebar">
          {/* Command Palette */}
          <div className="command-palette">
            <h4>
              <Icon icon="mdi:palette" width="16" />
              Commands
            </h4>

            <div className="command-buttons">
              <button onClick={handleClick} disabled={!sessionActive || executing} title="Click (assumes mouse already positioned)">
                <Icon icon="mdi:cursor-default-click" width="14" />
                Click
              </button>
              <button onClick={handleRightClick} disabled={!sessionActive || !clickPos || executing} title="Right click at position">
                <Icon icon="mdi:cursor-default-click-outline" width="14" />
                Right Click
              </button>
              <button onClick={handleMoveMouse} disabled={!sessionActive || !clickPos || executing} title="Move mouse to position">
                <Icon icon="mdi:cursor-default" width="14" />
                Move Mouse
              </button>
              <button onClick={handleScrollDown} disabled={!sessionActive || executing} title="Scroll down">
                <Icon icon="mdi:arrow-down" width="14" />
                Scroll Down
              </button>
              <button onClick={handleScrollUp} disabled={!sessionActive || executing} title="Scroll up">
                <Icon icon="mdi:arrow-up" width="14" />
                Scroll Up
              </button>
              <button onClick={handleType} disabled={!sessionActive || executing} title="Type text">
                <Icon icon="mdi:keyboard" width="14" />
                Type
              </button>
              <button onClick={handleNavigate} disabled={!sessionActive || executing} title="Navigate to URL">
                <Icon icon="mdi:link-variant" width="14" />
                Navigate
              </button>
            </div>
          </div>

          {/* Command History */}
          <div className="command-history">
            <div className="history-header">
              <h4>
                <Icon icon="mdi:history" width="16" />
                History ({commands.length})
              </h4>
              <div className="history-actions">
                <button onClick={undoLast} disabled={commands.length === 0} title="Undo last">
                  <Icon icon="mdi:undo" width="16" />
                </button>
                <button onClick={clearCommands} disabled={commands.length === 0} title="Clear all">
                  <Icon icon="mdi:delete-sweep" width="16" />
                </button>
              </div>
            </div>

            <div className="command-list">
              {commands.length === 0 ? (
                <div className="empty-history">
                  <Icon icon="mdi:script-text-outline" width="24" />
                  <p>No commands yet</p>
                </div>
              ) : (
                commands.map((cmd, index) => (
                  <div key={index} className="command-item">
                    <span className="command-index">{index + 1}</span>
                    <code className="command-text">{JSON.stringify(cmd)}</code>
                    <button
                      className="remove-btn"
                      onClick={() => removeCommand(index)}
                      title="Remove"
                    >
                      <Icon icon="mdi:close" width="12" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RabbitizeRecorderEditor;
