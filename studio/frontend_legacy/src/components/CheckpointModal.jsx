import React from 'react';
import { Icon } from '@iconify/react';
import { Badge } from './index';
import CheckpointRenderer from './CheckpointRenderer';
import './CheckpointModal.css';

/**
 * CheckpointModal - Modal overlay for rendering checkpoints anywhere
 *
 * Can be triggered from any page to show pending HITL checkpoints.
 * Renders checkpoints using universal CheckpointRenderer.
 *
 * Props:
 * - checkpoint: Checkpoint object to render
 * - onSubmit: Callback when user responds
 * - onClose: Callback to close modal
 * - onCancel: Optional callback to cancel checkpoint
 */
const CheckpointModal = ({
  checkpoint,
  onSubmit,
  onClose,
  onCancel,
}) => {
  if (!checkpoint) return null;

  const handleSubmit = async (response) => {
    if (onSubmit) {
      await onSubmit(response);
    }
    onClose();
  };

  const handleCancel = async () => {
    if (onCancel) {
      await onCancel();
    }
    onClose();
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="checkpoint-modal-overlay" onClick={handleOverlayClick}>
      <div className="checkpoint-modal-container">
        {/* Modal Header */}
        <div className="checkpoint-modal-header">
          <div className="modal-header-main">
            <Icon icon="mdi:hand-back-right" width="20" />
            <h2>Human Input Required</h2>
            <Badge variant="label" color="purple" size="sm">
              {checkpoint.checkpoint_type}
            </Badge>
          </div>

          <div className="modal-header-meta">
            <span className="modal-session" title={checkpoint.session_id}>
              {checkpoint.session_id.substring(0, 20)}...
            </span>
            <Icon icon="mdi:chevron-right" width="12" />
            <span className="modal-cascade">{checkpoint.cascade_id}</span>
            {checkpoint.cell_name && (
              <>
                <Icon icon="mdi:chevron-right" width="12" />
                <span className="modal-cell">{checkpoint.cell_name}</span>
              </>
            )}
          </div>

          <button
            className="modal-close-btn"
            onClick={onClose}
            title="Close (checkpoint remains pending)"
          >
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="checkpoint-modal-body">
          <CheckpointRenderer
            checkpoint={checkpoint}
            onSubmit={handleSubmit}
            onCancel={onCancel ? handleCancel : undefined}
            variant="modal"
            showPhaseOutput={true}
          />
        </div>
      </div>
    </div>
  );
};

export default CheckpointModal;
