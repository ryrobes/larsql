import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * OutputLayer - Shows cell output configuration and result
 */
const OutputLayer = ({ outputSchema, outputExtraction, callouts, handoffs, result }) => {
  const hasSchema = outputSchema && Object.keys(outputSchema).length > 0;
  const hasExtraction = outputExtraction && outputExtraction.length > 0;
  const hasCallouts = callouts && callouts.length > 0;
  const hasHandoffs = handoffs && handoffs.length > 0;
  const hasResult = result !== null && result !== undefined;

  return (
    <div className="cell-anatomy-layer cell-anatomy-layer-output">
      <div className="cell-anatomy-layer-header">
        <div className="cell-anatomy-layer-icon layer-icon-output">
          <Icon icon="mdi:export" width="14" />
        </div>
        <span className="cell-anatomy-layer-title">Output</span>
      </div>

      <div className="cell-anatomy-layer-content">
        {/* Output schema */}
        {hasSchema && (
          <div className="layer-output-section">
            <div className="layer-output-section-header">
              <Icon icon="mdi:code-json" width="12" />
              <span>Output Schema</span>
            </div>
            <div className="layer-output-schema">
              <span className="layer-output-schema-type">
                {outputSchema.type || 'object'}
              </span>
              {outputSchema.required && (
                <span className="layer-output-schema-required">
                  Required: {outputSchema.required.join(', ')}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Output extraction */}
        {hasExtraction && (
          <div className="layer-output-section">
            <div className="layer-output-section-header">
              <Icon icon="mdi:regex" width="12" />
              <span>Extraction</span>
            </div>
            <div className="layer-output-extraction">
              {(Array.isArray(outputExtraction) ? outputExtraction : [outputExtraction]).map((ext, idx) => (
                <div key={idx} className="layer-output-extraction-rule">
                  <code className="layer-output-extraction-pattern">{ext.pattern || ext}</code>
                  {ext.target && (
                    <span className="layer-output-extraction-target">
                      <Icon icon="mdi:arrow-right" width="10" />
                      state.{ext.target}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Callouts */}
        {hasCallouts && (
          <div className="layer-output-section">
            <div className="layer-output-section-header">
              <Icon icon="mdi:tag" width="12" />
              <span>Callouts</span>
            </div>
            <div className="layer-output-callouts">
              {(Array.isArray(callouts) ? callouts : [callouts]).map((callout, idx) => (
                <span key={idx} className="layer-output-callout-tag">
                  {callout}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Handoffs */}
        {hasHandoffs && (
          <div className="layer-output-section">
            <div className="layer-output-section-header">
              <Icon icon="mdi:arrow-decision" width="12" />
              <span>Handoffs</span>
            </div>
            <div className="layer-output-handoffs">
              {handoffs.map((handoff, idx) => (
                <span key={idx} className="layer-output-handoff">
                  <Icon icon="mdi:arrow-right-bold" width="10" />
                  {handoff}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Result preview */}
        {hasResult && (
          <div className="layer-output-section layer-output-result">
            <div className="layer-output-section-header">
              <Icon icon="mdi:check-circle" width="12" />
              <span>Result</span>
            </div>
            <div className="layer-output-result-preview">
              {typeof result === 'string' ? (
                <span>{result.length > 500 ? result.substring(0, 500) + '...' : result}</span>
              ) : result?.rows ? (
                <span>{result.rows.length} rows returned</span>
              ) : (
                <span>{JSON.stringify(result, null, 2).substring(0, 500)}{JSON.stringify(result).length > 500 ? '...' : ''}</span>
              )}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!hasSchema && !hasExtraction && !hasCallouts && !hasHandoffs && !hasResult && (
          <div className="layer-empty">
            <Icon icon="mdi:arrow-collapse-right" width="14" />
            <span>Output passed to lineage</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default OutputLayer;
