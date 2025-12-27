import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import './ModelFilterBanner.css';

/**
 * ModelFilterBanner - Shows which models were filtered due to insufficient context
 *
 * Displays when multi-model soundings filtered out models that couldn't handle
 * the estimated token count for the request.
 */
function ModelFilterBanner({ filterData }) {
  const [expanded, setExpanded] = useState(false);

  if (!filterData || !filterData.filtered_models || filterData.filtered_models.length === 0) {
    return null;
  }

  const {
    filtered_models,
    viable_models,
    filter_details,
    estimated_tokens,
    required_tokens,
    buffer_factor
  } = filterData;

  const filteredCount = filtered_models.length;
  const viableCount = viable_models.length;

  return (
    <div className="model-filter-banner">
      <div className="filter-banner-header" onClick={() => setExpanded(!expanded)}>
        <div className="filter-banner-left">
          <Icon icon="mdi:filter-variant" width="18" className="filter-icon" />
          <span className="filter-summary">
            <strong>{filteredCount} model{filteredCount !== 1 ? 's' : ''} filtered</strong>
            {' '}due to insufficient context
          </span>
          <span className="filter-tokens">
            (need {required_tokens.toLocaleString()} tokens, estimated {estimated_tokens.toLocaleString()})
          </span>
        </div>
        <Icon
          icon={expanded ? "mdi:chevron-up" : "mdi:chevron-down"}
          width="20"
          className="expand-icon"
        />
      </div>

      {expanded && (
        <div className="filter-banner-details">
          <div className="filter-section">
            <div className="filter-section-title">
              <Icon icon="mdi:close-circle" width="16" />
              Filtered Models ({filteredCount})
            </div>
            <div className="filter-models-grid">
              {filtered_models.map(model => {
                const details = filter_details[model];
                return (
                  <div key={model} className="filter-model-card filtered">
                    <div className="model-name">{model}</div>
                    {details && (
                      <div className="model-limit">
                        Context: {details.model_limit.toLocaleString()} tokens
                        <span className="shortfall">
                          (-{details.shortfall.toLocaleString()})
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="filter-section">
            <div className="filter-section-title">
              <Icon icon="mdi:check-circle" width="16" />
              Viable Models ({viableCount})
            </div>
            <div className="filter-models-grid">
              {viable_models.map(model => (
                <div key={model} className="filter-model-card viable">
                  <div className="model-name">{model}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="filter-info">
            <Icon icon="mdi:information" width="14" />
            Buffer factor: {buffer_factor.toFixed(2)}x (15% safety margin)
          </div>
        </div>
      )}
    </div>
  );
}

export default ModelFilterBanner;
