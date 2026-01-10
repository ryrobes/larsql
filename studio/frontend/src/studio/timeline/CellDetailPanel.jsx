import React, { useState, useRef, useCallback, useMemo } from 'react';
import Split from 'react-split';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { useDroppable } from '@dnd-kit/core';
import yaml from 'js-yaml';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import ResultRenderer from './results/ResultRenderer';
import HTMLSection from '../../components/sections/HTMLSection';
import SessionMessagesLog from '../components/SessionMessagesLog';
import { detectCellEditors } from '../editors';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount} from '../utils/monacoTheme';
import { Modal, ModalHeader, ModalContent, ModalFooter, Button } from '../../components';
import useSpecValidation from '../../hooks/useSpecValidation';
import ValidationPanel from '../../components/validation/ValidationPanel';
import './CellDetailPanel.css';

/**
 * Format milliseconds to human-readable time
 * Examples: <1s, 1s, 1m 12s, 5m 30s
 */
const formatDuration = (ms) => {
  if (!ms) return null;

  if (ms < 1000) return '<1s';

  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  if (minutes === 0) {
    return `${seconds}s`;
  }

  if (remainingSeconds === 0) {
    return `${minutes}m`;
  }

  return `${minutes}m ${remainingSeconds}s`;
};

/**
 * CellDetailPanel - Bottom panel showing full cell configuration
 *
 * Tabs:
 * - Code: Monaco editor for SQL/Python/JS/etc
 * - Config: Cell configuration (LLM settings, candidates, wards)
 * - Output: Results table/JSON
 */
