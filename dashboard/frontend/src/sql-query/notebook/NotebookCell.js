import React, { useState, useCallback, useRef, useMemo } from 'react';
import Editor from '@monaco-editor/react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import useNotebookStore from '../stores/notebookStore';
import './NotebookCell.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Create dark theme for AG Grid in notebook cells
const cellGridTheme = themeQuartz.withParams({
  backgroundColor: '#080c12',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0b1219',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#0a0e14',
  borderColor: '#1a2028',
  rowBorder: true,
  wrapperBorder: false,
  headerFontSize: 11,
  headerFontWeight: 600,
  fontFamily: "'IBM Plex Mono', 'Monaco', monospace",
  fontSize: 12,
  accentColor: '#2dd4bf',
  chromeBackgroundColor: '#080c12',
});

/**
 * NotebookCell - Individual cell in a data cascade notebook
 *
 * Supports SQL (sql_data) and Python (python_data) cell types.
 * Shows Monaco editor for code, inline results preview, and execution controls.
 */
const NotebookCell = ({ id, phase, index, cellState, connections }) => {
  const { updateCell, removeCell, runCell, runFromCell, moveCell, notebook } = useNotebookStore();
  const [isExpanded, setIsExpanded] = useState(true);
  const [showResults, setShowResults] = useState(true);
  const editorRef = useRef(null);

  // Sortable setup
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 1000 : 'auto',
  };

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

  const handleRunFromHere = () => {
    runFromCell(phase.name);
  };

  const handleToggleType = () => {
    const newTool = isSql ? 'python_data' : 'sql_data';
    const newInputs = isSql
      ? { code: `# Converted from SQL\n# Original query:\n# ${code.replace(/\n/g, '\n# ')}\n\nresult = {}` }
      : { query: `-- Converted from Python\n${code}` };
    updateCell(index, { tool: newTool, inputs: newInputs });
  };

  const handleExportCSV = () => {
    if (!result?.rows || !result?.columns) return;

    // Build CSV content
    const headers = result.columns.join(',');
    const rows = result.rows.map(row =>
      result.columns.map(col => {
        const val = row[col];
        if (val === null || val === undefined) return '';
        if (typeof val === 'string' && (val.includes(',') || val.includes('"') || val.includes('\n'))) {
          return `"${val.replace(/"/g, '""')}"`;
        }
        return String(val);
      }).join(',')
    );
    const csv = [headers, ...rows].join('\n');

    // Download
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${phase.name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyResults = () => {
    if (!result?.rows) return;
    navigator.clipboard.writeText(JSON.stringify(result.rows, null, 2));
  };

  // Handle editor mount - set up keyboard shortcuts and autocomplete
  const handleEditorMount = (editor, monaco) => {
    editorRef.current = editor;

    // Add Ctrl+Enter / Cmd+Enter to run cell
    editor.addAction({
      id: 'run-cell',
      label: 'Run Cell',
      keybindings: [
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter
      ],
      run: () => {
        runCell(phase.name);
      }
    });

    // Add Shift+Enter to run cell and move to next
    editor.addAction({
      id: 'run-cell-and-advance',
      label: 'Run Cell and Advance',
      keybindings: [
        monaco.KeyMod.Shift | monaco.KeyCode.Enter
      ],
      run: () => {
        runCell(phase.name);
        // Focus handled by parent if needed
      }
    });

    // Get prior phase names for autocomplete
    const priorPhases = notebook?.phases?.slice(0, index) || [];

    // Register completion provider for Python (data.phase_name)
    if (isPython) {
      const disposable = monaco.languages.registerCompletionItemProvider('python', {
        triggerCharacters: ['.'],
        provideCompletionItems: (model, position) => {
          const textUntilPosition = model.getValueInRange({
            startLineNumber: position.lineNumber,
            startColumn: 1,
            endLineNumber: position.lineNumber,
            endColumn: position.column
          });

          // Check if we're typing after "data."
          if (textUntilPosition.endsWith('data.')) {
            const suggestions = priorPhases.map(p => ({
              label: p.name,
              kind: monaco.languages.CompletionItemKind.Variable,
              insertText: p.name,
              detail: `DataFrame from ${p.tool} phase`,
              documentation: `Access the output of the "${p.name}" phase as a DataFrame`
            }));

            return { suggestions };
          }

          return { suggestions: [] };
        }
      });

      // Clean up on unmount
      return () => disposable.dispose();
    }

    // Register completion provider for SQL (_phase_name tables)
    if (isSql) {
      const disposable = monaco.languages.registerCompletionItemProvider('sql', {
        triggerCharacters: ['_'],
        provideCompletionItems: (model, position) => {
          const textUntilPosition = model.getValueInRange({
            startLineNumber: position.lineNumber,
            startColumn: 1,
            endLineNumber: position.lineNumber,
            endColumn: position.column
          });

          // Check if we just typed "_" (potential table reference)
          const match = textUntilPosition.match(/(?:FROM|JOIN|,)\s*_$/i);
          if (match || textUntilPosition.endsWith(' _') || textUntilPosition.endsWith('\t_') || textUntilPosition.endsWith('\n_')) {
            const suggestions = priorPhases.map(p => ({
              label: `_${p.name}`,
              kind: monaco.languages.CompletionItemKind.Struct,
              insertText: p.name,  // Just the name since _ is already typed
              detail: `Temp table from ${p.tool} phase`,
              documentation: `Query the materialized output of the "${p.name}" phase`
            }));

            return { suggestions };
          }

          return { suggestions: [] };
        }
      });

      // Clean up on unmount
      return () => disposable.dispose();
    }
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

  // AG-Grid column definitions for DataFrame results
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
      cellRenderer: (params) => {
        const value = params.value;
        if (value === null || value === undefined) {
          return <span className="cell-null">NULL</span>;
        }
        if (typeof value === 'object') {
          return <span className="cell-json-inline">{JSON.stringify(value)}</span>;
        }
        return value;
      }
    }));
  }, [result?.columns]);

  // AG-Grid row data
  const gridRowData = useMemo(() => {
    if (!result?.rows) return [];
    return result.rows;
  }, [result?.rows]);

  // Default column definition for AG-Grid
  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    minWidth: 60,
  }), []);

  // Calculate grid height based on row count
  const gridHeight = useMemo(() => {
    if (!result?.rows) return 250;
    const rowCount = result.rows.length;
    // 32px per row + 48px header, min 200px, max 500px
    return Math.min(Math.max(rowCount * 32 + 48, 200), 500);
  }, [result?.rows]);

  // Format JSON for Monaco display
  const jsonContent = useMemo(() => {
    if (result?.result !== undefined) {
      return JSON.stringify(result.result, null, 2);
    }
    return '';
  }, [result?.result]);

  // Calculate Monaco height for JSON based on content
  const jsonEditorHeight = useMemo(() => {
    if (!jsonContent) return 150;
    const lineCount = (jsonContent.match(/\n/g) || []).length + 1;
    // 20px per line, min 150px, max 400px
    return Math.min(Math.max(lineCount * 20 + 24, 150), 400);
  }, [jsonContent]);

  // Custom Monaco theme setup (pure black background)
  const handleMonacoBeforeMount = (monaco) => {
    monaco.editor.defineTheme('notebook-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [],
      colors: {
        'editor.background': '#080c12',
        'editor.foreground': '#cbd5e1',
        'editorLineNumber.foreground': '#475569',
        'editor.lineHighlightBackground': '#0f1821',
        'editor.selectionBackground': '#2dd4bf33',
        'editorCursor.foreground': '#2dd4bf',
      }
    });
  };

  // Result preview component
  const ResultPreview = () => {
    if (!result && !error) return null;

    if (error) {
      return (
        <div className="cell-result-error">
          <span className="cell-result-error-label">Error:</span>
          <Editor
            height={Math.min(Math.max((error.match(/\n/g) || []).length * 20 + 40, 100), 250)}
            language="text"
            value={error}
            theme="notebook-dark"
            beforeMount={handleMonacoBeforeMount}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              lineNumbers: 'off',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              fontSize: 12,
              fontFamily: "'IBM Plex Mono', 'Monaco', monospace",
              padding: { top: 12, bottom: 12 },
              renderLineHighlight: 'none',
              scrollbar: { vertical: 'auto', horizontal: 'auto' },
            }}
          />
        </div>
      );
    }

    // DataFrame result - use AG-Grid
    if (result?.rows && result?.columns) {
      const rowCount = result.row_count || result.rows.length;

      return (
        <div className="cell-result-grid-container" style={{ height: gridHeight }}>
          <AgGridReact
            rowData={gridRowData}
            columnDefs={gridColumnDefs}
            defaultColDef={defaultColDef}
            theme={cellGridTheme}
            animateRows={false}
            enableCellTextSelection={true}
            ensureDomOrder={true}
            suppressRowClickSelection={true}
            headerHeight={36}
            rowHeight={28}
          />
          {rowCount > result.rows.length && (
            <div className="cell-result-truncated">
              Showing {result.rows.length} of {rowCount} rows
            </div>
          )}
        </div>
      );
    }

    // Dict/scalar result - use Monaco read-only
    if (result?.result !== undefined) {
      return (
        <div className="cell-result-json-container">
          <Editor
            height={jsonEditorHeight}
            language="json"
            value={jsonContent}
            theme="notebook-dark"
            beforeMount={handleMonacoBeforeMount}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              lineNumbers: 'off',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              fontSize: 12,
              fontFamily: "'IBM Plex Mono', 'Monaco', monospace",
              padding: { top: 12, bottom: 12 },
              renderLineHighlight: 'none',
              folding: true,
              scrollbar: { vertical: 'auto', horizontal: 'auto' },
            }}
          />
        </div>
      );
    }

    return null;
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`notebook-cell notebook-cell-${status}${isDragging ? ' notebook-cell-dragging' : ''}`}
      data-phase-name={phase.name}
    >
      {/* Cell Header */}
      <div className="cell-header">
        <div className="cell-header-left">
          {/* Drag Handle */}
          <button
            className="cell-drag-handle"
            {...attributes}
            {...listeners}
            title="Drag to reorder"
          >
            ⠿
          </button>
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
              <button onClick={handleRunFromHere}>
                Run from here
              </button>
              <button onClick={handleToggleType}>
                Convert to {isSql ? 'Python' : 'SQL'}
              </button>
              <hr />
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
              onMount={handleEditorMount}
            />
          </div>

          {/* Results Preview */}
          {(result || error) && showResults && (
            <div className="cell-results">
              <div className="cell-results-header">
                <span>Output</span>
                <div className="cell-results-actions">
                  {result?.rows && (
                    <>
                      <button
                        className="cell-results-btn"
                        onClick={handleCopyResults}
                        title="Copy as JSON"
                      >
                        Copy
                      </button>
                      <button
                        className="cell-results-btn"
                        onClick={handleExportCSV}
                        title="Download as CSV"
                      >
                        CSV
                      </button>
                    </>
                  )}
                  <button
                    className="cell-results-toggle"
                    onClick={() => setShowResults(false)}
                  >
                    Hide
                  </button>
                </div>
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

export default NotebookCell;
