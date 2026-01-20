import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import CanvasRenderer from './components/CanvasRenderer';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount } from '../../studio/utils/monacoTheme';
import { API_BASE_URL } from '../../config/api';
import './CanvasView.css';

// Default example query using CANVAS/PANEL/GRID syntax
const DEFAULT_QUERY = `-- Canvas: SQL-defined dashboards
-- Compose multiple visualizations into a single view

WITH
  -- Define your data as regular CTEs
  employees AS (
    SELECT * FROM (VALUES
      ('Alice', 28, 'Engineering'),
      ('Bob', 34, 'Marketing'),
      ('Carol', 29, 'Engineering'),
      ('Dave', 42, 'Sales')
    ) AS t(name, age, dept)
  ),
  metrics AS (
    SELECT * FROM (VALUES
      ('Revenue', 125000),
      ('Users', 8420),
      ('Growth', 12.5)
    ) AS t(metric, value)
  )

-- CANVAS composes panels into a dashboard
-- PANEL(title, column, row, cte_reference)
SELECT * FROM CANVAS(
  PANEL('Team', 1, 1, employees),
  PANEL('Metrics', 2, 1, metrics)
) WITH GRID(2, 1)`;

/**
 * CanvasView - Hypermedia SQL Client
 *
 * A simple SQL client where queries return self-describing data.
 * The UI interprets the response format and renders accordingly.
 */
const CanvasView = () => {
  const [sql, setSql] = useState(DEFAULT_QUERY);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [executionTime, setExecutionTime] = useState(null);
  const [databases, setDatabases] = useState([{ name: 'memory', type: 'memory' }]);
  const [selectedDatabase, setSelectedDatabase] = useState('memory');

  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  // Fetch available databases on mount
  useEffect(() => {
    const fetchDatabases = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/sql/databases`);
        const data = await response.json();
        if (data.databases && data.databases.length > 0) {
          setDatabases(data.databases);
        }
      } catch (err) {
        console.error('Failed to fetch databases:', err);
      }
    };
    fetchDatabases();
  }, []);

  // Execute query
  const executeQuery = useCallback(async () => {
    if (!sql.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    const startTime = Date.now();

    try {
      const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: sql, database: selectedDatabase })
      });

      const data = await response.json();

      setExecutionTime(Date.now() - startTime);

      if (!data.success) {
        setError(data.error || 'Query execution failed');
        return;
      }

      setResult(data);
    } catch (err) {
      setError(err.message || 'Failed to execute query');
      setExecutionTime(Date.now() - startTime);
    } finally {
      setLoading(false);
    }
  }, [sql, selectedDatabase]);

  // Handle editor mount
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    handleEditorMount(editor, monaco);

    // Configure SQL settings
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });

    // Ctrl+Enter to execute
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      executeQuery();
    });
  }, [executeQuery]);

  // Editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 13,
    fontFamily: "'Google Sans Code', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    bracketPairColorization: { enabled: true },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    cursorBlinking: 'smooth',
  };

  // Detect if result is a canvas or error
  const isCanvasResult = result?.data?.[0]?.format === 'canvas';
  const canvasData = isCanvasResult ? result.data[0].canvas : null;
  const isErrorResult = result?.data?.[0]?.format === 'error';
  const errorMessage = isErrorResult ? result.data[0].error : null;

  return (
    <div className="canvas-view">
      {/* Header */}
      <div className="canvas-header">
        <div className="canvas-header-left">
          <Icon icon="mdi:view-dashboard-variant" width="22" />
          <h1>Canvas</h1>
          <span className="canvas-subtitle">Hypermedia SQL Client</span>
        </div>
        <div className="canvas-header-right">
          {/* Database selector */}
          <div className="canvas-db-selector">
            <Icon icon="mdi:database" width="14" />
            <select
              value={selectedDatabase}
              onChange={(e) => setSelectedDatabase(e.target.value)}
              className="canvas-db-select"
            >
              {databases.map((db) => (
                <option key={db.name} value={db.name}>
                  {db.name}
                  {db.type === 'persistent' && db.size_mb !== null ? ` (${db.size_mb}MB)` : ''}
                </option>
              ))}
            </select>
          </div>

          {executionTime !== null && (
            <span className="canvas-execution-time">
              {executionTime}ms
            </span>
          )}
          <button
            className="canvas-run-btn"
            onClick={executeQuery}
            disabled={loading || !sql.trim()}
          >
            <Icon
              icon={loading ? "mdi:loading" : "mdi:play"}
              width="16"
              className={loading ? "spinning" : ""}
            />
            Run
          </button>
        </div>
      </div>

      {/* Main layout */}
      <div className="canvas-layout">
        {/* Editor pane */}
        <div className="canvas-editor-pane">
          <div className="canvas-editor-header">
            <Icon icon="mdi:code-tags" width="14" />
            <span>SQL Query</span>
            <span className="canvas-hint">Ctrl+Enter to run</span>
          </div>
          <div className="canvas-editor-wrapper">
            <Editor
              height="100%"
              language="sql"
              theme={STUDIO_THEME_NAME}
              value={sql}
              onChange={setSql}
              onMount={handleEditorDidMount}
              beforeMount={configureMonacoTheme}
              options={editorOptions}
            />
          </div>
        </div>

        {/* Result pane */}
        <div className="canvas-result-pane">
          <div className="canvas-result-header">
            <Icon icon="mdi:monitor-dashboard" width="14" />
            <span>Output</span>
            {result && (
              <span className="canvas-result-info">
                {isCanvasResult
                  ? `${canvasData?.panels?.length || 0} panels`
                  : `${result.row_count} rows`
                }
              </span>
            )}
          </div>
          <div className="canvas-result-wrapper">
            {loading && (
              <div className="canvas-loading">
                <Icon icon="mdi:loading" width="32" className="spinning" />
                <span>Executing query...</span>
              </div>
            )}

            {error && (
              <div className="canvas-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <div className="canvas-error-content">
                  <h3>Error</h3>
                  <pre>{error}</pre>
                </div>
              </div>
            )}

            {!loading && !error && !result && (
              <div className="canvas-empty">
                <Icon icon="mdi:play-circle-outline" width="48" />
                <h3>Run a query to see results</h3>
                <p>Press Ctrl+Enter or click Run</p>
              </div>
            )}

            {!loading && !error && result && isErrorResult && (
              <div className="canvas-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <div className="canvas-error-content">
                  <h3>Query Error</h3>
                  <pre>{errorMessage}</pre>
                </div>
              </div>
            )}

            {!loading && !error && result && !isErrorResult && (
              <CanvasRenderer
                data={result.data}
                columns={result.columns}
                isCanvas={isCanvasResult}
                canvasData={canvasData}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CanvasView;
