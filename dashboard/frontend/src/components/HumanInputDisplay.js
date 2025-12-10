import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './HumanInputDisplay.css';

/**
 * HumanInputDisplay - Shows human input interactions (ask_human calls) for a phase.
 * Displays the question asked and the human's response inline under each phase bar.
 * @param {string} sessionId - The session ID
 * @param {string} phaseName - Filter to only show inputs from this phase
 * @param {boolean} isRunning - Whether the session is currently running
 * @param {number} sessionUpdate - Timestamp of last session update (triggers refresh)
 */
function HumanInputDisplay({ sessionId, phaseName, isRunning, sessionUpdate }) {
  const [inputs, setInputs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cachedForSession, setCachedForSession] = useState(null);
  const [expanded, setExpanded] = useState({});

  const fetchInputs = useCallback(async () => {
    if (!sessionId) return;

    // Smart caching: If session completed and we already have data, don't re-fetch
    if (!isRunning && cachedForSession === sessionId && inputs.length > 0) {
      return;
    }

    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}/human-inputs`);
      if (response.ok) {
        const data = await response.json();
        setInputs(data.human_inputs || []);
        // Mark as cached for this session
        if (!isRunning) {
          setCachedForSession(sessionId);
        }
      }
    } catch (err) {
      console.error('Error fetching human inputs:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isRunning, cachedForSession, inputs.length]);

  // Fetch on mount
  useEffect(() => {
    fetchInputs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Fetch when THIS session gets an SSE update
  useEffect(() => {
    if (sessionUpdate) {
      fetchInputs();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionUpdate]);

  if (!sessionId) {
    return null;
  }

  // Filter inputs by phase if phaseName is provided
  const phaseInputs = phaseName
    ? inputs.filter(p => p.phase_name === phaseName)
    : inputs;

  // Flatten to just interactions for this phase
  const interactions = phaseInputs.flatMap(p => p.interactions || []);

  if (interactions.length === 0 && !loading) {
    return null; // Don't show anything if no human inputs
  }

  const toggleExpand = (index) => {
    setExpanded(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  const getResponseIcon = (interaction) => {
    if (interaction.type !== 'complete') {
      return <Icon icon="mdi:clock-outline" width="14" className="pending-icon" />;
    }

    // Try to determine UI type from ui_hint or response content
    const hint = interaction.ui_hint;
    const response = interaction.response || '';

    if (hint === 'confirmation' || response === 'yes' || response === 'no') {
      return response === 'yes' || response === 'Yes'
        ? <Icon icon="mdi:check-circle" width="14" className="yes-icon" />
        : <Icon icon="mdi:close-circle" width="14" className="no-icon" />;
    }

    if (hint === 'rating' || /^\d+$/.test(response)) {
      return <Icon icon="mdi:star" width="14" className="rating-icon" />;
    }

    if (hint === 'choice') {
      return <Icon icon="mdi:radiobox-marked" width="14" className="choice-icon" />;
    }

    if (hint === 'multi_choice') {
      return <Icon icon="mdi:checkbox-multiple-marked" width="14" className="multi-choice-icon" />;
    }

    return <Icon icon="mdi:message-reply-text" width="14" className="text-icon" />;
  };

  const formatResponse = (interaction) => {
    const response = interaction.response;
    if (!response) return <span className="pending">Waiting for response...</span>;

    // For ratings, show stars
    if (interaction.ui_hint === 'rating' && /^\d+$/.test(response)) {
      const rating = parseInt(response, 10);
      return (
        <span className="rating-display">
          {[...Array(5)].map((_, i) => (
            <span key={i} className={i < rating ? 'star filled' : 'star'}>
              {i < rating ? '★' : '☆'}
            </span>
          ))}
          <span className="rating-value">({rating}/5)</span>
        </span>
      );
    }

    // For yes/no, show styled badge
    if (response === 'yes' || response === 'no') {
      return (
        <span className={`confirmation-badge ${response}`}>
          {response === 'yes' ? 'Approved' : 'Rejected'}
        </span>
      );
    }

    // For multi-choice, split by comma
    if (interaction.ui_hint === 'multi_choice' && response.includes(',')) {
      const selections = response.split(',').map(s => s.trim());
      return (
        <span className="multi-choice-display">
          {selections.map((sel, i) => (
            <span key={i} className="selection-chip">{sel}</span>
          ))}
        </span>
      );
    }

    // Default: show as text
    return <span className="text-response">{response}</span>;
  };

  return (
    <div className="human-input-display">
      {interactions.map((interaction, index) => (
        <div
          key={index}
          className={`human-input-item ${interaction.type} ${expanded[index] ? 'expanded' : ''}`}
          onClick={() => toggleExpand(index)}
        >
          <div className="input-header">
            <Icon icon="mdi:account-question" width="16" className="human-icon" />
            <span className="input-question" title={interaction.question}>
              {interaction.question?.length > 60
                ? interaction.question.substring(0, 60) + '...'
                : interaction.question}
            </span>
            <div className="input-response-preview">
              {getResponseIcon(interaction)}
              {formatResponse(interaction)}
            </div>
          </div>

          {expanded[index] && (
            <div className="input-details">
              <div className="detail-row">
                <span className="detail-label">Question:</span>
                <span className="detail-value">{interaction.question}</span>
              </div>
              {interaction.context && (
                <div className="detail-row">
                  <span className="detail-label">Context:</span>
                  <span className="detail-value context-preview">
                    {interaction.context.length > 200
                      ? interaction.context.substring(0, 200) + '...'
                      : interaction.context}
                  </span>
                </div>
              )}
              {interaction.ui_hint && (
                <div className="detail-row">
                  <span className="detail-label">UI Type:</span>
                  <span className="detail-value ui-type-badge">{interaction.ui_hint}</span>
                </div>
              )}
              <div className="detail-row">
                <span className="detail-label">Response:</span>
                <span className="detail-value">{interaction.response || 'Pending...'}</span>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default HumanInputDisplay;
