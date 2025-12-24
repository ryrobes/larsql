import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * Format a validator spec for display.
 * Handles: string (cascade name), or object with language key (polyglot validator)
 */
const formatValidatorName = (validator) => {
  if (!validator) return 'validator';
  if (typeof validator === 'string') return validator;

  // Polyglot validator - show language type
  if (validator.python) return 'python (inline)';
  if (validator.javascript) return 'javascript (inline)';
  if (validator.sql) return 'sql (inline)';
  if (validator.clojure) return 'clojure (inline)';
  if (validator.bash) return 'bash (inline)';
  if (validator.tool) return `${validator.tool} (inline)`;

  return 'polyglot (inline)';
};

/**
 * WardsLayer - Shows pre or post validation wards
 */
const WardsLayer = ({ type, wards = [], results = [] }) => {
  if (!wards || wards.length === 0) return null;

  const isPre = type === 'pre';
  const title = isPre ? 'Pre-Wards' : 'Post-Wards';

  // Match results to wards by name or index
  const getWardResult = (ward, idx) => {
    if (!results || results.length === 0) return null;

    const wardName = typeof ward === 'string' ? ward : formatValidatorName(ward.validator || ward.name);
    return results.find(r => r.name === wardName) || results[idx] || null;
  };

  return (
    <div className={`phase-anatomy-layer phase-anatomy-layer-wards phase-anatomy-layer-wards-${type}`}>
      <div className="phase-anatomy-layer-header">
        <div className={`phase-anatomy-layer-icon layer-icon-wards-${type}`}>
          <Icon icon={isPre ? "mdi:shield-check" : "mdi:shield-check-outline"} width="14" />
        </div>
        <span className="phase-anatomy-layer-title">{title}</span>
      </div>

      <div className="phase-anatomy-layer-content">
        <div className="layer-wards-list">
          {wards.map((ward, idx) => {
            const wardConfig = typeof ward === 'string' ? { validator: ward, mode: 'blocking' } : ward;
            const result = getWardResult(ward, idx);

            const isBlocking = (wardConfig.mode || 'blocking') === 'blocking';
            const isFailed = result?.status === 'failed';
            const causedAbort = isFailed && isBlocking;

            return (
              <div key={idx} className={`layer-ward ${causedAbort ? 'layer-ward-aborted' : ''}`}>
                {/* Status indicator */}
                <div className={`layer-ward-status ${result?.status || 'pending'}`}>
                  {result?.status === 'passed' && <Icon icon="mdi:check" width="12" />}
                  {result?.status === 'failed' && <Icon icon="mdi:close" width="12" />}
                  {!result && <Icon icon="mdi:circle-outline" width="10" />}
                </div>

                {/* Ward name */}
                <span className="layer-ward-name">
                  {formatValidatorName(wardConfig.validator || wardConfig.name)}
                </span>

                {/* Mode badge */}
                <span className={`layer-ward-mode layer-ward-mode-${wardConfig.mode || 'blocking'}`}>
                  {wardConfig.mode || 'blocking'}
                </span>

                {/* Abort indicator for blocking failures */}
                {causedAbort && (
                  <span className="layer-ward-abort-badge">
                    <Icon icon="mdi:alert-octagon" width="10" />
                    ABORTED
                  </span>
                )}

                {/* Result reason - show inline for failures, tooltip for passes */}
                {result?.reason && (
                  isFailed ? (
                    <div className="layer-ward-failure-reason">
                      <Icon icon="mdi:alert-circle" width="12" />
                      <span>{result.reason}</span>
                    </div>
                  ) : (
                    <span className="layer-ward-reason" title={result.reason}>
                      <Icon icon="mdi:information-outline" width="12" />
                    </span>
                  )
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default WardsLayer;
