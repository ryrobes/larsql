import React, { useState, useRef, useCallback, useMemo } from 'react';
import Split from 'react-split';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { useDroppable } from '@dnd-kit/core';
import yaml from 'js-yaml';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import ResultRenderer from './results/ResultRenderer';
import './PhaseDetailPanel.css';

/**
 * PhaseDetailPanel - Bottom panel showing full phase configuration
 *
 * Tabs:
 * - Code: Monaco editor for SQL/Python/JS/etc
 * - Config: Phase configuration (LLM settings, soundings, wards)
 * - Output: Results table/JSON
 */
const PhaseDetailPanel = ({ phase, index, cellState, onClose }) => {
  const { updateCell, runCell, removeCell, sessionId } = useStudioCascadeStore();
  const [activeTab, setActiveTab] = useState('code');
  const [activeOutputTab, setActiveOutputTab] = useState('output');
  const [showYamlEditor, setShowYamlEditor] = useState(false);
  const [phaseMessages, setPhaseMessages] = useState(null);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const editorRef = useRef(null);
  const yamlEditorRef = useRef(null);

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
  const result = cellState?.result;
  const error = cellState?.error;
  const images = cellState?.images;

  // Debug
  React.useEffect(() => {
    console.log('[PhaseDetailPanel] Phase:', phase.name, 'Status:', status, 'Has result:', !!result, 'Has error:', !!error);
  }, [phase.name, status, result, error]);

  // Fetch phase messages when Messages tab is active
  React.useEffect(() => {
    if (activeOutputTab === 'messages' && sessionId && phase.name && !messagesLoading && !phaseMessages) {
      setMessagesLoading(true);
      fetch(`http://localhost:5001/api/studio/phase-messages/${sessionId}/${encodeURIComponent(phase.name)}`)
        .then(res => res.json())
        .then(data => {
          if (data.messages) {
            setPhaseMessages(data.messages);
          }
        })
        .catch(err => {
          console.error('[PhaseDetailPanel] Failed to fetch phase messages:', err);
        })
        .finally(() => {
          setMessagesLoading(false);
        });
    }
  }, [activeOutputTab, sessionId, phase.name, messagesLoading, phaseMessages]);

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
          /* Code + Results with resizable splitter */
          (result || error) ? (
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
                    {cellState?.duration && (
                      <span className="phase-detail-duration">{Math.round(cellState.duration)}ms</span>
                    )}
                  </div>
                  <div className="phase-detail-results-tabs">
                    <button
                      className={`phase-detail-results-tab ${activeOutputTab === 'output' ? 'active' : ''}`}
                      onClick={() => setActiveOutputTab('output')}
                    >
                      Output
                    </button>
                    {sessionId && (result || error) && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'messages' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('messages')}
                      >
                        <Icon icon="mdi:message-processing" width="14" />
                        Messages
                      </button>
                    )}
                    {(result && !error) && (
                      <button
                        className={`phase-detail-results-tab ${activeOutputTab === 'raw' ? 'active' : ''}`}
                        onClick={() => setActiveOutputTab('raw')}
                      >
                        Raw
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
                  {activeOutputTab === 'output' && (
                    <ResultRenderer
                      result={result}
                      error={error}
                      images={activeOutputTab === 'output' ? images : null}
                      handleMonacoBeforeMount={handleMonacoBeforeMount}
                    />
                  )}
                  {activeOutputTab === 'messages' && (
                    <div className="phase-detail-messages">
                      {messagesLoading ? (
                        <div className="phase-detail-messages-loading">
                          <Icon icon="mdi:loading" className="spin" width="24" />
                          <span>Loading messages...</span>
                        </div>
                      ) : phaseMessages && phaseMessages.length > 0 ? (
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
                                  <pre>{msg.content}</pre>
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
                    <pre className="phase-detail-raw-json">
                      {JSON.stringify(result, null, 2)}
                    </pre>
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
                      <pre>{typeof error === 'string' ? error : JSON.stringify(error, null, 2)}</pre>
                    </div>
                  )}
                </div>
              </div>
            </Split>
          ) : (
            /* No results yet - just code editor (with optional YAML) */
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
                    onMount={(editor) => { editorRef.current = editor; }}
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
          )
        )}
      </div>
    </div>
  );
};

export default PhaseDetailPanel;
