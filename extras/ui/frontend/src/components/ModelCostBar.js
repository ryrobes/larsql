import React from 'react';
import { Icon } from '@iconify/react';
import './ModelCostBar.css';

// Color palette for different models - using theme-compatible colors
const MODEL_COLORS = [
  '#2DD4BF', // Glacial Ice
  '#D9A553', // Compass Brass
  '#60a5fa', // Blue
  '#a78bfa', // Purple
  '#4ADE80', // Aurora Green
  '#f472b6', // Pink
  '#fb923c', // Orange
  '#22d3ee', // Cyan
];

function ModelCostBar({ modelCosts, totalCost, usedCost = 0, explorationCost = 0 }) {
  // Don't render if there's only one model or no costs
  if (!modelCosts || modelCosts.length <= 1) {
    return null;
  }

  // Calculate percentages and assign colors
  const modelsWithPercentage = modelCosts.map((mc, idx) => ({
    ...mc,
    percentage: totalCost > 0 ? (mc.cost / totalCost) * 100 : 0,
    color: MODEL_COLORS[idx % MODEL_COLORS.length],
    shortName: mc.model.split('/').pop() // Just the model name without provider
  }));

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  // Calculate efficiency percentage
  const efficiencyPercent = totalCost > 0 ? Math.round((usedCost / totalCost) * 100) : 100;
  const hasExploration = explorationCost > 0;

  return (
    <div className="model-cost-bar-container">
      {/* Stacked bar visualization */}
      <div className="model-cost-bar">
        {modelsWithPercentage.map((mc, idx) => (
          <div
            key={idx}
            className="model-cost-segment"
            style={{
              width: `${Math.max(mc.percentage, 2)}%`, // Min 2% for visibility
              backgroundColor: mc.color,
            }}
            title={`${mc.shortName}: ${formatCost(mc.cost)} (${mc.percentage.toFixed(1)}%)`}
          />
        ))}
      </div>

      {/* Legend items */}
      <div className="model-cost-legend">
        {modelsWithPercentage.map((mc, idx) => (
          <div key={idx} className="model-cost-legend-item">
            <span
              className="model-cost-dot"
              style={{ backgroundColor: mc.color }}
            />
            <span className="model-cost-name">{mc.shortName}</span>
            <span className="model-cost-value">{formatCost(mc.cost)}</span>
          </div>
        ))}
      </div>

      {/* Efficiency summary - only show when there's exploration cost */}
      {hasExploration && (
        <div className="model-cost-efficiency-summary">
          <span className="efficiency-total">
            {formatCost(totalCost)}
          </span>
          <span className="efficiency-divider">│</span>
          <span className="efficiency-stat kept">
            {formatCost(usedCost)} kept ({efficiencyPercent}%)
          </span>
          <span className="efficiency-divider">│</span>
          <span className="efficiency-stat explored">
            {formatCost(explorationCost)} explored
          </span>
        </div>
      )}
    </div>
  );
}

// Simple version just showing model tags (for single model case)
export function ModelTags({ modelsUsed }) {
  if (!modelsUsed || modelsUsed.length === 0) {
    return null;
  }

  return (
    <div className="models-used">
      {modelsUsed.map((model, idx) => (
        <span key={idx} className="model-tag">
          <Icon icon="mdi:robot" width="12" />
          {model.split('/').pop()}
        </span>
      ))}
    </div>
  );
}

export default ModelCostBar;
