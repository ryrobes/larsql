import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import useNavigationStore from '../../../stores/navigationStore';
import './AlertsPanel.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching Console/Studio
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
 * AlertsPanel - Displays alerts and anomalies in a table
 * Uses ag-grid with dark theme matching Studio aesthetic
 *
 * @param {Array} alerts - Array of alert objects from backend
 */
const AlertsPanel = ({ alerts = [] }) => {
  const navigate = useNavigationStore((state) => state.navigate);

  // Handle row click - navigate to Studio with session
  const handleRowClick = (event) => {
    const { cascade_id, session_id } = event.data;
    if (session_id) {
      const params = { session: session_id };
      if (cascade_id) {
        params.cascade = cascade_id;
      }
      navigate('studio', params);
    }
  };

  const columnDefs = useMemo(() => [
    {
      field: 'severity',
      headerName: 'Severity',
      width: 120,
      cellRenderer: (params) => {
        const colors = {
          critical: '#ff006e',
          major: '#fbbf24',
          warning: '#fbbf24',
          minor: '#60a5fa',
          info: '#34d399',
        };
        const icons = {
          critical: 'mdi:alert-circle',
          major: 'mdi:alert',
          warning: 'mdi:alert',
          minor: 'mdi:information',
          info: 'mdi:information',
        };

        const color = colors[params.value] || '#64748b';
        const icon = icons[params.value] || 'mdi:information';

        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Icon icon={icon} style={{ color }} />
            <span style={{
              color,
              fontWeight: 600,
              textTransform: 'uppercase',
              fontSize: '11px'
            }}>
              {params.value}
            </span>
          </div>
        );
      },
    },
    {
      field: 'type',
      headerName: 'Type',
      width: 160,
      valueFormatter: (params) => {
        const labels = {
          cost_outlier: 'Cost Outlier',
          context_hotspot: 'Context Hotspot',
          regression: 'Regression',
          duration_outlier: 'Duration Outlier',
        };
        return labels[params.value] || params.value?.replace(/_/g, ' ') || '-';
      },
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      flex: 1,
      minWidth: 150,
    },
    {
      field: 'cell_name',
      headerName: 'Cell',
      width: 140,
      valueFormatter: (params) => params.value || '-',
    },
    {
      field: 'message',
      headerName: 'Description',
      flex: 2,
      minWidth: 300,
      cellStyle: { fontSize: '12px', lineHeight: '1.4' },
      wrapText: true,
      autoHeight: true,
    },
    {
      field: 'z_score',
      headerName: 'Deviation',
      width: 110,
      headerTooltip: 'Standard deviations from average (σ)',
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const absZ = Math.abs(params.value);
        if (absZ >= 4) return `Very High`;
        if (absZ >= 3) return `High`;
        if (absZ >= 2) return `Elevated`;
        return `Normal`;
      },
      cellStyle: (params) => {
        if (!params.value) return {};
        const absZ = Math.abs(params.value);
        const color = absZ > 3 ? '#ff006e' : absZ > 2 ? '#fbbf24' : '#cbd5e1';
        return { color, fontWeight: 600 };
      },
      tooltipValueGetter: (params) => {
        return params.value ? `${params.value.toFixed(1)}σ (${Math.abs(params.value).toFixed(1)} standard deviations)` : '';
      },
    },
    {
      field: 'timestamp',
      headerName: 'Time',
      width: 170,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const date = new Date(params.value);
        return date.toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
      },
    },
  ], []);

  return (
    <div className="alerts-panel">
      <div className="alerts-panel-header">
        <Icon icon="mdi:alert-circle" width={20} />
        <h2>Alerts & Anomalies</h2>
        <span className="alerts-count">
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="alerts-grid-container">
        {alerts.length === 0 ? (
          <div className="alerts-empty-state">
            <Icon icon="mdi:check-circle" width={48} style={{ color: '#34d399' }} />
            <p>No alerts detected</p>
            <span>All systems operating within normal parameters</span>
          </div>
        ) : (
          <AgGridReact
            theme={darkTheme}
            rowData={alerts}
            columnDefs={columnDefs}
            domLayout="autoHeight"
            suppressCellFocus={true}
            enableCellTextSelection={true}
            rowHeight={40}
            onRowClicked={handleRowClick}
            rowStyle={{ cursor: 'pointer' }}
          />
        )}
      </div>
    </div>
  );
};

export default AlertsPanel;
