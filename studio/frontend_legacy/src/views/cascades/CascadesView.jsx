import React, { useState, useEffect, useRef, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Button } from '../../components';
import useNavigationStore from '../../stores/navigationStore';
import useStudioCascadeStore from '../../studio/stores/studioCascadeStore';
import CostTimelineChart from '../../components/CostTimelineChart';
import './CascadesView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching other views
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
 * CascadesView - Browse cascade definitions and their execution history
 *
 * Two-page design:
 * 1. All cascades grid with aggregate metrics
 * 2. Cascade instances grid (when cascade selected)
 */
const CascadesView = ({ navigate, params = {} }) => {
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [cascades, setCascades] = useState([]);
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [gridHeight, setGridHeight] = useState(600);
  const gridRef = useRef(null);
  const containerRef = useRef(null);
  const { navigate: navStore } = useNavigationStore();

  // Filter state
  const [filters, setFilters] = useState({
    search: '',
    runCount: new Set(),     // '0', '1-10', '11-50', '50+'
    costRange: new Set(),    // '$0', '$0-$1', '$1-$10', '$10+'
    status: new Set(),       // For instances: 'completed', 'error', 'running', etc.
    hasCandidates: null,     // null | true | false
    hasSubCascades: null,    // null | true | false
  });

  // Handle loading cascade into Studio for first run
  const handleLoadInStudio = async () => {
    if (!selectedCascade) return;

    try {
      // Find the cascade definition to get its file path
      const cascade = cascades.find(c => c.cascade_id === selectedCascade);
      if (cascade && cascade.cascade_file) {
        console.log('[CascadesView] Loading cascade into Studio:', cascade.cascade_id, 'from', cascade.cascade_file);

        // Directly load the cascade using Studio store
        const { loadCascade, setMode } = useStudioCascadeStore.getState();
        await loadCascade(cascade.cascade_file);
        setMode('timeline');

        // Then navigate to Studio (will show the loaded cascade)
        navStore('studio', {});
      } else {
        console.warn('[CascadesView] Could not find cascade file for:', selectedCascade);
        // Fallback: navigate with cascade param, let Studio handle it
        navStore('studio', { cascade: selectedCascade });
      }
    } catch (err) {
      console.error('[CascadesView] Error loading cascade:', err);
    }
  };

  // Fetch all cascades
  const fetchCascades = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://localhost:5050/api/cascade-definitions');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setCascades(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch instances for selected cascade
  const fetchInstances = async (cascadeId) => {
    try {
      setLoading(true);
      // Use sessions API instead - much faster (no expensive batch queries)
      const res = await fetch(`http://localhost:5050/api/sessions?cascade_id=${cascadeId}&limit=100`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Transform sessions API response to match expected format
      const transformed = (data.sessions || []).map(session => ({
        session_id: session.session_id,
        cascade_id: session.cascade_id,
        status: session.status,
        total_cost: session.total_cost || 0,
        duration_seconds: session.started_at && session.completed_at
          ? (new Date(session.completed_at) - new Date(session.started_at)) / 1000
          : 0,
        input_data: session.input_data,
        start_time: session.started_at,
        end_time: session.completed_at,
        message_count: session.message_count || 0,
        // Include percentage differences (calculated by backend)
        cost_diff_pct: session.cost_diff_pct,
        messages_diff_pct: session.messages_diff_pct,
        duration_diff_pct: session.duration_diff_pct,
      }));

      setInstances(transformed);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Initialize from URL params
  useEffect(() => {
    if (params.cascade || params.id) {
      const cascadeId = params.cascade || params.id;
      setSelectedCascade(cascadeId);
    }
  }, [params.cascade, params.id]);

  // Initial load
  useEffect(() => {
    fetchCascades();
  }, []);

  // Load instances when cascade selected
  useEffect(() => {
    if (selectedCascade) {
      fetchInstances(selectedCascade);
    }
  }, [selectedCascade]);

  // Calculate grid height based on viewport
  useEffect(() => {
    const calculateGridHeight = () => {
      if (!containerRef.current) return;

      const viewportHeight = window.innerHeight;
      const containerTop = containerRef.current.getBoundingClientRect().top;
      const availableHeight = viewportHeight - containerTop - 20;
      const newHeight = Math.max(400, Math.min(availableHeight, viewportHeight * 0.7));

      setGridHeight(newHeight);
    };

    calculateGridHeight();
    window.addEventListener('resize', calculateGridHeight);
    const timeout = setTimeout(calculateGridHeight, 100);

    return () => {
      window.removeEventListener('resize', calculateGridHeight);
      clearTimeout(timeout);
    };
  }, [selectedCascade]); // Recalculate when view changes

  // Cascades grid columns
  const cascadeColumns = useMemo(() => [
    {
      field: 'cascade_id',
      headerName: 'Cascade ID',
      flex: 2,
      minWidth: 180,
      cellClass: 'cascades-id',
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 3,
      minWidth: 200,
    },
    {
      field: 'metrics.run_count',
      headerName: 'Runs',
      width: 90,
      valueFormatter: (params) => params.value || 0,
      cellStyle: { fontFamily: 'var(--font-mono)' },
    },
    {
      field: 'metrics.total_cost',
      headerName: 'Total Cost',
      width: 120,
      valueFormatter: (params) => {
        const cost = params.value || 0;
        return cost > 0 ? `$${cost.toFixed(6)}` : '-';
      },
      cellStyle: { color: '#34d399', fontFamily: 'var(--font-mono)' },
    },
    {
      field: 'metrics.avg_duration_seconds',
      headerName: 'Avg Duration',
      width: 120,
      valueFormatter: (params) => {
        const secs = params.value || 0;
        if (secs === 0) return '-';
        if (secs < 60) return `${Math.round(secs)}s`;
        const mins = Math.floor(secs / 60);
        const remainingSecs = Math.round(secs % 60);
        return `${mins}m ${remainingSecs}s`;
      },
      cellStyle: { fontFamily: 'var(--font-mono)' },
    },
    {
      field: 'latest_run',
      headerName: 'Latest Run',
      flex: 1.5,
      minWidth: 160,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        return new Date(params.value).toLocaleString();
      },
    },
  ], []);

  // Instances grid columns
  const instanceColumns = useMemo(() => [
    {
      field: 'session_id',
      headerName: 'Session ID',
      flex: 2,
      minWidth: 180,
      cellClass: 'cascades-session-id',
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 100,
      cellRenderer: (params) => {
        const status = params.value?.toLowerCase();
        const colorMap = {
          running: '#00e5ff',
          completed: '#34d399',
          error: '#ff006e',
          cancelled: '#64748b',
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
      field: 'duration_seconds',
      headerName: 'Duration',
      width: 100,
      valueFormatter: (params) => {
        const secs = params.value || 0;
        if (secs === 0) return '-';
        if (secs < 60) return `${Math.round(secs)}s`;
        const mins = Math.floor(secs / 60);
        const remainingSecs = Math.round(secs % 60);
        return `${mins}m ${remainingSecs}s`;
      },
      cellStyle: { fontFamily: 'var(--font-mono)' },
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
      field: 'input_data',
      headerName: 'Inputs',
      flex: 2,
      minWidth: 150,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        try {
          const inputs = typeof params.value === 'string' ? JSON.parse(params.value) : params.value;
          if (typeof inputs === 'object' && inputs !== null) {
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
      field: 'start_time',
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
  }), []);

  // Apply filters to cascades
  const filteredCascades = useMemo(() => {
    return cascades.filter(cascade => {
      // Search filter
      if (filters.search) {
        const searchLower = filters.search.toLowerCase();
        const matchesId = cascade.cascade_id?.toLowerCase().includes(searchLower);
        const matchesDesc = cascade.description?.toLowerCase().includes(searchLower);
        if (!matchesId && !matchesDesc) return false;
      }

      // Run count ranges
      if (filters.runCount.size > 0) {
        const count = cascade.metrics?.run_count || 0;
        let matches = false;
        if (filters.runCount.has('0') && count === 0) matches = true;
        if (filters.runCount.has('1-10') && count >= 1 && count <= 10) matches = true;
        if (filters.runCount.has('11-50') && count >= 11 && count <= 50) matches = true;
        if (filters.runCount.has('50+') && count > 50) matches = true;
        if (!matches) return false;
      }

      // Cost ranges
      if (filters.costRange.size > 0) {
        const cost = cascade.metrics?.total_cost || 0;
        let matches = false;
        if (filters.costRange.has('$0') && cost === 0) matches = true;
        if (filters.costRange.has('$0-$1') && cost > 0 && cost <= 1) matches = true;
        if (filters.costRange.has('$1-$10') && cost > 1 && cost <= 10) matches = true;
        if (filters.costRange.has('$10+') && cost > 10) matches = true;
        if (!matches) return false;
      }

      // Has Candidates toggle
      if (filters.hasCandidates !== null) {
        const hasCandidates = cascade.graph_complexity?.has_soundings || false;
        if (hasCandidates !== filters.hasCandidates) return false;
      }

      // Has Sub-Cascades toggle
      if (filters.hasSubCascades !== null) {
        const hasSubCascades = cascade.graph_complexity?.has_sub_cascades || false;
        if (hasSubCascades !== filters.hasSubCascades) return false;
      }

      return true;
    });
  }, [cascades, filters]);

  // Apply filters to instances
  const filteredInstances = useMemo(() => {
    return instances.filter(instance => {
      // Search filter
      if (filters.search) {
        const searchLower = filters.search.toLowerCase();
        const matchesSessionId = instance.session_id?.toLowerCase().includes(searchLower);
        const matchesInputs = JSON.stringify(instance.input_data || {}).toLowerCase().includes(searchLower);
        if (!matchesSessionId && !matchesInputs) return false;
      }

      // Status filter
      if (filters.status.size > 0) {
        const status = instance.status?.toLowerCase();
        if (!filters.status.has(status)) return false;
      }

      // Cost ranges
      if (filters.costRange.size > 0) {
        const cost = instance.total_cost || 0;
        let matches = false;
        if (filters.costRange.has('$0') && cost === 0) matches = true;
        if (filters.costRange.has('$0-$0.10') && cost > 0 && cost <= 0.10) matches = true;
        if (filters.costRange.has('$0.10-$1') && cost > 0.10 && cost <= 1) matches = true;
        if (filters.costRange.has('$1+') && cost > 1) matches = true;
        if (!matches) return false;
      }

      return true;
    });
  }, [instances, filters]);

  // Check if any filters are active
  const hasActiveFilters = useMemo(() => {
    return filters.search !== '' ||
      filters.runCount.size > 0 ||
      filters.costRange.size > 0 ||
      filters.status.size > 0 ||
      filters.hasCandidates !== null ||
      filters.hasSubCascades !== null;
  }, [filters]);

  // Clear all filters
  const clearFilters = () => {
    setFilters({
      search: '',
      runCount: new Set(),
      costRange: new Set(),
      status: new Set(),
      hasCandidates: null,
      hasSubCascades: null,
    });
  };

  // Toggle filter chip
  const toggleFilter = (category, value) => {
    setFilters(prev => {
      const newSet = new Set(prev[category]);
      if (newSet.has(value)) {
        newSet.delete(value);
      } else {
        newSet.add(value);
      }
      return { ...prev, [category]: newSet };
    });
  };

  // Toggle boolean filter
  const toggleBooleanFilter = (key) => {
    setFilters(prev => ({
      ...prev,
      [key]: prev[key] === null ? true : (prev[key] === true ? false : null)
    }));
  };

  // Handle cascade row click - transition to instances view
  const handleCascadeClick = (event) => {
    const { cascade_id } = event.data;
    if (cascade_id) {
      setSelectedCascade(cascade_id);
      // Update URL to /#/cascades/{cascade_id}
      navStore('cascades', { cascade: cascade_id });
    }
  };

  // Handle instance row click - navigate to Studio
  const handleInstanceClick = (event) => {
    const { session_id } = event.data;
    if (session_id && selectedCascade) {
      navStore('studio', { cascade: selectedCascade, session: session_id });
    }
  };

  // Back to cascades list
  const handleBack = () => {
    setSelectedCascade(null);
    setInstances([]);
    // Update URL back to /#/cascades
    navStore('cascades', {});
  };

  // Auto-size columns on first render
  const onFirstDataRendered = (params) => {
    params.api.sizeColumnsToFit();
  };

  // Determine which grid data to show (with filters applied)
  const gridData = selectedCascade ? filteredInstances : filteredCascades;
  const totalData = selectedCascade ? instances : cascades;
  const columnDefs = selectedCascade ? instanceColumns : cascadeColumns;
  const handleRowClick = selectedCascade ? handleInstanceClick : handleCascadeClick;

  // Determine cascade filter for chart (show filtered data in chart)
  const cascadeIdsForChart = useMemo(() => {
    // If specific cascade selected, show just that one
    if (selectedCascade) {
      return [selectedCascade];
    }

    // If filters are active, show only filtered cascades
    if (hasActiveFilters && filteredCascades.length > 0) {
      return filteredCascades.map(c => c.cascade_id);
    }

    // Otherwise show all cascades (empty array = no filter)
    return [];
  }, [selectedCascade, filteredCascades, hasActiveFilters]);

  return (
    <div className="cascades-view">
      {/* Header */}
      <div className="cascades-header">
        <div className="cascades-title">
          {selectedCascade && (
            <Button
              variant="ghost"
              size="sm"
              icon="mdi:arrow-left"
              onClick={handleBack}
              className="cascades-back-btn"
            >
              Back
            </Button>
          )}
          <Icon icon="mdi:file-tree" width="32" />
          <h1>{selectedCascade ? selectedCascade : 'Cascades'}</h1>
        </div>
        <div className="cascades-subtitle">
          {selectedCascade
            ? `Execution history for ${selectedCascade}`
            : 'All cascade definitions with aggregate metrics'
          }
        </div>
      </div>

      {/* Cost Chart Section - filtered when cascade selected or filters active */}
      <div className="cascades-section">
        <div className="cascades-section-header">
          <Icon icon="mdi:chart-line" width="14" />
          <h2>Cost Timeline</h2>
          <span className={`cascades-filter-label ${cascadeIdsForChart.length === 0 ? 'invisible' : ''}`}>
            {cascadeIdsForChart.length === 1
              ? `Filtered to: ${cascadeIdsForChart[0]}`
              : cascadeIdsForChart.length > 1
                ? `Filtered to ${cascadeIdsForChart.length} cascades`
                : '\u00A0' /* non-breaking space to maintain height */
            }
          </span>
        </div>
        <div className="cascades-chart-wrapper">
          <CostTimelineChart cascadeIds={cascadeIdsForChart} />
        </div>
      </div>

      {/* Grid Section */}
      <div className="cascades-section">
        <div className="cascades-section-header">
          <Icon icon="mdi:table" width="14" />
          <h2>{selectedCascade ? 'Execution History' : 'All Cascades'}</h2>
          <span className="cascades-count">
            {hasActiveFilters
              ? `${gridData.length} of ${totalData.length}`
              : gridData.length
            } {selectedCascade ? 'sessions' : 'cascades'}
          </span>
        </div>

        {/* Filter Bar */}
        <div className="cascades-filter-bar">
          {/* Search */}
          <div className="filter-search">
            <Icon icon="mdi:magnify" width="14" />
            <input
              type="text"
              placeholder={selectedCascade ? "Search sessions..." : "Search cascades..."}
              value={filters.search}
              onChange={(e) => setFilters(prev => ({ ...prev, search: e.target.value }))}
            />
            {filters.search && (
              <Icon
                icon="mdi:close-circle"
                width="14"
                className="filter-search-clear"
                onClick={() => setFilters(prev => ({ ...prev, search: '' }))}
              />
            )}
          </div>

          {/* Run Count (cascades only) */}
          {!selectedCascade && (
            <div className="filter-group">
              <span className="filter-label">Runs</span>
              <div className="filter-chips">
                {['0', '1-10', '11-50', '50+'].map(range => (
                  <button
                    key={range}
                    className={`filter-chip ${filters.runCount.has(range) ? 'active' : ''}`}
                    onClick={() => toggleFilter('runCount', range)}
                  >
                    {range}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Status (instances only) */}
          {selectedCascade && (
            <div className="filter-group">
              <span className="filter-label">Status</span>
              <div className="filter-chips">
                {['completed', 'error', 'running', 'blocked'].map(status => (
                  <button
                    key={status}
                    className={`filter-chip status-${status} ${filters.status.has(status) ? 'active' : ''}`}
                    onClick={() => toggleFilter('status', status)}
                  >
                    {status}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Cost Range */}
          <div className="filter-group">
            <span className="filter-label">Cost</span>
            <div className="filter-chips">
              {selectedCascade
                ? ['$0', '$0-$0.10', '$0.10-$1', '$1+'].map(range => (
                    <button
                      key={range}
                      className={`filter-chip ${filters.costRange.has(range) ? 'active' : ''}`}
                      onClick={() => toggleFilter('costRange', range)}
                    >
                      {range}
                    </button>
                  ))
                : ['$0', '$0-$1', '$1-$10', '$10+'].map(range => (
                    <button
                      key={range}
                      className={`filter-chip ${filters.costRange.has(range) ? 'active' : ''}`}
                      onClick={() => toggleFilter('costRange', range)}
                    >
                      {range}
                    </button>
                  ))
              }
            </div>
          </div>

          {/* Feature Toggles (cascades only) */}
          {!selectedCascade && (
            <div className="filter-group">
              <span className="filter-label">Features</span>
              <div className="filter-chips">
                <button
                  className={`filter-toggle ${filters.hasCandidates === true ? 'active' : ''} ${filters.hasCandidates === false ? 'inactive' : ''}`}
                  onClick={() => toggleBooleanFilter('hasCandidates')}
                  title={filters.hasCandidates === null ? 'Show all' : filters.hasCandidates ? 'With candidates' : 'Without candidates'}
                >
                  <Icon icon="mdi:routes" width="12" />
                  Candidates
                </button>
                <button
                  className={`filter-toggle ${filters.hasSubCascades === true ? 'active' : ''} ${filters.hasSubCascades === false ? 'inactive' : ''}`}
                  onClick={() => toggleBooleanFilter('hasSubCascades')}
                  title={filters.hasSubCascades === null ? 'Show all' : filters.hasSubCascades ? 'With sub-cascades' : 'Without sub-cascades'}
                >
                  <Icon icon="mdi:file-tree" width="12" />
                  Sub-Cascades
                </button>
              </div>
            </div>
          )}

          {/* Clear Filters */}
          {hasActiveFilters && (
            <button className="filter-clear" onClick={clearFilters}>
              <Icon icon="mdi:close-circle" width="14" />
              Clear
            </button>
          )}
        </div>

        {error && (
          <div className="cascades-error">
            <Icon icon="mdi:alert-circle" width="20" />
            <span>{error}</span>
          </div>
        )}

        {!error && (
          <>
            {gridData.length === 0 && !loading && selectedCascade ? (
              <div className="cascades-empty-state">
                <Icon icon="mdi:play-circle-outline" width="64" />
                <h3>No runs yet</h3>
                <p>This cascade hasn't been executed yet.</p>
                <Button
                  variant="primary"
                  icon="mdi:rocket-launch"
                  onClick={handleLoadInStudio}
                >
                  Load in Studio to Run
                </Button>
              </div>
            ) : (
              <div ref={containerRef} className="cascades-grid-container" style={{ height: `${gridHeight}px` }}>
                <AgGridReact
                  ref={gridRef}
                  theme={darkTheme}
                  rowData={gridData}
                  columnDefs={columnDefs}
                  defaultColDef={defaultColDef}
                  getRowId={(params) => params.data.cascade_id || params.data.session_id}
                  domLayout="normal"
                  suppressCellFocus={true}
                  suppressMovableColumns={false}
                  enableCellTextSelection={true}
                  ensureDomOrder={true}
                  animateRows={true}
                  loading={loading}
                  onRowClicked={handleRowClick}
                  onFirstDataRendered={onFirstDataRendered}
                  rowClass="cascades-grid-row-clickable"
                  tooltipShowDelay={500}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default CascadesView;
