import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import VoiceInputSection from './VoiceInputSection';
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
 * Simple markdown renderer for preview sections
 */
function renderMarkdown(content) {
  if (!content) return null;

  // Basic markdown transformations
  let html = content
    // Code blocks (must come before inline code)
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block" data-lang="$1"><code>$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    // Bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Headers
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Line breaks
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>');

  return <div className="markdown-content" dangerouslySetInnerHTML={{ __html: `<p>${html}</p>` }} />;
}

/**
 * CheckpointPanel - Displays pending human-in-the-loop checkpoints
 *
 * Supports generative UI with:
 * - Two-column layouts (image/data left, inputs right)
 * - Unified section rendering
 * - Preview sections (text, markdown, code)
 * - Images, data tables, and all input types
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

  // ==========================================================================
  // UNIFIED SECTION RENDERER
  // ==========================================================================

  /**
   * Render a single section based on its type
   */
  const renderSection = (section, checkpoint, sectionIdx) => {
    if (!section || !section.type) return null;

    const key = `section-${sectionIdx}-${section.type}`;

    switch (section.type) {
      case 'image':
        return renderImageSection(section, key);

      case 'data_table':
        return renderDataTableSection(section, key);

      case 'preview':
        return renderPreviewSection(section, key);

      case 'confirmation':
        return renderConfirmationInput(section, checkpoint, key);

      case 'choice':
        return renderChoiceInput(section, checkpoint, key);

      case 'multi_choice':
        return renderMultiChoiceInput(section, checkpoint, key);

      case 'rating':
        return renderRatingInput(section, checkpoint, key);

      case 'text':
        return renderTextInput(section, checkpoint, key);

      case 'card_grid':
        return renderCardGridSection(section, checkpoint, key);

      case 'voice':
      case 'voice_input':
      case 'audio_input':
        return renderVoiceInputSection(section, checkpoint, key);

      default:
        // Unknown section type - render as preview if it has content
        if (section.content) {
          return renderPreviewSection({ ...section, type: 'preview' }, key);
        }
        return null;
    }
  };

  // ==========================================================================
  // CONTENT SECTIONS (Display only, no input)
  // ==========================================================================

  const renderImageSection = (section, key) => {
    const imgSrc = section.base64
      ? (section.base64.startsWith('data:') ? section.base64 : `data:image/png;base64,${section.base64}`)
      : section.src;

    if (!imgSrc) return null;

    return (
      <div key={key} className="section section-image">
        <img
          src={imgSrc}
          alt={section.alt || section.caption || 'Image'}
          style={{
            maxWidth: '100%',
            maxHeight: section.max_height || 300,
            objectFit: 'contain'
          }}
        />
        {section.caption && (
          <div className="image-caption">{section.caption}</div>
        )}
      </div>
    );
  };

  const renderDataTableSection = (section, key) => {
    const columns = section.columns || [];
    const data = section.data || [];

    if (columns.length === 0 || data.length === 0) return null;

    return (
      <div key={key} className="section section-data-table">
        {section.title && (
          <div className="data-table-title">{section.title}</div>
        )}
        <div className="data-table-wrapper" style={{ maxHeight: section.max_height || 300 }}>
          <table>
            <thead>
              <tr>
                {columns.map((col, colIdx) => {
                  // Handle both string and object column definitions
                  const colObj = typeof col === 'string' ? { key: col, label: col } : col;
                  return (
                    <th
                      key={colIdx}
                      style={{
                        textAlign: colObj.align || 'left',
                        width: colObj.width
                      }}
                    >
                      {colObj.label || colObj.key || String(col)}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.map((row, rowIdx) => (
                <tr key={rowIdx} className={section.striped && rowIdx % 2 === 1 ? 'striped' : ''}>
                  {columns.map((col, colIdx) => {
                    const colObj = typeof col === 'string' ? { key: col } : col;
                    const colKey = colObj.key || col;
                    const cellValue = row[colKey];
                    // Handle object cell values
                    const displayValue = cellValue == null
                      ? ''
                      : typeof cellValue === 'object'
                        ? (cellValue.text || cellValue.label || cellValue.value || JSON.stringify(cellValue))
                        : String(cellValue);
                    return (
                      <td
                        key={colIdx}
                        style={{ textAlign: colObj.align || 'left' }}
                      >
                        {displayValue}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderPreviewSection = (section, key) => {
    const content = section.content;
    if (!content) return null;

    const render = section.render || 'auto';
    const isCode = render === 'code' || (render === 'auto' && content.includes('```'));
    const isMarkdown = render === 'markdown' || (render === 'auto' && (
      content.includes('**') || content.includes('##') || content.includes('- ')
    ));

    return (
      <div key={key} className={`section section-preview ${section.collapsible ? 'collapsible' : ''}`}>
        {section.label && (
          <div className="preview-label">{section.label}</div>
        )}
        <div
          className={`preview-content ${isCode ? 'code' : ''}`}
          style={{ maxHeight: section.max_height || 200 }}
        >
          {isMarkdown ? renderMarkdown(content) : (
            <div className="preview-text">{content}</div>
          )}
        </div>
      </div>
    );
  };

  const renderCardGridSection = (section, checkpoint, key) => {
    const cards = section.cards || [];
    const selected = responses[checkpoint.id];
    const cols = section.columns || 2;

    if (cards.length === 0) return null;

    return (
      <div key={key} className="section section-card-grid">
        <div
          className="card-grid"
          style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
        >
          {cards.map((card, idx) => {
            // Safely extract string values from potential objects
            const safeStr = (val) => {
              if (val == null) return '';
              if (typeof val === 'object') return val.text || val.label || val.value || JSON.stringify(val);
              return String(val);
            };
            const cardTitle = safeStr(card.title);
            const cardContent = safeStr(card.content);
            const cardBadge = safeStr(card.badge);

            return (
            <div
              key={idx}
              className={`card ${selected === card.id ? 'selected' : ''} ${card.disabled ? 'disabled' : ''}`}
              onClick={() => !card.disabled && handleResponseChange(checkpoint.id, card.id)}
            >
              {cardBadge && <span className="card-badge">{cardBadge}</span>}
              {card.image && (
                <div className="card-image">
                  <img src={card.image} alt={cardTitle} />
                </div>
              )}
              <div className="card-content">
                <div className="card-title">{cardTitle}</div>
                {cardContent && <div className="card-desc">{cardContent}</div>}
                {card.metadata && section.show_metadata !== false && (
                  <div className="card-metadata">
                    {Object.entries(card.metadata).map(([k, v]) => {
                      // Handle both simple values and {text, color} objects
                      const displayValue = typeof v === 'object' && v !== null
                        ? (v.text || v.label || JSON.stringify(v))
                        : String(v);
                      const chipStyle = typeof v === 'object' && v?.color
                        ? { color: v.color }
                        : {};
                      return (
                        <span key={k} className="metadata-chip" style={chipStyle}>
                          {k}: {displayValue}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
          })}
        </div>
      </div>
    );
  };

  // ==========================================================================
  // INPUT SECTIONS (Collect user response)
  // ==========================================================================

  const renderConfirmationInput = (section, checkpoint, key) => {
    const isSubmitting = submitting[checkpoint.id];

    return (
      <div key={key} className="section section-input confirmation">
        {section.prompt && (
          <div className="input-prompt">{section.prompt}</div>
        )}
        <div className="checkpoint-buttons">
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { confirmed: true })}
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : (section.yes_label || 'Approve')}
          </button>
          <button
            className="checkpoint-btn reject"
            onClick={() => handleSubmit(checkpoint, { confirmed: false })}
            disabled={isSubmitting}
          >
            {section.no_label || 'Reject'}
          </button>
        </div>
      </div>
    );
  };

  const renderChoiceInput = (section, checkpoint, key) => {
    const phaseOutput = checkpoint.phase_output_preview || checkpoint.phase_output || '';
    const rawOptions = section.options || [];
    const options = extractOptionsFromOutput(phaseOutput, rawOptions);
    const selected = responses[checkpoint.id];
    const isSubmitting = submitting[checkpoint.id];

    if (options.length === 0) {
      // Fallback to confirmation
      return renderConfirmationInput({ ...section, type: 'confirmation' }, checkpoint, key);
    }

    return (
      <div key={key} className="section section-input choice">
        {section.prompt && (
          <div className="input-prompt">{section.prompt}</div>
        )}
        <div className="choice-options">
          {options.map((opt, idx) => {
            // Safely convert potential objects to strings
            const safeStr = (val) => {
              if (val == null) return '';
              if (typeof val === 'object') return val.text || val.label || val.value || JSON.stringify(val);
              return String(val);
            };
            const optLabel = safeStr(opt.label);
            const optDesc = safeStr(opt.displayDescription);
            const optValue = typeof opt.value === 'object' ? JSON.stringify(opt.value) : opt.value;

            return (
              <label key={idx} className={`choice-option ${selected === opt.value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name={`choice-${checkpoint.id}`}
                  value={optValue}
                  checked={selected === opt.value}
                  onChange={() => handleResponseChange(checkpoint.id, opt.value)}
                />
                <div className="choice-content">
                  <span className="choice-label">{optLabel}</span>
                  {optDesc && (
                    <span className={`choice-desc ${opt.extractedText ? 'extracted' : ''}`}>
                      {optDesc}
                    </span>
                  )}
                </div>
              </label>
            );
          })}
        </div>
        <button
          className="checkpoint-btn approve"
          onClick={() => handleSubmit(checkpoint, { value: selected })}
          disabled={!selected || isSubmitting}
        >
          {isSubmitting ? 'Submitting...' : (section.submit_label || 'Submit Choice')}
        </button>
      </div>
    );
  };

  const renderMultiChoiceInput = (section, checkpoint, key) => {
    const phaseOutput = checkpoint.phase_output_preview || checkpoint.phase_output || '';
    const rawOptions = section.options || [];
    const options = extractOptionsFromOutput(phaseOutput, rawOptions);
    const selected = responses[checkpoint.id] || [];
    const isSubmitting = submitting[checkpoint.id];

    const handleToggle = (value) => {
      const newSelected = selected.includes(value)
        ? selected.filter(v => v !== value)
        : [...selected, value];
      handleResponseChange(checkpoint.id, newSelected);
    };

    return (
      <div key={key} className="section section-input multi-choice">
        {section.prompt && (
          <div className="input-prompt">{section.prompt}</div>
        )}
        <div className="choice-options">
          {options.map((opt, idx) => {
            // Safely convert potential objects to strings
            const safeStr = (val) => {
              if (val == null) return '';
              if (typeof val === 'object') return val.text || val.label || val.value || JSON.stringify(val);
              return String(val);
            };
            const optLabel = safeStr(opt.label);
            const optDesc = safeStr(opt.displayDescription);

            return (
              <label key={idx} className={`choice-option ${selected.includes(opt.value) ? 'selected' : ''}`}>
                <input
                  type="checkbox"
                  value={opt.value}
                  checked={selected.includes(opt.value)}
                  onChange={() => handleToggle(opt.value)}
                />
                <div className="choice-content">
                  <span className="choice-label">{optLabel}</span>
                  {optDesc && (
                    <span className={`choice-desc ${opt.extractedText ? 'extracted' : ''}`}>
                      {optDesc}
                    </span>
                  )}
                </div>
              </label>
            );
          })}
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
  };

  const renderRatingInput = (section, checkpoint, key) => {
    const maxRating = section.max || section.max_rating || 5;
    const selected = responses[checkpoint.id] || 0;
    const isSubmitting = submitting[checkpoint.id];

    return (
      <div key={key} className="section section-input rating">
        {section.prompt && (
          <div className="input-prompt">{section.prompt}</div>
        )}
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
          {section.show_value && selected > 0 && (
            <span className="rating-value">{selected}/{maxRating}</span>
          )}
        </div>
        {section.labels && selected > 0 && (
          <div className="rating-label">{section.labels[selected - 1]}</div>
        )}
        <button
          className="checkpoint-btn approve"
          onClick={() => handleSubmit(checkpoint, { rating: selected })}
          disabled={!selected || isSubmitting}
        >
          {isSubmitting ? 'Submitting...' : 'Submit Rating'}
        </button>
      </div>
    );
  };

  const renderTextInput = (section, checkpoint, key) => {
    const textValue = responses[checkpoint.id] || '';
    const isSubmitting = submitting[checkpoint.id];

    // Skip if show_if condition is not met
    if (section.show_if) {
      const fieldValue = responses[checkpoint.id + '_' + section.show_if.field];
      if (section.show_if.equals !== undefined && fieldValue !== section.show_if.equals) {
        return null;
      }
    }

    return (
      <div key={key} className="section section-input text">
        {section.label && (
          <div className="input-label">{section.label}</div>
        )}
        <textarea
          value={textValue}
          onChange={(e) => handleResponseChange(checkpoint.id, e.target.value)}
          placeholder={section.placeholder || 'Enter your response...'}
          rows={section.multiline !== false ? 4 : 1}
        />
        <button
          className="checkpoint-btn approve"
          onClick={() => handleSubmit(checkpoint, { text: textValue })}
          disabled={(section.required && !textValue.trim()) || isSubmitting}
        >
          {isSubmitting ? 'Submitting...' : 'Submit'}
        </button>
      </div>
    );
  };

  const renderVoiceInputSection = (section, checkpoint, key) => {
    const voiceValue = responses[checkpoint.id] || '';
    const isSubmitting = submitting[checkpoint.id];

    return (
      <div key={key} className="section section-input voice">
        <VoiceInputSection
          section={{
            label: section.label,
            prompt: section.prompt || 'Speak your response...',
            placeholder: section.placeholder || 'Or type your response here...',
            allow_text_fallback: section.allow_text_fallback !== false,
            editable_transcript: section.editable_transcript !== false,
            language: section.language,
          }}
          value={voiceValue}
          onChange={(value) => handleResponseChange(checkpoint.id, value)}
          sessionId={checkpoint.session_id}
          disabled={isSubmitting}
        />
        {voiceValue && (
          <button
            className="checkpoint-btn approve"
            onClick={() => handleSubmit(checkpoint, { voice_transcript: voiceValue })}
            disabled={!voiceValue.trim() || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit Voice Response'}
          </button>
        )}
      </div>
    );
  };

  // ==========================================================================
  // LAYOUT RENDERERS
  // ==========================================================================

  /**
   * Find the primary input type from sections (for fallback logic)
   */
  const findPrimaryInputType = (sections) => {
    const inputTypes = ['confirmation', 'choice', 'multi_choice', 'rating', 'text', 'card_grid', 'voice', 'voice_input', 'audio_input'];
    for (const section of sections) {
      if (inputTypes.includes(section.type)) {
        return section.type;
      }
    }
    return 'confirmation';
  };

  /**
   * Check if sections have any input component
   */
  const hasInputSection = (sections) => {
    const inputTypes = ['confirmation', 'choice', 'multi_choice', 'rating', 'text'];
    return sections.some(s => inputTypes.includes(s.type));
  };

  /**
   * Render the content area based on ui_spec layout
   */
  const renderContent = (checkpoint) => {
    const uiSpec = checkpoint.ui_spec || {};
    const layout = uiSpec.layout || 'vertical';
    const type = uiSpec._meta?.type || checkpoint.checkpoint_type || 'confirmation';
    const isSubmitting = submitting[checkpoint.id];

    // =======================================================================
    // TWO-COLUMN LAYOUT
    // =======================================================================
    if (layout === 'two-column' && uiSpec.columns && uiSpec.columns.length >= 2) {
      // Build grid-template-columns from column widths
      const gridTemplateColumns = uiSpec.columns
        .map(col => {
          const w = col.width || '1fr';
          // Convert percentages to fr units for better grid behavior
          if (w.endsWith('%')) {
            const pct = parseFloat(w);
            return `${pct}fr`;
          }
          return w;
        })
        .join(' ');

      return (
        <div
          className="checkpoint-layout two-column"
          style={{ gridTemplateColumns }}
        >
          {uiSpec.columns.map((col, colIdx) => (
            <div
              key={colIdx}
              className={`checkpoint-column ${col.sticky ? 'sticky' : ''}`}
            >
              {(col.sections || []).map((section, sIdx) =>
                renderSection(section, checkpoint, `${colIdx}-${sIdx}`)
              )}
            </div>
          ))}
        </div>
      );
    }

    // =======================================================================
    // VERTICAL LAYOUT (sections array)
    // =======================================================================
    if (uiSpec.sections && uiSpec.sections.length > 0) {
      const sections = uiSpec.sections;
      const hasInput = hasInputSection(sections);

      return (
        <div className="checkpoint-layout vertical">
          {sections.map((section, idx) =>
            renderSection(section, checkpoint, idx)
          )}

          {/* If no input section in sections, add default based on type */}
          {!hasInput && (
            renderSection(
              { type: type === 'choice' ? 'choice' : 'confirmation', prompt: uiSpec.prompt },
              checkpoint,
              'fallback-input'
            )
          )}
        </div>
      );
    }

    // =======================================================================
    // LEGACY FALLBACK (no sections, use old logic)
    // =======================================================================
    return renderLegacyContent(checkpoint, type, isSubmitting);
  };

  /**
   * Legacy content renderer for backward compatibility
   */
  const renderLegacyContent = (checkpoint, type, isSubmitting) => {
    const uiSpec = checkpoint.ui_spec || {};

    return (
      <div className="checkpoint-layout vertical legacy">
        {/* Phase output preview */}
        <div className="checkpoint-output">
          <div className="output-label">Phase Output:</div>
          <div className="output-content">
            {checkpoint.phase_output_preview || checkpoint.phase_output || 'No output available'}
          </div>
        </div>

        {/* Prompt */}
        {uiSpec.prompt && (
          <div className="checkpoint-prompt">{uiSpec.prompt}</div>
        )}

        {/* Title */}
        {uiSpec.title && (
          <div className="checkpoint-title-text">{uiSpec.title}</div>
        )}

        {/* Legacy input rendering */}
        {renderLegacyInputUI(checkpoint, type, isSubmitting)}
      </div>
    );
  };

  /**
   * Legacy input UI for backward compatibility
   */
  const renderLegacyInputUI = (checkpoint, type, isSubmitting) => {
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

    // Other legacy types would go here...
    // For now, fall back to confirmation
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

  // ==========================================================================
  // MAIN RENDER
  // ==========================================================================

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
                <span className="checkpoint-phase">Phase: {checkpoint.cell_name}</span>
              </div>
              <span className="checkpoint-expand">
                {expandedCheckpoint === checkpoint.id ? '▼' : '▶'}
              </span>
            </div>

            {expandedCheckpoint === checkpoint.id && (
              <div className="checkpoint-details">
                {/* For audible checkpoints, link to audible feedback view */}
                {checkpoint.checkpoint_type === 'audible' ? (
                  <div className="audible-link">
                    <p className="audible-message">
                      <Icon icon="mdi:bullhorn" width="16" style={{ marginRight: '6px' }} />
                      Cascade is paused for feedback
                    </p>
                    <button
                      className="open-audible-btn"
                      onClick={() => {
                        sessionStorage.setItem('checkpointReturnPath', window.location.hash);
                        window.location.hash = `#/checkpoint/${checkpoint.id}`;
                      }}
                    >
                      Provide Feedback →
                    </button>
                  </div>
                ) : checkpoint.checkpoint_type === 'sounding_eval' ? (
                  <div className="sounding-eval-link">
                    <p className="sounding-eval-message">
                      {checkpoint.sounding_outputs?.length || checkpoint.ui_spec?.num_soundings || 'Multiple'} sounding attempts ready for comparison
                    </p>
                    <button
                      className="open-comparison-btn"
                      onClick={() => {
                        // Store current location so we can return after checkpoint completion
                        sessionStorage.setItem('checkpointReturnPath', window.location.hash);
                        window.location.hash = `#/checkpoint/${checkpoint.id}`;
                      }}
                    >
                      Open Comparison View →
                    </button>
                  </div>
                ) : (
                  <>
                    {/* UI Spec Title (if present) */}
                    {checkpoint.ui_spec?.title && (
                      <div className="checkpoint-title-text">
                        {checkpoint.ui_spec.title}
                      </div>
                    )}

                    {/* Main content area with layout support */}
                    {renderContent(checkpoint)}

                    {/* Reasoning capture (if enabled) */}
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
                  </>
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
