import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
import './CascadeBar.css';

// Curated color palette - vibrant pastels that work on dark backgrounds
// Colors are ordered for visual appeal when adjacent
export const CELL_COLORS = [
  '#2DD4BF', // Teal (primary theme color)
  '#a78bfa', // Purple
  '#60a5fa', // Blue
  '#f472b6', // Pink
  '#fbbf24', // Amber
  '#34d399', // Emerald
  '#fb923c', // Orange
  '#22d3ee', // Cyan
  '#818cf8', // Indigo
  '#f87171', // Coral
  '#84cc16', // Lime
  '#e879f9', // Fuchsia
];

// Get a consistent color for a cell name (hash-based for consistency across renders)
export function getCellColor(cellName, index) {
  // Simple hash of cell name for consistent color assignment
  let hash = 0;
  for (let i = 0; i < cellName.length; i++) {
    hash = ((hash << 5) - hash) + cellName.charCodeAt(i);
    hash |= 0;
  }
  // Use absolute value and modulo to get index
  const colorIndex = Math.abs(hash) % CELL_COLORS.length;
  return CELL_COLORS[colorIndex];
}

// Sequential assignment for more predictable coloring (matches cascade bar order)
export function getSequentialColor(index) {
  return CELL_COLORS[index % CELL_COLORS.length];
}

function CascadeBar({ cells, totalCost, isRunning = false, mode = 'cost' }) {
  const [hoveredCell, setHoveredCell] = useState(null);
  const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 });
  const [selectedCell, setSelectedCell] = useState(null);  // Cell whose output is being displayed

  // Calculate cell data with colors and percentages
  const cellData = useMemo(() => {
    if (!cells || cells.length === 0) return [];

    // Use sequential colors for more pleasing adjacent color combinations
    return cells.map((cell, idx) => {
      const value = mode === 'cost'
        ? (cell.avg_cost || cell.total_cost || 0)
        : (cell.avg_duration || cell.duration || 0);

      return {
        ...cell,
        color: getSequentialColor(idx),
        value,
        index: idx
      };
    });
  }, [cells, mode]);

  // Calculate total for percentage calculation
  const total = useMemo(() => {
    return cellData.reduce((sum, p) => sum + p.value, 0) || 0.01;
  }, [cellData]);

  // Calculate percentage for each cell
  const cellsWithPercent = useMemo(() => {
    return cellData.map(p => ({
      ...p,
      percent: (p.value / total) * 100,
      displayPercent: Math.max((p.value / total) * 100, 2) // Minimum 2% for visibility
    }));
  }, [cellData, total]);

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const handleMouseMove = (e, cell) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltipPosition({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    });
    setHoveredCell(cell);
  };

  if (!cells || cells.length === 0) return null;

  return (
    <div className={`cascade-bar-container ${isRunning ? 'is-running' : ''}`}>
      {/* Main stacked bar */}
      <div className="cascade-bar-track">
        <div className="cascade-bar-segments">
          {cellsWithPercent.map((cell) => {
            const isCellRunning = cell.status === 'running';
            const isHovered = hoveredCell?.index === cell.index;

            return (
              <div
                key={cell.index}
                className={`cascade-segment ${isCellRunning ? 'running' : ''} ${isHovered ? 'hovered' : ''}`}
                style={{
                  width: `${cell.displayPercent}%`,
                  backgroundColor: cell.color,
                  '--cell-color': cell.color
                }}
                onMouseMove={(e) => handleMouseMove(e, cell)}
                onMouseLeave={() => setHoveredCell(null)}
              >
                {/* Inner glow effect */}
                <div className="segment-glow" />

                {/* Show cost label if segment is wide enough */}
                {cell.displayPercent > 12 && (
                  <span className="segment-label">
                    {mode === 'cost' ? formatCost(cell.value) : formatDuration(cell.value)}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Tooltip */}
        {hoveredCell && (
          <div
            className="cascade-bar-tooltip"
            style={{
              left: `${tooltipPosition.x}px`,
              top: '-60px'
            }}
          >
            <div className="tooltip-cell-name">
              <span
                className="tooltip-color-dot"
                style={{ backgroundColor: hoveredCell.color }}
              />
              {hoveredCell.name}
            </div>
            <div className="tooltip-stats">
              <span className="tooltip-cost">{formatCost(hoveredCell.value)}</span>
              <span className="tooltip-percent">{hoveredCell.percent.toFixed(1)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* Legend row */}
      <div className="cascade-bar-legend">
        {cellsWithPercent.map((cell) => {
          const isCellRunning = cell.status === 'running';
          const isCompleted = cell.status === 'completed';
          const isError = cell.status === 'error';
          const hasOutput = isCompleted && cell.cell_output;
          const isSelected = selectedCell?.index === cell.index;

          const handlePillClick = (e) => {
            e.stopPropagation();
            if (hasOutput) {
              // Toggle selection - if already selected, deselect; otherwise select this cell
              setSelectedCell(isSelected ? null : cell);
            }
          };

          return (
            <div
              key={cell.index}
              className={`legend-item ${isCellRunning ? 'running' : ''} ${hoveredCell?.index === cell.index ? 'hovered' : ''} ${hasOutput ? 'clickable' : ''} ${isSelected ? 'selected' : ''}`}
              onMouseEnter={() => setHoveredCell(cell)}
              onMouseLeave={() => setHoveredCell(null)}
              onClick={handlePillClick}
              title={hasOutput ? 'Click to view cell output' : undefined}
            >
              <span
                className="legend-color"
                style={{ backgroundColor: cell.color }}
              />
              <span className="legend-name">{cell.name}</span>
              {isCellRunning && (
                <Icon icon="mdi:loading" width="12" className="spinning legend-status" />
              )}
              {isCompleted && !isSelected && (
                <Icon icon="mdi:check" width="12" className="legend-status completed" />
              )}
              {isSelected && (
                <Icon icon="mdi:chevron-up" width="14" className="legend-status selected" />
              )}
              {isError && (
                <Icon icon="mdi:alert-circle" width="12" height="12" className="legend-status error" />
              )}
            </div>
          );
        })}
      </div>

      {/* Cell output panel */}
      {selectedCell && selectedCell.cell_output && (
        <div className="cell-output-panel" style={{ '--cell-color': selectedCell.color }}>
          <div className="cell-output-header">
            <div className="cell-output-title">
              <span className="cell-output-color" style={{ backgroundColor: selectedCell.color }} />
              <span className="cell-output-name">{selectedCell.name}</span>
              <span className="cell-output-label">output</span>
            </div>
            <button
              className="cell-output-close"
              onClick={() => setSelectedCell(null)}
              title="Close"
            >
              <Icon icon="mdi:close" width="16" />
            </button>
          </div>
          <div className="cell-output-content">
            <RichMarkdown>{selectedCell.cell_output}</RichMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

export default CascadeBar;
