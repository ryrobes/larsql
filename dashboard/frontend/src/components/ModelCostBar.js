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

function ModelCostBar({ modelCosts, totalCost, usedCost = 0, explorationCost = 0, winnerModel = null }) {
  // Don't render if no model cost data
  if (!modelCosts || modelCosts.length === 0) {
    return null;
  }

  // Normalize winnerModel to an array for easier comparison
  const winnerModels = winnerModel
    ? (Array.isArray(winnerModel) ? winnerModel : [winnerModel])
    : [];

  // Helper to check if a model is a winner (compares full name or short name)
  const isWinner = (model) => {
    if (winnerModels.length === 0) return false;
    const shortName = model.split('/').pop();
    return winnerModels.some(w => w === model || w === shortName || w.split('/').pop() === shortName);
  };

  // Calculate percentages and assign colors
  // Use model costs sum as the denominator to ensure bar adds to 100%
  // (handles any floating point discrepancies between totalCost and sum of model costs)
  const modelCostsSum = modelCosts.reduce((sum, mc) => sum + (mc.cost || 0), 0);
  const denominator = modelCostsSum > 0 ? modelCostsSum : totalCost;

  const modelsWithPercentage = modelCosts.map((mc, idx) => ({
    ...mc,
    percentage: denominator > 0 ? (mc.cost / denominator) * 100 : 0,
    color: MODEL_COLORS[idx % MODEL_COLORS.length],
    shortName: mc.model.split('/').pop(), // Just the model name without provider
    isWinner: isWinner(mc.model)
  }));

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  // Format duration in human-readable form (e.g., "1m 45s", "2h 30m", "45s")
  const formatDuration = (seconds) => {
    if (!seconds || seconds <= 0) return null;

    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.round(seconds % 60);

    if (hrs > 0) {
      return mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
    }
    if (mins > 0) {
      return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
    }
    return `${secs}s`;
  };

  // Check if any model has duration data
  const hasDurationData = modelCosts.some(mc => mc.duration && mc.duration > 0);

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
            className={`model-cost-segment${mc.isWinner ? ' winner' : ''}`}
            style={{
              width: `${Math.max(mc.percentage, 2)}%`, // Min 2% for visibility
              backgroundColor: mc.color,
            }}
            title={`${mc.shortName}: ${formatCost(mc.cost)} (${mc.percentage.toFixed(1)}%)${mc.isWinner ? ' ★ Winner' : ''}`}
          />
        ))}
      </div>

      {/* Legend items */}
      <div className="model-cost-legend">
        {modelsWithPercentage.map((mc, idx) => (
          <div key={idx} className={`model-cost-legend-item${mc.isWinner ? ' winner' : ''}${hasDurationData ? ' with-duration' : ''}`}>
            <span
              className="model-cost-dot"
              style={{ backgroundColor: mc.color }}
            />
            <span className="model-cost-name">{mc.shortName}</span>
            {mc.isWinner && <span className="winner-badge">★</span>}
            {hasDurationData && (
              <span className="model-cost-duration">
                {formatDuration(mc.duration) || '—'}
              </span>
            )}
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
