import React, { useState, useMemo } from 'react';
import './DataTableSection.css';

/**
 * DataTableSection - Display tabular data with optional selection and sorting
 *
 * Supports:
 * - Column definitions with formatting
 * - Row selection (single/multiple)
 * - Sortable columns
 * - Striped rows
 * - Max height with scroll
 */
function DataTableSection({ spec, value, onChange }) {
  const [sortConfig, setSortConfig] = useState({
    key: spec.default_sort || null,
    direction: 'asc'
  });

  const columns = spec.columns || [];
  const data = spec.data || [];

  // Format cell value based on column format
  const formatValue = (val, format) => {
    if (val === null || val === undefined) return '-';

    switch (format) {
      case 'currency':
        if (typeof val === 'number') {
          return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
          }).format(val);
        }
        return val;

      case 'percent':
        if (typeof val === 'number') {
          return `${(val * 100).toFixed(1)}%`;
        }
        return val;

      case 'date':
        if (val) {
          return new Date(val).toLocaleDateString();
        }
        return val;

      case 'number':
        if (typeof val === 'number') {
          return val.toLocaleString();
        }
        return val;

      default:
        return String(val);
    }
  };

  // Sort data
  const sortedData = useMemo(() => {
    if (!sortConfig.key) return data;

    return [...data].sort((a, b) => {
      const aVal = a[sortConfig.key];
      const bVal = b[sortConfig.key];

      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      const comparison = aVal < bVal ? -1 : 1;
      return sortConfig.direction === 'asc' ? comparison : -comparison;
    });
  }, [data, sortConfig]);

  // Handle sort click
  const handleSort = (key) => {
    if (!spec.sortable) return;

    const column = columns.find(c => c.key === key);
    if (!column?.sortable && !spec.sortable) return;

    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  // Handle row selection
  const handleRowSelect = (rowIndex) => {
    if (!spec.selectable || !onChange) return;

    if (spec.selection_mode === 'multiple') {
      const currentSelected = value || [];
      const newSelected = currentSelected.includes(rowIndex)
        ? currentSelected.filter(i => i !== rowIndex)
        : [...currentSelected, rowIndex];
      onChange(newSelected);
    } else {
      onChange(rowIndex);
    }
  };

  const isRowSelected = (rowIndex) => {
    if (spec.selection_mode === 'multiple') {
      return (value || []).includes(rowIndex);
    }
    return value === rowIndex;
  };

  return (
    <div className="ui-section data-table-section">
      <div
        className="table-container"
        style={{ maxHeight: spec.max_height || 300 }}
      >
        <table className={`data-table ${spec.striped !== false ? 'striped' : ''} ${spec.compact ? 'compact' : ''}`}>
          <thead>
            <tr>
              {spec.show_row_numbers && (
                <th className="row-number-header">#</th>
              )}
              {spec.selectable && (
                <th className="select-header"></th>
              )}
              {columns.map((col, idx) => (
                <th
                  key={idx}
                  className={`
                    ${col.sortable || spec.sortable ? 'sortable' : ''}
                    ${sortConfig.key === col.key ? 'sorted' : ''}
                    align-${col.align || 'left'}
                  `}
                  style={{ width: col.width }}
                  onClick={() => handleSort(col.key)}
                >
                  <span className="th-content">
                    {col.label}
                    {(col.sortable || spec.sortable) && (
                      <span className="sort-indicator">
                        {sortConfig.key === col.key && (
                          sortConfig.direction === 'asc' ? ' ↑' : ' ↓'
                        )}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className={`
                  ${spec.selectable ? 'selectable' : ''}
                  ${isRowSelected(rowIdx) ? 'selected' : ''}
                `}
                onClick={() => handleRowSelect(rowIdx)}
              >
                {spec.show_row_numbers && (
                  <td className="row-number">{rowIdx + 1}</td>
                )}
                {spec.selectable && (
                  <td className="select-cell">
                    <input
                      type={spec.selection_mode === 'multiple' ? 'checkbox' : 'radio'}
                      checked={isRowSelected(rowIdx)}
                      onChange={() => {}}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                )}
                {columns.map((col, colIdx) => (
                  <td
                    key={colIdx}
                    className={`align-${col.align || 'left'}`}
                  >
                    {formatValue(row[col.key], col.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default DataTableSection;
