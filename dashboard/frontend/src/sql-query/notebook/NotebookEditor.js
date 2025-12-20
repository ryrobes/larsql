import React, { useEffect, useRef, useCallback, useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import useNotebookStore from '../stores/notebookStore';
import useSqlQueryStore from '../stores/sqlQueryStore';
import NotebookCell from './NotebookCell';
import InputsForm from './InputsForm';
import { SQL_TEMPLATES, PYTHON_TEMPLATES } from './cellTemplates';
import './NotebookEditor.css';

/**
 * NotebookEditor - Main container for the data cascade notebook view
 *
 * Displays a vertical list of cells (SQL/Python) that can be edited and executed.
 * Supports inputs form for parameterized notebooks.
 */
const NotebookEditor = () => {
  const {
    notebook,
    notebookPath,
    notebookDirty,
    cellStates,
    isRunningAll,
    sessionId,
    newNotebook,
    addCell,
    moveCell,
    runAllCells,
    restartSession,
    fetchNotebooks,
    notebooks,
    loadNotebook,
    saveNotebook,
    updateNotebook,
    undo,
    redo,
    undoStack,
    redoStack
  } = useNotebookStore();

  const {
    connections,
    fetchConnections,
    history,
    historyLoading,
    fetchHistory,
    tabs,
    activeTabId
  } = useSqlQueryStore();
  const scrollRef = useRef(null);
  const [showSqlTemplates, setShowSqlTemplates] = useState(false);
  const [showPythonTemplates, setShowPythonTemplates] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);

  // Drag and drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,  // Require 8px of movement before starting drag
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = (event) => {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const phases = notebook?.phases || [];
      const oldIndex = phases.findIndex(p => p.name === active.id);
      const newIndex = phases.findIndex(p => p.name === over.id);

      if (oldIndex !== -1 && newIndex !== -1) {
        moveCell(oldIndex, newIndex);
      }
    }
  };

  // Keyboard shortcuts for undo/redo
  const handleKeyDown = useCallback((e) => {
    // Don't capture if user is typing in an input/textarea/editor
    const isEditing = ['INPUT', 'TEXTAREA'].includes(e.target.tagName) ||
                      e.target.closest('.monaco-editor');
    if (isEditing) return;

    const isMac = navigator.platform.toUpperCase().includes('MAC');
    const cmdKey = isMac ? e.metaKey : e.ctrlKey;

    if (cmdKey && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      undo();
    } else if (cmdKey && e.key === 'z' && e.shiftKey) {
      e.preventDefault();
      redo();
    } else if (cmdKey && e.key === 'y') {
      // Windows-style redo
      e.preventDefault();
      redo();
    }
  }, [undo, redo]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Load connections on mount
  useEffect(() => {
    if (connections.length === 0) {
      fetchConnections();
    }
    fetchNotebooks();
  }, []);

  // Create new notebook if none exists
  useEffect(() => {
    if (!notebook) {
      newNotebook();
    }
  }, [notebook, newNotebook]);

  const handleRunAll = async () => {
    try {
      await runAllCells();
    } catch (err) {
      console.error('Run all failed:', err);
    }
  };

  const handleSave = async () => {
    if (!notebookPath) {
      // Prompt for path
      const path = window.prompt('Save notebook as:', `tackle/${notebook?.cascade_id || 'notebook'}.yaml`);
      if (path) {
        await saveNotebook(path);
      }
    } else {
      await saveNotebook();
    }
  };

  const handleSaveAsTool = async () => {
    // Validate notebook has a valid ID
    const toolName = notebook?.cascade_id?.replace(/[^a-z0-9_]/gi, '_') || 'notebook';
    const path = `tackle/${toolName}.yaml`;

    if (window.confirm(`Save as tool at ${path}?\n\nThis will make the notebook callable from any cascade using:\n  tool: "${toolName}"`)) {
      try {
        await saveNotebook(path);
        alert(`Saved as tool: ${toolName}\n\nYou can now use this in any cascade with:\n  tool: "${toolName}"`);
      } catch (err) {
        alert(`Failed to save: ${err.message}`);
      }
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all cell outputs and temp tables.')) {
      await restartSession();
    }
  };

  const handleLoad = async (path) => {
    try {
      await loadNotebook(path);
    } catch (err) {
      console.error('Load failed:', err);
    }
  };

  const handleTitleChange = (e) => {
    updateNotebook({ cascade_id: e.target.value });
  };

  const handleDescriptionChange = (e) => {
    updateNotebook({ description: e.target.value });
  };

  const handleAddCellFromTemplate = (type, template) => {
    addCell(type, null, template.code);
    setShowSqlTemplates(false);
    setShowPythonTemplates(false);
  };

  const handleOpenImportModal = () => {
    // Fetch history when opening modal
    fetchHistory({ limit: 50 });
    setShowImportModal(true);
  };

  const handleImportQuery = (sql, connection = null) => {
    // Add a SQL cell with the imported query
    const code = connection
      ? `-- Imported from ${connection}\n${sql}`
      : sql;
    addCell('sql_data', null, code);
    setShowImportModal(false);
  };

  // Get active tab query for quick import
  const activeTab = tabs.find(t => t.id === activeTabId);
  const hasActiveQuery = activeTab?.sql?.trim()?.length > 0;

  if (!notebook) {
    return (
      <div className="notebook-editor notebook-loading">
        <div className="notebook-spinner" />
        Loading notebook...
      </div>
    );
  }

  const hasInputs = notebook.inputs_schema && Object.keys(notebook.inputs_schema).length > 0;
  const cellCount = notebook.phases?.length || 0;
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;

  return (
    <div className="notebook-editor">
      {/* Notebook Header */}
      <div className="notebook-header">
        <div className="notebook-header-left">
          <input
            className="notebook-title-input"
            value={notebook.cascade_id || ''}
            onChange={handleTitleChange}
            placeholder="Notebook name"
          />
          {notebookDirty && <span className="notebook-dirty-indicator" title="Unsaved changes" />}
        </div>
        <div className="notebook-header-right">
          {/* Notebook selector */}
          <select
            className="notebook-selector"
            value={notebookPath || ''}
            onChange={(e) => e.target.value && handleLoad(e.target.value)}
          >
            <option value="">Load notebook...</option>
            {notebooks.map(nb => (
              <option key={nb.path} value={nb.path}>
                {nb.cascade_id} ({nb.path})
              </option>
            ))}
          </select>

          {/* Undo/Redo Buttons */}
          <button
            className="notebook-btn notebook-btn-icon"
            onClick={undo}
            disabled={undoStack.length === 0}
            title="Undo (Ctrl+Z)"
          >
            ↶
          </button>
          <button
            className="notebook-btn notebook-btn-icon"
            onClick={redo}
            disabled={redoStack.length === 0}
            title="Redo (Ctrl+Shift+Z)"
          >
            ↷
          </button>

          <button
            className="notebook-btn notebook-btn-import"
            onClick={handleOpenImportModal}
            title="Import SQL query as cell"
          >
            Import
          </button>

          <button
            className="notebook-btn notebook-btn-secondary"
            onClick={handleSave}
            disabled={!notebookDirty && notebookPath}
          >
            Save
          </button>

          <button
            className="notebook-btn notebook-btn-tool"
            onClick={handleSaveAsTool}
            title="Save to tackle/ directory as a callable tool"
          >
            Save as Tool
          </button>

          <button
            className="notebook-btn notebook-btn-restart"
            onClick={handleRestart}
            title="Clear all outputs and restart session"
          >
            Restart
          </button>

          <button
            className="notebook-btn notebook-btn-primary"
            onClick={handleRunAll}
            disabled={isRunningAll || cellCount === 0}
          >
            {isRunningAll ? (
              <>
                <span className="notebook-spinner-small" />
                Running...
              </>
            ) : (
              <>Run All</>
            )}
          </button>

          <button
            className="notebook-btn notebook-btn-icon notebook-btn-help"
            onClick={() => setShowHelpModal(true)}
            title="Help & Keyboard Shortcuts"
          >
            ?
          </button>
        </div>
      </div>

      {/* Description */}
      <div className="notebook-description-row">
        <input
          className="notebook-description-input"
          value={notebook.description || ''}
          onChange={handleDescriptionChange}
          placeholder="Add a description..."
        />
        <span className="notebook-stats">
          {completedCount}/{cellCount} cells
        </span>
      </div>

      {/* Inputs Form */}
      {hasInputs && (
        <InputsForm schema={notebook.inputs_schema} />
      )}

      {/* Cells Container */}
      <div className="notebook-cells" ref={scrollRef}>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={notebook.phases?.map(p => p.name) || []}
            strategy={verticalListSortingStrategy}
          >
            {notebook.phases?.map((phase, index) => (
              <NotebookCell
                key={phase.name}
                id={phase.name}
                phase={phase}
                index={index}
                cellState={cellStates[phase.name]}
                connections={connections}
              />
            ))}
          </SortableContext>
        </DndContext>

        {/* Add Cell Row with Templates */}
        <div className="notebook-add-cell-row">
          {/* SQL Cell with Templates */}
          <div className="notebook-add-cell-group">
            <button
              className="notebook-add-cell-btn"
              onClick={() => addCell('sql_data')}
            >
              + SQL
            </button>
            <button
              className="notebook-template-toggle"
              onClick={() => {
                setShowSqlTemplates(!showSqlTemplates);
                setShowPythonTemplates(false);
              }}
              title="SQL Templates"
            >
              ▾
            </button>
            {showSqlTemplates && (
              <div className="notebook-template-dropdown">
                {SQL_TEMPLATES.map(template => (
                  <button
                    key={template.id}
                    className="notebook-template-item"
                    onClick={() => handleAddCellFromTemplate('sql_data', template)}
                  >
                    <span className="template-name">{template.name}</span>
                    <span className="template-desc">{template.description}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Python Cell with Templates */}
          <div className="notebook-add-cell-group">
            <button
              className="notebook-add-cell-btn"
              onClick={() => addCell('python_data')}
            >
              + Python
            </button>
            <button
              className="notebook-template-toggle"
              onClick={() => {
                setShowPythonTemplates(!showPythonTemplates);
                setShowSqlTemplates(false);
              }}
              title="Python Templates"
            >
              ▾
            </button>
            {showPythonTemplates && (
              <div className="notebook-template-dropdown">
                {PYTHON_TEMPLATES.map(template => (
                  <button
                    key={template.id}
                    className="notebook-template-item"
                    onClick={() => handleAddCellFromTemplate('python_data', template)}
                  >
                    <span className="template-name">{template.name}</span>
                    <span className="template-desc">{template.description}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* JavaScript Cell */}
          <button
            className="notebook-add-cell-btn notebook-add-cell-js"
            onClick={() => addCell('js_data')}
            title="Add JavaScript/Node.js cell"
          >
            + JS
          </button>

          {/* Clojure Cell */}
          <button
            className="notebook-add-cell-btn notebook-add-cell-clojure"
            onClick={() => addCell('clojure_data')}
            title="Add Clojure (Babashka) cell"
          >
            + Clj
          </button>

          {/* LLM Cell */}
          <button
            className="notebook-add-cell-btn notebook-add-cell-windlass"
            onClick={() => addCell('windlass_data')}
            title="Add LLM phase cell (full Windlass power: soundings, reforge, wards)"
          >
            + LLM
          </button>
        </div>
      </div>

      {/* Help Modal */}
      {showHelpModal && (
        <div className="notebook-modal-overlay" onClick={() => setShowHelpModal(false)}>
          <div className="notebook-modal notebook-modal-help" onClick={(e) => e.stopPropagation()}>
            <div className="notebook-modal-header">
              <h3>Notebook Help</h3>
              <button
                className="notebook-modal-close"
                onClick={() => setShowHelpModal(false)}
              >
                ×
              </button>
            </div>
            <div className="notebook-modal-body">
              {/* Keyboard Shortcuts */}
              <div className="help-section">
                <h4>Keyboard Shortcuts</h4>
                <div className="help-shortcuts">
                  <div className="help-shortcut">
                    <span className="help-key">Ctrl/Cmd + Enter</span>
                    <span className="help-desc">Run current cell</span>
                  </div>
                  <div className="help-shortcut">
                    <span className="help-key">Shift + Enter</span>
                    <span className="help-desc">Run cell and advance</span>
                  </div>
                  <div className="help-shortcut">
                    <span className="help-key">Ctrl/Cmd + Z</span>
                    <span className="help-desc">Undo cell changes</span>
                  </div>
                  <div className="help-shortcut">
                    <span className="help-key">Ctrl/Cmd + Shift + Z</span>
                    <span className="help-desc">Redo cell changes</span>
                  </div>
                  <div className="help-shortcut">
                    <span className="help-key">Shift + Click Run</span>
                    <span className="help-desc">Force run (bypass cache)</span>
                  </div>
                </div>
              </div>

              {/* Cell References */}
              <div className="help-section">
                <h4>Referencing Prior Cells</h4>
                <div className="help-example">
                  <h5>In SQL cells:</h5>
                  <pre className="help-code">-- Access prior cell output as temp table{'\n'}SELECT * FROM _cell_name{'\n'}WHERE column {'>'} 100</pre>
                </div>
                <div className="help-example">
                  <h5>In Python cells:</h5>
                  <pre className="help-code"># Access prior cell as DataFrame{'\n'}df = data.cell_name{'\n'}{'\n'}# Set result (DataFrame or dict){'\n'}result = df.head(10)</pre>
                </div>
              </div>

              {/* Tips */}
              <div className="help-section">
                <h4>Tips</h4>
                <ul className="help-tips">
                  <li>Cells are executed sequentially - each cell can access outputs from prior cells</li>
                  <li>SQL cells materialize results as temp tables with <code>_</code> prefix</li>
                  <li>Results are cached - unchanged cells will skip re-execution</li>
                  <li>Use "Save as Tool" to make your notebook callable from other cascades</li>
                  <li>Drag cells by the handle (⠿) to reorder them</li>
                  <li>Use the template dropdown (▾) for common code patterns</li>
                </ul>
              </div>

              {/* Data Types */}
              <div className="help-section">
                <h4>Supported Result Types</h4>
                <div className="help-types">
                  <div className="help-type">
                    <span className="help-type-name">DataFrame</span>
                    <span className="help-type-desc">Tabular data with columns and rows (displayed as grid)</span>
                  </div>
                  <div className="help-type">
                    <span className="help-type-name">Dict</span>
                    <span className="help-type-desc">Key-value pairs (displayed as JSON)</span>
                  </div>
                  <div className="help-type">
                    <span className="help-type-name">Scalar</span>
                    <span className="help-type-desc">Single values like strings, numbers (displayed as JSON)</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="notebook-modal-overlay" onClick={() => setShowImportModal(false)}>
          <div className="notebook-modal" onClick={(e) => e.stopPropagation()}>
            <div className="notebook-modal-header">
              <h3>Import SQL Query</h3>
              <button
                className="notebook-modal-close"
                onClick={() => setShowImportModal(false)}
              >
                ×
              </button>
            </div>
            <div className="notebook-modal-body">
              {/* Quick import from active tab */}
              {hasActiveQuery && (
                <div className="import-section">
                  <h4>Current Query Tab</h4>
                  <button
                    className="import-item import-item-current"
                    onClick={() => handleImportQuery(activeTab.sql, activeTab.connection)}
                  >
                    <div className="import-item-header">
                      <span className="import-item-source">{activeTab.connection || 'Session DB'}</span>
                    </div>
                    <pre className="import-item-preview">{activeTab.sql.slice(0, 200)}{activeTab.sql.length > 200 ? '...' : ''}</pre>
                  </button>
                </div>
              )}

              {/* Import from history */}
              <div className="import-section">
                <h4>Query History</h4>
                {historyLoading ? (
                  <div className="import-loading">Loading history...</div>
                ) : history.length === 0 ? (
                  <div className="import-empty">No queries in history</div>
                ) : (
                  <div className="import-list">
                    {history.slice(0, 20).map((entry, idx) => (
                      <button
                        key={entry.id || idx}
                        className="import-item"
                        onClick={() => handleImportQuery(entry.sql, entry.connection)}
                      >
                        <div className="import-item-header">
                          <span className="import-item-source">{entry.connection || 'Session DB'}</span>
                          {entry.row_count !== null && (
                            <span className="import-item-rows">{entry.row_count} rows</span>
                          )}
                          {entry.duration_ms && (
                            <span className="import-item-duration">{entry.duration_ms}ms</span>
                          )}
                        </div>
                        <pre className="import-item-preview">{entry.sql.slice(0, 150)}{entry.sql.length > 150 ? '...' : ''}</pre>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NotebookEditor;
