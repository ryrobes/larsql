import React, { useState, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import { ROUTES } from '../../../routes.helpers';
import TrainingDetailPanel from './TrainingDetailPanel';
import './TrainingGrid.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching Console/Studio/Receipts
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
 * TrainingGrid - AG-Grid table for training examples
 * Supports multi-select, inline toggling, filtering
 */
const TrainingGrid = ({ examples = [], onSelectionChanged, onMarkTrainable }) => {
  const navigate = useNavigate();
  const gridRef = useRef(null);
  const [quickFilter, setQuickFilter] = useState('');
  const [selectedExample, setSelectedExample] = useState(null);

  // Handle row selection
  const handleSelectionChanged = useCallback(() => {
    if (!gridRef.current) return;
    const selected = gridRef.current.api.getSelectedRows();
    onSelectionChanged && onSelectionChanged(selected);
  }, [onSelectionChanged]);

  // Handle trainable toggle (inline click)
  const handleTrainableToggle = async (trace_id, currentValue) => {
    try {
      await fetch('http://localhost:5050/api/training/mark-trainable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_ids: [trace_id],
          trainable: !currentValue
        })
      });

      // Update local state optimistically
      if (gridRef.current) {
        const rowNode = gridRef.current.api.getRowNode(trace_id);
        if (rowNode) {
          rowNode.setDataValue('trainable', !currentValue);
        }
      }
    } catch (err) {
      console.error('Failed to toggle trainable:', err);
    }
  };

  // Handle verified toggle (inline click)
  const handleVerifiedToggle = async (trace_id, currentValue) => {
    try {
      await fetch('http://localhost:5050/api/training/mark-trainable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_ids: [trace_id],
          trainable: true,  // Must be trainable to be verified
          verified: !currentValue
        })
      });

      // Update local state optimistically
      if (gridRef.current) {
        const rowNode = gridRef.current.api.getRowNode(trace_id);
        if (rowNode) {
          rowNode.setDataValue('verified', !currentValue);
          rowNode.setDataValue('trainable', true);
        }
      }
    } catch (err) {
      console.error('Failed to toggle verified:', err);
    }
  };

  // Single click - show detail panel
  const handleRowClick = useCallback((event) => {
    const clickedExample = event.data;
    // Toggle selection - if clicking same row, deselect
    if (selectedExample?.trace_id === clickedExample.trace_id) {
      setSelectedExample(null);
    } else {
      setSelectedExample(clickedExample);
    }
  }, [selectedExample]);

  // Double click - navigate to session
  const handleRowDoubleClick = (event) => {
    const { session_id, cascade_id } = event.data;
    if (session_id && cascade_id) {
      navigate(ROUTES.studioWithSession(cascade_id, session_id));
    }
  };

  // Close detail panel
  const closeDetailPanel = useCallback(() => {
    setSelectedExample(null);
  }, []);

  const columnDefs = useMemo(() => [
    {
      field: 'trainable',
      headerName: 'Trainable',
      width: 100,
      checkboxSelection: false,
      cellRenderer: (params) => {
        const checked = params.value;
        return (
          <div
            className="training-toggle-cell"
            onClick={(e) => {
              e.stopPropagation();
              handleTrainableToggle(params.data.trace_id, checked);
            }}
          >
            <Icon
              icon={checked ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'}
              width={18}
              style={{ color: checked ? '#34d399' : '#475569', cursor: 'pointer' }}
            />
          </div>
        );
      }
    },
    {
      field: 'verified',
      headerName: 'Verified',
      width: 100,
      cellRenderer: (params) => {
        const checked = params.value;
        return (
          <div
            className="training-toggle-cell"
            onClick={(e) => {
              e.stopPropagation();
              handleVerifiedToggle(params.data.trace_id, checked);
            }}
          >
            <Icon
              icon={checked ? 'mdi:shield-check' : 'mdi:shield-outline'}
              width={18}
              style={{ color: checked ? '#a78bfa' : '#475569', cursor: 'pointer' }}
            />
          </div>
        );
      }
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      width: 180,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Icon icon="mdi:sitemap" width={12} style={{ color: '#60a5fa' }} />
          <span>{params.value}</span>
        </div>
      )
    },
    {
      field: 'cell_name',
      headerName: 'Cell',
      width: 140,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => (
        <span style={{ color: '#fbbf24', fontFamily: "'JetBrains Mono', monospace" }}>
          {params.value}
        </span>
      )
    },
    {
      field: 'user_input',
      headerName: 'Input',
      width: 300,
      filter: 'agTextColumnFilter',
      cellClass: 'training-text-cell',
      tooltipField: 'user_input',
      wrapText: false,
      autoHeight: false
    },
    {
      field: 'assistant_output',
      headerName: 'Output',
      width: 300,
      filter: 'agTextColumnFilter',
      cellClass: 'training-text-cell',
      tooltipField: 'assistant_output',
      wrapText: false,
      autoHeight: false,
      cellRenderer: (params) => {
        // Highlight boolean outputs
        const val = params.value;
        if (val === 'true' || val === 'false') {
          return (
            <span style={{
              color: val === 'true' ? '#34d399' : '#ff006e',
              fontWeight: 600
            }}>
              {val}
            </span>
          );
        }
        return val;
      }
    },
    {
      field: 'confidence',
      headerName: 'Confidence',
      width: 120,
      filter: 'agNumberColumnFilter',
      valueFormatter: (params) => params.value?.toFixed(2) || '0.00',
      cellRenderer: (params) => {
        const value = params.value || 0;
        const color = value >= 0.9 ? '#34d399' : value >= 0.7 ? '#fbbf24' : '#ff006e';
        return (
          <span style={{
            color,
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600
          }}>
            {value.toFixed(2)}
          </span>
        );
      }
    },
    {
      field: 'model',
      headerName: 'Model',
      width: 220,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => {
        if (!params.value) return '-';
        // Show just the model name (after /)
        const parts = params.value.split('/');
        const modelName = parts[parts.length - 1];
        return (
          <span style={{
            color: '#94a3b8',
            fontSize: '11px',
            fontFamily: "'JetBrains Mono', monospace"
          }}>
            {modelName}
          </span>
        );
      }
    },
    {
      field: 'cost',
      headerName: 'Cost',
      width: 100,
      filter: 'agNumberColumnFilter',
      valueFormatter: (params) => params.value ? `$${params.value.toFixed(4)}` : '$0.0000',
      cellRenderer: (params) => {
        const value = params.value || 0;
        return (
          <span style={{
            color: '#34d399',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '12px'
          }}>
            ${value.toFixed(4)}
          </span>
        );
      }
    },
    {
      field: 'timestamp',
      headerName: 'Time',
      width: 160,
      filter: 'agDateColumnFilter',
      valueFormatter: (params) => {
        if (!params.value) return '-';
        try {
          const date = new Date(params.value);
          return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
          });
        } catch {
          return params.value;
        }
      }
    },
    {
      field: 'caller_id',
      headerName: 'Caller',
      width: 180,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => {
        if (!params.value) return '-';
        const parts = params.value.split('-');
        const identifier = parts[parts.length - 1];
        return (
          <span style={{
            color: '#64748b',
            fontSize: '11px',
            fontFamily: "'JetBrains Mono', monospace"
          }}>
            {identifier}
          </span>
        );
      }
    }
  ], []);

  const defaultColDef = useMemo(() => ({
    sortable: true,
    resizable: true,
    filter: true,
    floatingFilter: false,  // Can enable for more filtering
  }), []);

  // Grid content (reusable whether in split or standalone)
  const gridContent = (
    <>
      {/* Quick Search Bar */}
      <div className="training-grid-toolbar">
        <div className="training-search-box">
          <Icon icon="mdi:magnify" width={14} style={{ color: '#64748b' }} />
          <input
            type="text"
            placeholder="Quick search..."
            value={quickFilter}
            onChange={(e) => setQuickFilter(e.target.value)}
            className="training-search-input"
          />
        </div>
        <div className="training-grid-info">
          <span>{examples.length} examples</span>
          {selectedExample && <span className="training-grid-hint">· Click row again to deselect</span>}
        </div>
      </div>

      {/* AG-Grid Table */}
      <div className="training-grid-wrapper">
        <AgGridReact
          ref={gridRef}
          theme={darkTheme}
          rowData={examples}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection="multiple"
          suppressRowClickSelection={true}
          onSelectionChanged={handleSelectionChanged}
          onRowClicked={handleRowClick}
          onRowDoubleClicked={handleRowDoubleClick}
          getRowId={(params) => params.data.trace_id}
          quickFilterText={quickFilter}
          animateRows={true}
          domLayout="normal"
          pagination={true}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 200, 500]}
          enableCellTextSelection={true}
          tooltipShowDelay={500}
        />
      </div>
    </>
  );

  return (
    <div className="training-grid-container">
      {selectedExample ? (
        /* Split view with detail panel */
        <Split
          className="training-split-container"
          direction="vertical"
          sizes={[60, 40]}
          minSize={[200, 150]}
          gutterSize={6}
          cursor="row-resize"
        >
          <div className="training-split-pane">
            {gridContent}
          </div>
          <div className="training-split-pane">
            <TrainingDetailPanel
              example={selectedExample}
              onClose={closeDetailPanel}
            />
          </div>
        </Split>
      ) : (
        /* Grid only - no detail panel */
        gridContent
      )}
    </div>
  );
};

export default TrainingGrid;
