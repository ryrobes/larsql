import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { Icon } from '@iconify/react';
import VideoSpinner from './VideoSpinner';
import AudioGallery from './AudioGallery';
import ContextMatrixView from './ContextMatrixView';
import ContextCrossRefPanel from './ContextCrossRefPanel';
import SpeciesWidget from './SpeciesWidget';
import PhaseSpeciesBadges from './CellTypeBadges';
import MessageItem from './MessageItem';
import Header from './Header';
import './MessageFlowView.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5050';

// extractImagesFromMessage and MessageImages are now imported from MessageItem.js

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

function MessageFlowView({ onBack, initialSessionId, onSessionChange, hideControls = false, scrollToIndex = null, onMessageSelect = null, selectedMessageIndex = null, runningSessions: parentRunningSessions = null, sessionUpdates: parentSessionUpdates = null, externalData = null, onMessageFlow, onSextant, onWorkshop, onPlayground, onTools, onSearch, onArtifacts, onBlocked, blockedCount = 0, sseConnected = false }) {
  const [sessionId, setSessionId] = useState(initialSessionId || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState(new Set());
  const [highlightedMessage, setHighlightedMessage] = useState(null);
  const [localRunningSessions, setLocalRunningSessions] = useState([]);
  const [recentSessions, setRecentSessions] = useState([]); // Combined recent + running sessions for button row
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [waitingForData, setWaitingForData] = useState(false); // True when session is running but no data yet
  const [selectedImage, setSelectedImage] = useState(null); // For image modal
  const currentSessionIdRef = useRef(initialSessionId || null);

  // Context highlighting state
  const [hoveredContextHashes, setHoveredContextHashes] = useState(new Set());
  const [highlightMode, setHighlightMode] = useState('ancestors'); // 'ancestors' | 'descendants' | 'both'

  // Context Matrix view state
  const [showContextMatrix, setShowContextMatrix] = useState(false);

  // Cross-reference panel state
  const [showCrossRefPanel, setShowCrossRefPanel] = useState(false);
  const [crossRefMessage, setCrossRefMessage] = useState(null);

  // ===========================================
  // EXTERNAL DATA SUPPORT: Skip fetching when data provided
  // ===========================================

  // Use external data when provided (from SplitDetailView to avoid duplicate fetches)
  useEffect(() => {
    if (externalData) {
      setData(externalData);
      setLoading(false);
      setError(null);
      setWaitingForData(false);
    }
  }, [externalData]);

  // ===========================================
  // PERFORMANCE OPTIMIZATION: Memoized Computations
  // ===========================================

  // NOTE: imageCache removed - MessageItem now handles image extraction
  // lazily via IntersectionObserver (only when message scrolls into view)

  // Memoize phase grouping computation - this O(n²) algorithm was running inline in JSX on every render!
  // Now it only recomputes when the underlying data changes
  const { phaseGroups, soundingsBlockMap, reforgeBlockMap } = React.useMemo(() => {
    // Build a map of cell_name -> soundings block for quick lookup
    const soundingsBlockMap = {};
    if (data?.soundings_by_phase && data.soundings_by_phase.length > 0) {
      data.soundings_by_phase.forEach(block => {
        soundingsBlockMap[block.cell_name] = block;
      });
    }

    // Build a map of cell_name -> reforge block for quick lookup
    const reforgeBlockMap = {};
    if (data?.reforge_by_phase && data.reforge_by_phase.length > 0) {
      data.reforge_by_phase.forEach(block => {
        reforgeBlockMap[block.cell_name] = block;
      });
    }

    // Group messages by phase while maintaining order
    const phaseGroups = [];
    let currentPhase = null;
    let currentMessages = [];

    (data?.main_flow || []).forEach((msg, i) => {
      const phaseName = msg.cell_name || '_unknown_';

      if (phaseName !== currentPhase) {
        // Save the previous phase group
        if (currentPhase !== null && currentMessages.length > 0) {
          phaseGroups.push({
            cell_name: currentPhase,
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
        cell_name: currentPhase,
        messages: currentMessages,
        hasSoundings: !!soundingsBlockMap[currentPhase],
        hasReforge: !!reforgeBlockMap[currentPhase]
      });
    }

    // Also check for soundings that might not have messages in main_flow
    if (data?.soundings_by_phase && data.soundings_by_phase.length > 0) {
      data.soundings_by_phase.forEach(block => {
        const existingGroup = phaseGroups.find(g => g.cell_name === block.cell_name);
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
            cell_name: block.cell_name,
            messages: [],
            hasSoundings: true,
            hasReforge: !!reforgeBlockMap[block.cell_name],
            soundingsOnly: true
          });
        }
      });
    }

    // Also check for reforge phases that might not have messages in main_flow
    if (data?.reforge_by_phase && data.reforge_by_phase.length > 0) {
      data.reforge_by_phase.forEach(block => {
        const existingGroup = phaseGroups.find(g => g.cell_name === block.cell_name);
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
            cell_name: block.cell_name,
            messages: [],
            hasSoundings: !!soundingsBlockMap[block.cell_name],
            hasReforge: true,
            reforgeOnly: true
          });
        }
      });
    }

    return { phaseGroups, soundingsBlockMap, reforgeBlockMap };
  }, [data?.main_flow, data?.soundings_by_phase, data?.reforge_by_phase]);

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
  // Use parent-provided runningSessions (Set from SSE) if available, fall back to local polling
  const isSessionRunning = useCallback((sid) => {
    // If parent provides runningSessions (a Set from App.js SSE), use it for reliable real-time state
    if (parentRunningSessions) {
      return parentRunningSessions.has(sid);
    }
    // Otherwise fall back to local polling-based detection
    return localRunningSessions.some(s =>
      s.session_id === sid && (s.status === 'running' || s.status === 'completing')
    );
  }, [parentRunningSessions, localRunningSessions]);

  const fetchMessages = useCallback(async (targetSessionId = null, silent = false) => {
    // Skip fetching if using external data (data provided by parent)
    if (externalData) return;

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, isSessionRunning, externalData]); // onSessionChange intentionally excluded - it's stable from parent

  const fetchRunningSessions = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/running-sessions`);
      const sessions = response.data.sessions || [];
      setLocalRunningSessions(sessions);

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

  // Immediate refresh when parent notifies us of SSE session updates
  // This makes updates appear instantly instead of waiting for the 2s poll
  useEffect(() => {
    if (!parentSessionUpdates) return;
    const sid = data?.session_id || currentSessionIdRef.current;
    if (!sid) return;

    // If the parent has an update for our session, refresh immediately
    const lastUpdate = parentSessionUpdates[sid];
    if (lastUpdate) {
      fetchMessages(null, true); // silent refresh
    }
  }, [parentSessionUpdates, data?.session_id, fetchMessages]);

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

  const toggleMessage = useCallback((index) => {
    setExpandedMessages(prev => {
      const newExpanded = new Set(prev);
      if (newExpanded.has(index)) {
        newExpanded.delete(index);
      } else {
        newExpanded.add(index);
      }
      return newExpanded;
    });
  }, []);

  const scrollToMostExpensive = useCallback(() => {
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
  }, [data?.cost_summary?.most_expensive]);

  // Helper to find global index of a message
  // Uses _index field directly if available (added by backend to avoid lookup collisions)
  // Falls back to composite key lookup for backward compatibility
  const findGlobalIndex = useCallback((msg) => {
    if (!data?.all_messages) return -1;
    // Prefer direct _index from backend (avoids timestamp collision issues)
    if (msg._index !== undefined && msg._index !== null) {
      return msg._index;
    }
    // Fallback: Match by multiple fields for uniqueness
    return data.all_messages.findIndex(m =>
      m.timestamp === msg.timestamp &&
      m.role === msg.role &&
      m.node_type === msg.node_type &&
      m.turn_number === msg.turn_number &&
      m.candidate_index === msg.candidate_index &&
      m.cell_name === msg.cell_name
    );
  }, [data?.all_messages]);

  // categoryColors moved to MessageItem.js

  // Context highlighting handlers
  const handleMessageHover = useCallback((msg, isEntering) => {
    if (!isEntering || !data) {
      setHoveredContextHashes(new Set());
      return;
    }

    const hashesToHighlight = new Set();

    // Ancestors: messages that were in this message's context
    if (highlightMode === 'ancestors' || highlightMode === 'both') {
      (msg.context_hashes || []).forEach(h => hashesToHighlight.add(h));
    }

    // Descendants: messages that had this message in their context
    if ((highlightMode === 'descendants' || highlightMode === 'both') && msg.content_hash) {
      data.all_messages.forEach(m => {
        if (m.context_hashes?.includes(msg.content_hash)) {
          hashesToHighlight.add(m.content_hash);
        }
      });
    }

    setHoveredContextHashes(hashesToHighlight);
  }, [data, highlightMode]);

  // Check if a message should be highlighted based on hovered context
  const isContextHighlighted = useCallback((msg) => {
    if (hoveredContextHashes.size === 0) return false;
    return msg.content_hash && hoveredContextHashes.has(msg.content_hash);
  }, [hoveredContextHashes]);

  // Copy hash to clipboard (double-click)
  const copyHashToClipboard = useCallback((hash, e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(hash);
  }, []);

  // Show cross-reference panel for a message (single-click on hash badge)
  const showCrossRef = useCallback((msg, e) => {
    e.stopPropagation();
    setCrossRefMessage(msg);
    setShowCrossRefPanel(true);
  }, []);

  // Navigate from cross-ref panel to a message
  const handleCrossRefNavigate = useCallback((index) => {
    const messageEl = document.getElementById(`message-${index}`);
    if (messageEl) {
      messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setHighlightedMessage(index);
      setTimeout(() => setHighlightedMessage(null), 3000);
    }
  }, []);

  // Handle message selection from matrix view
  const handleMatrixMessageSelect = useCallback((msg) => {
    if (!msg || !data?.all_messages) return;
    // Prefer _index from backend, fallback to indexOf (works for same object reference)
    const index = msg._index !== undefined ? msg._index : data.all_messages.indexOf(msg);
    if (index >= 0) {
      // Scroll to and highlight the message
      const messageEl = document.getElementById(`message-${index}`);
      if (messageEl) {
        messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setHighlightedMessage(index);
        setTimeout(() => setHighlightedMessage(null), 3000);
      }
    }
  }, [data]);

  // Render a message using the memoized MessageItem component
  // This wrapper provides the necessary props and callbacks
  const renderMessage = useCallback((msg, index, label) => {
    const globalIndex = findGlobalIndex(msg);
    const isExternalMode = !!onMessageSelect;
    const isExpanded = isExternalMode ? false : expandedMessages.has(index);
    const isSelected = isExternalMode && selectedMessageIndex === globalIndex;
    const isHighlighted = highlightedMessage === globalIndex;
    const isMostExpensive = data?.cost_summary?.most_expensive?.index === globalIndex;

    return (
      <MessageItem
        key={`msg-${globalIndex}-${index}`}
        msg={msg}
        index={index}
        label={label}
        globalIndex={globalIndex}
        isExpanded={isExpanded}
        isSelected={isSelected}
        isHighlighted={isHighlighted}
        isMostExpensive={isMostExpensive}
        isContextHighlighted={isContextHighlighted(msg)}
        onToggle={toggleMessage}
        onSelect={onMessageSelect}
        onHover={handleMessageHover}
        onShowCrossRef={showCrossRef}
        onCopyHash={copyHashToClipboard}
        onImageClick={(img) => setSelectedImage(img)}
        hashIndex={data?.hash_index}
        setHighlightedMessage={setHighlightedMessage}
        isExternalMode={isExternalMode}
        sessionId={sessionId}
      />
    );
  }, [
    findGlobalIndex,
    onMessageSelect,
    expandedMessages,
    selectedMessageIndex,
    highlightedMessage,
    data?.cost_summary?.most_expensive?.index,
    data?.hash_index,
    isContextHighlighted,
    toggleMessage,
    handleMessageHover,
    showCrossRef,
    copyHashToClipboard,
    setSelectedImage,
    setHighlightedMessage
  ]);

  return (
    <div className={`message-flow-view ${hideControls ? 'embedded' : ''}`}>
      {!hideControls && (
        <>
          <Header
            onBack={onBack}
            backLabel="Back"
            centerContent={
              <span className="header-stat">Message Flow</span>
            }
            onMessageFlow={onMessageFlow}
            onSextant={onSextant}
            onWorkshop={onWorkshop}
            onPlayground={onPlayground}
            onTools={onTools}
            onSearch={onSearch}
            onArtifacts={onArtifacts}
            onBlocked={onBlocked}
            blockedCount={blockedCount}
            sseConnected={sseConnected}
          />
          <div className="controls">
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
        </>
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
              <div className="session-title-row">
                <h2>Session: {data.session_id}</h2>
                <SpeciesWidget sessionId={data.session_id} />
              </div>
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
              <span>Soundings: {data.candidates.length}</span>
              <span>Reforge Steps: {data.reforge_steps.length}</span>
              <PhaseSpeciesBadges sessionId={data.session_id} />
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

            {/* Context Stats & Highlight Controls */}
            <div className="context-controls-row">
              {data.context_stats && (
                <div className="context-stats-mini">
                  <span title="LLM calls with context">
                    <Icon icon="mdi:message-processing" width="14" /> {data.context_stats.llm_calls_with_context} LLM calls
                  </span>
                  <span title="Unique context items">
                    <Icon icon="mdi:fingerprint" width="14" /> {data.context_stats.unique_context_items} unique contexts
                  </span>
                  <span title="Average context size">
                    <Icon icon="mdi:chart-line" width="14" /> avg {data.context_stats.avg_context_size} / max {data.context_stats.max_context_size}
                  </span>
                </div>
              )}
              <div className="context-highlight-controls">
                <span className="highlight-label">Hover shows:</span>
                <button
                  className={`highlight-mode-btn ${highlightMode === 'ancestors' ? 'active' : ''}`}
                  onClick={() => setHighlightMode('ancestors')}
                  title="Show messages that were in hovered message's context"
                >
                  <Icon icon="mdi:arrow-up" width="14" /> Ancestors
                </button>
                <button
                  className={`highlight-mode-btn ${highlightMode === 'descendants' ? 'active' : ''}`}
                  onClick={() => setHighlightMode('descendants')}
                  title="Show messages that saw the hovered message in their context"
                >
                  <Icon icon="mdi:arrow-down" width="14" /> Descendants
                </button>
                <button
                  className={`highlight-mode-btn ${highlightMode === 'both' ? 'active' : ''}`}
                  onClick={() => setHighlightMode('both')}
                  title="Show both ancestors and descendants"
                >
                  <Icon icon="mdi:arrow-up-down" width="14" /> Both
                </button>
                <button
                  className={`highlight-mode-btn matrix-btn ${showContextMatrix ? 'active' : ''}`}
                  onClick={() => setShowContextMatrix(!showContextMatrix)}
                  title="Toggle context matrix heatmap view"
                >
                  <Icon icon="mdi:grid" width="14" /> Matrix
                </button>
              </div>
            </div>
          </div>

          {/* Context Matrix Heatmap View */}
          {showContextMatrix && (
            <div className="context-matrix-wrapper">
              <ContextMatrixView
                data={data}
                onMessageSelect={handleMatrixMessageSelect}
                onClose={() => setShowContextMatrix(false)}
              />
            </div>
          )}

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
                  // NOTE: phaseGroups, soundingsBlockMap, and reforgeBlockMap are now
                  // computed via useMemo above (PERFORMANCE FIX - was O(n²) inline every render)

                  // Track which phases we've shown soundings/reforge for (render-time tracking)
                  const shownSoundingsPhases = new Set();
                  const shownReforgePhases = new Set();

                  // Helper to render a soundings block
                  const renderSoundingsBlock = (block, phaseName) => (
                    <div key={`soundings-block-${phaseName}`} className="inline-soundings-block">
                      <div className="inline-soundings-header">
                        <span className="soundings-icon">🔱</span>
                        <span className="soundings-phase-name">Soundings</span>
                        <span className="soundings-count">{block.candidates.length} parallel attempts</span>
                        {block.winner_index !== null && (
                          <span className="soundings-winner">Winner: S{block.winner_index}</span>
                        )}
                      </div>
                      <div className="soundings-grid">
                        {block.candidates.map((sounding) => (
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
                    const phaseName = group.cell_name;
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
                      soundingsBlock.candidates.forEach(sounding => {
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
                              if (soundingsBlock && msg.candidate_index !== null && msg.candidate_index !== undefined) {
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

      {/* Cross-Reference Side Panel */}
      {showCrossRefPanel && (
        <div className="cross-ref-panel-container">
          <ContextCrossRefPanel
            selectedMessage={crossRefMessage}
            allMessages={data?.all_messages}
            hashIndex={data?.hash_index}
            onNavigate={handleCrossRefNavigate}
            onClose={() => {
              setShowCrossRefPanel(false);
              setCrossRefMessage(null);
            }}
          />
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
