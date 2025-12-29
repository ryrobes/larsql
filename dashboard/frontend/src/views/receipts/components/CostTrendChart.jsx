import React, { useMemo, memo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts';
import { Icon } from '@iconify/react';
import './CostTrendChart.css';

/**
 * CostTrendChart - Time series visualization of cost trends
 */
const CostTrendChart = ({ data = [], loading = false, granularity = 'daily', onPointClick = null }) => {
  // Process data for chart
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];

    return data.map(point => {
      const date = new Date(point.date);
      let label;

      if (granularity === 'hourly') {
        label = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
      } else if (granularity === 'weekly') {
        label = `Wk ${Math.ceil(date.getDate() / 7)}`;
      } else if (granularity === 'monthly') {
        label = date.toLocaleDateString('en-US', { month: 'short' });
      } else {
        label = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      }

      return {
        ...point,
        label,
        displayCost: point.cost,
        displayContextCost: point.context_cost || 0,
        newCost: (point.cost || 0) - (point.context_cost || 0),
      };
    });
  }, [data, granularity]);

  // Calculate average
  const avgCost = useMemo(() => {
    if (chartData.length === 0) return 0;
    return chartData.reduce((sum, d) => sum + d.displayCost, 0) / chartData.length;
  }, [chartData]);

  // Format currency
  const formatCost = (value) => {
    if (value >= 1) return `$${value.toFixed(2)}`;
    if (value >= 0.01) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="cost-trend-tooltip">
          <div className="tooltip-header">{data.label}</div>
          <div className="tooltip-row highlight">
            <span>Total:</span>
            <span>{formatCost(data.displayCost)}</span>
          </div>
          <div className="tooltip-row">
            <span>Context:</span>
            <span className="context">{formatCost(data.displayContextCost)}</span>
          </div>
          <div className="tooltip-row">
            <span>New:</span>
            <span className="new">{formatCost(data.newCost)}</span>
          </div>
          <div className="tooltip-row">
            <span>Runs:</span>
            <span>{data.runs}</span>
          </div>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="cost-trend-chart loading">
        <div className="chart-loading">
          <Icon icon="mdi:loading" className="spin" width={20} />
        </div>
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="cost-trend-chart empty">
        <div className="chart-empty">
          <Icon icon="mdi:chart-line" width={24} />
          <span>No data</span>
        </div>
      </div>
    );
  }

  return (
    <div className="cost-trend-chart">
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={120}>
          <AreaChart
            data={chartData}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00e5ff" stopOpacity={0.25}/>
                <stop offset="95%" stopColor="#00e5ff" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="contextGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.25}/>
                <stop offset="95%" stopColor="#a78bfa" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(100, 116, 139, 0.1)" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: '#64748b', fontSize: 9 }}
              axisLine={{ stroke: 'rgba(100, 116, 139, 0.15)' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 9 }}
              tickFormatter={formatCost}
              axisLine={false}
              tickLine={false}
              width={50}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={avgCost} stroke="#475569" strokeDasharray="3 3" />
            <Area
              type="monotone"
              dataKey="displayContextCost"
              stackId="1"
              stroke="#a78bfa"
              strokeWidth={0}
              fill="url(#contextGradient)"
            />
            <Area
              type="monotone"
              dataKey="newCost"
              stackId="1"
              stroke="#00e5ff"
              strokeWidth={1.5}
              fill="url(#costGradient)"
              activeDot={{
                r: 4,
                fill: '#00e5ff',
                stroke: '#0a0a0a',
                strokeWidth: 2,
                cursor: onPointClick ? 'pointer' : 'default'
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#00e5ff' }}></span>
          New Content
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#a78bfa' }}></span>
          Context
        </span>
        <span className="legend-item">
          <span className="legend-line"></span>
          Avg
        </span>
      </div>
    </div>
  );
};

export default memo(CostTrendChart);
