import React, { useMemo, useCallback } from 'react';
import './SliderPanel.css';

/**
 * SliderPanel - Renders a slider control for numeric filtering
 *
 * SQL format:
 * SELECT
 *   'slider' as format,
 *   50 as value,        -- current value
 *   0 as min,           -- minimum
 *   100 as max,         -- maximum
 *   1 as step,          -- optional step (default 1)
 *   'Price Range' as label  -- optional label
 *
 * @param {array} content - Array with single row containing slider config
 * @param {function} onChange - Callback when slider value changes
 * @param {boolean} interactive - Whether slider is interactive
 * @param {number} selectedValue - Current selected value (from param store)
 */
const SliderPanel = ({ content, onChange, interactive = true, selectedValue }) => {
  // Extract slider config from content
  const sliderConfig = useMemo(() => {
    if (Array.isArray(content) && content.length === 1) {
      return content[0];
    }
    if (content && typeof content === 'object' && !Array.isArray(content)) {
      return content;
    }
    return {};
  }, [content]);

  const {
    value: defaultValue = 50,
    min = 0,
    max = 100,
    step = 1,
    label,
    prefix = '',
    suffix = '',
    color
  } = sliderConfig;

  // Use selectedValue from param store if available, otherwise use default
  const currentValue = selectedValue !== undefined && selectedValue !== null
    ? Number(selectedValue)
    : Number(defaultValue);

  // Calculate percentage for gradient fill
  const percentage = ((currentValue - min) / (max - min)) * 100;

  // Handle slider change
  const handleChange = useCallback((e) => {
    if (!interactive || !onChange) return;

    const newValue = step % 1 === 0 ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
    onChange({ value: newValue });
  }, [interactive, onChange, step]);

  // Format display value
  const displayValue = `${prefix}${currentValue.toLocaleString()}${suffix}`;

  return (
    <div className="slider-panel" style={{ '--slider-color': color || '#00e5ff' }}>
      <div className="slider-panel-content">
        {label && (
          <div className="slider-panel-label">{label}</div>
        )}
        <div className="slider-panel-value">{displayValue}</div>
        <div className="slider-panel-control">
          <span className="slider-panel-bound">{prefix}{min.toLocaleString()}{suffix}</span>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={currentValue}
            onChange={handleChange}
            disabled={!interactive}
            className="slider-panel-input"
            style={{
              '--slider-percentage': `${percentage}%`
            }}
          />
          <span className="slider-panel-bound">{prefix}{max.toLocaleString()}{suffix}</span>
        </div>
      </div>
    </div>
  );
};

export default SliderPanel;
