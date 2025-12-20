import React, { useEffect, useRef } from 'react';
import useNotebookStore from '../stores/notebookStore';
import useSqlQueryStore from '../stores/sqlQueryStore';
import NotebookCell from './NotebookCell';
import InputsForm from './InputsForm';
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
    newNotebook,
    addCell,
    runAllCells,
    fetchNotebooks,
    notebooks,
    loadNotebook,
    saveNotebook,
    updateNotebook
  } = useNotebookStore();

  const { connections, fetchConnections } = useSqlQueryStore();
  const scrollRef = useRef(null);

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

          <button
            className="notebook-btn notebook-btn-secondary"
            onClick={handleSave}
            disabled={!notebookDirty && notebookPath}
          >
            Save
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
        {notebook.phases?.map((phase, index) => (
          <NotebookCell
            key={phase.name}
            phase={phase}
            index={index}
            cellState={cellStates[phase.name]}
            connections={connections}
          />
        ))}

        {/* Add Cell Button */}
        <div className="notebook-add-cell-row">
          <button
            className="notebook-add-cell-btn"
            onClick={() => addCell('sql_data')}
          >
            + SQL
          </button>
          <button
            className="notebook-add-cell-btn"
            onClick={() => addCell('python_data')}
          >
            + Python
          </button>
        </div>
      </div>
    </div>
  );
};

export default NotebookEditor;
