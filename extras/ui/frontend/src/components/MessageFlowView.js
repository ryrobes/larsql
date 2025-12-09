import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { Icon } from '@iconify/react';
import VideoSpinner from './VideoSpinner';
import AudioGallery from './AudioGallery';
import './MessageFlowView.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5001';

/**
 * Extract all images from a message, tracking direction (input vs output)
 * Returns: { inputs: [{url, size, index}], outputs: [{url, size, index}], total: number }
 */
function extractImagesFromMessage(msg) {
  const images = {
    inputs: [],   // Images sent TO the LLM (in full_request)
    outputs: [],  // Images FROM the LLM or tools (in content/response)
    total: 0
  };

  let inputIndex = 0;
  let outputIndex = 0;

  // 1. Extract INPUT images from full_request.messages (what was sent to LLM)
  if (msg.full_request?.messages) {
    msg.full_request.messages.forEach((m, msgIdx) => {
      if (Array.isArray(m.content)) {
        m.content.forEach((part, partIdx) => {
          if (part.type === 'image_url') {
            const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
            if (url) {
              const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
              images.inputs.push({
                url,
                sizeKb,
                index: inputIndex++,
                sourceMsg: msgIdx,
                role: m.role || 'unknown'
              });
            }
          }
        });
      } else if (typeof m.content === 'string' && m.content.includes('data:image')) {
        // Embedded base64 in string content
        const matches = m.content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
        matches.forEach(match => {
          const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
          images.inputs.push({
            url: match,
            sizeKb,
            index: inputIndex++,
            sourceMsg: msgIdx,
            role: m.role || 'unknown'
          });
        });
      }
    });
  }

  // 2. Extract OUTPUT images from content (tool results, assistant responses)
  const content = msg.content;
  if (content) {
    // Content might be a string with embedded images
    if (typeof content === 'string' && content.includes('data:image')) {
      const matches = content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
      matches.forEach(match => {
        const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
        images.outputs.push({
          url: match,
          sizeKb,
          index: outputIndex++,
          source: 'content'
        });
      });
    }
    // Content might be an object with images array (tool result protocol)
    if (typeof content === 'object') {
      // Check for images array
      if (Array.isArray(content.images)) {
        content.images.forEach(imgPath => {
          // These are typically file paths, not base64
          images.outputs.push({
            url: imgPath,
            sizeKb: 0,
            index: outputIndex++,
            source: 'tool_result',
            isPath: true
          });
        });
      }
      // Check for nested content string with images
      if (typeof content.content === 'string' && content.content.includes('data:image')) {
        const matches = content.content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
        matches.forEach(match => {
          const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
          images.outputs.push({
            url: match,
            sizeKb,
            index: outputIndex++,
            source: 'content'
          });
        });
      }
    }
    // Content might be an array (multimodal response)
    if (Array.isArray(content)) {
      content.forEach((part, idx) => {
        if (part.type === 'image_url') {
          const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
          if (url) {
            const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
            images.outputs.push({
              url,
              sizeKb,
              index: outputIndex++,
              source: 'response'
            });
          }
        }
      });
    }
  }

  images.total = images.inputs.length + images.outputs.length;
  return images;
}

/**
 * MessageImages - Inline gallery showing all images in a message with direction
 */
