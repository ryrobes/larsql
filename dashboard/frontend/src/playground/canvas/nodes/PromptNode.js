import React, { useCallback, useState, useRef, useEffect, memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import usePlaygroundStore from '../../stores/playgroundStore';
import useNodeResize from '../hooks/useNodeResize';
import './PromptNode.css';

// Default dimensions (grid-aligned to 16px)
const DEFAULT_WIDTH = 224;  // 14 * 16
const DEFAULT_HEIGHT = 128; // 8 * 16

/**
 * PromptNode - Text input node for prompts
 *
 * Has a source handle (right) to connect to generators.
 * Output type: text (green handle)
 * Resizable via bottom-right corner drag.
 * Double-click header to rename.
 */
function PromptNode({ id, data, selected }) {
  const updateNodeData = usePlaygroundStore(state => state.updateNodeData);
  const removeNode = usePlaygroundStore(state => state.removeNode);

  // Editable name state
  const [isEditingName, setIsEditingName] = useState(false);
  const [editingNameValue, setEditingNameValue] = useState('');
  const nameInputRef = useRef(null);

  // Get display name (custom name or fallback to id)
  const displayName = data.name || 'Prompt';

  // Get dimensions from data or use defaults
  const width = data.width || DEFAULT_WIDTH;
  const height = data.height || DEFAULT_HEIGHT;

  // Resize hook (grid-aligned constraints)
  const { onResizeStart } = useNodeResize(id, {
    minWidth: 176,  // 11 * 16
    minHeight: 96,  // 6 * 16
    maxWidth: 512,  // 32 * 16
    maxHeight: 400, // 25 * 16
  });

  const handleTextChange = useCallback((e) => {
    updateNodeData(id, { text: e.target.value });
  }, [id, updateNodeData]);

  const handleDelete = useCallback((e) => {
    e.stopPropagation();
    removeNode(id);
  }, [id, removeNode]);

  // Name editing handlers
  const startEditingName = useCallback((e) => {
    e.stopPropagation();
    setEditingNameValue(data.name || '');
    setIsEditingName(true);
  }, [data.name]);

  const saveName = useCallback(() => {
    const trimmedName = editingNameValue.trim();
    // Only save if changed and valid (alphanumeric + underscore, no spaces)
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


  return (
    <div
      className={`prompt-node ${selected ? 'selected' : ''}`}
      style={{ width, height }}
    >
      {/* Delete button */}
      <button
        className="node-delete-button"
        onClick={handleDelete}
        title="Delete node"
      >
        <Icon icon="mdi:close" width="12" />
      </button>

      <div className="prompt-node-header">
        <div className="prompt-node-icon">
          <Icon icon="mdi:text-box" width="16" />
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
          />
        ) : (
          <span
            className="prompt-node-title"
            onDoubleClick={startEditingName}
            title="Double-click to rename"
          >
            {displayName}
          </span>
        )}
      </div>

      <div className="prompt-node-body">
        <textarea
          className="prompt-textarea"
          value={data.text || ''}
          onChange={handleTextChange}
          placeholder="Enter your prompt..."
          rows={3}
        />
      </div>

      {/* Source handle for text output (green = text type) */}
      <Handle
        type="source"
        position={Position.Right}
        id="text-out"
        className="prompt-handle handle-text"
        title="Text output"
      />

      {/* Resize handle - nodrag class prevents React Flow from dragging */}
      <div
        className="node-resize-handle nodrag"
        onPointerDown={onResizeStart}
      />
    </div>
  );
}

export default memo(PromptNode);
