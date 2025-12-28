import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Button, useToast } from '../../components';
import CostTimelineChart from '../../components/CostTimelineChart';
import KPICard from '../receipts/components/KPICard';
import useNavigationStore from '../../stores/navigationStore';
import './ConsoleView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Cell renderer components for AG Grid
const InputBadgeRenderer = (props) => {
  const category = props.value;
  const badges = {
    tiny: { label: 'T', color: '#34d399' },
    small: { label: 'S', color: '#60a5fa' },
    medium: { label: 'M', color: '#94a3b8' },
    large: { label: 'L', color: '#fbbf24' },
    huge: { label: 'H', color: '#f87171' }
  };

  // Handle empty/null category
  if (!category) {
    return <span style={{ color: '#475569', fontSize: '11px' }}>-</span>;
  }

  const badge = badges[category] || { label: '?', color: '#94a3b8' };

  return (
    <span style={{
      background: badge.color,
      color: '#0f172a',
      padding: '2px 6px',
      borderRadius: '3px',
      fontSize: '11px',
      fontWeight: '600'
    }}>
      {badge.label}
    </span>
  );
};

const CostRenderer = (props) => {
  const cost = props.value || 0;
  const zScore = props.data.cost_z_score || 0;
  const isOutlier = props.data.is_cost_outlier;

  const color = isOutlier ? '#f87171' :
                Math.abs(zScore) > 1 ? '#fbbf24' :
                '#34d399';

  const zDisplay = Math.abs(zScore) > 1 ? `(${zScore > 0 ? '+' : ''}${zScore.toFixed(1)}σ)` : '';

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>${cost.toFixed(4)}</div>
      {zDisplay && <div style={{ fontSize: '10px', marginTop: '2px' }}>{zDisplay}</div>}
    </div>
  );
};

const ContextRenderer = (props) => {
  const pct = props.value || 0;
  const contextCost = props.data.total_context_cost_estimated || 0;
  const totalCost = props.data.total_cost || 0;
  const newCost = totalCost - contextCost;

  const color = pct > 60 ? '#fbbf24' : pct < 30 ? '#34d399' : '#94a3b8';

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{pct.toFixed(0)}%</div>
      {pct > 0 && (
        <div style={{ fontSize: '10px', marginTop: '2px', color: '#64748b' }}>
          ctx: ${contextCost.toFixed(3)}
        </div>
      )}
    </div>
  );
};

