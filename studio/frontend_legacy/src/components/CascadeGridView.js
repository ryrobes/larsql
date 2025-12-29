import React, { useState, useEffect, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
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
function CascadeGridView({ cascades, onSelectCascade, onVisualize, searchQuery }) {
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
      if (cascade.cells?.some(p => regex.test(p.name))) return true;
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

  // Format relative time (e.g., "2 days ago", "12 mins ago")
  const formatRelativeTime = (isoDate) => {
    if (!isoDate) return '—';

    const now = new Date();
    const then = new Date(isoDate);
    const diffMs = now - then;

    if (diffMs < 0) return 'just now';

    const seconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    const weeks = Math.floor(days / 7);
    const months = Math.floor(days / 30);

    // Round to most significant unit only
    if (months > 0) {
      return `${months} mo ago`;
    } else if (weeks > 0) {
      return `${weeks}w ago`;
    } else if (days > 0) {
      const remainingHours = hours % 24;
      if (remainingHours > 0 && days < 7) {
        return `${days}d ${remainingHours}h ago`;
      }
      return `${days}d ago`;
    } else if (hours > 0) {
      const remainingMins = minutes % 60;
      if (remainingMins > 0 && hours < 12) {
        return `${hours}h ${remainingMins}m ago`;
      }
      return `${hours}h ago`;
    } else if (minutes > 0) {
      return `${minutes}m ago`;
    } else {
      return 'just now';
    }
  };

  // Helper to get relative path (strips common prefixes)
  const getRelativePath = (fullPath) => {
    if (!fullPath) return null;
    // Try to find common directory markers and show path from there
    const markers = ['/examples/', '/cascades/', '/tackle/', '/windlass/'];
    for (const marker of markers) {
      const idx = fullPath.lastIndexOf(marker);
      if (idx !== -1) {
        return fullPath.substring(idx + 1); // +1 to skip the leading slash
      }
    }
    // Fallback: just show the filename
    return fullPath.split('/').pop();
  };

  // Custom cell renderers (React components)
  const CascadeIdRenderer = (props) => {
    const hasRuns = props.data.metrics?.run_count > 0;
    const cascadeFile = props.data.cascade_file;
    const relativePath = getRelativePath(cascadeFile);
    const isYaml = cascadeFile?.endsWith('.yaml') || cascadeFile?.endsWith('.yml');
    return (
      <div className="cascade-id-wrapper">
        <div className="cascade-id-row">
          <span className="cascade-id-text">{props.value}</span>
          {isYaml && <span className="yaml-badge">YAML</span>}
          {!hasRuns && <span className="no-runs-badge">No Runs</span>}
        </div>
        {relativePath && (
          <span className="cascade-file-path" title={cascadeFile}>{relativePath}</span>
        )}
      </div>
    );
  };

  const PhasesCellRenderer = (props) => {
    const soundingsCount = props.data.cells?.filter(p => p.has_soundings).length || 0;
    const reforgesCount = props.data.cells?.filter(p => p.reforge_steps).length || 0;
    const wardsCount = props.data.cells?.reduce((sum, p) => sum + (p.ward_count || 0), 0) || 0;

    return (
      <div className="phases-cell-content">
        <span className="phase-count">{props.value}</span>
        {soundingsCount > 0 && (
          <span className="phase-badge soundings" title="Soundings">
            <Icon icon="mdi:brain" width="14" style={{ marginRight: '4px' }} />{soundingsCount}
          </span>
        )}
        {reforgesCount > 0 && (
          <span className="phase-badge reforges" title="Reforges">
            <Icon icon="mdi:hammer" width="14" style={{ marginRight: '4px' }} />{reforgesCount}
          </span>
        )}
        {wardsCount > 0 && (
          <span className="phase-badge wards" title="Wards">
            <Icon icon="mdi:shield" width="14" style={{ marginRight: '4px' }} />{wardsCount}
          </span>
        )}
      </div>
    );
  };

  // Actions cell renderer with Visualize button
  const ActionsCellRenderer = (props) => {
    const handleVisualize = (e) => {
      e.stopPropagation(); // Don't trigger row click
      if (onVisualize) {
        onVisualize(props.data);
      }
    };

    return (
      <div className="actions-cell">
        <button
          className="action-btn visualize-btn"
          onClick={handleVisualize}
          title="Visualize cascade flow"
        >
          <Icon icon="ph:tree-structure" width="16" />
          <span>Flow</span>
        </button>
      </div>
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
      valueGetter: (params) => params.data.cells?.length || 0,
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
      width: 110,
      cellClass: 'center-cell',
      valueFormatter: (params) => formatDuration(params.value)
    },
    {
      field: 'latest_run',
      headerName: 'Last Run',
      width: 120,
      cellClass: 'center-cell last-run-cell',
      valueFormatter: (params) => formatRelativeTime(params.value),
      comparator: (valueA, valueB) => {
        // Treat nulls (never run) as epoch time so they sort to bottom in descending order
        // This makes "never run" cascades appear as OLD rather than NEW
        const dateA = valueA ? new Date(valueA).getTime() : 0;
        const dateB = valueB ? new Date(valueB).getTime() : 0;
        return dateA - dateB;
      },
      sort: 'desc'
    },
    {
      field: 'actions',
      colId: 'actions',
      headerName: '',
      width: 90,
      cellClass: 'actions-cell-container',
      cellRenderer: ActionsCellRenderer,
      sortable: false,
      filter: false,
      resizable: false,
      pinned: 'right',
    }
  ], [onVisualize]);

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

  // Handle cell clicks - clicking anywhere on the row opens it (except actions column)
  const onCellClicked = (event) => {
    // Skip navigation if clicking on the actions column
    if (event.column?.colId === 'actions') {
      return;
    }
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
          rowHeight={70}
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
