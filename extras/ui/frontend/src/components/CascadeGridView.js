import React, { useState, useEffect, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import './CascadeGridView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Create dark theme for AG Grid (matching tile mode's darker aesthetic)
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#0b1219',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0f1821',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#0d1419',
  borderColor: '#1a2028',
  rowBorder: true,
  wrapperBorder: true,
  wrapperBorderRadius: 12,
  headerFontSize: 11,
  headerFontWeight: 700,
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", sans-serif',
  fontSize: 13,
  accentColor: '#2dd4bf',
  chromeBackgroundColor: '#080c12',
});

/**
 * Grid view for cascades using AG Grid
 * Features: sorting, filtering, expandable rows, virtualization
 */
function CascadeGridView({ cascades, onSelectCascade, searchQuery }) {
  const [gridApi, setGridApi] = useState(null);

  // Filter cascades based on search query
  const wildcardToRegex = (pattern) => {
    const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&');
    const withWildcards = escaped.replace(/\*/g, '.*').replace(/\?/g, '.');
    return new RegExp(withWildcards, 'i');
  };

  const filteredCascades = useMemo(() => {
    if (!searchQuery?.trim()) return cascades;

    const regex = wildcardToRegex(searchQuery.trim());
    return cascades.filter(cascade => {
      if (regex.test(cascade.cascade_id)) return true;
      if (cascade.description && regex.test(cascade.description)) return true;
      if (cascade.phases?.some(p => regex.test(p.name))) return true;
      return false;
    });
  }, [cascades, searchQuery]);

  // Format helper functions
  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0.00';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  // Custom cell renderers (React components)
  const CascadeIdRenderer = (props) => {
    const hasRuns = props.data.metrics?.run_count > 0;
    return (
      <div className="cascade-id-wrapper">
        <span className="cascade-id-text">{props.value}</span>
        {!hasRuns && <span className="no-runs-badge">No Runs</span>}
      </div>
    );
  };

  const PhasesCellRenderer = (props) => {
    const soundingsCount = props.data.phases?.filter(p => p.has_soundings).length || 0;
    const reforgesCount = props.data.phases?.filter(p => p.reforge_steps).length || 0;
    const wardsCount = props.data.phases?.reduce((sum, p) => sum + (p.ward_count || 0), 0) || 0;

    return (
      <div className="phases-cell-content">
        <span className="phase-count">{props.value}</span>
        {soundingsCount > 0 && (
          <span className="phase-badge soundings" title="Soundings">
            🧠 {soundingsCount}
          </span>
        )}
        {reforgesCount > 0 && (
          <span className="phase-badge reforges" title="Reforges">
            🔨 {reforgesCount}
          </span>
        )}
        {wardsCount > 0 && (
          <span className="phase-badge wards" title="Wards">
            🛡️ {wardsCount}
          </span>
        )}
      </div>
    );
  };

  const ActionButtonRenderer = (props) => {
    const handleClick = (e) => {
      e.stopPropagation();
      onSelectCascade(props.data.cascade_id, props.data);
    };

    return (
      <button className="view-btn" onClick={handleClick}>
        View Details →
      </button>
    );
  };

  // Column definitions
  const columnDefs = useMemo(() => [
    {
      field: 'cascade_id',
      headerName: 'Cascade ID',
      flex: 2,
      minWidth: 200,
      cellClass: 'cascade-id-cell',
      cellRenderer: CascadeIdRenderer
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 3,
      minWidth: 250,
      cellClass: 'description-cell',
      valueFormatter: (params) => params.value || '—',
      wrapText: true,
      autoHeight: true
    },
    {
      field: 'phases',
      headerName: 'Phases',
      width: 180,
      cellClass: 'center-cell',
      valueGetter: (params) => params.data.phases?.length || 0,
      cellRenderer: PhasesCellRenderer
    },
    {
      field: 'metrics.run_count',
      headerName: 'Runs',
      width: 90,
      cellClass: 'center-cell',
      valueFormatter: (params) => params.value || 0
    },
    {
      field: 'metrics.total_cost',
      headerName: 'Total Cost',
      width: 120,
      cellClass: 'cost-cell',
      valueFormatter: (params) => formatCost(params.value)
    },
    {
      field: 'avg_cost',
      headerName: 'Avg Cost',
      width: 120,
      cellClass: 'cost-cell',
      valueGetter: (params) => {
        const runs = params.data.metrics?.run_count || 0;
        const total = params.data.metrics?.total_cost || 0;
        return runs > 0 ? total / runs : 0;
      },
      valueFormatter: (params) => formatCost(params.value)
    },
    {
      field: 'metrics.avg_duration_seconds',
      headerName: 'Avg Duration',
      width: 130,
      cellClass: 'center-cell',
      valueFormatter: (params) => formatDuration(params.value)
    },
    {
      field: 'actions',
      headerName: '',
      width: 120,
      sortable: false,
      filter: false,
      cellClass: 'actions-cell',
      cellRenderer: ActionButtonRenderer
    }
  ], [onSelectCascade]);

  // Default column settings
  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    suppressMovable: false,
  }), []);

  // Grid ready handler
  const onGridReady = (params) => {
    setGridApi(params.api);
    params.api.sizeColumnsToFit();
  };

  // Handle cell clicks (for action buttons and row clicks)
  const onCellClicked = (event) => {
    // Check if clicked element is the view button
    if (event.event.target.classList.contains('view-btn')) {
      const cascadeId = event.event.target.getAttribute('data-cascade-id');
      const cascade = cascades.find(c => c.cascade_id === cascadeId);
      if (cascade) {
        onSelectCascade(cascade.cascade_id, cascade);
      }
      return;
    }

    // Otherwise, clicking anywhere on the row opens it
    if (event.data) {
      onSelectCascade(event.data.cascade_id, event.data);
    }
  };

  // Row styling based on state
  const getRowStyle = (params) => {
    const hasRuns = params.data.metrics?.run_count > 0;
    if (!hasRuns) {
      return { opacity: 0.6 };
    }
    return null;
  };

  // Auto-size columns when window resizes
  useEffect(() => {
    const handleResize = () => {
      if (gridApi) {
        gridApi.sizeColumnsToFit();
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [gridApi]);

  return (
    <div className="cascade-grid-container">
      <div className="cascade-grid">
        <AgGridReact
          theme={darkTheme}
          rowData={filteredCascades}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          onGridReady={onGridReady}
          onCellClicked={onCellClicked}
          rowHeight={60}
          headerHeight={50}
          animateRows={true}
          getRowStyle={getRowStyle}
          enableCellTextSelection={true}
          ensureDomOrder={true}
          rowSelection={{
            mode: 'singleRow',
            enableClickSelection: false
          }}
        />
      </div>
    </div>
  );
}

export default CascadeGridView;
