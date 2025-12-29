import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Button } from '../../components';
import useStudioCascadeStore from '../../studio/stores/studioCascadeStore';
import CostTimelineChart from '../../components/CostTimelineChart';
import CascadeSpecGraph from '../../components/CascadeSpecGraph';
import KPICard from '../receipts/components/KPICard';
import { ROUTES } from '../../routes.helpers';
import './CascadesView.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Cell renderers for cascade analytics
const SuccessRateRenderer = (props) => {
  const rate = props.value || 0;
  const color = rate >= 95 ? '#34d399' : rate >= 80 ? '#fbbf24' : '#f87171';

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{rate.toFixed(0)}%</div>
    </div>
  );
};

const CostTrendRenderer = (props) => {
  const trend = props.value || 0;
  const cost7d = props.data.analytics?.cost_7d_avg || 0;
  const cost30d = props.data.analytics?.cost_30d_avg || 0;

  // No trend if insufficient data
  if (cost7d === 0 && cost30d === 0) {
    return <span style={{ color: '#475569' }}>-</span>;
  }

  const color = trend > 20 ? '#f87171' : trend > 5 ? '#fbbf24' : trend < -5 ? '#34d399' : '#94a3b8';
  const arrow = trend > 5 ? '↑' : trend < -5 ? '↓' : '';

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{arrow}{Math.abs(trend).toFixed(0)}%</div>
      {cost7d > 0 && (
        <div style={{ fontSize: '10px', marginTop: '2px', color: '#64748b' }}>
          7d: ${cost7d.toFixed(4)}
        </div>
      )}
    </div>
  );
};

const OutlierRateRenderer = (props) => {
  const rate = props.value || 0;
  const color = rate > 20 ? '#f87171' : rate > 10 ? '#fbbf24' : '#34d399';

  if (rate === 0) {
    return <span style={{ color: '#34d399', fontWeight: '500' }}>0%</span>;
  }

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{rate.toFixed(0)}%</div>
    </div>
  );
};

const AvgContextRenderer = (props) => {
  const pct = props.value || 0;
  const color = pct > 60 ? '#fbbf24' : pct < 30 ? '#34d399' : '#94a3b8';

  if (pct === 0) {
    return <span style={{ color: '#475569' }}>-</span>;
  }

  return (
    <div style={{ color, fontWeight: '500' }}>
      <div>{pct.toFixed(0)}%</div>
    </div>
  );
};

