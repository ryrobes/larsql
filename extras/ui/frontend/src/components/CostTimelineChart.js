import React, { useMemo } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';
import './CostTimelineChart.css';

function CostTimelineChart({ messages = [], isRunning = false }) {
  // Process messages into chart data
  const chartData = useMemo(() => {
    if (!messages || messages.length === 0) return [];

    // Filter to messages with cost or timestamps
    const relevantMessages = messages.filter(m =>
      m.cost > 0 || m.tokens_in > 0 || m.tokens_out > 0
    );

    if (relevantMessages.length === 0) return [];

    // Sort by timestamp
    const sorted = [...relevantMessages].sort((a, b) => a.timestamp - b.timestamp);

    // Calculate cumulative cost and time deltas
    let cumulativeCost = 0;
    const firstTimestamp = sorted[0].timestamp;

    return sorted.map((msg, index) => {
      cumulativeCost += msg.cost || 0;
      const timeSinceStart = msg.timestamp - firstTimestamp;

      // Determine color based on node_type/role
      let barColor = '#2DD4BF'; // Default teal
      if (msg.node_type === 'evaluator' || msg.message_category === 'evaluator') {
        barColor = '#a78bfa'; // Purple for evaluators
      } else if (msg.node_type === 'quartermaster' || msg.message_category === 'quartermaster') {
        barColor = '#60a5fa'; // Blue for quartermaster
      } else if (msg.sounding_index !== null && !msg.is_winner) {
        barColor = '#64748b'; // Gray for non-winner soundings
      } else if (msg.is_winner) {
        barColor = '#34d399'; // Green for winners
      }

      return {
        index,
        label: `${index + 1}`,
        cost: msg.cost || 0,
        cumulativeCost,
        timeSeconds: timeSinceStart,
        phase: msg.phase_name || '',
        role: msg.role,
        nodeType: msg.node_type,
        tokens: (msg.tokens_in || 0) + (msg.tokens_out || 0),
        model: msg.model,
        isWinner: msg.is_winner,
        soundingIndex: msg.sounding_index,
        barColor
      };
    });
  }, [messages]);

  // Calculate totals for header
  const totals = useMemo(() => {
    const totalCost = chartData.reduce((sum, d) => sum + d.cost, 0);
    const totalTokens = chartData.reduce((sum, d) => sum + d.tokens, 0);
    const totalTime = chartData.length > 0 ? chartData[chartData.length - 1].timeSeconds : 0;
    return { totalCost, totalTokens, totalTime };
  }, [chartData]);

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="cost-chart-tooltip">
          <div className="tooltip-header">Message #{data.index + 1}</div>
          <div className="tooltip-row">
            <span>Phase:</span>
            <span>{data.phase || 'N/A'}</span>
          </div>
          <div className="tooltip-row">
            <span>Type:</span>
            <span>{data.nodeType} / {data.role}</span>
          </div>
          <div className="tooltip-row highlight">
            <span>Cost:</span>
            <span>${data.cost.toFixed(6)}</span>
          </div>
          <div className="tooltip-row">
            <span>Tokens:</span>
            <span>{data.tokens.toLocaleString()}</span>
          </div>
          <div className="tooltip-row">
            <span>Time:</span>
            <span>{data.timeSeconds.toFixed(1)}s</span>
          </div>
          {data.model && (
            <div className="tooltip-row">
              <span>Model:</span>
              <span className="model-name">{data.model.split('/').pop()}</span>
            </div>
          )}
          {data.soundingIndex !== null && (
            <div className="tooltip-row">
              <span>Sounding:</span>
              <span>#{data.soundingIndex} {data.isWinner ? '(Winner)' : ''}</span>
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Format cost for Y-axis
  const formatCost = (value) => {
    if (value >= 0.01) return `$${value.toFixed(2)}`;
    if (value >= 0.001) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Format time for Y-axis
  const formatTime = (value) => {
    if (value >= 60) return `${(value / 60).toFixed(1)}m`;
    return `${value.toFixed(0)}s`;
  };

  if (chartData.length === 0) {
    return (
      <div className="cost-timeline-chart empty">
        <div className="chart-header">
          <span className="chart-title">Cost Timeline</span>
          <span className="no-data">No cost data yet</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`cost-timeline-chart ${isRunning ? 'running' : ''}`}>
      <div className="chart-header">
        <span className="chart-title">Cost Timeline</span>
        <div className="chart-stats">
          <span className="stat cost">
            <span className="stat-label">Total:</span>
            <span className="stat-value">${totals.totalCost.toFixed(4)}</span>
          </span>
          <span className="stat tokens">
            <span className="stat-label">Tokens:</span>
            <span className="stat-value">{totals.totalTokens.toLocaleString()}</span>
          </span>
          <span className="stat time">
            <span className="stat-label">Duration:</span>
            <span className="stat-value">{formatTime(totals.totalTime)}</span>
          </span>
          {isRunning && (
            <span className="stat running-indicator">
              <span className="pulse"></span>
              Live
            </span>
          )}
        </div>
      </div>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={100}>
          <ComposedChart
            data={chartData}
            margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: '#64748b', fontSize: 9 }}
              axisLine={{ stroke: '#2C3B4B' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="cost"
              orientation="left"
              tick={{ fill: '#2DD4BF', fontSize: 9 }}
              tickFormatter={formatCost}
              axisLine={false}
              tickLine={false}
              width={50}
            />
            <YAxis
              yAxisId="time"
              orientation="right"
              tick={{ fill: '#60a5fa', fontSize: 9 }}
              tickFormatter={formatTime}
              axisLine={false}
              tickLine={false}
              width={35}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              yAxisId="cost"
              dataKey="cost"
              radius={[2, 2, 0, 0]}
              isAnimationActive={true}
              animationDuration={300}
            >
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.barColor} />
              ))}
            </Bar>
            <Line
              yAxisId="time"
              type="monotone"
              dataKey="timeSeconds"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={false}
              isAnimationActive={true}
              animationDuration={300}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#2DD4BF' }}></span>
          Cost (left)
        </span>
        <span className="legend-item">
          <span className="legend-line" style={{ background: '#60a5fa' }}></span>
          Time (right)
        </span>
      </div>
    </div>
  );
}

export default CostTimelineChart;
