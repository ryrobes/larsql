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
      // Options can be at top level (old format) or inside sections (generative UI format)
      let rawOptions = uiSpec.options || [];
      if (rawOptions.length === 0 && uiSpec.sections) {
        // Look for options in the choice section
        const choiceSection = uiSpec.sections.find(s => s.type === 'choice');
        if (choiceSection) {
          rawOptions = choiceSection.options || [];
        }
        // Also check for card_grid sections (generative UI format)
        if (rawOptions.length === 0) {
          const cardGridSection = uiSpec.sections.find(s => s.type === 'card_grid');
          if (cardGridSection && cardGridSection.cards) {
            rawOptions = cardGridSection.cards.map(card => ({
              label: card.title || card.id,
              value: card.id,
              description: card.content
            }));
          }
        }
      }
      // Try to extract actual option text from phase output
      const phaseOutput = checkpoint.phase_output_preview || checkpoint.phase_output || '';
      const options = extractOptionsFromOutput(phaseOutput, rawOptions);
      const selected = responses[checkpoint.id];

      // Fallback to confirmation if no options available
      if (options.length === 0) {
        return (
          <div className="checkpoint-input confirmation">
            <p className="checkpoint-fallback-note">No options available. Please approve or reject:</p>
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
      // max_rating can be at top level or inside sections (generative UI format)
      let maxRating = uiSpec.max_rating || uiSpec.max || 5;
      if (uiSpec.sections) {
        const ratingSection = uiSpec.sections.find(s => s.type === 'rating');
        if (ratingSection) {
          maxRating = ratingSection.max || ratingSection.max_rating || 5;
        }
      }
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

    // Multi-choice type (checkboxes)
    if (type === 'multi_choice') {
      // Options can be at top level or inside sections (generative UI format)
      let rawOptions = uiSpec.options || [];
      if (rawOptions.length === 0 && uiSpec.sections) {
        const multiChoiceSection = uiSpec.sections.find(s => s.type === 'multi_choice');
        if (multiChoiceSection) {
          rawOptions = multiChoiceSection.options || [];
        }
      }
      const phaseOutput = checkpoint.phase_output_preview || checkpoint.phase_output || '';
      const options = extractOptionsFromOutput(phaseOutput, rawOptions);
      const selected = responses[checkpoint.id] || [];

      const handleToggle = (value) => {
        const newSelected = selected.includes(value)
          ? selected.filter(v => v !== value)
          : [...selected, value];
        handleResponseChange(checkpoint.id, newSelected);
      };

      return (
        <div className="checkpoint-input multi-choice">
          <div className="choice-options">
            {options.map((opt, idx) => (
              <label key={idx} className={`choice-option ${selected.includes(opt.value) ? 'selected' : ''}`}>
                <input
                  type="checkbox"
                  value={opt.value}
                  checked={selected.includes(opt.value)}
                  onChange={() => handleToggle(opt.value)}
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
            onClick={() => handleSubmit(checkpoint, { values: selected })}
            disabled={selected.length === 0 || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit Selection'}
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
                {/* Render images from sections (including from columns in two-column layouts) */}
                {(() => {
                  // Collect all sections including from columns
                  let allSections = checkpoint.ui_spec?.sections || [];
                  if (checkpoint.ui_spec?.columns) {
                    for (const col of checkpoint.ui_spec.columns) {
                      if (col.sections) {
                        allSections = [...allSections, ...col.sections];
                      }
                    }
                  }
                  const imageSections = allSections.filter(s => s.type === 'image' || s.base64 || s.src);

                  if (imageSections.length === 0) return null;

                  return (
                    <div className="checkpoint-images">
                      {imageSections.map((imgSection, idx) => {
                        const imgSrc = imgSection.base64
                          ? (imgSection.base64.startsWith('data:') ? imgSection.base64 : `data:image/png;base64,${imgSection.base64}`)
                          : imgSection.src;
                        return imgSrc ? (
                          <div key={idx} className="checkpoint-image">
                            <img
                              src={imgSrc}
                              alt={imgSection.alt || imgSection.caption || `Image ${idx + 1}`}
                              style={{ maxWidth: '100%', maxHeight: '300px', objectFit: 'contain' }}
                            />
                            {imgSection.caption && (
                              <div className="image-caption">{imgSection.caption}</div>
                            )}
                          </div>
                        ) : null;
                      })}
                    </div>
                  );
                })()}

                {/* Render data tables from sections */}
                {(() => {
                  // Collect all sections including from columns
                  let allSections = checkpoint.ui_spec?.sections || [];
                  if (checkpoint.ui_spec?.columns) {
                    for (const col of checkpoint.ui_spec.columns) {
                      if (col.sections) {
                        allSections = [...allSections, ...col.sections];
                      }
                    }
                  }
                  const dataTables = allSections.filter(s => s.type === 'data_table');

                  if (dataTables.length === 0) return null;

                  return (
                    <div className="checkpoint-data-tables">
                      {dataTables.map((tableSection, idx) => {
                        const columns = tableSection.columns || [];
                        const data = tableSection.data || [];

                        if (columns.length === 0 || data.length === 0) return null;

                        return (
                          <div key={idx} className="checkpoint-data-table">
                            {tableSection.title && (
                              <div className="data-table-title">{tableSection.title}</div>
                            )}
                            <table>
                              <thead>
                                <tr>
                                  {columns.map((col, colIdx) => (
                                    <th key={colIdx}>{col.label || col.key || col}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {data.map((row, rowIdx) => (
                                  <tr key={rowIdx} className={tableSection.striped && rowIdx % 2 === 1 ? 'striped' : ''}>
                                    {columns.map((col, colIdx) => {
                                      const key = col.key || col;
                                      return <td key={colIdx}>{row[key] ?? ''}</td>;
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

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

                {/* Render title from ui_spec if present */}
                {checkpoint.ui_spec?.title && (
                  <div className="checkpoint-title-text">
                    {checkpoint.ui_spec.title}
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