const BottleneckRenderer = (props) => {
  const cell = props.value;
  const pct = props.data.bottleneck_cell_pct || 0;

  if (!cell || pct < 40) {
    return <span style={{ color: '#475569' }}>-</span>;
  }

  const color = pct > 70 ? '#f87171' : '#fbbf24';

  return (
    <div style={{ color, fontWeight: '500', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
      <div>{cell}</div>
      <div style={{ fontSize: '10px', marginTop: '2px', color: '#64748b' }}>
        {pct.toFixed(0)}% of cascade
      </div>
    </div>
  );
};

const DurationRenderer = (props) => {
  const ms = props.value || 0;
  const seconds = (ms / 1000).toFixed(1);
  const clusterAvg = props.data.cluster_avg_duration || 0;
  const isOutlier = props.data.is_duration_outlier;

  const color = isOutlier ? '#f87171' : '#94a3b8';

  const multiplier = clusterAvg > 0 ? (ms / clusterAvg).toFixed(1) : null;

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{seconds}s</div>
      {isOutlier && multiplier && (
        <div style={{ fontSize: '10px', marginTop: '2px', color: '#64748b' }}>
          {multiplier}x slower
        </div>
      )}
    </div>
  );
};

// Dark theme for AG Grid matching Studio
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
 * ConsoleView - System console and analytics dashboard
 *
 * Features:
 * - Cost timeline chart
 * - Recent cascade executions table
 * - Live updates via polling
 */
// System cascades to hide when filter is enabled
const SYSTEM_CASCADES = ['analyze_context_relevance'];

const ConsoleView = () => {
  const [sessions, setSessions] = useState([]);
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [gridHeight, setGridHeight] = useState(600); // Dynamic grid height
  const [hideSystemCascades, setHideSystemCascades] = useState(true); // Default ON - hide system cascades
  const gridRef = useRef(null);
  const containerRef = useRef(null);
  const { showToast } = useToast();
  const { navigate } = useNavigationStore();
  const prevDataHashRef = useRef(null);

  // Fetch recent sessions from sessions API
  const fetchSessions = async () => {
    try {
      // Only show loading on first fetch
      if (sessions.length === 0) {
        setLoading(true);
      }

      // Use sessions API with limit parameter
      const res = await fetch('http://localhost:5001/api/sessions?limit=100');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Transform sessions to include duration and analytics metrics
      const rows = (data.sessions || []).map(session => ({
        session_id: session.session_id,
        cascade_id: session.cascade_id,
        status: session.status,
        current_phase: session.current_phase || session.current_cell,
        started_at: session.started_at,
        completed_at: session.completed_at,
        updated_at: session.updated_at,
        error_message: session.error_message,
        depth: session.depth || 0,
        duration: session.completed_at && session.started_at
          ? formatDuration(new Date(session.completed_at) - new Date(session.started_at))
          : session.status === 'RUNNING' ? 'Running...' : '-',
        total_cost: session.total_cost || 0,
        total_duration_ms: session.total_duration_ms || 0,
        message_count: session.message_count || 0,
        input_data: session.input_data,
        output: session.output || null,
        // Legacy percent diff columns (hidden by default)
        cost_diff_pct: session.cost_diff_pct,
        messages_diff_pct: session.messages_diff_pct,
        duration_diff_pct: session.duration_diff_pct,
        // New analytics metrics
        input_category: session.input_category,
        input_char_count: session.input_char_count || 0,
        cost_z_score: session.cost_z_score || 0,
        duration_z_score: session.duration_z_score || 0,
        is_cost_outlier: session.is_cost_outlier || false,
        is_duration_outlier: session.is_duration_outlier || false,
        cluster_avg_cost: session.cluster_avg_cost || 0,
        cluster_avg_duration: session.cluster_avg_duration || 0,
        cluster_run_count: session.cluster_run_count || 0,
        context_cost_pct: session.context_cost_pct || 0,
        total_context_cost_estimated: session.total_context_cost_estimated || 0,
        bottleneck_cell: session.bottleneck_cell,
        bottleneck_cell_pct: session.bottleneck_cell_pct || 0,
      }));

      // Only update state if data actually changed (prevent unnecessary re-renders)
      // Include enrichment fields in hash to detect changes
      const newHash = JSON.stringify(rows.map(r => ({
        id: r.session_id,
        status: r.status,
        phase: r.current_phase,
        updated: r.updated_at,
        cost: r.total_cost,
        msgs: r.message_count,
      })));

      if (newHash !== prevDataHashRef.current) {
        console.log('[Console] Data changed, updating grid. Sample row:', rows[0]);
        setSessions(rows);
        prevDataHashRef.current = newHash;
      } else {
        console.log('[Console] Data unchanged, skipping update');
      }

      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch KPIs from console/kpis API
  const fetchKpis = async () => {
    try {
      const res = await fetch('http://localhost:5001/api/console/kpis');
      const data = await res.json();

      if (data.error) {
        console.error('[Console] KPI fetch error:', data.error);
        return;
      }

      setKpis(data);
    } catch (err) {
      console.error('[Console] KPI fetch failed:', err.message);
    }
  };

  // Poll every 10 seconds (slower to reduce flicker, data doesn't change that fast)
  useEffect(() => {
    fetchSessions();
    fetchKpis();
    const interval = setInterval(() => {
      fetchSessions();
      fetchKpis();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // Calculate grid height based on viewport
  useEffect(() => {
    const calculateGridHeight = () => {
      if (!containerRef.current) return;

      // Get viewport height
      const viewportHeight = window.innerHeight;

      // Get container's offset from top
      const containerTop = containerRef.current.getBoundingClientRect().top;

      // Reserve space for bottom padding (20px)
      const availableHeight = viewportHeight - containerTop - 20;

      // Minimum height of 400px, max out at available space
      const newHeight = Math.max(400, Math.min(availableHeight, viewportHeight * 0.7));

      setGridHeight(newHeight);
    };

    // Calculate on mount and resize
    calculateGridHeight();
    window.addEventListener('resize', calculateGridHeight);

    // Recalculate after a short delay to account for dynamic content loading
    const timeout = setTimeout(calculateGridHeight, 100);

    return () => {
      window.removeEventListener('resize', calculateGridHeight);
      clearTimeout(timeout);
    };
  }, []);

  // Handle row click - navigate to Studio with cascade and session
  const handleRowClick = (event) => {
    const { cascade_id, session_id } = event.data;
    if (cascade_id && session_id) {
      navigate('studio', { cascade: cascade_id, session: session_id });
    }
  };

  // Format duration
  const formatDuration = (ms) => {
    if (!ms) return '-';
    const seconds = Math.floor(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  // Filter out system cascades when toggle is enabled
  const filteredSessions = useMemo(() => {
    if (!hideSystemCascades) return sessions;
    return sessions.filter(session =>
      !SYSTEM_CASCADES.includes(session.cascade_id)
    );
  }, [sessions, hideSystemCascades]);

  // AG Grid column definitions
  const columnDefs = useMemo(() => [
    {
      field: 'session_id',
      headerName: 'Session ID',
      cellClass: 'console-session-id',
      flex: 2,
      minWidth: 180,
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      flex: 2,
      minWidth: 150,
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 100,
      cellRenderer: (params) => {
        const status = params.value?.toLowerCase();
        const colorMap = {
          running: '#00e5ff',
          starting: '#00e5ff',
          completed: '#34d399',
          error: '#ff006e',
          cancelled: '#64748b',
          blocked: '#fbbf24',
          orphaned: '#9333ea',
        };
        const color = colorMap[status] || '#64748b';

        return (
          <span style={{ color, fontWeight: 600, textTransform: 'uppercase', fontSize: '11px' }}>
            {params.value}
          </span>
        );
      },
    },
    {
      field: 'current_phase',
      headerName: 'Last Cell',
      flex: 1,
      minWidth: 120,
      hide: true, // Hidden by default
    },
    {
      field: 'output',
      headerName: 'Output',
      flex: 2,
      minWidth: 180,
      wrapText: true,
      autoHeight: true,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        // Truncate to 150 chars for wrapping display
        const output = String(params.value);
        return output.length > 150 ? output.slice(0, 150) + '...' : output;
      },
      tooltipValueGetter: (params) => {
        if (!params.value) return null;
        // Show full truncated output (300 chars) in tooltip
        return String(params.value);
      },
      cellStyle: {
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        color: '#94a3b8',
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '8px',
        paddingBottom: '8px'
      },
    },
    // INPUT SIZE BADGE
    {
      field: 'input_category',
      headerName: 'Input',
      headerTooltip: 'Input size category for apples-to-apples comparison',
      width: 80,
      cellRenderer: InputBadgeRenderer,
      tooltipValueGetter: (params) => {
        const cat = params.value;
        const charCount = params.data.input_char_count || 0;
        if (!cat) {
          return charCount > 0 ? `Input size: ${charCount} chars (no category)` : 'No input data';
        }
        return `Input size: ${cat} (${charCount} chars)`;
      },
    },
    // COST WITH Z-SCORE
    {
      field: 'total_cost',
      headerName: 'Cost',
      headerTooltip: 'Statistical anomaly score vs similar input size runs',
      width: 130,
      wrapText: true,
      autoHeight: true,
      cellRenderer: CostRenderer,
      tooltipValueGetter: (params) => {
        const cost = params.value || 0;
        const clusterAvg = params.data.cluster_avg_cost || 0;
        const clusterSize = params.data.cluster_run_count || 0;
        const zScore = params.data.cost_z_score || 0;
        return `Cost: $${cost.toFixed(4)} | Cluster avg: $${clusterAvg.toFixed(4)} (n=${clusterSize} similar runs) | Z-score: ${zScore.toFixed(1)}σ`;
      },
      cellStyle: {
        fontFamily: 'var(--font-mono)',
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    // CONTEXT %
    {
      field: 'context_cost_pct',
      headerName: 'Context%',
      headerTooltip: 'Percentage of cost from context injection vs new tokens',
      width: 100,
      wrapText: true,
      autoHeight: true,
      cellRenderer: ContextRenderer,
      tooltipValueGetter: (params) => {
        const pct = params.value || 0;
        const contextCost = params.data.total_context_cost_estimated || 0;
        const totalCost = params.data.total_cost || 0;
        const newCost = totalCost - contextCost;
        return `Context cost: $${contextCost.toFixed(4)} (${pct.toFixed(0)}%) | New tokens: $${newCost.toFixed(4)}`;
      },
      cellStyle: {
        fontFamily: 'var(--font-mono)',
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    // BOTTLENECK CELL
    {
      field: 'bottleneck_cell',
      headerName: 'Bottleneck',
      headerTooltip: 'Cell that consumed the most cascade cost/time',
      width: 140,
      wrapText: true,
      autoHeight: true,
      cellRenderer: BottleneckRenderer,
      tooltipValueGetter: (params) => {
        const cell = params.value;
        const pct = params.data.bottleneck_cell_pct || 0;
        return cell ? `Cell '${cell}' consumed ${pct.toFixed(0)}% of cascade cost` : 'No dominant bottleneck';
      },
      cellStyle: {
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    // DURATION WITH MULTIPLIER
    {
      field: 'total_duration_ms',
      headerName: 'Duration',
      headerTooltip: 'Execution time compared to similar input size runs',
      width: 120,
      wrapText: true,
      autoHeight: true,
      cellRenderer: DurationRenderer,
      tooltipValueGetter: (params) => {
        const ms = params.value || 0;
        const clusterAvg = params.data.cluster_avg_duration || 0;
        const clusterSize = params.data.cluster_run_count || 0;
        const multiplier = clusterAvg > 0 ? (ms / clusterAvg).toFixed(1) : 0;
        return `Duration: ${(ms/1000).toFixed(1)}s | Cluster avg: ${(clusterAvg/1000).toFixed(1)}s (n=${clusterSize} similar runs) | ${multiplier}x ${ms > clusterAvg ? 'slower' : 'faster'}`;
      },
      cellStyle: {
        fontFamily: 'var(--font-mono)',
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    // LEGACY COLUMNS (HIDDEN)
    { field: 'cost_diff_pct', hide: true },
    { field: 'messages_diff_pct', hide: true },
    { field: 'duration_diff_pct', hide: true },
    { field: 'message_count', hide: true }, // Replaced by Context%
    {
      field: 'input_data',
      headerName: 'Inputs',
      flex: 2,
      minWidth: 150,
      wrapText: true,
      autoHeight: true,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        try {
          const inputs = typeof params.value === 'string' ? JSON.parse(params.value) : params.value;
          if (typeof inputs === 'object' && inputs !== null) {
            const str = JSON.stringify(inputs, null, 2);
            // Truncate to 150 chars (same as output)
            return str.length > 150 ? str.slice(0, 150) + '...' : str;
          }
          const str = JSON.stringify(inputs);
          return str.length > 150 ? str.slice(0, 150) + '...' : str;
        } catch {
          const str = String(params.value);
          return str.length > 150 ? str.slice(0, 150) + '...' : str;
        }
      },
      tooltipValueGetter: (params) => {
        if (!params.value) return null;
        try {
          const inputs = typeof params.value === 'string' ? JSON.parse(params.value) : params.value;
          return JSON.stringify(inputs, null, 2);
        } catch {
          return String(params.value);
        }
      },
      cellStyle: {
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '8px',
        paddingBottom: '8px'
      },
    },
    {
      field: 'started_at',
      headerName: 'Started',
      flex: 1.5,
      minWidth: 160,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        // Convert UTC timestamp to local timezone
        const utcDate = new Date(params.value + 'Z'); // Append Z to treat as UTC
        return utcDate.toLocaleString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        });
      },
      tooltipValueGetter: (params) => {
        if (!params.value) return null;
        const utcDate = new Date(params.value + 'Z');
        return `Local: ${utcDate.toLocaleString()}\nUTC: ${params.value}`;
      },
    },
  ], []);

  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    autoHeight: true,
    wrapText: false,
    menuTabs: ['filterMenuTab', 'generalMenuTab', 'columnsMenuTab'], // Enable column hiding
  }), []);

  // Context menu for column visibility
  const getContextMenuItems = useCallback((params) => {
    const result = [
      {
        name: 'Show/Hide Columns',
        icon: '<span class="ag-icon ag-icon-columns"></span>',
        subMenu: params.api.getColumns().map(col => ({
          name: col.getColDef().headerName || col.getColId(),
          checked: col.isVisible(),
          action: () => {
            params.api.setColumnsVisible([col.getColId()], !col.isVisible());
          },
        })),
      },
      'separator',
      'copy',
      'copyWithHeaders',
      'separator',
      'export',
    ];
    return result;
  }, []);

  // Columns sized on first render - flex handles responsive sizing automatically
  const onFirstDataRendered = (params) => {
    // Flex columns automatically fill viewport, no need to call sizeColumnsToFit
    // Just ensure the grid knows its size
    params.api.sizeColumnsToFit();
  };

  return (
    <div className="console-view">
      {/* Header */}
      <div className="console-header">
        <div className="console-title">
          <Icon icon="mdi:console" width="32" />
          <h1>Console</h1>
        </div>
        <div className="console-subtitle">
          System analytics and recent activity
        </div>
      </div>

      {/* KPI Header Panel */}
      {kpis && (
        <div className="console-kpi-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px' }}>
          <KPICard
            icon="mdi:cash"
            title="24h Cost"
            value={`$${kpis.total_cost_24h.toFixed(2)}`}
            subtitle={kpis.cost_trend}
            color="#34d399"
          />
          <KPICard
            icon="mdi:alert-circle"
            title="Active Outliers"
            value={kpis.outlier_count}
            subtitle="in last 24h"
            color={kpis.outlier_count > 0 ? '#f87171' : '#94a3b8'}
          />
          <KPICard
            icon="mdi:percent"
            title="Avg Context%"
            value={`${kpis.avg_context_pct.toFixed(0)}%`}
            subtitle={kpis.context_trend}
            color="#60a5fa"
          />
          <KPICard
            icon="mdi:target"
            title="Top Bottleneck"
            value={kpis.top_bottleneck_cell}
            subtitle={`${kpis.top_bottleneck_pct.toFixed(0)}% avg`}
            color="#fbbf24"
          />
        </div>
      )}

      {/* Cost Chart Section */}
      <div className="console-section">
        <div className="console-section-header">
          <Icon icon="mdi:chart-line" width="14" />
          <h2>Cost Timeline</h2>
        </div>
        <div className="console-chart-wrapper">
          <CostTimelineChart />
        </div>
      </div>

      {/* Sessions Table */}
      <div className="console-section">
        <div className="console-section-header">
          <Icon icon="mdi:table" width="14" />
          <h2>Recent Sessions</h2>
          <span className="console-count">
            {hideSystemCascades && filteredSessions.length !== sessions.length
              ? `${filteredSessions.length} of ${sessions.length}`
              : sessions.length
            } sessions
          </span>
          <button
            className={`console-system-toggle ${hideSystemCascades ? 'active' : ''}`}
            onClick={() => setHideSystemCascades(!hideSystemCascades)}
            title={hideSystemCascades ? 'Show system cascades' : 'Hide system cascades'}
          >
            <Icon icon={hideSystemCascades ? 'mdi:eye-off' : 'mdi:eye'} width="12" />
            <span>System</span>
          </button>
        </div>

        {error && (
          <div className="console-error">
            <Icon icon="mdi:alert-circle" width="20" />
            <span>{error}</span>
          </div>
        )}

        {!error && (
          <div ref={containerRef} className="console-grid-container" style={{ height: `${gridHeight}px` }}>
            <AgGridReact
              ref={gridRef}
              theme={darkTheme}
              rowData={filteredSessions}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              getRowId={(params) => params.data.session_id} // Stable row tracking
              getContextMenuItems={getContextMenuItems} // Custom context menu
              domLayout="normal"
              suppressCellFocus={true}
              suppressMovableColumns={false}
              enableCellTextSelection={true}
              ensureDomOrder={true}
              animateRows={true}
              loading={loading}
              onRowClicked={handleRowClick}
              onFirstDataRendered={onFirstDataRendered}
              rowClass="console-grid-row-clickable"
              tooltipShowDelay={500}
              preventDefaultOnContextMenu={true} // Prevent browser context menu
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default ConsoleView;
