import React from 'react';
import { Icon } from '@iconify/react';
import {
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ComposedChart,
  Area,
  Line
} from 'recharts';

const formatCost = (cost) => {
  if (cost === null || cost === undefined) return '$0.00';
  if (cost >= 1) return `$${cost.toFixed(2)}`;
  if (cost >= 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(4)}`;
};

const formatNumber = (num) => {
  if (num === null || num === undefined) return '0';
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toString();
};

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '0ms';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

const getRateColor = (rate) => {
  if (rate >= 80) return 'var(--color-accent-green)';
  if (rate >= 50) return 'var(--color-accent-yellow)';
  return 'var(--color-accent-red)';
};

const getRateClass = (rate) => {
  if (rate >= 80) return 'rate-high';
  if (rate >= 50) return 'rate-mid';
  return 'rate-low';
};

const formatDate = (value, options) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, options);
};

const CacheGauge = ({ hitRate }) => {
  const rate = Number.isFinite(hitRate) ? hitRate : 0;
  const rateClass = getRateClass(rate);
  const data = [{ name: 'Hit Rate', value: rate }];

  return (
    <div className="cache-gauge">
      <div className="cache-gauge-chart">
        <ResponsiveContainer width="100%" height={160}>
          <RadialBarChart
            cx="50%"
            cy="65%"
            innerRadius="70%"
            outerRadius="100%"
            barSize={12}
            data={data}
            startAngle={180}
            endAngle={0}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar
              background={{ fill: 'var(--color-border-dim)' }}
              dataKey="value"
              cornerRadius={8}
              fill={getRateColor(rate)}
            />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className={`cache-gauge-center ${rateClass}`}>
        <div className="cache-gauge-value">{rate.toFixed(1)}%</div>
        <div className="cache-gauge-label">Cache Hit Rate</div>
      </div>
    </div>
  );
};

const TypeTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const item = payload[0].payload;
  return (
    <div className="sql-trail-tooltip">
      <div className="sql-trail-tooltip-title">{item.query_type || 'Unknown'}</div>
      <div className="sql-trail-tooltip-row">
        <span>Queries</span>
        <span>{formatNumber(item.count)}</span>
      </div>
    </div>
  );
};

const OverviewPanel = ({
  data,
  cacheStats,
  timeSeries,
  onQueryClick,
  granularity = 'daily',
  onGranularityChange
}) => {
  if (!data || !data.kpis) {
    return (
      <div className="empty-state">
        <Icon icon="mdi:database-off" width={48} className="empty-state-icon" />
        <div className="empty-state-title">No data available</div>
        <div className="empty-state-text">
          Run some SQL queries with RVBBIT UDFs to see analytics here.
        </div>
      </div>
    );
  }

  const {
    total_queries = 0,
    total_cost = 0,
    total_llm_calls = 0,
    avg_duration_ms = 0,
    cache_hit_rate = 0
  } = data.kpis;

  const queries_by_type = data.udf_distribution || [];

  const timeSeriesData = (timeSeries?.series || []).map((point) => ({
    period: point.period || point.date || point.timestamp,
    queries: point.query_count ?? point.queries ?? 0,
    calls: point.llm_calls ?? point.llm_calls_count ?? 0,
    cost: point.total_cost ?? point.cost ?? 0
  }));
  const typeData = [...queries_by_type].sort((a, b) => (b.count || 0) - (a.count || 0));
  const granularityOptions = [
    { value: 'minute', label: 'Minutes' },
    { value: 'hourly', label: 'Hourly' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' }
  ];

  const formatPeriodLabel = (value, { tick } = {}) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;

    switch (granularity) {
      case 'minute':
        return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      case 'hourly':
        return tick
          ? date.toLocaleTimeString(undefined, { hour: '2-digit' })
          : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit' });
      case 'weekly':
        return tick
          ? `Wk ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
          : `Week of ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
      case 'monthly':
        return tick
          ? date.toLocaleDateString(undefined, { month: 'short' })
          : date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
      default:
        return formatDate(value, { month: 'short', day: 'numeric' });
    }
  };

  const ActivityTooltip = ({ active, payload, label }) => {
    if (!active || !payload || !payload.length) return null;
    const queries = payload.find((entry) => entry.dataKey === 'queries');
    const calls = payload.find((entry) => entry.dataKey === 'calls');
    const point = payload[0]?.payload || {};
    const costValue = point.cost;

    return (
      <div className="sql-trail-tooltip">
        <div className="sql-trail-tooltip-title">
          {formatPeriodLabel(label)}
        </div>
        <div className="sql-trail-tooltip-row">
          <span>Queries</span>
          <span>{queries ? formatNumber(queries.value) : '0'}</span>
        </div>
        <div className="sql-trail-tooltip-row">
          <span>LLM Calls</span>
          <span>{calls ? formatNumber(calls.value) : '0'}</span>
        </div>
        {costValue > 0 && (
          <div className="sql-trail-tooltip-row">
            <span>Cost</span>
            <span>{formatCost(costValue || 0)}</span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="overview-panel">
      <div className="overview-kpis">
        <div className="kpi-card">
          <div className="kpi-header">
            <Icon icon="mdi:database-search" width={16} />
            <span>Total Queries</span>
          </div>
          <div className="kpi-value purple">{formatNumber(total_queries)}</div>
          <div className="kpi-subtext">SQL queries executed</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <Icon icon="mdi:currency-usd" width={16} />
            <span>Total Cost</span>
          </div>
          <div className="kpi-value green">{formatCost(total_cost)}</div>
          <div className="kpi-subtext">{formatNumber(total_llm_calls)} LLM calls</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <Icon icon="mdi:cached" width={16} />
            <span>Cache Hit Rate</span>
          </div>
          <div className="kpi-value blue">{cache_hit_rate.toFixed(1)}%</div>
          <div className="kpi-subtext">
            {cacheStats ? `${formatNumber(cacheStats.total_hits)} hits / ${formatNumber(cacheStats.total_misses)} misses` : 'From query logs'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <Icon icon="mdi:timer-outline" width={16} />
            <span>Avg Duration</span>
          </div>
          <div className="kpi-value yellow">{formatDuration(avg_duration_ms)}</div>
          <div className="kpi-subtext">Per query execution</div>
        </div>
      </div>

      <div className="overview-row">
        <div className="overview-chart-card">
          <div className="overview-card-header">
            <div className="overview-card-title">
              <Icon icon="mdi:cached" width={14} />
              <span>Cache Performance</span>
            </div>
          </div>
          <CacheGauge hitRate={cache_hit_rate} />
          {cacheStats && (
            <div className="cache-stats">
              <div className="cache-stat cache-stat--hits">
                <div className="cache-stat-value">{formatNumber(cacheStats.total_hits)}</div>
                <div className="cache-stat-label">Cache Hits</div>
              </div>
              <div className="cache-stat cache-stat--misses">
                <div className="cache-stat-value">{formatNumber(cacheStats.total_misses)}</div>
                <div className="cache-stat-label">Cache Misses</div>
              </div>
              {cacheStats.estimated_savings > 0 && (
                <div className="cache-stat cache-stat--savings">
                  <div className="cache-stat-value">{formatCost(cacheStats.estimated_savings)}</div>
                  <div className="cache-stat-label">Est. Savings</div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="overview-chart-card">
          <div className="overview-card-header">
            <div className="overview-card-title">
              <Icon icon="mdi:shape-outline" width={14} />
              <span>Queries by Type</span>
            </div>
          </div>
          {typeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={typeData}
                layout="vertical"
                margin={{ top: 8, right: 16, left: 24, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="sqlTrailTypeGradient" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--color-accent-cyan)" stopOpacity={0.85} />
                    <stop offset="100%" stopColor="var(--color-accent-purple)" stopOpacity={0.85} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-dim)" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fill: 'var(--color-text-dim)', fontSize: 10 }}
                  axisLine={{ stroke: 'var(--color-border-dim)' }}
                  tickLine={false}
                />
                <YAxis
                  type="category"
                  dataKey="query_type"
                  width={120}
                  tick={{ fill: 'var(--color-text-muted)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<TypeTooltip />} cursor={{ fill: 'rgba(0, 229, 255, 0.08)' }} />
                <Bar dataKey="count" fill="url(#sqlTrailTypeGradient)" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="overview-empty">No type data available</div>
          )}
        </div>
      </div>

      <div className="overview-chart-card">
        <div className="overview-card-header">
          <div className="overview-card-title">
            <Icon icon="mdi:chart-timeline-variant" width={14} />
            <span>Query Activity Over Time</span>
          </div>
          <div className="sql-trail-granularity">
            {granularityOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`sql-trail-granularity-btn ${granularity === option.value ? 'active' : ''}`}
                onClick={() => onGranularityChange && onGranularityChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        {timeSeriesData.length > 0 ? (
          <>
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={timeSeriesData} margin={{ top: 12, right: 16, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="sqlTrailQueriesGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-accent-cyan)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--color-accent-cyan)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-dim)" vertical={false} />
                <XAxis
                  dataKey="period"
                  tick={{ fill: 'var(--color-text-dim)', fontSize: 10 }}
                  axisLine={{ stroke: 'var(--color-border-dim)' }}
                  tickLine={false}
                  tickFormatter={(value) => formatPeriodLabel(value, { tick: true })}
                />
                <YAxis
                  yAxisId="left"
                  tick={{ fill: 'var(--color-text-dim)', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => formatNumber(v)}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fill: 'var(--color-text-dim)', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => formatNumber(v)}
                />
                <Tooltip content={<ActivityTooltip />} />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="queries"
                  stroke="var(--color-accent-cyan)"
                  strokeWidth={1.5}
                  fill="url(#sqlTrailQueriesGradient)"
                  name="Queries"
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="calls"
                  stroke="var(--color-accent-purple)"
                  strokeWidth={2}
                  dot={false}
                  name="LLM Calls"
                  activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--color-bg-primary)' }}
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="sql-trail-activity-legend">
              <span className="legend-item">
                <span className="legend-dot legend-queries" />
                Queries
              </span>
              <span className="legend-item">
                <span className="legend-dot legend-calls" />
                LLM Calls
              </span>
            </div>
          </>
        ) : (
          <div className="overview-empty">No time series data available</div>
        )}
      </div>
    </div>
  );
};

export default OverviewPanel;
