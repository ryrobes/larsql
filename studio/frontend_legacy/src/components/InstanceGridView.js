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

// Animated cost display that smoothly transitions when value changes
function AnimatedCostCell({ value, formatFn }) {
  const [displayValue, setDisplayValue] = useState(value || 0);
  const animationRef = useRef(null);
  const startValueRef = useRef(value || 0);
  const startTimeRef = useRef(null);

  useEffect(() => {
    const targetValue = value || 0;
    const startValue = displayValue;

    // Skip animation if values are very close or target is 0
    if (Math.abs(targetValue - startValue) < 0.0000001) {
      return;
    }

    // Cancel any existing animation
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }

    startValueRef.current = startValue;
    startTimeRef.current = performance.now();
    const duration = 2000; // 2000ms animation

    const animate = (currentTime) => {
      const elapsed = currentTime - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);

      // Ease-out cubic for smooth deceleration
      const easeOut = 1 - Math.pow(1 - progress, 3);

      const currentValue = startValueRef.current + (targetValue - startValueRef.current) * easeOut;
      setDisplayValue(currentValue);

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [value]); // Only depend on value, not displayValue

  return <span>{formatFn(displayValue)}</span>;
}

// Live duration component that updates smoothly for running instances
// sseStartTime is tracked from SSE cascade_start (instant), startTime comes from DB (may have delay)
function LiveDurationCell({ startTime, sseStartTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(staticDuration || 0);
  const intervalRef = useRef(null);
  const lockedStartRef = useRef(null); // Lock in start time to prevent jumps

  useEffect(() => {
    // Clear interval on any change
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isRunning) {
      // Not running - show static duration, clear locked start
      lockedStartRef.current = null;
      setElapsed(staticDuration || 0);
      return;
    }

    // Running - determine start time
    // Priority: use already locked time > sseStartTime > startTime from DB
    // Once locked, don't change (prevents jumps from slightly different timestamps)
    if (!lockedStartRef.current) {
      const timeSource = sseStartTime || startTime;
      if (timeSource) {
        let parsed;
        if (typeof timeSource === 'number') {
          parsed = timeSource < 10000000000 ? timeSource * 1000 : timeSource;
        } else {
          parsed = new Date(timeSource).getTime();
        }

        if (!isNaN(parsed) && parsed > 0) {
          lockedStartRef.current = parsed;
        }
      }
    }

    // If we have a locked start time, run the counter
    if (lockedStartRef.current) {
      const start = lockedStartRef.current;

      const updateElapsed = () => {
        const now = Date.now();
        const diff = (now - start) / 1000;
        setElapsed(diff >= 0 ? diff : 0);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 100);
    } else {
      // No valid start time yet, show 0
      setElapsed(0);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning, startTime, sseStartTime, staticDuration]);

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
  sessionStartTimes,
  onSoundingsExplorer,
  onVisualize,
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
    const hasRunningCells = instance.cells?.some(p => p.status === 'running');
    const hasFailed = instance.status === 'failed';
    const isChild = instance._isChild;

    return (
      <div className="session-id-cell">
        {isChild && <span className="child-badge">└─</span>}
        <span className="session-id-text">{props.value}</span>
        {(isRunning || hasRunningCells) && !isFinalizing && (
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
    const hasRunningCells = instance.cells?.some(p => p.status === 'running');
    const isCompleted = instance.cells?.every(p => p.status === 'completed');
    const hasFailed = instance.status === 'failed' || instance.cells?.some(p => p.status === 'error');

    let statusText = 'Unknown';
    let statusClass = '';

    if (isFinalizing) {
      statusText = 'Processing';
      statusClass = 'finalizing';
    } else if (isRunning || hasRunningCells) {
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

  const CellsRenderer = (props) => {
    const cells = props.data.cells || [];
    const completed = cells.filter(p => p.status === 'completed').length;
    const running = cells.filter(p => p.status === 'running').length;
    const failed = cells.filter(p => p.status === 'error').length;
    const total = cells.length;

    return (
      <div className="cells-cell">
        <span className="cell-count">{total}</span>
        {running > 0 && (
          <span className="cell-indicator running" title={`${running} running`}>
            <Icon icon="mdi:circle" width="8" />
          </span>
        )}
        {failed > 0 && (
          <span className="cell-indicator failed" title={`${failed} failed`}>
            {failed}
          </span>
        )}
        <span className="cell-progress">
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
        sseStartTime={sessionStartTimes?.[instance.session_id]}
        isRunning={isRunning || isFinalizing}
        staticDuration={instance.duration_seconds}
      />
    );
  };

  const CostRenderer = (props) => {
    return (
      <AnimatedCostCell value={props.data.total_cost} formatFn={formatCost} />
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
    // Get callbacks from cellRendererParams
    const {
      runningSessions: rs,
      finalizingSessions: fs,
      onVisualize: visualize,
      onSoundingsExplorer: soundings,
      onRunCascade: runCascade,
      cascadeData: cData,
      onAudibleClick: audible,
      audibleSignaled: aSig,
      audibleSending: aSend,
      onFreezeInstance: freeze
    } = props;

    const isRunning = rs?.has(instance.session_id);
    const isFinalizing = fs?.has(instance.session_id);
    const hasRunningCells = instance.cells?.some(p => p.status === 'running');
    const isCompleted = instance.cells?.every(p => p.status === 'completed');
    const isChild = instance._isChild;

    const handleClick = (e, callback, ...args) => {
      e.stopPropagation();
      e.preventDefault();
      if (callback) callback(...args);
    };

    return (
      <div className="actions-cell" onClick={(e) => e.stopPropagation()}>
        <button
          className="action-btn flow"
          onClick={(e) => handleClick(e, visualize, instance.session_id, instance.cascade_id)}
          title="View execution flow"
        >
          <Icon icon="ph:tree-structure" width="14" />
        </button>
        {instance.has_soundings && (
          <button
            className="action-btn soundings"
            onClick={(e) => handleClick(e, soundings, instance.session_id)}
            title="Explore soundings"
          >
            <Icon icon="mdi:sign-direction" width="14" />
          </button>
        )}
        <button
          className="action-btn rerun"
          onClick={(e) => handleClick(e, runCascade, {
            ...cData,
            prefilled_inputs: instance.input_data || {}
          })}
          title="Re-run with these inputs"
        >
          <Icon icon="mdi:replay" width="14" />
        </button>
        {(isRunning || (hasRunningCells && !isFinalizing)) && (
          <button
            className={`action-btn audible ${aSig?.[instance.session_id] ? 'signaled' : ''}`}
            onClick={(e) => handleClick(e, audible, e, instance.session_id)}
            disabled={aSend?.[instance.session_id] || aSig?.[instance.session_id]}
            title={aSig?.[instance.session_id] ? 'Audible signaled' : 'Call audible'}
          >
            <Icon icon="mdi:bullhorn" width="14" />
          </button>
        )}
        {isCompleted && freeze && !isChild && (
          <button
            className="action-btn freeze"
            onClick={(e) => handleClick(e, freeze, instance)}
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
      cellRendererParams: {
        runningSessions,
        finalizingSessions,
        onVisualize,
        onSoundingsExplorer,
        onRunCascade,
        cascadeData,
        onAudibleClick,
        audibleSignaled,
        audibleSending,
        onFreezeInstance
      },
      sortable: false,
      filter: false,
      cellClass: 'actions-column',
      suppressMenu: true,
      // Prevent row click when clicking in this column
      onCellClicked: (params) => {
        params.event.stopPropagation();
      }
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
      field: 'cells',
      headerName: 'Cells',
      width: 100,
      cellRenderer: CellsRenderer,
      valueGetter: (params) => params.data.cells?.length || 0,
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
      cellRenderer: CostRenderer
    }
  ], [runningSessions, finalizingSessions, cascadeData, onFreezeInstance, onRunCascade, onSoundingsExplorer, onVisualize, onAudibleClick, audibleSignaled, audibleSending]);

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
    // Skip if click was in the actions column
    if (event.column?.getColId() === 'actions') {
      return;
    }
    // Skip if click was on a button or inside a button
    const target = event.event?.target;
    if (target?.closest('button') || target?.closest('.action-btn')) {
      return;
    }
    if (event.data && onSelectInstance) {
      onSelectInstance(event.data.session_id);
    }
  };

  // Row styling based on state
  const getRowStyle = (params) => {
    const instance = params.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningCells = instance.cells?.some(p => p.status === 'running');
    const isChild = instance._isChild;

    const style = {};

    if (isChild) {
      style.backgroundColor = '#0a0f14';
      style.borderLeft = '3px solid #2dd4bf';
    }

    if (isFinalizing) {
      style.backgroundColor = 'rgba(45, 212, 191, 0.08)';
    } else if (isRunning || hasRunningCells) {
      style.backgroundColor = 'rgba(251, 191, 36, 0.08)';
    }

    return style;
  };

  // Row class based on state
  const getRowClass = (params) => {
    const instance = params.data;
    const isRunning = runningSessions?.has(instance.session_id);
    const isFinalizing = finalizingSessions?.has(instance.session_id);
    const hasRunningCells = instance.cells?.some(p => p.status === 'running');
    const isChild = instance._isChild;

    const classes = [];
    if (isChild) classes.push('child-row');
    if (isFinalizing) classes.push('finalizing-row');
    if (isRunning || hasRunningCells) classes.push('running-row');

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
