import React, { useMemo, memo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';
import { Icon } from '@iconify/react';
import './ContextValueChart.css';

/**
 * ContextValueChart - Shows distribution of context cost by relevance tier
 * Answers: "Where is my context budget going - useful or wasted?"
 */
const ContextValueChart = ({ data = null, loading = false }) => {
  // Process distribution data for chart
  const chartData = useMemo(() => {
    if (!data?.distribution) return [];
    return data.distribution.map(tier => ({
      ...tier,
      name: tier.label,
    }));
  }, [data]);

  // Calculate summary stats
  const stats = useMemo(() => {
    if (!data) return { useful: 0, wasted: 0, efficiency: 0 };

    const useful = (data.high_value_cost || 0) + (data.medium_value_cost || 0);
    const wasted = data.wasted_cost || 0;

    return {
      useful,
      wasted,
      efficiency: data.efficiency_score || 0,
      wastedPct: data.wasted_pct || 0,
    };
  }, [data]);

  const formatCost = (value) => {
    if (value >= 1) return `$${value.toFixed(2)}`;
    if (value >= 0.01) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const tier = payload[0].payload;
      return (
        <div className="context-value-tooltip">
          <div className="tooltip-header">{tier.label} ({tier.tier})</div>
          <div className="tooltip-row">
            <span>Cost:</span>
            <span className="value">{formatCost(tier.cost)}</span>
          </div>
          <div className="tooltip-row">
            <span>Messages:</span>
            <span>{tier.count}</span>
          </div>
          <div className="tooltip-row">
            <span>% of Context:</span>
            <span>{tier.pct.toFixed(1)}%</span>
          </div>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="context-value-chart loading">
        <div className="chart-header">
          <Icon icon="mdi:target" width={14} />
          <span className="chart-title">Context Value</span>
        </div>
        <div className="chart-loading">
          <Icon icon="mdi:loading" className="spin" width={20} />
        </div>
      </div>
    );
  }

  if (!data || chartData.length === 0) {
    return (
      <div className="context-value-chart empty">
        <div className="chart-header">
          <Icon icon="mdi:target" width={14} />
          <span className="chart-title">Context Value</span>
        </div>
        <div className="chart-empty">
          <Icon icon="mdi:database-off" width={24} />
          <span>No relevance data</span>
        </div>
      </div>
    );
  }

  return (
    <div className="context-value-chart">
      <div className="chart-header">
        <Icon icon="mdi:target" width={14} />
        <span className="chart-title">Context Value</span>
        <div className="chart-stats">
          <span className="stat useful">
            <span className="stat-value">{formatCost(stats.useful)}</span>
            <span className="stat-label">useful</span>
          </span>
          <span className="stat wasted">
            <span className="stat-value">{formatCost(stats.wasted)}</span>
            <span className="stat-label">wasted</span>
          </span>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="100%" height={100}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 5, right: 5, left: 0, bottom: 5 }}
          >
            <XAxis
              type="number"
              tick={{ fill: '#64748b', fontSize: 8 }}
              tickFormatter={(v) => `${v.toFixed(0)}%`}
              axisLine={{ stroke: 'rgba(100, 116, 139, 0.15)' }}
              tickLine={false}
              domain={[0, 'dataMax']}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fill: '#94a3b8', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              width={55}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.03)' }} />
            <Bar
              dataKey="pct"
              radius={[0, 3, 3, 0]}
            >
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} opacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Data grid */}
      <div className="chart-data-grid">
        <div className="grid-header">
          <span className="grid-col col-tier">Tier</span>
          <span className="grid-col col-cost">Cost</span>
          <span className="grid-col col-msgs">Msgs</span>
          <span className="grid-col col-pct">%</span>
        </div>
        <div className="grid-body">
          {chartData.map((tier, index) => (
            <div key={index} className="grid-row">
              <span className="grid-col col-tier">
                <span className="tier-dot" style={{ background: tier.color }}></span>
                {tier.label}
              </span>
              <span className="grid-col col-cost">{formatCost(tier.cost)}</span>
              <span className="grid-col col-msgs">{tier.count}</span>
              <span className="grid-col col-pct">{tier.pct.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default memo(ContextValueChart);
