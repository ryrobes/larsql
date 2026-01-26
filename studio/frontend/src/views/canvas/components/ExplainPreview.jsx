/**
 * ExplainPreview - Detailed explain plan visualization for skeleton panels
 *
 * Shows estimated cost, LLM calls, operation breakdown with row counts,
 * cache rates, and model info before query execution.
 */

import React from 'react';
import { Icon } from '@iconify/react';
import './ExplainPreview.css';

// Cost tier helpers
function getCostTier(cost) {
  if (cost === 0) return { color: 'zero', icon: 'mdi:circle-outline', label: 'No LLM' };
  if (cost <= 0.001) return { color: 'free', icon: 'mdi:check-circle', label: 'Free' };
  if (cost <= 0.01) return { color: 'green', icon: 'mdi:cash-fast', label: 'Low' };
  if (cost <= 0.10) return { color: 'yellow', icon: 'mdi:currency-usd', label: 'Moderate' };
  if (cost <= 1.00) return { color: 'orange', icon: 'mdi:alert', label: 'High' };
  return { color: 'red', icon: 'mdi:fire', label: 'Very High' };
}

function formatCost(cost) {
  if (cost === 0) return '$0';
  if (cost < 0.001) return '<$0.001';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

function formatCacheRate(rate) {
  if (rate === undefined || rate === null) return null;
  const pct = Math.round(rate * 100);
  return `${pct}%`;
}


const ExplainPreview = ({ explain }) => {
  if (!explain) {
    // No explain data - show minimal pending state
    return (
      <div className="explain-preview explain-preview-empty">
        <Icon icon="mdi:timer-sand" width="20" className="explain-preview-wait-icon" />
        <span className="explain-preview-wait-text">Awaiting explain...</span>
      </div>
    );
  }

  const {
    estimatedCost = 0,
    estimatedCalls = 0,
    operations = [],
    aggregates = [],
    pipelineStages = [],
    queryType,
    error,
    hints = [],
  } = explain;

  // Handle error state
  if (queryType === 'error' || error) {
    return (
      <div className="explain-preview explain-preview-error">
        <Icon icon="mdi:alert-circle-outline" width="20" />
        <div className="explain-preview-error-content">
          <span className="explain-preview-error-title">Explain Failed</span>
          <span className="explain-preview-error-text">
            {error?.substring(0, 80) || 'Could not analyze query'}
          </span>
        </div>
      </div>
    );
  }

  // Check if this is a pure SQL query (no LLM operations)
  const isPureSql = estimatedCalls === 0 && operations.length === 0 && aggregates.length === 0 && pipelineStages.length === 0;

  if (isPureSql) {
    return (
      <div className="explain-preview explain-preview-sql">
        <div className="explain-preview-sql-icon">
          <Icon icon="mdi:database-check" width="24" />
        </div>
        <div className="explain-preview-sql-info">
          <span className="explain-preview-sql-label">Pure SQL</span>
          <span className="explain-preview-sql-hint">No LLM operations - runs instantly</span>
        </div>
      </div>
    );
  }

  const tier = getCostTier(estimatedCost);
  const allOperations = [...operations, ...aggregates];

  return (
    <div className="explain-preview explain-preview-detailed">
      {/* Summary row: cost, calls, and hints */}
      <div className="explain-preview-summary">
        <div className={`explain-preview-cost explain-preview-cost-${tier.color}`}>
          <Icon icon={tier.icon} width="16" />
          <span className="explain-preview-cost-value">{formatCost(estimatedCost)}</span>
        </div>
        <div className="explain-preview-calls">
          <Icon icon="mdi:robot-outline" width="12" />
          <span>{estimatedCalls} calls</span>
        </div>
        {hints.length > 0 && hints.slice(0, 2).map((hint, idx) => (
          <div key={idx} className="explain-preview-hint">
            <Icon icon="mdi:lightbulb-outline" width="11" />
            <span>{hint}</span>
          </div>
        ))}
      </div>

      {/* Operations breakdown */}
      {allOperations.length > 0 && (
        <div className="explain-preview-operations">
          <div className="explain-preview-op-list">
            {allOperations.map((op, idx) => {
              const opTier = getCostTier(op.estimated_cost);
              const cacheRate = formatCacheRate(op.cache_hit_rate);
              const calls = op.estimated_llm_calls || op.estimated_groups || 0;
              return (
                <div key={idx} className={`explain-preview-op-row explain-preview-op-${opTier.color}`}>
                  <span className="explain-preview-op-func">
                    {op.function?.replace('semantic_', '')}
                  </span>
                  {op.model && (
                    <span className="explain-preview-op-model">{op.model}</span>
                  )}
                  <div className="explain-preview-op-stats">
                    <span className="explain-preview-op-calls" title="LLM calls">
                      <Icon icon="mdi:message-processing-outline" width="10" />
                      {calls}
                    </span>
                    {cacheRate && (
                      <span
                        className={`explain-preview-op-cache ${op.cache_hit_rate > 0.5 ? 'high' : ''}`}
                        title="Cache hit rate"
                      >
                        <Icon icon="mdi:cached" width="10" />
                        {cacheRate}
                      </span>
                    )}
                    <span className={`explain-preview-op-cost cost-${opTier.color}`}>
                      {formatCost(op.estimated_cost)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pipeline stages */}
      {pipelineStages.length > 0 && (
        <div className="explain-preview-pipeline">
          <div className="explain-preview-stage-list">
            {pipelineStages.map((stage, idx) => {
              const stageTier = getCostTier(stage.estimated_cost);

              return (
                <div key={idx} className={`explain-preview-stage-row explain-preview-stage-${stageTier.color}`}>
                  <span className="explain-preview-stage-name">{stage.stage_name}</span>
                  {stage.description && (
                    <span className="explain-preview-stage-desc">{stage.description}</span>
                  )}
                  {stage.model && (
                    <span className="explain-preview-stage-model">{stage.model}</span>
                  )}
                  <span className={`explain-preview-stage-cost cost-${stageTier.color}`}>
                    {formatCost(stage.estimated_cost)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default ExplainPreview;
