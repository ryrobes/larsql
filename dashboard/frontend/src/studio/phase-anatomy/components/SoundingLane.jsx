import React from 'react';
import { Icon } from '@iconify/react';
import ModelIcon, { getProviderColor, getProvider } from '../../../components/ModelIcon';
import './layers.css';

/**
 * SoundingLane - A single parallel execution track
 *
 * Shows:
 * - Mutation type (rewrite/augment/approach/original)
 * - Model used
 * - Stack of turns with tool calls
 * - Loop-until validation markers
 * - Cost/duration footer
 */
const SoundingLane = ({ lane, maxTurns, loopUntil, hasExecution }) => {
  const { index, mutation, model, turns, toolCalls, cost, duration, status, isWinner } = lane;

  // Format duration
  const formatDuration = (ms) => {
    if (!ms || ms === 0) return null;
    if (ms < 1000) return `${Math.round(ms)}ms`;
    const seconds = ms / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m${remainingSeconds}s`;
  };

  // Generate turn slots (fill unused with placeholders)
  const turnSlots = React.useMemo(() => {
    const slots = [];
    for (let i = 0; i < maxTurns; i++) {
      const turn = turns[i] || null;
      slots.push({
        index: i,
        data: turn,
        isUsed: !!turn && turn.status !== 'pending',
        isEarlyExit: turn?.status === 'complete' && turn?.validationPassed,
        toolCalls: turn?.toolCalls || [],
        duration: turn?.duration || null
      });
    }
    return slots;
  }, [turns, maxTurns]);

  // Count total tool calls
  const totalToolCalls = toolCalls.length || turns.reduce((sum, t) => sum + (t.toolCalls?.length || 0), 0);

  // Short model name
  const shortModel = model ? model.split('/').pop() : null;

  // Format duration for display
  const durationDisplay = formatDuration(duration);

  return (
    <div className={`sounding-lane ${isWinner ? 'sounding-lane-winner' : ''} sounding-lane-${status}`}>
      {/* Lane header */}
      <div className="sounding-lane-header">
        <span className="sounding-lane-index">
          {isWinner && <Icon icon="mdi:crown" width="12" className="sounding-lane-crown" />}
          S{index}
        </span>
      </div>

      {/* Mutation row */}
      {mutation && (
        <div className="sounding-lane-row sounding-lane-mutation">
          <span className="sounding-lane-row-label">
            <Icon icon="mdi:shuffle-variant" width="10" />
          </span>
          <span className={`sounding-lane-mutation-badge mutation-${mutation}`}>
            {mutation}
          </span>
        </div>
      )}

      {/* Model row */}
      {model && (
        <div className="sounding-lane-row sounding-lane-model">
          <span className="sounding-lane-row-label">
            <ModelIcon modelId={model} size={10} />
          </span>
          <span
            className="sounding-lane-model-name"
            title={model}
            style={{ color: getProviderColor(getProvider(model)) }}
          >
            {shortModel}
          </span>
        </div>
      )}

      {/* Turns stack divider */}
      <div className="sounding-lane-divider" />

      {/* Turns stack */}
      <div className="sounding-lane-turns">
        {turnSlots.map((slot) => (
          <div
            key={slot.index}
            className={`sounding-lane-turn ${slot.isUsed ? 'used' : 'unused'} ${slot.isEarlyExit ? 'early-exit' : ''}`}
          >
            <span className="sounding-lane-turn-index">T{slot.index}</span>

            {/* Tool call badges */}
            {slot.toolCalls.length > 0 && (
              <div className="sounding-lane-turn-tools">
                {slot.toolCalls.slice(0, 3).map((tc, idx) => (
                  <span key={idx} className="sounding-lane-tool-badge" title={tc.name || tc}>
                    <Icon icon="mdi:hammer-wrench" width="8" />
                  </span>
                ))}
                {slot.toolCalls.length > 3 && (
                  <span className="sounding-lane-tool-more">+{slot.toolCalls.length - 3}</span>
                )}
              </div>
            )}

            {/* Turn duration */}
            {slot.duration && (
              <span className="sounding-lane-turn-duration" title={`Turn ${slot.index} duration`}>
                {formatDuration(slot.duration)}
              </span>
            )}

            {/* Validation marker */}
            {loopUntil && slot.isUsed && (
              <span className={`sounding-lane-turn-validation ${slot.isEarlyExit ? 'passed' : 'pending'}`}>
                {slot.isEarlyExit ? (
                  <Icon icon="mdi:lightning-bolt" width="10" title="Early exit - validation passed" />
                ) : (
                  <Icon icon="mdi:sync" width="10" title="Loop-until check" />
                )}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Unused turns indicator */}
      {turns.length < maxTurns && maxTurns > 1 && (
        <div className="sounding-lane-unused">
          <span className="sounding-lane-unused-label">
            (max {maxTurns})
          </span>
        </div>
      )}

      {/* Lane footer divider */}
      <div className="sounding-lane-divider" />

      {/* Footer stats */}
      <div className="sounding-lane-footer">
        {hasExecution ? (
          <>
            {cost > 0 && (
              <span className="sounding-lane-stat sounding-lane-cost">
                ${cost < 0.01 ? '<.01' : cost.toFixed(3)}
              </span>
            )}
            {durationDisplay && (
              <span className="sounding-lane-stat sounding-lane-duration">
                <Icon icon="mdi:clock-outline" width="10" />
                {durationDisplay}
              </span>
            )}
            <span className="sounding-lane-stat sounding-lane-turns-count">
              {turns.filter(t => t.status !== 'pending').length} turns
            </span>
            <span className="sounding-lane-stat sounding-lane-tools-count">
              {totalToolCalls} tools
            </span>
          </>
        ) : (
          <span className="sounding-lane-stat sounding-lane-tools-count">
            {maxTurns} max turns
          </span>
        )}
      </div>
    </div>
  );
};

export default SoundingLane;
