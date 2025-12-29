import React, { useMemo } from 'react';
import {
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from 'recharts';
import { Icon } from '@iconify/react';
import './ParetoChart.css';

/**
 * ParetoChart - Visualizes the Pareto frontier for multi-model soundings
 *
 * Shows a scatter plot of cost vs quality with:
 * - Green points for Pareto-optimal solutions (frontier)
 * - Gray points for dominated solutions
 * - Star marker for the selected winner
 * - Dashed line connecting frontier points (the Pareto curve)
 * - Model color coding
 */
function ParetoChart({ paretoData, onPointClick }) {
  // Process data for visualization
  const { frontierData, dominatedData, winnerData, frontierLine, modelColors, stats } = useMemo(() => {
    if (!paretoData || !paretoData.all_soundings) {
      return { frontierData: [], dominatedData: [], winnerData: [], frontierLine: [], modelColors: {}, stats: null };
    }

    // Generate consistent colors for each model
    const uniqueModels = [...new Set(paretoData.all_soundings.map(s => s.model))];
    const colorPalette = [
      '#a78bfa', // purple
      '#60a5fa', // blue
      '#34d399', // green
      '#fbbf24', // yellow
      '#f472b6', // pink
      '#fb923c', // orange
    ];
    const colors = {};
    uniqueModels.forEach((model, idx) => {
      colors[model] = colorPalette[idx % colorPalette.length];
    });

    // Separate frontier, dominated, and winner
    const frontier = [];
    const dominated = [];
    let winner = null;

    paretoData.all_soundings.forEach((sounding) => {
      const point = {
        ...sounding,
        // Scale cost to be visible (multiply by 1000 for display in millicents)
        displayCost: sounding.cost * 1000,
        color: colors[sounding.model],
        shortModel: sounding.model.split('/').pop(),
      };

      if (sounding.is_winner) {
        winner = point;
      }

      if (sounding.is_pareto_optimal) {
        frontier.push(point);
      } else {
        dominated.push(point);
      }
    });

    // Sort frontier by cost for line drawing
    const sortedFrontier = [...frontier].sort((a, b) => a.cost - b.cost);

    // Calculate stats
    const allCosts = paretoData.all_soundings.map(s => s.cost);
    const allQualities = paretoData.all_soundings.map(s => s.quality);
    const calculatedStats = {
      minCost: Math.min(...allCosts),
      maxCost: Math.max(...allCosts),
      minQuality: Math.min(...allQualities),
      maxQuality: Math.max(...allQualities),
      frontierSize: frontier.length,
      dominatedSize: dominated.length,
      totalSoundings: paretoData.all_soundings.length,
    };

    return {
      frontierData: frontier,
      dominatedData: dominated,
      winnerData: winner ? [winner] : [],
      frontierLine: sortedFrontier,
      modelColors: colors,
      stats: calculatedStats,
    };
  }, [paretoData]);

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload || !payload.length) return null;

    const point = payload[0].payload;
    return (
      <div className="pareto-tooltip">
        <div className="tooltip-header">
          <span className="tooltip-model" style={{ color: point.color }}>
            {point.shortModel}
          </span>
          {point.is_winner && (
            <Icon icon="mdi:trophy" width="14" className="tooltip-trophy" />
          )}
        </div>
        <div className="tooltip-row">
          <Icon icon="mdi:chart-line" width="12" />
          <span>Quality: {point.quality.toFixed(1)}</span>
        </div>
        <div className="tooltip-row">
          <Icon icon="mdi:currency-usd" width="12" />
          <span>Cost: ${point.cost.toFixed(6)}</span>
        </div>
        <div className="tooltip-row">
          <Icon icon="mdi:identifier" width="12" />
          <span>Sounding #{point.index}</span>
        </div>
        {point.is_pareto_optimal && (
          <div className="tooltip-badge frontier">Pareto Optimal</div>
        )}
        {!point.is_pareto_optimal && (
          <div className="tooltip-badge dominated">Dominated</div>
        )}
      </div>
    );
  };

  // Custom dot for scatter points
  const renderDot = (props, type) => {
    const { cx, cy, payload } = props;
    if (!cx || !cy) return null;

    const isWinner = payload.is_winner;
    const size = isWinner ? 12 : type === 'frontier' ? 8 : 6;

    if (isWinner) {
      // Star shape for winner
      return (
        <g>
          <circle
            cx={cx}
            cy={cy}
            r={size + 4}
            fill="none"
            stroke="#fbbf24"
            strokeWidth="2"
            strokeDasharray="4 2"
          />
          <polygon
            points={getStarPoints(cx, cy, size, size / 2)}
            fill="#fbbf24"
            stroke="#1a1d24"
            strokeWidth="1"
          />
        </g>
      );
    }

    return (
      <circle
        cx={cx}
        cy={cy}
        r={size}
        fill={type === 'frontier' ? payload.color : '#4a5568'}
        stroke={type === 'frontier' ? '#1a1d24' : 'none'}
        strokeWidth="2"
        opacity={type === 'frontier' ? 1 : 0.5}
        style={{ cursor: 'pointer' }}
      />
    );
  };

  // Helper to generate star polygon points
  const getStarPoints = (cx, cy, outerRadius, innerRadius) => {
    const points = [];
    for (let i = 0; i < 5; i++) {
      // Outer point
      const outerAngle = (i * 72 - 90) * (Math.PI / 180);
      points.push(`${cx + outerRadius * Math.cos(outerAngle)},${cy + outerRadius * Math.sin(outerAngle)}`);
      // Inner point
      const innerAngle = ((i * 72) + 36 - 90) * (Math.PI / 180);
      points.push(`${cx + innerRadius * Math.cos(innerAngle)},${cy + innerRadius * Math.sin(innerAngle)}`);
    }
    return points.join(' ');
  };

  // Format cost for axis
  const formatCost = (value) => {
    if (value === 0) return '$0';
    if (value < 1) return `$${(value / 1000).toFixed(4)}`;
    return `$${(value / 1000).toFixed(3)}`;
  };

  if (!paretoData || !paretoData.all_soundings || paretoData.all_soundings.length === 0) {
    return (
      <div className="pareto-empty">
        <Icon icon="mdi:chart-scatter-plot" width="48" />
        <span>No Pareto data available</span>
      </div>
    );
  }

  return (
    <div className="pareto-chart-container">
      {/* Header with stats */}
      <div className="pareto-header">
        <div className="pareto-title">
          <Icon icon="mdi:chart-scatter-plot" width="20" />
          <span>Pareto Frontier Analysis</span>
        </div>
        <div className="pareto-stats">
          <span className="stat">
            <Icon icon="mdi:target" width="14" />
            {stats?.frontierSize || 0} on frontier
          </span>
          <span className="stat">
            <Icon icon="mdi:dots-horizontal" width="14" />
            {stats?.dominatedSize || 0} dominated
          </span>
          <span className="stat winner-stat">
            <Icon icon="mdi:trophy" width="14" />
            {paretoData.cell_name || 'Unknown'} phase
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="pareto-chart-wrapper">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart
            margin={{ top: 20, right: 30, bottom: 40, left: 50 }}
          >
            <XAxis
              type="number"
              dataKey="displayCost"
              name="Cost"
              tickFormatter={formatCost}
              domain={['dataMin - 0.1', 'dataMax + 0.1']}
              label={{
                value: 'Cost ($)',
                position: 'bottom',
                offset: 20,
                style: { fill: '#8b92a0', fontSize: 12 }
              }}
              tick={{ fill: '#8b92a0', fontSize: 11 }}
              stroke="#3a3f4b"
            />
            <YAxis
              type="number"
              dataKey="quality"
              name="Quality"
              domain={[
                (dataMin) => Math.max(0, Math.floor(dataMin - 5)),
                (dataMax) => Math.min(100, Math.ceil(dataMax + 5))
              ]}
              label={{
                value: 'Quality Score',
                angle: -90,
                position: 'insideLeft',
                style: { fill: '#8b92a0', fontSize: 12, textAnchor: 'middle' }
              }}
              tick={{ fill: '#8b92a0', fontSize: 11 }}
              stroke="#3a3f4b"
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Pareto frontier line (dashed, connecting frontier points) */}
            {frontierLine.length > 1 && (
              <Line
                type="monotone"
                data={frontierLine}
                dataKey="quality"
                stroke="#34d399"
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                isAnimationActive={false}
                name="Pareto Frontier"
                xAxisId={0}
                yAxisId={0}
              />
            )}

            {/* Dominated points (gray) */}
            <Scatter
              name="Dominated"
              data={dominatedData}
              fill="#4a5568"
              opacity={0.5}
              shape={(props) => renderDot(props, 'dominated')}
            />

            {/* Frontier points (colored by model) */}
            <Scatter
              name="Pareto Optimal"
              data={frontierData}
              shape={(props) => renderDot(props, 'frontier')}
            />

            {/* Winner point (star) */}
            {winnerData.length > 0 && (
              <Scatter
                name="Winner"
                data={winnerData}
                shape={(props) => renderDot(props, 'winner')}
              />
            )}

            <Legend
              wrapperStyle={{ paddingTop: 10 }}
              formatter={(value) => (
                <span style={{ color: '#d4d7dd', fontSize: 11 }}>{value}</span>
              )}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Model Legend */}
      <div className="model-legend">
        <span className="legend-title">Models:</span>
        {Object.entries(modelColors).map(([model, color]) => (
          <span key={model} className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: color }} />
            <span className="legend-model">{model.split('/').pop()}</span>
          </span>
        ))}
      </div>

      {/* Winner Info */}
      {winnerData.length > 0 && (
        <div className="winner-info">
          <Icon icon="mdi:trophy" width="16" />
          <span>
            Winner: <strong>{winnerData[0].shortModel}</strong>
            {' '} (Quality: {winnerData[0].quality.toFixed(1)}, Cost: ${winnerData[0].cost.toFixed(6)})
          </span>
        </div>
      )}
    </div>
  );
}

export default ParetoChart;
