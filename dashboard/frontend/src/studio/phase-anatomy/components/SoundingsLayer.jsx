import React from 'react';
import { Icon } from '@iconify/react';
import SoundingLane from './SoundingLane';
import './layers.css';

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
        {/* Tackle (tools available) */}
        {tackle.length > 0 && (
          <div className="layer-soundings-tackle">
            <span className="layer-soundings-tackle-label">
              <Icon icon="mdi:tools" width="12" />
              Tackle:
            </span>
            <div className="layer-soundings-tackle-list">
              {(Array.isArray(tackle) ? tackle : [tackle]).map((tool, idx) => (
                <span key={idx} className="layer-soundings-tackle-item">
                  {tool === 'manifest' ? (
                    <>
                      <Icon icon="mdi:auto-fix" width="10" />
                      manifest
                    </>
                  ) : (
                    tool
                  )}
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
