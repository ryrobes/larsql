import React, { useMemo, memo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Line,
  ComposedChart
} from 'recharts';
import { Icon } from '@iconify/react';
import './RunsActivityChart.css';

/**
 * RunsActivityChart - Shows runs count and cost efficiency trends
 * Helps answer: "Are we running more? Are we spending more per run?"
 */
const RunsActivityChart = ({ data = [], loading = false, granularity = 'daily' }) => {
  // Process data for chart
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];

    return data.map(point => {
      const date = new Date(point.date);
      let label;

      if (granularity === 'hourly') {
        label = date.toLocaleTimeString('en-US', { hour: 'numeric' });
      } else if (granularity === 'weekly') {
        label = `W${Math.ceil(date.getDate() / 7)}`;
      } else if (granularity === 'monthly') {
        label = date.toLocaleDateString('en-US', { month: 'short' });
      } else {
        label = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      }

      return {
        label,
        runs: point.runs || 0,
        avgCost: point.avg_cost || 0,
        contextPct: point.context_pct || 0,
      };
    });
  }, [data, granularity]);

  // Calculate stats
  const stats = useMemo(() => {
    if (chartData.length === 0) return { totalRuns: 0, avgPerPeriod: 0, avgCostPerRun: 0 };

    const totalRuns = chartData.reduce((sum, d) => sum + d.runs, 0);
    const avgPerPeriod = totalRuns / chartData.length;
    const avgCostPerRun = chartData.reduce((sum, d) => sum + d.avgCost, 0) / chartData.length;

    return { totalRuns, avgPerPeriod, avgCostPerRun };
  }, [chartData]);

  // Format currency - consistent 4 decimal places for grid alignment
  const formatCost = (value, forGrid = false) => {
    if (forGrid) {
      return `$${value.toFixed(4)}`;
    }
    // Dynamic format for stats/tooltips
    if (value >= 0.01) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="runs-tooltip">
          <div className="tooltip-header">{data.label}</div>
          <div className="tooltip-row">
            <span>Runs:</span>
            <span className="runs">{data.runs}</span>
          </div>
          <div className="tooltip-row">
            <span>Avg Cost:</span>
            <span className="cost">{formatCost(data.avgCost)}</span>
          </div>
          <div className="tooltip-row">
            <span>Context %:</span>
            <span>{data.contextPct.toFixed(1)}%</span>
          </div>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="runs-activity-chart loading">
        <div className="chart-header">
          <Icon icon="mdi:chart-line-variant" width={14} />
          <span className="chart-title">Runs & Efficiency</span>
        </div>
        <div className="chart-loading">
          <Icon icon="mdi:loading" className="spin" width={20} />
        </div>
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="runs-activity-chart empty">
        <div className="chart-header">
          <Icon icon="mdi:chart-line-variant" width={14} />
          <span className="chart-title">Runs & Efficiency</span>
        </div>
        <div className="chart-empty">
          <Icon icon="mdi:chart-line" width={24} />
          <span>No data</span>
        </div>
      </div>
    );
  }

  return (
    <div className="runs-activity-chart">
      <div className="chart-header">
        <Icon icon="mdi:chart-line-variant" width={14} />
        <span className="chart-title">Runs & Efficiency</span>
        <div className="chart-stats">
          <span className="stat">
            <span className="stat-value runs">{stats.totalRuns}</span>
            <span className="stat-label">runs</span>
          </span>
          <span className="stat">
            <span className="stat-value cost">{formatCost(stats.avgCostPerRun)}</span>
            <span className="stat-label">/run</span>
          </span>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="100%" height={100}>
          <ComposedChart
            data={chartData}
            margin={{ top: 5, right: 5, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="runsGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#a78bfa" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={{ fill: '#64748b', fontSize: 8 }}
              axisLine={{ stroke: 'rgba(100, 116, 139, 0.15)' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="runs"
              tick={{ fill: '#64748b', fontSize: 8 }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <YAxis
              yAxisId="cost"
              orientation="right"
              tick={{ fill: '#64748b', fontSize: 8 }}
              tickFormatter={formatCost}
              axisLine={false}
              tickLine={false}
              width={40}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              yAxisId="runs"
              type="monotone"
              dataKey="runs"
              stroke="#a78bfa"
              strokeWidth={1.5}
              fill="url(#runsGradient)"
            />
            <Line
              yAxisId="cost"
              type="monotone"
              dataKey="avgCost"
              stroke="#00e5ff"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="3 3"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#a78bfa' }}></span>
          Runs
        </span>
        <span className="legend-item">
          <span className="legend-line"></span>
          Avg Cost/Run
        </span>
      </div>

      {/* Data grid with time period breakdown */}
      <div className="chart-data-grid">
        <div className="grid-header">
          <span className="grid-col col-period">Period</span>
          <span className="grid-col col-runs">Runs</span>
          <span className="grid-col col-avg">Avg Cost</span>
          <span className="grid-col col-ctx">Ctx %</span>
        </div>
        <div className="grid-body">
          {chartData.slice(0, 8).map((item, index) => (
            <div key={index} className="grid-row">
              <span className="grid-col col-period">{item.label}</span>
              <span className="grid-col col-runs">{item.runs}</span>
              <span className="grid-col col-avg">{formatCost(item.avgCost, true)}</span>
              <span className="grid-col col-ctx">{item.contextPct.toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default memo(RunsActivityChart);
