import React from 'react';
import PanelRenderer from './PanelRenderer';
import DataGridPanel from './DataGridPanel';
import { isDataDrivenChart, processDataDrivenChart } from './chartConfigExpander';
import './CanvasRenderer.css';

/**
 * CanvasRenderer - Renders either a canvas layout or a plain data grid
 *
 * Detects the format of the result and renders accordingly:
 * - Multi-panel format: Auto-generated grid from --- PANEL syntax
 * - Canvas format (GRID): CSS Grid layout with cell-based positioning
 * - Canvas format (FLOATING): Absolute positioned panels with pixel coordinates
 * - Plain data: Simple data grid table
 *
 * @param {function} onInteraction - Callback for panel interactions (clicks, etc.)
 */
const CanvasRenderer = ({ data, columns, isCanvas, canvasData, isMultiPanel, multiPanelData, onInteraction }) => {
  // Multi-panel format: auto-generated grid from --- PANEL syntax
  if (isMultiPanel && multiPanelData && multiPanelData.length > 0) {
    // Check if any panels have position hints
    const hasPositionHints = multiPanelData.some(p => p.position);

    let cols, rows;

    if (hasPositionHints) {
      // Calculate implied grid dimensions from position hints
      // Grid size = max extent of all panels (col + colspan - 1, row + rowspan - 1)
      cols = Math.max(...multiPanelData.map(p => {
        if (p.position) {
          return p.position.col + (p.position.colspan || 1) - 1;
        }
        return 1;
      }));
      rows = Math.max(...multiPanelData.map(p => {
        if (p.position) {
          return p.position.row + (p.position.rowspan || 1) - 1;
        }
        return 1;
      }));
    } else {
      // Auto-layout: calculate grid dimensions based on panel count
      const panelCount = multiPanelData.length;
      cols = panelCount <= 2 ? panelCount : panelCount <= 4 ? 2 : 3;
      rows = Math.ceil(panelCount / cols);
    }

    // Convert multi-panel data to panel format for PanelRenderer
    // Detect panel type based on content structure
    const panels = multiPanelData.map((panel, index) => {
      const panelData = panel.data;

      // Detect mermaid content: single-row array with 'mermaid' key
      const isMermaid = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.mermaid;

      // Detect explicit metric: single-row array with format: "metric"
      const isExplicitMetric = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'metric';

      // Detect data-driven chart: multiple rows with format, config, and data columns
      // e.g., SELECT 'vega-lite' as format, {mark: 'bar', x: 'month', y: 'value'} as config, month, value FROM data
      const dataDrivenChart = isDataDrivenChart(panelData) ? processDataDrivenChart(panelData) : null;

      // Detect Plotly chart: single-row array with format: "plotly" (legacy spec format)
      const isPlotly = !dataDrivenChart && Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'plotly';

      // Detect Vega-Lite chart: single-row array with format: "vega-lite" (legacy spec format)
      const isVegaLite = !dataDrivenChart && Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'vega-lite';

      // Detect auto-metric: single row with single value column
      // (excluding 'format' key if present)
      const isAutoMetric = !isMermaid && !isExplicitMetric && !isPlotly && !isVegaLite && !dataDrivenChart &&
        Array.isArray(panelData) &&
        panelData.length === 1 &&
        (() => {
          const row = panelData[0];
          if (!row || typeof row !== 'object') return false;
          const keys = Object.keys(row).filter(k => k !== 'format');
          return keys.length === 1;
        })();

      // Determine panel type and content
      let panelType = 'data-grid';
      let isAutoMetricFlag = false;
      let panelContent = panelData;

      if (isMermaid) {
        panelType = 'mermaid-graph';
      } else if (isExplicitMetric) {
        panelType = 'metric';
      } else if (isAutoMetric) {
        panelType = 'metric';
        isAutoMetricFlag = true;
      } else if (dataDrivenChart) {
        // Data-driven chart: use processed spec
        panelType = dataDrivenChart.format;
        panelContent = [{ format: dataDrivenChart.format, spec: dataDrivenChart.spec }];
      } else if (isPlotly) {
        panelType = 'plotly';
      } else if (isVegaLite) {
        panelType = 'vega-lite';
      }

      // Calculate grid position
      let gridStyle = {};
      if (panel.position) {
        // Use explicit position from hints
        const { col, row, colspan = 1, rowspan = 1 } = panel.position;
        gridStyle = {
          gridColumn: `${col} / span ${colspan}`,
          gridRow: `${row} / span ${rowspan}`
        };
      } else if (hasPositionHints) {
        // Panel without position in a positioned layout - place in first available cell
        // For simplicity, just let it flow naturally
        gridStyle = {};
      }

      return {
        name: panel.name,
        type: panelType,
        content: panelContent,
        gridStyle,
        isAutoMetric: isAutoMetricFlag,
        // Pass through interaction metadata
        on_select: panel.on_select,
        multi_select: panel.multi_select,
        selected_values: panel.selected_values,  // multi-select
        selected_value: panel.selected_value,    // single-select
        select_field: panel.select_field,
      };
    });

    return (
      <div
        className="canvas-grid canvas-multi-panel"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, minmax(200px, 1fr))`,
          gap: '16px',
          height: '100%',
          minHeight: '400px'
        }}
      >
        {panels.map((panel, index) => (
          <PanelRenderer
            key={`${panel.name}_${index}`}
            panel={panel}
            style={panel.gridStyle}
            onInteraction={onInteraction}
          />
        ))}
      </div>
    );
  }

  // Canvas format: render layout with panels
  if (isCanvas && canvasData) {
    const { layout, panels } = canvasData;
    const isFloating = layout?.type === 'floating';

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

    // FLOATING layout: absolute positioning
    if (isFloating) {
      return (
        <div
          className="canvas-floating"
          style={{
            position: 'relative',
            width: layout?.width || 800,
            height: layout?.height || 600,
            minHeight: '400px',
            margin: '0 auto'
          }}
        >
          {panels.map((panel, index) => (
            <PanelRenderer
              key={`${panel.name}_${index}`}
              panel={panel}
              style={{
                position: 'absolute',
                left: panel.position?.x || 0,
                top: panel.position?.y || 0,
                width: panel.position?.width || 200,
                height: panel.position?.height || 150
              }}
              onInteraction={onInteraction}
            />
          ))}
        </div>
      );
    }

    // GRID layout: CSS Grid with cell positioning
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
              gridColumn: `${panel.cell?.[0] || 1} / span ${panel.cell?.[2] || 1}`,
              gridRow: `${panel.cell?.[1] || 1} / span ${panel.cell?.[3] || 1}`
            }}
            onInteraction={onInteraction}
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
