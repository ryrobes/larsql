import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import CellBlock from './blocks/CellBlock';
import './CellsRail.css';

/**
 * CellsRail - Sortable vertical list of cells in the editor
 *
 * Features:
 * - Drag to reorder cells
 * - Drop zone for new cells from palette
 * - Add new cell button
 * - Visual connection lines between cells
 *
 * Note: Ghost visualization (preview of execution) is shown in ExecutionNotebook,
 * not here. This is purely the editor view for configuring cells.
 */
function CellsRail() {
  const {
    cascade,
    selectedCellIndex,
    setSelectedCell,
    addCell,
  } = useWorkshopStore();

  const cells = cascade.cells || [];

  // Droppable zone for new cells from palette
  const { setNodeRef: setDropZoneRef, isOver } = useDroppable({
    id: 'cells-drop-zone',
    data: {
      accepts: ['cell'],
    },
  });

  const handleAddCell = () => {
    addCell();
  };

  const cellIds = cells.map((p) => `cell-${p.name}`);

  return (
    <div className="cells-rail" ref={setDropZoneRef}>
      <SortableContext items={cellIds} strategy={verticalListSortingStrategy}>
        <div className={`cells-list ${isOver ? 'drop-active' : ''}`}>
          {cells.map((cell, index) => (
            <div key={`cell-${cell.name}`} className="cell-wrapper">
              {/* Connection line from previous cell */}
              {index > 0 && (
                <div className="cell-connector">
                  <div className="connector-line" />
                  <Icon icon="mdi:chevron-down" width="16" className="connector-arrow" />
                </div>
              )}

              <CellBlock
                cell={cell}
                index={index}
                isSelected={selectedCellIndex === index}
                onSelect={() => setSelectedCell(index)}
              />
            </div>
          ))}

          {/* Drop indicator when dragging cell over */}
          {isOver && (
            <div className="drop-indicator">
              <Icon icon="mdi:plus-circle" width="24" />
              <span>Drop to add cell</span>
            </div>
          )}
        </div>
      </SortableContext>

      {/* Add Cell Button */}
      <button className="add-cell-btn" onClick={handleAddCell}>
        <Icon icon="mdi:plus" width="20" />
        <span>Add Cell</span>
      </button>

      {/* Empty state */}
      {cells.length === 0 && !isOver && (
        <div className="cells-empty">
          <Icon icon="mdi:view-sequential-outline" width="48" />
          <p>No cells yet</p>
          <p className="empty-hint">Drag a Cell block here or click "Add Cell"</p>
        </div>
      )}
    </div>
  );
}

export default CellsRail;
