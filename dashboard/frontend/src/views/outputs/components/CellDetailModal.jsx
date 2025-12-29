import React from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import RichMarkdown from '../../../components/RichMarkdown';
import DynamicUI from '../../../components/DynamicUI';
import './CellDetailModal.css';

/**
 * Get base content type (handles hierarchical types like tool_call:request_decision)
 */
const getBaseContentType = (contentType) => {
  if (!contentType) return 'text';
  return contentType.includes(':') ? contentType.split(':')[0] : contentType;
};

/**
 * Get tool name from hierarchical content type
 */
const getToolName = (contentType) => {
  if (!contentType || !contentType.startsWith('tool_call:')) return null;
  return contentType.split(':')[1];
};

/**
 * Get icon for content type
 */
const getContentTypeIcon = (contentType) => {
  const baseType = getBaseContentType(contentType);

  switch (baseType) {
    case 'image':
      return 'mdi:image';
    case 'chart':
      return 'mdi:chart-line';
    case 'table':
      return 'mdi:table';
    case 'markdown':
      return 'mdi:language-markdown';
    case 'json':
      return 'mdi:code-json';
    case 'tool_call':
      return 'mdi:tools';
    case 'error':
      return 'mdi:alert-circle';
    default:
      return 'mdi:text';
  }
};

/**
 * Extract tool call data from content (handles various encodings)
 * - Direct object with tool property
 * - JSON string with tool property
 * - Markdown code block containing tool call JSON
 * - Double-encoded JSON (string literal containing JSON string)
 */
const extractToolCall = (content) => {
  if (!content) return null;

  // If already an object with tool property
  if (typeof content === 'object' && content.tool) {
    return content;
  }

  // If string, try various extraction methods
  if (typeof content === 'string') {
    let workingContent = content;

    // Check if the entire content is a JSON string literal (starts with quote)
    // This handles double-encoded JSON like: "\"```json\\n{...}```\""
    if (workingContent.startsWith('"') && workingContent.endsWith('"')) {
      try {
        workingContent = JSON.parse(workingContent);
      } catch (e) {
        // Not a JSON string, continue with original
      }
    }

    // Try to extract from markdown code block
    const codeBlockMatch = workingContent.match(/```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```/);
    if (codeBlockMatch) {
      try {
        const parsed = JSON.parse(codeBlockMatch[1]);
        if (parsed.tool) return parsed;
      } catch (e) {
        // Continue to other methods
      }
    }

    // Try direct JSON parse
    try {
      const parsed = JSON.parse(workingContent);
      if (parsed.tool) return parsed;
      // If parsed is a string, it might be double-encoded
      if (typeof parsed === 'string') {
        return extractToolCall(parsed); // Recursive call to unwrap
      }
    } catch (e) {
      // Not JSON
    }

    // Try to find JSON object anywhere in the string (less strict)
    const jsonMatch = workingContent.match(/\{[^{}]*"tool"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0]);
        if (parsed.tool) return parsed;
      } catch (e) {
        // Continue
      }
    }
  }

  return null;
};

/**
 * Convert request_decision tool call to DynamicUI spec
 */
const convertRequestDecisionToUISpec = (toolCall) => {
  if (!toolCall?.arguments) return null;

  const args = toolCall.arguments;
  const sections = [];

  // Add context if present
  if (args.context) {
    sections.push({
      type: 'text',
      content: args.context,
      style: 'muted'
    });
  }

  // Add question as header
  if (args.question) {
    sections.push({
      type: 'header',
      text: args.question,
      level: 3
    });
  }

  // Add options as choice section
  if (args.options && args.options.length > 0) {
    sections.push({
      type: 'choice',
      label: 'Options',
      options: args.options.map(opt => ({
        value: opt.id || opt.label,
        label: opt.label,
        description: opt.description
      }))
    });
  }

  return {
    title: 'Human Decision Request',
    sections
  };
};

/**
 * Format cost
 */
const formatCost = (cost) => {
  if (!cost || cost === 0) return '$0.00';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
};

/**
 * Format timestamp
 */
const formatTimestamp = (timestamp) => {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleString();
};

/**
 * Tool Call Renderer - Renders tool calls with special handling for request_decision
 */
