import React, { useCallback, useState, useRef, useEffect, memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import usePlaygroundStore from '../../stores/playgroundStore';
import useNodeResize from '../hooks/useNodeResize';
import './PromptNode.css';

// Default dimensions (grid-aligned to 16px)
const DEFAULT_WIDTH = 256;  // 16 * 16
const DEFAULT_HEIGHT = 160; // 10 * 16

/**
 * PromptNode - Text input node for prompts with Monaco editor
 *
 * Has a source handle (right) to connect to generators.
 * Output type: text (green handle)
 * Resizable via bottom-right corner drag.
 * Double-click header to rename.
 */
function PromptNode({ id, data, selected }) {
  const updateNodeData = usePlaygroundStore(state => state.updateNodeData);
  const removeNode = usePlaygroundStore(state => state.removeNode);

  const editorRef = useRef(null);

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
    minWidth: 192,  // 12 * 16
    minHeight: 128, // 8 * 16
    maxWidth: 512,  // 32 * 16
    maxHeight: 400, // 25 * 16
  });

  const handleTextChange = useCallback((newValue) => {
    updateNodeData(id, { text: newValue });
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

  // Monaco editor configuration
  const handleEditorDidMount = useCallback((editor) => {
    editorRef.current = editor;
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
    });
  }, []);

  // Custom dark theme - GitHub Dark inspired, pastels on black
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-prompt', {
      base: 'vs-dark',
      inherit: true,
      rules: [],
      colors: {
        'editor.background': '#000000',                   // pure black
        'editor.foreground': '#e6edf3',                   // light gray
        'editor.lineHighlightBackground': '#161b22',
        'editor.selectionBackground': '#264f78',
        'editorLineNumber.foreground': '#6e7681',
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorCursor.foreground': '#7ee787',             // pastel green (prompt accent)
        'editorIndentGuide.background': '#21262d',
        'editorGutter.background': '#000000',
      },
    });
  }, []);

  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 12,
    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
    lineNumbers: 'on',  // Show line numbers for consistency with YAML editor
    lineNumbersMinChars: 2,
    renderLineHighlight: 'line',
    renderLineHighlightOnlyWhenFocus: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    wrappingStrategy: 'advanced',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: false,
    glyphMargin: false,
    lineDecorationsWidth: 8, // Padding between line numbers and content
    padding: { top: 8, bottom: 8 },
    scrollbar: {
      vertical: 'auto',
      horizontal: 'hidden',
      verticalScrollbarSize: 6,
    },
    overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true,
    overviewRulerBorder: false,
    // Prevent layout jitter by fixing content widget positions
    fixedOverflowWidgets: true,
  };

  return (
    <div
      className={`playground-prompt-node ${selected ? 'selected' : ''}`}
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

      <div className="playground-prompt-node-header">
        <div className="playground-prompt-node-icon">
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
            className="playground-prompt-node-title"
            onDoubleClick={startEditingName}
            title="Double-click to rename"
          >
            {displayName}
          </span>
        )}
      </div>

      <div
        className="playground-prompt-node-body nodrag"
        onKeyDown={(e) => e.stopPropagation()}
        onKeyUp={(e) => e.stopPropagation()}
        onKeyPress={(e) => e.stopPropagation()}
      >
        <div className="prompt-editor-container">
          {/* Placeholder overlay - shown when text is empty */}
          {(!data.text || data.text.trim() === '') && data.placeholder && (
            <div className="prompt-placeholder">
              {data.placeholder}
            </div>
          )}
          <Editor
            // Key based on node id + name ensures editor remounts when loading new cascade
            // (prevents stale content when React reuses component with same node id)
            key={`${id}-${data.name || 'prompt'}`}
            height="100%"
            defaultLanguage="plaintext"
            value={data.text || ''}
            onChange={handleTextChange}
            onMount={handleEditorDidMount}
            beforeMount={handleEditorWillMount}
            theme="windlass-prompt"
            options={editorOptions}
            loading={
              <div className="editor-loading">
                <Icon icon="mdi:loading" width="16" className="spinning" />
              </div>
            }
          />
        </div>
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
