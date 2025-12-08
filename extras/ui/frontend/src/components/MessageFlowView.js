import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { Icon } from '@iconify/react';
import './MessageFlowView.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5001';

function MessageFlowView({ onBack }) {
  const [sessionId, setSessionId] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState(new Set());
  const [highlightedMessage, setHighlightedMessage] = useState(null);
  const [runningSessions, setRunningSessions] = useState([]);
  const [showSessionDropdown, setShowSessionDropdown] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [waitingForData, setWaitingForData] = useState(false); // True when session is running but no data yet
  const dropdownRef = useRef(null);
  const currentSessionIdRef = useRef(null);

  // Check if a session ID is in the running sessions list
  const isSessionRunning = useCallback((sid) => {
    return runningSessions.some(s =>
      s.session_id === sid && (s.status === 'running' || s.status === 'completing')
    );
  }, [runningSessions]);

  const fetchMessages = useCallback(async (targetSessionId = null, silent = false) => {
    const sid = targetSessionId || currentSessionIdRef.current || sessionId;
    if (!sid.trim()) return;

    if (!silent) {
      setLoading(true);
      setError(null);
      setWaitingForData(false);
    }

    try {
      const response = await axios.get(`${API_BASE_URL}/api/message-flow/${sid}`);
      setData(response.data);
      setWaitingForData(false);
      setError(null);
      currentSessionIdRef.current = sid;
      if (targetSessionId && targetSessionId !== sessionId) {
        setSessionId(targetSessionId);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.error || err.message;
      const isNotFound = err.response?.status === 404 || errorMsg.includes('No data found');

      // If session is running but no data yet, show "waiting" state instead of error
      if (isNotFound && isSessionRunning(sid)) {
        setWaitingForData(true);
        setError(null);
        currentSessionIdRef.current = sid;
        if (targetSessionId && targetSessionId !== sessionId) {
          setSessionId(targetSessionId);
        }
      } else if (!silent) {
        setError(errorMsg);
        setWaitingForData(false);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [sessionId, isSessionRunning]);

  const fetchRunningSessions = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/running-sessions`);
      setRunningSessions(response.data.sessions || []);
    } catch (err) {
      console.error('Failed to fetch running sessions:', err);
    }
  }, []);

  // Fetch running sessions on mount and every 5 seconds
  useEffect(() => {
    fetchRunningSessions();
    const interval = setInterval(fetchRunningSessions, 5000);
    return () => clearInterval(interval);
  }, [fetchRunningSessions]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowSessionDropdown(false);
      }
    };

    if (showSessionDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showSessionDropdown]);

  // Check if current session is running (works even without data)
  const isCurrentSessionRunning = useCallback(() => {
    const sid = data?.session_id || currentSessionIdRef.current;
    if (!sid) return false;
    return isSessionRunning(sid);
  }, [data?.session_id, isSessionRunning]);

  // Auto-refresh when viewing a running session OR waiting for data
  useEffect(() => {
    const sid = data?.session_id || currentSessionIdRef.current;
    const shouldRefresh = autoRefresh && sid && (isCurrentSessionRunning() || waitingForData);

    if (!shouldRefresh) {
      return;
    }

    const interval = setInterval(() => {
      fetchMessages(null, true); // silent refresh
    }, 2000); // refresh every 2 seconds

    return () => clearInterval(interval);
  }, [autoRefresh, data?.session_id, isCurrentSessionRunning, waitingForData, fetchMessages]);

  const handleSessionSelect = (session) => {
    setShowSessionDropdown(false);
    fetchMessages(session.session_id);
  };

  const formatAge = (seconds) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  const toggleMessage = (index) => {
    const newExpanded = new Set(expandedMessages);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedMessages(newExpanded);
  };

  const scrollToMostExpensive = () => {
    if (!data?.cost_summary?.most_expensive) return;

    const expensiveInfo = data.cost_summary.most_expensive;
    const elementId = `message-${expensiveInfo.index}`;
    const element = document.getElementById(elementId);

    if (element) {
      // Highlight temporarily
      setHighlightedMessage(expensiveInfo.index);
      setTimeout(() => setHighlightedMessage(null), 3000);

      // Smooth scroll
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  // Helper to find global index of a message
  const findGlobalIndex = (msg) => {
    if (!data?.all_messages) return -1;
    // Match by timestamp and role as unique identifier
    return data.all_messages.findIndex(m =>
      m.timestamp === msg.timestamp &&
      m.role === msg.role &&
      m.node_type === msg.node_type
    );
  };

  // Category colors for badges
  const categoryColors = {
    'llm_call': { bg: '#4ec9b0', color: '#1e1e1e', label: 'LLM' },
    'conversation': { bg: '#60a5fa', color: '#1e1e1e', label: 'Conv' },
    'evaluator': { bg: '#c586c0', color: '#1e1e1e', label: 'Eval' },
    'quartermaster': { bg: '#dcdcaa', color: '#1e1e1e', label: 'QM' },
    'ward': { bg: '#ce9178', color: '#1e1e1e', label: 'Ward' },
    'lifecycle': { bg: '#6a9955', color: '#1e1e1e', label: 'Life' },
    'metadata': { bg: '#808080', color: '#1e1e1e', label: 'Meta' },
    'error': { bg: '#f87171', color: '#1e1e1e', label: 'Err' },
    'other': { bg: '#666666', color: '#1e1e1e', label: '?' }
  };

  const renderMessage = (msg, index, label) => {
    const globalIndex = findGlobalIndex(msg);
    const isExpanded = expandedMessages.has(index);
    const hasFullRequest = msg.full_request && msg.full_request.messages;
    const hasContent = msg.content && msg.content.length > 200;
    const isExpandable = hasFullRequest || hasContent;
    const messageCount = hasFullRequest ? msg.full_request.messages.length : 0;
    const fromSounding = msg.sounding_index !== null;
    const fromReforge = msg.reforge_step !== null;
    const isFollowUp = msg.node_type === 'follow_up';
    const isHighlighted = highlightedMessage === globalIndex;
    const isMostExpensive = data?.cost_summary?.most_expensive?.index === globalIndex;
    const isInternal = msg.is_internal;
    const category = msg.message_category || 'other';
    const categoryStyle = categoryColors[category] || categoryColors['other'];

    // Count images in full_request and extract first thumbnail
    let imageCount = 0;
    let totalBase64Size = 0;
    let firstImageUrl = null;  // For thumbnail preview
    if (hasFullRequest) {
      msg.full_request.messages.forEach(m => {
        if (Array.isArray(m.content)) {
          m.content.forEach(part => {
            if (part.type === 'image_url') {
              imageCount++;
              const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
              if (url.startsWith('data:image')) {
                // Estimate base64 size (remove data URL prefix)
                const base64Data = url.split(',')[1] || '';
                totalBase64Size += base64Data.length;

                // Capture first image for thumbnail
                if (!firstImageUrl) {
                  firstImageUrl = url;
                }
              }
            }
          });
        } else if (typeof m.content === 'string' && m.content.includes('data:image')) {
          // Count embedded base64 in string content
          const matches = m.content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
          imageCount += matches.length;
          matches.forEach(match => {
            const base64Data = match.split(',')[1] || '';
            totalBase64Size += base64Data.length;

            // Capture first image for thumbnail
            if (!firstImageUrl) {
              firstImageUrl = match;
            }
          });
        }
      });
    }

    return (
      <div
        key={index}
        id={`message-${globalIndex}`}
        className={`message ${msg.role} ${msg.is_winner ? 'winner' : ''} ${isFollowUp ? 'follow-up' : ''} ${isHighlighted ? 'highlighted' : ''} ${isMostExpensive ? 'most-expensive' : ''} ${isInternal ? 'is-internal' : ''}`}
        onClick={() => isExpandable && toggleMessage(index)}
        style={{ cursor: isExpandable ? 'pointer' : 'default' }}
      >
        <div className="message-header">
          <span className="message-label">{label}</span>
          {/* Category badge */}
          <span
            className="category-badge"
            style={{
              background: categoryStyle.bg,
              color: categoryStyle.color,
              padding: '2px 6px',
              borderRadius: '3px',
              fontSize: '10px',
              fontWeight: 'bold',
              opacity: isInternal ? 0.7 : 1
            }}
            title={`Category: ${category}${isInternal ? ' (internal - not sent to LLM)' : ''}`}
          >
            {categoryStyle.label}
          </span>
          {fromSounding && <span className="source-badge" style={{background: '#4ec9b0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px'}}>S{msg.sounding_index}</span>}
          {fromReforge && <span className="source-badge" style={{background: '#c586c0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px'}}>R{msg.reforge_step}</span>}
          <span className="message-role">{msg.role}</span>
          <span className="message-node-type">{msg.node_type}</span>
          {msg.model && <span className="message-model" title={msg.model}>{msg.model.split('/').pop()}</span>}
          {msg.turn_number !== null && <span className="turn">Turn {msg.turn_number}</span>}
          {msg.tokens_in > 0 && <span className="tokens">{msg.tokens_in.toLocaleString()} tokens in</span>}
          {msg.cost > 0 && <span className="cost-badge">${msg.cost.toFixed(4)}</span>}
          {imageCount > 0 && (
            <span className="image-badge" title={`Total base64 size: ${(totalBase64Size / 1024).toFixed(1)}kb (~${Math.round(totalBase64Size / 4)} tokens)`}>
              <Icon icon="mdi:image" width="14" style={{ marginRight: '4px' }} />{imageCount} image{imageCount > 1 ? 's' : ''}
            </span>
          )}
          {msg.is_winner && <span className="winner-badge"><Icon icon="mdi:trophy" width="14" style={{ marginRight: '4px' }} />Winner</span>}
          {isMostExpensive && <span className="most-expensive-badge"><Icon icon="mdi:currency-usd" width="14" style={{ marginRight: '4px' }} />Most Expensive</span>}
          {hasFullRequest && <span className="full-request-badge"><Icon icon="mdi:email-arrow-right" width="14" style={{ marginRight: '4px' }} />{messageCount} msgs sent to LLM</span>}
          {isExpandable && <span className="expand-hint"><Icon icon={isExpanded ? "mdi:chevron-down" : "mdi:chevron-right"} width="14" style={{ marginRight: '4px' }} />{isExpanded ? 'Click to collapse' : 'Click to expand'}</span>}
          {firstImageUrl && (
            <img
              src={firstImageUrl}
              alt="Message thumbnail"
              className="message-thumbnail"
              onClick={(e) => e.stopPropagation()}
            />
          )}
        </div>

        {msg.content && !isExpanded && (
          <div className="message-content-preview">
            {typeof msg.content === 'string'
              ? msg.content.substring(0, 200) + (msg.content.length > 200 ? '...' : '')
              : JSON.stringify(msg.content).substring(0, 200) + '...'}
          </div>
        )}

        {isExpanded && msg.content && (
          <div className="message-content-full" onClick={(e) => e.stopPropagation()}>
            <h4>Full Response Content:</h4>
            <div className="content-text">
              {typeof msg.content === 'string'
                ? msg.content
                : JSON.stringify(msg.content, null, 2)}
            </div>
          </div>
        )}

        {isExpanded && hasFullRequest && (
          <div className="full-request" onClick={(e) => e.stopPropagation()}>
            <h4>Actual Messages Sent to LLM ({messageCount} total):</h4>
            <div className="llm-messages">
              {msg.full_request.messages.map((llmMsg, i) => {
                // Detect if this message contains images
                let msgImageCount = 0;
                let textContent = '';

                if (Array.isArray(llmMsg.content)) {
                  // Multi-modal content (array of parts)
                  llmMsg.content.forEach(part => {
                    if (part.type === 'text') {
                      textContent += part.text || '';
                    } else if (part.type === 'image_url') {
                      msgImageCount++;
                      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
                      const sizeKb = url.startsWith('data:image') ? Math.round(url.split(',')[1]?.length / 1024) || 0 : 0;
                      textContent += `\n[IMAGE ${msgImageCount}: ~${sizeKb}kb base64]\n`;
                    }
                  });
                } else if (typeof llmMsg.content === 'string') {
                  // String content (might have embedded images)
                  textContent = llmMsg.content;
                  if (textContent.includes('data:image')) {
                    const matches = textContent.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
                    msgImageCount = matches.length;
                  }
                } else {
                  // Other (JSON, etc.)
                  textContent = JSON.stringify(llmMsg.content, null, 2);
                }

                return (
                  <div key={i} className={`llm-message ${llmMsg.role}`}>
                    <div className="llm-message-header">
                      <span className="llm-role">[{i}] {llmMsg.role}</span>
                      {msgImageCount > 0 && <span className="msg-image-badge"><Icon icon="mdi:image" width="14" style={{ marginRight: '2px' }} />{msgImageCount}</span>}
                      {llmMsg.tool_calls && <span className="has-tools"><Icon icon="mdi:wrench" width="14" style={{ marginRight: '4px' }} />Has tools</span>}
                      {llmMsg.tool_call_id && <span className="has-tool-id"><Icon icon="mdi:link" width="14" style={{ marginRight: '4px' }} />Tool ID</span>}
                    </div>
                    <div className="llm-message-content">
                      {textContent}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="full-request-meta">
              <div>Model: {msg.full_request.model}</div>
              <div>Total tokens: {msg.tokens_in.toLocaleString()}</div>
              {msg.cost > 0 && <div>Cost: ${msg.cost.toFixed(4)}</div>}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="message-flow-view">
      <div className="controls">
        {onBack && (
          <button onClick={onBack} className="back-button">
            <Icon icon="mdi:arrow-left" width="16" style={{ marginRight: '4px' }} />Back
          </button>
        )}

        {/* Running Sessions Dropdown */}
        <div className="running-sessions-wrapper" ref={dropdownRef}>
          <button
            className={`running-sessions-button ${runningSessions.length > 0 ? 'has-sessions' : ''}`}
            onClick={() => setShowSessionDropdown(!showSessionDropdown)}
            title={runningSessions.length > 0 ? `${runningSessions.length} active session(s)` : 'No active sessions'}
          >
            <span className="pulse-dot" style={{ display: runningSessions.some(s => s.status === 'running') ? 'inline-block' : 'none' }}></span>
            {runningSessions.length > 0 ? `${runningSessions.length} Active` : 'No Active'}
            <span className="dropdown-arrow"><Icon icon={showSessionDropdown ? "mdi:chevron-up" : "mdi:chevron-down"} width="16" /></span>
          </button>

          {showSessionDropdown && (
            <div className="running-sessions-dropdown">
              {runningSessions.length === 0 ? (
                <div className="no-sessions">No active sessions</div>
              ) : (
                runningSessions.map((session) => (
                  <button
                    key={session.session_id}
                    className={`session-item ${session.status === 'running' ? 'running' : 'completing'}`}
                    onClick={() => handleSessionSelect(session)}
                  >
                    <div className="session-item-header">
                      <span className={`status-indicator ${session.status}`}></span>
                      <span className="session-cascade">{session.cascade_id || 'unknown'}</span>
                      <span className="session-age">{formatAge(session.age_seconds)}</span>
                    </div>
                    <div className="session-id-preview">{session.session_id}</div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        <input
          type="text"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchMessages()}
          placeholder="Enter session ID (e.g., ui_run_426c918654f4)"
          className="session-input"
        />
        <button onClick={() => fetchMessages()} disabled={loading} className="fetch-button">
          {loading ? 'Loading...' : 'Fetch Messages'}
        </button>
      </div>

      {error && (
        <div className="error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Waiting for data state - session is running but no logs written yet */}
      {waitingForData && !data && (
        <div className="waiting-for-data">
          <div className="waiting-icon">
            <Icon icon="mdi:timer-sand" width="48" />
          </div>
          <h3>Waiting for data...</h3>
          <p>
            Session <code>{currentSessionIdRef.current || sessionId}</code> is running but hasn't written any logs yet.
          </p>
          <p className="waiting-hint">
            Auto-refreshing every 2 seconds. Data will appear once the cascade starts logging.
          </p>
          <div className="waiting-spinner">
            <Icon icon="mdi:loading" width="24" className="spin" />
          </div>
        </div>
      )}

      {data && (
        <div className="message-flow">
          <div className="flow-header">
            <div className="flow-header-top">
              <h2>Session: {data.session_id}</h2>
              {isCurrentSessionRunning() && (
                <div className="live-indicator">
                  <span className="live-dot"></span>
                  <span className="live-text">LIVE</span>
                  <button
                    className={`auto-refresh-toggle ${autoRefresh ? 'active' : ''}`}
                    onClick={() => setAutoRefresh(!autoRefresh)}
                    title={autoRefresh ? 'Auto-refresh ON (click to pause)' : 'Auto-refresh OFF (click to resume)'}
                  >
                    <Icon icon={autoRefresh ? "mdi:pause" : "mdi:play"} width="14" />
                  </button>
                </div>
              )}
            </div>
            <div className="stats">
              <span>Total Messages: {data.total_messages}</span>
              <span>Soundings: {data.soundings.length}</span>
              <span>Reforge Steps: {data.reforge_steps.length}</span>
            </div>
            {data.cost_summary && (
              <div className="cost-summary">
                <span className="cost-total">Total Cost: ${data.cost_summary.total_cost.toFixed(4)}</span>
                <span className="cost-detail">{data.cost_summary.total_tokens_in.toLocaleString()} tokens in</span>
                <span className="cost-detail">{data.cost_summary.total_tokens_out.toLocaleString()} tokens out</span>
                <span className="cost-detail">{data.cost_summary.messages_with_cost}/{data.total_messages} msgs tracked</span>
                {data.cost_summary.most_expensive && (
                  <button onClick={scrollToMostExpensive} className="most-expensive-button" title="Jump to most expensive message">
                    <Icon icon="mdi:currency-usd" width="14" style={{ marginRight: '4px' }} />Most Expensive: ${data.cost_summary.most_expensive.cost.toFixed(4)}
                    {data.cost_summary.most_expensive.tokens_in > 0 && ` (${data.cost_summary.most_expensive.tokens_in.toLocaleString()} tokens)`}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Legacy Reforge Steps - only show if not organized by phase */}
          {data.reforge_steps.length > 0 && (!data.reforge_by_phase || data.reforge_by_phase.length === 0) && (
            <div className="reforge-section">
              <h3><Icon icon="mdi:hammer" width="18" style={{ marginRight: '8px', color: '#c586c0' }} />Reforge Steps</h3>
              {data.reforge_steps.map((reforge) => (
                <div key={reforge.step} className="reforge-step">
                  <h4>Reforge Step {reforge.step}</h4>
                  <div className="reforge-messages">
                    {reforge.messages.map((msg, i) =>
                      renderMessage(msg, `reforge-${reforge.step}-${i}`, `R${reforge.step}-${i}`)
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Main Flow with Inline Soundings - Grouped by Phase */}
          {data.main_flow.length > 0 && (
            <div className="main-flow-section">
              <h3><Icon icon="mdi:format-list-bulleted-type" width="18" style={{ marginRight: '8px', color: '#60a5fa' }} />Canonical Timeline ({data.main_flow.length} messages)</h3>
              <p style={{color: '#858585', fontSize: '13px', marginTop: '-10px', marginBottom: '15px'}}>
                This is the actual history the LLM sees. Messages are grouped by phase. Soundings blocks show all parallel attempts before the winner continues.
              </p>

              <div className="main-messages">
                {(() => {
                  // Build a map of phase_name -> soundings block for quick lookup
                  const soundingsBlockMap = {};
                  if (data.soundings_by_phase && data.soundings_by_phase.length > 0) {
                    data.soundings_by_phase.forEach(block => {
                      soundingsBlockMap[block.phase_name] = block;
                    });
                  }

                  // Build a map of phase_name -> reforge block for quick lookup
                  const reforgeBlockMap = {};
                  if (data.reforge_by_phase && data.reforge_by_phase.length > 0) {
                    data.reforge_by_phase.forEach(block => {
                      reforgeBlockMap[block.phase_name] = block;
                    });
                  }

                  // Group messages by phase while maintaining order
                  const phaseGroups = [];
                  let currentPhase = null;
                  let currentMessages = [];

                  data.main_flow.forEach((msg, i) => {
                    const phaseName = msg.phase_name || '_unknown_';

                    if (phaseName !== currentPhase) {
                      // Save the previous phase group
                      if (currentPhase !== null && currentMessages.length > 0) {
                        phaseGroups.push({
                          phase_name: currentPhase,
                          messages: currentMessages,
                          hasSoundings: !!soundingsBlockMap[currentPhase],
                          hasReforge: !!reforgeBlockMap[currentPhase]
                        });
                      }
                      // Start new phase group
                      currentPhase = phaseName;
                      currentMessages = [];
                    }

                    currentMessages.push({ msg, index: i });
                  });

                  // Don't forget the last phase group
                  if (currentPhase !== null && currentMessages.length > 0) {
                    phaseGroups.push({
                      phase_name: currentPhase,
                      messages: currentMessages,
                      hasSoundings: !!soundingsBlockMap[currentPhase],
                      hasReforge: !!reforgeBlockMap[currentPhase]
                    });
                  }

                  // Also check for soundings that might not have messages in main_flow
                  if (data.soundings_by_phase && data.soundings_by_phase.length > 0) {
                    data.soundings_by_phase.forEach(block => {
                      const existingGroup = phaseGroups.find(g => g.phase_name === block.phase_name);
                      if (!existingGroup) {
                        // Find the right position based on first_timestamp
                        let insertIdx = phaseGroups.length;
                        for (let i = 0; i < phaseGroups.length; i++) {
                          const groupFirstTs = phaseGroups[i].messages[0]?.msg?.timestamp || 0;
                          if (block.first_timestamp < groupFirstTs) {
                            insertIdx = i;
                            break;
                          }
                        }
                        phaseGroups.splice(insertIdx, 0, {
                          phase_name: block.phase_name,
                          messages: [],
                          hasSoundings: true,
                          hasReforge: !!reforgeBlockMap[block.phase_name],
                          soundingsOnly: true
                        });
                      }
                    });
                  }

                  // Also check for reforge phases that might not have messages in main_flow
                  if (data.reforge_by_phase && data.reforge_by_phase.length > 0) {
                    data.reforge_by_phase.forEach(block => {
                      const existingGroup = phaseGroups.find(g => g.phase_name === block.phase_name);
                      if (!existingGroup) {
                        // Find the right position based on first_timestamp
                        let insertIdx = phaseGroups.length;
                        for (let i = 0; i < phaseGroups.length; i++) {
                          const groupFirstTs = phaseGroups[i].messages[0]?.msg?.timestamp || 0;
                          if (block.first_timestamp < groupFirstTs) {
                            insertIdx = i;
                            break;
                          }
                        }
                        phaseGroups.splice(insertIdx, 0, {
                          phase_name: block.phase_name,
                          messages: [],
                          hasSoundings: !!soundingsBlockMap[block.phase_name],
                          hasReforge: true,
                          reforgeOnly: true
                        });
                      }
                    });
                  }

                  // Track which phases we've shown soundings/reforge for
                  const shownSoundingsPhases = new Set();
                  const shownReforgePhases = new Set();

                  // Helper to render a soundings block
                  const renderSoundingsBlock = (block, phaseName) => (
                    <div key={`soundings-block-${phaseName}`} className="inline-soundings-block">
                      <div className="inline-soundings-header">
                        <span className="soundings-icon">🔱</span>
                        <span className="soundings-phase-name">Soundings</span>
                        <span className="soundings-count">{block.soundings.length} parallel attempts</span>
                        {block.winner_index !== null && (
                          <span className="soundings-winner">Winner: S{block.winner_index}</span>
                        )}
                      </div>
                      <div className="soundings-grid">
                        {block.soundings.map((sounding) => (
                          <div
                            key={`${phaseName}-${sounding.index}`}
                            className={`sounding-branch ${sounding.is_winner ? 'winner-branch' : ''}`}
                          >
                            <div className="sounding-header">
                              <h4>
                                S{sounding.index}
                                {sounding.is_winner && <Icon icon="mdi:trophy" width="14" style={{ marginLeft: '4px', color: '#fbbf24' }} />}
                              </h4>
                              <span className="sounding-msg-count">{sounding.messages.length} msgs</span>
                            </div>
                            <div className="sounding-messages">
                              {sounding.messages.map((sMsg, si) =>
                                renderMessage(sMsg, `sounding-${phaseName}-${sounding.index}-${si}`, `S${sounding.index}.${si}`)
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Evaluator Section */}
                      {block.evaluator && (
                        <div className="evaluator-section">
                          <div className="evaluator-header">
                            <span className="evaluator-icon"><Icon icon="mdi:scale-balance" width="16" /></span>
                            <span className="evaluator-label">Evaluation</span>
                            {block.evaluator.cost > 0 && (
                              <span className="evaluator-cost">${block.evaluator.cost.toFixed(4)}</span>
                            )}
                            {block.evaluator.model && (
                              <span className="evaluator-model">{block.evaluator.model}</span>
                            )}
                          </div>
                          <div className="evaluator-content">
                            {typeof block.evaluator.content === 'string'
                              ? block.evaluator.content
                              : block.evaluator.evaluation || JSON.stringify(block.evaluator.content)}
                          </div>
                          {block.winner_index !== null && (
                            <div className="evaluator-result">
                              <span className="winner-badge"><Icon icon="mdi:trophy" width="14" style={{ marginRight: '4px' }} />Selected: Sounding {block.winner_index}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );

                  // Helper to render a reforge block
                  const renderReforgeBlock = (block, phaseName) => (
                    <div key={`reforge-block-${phaseName}`} className="inline-reforge-block">
                      <div className="inline-reforge-header">
                        <span className="reforge-icon"><Icon icon="mdi:hammer" width="16" /></span>
                        <span className="reforge-phase-name">Reforge</span>
                        <span className="reforge-count">{block.reforge_steps.length} refinement step{block.reforge_steps.length !== 1 ? 's' : ''}</span>
                        {block.winner_step !== null && (
                          <span className="reforge-winner">Winner: R{block.winner_step}</span>
                        )}
                      </div>
                      <div className="reforge-grid">
                        {block.reforge_steps.map((reforge) => (
                          <div
                            key={`${phaseName}-reforge-${reforge.step}`}
                            className={`reforge-branch ${reforge.is_winner ? 'winner-branch' : ''}`}
                          >
                            <div className="reforge-header">
                              <h4>
                                R{reforge.step}
                                {reforge.is_winner && <Icon icon="mdi:trophy" width="14" style={{ marginLeft: '4px', color: '#fbbf24' }} />}
                              </h4>
                              <span className="reforge-msg-count">{reforge.messages.length} msgs</span>
                            </div>
                            <div className="reforge-messages">
                              {reforge.messages.map((rMsg, ri) =>
                                renderMessage(rMsg, `reforge-${phaseName}-${reforge.step}-${ri}`, `R${reforge.step}.${ri}`)
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );

                  // Render phase groups
                  return phaseGroups.map((group, groupIdx) => {
                    const phaseName = group.phase_name;
                    const soundingsBlock = soundingsBlockMap[phaseName];
                    const reforgeBlock = reforgeBlockMap[phaseName];
                    const shouldShowSoundings = soundingsBlock && !shownSoundingsPhases.has(phaseName);
                    const shouldShowReforge = reforgeBlock && !shownReforgePhases.has(phaseName);

                    if (shouldShowSoundings) {
                      shownSoundingsPhases.add(phaseName);
                    }
                    if (shouldShowReforge) {
                      shownReforgePhases.add(phaseName);
                    }

                    // Calculate phase stats (include main_flow messages + soundings + evaluator + reforge)
                    let phaseCost = group.messages.reduce((sum, { msg }) => sum + (msg.cost || 0), 0);
                    let phaseTokens = group.messages.reduce((sum, { msg }) => sum + (msg.tokens_in || 0), 0);

                    // Add soundings costs if this phase has them
                    if (soundingsBlock) {
                      soundingsBlock.soundings.forEach(sounding => {
                        sounding.messages.forEach(msg => {
                          phaseCost += msg.cost || 0;
                          phaseTokens += msg.tokens_in || 0;
                        });
                      });
                      // Add evaluator cost
                      if (soundingsBlock.evaluator) {
                        phaseCost += soundingsBlock.evaluator.cost || 0;
                        phaseTokens += soundingsBlock.evaluator.tokens_in || 0;
                      }
                    }

                    // Add reforge costs if this phase has them
                    if (reforgeBlock) {
                      reforgeBlock.reforge_steps.forEach(reforge => {
                        reforge.messages.forEach(msg => {
                          phaseCost += msg.cost || 0;
                          phaseTokens += msg.tokens_in || 0;
                        });
                      });
                    }

                    return (
                      <div key={`phase-group-${phaseName}-${groupIdx}`} className="phase-group">
                        <div className="phase-group-header">
                          <span className="phase-group-icon"><Icon icon="mdi:map-marker" width="16" /></span>
                          <span className="phase-group-name">{phaseName}</span>
                          <span className="phase-group-stats">
                            {group.messages.length} msg{group.messages.length !== 1 ? 's' : ''}
                            {phaseCost > 0 && <span className="phase-cost">${phaseCost.toFixed(4)}</span>}
                            {phaseTokens > 0 && <span className="phase-tokens">{phaseTokens.toLocaleString()} tokens</span>}
                          </span>
                          {group.hasSoundings && <span className="phase-soundings-badge">🔱 Soundings</span>}
                          {group.hasReforge && <span className="phase-reforge-badge"><Icon icon="mdi:hammer" width="14" style={{ marginRight: '4px' }} />Reforge</span>}
                        </div>
                        <div className="phase-group-content">
                          {/* Soundings block (if any) */}
                          {shouldShowSoundings && renderSoundingsBlock(soundingsBlock, phaseName)}

                          {/* Reforge block (if any) */}
                          {shouldShowReforge && renderReforgeBlock(reforgeBlock, phaseName)}

                          {/* Regular messages (skip sounding/reforge messages as they're in their blocks) */}
                          {group.messages
                            .filter(({ msg }) => {
                              // Skip messages that are part of a sounding (already shown in soundings block)
                              if (soundingsBlock && msg.sounding_index !== null && msg.sounding_index !== undefined) {
                                return false;
                              }
                              // Skip messages that are part of a reforge (already shown in reforge block)
                              if (reforgeBlock && msg.reforge_step !== null && msg.reforge_step !== undefined) {
                                return false;
                              }
                              return true;
                            })
                            .map(({ msg, index }) =>
                              renderMessage(msg, `main-${index}`, `M${index}`)
                            )}
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MessageFlowView;
