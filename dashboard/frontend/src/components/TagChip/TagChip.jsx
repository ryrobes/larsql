import React from 'react';
import { Icon } from '@iconify/react';
import './TagChip.css';

/**
 * TagChip - A chip component for displaying a tag
 *
 * @param {string} tagName - The tag name to display
 * @param {string} tagColor - Hex color for the tag
 * @param {string} tagMode - 'instance' or 'dynamic'
 * @param {boolean} removable - Whether to show remove button
 * @param {function} onRemove - Handler when remove is clicked
 * @param {string} size - 'sm' | 'md' | 'lg' (default: 'md')
 * @param {boolean} clickable - Whether the chip is clickable
 * @param {function} onClick - Handler when chip is clicked
 */
const TagChip = ({
  tagName,
  tagColor = '#a78bfa',
  tagMode,
  removable = false,
  onRemove,
  size = 'md',
  clickable = false,
  onClick,
}) => {
  const handleRemove = (e) => {
    e.stopPropagation();
    if (onRemove) {
      onRemove();
    }
  };

  const handleClick = () => {
    if (clickable && onClick) {
      onClick();
    }
  };

  return (
    <span
      className={`tag-chip tag-chip-${size} ${clickable ? 'tag-chip-clickable' : ''}`}
      style={{ '--tag-color': tagColor }}
      onClick={handleClick}
    >
      <span className="tag-chip-dot" />
      <span className="tag-chip-name">{tagName}</span>
      {tagMode === 'dynamic' && (
        <Icon
          icon="mdi:refresh-auto"
          className="tag-chip-dynamic-icon"
          title="Dynamic - auto-updates to latest"
        />
      )}
      {removable && (
        <button
          type="button"
          className="tag-chip-remove"
          onClick={handleRemove}
          title="Remove tag"
        >
          <Icon icon="mdi:close" />
        </button>
      )}
    </span>
  );
};

/**
 * TagChipList - A list of tag chips
 *
 * @param {array} tags - Array of tag objects [{tag_name, tag_color, tag_mode, tag_id}]
 * @param {boolean} removable - Whether tags can be removed
 * @param {function} onRemove - Handler when a tag is removed (receives tag_id)
 * @param {string} size - Size for all chips
 * @param {string} emptyMessage - Message when no tags
 */
export const TagChipList = ({
  tags = [],
  removable = false,
  onRemove,
  size = 'md',
  emptyMessage,
}) => {
  if (tags.length === 0 && emptyMessage) {
    return <span className="tag-chip-list-empty">{emptyMessage}</span>;
  }

  return (
    <div className="tag-chip-list">
      {tags.map((tag) => (
        <TagChip
          key={tag.tag_id || tag.tag_name}
          tagName={tag.tag_name}
          tagColor={tag.tag_color}
          tagMode={tag.tag_mode}
          removable={removable}
          onRemove={onRemove ? () => onRemove(tag.tag_id) : undefined}
          size={size}
        />
      ))}
    </div>
  );
};

export default TagChip;
