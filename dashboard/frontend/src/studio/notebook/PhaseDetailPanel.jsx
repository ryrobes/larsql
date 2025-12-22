import React, { useState, useRef, useCallback, useMemo } from 'react';
import Split from 'react-split';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { useDroppable } from '@dnd-kit/core';
import yaml from 'js-yaml';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import ResultRenderer from './results/ResultRenderer';
import HTMLSection from '../../components/sections/HTMLSection';
import './PhaseDetailPanel.css';

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
 * PhaseDetailPanel - Bottom panel showing full phase configuration
 *
 * Tabs:
 * - Code: Monaco editor for SQL/Python/JS/etc
 * - Config: Phase configuration (LLM settings, soundings, wards)
 * - Output: Results table/JSON
 */
const PhaseDetailPanel = ({ phase, index, cellState, phaseLogs = [], allSessionLogs = [], onClose }) => {
  const { updateCell, runCell, removeCell, desiredOutputTab, setDesiredOutputTab, isRunningAll, cascadeSessionId, viewMode } = useStudioCascadeStore();
  const [activeTab, setActiveTab] = useState('code');
  const [activeOutputTab, setActiveOutputTab] = useState('output');
  const [showYamlEditor, setShowYamlEditor] = useState(false);
  const editorRef = useRef(null);
  const yamlEditorRef = useRef(null);

  // Apply desired output tab when it changes (from Media section navigation)
  React.useEffect(() => {
    if (desiredOutputTab) {
      setActiveOutputTab(desiredOutputTab);
      setDesiredOutputTab(null); // Clear after applying
    }
  }, [desiredOutputTab, setDesiredOutputTab]);

  // Make editor droppable
  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `editor-drop-${phase.name}`,
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

  const isSql = phase.tool === 'sql_data';
  const isPython = phase.tool === 'python_data';
  const isJs = phase.tool === 'js_data';
  const isClojure = phase.tool === 'clojure_data';
  const isWindlass = phase.tool === 'windlass_data';
  const isLLMPhase = !phase.tool && phase.instructions;

  const typeInfo = {
    sql_data: { language: 'sql', codeKey: 'query', source: 'inputs' },
    python_data: { language: 'python', codeKey: 'code', source: 'inputs' },
    js_data: { language: 'javascript', codeKey: 'code', source: 'inputs' },
    clojure_data: { language: 'clojure', codeKey: 'code', source: 'inputs' },
    llm_phase: { language: 'markdown', codeKey: 'instructions', source: 'phase' },
    windlass_data: { language: 'yaml', codeKey: 'code', source: 'inputs' },
  };
  const phaseType = phase.tool || (isLLMPhase ? 'llm_phase' : 'python_data');
  const info = typeInfo[phaseType] || typeInfo.python_data;

  const code = info.source === 'inputs'
    ? (phase.inputs?.[info.codeKey] || '')
    : (phase[info.codeKey] || '');
  const status = cellState?.status || 'pending';
  const error = cellState?.error;
  const images = cellState?.images;

  // Debug - only log when we have meaningful stats
  React.useEffect(() => {
    if (cellState?.duration || cellState?.cost || cellState?.tokens_in) {
      console.log('[PhaseDetailPanel]', phase.name, '- Duration:', cellState.duration, 'Cost:', cellState.cost, 'Tokens:', cellState.tokens_in, '/', cellState.tokens_out);
    }
  }, [phase.name, cellState]);

  // Group messages by sounding index
  const messagesBySounding = React.useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return null;

    const grouped = {};
    let winningIndex = null;
    const hasAnySounding = phaseLogs.some(log =>
      log.sounding_index !== null && log.sounding_index !== undefined
    );

    if (!hasAnySounding) {
      // No soundings - return all messages in single group
      return null;
    }

    for (const log of phaseLogs) {
      if (log.winning_sounding_index !== null && log.winning_sounding_index !== undefined) {
        winningIndex = log.winning_sounding_index;
      }
    }

    for (const log of phaseLogs) {
      if (!['user', 'assistant', 'tool', 'system'].includes(log.role)) continue;

      const soundingIdx = log.sounding_index ?? 'main';
      if (!grouped[soundingIdx]) {
        grouped[soundingIdx] = [];
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

      grouped[soundingIdx].push({
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
        has_images: log.has_images
      });
    }

    return { grouped, winner: winningIndex };
  }, [phaseLogs]);

  // Process phase logs into messages (filtering for relevant roles) - fallback for non-sounding phases
  const phaseMessages = React.useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return [];

    // Check if phase has soundings - if so, skip this (use sounding tabs instead)
    const hasAnySounding = phaseLogs.some(log =>
      log.sounding_index !== null && log.sounding_index !== undefined
    );
    if (hasAnySounding) return [];

    return phaseLogs
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
          has_images: log.has_images
        };
      });
  }, [phaseLogs]);

  // Use result directly from cellState (don't override it)
  const result = cellState?.result;

  // Extract evaluator message (explains why winner was chosen)
  const evaluatorMessage = React.useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return null;

    const evaluatorLog = phaseLogs.find(log => log.role === 'evaluator');
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
  }, [phaseLogs]);

  // Extract checkpoint/decision data - supports BOTH checkpoint-based AND tag-based decisions
  const checkpointData = React.useMemo(() => {
    // PATH 1: Look for checkpoint_waiting event in ALL session logs (might not have phase_name)
    // Check allSessionLogs first, then fall back to phaseLogs
    const logsToSearch = allSessionLogs.length > 0 ? allSessionLogs : phaseLogs;

    if (!logsToSearch || logsToSearch.length === 0) return null;

    const checkpointLog = logsToSearch.find(log => log.role === 'checkpoint_waiting');
    if (checkpointLog) {
      console.log('[PhaseDetailPanel] Found checkpoint_waiting log in session logs');

      let metadata = checkpointLog.metadata_json;
      if (typeof metadata === 'string') {
        try {
          metadata = JSON.parse(metadata);
        } catch (e) {
          console.error('[PhaseDetailPanel] Failed to parse metadata_json:', e);
        }
      }

      if (metadata?.ui_spec && metadata?.checkpoint_id) {
        let uiSpec = metadata.ui_spec;
        if (typeof uiSpec === 'string') {
          try {
            uiSpec = JSON.parse(uiSpec);
          } catch {}
        }

        console.log('[PhaseDetailPanel] Using checkpoint ui_spec:', {
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
    for (const log of phaseLogs) {
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
            console.log('[PhaseDetailPanel] Found <decision> tag - building ui_spec');

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
            console.error('[PhaseDetailPanel] Failed to parse <decision> JSON:', e);
          }
        }
      }
    }

    console.log('[PhaseDetailPanel] No checkpoint or decision found');
    return null;
  }, [phaseLogs, allSessionLogs]);

  // Build HTML for decision tag (converts JSON to HTMX form)
  const buildDecisionHTML = (decisionData) => {
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
  };

  // Extract full_request_json from logs for debugging
  const fullRequest = React.useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return null;

    // Find the first log with full_request_json
    const logWithRequest = phaseLogs.find(log => log.full_request_json);
    if (!logWithRequest) return null;

    let request = logWithRequest.full_request_json;
    if (typeof request === 'string') {
      try {
        request = JSON.parse(request);
      } catch (e) {
        console.error('[PhaseDetailPanel] Failed to parse request JSON:', e);
      }
    }
    return request;
  }, [phaseLogs]);

  // Auto-select winner sounding tab when phase changes and has soundings
  React.useEffect(() => {
    if (messagesBySounding && messagesBySounding.winner !== null) {
      setActiveOutputTab(`sounding-${messagesBySounding.winner}`);
    }
  }, [phase.name, messagesBySounding]);

  // Serialize phase to YAML for YAML editor
  const phaseYaml = useMemo(() => {
    try {
      return yaml.dump(phase, { indent: 2, lineWidth: -1 });
    } catch (e) {
      return `# Error serializing phase:\n# ${e.message}`;
    }
  }, [phase]);

  const handleYamlChange = useCallback((value) => {
    try {
      const parsed = yaml.load(value);
      // Update entire phase object
      updateCell(index, parsed);
    } catch (e) {
      // Invalid YAML - don't update (user is still typing)
      console.debug('YAML parse error:', e.message);
    }
  }, [index, updateCell]);

  const handleCodeChange = useCallback((value) => {
    if (info.source === 'inputs') {
      updateCell(index, { inputs: { ...phase.inputs, [info.codeKey]: value } });
    } else {
      updateCell(index, { [info.codeKey]: value });
    }
  }, [index, phase.inputs, info.codeKey, info.source, updateCell]);

  const handleNameChange = (e) => {
    updateCell(index, { name: e.target.value });
  };

  const handleRun = () => {
    runCell(phase.name);
  };

  const handleDelete = () => {
    if (window.confirm(`Delete phase "${phase.name}"?`)) {
      removeCell(index);
      onClose();
    }
  };

  // Determine if this is a LIVE decision (actively waiting) vs replay
  const isLiveDecision = React.useMemo(() => {
    if (!checkpointData) return false;

    // Tag-based decisions (<decision> in message) have no checkpoint - can't submit
    if (checkpointData.source === 'decision_tag') {
      console.log('[PhaseDetailPanel] Decision tag detected - no checkpoint to submit to, read-only');
      return false;
    }

    // If in replay mode, never live
    if (viewMode === 'replay') return false;

    // Check if already responded to
    const hasResponse = phaseLogs?.some(log =>
      log.role === 'checkpoint_responded' || log.role === 'checkpoint_cancelled'
    );

    // Live if in live mode, has checkpoint, and not yet responded
    const isLive = viewMode === 'live' && !hasResponse && checkpointData.checkpointId;
    console.log('[PhaseDetailPanel] Decision live status:', {
      viewMode,
      hasResponse,
      isLive,
      checkpointId: checkpointData.checkpointId,
      source: checkpointData.source
    });
    return isLive;
  }, [checkpointData, viewMode, phaseLogs]);

  // Auto-select decision tab when it's live (most important - it's blocking!)
  React.useEffect(() => {
    if (checkpointData && isLiveDecision) {
      setActiveOutputTab('decision');
    }
  }, [phase.name, checkpointData, isLiveDecision]);

  // Monaco theme
  const handleMonacoBeforeMount = (monaco) => {
    monaco.editor.defineTheme('detail-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: 'ff9eb8', fontStyle: 'bold' },
        { token: 'string', foreground: '9be9a8' },
        { token: 'number', foreground: 'd2a8ff' },
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
      ],
      colors: {
        'editor.background': '#0a0e14',
        'editor.foreground': '#e6edf3',
        'editorLineNumber.foreground': '#6e7681',
        'editor.lineHighlightBackground': '#161b22',
      }
    });
  };


  return (
    <div className="phase-detail-panel">
      {/* Header */}
      <div className="phase-detail-header">
        <div className="phase-detail-header-left">
          <input
            className="phase-detail-name-input"
            value={phase.name}
            onChange={handleNameChange}
            placeholder="phase_name"
          />
          <span className="phase-detail-index">#{index + 1}</span>
        </div>

        <div className="phase-detail-header-center">
          {isWindlass && (
            <>
              <button
                className={`phase-detail-tab ${activeTab === 'code' ? 'active' : ''}`}
                onClick={() => setActiveTab('code')}
              >
                <Icon icon="mdi:code-braces" width="16" />
                Code
              </button>
              <button
                className={`phase-detail-tab ${activeTab === 'config' ? 'active' : ''}`}
                onClick={() => setActiveTab('config')}
              >
                <Icon icon="mdi:cog" width="16" />
                Config
              </button>
            </>
          )}
          {!isWindlass && (
            <div className="phase-detail-mode-label">
              <Icon icon="mdi:code-braces" width="16" />
              Code Editor
              <button
                className={`phase-detail-yaml-toggle ${showYamlEditor ? 'active' : ''}`}
                onClick={() => setShowYamlEditor(!showYamlEditor)}
                title={showYamlEditor ? 'Hide YAML editor' : 'Show YAML editor'}
              >
                <Icon icon="mdi:code-json" width="14" />
                YAML
              </button>
            </div>
          )}
        </div>

        <div className="phase-detail-header-right">
          <button
            className="phase-detail-btn phase-detail-btn-run"
            onClick={handleRun}
            disabled={status === 'running'}
          >
            {status === 'running' ? (
              <span className="phase-detail-spinner" />
            ) : (
              <Icon icon="mdi:play" width="16" />
            )}
            Run
          </button>
          <button
            className="phase-detail-btn phase-detail-btn-delete"
            onClick={handleDelete}
          >
            <Icon icon="mdi:delete" width="16" />
          </button>
          <button
            className="phase-detail-btn phase-detail-btn-close"
            onClick={onClose}
          >
            <Icon icon="mdi:close" width="16" />
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="phase-detail-body">
        {activeTab === 'config' && isWindlass ? (
          <div className="phase-detail-config">
            <div className="phase-detail-config-section">
              <h4>LLM Configuration</h4>
              <p className="phase-detail-placeholder">
                Config UI coming soon: model selection, soundings, wards, handoffs...
              </p>
            </div>
          </div>
        ) : (
          /* Code + Results with resizable splitter (always shown) */
          <Split
            className="phase-detail-split"
            direction="vertical"
            sizes={[60, 40]}
            minSize={[100, 100]}
            gutterSize={6}
            gutterAlign="center"
          >
              {/* Code Editor Container (keeps consistent structure for Split) */}
              <div className="phase-detail-code-container">
                {showYamlEditor ? (
                  <Split
                    className="phase-detail-code-yaml-split"
                    direction="horizontal"
                    sizes={[60, 40]}
                    minSize={[200, 200]}
                    gutterSize={6}
                    gutterAlign="center"
                  >
                    <div
                      ref={setDropRef}
                      className={`phase-detail-code-section ${isOver ? 'drop-active' : ''}`}
                    >
                      <Editor
                        key={`editor-${phase.name}`}
                        height="100%"
                        language={info.language}
                        value={code}
                        onChange={handleCodeChange}
                        theme="detail-dark"
                        beforeMount={handleMonacoBeforeMount}
                        onMount={(editor) => {
                          editorRef.current = editor;
                          window.__activeMonacoEditor = editor;
                        }}
                        options={{
                          minimap: { enabled: false },
                          fontSize: 13,
                          fontFamily: "'IBM Plex Mono', monospace",
                          lineNumbers: 'on',
                          renderLineHighlightOnlyWhenFocus: true,
                          wordWrap: 'on',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                        }}
                      />
                    </div>
                    <div className="phase-detail-yaml-section">
                      <div className="phase-detail-yaml-header">
                        <Icon icon="mdi:file-code-outline" width="14" />
                        <span>Full Phase YAML</span>
                      </div>
                      <Editor
                        key={`yaml-${phase.name}`}
                        height="100%"
                        language="yaml"
                        value={phaseYaml}
                        onChange={handleYamlChange}
                        theme="detail-dark"
                        beforeMount={handleMonacoBeforeMount}
                        onMount={(editor) => { yamlEditorRef.current = editor; }}
                        options={{
                          minimap: { enabled: false },
                          fontSize: 12,
                          fontFamily: "'IBM Plex Mono', monospace",
                          lineNumbers: 'on',
                          renderLineHighlightOnlyWhenFocus: true,
                          wordWrap: 'on',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                          padding: { top: 12, bottom: 12 },
                        }}
                      />
                    </div>
                  </Split>
                ) : (
                  <div
                    ref={setDropRef}
                    className={`phase-detail-code-section ${isOver ? 'drop-active' : ''}`}
                  >
                    <Editor
                      key={`editor-${phase.name}`}
                      height="100%"
                      language={info.language}
                      value={code}
                      onChange={handleCodeChange}
                      theme="detail-dark"
                      beforeMount={handleMonacoBeforeMount}
                      onMount={(editor) => {
                        editorRef.current = editor;
                        window.__activeMonacoEditor = editor;
                      }}
                      options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        fontFamily: "'IBM Plex Mono', monospace",
                        lineNumbers: 'on',
                        wordWrap: 'on',
                        automaticLayout: true,
                        scrollBeyondLastLine: false,
                        padding: { top: 12, bottom: 12 },
                      }}
                    />
                  </div>
                )}
              </div>

              {/* Results Section */}
              <div className="phase-detail-results-section">
                <div className="phase-detail-results-header">
                  <div className="phase-detail-results-header-left">
                    {result?.row_count !== undefined && (
                      <span className="phase-detail-row-count">{result.row_count} rows</span>
                    )}
                    {cellState?.duration !== undefined && cellState.duration !== null && (
                      <span className="phase-detail-duration">
                        <Icon icon="mdi:clock-outline" width="12" />
                        {formatDuration(cellState.duration)}
                      </span>
                    )}
                    {cellState?.cost > 0 && (
                      <span className="phase-detail-cost">
                        <Icon icon="mdi:currency-usd" width="12" />
                        ${cellState.cost < 0.01 ? '<0.01' : cellState.cost.toFixed(4)}
                      </span>
                    )}
                    {(cellState?.tokens_in > 0 || cellState?.tokens_out > 0) && (
                      <span className="phase-detail-tokens">
                        <Icon icon="mdi:dice-multiple" width="12" />
                        {cellState.tokens_in || 0}↓ {cellState.tokens_out || 0}↑
                      </span>
                    )}
                  </div>
                  <div className="phase-detail-results-tabs">
                    {/* Decision tab - appears FIRST if present (blocking interaction) */}
                    {checkpointData && (
                      <button
                        className={`phase-detail-results-tab phase-detail-results-tab-decision ${activeOutputTab === 'decision' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('decision')}
                        title={isLiveDecision ? "Human decision required (LIVE)" : "Decision UI (replay)"}
                      >
                        <Icon icon="mdi:hand-front-right" width="14" />
                        Decision
                        {isLiveDecision && <Icon icon="mdi:circle" width="8" style={{ color: '#ef4444', marginLeft: '4px' }} />}
                      </button>
                    )}
                    <button
                      className={`phase-detail-results-tab ${activeOutputTab === 'output' ? 'active' : ''}`}
                      onClick={() => setActiveOutputTab('output')}
                    >
                      Output
                    </button>
                    {/* Sounding tabs OR single Messages tab */}
                    {messagesBySounding ? (
                      // Multiple soundings - show tab per sounding
                      Object.keys(messagesBySounding.grouped).sort().map((soundingIdx) => {
                        // Compare as numbers (soundingIdx from Object.keys is string)
                        const isWinner = parseInt(soundingIdx) === messagesBySounding.winner || soundingIdx === 'main';
                        const count = messagesBySounding.grouped[soundingIdx].length;

                        // Debug winner detection
                        if (soundingIdx === '0' || soundingIdx === '1') {
                          console.log('[PhaseDetailPanel] Tab', soundingIdx, '- isWinner:', isWinner, 'winner:', messagesBySounding.winner, 'parsed:', parseInt(soundingIdx));
                        }

                        return (
                          <button
                            key={soundingIdx}
                            className={`phase-detail-results-tab ${activeOutputTab === `sounding-${soundingIdx}` ? 'active' : ''} ${isWinner ? 'winner' : ''}`}
                            onClick={() => setActiveOutputTab(`sounding-${soundingIdx}`)}
                            title={isWinner ? `Sounding ${soundingIdx} (WINNER - ${count} messages)` : `Sounding ${soundingIdx} (${count} messages)`}
                          >
                            {isWinner && <Icon icon="mdi:crown" width="14" />}
                            <Icon icon="mdi:message-processing" width="14" />
                            S{soundingIdx}
                          </button>
                        );
                      })
                    ) : (
                      // No soundings - single Messages tab
                      phaseMessages.length > 0 && (
                        <button
                          className={`phase-detail-results-tab ${activeOutputTab === 'messages' ? 'active' : ''}`}
                          onClick={() => setActiveOutputTab('messages')}
                        >
                          <Icon icon="mdi:message-processing" width="14" />
                          Messages ({phaseMessages.length})
                        </button>
                      )
                    )}
                    {(result && !error) && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'raw' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('raw')}
                      >
                        Raw
                      </button>
                    )}
                    {fullRequest && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'request' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('request')}
                        title="Full LLM request (for debugging)"
                      >
                        <Icon icon="mdi:api" width="14" />
                        Request
                      </button>
                    )}
                    {images && images.length > 0 && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'images' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('images')}
                      >
                        <Icon icon="mdi:image" width="14" />
                        Images ({images.length})
                      </button>
                    )}
                    {error && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'error' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('error')}
                      >
                        <Icon icon="mdi:alert-circle" width="14" />
                        Error
                      </button>
                    )}
                  </div>
                </div>
                <div className="phase-detail-results-content">
                  {activeOutputTab === 'decision' && checkpointData && (
                    <div className="phase-detail-decision-view">
                      {isLiveDecision && (
                        <div className="phase-detail-decision-live-banner">
                          <Icon icon="mdi:clock-alert" width="16" />
                          <span>Cascade is waiting for your decision</span>
                        </div>
                      )}
                      {checkpointData.uiSpec?.sections?.find(s => s.type === 'html') ? (
                        // Render actual HTMX UI using HTMLSection (same as blockers panel)
                        <HTMLSection
                          spec={checkpointData.uiSpec.sections.find(s => s.type === 'html')}
                          checkpointId={checkpointData.checkpointId}
                          sessionId={cascadeSessionId}
                          isSavedCheckpoint={!isLiveDecision}
                        />
                      ) : (
                        // Fallback if no HTML section
                        <div className="phase-detail-decision-fallback">
                          <div className="phase-detail-decision-note">
                            <Icon icon="mdi:information-outline" width="16" />
                            No HTML UI found for this checkpoint
                          </div>
                          <pre className="phase-detail-raw-json">
                            {JSON.stringify(checkpointData.uiSpec, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                  {activeOutputTab === 'output' && (
                    (result || error) ? (
                      <>
                        {/* Evaluator reasoning (for soundings) */}
                        {evaluatorMessage && (
                          <div className="phase-detail-evaluator-banner">
                            <div className="phase-detail-evaluator-header">
                              <Icon icon="mdi:scale-balance" width="16" />
                              <span>Evaluator Selection</span>
                              {evaluatorMessage.model && (
                                <span className="phase-detail-evaluator-model">({evaluatorMessage.model})</span>
                              )}
                            </div>
                            <div className="phase-detail-evaluator-content">
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
                          handleMonacoBeforeMount={handleMonacoBeforeMount}
                        />
                      </>
                    ) : (
                      <div className="phase-detail-no-data">
                        <Icon icon="mdi:package-variant" width="48" />
                        <p>No output yet</p>
                        <span>Run the phase to see results here</span>
                      </div>
                    )
                  )}
                  {/* Sounding-specific message tabs */}
                  {messagesBySounding && activeOutputTab.startsWith('sounding-') && (
                    <div className="phase-detail-messages">
                      {(() => {
                        const soundingIdx = activeOutputTab.replace('sounding-', '');
                        const messages = messagesBySounding.grouped[soundingIdx] || [];
                        const isWinner = parseInt(soundingIdx) === messagesBySounding.winner || soundingIdx === 'main';

                        return messages.length > 0 ? (
                          <div className="phase-detail-messages-list">
                            {isWinner && (
                              <div className="phase-detail-sounding-winner-banner">
                                <Icon icon="mdi:crown" width="16" />
                                This sounding was selected as the winner
                              </div>
                            )}
                            {messages.map((msg, idx) => (
                              <div key={idx} className={`phase-detail-message phase-detail-message-${msg.role}`}>
                                <div className="phase-detail-message-header">
                                  <div className="phase-detail-message-role">
                                    {msg.role === 'tool' && <Icon icon="mdi:hammer-wrench" width="16" />}
                                    {msg.role === 'assistant' && <Icon icon="mdi:robot" width="16" />}
                                    {msg.role === 'user' && <Icon icon="mdi:account" width="16" />}
                                    {msg.role === 'system' && <Icon icon="mdi:cog" width="16" />}
                                    <span>{msg.role}</span>
                                    {msg.node_type && msg.node_type !== msg.role && (
                                      <span className="phase-detail-message-node-type">({msg.node_type})</span>
                                    )}
                                  </div>
                                  <div className="phase-detail-message-meta">
                                    {msg.duration_ms && (
                                      <span className="phase-detail-message-duration">
                                        <Icon icon="mdi:clock-outline" width="12" />
                                        {Math.round(msg.duration_ms)}ms
                                      </span>
                                    )}
                                    {msg.turn_number && (
                                      <span className="phase-detail-message-turn">Turn {msg.turn_number}</span>
                                    )}
                                    {msg.cost > 0 && (
                                      <span className="phase-detail-message-cost">
                                        <Icon icon="mdi:currency-usd" width="12" />
                                        ${msg.cost.toFixed(4)}
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <div className="phase-detail-message-content">
                                  {typeof msg.content === 'string' ? (
                                    msg.content.length > 50 && (msg.content.includes('#') || msg.content.includes('**') || msg.content.includes('```')) ? (
                                      <div className="phase-detail-message-markdown">
                                        <pre>{msg.content.replace(/\\n/g, '\n')}</pre>
                                      </div>
                                    ) : (
                                      <pre>{msg.content.replace(/\\n/g, '\n')}</pre>
                                    )
                                  ) : (
                                    <pre>{JSON.stringify(msg.content, null, 2)}</pre>
                                  )}
                                </div>
                                {msg.tool_calls && msg.tool_calls.length > 0 && (
                                  <div className="phase-detail-message-tool-calls">
                                    <div className="phase-detail-message-tool-calls-header">
                                      <Icon icon="mdi:hammer-wrench" width="14" />
                                      Tool Calls ({msg.tool_calls.length})
                                    </div>
                                    {msg.tool_calls.map((call, callIdx) => (
                                      <div key={callIdx} className="phase-detail-tool-call">
                                        <strong>{call.function?.name || call.name}</strong>
                                        <pre>{JSON.stringify(call.function?.arguments || call.arguments, null, 2)}</pre>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="phase-detail-messages-empty">
                            <Icon icon="mdi:message-off" width="48" />
                            <p>No messages found for sounding {soundingIdx}</p>
                          </div>
                        );
                      })()}
                    </div>
                  )}
                  {/* Fallback single Messages tab for non-sounding phases */}
                  {activeOutputTab === 'messages' && (
                    <div className="phase-detail-messages">
                      {phaseMessages && phaseMessages.length > 0 ? (
                        <div className="phase-detail-messages-list">
                          {phaseMessages.map((msg, idx) => (
                            <div key={idx} className={`phase-detail-message phase-detail-message-${msg.role}`}>
                              <div className="phase-detail-message-header">
                                <div className="phase-detail-message-role">
                                  {msg.role === 'tool' && <Icon icon="mdi:hammer-wrench" width="16" />}
                                  {msg.role === 'assistant' && <Icon icon="mdi:robot" width="16" />}
                                  {msg.role === 'user' && <Icon icon="mdi:account" width="16" />}
                                  {msg.role === 'system' && <Icon icon="mdi:cog" width="16" />}
                                  <span>{msg.role}</span>
                                  {msg.node_type && msg.node_type !== msg.role && (
                                    <span className="phase-detail-message-node-type">({msg.node_type})</span>
                                  )}
                                </div>
                                <div className="phase-detail-message-meta">
                                  {msg.duration_ms && (
                                    <span className="phase-detail-message-duration">
                                      <Icon icon="mdi:clock-outline" width="12" />
                                      {Math.round(msg.duration_ms)}ms
                                    </span>
                                  )}
                                  {msg.turn_number && (
                                    <span className="phase-detail-message-turn">Turn {msg.turn_number}</span>
                                  )}
                                  {msg.cost > 0 && (
                                    <span className="phase-detail-message-cost">
                                      <Icon icon="mdi:currency-usd" width="12" />
                                      ${msg.cost.toFixed(4)}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div className="phase-detail-message-content">
                                {typeof msg.content === 'string' ? (
                                  msg.content.length > 50 && (msg.content.includes('#') || msg.content.includes('**') || msg.content.includes('```')) ? (
                                    <div className="phase-detail-message-markdown">
                                      <pre>{msg.content.replace(/\\n/g, '\n')}</pre>
                                    </div>
                                  ) : (
                                    <pre>{msg.content.replace(/\\n/g, '\n')}</pre>
                                  )
                                ) : (
                                  <pre>{JSON.stringify(msg.content, null, 2)}</pre>
                                )}
                              </div>
                              {msg.tool_calls && msg.tool_calls.length > 0 && (
                                <div className="phase-detail-message-tool-calls">
                                  <div className="phase-detail-message-tool-calls-header">
                                    <Icon icon="mdi:hammer-wrench" width="14" />
                                    Tool Calls ({msg.tool_calls.length})
                                  </div>
                                  {msg.tool_calls.map((call, callIdx) => (
                                    <div key={callIdx} className="phase-detail-tool-call">
                                      <strong>{call.function?.name || call.name}</strong>
                                      <pre>{JSON.stringify(call.function?.arguments || call.arguments, null, 2)}</pre>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="phase-detail-messages-empty">
                          <Icon icon="mdi:message-off" width="48" />
                          <p>No messages found for this phase</p>
                        </div>
                      )}
                    </div>
                  )}
                  {activeOutputTab === 'raw' && result && (
                    <div className="phase-detail-monaco-readonly">
                      <Editor
                        height="100%"
                        language="json"
                        value={JSON.stringify(result, null, 2)}
                        theme="detail-dark"
                        beforeMount={handleMonacoBeforeMount}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 12,
                          fontFamily: "'IBM Plex Mono', monospace",
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
                    <div className="phase-detail-monaco-readonly">
                      <Editor
                        height="100%"
                        language="json"
                        value={JSON.stringify(fullRequest, null, 2)}
                        theme="detail-dark"
                        beforeMount={handleMonacoBeforeMount}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 12,
                          fontFamily: "'IBM Plex Mono', monospace",
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
                    <div className="phase-detail-images-only">
                      {images.map((imagePath, idx) => {
                        const imageUrl = imagePath.startsWith('/api')
                          ? `http://localhost:5001${imagePath}`
                          : imagePath;
                        return (
                          <div key={idx} className="phase-detail-image-container">
                            <img src={imageUrl} alt={`Output ${idx + 1}`} />
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {activeOutputTab === 'error' && error && (
                    <div className="phase-detail-error-detail">
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
    </div>
  );
};

export default PhaseDetailPanel;
