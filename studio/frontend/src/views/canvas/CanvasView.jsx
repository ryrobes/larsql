import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import CanvasRenderer from './components/CanvasRenderer';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount } from '../../studio/utils/monacoTheme';
import { API_BASE_URL } from '../../config/api';
import { fillCascadeTemplate } from './utils/cascadeTemplate';
import './CanvasView.css';

// Default example query demonstrating SQL-native chart specs
const DEFAULT_QUERY = `-- SQL-Native Charts Demo with Interactive Filters
-- ON_SELECT[] = multi-select (checkboxes), ON_SELECT = single-select (click row)
-- Charts use format + config columns - data comes from the query itself

CREATE OR REPLACE TABLE sales AS
SELECT * FROM (VALUES
  ('Jan', 'Electronics', 12400, 89),
  ('Jan', 'Clothing', 8200, 156),
  ('Jan', 'Food', 15600, 423),
  ('Feb', 'Electronics', 14100, 102),
  ('Feb', 'Clothing', 9800, 178),
  ('Feb', 'Food', 14200, 398),
  ('Mar', 'Electronics', 15800, 118),
  ('Mar', 'Clothing', 11200, 201),
  ('Mar', 'Food', 16800, 445),
  ('Apr', 'Electronics', 13900, 95),
  ('Apr', 'Clothing', 12400, 223),
  ('Apr', 'Food', 18200, 489)
) AS t(month, category, revenue, units);

--- PANEL 'Categories' (1, 1, 1, 1) ON_SELECT[] @params_set('cats', category)
SELECT DISTINCT category FROM sales;

--- PANEL 'Months' (2, 1, 1, 1) ON_SELECT @param_set('month', month)
SELECT DISTINCT month FROM sales;

--- PANEL 'Monthly Trend' (1, 2, 1, 1)
SELECT
  'vega-lite' as format,
  {mark: 'line', x: 'month', y: 'total_revenue', title: 'Monthly Revenue'} as config,
  month, SUM(revenue) as total_revenue
FROM sales
WHERE (CASE WHEN len(@params_get('cats')) = 0 THEN true ELSE list_contains(@params_get('cats'), category) END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END)
GROUP BY month;

--- PANEL 'Category Breakdown' (2, 2, 1, 1)
SELECT
  'plotly' as format,
  {type: 'pie', values: 'revenue', labels: 'category', title: 'Revenue by Category'} as config,
  category, SUM(revenue) as revenue
FROM sales
WHERE (CASE WHEN len(@params_get('cats')) = 0 THEN true ELSE list_contains(@params_get('cats'), category) END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END)
GROUP BY category;

--- PANEL 'Revenue by Category' (1, 3, 1, 1)
SELECT
  'vega-lite' as format,
  {
    mark: {type: 'bar', cornerRadius: 4},
    encoding: {
      x: {field: 'category', type: 'nominal', axis: {labelAngle: 0}},
      y: {field: 'revenue', type: 'quantitative', title: 'Revenue ($)'},
      color: {field: 'category', type: 'nominal', legend: null}
    }
  } as config,
  category, SUM(revenue) as revenue
FROM sales
WHERE (CASE WHEN len(@params_get('cats')) = 0 THEN true ELSE list_contains(@params_get('cats'), category) END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END)
GROUP BY category;

--- PANEL 'Stacked Area' (2, 3, 1, 1)
SELECT
  'vega-lite' as format,
  {
    mark: 'area',
    encoding: {
      x: {field: 'month', type: 'ordinal'},
      y: {field: 'revenue', type: 'quantitative', stack: 'zero'},
      color: {field: 'category', type: 'nominal'}
    }
  } as config,
  month, category, revenue
FROM sales
WHERE (CASE WHEN len(@params_get('cats')) = 0 THEN true ELSE list_contains(@params_get('cats'), category) END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END);`;

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

  // Track previous panel data for smart re-render diffing
  const prevPanelsRef = useRef({});

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

      // Update previous panels ref for smart diffing
      if (data.multi_panel && data.panels) {
        const panelMap = {};
        data.panels.forEach(p => {
          panelMap[p.name] = JSON.stringify(p.data);
        });
        prevPanelsRef.current = panelMap;
      }

      setResult(data);
    } catch (err) {
      setError(err.message || 'Failed to execute query');
      setExecutionTime(Date.now() - startTime);
    } finally {
      setLoading(false);
    }
  }, [sql, selectedDatabase]);

  // Handle panel interactions (clicks, etc.)
  // Executes the cascade and re-runs the dashboard
  const handleInteraction = useCallback(async (event) => {
    const { panelName, data: rowData, onSelectTemplate } = event;

    if (!onSelectTemplate) return;

    let cascadeToExecute;

    // Check for deselect (toggle off) - single-select only
    if (rowData._isDeselect) {
      // Extract param key from template like @param_set('level', level)
      const match = onSelectTemplate.match(/@param_set\(['"]([^'"]+)['"]/);
      if (match) {
        cascadeToExecute = `@param_clear('${match[1]}')`;
      } else {
        return; // Can't determine param key
      }
    } else {
      // Fill the cascade template with values from clicked row
      cascadeToExecute = fillCascadeTemplate(onSelectTemplate, rowData);
    }

    try {
      // Execute the cascade (e.g., @param_set('region', 'US') or @param_clear('region'))
      await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: `SELECT ${cascadeToExecute}`,
          database: selectedDatabase
        })
      });

      // Re-run the entire dashboard query
      // The smart diffing happens in React - panels with unchanged data
      // will keep their identity and not re-render
      const startTime = Date.now();

      const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: sql, database: selectedDatabase })
      });

      const newResult = await response.json();
      setExecutionTime(Date.now() - startTime);

      if (!newResult.success) {
        setError(newResult.error || 'Query execution failed');
        return;
      }

      // Smart update: compare with previous panel data
      // Only panels with changed data will get new object references
      if (newResult.multi_panel && newResult.panels) {
        newResult.panels = newResult.panels.map(panel => {
          const prevDataStr = prevPanelsRef.current[panel.name];
          const newDataStr = JSON.stringify(panel.data);

          // If data is the same, preserve the previous data reference
          // This helps React skip re-rendering unchanged panels
          if (prevDataStr === newDataStr) {
            return { ...panel, _unchanged: true };
          }

          // Update the ref with new data
          prevPanelsRef.current[panel.name] = newDataStr;
          return panel;
        });
      }

      setResult(newResult);
    } catch (err) {
      console.error('Interaction failed:', err);
      setError(err.message || 'Failed to execute interaction');
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

  // Detect result format: multi-panel, canvas, or error
  const isMultiPanelResult = result?.multi_panel === true;
  const multiPanelData = isMultiPanelResult ? result.panels : null;
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
                {isMultiPanelResult
                  ? `${multiPanelData?.length || 0} panels`
                  : isCanvasResult
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
                isMultiPanel={isMultiPanelResult}
                multiPanelData={multiPanelData}
                onInteraction={handleInteraction}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CanvasView;
