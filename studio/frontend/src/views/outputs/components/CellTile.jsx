import React from 'react';
import { Icon } from '@iconify/react';
import './CellTile.css';
import { API_BASE_URL } from '../../../config/api';

/**
 * Get base content type (handles hierarchical types like 'tool_call:request_decision')
 */
const getBaseContentType = (contentType) => {
  if (!contentType) return 'text';
  return contentType.includes(':') ? contentType.split(':')[0] : contentType;
};

/**
 * Get tool name from tool_call type (e.g., 'tool_call:request_decision' -> 'request_decision')
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
    case 'tool_call':
      return 'mdi:tools';
    case 'markdown':
      return 'mdi:language-markdown';
    case 'json':
      return 'mdi:code-json';
    case 'error':
      return 'mdi:alert-circle';
    default:
      return 'mdi:text';
  }
};

/**
 * Get color for content type
 */
const getContentTypeColor = (contentType) => {
  const baseType = getBaseContentType(contentType);

  switch (baseType) {
    case 'image':
      return 'var(--color-accent-pink)';
    case 'chart':
      return 'var(--color-accent-green)';
    case 'table':
      return 'var(--color-accent-yellow)';
    case 'tool_call':
      return 'var(--color-accent-orange)';
    case 'markdown':
      return 'var(--color-accent-purple)';
    case 'json':
      return 'var(--color-accent-blue)';
    case 'error':
      return 'var(--color-error)';
    default:
      return 'var(--color-accent-cyan)';
  }
};

/**
 * Format cost
 */
const formatCost = (cost) => {
  if (!cost || cost === 0) return '';
  if (cost < 0.001) return `$${cost.toFixed(5)}`;
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(3)}`;
};

/**
 * Get first image URL from images array or metadata
 */
const getImageUrl = (images, content) => {
  // Check images array
  if (images && images.length > 0) {
    const img = images[0];
    if (typeof img === 'string') {
      return img.startsWith('http') ? img : `${API_BASE_URL}${img}`;
    }
    if (img.url) {
      return img.url.startsWith('http') ? img.url : `${API_BASE_URL}${img.url}`;
    }
  }
  // Check if content has image URL
  if (content && typeof content === 'object' && content.url) {
    return content.url.startsWith('http') ? content.url : `${API_BASE_URL}${content.url}`;
  }
  return null;
};

/**
 * Simple markdown-like rendering for preview
 */
const renderMarkdownPreview = (text) => {
  if (!text || typeof text !== 'string') return text;

  // Split into lines and process
  const lines = text.split('\n').slice(0, 12); // Max 12 lines

  return lines.map((line, idx) => {
    // Headers
    if (line.startsWith('### ')) {
      return <div key={idx} className="preview-h3">{line.slice(4)}</div>;
    }
    if (line.startsWith('## ')) {
      return <div key={idx} className="preview-h2">{line.slice(3)}</div>;
    }
    if (line.startsWith('# ')) {
      return <div key={idx} className="preview-h1">{line.slice(2)}</div>;
    }
    // Bold
    if (line.includes('**')) {
      const parts = line.split(/\*\*(.*?)\*\*/g);
      return (
        <div key={idx} className="preview-line">
          {parts.map((part, i) =>
            i % 2 === 1 ? <strong key={i}>{part}</strong> : part
          )}
        </div>
      );
    }
    // List items
    if (line.startsWith('- ') || line.startsWith('* ')) {
      return <div key={idx} className="preview-list-item">{line.slice(2)}</div>;
    }
    if (/^\d+\.\s/.test(line)) {
      return <div key={idx} className="preview-list-item">{line}</div>;
    }
    // Code blocks (just show as mono)
    if (line.startsWith('```')) {
      return <div key={idx} className="preview-code-fence">...</div>;
    }
    // Empty lines
    if (line.trim() === '') {
      return <div key={idx} className="preview-spacer" />;
    }
    // Regular text
    return <div key={idx} className="preview-line">{line}</div>;
  });
};

/**
 * Render JSON preview
 */
const renderJsonPreview = (content) => {
  if (!content) return null;

  try {
    const json = typeof content === 'string' ? JSON.parse(content) : content;
    const formatted = JSON.stringify(json, null, 2);
    const lines = formatted.split('\n').slice(0, 10);
    return (
      <pre className="preview-json">
        {lines.join('\n')}
        {formatted.split('\n').length > 10 && '\n...'}
      </pre>
    );
  } catch {
    return <pre className="preview-json">{String(content).slice(0, 300)}</pre>;
  }
};

