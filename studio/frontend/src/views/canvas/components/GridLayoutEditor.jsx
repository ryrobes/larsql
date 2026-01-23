import React, { useState, useMemo, useEffect, useCallback } from 'react';
import GridLayout from 'react-grid-layout';
import { noCompactor } from 'react-grid-layout/core';
import { Icon } from '@iconify/react';
import {
  parsePanelLayout,
  updatePanelPositions,
  toRGLLayout,
  parseGridSize,
  updateGridSize,
} from '../utils/sqlPanelLayout';
import PanelRenderer from './PanelRenderer';
import { isDataDrivenChart, processDataDrivenChart } from './chartConfigExpander';
import 'react-grid-layout/css/styles.css';
import './GridLayoutEditor.css';

/**
 * Try to parse JSON strings from cascade UDF results
 * When a cascade returns {"format": "image", "images": [...]}, SQL returns it as a string
 */
function tryParseJsonFromCell(panelData) {
  if (!Array.isArray(panelData) || panelData.length === 0) return panelData;

  return panelData.map(row => {
    if (!row || typeof row !== 'object') return row;

    const keys = Object.keys(row);
    let parsedImageData = null;
    const otherFields = {};

    for (const key of keys) {
      const value = row[key];
      if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
          try {
            const parsed = JSON.parse(trimmed);
            if (parsed.format === 'image' || (Array.isArray(parsed.images) && parsed.images.length > 0)) {
              parsedImageData = parsed;
              continue;
            }
          } catch (e) {
            // Not valid JSON
          }
        }
      }
      otherFields[key] = value;
    }

    if (parsedImageData) {
      return { ...parsedImageData, ...otherFields };
    }
    return row;
  });
}

/**
 * Helper to detect image values
 */
