import React from 'react';
import { Icon } from '@iconify/react';
import CandidateLane from './CandidateLane';
import './layers.css';

/**
 * Format a validator spec for display.
 * Handles: string (cascade name), or object with language key (polyglot validator)
 */
const formatValidatorDisplay = (validator) => {
  if (!validator) return null;
  if (typeof validator === 'string') {
    return { type: 'cascade', name: validator, preview: validator };
  }

  // Polyglot validator - extract language and code
  if (validator.python) {
    return { type: 'python', name: 'python (inline)', preview: validator.python };
  }
  if (validator.javascript) {
    return { type: 'javascript', name: 'javascript (inline)', preview: validator.javascript };
  }
  if (validator.sql) {
    return { type: 'sql', name: 'sql (inline)', preview: validator.sql };
  }
  if (validator.clojure) {
    return { type: 'clojure', name: 'clojure (inline)', preview: validator.clojure };
  }
  if (validator.bash) {
    return { type: 'bash', name: 'bash (inline)', preview: validator.bash };
  }
  if (validator.tool) {
    return { type: 'tool', name: `${validator.tool} (inline)`, preview: JSON.stringify(validator.inputs || {}) };
  }

  return { type: 'unknown', name: 'polyglot (inline)', preview: JSON.stringify(validator) };
};

/**
 * CandidatesLayer - The main execution chamber with parallel lanes
 *
 * Shows:
 * - Parallel candidate lanes (factor N)
 * - Each lane has mutation, model, turns stack
 * - Tools called per turn
 * - Loop-until validation per turn
 */
const CandidatesLayer = ({ config, execution, isLLMCell }) => {
  const factor = config.factor || 1;
  const maxTurns = config.maxTurns || 1;
  const traits = config.traits || [];
  const loopUntil = config.loopUntil;
  const mutate = config.mutate;
  const models = config.models;

  // Check if manifest/quartermaster was used for tool selection
  const isManifestMode = traits === 'manifest' || (Array.isArray(traits) && traits.includes('manifest'));
  const manifestSelection = execution?.manifestSelection;

  // Check if there's a winner (evaluation complete)
  const hasWinner = execution?.winnerIndex !== null && execution?.winnerIndex !== undefined;

  // Generate lane data - spec or execution
  const lanes = React.useMemo(() => {
    if (execution?.candidates && execution.candidates.length > 0) {
      // Execution mode - use actual data
      return execution.candidates.map((c, idx) => ({
        index: idx,
        mutation: c.mutation || (mutate ? ['rewrite', 'augment', 'approach', 'original'][idx % 4] : null),
        model: c.model,
        turns: c.turns || [],
        toolCalls: c.toolCalls || [],
        cost: c.cost || 0,
        duration: c.duration || 0,
        status: c.status || 'pending',
        isWinner: execution.winnerIndex === idx,
        isLoser: hasWinner && execution.winnerIndex !== idx,
        output: c.output || null  // Include output preview for winner
      }));
    }

    // Spec mode - generate placeholder lanes
    return Array.from({ length: factor }, (_, idx) => ({
      index: idx,
      mutation: mutate ? ['rewrite', 'augment', 'approach', 'original'][idx % 4] : null,
      model: models ? (Array.isArray(models) ? models[idx % models.length] : models) : null,
      turns: Array.from({ length: maxTurns }, (_, t) => ({
        index: t,
        toolCalls: [],
        status: 'pending'
      })),
      toolCalls: [],
      cost: null,
      duration: null,
      status: 'pending',
      isWinner: false,
      isLoser: false,
      output: null
    }));
  }, [factor, maxTurns, mutate, models, execution, hasWinner]);

  const hasCandidates = factor > 1;

  return (
    <div className="cell-anatomy-layer cell-anatomy-layer-candidates">
      <div className="cell-anatomy-layer-header">
        <div className="cell-anatomy-layer-icon layer-icon-candidates">
          <Icon icon="mdi:animation-play" width="14" />
        </div>
        <span className="cell-anatomy-layer-title">
          {hasCandidates ? `Candidates (factor: ${factor})` : 'Execution'}
        </span>

        {/* Config badges */}
        <div className="layer-candidates-badges">
          {mutate && (
            <span className="layer-candidates-badge badge-mutate">
              <Icon icon="mdi:shuffle-variant" width="10" />
              Mutate
            </span>
          )}
          {models && (
            <span className="layer-candidates-badge badge-multimodel">
              <Icon icon="mdi:robot" width="10" />
              Multi-Model
            </span>
          )}
          {loopUntil && (
            <span className="layer-candidates-badge badge-loop">
              <Icon icon="mdi:sync" width="10" />
              Loop-Until
            </span>
          )}
        </div>
      </div>

      <div className="cell-anatomy-layer-content">
        {/* Loop-Until validation condition */}
        {loopUntil && (() => {
          const validatorInfo = formatValidatorDisplay(loopUntil);
          const previewText = validatorInfo?.preview || '';
          const truncatedPreview = previewText.length > 150 ? previewText.substring(0, 150) + '...' : previewText;

          return (
            <div className="layer-candidates-loop-until">
              <Icon icon="mdi:sync" width="12" />
              <span className="layer-candidates-loop-until-label">Loop Until:</span>
              {validatorInfo?.type !== 'cascade' && (
                <span className={`layer-candidates-loop-until-type type-${validatorInfo?.type}`}>
                  {validatorInfo?.name}
                </span>
              )}
              <span className="layer-candidates-loop-until-preview">
                {truncatedPreview}
              </span>
            </div>
          );
        })()}

        {/* Traits (tools available) - show quartermaster selection if manifest mode */}
        {isManifestMode && manifestSelection && manifestSelection.selectedTools.length > 0 ? (
          <div className="layer-candidates-manifest">
            <div className="layer-candidates-manifest-header">
              <Icon icon="mdi:auto-fix" width="14" className="manifest-icon" />
              <span className="layer-candidates-manifest-label">Quartermaster Selected:</span>
              {manifestSelection.model && (
                <span className="layer-candidates-manifest-model" title={manifestSelection.model}>
                  via {manifestSelection.model.split('/').pop()}
                </span>
              )}
            </div>
            <div className="layer-candidates-traits-list">
              {manifestSelection.selectedTools.map((tool, idx) => (
                <span key={idx} className="layer-candidates-traits-item manifest-selected">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        ) : isManifestMode ? (
          <div className="layer-candidates-manifest">
            <div className="layer-candidates-manifest-header">
              <Icon icon="mdi:auto-fix" width="14" className="manifest-icon" />
              <span className="layer-candidates-manifest-label">Manifest Mode</span>
              <span className="layer-candidates-manifest-pending">(Quartermaster will select tools)</span>
            </div>
          </div>
        ) : traits.length > 0 && (
          <div className="layer-candidates-traits">
            <span className="layer-candidates-traits-label">
              <Icon icon="mdi:tools" width="12" />
              Traits:
            </span>
            <div className="layer-candidates-traits-list">
              {(Array.isArray(traits) ? traits : [traits]).map((tool, idx) => (
                <span key={idx} className="layer-candidates-traits-item">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Lanes container */}
        <div className="layer-candidates-lanes">
          {lanes.map((lane) => (
            <CandidateLane
              key={lane.index}
              lane={lane}
              maxTurns={maxTurns}
              loopUntil={loopUntil}
              hasExecution={!!execution}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export default CandidatesLayer;