const ToolCallRenderer = ({ content, contentType }) => {
  const toolCall = extractToolCall(content);
  const toolName = getToolName(contentType) || toolCall?.tool;

  // Special rendering for request_decision
  if (toolName === 'request_decision' && toolCall) {
    const uiSpec = convertRequestDecisionToUISpec(toolCall);
    if (uiSpec) {
      return (
        <div className="cell-detail-request-decision">
          <div className="request-decision-header">
            <Icon icon="mdi:account-question" width="20" />
            <span>Human Decision Request</span>
          </div>
          <DynamicUI
            spec={uiSpec}
            onSubmit={() => {}} // Read-only, no submission
            isLoading={false}
          />
          <div className="request-decision-note">
            <Icon icon="mdi:information-outline" width="14" />
            <span>This is a historical view of the decision request</span>
          </div>
        </div>
      );
    }
  }

  // Default tool call rendering - show structured JSON
  if (toolCall) {
    return (
      <div className="cell-detail-tool-call">
        <div className="tool-call-header">
          <Icon icon="mdi:tools" width="16" />
          <span className="tool-name">{toolName || toolCall.tool}</span>
        </div>
        <div className="tool-call-arguments">
          <div className="arguments-label">Arguments:</div>
          <pre>{JSON.stringify(toolCall.arguments, null, 2)}</pre>
        </div>
      </div>
    );
  }

  // Fallback to raw content
  return (
    <div className="cell-detail-json">
      <pre>{typeof content === 'string' ? content : JSON.stringify(content, null, 2)}</pre>
    </div>
  );
};

/**
 * Render content based on type
 */
