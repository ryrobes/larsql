import React, { useState, useEffect, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import './CostTimelineChart.css';

/**
 * CostTimelineChart - Elegant cost visualization with Bret Victor-inspired design
 *
 * Design philosophy:
 * - Let the data breathe - minimal chrome, maximum clarity
 * - Harmonious color palette that blends with the dashboard
 * - Direct, honest representation of values
 * - Smooth interactions that reveal detail on demand
 */
function CostTimelineChart({ cascadeFilter = null, cascadeIds = [] }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredModel, setHoveredModel] = useState(null);

  // Load granularity from localStorage, default to 'day'
  const [granularity, setGranularityState] = useState(() => {
    try {
      return localStorage.getItem('lars_cost_analytics_granularity') || 'day';
    } catch (err) {
      return 'day';
    }
  });

  // Wrapper to save to localStorage when granularity changes
  const setGranularity = (newGranularity) => {
    setGranularityState(newGranularity);
    try {
      localStorage.setItem('lars_cost_analytics_granularity', newGranularity);
    } catch (err) {
      console.error('Failed to save granularity preference:', err);
    }
  };

  // Stable string representation of cascadeIds to avoid infinite re-renders
  const cascadeIdsKey = cascadeIds.join(',');

  useEffect(() => {
    const fetchCostTimeline = async () => {
    try {
      setLoading(true);

      const params = new URLSearchParams();

      // Prefer cascadeIds (array) over cascadeFilter (single string) for backwards compatibility
      if (cascadeIds && cascadeIds.length > 0) {
        params.append('cascade_ids', cascadeIds.join(','));
      } else if (cascadeFilter) {
        params.append('cascade_id', cascadeFilter);
      }

      params.append('limit', '14');
      params.append('granularity', granularity);

      const res = await fetch(`http://localhost:5050/api/analytics/cost-timeline?${params}`);
      const result = await res.json();

      if (result.error) {
        setError(result.error);
        return;
      }

      setData(result);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    };

    fetchCostTimeline();
  }, [cascadeFilter, cascadeIdsKey, granularity]);

  // Cyberpunk color palette - cyan, purple, pink neon
  const colorPalette = useMemo(() => ({
    primary: [
      '#00e5ff',  // Cyan (primary accent)
      '#a78bfa',  // Purple (secondary accent)
      '#ff006e',  // Hot pink (error/accent)
      '#34d399',  // Green (success)
      '#fbbf24',  // Yellow (warning)
      '#60a5fa',  // Blue (info)
      '#f472b6',  // Pink variant
      '#64748b',  // Gray for "Other"
    ],
    gradient: {
      start: 'rgba(0, 229, 255, 0.3)',
      end: 'rgba(0, 229, 255, 0.01)'
    },
    tokens: {
      input: '#00e5ff',   // Cyan for input tokens
      output: '#a78bfa',  // Purple for output tokens
    }
  }), []);

  // Shorten model names for elegant display
  const shortenModelName = (fullName) => {
    if (!fullName || fullName === 'None' || fullName === 'Other') {
      return fullName === 'Other' ? 'Other' : 'Unknown';
    }

    let name = fullName;
    name = name.replace(/^(openai|anthropic|google|x-ai)\//, '');

    const transforms = [
      [/claude-(\d+\.?\d*)-sonnet.*/, 'Claude $1 Sonnet'],
      [/claude-sonnet-(\d+\.?\d*).*/, 'Claude $1 Sonnet'],
      [/claude-(\d+\.?\d*)-opus.*/, 'Claude $1 Opus'],
      [/claude-opus-(\d+\.?\d*).*/, 'Claude $1 Opus'],
      [/claude-(\d+\.?\d*)-haiku.*/, 'Claude $1 Haiku'],
      [/claude-haiku-(\d+\.?\d*).*/, 'Claude $1 Haiku'],
      [/gpt-(\d+\.?\d*).*/, 'GPT-$1'],
      [/gemini-(\d+\.?\d*)-pro.*/, 'Gemini $1 Pro'],
      [/gemini-(\d+\.?\d*)-flash-lite.*/, 'Gemini $1 Lite'],
      [/gemini-(\d+\.?\d*)-flash.*/, 'Gemini $1 Flash'],
      [/grok-(\d+).*/, 'Grok $1'],
      [/qwen.*embed.*/, 'Qwen Embed'],
    ];

    for (const [pattern, replacement] of transforms) {
      if (pattern.test(name)) {
        name = name.replace(pattern, replacement);
        break;
      }
    }

    if (name.length > 20) {
      name = name.substring(0, 18) + '…';
    }

    return name;
  };

  // Format currency elegantly
  const formatCost = (value, precision = 2) => {
    if (value >= 100) return `$${value.toFixed(0)}`;
    if (value >= 10) return `$${value.toFixed(1)}`;
    if (value >= 1) return `$${value.toFixed(precision)}`;
    return `$${value.toFixed(Math.min(precision + 2, 4))}`;
  };

  // Format token count
  const formatTokens = (value) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
    return value.toString();
  };

  // Format time bucket - convert UTC to local timezone
  const formatTimeBucket = (bucket) => {
    if (!data) return bucket;
    const bucketType = data.bucket_type;

    // Parse the timestamp correctly based on format
    let date;
    if (bucket.includes('T')) {
      // ISO format with time (e.g., "2025-12-25T10:00:00Z")
      date = new Date(bucket);
    } else {
      // Date-only format (e.g., "2025-12-25")
      // Parse as local date to avoid timezone shifts
      const parts = bucket.split('-');
      date = new Date(parts[0], parts[1] - 1, parts[2]);
    }

    if (bucketType === 'hour') {
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    } else if (bucketType === 'day') {
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } else if (bucketType === 'week') {
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } else if (bucketType === 'month') {
      return date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    }
    return bucket;
  };

  // Process data for visualization
  const processedData = useMemo(() => {
    if (!data || !data.buckets) return { chartData: [], modelBreakdown: [], tokenData: [] };

    // Sort models by total cost
    const modelTotals = Object.entries(data.model_totals || {})
      .map(([model, cost]) => ({ model, cost, displayName: shortenModelName(model) }))
      .sort((a, b) => b.cost - a.cost);

    // Top 7 models + Other
    const topModels = modelTotals.slice(0, 7);
    const otherModels = modelTotals.slice(7);
    const otherTotal = otherModels.reduce((sum, m) => sum + m.cost, 0);

    const modelBreakdown = [...topModels];
    if (otherTotal > 0) {
      modelBreakdown.push({ model: 'Other', cost: otherTotal, displayName: 'Other' });
    }

    // Assign colors
    modelBreakdown.forEach((item, idx) => {
      item.color = colorPalette.primary[idx] || colorPalette.primary[7];
    });

    // Chart data - costs and tokens
    const chartData = data.buckets.map(bucket => ({
      time: bucket.time_bucket,
      total: bucket.total_cost,
      tokens_in: bucket.tokens_in || 0,
      tokens_out: bucket.tokens_out || 0,
      models: bucket.models
    }));

    return { chartData, modelBreakdown };
  }, [data, colorPalette]);

  // Custom tooltip for cost chart
  const CostTooltip = ({ active, payload, label }) => {
    if (!active || !payload || !payload[0]) return null;

    const dataPoint = payload[0].payload;
    const models = dataPoint.models || {};

    const sortedModels = Object.entries(models)
      .filter(([, cost]) => cost > 0)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    return (
      <div className="cost-tooltip-v2">
        <div className="tooltip-header-v2">{formatTimeBucket(label)}</div>
        <div className="tooltip-total-v2">{formatCost(dataPoint.total, 3)}</div>
        {sortedModels.length > 0 && (
          <div className="tooltip-models-v2">
            {sortedModels.map(([model, cost]) => (
              <div key={model} className="tooltip-model-row">
                <span className="tooltip-model-name">{shortenModelName(model)}</span>
                <span className="tooltip-model-cost">{formatCost(cost, 3)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Custom tooltip for token chart
  const TokenTooltip = ({ active, payload, label }) => {
    if (!active || !payload || !payload[0]) return null;

    const dataPoint = payload[0].payload;

    return (
      <div className="cost-tooltip-v2">
        <div className="tooltip-header-v2">{formatTimeBucket(label)}</div>
        <div className="tooltip-token-row">
          <span className="token-label" style={{ color: colorPalette.tokens.input }}>Input</span>
          <span className="token-value">{formatTokens(dataPoint.tokens_in)}</span>
        </div>
        <div className="tooltip-token-row">
          <span className="token-label" style={{ color: colorPalette.tokens.output }}>Output</span>
          <span className="token-value">{formatTokens(dataPoint.tokens_out)}</span>
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="cost-analytics-v2 loading">
        <div className="loading-pulse" />
        <span>Loading analytics...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cost-analytics-v2 error">
        <span className="error-icon">○</span>
        <span>{error}</span>
      </div>
    );
  }

  if (!data || !data.buckets || data.buckets.length === 0) {
    return (
      <div className="cost-analytics-v2 empty">
        <span>No cost data available</span>
      </div>
    );
  }

  const { chartData, modelBreakdown } = processedData;
  const totalCost = data.total_cost || 0;
  const totalTokensIn = data.total_tokens_in || 0;
  const totalTokensOut = data.total_tokens_out || 0;
  const maxModelCost = modelBreakdown.length > 0 ? modelBreakdown[0].cost : 0;

  return (
    <div className="cost-analytics-v2">
      {/* Header */}
      <div className="analytics-header">
        <div className="header-primary">
          <h3 className="analytics-title">Cost Analytics</h3>
          <div className="granularity-toggle">
            <button
              className={`granularity-btn ${granularity === 'hour' ? 'active' : ''}`}
              onClick={() => setGranularity('hour')}
            >
              Hourly
            </button>
            <button
              className={`granularity-btn ${granularity === 'day' ? 'active' : ''}`}
              onClick={() => setGranularity('day')}
            >
              Daily
            </button>
            <button
              className={`granularity-btn ${granularity === 'week' ? 'active' : ''}`}
              onClick={() => setGranularity('week')}
            >
              Weekly
            </button>
            <button
              className={`granularity-btn ${granularity === 'month' ? 'active' : ''}`}
              onClick={() => setGranularity('month')}
            >
              Monthly
            </button>
          </div>
        </div>
        <div className="header-stats">
          <div className="header-stat">
            <span className="stat-label">Total</span>
            <span className="stat-value cost">{formatCost(totalCost, 2)}</span>
          </div>
          <div className="header-stat">
            <span className="stat-label">Tokens</span>
            <span className="stat-value tokens">{formatTokens(totalTokensIn + totalTokensOut)}</span>
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="analytics-content">
        {/* Charts column */}
        <div className="charts-column">
          {/* Cost timeline chart */}
          <div className="chart-section">
            <div className="chart-label">
              <span className="chart-label-text">Cost</span>
            </div>
            <div className="timeline-chart">
              <ResponsiveContainer width="100%" height={120}>
                <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colorPalette.gradient.start} />
                      <stop offset="100%" stopColor={colorPalette.gradient.end} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="time"
                    tickFormatter={formatTimeBucket}
                    stroke="#3A4A5A"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    dy={4}
                    interval="preserveStartEnd"
                    hide
                  />
                  <YAxis
                    stroke="#3A4A5A"
                    fontSize={9}
                    tickFormatter={(v) => formatCost(v, 0)}
                    tickLine={false}
                    axisLine={false}
                    width={44}
                    dx={-4}
                  />
                  <Tooltip content={<CostTooltip />} cursor={{ stroke: 'rgba(74, 158, 221, 0.3)', strokeWidth: 1 }} />
                  <Area
                    type="monotone"
                    dataKey="total"
                    stroke="#4A9EDD"
                    strokeWidth={2}
                    fill="url(#costGradient)"
                    dot={false}
                    activeDot={{ r: 3, fill: '#4A9EDD', stroke: '#0B1219', strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Token usage chart */}
          <div className="chart-section token-section">
            <div className="chart-label">
              <span className="chart-label-text">Tokens</span>
              <div className="token-legend">
                <span className="token-legend-item">
                  <span className="legend-dot" style={{ background: colorPalette.tokens.input }} />
                  In
                </span>
                <span className="token-legend-item">
                  <span className="legend-dot" style={{ background: colorPalette.tokens.output }} />
                  Out
                </span>
              </div>
            </div>
            <div className="timeline-chart">
              <ResponsiveContainer width="100%" height={80}>
                <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="tokensInGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="rgba(94, 234, 212, 0.35)" />
                      <stop offset="100%" stopColor="rgba(94, 234, 212, 0.02)" />
                    </linearGradient>
                    <linearGradient id="tokensOutGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="rgba(167, 139, 250, 0.35)" />
                      <stop offset="100%" stopColor="rgba(167, 139, 250, 0.02)" />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="time"
                    tickFormatter={formatTimeBucket}
                    stroke="#3A4A5A"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    dy={4}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    stroke="#3A4A5A"
                    fontSize={9}
                    tickFormatter={formatTokens}
                    tickLine={false}
                    axisLine={false}
                    width={44}
                    dx={-4}
                  />
                  <Tooltip content={<TokenTooltip />} cursor={{ stroke: 'rgba(94, 234, 212, 0.3)', strokeWidth: 1 }} />
                  <Area
                    type="monotone"
                    dataKey="tokens_in"
                    stroke={colorPalette.tokens.input}
                    strokeWidth={1.5}
                    fill="url(#tokensInGradient)"
                    dot={false}
                    activeDot={{ r: 2, fill: colorPalette.tokens.input, stroke: '#0B1219', strokeWidth: 1 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="tokens_out"
                    stroke={colorPalette.tokens.output}
                    strokeWidth={1.5}
                    fill="url(#tokensOutGradient)"
                    dot={false}
                    activeDot={{ r: 2, fill: colorPalette.tokens.output, stroke: '#0B1219', strokeWidth: 1 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Model breakdown - horizontal bars */}
        <div className="model-breakdown">
          <div className="breakdown-header">
            <span className="breakdown-title">Model Distribution</span>
          </div>
          <div className="breakdown-bars">
            {modelBreakdown.map((item, idx) => {
              const percentage = maxModelCost > 0 ? (item.cost / totalCost) * 100 : 0;
              const barWidth = maxModelCost > 0 ? (item.cost / maxModelCost) * 100 : 0;
              const isHovered = hoveredModel === item.model;

              return (
                <div
                  key={item.model}
                  className={`breakdown-row ${isHovered ? 'hovered' : ''}`}
                  onMouseEnter={() => setHoveredModel(item.model)}
                  onMouseLeave={() => setHoveredModel(null)}
                >
                  <div className="breakdown-label">
                    <span
                      className="breakdown-dot"
                      style={{ background: item.color }}
                    />
                    <span className="breakdown-name">{item.displayName}</span>
                  </div>
                  <div className="breakdown-bar-container">
                    <div
                      className="breakdown-bar"
                      style={{
                        width: `${barWidth}%`,
                        background: item.color,
                        opacity: isHovered ? 1 : 0.7
                      }}
                    />
                  </div>
                  <div className="breakdown-values">
                    <span className="breakdown-cost">{formatCost(item.cost, 2)}</span>
                    <span className="breakdown-percent">{percentage.toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {cascadeFilter && (
        <div className="filter-indicator">
          Filtered: <span className="filter-value">{cascadeFilter}</span>
        </div>
      )}
    </div>
  );
}

export default CostTimelineChart;
