import React, { useState } from 'react';
import './CheckpointPanel.css';

/**
 * Parse phase output to extract actual option content.
 * Looks for patterns like "**Option A**\nActual title here" or "Option A: Title here"
 */
function extractOptionsFromOutput(phaseOutput, options) {
  if (!phaseOutput || !options || options.length === 0) {
    return options;
  }

  const output = phaseOutput;

  // Build a map of option values to their extracted text
  const extractedText = {};

  // Try to extract content for each option label (e.g., "Option A", "Option B", etc.)
  for (const opt of options) {
    const label = opt.label; // e.g., "Option A"

    // Pattern 1: **Option A**\nContent here\n\n (markdown bold headers)
    const boldPattern = new RegExp(
      `\\*\\*${label}\\*\\*[:\\s]*\\n([^\\n]+(?:\\n(?!\\*\\*Option|\\n\\n)[^\\n]*)*)`,
      'i'
    );

    // Pattern 2: Option A: Content here (inline format)
    const inlinePattern = new RegExp(
      `${label}[:\\s]+([^\\n]+)`,
      'i'
    );

    // Pattern 3: Just look for the label followed by content (numbered list style)
    const simplePattern = new RegExp(
      `${label}[.:\\s]+(.+?)(?=\\n(?:Option|$)|$)`,
      'is'
    );

    let match = output.match(boldPattern);
    if (match && match[1]) {
      extractedText[opt.value] = match[1].trim();
      continue;
    }

    match = output.match(inlinePattern);
    if (match && match[1]) {
      extractedText[opt.value] = match[1].trim();
      continue;
    }

    match = output.match(simplePattern);
    if (match && match[1]) {
      extractedText[opt.value] = match[1].trim().substring(0, 200); // Limit length
    }
  }

  // Enrich options with extracted text
  return options.map(opt => ({
    ...opt,
    // Use extracted text as description if we found it, otherwise keep original
    extractedText: extractedText[opt.value] || null,
    // Show extracted text as description if available
    displayDescription: extractedText[opt.value] || opt.description
  }));
}

/**
 * CheckpointPanel - Displays pending human-in-the-loop checkpoints
 *
 * Shows a notification panel when cascades are waiting for human input.
 * Supports different input types: confirmation, choice, rating, text, etc.
 */
