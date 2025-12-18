import React, { useMemo, useCallback, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import useSqlQueryStore from '../stores/sqlQueryStore';
import './QueryResultsGrid.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Create dark theme for AG Grid
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#0b1219',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0f1821',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#0d1419',
  borderColor: '#1a2028',
  rowBorder: true,
  wrapperBorder: false,
  headerFontSize: 12,
  headerFontWeight: 600,
  fontFamily: "'IBM Plex Mono', 'Monaco', monospace",
  fontSize: 13,
  accentColor: '#2dd4bf',
  chromeBackgroundColor: '#080c12',
});

function QueryResultsGrid() {
  const gridRef = useRef(null);
  const { tabs, activeTabId } = useSqlQueryStore();

  const activeTab = tabs.find(t => t.id === activeTabId);
  const results = activeTab?.results;
  const error = activeTab?.error;
  const isRunning = activeTab?.isRunning;

  // Generate column definitions from results
  const columnDefs = useMemo(() => {
    if (!results?.columns) return [];

    return results.columns.map((col, idx) => ({
      field: `col_${idx}`,
      headerName: col,
      sortable: true,
      filter: true,
      resizable: true,
      minWidth: 100,
      flex: 1,
      cellRenderer: (params) => {
        const value = params.value;
        if (value === null || value === undefined) {
          return <span className="null-value">NULL</span>;
        }
        if (typeof value === 'object') {
          return <span className="json-value">{JSON.stringify(value)}</span>;
        }
        return value;
      }
    }));
  }, [results?.columns]);

  // Transform row data for AG Grid
  // API returns rows as objects: [{col1: val1, col2: val2}, ...]
  const rowData = useMemo(() => {
    if (!results?.rows || !results?.columns) return [];

    return results.rows.map((row, rowIdx) => {
      const rowObj = { _rowIndex: rowIdx };
      results.columns.forEach((col, colIdx) => {
        // Access by column name (API returns row objects, not arrays)
        rowObj[`col_${colIdx}`] = row[col];
      });
      return rowObj;
    });
  }, [results]);

  // Default column definition
  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    minWidth: 80,
  }), []);

  // Export to CSV
  const handleExportCsv = useCallback(() => {
    if (gridRef.current?.api) {
      gridRef.current.api.exportDataAsCsv({
        fileName: `query_results_${new Date().toISOString().slice(0, 10)}.csv`
      });
    }
  }, []);

  // Auto-size columns on first data load
  const onFirstDataRendered = useCallback((params) => {
    params.api.autoSizeAllColumns();
  }, []);

  // Loading state
  if (isRunning) {
    return (
      <div className="query-results-container">
        <div className="query-results-status">
          <Icon icon="mdi:loading" className="spin" />
          <span>Executing query...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="query-results-container">
        <div className="query-results-error">
          <div className="query-results-error-header">
            <Icon icon="mdi:alert-circle" />
            <span>Query Error</span>
          </div>
          <pre className="query-results-error-message">{error}</pre>
        </div>
      </div>
    );
  }

  // Empty state
  if (!results) {
    return (
      <div className="query-results-container">
        <div className="query-results-empty">
          <Icon icon="mdi:database-search" />
          <span>Run a query to see results</span>
          <span className="query-results-hint">Press Ctrl+Enter to execute</span>
        </div>
      </div>
    );
  }

  // No rows returned
  if (results.rows?.length === 0) {
    return (
      <div className="query-results-container">
        <div className="query-results-toolbar">
          <span className="query-results-info">
            <Icon icon="mdi:table" />
            0 rows returned
          </span>
        </div>
        <div className="query-results-empty">
          <Icon icon="mdi:table-off" />
          <span>Query returned no results</span>
        </div>
      </div>
    );
  }

  return (
    <div className="query-results-container">
      {/* Toolbar */}
      <div className="query-results-toolbar">
        <span className="query-results-info">
          <Icon icon="mdi:table-row" />
          {results.rows?.length || 0} rows
          {results.rows?.length >= 1000 && (
            <span className="query-results-truncated">(limited)</span>
          )}
        </span>

        <div className="query-results-actions">
          <button
            className="query-results-export-btn"
            onClick={handleExportCsv}
            title="Export to CSV"
          >
            <Icon icon="mdi:download" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="query-results-grid">
        <AgGridReact
          ref={gridRef}
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          theme={darkTheme}
          animateRows={false}
          onFirstDataRendered={onFirstDataRendered}
          enableCellTextSelection={true}
          ensureDomOrder={true}
          suppressRowClickSelection={true}
          pagination={rowData.length > 100}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 500, 1000]}
        />
      </div>
    </div>
  );
}

export default QueryResultsGrid;
