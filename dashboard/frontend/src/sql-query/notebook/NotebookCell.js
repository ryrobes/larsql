import React, { useState, useCallback, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import useNotebookStore from '../stores/notebookStore';
import './NotebookCell.css';

/**
 * NotebookCell - Individual cell in a data cascade notebook
 *
 * Supports SQL (sql_data) and Python (python_data) cell types.
 * Shows Monaco editor for code, inline results preview, and execution controls.
 */
const NotebookCell = ({ phase, index, cellState, connections }) => {
  const { updateCell, removeCell, runCell, moveCell } = useNotebookStore();
  const [isExpanded, setIsExpanded] = useState(true);
  const [showResults, setShowResults] = useState(true);
  const editorRef = useRef(null);

  const isSql = phase.tool === 'sql_data';
  const isPython = phase.tool === 'python_data';

  const status = cellState?.status || 'pending';
  const result = cellState?.result;
  const error = cellState?.error;
  const duration = cellState?.duration;

  // Get current code/query
  const code = isSql
    ? (phase.inputs?.query || '')
    : (phase.inputs?.code || '');

  const connection = phase.inputs?.connection;

  const handleCodeChange = useCallback((value) => {
    if (isSql) {
      updateCell(index, { inputs: { ...phase.inputs, query: value } });
    } else {
      updateCell(index, { inputs: { ...phase.inputs, code: value } });
    }
  }, [index, phase.inputs, isSql, updateCell]);

  const handleNameChange = (e) => {
    updateCell(index, { name: e.target.value });
  };

  const handleConnectionChange = (e) => {
    updateCell(index, { inputs: { ...phase.inputs, connection: e.target.value || undefined } });
  };

  const handleRun = () => {
    runCell(phase.name);
  };

  const handleDelete = () => {
    if (window.confirm(`Delete cell "${phase.name}"?`)) {
      removeCell(index);
    }
  };

  const handleMoveUp = () => {
    if (index > 0) {
      moveCell(index, index - 1);
    }
  };

  const handleMoveDown = () => {
    moveCell(index, index + 1);
  };

  const handleToggleType = () => {
    const newTool = isSql ? 'python_data' : 'sql_data';
    const newInputs = isSql
      ? { code: `# Converted from SQL\n# Original query:\n# ${code.replace(/\n/g, '\n# ')}\n\nresult = {}` }
      : { query: `-- Converted from Python\n${code}` };
    updateCell(index, { tool: newTool, inputs: newInputs });
  };

  // Monaco editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 13,
    fontFamily: "'IBM Plex Mono', 'Monaco', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    wordWrap: 'on',
    automaticLayout: true,
    scrollBeyondLastLine: false,
    padding: { top: 8, bottom: 8 },
    lineDecorationsWidth: 8
  };

  // Calculate editor height based on content
  const lineCount = (code.match(/\n/g) || []).length + 1;
  const editorHeight = Math.min(Math.max(lineCount * 20 + 24, 80), 300);

  // Status icon
  const StatusIcon = () => {
    switch (status) {
      case 'running':
        return <span className="cell-status-icon cell-status-running" />;
      case 'success':
        return <span className="cell-status-icon cell-status-success">✓</span>;
      case 'error':
        return <span className="cell-status-icon cell-status-error">✗</span>;
      case 'stale':
        return <span className="cell-status-icon cell-status-stale">○</span>;
      default:
        return <span className="cell-status-icon cell-status-pending">○</span>;
    }
  };

  // Result preview
  const ResultPreview = () => {
    if (!result && !error) return null;

    if (error) {
      return (
        <div className="cell-result-error">
          <span className="cell-result-error-label">Error:</span>
          <pre className="cell-result-error-text">{error}</pre>
        </div>
      );
    }

    // DataFrame result
    if (result?.rows && result?.columns) {
      const rows = result.rows.slice(0, 5); // Preview first 5 rows
      const rowCount = result.row_count || result.rows.length;

      return (
        <div className="cell-result-table-container">
          <table className="cell-result-table">
            <thead>
              <tr>
                {result.columns.map(col => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  {result.columns.map(col => (
                    <td key={col}>{formatValue(row[col])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rowCount > 5 && (
            <div className="cell-result-more">
              ...and {rowCount - 5} more rows
            </div>
          )}
        </div>
      );
    }

    // Dict/scalar result
    if (result?.result !== undefined) {
      return (
        <div className="cell-result-json">
          <pre>{JSON.stringify(result.result, null, 2)}</pre>
        </div>
      );
    }

    return null;
  };

  return (
    <div className={`notebook-cell notebook-cell-${status}`}>
      {/* Cell Header */}
      <div className="cell-header">
        <div className="cell-header-left">
          <StatusIcon />
          <span className={`cell-type-badge cell-type-${isSql ? 'sql' : 'python'}`}>
            {isSql ? 'SQL' : 'Python'}
          </span>
          <input
            className="cell-name-input"
            value={phase.name}
            onChange={handleNameChange}
            placeholder="cell_name"
          />
          {isSql && (
            <select
              className="cell-connection-select"
              value={connection || ''}
              onChange={handleConnectionChange}
            >
              <option value="">Session DB</option>
              {connections.map(conn => (
                <option key={conn.name} value={conn.name}>{conn.name}</option>
              ))}
            </select>
          )}
        </div>
        <div className="cell-header-right">
          {duration && (
            <span className="cell-duration">{duration}ms</span>
          )}
          {result?.row_count !== undefined && (
            <span className="cell-row-count">{result.row_count} rows</span>
          )}
          <button
            className="cell-action-btn"
            onClick={handleRun}
            disabled={status === 'running'}
            title="Run cell"
          >
            {status === 'running' ? (
              <span className="cell-spinner" />
            ) : (
              '▶'
            )}
          </button>
          <button
            className="cell-action-btn"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? '▼' : '▶'}
          </button>
          <div className="cell-menu">
            <button className="cell-menu-btn" title="More actions">⋮</button>
            <div className="cell-menu-dropdown">
              <button onClick={handleToggleType}>
                Convert to {isSql ? 'Python' : 'SQL'}
              </button>
              <button onClick={handleMoveUp} disabled={index === 0}>
                Move up
              </button>
              <button onClick={handleMoveDown}>
                Move down
              </button>
              <hr />
              <button onClick={handleDelete} className="cell-menu-danger">
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cell Body */}
      {isExpanded && (
        <div className="cell-body">
          <div className="cell-editor" style={{ height: editorHeight }}>
            <Editor
              height="100%"
              language={isSql ? 'sql' : 'python'}
              value={code}
              onChange={handleCodeChange}
              theme="vs-dark"
              options={editorOptions}
              onMount={(editor) => { editorRef.current = editor; }}
            />
          </div>

          {/* Results Preview */}
          {(result || error) && showResults && (
            <div className="cell-results">
              <div className="cell-results-header">
                <span>Output</span>
                <button
                  className="cell-results-toggle"
                  onClick={() => setShowResults(false)}
                >
                  Hide
                </button>
              </div>
              <ResultPreview />
            </div>
          )}

          {/* Show results button */}
          {(result || error) && !showResults && (
            <button
              className="cell-show-results-btn"
              onClick={() => setShowResults(true)}
            >
              Show output ({result?.row_count || 'error'})
            </button>
          )}
        </div>
      )}
    </div>
  );
};

// Format cell values for display
function formatValue(value) {
  if (value === null || value === undefined) {
    return <span className="cell-null">NULL</span>;
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    // Format large numbers
    if (Math.abs(value) >= 1000000) {
      return value.toLocaleString();
    }
    if (!Number.isInteger(value)) {
      return value.toFixed(2);
    }
  }
  return String(value);
}

export default NotebookCell;
