import React, { useMemo, useCallback, useRef, useEffect } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import './DataGridPanel.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching rest of application
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#000000',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0a0510',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#050410',
  borderColor: '#1a1628',
  rowBorder: true,
  wrapperBorder: false,
  headerFontSize: 12,
  headerFontWeight: 600,
  fontFamily: "'Google Sans Code', monospace",
  fontSize: 13,
  accentColor: '#00e5ff',
  chromeBackgroundColor: '#000000',
});

/**
 * DataGridPanel - Renders tabular data using AG Grid
 *
 * Accepts an array of objects (records) and renders them in a grid.
 *
 * @param {array} content - Array of row objects to display
 * @param {function} onRowClick - Callback when a row is clicked (receives row data)
 * @param {boolean} interactive - Whether the grid is interactive (shows hover states)
 * @param {boolean} multiSelect - Whether to enable checkbox multi-select mode
 * @param {array} selectedValues - Array of values currently selected (for multi-select)
 * @param {string} selectedValue - Single value currently selected (for single-select)
 * @param {string} selectField - Field name to match for selection highlighting
 */
const DataGridPanel = ({ content, onRowClick, interactive, multiSelect, selectedValues, selectedValue, selectField }) => {
  const gridRef = useRef(null);
  const gridApiRef = useRef(null);
  // Track selection state for detecting individual toggles
  const lastSelectionRef = useRef(new Set());
  // Flag to prevent event emission during initialization
  const isInitializingRef = useRef(false);

  // Normalize content to array
  const data = useMemo(() => {
    if (!content) return null;
    if (Array.isArray(content)) return content;
    if (typeof content === 'object' && content !== null) return [content];
    return null;
  }, [content]);

  // Extract columns from first row
  const columns = useMemo(() => {
    if (!data || data.length === 0) return [];
    return Object.keys(data[0]);
  }, [data]);

  // Generate column definitions
  const columnDefs = useMemo(() => {
    const dataCols = columns.map((col, index) => {
      const colDef = {
        field: col,
        headerName: col,
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 100,
        cellRenderer: (params) => {
          const value = params.value;
          if (value === null || value === undefined) {
            return <span className="data-grid-null">NULL</span>;
          }
          if (typeof value === 'object') {
            return <span className="data-grid-json">{JSON.stringify(value)}</span>;
          }
          if (typeof value === 'boolean') {
            return value ? 'true' : 'false';
          }
          if (typeof value === 'number') {
            if (Number.isInteger(value)) {
              return value.toLocaleString();
            }
            return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
          }
          return String(value);
        }
      };

      // Add checkbox to first column for multi-select mode
      if (index === 0 && multiSelect) {
        colDef.checkboxSelection = true;
        colDef.headerCheckboxSelection = true;
      }

      return colDef;
    });

    return dataCols;
  }, [columns, multiSelect]);

  // Default column definition
  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    minWidth: 80,
    flex: 1,  // Columns expand to fill available width
  }), []);

  // Store grid API when ready
  const onGridReady = useCallback((params) => {
    // Store API ref for use in useEffect
    gridApiRef.current = params.api;
  }, []);

  // Auto-size columns on first render
  const onFirstDataRendered = useCallback((params) => {
    params.api.autoSizeAllColumns();

    // Trigger initial selection sync now that data is rendered
    if (multiSelect && selectedValues && selectedValues.length > 0 && selectField) {
      isInitializingRef.current = true;

      const selectedSet = new Set(selectedValues.map(v => String(v)));
      const newSelection = new Set();

      params.api.forEachNode((node) => {
        const fieldValue = String(node.data[selectField]);
        if (selectedSet.has(fieldValue)) {
          node.setSelected(true);
          newSelection.add(JSON.stringify(node.data));
        }
      });

      lastSelectionRef.current = newSelection;

      setTimeout(() => {
        isInitializingRef.current = false;
      }, 0);
    }

    // Single-select: highlight the selected row
    if (!multiSelect && selectedValue !== null && selectedValue !== undefined && selectField) {
      params.api.forEachNode((node) => {
        const fieldValue = String(node.data[selectField]);
        if (fieldValue === String(selectedValue)) {
          node.setSelected(true);
        }
      });
    }
  }, [multiSelect, selectedValues, selectedValue, selectField]);

  // Handle row click (single-select mode)
  const handleRowClicked = useCallback((event) => {
    if (onRowClick && !multiSelect) {
      // Check if clicking the already-selected row (toggle off)
      if (selectField && selectedValue !== null && selectedValue !== undefined) {
        const clickedValue = String(event.data[selectField]);
        if (clickedValue === String(selectedValue)) {
          // This is a deselect - pass flag to handler
          onRowClick({ ...event.data, _isDeselect: true });
          return;
        }
      }
      onRowClick(event.data);
    }
  }, [onRowClick, multiSelect, selectField, selectedValue]);

  // Handle checkbox selection change (multi-select mode)
  // Detects which row was toggled and emits just that row
  const handleSelectionChanged = useCallback((event) => {
    if (!onRowClick || !multiSelect) return;
    // Skip during initialization to prevent cascading events
    if (isInitializingRef.current) return;

    const selectedNodes = event.api.getSelectedNodes();
    const currentSelection = new Set(selectedNodes.map(n => JSON.stringify(n.data)));
    const lastSelection = lastSelectionRef.current;

    // Find the row that was toggled
    // Check for newly selected rows
    for (const node of selectedNodes) {
      const key = JSON.stringify(node.data);
      if (!lastSelection.has(key)) {
        // This row was just selected - emit it
        onRowClick(node.data);
        lastSelectionRef.current = currentSelection;
        return;
      }
    }

    // Check for deselected rows (row was in lastSelection but not in current)
    for (const key of lastSelection) {
      if (!currentSelection.has(key)) {
        // This row was just deselected - emit it (for toggle-off)
        onRowClick(JSON.parse(key));
        lastSelectionRef.current = currentSelection;
        return;
      }
    }

    lastSelectionRef.current = currentSelection;
  }, [onRowClick, multiSelect]);

  // Determine row selection mode (must be before early returns)
  // Use string format for broader compatibility with AG Grid community
  const rowSelectionMode = useMemo(() => {
    if (!interactive) return undefined;
    return multiSelect ? 'multiple' : 'single';
  }, [interactive, multiSelect]);

  // Sync selection when selectedValues or data changes (after initial render)
  // We need to re-apply selection when data refreshes, even if selectedValues is unchanged
  useEffect(() => {
    if (!multiSelect || !selectField || !gridApiRef.current) return;

    // Set flag to prevent cascading events
    isInitializingRef.current = true;

    const api = gridApiRef.current;
    const selectedSet = new Set((selectedValues || []).map(v => String(v)));
    const newSelection = new Set();

    // Update selection state for all nodes
    api.forEachNode((node) => {
      const fieldValue = String(node.data[selectField]);
      const shouldBeSelected = selectedSet.has(fieldValue);
      const isSelected = node.isSelected();

      if (shouldBeSelected !== isSelected) {
        node.setSelected(shouldBeSelected);
      }

      if (shouldBeSelected) {
        newSelection.add(JSON.stringify(node.data));
      }
    });

    // Update lastSelectionRef
    lastSelectionRef.current = newSelection;

    // Clear flag after events settle
    setTimeout(() => {
      isInitializingRef.current = false;
    }, 0);
  }, [selectedValues, selectField, multiSelect, data]);

  // Sync selection when selectedValue or data changes (single-select mode)
  // We need to re-apply selection when data refreshes, even if selectedValue is unchanged
  useEffect(() => {
    if (multiSelect || !selectField || !gridApiRef.current) return;

    const api = gridApiRef.current;

    // Update selection state for all nodes
    api.forEachNode((node) => {
      const fieldValue = String(node.data[selectField]);
      const shouldBeSelected = selectedValue !== null && selectedValue !== undefined &&
        fieldValue === String(selectedValue);
      const isSelected = node.isSelected();

      if (shouldBeSelected !== isSelected) {
        node.setSelected(shouldBeSelected);
      }
    });
  }, [selectedValue, selectField, multiSelect, data]);

  // Empty/invalid states
  if (!data) {
    return (
      <div className="data-grid-empty">
        <Icon icon="mdi:table-off" width="24" />
        <span>No data</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="data-grid-empty">
        <Icon icon="mdi:table-off" width="24" />
        <span>No rows</span>
      </div>
    );
  }

  return (
    <div className={`data-grid-wrapper ${interactive ? 'data-grid-interactive' : ''} ${multiSelect ? 'data-grid-multiselect' : ''}`}>
      <div className="data-grid-container">
        <AgGridReact
          ref={gridRef}
          rowData={data}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          theme={darkTheme}
          animateRows={false}
          onGridReady={onGridReady}
          onFirstDataRendered={onFirstDataRendered}
          onRowClicked={interactive && !multiSelect ? handleRowClicked : undefined}
          onSelectionChanged={multiSelect ? handleSelectionChanged : undefined}
          enableCellTextSelection={!interactive}
          ensureDomOrder={true}
          rowSelection={rowSelectionMode}
          suppressRowClickSelection={multiSelect}
          rowStyle={interactive && !multiSelect ? { cursor: 'pointer' } : undefined}
          domLayout={data.length <= 10 ? 'autoHeight' : 'normal'}
          pagination={data.length > 100}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 500]}
        />
      </div>
      <div className="data-grid-footer">
        {data.length} row{data.length !== 1 ? 's' : ''}
        {interactive && !multiSelect && <span className="data-grid-interactive-hint">Click to select</span>}
        {multiSelect && <span className="data-grid-interactive-hint">Select with checkboxes</span>}
      </div>
    </div>
  );
};

export default DataGridPanel;
