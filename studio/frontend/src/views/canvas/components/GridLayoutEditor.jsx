import React, { useState, useMemo, useEffect, useCallback } from 'react';
import GridLayout from 'react-grid-layout';
import { Icon } from '@iconify/react';
import {
  parsePanelLayout,
  updatePanelPositions,
  toRGLLayout,
  parseGridSize,
  updateGridSize,
} from '../utils/sqlPanelLayout';
import 'react-grid-layout/css/styles.css';
import './GridLayoutEditor.css';

/**
 * GridLayoutEditor - Visual drag/drop grid editor for Hyper dashboards
 *
 * Allows users to:
 * - Drag panels to reposition
 * - Resize panels by dragging corners
 * - Change grid dimensions
 * - Changes are written back to the SQL source
 *
 * @param {string} sql - Current SQL in the editor
 * @param {function} onSqlChange - Callback to update SQL
 * @param {Array} multiPanelData - Rendered panel data from query execution
 * @param {function} onInteraction - Panel interaction callback
 * @param {boolean} editMode - Whether we're in edit mode
 * @param {function} onExitEdit - Callback to exit edit mode
 */
const GridLayoutEditor = ({
  sql,
  onSqlChange,
  multiPanelData,
  panelThumbnails = {},
  onInteraction,
  editMode,
  onExitEdit,
}) => {
  // Parse layout from SQL
  const parsed = useMemo(() => parsePanelLayout(sql), [sql]);
  const explicitGridSize = useMemo(() => parseGridSize(sql), [sql]);

  // Grid dimensions state - initialize from SQL or parsed
  const [gridCols, setGridCols] = useState(explicitGridSize?.cols || parsed.gridSize.cols);
  const [gridRows, setGridRows] = useState(explicitGridSize?.rows || parsed.gridSize.rows);

  // Update grid size when SQL changes
  useEffect(() => {
    const newExplicit = parseGridSize(sql);
    const newParsed = parsePanelLayout(sql);
    setGridCols(newExplicit?.cols || newParsed.gridSize.cols);
    setGridRows(newExplicit?.rows || newParsed.gridSize.rows);
  }, [sql]);

  // Convert to react-grid-layout format
  const layout = useMemo(() => toRGLLayout(parsed.panels), [parsed.panels]);

  const containerRef = React.useRef(null);

  // Fixed cell dimensions for edit mode
  const CELL_SIZE = 140; // Fixed 100x100 cells
  const GRID_MARGIN = 10;
  const EDITOR_COLS = 12; // Fixed large grid for editor canvas

  // Calculate GridLayout width based on fixed cell size and editor columns
  // Formula: width = (cellSize * cols) + (margin * (cols - 1))
  const gridLayoutWidth = (CELL_SIZE * EDITOR_COLS) + (GRID_MARGIN * (EDITOR_COLS - 1));

  // Handle layout change from drag/resize
  const handleLayoutChange = useCallback((newLayout) => {
    // Update SQL with new positions
    const updatedSql = updatePanelPositions(sql, newLayout);
    onSqlChange(updatedSql);
  }, [sql, onSqlChange]);

  // Handle grid size change
  const handleGridSizeChange = useCallback((newCols, newRows) => {
    setGridCols(newCols);
    setGridRows(newRows);
    // Update SQL with grid comment
    const updatedSql = updateGridSize(sql, newCols, newRows);
    onSqlChange(updatedSql);
  }, [sql, onSqlChange]);

  // Build panel content map from executed data
  const panelContentMap = useMemo(() => {
    const map = {};
    if (multiPanelData) {
      multiPanelData.forEach(panel => {
        map[panel.name] = panel;
      });
    }
    return map;
  }, [multiPanelData]);

  // If not in edit mode, just render normally
  if (!editMode) {
    return null; // Let CanvasRenderer handle normal rendering
  }

  return (
    <div className="grid-layout-editor" ref={containerRef}>
      {/* Edit toolbar */}
      <div className="grid-editor-toolbar">
        <div className="grid-editor-toolbar-left">
          <Icon icon="mdi:grid" width="18" />
          <span className="grid-editor-title">Layout Editor</span>
        </div>
        <div className="grid-editor-toolbar-center">
          <label className="grid-size-control">
            <span>Columns:</span>
            <input
              type="number"
              min="1"
              max="12"
              value={gridCols}
              onChange={(e) => handleGridSizeChange(parseInt(e.target.value) || 1, gridRows)}
            />
          </label>
          <label className="grid-size-control">
            <span>Rows:</span>
            <input
              type="number"
              min="1"
              max="12"
              value={gridRows}
              onChange={(e) => handleGridSizeChange(gridCols, parseInt(e.target.value) || 1)}
            />
          </label>
        </div>
        <div className="grid-editor-toolbar-right">
          <button className="grid-editor-done-btn" onClick={onExitEdit}>
            <Icon icon="mdi:check" width="16" />
            Done
          </button>
        </div>
      </div>

      {/* Grid layout */}
      <div className="grid-editor-canvas">
        <GridLayout
          className="grid-layout"
          layout={layout}
          cols={EDITOR_COLS}
          rowHeight={CELL_SIZE}
          width={gridLayoutWidth}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          containerPadding={[0, 0]}
          onLayoutChange={handleLayoutChange}
          isDraggable={true}
          isResizable={true}
          resizeHandles={['se', 'sw', 'ne', 'nw']}
        >
          {parsed.panels.map(panel => {
            const panelData = panelContentMap[panel.name];

            return (
              <div key={panel.name} className="grid-editor-panel">
                {panelThumbnails[panel.name] ? (
                  <img
                    src={panelThumbnails[panel.name]}
                    alt={panel.name}
                    className="grid-panel-thumbnail"
                  />
                ) : panelData ? (
                  <div className="grid-panel-placeholder">
                    <Icon icon="mdi:image-outline" width="24" />
                  </div>
                ) : (
                  <div className="grid-panel-placeholder">
                    <Icon icon="mdi:play-circle-outline" width="24" />
                  </div>
                )}
              </div>
            );
          })}
        </GridLayout>
      </div>
    </div>
  );
};

export default GridLayoutEditor;
