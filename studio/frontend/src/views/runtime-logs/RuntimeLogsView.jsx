import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../components';
import RuntimeLogDetailPanel from './components/RuntimeLogDetailPanel';
import './RuntimeLogsView.css';
import { API_BASE_URL } from '../../config/api';

ModuleRegistry.registerModules([AllCommunityModule]);

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

const LEVEL_COLORS = {
  DEBUG: '#64748b',
  INFO: '#00e5ff',
  WARN: '#fbbf24',
  WARNING: '#fbbf24',
  ERROR: '#f87171',
  FATAL: '#f87171',
};

const STORAGE_KEY_RANGE_HOURS = 'runtimeLogs_rangeHours';

const getInitialRange = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_RANGE_HOURS);
    const val = stored ? parseInt(stored, 10) : NaN;
    if (Number.isFinite(val) && val > 0) return val;
  } catch (e) {}
  return 24;
};

const TIME_RANGES = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 24 * 7 },
  { label: '30d', hours: 24 * 30 },
];

const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

const MultiSelectFilter = ({ label, options, selected, onChange, color }) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleOption = (value) => {
    if (selected.includes(value)) {
      onChange(selected.filter(v => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  const clearAll = (e) => {
    e.stopPropagation();
    onChange([]);
  };

  return (
    <div className="runtime-logs-filter" ref={dropdownRef}>
      <button
        className={`runtime-logs-filter-btn ${selected.length > 0 ? 'active' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="runtime-logs-filter-label">{label}</span>
        {selected.length > 0 && (
          <span className="runtime-logs-filter-count" style={{ background: color || '#64748b' }}>
            {selected.length}
          </span>
        )}
        <Icon icon={isOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
      </button>
      {isOpen && (
        <div className="runtime-logs-filter-dropdown">
          <div className="runtime-logs-filter-header">
            <span>{label}</span>
            {selected.length > 0 && (
              <button className="runtime-logs-filter-clear" onClick={clearAll}>
                Clear
              </button>
            )}
          </div>
          <div className="runtime-logs-filter-options">
            {options.map(opt => (
              <label key={opt.value} className="runtime-logs-filter-option">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggleOption(opt.value)}
                />
                <span
                  className="runtime-logs-filter-option-label"
                  style={{ color: opt.color || '#94a3b8' }}
                  title={opt.value}
                >
                  {opt.label}
                </span>
                <span className="runtime-logs-filter-option-count">{opt.count}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const RuntimeLogsView = () => {
  const [rangeHours, setRangeHours] = useState(getInitialRange);
  const [searchText, setSearchText] = useState('');
  const [logs, setLogs] = useState([]);
  const [facets, setFacets] = useState({ levels: [], sources: [], events: [] });
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedLog, setSelectedLog] = useState(null);

  const [selectedLevels, setSelectedLevels] = useState([]);
  const [selectedSources, setSelectedSources] = useState([]);
  const [selectedEvents, setSelectedEvents] = useState([]);

  const fetchRuntimeLogs = useCallback(async (searchValue) => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      params.set('hours', String(rangeHours));
      params.set('limit', '500');
      params.set('offset', '0');
      params.set('include_facets', '1');

      const q = (searchValue ?? '').trim();
      if (q) params.set('search', q);
      selectedLevels.forEach(l => params.append('level', l));
      selectedSources.forEach(s => params.append('source', s));
      selectedEvents.forEach(e => params.append('event', e));

      const res = await fetch(`${API_BASE_URL}/api/runtime-logs?${params.toString()}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }

      setLogs(prev => isEqual(prev, data.logs) ? prev : (data.logs || []));
      setFacets(prev => isEqual(prev, data.facets) ? prev : (data.facets || { levels: [], sources: [], events: [] }));
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [rangeHours, selectedLevels, selectedSources, selectedEvents]);

  // Initial fetch + range/filter change (no debounce)
  useEffect(() => {
    fetchRuntimeLogs(searchText);
  }, [rangeHours, selectedLevels, selectedSources, selectedEvents]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchRuntimeLogs(searchText);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText, fetchRuntimeLogs]);

  const handleSearchChange = useCallback((e) => {
    setSearchText(e.target.value);
  }, []);

  const handleRefresh = useCallback(() => {
    fetchRuntimeLogs(searchText);
  }, [fetchRuntimeLogs, searchText]);

  const levelOptions = useMemo(() => {
    return (facets?.levels || []).map(({ value, count }) => ({
      value,
      label: value,
      count,
      color: LEVEL_COLORS[value] || '#94a3b8',
    }));
  }, [facets]);

  const sourceOptions = useMemo(() => {
    return (facets?.sources || []).map(({ value, count }) => ({
      value,
      label: value || '(empty)',
      count,
      color: '#94a3b8',
    }));
  }, [facets]);

  const eventOptions = useMemo(() => {
    return (facets?.events || [])
      .filter(x => x.value) // hide empty event by default
      .map(({ value, count }) => ({
        value,
        label: value.length > 40 ? value.slice(0, 37) + '...' : value,
        count,
        color: '#94a3b8',
      }));
  }, [facets]);

  const filteredCount = logs.length;

  const columnDefs = useMemo(() => [
    {
      field: 'timestamp',
      headerName: 'Time',
      width: 180,
      valueFormatter: (params) => {
        const v = params.value || params.data?.timestamp_iso;
        if (!v) return '-';
        const d = new Date(v);
        if (Number.isNaN(d.getTime())) return String(v);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      },
      cellStyle: { fontSize: '11px', color: '#94a3b8', fontFamily: "'Google Sans Code', monospace" },
    },
    {
      field: 'level',
      headerName: 'Level',
      width: 90,
      cellRenderer: (params) => {
        const level = (params.value || '').toUpperCase();
        const color = LEVEL_COLORS[level] || '#94a3b8';
        return (
          <span style={{ color, fontSize: '11px', fontWeight: 600 }}>
            {level || '-'}
          </span>
        );
      },
    },
    {
      field: 'event',
      headerName: 'Event',
      width: 180,
      cellStyle: { fontSize: '11px', color: '#cbd5e1' },
      tooltipField: 'event',
    },
    {
      field: 'message',
      headerName: 'Message',
      flex: 1,
      valueGetter: (params) => params.data?.message || '',
      cellRenderer: (params) => {
        const msg = params.value || '';
        const preview = msg.length > 180 ? msg.slice(0, 180) + '...' : msg;
        return (
          <span title={msg} style={{ color: '#94a3b8', fontSize: '11px' }}>
            {preview}
          </span>
        );
      },
    },
    {
      field: 'connection_id',
      headerName: 'Conn',
      width: 110,
      cellStyle: { fontSize: '11px', color: '#60a5fa', fontFamily: "'Google Sans Code', monospace" },
    },
    {
      field: 'thread_id',
      headerName: 'Thread',
      width: 110,
      cellStyle: { fontSize: '11px', color: '#64748b', fontFamily: "'Google Sans Code', monospace" },
    },
  ], []);

  const handleRowClick = useCallback((event) => {
    setSelectedLog(event.data);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedLog(null);
  }, []);

  const handleRangeChange = useCallback((hours) => {
    setRangeHours(hours);
    setSelectedLog(null);
    try {
      localStorage.setItem(STORAGE_KEY_RANGE_HOURS, String(hours));
    } catch (e) {}
  }, []);

  return (
    <div className={`runtime-logs-view ${selectedLog ? 'with-detail' : ''}`}>
      {/* Header */}
      <div className="runtime-logs-header">
        <div className="runtime-logs-header-left">
          <Icon icon="mdi:clipboard-text-outline" width={20} style={{ color: '#00e5ff' }} />
          <h1>Runtime Logs</h1>
          <span className="runtime-logs-subtitle">pgwire / server operational events</span>
        </div>

        <div className="runtime-logs-header-right">
          <div className="runtime-logs-search">
            <Icon icon="mdi:magnify" width={16} style={{ color: '#64748b' }} />
            <input
              type="text"
              placeholder="Search message, event, ids..."
              value={searchText}
              onChange={handleSearchChange}
              className="runtime-logs-search-input"
            />
            {searchText && (
              <button className="runtime-logs-search-clear" onClick={() => setSearchText('')}>
                <Icon icon="mdi:close" width={14} />
              </button>
            )}
          </div>

          <button className="runtime-logs-refresh" onClick={handleRefresh} title="Refresh">
            <Icon icon="mdi:refresh" width={16} />
            Refresh
          </button>

          <div className="runtime-logs-stats">
            <span className="runtime-logs-stat">
              <Icon icon="mdi:clock-outline" width={14} />
              {TIME_RANGES.find(r => r.hours === rangeHours)?.label || `${rangeHours}h`}
            </span>
            <span className="runtime-logs-stat">
              <Icon icon="mdi:counter" width={14} />
              {total.toLocaleString()} rows
            </span>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="runtime-logs-filter-bar">
        <div className="runtime-logs-filters">
          <div className="runtime-logs-filter">
            <button
              className="runtime-logs-filter-btn"
              onClick={() => {
                const currentIdx = TIME_RANGES.findIndex(r => r.hours === rangeHours);
                const next = TIME_RANGES[(currentIdx + 1) % TIME_RANGES.length];
                handleRangeChange(next.hours);
              }}
              title="Click to cycle time range"
            >
              <Icon icon="mdi:clock-outline" width={14} />
              <span className="runtime-logs-filter-label">Range</span>
              <span className="runtime-logs-filter-count" style={{ background: '#64748b' }}>
                {TIME_RANGES.find(r => r.hours === rangeHours)?.label || `${rangeHours}h`}
              </span>
            </button>
          </div>

          {levelOptions.length > 0 && (
            <MultiSelectFilter
              label="Level"
              options={levelOptions}
              selected={selectedLevels}
              onChange={setSelectedLevels}
              color="#00e5ff"
            />
          )}
          {sourceOptions.length > 1 && (
            <MultiSelectFilter
              label="Source"
              options={sourceOptions}
              selected={selectedSources}
              onChange={setSelectedSources}
              color="#94a3b8"
            />
          )}
          {eventOptions.length > 1 && (
            <MultiSelectFilter
              label="Event"
              options={eventOptions}
              selected={selectedEvents}
              onChange={setSelectedEvents}
              color="#a78bfa"
            />
          )}
        </div>

        <div className="runtime-logs-filter-summary">
          {(selectedLevels.length > 0 || selectedSources.length > 0 || selectedEvents.length > 0) && (
            <>
              <span className="runtime-logs-filter-showing">
                Showing {filteredCount} rows
              </span>
              <button
                className="runtime-logs-filter-clear-all"
                onClick={() => { setSelectedLevels([]); setSelectedSources([]); setSelectedEvents([]); }}
              >
                <Icon icon="mdi:close" width={12} />
                Clear filters
              </button>
            </>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="runtime-logs-content">
        {error && (
          <div className="runtime-logs-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading runtime logs</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !logs.length && (
          <VideoLoader size="medium" message="Loading runtime logs..." className="video-loader--flex" />
        )}

        {!loading && !error && (
          <div className="runtime-logs-grid-wrapper">
            <div className="runtime-logs-grid-container">
              {logs.length === 0 ? (
                <div className="runtime-logs-empty-state">
                  <Icon icon="mdi:clipboard-text-off-outline" width={48} style={{ color: '#64748b' }} />
                  <p>No logs found</p>
                  <span>
                    {searchText ? 'Try adjusting your search' : 'Try increasing the time range'}
                  </span>
                </div>
              ) : (
                <AgGridReact
                  theme={darkTheme}
                  rowData={logs}
                  columnDefs={columnDefs}
                  domLayout="normal"
                  suppressCellFocus={true}
                  enableCellTextSelection={true}
                  rowHeight={44}
                  headerHeight={40}
                  onRowClicked={handleRowClick}
                  rowStyle={{ cursor: 'pointer' }}
                  rowSelection="single"
                  getRowId={(params) => params.data.event_id}
                  rowClass={(params) => selectedLog?.event_id === params.data.event_id ? 'runtime-logs-row-selected' : ''}
                />
              )}
            </div>

            {selectedLog && (
              <RuntimeLogDetailPanel
                log={selectedLog}
                loading={false}
                onClose={handleCloseDetail}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RuntimeLogsView;
