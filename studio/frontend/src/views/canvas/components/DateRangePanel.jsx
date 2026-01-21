import React, { useMemo, useCallback } from 'react';
import './DateRangePanel.css';

/**
 * DateRangePanel - Renders date range picker controls for time-based filtering
 *
 * SQL format:
 * SELECT
 *   'daterange' as format,
 *   '2024-01-01' as start,      -- start date (YYYY-MM-DD)
 *   '2024-03-31' as end,        -- end date (YYYY-MM-DD)
 *   'Date Range' as label,      -- optional label
 *   '2020-01-01' as min_date,   -- optional min constraint
 *   '2025-12-31' as max_date    -- optional max constraint
 *
 * Sets two params: {param}_start and {param}_end
 * Use ON_SELECT @param_set('daterange', *) to set both as JSON
 * Or use ON_SELECT @param_set('start', start) for just start date
 *
 * @param {array} content - Array with single row containing daterange config
 * @param {function} onChange - Callback when dates change
 * @param {boolean} interactive - Whether picker is interactive
 * @param {string} selectedValue - Current selected value (JSON string or start date)
 */
const DateRangePanel = ({ content, onChange, interactive = true, selectedValue }) => {
  // Extract daterange config from content
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
    start: defaultStart,
    end: defaultEnd,
    label,
    min_date: minDate,
    max_date: maxDate
  } = config;

  // Parse selected value - could be JSON object or just a date string
  const { currentStart, currentEnd } = useMemo(() => {
    if (selectedValue) {
      // Try parsing as JSON first
      if (typeof selectedValue === 'string' && selectedValue.startsWith('{')) {
        try {
          const parsed = JSON.parse(selectedValue);
          return {
            currentStart: parsed.start || defaultStart || '',
            currentEnd: parsed.end || defaultEnd || ''
          };
        } catch (e) {
          // Not JSON, treat as start date
        }
      }
      // If it's an object already
      if (typeof selectedValue === 'object' && selectedValue !== null) {
        return {
          currentStart: selectedValue.start || defaultStart || '',
          currentEnd: selectedValue.end || defaultEnd || ''
        };
      }
    }
    return {
      currentStart: defaultStart || '',
      currentEnd: defaultEnd || ''
    };
  }, [selectedValue, defaultStart, defaultEnd]);

  // Handle start date change
  const handleStartChange = useCallback((e) => {
    if (!interactive || !onChange) return;
    const newStart = e.target.value;
    onChange({ start: newStart, end: currentEnd });
  }, [interactive, onChange, currentEnd]);

  // Handle end date change
  const handleEndChange = useCallback((e) => {
    if (!interactive || !onChange) return;
    const newEnd = e.target.value;
    onChange({ start: currentStart, end: newEnd });
  }, [interactive, onChange, currentStart]);

  // Quick preset buttons
  const applyPreset = useCallback((preset) => {
    if (!interactive || !onChange) return;

    const today = new Date();
    let start, end;

    switch (preset) {
      case '7d':
        end = today.toISOString().split('T')[0];
        start = new Date(today.setDate(today.getDate() - 7)).toISOString().split('T')[0];
        break;
      case '30d':
        end = new Date().toISOString().split('T')[0];
        start = new Date(new Date().setDate(new Date().getDate() - 30)).toISOString().split('T')[0];
        break;
      case '90d':
        end = new Date().toISOString().split('T')[0];
        start = new Date(new Date().setDate(new Date().getDate() - 90)).toISOString().split('T')[0];
        break;
      case 'ytd':
        end = new Date().toISOString().split('T')[0];
        start = `${new Date().getFullYear()}-01-01`;
        break;
      case 'all':
        onChange({ start: null, end: null, _isDeselect: true });
        return;
      default:
        return;
    }

    onChange({ start, end });
  }, [interactive, onChange]);

  return (
    <div className="daterange-panel">
      <div className="daterange-panel-content">
        {label && (
          <div className="daterange-panel-label">{label}</div>
        )}

        <div className="daterange-panel-inputs">
          <div className="daterange-panel-field">
            <span className="daterange-panel-field-label">From</span>
            <input
              type="date"
              value={currentStart}
              onChange={handleStartChange}
              min={minDate}
              max={currentEnd || maxDate}
              disabled={!interactive}
              className="daterange-panel-input"
            />
          </div>

          <div className="daterange-panel-separator">→</div>

          <div className="daterange-panel-field">
            <span className="daterange-panel-field-label">To</span>
            <input
              type="date"
              value={currentEnd}
              onChange={handleEndChange}
              min={currentStart || minDate}
              max={maxDate}
              disabled={!interactive}
              className="daterange-panel-input"
            />
          </div>
        </div>

        <div className="daterange-panel-presets">
          <button onClick={() => applyPreset('7d')} disabled={!interactive}>7D</button>
          <button onClick={() => applyPreset('30d')} disabled={!interactive}>30D</button>
          <button onClick={() => applyPreset('90d')} disabled={!interactive}>90D</button>
          <button onClick={() => applyPreset('ytd')} disabled={!interactive}>YTD</button>
          <button onClick={() => applyPreset('all')} disabled={!interactive}>All</button>
        </div>
      </div>
    </div>
  );
};

export default DateRangePanel;
