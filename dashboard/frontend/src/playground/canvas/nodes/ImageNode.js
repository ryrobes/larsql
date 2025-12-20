import React, { memo, useCallback } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import usePlaygroundStore from '../../stores/playgroundStore';
import './ImageNode.css';

/**
 * ImageNode - Image generation/transformation node
 *
 * Displays:
 * - Node type icon and name from palette
 * - Status indicator (idle/running/completed/error)
 * - Generated image thumbnail (when completed)
 * - Cost and duration (when available)
 * - Play button for "run from here" (when cached results available)
 *
 * Handles:
 * - Target (left-top) for prompt input
 * - Target (left-bottom) for image input (optional, for image-to-image)
 * - Source (right) for image output
 */
function ImageNode({ id, data, selected }) {
  const runFromNode = usePlaygroundStore((state) => state.runFromNode);
  const lastSuccessfulSessionId = usePlaygroundStore((state) => state.lastSuccessfulSessionId);
  const executionStatus = usePlaygroundStore((state) => state.executionStatus);

  // Handle "Run from here" action
  const handleRunFromHere = useCallback(async (e) => {
    e.stopPropagation(); // Prevent node selection
    const result = await runFromNode(id);
    if (!result.success) {
      console.error('[ImageNode] Run from here failed:', result.error);
    }
  }, [id, runFromNode]);

  const {
    paletteName,
    paletteIcon,
    paletteColor,
    status = 'idle',
    images = [],
    cost,
    duration,
  } = data;

  // Format cost for display
  const formatCost = (cost) => {
    if (!cost) return null;
    if (cost < 0.01) return '<$0.01';
    return `$${cost.toFixed(3)}`;
  };

  // Format duration for display
  const formatDuration = (ms) => {
    if (!ms) return null;
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const statusConfig = {
    idle: { icon: 'mdi:circle-outline', label: 'Ready', className: 'idle' },
    pending: { icon: 'mdi:clock-outline', label: 'Pending', className: 'pending' },
    running: { icon: 'mdi:loading', label: 'Running...', className: 'running' },
    completed: { icon: 'mdi:check-circle', label: 'Done', className: 'completed' },
    error: { icon: 'mdi:alert-circle', label: 'Error', className: 'error' },
  };

  const statusInfo = statusConfig[status] || statusConfig.idle;
  const hasImages = images.length > 0;

  const formattedCost = formatCost(cost);
  const formattedDuration = formatDuration(duration);
  const showFooter = status === 'completed' && (formattedCost || formattedDuration);

  const canRunFromHere = lastSuccessfulSessionId && executionStatus !== 'running';

  return (
    <div
      className={`image-node ${selected ? 'selected' : ''} status-${status}`}
      style={{ borderColor: paletteColor }}
    >
      {/* Play button - run from this node using cached upstream results */}
      {canRunFromHere && (
        <button
          className="node-play-button"
          onClick={handleRunFromHere}
          title="Run from here (use cached upstream results)"
        >
          <Icon icon="mdi:play" width="14" />
        </button>
      )}

      {/* Target handle for prompt input (top-left) */}
      <Handle
        type="target"
        position={Position.Left}
        id="prompt"
        className="image-handle input-handle prompt-handle"
        style={{ top: '30%' }}
        title="Prompt input"
      />

      {/* Target handle for image input (bottom-left) - for image-to-image */}
      <Handle
        type="target"
        position={Position.Left}
        id="image"
        className="image-handle input-handle image-input-handle"
        style={{ top: '70%' }}
        title="Image input (optional)"
      />

      <div className="image-node-header" style={{ backgroundColor: `${paletteColor}15` }}>
        <div
          className="image-node-icon"
          style={{ backgroundColor: `${paletteColor}20`, color: paletteColor }}
        >
          <Icon icon={paletteIcon || 'mdi:image'} width="18" />
        </div>
        <span className="image-node-title">{paletteName || 'Image'}</span>
        <div className={`image-node-status ${statusInfo.className}`}>
          <Icon
            icon={statusInfo.icon}
            width="14"
            className={status === 'running' ? 'spinning' : ''}
          />
        </div>
      </div>

      <div className="image-node-body">
        {hasImages ? (
          <div className="image-preview">
            <img
              src={`http://localhost:5001${images[0]}`}
              alt="Generated"
              className="preview-image"
            />
            {images.length > 1 && (
              <div className="image-count">+{images.length - 1}</div>
            )}
          </div>
        ) : (
          <div className="image-placeholder">
            <Icon icon="mdi:image-outline" width="32" />
            <span>{status === 'running' ? 'Generating...' : 'No image yet'}</span>
          </div>
        )}
      </div>

      {/* Footer with cost/duration - only shown when completed */}
      {showFooter && (
        <div className="image-node-footer">
          {formattedDuration && (
            <span className="footer-stat duration">
              <Icon icon="mdi:timer-outline" width="12" />
              {formattedDuration}
            </span>
          )}
          {formattedCost && (
            <span className="footer-stat cost">
              <Icon icon="mdi:currency-usd" width="12" />
              {formattedCost}
            </span>
          )}
        </div>
      )}

      {/* Source handle for image output */}
      <Handle
        type="source"
        position={Position.Right}
        id="output"
        className="image-handle output-handle"
        style={{ backgroundColor: paletteColor }}
      />
    </div>
  );
}

export default memo(ImageNode);
