import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useNotebookStore from '../stores/notebookStore';
import PhaseCard from './PhaseCard';
import PhaseDetailPanel from './PhaseDetailPanel';
import './CascadeTimeline.css';

/**
 * DropZone - Visual drop target between phases
 */
const DropZone = ({ position }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: `drop-zone-${position}`,
    data: { position },
  });

  return (
    <div
      ref={setNodeRef}
      className={`cascade-drop-zone ${isOver ? 'cascade-drop-zone-active' : ''}`}
    >
      <div className="cascade-drop-zone-indicator">
        {isOver && <Icon icon="mdi:plus-circle" width="20" />}
      </div>
    </div>
  );
};

/**
 * CascadeTimeline - Horizontal cascade builder (DAW-style)
 *
 * Layout:
 * - Top bar: Cascade controls + metadata
 * - Middle strip: Horizontal scrolling phase cards (left→right) with drop zones
 * - Bottom panel: Selected phase details (config, code, outputs)
 */
const CascadeTimeline = () => {
  const {
    notebook,
    notebookPath,
    notebookDirty,
    cellStates,
    isRunningAll,
    sessionId,
    notebooks,
    fetchNotebooks,
    loadNotebook,
    newNotebook,
    addCell,
    runAllCells,
    restartSession,
    updateNotebook,
    saveNotebook,
    selectedPhaseIndex,
    setSelectedPhaseIndex,
  } = useNotebookStore();

  const timelineRef = useRef(null);

  const handleTitleChange = (e) => {
    updateNotebook({ cascade_id: e.target.value });
  };

  const handleDescriptionChange = (e) => {
    updateNotebook({ description: e.target.value });
  };

  const handleRunAll = async () => {
    await runAllCells();
  };

  const handleSave = async () => {
    if (!notebookPath) {
      const path = window.prompt('Save cascade as:', `cascades/${notebook?.cascade_id || 'cascade'}.yaml`);
      if (path) {
        await saveNotebook(path);
      }
    } else {
      await saveNotebook();
    }
  };

  const handleSaveAsTool = async () => {
    const toolName = notebook?.cascade_id?.replace(/[^a-z0-9_]/gi, '_') || 'cascade';
    const path = `tackle/${toolName}.yaml`;

    if (window.confirm(`Save as tool: ${toolName}?\n\nThis will make it callable from other cascades.`)) {
      await saveNotebook(path);
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all outputs.')) {
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

  // Fetch notebooks on mount
  useEffect(() => {
    fetchNotebooks();
  }, [fetchNotebooks]);

  // Create new notebook if none exists (same pattern as NotebookEditor)
  useEffect(() => {
    if (!notebook) {
      newNotebook();
    }
  }, [notebook, newNotebook]);

  const handleSelectPhase = (index) => {
    setSelectedPhaseIndex(index);
  };

  if (!notebook) {
    return (
      <div className="cascade-timeline cascade-loading">
        <div className="cascade-spinner" />
        Loading cascade...
      </div>
    );
  }

  const phases = notebook.phases || [];
  const selectedPhase = selectedPhaseIndex !== null ? phases[selectedPhaseIndex] : null;
  const cellCount = phases.length;
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;

  return (
    <div className="cascade-timeline">
        {/* Top Control Bar */}
        <div className="cascade-control-bar">
        <div className="cascade-control-left">
          <input
            className="cascade-title-input"
            value={notebook.cascade_id || ''}
            onChange={handleTitleChange}
            placeholder="cascade_name"
          />
          {notebookDirty && <span className="cascade-dirty-dot" title="Unsaved changes" />}
          <input
            className="cascade-description-input"
            value={notebook.description || ''}
            onChange={handleDescriptionChange}
            placeholder="Description..."
          />
        </div>

        <div className="cascade-control-right">
          <span className="cascade-stats">
            {completedCount}/{cellCount} phases
          </span>

          {/* Cascade selector dropdown */}
          <select
            className="cascade-selector"
            value={notebookPath || ''}
            onChange={(e) => e.target.value && handleLoad(e.target.value)}
          >
            <option value="">Load cascade...</option>
            {notebooks.map(nb => (
              <option key={nb.path} value={nb.path}>
                {nb.cascade_id} ({nb.path})
              </option>
            ))}
          </select>

          <button
            className="cascade-btn cascade-btn-secondary"
            onClick={handleRestart}
            title="Restart session"
          >
            <Icon icon="mdi:restart" width="16" />
          </button>

          <button
            className="cascade-btn cascade-btn-secondary"
            onClick={handleSave}
            disabled={!notebookDirty && notebookPath}
          >
            <Icon icon="mdi:content-save" width="16" />
            Save
          </button>

          <button
            className="cascade-btn cascade-btn-tool"
            onClick={handleSaveAsTool}
            title="Save to tackle/ as reusable tool"
          >
            <Icon icon="mdi:package" width="16" />
            As Tool
          </button>

        </div>
      </div>

      {/* Horizontal Phase Timeline */}
      <div className="cascade-timeline-strip" ref={timelineRef}>
        <div className="cascade-timeline-track">
          {/* Continuous track line (metro map style) */}
          {phases.length > 0 && <div className="cascade-track-line" />}

          {/* Drop zone at start */}
          <DropZone position={0} />

          {phases.map((phase, index) => (
            <React.Fragment key={phase.name}>
              <PhaseCard
                phase={phase}
                index={index}
                cellState={cellStates[phase.name]}
                isSelected={selectedPhaseIndex === index}
                onSelect={() => handleSelectPhase(index)}
              />
              {/* Drop zone after this phase */}
              <DropZone position={index + 1} />
            </React.Fragment>
          ))}

          {/* Empty state hint */}
          {phases.length === 0 && (
            <div className="cascade-empty-hint">
              <Icon icon="mdi:hand-back-left" width="24" />
              <span>Drag phase types from the sidebar to start</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Detail Panel */}
      {selectedPhase ? (
        <PhaseDetailPanel
          phase={selectedPhase}
          index={selectedPhaseIndex}
          cellState={cellStates[selectedPhase.name]}
          onClose={() => setSelectedPhaseIndex(null)}
        />
      ) : (
        <div className="cascade-empty-detail">
          <Icon icon="mdi:cursor-pointer" width="32" />
          <p>Select a phase above to view details</p>
        </div>
      )}

    </div>
  );
};

export default CascadeTimeline;