/**
 * Render table preview
 */
const renderTablePreview = (content) => {
  if (!content || typeof content !== 'object') return null;

  const { rows, columns } = content;
  if (!rows || !columns) return null;

  const displayRows = rows.slice(0, 4);
  const displayCols = columns.slice(0, 4);

  return (
    <div className="preview-table">
      <div className="preview-table-header">
        {displayCols.map((col, i) => (
          <div key={i} className="preview-table-cell header">{col}</div>
        ))}
        {columns.length > 4 && <div className="preview-table-cell more">...</div>}
      </div>
      {displayRows.map((row, ri) => (
        <div key={ri} className="preview-table-row">
          {displayCols.map((col, ci) => (
            <div key={ci} className="preview-table-cell">
              {String(Array.isArray(row) ? row[ci] : row[col] ?? '').slice(0, 15)}
            </div>
          ))}
        </div>
      ))}
      {rows.length > 4 && (
        <div className="preview-table-more">+{rows.length - 4} more rows</div>
      )}
    </div>
  );
};

/**
 * ContentPreview - Renders actual content based on type
 */
const ContentPreview = ({ content, contentType, images }) => {
  const imageUrl = getImageUrl(images, content);

  // Image content
  if (imageUrl) {
    return (
      <div className="preview-image">
        <img src={imageUrl} alt="preview" />
      </div>
    );
  }

  // Table content
  if (contentType === 'table' || (content && typeof content === 'object' && content.rows)) {
    return renderTablePreview(content);
  }

  // JSON content
  if (contentType === 'json' || (content && typeof content === 'object' && !content.rows)) {
    return renderJsonPreview(content);
  }

  // Markdown/text content
  if (typeof content === 'string') {
    return (
      <div className="preview-markdown">
        {renderMarkdownPreview(content)}
      </div>
    );
  }

  return null;
};

/**
 * CellTile - A single cell output preview tile with rendered content
 *
 * @param {object} cell - Cell data (latest output when grouped)
 * @param {function} onClick - Click handler
 * @param {boolean} compact - Compact display mode
 * @param {number} outputCount - Number of outputs for this cell (for grouped display)
 */
const CellTile = ({ cell, onClick, compact = false, outputCount = 1 }) => {
  const {
    cell_name,
    cell_index,
    content_type,
    content,
    preview,
    cost,
    starred,
    images,
  } = cell;

  const hasMultipleOutputs = outputCount > 1;

  const icon = getContentTypeIcon(content_type);
  const color = getContentTypeColor(content_type);
  const toolName = getToolName(content_type);
  const hasContent = content || (images && images.length > 0);

  return (
    <div
      className={`cell-tile ${compact ? 'compact' : ''} ${starred ? 'starred' : ''} ${hasMultipleOutputs ? 'has-stack' : ''}`}
      onClick={onClick}
      style={{ '--tile-accent': color }}
    >
      {/* Stack indicator for multiple outputs */}
      {hasMultipleOutputs && (
        <div className="cell-tile-stack" title={`${outputCount} outputs`}>
          <div className="stack-layer" />
          <div className="stack-layer" />
        </div>
      )}

      {/* Header with name and type icon */}
      <div className="cell-tile-header">
        <div className="cell-tile-index">{cell_index !== undefined ? cell_index + 1 : '?'}</div>
        <Icon icon={icon} width="14" className="cell-tile-type-icon" />
        <span className="cell-tile-name" title={cell_name}>{cell_name}</span>
        {toolName && (
          <span className="cell-tile-tool-badge" title={`Tool: ${toolName}`}>
            {toolName}
          </span>
        )}
        {hasMultipleOutputs && (
          <span className="cell-tile-output-count" title={`${outputCount} outputs from this cell`}>
            {outputCount}
          </span>
        )}
      </div>

      {/* Content preview area */}
      <div className="cell-tile-content">
        {hasContent ? (
          <ContentPreview
            content={content}
            contentType={content_type}
            images={images}
          />
        ) : preview ? (
          <div className="preview-text">{preview}</div>
        ) : (
          <div className="preview-empty">
            <Icon icon={icon} width="24" />
          </div>
        )}
      </div>

      {/* Cost badge */}
      {cost > 0 && (
        <div className="cell-tile-cost">
          {formatCost(cost)}
        </div>
      )}

      {/* Starred indicator */}
      {starred && (
        <div className="cell-tile-star">
          <Icon icon="mdi:star" width="12" />
        </div>
      )}
    </div>
  );
};

export default CellTile;
