import React, { useMemo, useState } from 'react';
import {
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from 'recharts';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * ParetoLayer - Visualizes Pareto frontier for multi-model candidates
 *
 * Shows cost vs quality trade-offs with frontier curve and winner highlighting.
 * Only rendered when pareto frontier analysis was performed.
 */
const ParetoLayer = ({ paretoData }) => {
  const [isExpanded, setIsExpanded] = useState(true);

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
      <div className="layer-pareto-tooltip">
        <div className="pareto-tooltip-header">
          <span className="pareto-tooltip-model" style={{ color: point.color }}>
            {point.shortModel}
          </span>
          {point.is_winner && (
            <Icon icon="mdi:trophy" width="12" className="pareto-tooltip-trophy" />
          )}
        </div>
        <div className="pareto-tooltip-row">
          <Icon icon="mdi:chart-line" width="10" />
          <span>Quality: {point.quality.toFixed(1)}</span>
        </div>
        <div className="pareto-tooltip-row">
          <Icon icon="mdi:currency-usd" width="10" />
          <span>Cost: ${point.cost.toFixed(6)}</span>
        </div>
        <div className="pareto-tooltip-row">
          <Icon icon="mdi:identifier" width="10" />
          <span>Candidate #{point.index}</span>
        </div>
        {point.is_pareto_optimal && (
          <div className="pareto-tooltip-badge frontier">Optimal</div>
        )}
        {!point.is_pareto_optimal && (
          <div className="pareto-tooltip-badge dominated">Dominated</div>
        )}
      </div>
    );
  };

  // Custom dot for scatter points
  const renderDot = (props, type) => {
    const { cx, cy, payload } = props;
    if (!cx || !cy) return null;

    const isWinner = payload.is_winner;
    const size = isWinner ? 10 : type === 'frontier' ? 7 : 5;

    if (isWinner) {
      // Star shape for winner with gold
      return (
        <g>
          <circle
            cx={cx}
            cy={cy}
            r={size + 3}
            fill="none"
            stroke="#FFD700"
            strokeWidth="1.5"
            strokeDasharray="3 2"
          />
          <polygon
            points={getStarPoints(cx, cy, size, size / 2)}
            fill="#FFD700"
            stroke="#0a0a0a"
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
        stroke={type === 'frontier' ? '#0a0a0a' : 'none'}
        strokeWidth="1.5"
        opacity={type === 'frontier' ? 1 : 0.4}
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
    return null; // Don't render empty state in anatomy panel
  }

  return (
    <div className="cell-anatomy-layer cell-anatomy-layer-pareto">
      <div className="cell-anatomy-layer-header" onClick={() => setIsExpanded(!isExpanded)}>
        <div className="cell-anatomy-layer-icon layer-icon-pareto">
          <Icon icon="mdi:chart-scatter-plot" width="14" />
        </div>
        <span className="cell-anatomy-layer-title">Pareto Frontier</span>

        {/* Stats badges */}
        <div className="layer-pareto-badges">
          <span className="layer-pareto-badge badge-frontier">
            <Icon icon="mdi:target" width="10" />
            {stats?.frontierSize || 0} optimal
          </span>
          <span className="layer-pareto-badge badge-dominated">
            <Icon icon="mdi:dots-horizontal" width="10" />
            {stats?.dominatedSize || 0} dominated
          </span>
        </div>

        <Icon
          icon={isExpanded ? "mdi:chevron-up" : "mdi:chevron-down"}
          width="16"
          className="cell-anatomy-layer-chevron"
        />
      </div>

      {isExpanded && (
        <div className="cell-anatomy-layer-content">
          {/* Chart */}
          <div className="layer-pareto-chart-wrapper">
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart margin={{ top: 10, right: 20, bottom: 30, left: 40 }}>
                <XAxis
                  type="number"
                  dataKey="displayCost"
                  name="Cost"
                  tickFormatter={formatCost}
                  domain={['dataMin - 0.1', 'dataMax + 0.1']}
                  label={{
                    value: 'Cost ($)',
                    position: 'bottom',
                    offset: 10,
                    style: { fill: '#64748b', fontSize: 10 }
                  }}
                  tick={{ fill: '#64748b', fontSize: 9 }}
                  stroke="#1a1628"
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
                    value: 'Quality',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fill: '#64748b', fontSize: 10, textAnchor: 'middle' }
                  }}
                  tick={{ fill: '#64748b', fontSize: 9 }}
                  stroke="#1a1628"
                />
                <Tooltip content={<CustomTooltip />} />

                {/* Pareto frontier line (green dashed) */}
                {frontierLine.length > 1 && (
                  <Line
                    type="monotone"
                    data={frontierLine}
                    dataKey="quality"
                    stroke="#34d399"
                    strokeWidth={2}
                    strokeDasharray="5 3"
                    dot={false}
                    isAnimationActive={false}
                    name="Frontier"
                    xAxisId={0}
                    yAxisId={0}
                  />
                )}

                {/* Dominated points (gray) */}
                <Scatter
                  name="Dominated"
                  data={dominatedData}
                  fill="#4a5568"
                  shape={(props) => renderDot(props, 'dominated')}
                />

                {/* Frontier points (colored by model) */}
                <Scatter
                  name="Optimal"
                  data={frontierData}
                  shape={(props) => renderDot(props, 'frontier')}
                />

                {/* Winner point (gold star) */}
                {winnerData.length > 0 && (
                  <Scatter
                    name="Winner"
                    data={winnerData}
                    shape={(props) => renderDot(props, 'winner')}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Model Legend */}
          <div className="layer-pareto-legend">
            <span className="layer-pareto-legend-title">Models:</span>
            {Object.entries(modelColors).map(([model, color]) => (
              <span key={model} className="layer-pareto-legend-item">
                <span className="layer-pareto-legend-dot" style={{ backgroundColor: color }} />
                <span className="layer-pareto-legend-model">{model.split('/').pop()}</span>
              </span>
            ))}
          </div>

          {/* Winner Info */}
          {winnerData.length > 0 && (
            <div className="layer-pareto-winner">
              <Icon icon="mdi:trophy" width="12" />
              <span>
                Winner: <strong>{winnerData[0].shortModel}</strong>
                {' '} (Q: {winnerData[0].quality.toFixed(1)}, ${winnerData[0].cost.toFixed(6)})
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ParetoLayer;
