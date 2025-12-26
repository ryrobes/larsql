import React, { useState, useEffect, useMemo, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Button, useToast } from '../../components';
import CostTimelineChart from '../../components/CostTimelineChart';
import useNavigationStore from '../../stores/navigationStore';
import './ConsoleView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

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
const ConsoleView = () => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [gridHeight, setGridHeight] = useState(600); // Dynamic grid height
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

      // Transform sessions to include duration and new metrics
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
        message_count: session.message_count || 0,
        input_data: session.input_data,
        cost_diff_pct: session.cost_diff_pct,
        messages_diff_pct: session.messages_diff_pct,
        duration_diff_pct: session.duration_diff_pct,
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

  // Poll every 10 seconds (slower to reduce flicker, data doesn't change that fast)
  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 10000);
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
    },
    {
      field: 'total_cost',
      headerName: 'Cost',
      width: 110,
      valueFormatter: (params) => {
        const cost = params.value || 0;
        return cost > 0 ? `$${cost.toFixed(6)}` : '-';
      },
      cellStyle: { color: '#34d399', fontFamily: 'var(--font-mono)' },
    },
    {
      field: 'cost_diff_pct',
      headerName: 'Δ%',
      width: 85,
      valueFormatter: (params) => {
        if (params.value === null || params.value === undefined) return '-';
        const val = params.value;
        return val > 0 ? `+${val}%` : `${val}%`;
      },
      cellStyle: (params) => {
        if (params.value === null || params.value === undefined) return { fontFamily: 'var(--font-mono)', fontSize: '11px' };
        const val = params.value;
        const color = val > 10 ? '#ff006e' : val < -10 ? '#34d399' : '#cbd5e1';
        return { color, fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600 };
      },
      tooltipValueGetter: (params) => {
        if (params.value === null || params.value === undefined) return null;
        return `${params.value}% vs cascade average cost`;
      },
    },
    {
      field: 'message_count',
      headerName: 'Messages',
      width: 95,
      valueFormatter: (params) => {
        const count = params.value || 0;
        return count > 0 ? count.toString() : '-';
      },
      cellStyle: { fontFamily: 'var(--font-mono)' },
    },
    {
      field: 'messages_diff_pct',
      headerName: 'Δ%',
      width: 85,
      valueFormatter: (params) => {
        if (params.value === null || params.value === undefined) return '-';
        const val = params.value;
        return val > 0 ? `+${val}%` : `${val}%`;
      },
      cellStyle: (params) => {
        if (params.value === null || params.value === undefined) return { fontFamily: 'var(--font-mono)', fontSize: '11px' };
        const val = params.value;
        const color = val > 10 ? '#ff006e' : val < -10 ? '#34d399' : '#cbd5e1';
        return { color, fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600 };
      },
      tooltipValueGetter: (params) => {
        if (params.value === null || params.value === undefined) return null;
        return `${params.value}% vs cascade average messages`;
      },
    },
    {
      field: 'input_data',
      headerName: 'Inputs',
      flex: 2,
      minWidth: 150,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        try {
          const inputs = typeof params.value === 'string' ? JSON.parse(params.value) : params.value;
          if (typeof inputs === 'object' && inputs !== null) {
            // Show first few keys
            const keys = Object.keys(inputs);
            if (keys.length === 0) return '{}';
            if (keys.length <= 2) {
              return keys.map(k => `${k}: ${JSON.stringify(inputs[k])}`).join(', ');
            }
            return `${keys.length} inputs`;
          }
          return JSON.stringify(inputs).slice(0, 50);
        } catch {
          return String(params.value).slice(0, 50);
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
      cellStyle: { fontFamily: 'var(--font-mono)', fontSize: '12px' },
    },
    {
      field: 'duration',
      headerName: 'Duration',
      width: 95,
    },
    {
      field: 'duration_diff_pct',
      headerName: 'Δ%',
      width: 85,
      valueFormatter: (params) => {
        if (params.value === null || params.value === undefined) return '-';
        const val = params.value;
        return val > 0 ? `+${val}%` : `${val}%`;
      },
      cellStyle: (params) => {
        if (params.value === null || params.value === undefined) return { fontFamily: 'var(--font-mono)', fontSize: '11px' };
        const val = params.value;
        // For duration: faster is better (negative is good)
        const color = val > 10 ? '#ff006e' : val < -10 ? '#34d399' : '#cbd5e1';
        return { color, fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600 };
      },
      tooltipValueGetter: (params) => {
        if (params.value === null || params.value === undefined) return null;
        return `${params.value}% vs cascade average duration`;
      },
    },
    {
      field: 'started_at',
      headerName: 'Started',
      flex: 1.5,
      minWidth: 160,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        return new Date(params.value).toLocaleString();
      },
    },
  ], []);

  const defaultColDef = useMemo(() => ({
    sortable: true,
    filter: true,
    resizable: true,
    autoHeight: true,
    wrapText: false,
  }), []);

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
          <span className="console-count">{sessions.length} sessions</span>
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
              rowData={sessions}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              getRowId={(params) => params.data.session_id} // Stable row tracking
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
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default ConsoleView;
