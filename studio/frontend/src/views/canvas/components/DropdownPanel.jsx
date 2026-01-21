import React, { useMemo, useCallback } from 'react';
import './DropdownPanel.css';

/**
 * DropdownPanel - Renders a dropdown select control for filtering
 *
 * SQL format (data-driven - each row is an option):
 * SELECT
 *   'dropdown' as format,
 *   category as value,     -- option value
 *   category as label      -- optional display label (defaults to value)
 * FROM (SELECT DISTINCT category FROM sales)
 *
 * Or with header row for metadata:
 * SELECT 'dropdown' as format, NULL as value, 'Select Category' as placeholder, 'Category' as label
 * UNION ALL
 * SELECT 'dropdown', category, NULL, category FROM ...
 *
 * @param {array} content - Array of rows, each representing an option
 * @param {function} onChange - Callback when selection changes
 * @param {boolean} interactive - Whether dropdown is interactive
 * @param {string} selectedValue - Current selected value (from param store)
 */
const DropdownPanel = ({ content, onChange, interactive = true, selectedValue }) => {
  // Extract dropdown config and options from content
  const { label, placeholder, options } = useMemo(() => {
    if (!Array.isArray(content) || content.length === 0) {
      return { label: null, placeholder: 'Select...', options: [] };
    }

    // Check if first row is a header/config row (has placeholder or null value)
    const firstRow = content[0];
    let configRow = null;
    let optionRows = content;

    if (firstRow.placeholder || firstRow.value === null || firstRow.value === undefined) {
      configRow = firstRow;
      optionRows = content.slice(1);
    }

    // Extract options from rows
    const opts = optionRows
      .filter(row => row.value !== null && row.value !== undefined)
      .map(row => ({
        value: row.value,
        label: row.label || row.value
      }));

    return {
      label: configRow?.label || firstRow?.title || null,
      placeholder: configRow?.placeholder || 'Select...',
      options: opts
    };
  }, [content]);

  // Handle selection change
  const handleChange = useCallback((e) => {
    if (!interactive || !onChange) return;

    const newValue = e.target.value;
    // If selecting placeholder (empty), treat as deselect
    if (newValue === '') {
      onChange({ value: null, _isDeselect: true });
    } else {
      onChange({ value: newValue });
    }
  }, [interactive, onChange]);

  // Determine current selection
  const currentValue = selectedValue !== undefined && selectedValue !== null
    ? String(selectedValue)
    : '';

  return (
    <div className="dropdown-panel">
      <div className="dropdown-panel-content">
        {label && (
          <div className="dropdown-panel-label">{label}</div>
        )}
        <div className="dropdown-panel-control">
          <select
            value={currentValue}
            onChange={handleChange}
            disabled={!interactive}
            className="dropdown-panel-select"
          >
            <option value="">{placeholder}</option>
            {options.map((opt, index) => (
              <option key={`${opt.value}_${index}`} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <div className="dropdown-panel-arrow">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
        </div>
        {currentValue && (
          <div className="dropdown-panel-selected">
            Selected: <span className="dropdown-panel-selected-value">{currentValue}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default DropdownPanel;
