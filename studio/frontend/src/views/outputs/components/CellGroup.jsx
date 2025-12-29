import React from 'react';
import { Icon } from '@iconify/react';
import './CellGroup.css';

/**
 * Get base content type (handles hierarchical types like 'tool_call:request_decision')
 */
const getBaseContentType = (contentType) => {
  if (!contentType) return 'text';
  return contentType.includes(':') ? contentType.split(':')[0] : contentType;
};

/**
 * Get tool name from tool_call type
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
 * Get first image URL from images array or metadata
 */
const getImageUrl = (images, content) => {
  if (images && images.length > 0) {
    const img = images[0];
    if (typeof img === 'string') {
      return img.startsWith('http') ? img : `http://localhost:5050${img}`;
    }
    if (img.url) {
      return img.url.startsWith('http') ? img.url : `http://localhost:5050${img.url}`;
    }
  }
  if (content && typeof content === 'object' && content.url) {
    return content.url.startsWith('http') ? content.url : `http://localhost:5050${content.url}`;
  }
  return null;
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
 * Truncate content for mini preview
 */
const truncateContent = (content, maxLength = 80) => {
  if (!content) return '';
  const text = typeof content === 'string' ? content : JSON.stringify(content);
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
};

/**
 * MiniTile - Compact tile for grouped display
 */
const MiniTile = ({ cell, onClick, isFirst }) => {
  const {
    content_type,
    content,
    images,
    cost,
  } = cell;

  const icon = getContentTypeIcon(content_type);
  const color = getContentTypeColor(content_type);
  const toolName = getToolName(content_type);
  const imageUrl = getImageUrl(images, content);
  const preview = truncateContent(content);

  return (
    <div
      className={`cell-group-mini-tile ${isFirst ? 'first' : ''}`}
      onClick={onClick}
      style={{ '--tile-accent': color }}
    >
      {/* Connector line from previous tile */}
      {!isFirst && (
        <div className="mini-tile-connector">
          <div className="connector-line" />
        </div>
      )}

      <div className="mini-tile-content">
        {/* Left: Icon and optional image */}
        <div className="mini-tile-left">
          {imageUrl ? (
            <img src={imageUrl} alt="preview" className="mini-tile-image" />
          ) : (
            <Icon icon={icon} width="14" className="mini-tile-icon" />
          )}
        </div>

        {/* Center: Preview text */}
        <div className="mini-tile-preview">
          {toolName ? (
            <span className="mini-tile-tool">{toolName}</span>
          ) : (
            <span className="mini-tile-text">{preview || 'No content'}</span>
          )}
        </div>

        {/* Right: Cost */}
        {cost > 0 && (
          <span className="mini-tile-cost">{formatCost(cost)}</span>
        )}
      </div>
    </div>
  );
};

/**
 * CellGroup - Displays multiple outputs from the same cell as attached tiles
 *
 * @param {string} cellName - Name of the cell
 * @param {number} cellIndex - Index of the cell in the cascade
 * @param {array} cells - Array of cell outputs
 * @param {function} onCellClick - Click handler (receives message_id)
 */
const CellGroup = ({ cellName, cellIndex, cells, onCellClick }) => {
  const hasMultiple = cells.length > 1;
  const primaryCell = cells[0]; // First/oldest output
  const color = getContentTypeColor(primaryCell?.content_type);
  const icon = getContentTypeIcon(primaryCell?.content_type);
  const toolName = getToolName(primaryCell?.content_type);

  return (
    <div
      className={`cell-group ${hasMultiple ? 'has-multiple' : ''}`}
      style={{ '--group-accent': color }}
    >
      {/* Group header - always visible */}
      <div className="cell-group-header">
        <div className="cell-group-index">{cellIndex + 1}</div>
        <Icon icon={icon} width="14" className="cell-group-icon" />
        <span className="cell-group-name" title={cellName}>{cellName}</span>
        {toolName && (
          <span className="cell-group-tool-badge">{toolName}</span>
        )}
        {hasMultiple && (
          <span className="cell-group-count">{cells.length}</span>
        )}
      </div>

      {/* Output tiles - stacked vertically */}
      <div className="cell-group-tiles">
        {cells.map((cell, idx) => (
          <MiniTile
            key={cell.message_id}
            cell={cell}
            onClick={() => onCellClick(cell.message_id)}
            isFirst={idx === 0}
          />
        ))}
      </div>
    </div>
  );
};

export default CellGroup;
