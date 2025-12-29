import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Modal, { ModalHeader, ModalContent, ModalFooter } from '../Modal/Modal';
import './TagModal.css';

/**
 * Default tag colors matching the design system
 */
const DEFAULT_COLORS = [
  '#a78bfa', // Purple (default)
  '#60a5fa', // Blue
  '#34d399', // Green
  '#fbbf24', // Yellow
  '#f87171', // Red
  '#fb7185', // Pink
  '#f97316', // Orange
  '#06b6d4', // Cyan
];

/**
 * TagModal - Modal for adding/selecting tags for an output
 *
 * @param {boolean} isOpen - Whether modal is visible
 * @param {function} onClose - Close handler
 * @param {object} outputInfo - Information about the output to tag
 *   - message_id: UUID of the specific output
 *   - cascade_id: Cascade identifier
 *   - cell_name: Cell name for dynamic tagging
 * @param {array} availableTags - List of existing tags [{tag_name, tag_color, count}]
 * @param {function} onTagAdded - Callback when tag is successfully added
 * @param {function} onRefreshTags - Optional callback to refresh available tags
 */
const TagModal = ({
  isOpen,
  onClose,
  outputInfo,
  availableTags = [],
  onTagAdded,
  onRefreshTags,
}) => {
  const [tagMode, setTagMode] = useState('instance');
  const [selectedTag, setSelectedTag] = useState('');
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState(DEFAULT_COLORS[0]);
  const [note, setNote] = useState('');
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setTagMode('instance');
      setSelectedTag('');
      setNewTagName('');
      setNewTagColor(DEFAULT_COLORS[0]);
      setNote('');
      setIsCreatingNew(false);
      setError(null);
    }
  }, [isOpen]);

  const handleSubmit = async () => {
    const tagName = isCreatingNew ? newTagName.trim() : selectedTag;

    if (!tagName) {
      setError('Please select or create a tag');
      return;
    }

    if (!outputInfo) {
      setError('No output information provided');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const payload = {
        tag_name: tagName,
        tag_mode: tagMode,
        note: note.trim() || null,
      };

      if (tagMode === 'instance') {
        payload.message_id = outputInfo.message_id;
      } else {
        payload.cascade_id = outputInfo.cascade_id;
        payload.cell_name = outputInfo.cell_name;
      }

      if (isCreatingNew) {
        payload.tag_color = newTagColor;
      }

      const response = await fetch('http://localhost:5001/api/outputs/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to add tag');
      }

      // Success - refresh tags and close
      if (onRefreshTags) {
        await onRefreshTags();
      }
      if (onTagAdded) {
        onTagAdded(data);
      }
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="sm" className="tag-modal">
      <ModalHeader
        title="Tag Output"
        subtitle={outputInfo?.cell_name ? `${outputInfo.cascade_id} / ${outputInfo.cell_name}` : ''}
        icon="mdi:tag-plus"
      />

      <ModalContent>
        {/* Tag Mode Selection */}
        <div className="tag-mode-section">
          <label className="tag-section-label">Tag Mode</label>
          <div className="tag-mode-options">
            <label
              className={`tag-mode-option ${tagMode === 'instance' ? 'active' : ''}`}
            >
              <input
                type="radio"
                name="tagMode"
                value="instance"
                checked={tagMode === 'instance'}
                onChange={(e) => setTagMode(e.target.value)}
              />
              <Icon icon="mdi:pin" width="18" />
              <div className="tag-mode-text">
                <span className="tag-mode-title">This Output</span>
                <span className="tag-mode-desc">Tag this specific version</span>
              </div>
            </label>
            <label
              className={`tag-mode-option ${tagMode === 'dynamic' ? 'active' : ''}`}
            >
              <input
                type="radio"
                name="tagMode"
                value="dynamic"
                checked={tagMode === 'dynamic'}
                onChange={(e) => setTagMode(e.target.value)}
              />
              <Icon icon="mdi:refresh-auto" width="18" />
              <div className="tag-mode-text">
                <span className="tag-mode-title">Latest Output</span>
                <span className="tag-mode-desc">Auto-updates to newest</span>
              </div>
            </label>
          </div>
        </div>

        {/* Tag Selection */}
        <div className="tag-selection-section">
          <label className="tag-section-label">
            {isCreatingNew ? 'New Tag' : 'Select Tag'}
          </label>

          {!isCreatingNew ? (
            <div className="tag-selection-controls">
              <select
                className="tag-select"
                value={selectedTag}
                onChange={(e) => setSelectedTag(e.target.value)}
              >
                <option value="">Choose a tag...</option>
                {availableTags.map((tag) => (
                  <option key={tag.tag_name} value={tag.tag_name}>
                    {tag.tag_name} ({tag.count})
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="tag-new-btn"
                onClick={() => setIsCreatingNew(true)}
              >
                <Icon icon="mdi:plus" width="16" />
                New
              </button>
            </div>
          ) : (
            <div className="tag-create-controls">
              <div className="tag-create-row">
                <input
                  type="text"
                  className="tag-name-input"
                  placeholder="Tag name..."
                  value={newTagName}
                  onChange={(e) => setNewTagName(e.target.value)}
                  onKeyDown={handleKeyDown}
                  autoFocus
                />
                <button
                  type="button"
                  className="tag-cancel-new-btn"
                  onClick={() => {
                    setIsCreatingNew(false);
                    setNewTagName('');
                  }}
                >
                  <Icon icon="mdi:close" width="16" />
                </button>
              </div>
              <div className="tag-color-picker">
                {DEFAULT_COLORS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className={`tag-color-swatch ${newTagColor === color ? 'active' : ''}`}
                    style={{ '--swatch-color': color }}
                    onClick={() => setNewTagColor(color)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Optional Note */}
        <div className="tag-note-section">
          <label className="tag-section-label">Note (optional)</label>
          <textarea
            className="tag-note-input"
            placeholder="Why are you tagging this output?"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
          />
        </div>

        {/* Error display */}
        {error && (
          <div className="tag-error">
            <Icon icon="mdi:alert-circle" width="16" />
            <span>{error}</span>
          </div>
        )}
      </ModalContent>

      <ModalFooter>
        <button
          type="button"
          className="tag-modal-btn tag-modal-btn-secondary"
          onClick={onClose}
          disabled={isSubmitting}
        >
          Cancel
        </button>
        <button
          type="button"
          className="tag-modal-btn tag-modal-btn-primary"
          onClick={handleSubmit}
          disabled={isSubmitting || (!selectedTag && !newTagName.trim())}
        >
          {isSubmitting ? (
            <>
              <Icon icon="mdi:loading" className="spinning" width="16" />
              Adding...
            </>
          ) : (
            <>
              <Icon icon="mdi:tag-plus" width="16" />
              Add Tag
            </>
          )}
        </button>
      </ModalFooter>
    </Modal>
  );
};

export default TagModal;
