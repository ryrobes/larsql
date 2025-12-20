import React, { useEffect, useRef } from 'react';
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
    updateNotebook
  } = useNotebookStore();

  const { connections, fetchConnections } = useSqlQueryStore();
  const scrollRef = useRef(null);

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