function MessageImages({ images, onImageClick, compact = false }) {
  if (images.total === 0) return null;

  const renderImage = (img, direction) => (
    <div
      key={`${direction}-${img.index}`}
      className={`msg-image-item ${compact ? 'compact' : ''}`}
      onClick={(e) => {
        e.stopPropagation();
        if (img.url.startsWith('data:image') || img.url.startsWith('http')) {
          onImageClick({ url: img.url, direction, index: img.index });
        }
      }}
    >
      {img.url.startsWith('data:image') ? (
        <img src={img.url} alt={`${direction} ${img.index + 1}`} className="msg-image-thumb" />
      ) : img.url.startsWith('http') ? (
        <img src={img.url} alt={`${direction} ${img.index + 1}`} className="msg-image-thumb" />
      ) : (
        <div className="msg-image-path" title={img.url}>
          <Icon icon="mdi:file-image" width="24" />
          <span>{img.url.split('/').pop()}</span>
        </div>
      )}
      <div className={`msg-image-badge ${direction}`}>
        <Icon icon={direction === 'in' ? 'mdi:arrow-right' : 'mdi:arrow-left'} width="10" />
        {direction.toUpperCase()}
      </div>
      {img.sizeKb > 0 && <span className="msg-image-size">{img.sizeKb}kb</span>}
    </div>
  );

  if (compact) {
    // Compact mode: just show first image with count
    const firstImg = images.inputs[0] || images.outputs[0];
    if (!firstImg) return null;
    return (
      <div className="msg-images-compact">
        {renderImage(firstImg, images.inputs[0] ? 'in' : 'out')}
        {images.total > 1 && <span className="msg-images-more">+{images.total - 1}</span>}
      </div>
    );
  }

  return (
    <div className="msg-images-gallery">
      {images.inputs.length > 0 && (
        <div className="msg-images-group">
          <div className="msg-images-group-header">
            <Icon icon="mdi:arrow-right-bold" width="14" />
            <span>Input ({images.inputs.length})</span>
          </div>
          <div className="msg-images-row">
            {images.inputs.map(img => renderImage(img, 'in'))}
          </div>
        </div>
      )}
      {images.outputs.length > 0 && (
        <div className="msg-images-group">
          <div className="msg-images-group-header">
            <Icon icon="mdi:arrow-left-bold" width="14" />
            <span>Output ({images.outputs.length})</span>
          </div>
          <div className="msg-images-row">
            {images.outputs.map(img => renderImage(img, 'out'))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * EvaluatorSection - Shows detailed evaluator input observability
 * Displays what exactly the evaluator LLM received to make its determination
 */
function EvaluatorSection({ evaluator, winnerIndex }) {
  const [showInput, setShowInput] = useState(false);
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [showFullPrompt, setShowFullPrompt] = useState(false);

  const inputSummary = evaluator.evaluator_input_summary;
  const evalMode = inputSummary?.evaluation_mode || 'quality_only';

  // Format evaluation mode for display
  const evalModeLabel = {
    'quality_only': 'Quality Only',
    'cost_aware': 'Cost-Aware',
    'pareto': 'Pareto Frontier'
  }[evalMode] || evalMode;

  return (
    <div className="evaluator-section">
      {/* Header with basic info */}
      <div className="evaluator-header">
        <span className="evaluator-icon"><Icon icon="mdi:scale-balance" width="16" /></span>
        <span className="evaluator-label">Evaluation</span>
        {inputSummary && (
          <span className={`eval-mode-badge eval-mode-${evalMode}`}>{evalModeLabel}</span>
        )}
        {inputSummary?.is_multimodal && (
          <span className="eval-multimodal-badge">
            <Icon icon="mdi:image-multiple" width="14" style={{ marginRight: '4px' }} />
            {inputSummary.total_images} images
          </span>
        )}
        {evaluator.cost > 0 && (
          <span className="evaluator-cost">${evaluator.cost.toFixed(4)}</span>
        )}
        {evaluator.model && (
          <span className="evaluator-model">{evaluator.model}</span>
        )}
      </div>

      {/* Evaluator output */}
      <div className="evaluator-content">
        {typeof evaluator.content === 'string'
          ? evaluator.content
          : evaluator.evaluation || JSON.stringify(evaluator.content)}
      </div>

      {/* Winner result */}
      {winnerIndex !== null && (
        <div className="evaluator-result">
          <span className="winner-badge">
            <Icon icon="mdi:trophy" width="14" style={{ marginRight: '4px' }} />
            Selected: Sounding {winnerIndex}
          </span>
        </div>
      )}

      {/* Toggle for evaluator input details */}
      {(inputSummary || evaluator.evaluator_prompt) && (
        <button
          className="eval-input-toggle"
          onClick={() => setShowInput(!showInput)}
        >
          <Icon icon={showInput ? "mdi:chevron-up" : "mdi:chevron-down"} width="16" />
          {showInput ? 'Hide' : 'Show'} Evaluator Input Details
        </button>
      )}

      {/* Expanded evaluator input observability */}
      {showInput && (
        <div className="eval-input-details">
          {/* Summary stats */}
          {inputSummary && (
            <div className="eval-input-stats">
              <div className="eval-stat">
                <span className="eval-stat-label">Attempts Shown</span>
                <span className="eval-stat-value">{inputSummary.total_attempts_shown}</span>
              </div>
              <div className="eval-stat">
                <span className="eval-stat-label">Total Run</span>
                <span className="eval-stat-value">{inputSummary.total_soundings_run}</span>
              </div>
              {inputSummary.filtered_count > 0 && (
                <div className="eval-stat eval-stat-warning">
                  <span className="eval-stat-label">Filtered Out</span>
                  <span className="eval-stat-value">{inputSummary.filtered_count}</span>
                </div>
              )}
              {inputSummary.is_multimodal && (
                <div className="eval-stat eval-stat-images">
                  <span className="eval-stat-label">Total Images</span>
                  <span className="eval-stat-value">{inputSummary.total_images}</span>
                </div>
              )}
            </div>
          )}

          {/* Cost-aware info */}
          {evaluator.cost_aware && (
            <div className="eval-cost-aware-info">
              <h5><Icon icon="mdi:currency-usd" width="14" /> Cost-Aware Evaluation</h5>
              <div className="eval-weights">
                <span>Quality Weight: {(evaluator.quality_weight * 100).toFixed(0)}%</span>
                <span>Cost Weight: {(evaluator.cost_weight * 100).toFixed(0)}%</span>
              </div>
            </div>
          )}

          {/* Pareto info */}
          {evaluator.pareto_enabled && (
            <div className="eval-pareto-info">
              <h5><Icon icon="mdi:chart-scatter-plot" width="14" /> Pareto Frontier</h5>
              <div className="eval-pareto-details">
                <span>Policy: {evaluator.pareto_policy}</span>
                <span>Frontier Size: {evaluator.frontier_size}</span>
                {evaluator.winner_quality && <span>Winner Quality: {evaluator.winner_quality.toFixed(1)}</span>}
                {evaluator.winner_cost && <span>Winner Cost: ${evaluator.winner_cost.toFixed(6)}</span>}
              </div>
            </div>
          )}

          {/* Per-attempt breakdown */}
          {inputSummary?.attempts && inputSummary.attempts.length > 0 && (
            <div className="eval-attempts-breakdown">
              <h5><Icon icon="mdi:format-list-numbered" width="14" /> Per-Attempt Breakdown</h5>
              <table className="eval-attempts-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Original S#</th>
                    <th>Model</th>
                    <th>Images</th>
                    <th>Text Len</th>
                    {evaluator.sounding_costs && <th>Cost</th>}
                    {evaluator.quality_scores && <th>Quality</th>}
                    <th>Mutation</th>
                    <th>Valid</th>
                  </tr>
                </thead>
                <tbody>
                  {inputSummary.attempts.map((attempt, idx) => (
                    <tr key={idx} className={attempt.original_sounding_index === winnerIndex ? 'winner-row' : ''}>
                      <td>{attempt.attempt_number}</td>
                      <td>S{attempt.original_sounding_index}</td>
                      <td className="model-cell">{attempt.model ? attempt.model.split('/').pop() : '-'}</td>
                      <td>
                        {attempt.has_images ? (
                          <span className="has-images">
                            <Icon icon="mdi:image" width="12" /> {attempt.image_count}
                          </span>
                        ) : '-'}
                      </td>
                      <td>{attempt.result_length.toLocaleString()}</td>
                      {evaluator.sounding_costs && (
                        <td>${evaluator.sounding_costs[idx]?.toFixed(6) || '-'}</td>
                      )}
                      {evaluator.quality_scores && (
                        <td>{evaluator.quality_scores[idx]?.toFixed(1) || '-'}</td>
                      )}
                      <td className="mutation-cell">
                        {attempt.mutation_applied ? (
                          <span className="has-mutation" title={attempt.mutation_applied}>
                            <Icon icon="mdi:dna" width="12" /> Yes
                          </span>
                        ) : '-'}
                      </td>
                      <td>
                        {attempt.validation ? (
                          attempt.validation.valid ? (
                            <Icon icon="mdi:check-circle" width="14" style={{ color: '#34d399' }} />
                          ) : (
                            <span title={attempt.validation.reason}>
                              <Icon icon="mdi:close-circle" width="14" style={{ color: '#f87171' }} />
                            </span>
                          )
                        ) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* System prompt (collapsible) */}
          {evaluator.evaluator_system_prompt && (
            <div className="eval-prompt-section">
              <button
                className="eval-prompt-toggle"
                onClick={() => setShowSystemPrompt(!showSystemPrompt)}
              >
                <Icon icon={showSystemPrompt ? "mdi:chevron-up" : "mdi:chevron-down"} width="14" />
                System Prompt
              </button>
              {showSystemPrompt && (
                <pre className="eval-prompt-content">{evaluator.evaluator_system_prompt}</pre>
              )}
            </div>
          )}

          {/* Full evaluation prompt (collapsible) */}
          {evaluator.evaluator_prompt && (
            <div className="eval-prompt-section">
              <button
                className="eval-prompt-toggle"
                onClick={() => setShowFullPrompt(!showFullPrompt)}
              >
                <Icon icon={showFullPrompt ? "mdi:chevron-up" : "mdi:chevron-down"} width="14" />
                Full Evaluation Prompt ({evaluator.evaluator_prompt.length.toLocaleString()} chars)
              </button>
              {showFullPrompt && (
                <pre className="eval-prompt-content eval-prompt-full">{evaluator.evaluator_prompt}</pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessageFlowView({ onBack, initialSessionId, onSessionChange, hideControls = false, scrollToIndex = null }) {
  const [sessionId, setSessionId] = useState(initialSessionId || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState(new Set());
  const [highlightedMessage, setHighlightedMessage] = useState(null);
  const [runningSessions, setRunningSessions] = useState([]);
  const [recentSessions, setRecentSessions] = useState([]); // Combined recent + running sessions for button row
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [waitingForData, setWaitingForData] = useState(false); // True when session is running but no data yet
  const [selectedImage, setSelectedImage] = useState(null); // For image modal
  const currentSessionIdRef = useRef(initialSessionId || null);

  // Scroll to message when scrollToIndex changes (triggered by chart click)
  useEffect(() => {
    if (scrollToIndex !== null && scrollToIndex !== undefined) {
      const messageEl = document.getElementById(`message-${scrollToIndex}`);
      if (messageEl) {
        messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Temporarily highlight the message
        setHighlightedMessage(scrollToIndex);
        setTimeout(() => setHighlightedMessage(null), 2000);
      }
    }
  }, [scrollToIndex]);

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
      // Notify parent of session change for URL update
      if (onSessionChange && sid) {
        onSessionChange(sid);
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
        // Notify parent of session change for URL update
        if (onSessionChange && sid) {
          onSessionChange(sid);
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
      const sessions = response.data.sessions || [];
      setRunningSessions(sessions);

      // Update recent sessions list (combine running sessions with history)
      setRecentSessions(prev => {
        // Start with running sessions
        const sessionMap = new Map();
        sessions.forEach(s => sessionMap.set(s.session_id, { ...s, isActive: true }));

        // Add previous sessions that aren't in running list
        prev.forEach(s => {
          if (!sessionMap.has(s.session_id)) {
            sessionMap.set(s.session_id, { ...s, isActive: false });
          }
        });

        // Convert to array and sort by start_time (most recent first)
        const combined = Array.from(sessionMap.values());
        combined.sort((a, b) => (b.start_time || 0) - (a.start_time || 0));

        // Keep only last 10
        return combined.slice(0, 10);
      });
    } catch (err) {
      console.error('Failed to fetch running sessions:', err);
    }
  }, []);

  // Load initial session from URL on mount
  useEffect(() => {
    if (initialSessionId) {
      fetchMessages(initialSessionId);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch running sessions on mount and every 5 seconds
  useEffect(() => {
    fetchRunningSessions();
    const interval = setInterval(fetchRunningSessions, 5000);
    return () => clearInterval(interval);
  }, [fetchRunningSessions]);

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
    fetchMessages(session.session_id);
    // Add to recent sessions if not already there
    setRecentSessions(prev => {
      const exists = prev.some(s => s.session_id === session.session_id);
      if (exists) return prev;
      const updated = [{ ...session, isActive: session.status === 'running' }, ...prev];
      return updated.slice(0, 10);
    });
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
    const hasContent = msg.content && (typeof msg.content === 'string' ? msg.content.length > 200 : true);
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

    // Extract all images with direction tracking
    const msgImages = extractImagesFromMessage(msg);
    const hasImages = msgImages.total > 0;
    const totalBase64Size = [...msgImages.inputs, ...msgImages.outputs]
      .reduce((sum, img) => sum + (img.sizeKb || 0), 0);

    // Get first image for thumbnail
    const firstImage = msgImages.inputs[0] || msgImages.outputs[0];
    const firstImageUrl = firstImage?.url;

    return (
      <div
        key={index}
        id={`message-${globalIndex}`}
        className={`message ${msg.role} ${msg.is_winner ? 'winner' : ''} ${isFollowUp ? 'follow-up' : ''} ${isHighlighted ? 'highlighted' : ''} ${isMostExpensive ? 'most-expensive' : ''} ${isInternal ? 'is-internal' : ''} ${hasImages ? 'has-images' : ''}`}
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
          {/* Image badges with direction */}
          {msgImages.inputs.length > 0 && (
            <span className="image-badge image-in" title={`${msgImages.inputs.length} image(s) sent TO the LLM`}>
              <Icon icon="mdi:arrow-right" width="12" />
              <Icon icon="mdi:image" width="14" />
              {msgImages.inputs.length}
            </span>
          )}
          {msgImages.outputs.length > 0 && (
            <span className="image-badge image-out" title={`${msgImages.outputs.length} image(s) FROM tool/response`}>
              <Icon icon="mdi:arrow-left" width="12" />
              <Icon icon="mdi:image" width="14" />
              {msgImages.outputs.length}
            </span>
          )}
          {msg.is_winner && <span className="winner-badge"><Icon icon="mdi:trophy" width="14" style={{ marginRight: '4px' }} />Winner</span>}
          {isMostExpensive && <span className="most-expensive-badge"><Icon icon="mdi:currency-usd" width="14" style={{ marginRight: '4px' }} />Most Expensive</span>}
          {hasFullRequest && <span className="full-request-badge"><Icon icon="mdi:email-arrow-right" width="14" style={{ marginRight: '4px' }} />{messageCount} msgs sent to LLM</span>}
          {isExpandable && <span className="expand-hint"><Icon icon={isExpanded ? "mdi:chevron-down" : "mdi:chevron-right"} width="14" style={{ marginRight: '4px' }} />{isExpanded ? 'Click to collapse' : 'Click to expand'}</span>}
          {/* Compact image preview in header */}
          {firstImageUrl && firstImageUrl.startsWith('data:image') && (
            <img
              src={firstImageUrl}
              alt="Message thumbnail"
              className="message-thumbnail"
              onClick={(e) => {
                e.stopPropagation();
                setSelectedImage({ url: firstImageUrl, phase: msg.phase_name, index: globalIndex });
              }}
              title="Click to enlarge"
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

        {/* Inline image gallery when NOT expanded (quick preview) */}
        {!isExpanded && hasImages && (
          <MessageImages
            images={msgImages}
            onImageClick={(img) => setSelectedImage({ ...img, phase: msg.phase_name, messageIndex: globalIndex })}
            compact={true}
          />
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

        {/* Full image gallery when expanded */}
        {isExpanded && hasImages && (
          <div className="message-images-expanded" onClick={(e) => e.stopPropagation()}>
            <h4>
              <Icon icon="mdi:image-multiple" width="18" style={{ marginRight: '8px' }} />
              Images ({msgImages.total})
              {totalBase64Size > 0 && <span className="images-size-note">~{totalBase64Size}kb total</span>}
            </h4>
            <MessageImages
              images={msgImages}
              onImageClick={(img) => setSelectedImage({ ...img, phase: msg.phase_name, messageIndex: globalIndex })}
              compact={false}
            />
          </div>
        )}

        {isExpanded && hasFullRequest && (
          <div className="full-request" onClick={(e) => e.stopPropagation()}>
            <h4>Actual Messages Sent to LLM ({messageCount} total):</h4>
            <div className="llm-messages">
              {msg.full_request.messages.map((llmMsg, i) => {
                // Extract images from this specific LLM message
                const llmMsgImages = [];
                let textContent = '';

                if (Array.isArray(llmMsg.content)) {
                  // Multi-modal content (array of parts)
                  llmMsg.content.forEach((part, partIdx) => {
                    if (part.type === 'text') {
                      textContent += part.text || '';
                    } else if (part.type === 'image_url') {
                      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
                      const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
                      llmMsgImages.push({ url, sizeKb, index: partIdx });
                      textContent += `\n[📷 IMAGE ${llmMsgImages.length}]\n`;
                    }
                  });
                } else if (typeof llmMsg.content === 'string') {
                  textContent = llmMsg.content;
                  // Don't extract embedded images in text for inline rendering (too complex)
                } else {
                  textContent = JSON.stringify(llmMsg.content, null, 2);
                }

                return (
                  <div key={i} className={`llm-message ${llmMsg.role}`}>
                    <div className="llm-message-header">
                      <span className="llm-role">[{i}] {llmMsg.role}</span>
                      {llmMsgImages.length > 0 && (
                        <span className="msg-image-badge">
                          <Icon icon="mdi:image" width="14" style={{ marginRight: '2px' }} />
                          {llmMsgImages.length}
                        </span>
                      )}
                      {llmMsg.tool_calls && <span className="has-tools"><Icon icon="mdi:wrench" width="14" style={{ marginRight: '4px' }} />Has tools</span>}
                      {llmMsg.tool_call_id && <span className="has-tool-id"><Icon icon="mdi:link" width="14" style={{ marginRight: '4px' }} />Tool ID</span>}
                    </div>
                    <div className="llm-message-content">
                      {textContent}
                    </div>
                    {/* Render actual images inline */}
                    {llmMsgImages.length > 0 && (
                      <div className="llm-message-images">
                        {llmMsgImages.map((img, imgIdx) => (
                          <div key={imgIdx} className="llm-inline-image">
                            {img.url.startsWith('data:image') ? (
                              <img
                                src={img.url}
                                alt={`LLM msg ${i} image ${imgIdx + 1}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedImage({ url: img.url, phase: msg.phase_name, index: globalIndex, direction: 'in' });
                                }}
                              />
                            ) : (
                              <span className="llm-image-url">{img.url}</span>
                            )}
                            <span className="llm-image-label">
                              <Icon icon="mdi:arrow-right" width="10" /> IN #{imgIdx + 1}
                              {img.sizeKb > 0 && <span className="llm-image-size">{img.sizeKb}kb</span>}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
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
    <div className={`message-flow-view ${hideControls ? 'embedded' : ''}`}>
      {!hideControls && (
        <div className="controls">
          {onBack && (
            <button onClick={onBack} className="back-button" title="Back to Cascades">
              <Icon icon="mdi:arrow-left" width="18" />
            </button>
          )}

          {/* Recent Sessions Row */}
          <div className="recent-sessions-row">
            {recentSessions.length === 0 ? (
              <span className="no-recent-sessions">No recent sessions</span>
            ) : (
              recentSessions.map((session) => {
                const isSelected = currentSessionIdRef.current === session.session_id;
                const isRunning = session.isActive || session.status === 'running';
                return (
                  <button
                    key={session.session_id}
                    className={`session-button ${isSelected ? 'selected' : ''} ${isRunning ? 'running' : ''}`}
                    onClick={() => handleSessionSelect(session)}
                    title={`${session.cascade_id || 'unknown'}\n${session.session_id}`}
                  >
                    {isRunning && <span className="session-pulse"></span>}
                    <span className="session-button-cascade">{session.cascade_id || 'unknown'}</span>
                    <span className="session-button-id">{session.session_id.slice(-8)}</span>
                  </button>
                );
              })
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
      )}

      {error && (
        <div className="error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Waiting for data state - session is running but no logs written yet */}
      {waitingForData && !data && (
        <div className="waiting-for-data">
          <VideoSpinner size={100} opacity={0.8} />
          <h3>Waiting for data...</h3>
          <p>
            Session <code>{currentSessionIdRef.current || sessionId}</code> is running but hasn't written any logs yet.
          </p>
          <p className="waiting-hint">
            Auto-refreshing every 2 seconds. Data will appear once the cascade starts logging.
          </p>
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
                        <EvaluatorSection evaluator={block.evaluator} winnerIndex={block.winner_index} />
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

                    // For "_unknown_" phase messages (system status messages without a phase),
                    // render them inline without a phase wrapper container
                    if (phaseName === '_unknown_') {
                      return (
                        <div key={`phaseless-${groupIdx}`} className="phaseless-messages">
                          {group.messages.map(({ msg, index }) =>
                            renderMessage(msg, `main-${index}`, `M${index}`)
                          )}
                        </div>
                      );
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

                          {/* Regular messages (skip sounding/reforge messages as they're shown in their blocks) */}
                          {group.messages
                            .filter(({ msg }) => {
                              // Skip messages that are part of a sounding (shown in soundings block)
                              if (soundingsBlock && msg.sounding_index !== null && msg.sounding_index !== undefined) {
                                return false;
                              }
                              // Skip messages that are part of a reforge (shown in reforge block)
                              if (reforgeBlock && msg.reforge_step !== null && msg.reforge_step !== undefined) {
                                return false;
                              }
                              return true;
                            })
                            .map(({ msg, index }) =>
                              renderMessage(msg, `main-${index}`, `M${index}`)
                            )}

                          {/* Audio files for this phase */}
                          <AudioGallery
                            sessionId={sessionId}
                            phaseName={phaseName}
                            isRunning={isSessionRunning(sessionId)}
                          />
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

      {/* Image Modal - rendered via portal */}
      {selectedImage && createPortal(
        <div className="message-image-modal-overlay" onClick={() => setSelectedImage(null)}>
          <div className="message-image-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="message-image-modal-close" onClick={() => setSelectedImage(null)}>
              <Icon icon="mdi:close" width="24" />
            </button>
            <img
              src={selectedImage.url}
              alt="Full size"
              className="message-image-modal-full"
            />
            <div className="message-image-modal-info">
              {selectedImage.phase && (
                <span className="message-image-modal-phase">Phase: {selectedImage.phase}</span>
              )}
              <span className="message-image-modal-msg">Message #{selectedImage.index + 1}</span>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

export default MessageFlowView;
