import React from 'react';
import { Icon } from '@iconify/react';
import ModelIcon, { getProviderColor, getProvider } from '../../../components/ModelIcon';
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
 * ConvergenceSection - Shows where candidates converge
 *
 * Contains:
 * - Pre-validator (filters broken outputs)
 * - Evaluator config (left) + Evaluator result (right) in 50/50 split
 */
const ConvergenceSection = ({ config, winnerIndex, mode = 'evaluate', evaluatorResult }) => {
  const { preValidator, evaluator } = config;
  const isAggregate = mode === 'aggregate';
  const hasResult = evaluatorResult && evaluatorResult.content;

  return (
    <div className="cell-anatomy-convergence">
      {/* Funnel visualization */}
      <div className="convergence-funnel">
        <div className="convergence-funnel-line" />
      </div>

      {/* Pre-validator */}
      {preValidator && (
        <div className="convergence-section convergence-prevalidator">
          <div className="convergence-section-icon">
            <Icon icon="mdi:filter-check" width="14" />
          </div>
          <div className="convergence-section-content">
            <span className="convergence-section-label">Pre-Validator</span>
            <span className="convergence-section-name">{formatValidatorName(preValidator)}</span>
          </div>
        </div>
      )}

      {/* Evaluator - 50/50 split when there's a result */}
      <div className={`convergence-evaluator-container ${hasResult ? 'has-result' : ''}`}>
        {/* Left side: Evaluator Config */}
        <div className="convergence-section convergence-evaluator">
          <div className="convergence-section-icon convergence-icon-evaluator">
            <Icon icon={isAggregate ? "mdi:merge" : "mdi:scale-balance"} width="16" />
          </div>
          <div className="convergence-section-content">
            <span className="convergence-section-label">
              {isAggregate ? 'Aggregator' : 'Evaluator'}
            </span>

            {/* Mode badge */}
            <span className={`convergence-mode-badge ${isAggregate ? 'mode-aggregate' : 'mode-evaluate'}`}>
              {isAggregate ? (
                <>
                  <Icon icon="mdi:set-merge" width="10" />
                  Combine All
                </>
              ) : (
                <>
                  <Icon icon="mdi:trophy" width="10" />
                  Pick Winner
                </>
              )}
            </span>

            {/* Instructions preview */}
            {evaluator && (
              <span className="convergence-instructions" title={evaluator}>
                {evaluator.length > 300 ? evaluator.substring(0, 300) + '...' : evaluator}
              </span>
            )}
          </div>
        </div>

        {/* Right side: Evaluator Result (only if we have one) */}
        {hasResult && (
          <div className="convergence-section convergence-result">
            <div className="convergence-section-icon convergence-icon-result">
              <Icon icon="mdi:message-text" width="16" />
            </div>
            <div className="convergence-section-content">
              <div className="convergence-result-header">
                <span className="convergence-section-label">Evaluator Decision</span>
                {/* Winner badge */}
                {winnerIndex !== null && winnerIndex !== undefined && !isAggregate && (
                  <div className="convergence-winner">
                    <Icon icon="mdi:crown" width="14" />
                    <span>Winner: S{winnerIndex}</span>
                  </div>
                )}
              </div>

              {/* Model used */}
              {evaluatorResult.model && (
                <span
                  className="convergence-result-model"
                  style={{ color: getProviderColor(getProvider(evaluatorResult.model)) }}
                >
                  <ModelIcon modelId={evaluatorResult.model} size={10} />
                  {evaluatorResult.model.split('/').pop()}
                </span>
              )}

              {/* Evaluator reasoning */}
              <div className="convergence-result-content">
                {evaluatorResult.content}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Winner result - only show if no result panel */}
      {!hasResult && winnerIndex !== null && winnerIndex !== undefined && !isAggregate && (
        <div className="convergence-winner-standalone">
          <Icon icon="mdi:crown" width="14" />
          <span>Winner: S{winnerIndex}</span>
        </div>
      )}
    </div>
  );
};

export default ConvergenceSection;
