import React, { useRef, useEffect, useState } from 'react';
import './MetricPanel.css';

/**
 * MetricPanel - Renders a single value as a large metric display
 *
 * Supports two modes:
 * 1. Auto-metric: Just a value, rendered as large as possible to fit container
 * 2. Explicit metric: Rich formatting with label, prefix, suffix, color, etc.
 *
 * Explicit metric format:
 * {
 *   format: "metric",
 *   value: 12345,
 *   label: "Total Revenue",     // optional subtitle
 *   value_format: "currency",   // optional: number|currency|percent|compact
 *   prefix: "$",                // optional
 *   suffix: "M",                // optional
 *   decimals: 2,                // optional
 *   color: "#00e5ff"            // optional accent color
 * }
 *
 * @param {any} content - The metric content (value or formatted object)
 * @param {boolean} isAuto - Whether this is auto-detected (single value) vs explicit
 */
const MetricPanel = ({ content, isAuto = false }) => {
  const containerRef = useRef(null);
  const valueRef = useRef(null);
  const [fontSize, setFontSize] = useState(48);

  // Extract metric data from content
  const metricData = React.useMemo(() => {
    if (isAuto) {
      // Auto-metric: content is the raw value
      return { value: content };
    }

    // Explicit metric: content is array with metric object
    if (Array.isArray(content) && content.length === 1) {
      return content[0];
    }

    // Direct object
    if (content && typeof content === 'object') {
      return content;
    }

    return { value: content };
  }, [content, isAuto]);

  const {
    value,
    label,
    value_format: valueFormat,
    prefix = '',
    suffix = '',
    decimals,
    color
  } = metricData;

  // Format the value based on value_format option
  const formattedValue = React.useMemo(() => {
    if (value === null || value === undefined) {
      return 'N/A';
    }

    const numValue = typeof value === 'number' ? value : parseFloat(value);

    if (isNaN(numValue)) {
      // Not a number, return as string
      return String(value);
    }

    const decimalPlaces = decimals !== undefined ? decimals :
      (valueFormat === 'currency' ? 2 :
       valueFormat === 'percent' ? 1 : 0);

    switch (valueFormat) {
      case 'currency':
        return numValue.toLocaleString(undefined, {
          minimumFractionDigits: decimalPlaces,
          maximumFractionDigits: decimalPlaces
        });

      case 'percent':
        return (numValue * 100).toLocaleString(undefined, {
          minimumFractionDigits: decimalPlaces,
          maximumFractionDigits: decimalPlaces
        }) + '%';

      case 'compact':
        if (Math.abs(numValue) >= 1e9) {
          return (numValue / 1e9).toLocaleString(undefined, {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
          }) + 'B';
        }
        if (Math.abs(numValue) >= 1e6) {
          return (numValue / 1e6).toLocaleString(undefined, {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
          }) + 'M';
        }
        if (Math.abs(numValue) >= 1e3) {
          return (numValue / 1e3).toLocaleString(undefined, {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
          }) + 'K';
        }
        return numValue.toLocaleString();

      case 'number':
      default:
        if (decimals !== undefined) {
          return numValue.toLocaleString(undefined, {
            minimumFractionDigits: decimalPlaces,
            maximumFractionDigits: decimalPlaces
          });
        }
        return numValue.toLocaleString();
    }
  }, [value, valueFormat, decimals]);

  // Auto-size the font to fit the container
  // Uses "measure at reference size, then scale" approach for reliability
  useEffect(() => {
    const fitText = () => {
      if (!containerRef.current || !valueRef.current) return;

      const container = containerRef.current;
      const valueEl = valueRef.current;

      // Get available space (with padding)
      const availableWidth = container.clientWidth - 42;
      const availableHeight = container.clientHeight - (label ? 60 : 32);

      if (availableWidth <= 0 || availableHeight <= 0) return;

      // Set to reference size and measure
      const referenceSize = 60;
      valueEl.style.fontSize = `${referenceSize}px`;

      // Force reflow to get accurate measurements
      const textWidth = valueEl.scrollWidth;
      const textHeight = valueEl.scrollHeight;

      if (textWidth === 0 || textHeight === 0) return;

      // Calculate scale factors
      const scaleX = availableWidth / textWidth;
      const scaleY = availableHeight / textHeight;
      const scale = Math.min(scaleX, scaleY);

      // Calculate optimal font size, clamped to reasonable bounds
      const optimalSize = Math.max(16, Math.min(100, Math.floor(referenceSize * scale)));

      setFontSize(optimalSize);
    };

    // Delay initial fit to ensure DOM is ready
    const timeoutId = setTimeout(fitText, 10);

    // Re-fit on resize
    const resizeObserver = new ResizeObserver(() => {
      // Debounce resize events
      setTimeout(fitText, 10);
    });

    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      clearTimeout(timeoutId);
      resizeObserver.disconnect();
    };
  }, [formattedValue, prefix, suffix, label]);

  const displayValue = `${prefix}${formattedValue}${suffix}`;

  return (
    <div
      ref={containerRef}
      className="metric-panel"
      style={{ '--metric-color': color || '#00e5ff' }}
    >
      <div className="metric-panel-content">
        <div
          ref={valueRef}
          className="metric-panel-value"
          style={{ fontSize: `${fontSize}px` }}
        >
          {displayValue}
        </div>
        {label && (
          <div className="metric-panel-label">
            {label}
          </div>
        )}
      </div>
    </div>
  );
};

export default MetricPanel;