const ContentRenderer = ({ content, contentType, images }) => {
  const baseType = getBaseContentType(contentType);

  // Handle images
  if (images && images.length > 0) {
    return (
      <div className="cell-detail-images">
        {images.map((img, idx) => (
          <img
            key={idx}
            src={typeof img === 'string' ? `http://localhost:5001${img}` : img.url}
            alt={`Output ${idx + 1}`}
            className="cell-detail-image"
          />
        ))}
      </div>
    );
  }

  // Handle tool calls with special rendering
  if (baseType === 'tool_call') {
    return <ToolCallRenderer content={content} contentType={contentType} />;
  }

  // Handle string content
  if (typeof content === 'string') {
    // Check if it looks like markdown
    if (contentType === 'markdown' || content.includes('#') || content.includes('**') || content.includes('```')) {
      return (
        <div className="cell-detail-markdown">
          <RichMarkdown>{content}</RichMarkdown>
        </div>
      );
    }

    // Plain text
    return (
      <div className="cell-detail-text">
        <pre>{content}</pre>
      </div>
    );
  }

  // Handle object/JSON content
  if (typeof content === 'object' && content !== null) {
    // Table data
    if (content.rows && content.columns) {
      return (
        <div className="cell-detail-table">
          <div className="table-meta">
            {content.rows.length} rows × {content.columns.length} columns
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {content.columns.map((col, idx) => (
                    <th key={idx}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {content.rows.slice(0, 50).map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {Array.isArray(row) ? (
                      row.map((cell, cellIdx) => (
                        <td key={cellIdx}>{String(cell)}</td>
                      ))
                    ) : (
                      content.columns.map((col, colIdx) => (
                        <td key={colIdx}>{String(row[col] ?? '')}</td>
                      ))
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {content.rows.length > 50 && (
              <div className="table-truncated">
                Showing 50 of {content.rows.length} rows
              </div>
            )}
          </div>
        </div>
      );
    }

    // Generic JSON
    return (
      <div className="cell-detail-json">
        <pre>{JSON.stringify(content, null, 2)}</pre>
      </div>
    );
  }

  // Fallback
  return (
    <div className="cell-detail-empty">
      <Icon icon="mdi:file-question" width="32" />
      <span>No content to display</span>
    </div>
  );
};

/**
 * CellDetailModal - Full content view for a single cell output
 *
 * @param {boolean} isOpen - Whether modal is visible
 * @param {function} onClose - Close handler
 * @param {object} cellDetail - Cell data to display
 * @param {boolean} loading - Loading state
 * @param {function} navigate - Navigation function
 * @param {number} siblingCount - Total number of outputs in this cell group
 * @param {number} currentIndex - Current output index (0-based)
 * @param {function} onNavigate - Navigate to prev/next output ('prev' | 'next')
 */
const CellDetailModal = ({
  isOpen,
  onClose,
  cellDetail,
  loading,
  navigate,
  siblingCount = 1,
  currentIndex = 0,
  onNavigate,
}) => {
  if (!isOpen) return null;

  const hasMultipleOutputs = siblingCount > 1;
  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex < siblingCount - 1;

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleOpenInStudio = () => {
    if (cellDetail && navigate) {
      navigate('studio', { session: cellDetail.session_id });
      onClose();
    }
  };

  const handleCopyContent = async () => {
    if (!cellDetail?.content) return;

    try {
      const text = typeof cellDetail.content === 'string'
        ? cellDetail.content
        : JSON.stringify(cellDetail.content, null, 2);

      await navigator.clipboard.writeText(text);
      // Could show a toast here
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const modal = (
    <div className="cell-detail-overlay" onClick={handleBackdropClick}>
      <div className="cell-detail-modal">
        {/* Header */}
        <div className="cell-detail-header">
          <div className="cell-detail-header-left">
            {cellDetail && (
              <>
                <Icon
                  icon={getContentTypeIcon(cellDetail.content_type)}
                  width="18"
                  className={`header-type-icon ${getBaseContentType(cellDetail.content_type) === 'tool_call' ? 'tool-call' : ''}`}
                />
                <span className="header-cell-name">{cellDetail.cell_name}</span>
                {getToolName(cellDetail.content_type) && (
                  <span className="header-tool-badge">
                    {getToolName(cellDetail.content_type).replace(/_/g, ' ')}
                  </span>
                )}
                <span className="header-separator">•</span>
                <span className="header-cascade">{cellDetail.cascade_id}</span>
              </>
            )}
          </div>

          {/* Output Navigation (when multiple outputs) */}
          {hasMultipleOutputs && (
            <div className="cell-detail-nav">
              <button
                className="nav-btn"
                onClick={() => onNavigate('prev')}
                disabled={!canGoPrev}
                title="Previous output"
              >
                <Icon icon="mdi:chevron-left" width="20" />
              </button>
              <span className="nav-counter">
                {currentIndex + 1} / {siblingCount}
              </span>
              <button
                className="nav-btn"
                onClick={() => onNavigate('next')}
                disabled={!canGoNext}
                title="Next output"
              >
                <Icon icon="mdi:chevron-right" width="20" />
              </button>
            </div>
          )}

          <button className="cell-detail-close" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Meta */}
        {cellDetail && (
          <div className="cell-detail-meta">
            <span className="meta-session">{cellDetail.session_id}</span>
            <span className="meta-separator">•</span>
            <span className="meta-time">{formatTimestamp(cellDetail.timestamp)}</span>
            <span className="meta-separator">•</span>
            <span className="meta-cost">{formatCost(cellDetail.cost)}</span>
            {cellDetail.model && (
              <>
                <span className="meta-separator">•</span>
                <span className="meta-model">{cellDetail.model}</span>
              </>
            )}
          </div>
        )}

        {/* Content */}
        <div className="cell-detail-content">
          {loading ? (
            <div className="cell-detail-loading">
              <Icon icon="mdi:loading" className="spinning" width="24" />
              <span>Loading content...</span>
            </div>
          ) : cellDetail ? (
            <ContentRenderer
              content={cellDetail.content}
              contentType={cellDetail.content_type}
              images={cellDetail.images}
            />
          ) : (
            <div className="cell-detail-empty">
              <Icon icon="mdi:file-question" width="32" />
              <span>No content available</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="cell-detail-actions">
          <button className="action-btn action-secondary" onClick={handleCopyContent}>
            <Icon icon="mdi:content-copy" width="16" />
            Copy
          </button>
          <button className="action-btn action-secondary" onClick={handleOpenInStudio}>
            <Icon icon="mdi:open-in-new" width="16" />
            Open in Studio
          </button>
          <button className="action-btn action-primary">
            <Icon icon="mdi:star-outline" width="16" />
            Promote
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
};

export default CellDetailModal;
