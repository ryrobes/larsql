import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, AreaChart, Area
} from 'recharts';
import { VideoLoader } from '../../components';
import TestDetailPanel from './components/TestDetailPanel';
import './TestsView.css';

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
  accentColor: '#34d399',
  chromeBackgroundColor: '#000000',
});

// Deep equality check for data comparison
const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

// Test type configuration
const TEST_TYPES = {
  all: { label: 'All Tests', icon: 'mdi:test-tube', color: '#94a3b8' },
  semantic_sql: { label: 'Semantic SQL', icon: 'mdi:database-search', color: '#60a5fa' },
  cascade_snapshot: { label: 'Snapshots', icon: 'mdi:camera', color: '#a78bfa' },
};

// Status colors
const STATUS_COLORS = {
  passed: '#34d399',
  failed: '#f87171',
  error: '#fb923c',
  skipped: '#64748b',
  running: '#fbbf24',
  pending: '#94a3b8',
};

// localStorage key
const STORAGE_KEY_TYPE = 'tests_type';

const getInitialType = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_TYPE);
    if (stored && TEST_TYPES[stored]) return stored;
  } catch (e) {}
  return 'all';
};

/**
 * Mini Dashboard Chart Component
 */
const MiniChart = ({ data, title, icon, color, type = 'area' }) => {
  if (!data || data.length === 0) {
    return (
      <div className="tests-mini-chart">
        <div className="tests-mini-chart-header">
          <Icon icon={icon} width={14} style={{ color }} />
          <span>{title}</span>
        </div>
        <div className="tests-mini-chart-empty">No data</div>
      </div>
    );
  }

  return (
    <div className="tests-mini-chart">
      <div className="tests-mini-chart-header">
        <Icon icon={icon} width={14} style={{ color }} />
        <span>{title}</span>
      </div>
      <div className="tests-mini-chart-content">
        <ResponsiveContainer width="100%" height={60}>
          {type === 'bar' ? (
            <BarChart data={data}>
              <Bar dataKey="value" fill={color} radius={[2, 2, 0, 0]} />
              <Tooltip
                contentStyle={{ background: '#1a1a1f', border: 'none', borderRadius: 6, fontSize: 11 }}
                labelStyle={{ color: '#94a3b8' }}
              />
            </BarChart>
          ) : (
            <AreaChart data={data}>
              <defs>
                <linearGradient id={`gradient-${title.replace(/\s/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={color} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="value"
                stroke={color}
                fill={`url(#gradient-${title.replace(/\s/g, '')})`}
                strokeWidth={1.5}
              />
              <Tooltip
                contentStyle={{ background: '#1a1a1f', border: 'none', borderRadius: 6, fontSize: 11 }}
                labelStyle={{ color: '#94a3b8' }}
              />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
};

/**
 * Stats Card Component
 */
const StatCard = ({ label, value, icon, color, subtext, onClick, active, clickable }) => (
  <div
    className={`tests-stat-card ${clickable ? 'clickable' : ''} ${active ? 'active' : ''}`}
    onClick={onClick}
    style={active ? { borderColor: color, background: `${color}10` } : {}}
  >
    <div className="tests-stat-icon" style={{ background: `${color}15`, color }}>
      <Icon icon={icon} width={18} />
    </div>
    <div className="tests-stat-content">
      <div className="tests-stat-value" style={{ color }}>{value}</div>
      <div className="tests-stat-label">{label}</div>
      {subtext && <div className="tests-stat-subtext">{subtext}</div>}
    </div>
  </div>
);

/**
 * MultiSelect Filter Component (from CatalogView)
 */
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
    <div className="tests-filter" ref={dropdownRef}>
      <button
        className={`tests-filter-btn ${selected.length > 0 ? 'active' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="tests-filter-label">{label}</span>
        {selected.length > 0 && (
          <span className="tests-filter-count" style={{ background: color || '#64748b' }}>
            {selected.length}
          </span>
        )}
        <Icon icon={isOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
      </button>
      {isOpen && (
        <div className="tests-filter-dropdown">
          <div className="tests-filter-header">
            <span>{label}</span>
            {selected.length > 0 && (
              <button className="tests-filter-clear" onClick={clearAll}>
                Clear
              </button>
            )}
          </div>
          <div className="tests-filter-options">
            {options.map(opt => (
              <label key={opt.value} className="tests-filter-option">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggleOption(opt.value)}
                />
                <span
                  className="tests-filter-option-label"
                  style={{ color: opt.color || '#94a3b8' }}
                >
                  {opt.label}
                </span>
                <span className="tests-filter-option-count">{opt.count}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * TestsView - Test Dashboard
 */
const TestsView = () => {
  const [activeType, setActiveType] = useState(getInitialType);
  const [searchText, setSearchText] = useState('');
  const [counts, setCounts] = useState({});
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedTest, setSelectedTest] = useState(null);
  const [selectedStatuses, setSelectedStatuses] = useState([]);
  const [selectedGroups, setSelectedGroups] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [ssqlMode, setSsqlMode] = useState('internal');  // internal, simple, extended
  const [snapshotMode, setSnapshotMode] = useState('structure');  // structure, contracts, anchors, deterministic, full

  // Store raw test definitions (without status)
  const [rawTests, setRawTests] = useState([]);

  // History for sparklines (test_id -> [{status, run_id}])
  const [testHistory, setTestHistory] = useState({});

  // Status filter from dashboard cards (null = no filter)
  const [statusFilter, setStatusFilter] = useState(null);

  // Fetch tests (without status - status computed separately)
  const fetchTests = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (activeType !== 'all') {
        params.set('type', activeType);
      }
      if (searchText.trim()) {
        params.set('filter', searchText.trim());
      }

      const res = await fetch(`http://localhost:5050/api/tests?${params.toString()}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Flatten tests for grid (without status)
      const allTests = [];
      for (const [type, typeTests] of Object.entries(data.tests || {})) {
        for (const test of typeTests) {
          allTests.push({
            ...test,
            _type: type
          });
        }
      }

      setRawTests(prev => isEqual(prev, allTests) ? prev : allTests);
      setCounts(data.counts || {});
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeType, searchText]);

  // Compute tests with status from testHistory (most recent result per test)
  const tests = useMemo(() => {
    return rawTests.map(test => {
      // Get status from history - use first result from any mode (newest first)
      const modeHistory = testHistory[test.test_id] || {};
      const modes = Object.values(modeHistory);
      const mostRecent = modes.length > 0 ? modes[0][0] : null;
      return {
        ...test,
        _status: mostRecent?.status || 'pending'
      };
    });
  }, [rawTests, testHistory]);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:5050/api/tests/stats?days=7');
      const data = await res.json();
      if (!data.error) {
        setStats(data);
      }
    } catch (err) {
      console.error('Error fetching stats:', err);
    }
  }, []);

  // Fetch bulk history for sparklines
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:5050/api/tests/history/bulk?limit=10');
      const data = await res.json();
      if (!data.error && data.history) {
        setTestHistory(data.history);
      }
    } catch (err) {
      console.error('Error fetching test history:', err);
    }
  }, []);

  // Fetch most recent run to get last known statuses
  const fetchLastRun = useCallback(async () => {
    try {
      // Get the most recent run
      const runsRes = await fetch('http://localhost:5050/api/tests/runs?limit=1');
      const runsData = await runsRes.json();

      if (runsData.runs && runsData.runs.length > 0) {
        const latestRunId = runsData.runs[0].run_id;
        // Fetch the full run with results
        const runRes = await fetch(`http://localhost:5050/api/tests/runs/${latestRunId}`);
        const runData = await runRes.json();

        if (!runData.error && runData.results) {
          // Normalize field names to match runTests output
          setLastRun({
            ...runData.run,
            passed: runData.run.passed_tests,
            failed: runData.run.failed_tests,
            total: runData.run.total_tests,
            results: runData.results
          });
        }
      }
    } catch (err) {
      console.error('Error fetching last run:', err);
    }
  }, []);

  // Handle type change
  const handleTypeChange = useCallback((type) => {
    setActiveType(type);
    setSelectedTest(null);
    setSelectedStatuses([]);
    setSelectedGroups([]);
    try {
      localStorage.setItem(STORAGE_KEY_TYPE, type);
    } catch (e) {}
  }, []);

  // Compute available filters
  const { statusOptions, groupOptions } = useMemo(() => {
    const statusCounts = {};
    const groupCounts = {};

    tests.forEach(test => {
      const status = test._status || 'pending';
      statusCounts[status] = (statusCounts[status] || 0) + 1;

      const group = test.test_group || 'unknown';
      groupCounts[group] = (groupCounts[group] || 0) + 1;
    });

    const statusOptions = Object.entries(statusCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({
        value,
        label: value,
        count,
        color: STATUS_COLORS[value] || STATUS_COLORS.pending
      }));

    const groupOptions = Object.entries(groupCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([value, count]) => ({
        value,
        label: value.length > 30 ? '...' + value.slice(-27) : value,
        count,
        color: '#94a3b8'
      }));

    return { statusOptions, groupOptions };
  }, [tests]);

  // Filter tests (without status filter - used for status counts)
  const preStatusFilteredTests = useMemo(() => {
    let result = tests;

    if (selectedStatuses.length > 0) {
      result = result.filter(t => selectedStatuses.includes(t._status));
    }

    if (selectedGroups.length > 0) {
      result = result.filter(t => selectedGroups.includes(t.test_group));
    }

    return result;
  }, [tests, selectedStatuses, selectedGroups]);

  // Compute current status counts from pre-filtered tests (for dashboard cards)
  const currentStatusCounts = useMemo(() => {
    const counts = { passed: 0, failed: 0, error: 0, skipped: 0, pending: 0 };
    preStatusFilteredTests.forEach(t => {
      const status = t._status || 'pending';
      if (counts[status] !== undefined) {
        counts[status]++;
      }
    });
    return counts;
  }, [preStatusFilteredTests]);

  // Filter tests (with status filter)
  const filteredTests = useMemo(() => {
    let result = preStatusFilteredTests;

    // Dashboard status filter (single status)
    if (statusFilter) {
      result = result.filter(t => t._status === statusFilter);
    }

    return result;
  }, [preStatusFilteredTests, statusFilter]);

  // Run tests - can run specific IDs, or all filtered tests
  const runTests = useCallback(async (testIds = null) => {
    setIsRunning(true);
    setRunResult(null);

    try {
      // If no specific testIds provided, run filtered tests
      const idsToRun = testIds || filteredTests.map(t => t.test_id);

      const body = {
        test_ids: idsToRun,
        ssql_mode: ssqlMode,
        snapshot_mode: snapshotMode
      };

      const res = await fetch('http://localhost:5050/api/tests/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        console.log('[TestsView] Run complete:', data);
        setRunResult(data);
        setLastRun(data);  // Status computed via useMemo from lastRun

        // Refresh stats and history after run
        fetchStats();
        fetchHistory();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsRunning(false);
    }
  }, [filteredTests, fetchStats, ssqlMode, snapshotMode]);

  // Determine if we have an active filter (type, search, status, or group filters)
  const hasActiveFilter = activeType !== 'all' || searchText.trim() || statusFilter || selectedStatuses.length > 0 || selectedGroups.length > 0;
  const runButtonLabel = hasActiveFilter ? `Run These (${filteredTests.length})` : 'Run All';

  // Toggle status filter from dashboard cards
  const toggleStatusFilter = useCallback((status) => {
    setStatusFilter(prev => prev === status ? null : status);
  }, []);

  // Prepare chart data from stats
  const chartData = useMemo(() => {
    if (!stats?.daily_trends) return { passed: [], failed: [], runs: [] };

    const passed = stats.daily_trends.map(d => ({
      date: d.date,
      value: d.passed || 0
    }));

    const failed = stats.daily_trends.map(d => ({
      date: d.date,
      value: (d.failed || 0) + (d.errors || 0)
    }));

    const runs = stats.daily_trends.map(d => ({
      date: d.date,
      value: d.run_count || 0
    }));

    return { passed, failed, runs };
  }, [stats]);

  // Total stats
  const totalStats = useMemo(() => {
    if (!stats?.daily_trends) return { passed: 0, failed: 0, runs: 0 };

    return stats.daily_trends.reduce((acc, d) => ({
      passed: acc.passed + (d.passed || 0),
      failed: acc.failed + (d.failed || 0) + (d.errors || 0),
      runs: acc.runs + (d.run_count || 0)
    }), { passed: 0, failed: 0, runs: 0 });
  }, [stats]);

  // Initial fetch - get last run first so we have statuses
  useEffect(() => {
    const init = async () => {
      await fetchLastRun();
      fetchStats();
      fetchHistory();
    };
    init();
  }, []);

  // Fetch tests when lastRun is loaded (or on mount if no history)
  useEffect(() => {
    fetchTests();
  }, [lastRun]);

  // Fetch on type change
  useEffect(() => {
    fetchTests();
  }, [activeType]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchTests();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  // Polling interval (30 seconds)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchLastRun();  // Refresh statuses from latest run
      fetchStats();
      fetchHistory();  // Refresh sparklines
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Column definitions
  const columnDefs = useMemo(() => [
    {
      field: '_status',
      headerName: 'Status',
      width: 100,
      cellRenderer: (params) => {
        const status = params.value || 'pending';
        const color = STATUS_COLORS[status] || STATUS_COLORS.pending;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: color,
                flexShrink: 0
              }}
            />
            <span style={{ color, fontSize: '11px', textTransform: 'capitalize' }}>
              {status}
            </span>
          </div>
        );
      },
    },
    {
      field: 'test_id',
      headerName: 'History',
      width: 140,
      cellRenderer: (params) => {
        const modeHistory = testHistory[params.value] || {};
        const modes = Object.keys(modeHistory);

        if (modes.length === 0) {
          return (
            <div className="tests-sparkline-container" title="No history">
              <span style={{ color: '#475569', fontSize: '10px' }}>—</span>
            </div>
          );
        }

        // Mode abbreviations for compact display
        const modeAbbrev = {
          'internal': 'int',
          'simple': 'sim',
          'extended': 'ext',
          'structure': 'str',
          'contracts': 'con',
          'anchors': 'anc',
          'deterministic': 'det',
          'full': 'ful'
        };

        // Sort modes in a sensible order
        const modeOrder = ['internal', 'simple', 'extended', 'structure', 'contracts', 'anchors', 'deterministic', 'full'];
        const sortedModes = modes.sort((a, b) => {
          const aIdx = modeOrder.indexOf(a);
          const bIdx = modeOrder.indexOf(b);
          return (aIdx === -1 ? 999 : aIdx) - (bIdx === -1 ? 999 : bIdx);
        });

        return (
          <div className="tests-sparkline-container">
            {sortedModes.map(mode => {
              const runs = modeHistory[mode] || [];
              // Show oldest to newest (reverse since API returns newest first)
              const reversed = [...runs].reverse();
              const passCount = runs.filter(h => h.status === 'passed').length;

              return (
                <div
                  key={mode}
                  className="tests-sparkline-row"
                  title={`${mode}: ${passCount}/${runs.length} passed`}
                >
                  <span className="tests-sparkline-mode">{modeAbbrev[mode] || mode.slice(0, 3)}</span>
                  <div className="tests-sparkline">
                    {reversed.map((h, i) => (
                      <span
                        key={i}
                        className="tests-sparkline-block"
                        style={{
                          background: STATUS_COLORS[h.status] || STATUS_COLORS.pending
                        }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        );
      },
    },
    {
      field: 'test_type',
      headerName: 'Type',
      width: 130,
      cellRenderer: (params) => {
        const config = TEST_TYPES[params.value] || TEST_TYPES.all;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Icon icon={config.icon} width={14} style={{ color: config.color }} />
            <span style={{ color: config.color, fontSize: '11px' }}>
              {params.value === 'semantic_sql' ? 'SQL' : 'Snapshot'}
            </span>
          </div>
        );
      },
      hide: activeType !== 'all',
    },
    {
      field: 'test_name',
      headerName: 'Name',
      flex: 1,
      minWidth: 200,
      cellStyle: { color: '#f1f5f9', fontWeight: 500 },
    },
    {
      field: 'test_group',
      headerName: 'Group',
      width: 200,
      cellStyle: { fontSize: '12px', color: '#94a3b8' },
      valueFormatter: (params) => {
        const group = params.value || '';
        return group.length > 30 ? '...' + group.slice(-27) : group;
      },
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 2,
      minWidth: 250,
      cellStyle: { fontSize: '12px', color: '#64748b' },
      valueFormatter: (params) => {
        const desc = params.value || '';
        return desc.length > 100 ? desc.substring(0, 100) + '...' : desc;
      },
    },
    {
      field: 'source_file',
      headerName: 'Source',
      width: 180,
      cellStyle: { fontSize: '11px', color: '#64748b' },
      valueFormatter: (params) => {
        const src = params.value || '';
        if (src.length > 30) {
          return '...' + src.substring(src.length - 27);
        }
        return src;
      },
    },
  ], [activeType, testHistory]);

  // Get total count
  const getTotalCount = () => {
    return Object.values(counts).reduce((sum, count) => sum + count, 0);
  };

  // Handle row click
  const handleRowClick = useCallback((event) => {
    setSelectedTest(event.data);
  }, []);

  // Handle close detail panel
  const handleCloseDetail = useCallback(() => {
    setSelectedTest(null);
  }, []);

  return (
    <div className={`tests-view ${selectedTest ? 'with-detail' : ''}`}>
      {/* Header */}
      <div className="tests-header">
        <div className="tests-header-left">
          <Icon icon="mdi:test-tube" width={20} style={{ color: '#34d399' }} />
          <h1>Tests</h1>
          <span className="tests-subtitle">Test Dashboard</span>
        </div>

        <div className="tests-header-right">
          <div className="tests-search">
            <Icon icon="mdi:magnify" width={16} style={{ color: '#64748b' }} />
            <input
              type="text"
              placeholder="Search tests..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="tests-search-input"
            />
            {searchText && (
              <button
                className="tests-search-clear"
                onClick={() => setSearchText('')}
              >
                <Icon icon="mdi:close" width={14} />
              </button>
            )}
          </div>

          {/* Mode Selectors */}
          <div className="tests-mode-selectors">
            <select
              className="tests-mode-select"
              value={ssqlMode}
              onChange={(e) => setSsqlMode(e.target.value)}
              title="SQL Test Mode"
            >
              <option value="internal">SQL: Internal</option>
              <option value="simple">SQL: Simple</option>
              <option value="extended">SQL: Extended</option>
              <option value="full">SQL: Full (all 3)</option>
            </select>
            <select
              className="tests-mode-select"
              value={snapshotMode}
              onChange={(e) => setSnapshotMode(e.target.value)}
              title="Snapshot Test Mode"
            >
              <option value="structure">Snapshot: Structure</option>
              <option value="contracts">Snapshot: Contracts</option>
              <option value="anchors">Snapshot: Anchors</option>
              <option value="deterministic">Snapshot: Deterministic</option>
              <option value="full">Snapshot: Full</option>
            </select>
          </div>

          <button
            className={`tests-run-btn ${isRunning ? 'running' : ''} ${hasActiveFilter ? 'filtered' : ''}`}
            onClick={() => runTests()}
            disabled={isRunning || filteredTests.length === 0}
          >
            <Icon icon={isRunning ? 'mdi:loading' : 'mdi:play'} width={16} className={isRunning ? 'spin' : ''} />
            <span>{isRunning ? 'Running...' : runButtonLabel}</span>
          </button>

          <div className="tests-stats">
            <span className="tests-stat">
              <Icon icon="mdi:counter" width={14} />
              {getTotalCount().toLocaleString()} tests
            </span>
          </div>
        </div>
      </div>

      {/* Mini Dashboard */}
      <div className="tests-dashboard">
        <div className="tests-dashboard-stats">
          <StatCard
            label="Passed"
            value={currentStatusCounts.passed.toLocaleString()}
            icon="mdi:check-circle"
            color="#34d399"
            clickable
            active={statusFilter === 'passed'}
            onClick={() => toggleStatusFilter('passed')}
          />
          <StatCard
            label="Failed"
            value={currentStatusCounts.failed.toLocaleString()}
            icon="mdi:close-circle"
            color="#f87171"
            clickable
            active={statusFilter === 'failed'}
            onClick={() => toggleStatusFilter('failed')}
          />
          <StatCard
            label="Error"
            value={currentStatusCounts.error.toLocaleString()}
            icon="mdi:alert-circle"
            color="#fb923c"
            clickable
            active={statusFilter === 'error'}
            onClick={() => toggleStatusFilter('error')}
          />
          <StatCard
            label="Skipped"
            value={currentStatusCounts.skipped.toLocaleString()}
            icon="mdi:skip-next-circle"
            color="#64748b"
            clickable
            active={statusFilter === 'skipped'}
            onClick={() => toggleStatusFilter('skipped')}
          />
          {lastRun && (
            <StatCard
              label="Last Run"
              value={`${lastRun.passed}/${lastRun.total}`}
              icon="mdi:clock-check"
              color={lastRun.status === 'passed' ? '#34d399' : '#f87171'}
              subtext={`${Math.round(lastRun.duration_ms)}ms`}
            />
          )}
        </div>

        <div className="tests-dashboard-charts">
          <MiniChart
            data={chartData.passed}
            title="Passed"
            icon="mdi:check-circle"
            color="#34d399"
            type="area"
          />
          <MiniChart
            data={chartData.failed}
            title="Failed"
            icon="mdi:close-circle"
            color="#f87171"
            type="area"
          />
          <MiniChart
            data={chartData.runs}
            title="Runs"
            icon="mdi:play-circle"
            color="#60a5fa"
            type="bar"
          />
        </div>
      </div>

      {/* Type Tabs */}
      <div className="tests-tabs">
        {Object.entries(TEST_TYPES).map(([key, config]) => {
          const count = key === 'all' ? getTotalCount() : (counts[key] || 0);
          if (key !== 'all' && count === 0) return null;

          return (
            <button
              key={key}
              className={`tests-tab ${activeType === key ? 'active' : ''}`}
              onClick={() => handleTypeChange(key)}
            >
              <Icon icon={config.icon} width={14} style={{ color: activeType === key ? config.color : undefined }} />
              <span>{config.label}</span>
              <span className="tests-tab-count">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Filter Bar */}
      {tests.length > 0 && (
        <div className="tests-filter-bar">
          <div className="tests-filters">
            {statusOptions.length > 1 && (
              <MultiSelectFilter
                label="Status"
                options={statusOptions}
                selected={selectedStatuses}
                onChange={setSelectedStatuses}
                color={TEST_TYPES[activeType]?.color || '#64748b'}
              />
            )}
            {groupOptions.length > 1 && (
              <MultiSelectFilter
                label="Group"
                options={groupOptions}
                selected={selectedGroups}
                onChange={setSelectedGroups}
                color="#64748b"
              />
            )}
          </div>
          <div className="tests-filter-summary">
            {statusFilter && (
              <span className="tests-filter-badge" style={{ background: `${STATUS_COLORS[statusFilter]}20`, color: STATUS_COLORS[statusFilter] }}>
                {statusFilter}
                <button onClick={() => setStatusFilter(null)}>
                  <Icon icon="mdi:close" width={10} />
                </button>
              </span>
            )}
            {(statusFilter || selectedStatuses.length > 0 || selectedGroups.length > 0) && (
              <>
                <span className="tests-filter-showing">
                  Showing {filteredTests.length} of {tests.length}
                </span>
                <button
                  className="tests-filter-clear-all"
                  onClick={() => { setStatusFilter(null); setSelectedStatuses([]); setSelectedGroups([]); }}
                >
                  <Icon icon="mdi:close" width={12} />
                  Clear all
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="tests-content">
        {error && (
          <div className="tests-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading tests</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !tests.length && (
          <VideoLoader
            size="medium"
            message="Loading tests..."
            className="video-loader--flex"
          />
        )}

        {!loading && !error && (
          <div className="tests-grid-wrapper">
            <div className="tests-grid-container">
              {filteredTests.length === 0 ? (
                <div className="tests-empty-state">
                  <Icon icon="mdi:test-tube-off" width={48} style={{ color: '#64748b' }} />
                  <p>No tests found</p>
                  <span>
                    {selectedStatuses.length > 0 || selectedGroups.length > 0
                      ? 'Try adjusting your filters'
                      : searchText
                        ? 'Try adjusting your search'
                        : 'No tests discovered yet'}
                  </span>
                </div>
              ) : (
                <AgGridReact
                  key={`grid-${Object.values(testHistory).reduce((sum, modes) => sum + Object.keys(modes).length, 0)}`}
                  theme={darkTheme}
                  rowData={filteredTests}
                  columnDefs={columnDefs}
                  domLayout="normal"
                  suppressCellFocus={true}
                  enableCellTextSelection={true}
                  getRowHeight={(params) => {
                    // Dynamic height based on number of modes in history
                    const modeHistory = testHistory[params.data.test_id] || {};
                    const modeCount = Object.keys(modeHistory).length;
                    // Base height 36, add 15px per mode row (min 1)
                    // 5 modes = 20 + 5*15 = 95px
                    return Math.max(36, 20 + Math.max(1, modeCount) * 15);
                  }}
                  headerHeight={40}
                  onRowClicked={handleRowClick}
                  rowStyle={{ cursor: 'pointer' }}
                  rowSelection="single"
                  getRowId={(params) => params.data.test_id}
                  rowClass={(params) =>
                    selectedTest?.test_id === params.data.test_id ? 'tests-row-selected' : ''
                  }
                />
              )}
            </div>

            {/* Detail Panel */}
            {selectedTest && (
              <TestDetailPanel
                test={selectedTest}
                lastRun={lastRun}
                onClose={handleCloseDetail}
                onRun={(testId) => runTests([testId])}
                isRunning={isRunning}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default TestsView;