// Session-level cell renderers (for instances grid)
const InputBadgeRenderer = (props) => {
  const category = props.value;
  const badges = {
    tiny: { label: 'T', color: '#34d399' },
    small: { label: 'S', color: '#60a5fa' },
    medium: { label: 'M', color: '#94a3b8' },
    large: { label: 'L', color: '#fbbf24' },
    huge: { label: 'H', color: '#f87171' }
  };

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
const CascadesView = () => {
  // React Router hooks
  const { cascadeId: urlCascadeId } = useParams();
  const navigate = useNavigate();

  // Decode the cascade ID from URL
  const initialCascadeId = urlCascadeId ? decodeURIComponent(urlCascadeId) : null;

  const [selectedCascade, setSelectedCascade] = useState(initialCascadeId);
  const [cascades, setCascades] = useState([]);
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [gridHeight, setGridHeight] = useState(600);
  const gridRef = useRef(null);
  const containerRef = useRef(null);

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
        navigate(ROUTES.STUDIO);
      } else {
        console.warn('[CascadesView] Could not find cascade file for:', selectedCascade);
        // Fallback: navigate with cascade param, let Studio handle it
        navigate(ROUTES.studioWithCascade(selectedCascade));
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
        total_duration_ms: session.total_duration_ms || 0,
        duration_seconds: session.started_at && session.completed_at
          ? (new Date(session.completed_at) - new Date(session.started_at)) / 1000
          : 0,
        input_data: session.input_data,
        start_time: session.started_at,
        end_time: session.completed_at,
        message_count: session.message_count || 0,
        // Legacy percentage differences (hidden by default)
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

      setInstances(transformed);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Sync state with URL params when URL changes
  useEffect(() => {
    const newCascadeId = urlCascadeId ? decodeURIComponent(urlCascadeId) : null;
    if (newCascadeId !== selectedCascade) {
      setSelectedCascade(newCascadeId);
      if (!newCascadeId) {
        setInstances([]);
      }
    }
  }, [urlCascadeId]); // eslint-disable-line react-hooks/exhaustive-deps

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
      field: 'analytics.success_rate',
      headerName: 'Success',
      headerTooltip: 'Percentage of runs that completed successfully',
      width: 95,
      wrapText: true,
      autoHeight: true,
      cellRenderer: SuccessRateRenderer,
      tooltipValueGetter: (params) => {
        const rate = params.value || 0;
        return `Success rate: ${rate.toFixed(1)}% of runs completed successfully`;
      },
      cellStyle: {
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    {
      field: 'analytics.cost_trend_pct',
      headerName: 'Cost Trend',
      headerTooltip: '7-day vs 30-day average cost trend',
      width: 110,
      wrapText: true,
      autoHeight: true,
      cellRenderer: CostTrendRenderer,
      tooltipValueGetter: (params) => {
        const trend = params.value || 0;
        const cost7d = params.data.analytics?.cost_7d_avg || 0;
        const cost30d = params.data.analytics?.cost_30d_avg || 0;
        if (cost7d === 0 && cost30d === 0) return 'Insufficient data for trend';
        return `7d avg: $${cost7d.toFixed(4)} | 30d avg: $${cost30d.toFixed(4)} | Trend: ${trend > 0 ? '+' : ''}${trend.toFixed(1)}%`;
      },
      cellStyle: {
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    {
      field: 'analytics.outlier_rate',
      headerName: 'Outliers',
      headerTooltip: 'Percentage of runs that are cost outliers',
      width: 95,
      wrapText: true,
      autoHeight: true,
      cellRenderer: OutlierRateRenderer,
      tooltipValueGetter: (params) => {
        const rate = params.value || 0;
        return `Outlier rate: ${rate.toFixed(1)}% of runs are statistical outliers (>2σ)`;
      },
      cellStyle: {
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
    },
    {
      field: 'analytics.avg_context_pct',
      headerName: 'Avg Ctx%',
      headerTooltip: 'Average percentage of cost from context injection',
      width: 95,
      wrapText: true,
      autoHeight: true,
      cellRenderer: AvgContextRenderer,
      tooltipValueGetter: (params) => {
        const pct = params.value || 0;
        return `Average context cost: ${pct.toFixed(1)}% of total cost typically from context injection`;
      },
      cellStyle: {
        lineHeight: '1.4',
        whiteSpace: 'normal',
        paddingTop: '4px',
        paddingBottom: '4px'
      },
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

  // Instances grid columns (execution history for selected cascade)
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
    { field: 'message_count', hide: true },
    { field: 'duration_seconds', hide: true },
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
            // Truncate to 150 chars (same as console/output)
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

  // Compute cascade-specific KPIs from instances (for drill-down view)
  const cascadeKpis = useMemo(() => {
    if (!selectedCascade || instances.length === 0) {
      return null;
    }

    // Total runs and cost
    const totalRuns = instances.length;
    const totalCost = instances.reduce((sum, i) => sum + (i.total_cost || 0), 0);

    // Outlier count
    const outlierCount = instances.filter(i => i.is_cost_outlier).length;

    // Average context %
    const instancesWithContext = instances.filter(i => i.context_cost_pct > 0);
    const avgContextPct = instancesWithContext.length > 0
      ? instancesWithContext.reduce((sum, i) => sum + i.context_cost_pct, 0) / instancesWithContext.length
      : 0;

    // Top bottleneck cell (most frequent bottleneck across runs)
    const bottleneckCounts = {};
    const bottleneckPcts = {};
    instances.forEach(i => {
      if (i.bottleneck_cell && i.bottleneck_cell_pct >= 40) {
        bottleneckCounts[i.bottleneck_cell] = (bottleneckCounts[i.bottleneck_cell] || 0) + 1;
        if (!bottleneckPcts[i.bottleneck_cell]) {
          bottleneckPcts[i.bottleneck_cell] = [];
        }
        bottleneckPcts[i.bottleneck_cell].push(i.bottleneck_cell_pct);
      }
    });

    let topBottleneck = null;
    let topBottleneckCount = 0;
    let topBottleneckAvgPct = 0;
    Object.entries(bottleneckCounts).forEach(([cell, count]) => {
      if (count > topBottleneckCount) {
        topBottleneckCount = count;
        topBottleneck = cell;
        const pcts = bottleneckPcts[cell];
        topBottleneckAvgPct = pcts.reduce((a, b) => a + b, 0) / pcts.length;
      }
    });

    // Success rate
    const completedCount = instances.filter(i => i.status === 'completed').length;
    const errorCount = instances.filter(i => i.status === 'error').length;
    const successRate = totalRuns > 0 ? (completedCount / (completedCount + errorCount)) * 100 : 100;

    return {
      totalRuns,
      totalCost,
      outlierCount,
      avgContextPct,
      topBottleneck,
      topBottleneckCount,
      topBottleneckAvgPct,
      successRate,
      errorCount,
    };
  }, [selectedCascade, instances]);

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
      // Update URL to /cascades/{cascade_id}
      navigate(ROUTES.cascadesWithCascade(cascade_id));
    }
  };

  // Handle instance row click - navigate to Studio
  const handleInstanceClick = (event) => {
    const { session_id } = event.data;
    if (session_id && selectedCascade) {
      navigate(ROUTES.studioWithSession(selectedCascade, session_id));
    }
  };

  // Back to cascades list
  const handleBack = () => {
    setSelectedCascade(null);
    setInstances([]);
    // Update URL back to /
    navigate(ROUTES.CASCADES);
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

  // Get selected cascade's cells for spec graph
  const selectedCascadeData = useMemo(() => {
    if (!selectedCascade) return null;
    const cascade = cascades.find(c => c.cascade_id === selectedCascade);
    if (!cascade) return null;
    return {
      cells: cascade.phases || [],
      inputsSchema: cascade.inputs_schema || {},
    };
  }, [selectedCascade, cascades]);

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

      {/* KPI Cards Section - Only show when viewing a specific cascade */}
      {selectedCascade && cascadeKpis && (
        <div className="cascades-kpi-section">
          <div className="cascades-kpi-grid">
            <KPICard
              title="Total Runs"
              value={cascadeKpis.totalRuns}
              subtitle={cascadeKpis.errorCount > 0 ? `${cascadeKpis.errorCount} errors` : 'no errors'}
              icon="mdi:play-circle"
              color={cascadeKpis.successRate >= 95 ? '#34d399' : cascadeKpis.successRate >= 80 ? '#fbbf24' : '#f87171'}
            />
            <KPICard
              title="Total Cost"
              value={`$${cascadeKpis.totalCost.toFixed(4)}`}
              subtitle={`$${(cascadeKpis.totalCost / cascadeKpis.totalRuns).toFixed(4)} avg/run`}
              icon="mdi:cash"
              color="#34d399"
            />
            <KPICard
              title="Outliers"
              value={cascadeKpis.outlierCount}
              subtitle={cascadeKpis.outlierCount > 0
                ? `${((cascadeKpis.outlierCount / cascadeKpis.totalRuns) * 100).toFixed(0)}% of runs`
                : 'none detected'
              }
              icon="mdi:alert-circle"
              color={cascadeKpis.outlierCount > 0 ? '#f87171' : '#64748b'}
            />
            <KPICard
              title="Avg Context%"
              value={`${cascadeKpis.avgContextPct.toFixed(0)}%`}
              subtitle="of cost is context"
              icon="mdi:database-import"
              color={cascadeKpis.avgContextPct > 60 ? '#fbbf24' : cascadeKpis.avgContextPct > 30 ? '#60a5fa' : '#34d399'}
            />
            {cascadeKpis.topBottleneck && (
              <KPICard
                title="Top Bottleneck"
                value={cascadeKpis.topBottleneck}
                subtitle={`${cascadeKpis.topBottleneckAvgPct.toFixed(0)}% avg (${cascadeKpis.topBottleneckCount} runs)`}
                icon="mdi:target"
                color="#fbbf24"
              />
            )}
          </div>
        </div>
      )}

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

      {/* Cascade Spec Graph - only show when viewing a specific cascade */}
      {selectedCascade && selectedCascadeData && selectedCascadeData.cells.length > 0 && (
        <div className="cascades-section">
          <CascadeSpecGraph
            cells={selectedCascadeData.cells}
            inputsSchema={selectedCascadeData.inputsSchema}
            cascadeId={selectedCascade}
          />
        </div>
      )}

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
          {selectedCascade && (
            <button
              className="cascades-open-studio-btn"
              onClick={handleLoadInStudio}
              title="Open cascade spec in Studio (no session)"
            >
              <Icon icon="mdi:pencil-ruler" width="14" />
              Open in Studio
            </button>
          )}
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
                  getRowId={(params) => params.data.session_id || params.data.cascade_id}
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
