import React from 'react';
import { Icon } from '@iconify/react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
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

const CacheGauge = ({ hitRate }) => {
  const rate = hitRate || 0;
  const radius = 70;
  const strokeWidth = 12;
  const circumference = Math.PI * radius;
  const offset = circumference - (rate / 100) * circumference;

  // Color based on hit rate
  const getColor = (r) => {
    if (r >= 80) return '#34d399';  // green
    if (r >= 50) return '#fbbf24';  // yellow
    return '#f87171';  // red
  };

  return (
    <div className="cache-gauge">
      <div className="gauge-container">
        <svg width="160" height="90" viewBox="0 0 160 90">
          <path
            className="gauge-bg"
            d="M 10 80 A 70 70 0 0 1 150 80"
            fill="none"
            strokeWidth={strokeWidth}
          />
          <path
            className="gauge-fill"
            d="M 10 80 A 70 70 0 0 1 150 80"
            fill="none"
            strokeWidth={strokeWidth}
            stroke={getColor(rate)}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
        </svg>
        <div className="gauge-text">
          <div className="gauge-value" style={{ color: getColor(rate) }}>
            {rate.toFixed(1)}%
          </div>
          <div className="gauge-label">Cache Hit Rate</div>
        </div>
      </div>
    </div>
  );
};

const COLORS = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171'];

const OverviewPanel = ({ data, cacheStats, timeSeries, onQueryClick }) => {
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

  const timeSeriesData = timeSeries?.series || [];

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
          <h3>Cache Performance</h3>
          <CacheGauge hitRate={cache_hit_rate} />
          {cacheStats && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: '24px', marginTop: '16px' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#34d399' }}>
                  {formatNumber(cacheStats.total_hits)}
                </div>
                <div style={{ fontSize: '11px', color: '#888' }}>Cache Hits</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#f87171' }}>
                  {formatNumber(cacheStats.total_misses)}
                </div>
                <div style={{ fontSize: '11px', color: '#888' }}>Cache Misses</div>
              </div>
              {cacheStats.estimated_savings > 0 && (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '20px', fontWeight: 600, color: '#60a5fa' }}>
                    {formatCost(cacheStats.estimated_savings)}
                  </div>
                  <div style={{ fontSize: '11px', color: '#888' }}>Est. Savings</div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="overview-chart-card">
          <h3>Queries by Type</h3>
          {queries_by_type.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={queries_by_type}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="count"
                  nameKey="query_type"
                  label={({ query_type, percent }) => `${query_type} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {queries_by_type.map((entry, index) => (
                    <Cell key={entry.query_type} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1a1a1a', border: '1px solid #333', borderRadius: '4px' }}
                  labelStyle={{ color: '#e0e0e0' }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ height: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
              No type data available
            </div>
          )}
        </div>
      </div>

      <div className="overview-chart-card">
        <h3>Query Activity Over Time</h3>
        {timeSeriesData.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={timeSeriesData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#888', fontSize: 11 }}
                axisLine={{ stroke: '#2a2a2a' }}
              />
              <YAxis
                yAxisId="left"
                tick={{ fill: '#888', fontSize: 11 }}
                axisLine={{ stroke: '#2a2a2a' }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: '#888', fontSize: 11 }}
                axisLine={{ stroke: '#2a2a2a' }}
                tickFormatter={(v) => formatCost(v)}
              />
              <Tooltip
                contentStyle={{ background: '#1a1a1a', border: '1px solid #333', borderRadius: '4px' }}
                labelStyle={{ color: '#e0e0e0' }}
                formatter={(value, name) => {
                  if (name === 'cost') return [formatCost(value), 'Cost'];
                  return [value, name];
                }}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="queries"
                stroke="#a78bfa"
                strokeWidth={2}
                dot={false}
                name="Queries"
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="cost"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
                name="cost"
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: '250px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
            No time series data available
          </div>
        )}
      </div>
    </div>
  );
};

export default OverviewPanel;
