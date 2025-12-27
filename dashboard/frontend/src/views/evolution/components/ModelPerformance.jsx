import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import './ModelPerformance.css';

/**
 * ModelBar - Shows win rate and cost for a single model
 */
function ModelBar({ model }) {
  const winRate = model.win_rate;
  const avgCost = model.avg_cost;

  // Color based on win rate
  const getColor = (rate) => {
    if (rate >= 70) return '#34d399';  // High - green
    if (rate >= 50) return '#00e5ff';  // Medium-high - cyan
    if (rate >= 30) return '#f59e0b';  // Medium-low - amber
    return '#f87171';                  // Low - red
  };

  const barColor = getColor(winRate);

  return (
    <div className="model-bar">
      <div className="model-bar-header">
        <div className="model-info">
          <Icon icon="mdi:robot" width="14" />
          <span className="model-name" title={model.model_full}>
            {model.model_short}
          </span>
        </div>
        <div className="model-meta">
          <span className="model-record">{model.wins}/{model.attempts}</span>
          {avgCost > 0 && (
            <span className="model-avg-cost">${avgCost.toFixed(5)}</span>
          )}
        </div>
      </div>

      <div className="win-rate-track">
        <div
          className="win-rate-fill"
          style={{
            width: `${Math.min(winRate, 100)}%`,
            backgroundColor: barColor
          }}
        />
      </div>

      <div className="model-bar-footer">
        <span className="win-rate-label" style={{ color: barColor }}>
          {winRate.toFixed(1)}% win rate
        </span>
        {model.total_cost > 0 && (
          <span className="total-cost-label">
            Total: ${model.total_cost.toFixed(4)}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * ModelPerformance - Shows which models win most often
 *
 * Props:
 * - nodes: Evolution nodes array
 */
const ModelPerformance = ({ nodes }) => {
  // Compute model statistics from nodes
  const modelStats = useMemo(() => {
    if (!nodes || nodes.length === 0) return [];

    const modelMap = {};

    nodes.forEach(node => {
      const model = node.data.model || 'unknown';
      const modelShort = model.split('/').pop();

      if (!modelMap[model]) {
        modelMap[model] = {
          model_full: model,
          model_short: modelShort,
          wins: 0,
          attempts: 0,
          total_cost: 0,
          costs: [],
        };
      }

      modelMap[model].attempts += 1;
      if (node.data.is_winner) {
        modelMap[model].wins += 1;
      }

      const cost = node.data.cost || 0;
      modelMap[model].total_cost += cost;
      modelMap[model].costs.push(cost);
    });

    // Calculate averages and sort by win rate
    return Object.values(modelMap)
      .map(m => ({
        ...m,
        win_rate: (m.wins / m.attempts) * 100,
        avg_cost: m.costs.length > 0 ? m.costs.reduce((a, b) => a + b, 0) / m.costs.length : 0,
      }))
      .sort((a, b) => b.win_rate - a.win_rate); // Sort by win rate descending

  }, [nodes]);

  if (!nodes || nodes.length === 0) {
    return (
      <div className="model-performance-empty">
        <Icon icon="mdi:robot-outline" width="32" />
        <p>No model data available</p>
      </div>
    );
  }

  if (modelStats.length === 0) {
    return (
      <div className="model-performance-empty">
        <Icon icon="mdi:robot-outline" width="32" />
        <p>No models found in evolution data</p>
      </div>
    );
  }

  return (
    <div className="model-performance">
      {/* Header */}
      <div className="model-performance-header">
        <Icon icon="mdi:podium" width="18" />
        <h4>Model Leaderboard</h4>
        <span className="model-count">{modelStats.length} model{modelStats.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Model List */}
      <div className="model-list">
        {modelStats.map((model, idx) => (
          <div key={model.model_full} className="model-rank-item">
            <div className="rank-badge" style={{
              backgroundColor: idx === 0 ? '#f59e0b' : idx === 1 ? '#94a3b8' : idx === 2 ? '#cd7f32' : '#334155'
            }}>
              #{idx + 1}
            </div>
            <ModelBar model={model} />
          </div>
        ))}
      </div>

      {/* Interpretation */}
      <div className="model-interpretation">
        <Icon icon="mdi:information-outline" width="14" />
        <span>
          {modelStats.length === 1 ? (
            'Only one model tested. Run with multiple models to compare performance.'
          ) : (
            `Best performing: ${modelStats[0].model_short} with ${modelStats[0].win_rate.toFixed(1)}% win rate`
          )}
        </span>
      </div>
    </div>
  );
};

export default ModelPerformance;
