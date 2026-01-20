import React from 'react';
import PanelRenderer from './PanelRenderer';
import DataGridPanel from './DataGridPanel';
import './CanvasRenderer.css';

/**
 * CanvasRenderer - Renders either a canvas layout or a plain data grid
 *
 * Detects the format of the result and renders accordingly:
 * - Canvas format: Grid layout with multiple panels
 * - Plain data: Simple data grid table
 */
const CanvasRenderer = ({ data, columns, isCanvas, canvasData }) => {
  // Canvas format: render grid layout with panels
  if (isCanvas && canvasData) {
    const { layout, panels } = canvasData;

    if (!panels || panels.length === 0) {
      return (
        <div className="canvas-renderer-empty">
          No panels in canvas
        </div>
      );
    }

    // Client-side check for duplicate panel names (prevents React key issues)
    const panelNames = panels.map(p => p.name);
    const duplicates = panelNames.filter((name, idx) => panelNames.indexOf(name) !== idx);
    if (duplicates.length > 0) {
      return (
        <div className="canvas-renderer-error">
          <strong>Error:</strong> Duplicate panel names detected: {[...new Set(duplicates)].join(', ')}.
          Each panel must have a unique name.
        </div>
      );
    }

    return (
      <div
        className="canvas-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${layout?.cols || 2}, 1fr)`,
          gridTemplateRows: `repeat(${layout?.rows || 2}, minmax(200px, 1fr))`,
          gap: '16px',
          height: '100%',
          minHeight: '400px'
        }}
      >
        {panels.map((panel, index) => (
          <PanelRenderer
            key={`${panel.name}_${index}`}
            panel={panel}
            style={{
              gridColumn: `${panel.cell[0]} / span ${panel.cell[2] || 1}`,
              gridRow: `${panel.cell[1]} / span ${panel.cell[3] || 1}`
            }}
          />
        ))}
      </div>
    );
  }

  // Plain data format: render as data grid
  if (data && Array.isArray(data) && data.length > 0) {
    return (
      <div className="canvas-data-wrapper">
        <DataGridPanel content={data} />
      </div>
    );
  }

  // Empty result
  return (
    <div className="canvas-renderer-empty">
      No data to display
    </div>
  );
};

export default CanvasRenderer;
