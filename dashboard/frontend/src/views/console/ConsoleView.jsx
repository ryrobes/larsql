import React, { useState, useEffect, useMemo, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Button, useToast } from '../../components';
import CostTimelineChart from '../../components/CostTimelineChart';
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
  const gridRef = useRef(null);
  const { showToast } = useToast();
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

      // Transform sessions to include duration
      const rows = (data.sessions || []).map(session => ({
        session_id: session.session_id,
        cascade_id: session.cascade_id,
        status: session.status,
        current_phase: session.current_phase,
        started_at: session.started_at,
        completed_at: session.completed_at,
        updated_at: session.updated_at,
        error_message: session.error_message,
        depth: session.depth || 0,
        duration: session.completed_at && session.started_at
          ? formatDuration(new Date(session.completed_at) - new Date(session.started_at))
          : session.status === 'RUNNING' ? 'Running...' : '-',
      }));

      // Only update state if data actually changed (prevent unnecessary re-renders)
      const newHash = JSON.stringify(rows.map(r => ({
        id: r.session_id,
        status: r.status,
        phase: r.current_phase,
        updated: r.updated_at
      })));

      if (newHash !== prevDataHashRef.current) {
        console.log('[Console] Data changed, updating grid');
        setSessions(rows);
        prevDataHashRef.current = newHash;
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
      headerName: 'Session',
      width: 180,
      cellRenderer: (params) => (
        <span className="console-session-id" title={params.value}>
          {params.value?.slice(0, 12)}...
        </span>
      ),
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      flex: 1,
      minWidth: 200,
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 110,
      cellRenderer: (params) => {
        const status = params.value?.toLowerCase();
        const colorMap = {
          running: '#00e5ff',
          completed: '#34d399',
          error: '#ff006e',
          cancelled: '#64748b',
          blocked: '#fbbf24',
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
      headerName: 'Phase',
      width: 150,
    },
    {
      field: 'duration',
      headerName: 'Duration',
      width: 100,
    },
    {
      field: 'started_at',
      headerName: 'Started',
      width: 180,
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
  }), []);

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
        {/* Test toast button (for demo) */}
        {process.env.NODE_ENV === 'development' && (
          <Button
            variant="ghost"
            size="sm"
            icon="mdi:bell"
            onClick={() => showToast('Toast test!', { type: 'success' })}
          >
            Test Toast
          </Button>
        )}
      </div>

      {/* Cost Chart Section */}
      <div className="console-section">
        <div className="console-section-header">
          <Icon icon="mdi:chart-line" width="20" />
          <h2>Cost Timeline</h2>
        </div>
        <div className="console-chart-wrapper">
          <CostTimelineChart />
        </div>
      </div>

      {/* Sessions Table */}
      <div className="console-section">
        <div className="console-section-header">
          <Icon icon="mdi:table" width="20" />
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
          <div className="console-grid-container">
            <AgGridReact
              ref={gridRef}
              theme={darkTheme}
              rowData={sessions}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              getRowId={(params) => params.data.session_id} // Stable row tracking
              domLayout="autoHeight"
              suppressCellFocus={true}
              suppressMovableColumns={false}
              enableCellTextSelection={true}
              ensureDomOrder={true}
              animateRows={true}
              loading={loading}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default ConsoleView;
