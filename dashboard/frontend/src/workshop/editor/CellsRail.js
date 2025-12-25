import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import PhaseBlock from './blocks/CellBlock';
import './CellsRail.css';

/**
 * PhasesRail - Sortable vertical list of phases in the editor
 *
 * Features:
 * - Drag to reorder phases
 * - Drop zone for new phases from palette
 * - Add new phase button
 * - Visual connection lines between phases
 *
 * Note: Ghost visualization (preview of execution) is shown in ExecutionNotebook,
 * not here. This is purely the editor view for configuring phases.
 */
function PhasesRail() {
  const {
    cascade,
    selectedPhaseIndex,
    setSelectedPhase,
    addPhase,
  } = useWorkshopStore();

  const phases = cascade.cells || [];

  // Droppable zone for new phases from palette
  const { setNodeRef: setDropZoneRef, isOver } = useDroppable({
    id: 'phases-drop-zone',
    data: {
      accepts: ['phase'],
    },
  });

  const handleAddPhase = () => {
    addPhase();
  };

  const phaseIds = phases.map((p) => `phase-${p.name}`);

  return (
    <div className="phases-rail" ref={setDropZoneRef}>
      <SortableContext items={phaseIds} strategy={verticalListSortingStrategy}>
        <div className={`phases-list ${isOver ? 'drop-active' : ''}`}>
          {phases.map((phase, index) => (
            <div key={`phase-${phase.name}`} className="phase-wrapper">
              {/* Connection line from previous phase */}
              {index > 0 && (
                <div className="phase-connector">
                  <div className="connector-line" />
                  <Icon icon="mdi:chevron-down" width="16" className="connector-arrow" />
                </div>
              )}

              <PhaseBlock
                phase={phase}
                index={index}
                isSelected={selectedPhaseIndex === index}
                onSelect={() => setSelectedPhase(index)}
              />
            </div>
          ))}

          {/* Drop indicator when dragging phase over */}
          {isOver && (
            <div className="drop-indicator">
              <Icon icon="mdi:plus-circle" width="24" />
              <span>Drop to add phase</span>
            </div>
          )}
        </div>
      </SortableContext>

      {/* Add Phase Button */}
      <button className="add-phase-btn" onClick={handleAddPhase}>
        <Icon icon="mdi:plus" width="20" />
        <span>Add Phase</span>
      </button>

      {/* Empty state */}
      {phases.length === 0 && !isOver && (
        <div className="phases-empty">
          <Icon icon="mdi:view-sequential-outline" width="48" />
          <p>No phases yet</p>
          <p className="empty-hint">Drag a Phase block here or click "Add Phase"</p>
        </div>
      )}
    </div>
  );
}

export default PhasesRail;