function CheckpointPanel({ checkpoints, onRespond, onCancel, onDismiss }) {
  const [expandedCheckpoint, setExpandedCheckpoint] = useState(null);
  const [responses, setResponses] = useState({});
  const [reasoning, setReasoning] = useState({});
  const [submitting, setSubmitting] = useState({});

  if (!checkpoints || checkpoints.length === 0) {
    return null;
  }

  const handleToggleExpand = (checkpointId) => {
    setExpandedCheckpoint(prev => prev === checkpointId ? null : checkpointId);
  };

  const handleResponseChange = (checkpointId, value) => {
    setResponses(prev => ({ ...prev, [checkpointId]: value }));
  };

  const handleReasoningChange = (checkpointId, value) => {
    setReasoning(prev => ({ ...prev, [checkpointId]: value }));
  };

  const handleSubmit = async (checkpoint, responseValue) => {
    setSubmitting(prev => ({ ...prev, [checkpoint.id]: true }));

    try {
      await onRespond(checkpoint.id, responseValue, reasoning[checkpoint.id]);
    } catch (error) {
      console.error('Failed to submit checkpoint response:', error);
    } finally {
      setSubmitting(prev => ({ ...prev, [checkpoint.id]: false }));
    }
  };

  const renderInputUI = (checkpoint) => {
    const uiSpec = checkpoint.ui_spec || {};
    const type = uiSpec._meta?.type || checkpoint.checkpoint_type || 'confirmation';
    const isSubmitting = submitting[checkpoint.id];

    // Confirmation type (default)
    if (type === 'confirmation' || type === 'simple' || type === 'phase_input') {
      return (
        <div className="checkpoint-input confirmation">
          <div className="checkpoint-buttons">
            <button
              className="checkpoint-btn approve"
              onClick={() => handleSubmit(checkpoint, { confirmed: true })}
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Submitting...' : 'Approve'}
            </button>
            <button
              className="checkpoint-btn reject"
              onClick={() => handleSubmit(checkpoint, { confirmed: false })}
              disabled={isSubmitting}
            >
              Reject
            </button>
          </div>
        </div>
      );
    }

    // Choice type
    if (type === 'choice') {
      const rawOptions = uiSpec.options || [];
      // Try to extract actual option text from phase output
      const phaseOutput = checkpoint.phase_output_preview || checkpoint.phase_output || '';
      const options = extractOptionsFromOutput(phaseOutput, rawOptions);
      const selected = responses[checkpoint.id];

      return (
        <div className="checkpoint-input choice">
          <div className="choice-options">
            {options.map((opt, idx) => (
              <label key={idx} className={`choice-option ${selected === opt.value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name={`choice-${checkpoint.id}`}
                  value={opt.value}
                  checked={selected === opt.value}
                  onChange={() => handleResponseChange(checkpoint.id, opt.value)}
                />
                <div className="choice-content">
                  <span className="choice-label">{opt.label}</span>
                  {opt.displayDescription && (
                    <span className={`choice-desc ${opt.extractedText ? 'extracted' : ''}`}>
                      {opt.displayDescription}
                    </span>
                  )}
                </div>
              </label>
            ))}
          </div>
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { value: selected })}
            disabled={!selected || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit Choice'}
          </button>
        </div>
      );
    }

    // Rating type
    if (type === 'rating') {
      const maxRating = uiSpec.max_rating || 5;
      const selected = responses[checkpoint.id] || 0;

      return (
        <div className="checkpoint-input rating">
          <div className="rating-stars">
            {[...Array(maxRating)].map((_, idx) => (
              <button
                key={idx}
                className={`star ${idx < selected ? 'filled' : ''}`}
                onClick={() => handleResponseChange(checkpoint.id, idx + 1)}
              >
                {idx < selected ? '★' : '☆'}
              </button>
            ))}
          </div>
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { rating: selected })}
            disabled={!selected || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit Rating'}
          </button>
        </div>
      );
    }

    // Text type (also handles free_text from CheckpointType.FREE_TEXT)
    if (type === 'text' || type === 'free_text') {
      const textValue = responses[checkpoint.id] || '';

      return (
        <div className="checkpoint-input text">
          <textarea
            value={textValue}
            onChange={(e) => handleResponseChange(checkpoint.id, e.target.value)}
            placeholder={uiSpec.prompt || 'Enter your response...'}
            rows={4}
          />
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { text: textValue })}
            disabled={!textValue.trim() || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      );
    }

    // Default fallback - simple confirmation
    return (
      <div className="checkpoint-input confirmation">
        <div className="checkpoint-buttons">
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { confirmed: true })}
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Continue'}
          </button>
          <button
            className="checkpoint-btn cancel"
            onClick={() => onCancel(checkpoint.id)}
            disabled={isSubmitting}
          >
            Cancel
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="checkpoint-panel">
      <div className="checkpoint-header">
        <span className="checkpoint-icon">⏸️</span>
        <span className="checkpoint-title">
          Human Input Required ({checkpoints.length})
        </span>
        {onDismiss && (
          <button className="checkpoint-dismiss" onClick={onDismiss}>×</button>
        )}
      </div>

      <div className="checkpoint-list">
        {checkpoints.map(checkpoint => (
          <div
            key={checkpoint.id}
            className={`checkpoint-item ${expandedCheckpoint === checkpoint.id ? 'expanded' : ''}`}
          >
            <div
              className="checkpoint-summary"
              onClick={() => handleToggleExpand(checkpoint.id)}
            >
              <div className="checkpoint-info">
                <span className="checkpoint-cascade">{checkpoint.cascade_id}</span>
                <span className="checkpoint-phase">Phase: {checkpoint.phase_name}</span>
              </div>
              <span className="checkpoint-expand">
                {expandedCheckpoint === checkpoint.id ? '▼' : '▶'}
              </span>
            </div>

            {expandedCheckpoint === checkpoint.id && (
              <div className="checkpoint-details">
                <div className="checkpoint-output">
                  <div className="output-label">Phase Output:</div>
                  <div className="output-content">
                    {checkpoint.phase_output_preview || checkpoint.phase_output || 'No output available'}
                  </div>
                </div>

                {checkpoint.ui_spec?.prompt && (
                  <div className="checkpoint-prompt">
                    {checkpoint.ui_spec.prompt}
                  </div>
                )}

                {renderInputUI(checkpoint)}

                {checkpoint.ui_spec?.capture_reasoning && (
                  <div className="checkpoint-reasoning">
                    <textarea
                      value={reasoning[checkpoint.id] || ''}
                      onChange={(e) => handleReasoningChange(checkpoint.id, e.target.value)}
                      placeholder="Explain your choice (optional)..."
                      rows={2}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default CheckpointPanel;
