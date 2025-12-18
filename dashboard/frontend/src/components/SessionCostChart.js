import React, { useMemo, useState } from 'react';
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
import { getSequentialColor } from './CascadeBar';
import './SessionCostChart.css';

function SessionCostChart({ messages = [], isRunning = false, onBarClick = null }) {
  const [hoveredBar, setHoveredBar] = useState(null);

  // Build phase color map based on order of first appearance
  const phaseColorMap = useMemo(() => {
    if (!messages || messages.length === 0) return {};

    const map = {};
    let colorIndex = 0;

    // Sort by timestamp to get correct order
    const sorted = [...messages].sort((a, b) => a.timestamp - b.timestamp);

    sorted.forEach(msg => {
      const phaseName = msg.phase_name || '_unknown_';
      if (!(phaseName in map)) {
        map[phaseName] = getSequentialColor(colorIndex);
        colorIndex++;
      }
    });

    return map;
  }, [messages]);

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
    let prevTimestamp = sorted[0].timestamp;

    return sorted.map((msg, index) => {
      cumulativeCost += msg.cost || 0;
      // Calculate duration of this message (time since previous message)
      const messageDuration = index === 0 ? 0 : msg.timestamp - prevTimestamp;
      prevTimestamp = msg.timestamp;

      // Get phase color from our map (matches CascadeBar colors)
      const phaseName = msg.phase_name || '_unknown_';
      let barColor = phaseColorMap[phaseName] || '#2DD4BF';

      // Dim non-winner soundings slightly
      const isDimmed = msg.sounding_index !== null && !msg.is_winner;

      // Find the original index in all_messages for scrolling
      // Prefer _index from backend (avoids timestamp collision issues)
      let originalIndex = msg._index;
      if (originalIndex === undefined || originalIndex === null) {
        // Fallback: Match by multiple fields for uniqueness
        originalIndex = messages.findIndex(m =>
          m.timestamp === msg.timestamp &&
          m.phase_name === msg.phase_name &&
          m.node_type === msg.node_type &&
          m.turn_number === msg.turn_number &&
          m.sounding_index === msg.sounding_index &&
          m.role === msg.role
        );
      }

      return {
        index,
        originalIndex, // Index in all_messages for scrolling
        label: `${index + 1}`,
        cost: msg.cost || 0,
        cumulativeCost,
        duration: messageDuration, // Time this message took (delta from previous)
        phase: phaseName,
        role: msg.role,
        nodeType: msg.node_type,
        tokens: (msg.tokens_in || 0) + (msg.tokens_out || 0),
        model: msg.model,
        isWinner: msg.is_winner,
        soundingIndex: msg.sounding_index,
        barColor,
        isDimmed
      };
    });
  }, [messages, phaseColorMap]);

  // Calculate totals for header
  const totals = useMemo(() => {
    const totalCost = chartData.reduce((sum, d) => sum + d.cost, 0);
    const totalTokens = chartData.reduce((sum, d) => sum + d.tokens, 0);
    const totalDuration = chartData.reduce((sum, d) => sum + d.duration, 0);
    return { totalCost, totalTokens, totalDuration };
  }, [chartData]);

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="session-cost-tooltip">
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
            <span>Duration:</span>
            <span>{data.duration.toFixed(1)}s</span>
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
      <div className="session-cost-chart empty">
        <div className="chart-header">
          <span className="chart-title">Session Cost Timeline</span>
          <span className="no-data">No cost data yet</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`session-cost-chart ${isRunning ? 'running' : ''}`}>
      <div className="chart-header">
        <span className="chart-title">Session Cost Timeline</span>
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
            <span className="stat-value">{formatTime(totals.totalDuration)}</span>
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
              onClick={(data, index) => {
                if (onBarClick && data && data.originalIndex !== undefined) {
                  onBarClick(data.originalIndex);
                }
              }}
              onMouseEnter={(data, index) => setHoveredBar(index)}
              onMouseLeave={() => setHoveredBar(null)}
              style={{ cursor: onBarClick ? 'pointer' : 'default' }}
            >
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.barColor}
                  opacity={entry.isDimmed ? 0.4 : (hoveredBar === index ? 1 : 0.85)}
                  stroke={hoveredBar === index ? '#fff' : 'none'}
                  strokeWidth={hoveredBar === index ? 1 : 0}
                />
              ))}
            </Bar>
            <Line
              yAxisId="time"
              type="monotone"
              dataKey="duration"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={{ r: 3, fill: '#60a5fa', stroke: '#0a0f14', strokeWidth: 1, cursor: 'pointer' }}
              activeDot={{
                r: 5,
                fill: '#60a5fa',
                stroke: '#fff',
                strokeWidth: 2,
                cursor: 'pointer',
                onClick: (e, payload) => {
                  if (onBarClick && payload && payload.payload && payload.payload.originalIndex !== undefined) {
                    onBarClick(payload.payload.originalIndex);
                  }
                }
              }}
              isAnimationActive={true}
              animationDuration={300}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        {Object.entries(phaseColorMap).slice(0, 6).map(([phase, color]) => (
          <span key={phase} className="legend-item phase-legend">
            <span className="legend-dot" style={{ background: color }}></span>
            {phase === '_unknown_' ? 'Init' : phase.length > 12 ? phase.substring(0, 10) + '...' : phase}
          </span>
        ))}
        {Object.keys(phaseColorMap).length > 6 && (
          <span className="legend-item phase-legend">
            +{Object.keys(phaseColorMap).length - 6} more
          </span>
        )}
        <span className="legend-divider">|</span>
        <span className="legend-item">
          <span className="legend-line" style={{ background: '#60a5fa' }}></span>
          Time
        </span>
      </div>
    </div>
  );
}

export default SessionCostChart;
