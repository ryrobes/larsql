import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../components';
import WatchDetail from './components/WatchDetail';
import './WatchersView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching Studio aesthetic
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

// Deep equality check for data comparison
const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

// Status configuration
const STATUS_CONFIG = {
  all: { label: 'All', icon: 'mdi:view-grid', color: '#94a3b8' },
  enabled: { label: 'Enabled', icon: 'mdi:play-circle', color: '#34d399' },
  disabled: { label: 'Disabled', icon: 'mdi:pause-circle', color: '#64748b' },
  error: { label: 'Error', icon: 'mdi:alert-circle', color: '#f87171' },
};

// Action type colors
const ACTION_TYPE_COLORS = {
  cascade: '#a78bfa',
  signal: '#818cf8',
  sql: '#f59e0b',
  default: '#94a3b8',
};

// localStorage keys
const STORAGE_KEY_STATUS = 'watchers_status';

const getInitialStatus = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_STATUS);
    if (stored && STATUS_CONFIG[stored]) return stored;
  } catch (e) {}
  return 'all';
};

/**
 * WatchersView - Monitor SQL watch subscriptions
 */
const WatchersView = () => {
  const [activeStatus, setActiveStatus] = useState(getInitialStatus);
  const [searchText, setSearchText] = useState('');
  const [watches, setWatches] = useState([]);
  const [statusCounts, setStatusCounts] = useState({});
  const [actionTypeCounts, setActionTypeCounts] = useState({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedWatch, setSelectedWatch] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState(null);

  // Fetch watches list
  const fetchWatches = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (activeStatus !== 'all') {
        params.set('status', activeStatus);
      }
      if (searchText.trim()) {
        params.set('search', searchText.trim());
      }
      params.set('limit', '500');

      const res = await fetch(`http://localhost:5050/api/watchers?${params.toString()}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setWatches(prev => isEqual(prev, data.watches) ? prev : data.watches);
      setStatusCounts(prev => isEqual(prev, data.status_counts) ? prev : data.status_counts);
      setActionTypeCounts(prev => isEqual(prev, data.action_type_counts) ? prev : data.action_type_counts);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeStatus, searchText]);

  // Fetch watch detail
  const fetchDetail = useCallback(async (watchName) => {
    if (!watchName) {
      setDetailData(null);
      return;
    }

    setDetailLoading(true);
    try {
      const res = await fetch(`http://localhost:5050/api/watchers/${encodeURIComponent(watchName)}`);
      const data = await res.json();

      if (data.error) {
        console.error('Error fetching watch detail:', data.error);
        setDetailData(null);
      } else {
        setDetailData(data);
      }
    } catch (err) {
      console.error('Error fetching watch detail:', err);
      setDetailData(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Handle toggle watch
  const handleToggleWatch = useCallback(async (watchName) => {
    try {
      const res = await fetch(`http://localhost:5050/api/watchers/${encodeURIComponent(watchName)}/toggle`, {
        method: 'POST',
      });
      const data = await res.json();

      if (data.success) {
        // Refresh the list
        fetchWatches();
        // Refresh detail if the toggled watch is selected
        if (selectedWatch?.name === watchName) {
          fetchDetail(watchName);
        }
      } else {
        console.error('Failed to toggle watch:', data.error);
      }
    } catch (err) {
      console.error('Error toggling watch:', err);
    }
  }, [fetchWatches, fetchDetail, selectedWatch]);

  // Handle manual trigger
  const handleTriggerWatch = useCallback(async (watchName) => {
    try {
      const res = await fetch(`http://localhost:5050/api/watchers/${encodeURIComponent(watchName)}/trigger`, {
        method: 'POST',
      });
      const data = await res.json();

      if (data.success) {
        // Refresh detail to show new execution
        if (selectedWatch?.name === watchName) {
          fetchDetail(watchName);
        }
      } else {
        console.error('Failed to trigger watch:', data.error);
      }
    } catch (err) {
      console.error('Error triggering watch:', err);
    }
  }, [fetchDetail, selectedWatch]);

  // Handle delete watch
  const handleDeleteWatch = useCallback(async (watchName) => {
    if (!window.confirm(`Are you sure you want to delete watch "${watchName}"?`)) {
      return;
    }

    try {
      const res = await fetch(`http://localhost:5050/api/watchers/${encodeURIComponent(watchName)}`, {
        method: 'DELETE',
      });
      const data = await res.json();

      if (data.success) {
        // Clear selection if deleted watch was selected
        if (selectedWatch?.name === watchName) {
          setSelectedWatch(null);
          setDetailData(null);
        }
        // Refresh the list
        fetchWatches();
      } else {
        console.error('Failed to delete watch:', data.error);
      }
    } catch (err) {
      console.error('Error deleting watch:', err);
    }
  }, [fetchWatches, selectedWatch]);

  // Handle status tab change
  const handleStatusChange = useCallback((status) => {
    setActiveStatus(status);
    setSelectedWatch(null);
    setDetailData(null);
    try {
      localStorage.setItem(STORAGE_KEY_STATUS, status);
    } catch (e) {}
  }, []);

  // Handle search
  const handleSearchChange = useCallback((e) => {
    setSearchText(e.target.value);
  }, []);

  // Handle row click
  const handleRowClick = useCallback((event) => {
    const watch = event.data;
    setSelectedWatch(watch);
    fetchDetail(watch.name);
  }, [fetchDetail]);

  // Handle close detail panel
  const handleCloseDetail = useCallback(() => {
    setSelectedWatch(null);
    setDetailData(null);
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchWatches();
  }, [activeStatus]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchWatches();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  // Polling interval (30 seconds for watchers - they change more frequently)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchWatches();
      // Also refresh detail if a watch is selected
      if (selectedWatch) {
        fetchDetail(selectedWatch.name);
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [activeStatus, searchText, fetchWatches, fetchDetail, selectedWatch]);

  // Column definitions
  const columnDefs = useMemo(() => [
    {
      field: 'status',
      headerName: 'Status',
      width: 100,
      cellRenderer: (params) => {
        const config = STATUS_CONFIG[params.value] || STATUS_CONFIG.disabled;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Icon icon={config.icon} width={14} style={{ color: config.color }} />
            <span style={{ color: config.color, textTransform: 'capitalize', fontSize: '11px' }}>
              {params.value}
            </span>
          </div>
        );
      },
    },
    {
      field: 'name',
      headerName: 'Name',
      flex: 1,
      minWidth: 180,
      cellStyle: { color: '#f1f5f9', fontWeight: 500 },
    },
    {
      field: 'action_type',
      headerName: 'Action',
      width: 100,
      cellRenderer: (params) => {
        const color = ACTION_TYPE_COLORS[params.value] || ACTION_TYPE_COLORS.default;
        return (
          <span
            style={{
              color,
              fontSize: '11px',
              padding: '2px 6px',
              borderRadius: '4px',
              background: `${color}15`,
            }}
          >
            {params.value}
          </span>
        );
      },
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 2,
      minWidth: 200,
      cellStyle: { fontSize: '12px', color: '#94a3b8' },
      valueFormatter: (params) => {
        const desc = params.value || '';
        return desc.length > 100 ? desc.substring(0, 100) + '...' : desc;
      },
    },
    {
      field: 'poll_interval_seconds',
      headerName: 'Interval',
      width: 90,
      valueFormatter: (params) => {
        const secs = params.value || 0;
        if (secs < 60) return `${secs}s`;
        if (secs < 3600) return `${Math.floor(secs / 60)}m`;
        return `${Math.floor(secs / 3600)}h`;
      },
      cellStyle: { fontSize: '11px', color: '#64748b' },
    },
    {
      field: 'trigger_count',
      headerName: 'Triggers',
      width: 90,
      cellStyle: { fontSize: '11px', color: '#34d399', textAlign: 'right' },
    },
    {
      field: 'consecutive_errors',
      headerName: 'Errors',
      width: 80,
      cellRenderer: (params) => {
        const errors = params.value || 0;
        const color = errors > 0 ? '#f87171' : '#64748b';
        return (
          <span style={{ color, fontSize: '11px' }}>
            {errors}
          </span>
        );
      },
    },
    {
      field: 'last_checked_at',
      headerName: 'Last Check',
      width: 140,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const date = new Date(params.value);
        return date.toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });
      },
      cellStyle: { fontSize: '11px', color: '#64748b' },
    },
    {
      field: 'next_due',
      headerName: 'Next Due',
      width: 140,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const date = new Date(params.value);
        const now = new Date();
        const diff = date - now;
        if (diff < 0) return 'Overdue';
        if (diff < 60000) return `${Math.floor(diff / 1000)}s`;
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
        return date.toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
        });
      },
      cellStyle: { fontSize: '11px', color: '#64748b' },
    },
  ], []);

  // Calculate total count for tabs
  const getTotalCount = () => {
    return Object.values(statusCounts).reduce((sum, count) => sum + count, 0);
  };

  return (
    <div className={`watchers-view ${selectedWatch ? 'with-detail' : ''}`}>
      {/* Header */}
      <div className="watchers-header">
        <div className="watchers-header-left">
          <Icon icon="mdi:eye-circle" width={20} style={{ color: '#00e5ff' }} />
          <h1>Watchers</h1>
          <span className="watchers-subtitle">SQL Watch Subscriptions</span>
        </div>

        <div className="watchers-header-right">
          <div className="watchers-search">
            <Icon icon="mdi:magnify" width={16} style={{ color: '#64748b' }} />
            <input
              type="text"
              placeholder="Search by name, description..."
              value={searchText}
              onChange={handleSearchChange}
              className="watchers-search-input"
            />
            {searchText && (
              <button
                className="watchers-search-clear"
                onClick={() => setSearchText('')}
              >
                <Icon icon="mdi:close" width={14} />
              </button>
            )}
          </div>

          <div className="watchers-stats">
            <span className="watchers-stat">
              <Icon icon="mdi:counter" width={14} />
              {total} watches
            </span>
          </div>
        </div>
      </div>

      {/* Status Tabs */}
      <div className="watchers-tabs">
        {Object.entries(STATUS_CONFIG).map(([key, config]) => {
          const count = key === 'all' ? getTotalCount() : (statusCounts[key] || 0);

          return (
            <button
              key={key}
              className={`watchers-tab ${activeStatus === key ? 'active' : ''}`}
              onClick={() => handleStatusChange(key)}
            >
              <Icon icon={config.icon} width={14} style={{ color: activeStatus === key ? config.color : undefined }} />
              <span>{config.label}</span>
              <span className="watchers-tab-count">{count}</span>
            </button>
          );
        })}

        {/* Action type counts */}
        <div className="watchers-action-counts">
          {Object.entries(actionTypeCounts).map(([type, count]) => (
            <span key={type} className="watchers-action-count">
              <span
                className="watchers-action-dot"
                style={{ background: ACTION_TYPE_COLORS[type] || ACTION_TYPE_COLORS.default }}
              />
              {type}: {count}
            </span>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="watchers-content">
        {error && (
          <div className="watchers-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading watchers</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !watches.length && (
          <VideoLoader
            size="medium"
            message="Loading watchers..."
            className="video-loader--flex"
          />
        )}

        {!loading && !error && (
          <div className="watchers-grid-wrapper">
            <div className="watchers-grid-container">
              {watches.length === 0 ? (
                <div className="watchers-empty-state">
                  <Icon icon="mdi:eye-off" width={48} style={{ color: '#64748b' }} />
                  <p>No watches found</p>
                  <span>
                    {searchText
                      ? 'Try adjusting your search'
                      : 'Create a watch using the WATCH SQL command'}
                  </span>
                </div>
              ) : (
                <AgGridReact
                  theme={darkTheme}
                  rowData={watches}
                  columnDefs={columnDefs}
                  domLayout="normal"
                  suppressCellFocus={true}
                  enableCellTextSelection={true}
                  rowHeight={44}
                  headerHeight={40}
                  onRowClicked={handleRowClick}
                  rowStyle={{ cursor: 'pointer' }}
                  rowSelection="single"
                  getRowId={(params) => params.data.watch_id}
                  rowClass={(params) =>
                    selectedWatch?.watch_id === params.data.watch_id ? 'watchers-row-selected' : ''
                  }
                />
              )}
            </div>

            {/* Detail Panel */}
            {selectedWatch && (
              <WatchDetail
                watch={selectedWatch}
                detailData={detailData}
                loading={detailLoading}
                onClose={handleCloseDetail}
                onToggle={() => handleToggleWatch(selectedWatch.name)}
                onTrigger={() => handleTriggerWatch(selectedWatch.name)}
                onDelete={() => handleDeleteWatch(selectedWatch.name)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default WatchersView;