const CellDetailPanel = ({ cell, index, cellState, cellLogs = [], allSessionLogs = [], currentSessionId = null, onClose, onMessageClick, hoveredHash = null, onHoverHash, externalSelectedMessage = null }) => {
  const { updateCell, runCell, removeCell, desiredOutputTab, setDesiredOutputTab, isRunningAll, cascadeSessionId, viewMode, cascade } = useStudioCascadeStore();
  const [activeTab, setActiveTab] = useState('code');
  const [activeOutputTab, setActiveOutputTab] = useState('output');
  const [showYamlEditor, setShowYamlEditor] = useState(false);
  const [yamlEditorFocused, setYamlEditorFocused] = useState(false);
  const [localYaml, setLocalYaml] = useState('');
  const [yamlParseError, setYamlParseError] = useState(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [modalImage, setModalImage] = useState(null);
  const lastSyncedYamlRef = useRef('');

  // Split sizes with localStorage persistence
  const [editorResultsSplit, setEditorResultsSplit] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-cell-editor-results-split');
      return saved ? JSON.parse(saved) : [60, 40];
    } catch {
      return [60, 40];
    }
  });
  const [codeYamlSplit, setCodeYamlSplit] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-cell-code-yaml-split');
      return saved ? JSON.parse(saved) : [60, 40];
    } catch {
      return [60, 40];
    }
  });

  const handleEditorResultsSplitChange = useCallback((sizes) => {
    setEditorResultsSplit(sizes);
    try {
      localStorage.setItem('studio-cell-editor-results-split', JSON.stringify(sizes));
    } catch (e) {
      console.warn('Failed to save split sizes to localStorage:', e);
    }
  }, []);

  const handleCodeYamlSplitChange = useCallback((sizes) => {
    setCodeYamlSplit(sizes);
    try {
      localStorage.setItem('studio-cell-code-yaml-split', JSON.stringify(sizes));
    } catch (e) {
      console.warn('Failed to save split sizes to localStorage:', e);
    }
  }, []);
  const editorRef = useRef(null);
  const yamlEditorRef = useRef(null);
  const yamlEditorEverFocusedRef = useRef(false);

  // Build cascade context for validation (all cell names for accurate handoff checking)
  const cascadeContext = useMemo(() => {
    if (!cascade || !cascade.cells) return null;
    return {
      cellNames: cascade.cells.map(c => c.name),
      cascadeId: cascade.cascade_id || '_temp',
    };
  }, [cascade]);

  // Spec validation for YAML editor
  const validation = useSpecValidation(localYaml, {
    enabled: showYamlEditor && localYaml.length > 0,
    cellMode: true, // Always treat as single cell YAML
    cascadeContext, // Pass full cascade context for accurate validation
  });

  // Apply desired output tab when it changes (from Media section navigation)
  React.useEffect(() => {
    if (desiredOutputTab) {
      setActiveOutputTab(desiredOutputTab);
      setDesiredOutputTab(null); // Clear after applying
    }
  }, [desiredOutputTab, setDesiredOutputTab]);

  // Make code editor droppable
  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `editor-drop-${cell.name}`,
    data: { type: 'monaco-editor' },
  });

  // Make YAML editor droppable
  const { setNodeRef: setYamlDropRef, isOver: isYamlOver } = useDroppable({
    id: `yaml-editor-drop-${cell.name}`,
    data: { type: 'monaco-editor' },
  });

  // Cleanup editors on unmount
  React.useEffect(() => {
    return () => {
      if (editorRef.current) {
        try {
          editorRef.current.dispose();
        } catch (e) {
          // Ignore disposal errors
        }
      }
      if (yamlEditorRef.current) {
        try {
          yamlEditorRef.current.dispose();
        } catch (e) {
          // Ignore disposal errors
        }
      }
    };
  }, []);

  const isSql = cell.tool === 'sql_data';
  const isPython = cell.tool === 'python_data';
  const isJs = cell.tool === 'js_data';
  const isClojure = cell.tool === 'clojure_data';
  const isRvbbit = cell.tool === 'rvbbit_data';
  const isHitl = !!cell.hitl;
  const isLLMCell = !cell.tool && !cell.hitl && cell.instructions;

  const typeInfo = {
    sql_data: { language: 'sql', codeKey: 'query', source: 'inputs' },
    python_data: { language: 'python', codeKey: 'code', source: 'inputs' },
    js_data: { language: 'javascript', codeKey: 'code', source: 'inputs' },
    clojure_data: { language: 'clojure', codeKey: 'code', source: 'inputs' },
    llm_cell: { language: 'markdown', codeKey: 'instructions', source: 'cell' },
    rvbbit_data: { language: 'yaml', codeKey: 'code', source: 'inputs' },
    bodybuilder: { language: 'markdown', codeKey: 'request', source: 'inputs' }, // Natural language LLM request
    browser: { language: 'yaml', codeKey: 'inputs', source: 'inputs_yaml' }, // Browser automation - show all inputs as YAML
    linux_shell: { language: 'shell', codeKey: 'command', source: 'inputs' }, // Shell commands
    linux_shell_dangerous: { language: 'shell', codeKey: 'command', source: 'inputs' }, // Shell commands (host)
    hitl_screen: { language: 'html', codeKey: 'hitl', source: 'cell' }, // HTMX screen content
  };
  // Determine cell type - tool takes priority, HITL only for pure HITL cells (no tool)
  const cellType = cell.tool || (isHitl ? 'hitl_screen' :
    (isLLMCell ? 'llm_cell' : 'python_data'));
  const info = typeInfo[cellType] || typeInfo.python_data;

  // Detect custom editors for this cell
  const customEditors = useMemo(() => detectCellEditors(cell), [cell]);
  const hasCustomEditors = customEditors.length > 0;

  // Extract code based on source type
  const code = useMemo(() => {
    if (info.source === 'inputs_yaml') {
      // Serialize entire inputs object as YAML (for browser cells)
      try {
        return cell.inputs ? yaml.dump(cell.inputs, { indent: 2, lineWidth: -1 }) : '';
      } catch (e) {
        console.error('Failed to serialize inputs as YAML:', e);
        return JSON.stringify(cell.inputs, null, 2) || '';
      }
    } else if (info.source === 'inputs') {
      return cell.inputs?.[info.codeKey] || '';
    } else {
      return cell[info.codeKey] || '';
    }
  }, [cell, info.source, info.codeKey]);
  const status = cellState?.status || 'pending';
  const error = cellState?.error;
  const images = cellState?.images;

  // DEBUG: Log code extraction
  React.useEffect(() => {
    console.log('[CellDetailPanel] Code extraction:', {
      cellName: cell.name,
      cellTool: cell.tool,
      cellType,
      infoSource: info.source,
      infoCodeKey: info.codeKey,
      infoLanguage: info.language,
      codeLength: code?.length || 0,
      hasInputs: !!cell.inputs,
      inputsKeys: cell.inputs ? Object.keys(cell.inputs) : [],
      cellKeys: Object.keys(cell)
    });
  }, [cell, cellType, info, code]);

  // Debug - only log when we have meaningful stats
  React.useEffect(() => {
    if (cellState?.duration || cellState?.cost || cellState?.tokens_in) {
      console.log('[CellDetailPanel]', cell.name, '- Duration:', cellState.duration, 'Cost:', cellState.cost, 'Tokens:', cellState.tokens_in, '/', cellState.tokens_out);
    }
  }, [cell.name, cellState]);

  // Build HTML for decision tag (converts JSON to HTMX form)
  const buildDecisionHTML = useCallback((decisionData) => {
    const optionsHTML = (decisionData.options || []).map(option => `
      <button
        type="submit"
        name="response[option]"
        value="${option.id}"
        class="decision-option decision-option-${option.style || 'secondary'}"
      >
        <div class="decision-option-label">${option.label}</div>
        ${option.description ? `<div class="decision-option-desc">${option.description}</div>` : ''}
      </button>
    `).join('');

    return `
      <div class="decision-card">
        <div class="decision-header">
          <h3>${decisionData.question || 'Decision Required'}</h3>
        </div>
        ${decisionData.context ? `
          <div class="decision-context">
            ${decisionData.context}
          </div>
        ` : ''}
        <form hx-post="{{ api_endpoint }}" hx-headers='{"X-Checkpoint-ID": "{{ checkpoint_id }}"}'>
          <div class="decision-options">
            ${optionsHTML}
          </div>
        </form>
      </div>
      <style>
        .decision-card {
          max-width: 600px;
          margin: 0 auto;
          background: linear-gradient(135deg, #0f1821, #0a0e14);
          border: 2px solid #f59e0b;
          border-radius: 12px;
          padding: 24px;
        }
        .decision-header h3 {
          margin: 0 0 16px 0;
          font-size: 18px;
          font-weight: 700;
          color: #fbbf24;
        }
        .decision-context {
          padding: 12px 16px;
          background-color: rgba(100, 116, 139, 0.1);
          border-left: 3px solid #64748b;
          border-radius: 6px;
          margin-bottom: 20px;
        }
        .decision-options {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .decision-option {
          padding: 16px;
          border-radius: 8px;
          border: 2px solid #1a2028;
          background-color: #0a0e14;
          cursor: pointer;
          transition: all 0.2s ease;
          text-align: left;
          width: 100%;
        }
        .decision-option:hover {
          transform: translateY(-2px);
        }
        .decision-option-primary {
          border-color: #2dd4bf;
          background: linear-gradient(135deg, rgba(45, 212, 191, 0.15), rgba(20, 184, 166, 0.1));
        }
        .decision-option-primary:hover {
          border-color: #14b8a6;
          background: linear-gradient(135deg, rgba(45, 212, 191, 0.25), rgba(20, 184, 166, 0.15));
          box-shadow: 0 4px 16px rgba(45, 212, 191, 0.4);
        }
        .decision-option-secondary {
          border-color: #475569;
        }
        .decision-option-secondary:hover {
          border-color: #64748b;
          background-color: #0f1419;
        }
        .decision-option-danger {
          border-color: #f87171;
          background: linear-gradient(135deg, rgba(248, 113, 113, 0.15), rgba(239, 68, 68, 0.1));
        }
        .decision-option-danger:hover {
          border-color: #ef4444;
          box-shadow: 0 4px 16px rgba(248, 113, 113, 0.4);
        }
        .decision-option-label {
          font-size: 15px;
          font-weight: 600;
          color: #f0f4f8;
          margin-bottom: 4px;
        }
        .decision-option-desc {
          font-size: 13px;
          color: #94a3b8;
        }
      </style>
    `;
  }, []);

  // Group messages by candidate index
  const messagesByCandidate = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    const grouped = {};
    let winningIndex = null;
    const hasAnyCandidate = cellLogs.some(log =>
      log.candidate_index !== null && log.candidate_index !== undefined
    );

    if (!hasAnyCandidate) {
      // No candidates - return all messages in single group
      return null;
    }

    for (const log of cellLogs) {
      if (log.winning_candidate_index !== null && log.winning_candidate_index !== undefined) {
        winningIndex = log.winning_candidate_index;
      }
    }

    for (const log of cellLogs) {
      if (!['user', 'assistant', 'tool', 'system'].includes(log.role)) continue;

      const candidateIdx = log.candidate_index ?? 'main';
      if (!grouped[candidateIdx]) {
        grouped[candidateIdx] = [];
      }

      // Parse JSON fields
      let content = log.content_json;
      if (typeof content === 'string') {
        try {
          content = JSON.parse(content);
        } catch {}
      }

      let toolCalls = log.tool_calls_json;
      if (typeof toolCalls === 'string') {
        try {
          toolCalls = JSON.parse(toolCalls);
        } catch {}
      }

      let images = log.images_json;
      if (typeof images === 'string') {
        try {
          images = JSON.parse(images);
        } catch {}
      }

      grouped[candidateIdx].push({
        role: log.role,
        node_type: log.node_type,
        turn_number: log.turn_number,
        content,
        tool_calls: toolCalls,
        duration_ms: log.duration_ms,
        cost: log.cost,
        tokens_in: log.tokens_in,
        tokens_out: log.tokens_out,
        model: log.model,
        timestamp: log.timestamp_iso,
        trace_id: log.trace_id,
        images,
        has_images: log.has_images,
        session_id: log.session_id  // Include session_id for child session detection
      });
    }

    return { grouped, winner: winningIndex };
  }, [cellLogs]);

  // Process cell logs into messages (filtering for relevant roles) - ALWAYS available
  const cellMessages = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return [];

    // Always return all messages - Messages tab should always be available
    // (candidate tabs are ADDITIONAL views, not replacements)
    return cellLogs
      .filter(log => ['user', 'assistant', 'tool', 'system'].includes(log.role))
      .map(log => {
        // Parse JSON fields if they're strings
        let content = log.content_json;
        if (typeof content === 'string') {
          try {
            content = JSON.parse(content);
          } catch {}
        }

        let toolCalls = log.tool_calls_json;
        if (typeof toolCalls === 'string') {
          try {
            toolCalls = JSON.parse(toolCalls);
          } catch {}
        }

        let images = log.images_json;
        if (typeof images === 'string') {
          try {
            images = JSON.parse(images);
          } catch {}
        }

        return {
          role: log.role,
          node_type: log.node_type,
          turn_number: log.turn_number,
          content,
          tool_calls: toolCalls,
          duration_ms: log.duration_ms,
          cost: log.cost,
          tokens_in: log.tokens_in,
          tokens_out: log.tokens_out,
          model: log.model,
          timestamp: log.timestamp_iso,
          trace_id: log.trace_id,
          images,
          has_images: log.has_images,
          session_id: log.session_id  // Include session_id for child session detection
        };
      });
  }, [cellLogs]);

  // Use result directly from cellState (don't override it)
  const result = cellState?.result;

  // Extract evaluator message (explains why winner was chosen)
  const evaluatorMessage = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    const evaluatorLog = cellLogs.find(log => log.role === 'evaluator');
    if (!evaluatorLog) return null;

    let content = evaluatorLog.content_json;
    if (typeof content === 'string') {
      try {
        content = JSON.parse(content);
      } catch {}
    }

    return {
      content,
      timestamp: evaluatorLog.timestamp_iso,
      model: evaluatorLog.model
    };
  }, [cellLogs]);

  // Extract checkpoint/decision data - supports BOTH checkpoint-based AND tag-based decisions
  const checkpointData = React.useMemo(() => {
    // PATH 1: Look for checkpoint_waiting event in ALL session logs (might not have cell_name)
    // Check allSessionLogs first, then fall back to cellLogs
    const logsToSearch = allSessionLogs.length > 0 ? allSessionLogs : cellLogs;

    if (!logsToSearch || logsToSearch.length === 0) return null;

    const checkpointLog = logsToSearch.find(log => log.role === 'checkpoint_waiting');
    if (checkpointLog) {
      console.log('[CellDetailPanel] Found checkpoint_waiting log in session logs');

      let metadata = checkpointLog.metadata_json;
      if (typeof metadata === 'string') {
        try {
          metadata = JSON.parse(metadata);
        } catch (e) {
          console.error('[CellDetailPanel] Failed to parse metadata_json:', e);
        }
      }

      if (metadata?.ui_spec && metadata?.checkpoint_id) {
        let uiSpec = metadata.ui_spec;
        if (typeof uiSpec === 'string') {
          try {
            uiSpec = JSON.parse(uiSpec);
          } catch {}
        }

        console.log('[CellDetailPanel] Using checkpoint ui_spec:', {
          checkpointId: metadata.checkpoint_id,
          hasHtml: uiSpec.sections?.some(s => s.type === 'html')
        });

        return {
          checkpointId: metadata.checkpoint_id,
          uiSpec: uiSpec,
          checkpointType: metadata.checkpoint_type,
          source: 'checkpoint'
        };
      }
    }

    // PATH 2: Look for <decision> tag in assistant message (legacy/simple decision)
    for (const log of cellLogs) {
      if (log.role === 'assistant' && log.content_json) {
        let content = log.content_json;
        if (typeof content === 'string') {
          try {
            content = JSON.parse(content);
          } catch {}
        }

        const contentStr = typeof content === 'string' ? content : JSON.stringify(content);
        const decisionMatch = contentStr.match(/<decision>\s*([\s\S]*?)\s*<\/decision>/);
        if (decisionMatch) {
          try {
            const parsed = JSON.parse(decisionMatch[1]);
            console.log('[CellDetailPanel] Found <decision> tag - building ui_spec');

            // Build ui_spec compatible with HTMLSection
            const uiSpec = {
              sections: [{
                type: 'html',
                content: buildDecisionHTML(parsed)
              }]
            };

            return {
              checkpointId: null, // No checkpoint ID for tag-based decisions
              uiSpec: uiSpec,
              checkpointType: 'decision',
              decisionData: parsed,
              source: 'decision_tag'
            };
          } catch (e) {
            console.error('[CellDetailPanel] Failed to parse <decision> JSON:', e);
          }
        }
      }
    }

    //console.log('[CellDetailPanel] No checkpoint or decision found');
    return null;
  }, [cellLogs, allSessionLogs, buildDecisionHTML]);

  // Extract full_request_json from logs for debugging
  const fullRequest = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    // Find the first log with full_request_json
    const logWithRequest = cellLogs.find(log => log.full_request_json);
    if (!logWithRequest) return null;

    let request = logWithRequest.full_request_json;
    if (typeof request === 'string') {
      try {
        request = JSON.parse(request);
      } catch (e) {
        console.error('[CellDetailPanel] Failed to parse request JSON:', e);
      }
    }
    return request;
  }, [cellLogs]);

  // Auto-select winner candidate tab when cell changes and has candidates
  React.useEffect(() => {
    if (messagesByCandidate && messagesByCandidate.winner !== null) {
      setActiveOutputTab(`candidate-${messagesByCandidate.winner}`);
    }
  }, [cell.name, messagesByCandidate]);

  // Initialize/reset localYaml when cell changes or YAML editor is opened
  // Use a ref to track which cell we last initialized for
  const lastInitializedCellRef = useRef(null);

  React.useEffect(() => {
    if (!showYamlEditor) return; // Only initialize when editor is visible

    // Always reinitialize when cell identity changes (name or cascade)
    const cellKey = `${cascadeContext?.cascadeId || ''}_${cell.name}`;
    if (lastInitializedCellRef.current !== cellKey) {
      const initialYaml = yaml.dump(cell, { indent: 2, lineWidth: -1, noRefs: true });
      setLocalYaml(initialYaml);
      lastSyncedYamlRef.current = initialYaml;
      lastInitializedCellRef.current = cellKey;
      setYamlParseError(null);
    }
  }, [cell, cell.name, showYamlEditor, cascadeContext]); // Re-init when cell/cascade changes or editor opens

  // Clear localYaml when YAML editor is closed (free memory)
  React.useEffect(() => {
    if (!showYamlEditor && localYaml) {
      setLocalYaml('');
      lastSyncedYamlRef.current = '';
      lastInitializedCellRef.current = null; // Reset so it reinitializes on next open
      setYamlParseError(null);
      yamlEditorEverFocusedRef.current = false;
    }
  }, [showYamlEditor, localYaml]);

  // Sync cell → localYaml when cell changes externally (not when focused)
  React.useEffect(() => {
    if (yamlEditorFocused) return;
    if (!localYaml) return; // Let initialization effect handle it

    // Don't overwrite user's formatting unless cell structure actually changed
    try {
      const currentParsed = yaml.load(localYaml);
      // Deep comparison - only update if structure changed
      if (JSON.stringify(currentParsed) === JSON.stringify(cell)) {
        return; // No structural change, keep user's formatting and comments!
      }

      // Structure changed externally - regenerate YAML
      const yamlStr = yaml.dump(cell, { indent: 2, lineWidth: -1, noRefs: true });
      if (yamlStr !== lastSyncedYamlRef.current) {
        console.log('[CellDetailPanel] Cell structure changed externally, regenerating YAML');
        setLocalYaml(yamlStr);
        lastSyncedYamlRef.current = yamlStr;
      }
    } catch (e) {
      // Parse error in localYaml - regenerate
      console.warn('[CellDetailPanel] Parse error in localYaml, regenerating:', e);
      const yamlStr = yaml.dump(cell, { indent: 2, lineWidth: -1, noRefs: true });
      setLocalYaml(yamlStr);
      lastSyncedYamlRef.current = yamlStr;
    }
  }, [cell, yamlEditorFocused, localYaml]);

  // Use localYaml as the editor value
  const cellYaml = localYaml;

  const handleYamlChange = useCallback((value) => {
    // Only update local YAML for display, don't sync to store until blur
    setLocalYaml(value);

    // Validate as complete YAML document by wrapping fragment
    try {
      // Indent the cell YAML and wrap in a parent structure for validation
      const indented = value.split('\n').map(line => '  ' + line).join('\n');
      const wrappedYaml = `cells:\n${indented}`;

      const parsed = yaml.load(wrappedYaml);

      // Check if parse succeeded and returned valid structure
      if (parsed && parsed.cells && typeof parsed.cells === 'object') {
        setYamlParseError(null);
      }
    } catch (e) {
      // Only show parse error if it's a real syntax error
      // Ignore errors for empty/whitespace-only
      if (value.trim().length > 0) {
        setYamlParseError(e.message);
      } else {
        setYamlParseError(null);
      }
    }
  }, []);

  const handleYamlBlur = useCallback((editorValue) => {
    console.log('[CellDetailPanel] YAML editor blurred, syncing to store');

    // Prevent sync loop
    if (editorValue === lastSyncedYamlRef.current) {
      setYamlEditorFocused(false);
      return;
    }

    try {
      // Parse the cell YAML directly (it's a valid YAML object on its own)
      const parsed = yaml.load(editorValue);

      // Validate that parsed has required fields
      if (!parsed || typeof parsed !== 'object') {
        throw new Error('Invalid cell structure: must be an object');
      }

      if (!parsed.name) {
        throw new Error('Invalid cell: missing required field "name"');
      }

      // Update entire cell object (spread to preserve all keys)
      updateCell(index, { ...parsed });
      lastSyncedYamlRef.current = editorValue;
      setYamlParseError(null);
      // Only set unfocused after successful update
      setYamlEditorFocused(false);
    } catch (e) {
      // Invalid YAML - keep error visible but still unfocus
      setYamlParseError(e.message);
      console.debug('YAML parse/validation error on blur:', e.message);
      setYamlEditorFocused(false);
    }
  }, [index, updateCell]);

  const handleCodeChange = useCallback((value) => {
    if (info.source === 'inputs_yaml') {
      // Parse YAML and replace entire inputs object (for browser cells)
      try {
        const parsedInputs = yaml.load(value);
        if (parsedInputs && typeof parsedInputs === 'object') {
          updateCell(index, { inputs: parsedInputs });
        }
      } catch (e) {
        // Don't update on invalid YAML - user is still typing
        console.debug('YAML parse error (still typing):', e.message);
      }
    } else if (info.source === 'inputs') {
      updateCell(index, { inputs: { ...cell.inputs, [info.codeKey]: value } });
    } else {
      updateCell(index, { [info.codeKey]: value });
    }
  }, [index, cell.inputs, info.codeKey, info.source, updateCell]);

  const handleNameChange = (e) => {
    updateCell(index, { name: e.target.value });
  };

  const handleRun = () => {
    runCell(cell.name);
  };

  const handleDelete = () => {
    setIsDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    removeCell(index);
    setIsDeleteModalOpen(false);
    onClose();
  };

  // Determine if this is a LIVE decision (actively waiting) vs replay
  const isLiveDecision = React.useMemo(() => {
    if (!checkpointData) return false;

    // Tag-based decisions (<decision> in message) have no checkpoint - can't submit
    if (checkpointData.source === 'decision_tag') {
      console.log('[CellDetailPanel] Decision tag detected - no checkpoint to submit to, read-only');
      return false;
    }

    // If in replay mode, never live
    if (viewMode === 'replay') return false;

    // Check if already responded to
    const hasResponse = cellLogs?.some(log =>
      log.role === 'checkpoint_responded' || log.role === 'checkpoint_cancelled'
    );

    // Live if in live mode, has checkpoint, and not yet responded
    const isLive = viewMode === 'live' && !hasResponse && checkpointData.checkpointId;
    console.log('[CellDetailPanel] Decision live status:', {
      viewMode,
      hasResponse,
      isLive,
      checkpointId: checkpointData.checkpointId,
      source: checkpointData.source
    });
    return isLive;
  }, [checkpointData, viewMode, cellLogs]);

  // Auto-select decision tab when it exists (even if not live - it's important!)
  React.useEffect(() => {
    if (checkpointData) {
      console.log('[CellDetailPanel] Setting active tab to decision');
      setActiveOutputTab('decision');
    }
  }, [cell.name, checkpointData]);

  // Validate activeOutputTab when cell changes - reset to 'output' if invalid
  React.useEffect(() => {
    // Skip if already on a safe tab
    if (activeOutputTab === 'output' || activeOutputTab === 'raw' || activeOutputTab === 'request') {
      return;
    }

    let isValid = true;

    // Check if current tab is valid for this cell
    if (activeOutputTab === 'decision' && !checkpointData) {
      isValid = false;
    } else if (activeOutputTab === 'images' && (!images || images.length === 0)) {
      isValid = false;
    } else if (activeOutputTab === 'error' && !error) {
      isValid = false;
    } else if (activeOutputTab === 'messages' && (!cellMessages || cellMessages.length === 0)) {
      isValid = false;
    } else if (activeOutputTab.startsWith('candidate-')) {
      // Check if this candidate index exists
      const candidateIdx = activeOutputTab.replace('candidate-', '');
      if (!messagesByCandidate || !messagesByCandidate.grouped[candidateIdx]) {
        isValid = false;
      }
    }

    // Reset to 'output' if invalid
    if (!isValid) {
      console.log('[CellDetailPanel] Tab invalid for new cell, resetting:', activeOutputTab, '→ output');
      setActiveOutputTab('output');
    }
  }, [cell.name, activeOutputTab, checkpointData, images, error, cellMessages, messagesByCandidate]);

  return (
    <div className="cell-detail-panel">
      {/* Header */}
      <div className="cell-detail-header">
        <div className="cell-detail-header-left">
          <input
            className="cell-detail-name-input"
            value={cell.name}
            onChange={handleNameChange}
            placeholder="cell_name"
          />
          <span className="cell-detail-index">#{index + 1}</span>
        </div>

        <div className="cell-detail-header-center">
          {isRvbbit && (
            <>
              <button
                className={`cell-detail-tab ${activeTab === 'code' ? 'active' : ''}`}
                onClick={() => setActiveTab('code')}
              >
                <Icon icon="mdi:code-braces" width="16" />
                Code
              </button>
              <button
                className={`cell-detail-tab ${activeTab === 'config' ? 'active' : ''}`}
                onClick={() => setActiveTab('config')}
              >
                <Icon icon="mdi:cog" width="16" />
                Config
              </button>
            </>
          )}
          {!isRvbbit && !hasCustomEditors && (
            <div className="cell-detail-mode-label">
              <Icon icon="mdi:code-braces" width="16" />
              Code Editor
              <button
                className={`cell-detail-yaml-toggle ${showYamlEditor ? 'active' : ''}`}
                onClick={() => setShowYamlEditor(!showYamlEditor)}
                title={showYamlEditor ? 'Hide YAML editor' : 'Show YAML editor'}
              >
                <Icon icon="mdi:code-json" width="14" />
                YAML
              </button>
            </div>
          )}
          {!isRvbbit && hasCustomEditors && (
            <>
              <button
                className={`cell-detail-tab ${activeTab === 'code' ? 'active' : ''}`}
                onClick={() => setActiveTab('code')}
              >
                <Icon icon="mdi:code-braces" width="16" />
                Code
              </button>
              {customEditors.map(editor => (
                <button
                  key={editor.id}
                  className={`cell-detail-tab ${activeTab === editor.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(editor.id)}
                >
                  {editor.icon && <Icon icon={editor.icon} width="16" />}
                  {editor.label}
                  <span className="cell-detail-tab-badge">Custom</span>
                </button>
              ))}
              <button
                className={`cell-detail-yaml-toggle ${showYamlEditor ? 'active' : ''}`}
                onClick={() => setShowYamlEditor(!showYamlEditor)}
                title={showYamlEditor ? 'Hide YAML editor' : 'Show YAML editor'}
                style={{ marginLeft: 'auto' }}
              >
                <Icon icon="mdi:code-json" width="14" />
                YAML
              </button>
            </>
          )}
        </div>

        <div className="cell-detail-header-right">
          <button
            className="cell-detail-btn cell-detail-btn-run"
            onClick={handleRun}
            disabled={status === 'running'}
          >
            {status === 'running' ? (
              <span className="cell-detail-spinner" />
            ) : (
              <Icon icon="mdi:play" width="16" />
            )}
            Run
          </button>
          <button
            className="cell-detail-btn cell-detail-btn-delete"
            onClick={handleDelete}
          >
            <Icon icon="mdi:delete" width="16" />
          </button>
          <button
            className="cell-detail-btn cell-detail-btn-close"
            onClick={onClose}
          >
            <Icon icon="mdi:close" width="16" />
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="cell-detail-body">
        {activeTab === 'config' && isRvbbit ? (
          <div className="cell-detail-config">
            <div className="cell-detail-config-section">
              <h4>LLM Configuration</h4>
              <p className="cell-detail-placeholder">
                Config UI coming soon: model selection, candidates, wards, handoffs...
              </p>
            </div>
          </div>
        ) : (
          /* Code/Custom Editor + Results with resizable splitter (always shown) */
          <Split
            className="cell-detail-split"
            direction="vertical"
            sizes={editorResultsSplit}
            minSize={[100, 100]}
            gutterSize={6}
            gutterAlign="center"
            onDragEnd={handleEditorResultsSplitChange}
          >
              {/* Code/Custom Editor Container (keeps consistent structure for Split) */}
              <div className="cell-detail-code-container">
                {/* Render Custom Editor or Monaco Editor */}
                {customEditors.find(e => e.id === activeTab) ? (
                  /* Custom Editor (with optional YAML split) */
                  showYamlEditor ? (
                    <Split
                      className="cell-detail-code-yaml-split"
                      direction="horizontal"
                      sizes={codeYamlSplit}
                      minSize={[200, 200]}
                      gutterSize={6}
                      gutterAlign="center"
                      onDragEnd={handleCodeYamlSplitChange}
                    >
                      <div className="cell-detail-custom-editor">
                        {React.createElement(
                          customEditors.find(e => e.id === activeTab).component,
                          {
                            cell,
                            onChange: (updatedCell) => updateCell(index, updatedCell),
                            cellName: cell.name
                          }
                        )}
                      </div>
                      <div className="cell-detail-yaml-section">
                        <div className="cell-detail-yaml-header">
                          <Icon icon="mdi:file-code-outline" width="14" />
                          <span>Full Cell YAML</span>
                          {yamlParseError && (
                            <span className="cell-yaml-error" title={yamlParseError}>
                              <Icon icon="mdi:alert-circle" width="12" />
                              Parse Error
                            </span>
                          )}
                          {!yamlParseError && validation.errorCount > 0 && (
                            <span className="cell-yaml-error" title={`${validation.errorCount} validation error(s)`}>
                              <Icon icon="mdi:alert-circle" width="12" />
                              {validation.errorCount} error{validation.errorCount > 1 ? 's' : ''}
                            </span>
                          )}
                          {!yamlParseError && validation.warningCount > 0 && (
                            <span className="cell-yaml-warning" title={`${validation.warningCount} warning(s)`}>
                              <Icon icon="mdi:alert" width="12" />
                              {validation.warningCount}
                            </span>
                          )}
                          <span className="cell-yaml-hint">Auto-saves on blur</span>
                        </div>
                        <div className="cell-detail-yaml-editor-wrapper">
                          <Editor
                            key={`yaml-${cell.name}`}
                            height="100%"
                            language="yaml"
                            value={cellYaml}
                            onChange={handleYamlChange}
                            theme={STUDIO_THEME_NAME}
                            beforeMount={configureMonacoTheme}
                            onMount={(editor, monaco) => {
                              yamlEditorRef.current = editor;
                              handleEditorMount(editor, monaco);
                              // Add focus/blur handlers
                              editor.onDidFocusEditorText(() => {
                                yamlEditorEverFocusedRef.current = true;
                                setYamlEditorFocused(true);
                              });
                              editor.onDidBlurEditorText(() => {
                                // Only process blur if editor was actually focused by user
                                if (!yamlEditorEverFocusedRef.current) return;
                                const currentValue = editor.getValue();
                                handleYamlBlur(currentValue);
                              });
                            }}
                            options={{
                              minimap: { enabled: false },
                              fontSize: 13,
                              fontFamily: "'Google Sans Code', monospace",
                              lineNumbers: 'on',
                              renderLineHighlightOnlyWhenFocus: true,
                              wordWrap: 'on',
                              automaticLayout: true,
                              scrollBeyondLastLine: false,
                              padding: { top: 12, bottom: 12 },
                            }}
                          />
                        </div>
                        <ValidationPanel
                          errors={validation.errors}
                          warnings={validation.warnings}
                          suggestions={validation.suggestions}
                          isValidating={validation.isValidating}
                          parseError={validation.parseError}
                          collapsed={true}
                        />
                      </div>
                    </Split>
                  ) : (
                    <div className="cell-detail-custom-editor">
                      {React.createElement(
                        customEditors.find(e => e.id === activeTab).component,
                        {
                          cell,
                          onChange: (updatedCell) => updateCell(index, updatedCell),
                          cellName: cell.name
                        }
                      )}
                    </div>
                  )
                ) : (
                  /* Monaco Code Editor (with optional YAML split) */
                  showYamlEditor ? (
                  <Split
                    className="cell-detail-code-yaml-split"
                    direction="horizontal"
                    sizes={codeYamlSplit}
                    minSize={[200, 200]}
                    gutterSize={6}
                    gutterAlign="center"
                    onDragEnd={handleCodeYamlSplitChange}
                  >
                    <div
                      ref={setDropRef}
                      className={`cell-detail-code-section ${isOver ? 'drop-active' : ''}`}
                    >
                      <div className="cell-detail-code-header">
                        <Icon icon="mdi:code-braces" width="14" />
                        <span>
                          {info.codeKey === 'query' ? 'Query' :
                           info.codeKey === 'code' ? 'Code' :
                           info.codeKey === 'instructions' ? 'Instructions' :
                           info.codeKey === 'command' ? 'Command' :
                           info.codeKey === 'inputs' ? 'Inputs' :
                           info.codeKey.charAt(0).toUpperCase() + info.codeKey.slice(1)}
                        </span>
                      </div>
                      <div className="cell-detail-editor-wrapper">
                        {/* DEBUG: Show code value */}
                        {/* <div style={{position: 'absolute', top: 0, right: 0, background: '#ff0066', color: '#fff', padding: '4px', fontSize: '10px', zIndex: 9999}}>
                          code.length={code?.length || 0}
                        </div> */}
                        <Editor
                          key={`editor-${cell.name}`}
                          height="100%"
                        language={info.language}
                        value={code}
                        onChange={handleCodeChange}
                        theme={STUDIO_THEME_NAME}
                        beforeMount={configureMonacoTheme}
                        onMount={(editor, monaco) => {
                          editorRef.current = editor;
                          window.__activeMonacoEditor = editor;
                          handleEditorMount(editor, monaco);
                        }}
                        options={{
                          minimap: { enabled: false },
                          fontSize: 13,
                          fontFamily: "'Google Sans Code', monospace",
                          lineNumbers: 'on',
                          renderLineHighlightOnlyWhenFocus: true,
                          wordWrap: 'on',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                        }}
                        />
                      </div>
                    </div>
                    <div
                      ref={setYamlDropRef}
                      className={`cell-detail-yaml-section ${isYamlOver ? 'drop-active' : ''}`}
                    >
                      <div className="cell-detail-yaml-header">
                        <Icon icon="mdi:file-code-outline" width="14" />
                        <span>Full Cell YAML</span>
                        {yamlParseError && (
                          <span className="cell-yaml-error" title={yamlParseError}>
                            <Icon icon="mdi:alert-circle" width="12" />
                            Parse Error
                          </span>
                        )}
                        {!yamlParseError && validation.errorCount > 0 && (
                          <span className="cell-yaml-error" title={`${validation.errorCount} validation error(s)`}>
                            <Icon icon="mdi:alert-circle" width="12" />
                            {validation.errorCount} error{validation.errorCount > 1 ? 's' : ''}
                          </span>
                        )}
                        {!yamlParseError && validation.warningCount > 0 && (
                          <span className="cell-yaml-warning" title={`${validation.warningCount} warning(s)`}>
                            <Icon icon="mdi:alert" width="12" />
                            {validation.warningCount}
                          </span>
                        )}
                        <span className="cell-yaml-hint">Auto-saves on blur</span>
                      </div>
                      <div className="cell-detail-editor-wrapper">
                        <Editor
                          key={`yaml-${cell.name}`}
                          height="100%"
                          language="yaml"
                          value={cellYaml}
                          onChange={handleYamlChange}
                          theme={STUDIO_THEME_NAME}
                          beforeMount={configureMonacoTheme}
                          onMount={(editor, monaco) => {
                            yamlEditorRef.current = editor;
                            window.__activeMonacoEditor = editor; // Enable drag-and-drop
                            handleEditorMount(editor, monaco);
                            // Add focus/blur handlers
                            editor.onDidFocusEditorText(() => {
                              yamlEditorEverFocusedRef.current = true;
                              setYamlEditorFocused(true);
                              window.__activeMonacoEditor = editor; // Update on focus
                            });
                            editor.onDidBlurEditorText(() => {
                              // Only process blur if editor was actually focused by user
                              if (!yamlEditorEverFocusedRef.current) return;
                              const currentValue = editor.getValue();
                              handleYamlBlur(currentValue);
                            });
                          }}
                          options={{
                            minimap: { enabled: false },
                            fontSize: 12,
                            fontFamily: "'Google Sans Code', 'Menlo', monospace",
                            lineNumbers: 'off',
                            renderLineHighlight: 'line',
                            renderLineHighlightOnlyWhenFocus: true,
                            wordWrap: 'on',
                            wrappingStrategy: 'advanced',
                            automaticLayout: true,
                            scrollBeyondLastLine: false,
                            folding: true,
                            foldingStrategy: 'indentation',
                            showFoldingControls: 'mouseover',
                            bracketPairColorization: { enabled: true },
                            guides: {
                              indentation: true,
                              bracketPairs: true,
                            },
                            padding: { top: 12, bottom: 12 },
                            smoothScrolling: true,
                            cursorBlinking: 'smooth',
                            cursorSmoothCaretAnimation: 'on',
                          }}
                        />
                      </div>
                      <ValidationPanel
                        errors={validation.errors}
                        warnings={validation.warnings}
                        suggestions={validation.suggestions}
                        isValidating={validation.isValidating}
                        parseError={validation.parseError}
                        collapsed={true}
                      />
                    </div>
                  </Split>
                ) : (
                  <div
                    ref={setDropRef}
                    className={`cell-detail-code-section ${isOver ? 'drop-active' : ''}`}
                  >
                    <div className="cell-detail-code-header">
                      <Icon icon="mdi:code-braces" width="14" />
                      <span>
                        {info.codeKey === 'query' ? 'Query' :
                         info.codeKey === 'code' ? 'Code' :
                         info.codeKey === 'instructions' ? 'Instructions' :
                         info.codeKey === 'command' ? 'Command' :
                         info.codeKey.charAt(0).toUpperCase() + info.codeKey.slice(1)}
                      </span>
                    </div>
                    <div className="cell-detail-editor-wrapper">
                      <Editor
                        key={`editor-${cell.name}`}
                        height="100%"
                        language={info.language}
                        value={code}
                        onChange={handleCodeChange}
                        theme={STUDIO_THEME_NAME}
                        beforeMount={configureMonacoTheme}
                        onMount={(editor, monaco) => {
                          editorRef.current = editor;
                          window.__activeMonacoEditor = editor;
                          handleEditorMount(editor, monaco);
                        }}
                        options={{
                          minimap: { enabled: false },
                          fontSize: 13,
                          fontFamily: "'Google Sans Code', monospace",
                          lineNumbers: 'on',
                          wordWrap: 'on',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                        }}
                      />
                    </div>
                  </div>
                )
              )}
              </div>

              {/* Results Section */}
              <div className="cell-detail-results-section">
                <div className="cell-detail-results-header">
                  <div className="cell-detail-results-header-left">
                    {result?.row_count !== undefined && (
                      <span className="cell-detail-row-count">{result.row_count} rows</span>
                    )}
                    {cellState?.duration !== undefined && cellState.duration !== null && (
                      <span className="cell-detail-duration">
                        <Icon icon="mdi:clock-outline" width="12" />
                        {formatDuration(cellState.duration)}
                      </span>
                    )}
                    {cellState?.cost > 0 && (
                      <span className="cell-detail-cost">
                        <Icon icon="mdi:currency-usd" width="12" />
                        ${cellState.cost < 0.01 ? '<0.01' : cellState.cost.toFixed(4)}
                      </span>
                    )}
                    {(cellState?.tokens_in > 0 || cellState?.tokens_out > 0) && (
                      <span className="cell-detail-tokens">
                        <Icon icon="mdi:dice-multiple" width="12" />
                        {cellState.tokens_in || 0}↓ {cellState.tokens_out || 0}↑
                      </span>
                    )}
                  </div>
                  <div className="cell-detail-results-tabs">
                    {/* Decision tab - appears FIRST if present (blocking interaction) */}
                    {checkpointData && (() => {
                      console.log('[CellDetailPanel] Rendering Decision tab button');
                      return (
                        <button
                          className={`cell-detail-results-tab cell-detail-results-tab-decision ${activeOutputTab === 'decision' ? 'active' : ''}`}
                          onClick={() => {
                            console.log('[CellDetailPanel] Decision tab clicked');
                            setActiveOutputTab('decision');
                          }}
                          title={isLiveDecision ? "Human decision required (LIVE)" : "Decision UI (replay)"}
                        >
                          <Icon icon="mdi:hand-front-right" width="14" />
                          Decision
                          {isLiveDecision && <Icon icon="mdi:circle" width="8" style={{ color: '#ef4444', marginLeft: '4px' }} />}
                        </button>
                      );
                    })()}
                    <button
                      className={`cell-detail-results-tab ${activeOutputTab === 'output' ? 'active' : ''}`}
                      onClick={() => setActiveOutputTab('output')}
                    >
                      Output
                    </button>
                    {/* Messages tab - ALWAYS available when there are messages */}
                    {cellMessages.length > 0 && (
                      <button
                        className={`cell-detail-results-tab ${activeOutputTab === 'messages' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('messages')}
                      >
                        <Icon icon="mdi:message-processing" width="14" />
                        Messages ({cellMessages.length})
                      </button>
                    )}
                    {/* Candidate tabs (additional per-candidate views) */}
                    {messagesByCandidate && Object.keys(messagesByCandidate.grouped).sort().map((candidateIdx) => {
                      // Compare as numbers (candidateIdx from Object.keys is string)
                      const isWinner = parseInt(candidateIdx) === messagesByCandidate.winner || candidateIdx === 'main';
                      const count = messagesByCandidate.grouped[candidateIdx].length;

                      // Debug winner detection
                      if (candidateIdx === '0' || candidateIdx === '1') {
                        console.log('[CellDetailPanel] Tab', candidateIdx, '- isWinner:', isWinner, 'winner:', messagesByCandidate.winner, 'parsed:', parseInt(candidateIdx));
                      }

                      return (
                        <button
                          key={candidateIdx}
                          className={`cell-detail-results-tab ${activeOutputTab === `candidate-${candidateIdx}` ? 'active' : ''} ${isWinner ? 'winner' : ''}`}
                          onClick={() => setActiveOutputTab(`candidate-${candidateIdx}`)}
                          title={isWinner ? `Candidate ${candidateIdx} (WINNER - ${count} messages)` : `Candidate ${candidateIdx} (${count} messages)`}
                        >
                          {isWinner && <Icon icon="mdi:crown" width="14" />}
                          <Icon icon="mdi:message-processing" width="14" />
                          C{candidateIdx}
                        </button>
                      );
                    })}
                    {(result && !error) && (
                      <button
                        className={`cell-detail-results-tab ${activeOutputTab === 'raw' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('raw')}
                      >
                        Raw
                      </button>
                    )}
                    {fullRequest && (
                      <button
                        className={`cell-detail-results-tab ${activeOutputTab === 'request' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('request')}
                        title="Full LLM request (for debugging)"
                      >
                        <Icon icon="mdi:api" width="14" />
                        Request
                      </button>
                    )}
                    {images && images.length > 0 && (
                      <button
                        className={`cell-detail-results-tab ${activeOutputTab === 'images' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('images')}
                      >
                        <Icon icon="mdi:image" width="14" />
                        Images ({images.length})
                      </button>
                    )}
                    {error && (
                      <button
                        className={`cell-detail-results-tab ${activeOutputTab === 'error' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('error')}
                      >
                        <Icon icon="mdi:alert-circle" width="14" />
                        Error
                      </button>
                    )}
                  </div>
                </div>
                <div className="cell-detail-results-content">
                  {activeOutputTab === 'decision' && checkpointData && (() => {
                    console.log('[CellDetailPanel] Rendering decision content:', {
                      source: checkpointData.source,
                      hasUiSpec: !!checkpointData.uiSpec,
                      sections: checkpointData.uiSpec?.sections?.length,
                      checkpointId: checkpointData.checkpointId
                    });

                    const htmlSection = checkpointData.uiSpec?.sections?.find(s => s.type === 'html');
                    console.log('[CellDetailPanel] HTML section:', {
                      found: !!htmlSection,
                      contentLength: htmlSection?.content?.length
                    });

                    return (
                      <div className="cell-detail-decision-view">
                        {isLiveDecision && (
                          <div className="cell-detail-decision-live-banner">
                            <Icon icon="mdi:clock-alert" width="16" />
                            <span>Cascade is waiting for your decision</span>
                          </div>
                        )}
                        {htmlSection ? (
                          // Render actual HTMX UI using HTMLSection (same as blockers panel)
                          <HTMLSection
                            spec={htmlSection}
                            checkpointId={checkpointData.checkpointId}
                            sessionId={cascadeSessionId}
                            isSavedCheckpoint={!isLiveDecision}
                          />
                        ) : (
                          // Fallback if no HTML section
                          <div className="cell-detail-decision-fallback">
                            <div className="cell-detail-decision-note">
                              <Icon icon="mdi:information-outline" width="16" />
                              No HTML UI found for this checkpoint
                            </div>
                            <pre className="cell-detail-raw-json">
                              {JSON.stringify(checkpointData, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                  {activeOutputTab === 'output' && (
                    (result || error) ? (
                      <>
                        {/* DEBUG: Show result data */}
                        {/* <div style={{background: '#ff0066', color: '#fff', padding: '4px', fontSize: '10px'}}>
                          DEBUG OUTPUT: hasResult={!!result} hasError={!!error} resultType={typeof result}
                          {result && ` keys=${Object.keys(result).join(',')}`}
                        </div> */}
                        {/* Evaluator reasoning (for candidates) */}
                        {evaluatorMessage && (
                          <div className="cell-detail-evaluator-banner">
                            <div className="cell-detail-evaluator-header">
                              <Icon icon="mdi:scale-balance" width="16" />
                              <span>Evaluator Selection</span>
                              {evaluatorMessage.model && (
                                <span className="cell-detail-evaluator-model">({evaluatorMessage.model})</span>
                              )}
                            </div>
                            <div className="cell-detail-evaluator-content">
                              {typeof evaluatorMessage.content === 'string' ? (
                                <pre>{evaluatorMessage.content}</pre>
                              ) : (
                                <pre>{JSON.stringify(evaluatorMessage.content, null, 2)}</pre>
                              )}
                            </div>
                          </div>
                        )}
                        <ResultRenderer
                          result={result}
                          error={error}
                          images={activeOutputTab === 'output' ? images : null}
                        />
                      </>
                    ) : (
                      <div className="cell-detail-no-data">
                        <Icon icon="mdi:package-variant" width="48" />
                        <p>No output yet</p>
                        <span>Run the cell to see results here</span>
                      </div>
                    )
                  )}
                  {/* Candidate-specific message tabs */}
                  {messagesByCandidate && activeOutputTab.startsWith('candidate-') && (() => {
                    const candidateIdx = activeOutputTab.replace('candidate-', '');
                    const isWinner = parseInt(candidateIdx) === messagesByCandidate.winner || candidateIdx === 'main';

                    return (
                      <div className="cell-detail-candidate-messages-wrapper">
                        {isWinner && (
                          <div className="cell-detail-candidate-winner-banner">
                            <Icon icon="mdi:crown" width="16" />
                            This candidate was selected as the winner
                          </div>
                        )}
                        <SessionMessagesLog
                          logs={cellLogs || []}
                          currentSessionId={currentSessionId}
                          shouldPollBudget={viewMode !== 'replay' && isRunningAll}
                          showFilters={true}
                          filterByCell={cell.name}
                          filterByCandidate={candidateIdx}
                          showCellColumn={false}
                          compact={true}
                          className="cell-detail-messages-log"
                          onMessageClick={onMessageClick}
                          hoveredHash={hoveredHash}
                          onHoverHash={onHoverHash}
                          externalSelectedMessage={externalSelectedMessage}
                        />
                      </div>
                    );
                  })()}
                  {/* Fallback single Messages tab for non-candidate cells */}
                  {activeOutputTab === 'messages' && (
                    <SessionMessagesLog
                      logs={cellLogs || []}
                      currentSessionId={currentSessionId}
                      shouldPollBudget={viewMode !== 'replay' && isRunningAll}
                      showFilters={true}
                      filterByCell={cell.name}
                      showCellColumn={false}
                      compact={true}
                      className="cell-detail-messages-log"
                      onMessageClick={onMessageClick}
                      hoveredHash={hoveredHash}
                      onHoverHash={onHoverHash}
                      externalSelectedMessage={externalSelectedMessage}
                    />
                  )}
                  {activeOutputTab === 'raw' && result && (
                    <div className="cell-detail-monaco-readonly">
                      <Editor
                        height="100%"
                        language="json"
                        value={JSON.stringify(result, null, 2)}
                        theme={STUDIO_THEME_NAME}
                        beforeMount={configureMonacoTheme}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 12,
                          fontFamily: "'Google Sans Code', monospace",
                          lineNumbers: 'on',
                          wordWrap: 'on',
                          wrappingIndent: 'indent',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                          renderLineHighlight: 'none',
                          scrollbar: {
                            vertical: 'auto',
                            horizontal: 'auto',
                            verticalScrollbarSize: 10,
                            horizontalScrollbarSize: 10,
                          },
                        }}
                      />
                    </div>
                  )}
                  {activeOutputTab === 'request' && fullRequest && (
                    <div className="cell-detail-monaco-readonly">
                      <Editor
                        height="100%"
                        language="json"
                        value={JSON.stringify(fullRequest, null, 2)}
                        theme={STUDIO_THEME_NAME}
                        beforeMount={configureMonacoTheme}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 12,
                          fontFamily: "'Google Sans Code', monospace",
                          lineNumbers: 'on',
                          wordWrap: 'on',
                          wrappingIndent: 'indent',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                          renderLineHighlight: 'none',
                          scrollbar: {
                            vertical: 'auto',
                            horizontal: 'auto',
                            verticalScrollbarSize: 10,
                            horizontalScrollbarSize: 10,
                          },
                        }}
                      />
                    </div>
                  )}
                  {activeOutputTab === 'images' && images && images.length > 0 && (
                    <div className="cell-detail-images-only">
                      {images.map((imagePath, idx) => {
                        const imageUrl = imagePath.startsWith('/api')
                          ? `http://localhost:5050${imagePath}`
                          : imagePath;
                        return (
                          <div key={idx} className="cell-detail-image-container">
                            <img
                              src={imageUrl}
                              alt={`Output ${idx + 1}`}
                              onClick={() => setModalImage({ url: imageUrl, path: imagePath })}
                              style={{ cursor: 'pointer' }}
                              title="Click to view full size"
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {activeOutputTab === 'error' && error && (
                    <div className="cell-detail-error-detail">
                      <pre>
                        {typeof error === 'string'
                          ? error.replace(/\\n/g, '\n')
                          : JSON.stringify(error, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            </Split>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        size="sm"
      >
        <ModalHeader
          title="Delete Cell"
          icon="mdi:delete-alert"
        />
        <ModalContent>
          <p style={{ color: 'var(--color-text-secondary)', lineHeight: '1.5' }}>
            Are you sure you want to delete <strong style={{ color: 'var(--color-accent-cyan)' }}>"{cell.name}"</strong>?
          </p>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', marginTop: '8px' }}>
            This action cannot be undone.
          </p>
        </ModalContent>
        <ModalFooter align="right">
          <Button
            variant="secondary"
            onClick={() => setIsDeleteModalOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            icon="mdi:delete"
            onClick={confirmDelete}
          >
            Delete
          </Button>
        </ModalFooter>
      </Modal>

      {/* Image Modal - Full size view */}
      <Modal
        isOpen={!!modalImage}
        onClose={() => setModalImage(null)}
        size="full"
        closeOnBackdrop={true}
        closeOnEscape={true}
        className="result-image-modal"
      >
        {modalImage && (
          <div className="result-modal-image-container">
            <div className="result-modal-image-header">
              <span className="result-modal-image-title">{modalImage.path}</span>
            </div>
            <div className="result-modal-image-body">
              <img
                src={modalImage.url}
                alt="Full size"
                className="result-modal-image"
                onClick={() => setModalImage(null)}
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default CellDetailPanel;
