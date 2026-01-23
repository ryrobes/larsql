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
  // Helper: Try to parse JSON strings from cascade UDF results
  // When a cascade returns {"format": "image", "images": [...]}, SQL returns it as a string
  // This function parses that string back to an object
  // Handles multiple columns: SELECT generate_image('cat') as src, 'My Cat' as caption
  function tryParseJsonFromCell(panelData) {
    if (!Array.isArray(panelData) || panelData.length === 0) return panelData;

    // Process each row to find and parse JSON strings
    return panelData.map(row => {
      if (!row || typeof row !== 'object') return row;

      const keys = Object.keys(row);
      let parsedImageData = null;
      const otherFields = {};

      // Look through all columns for JSON image data
      for (const key of keys) {
        const value = row[key];
        if (typeof value === 'string') {
          const trimmed = value.trim();
          if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
            try {
              const parsed = JSON.parse(trimmed);
              // Check if this is image data (has format: "image" or images array)
              if (parsed.format === 'image' || (Array.isArray(parsed.images) && parsed.images.length > 0)) {
                parsedImageData = parsed;
                continue; // Don't add to otherFields
              }
            } catch (e) {
              // Not valid JSON, treat as regular field
            }
          }
        }
        // Keep non-JSON fields (like caption, title, etc.)
        otherFields[key] = value;
      }

      // If we found image data, merge with other fields
      if (parsedImageData) {
        return { ...parsedImageData, ...otherFields };
      }

      // No image JSON found, return original row
      return row;
    });
  }

  // Multi-panel format: auto-generated grid from --- PANEL syntax
  if (isMultiPanel && multiPanelData && multiPanelData.length > 0) {
    // Separate background panels (position 0,0) from regular grid panels
    const backgroundPanelData = multiPanelData.filter(p =>
      p.position?.col === 0 && p.position?.row === 0
    );
    const gridPanelData = multiPanelData.filter(p =>
      !(p.position?.col === 0 && p.position?.row === 0)
    );

    // Check if any grid panels have position hints
    const hasPositionHints = gridPanelData.some(p => p.position);

    let cols, rows;

    if (hasPositionHints) {
      // Calculate implied grid dimensions from position hints (excluding background panels)
      // Grid size = max extent of all panels (col + colspan - 1, row + rowspan - 1)
      cols = Math.max(1, ...gridPanelData.map(p => {
        if (p.position) {
          return p.position.col + (p.position.colspan || 1) - 1;
        }
        return 1;
      }));
      rows = Math.max(1, ...gridPanelData.map(p => {
        if (p.position) {
          return p.position.row + (p.position.rowspan || 1) - 1;
        }
        return 1;
      }));
    } else {
      // Auto-layout: calculate grid dimensions based on panel count
      const panelCount = gridPanelData.length;
      cols = panelCount <= 2 ? Math.max(1, panelCount) : panelCount <= 4 ? 2 : 3;
      rows = Math.max(1, Math.ceil(panelCount / cols));
    }

    // Convert multi-panel data to panel format for PanelRenderer
    // Detect panel type based on content structure
    const panels = multiPanelData.map((panel, index) => {
      // Try to parse JSON from cascade UDF results (e.g., image generation)
      const panelData = tryParseJsonFromCell(panel.data);

      // Detect mermaid content: single-row array with 'mermaid' key
      const isMermaid = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.mermaid;

      // Detect explicit metric: single-row array with format: "metric"
      const isExplicitMetric = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'metric';

      // Detect slider: single-row array with format: "slider"
      const isSlider = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'slider';

      // Detect dropdown: array with format: "dropdown" (can have multiple rows for options)
      const isDropdown = Array.isArray(panelData) &&
        panelData.length > 0 &&
        panelData[0]?.format === 'dropdown';

      // Detect daterange: single-row array with format: "daterange"
      const isDateRange = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'daterange';

      // Detect toggle: single-row array with format: "toggle"
      const isToggle = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'toggle';

      // Detect sparkline: array with format: "sparkline"
      const isSparkline = Array.isArray(panelData) &&
        panelData.length > 0 &&
        panelData[0]?.format === 'sparkline';

      // Detect markdown: array with format: "markdown" and code/content/markdown/text/body field
      const isMarkdown = Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'markdown';

      // Detect explicit image: array with format: "image"
      const isExplicitImage = Array.isArray(panelData) &&
        panelData.length > 0 &&
        panelData[0]?.format === 'image';

      // Detect auto-image: data containing image paths, URLs, or base64
      const isAutoImage = !isExplicitImage && Array.isArray(panelData) &&
        panelData.length > 0 &&
        panelData.some(row => {
          if (!row || typeof row !== 'object') return false;

          // Check for 'images' array (from cascade image generation)
          if (Array.isArray(row.images) && row.images.length > 0) {
            return row.images.some(img => typeof img === 'string' && isImageValue(img, true));
          }

          const values = Object.entries(row);
          return values.some(([key, val]) => {
            if (typeof val !== 'string') return false;
            // Check column name hints
            const imageColNames = ['image', 'img', 'src', 'photo', 'thumbnail', 'picture', 'avatar'];
            const keyLower = key.toLowerCase();
            if (imageColNames.some(name => keyLower.includes(name))) {
              // Column name suggests image - be lenient with URL validation
              return isImageValue(val, true);
            }
            // Check value patterns (more strict when column name doesn't hint)
            return val.startsWith('data:image/') ||
                   (val.match(/\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i) && val.length < 500);
          });
        });

      // Helper to detect image values
      // When columnHint is true, we're more lenient (column name suggests image)
      function isImageValue(val, columnHint = false) {
        if (!val || typeof val !== 'string') return false;
        // Base64 data URL
        if (val.startsWith('data:image/')) return true;
        // File extensions
        if (val.match(/\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i)) return true;
        // HTTP URLs with image extensions
        if (val.match(/^https?:\/\/.*\.(png|jpg|jpeg|gif|webp|svg|bmp)/i)) return true;
        // API image paths (from cascade image generation)
        if (val.startsWith('/api/images/')) return true;
        // If column name hints at image, trust HTTP URLs even without extension
        // (e.g., picsum.photos, imgur, cloudinary dynamic URLs)
        if (columnHint && val.match(/^https?:\/\//)) return true;
        return false;
      }

      // Detect data-driven chart: multiple rows with format, config, and data columns
      // e.g., SELECT 'vega-lite' as format, {mark: 'bar', x: 'month', y: 'value'} as config, month, value FROM data
      const dataDrivenChart = isDataDrivenChart(panelData) ? processDataDrivenChart(panelData) : null;

      // Detect Plotly chart: single-row array with format: "plotly" (legacy spec format)
      // Also check for 'spec' field to distinguish from data-driven format
      const isPlotly = !dataDrivenChart && Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'plotly' &&
        panelData[0]?.spec !== undefined;

      // Detect Vega-Lite chart: single-row array with format: "vega-lite" (legacy spec format)
      // Also check for 'spec' field to distinguish from data-driven format
      const isVegaLite = !dataDrivenChart && Array.isArray(panelData) &&
        panelData.length === 1 &&
        panelData[0]?.format === 'vega-lite' &&
        panelData[0]?.spec !== undefined;

      // Detect auto-metric: single row with single value column
      // (excluding 'format' key if present)
      const isAutoMetric = !isMermaid && !isExplicitMetric && !isSlider && !isDropdown && !isDateRange && !isToggle && !isSparkline && !isMarkdown && !isExplicitImage && !isAutoImage && !isPlotly && !isVegaLite && !dataDrivenChart &&
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
      } else if (isSlider) {
        panelType = 'slider';
      } else if (isDropdown) {
        panelType = 'dropdown';
      } else if (isDateRange) {
        panelType = 'daterange';
      } else if (isToggle) {
        panelType = 'toggle';
      } else if (isSparkline) {
        panelType = 'sparkline';
      } else if (isMarkdown) {
        panelType = 'markdown';
      } else if (isExplicitImage || isAutoImage) {
        panelType = 'image';
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
        // Pass through display options
        hide_border: panel.hide_border,
        hide_title: panel.hide_title,
        // Pass through visual modifiers
        opacity: panel.opacity,
        blur: panel.blur,
        objectFit: panel.object_fit,
        // Track if this is a background panel (position 0,0)
        isBackground: panel.position?.col === 0 && panel.position?.row === 0,
      };
    });

    // Separate processed panels into background and grid panels
    const backgroundPanels = panels.filter(p => p.isBackground);
    const gridPanels = panels.filter(p => !p.isBackground);
    const hasBackground = backgroundPanels.length > 0;

    return (
      <div
        className={`canvas-container ${hasBackground ? 'canvas-has-background' : ''}`}
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          minHeight: '400px'
        }}
      >
        {/* Background panels - render first, behind everything */}
        {backgroundPanels.map((panel, index) => (
          <div
            key={`bg-${panel.name}_${index}`}
            className="canvas-background-panel"
            data-object-fit={panel.objectFit || 'cover'}
            style={{
              position: 'absolute',
              inset: 0,
              zIndex: 0,
              pointerEvents: 'none',
              opacity: panel.opacity ?? 1,
              filter: panel.blur ? `blur(${panel.blur})` : undefined,
              '--bg-object-fit': panel.objectFit || 'cover'
            }}
          >
            <PanelRenderer
              panel={{ ...panel, hide_border: true, hide_title: true }}
              style={{ width: '100%', height: '100%' }}
              isBackground={true}
            />
          </div>
        ))}

        {/* Grid panels - render on top */}
        <div
          className="canvas-grid canvas-multi-panel"
          style={{
            position: 'relative',
            zIndex: 1,
            display: 'grid',
            gridTemplateColumns: `repeat(${cols}, 1fr)`,
            gridTemplateRows: `repeat(${rows}, minmax(200px, 1fr))`,
            gap: '16px',
            height: '100%',
          }}
        >
          {gridPanels.map((panel, index) => (
            <PanelRenderer
              key={`${panel.name}_${index}`}
              panel={panel}
              style={{
                ...panel.gridStyle,
                // Pass opacity/blur as CSS variables for background-only effect
                '--panel-bg-opacity': panel.opacity ?? 1,
                '--panel-blur': panel.blur ? `blur(${panel.blur})` : 'none',
              }}
              onInteraction={onInteraction}
            />
          ))}
        </div>
      </div>
    );
  }

  // Canvas format: render layout with panels
  if (isCanvas && canvasData) {
    const { layout, panels: rawPanels } = canvasData;
    const isFloating = layout?.type === 'floating';

    if (!rawPanels || rawPanels.length === 0) {
      return (
        <div className="canvas-renderer-empty">
          No panels in canvas
        </div>
      );
    }

    // Client-side check for duplicate panel names (prevents React key issues)
    const panelNames = rawPanels.map(p => p.name);
    const duplicates = panelNames.filter((name, idx) => panelNames.indexOf(name) !== idx);
    if (duplicates.length > 0) {
      return (
        <div className="canvas-renderer-error">
          <strong>Error:</strong> Duplicate panel names detected: {[...new Set(duplicates)].join(', ')}.
          Each panel must have a unique name.
        </div>
      );
    }

    // Process panels to detect data-driven charts (same logic as multi-panel)
    const panels = rawPanels.map(panel => {
      // Try to parse JSON from cascade UDF results (e.g., image generation)
      const panelData = tryParseJsonFromCell(panel.content);

      // Check for data-driven chart format
      const dataDrivenChart = isDataDrivenChart(panelData) ? processDataDrivenChart(panelData) : null;

      if (dataDrivenChart) {
        // Transform to chart panel
        return {
          ...panel,
          type: dataDrivenChart.format,
          content: [{ format: dataDrivenChart.format, spec: dataDrivenChart.spec }],
        };
      }

      // Keep original panel (already has type from backend)
      return panel;
    });

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
