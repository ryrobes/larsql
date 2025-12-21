import React, { useState, useRef, useCallback, useMemo } from 'react';
import Split from 'react-split';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import useNotebookStore from '../stores/notebookStore';
import './PhaseDetailPanel.css';

// Dark AG Grid theme
const detailGridTheme = themeQuartz.withParams({
  backgroundColor: '#080c12',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0b1219',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#0a0e14',
  borderColor: '#1a2028',
  rowBorder: true,
  headerFontSize: 11,
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 12,
  accentColor: '#2dd4bf',
});

/**
 * PhaseDetailPanel - Bottom panel showing full phase configuration
 *
 * Tabs:
 * - Code: Monaco editor for SQL/Python/JS/etc
 * - Config: Phase configuration (LLM settings, soundings, wards)
 * - Output: Results table/JSON
 */
const PhaseDetailPanel = ({ phase, index, cellState, onClose }) => {
  const { updateCell, runCell, removeCell } = useNotebookStore();
  const [activeTab, setActiveTab] = useState('code');
  const editorRef = useRef(null);

  // Cleanup editor on unmount
  React.useEffect(() => {
    return () => {
      if (editorRef.current) {
        try {
          editorRef.current.dispose();
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

  const typeInfo = {
    sql_data: { language: 'sql', codeKey: 'query' },
    python_data: { language: 'python', codeKey: 'code' },
    js_data: { language: 'javascript', codeKey: 'code' },
    clojure_data: { language: 'clojure', codeKey: 'code' },
    windlass_data: { language: 'yaml', codeKey: 'code' },
  };
  const info = typeInfo[phase.tool] || typeInfo.python_data;

  const code = phase.inputs?.[info.codeKey] || '';
  const status = cellState?.status || 'pending';
  const result = cellState?.result;
  const error = cellState?.error;

  const handleCodeChange = useCallback((value) => {
    updateCell(index, { inputs: { ...phase.inputs, [info.codeKey]: value } });
  }, [index, phase.inputs, info.codeKey, updateCell]);

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

  // AG Grid config for DataFrame results
  const gridColumnDefs = useMemo(() => {
    if (!result?.columns) return [];
    return result.columns.map((col) => ({
      field: col,
      headerName: col,
      sortable: true,
      filter: true,
      resizable: true,
      minWidth: 80,
      flex: 1,
    }));
  }, [result?.columns]);

  const gridRowData = useMemo(() => result?.rows || [], [result?.rows]);

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
            <span className="phase-detail-mode-label">
              <Icon icon="mdi:code-braces" width="16" />
              Code Editor
            </span>
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
              {/* Code Editor */}
              <div className="phase-detail-code-section">
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

              {/* Results Section */}
              <div className="phase-detail-results-section">
                <div className="phase-detail-results-header">
                  <span>Output</span>
                  {result?.row_count !== undefined && (
                    <span className="phase-detail-row-count">{result.row_count} rows</span>
                  )}
                  {cellState?.duration && (
                    <span className="phase-detail-duration">{cellState.duration}ms</span>
                  )}
                </div>
                <div className="phase-detail-results-content">
                  {error ? (
                    <div className="phase-detail-error">
                      <span className="phase-detail-error-label">Error:</span>
                      <pre className="phase-detail-error-message">{error}</pre>
                    </div>
                  ) : result?.rows && result?.columns ? (
                    <div className="phase-detail-grid">
                      <AgGridReact
                        rowData={gridRowData}
                        columnDefs={gridColumnDefs}
                        theme={detailGridTheme}
                        animateRows={false}
                        enableCellTextSelection={true}
                        headerHeight={36}
                        rowHeight={28}
                      />
                    </div>
                  ) : result?.result !== undefined ? (
                    <div className="phase-detail-json">
                      <Editor
                        height="100%"
                        language="json"
                        value={JSON.stringify(result.result, null, 2)}
                        theme="detail-dark"
                        beforeMount={handleMonacoBeforeMount}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 13,
                          lineNumbers: 'off',
                          wordWrap: 'on',
                        }}
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </Split>
          ) : (
            /* No results yet - just code editor */
            <div className="phase-detail-code-section phase-detail-code-only">
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
          )
        )}
      </div>
    </div>
  );
};

export default PhaseDetailPanel;
