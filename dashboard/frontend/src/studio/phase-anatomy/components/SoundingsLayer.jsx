import React from 'react';
import { Icon } from '@iconify/react';
import SoundingLane from './SoundingLane';
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
 * SoundingsLayer - The main execution chamber with parallel lanes
 *
 * Shows:
 * - Parallel sounding lanes (factor N)
 * - Each lane has mutation, model, turns stack
 * - Tools called per turn
 * - Loop-until validation per turn
 */
const SoundingsLayer = ({ config, execution, isLLMPhase }) => {
  const factor = config.factor || 1;
  const maxTurns = config.maxTurns || 1;
  const tackle = config.tackle || [];
  const loopUntil = config.loopUntil;
  const mutate = config.mutate;
  const models = config.models;

  // Check if manifest/quartermaster was used for tool selection
  const isManifestMode = tackle === 'manifest' || (Array.isArray(tackle) && tackle.includes('manifest'));
  const manifestSelection = execution?.manifestSelection;

  console.log('[SoundingsLayer] Manifest check:', {
    tackle,
    isManifestMode,
    execution: execution ? { hasSoundings: execution.hasSoundings, manifestSelection: execution.manifestSelection } : null,
    manifestSelectionDirect: manifestSelection
  });

  // Check if there's a winner (evaluation complete)
  const hasWinner = execution?.winnerIndex !== null && execution?.winnerIndex !== undefined;

  // Generate lane data - spec or execution
  const lanes = React.useMemo(() => {
    if (execution?.soundings && execution.soundings.length > 0) {
      // Execution mode - use actual data
      return execution.soundings.map((s, idx) => ({
        index: idx,
        mutation: s.mutation || (mutate ? ['rewrite', 'augment', 'approach', 'original'][idx % 4] : null),
        model: s.model,
        turns: s.turns || [],
        toolCalls: s.toolCalls || [],
        cost: s.cost || 0,
        duration: s.duration || 0,
        status: s.status || 'pending',
        isWinner: execution.winnerIndex === idx,
        isLoser: hasWinner && execution.winnerIndex !== idx,
        output: s.output || null  // Include output preview for winner
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

  const hasSoundings = factor > 1;

  return (
    <div className="phase-anatomy-layer phase-anatomy-layer-soundings">
      <div className="phase-anatomy-layer-header">
        <div className="phase-anatomy-layer-icon layer-icon-soundings">
          <Icon icon="mdi:animation-play" width="14" />
        </div>
        <span className="phase-anatomy-layer-title">
          {hasSoundings ? `Soundings (factor: ${factor})` : 'Execution'}
        </span>

        {/* Config badges */}
        <div className="layer-soundings-badges">
          {mutate && (
            <span className="layer-soundings-badge badge-mutate">
              <Icon icon="mdi:shuffle-variant" width="10" />
              Mutate
            </span>
          )}
          {models && (
            <span className="layer-soundings-badge badge-multimodel">
              <Icon icon="mdi:robot" width="10" />
              Multi-Model
            </span>
          )}
          {loopUntil && (
            <span className="layer-soundings-badge badge-loop">
              <Icon icon="mdi:sync" width="10" />
              Loop-Until
            </span>
          )}
        </div>
      </div>

      <div className="phase-anatomy-layer-content">
        {/* Loop-Until validation condition */}
        {loopUntil && (() => {
          const validatorInfo = formatValidatorDisplay(loopUntil);
          const previewText = validatorInfo?.preview || '';
          const truncatedPreview = previewText.length > 150 ? previewText.substring(0, 150) + '...' : previewText;

          return (
            <div className="layer-soundings-loop-until">
              <Icon icon="mdi:sync" width="12" />
              <span className="layer-soundings-loop-until-label">Loop Until:</span>
              {validatorInfo?.type !== 'cascade' && (
                <span className={`layer-soundings-loop-until-type type-${validatorInfo?.type}`}>
                  {validatorInfo?.name}
                </span>
              )}
              <span className="layer-soundings-loop-until-preview">
                {truncatedPreview}
              </span>
            </div>
          );
        })()}

        {/* Tackle (tools available) - show quartermaster selection if manifest mode */}
        {isManifestMode && manifestSelection && manifestSelection.selectedTools.length > 0 ? (
          <div className="layer-soundings-manifest">
            <div className="layer-soundings-manifest-header">
              <Icon icon="mdi:auto-fix" width="14" className="manifest-icon" />
              <span className="layer-soundings-manifest-label">Quartermaster Selected:</span>
              {manifestSelection.model && (
                <span className="layer-soundings-manifest-model" title={manifestSelection.model}>
                  via {manifestSelection.model.split('/').pop()}
                </span>
              )}
            </div>
            <div className="layer-soundings-tackle-list">
              {manifestSelection.selectedTools.map((tool, idx) => (
                <span key={idx} className="layer-soundings-tackle-item manifest-selected">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        ) : isManifestMode ? (
          <div className="layer-soundings-manifest">
            <div className="layer-soundings-manifest-header">
              <Icon icon="mdi:auto-fix" width="14" className="manifest-icon" />
              <span className="layer-soundings-manifest-label">Manifest Mode</span>
              <span className="layer-soundings-manifest-pending">(Quartermaster will select tools)</span>
            </div>
          </div>
        ) : tackle.length > 0 && (
          <div className="layer-soundings-tackle">
            <span className="layer-soundings-tackle-label">
              <Icon icon="mdi:tools" width="12" />
              Tackle:
            </span>
            <div className="layer-soundings-tackle-list">
              {(Array.isArray(tackle) ? tackle : [tackle]).map((tool, idx) => (
                <span key={idx} className="layer-soundings-tackle-item">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Lanes container */}
        <div className="layer-soundings-lanes">
          {lanes.map((lane) => (
            <SoundingLane
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

export default SoundingsLayer;
