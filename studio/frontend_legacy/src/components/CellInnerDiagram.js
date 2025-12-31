/**
 * CellInnerDiagram - Visualize inner cell complexity
 *
 * Shows the internal structure of a cell:
 * - Soundings: Parallel attempts → Evaluator → Winner
 * - Reforge: Sequential refinement iterations
 * - Wards: Pre/Post validation checkpoints
 *
 * Works in two modes:
 * - Spec View: Shows POTENTIAL structure from YAML config (ghost/translucent)
 * - Execution View: Shows ACTUAL execution with winners highlighted
 */

import React from 'react';
import { Icon } from '@iconify/react';
import './CellInnerDiagram.css';

/**
 * Extract inner complexity config from cell spec
 */
function extractCellComplexity(cell) {
  const soundings = cell.candidates || {};
  const reforge = soundings.reforge || {};
  const wards = cell.wards || {};

  return {
    // Soundings
    hasSoundings: soundings.factor > 1,
    soundingsFactor: soundings.factor || 1,
    soundingsMode: soundings.mode || 'evaluate', // 'evaluate' or 'aggregate'
    hasMutation: soundings.mutate !== false,
    mutationMode: soundings.mutation_mode || 'rewrite',

    // Soundings instructions
    evaluatorInstructions: soundings.evaluator_instructions,
    aggregatorInstructions: soundings.aggregator_instructions,

    // Reforge
    hasReforge: reforge.steps > 0,
    reforgeSteps: reforge.steps || 0,
    reforgeFactorPerStep: reforge.factor_per_step || 2,
    reforgeHoningPrompt: reforge.honing_prompt,

    // Wards
    hasWards: (wards.pre?.length || 0) + (wards.post?.length || 0) + (wards.turn?.length || 0) > 0,
    preWards: wards.pre || [],
    postWards: wards.post || [],
    turnWards: wards.turn || [],

    // Multi-model
    hasMultiModel: !!soundings.models,
    models: soundings.models,
  };
}

/**
 * Instruction snippet - truncated prompt preview
 */
function InstructionSnippet({ label, icon, text, colorClass }) {
  if (!text) return null;

  const truncated = text.length > 60 ? text.slice(0, 60) + '...' : text;

  return (
    <div className={`instruction-snippet ${colorClass || ''}`} title={text}>
      <div className="snippet-header">
        <Icon icon={icon} width="10" />
        <span>{label}</span>
      </div>
      <div className="snippet-text">{truncated}</div>
    </div>
  );
}

/**
 * Soundings visualization - fan-out pattern
 */
