import React, { useMemo } from 'react';
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
 */
const PlotlyPanel = ({ content }) => {
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

  return (
    <div className="plotly-panel">
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
      />
    </div>
  );
};

export default PlotlyPanel;
