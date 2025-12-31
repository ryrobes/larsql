import React from 'react';
import DynamicUI from './DynamicUI';
import HTMLSection from './sections/HTMLSection';
import './CheckpointRenderer.css';

/**
 * CheckpointRenderer - Universal checkpoint UI renderer
 *
 * Automatically detects and renders:
 * - DSL UI (text, choice, rating, card_grid, etc.) → DynamicUI
 * - HTMX HTML (custom forms, charts, tables) → HTMLSection
 *
 * Can be embedded anywhere:
 * - Inline in chat/timeline (ResearchCockpit)
 * - Modal overlay (CheckpointModal)
 * - Dedicated page (InterruptsView)
 *
 * Props:
 * - checkpoint: Full checkpoint object with ui_spec
 * - onSubmit: Callback when user submits (receives response object)
 * - onCancel: Optional callback for cancel action
 * - variant: 'inline' | 'modal' | 'page' (affects styling)
 * - showCellOutput: Whether to show the LLM's question/output above UI
 * - isSavedCheckpoint: If true, enables branching mode (ResearchCockpit)
 * - onBranchSubmit: Callback for creating branches from saved checkpoints
 */
const CheckpointRenderer = ({
  checkpoint,
  onSubmit,
  onCancel,
  variant = 'page',
  showCellOutput = true,
  isSavedCheckpoint = false,
  onBranchSubmit,
  className = '',
}) => {
  if (!checkpoint || !checkpoint.ui_spec) {
    return (
      <div className="checkpoint-renderer-error">
        <p>Invalid checkpoint data</p>
      </div>
    );
  }

  // Detect rendering mode
  const hasHTMLSections = checkpoint.ui_spec.sections?.some(s => s.type === 'html');
  const htmlSections = checkpoint.ui_spec.sections?.filter(s => s.type === 'html') || [];

  const containerClass = [
    'checkpoint-renderer',
    `checkpoint-renderer-${variant}`,
    hasHTMLSections ? 'checkpoint-renderer-htmx' : 'checkpoint-renderer-dsl',
    className
  ].filter(Boolean).join(' ');

  return (
    <div className={containerClass}>
      {/* Cell Output (optional) */}
      {showCellOutput && checkpoint.cell_output && (
        <div className="checkpoint-cell-output">
          <div className="cell-output-label">Question</div>
          <div className="cell-output-text">{checkpoint.cell_output}</div>
        </div>
      )}

      {/* UI Rendering */}
      <div className="checkpoint-ui-container">
        {hasHTMLSections ? (
          // HTMX HTML Mode
          htmlSections.map((section, idx) => (
            <HTMLSection
              key={idx}
              spec={section}
              checkpointId={checkpoint.id}
              sessionId={checkpoint.session_id}
              cellName={checkpoint.cell_name}
              cascadeId={checkpoint.cascade_id}
              onSubmit={onSubmit}
              isSavedCheckpoint={isSavedCheckpoint}
              onBranchSubmit={onBranchSubmit}
            />
          ))
        ) : (
          // DSL UI Mode
          <DynamicUI
            spec={checkpoint.ui_spec}
            onSubmit={onSubmit}
            cellOutput={checkpoint.cell_output}
            checkpointId={checkpoint.id}
            sessionId={checkpoint.session_id}
          />
        )}
      </div>

      {/* Cancel button (optional) */}
      {onCancel && variant === 'modal' && (
        <div className="checkpoint-actions">
          <button
            className="checkpoint-cancel-btn"
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
};

export default CheckpointRenderer;
