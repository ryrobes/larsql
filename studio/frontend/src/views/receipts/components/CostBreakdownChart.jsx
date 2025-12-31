import React, { useMemo, useState, memo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie,
  Legend
} from 'recharts';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './CostBreakdownChart.css';

// Color palette for charts
const COLORS = [
  '#00e5ff', '#a78bfa', '#34d399', '#fbbf24', '#ff006e',
  '#60a5fa', '#f472b6', '#4ade80', '#fb923c', '#818cf8'
];

/**
 * CostBreakdownChart - Shows cost breakdown by cascade or model
 * Can display as horizontal bar chart or pie chart
 */
const CostBreakdownChart = ({
  data = [],
  type = 'cascade', // 'cascade' | 'model'
  chartType = 'bar', // 'bar' | 'pie'
  loading = false,
  onItemClick = null,
  grandTotal = 0
}) => {
  const [hoveredIndex, setHoveredIndex] = useState(null);

  // Process data for chart
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];

    return data.slice(0, 8).map((item, index) => {
      const name = type === 'cascade'
        ? item.cascade_id
        : (item.display_name || item.model);

      // Truncate long names
      const displayName = name.length > 25 ? name.substring(0, 22) + '...' : name;

      return {
        ...item,
        name: displayName,
        fullName: name,
        cost: item.total_cost,
        pct: item.pct_of_total,
        color: COLORS[index % COLORS.length],
      };
    });
  }, [data, type]);

  // Format currency - consistent 4 decimal places for grid alignment
  const formatCost = (value, forGrid = false) => {
    if (forGrid) {
      // Fixed format for data grid alignment
      return `$${value.toFixed(4)}`;
    }
    // Dynamic format for tooltips
    if (value >= 1) return `$${value.toFixed(2)}`;
    if (value >= 0.01) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Custom tooltip for bar chart
  const BarTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="breakdown-tooltip">
          <div className="tooltip-header">{data.fullName}</div>
          <div className="tooltip-row highlight">
            <span>Total Cost:</span>
            <span>{formatCost(data.cost)}</span>
          </div>
          <div className="tooltip-row">
            <span>% of Total:</span>
            <span>{data.pct.toFixed(1)}%</span>
          </div>
          <div className="tooltip-row">
            <span>Runs:</span>
            <span>{data.run_count}</span>
          </div>
          <div className="tooltip-row">
            <span>Avg per Run:</span>
            <span>{formatCost(data.avg_cost)}</span>
          </div>
          {data.outlier_count > 0 && (
            <div className="tooltip-row warning">
              <span>Outliers:</span>
              <span>{data.outlier_count}</span>
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Custom tooltip for pie chart
  const PieTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="breakdown-tooltip">
          <div className="tooltip-header">{data.fullName}</div>
          <div className="tooltip-row highlight">
            <span>Total Cost:</span>
            <span>{formatCost(data.cost)}</span>
          </div>
          <div className="tooltip-row">
            <span>% of Total:</span>
            <span>{data.pct.toFixed(1)}%</span>
          </div>
          <div className="tooltip-row">
            <span>Runs:</span>
            <span>{data.run_count}</span>
          </div>
          {data.total_tokens && (
            <div className="tooltip-row">
              <span>Tokens:</span>
              <span>{data.total_tokens.toLocaleString()}</span>
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Custom label for pie chart
  const renderPieLabel = ({ name, pct, cx, cy, midAngle, innerRadius, outerRadius }) => {
    if (pct < 5) return null; // Don't show labels for small slices
    const RADIAN = Math.PI / 180;
    const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    return (
      <text
        x={x}
        y={y}
        fill="#fff"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={10}
        fontWeight={500}
      >
        {pct.toFixed(0)}%
      </text>
    );
  };

  const title = type === 'cascade' ? 'Cost by Cascade' : 'Cost by Model';
  const icon = type === 'cascade' ? 'mdi:sitemap' : 'mdi:chip';

  if (loading) {
    return (
      <div className="cost-breakdown-chart loading">
        <div className="chart-header">
          <span className="chart-title">
            <Icon icon={icon} width={14} />
            {title}
          </span>
        </div>
        <VideoLoader size="small" showMessage={false} />
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="cost-breakdown-chart empty">
        <div className="chart-header">
          <span className="chart-title">
            <Icon icon={icon} width={14} />
            {title}
          </span>
        </div>
        <div className="chart-empty">
          <Icon icon={chartType === 'pie' ? 'mdi:chart-pie' : 'mdi:chart-bar'} width={24} />
          <span>No data</span>
        </div>
      </div>
    );
  }

  return (
    <div className="cost-breakdown-chart">
      <div className="chart-header">
        <span className="chart-title">
          <Icon icon={icon} width={14} />
          {title}
        </span>
        <span className="chart-subtitle">
          {data.length} {type === 'cascade' ? 'cascades' : 'models'} · {formatCost(grandTotal)} total
        </span>
      </div>

      <div className="chart-container">
        {chartType === 'bar' ? (
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(100, 116, 139, 0.1)" horizontal={true} vertical={false} />
              <XAxis
                type="number"
                tick={{ fill: '#64748b', fontSize: 9 }}
                tickFormatter={formatCost}
                axisLine={{ stroke: 'rgba(100, 116, 139, 0.15)' }}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={110}
              />
              <Tooltip content={<BarTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.03)' }} />
              <Bar
                dataKey="cost"
                radius={[0, 3, 3, 0]}
                onClick={(data) => onItemClick && onItemClick(data)}
                onMouseEnter={(_, index) => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                style={{ cursor: onItemClick ? 'pointer' : 'default' }}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.color}
                    opacity={hoveredIndex === null ? 0.85 : hoveredIndex === index ? 1 : 0.5}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height={140}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={45}
                outerRadius={70}
                paddingAngle={2}
                dataKey="cost"
                labelLine={false}
                label={renderPieLabel}
                onClick={(data) => onItemClick && onItemClick(data)}
                onMouseEnter={(_, index) => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                style={{ cursor: onItemClick ? 'pointer' : 'default' }}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.color}
                    opacity={hoveredIndex === null ? 0.85 : hoveredIndex === index ? 1 : 0.5}
                    stroke={hoveredIndex === index ? '#fff' : 'transparent'}
                    strokeWidth={2}
                  />
                ))}
              </Pie>
              <Tooltip content={<PieTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Data grid table - bar chart */}
      {chartType === 'bar' && (
        <div className="chart-data-grid">
          <div className="grid-header">
            <span className="grid-col col-name">Name</span>
            <span className="grid-col col-cost">Cost</span>
            <span className="grid-col col-pct">%</span>
          </div>
          <div className="grid-body">
            {chartData.map((item, index) => (
              <div
                key={index}
                className={`grid-row ${hoveredIndex === index ? 'hovered' : ''}`}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                onClick={() => onItemClick && onItemClick(item)}
              >
                <span className="grid-col col-name">
                  <span className="legend-dot" style={{ background: item.color }}></span>
                  {item.name}
                </span>
                <span className="grid-col col-cost">{formatCost(item.cost, true)}</span>
                <span className="grid-col col-pct">{item.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data grid table - pie chart */}
      {chartType === 'pie' && (
        <div className="chart-data-grid">
          <div className="grid-header">
            <span className="grid-col col-name">Model</span>
            <span className="grid-col col-cost">Cost</span>
            <span className="grid-col col-pct">%</span>
          </div>
          <div className="grid-body">
            {chartData.map((item, index) => (
              <div
                key={index}
                className={`grid-row ${hoveredIndex === index ? 'hovered' : ''}`}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                onClick={() => onItemClick && onItemClick(item)}
              >
                <span className="grid-col col-name">
                  <span className="legend-dot" style={{ background: item.color }}></span>
                  {item.name}
                </span>
                <span className="grid-col col-cost">{formatCost(item.cost, true)}</span>
                <span className="grid-col col-pct">{item.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default memo(CostBreakdownChart);
