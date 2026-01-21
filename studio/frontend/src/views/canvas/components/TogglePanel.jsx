import React, { useMemo, useCallback } from 'react';
import './TogglePanel.css';

/**
 * TogglePanel - Renders a toggle switch for boolean filtering
 *
 * SQL format:
 * SELECT
 *   'toggle' as format,
 *   true as value,              -- current/default value (true/false)
 *   'Include Archived' as label, -- label text
 *   'Show archived items' as description  -- optional description
 *
 * @param {array} content - Array with single row containing toggle config
 * @param {function} onChange - Callback when toggle changes
 * @param {boolean} interactive - Whether toggle is interactive
 * @param {boolean|string} selectedValue - Current selected value
 */
const TogglePanel = ({ content, onChange, interactive = true, selectedValue }) => {
  // Extract toggle config from content
  const config = useMemo(() => {
    if (Array.isArray(content) && content.length === 1) {
      return content[0];
    }
    if (content && typeof content === 'object' && !Array.isArray(content)) {
      return content;
    }
    return {};
  }, [content]);

  const {
    value: defaultValue = false,
    label,
    description,
    on_label: onLabel = 'On',
    off_label: offLabel = 'Off'
  } = config;

  // Determine current value - handle various truthy/falsy representations
  const isChecked = useMemo(() => {
    const val = selectedValue !== undefined && selectedValue !== null
      ? selectedValue
      : defaultValue;

    if (typeof val === 'boolean') return val;
    if (typeof val === 'string') {
      return val.toLowerCase() === 'true' || val === '1' || val.toLowerCase() === 'yes';
    }
    if (typeof val === 'number') return val !== 0;
    return Boolean(val);
  }, [selectedValue, defaultValue]);

  // Handle toggle change
  const handleChange = useCallback(() => {
    if (!interactive || !onChange) return;
    onChange({ value: !isChecked });
  }, [interactive, onChange, isChecked]);

  return (
    <div className="toggle-panel">
      <div className="toggle-panel-content">
        <div className="toggle-panel-main">
          <div className="toggle-panel-text">
            {label && <div className="toggle-panel-label">{label}</div>}
            {description && <div className="toggle-panel-description">{description}</div>}
          </div>

          <button
            type="button"
            role="switch"
            aria-checked={isChecked}
            onClick={handleChange}
            disabled={!interactive}
            className={`toggle-panel-switch ${isChecked ? 'toggle-panel-switch-on' : ''}`}
          >
            <span className="toggle-panel-switch-thumb" />
          </button>
        </div>

        <div className="toggle-panel-status">
          <span className={!isChecked ? 'toggle-panel-status-active' : ''}>{offLabel}</span>
          <span className="toggle-panel-status-divider">/</span>
          <span className={isChecked ? 'toggle-panel-status-active' : ''}>{onLabel}</span>
        </div>
      </div>
    </div>
  );
};

export default TogglePanel;
