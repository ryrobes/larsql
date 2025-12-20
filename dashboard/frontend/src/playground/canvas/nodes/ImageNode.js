import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import './ImageNode.css';

/**
 * ImageNode - Image generation/transformation node
 *
 * Displays:
 * - Node type icon and name from palette
 * - Status indicator (idle/running/completed/error)
 * - Generated image thumbnail (when completed)
 *
 * Handles:
 * - Target (left) for prompt input
 * - Source (right) for image output
 */
function ImageNode({ id, data, selected }) {
  const {
    paletteName,
    paletteIcon,
    paletteColor,
    status = 'idle',
    images = [],
  } = data;

  const statusConfig = {
    idle: { icon: 'mdi:circle-outline', label: 'Ready', className: 'idle' },
    pending: { icon: 'mdi:clock-outline', label: 'Pending', className: 'pending' },
    running: { icon: 'mdi:loading', label: 'Running...', className: 'running' },
    completed: { icon: 'mdi:check-circle', label: 'Done', className: 'completed' },
    error: { icon: 'mdi:alert-circle', label: 'Error', className: 'error' },
  };

  const statusInfo = statusConfig[status] || statusConfig.idle;
  const hasImages = images.length > 0;

  return (
    <div
      className={`image-node ${selected ? 'selected' : ''} status-${status}`}
      style={{ borderColor: paletteColor }}
    >
      {/* Target handle for prompt input */}
      <Handle
        type="target"
        position={Position.Left}
        id="input"
        className="image-handle input-handle"
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
