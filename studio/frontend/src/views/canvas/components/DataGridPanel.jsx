import React from 'react';
import { Icon } from '@iconify/react';
import './DataGridPanel.css';

/**
 * DataGridPanel - Renders tabular data as a styled table
 *
 * Accepts an array of objects (records) and renders them as a table.
 */
const DataGridPanel = ({ content }) => {
  // Handle various content formats
  if (!content) {
    return (
      <div className="data-grid-empty">
        <Icon icon="mdi:table-off" width="24" />
        <span>No data</span>
      </div>
    );
  }

  // If content is not an array, try to handle it
  let data = content;
  if (!Array.isArray(data)) {
    // Single object - wrap in array
    if (typeof data === 'object' && data !== null) {
      data = [data];
    } else {
      return (
        <div className="data-grid-empty">
          <span>Invalid data format</span>
        </div>
      );
    }
  }

  if (data.length === 0) {
    return (
      <div className="data-grid-empty">
        <Icon icon="mdi:table-off" width="24" />
        <span>No rows</span>
      </div>
    );
  }

  // Extract columns from first row
  const columns = Object.keys(data[0]);

  // Format cell value for display
  const formatValue = (value) => {
    if (value === null || value === undefined) {
      return <span className="data-grid-null">null</span>;
    }
    if (typeof value === 'boolean') {
      return value ? 'true' : 'false';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    if (typeof value === 'number') {
      // Format numbers nicely
      if (Number.isInteger(value)) {
        return value.toLocaleString();
      }
      return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
    }
    return String(value);
  };

  return (
    <div className="data-grid-wrapper">
      <table className="data-grid-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {columns.map((col) => (
                <td key={col}>{formatValue(row[col])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="data-grid-footer">
        {data.length} row{data.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
};

export default DataGridPanel;
