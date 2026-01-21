import React, { useRef, useEffect, useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './VegaLitePanel.css';

// Lazy load vega-embed
let vegaEmbedInstance = null;
const getVegaEmbed = async () => {
  if (!vegaEmbedInstance) {
    const vegaEmbed = await import('vega-embed');
    vegaEmbedInstance = vegaEmbed.default;
  }
  return vegaEmbedInstance;
};

/**
 * VegaLitePanel - Renders Vega-Lite charts from JSON spec
 *
 * Accepts content in format:
 * {
 *   format: "vega-lite",
 *   spec: { mark: "bar", encoding: {...}, data: {...} }  // or as JSON string
 * }
 *
 * Or array format from SQL:
 * [{ format: "vega-lite", spec: "..." }]
 *
 * @param {array|object} content - Chart content with spec
 * @param {function} onClick - Callback when a data point is clicked (receives datum)
 * @param {boolean} interactive - Whether chart is interactive (enables selection)
 * @param {*} selectedValue - Currently selected value (for toggle detection)
 * @param {string} selectField - Field name to match for selection
 */
const VegaLitePanel = ({ content, onClick, interactive, selectedValue, selectField }) => {
  const containerRef = useRef(null);
  const viewRef = useRef(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Debug: log props on render
  console.log('[VegaLitePanel] Render props:', { interactive, selectedValue, selectField });

  // Extract and parse the Vega-Lite spec
  const spec = useMemo(() => {
    try {
      let rawSpec;

      // Handle array format (from SQL result)
      if (Array.isArray(content) && content.length === 1) {
        rawSpec = content[0].spec;
      } else if (content && typeof content === 'object') {
        rawSpec = content.spec;
      }

      if (!rawSpec) {
        return null;
      }

      // Parse if string
      return typeof rawSpec === 'string' ? JSON.parse(rawSpec) : rawSpec;
    } catch (err) {
      setError(`Invalid Vega-Lite spec: ${err.message}`);
      return null;
    }
  }, [content]);

  // Dark theme config for Vega-Lite
  const darkConfig = useMemo(() => ({
    background: 'transparent',
    view: { stroke: 'transparent' },
    axis: {
      domainColor: '#334155',
      gridColor: '#1e293b',
      tickColor: '#64748b',
      labelColor: '#94a3b8',
      titleColor: '#cbd5e1',
      labelFont: "'Google Sans', sans-serif",
      titleFont: "'Google Sans', sans-serif",
    },
    legend: {
      labelColor: '#94a3b8',
      titleColor: '#cbd5e1',
      labelFont: "'Google Sans', sans-serif",
      titleFont: "'Google Sans', sans-serif",
    },
    title: {
      color: '#e2e8f0',
      font: "'Google Sans', sans-serif",
    },
    range: {
      category: ['#00e5ff', '#ff6b6b', '#4ade80', '#fbbf24', '#a78bfa', '#f472b6'],
    },
  }), []);

  useEffect(() => {
    if (!spec) {
      setLoading(false);
      return;
    }

    let resizeObserver = null;

    const renderChart = async () => {
      if (!containerRef.current) {
        setTimeout(renderChart, 10);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const vegaEmbed = await getVegaEmbed();

        // Get container dimensions
        const container = containerRef.current;
        const width = container.clientWidth || 400;
        const height = container.clientHeight || 300;

        // Merge spec with explicit dimensions
        const fullSpec = {
          $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
          width: width - 20,  // Padding for axes
          height: height - 40, // Padding for title/axes
          autosize: { type: 'fit', contains: 'padding' },
          ...spec,
          config: {
            ...darkConfig,
            ...spec.config,
          },
        };

        // Add point selection for interactivity if onClick is provided
        if (interactive && onClick) {
          fullSpec.params = [
            ...(fullSpec.params || []),
            {
              name: 'clickSelect',
              select: { type: 'point', on: 'click' },
            },
          ];
        }

        const result = await vegaEmbed(container, fullSpec, {
          actions: {
            export: true,
            source: false,
            compiled: false,
            editor: false,
          },
          renderer: 'svg',
        });

        // Store view reference for event handling
        viewRef.current = result.view;

        // Add click listener if interactive
        if (interactive && onClick) {
          result.view.addEventListener('click', (event, item) => {
            if (item && item.datum) {
              // Extract the data from the clicked mark
              const clickedData = { ...item.datum };
              // Remove internal Vega fields
              delete clickedData._vgsid_;

              // Debug: log click and selection state
              console.log('[VegaLitePanel] Click:', {
                clickedData,
                selectField,
                selectedValue,
                clickedFieldValue: selectField ? clickedData[selectField] : 'N/A'
              });

              // Check if this is a toggle-off (clicking already selected item)
              if (selectField && selectedValue !== null && selectedValue !== undefined) {
                const clickedFieldValue = String(clickedData[selectField]);
                console.log('[VegaLitePanel] Deselect check:', {
                  clickedFieldValue,
                  selectedValue: String(selectedValue),
                  match: clickedFieldValue === String(selectedValue)
                });
                if (clickedFieldValue === String(selectedValue)) {
                  // This is a deselect
                  console.log('[VegaLitePanel] Triggering deselect');
                  onClick({ ...clickedData, _isDeselect: true });
                  return;
                }
              }

              onClick(clickedData);
            }
          });
        }
      } catch (err) {
        console.error('Vega-Lite render error:', err);
        setError(err.message || 'Failed to render chart');
      } finally {
        setLoading(false);
      }
    };

    // Initial render with delay to ensure container has dimensions
    const timeoutId = setTimeout(renderChart, 50);

    // Re-render on resize
    resizeObserver = new ResizeObserver(() => {
      renderChart();
    });

    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      clearTimeout(timeoutId);
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      // Clean up view reference
      viewRef.current = null;
    };
  }, [spec, darkConfig, interactive, onClick, selectedValue, selectField]);

  if (error) {
    return (
      <div className="vega-panel-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
      </div>
    );
  }

  if (!spec && !loading) {
    return (
      <div className="vega-panel-error">
        <Icon icon="mdi:chart-box-outline" width="20" />
        <span>No chart data</span>
      </div>
    );
  }

  return (
    <div className={`vega-panel ${interactive ? 'vega-interactive' : ''}`}>
      {loading && (
        <div className="vega-panel-loading">
          <Icon icon="mdi:loading" width="24" className="spinning" />
          <span>Rendering chart...</span>
        </div>
      )}
      <div
        ref={containerRef}
        className="vega-panel-container"
        style={{ display: loading ? 'none' : 'block' }}
      />
    </div>
  );
};

export default VegaLitePanel;
