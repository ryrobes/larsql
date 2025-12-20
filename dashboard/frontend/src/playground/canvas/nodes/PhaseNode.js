import React, { memo, useCallback, useState, useRef, useEffect, useMemo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';
import usePlaygroundStore from '../../stores/playgroundStore';
import useNodeResize from '../hooks/useNodeResize';
import './PhaseNode.css';

// Default dimensions (grid-aligned to 16px)
const DEFAULT_WIDTH = 320;  // 20 * 16
const DEFAULT_HEIGHT = 288; // 18 * 16

// Default YAML template for new phase nodes
const DEFAULT_YAML = `name: llm_transform
instructions: |
  {{ input.prompt }}
model: google/gemini-2.5-flash-lite
rules:
  max_turns: 1
`;

// Pattern to discover {{ input.X }} references in YAML
// Note: Create fresh regex in function to avoid global state issues
const INPUT_PATTERN_STR = '\\{\\{\\s*input\\.(\\w+)(?:\\s*\\|[^}]*)?\\s*\\}\\}';

/**
 * PhaseNode - LLM Phase node with Monaco YAML editor
 *
 * Displays:
 * - Node name (from YAML or custom) and status
 * - Monaco YAML editor for full phase configuration
 * - Output preview (after execution)
 *
 * Handles (typed for connection validation):
 * - Target (left-top): image-in - for vision model image input (purple)
 * - Target (left, dynamic): text-in-X - one per {{ input.X }} in YAML (green)
 * - Source (right): text-out - for text output (green)
 */
function PhaseNode({ id, data, selected }) {
  const removeNode = usePlaygroundStore((state) => state.removeNode);
  const updateNodeData = usePlaygroundStore((state) => state.updateNodeData);
  const runFromNode = usePlaygroundStore((state) => state.runFromNode);
  const lastSuccessfulSessionId = usePlaygroundStore((state) => state.lastSuccessfulSessionId);
  const executionStatus = usePlaygroundStore((state) => state.executionStatus);

  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  // Local state for YAML editing
  const [localYaml, setLocalYaml] = useState(data.yaml || DEFAULT_YAML);
  const [parseError, setParseError] = useState(null);
  const [discoveredInputs, setDiscoveredInputs] = useState(data.discoveredInputs || []);

  // Track last synced value to detect external changes (new cascade loaded)
  const lastSyncedYamlRef = useRef(data.yaml);

  // Sync localYaml when data.yaml changes externally (e.g., new cascade loaded)
  // This handles the case where React reuses the component (same node ID)
  useEffect(() => {
    // Only sync if data.yaml changed and it wasn't from our own edit
    if (data.yaml !== lastSyncedYamlRef.current && data.yaml !== localYaml) {
      setLocalYaml(data.yaml || DEFAULT_YAML);
      lastSyncedYamlRef.current = data.yaml;

      // Re-discover inputs for the new YAML
      const inputs = discoverInputs(data.yaml || DEFAULT_YAML);
      setDiscoveredInputs(inputs);
      setParseError(null);
    }
  }, [data.yaml, localYaml, discoverInputs]);

  // Editable name state
  const [isEditingName, setIsEditingName] = useState(false);
  const [editingNameValue, setEditingNameValue] = useState('');
  const nameInputRef = useRef(null);

  const {
    status = 'idle',
    output = '',
    cost,
    duration,
    width: dataWidth,
    height: dataHeight,
    name: customName,
  } = data;

  // Parse YAML to get phase name and validate
  const { phaseName, validationWarnings } = useMemo(() => {
    try {
      const parsed = yaml.load(localYaml);
      const warnings = [];

      // Check for required fields
      if (!parsed?.name) {
        warnings.push('Missing "name" field');
      }
      if (!parsed?.instructions) {
        warnings.push('Missing "instructions" field');
      }

      return {
        phaseName: parsed?.name || 'llm_phase',
        validationWarnings: warnings,
      };
    } catch {
      return {
        phaseName: 'llm_phase',
        validationWarnings: [],
      };
    }
  }, [localYaml]);

  // Display name: custom name > YAML name > fallback
  const displayName = customName || phaseName || 'LLM Phase';

  // Get dimensions from data or use defaults
  const width = dataWidth || DEFAULT_WIDTH;
  const height = dataHeight || DEFAULT_HEIGHT;

  // Resize hook (grid-aligned constraints)
  const { onResizeStart } = useNodeResize(id, {
    minWidth: 256,  // 16 * 16
    minHeight: 192, // 12 * 16
    maxWidth: 640,  // 40 * 16
    maxHeight: 576, // 36 * 16
  });

  // Discover input references in YAML
  const discoverInputs = useCallback((yamlString) => {
    // Create fresh regex each time to avoid global state issues
    const pattern = new RegExp(INPUT_PATTERN_STR, 'g');
    const matches = [...yamlString.matchAll(pattern)];
    const inputs = [...new Set(matches.map(m => m[1]))];
    return inputs;
  }, []);

  // Parse and validate YAML on change (debounced in Monaco)
  const handleYamlChange = useCallback((newValue) => {
    setLocalYaml(newValue);
    // Update ref to prevent sync effect from overwriting user edits
    lastSyncedYamlRef.current = newValue;

    try {
      const parsed = yaml.load(newValue);
      setParseError(null);

      // Discover inputs from instructions
      const inputs = discoverInputs(newValue);
      setDiscoveredInputs(inputs);

      // Update store with parsed data
      updateNodeData(id, {
        yaml: newValue,
        parsedPhase: parsed,
        discoveredInputs: inputs,
      });
    } catch (err) {
      setParseError(err.message);
    }
  }, [id, updateNodeData, discoverInputs]);

  // Initialize discovered inputs on mount
  useEffect(() => {
    const inputs = discoverInputs(localYaml);
    setDiscoveredInputs(inputs);
    if (!data.yaml) {
      updateNodeData(id, {
        yaml: localYaml,
        discoveredInputs: inputs,
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps


  // Handle delete
  const handleDelete = useCallback((e) => {
    e.stopPropagation();
    removeNode(id);
  }, [id, removeNode]);

  // Handle "Run from here" action
  const handleRunFromHere = useCallback(async (e) => {
    e.stopPropagation();
    const result = await runFromNode(id);
    if (!result.success) {
      console.error('[PhaseNode] Run from here failed:', result.error);
    }
  }, [id, runFromNode]);

  const canRunFromHere = lastSuccessfulSessionId && executionStatus !== 'running';

  // Name editing handlers
  const startEditingName = useCallback((e) => {
    e.stopPropagation();
    setEditingNameValue(customName || '');
    setIsEditingName(true);
  }, [customName]);

  const saveName = useCallback(() => {
    const trimmedName = editingNameValue.trim();
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
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });
  }, []);

  // Custom dark theme - GitHub Dark inspired, pastels on black
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-phase', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'key', foreground: '7ee787' },           // pastel green
        { token: 'string.yaml', foreground: 'a5d6ff' },   // pastel blue
        { token: 'number', foreground: 'd2a8ff' },        // pastel purple
        { token: 'keyword', foreground: 'ff9eb8' },       // pastel pink
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
      ],
      colors: {
        'editor.background': '#000000',                   // pure black
        'editor.foreground': '#e6edf3',                   // light gray
        'editor.lineHighlightBackground': '#161b22',
        'editor.selectionBackground': '#264f78',
        'editorLineNumber.foreground': '#6e7681',
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorCursor.foreground': '#79c0ff',             // pastel cyan
        'editorIndentGuide.background': '#21262d',
        'editorGutter.background': '#000000',
      },
    });
  }, []);

  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 11,
    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    foldingStrategy: 'indentation',
    padding: { top: 8, bottom: 8 },
    scrollbar: {
      vertical: 'auto',
      horizontal: 'hidden',
      verticalScrollbarSize: 8,
    },
  };

  // Format helpers
  const formatCost = (cost) => {
    if (!cost) return null;
    if (cost < 0.01) return '<$0.01';
    return `$${cost.toFixed(3)}`;
  };

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
  const formattedCost = formatCost(cost);
  const formattedDuration = formatDuration(duration);
  const showFooter = status === 'completed' && (formattedCost || formattedDuration || output);

  return (
    <div
      className={`phase-node ${selected ? 'selected' : ''} status-${status}`}
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

      {/* Target handle for image input (top-left) - purple for image */}
      <Handle
        type="target"
        position={Position.Left}
        id="image-in"
        className="phase-handle input-handle handle-image"
        style={{ top: '15%' }}
        title="Image input (for vision models)"
      />

      {/* Text input handle - single handle for text/prompt input */}
      <Handle
        type="target"
        position={Position.Left}
        id="text-in"
        className="phase-handle input-handle handle-text"
        style={{ top: '50%' }}
        title="Text input"
      />

      {/* Header */}
      <div className="phase-node-header">
        <div className="phase-node-icon">
          <Icon icon="mdi:cog-play" width="16" />
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
            className="phase-node-title"
            onDoubleClick={startEditingName}
            title="Double-click to rename"
          >
            {displayName}
          </span>
        )}
        {validationWarnings.length > 0 && !parseError && (
          <div
            className="phase-node-warning"
            title={validationWarnings.join('\n')}
          >
            <Icon icon="mdi:alert-outline" width="14" />
          </div>
        )}
        <div className={`phase-node-status ${statusInfo.className}`}>
          <Icon
            icon={statusInfo.icon}
            width="14"
            className={status === 'running' ? 'spinning' : ''}
          />
        </div>
      </div>

      {/* Monaco YAML Editor */}
      <div
        className="phase-node-body nodrag"
        onKeyDown={(e) => e.stopPropagation()}
        onKeyUp={(e) => e.stopPropagation()}
        onKeyPress={(e) => e.stopPropagation()}
      >
        <div className="phase-editor-container">
          <Editor
            // Key based on node id + name ensures editor remounts when loading new cascade
            key={`${id}-${customName || phaseName}`}
            height="100%"
            defaultLanguage="yaml"
            value={localYaml}
            onChange={handleYamlChange}
            onMount={handleEditorDidMount}
            beforeMount={handleEditorWillMount}
            theme="windlass-phase"
            options={editorOptions}
            loading={
              <div className="editor-loading">
                <Icon icon="mdi:loading" width="16" className="spinning" />
              </div>
            }
          />
        </div>
        {parseError && (
          <div className="phase-error">
            <Icon icon="mdi:alert" width="12" />
            <span>{parseError}</span>
          </div>
        )}
      </div>

      {/* Footer with output/cost/duration - only shown when completed */}
      {showFooter && (
        <div className="phase-node-footer">
          {output && (
            <div className="footer-output nodrag" title="LLM output (scroll to see more)">
              <div className="output-label">
                <Icon icon="mdi:message-text-outline" width="12" />
                <span>Output</span>
              </div>
              <div className="output-content">{output}</div>
            </div>
          )}
          <div className="footer-stats">
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
        </div>
      )}

      {/* Source handle for text output - green for text */}
      <Handle
        type="source"
        position={Position.Right}
        id="text-out"
        className="phase-handle output-handle handle-text"
        title="Text output"
      />

      {/* Resize handle */}
      <div
        className="node-resize-handle nodrag"
        onPointerDown={onResizeStart}
      />
    </div>
  );
}

export default memo(PhaseNode);