function isImageValue(val, columnHint = false) {
  if (!val || typeof val !== 'string') return false;
  if (val.startsWith('data:image/')) return true;
  if (val.match(/\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i)) return true;
  if (val.match(/^https?:\/\/.*\.(png|jpg|jpeg|gif|webp|svg|bmp)/i)) return true;
  if (val.startsWith('/api/images/')) return true;
  if (columnHint && val.match(/^https?:\/\//)) return true;
  return false;
}

/**
 * Convert API panel format to PanelRenderer format
 * API gives: { name, data, on_select, ... }
 * PanelRenderer expects: { name, content, type, ... }
 */
function convertPanelForRenderer(apiPanel) {
  // Try to parse JSON from cascade UDF results (e.g., image generation)
  const panelData = tryParseJsonFromCell(apiPanel.data);

  // Detect panel type based on content
  const isMermaid = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.mermaid;
  const isExplicitMetric = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'metric';
  const isSlider = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'slider';
  const isDropdown = Array.isArray(panelData) && panelData.length > 0 && panelData[0]?.format === 'dropdown';
  const isDateRange = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'daterange';
  const isToggle = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'toggle';
  const isSparkline = Array.isArray(panelData) && panelData.length > 0 && panelData[0]?.format === 'sparkline';
  const isMarkdown = Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'markdown';

  // Detect explicit image: array with format: "image"
  const isExplicitImage = Array.isArray(panelData) &&
    panelData.length > 0 &&
    panelData[0]?.format === 'image';

  // Detect auto-image: data containing image paths, URLs, or base64
  const isAutoImage = !isExplicitImage && Array.isArray(panelData) &&
    panelData.length > 0 &&
    panelData.some(row => {
      if (!row || typeof row !== 'object') return false;
      if (Array.isArray(row.images) && row.images.length > 0) {
        return row.images.some(img => typeof img === 'string' && isImageValue(img, true));
      }
      const values = Object.entries(row);
      return values.some(([key, val]) => {
        if (typeof val !== 'string') return false;
        const imageColNames = ['image', 'img', 'src', 'photo', 'thumbnail', 'picture', 'avatar'];
        const keyLower = key.toLowerCase();
        if (imageColNames.some(name => keyLower.includes(name))) {
          return isImageValue(val, true);
        }
        return val.startsWith('data:image/') ||
               (val.match(/\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i) && val.length < 500);
      });
    });

  // Check for data-driven chart
  const dataDrivenChart = isDataDrivenChart(panelData) ? processDataDrivenChart(panelData) : null;

  const isPlotly = !dataDrivenChart && Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'plotly';
  const isVegaLite = !dataDrivenChart && Array.isArray(panelData) && panelData.length === 1 && panelData[0]?.format === 'vega-lite';

  // Auto-metric detection (exclude images)
  const isAutoMetric = !isMermaid && !isExplicitMetric && !isSlider && !isDropdown && !isDateRange && !isToggle && !isSparkline && !isPlotly && !isVegaLite && !dataDrivenChart && !isExplicitImage && !isAutoImage &&
    Array.isArray(panelData) && panelData.length === 1 && (() => {
      const row = panelData[0];
      if (!row || typeof row !== 'object') return false;
      const keys = Object.keys(row).filter(k => k !== 'format');
      return keys.length === 1;
    })();

  let panelType = 'data-grid';
  let panelContent = panelData;

  if (isMermaid) panelType = 'mermaid-graph';
  else if (isExplicitMetric) panelType = 'metric';
  else if (isSlider) panelType = 'slider';
  else if (isDropdown) panelType = 'dropdown';
  else if (isDateRange) panelType = 'daterange';
  else if (isToggle) panelType = 'toggle';
  else if (isSparkline) panelType = 'sparkline';
  else if (isMarkdown) panelType = 'markdown';
  else if (isExplicitImage || isAutoImage) panelType = 'image';
  else if (isAutoMetric) panelType = 'metric';
  else if (dataDrivenChart) {
    panelType = dataDrivenChart.format;
    panelContent = [{ format: dataDrivenChart.format, spec: dataDrivenChart.spec }];
  }
  else if (isPlotly) panelType = 'plotly';
  else if (isVegaLite) panelType = 'vega-lite';

  return {
    name: apiPanel.name,
    type: panelType,
    content: panelContent,
    isAutoMetric,
    on_select: apiPanel.on_select,
    multi_select: apiPanel.multi_select,
    selected_values: apiPanel.selected_values,
    selected_value: apiPanel.selected_value,
    select_field: apiPanel.select_field,
    hide_border: apiPanel.hide_border,
    hide_title: apiPanel.hide_title,
  };
}

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
  onInteraction,
  editMode,
  onExitEdit,
}) => {
  // Parse layout from SQL (only used for initialization)
  const parsed = useMemo(() => parsePanelLayout(sql), [sql]);
  const explicitGridSize = useMemo(() => parseGridSize(sql), [sql]);

  // Local layout state - only written to SQL on "Done"
  const [localLayout, setLocalLayout] = useState(() => toRGLLayout(parsed.panels));
  const [gridCols, setGridCols] = useState(explicitGridSize?.cols || parsed.gridSize.cols);
  const [gridRows, setGridRows] = useState(explicitGridSize?.rows || parsed.gridSize.rows);

  // Re-initialize local state when entering edit mode or SQL changes externally
  const prevEditMode = React.useRef(editMode);
  useEffect(() => {
    // Only reset when entering edit mode (not while dragging)
    if (editMode && !prevEditMode.current) {
      const newParsed = parsePanelLayout(sql);
      const newExplicit = parseGridSize(sql);
      setLocalLayout(toRGLLayout(newParsed.panels));
      setGridCols(newExplicit?.cols || newParsed.gridSize.cols);
      setGridRows(newExplicit?.rows || newParsed.gridSize.rows);
    }
    prevEditMode.current = editMode;
  }, [editMode, sql]);

  const containerRef = React.useRef(null);

  // Fixed cell dimensions for edit mode
  const CELL_SIZE = 140;
  const GRID_MARGIN = 10;
  const EDITOR_COLS = 12;

  const gridLayoutWidth = (CELL_SIZE * EDITOR_COLS) + (GRID_MARGIN * (EDITOR_COLS - 1));

  // Handle layout change from drag/resize - only update local state
  const handleLayoutChange = useCallback((newLayout) => {
    setLocalLayout(newLayout);
  }, []);

  // Handle grid size change - only update local state
  const handleGridSizeChange = useCallback((newCols, newRows) => {
    setGridCols(newCols);
    setGridRows(newRows);
  }, []);

  // Apply changes to SQL when "Done" is clicked
  const handleDone = useCallback(() => {
    let updatedSql = updatePanelPositions(sql, localLayout);
    updatedSql = updateGridSize(updatedSql, gridCols, gridRows);
    // Pass updated SQL to onExitEdit so it can update state and run query atomically
    onExitEdit(updatedSql);
  }, [sql, localLayout, gridCols, gridRows, onExitEdit]);

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
          <button className="grid-editor-done-btn" onClick={handleDone}>
            <Icon icon="mdi:check" width="16" />
            Done
          </button>
        </div>
      </div>

      {/* Grid layout */}
      <div className="grid-editor-canvas">
        <GridLayout
          className="grid-layout"
          layout={localLayout}
          cols={EDITOR_COLS}
          rowHeight={CELL_SIZE}
          width={gridLayoutWidth}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          containerPadding={[0, 0]}
          compactor={noCompactor}
          allowOverlap={true}
          preventCollision={false}
          onLayoutChange={handleLayoutChange}
          isDraggable={true}
          isResizable={true}
          resizeHandles={['se', 'sw', 'ne', 'nw']}
        >
          {parsed.panels.map(panel => {
            const apiPanel = panelContentMap[panel.name];

            return (
              <div key={panel.name} className="grid-editor-panel">
                {apiPanel ? (
                  <div className="grid-panel-scaled-content">
                    <PanelRenderer
                      panel={{
                        ...convertPanelForRenderer(apiPanel),
                        hide_title: true,
                        hide_border: true,
                      }}
                      onInteraction={null}
                    />
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
