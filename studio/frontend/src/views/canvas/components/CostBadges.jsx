/**
 * CostBadges - Glanceable cost indicators for the query bar
 *
 * Shows at-a-glance metrics:
 * - Estimated cost badge
 * - Actual cost badge (with delta)
 * - LLM calls count
 * - Cache hit rate
 * - Operator dots (hover for details)
 */

import React from 'react';
import { Icon } from '@iconify/react';
import './CostBadges.css';

// Cost tier colors
const getCostTier = (cost) => {
  if (cost === 0) return { color: 'zero', label: 'Free' };
  if (cost <= 0.001) return { color: 'free', label: 'Minimal' };
  if (cost <= 0.01) return { color: 'cheap', label: 'Low' };
  if (cost <= 0.10) return { color: 'moderate', label: 'Moderate' };
  if (cost <= 1.00) return { color: 'expensive', label: 'Expensive' };
  return { color: 'very-expensive', label: 'Very Expensive' };
};

const formatCost = (cost) => {
  if (cost === 0) return '$0';
  if (cost < 0.001) return `$${cost.toFixed(4)}`;
  if (cost < 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
};

const formatDelta = (estimated, actual) => {
  if (!estimated || !actual || estimated === 0) return null;
  const pct = ((actual - estimated) / estimated) * 100;
  if (Math.abs(pct) < 5) return { text: '≈', color: 'neutral' };
  if (pct > 0) return { text: `+${pct.toFixed(0)}%`, color: 'over' };
  return { text: `${pct.toFixed(0)}%`, color: 'under' };
};

const CostBadges = ({
  queryExplains,
  totalEstimatedCost,
  totalActualCost,
  costPollingStatus,
  onOpenCostAnalysis,
}) => {
  // Aggregate stats from all explains
  const stats = React.useMemo(() => {
    let totalCalls = 0;
    let totalCacheHits = 0;
    let totalCacheTotal = 0;
    const operators = [];

    queryExplains.forEach((explain) => {
      // Count LLM calls
      totalCalls += explain.estimatedCalls || 0;

      // Aggregate cache stats
      (explain.operations || []).forEach(op => {
        totalCacheHits += op.cache_hits || 0;
        totalCacheTotal += op.cache_total || op.distinct_count || 0;
        operators.push({
          function: op.function,
          cost: op.estimated_cost,
          calls: op.estimated_llm_calls,
          cacheRate: op.cache_hit_rate,
        });
      });

      // Include aggregates in operators list
      (explain.aggregates || []).forEach(agg => {
        operators.push({
          function: agg.function,
          cost: agg.estimated_cost,
          calls: agg.estimated_groups,
          cacheRate: 0, // Aggregates don't cache
        });
      });
    });

    const overallCacheRate = totalCacheTotal > 0
      ? (totalCacheHits / totalCacheTotal)
      : 0;

    return { totalCalls, overallCacheRate, operators };
  }, [queryExplains]);

  const estimatedTier = getCostTier(totalEstimatedCost);
  const actualTier = getCostTier(totalActualCost);
  const delta = formatDelta(totalEstimatedCost, totalActualCost);
  const hasActual = totalActualCost > 0 && costPollingStatus !== 'polling';
  const isPolling = costPollingStatus === 'polling';

  if (queryExplains.size === 0) {
    return null;
  }

  return (
    <div className="cost-badges">
      {/* Estimated cost */}
      <div
        className={`cost-badge cost-badge-${estimatedTier.color}`}
        title={`Estimated: ${formatCost(totalEstimatedCost)} (${estimatedTier.label})`}
      >
        <Icon icon="mdi:calculator-variant" width="12" />
        <span className="cost-badge-value">{formatCost(totalEstimatedCost)}</span>
        <span className="cost-badge-label">est</span>
      </div>

      {/* Actual cost or polling indicator */}
      {isPolling && (
        <div className="cost-badge cost-badge-polling" title="Calculating actual cost...">
          <Icon icon="mdi:loading" width="12" className="spin" />
          <span className="cost-badge-value">...</span>
        </div>
      )}

      {hasActual && (
        <div
          className={`cost-badge cost-badge-${actualTier.color}`}
          title={`Actual: ${formatCost(totalActualCost)} (${actualTier.label})`}
        >
          <Icon icon="mdi:check-circle" width="12" />
          <span className="cost-badge-value">{formatCost(totalActualCost)}</span>
          {delta && (
            <span className={`cost-badge-delta delta-${delta.color}`}>
              {delta.text}
            </span>
          )}
        </div>
      )}

      {/* LLM calls count */}
      {stats.totalCalls > 0 && (
        <div
          className="cost-badge cost-badge-calls"
          title={`${stats.totalCalls} LLM call${stats.totalCalls !== 1 ? 's' : ''}`}
        >
          <Icon icon="mdi:robot" width="12" />
          <span className="cost-badge-value">{stats.totalCalls}</span>
          <span className="cost-badge-label">calls</span>
        </div>
      )}

      {/* Cache rate */}
      {stats.overallCacheRate > 0 && (
        <div
          className={`cost-badge cost-badge-cache ${stats.overallCacheRate > 0.5 ? 'high' : ''}`}
          title={`${(stats.overallCacheRate * 100).toFixed(0)}% cache hit rate`}
        >
          <Icon icon="mdi:cached" width="12" />
          <span className="cost-badge-value">{(stats.overallCacheRate * 100).toFixed(0)}%</span>
        </div>
      )}

      {/* Operator dots */}
      {stats.operators.length > 0 && stats.operators.length <= 6 && (
        <div className="cost-badge cost-badge-operators">
          {stats.operators.slice(0, 6).map((op, idx) => {
            const tier = getCostTier(op.cost);
            return (
              <span
                key={idx}
                className={`operator-dot operator-dot-${tier.color}`}
                title={`${op.function}: ${formatCost(op.cost)} (${op.calls} calls)`}
              />
            );
          })}
          {stats.operators.length > 6 && (
            <span className="operator-dot-more">+{stats.operators.length - 6}</span>
          )}
        </div>
      )}

      {/* Analyze button */}
      {onOpenCostAnalysis && (
        <button
          className="cost-badge cost-badge-analyze"
          onClick={onOpenCostAnalysis}
          title="Open cost analysis dashboard"
        >
          <Icon icon="mdi:chart-timeline-variant" width="12" />
          <span className="cost-badge-label">Analyze</span>
        </button>
      )}
    </div>
  );
};

export default CostBadges;
