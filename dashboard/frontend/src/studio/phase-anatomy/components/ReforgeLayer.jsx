import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * ReforgeLayer - Shows iterative refinement loop
 *
 * The reforge process:
 * - Winner enters from soundings
 * - For each step: run factor_per_step attempts with honing_prompt
 * - Evaluate and pick winner
 * - Optional threshold check for early stopping
 */
const ReforgeLayer = ({ config, execution }) => {
  const steps = config?.steps || 3;
  const factor_per_step = config?.factor_per_step || 2;
  const honing_prompt = config?.honing_prompt;
  const threshold = config?.threshold;
  const mutate = config?.mutate || false;

  // Generate step data - spec or execution
  const stepData = React.useMemo(() => {
    if (execution?.steps && execution.steps.length > 0) {
      return execution.steps;
    }

    // Spec mode - generate placeholder steps
    return Array.from({ length: steps }, (_, idx) => ({
      index: idx,
      attempts: Array.from({ length: factor_per_step }, (_, a) => ({
        index: a,
        turns: [{ index: 0 }, { index: 1 }],
        status: 'pending',
        cost: null,
        duration: null
      })),
      winner: null,
      thresholdPassed: null,
      evaluatorReason: null
    }));
  }, [steps, factor_per_step, execution]);

  // Find early stop step
  const earlyStopStep = stepData.findIndex(s => s.thresholdPassed === true);

  // Calculate totals for execution mode
  const hasExecution = execution?.steps && execution.steps.length > 0;
  const totalAttempts = stepData.reduce((sum, step) => sum + (step.attempts?.length || 0), 0);
  const completedSteps = stepData.filter(s => s.winner !== null).length;

  // Early return after hooks
  if (!config) return null;

  return (
    <div className="phase-anatomy-layer phase-anatomy-layer-reforge">
      <div className="phase-anatomy-layer-header">
        <div className="phase-anatomy-layer-icon layer-icon-reforge">
          <Icon icon="mdi:anvil" width="14" />
        </div>
        <span className="phase-anatomy-layer-title">
          Reforge ({completedSteps}/{steps} steps)
        </span>

        {/* Config badges */}
        <div className="layer-reforge-badges">
          <span className="layer-reforge-badge">
            <Icon icon="mdi:content-copy" width="10" />
            {factor_per_step}/step
          </span>
          {threshold && (
            <span className="layer-reforge-badge badge-threshold">
              <Icon icon="mdi:target" width="10" />
              Threshold
            </span>
          )}
          {mutate && (
            <span className="layer-reforge-badge badge-mutate">
              <Icon icon="mdi:shuffle-variant" width="10" />
              Mutate
            </span>
          )}
        </div>
      </div>

      <div className="phase-anatomy-layer-content">
        {/* Honing prompt */}
        {honing_prompt && (
          <div className="layer-reforge-honing">
            <Icon icon="mdi:text-box-edit" width="12" />
            <span className="layer-reforge-honing-label">Honing:</span>
            <span className="layer-reforge-honing-preview">
              {honing_prompt.length > 120 ? honing_prompt.substring(0, 120) + '...' : honing_prompt}
            </span>
          </div>
        )}

        {/* Steps container */}
        <div className="layer-reforge-steps">
          {stepData.map((step, idx) => {
            const isComplete = step.winner !== null;
            const isFinal = earlyStopStep === idx || (idx === stepData.length - 1 && isComplete);

            return (
              <div
                key={idx}
                className={`layer-reforge-step ${step.thresholdPassed ? 'step-stopped' : ''} ${isFinal ? 'step-final' : ''} ${isComplete ? 'step-complete' : ''}`}
              >
                <div className="layer-reforge-step-header">
                  <span className="layer-reforge-step-label">
                    {isFinal && <Icon icon="mdi:star" width="10" className="step-final-icon" />}
                    Step {idx + 1}
                  </span>
                  {step.thresholdPassed && (
                    <span className="layer-reforge-step-stopped">
                      <Icon icon="mdi:check-circle" width="12" />
                      Threshold Met
                    </span>
                  )}
                </div>

                {/* Mini lanes for attempts */}
                <div className="layer-reforge-attempts">
                  {step.attempts.map((attempt, aIdx) => {
                    const isWinner = step.winner === aIdx;
                    const isLoser = step.winner !== null && step.winner !== aIdx;

                    return (
                      <div
                        key={aIdx}
                        className={`layer-reforge-attempt ${isWinner ? 'attempt-winner' : ''} ${isLoser ? 'attempt-loser' : ''}`}
                      >
                        <span className="layer-reforge-attempt-label">
                          {isWinner && <Icon icon="mdi:crown" width="8" className="attempt-crown" />}
                          R{idx}.{aIdx}
                        </span>
                        <div className="layer-reforge-attempt-turns">
                          {attempt.turns.map((turn, tIdx) => (
                            <span
                              key={tIdx}
                              className={`layer-reforge-attempt-turn ${turn.status === 'complete' ? 'turn-complete' : ''}`}
                            />
                          ))}
                        </div>
                        {/* Cost/duration for completed attempts */}
                        {attempt.cost > 0 && (
                          <span className="layer-reforge-attempt-cost">
                            ${attempt.cost < 0.01 ? '<.01' : attempt.cost.toFixed(3)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Eval section */}
                <div className={`layer-reforge-step-eval ${isComplete ? 'eval-complete' : ''}`}>
                  <div className="layer-reforge-eval-header">
                    <Icon icon={isComplete ? "mdi:scale-balance" : "mdi:chevron-down"} width="14" />
                    <span className="layer-reforge-step-eval-label">
                      {isComplete ? 'EVALUATED' : 'EVAL'}
                    </span>
                  </div>

                  {step.winner !== null && (
                    <div className="layer-reforge-eval-result">
                      <span className="layer-reforge-step-winner">
                        <Icon icon="mdi:crown" width="10" />
                        R{idx}.{step.winner} wins
                      </span>

                      {/* Evaluator reasoning if available */}
                      {step.evaluatorReason && (
                        <span className="layer-reforge-eval-reason" title={step.evaluatorReason}>
                          {step.evaluatorReason.length > 60
                            ? step.evaluatorReason.substring(0, 60) + '...'
                            : step.evaluatorReason}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Arrow to next step */}
                {idx < stepData.length - 1 && !step.thresholdPassed && (
                  <div className="layer-reforge-step-arrow">
                    <Icon icon="mdi:arrow-right" width="16" />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Final output indicator */}
        <div className={`layer-reforge-final ${hasExecution && completedSteps > 0 ? 'final-complete' : ''}`}>
          <Icon icon="mdi:shimmer" width="14" />
          <span>
            {earlyStopStep >= 0
              ? `Early stop at Step ${earlyStopStep + 1} (threshold met)`
              : hasExecution && completedSteps > 0
                ? `Final Output from Step ${completedSteps}`
                : `Will output from Step ${steps}`
            }
          </span>
          {hasExecution && (
            <span className="layer-reforge-final-stats">
              ({totalAttempts} total attempts)
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReforgeLayer;
