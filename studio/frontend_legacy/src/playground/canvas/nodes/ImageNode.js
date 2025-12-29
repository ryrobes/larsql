import React, { memo, useCallback, useState, useRef, useEffect } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import usePlaygroundStore from '../../stores/playgroundStore';
import useNodeResize from '../hooks/useNodeResize';
import './ImageNode.css';

// Default dimensions (grid-aligned to 16px)
const DEFAULT_WIDTH = 208;  // 13 * 16
const DEFAULT_HEIGHT = 192; // 12 * 16

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
 * Handles (typed for connection validation):
 * - Target (left-top): text-in - for prompt input (green)
 * - Target (left-bottom): image-in - for image input (purple)
 * - Source (right): image-out - for image output (purple)
 */
function ImageNode({ id, data, selected }) {
  const runFromNode = usePlaygroundStore((state) => state.runFromNode);
  const removeNode = usePlaygroundStore((state) => state.removeNode);
  const updateNodeData = usePlaygroundStore((state) => state.updateNodeData);
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

  // Handle delete
  const handleDelete = useCallback((e) => {
    e.stopPropagation();
    removeNode(id);
  }, [id, removeNode]);

  const {
    paletteName,
    paletteIcon,
    paletteColor,
    status = 'idle',
    images = [],
    cost,
    duration,
    width: dataWidth,
    height: dataHeight,
    name: customName,
  } = data;

  // Editable name state
  const [isEditingName, setIsEditingName] = useState(false);
  const [editingNameValue, setEditingNameValue] = useState('');
  const nameInputRef = useRef(null);

  // Get display name (custom name or fallback to palette name)
  const displayName = customName || paletteName || 'Image';

  // Get dimensions from data or use defaults
  const width = dataWidth || DEFAULT_WIDTH;
  const height = dataHeight || DEFAULT_HEIGHT;

  // Resize hook (grid-aligned constraints)
  const { onResizeStart } = useNodeResize(id, {
    minWidth: 160,  // 10 * 16
    minHeight: 144, // 9 * 16
    maxWidth: 608,  // 38 * 16
    maxHeight: 608, // 38 * 16
  });

  // Name editing handlers
  const startEditingName = useCallback((e) => {
    e.stopPropagation();
    setEditingNameValue(customName || '');
    setIsEditingName(true);
  }, [customName]);

  const saveName = useCallback(() => {
    const trimmedName = editingNameValue.trim();
    // Only save if valid (alphanumeric + underscore, starts with letter)
    if (trimmedName && /^[a-zA-Z][a-zA-Z0-9_]*$/.test(trimmedName)) {
      updateNodeData(id, { name: trimmedName });
    }
    setIsEditingName(false);
  }, [id, editingNameValue, updateNodeData]);

  const cancelEditingName = useCallback(() => {
    setIsEditingName(false);
  }, []);

  const handleNameKeyDown = useCallback((e) => {
    e.stopPropagation();
    if (e.key === 'Enter') {
      saveName();
    } else if (e.key === 'Escape') {
      cancelEditingName();
    }
  }, [saveName, cancelEditingName]);

  // Focus input when editing starts
  useEffect(() => {
    if (isEditingName && nameInputRef.current) {
      nameInputRef.current.focus();
      nameInputRef.current.select();
    }
  }, [isEditingName]);


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
      style={{ borderColor: paletteColor, width, height }}
    >
      {/* Delete button */}
      <button
        className="node-delete-button"
        onClick={handleDelete}
        title="Delete node"
      >
        <Icon icon="mdi:close" width="12" />
      </button>

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

      {/* Target handle for text/prompt input (top-left) - green for text */}
      <Handle
        type="target"
        position={Position.Left}
        id="text-in"
        className="image-handle input-handle handle-text"
        style={{ top: '30%' }}
        title="Text input (prompt)"
      />

      {/* Target handle for image input (bottom-left) - purple for image */}
      <Handle
        type="target"
        position={Position.Left}
        id="image-in"
        className="image-handle input-handle handle-image"
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
        {isEditingName ? (
          <input
            ref={nameInputRef}
            type="text"
            className="node-name-input nodrag"
            value={editingNameValue}
            onChange={(e) => setEditingNameValue(e.target.value)}
            onBlur={saveName}
            onKeyDown={handleNameKeyDown}
            placeholder="Enter name..."
            style={{ borderColor: paletteColor }}
          />
        ) : (
          <span
            className="image-node-title"
            onDoubleClick={startEditingName}
            title="Double-click to rename"
          >
            {displayName}
          </span>
        )}
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
              src={`http://localhost:5050${images[0]}`}
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

      {/* Source handle for image output - purple for image */}
      <Handle
        type="source"
        position={Position.Right}
        id="image-out"
        className="image-handle output-handle handle-image"
        title="Image output"
      />

      {/* Resize handle - nodrag class prevents React Flow from dragging */}
      <div
        className="node-resize-handle nodrag"
        onPointerDown={onResizeStart}
      />
    </div>
  );
}

export default memo(ImageNode);
