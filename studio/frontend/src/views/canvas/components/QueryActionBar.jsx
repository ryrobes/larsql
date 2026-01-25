import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import ModelIcon, { getProviderColor, getProvider } from '../../../components/ModelIcon';
import './QueryActionBar.css';

/**
 * QueryActionBar - Rich action bar above SQL query blocks
 *
 * Shows:
 * - Model icons (using shared ModelIcon component)
 * - Colored cost badge
 * - LLM call count
 * - Run/Solo action buttons
 * - Collapsible
 */

function getCostTier(cost) {
  if (cost === 0) return 'zero';
  if (cost < 0.001) return 'free';
  if (cost < 0.01) return 'low';
  if (cost < 0.1) return 'medium';
  if (cost < 1.0) return 'high';
  return 'very-high';
}

const QueryActionBar = ({ query, explain, onRunSolo }) => {
  const { estimatedCost, estimatedCalls, operations, aggregates, pipelineStages, queryType, error } = explain || {};

  const isError = queryType === 'error';
  const tier = getCostTier(estimatedCost || 0);

  // Collect unique models
  const models = new Set();
  if (operations) operations.forEach(op => op.model && models.add(op.model));
  if (aggregates) aggregates.forEach(agg => agg.model && models.add(agg.model));
  if (pipelineStages) pipelineStages.forEach(s => s.model && models.add(s.model));

  const modelList = Array.from(models);
  const operationCount = (operations?.length || 0) + (aggregates?.length || 0) + (pipelineStages?.length || 0);

  return (
    <div className="query-action-bar">
      <div className="query-action-bar-content">
        {/* Left side: Metadata */}
        <div className="query-action-bar-meta">
          {/* Cost badge */}
          <div className={`cost-badge cost-${tier}`} title={`Estimated cost: $${(estimatedCost || 0).toFixed(6)}`}>
            ${(estimatedCost || 0) < 0.01 ? (estimatedCost || 0).toFixed(4) : (estimatedCost || 0).toFixed(3)}
          </div>

          {/* Operation count */}
          {operationCount > 0 && (
            <span className="operation-count" title={`${operationCount} semantic operations`}>
              <Icon icon="mdi:function-variant" width="9" />
              {operationCount}
            </span>
          )}

          {/* LLM calls */}
          {estimatedCalls > 0 && (
            <span className="call-count" title="LLM calls">
              <Icon icon="mdi:api" width="9" />
              {estimatedCalls}
            </span>
          )}

          {/* Model icons - after stats */}
          {modelList.length > 0 && (
            <div className="model-icons" title={modelList.join(', ')}>
              {modelList.slice(0, 4).map((modelId, i) => (
                <div key={i} className="model-icon-badge" title={modelId}>
                  <ModelIcon modelId={modelId} size={12} />
                </div>
              ))}
              {modelList.length > 4 && (
                <span className="model-more">+{modelList.length - 4}</span>
              )}
            </div>
          )}

          {/* Error indicator */}
          {isError && (
            <span className="error-indicator" title={error}>
              <Icon icon="mdi:alert-circle" width="11" />
              {error?.substring(0, 30)}...
            </span>
          )}
        </div>

        {/* Right side: Play button */}
        <button className="action-btn-play" onClick={onRunSolo} title="Run query solo (Ctrl+Shift+Enter)">
          <Icon icon="mdi:play" width="14" />
        </button>
      </div>
    </div>
  );
};

export default QueryActionBar;
