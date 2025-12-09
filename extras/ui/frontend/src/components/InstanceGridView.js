import React, { useState, useEffect, useMemo, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import TokenSparkline from './TokenSparkline';
import './InstanceGridView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Create dark theme for AG Grid (matching the app's dark aesthetic)
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

// Live duration component that updates every second
function LiveDurationCell({ startTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (isRunning && startTime) {
      const start = new Date(startTime).getTime();
      const updateElapsed = () => {
        const now = Date.now();
        setElapsed((now - start) / 1000);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 1000);

      return () => {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      };
    } else {
      setElapsed(staticDuration || 0);
    }
  }, [isRunning, startTime, staticDuration]);

  const formatDuration = (seconds) => {
    if (!seconds || seconds < 0) return '0.0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  return (
    <span className={isRunning ? 'live-duration-cell' : ''}>
      {formatDuration(elapsed)}
    </span>
  );
}

/**
 * Grid view for cascade instances using AG Grid
 * Features: sorting, real-time updates, status indicators, action buttons
 */
function InstanceGridView({
  instances,
  onSelectInstance,
  onFreezeInstance,
  onRunCascade,
  cascadeData,
  runningSessions,
  finalizingSessions,
  onSoundingsExplorer,
  onAudibleClick,
  audibleSignaled,
  audibleSending,
  allInstances // For RunPercentile calculations
}) {
  const [gridApi, setGridApi] = useState(null);

  // Format helper functions
  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0.00';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatTimestamp = (isoString) => {
    if (!isoString) return '—';
    const date = new Date(isoString);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Custom cell renderers
  const SessionIdRenderer = (props) => {
    const instance = props.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningPhases = instance.phases?.some(p => p.status === 'running');
    const hasFailed = instance.status === 'failed';
    const isChild = instance._isChild;

    return (
      <div className="session-id-cell">
        {isChild && <span className="child-badge">└─</span>}
        <span className="session-id-text">{props.value}</span>
        {(isRunning || hasRunningPhases) && !isFinalizing && (
          <span className="status-badge running">
            <Icon icon="mdi:lightning-bolt" width="12" />
          </span>
        )}
        {isFinalizing && (
          <span className="status-badge finalizing">
            <Icon icon="mdi:sync" width="12" className="spinning" />
          </span>
        )}
        {hasFailed && (
          <span className="status-badge failed">
            <Icon icon="mdi:alert-circle" width="12" />
          </span>
        )}
      </div>
    );
  };

  const StatusRenderer = (props) => {
    const instance = props.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningPhases = instance.phases?.some(p => p.status === 'running');
    const isCompleted = instance.phases?.every(p => p.status === 'completed');
    const hasFailed = instance.status === 'failed' || instance.phases?.some(p => p.status === 'error');

    let statusText = 'Unknown';
    let statusClass = '';

    if (isFinalizing) {
      statusText = 'Processing';
      statusClass = 'finalizing';
    } else if (isRunning || hasRunningPhases) {
      statusText = 'Running';
      statusClass = 'running';
    } else if (hasFailed) {
      statusText = 'Failed';
      statusClass = 'failed';
    } else if (isCompleted) {
      statusText = 'Completed';
      statusClass = 'completed';
    }

    return (
      <span className={`status-text ${statusClass}`}>
        {statusText}
      </span>
    );
  };

  const PhasesRenderer = (props) => {
    const phases = props.data.phases || [];
    const completed = phases.filter(p => p.status === 'completed').length;
    const running = phases.filter(p => p.status === 'running').length;
    const failed = phases.filter(p => p.status === 'error').length;
    const total = phases.length;

    return (
      <div className="phases-cell">
        <span className="phase-count">{total}</span>
        {running > 0 && (
          <span className="phase-indicator running" title={`${running} running`}>
            <Icon icon="mdi:circle" width="8" />
          </span>
        )}
        {failed > 0 && (
          <span className="phase-indicator failed" title={`${failed} failed`}>
            {failed}
          </span>
        )}
        <span className="phase-progress">
          ({completed}/{total})
        </span>
      </div>
    );
  };

  const DurationRenderer = (props) => {
    const instance = props.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);

    return (
      <LiveDurationCell
        startTime={instance.start_time}
        isRunning={isRunning || isFinalizing}
        staticDuration={instance.duration_seconds}
      />
    );
  };

  const SparklineRenderer = (props) => {
    const data = props.data.token_timeseries;
    if (!data || data.length === 0) return <span className="no-data">—</span>;

    return (
      <div className="sparkline-cell">
        <TokenSparkline data={data} width={60} height={20} />
      </div>
    );
  };

  const InputsRenderer = (props) => {
    const inputs = props.data.input_data;
    if (!inputs || Object.keys(inputs).length === 0) {
      return <span className="no-data">—</span>;
    }

    // Get the first entry and format it as "key: value"
    const entries = Object.entries(inputs);
    const [firstKey, firstValue] = entries[0];
    const valueStr = typeof firstValue === 'object' ? JSON.stringify(firstValue) : String(firstValue);
    const displayText = `${firstKey}: ${valueStr}`;
    const fullText = entries.map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join('\n');

    return (
      <div className="inputs-cell" title={fullText}>
        <span className="input-text">{displayText}</span>
      </div>
    );
  };

  const ActionsRenderer = (props) => {
    const instance = props.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningPhases = instance.phases?.some(p => p.status === 'running');
    const isCompleted = instance.phases?.every(p => p.status === 'completed');
    const isChild = instance._isChild;

    return (
      <div className="actions-cell" onClick={(e) => e.stopPropagation()}>
        {instance.has_soundings && (
          <button
            className="action-btn soundings"
            onClick={(e) => {
              e.stopPropagation();
              onSoundingsExplorer && onSoundingsExplorer(instance.session_id);
            }}
            title="Explore soundings"
          >
            <Icon icon="mdi:sign-direction" width="14" />
          </button>
        )}
        <button
          className="action-btn rerun"
          onClick={(e) => {
            e.stopPropagation();
            onRunCascade && onRunCascade({
              ...cascadeData,
              prefilled_inputs: instance.input_data || {}
            });
          }}
          title="Re-run with these inputs"
        >
          <Icon icon="mdi:replay" width="14" />
        </button>
        {(isRunning || (hasRunningPhases && !isFinalizing)) && (
          <button
            className={`action-btn audible ${audibleSignaled?.[instance.session_id] ? 'signaled' : ''}`}
            onClick={(e) => {
              e.stopPropagation();
              onAudibleClick && onAudibleClick(e, instance.session_id);
            }}
            disabled={audibleSending?.[instance.session_id] || audibleSignaled?.[instance.session_id]}
            title={audibleSignaled?.[instance.session_id] ? 'Audible signaled' : 'Call audible'}
          >
            <Icon icon="mdi:bullhorn" width="14" />
          </button>
        )}
        {isCompleted && onFreezeInstance && !isChild && (
          <button
            className="action-btn freeze"
            onClick={(e) => {
              e.stopPropagation();
              onFreezeInstance(instance);
            }}
            title="Freeze as test snapshot"
          >
            <Icon icon="mdi:snowflake" width="14" />
          </button>
        )}
      </div>
    );
  };

  // Flatten instances with children for grid display
  const flattenedInstances = useMemo(() => {
    const result = [];
    instances.forEach(instance => {
      result.push({ ...instance, _isChild: false });
      if (instance.children && instance.children.length > 0) {
        instance.children.forEach(child => {
          result.push({ ...child, _isChild: true, _parentId: instance.session_id });
        });
      }
    });
    return result;
  }, [instances]);

  // Column definitions
  const columnDefs = useMemo(() => [
    {
      field: 'actions',
      headerName: '',
      width: 120,
      cellRenderer: ActionsRenderer,
      sortable: false,
      filter: false,
      cellClass: 'actions-column',
      suppressMenu: true
    },
    {
      field: 'session_id',
      headerName: 'Session ID',
      width: 180,
      minWidth: 150,
      cellRenderer: SessionIdRenderer,
      cellClass: 'session-id-column'
    },
    {
      field: 'phases',
      headerName: 'Phases',
      width: 100,
      cellRenderer: PhasesRenderer,
      valueGetter: (params) => params.data.phases?.length || 0,
      cellClass: 'center-cell'
    },
    {
      field: 'token_timeseries',
      headerName: 'Tokens',
      width: 80,
      cellRenderer: SparklineRenderer,
      sortable: false,
      filter: false,
      cellClass: 'sparkline-column'
    },
    {
      field: 'input_data',
      headerName: 'Inputs',
      flex: 2,
      minWidth: 250,
      cellRenderer: InputsRenderer,
      sortable: false,
      filter: false,
      cellClass: 'inputs-column'
    },
    {
      field: 'start_time',
      headerName: 'Started',
      width: 140,
      cellClass: 'timestamp-column',
      valueFormatter: (params) => formatTimestamp(params.value),
      sort: 'desc'
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 110,
      cellRenderer: StatusRenderer,
      cellClass: 'status-column'
    },
    {
      field: 'duration_seconds',
      headerName: 'Duration',
      width: 100,
      cellRenderer: DurationRenderer,
      cellClass: 'duration-column'
    },
    {
      field: 'total_cost',
      headerName: 'Cost',
      width: 100,
      cellClass: 'cost-cell',
      valueFormatter: (params) => formatCost(params.value)
    }
  ], [runningSessions, finalizingSessions, cascadeData, onFreezeInstance, onRunCascade, onSoundingsExplorer, onAudibleClick, audibleSignaled, audibleSending]);

  // Default column settings
  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    suppressMovable: false,
    autoHeight: false,
    wrapText: false,
  }), []);

  // Grid ready handler
  const onGridReady = (params) => {
    setGridApi(params.api);
    params.api.sizeColumnsToFit();
  };

  // Handle row clicks
  const onRowClicked = (event) => {
    if (event.data && onSelectInstance) {
      onSelectInstance(event.data.session_id);
    }
  };

  // Row styling based on state
  const getRowStyle = (params) => {
    const instance = params.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningPhases = instance.phases?.some(p => p.status === 'running');
    const isChild = instance._isChild;

    const style = {};

    if (isChild) {
      style.backgroundColor = '#0a0f14';
      style.borderLeft = '3px solid #2dd4bf';
    }

    if (isFinalizing) {
      style.backgroundColor = 'rgba(45, 212, 191, 0.08)';
    } else if (isRunning || hasRunningPhases) {
      style.backgroundColor = 'rgba(251, 191, 36, 0.08)';
    }

    return style;
  };

  // Row class based on state
  const getRowClass = (params) => {
    const instance = params.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningPhases = instance.phases?.some(p => p.status === 'running');
    const isChild = instance._isChild;

    const classes = [];
    if (isChild) classes.push('child-row');
    if (isFinalizing) classes.push('finalizing-row');
    if (isRunning || hasRunningPhases) classes.push('running-row');

    return classes.join(' ');
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

  // Refresh grid when data changes
  useEffect(() => {
    if (gridApi) {
      gridApi.refreshCells({ force: true });
    }
  }, [gridApi, runningSessions, finalizingSessions]);

  return (
    <div className="instance-grid-container">
      <div className="instance-grid">
        <AgGridReact
          theme={darkTheme}
          rowData={flattenedInstances}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          onGridReady={onGridReady}
          onRowClicked={onRowClicked}
          rowHeight={50}
          headerHeight={45}
          animateRows={true}
          getRowStyle={getRowStyle}
          getRowClass={getRowClass}
          enableCellTextSelection={true}
          ensureDomOrder={true}
          rowSelection={{
            mode: 'singleRow',
            enableClickSelection: false
          }}
          suppressRowHoverHighlight={false}
          suppressCellFocus={true}
        />
      </div>
    </div>
  );
}

export default InstanceGridView;
