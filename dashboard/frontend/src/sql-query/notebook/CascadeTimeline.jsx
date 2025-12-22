import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useCascadeStore from '../stores/cascadeStore';
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
    cascade,
    cascadePath,
    cascadeDirty,
    cellStates,
    isRunningAll,
    sessionId,
    cascades,
    fetchCascades,
    loadCascade,
    newCascade,
    addCell,
    runAllCells,
    restartSession,
    updateCascade,
    saveCascade,
    selectedPhaseIndex,
    setSelectedPhaseIndex,
  } = useCascadeStore();

  const timelineRef = useRef(null);

  const handleTitleChange = (e) => {
    updateCascade({ cascade_id: e.target.value });
  };

  const handleDescriptionChange = (e) => {
    updateCascade({ description: e.target.value });
  };

  const handleRunAll = async () => {
    await runAllCells();
  };

  const handleSave = async () => {
    if (!cascadePath) {
      const path = window.prompt('Save cascade as:', `cascades/${cascade?.cascade_id || 'cascade'}.yaml`);
      if (path) {
        await saveCascade(path);
      }
    } else {
      await saveCascade();
    }
  };

  const handleSaveAsTool = async () => {
    const toolName = cascade?.cascade_id?.replace(/[^a-z0-9_]/gi, '_') || 'cascade';
    const path = `tackle/${toolName}.yaml`;

    if (window.confirm(`Save as tool: ${toolName}?\n\nThis will make it callable from other cascades.`)) {
      await saveCascade(path);
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all outputs.')) {
      await restartSession();
    }
  };

  const handleLoad = async (path) => {
    try {
      await loadCascade(path);
    } catch (err) {
      console.error('Load failed:', err);
    }
  };

  // Fetch cascades on mount
  useEffect(() => {
    fetchCascades();
  }, [fetchCascades]);

  // Create new cascade if none exists (same pattern as NotebookEditor)
  useEffect(() => {
    if (!cascade) {
      newCascade();
    }
  }, [cascade, newCascade]);

  const handleSelectPhase = (index) => {
    setSelectedPhaseIndex(index);
  };

  if (!cascade) {
    return (
      <div className="cascade-timeline cascade-loading">
        <div className="cascade-spinner" />
        Loading cascade...
      </div>
    );
  }

  const phases = cascade.phases || [];
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
            value={cascade.cascade_id || ''}
            onChange={handleTitleChange}
            placeholder="cascade_name"
          />
          {cascadeDirty && <span className="cascade-dirty-dot" title="Unsaved changes" />}
          <input
            className="cascade-description-input"
            value={cascade.description || ''}
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
            value={cascadePath || ''}
            onChange={(e) => e.target.value && handleLoad(e.target.value)}
          >
            <option value="">Load cascade...</option>
            {cascades.map(nb => (
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
            disabled={!cascadeDirty && cascadePath}
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
