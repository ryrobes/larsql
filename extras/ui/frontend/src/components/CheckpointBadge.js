import React, { useState } from 'react';
import './CheckpointBadge.css';

/**
 * CheckpointBadge - Notification badge for pending HITL checkpoints
 *
 * Shows a floating badge in the corner with checkpoint count.
 * Clicking opens a dropdown to select which checkpoint to respond to.
 */
function CheckpointBadge({ checkpoints, onSelectCheckpoint }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!checkpoints || checkpoints.length === 0) {
    return null;
  }

  const toggleExpanded = () => setIsExpanded(!isExpanded);

  const handleSelect = (checkpoint) => {
    setIsExpanded(false);
    if (onSelectCheckpoint) {
      onSelectCheckpoint(checkpoint);
    }
  };

  // Sort by timeout (most urgent first)
  const sortedCheckpoints = [...checkpoints].sort((a, b) => {
    if (!a.timeout_at && !b.timeout_at) return 0;
    if (!a.timeout_at) return 1;
    if (!b.timeout_at) return -1;
    return new Date(a.timeout_at) - new Date(b.timeout_at);
  });

  const mostUrgent = sortedCheckpoints[0];
  const timeRemaining = mostUrgent?.timeout_at
    ? Math.max(0, Math.floor((new Date(mostUrgent.timeout_at) - new Date()) / 1000))
    : null;

  const isUrgent = timeRemaining !== null && timeRemaining < 60;

  return (
    <div className={`checkpoint-badge-container ${isUrgent ? 'urgent' : ''}`}>
      {/* Main Badge */}
      <button
        className={`checkpoint-badge ${isExpanded ? 'expanded' : ''}`}
        onClick={toggleExpanded}
        title={`${checkpoints.length} checkpoint${checkpoints.length > 1 ? 's' : ''} waiting`}
      >
        <span className="badge-icon">✋</span>
        <span className="badge-count">{checkpoints.length}</span>
        {timeRemaining !== null && timeRemaining <= 300 && (
          <span className="badge-timer">
            {Math.floor(timeRemaining / 60)}:{(timeRemaining % 60).toString().padStart(2, '0')}
          </span>
        )}
      </button>

      {/* Dropdown Menu */}
      {isExpanded && (
        <div className="checkpoint-dropdown">
          <div className="dropdown-header">
            <span className="dropdown-title">Pending Checkpoints</span>
            <button className="dropdown-close" onClick={() => setIsExpanded(false)}>×</button>
          </div>
          <div className="dropdown-list">
            {sortedCheckpoints.map((checkpoint) => (
              <CheckpointItem
                key={checkpoint.id}
                checkpoint={checkpoint}
                onSelect={() => handleSelect(checkpoint)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Single checkpoint item in the dropdown
 */
function CheckpointItem({ checkpoint, onSelect }) {
  const typeLabels = {
    'phase_input': 'Input Required',
    'sounding_eval': 'Compare Outputs',
    'form': 'Form',
    'approval': 'Approval'
  };

  const typeIcons = {
    'phase_input': '✍️',
    'sounding_eval': '⚖️',
    'form': '📝',
    'approval': '✓'
  };

  const timeRemaining = checkpoint.timeout_at
    ? Math.max(0, Math.floor((new Date(checkpoint.timeout_at) - new Date()) / 1000))
    : null;

  const isUrgent = timeRemaining !== null && timeRemaining < 60;

  return (
    <button className={`checkpoint-item ${isUrgent ? 'urgent' : ''}`} onClick={onSelect}>
      <div className="item-header">
        <span className="item-icon">
          {typeIcons[checkpoint.checkpoint_type] || '✋'}
        </span>
        <span className="item-type">
          {typeLabels[checkpoint.checkpoint_type] || checkpoint.checkpoint_type}
        </span>
        {timeRemaining !== null && (
          <span className={`item-timer ${isUrgent ? 'urgent' : ''}`}>
            {Math.floor(timeRemaining / 60)}:{(timeRemaining % 60).toString().padStart(2, '0')}
          </span>
        )}
      </div>
      <div className="item-details">
        <span className="item-phase">{checkpoint.phase_name}</span>
        <span className="item-cascade">{checkpoint.cascade_id}</span>
      </div>
      {checkpoint.num_soundings && (
        <div className="item-soundings">
          {checkpoint.num_soundings} outputs to compare
        </div>
      )}
    </button>
  );
}

export default CheckpointBadge;
