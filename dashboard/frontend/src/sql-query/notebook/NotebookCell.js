import React, { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js/dist/plotly';
import useNotebookStore from '../stores/notebookStore';
import './NotebookCell.css';

// Create Plot component using factory pattern for better Plotly loading control
const Plot = createPlotlyComponent(Plotly);

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
  const {
    updateCell, removeCell, runCell, runFromCell, moveCell, notebook,
    cellAutoFixOverrides, setCellAutoFix, clearCellAutoFix, getEffectiveAutoFixConfig
  } = useNotebookStore();
  const [isExpanded, setIsExpanded] = useState(true);
  const [showResults, setShowResults] = useState(true);
  const [showAutoFixSettings, setShowAutoFixSettings] = useState(false);
  const [showDiff, setShowDiff] = useState(true); // Auto-show diff when fix happens
  const [diffDismissed, setDiffDismissed] = useState(false); // Track if user dismissed diff
  const editorRef = useRef(null);

  // Get effective auto-fix config for this cell
  const effectiveAutoFix = getEffectiveAutoFixConfig(phase.name);
  const hasAutoFixOverride = !!cellAutoFixOverrides[phase.name];

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
  const isJs = phase.tool === 'js_data';
  const isClojure = phase.tool === 'clojure_data';

  // Get display info for cell type
  const cellTypeInfo = {
    sql_data: { label: 'SQL', class: 'sql', language: 'sql', icon: 'mdi:database' },
    python_data: { label: 'Python', class: 'python', language: 'python', icon: 'mdi:language-python' },
    js_data: { label: 'JS', class: 'js', language: 'javascript', icon: 'mdi:language-javascript' },
    clojure_data: { label: 'Clojure', class: 'clojure', language: 'clojure', icon: 'simple-icons:clojure' },
    windlass_data: { label: 'LLM', class: 'windlass', language: 'yaml', icon: 'mdi:sail-boat' },
  };
  const typeInfo = cellTypeInfo[phase.tool] || cellTypeInfo.python_data;
  const isWindlass = phase.tool === 'windlass_data';

  const status = cellState?.status || 'pending';
  const result = cellState?.result;
  const error = cellState?.error;
  const duration = cellState?.duration;
  const autoFixed = cellState?.autoFixed;
  const fixedCode = cellState?.fixedCode;
  const fixAttempts = cellState?.fixAttempts;
  const originalError = cellState?.originalError;

  // Reset diffDismissed when a new auto-fix happens
  useEffect(() => {
    if (autoFixed && fixedCode) {
      setDiffDismissed(false);
      setShowDiff(true);
    }
  }, [autoFixed, fixedCode]);

  // Get current code/query
  const code = isSql
    ? (phase.inputs?.query || '')
    : (phase.inputs?.code || '');

  // Code key for updates (query for SQL, code for everything else)
  const codeKey = isSql ? 'query' : 'code';

  const connection = phase.inputs?.connection;

  const handleCodeChange = useCallback((value) => {
    updateCell(index, { inputs: { ...phase.inputs, [codeKey]: value } });
  }, [index, phase.inputs, codeKey, updateCell]);

  const handleNameChange = (e) => {
    updateCell(index, { name: e.target.value });
  };

  const handleConnectionChange = (e) => {
    updateCell(index, { inputs: { ...phase.inputs, connection: e.target.value || undefined } });
  };

  const handleRun = (forceRun = false) => {
    runCell(phase.name, forceRun);
  };

  // Check if result is cached
  const isCached = cellState?.cached === true;

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

  const handleConvertTo = (newTool) => {
    // Conversion templates for different language pairs
    const conversions = {
      sql_data: {
        code: `# Converted from SQL\n# Original query:\n# ${code.replace(/\n/g, '\n# ')}\n\nresult = {}`,
        defaultInputs: (c) => ({ code: c })
      },
      python_data: {
        fromSql: `# Converted from SQL\n# Original query:\n# ${code.replace(/\n/g, '\n# ')}\n\nresult = {}`,
        fromOther: `# Converted code\n# Original:\n# ${code.replace(/\n/g, '\n# ')}\n\nresult = {}`,
        defaultInputs: (c) => ({ code: c })
      },
      js_data: {
        fromSql: `// Converted from SQL\n// Original query:\n// ${code.replace(/\n/g, '\n// ')}\n\nresult = [];`,
        fromOther: `// Converted code\n// Original:\n// ${code.replace(/\n/g, '\n// ')}\n\nresult = [];`,
        defaultInputs: (c) => ({ code: c })
      },
      clojure_data: {
        fromSql: `; Converted from SQL\n; Original query:\n; ${code.replace(/\n/g, '\n; ')}\n\n[]`,
        fromOther: `; Converted code\n; Original:\n; ${code.replace(/\n/g, '\n; ')}\n\n[]`,
        defaultInputs: (c) => ({ code: c })
      }
    };

    let newCode;
    if (newTool === 'sql_data') {
      newCode = `-- Converted from ${typeInfo.label}\n-- Original code commented below\n${code.split('\n').map(l => '-- ' + l).join('\n')}`;
      updateCell(index, { tool: newTool, inputs: { query: newCode } });
    } else {
      const conv = conversions[newTool];
      newCode = isSql ? conv.fromSql : conv.fromOther;
      updateCell(index, { tool: newTool, inputs: conv.defaultInputs(newCode) });
    }
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

  // Apply the auto-fixed code to the cell
  const handleApplyFix = () => {
    if (!fixedCode) return;
    updateCell(index, { inputs: { ...phase.inputs, [codeKey]: fixedCode } });
    setDiffDismissed(true); // Hide diff after applying
  };

  // Dismiss the diff view without applying
  const handleDismissDiff = () => {
    setDiffDismissed(true);
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

  // Custom Monaco theme setup - GitHub Dark inspired, pastels on black
  const handleMonacoBeforeMount = (monaco) => {
    monaco.editor.defineTheme('notebook-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: 'ff9eb8', fontStyle: 'bold' },  // pastel pink
        { token: 'string', foreground: 'a5d6ff' },                      // pastel blue
        { token: 'number', foreground: 'd2a8ff' },                      // pastel purple
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
        { token: 'operator', foreground: 'ffc9e3' },                    // pastel rose
        { token: 'identifier', foreground: '79c0ff' },                  // pastel cyan
        { token: 'type', foreground: '7ee787' },                        // pastel green
        { token: 'function', foreground: 'd2a8ff' },                    // pastel purple
        { token: 'variable', foreground: 'e6edf3' },                    // light gray
      ],
      colors: {
        'editor.background': '#000000',                                 // pure black
        'editor.foreground': '#e6edf3',
        'editorLineNumber.foreground': '#6e7681',
        'editor.lineHighlightBackground': '#161b22',
        'editor.selectionBackground': '#264f78',
        'editorCursor.foreground': '#79c0ff',                           // pastel cyan
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorIndentGuide.background': '#21262d',
        'editorGutter.background': '#000000',
      }
    });
  };

  // Result preview component
  const ResultPreview = () => {
    if (!result && !error) return null;

    // Stdout/stderr display (for console.log/println debugging)
    const StdoutDisplay = () => {
      const stdout = result?.stdout;
      const stderr = result?.stderr;
      if (!stdout && !stderr) return null;

      return (
        <div className="cell-stdout-container">
          {stdout && (
            <div className="cell-stdout">
              <span className="cell-stdout-label">stdout:</span>
              <pre className="cell-stdout-content">{stdout}</pre>
            </div>
          )}
          {stderr && (
            <div className="cell-stderr">
              <span className="cell-stderr-label">stderr:</span>
              <pre className="cell-stderr-content">{stderr}</pre>
            </div>
          )}
        </div>
      );
    };

    if (error) {
      return (
        <>
          <StdoutDisplay />
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
        </>
      );
    }

    // === Multi-modal outputs ===

    // Image result (matplotlib, PIL, numpy array)
    // Supports both api_url (preferred) and base64 fallback
    if (result?.type === 'image' && (result?.api_url || result?.base64)) {
      const imgSrc = result.api_url || `data:image/${result.format || 'png'};base64,${result.base64}`;
      return (
        <>
          <StdoutDisplay />
          <div className="cell-result-image">
            <img
              src={imgSrc}
              alt={result.content || "Cell output"}
              style={{ maxWidth: '100%', height: 'auto' }}
            />
            {result.width && result.height && (
              <div className="cell-result-image-info">
                {result.width} × {result.height}
              </div>
            )}
          </div>
        </>
      );
    }

    // Plotly chart result
    if (result?.type === 'plotly' && result?.data) {
      // Deep clone data and layout to avoid "read only property" errors
      // Plotly mutates these objects internally during rendering
      const clonedData = JSON.parse(JSON.stringify(result.data));
      const clonedLayout = JSON.parse(JSON.stringify(result.layout || {}));

      // Apply dark theme to the cloned layout
      const darkLayout = {
        ...clonedLayout,
        paper_bgcolor: '#080c12',
        plot_bgcolor: '#080c12',
        font: { ...clonedLayout.font, color: '#cbd5e1' },
        xaxis: { ...clonedLayout.xaxis, gridcolor: '#1a2028', zerolinecolor: '#1a2028' },
        yaxis: { ...clonedLayout.yaxis, gridcolor: '#1a2028', zerolinecolor: '#1a2028' },
        legend: { ...clonedLayout.legend, bgcolor: 'rgba(0,0,0,0)' },
      };

      return (
        <>
          <StdoutDisplay />
          <div className="cell-result-plotly">
            <Plot
              data={clonedData}
              layout={darkLayout}
              config={{ responsive: true, displayModeBar: true }}
              style={{ width: '100%', height: '400px' }}
            />
          </div>
        </>
      );
    }

    // === Standard data outputs ===

    // DataFrame result - use AG-Grid
    if (result?.rows && result?.columns) {
      const rowCount = result.row_count || result.rows.length;

      return (
        <>
          <StdoutDisplay />
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
        </>
      );
    }

    // Dict/scalar result - use Monaco read-only
    if (result?.result !== undefined) {
      return (
        <>
          <StdoutDisplay />
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
        </>
      );
    }

    return <StdoutDisplay />;
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
          <span className={`cell-type-badge cell-type-${typeInfo.class}`}>
            <Icon icon={typeInfo.icon} width="14" />
            {typeInfo.label}
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
          {/* Cached indicator */}
          {isCached && status === 'success' && (
            <span className="cell-cached-badge" title="Result from cache - Shift+Click to force re-run">
              cached
            </span>
          )}
          {/* Auto-fixed indicator */}
          {cellState?.autoFixed && status === 'success' && (
            <span className="cell-autofixed-badge" title={`Auto-fixed after ${cellState.fixAttempts?.length || 1} attempt(s)`}>
              🔧 fixed
            </span>
          )}
          {/* Auto-fix enabled indicator */}
          {effectiveAutoFix?.enabled && (
            <span
              className={`cell-autofix-indicator ${hasAutoFixOverride ? 'cell-autofix-override' : ''}`}
              title={`Auto-fix: ${effectiveAutoFix.model}${hasAutoFixOverride ? ' (custom)' : ''}`}
              onClick={() => setShowAutoFixSettings(true)}
            >
              🔧
            </span>
          )}
          <button
            className="cell-action-btn"
            onClick={(e) => handleRun(e.shiftKey)}
            disabled={status === 'running'}
            title={isCached ? "Run cell (Shift+Click to force re-run)" : "Run cell"}
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
              <button onClick={() => handleRun(true)}>
                Force Run (bypass cache)
              </button>
              <button onClick={handleRunFromHere}>
                Run from here
              </button>
              {/* Hide conversion options for LLM cells - doesn't make sense */}
              {!isWindlass && (
                <>
                  <hr />
                  <div className="cell-menu-submenu">
                    <span className="cell-menu-label">Convert to:</span>
                    {phase.tool !== 'sql_data' && (
                      <button onClick={() => handleConvertTo('sql_data')}>SQL</button>
                    )}
                    {phase.tool !== 'python_data' && (
                      <button onClick={() => handleConvertTo('python_data')}>Python</button>
                    )}
                    {phase.tool !== 'js_data' && (
                      <button onClick={() => handleConvertTo('js_data')}>JavaScript</button>
                    )}
                    {phase.tool !== 'clojure_data' && (
                      <button onClick={() => handleConvertTo('clojure_data')}>Clojure</button>
                    )}
                  </div>
                  <button onClick={() => setShowAutoFixSettings(true)}>
                    Auto-fix settings...
                  </button>
                </>
              )}
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
              language={typeInfo.language}
              value={code}
              onChange={handleCodeChange}
              theme="notebook-dark"
              beforeMount={handleMonacoBeforeMount}
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

          {/* Auto-fix Diff View */}
          {autoFixed && fixedCode && !diffDismissed && showDiff && (
            <div className="cell-diff-container">
              <div className="cell-diff-header">
                <div className="cell-diff-title">
                  <span className="cell-diff-icon">🔧</span>
                  <span>Auto-fix applied</span>
                  {fixAttempts && fixAttempts.length > 0 && (
                    <span className="cell-diff-model">
                      via {fixAttempts[fixAttempts.length - 1]?.model || 'LLM'}
                    </span>
                  )}
                </div>
                <div className="cell-diff-actions">
                  <button
                    className="cell-diff-apply-btn"
                    onClick={handleApplyFix}
                    title="Update cell code with the fixed version"
                  >
                    Apply Fix
                  </button>
                  <button
                    className="cell-diff-dismiss-btn"
                    onClick={handleDismissDiff}
                    title="Keep original code, dismiss diff"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
              {originalError && (
                <div className="cell-diff-original-error">
                  <span className="cell-diff-error-label">Original error:</span>
                  <code className="cell-diff-error-message">{originalError}</code>
                </div>
              )}
              <div className="cell-diff-editor">
                <DiffEditor
                  height={Math.min(Math.max(
                    Math.max(
                      (code.match(/\n/g) || []).length,
                      (fixedCode.match(/\n/g) || []).length
                    ) * 20 + 40,
                    120
                  ), 300)}
                  language={typeInfo.language}
                  original={code}
                  modified={fixedCode}
                  theme="notebook-dark"
                  beforeMount={handleMonacoBeforeMount}
                  options={{
                    readOnly: true,
                    renderSideBySide: true,
                    minimap: { enabled: false },
                    fontSize: 12,
                    fontFamily: "'IBM Plex Mono', 'Monaco', monospace",
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    renderOverviewRuler: false,
                    diffWordWrap: 'on',
                  }}
                />
              </div>
              <div className="cell-diff-legend">
                <span className="cell-diff-legend-item cell-diff-legend-removed">― Removed</span>
                <span className="cell-diff-legend-item cell-diff-legend-added">+ Added</span>
              </div>
            </div>
          )}

          {/* Collapsed diff indicator */}
          {autoFixed && fixedCode && !diffDismissed && !showDiff && (
            <button
              className="cell-diff-show-btn"
              onClick={() => setShowDiff(true)}
            >
              Show auto-fix diff
            </button>
          )}
        </div>
      )}

      {/* Auto-fix Settings Modal */}
      {showAutoFixSettings && (
        <div className="cell-autofix-modal-backdrop" onClick={() => setShowAutoFixSettings(false)}>
          <div className="cell-autofix-modal" onClick={e => e.stopPropagation()}>
            <div className="cell-autofix-modal-header">
              <h3>Auto-fix Settings</h3>
              <button onClick={() => setShowAutoFixSettings(false)}>×</button>
            </div>
            <div className="cell-autofix-modal-body">
              <div className="cell-autofix-option">
                <label>
                  <input
                    type="checkbox"
                    checked={effectiveAutoFix?.enabled ?? true}
                    onChange={(e) => setCellAutoFix(phase.name, { enabled: e.target.checked })}
                  />
                  Enable auto-fix for this cell
                </label>
              </div>

              <div className="cell-autofix-option">
                <label>Model:</label>
                <select
                  value={effectiveAutoFix?.model || 'x-ai/grok-4.1-fast'}
                  onChange={(e) => setCellAutoFix(phase.name, { model: e.target.value })}
                >
                  <option value="x-ai/grok-4.1-fast">Grok 4.1 Fast (recommended)</option>
                  <option value="anthropic/claude-sonnet-4">Claude Sonnet 4</option>
                  <option value="openai/gpt-4o">GPT-4o</option>
                  <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
                  <option value="google/gemini-2.5-flash-lite">Gemini Flash Lite (cheap)</option>
                </select>
              </div>

              <div className="cell-autofix-option">
                <label>Max attempts:</label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={effectiveAutoFix?.max_attempts || 2}
                  onChange={(e) => setCellAutoFix(phase.name, { max_attempts: parseInt(e.target.value) || 2 })}
                />
              </div>

              <div className="cell-autofix-option">
                <label>Custom prompt (optional):</label>
                <textarea
                  placeholder="Leave empty for default prompt. Use {error} and {original_code} placeholders."
                  value={cellAutoFixOverrides[phase.name]?.prompt || ''}
                  onChange={(e) => setCellAutoFix(phase.name, { prompt: e.target.value || null })}
                  rows={4}
                />
              </div>

              {hasAutoFixOverride && (
                <button
                  className="cell-autofix-reset-btn"
                  onClick={() => {
                    clearCellAutoFix(phase.name);
                  }}
                >
                  Reset to global defaults
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NotebookCell;
