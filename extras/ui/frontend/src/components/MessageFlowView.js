import React, { useState } from 'react';
import axios from 'axios';
import './MessageFlowView.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5001';

function MessageFlowView({ onBack }) {
  const [sessionId, setSessionId] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState(new Set());
  const [highlightedMessage, setHighlightedMessage] = useState(null);

  const fetchMessages = async () => {
    if (!sessionId.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(`${API_BASE_URL}/api/message-flow/${sessionId}`);
      setData(response.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
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
        className={`message ${msg.role} ${msg.is_winner ? 'winner' : ''} ${isFollowUp ? 'follow-up' : ''} ${isHighlighted ? 'highlighted' : ''} ${isMostExpensive ? 'most-expensive' : ''}`}
        onClick={() => isExpandable && toggleMessage(index)}
        style={{ cursor: isExpandable ? 'pointer' : 'default' }}
      >
        <div className="message-header">
          <span className="message-label">{label}</span>
          {fromSounding && <span className="source-badge" style={{background: '#4ec9b0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px'}}>S{msg.sounding_index}</span>}
          {fromReforge && <span className="source-badge" style={{background: '#c586c0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px'}}>R{msg.reforge_step}</span>}
          <span className="message-role">{msg.role}</span>
          <span className="message-node-type">{msg.node_type}</span>
          {msg.turn_number !== null && <span className="turn">Turn {msg.turn_number}</span>}
          {msg.tokens_in > 0 && <span className="tokens">{msg.tokens_in.toLocaleString()} tokens in</span>}
          {msg.cost > 0 && <span className="cost-badge">${msg.cost.toFixed(4)}</span>}
          {imageCount > 0 && (
            <span className="image-badge" title={`Total base64 size: ${(totalBase64Size / 1024).toFixed(1)}kb (~${Math.round(totalBase64Size / 4)} tokens)`}>
              🖼️ {imageCount} image{imageCount > 1 ? 's' : ''}
            </span>
          )}
          {msg.is_winner && <span className="winner-badge">🏆 Winner</span>}
          {isMostExpensive && <span className="most-expensive-badge">💰 Most Expensive</span>}
          {hasFullRequest && <span className="full-request-badge">📨 {messageCount} msgs sent to LLM</span>}
          {isExpandable && <span className="expand-hint">{isExpanded ? '▼ Click to collapse' : '▶ Click to expand'}</span>}
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
                      {msgImageCount > 0 && <span className="msg-image-badge">🖼️ {msgImageCount}</span>}
                      {llmMsg.tool_calls && <span className="has-tools">🔧 Has tools</span>}
                      {llmMsg.tool_call_id && <span className="has-tool-id">🔗 Tool ID</span>}
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
            ← Back
          </button>
        )}
        <input
          type="text"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          placeholder="Enter session ID (e.g., ui_run_426c918654f4)"
          className="session-input"
        />
        <button onClick={fetchMessages} disabled={loading} className="fetch-button">
          {loading ? 'Loading...' : 'Fetch Messages'}
        </button>
      </div>

      {error && (
        <div className="error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {data && (
        <div className="message-flow">
          <div className="flow-header">
            <h2>Session: {data.session_id}</h2>
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
                    💰 Most Expensive: ${data.cost_summary.most_expensive.cost.toFixed(4)}
                    {data.cost_summary.most_expensive.tokens_in > 0 && ` (${data.cost_summary.most_expensive.tokens_in.toLocaleString()} tokens)`}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Soundings - Show as parallel branches */}
          {data.soundings.length > 0 && (
            <div className="soundings-section">
              <h3>🔱 Soundings ({data.soundings.length} parallel attempts)</h3>
              <div className="soundings-grid">
                {data.soundings.map((sounding) => (
                  <div
                    key={sounding.index}
                    className={`sounding-branch ${sounding.is_winner ? 'winner-branch' : ''}`}
                  >
                    <div className="sounding-header">
                      <h4>
                        Sounding {sounding.index}
                        {sounding.is_winner && ' 🏆'}
                      </h4>
                      <span className="sounding-msg-count">{sounding.messages.length} messages</span>
                    </div>
                    <div className="sounding-messages">
                      {sounding.messages.map((msg, i) =>
                        renderMessage(msg, `sounding-${sounding.index}-${i}`, `S${sounding.index}-${i}`)
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reforge Steps */}
          {data.reforge_steps.length > 0 && (
            <div className="reforge-section">
              <h3>🔨 Reforge Steps</h3>
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

          {/* Main Flow */}
          {data.main_flow.length > 0 && (
            <div className="main-flow-section">
              <h3>📜 Canonical Timeline ({data.main_flow.length} messages)</h3>
              <p style={{color: '#858585', fontSize: '13px', marginTop: '-10px', marginBottom: '15px'}}>
                This is the actual history the LLM sees: pre-soundings setup → winner branch → post-soundings continuation
              </p>
              <div className="main-messages">
                {data.main_flow.map((msg, i) =>
                  renderMessage(msg, `main-${i}`, `M${i}`)
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MessageFlowView;