function SoundingsVisual({ factor, mode, executionData, isGhost, evaluatorInstructions, aggregatorInstructions }) {
  const attempts = Array(factor).fill(null);
  const winnerIndex = executionData?.winnerIndex;
  const isAggregate = mode === 'aggregate';
  const hasExecutionData = executionData?.attempts?.length > 0;

  return (
    <div className={`soundings-visual ${isGhost ? 'ghost' : ''}`}>
      {/* Attempts row */}
      <div className="attempts-row">
        {attempts.map((_, i) => {
          const isWinner = winnerIndex === i;
          const attemptData = executionData?.attempts?.[i];

          return (
            <div
              key={i}
              className={`attempt-box ${isWinner ? 'winner' : ''} ${attemptData?.status || ''}`}
              title={attemptData ? `Attempt ${i + 1}: ${attemptData.preview || ''}` : `Attempt ${i + 1}`}
            >
              <span className="attempt-number">{i + 1}</span>
              {isWinner && <Icon icon="mdi:check" className="winner-check" width="10" />}
            </div>
          );
        })}
      </div>

      {/* Sounding Content Previews (when executed) */}
      {hasExecutionData && (
        <div className="soundings-content">
          {attempts.map((_, i) => {
            const isWinner = winnerIndex === i;
            const attemptData = executionData?.attempts?.[i];
            if (!attemptData?.preview) return null;

            return (
              <div key={i} className={`sounding-preview ${isWinner ? 'winner' : ''}`}>
                <div className="sounding-preview-header">
                  <span className="sounding-num">#{i + 1}</span>
                  {isWinner && (
                    <span className="winner-badge">
                      <Icon icon="mdi:trophy" width="10" />
                      Winner
                    </span>
                  )}
                  {attemptData.cost > 0 && (
                    <span className="sounding-cost">${attemptData.cost.toFixed(4)}</span>
                  )}
                  {attemptData.model && (
                    <span className="sounding-model" title={attemptData.model}>
                      {attemptData.model.split('/').pop().slice(0, 12)}
                    </span>
                  )}
                </div>
                <div className="sounding-preview-text" title={attemptData.preview}>
                  {attemptData.preview.length > 120 ? attemptData.preview.slice(0, 120) + '...' : attemptData.preview}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Convergence arrows */}
      <div className="convergence-arrows">
        <svg viewBox="0 0 100 20" preserveAspectRatio="none">
          <path d="M10,0 L50,18 M90,0 L50,18" stroke="currentColor" strokeWidth="1" fill="none" />
        </svg>
      </div>

      {/* Evaluator/Aggregator */}
      <div className={`evaluator-box ${isAggregate ? 'aggregate' : ''}`}>
        <Icon icon={isAggregate ? 'mdi:merge' : 'mdi:scale-balance'} width="14" />
        <span>{isAggregate ? 'Aggregate' : 'Eval'}</span>
      </div>

      {/* Evaluator/Aggregator Instructions */}
      {isAggregate ? (
        <InstructionSnippet
          label="Aggregator"
          icon="mdi:merge"
          text={aggregatorInstructions}
          colorClass="aggregator"
        />
      ) : (
        <InstructionSnippet
          label="Evaluator"
          icon="mdi:scale-balance"
          text={evaluatorInstructions}
          colorClass="evaluator"
        />
      )}

      {/* Output indicator */}
      <div className="output-indicator">
        <Icon icon="mdi:arrow-down" width="12" />
      </div>
    </div>
  );
}

/**
 * Reforge visualization - sequential refinement
 */
function ReforgeVisual({ steps, factorPerStep, executionData, isGhost, honingPrompt }) {
  return (
    <div className={`reforge-visual ${isGhost ? 'ghost' : ''}`}>
      <div className="reforge-header">
        <Icon icon="mdi:hammer-wrench" width="12" />
        <span>Reforge</span>
      </div>

      <div className="reforge-steps">
        {Array(steps).fill(null).map((_, stepIdx) => {
          const stepData = executionData?.reforgeSteps?.[stepIdx];
          const winnerIdx = stepData?.winnerIndex;

          return (
            <div key={stepIdx} className="reforge-step">
              <div className="step-label">R{stepIdx + 1}</div>
              <div className="step-attempts">
                {Array(factorPerStep).fill(null).map((_, attemptIdx) => (
                  <div
                    key={attemptIdx}
                    className={`reforge-attempt ${winnerIdx === attemptIdx ? 'winner' : ''}`}
                  >
                    {attemptIdx + 1}
                  </div>
                ))}
              </div>
              {stepIdx < steps - 1 && (
                <div className="step-arrow">
                  <Icon icon="mdi:arrow-right" width="10" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Honing Prompt */}
      <InstructionSnippet
        label="Honing"
        icon="mdi:hammer-wrench"
        text={honingPrompt}
        colorClass="honing"
      />
    </div>
  );
}

/**
 * Wards visualization - validation checkpoints
 */
function WardsVisual({ preWards, postWards, executionData, isGhost }) {
  const hasPreWards = preWards.length > 0;
  const hasPostWards = postWards.length > 0;

  if (!hasPreWards && !hasPostWards) return null;

  const renderWard = (ward, idx, type) => {
    const wardData = executionData?.wards?.[`${type}_${idx}`];
    const status = wardData?.valid;
    const mode = ward.mode || 'blocking';
    const modeIcon = mode === 'blocking' ? 'mdi:shield' : mode === 'retry' ? 'mdi:refresh' : 'mdi:information';

    return (
      <div
        key={`${type}-${idx}`}
        className={`ward-chip ${type} ${mode} ${status === true ? 'pass' : status === false ? 'fail' : ''}`}
        title={`${mode} ward: ${ward.validator}${wardData?.reason ? ` - ${wardData.reason}` : ''}`}
      >
        <Icon icon={modeIcon} width="10" />
        <span className="ward-name">{ward.validator?.split('_')[0] || 'val'}</span>
        {status !== undefined && (
          <Icon
            icon={status ? 'mdi:check' : 'mdi:close'}
            className="ward-status"
            width="10"
          />
        )}
      </div>
    );
  };

  return (
    <div className={`wards-visual ${isGhost ? 'ghost' : ''}`}>
      {hasPreWards && (
        <div className="wards-row pre">
          <span className="wards-label">Pre</span>
          {preWards.map((ward, idx) => renderWard(ward, idx, 'pre'))}
        </div>
      )}
      {hasPostWards && (
        <div className="wards-row post">
          <span className="wards-label">Post</span>
          {postWards.map((ward, idx) => renderWard(ward, idx, 'post'))}
        </div>
      )}
    </div>
  );
}

/**
 * Main CellInnerDiagram component
 */
function CellInnerDiagram({ cell, executionData, expanded = false }) {
  const complexity = extractCellComplexity(cell);
  const isGhost = !executionData;

  // Don't render if no inner complexity
  if (!complexity.hasSoundings && !complexity.hasWards) {
    return null;
  }

  // Collapsed view - just show complexity summary
  if (!expanded) {
    return (
      <div className="cell-inner-collapsed">
        {complexity.hasSoundings && (
          <span className="complexity-chip soundings">
            <Icon icon="mdi:source-branch" width="12" />
            {complexity.soundingsFactor}×
            {complexity.hasReforge && ` → ${complexity.reforgeSteps}R`}
          </span>
        )}
        {complexity.hasWards && (
          <span className="complexity-chip wards">
            <Icon icon="mdi:shield-check" width="12" />
            {complexity.preWards.length + complexity.postWards.length}
          </span>
        )}
      </div>
    );
  }

  // Expanded view - full diagram
  return (
    <div className={`cell-inner-diagram ${isGhost ? 'ghost' : 'executed'}`}>
      {/* Pre-wards */}
      {complexity.preWards.length > 0 && (
        <WardsVisual
          preWards={complexity.preWards}
          postWards={[]}
          executionData={executionData}
          isGhost={isGhost}
        />
      )}

      {/* Soundings */}
      {complexity.hasSoundings && (
        <SoundingsVisual
          factor={complexity.soundingsFactor}
          mode={complexity.soundingsMode}
          executionData={executionData?.soundings}
          isGhost={isGhost}
          evaluatorInstructions={complexity.evaluatorInstructions}
          aggregatorInstructions={complexity.aggregatorInstructions}
        />
      )}

      {/* Reforge */}
      {complexity.hasReforge && (
        <ReforgeVisual
          steps={complexity.reforgeSteps}
          factorPerStep={complexity.reforgeFactorPerStep}
          executionData={executionData?.reforge}
          isGhost={isGhost}
          honingPrompt={complexity.reforgeHoningPrompt}
        />
      )}

      {/* Post-wards */}
      {complexity.postWards.length > 0 && (
        <WardsVisual
          preWards={[]}
          postWards={complexity.postWards}
          executionData={executionData}
          isGhost={isGhost}
        />
      )}
    </div>
  );
}

export default CellInnerDiagram;
export { extractCellComplexity };
