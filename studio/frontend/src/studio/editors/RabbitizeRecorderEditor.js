import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './RabbitizeRecorderEditor.css';
import { API_BASE_URL } from '../../config/api';

/**
 * Rabbitize Recorder Editor (Studio-embedded version)
 *
 * Simplified browser automation recorder for embedding in CellDetailPanel.
 * Records user interactions with live MJPEG stream and builds action arrays.
 *
 * Now uses the native `browser` tool format with declarative actions:
 *   tool: browser
 *   inputs:
 *     url: "https://example.com"
 *     actions:
 *       - wait: 1
 *       - screenshot: {}
 *       - move: {x: 400, y: 300}
 *       - click: {}
 *
 * Props:
 * - cell: Current cell object (for reading initial state)
 * - onChange: (updatedCell) => void - Called when commands change
 * - cellName: string - Cell name (for session ID)
 */
function RabbitizeRecorderEditor({ cell, onChange, cellName }) {
  // Extract initial state from cell (supports both native format and legacy shell format)
  const extractFromCell = (cell) => {
    // Check for native browser tool format first
    if (cell?.tool === 'browser' && cell?.inputs) {
      const inputs = cell.inputs;
      const initialUrl = inputs.url || 'https://example.com';

      // Convert actions to command arrays (internal format for recording)
      let commands = [];
      if (inputs.actions && Array.isArray(inputs.actions)) {
        commands = inputs.actions.map(action => actionsToCommand(action));
      } else if (inputs.commands && Array.isArray(inputs.commands)) {
        commands = inputs.commands;
      }

      return { initialUrl, commands, clientId: null, testId: null };
    }

    // Legacy: parse lars browser batch shell command
    const command = cell?.inputs?.command || '';

    // Parse --url "..." (new format) or --batch-url "..." (legacy)
    const urlMatch = command.match(/--url\s+"([^"]+)"/) || command.match(/--batch-url\s+"([^"]+)"/);
    const initialUrl = urlMatch ? urlMatch[1] : 'https://example.com';

    // Parse --commands='[...]' (new format) or --batch-commands='[...]' (legacy)
    const batchMatch = command.match(/--commands='(\[[\s\S]*?\])'/) || command.match(/--batch-commands='(\[[\s\S]*?\])'/);
    let commands = [];

    if (batchMatch) {
      try {
        commands = JSON.parse(batchMatch[1]);
      } catch (e) {
        console.error('Failed to parse batch commands:', e);
      }
    }

    // Parse --client-id "..." (not used in native format)
    const clientIdMatch = command.match(/--client-id\s+"([^"]+)"/);
    const clientId = clientIdMatch ? clientIdMatch[1] : null;

    // Parse --test-id "..."
    const testIdMatch = command.match(/--test-id\s+"([^"]+)"/);
    const testId = testIdMatch ? testIdMatch[1] : null;

    return { initialUrl, commands, clientId, testId };
  };

  // Convert a single action object to command array (for internal recording)
  const actionsToCommand = (action) => {
    if (Array.isArray(action)) return action; // Already a command

    const key = Object.keys(action)[0];
    const value = action[key];

    switch (key) {
      case 'wait': return [':wait', value];
      case 'screenshot': return [':screenshot'];
      case 'move': case 'move_mouse': return [':move-mouse', ':to', value.x || 0, value.y || 0];
      case 'click': return [':click'];
      case 'double_click': return [':double-click'];
      case 'right_click': return [':right-click'];
      case 'type': case 'text':
        return [':type', typeof value === 'object' ? value.text : value];
      case 'keypress': case 'key': return [':keypress', value];
      case 'scroll_down': return [':scroll-wheel-down', typeof value === 'number' ? value : 3];
      case 'scroll_up': return [':scroll-wheel-up', typeof value === 'number' ? value : 3];
      case 'url': case 'navigate': case 'goto': return [':url', value];
      default: return [`:${key}`, value];
    }
  };

  const { initialUrl: extractedUrl, commands: extractedCommands } = extractFromCell(cell);

  // Generate IDs for the recording session (used for live preview, not final cell output)
  const recordingClientId = `studio_recorder`;
  const recordingTestId = cellName || 'browser';

  // State
  const [sessionActive, setSessionActive] = useState(false);
  const [, setSessionId] = useState(null);
  const [dashboardSessionId, setDashboardSessionId] = useState(null);
  const [streamPath, setStreamPath] = useState('');
  const [port, setPort] = useState(null);

  const [url, setUrl] = useState(extractedUrl);
  const [currentUrl, setCurrentUrl] = useState(extractedUrl);
  const [commands, setCommands] = useState(extractedCommands);

  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [clickPos, setClickPos] = useState(null);

  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState(null);

  const streamRef = useRef(null);
  const apiUrl = process.env.REACT_APP_API_URL || API_BASE_URL;

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

  // Convert command array to action object (for native format)
  const commandToAction = (command) => {
    if (!Array.isArray(command) || command.length === 0) return null;

    const cmd = command[0];
    switch (cmd) {
      case ':wait':
        return { wait: command[1] || 1 };
      case ':screenshot':
        return { screenshot: {} };
      case ':move-mouse':
        // [':move-mouse', ':to', x, y]
        return { move: { x: command[2] || 0, y: command[3] || 0 } };
      case ':click':
        return { click: {} };
      case ':double-click':
        return { double_click: {} };
      case ':right-click':
        return { right_click: {} };
      case ':type':
        // [':type', text] or [':type', ':text', text]
        const text = command[1] === ':text' ? command[2] : command[1];
        return { type: { text: text || '' } };
      case ':keypress': case ':key':
        return { keypress: command[1] || '' };
      case ':scroll-wheel-down':
        return { scroll_down: command[1] || 3 };
      case ':scroll-wheel-up':
        return { scroll_up: command[1] || 3 };
      case ':url': case ':navigate':
        return { navigate: command[1] || command[2] || '' };
      default:
        // Keep as raw command array for unknown commands
        return null;
    }
  };

  // Update parent cell when commands change - now uses native browser tool format
  const updateCellCommands = useCallback((newCommands, newUrl) => {
    // Convert command arrays to declarative actions
    const actions = newCommands
      .map(cmd => commandToAction(cmd))
      .filter(action => action !== null);

    const updatedCell = {
      ...cell,
      tool: 'browser',  // Native browser tool
      inputs: {
        url: newUrl || currentUrl,
        actions: actions.length > 0 ? actions : [{ wait: 1 }, { screenshot: {} }]
      }
    };

    // Remove legacy 'command' field if present
    if (updatedCell.inputs.command) {
      delete updatedCell.inputs.command;
    }

    onChange(updatedCell);
  }, [cell, onChange, currentUrl]);

  // Start recording session
  const startSession = useCallback(async (navigateUrl) => {
    if (!navigateUrl) return;

    setLoading(true);
    setError(null);

    const newDashboardSessionId = `studio_recorder_${cellName}_${Date.now()}`;

    try {
      const response = await fetch(`${apiUrl}/api/rabbitize/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: navigateUrl,
          clientId: recordingClientId,
          testId: recordingTestId,
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

      // Immediately update cell with the URL (even before commands are recorded)
      updateCellCommands(commands, navigateUrl);
    } catch (err) {
      setError(err.message || 'Failed to start session');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, cellName, recordingClientId, recordingTestId, commands, updateCellCommands]);

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

      const response = await fetch(`${apiUrl}/api/rabbitize/session/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          command: commandArray,
          dashboard_session_id: dashboardSessionId
        })
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Add to commands and update parent
      const newCommands = [...commands, commandArray];
      setCommands(newCommands);
      updateCellCommands(newCommands, currentUrl);

    } catch (err) {
      setError(err.message);
    } finally {
      setExecuting(false);
    }
  }, [sessionActive, apiUrl, dashboardSessionId, commands, currentUrl, updateCellCommands]);

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
    updateCellCommands([], currentUrl);
  };

  // Remove command
  const removeCommand = (index) => {
    const newCommands = commands.filter((_, i) => i !== index);
    setCommands(newCommands);
    updateCellCommands(newCommands, currentUrl);
  };

  // Undo last command
  const undoLast = () => {
    if (commands.length === 0) return;
    const newCommands = commands.slice(0, -1);
    setCommands(newCommands);
    updateCellCommands(newCommands, currentUrl);
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
                  src={`${apiUrl}/api/rabbitize/stream/${dashboardSessionId}/${streamPath}`}
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
