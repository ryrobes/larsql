/**
 * ContextDropPicker - Quick picker that appears when dropping a phase output
 * onto the Context drawer toggle.
 *
 * Lets user choose the include mode:
 * - Output only
 * - Full messages
 * - Output + Images
 */

import React, { useEffect, useRef } from 'react';
import { Icon } from '@iconify/react';
import './ContextDropPicker.css';

const INCLUDE_OPTIONS = [
  {
    id: 'output_only',
    label: 'Output only',
    description: 'Just the final output text',
    icon: 'mdi:text',
    include: ['output'],
  },
  {
    id: 'output_images',
    label: 'Output + Images',
    description: 'Output text and any generated images',
    icon: 'mdi:image-text',
    include: ['output', 'images'],
    recommended: true,
  },
  {
    id: 'full_messages',
    label: 'Full messages',
    description: 'Complete conversation history',
    icon: 'mdi:message-text-outline',
    include: ['messages'],
  },
  {
    id: 'everything',
    label: 'Everything',
    description: 'Output, images, messages, and state',
    icon: 'mdi:select-all',
    include: ['output', 'images', 'messages', 'state'],
  },
];

function ContextDropPicker({ phaseName, position, onSelect, onCancel }) {
  const pickerRef = useRef(null);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        onCancel();
      }
    };

    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onCancel();
      }
    };

    // Delay adding listeners to avoid immediate trigger from drop
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onCancel]);

  // Position the picker near the drop point, but keep it on screen
  const style = {
    position: 'fixed',
    left: Math.min(position.x, window.innerWidth - 260),
    top: Math.min(position.y, window.innerHeight - 280),
    zIndex: 10000,
  };

  return (
    <div className="context-drop-picker" style={style} ref={pickerRef}>
      <div className="picker-header">
        <Icon icon="mdi:link-variant" width="14" />
        <span>Add context from <strong>{phaseName}</strong></span>
      </div>

      <div className="picker-options">
        {INCLUDE_OPTIONS.map((option) => (
          <button
            key={option.id}
            className={`picker-option ${option.recommended ? 'recommended' : ''}`}
            onClick={() => onSelect(option.include)}
          >
            <Icon icon={option.icon} width="18" className="option-icon" />
            <div className="option-content">
              <span className="option-label">
                {option.label}
                {option.recommended && <span className="rec-badge">Recommended</span>}
              </span>
              <span className="option-desc">{option.description}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="picker-footer">
        <button className="cancel-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export default ContextDropPicker;
