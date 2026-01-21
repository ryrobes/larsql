import React, { useMemo, useCallback } from 'react';
import Plot from 'react-plotly.js';
import { Icon } from '@iconify/react';
import './PlotlyPanel.css';

/**
 * PlotlyPanel - Renders Plotly charts from JSON spec
 *
 * Accepts content in format:
 * {
 *   format: "plotly",
 *   spec: { data: [...], layout: {...} }  // or as JSON string
 * }
 *
 * Or array format from SQL:
 * [{ format: "plotly", spec: "..." }]
 *
 * @param {array|object} content - Chart content with spec
 * @param {function} onClick - Callback when a data point is clicked (receives point data)
 * @param {boolean} interactive - Whether chart is interactive (shows cursor)
 * @param {*} selectedValue - Currently selected value (for toggle detection)
 * @param {string} selectField - Field name to match for selection
 */
const PlotlyPanel = ({ content, onClick, interactive, selectedValue, selectField }) => {
  // Extract and parse the Plotly spec
  const { spec, error } = useMemo(() => {
    try {
      let rawSpec;

      // Handle array format (from SQL result)
      if (Array.isArray(content) && content.length === 1) {
        rawSpec = content[0].spec;
      } else if (content && typeof content === 'object') {
        rawSpec = content.spec;
      }

      if (!rawSpec) {
        return { spec: null, error: 'No spec provided' };
      }

      // Parse if string
      const parsed = typeof rawSpec === 'string' ? JSON.parse(rawSpec) : rawSpec;

      return { spec: parsed, error: null };
    } catch (err) {
      return { spec: null, error: `Invalid Plotly spec: ${err.message}` };
    }
  }, [content]);

  // Dark theme defaults for Plotly
  const darkLayout = useMemo(() => ({
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: {
      family: "'Google Sans', sans-serif",
      color: '#cbd5e1',
    },
    xaxis: {
      gridcolor: '#1e293b',
      linecolor: '#334155',
      tickcolor: '#64748b',
      zerolinecolor: '#334155',
    },
    yaxis: {
      gridcolor: '#1e293b',
      linecolor: '#334155',
      tickcolor: '#64748b',
      zerolinecolor: '#334155',
    },
    colorway: ['#00e5ff', '#ff6b6b', '#4ade80', '#fbbf24', '#a78bfa', '#f472b6'],
    margin: { t: 40, r: 20, b: 40, l: 50 },
    ...spec?.layout,
  }), [spec?.layout]);

  // Handle click on data point
  const handleClick = useCallback((event) => {
    if (!onClick || !event.points || event.points.length === 0) return;

    const point = event.points[0];

    // Debug: log what we receive from Plotly
    console.log('[PlotlyPanel] Click event point:', point);
    console.log('[PlotlyPanel] point.customdata:', point.customdata);
    console.log('[PlotlyPanel] point.data.customdata:', point.data?.customdata);

    // Build data object from clicked point
    // Start with original row data from customdata (preserves SQL column names)
    // Then overlay Plotly's standard fields
    const clickedData = {};

    // Merge original row data if available (from customdata)
    // This gives us the original SQL column names (e.g., 'category' instead of 'label')
    // Note: point.customdata can be an array (for pie charts) or object (for other charts)
    if (point.customdata) {
      const rowData = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
      if (rowData && typeof rowData === 'object') {
        Object.assign(clickedData, rowData);
      }
    }

    // Overlay Plotly's standard fields
    if (point.label !== undefined) {
      // Pie chart - use label field
      clickedData.label = point.label;
      clickedData.value = point.value;
    }
    if (point.x !== undefined) {
      clickedData.x = point.x;
    }
    if (point.y !== undefined) {
      clickedData.y = point.y;
    }
    if (point.z !== undefined) {
      clickedData.z = point.z;
    }

    // Include the trace name if available (for multi-series)
    if (point.data?.name) {
      clickedData._series = point.data.name;
    }

    // Include point index for reference
    clickedData._pointIndex = point.pointIndex;

    // Check if this is a toggle-off (clicking already selected item)
    if (selectField && selectedValue !== null && selectedValue !== undefined) {
      const clickedFieldValue = String(clickedData[selectField]);
      if (clickedFieldValue === String(selectedValue)) {
        // This is a deselect
        onClick({ ...clickedData, _isDeselect: true });
        return;
      }
    }

    onClick(clickedData);
  }, [onClick, selectedValue, selectField]);

  if (error) {
    return (
      <div className="plotly-panel-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
      </div>
    );
  }

  if (!spec) {
    return (
      <div className="plotly-panel-error">
        <Icon icon="mdi:chart-box-outline" width="20" />
        <span>No chart data</span>
      </div>
    );
  }

  // Debug: log the spec to verify customdata is set
  console.log('[PlotlyPanel] Rendering spec:', spec);
  console.log('[PlotlyPanel] First trace customdata:', spec.data?.[0]?.customdata);

  return (
    <div className={`plotly-panel ${interactive ? 'plotly-interactive' : ''}`}>
      <Plot
        data={spec.data || []}
        layout={darkLayout}
        config={{
          displayModeBar: true,
          displaylogo: false,
          responsive: true,
          modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        }}
        useResizeHandler={true}
        style={{ width: '100%', height: '100%' }}
        onClick={interactive ? handleClick : undefined}
      />
    </div>
  );
};

export default PlotlyPanel;
