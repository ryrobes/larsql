import React from 'react';
import { Icon } from '@iconify/react';
import './AnnotationToolbar.css';

/**
 * AnnotationToolbar - Floating toolbar for drawing controls
 *
 * Positioned at top of annotation area.
 * Contains: Color picker, Size picker, Undo, Clear, Done
 */

// Available colors
const COLORS = [
  { id: 'red', value: '#ef4444', label: 'Red' },
  { id: 'blue', value: '#3b82f6', label: 'Blue' },
  { id: 'green', value: '#22c55e', label: 'Green' },
  { id: 'yellow', value: '#eab308', label: 'Yellow' },
  { id: 'white', value: '#ffffff', label: 'White' },
  { id: 'black', value: '#000000', label: 'Black' },
];

// Available brush sizes
const SIZES = [
  { id: 'small', value: 2, label: 'S' },
  { id: 'medium', value: 5, label: 'M' },
  { id: 'large', value: 10, label: 'L' },
];

function AnnotationToolbar({
  brushColor,
  brushSize,
  onColorChange,
  onSizeChange,
  onUndo,
  onClear,
  onDone,
  onSaveScreenshot,
  canUndo,
  strokeCount,
  isSaving,
  hasSavedScreenshot,
}) {
  return (
    <div className="annotation-toolbar">
      {/* Color picker */}
      <div className="toolbar-section colors">
        <span className="toolbar-label">Color</span>
        <div className="color-buttons">
          {COLORS.map(color => (
            <button
              key={color.id}
              className={`color-btn ${brushColor === color.value ? 'active' : ''}`}
              style={{ backgroundColor: color.value }}
              onClick={() => onColorChange(color.value)}
              title={color.label}
              aria-label={`Select ${color.label}`}
            />
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="toolbar-divider" />

      {/* Size picker */}
      <div className="toolbar-section sizes">
        <span className="toolbar-label">Size</span>
        <div className="size-buttons">
          {SIZES.map(size => (
            <button
              key={size.id}
              className={`size-btn ${brushSize === size.value ? 'active' : ''}`}
              onClick={() => onSizeChange(size.value)}
              title={`${size.label} brush`}
            >
              <span
                className="size-dot"
                style={{ width: size.value * 2, height: size.value * 2 }}
              />
            </button>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="toolbar-divider" />

      {/* Actions */}
      <div className="toolbar-section actions">
        <button
          className="action-btn undo"
          onClick={onUndo}
          disabled={!canUndo}
          title="Undo last stroke"
        >
          <Icon icon="mdi:undo" width="18" />
          <span>Undo</span>
        </button>

        <button
          className="action-btn clear"
          onClick={onClear}
          disabled={strokeCount === 0}
          title="Clear all strokes"
        >
          <Icon icon="mdi:delete-outline" width="18" />
          <span>Clear</span>
        </button>
      </div>

      {/* Divider */}
      <div className="toolbar-divider" />

      {/* Save Screenshot button */}
      <button
        className={`action-btn save-screenshot ${hasSavedScreenshot ? 'saved' : ''}`}
        onClick={onSaveScreenshot}
        disabled={isSaving}
        title={hasSavedScreenshot ? "Screenshot saved! Click to save again" : "Save annotated screenshot"}
      >
        {isSaving ? (
          <>
            <Icon icon="mdi:loading" width="18" className="spinning" />
            <span>Saving...</span>
          </>
        ) : hasSavedScreenshot ? (
          <>
            <Icon icon="mdi:check-circle" width="18" />
            <span>Saved</span>
          </>
        ) : (
          <>
            <Icon icon="mdi:camera" width="18" />
            <span>Save</span>
          </>
        )}
      </button>

      {/* Done button */}
      <button
        className="action-btn done"
        onClick={onDone}
        title="Finish annotating"
      >
        <Icon icon="mdi:check" width="18" />
        <span>Done</span>
      </button>

      {/* Stroke count indicator */}
      {strokeCount > 0 && (
        <div className="stroke-count" title={`${strokeCount} stroke(s)`}>
          {strokeCount}
        </div>
      )}
    </div>
  );
}

export default AnnotationToolbar;
