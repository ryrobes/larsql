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
  const { index, mutation, model, turns, toolCalls, cost, duration, status, isWinner, isLoser } = lane;

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
      const validationResult = turn?.validationResult || null;
      const validationPassed = validationResult?.valid === true;
      const validationFailed = validationResult?.valid === false;
      slots.push({
        index: i,
        data: turn,
        isUsed: !!turn && turn.status !== 'pending',
        isEarlyExit: turn?.status === 'complete' && validationPassed,
        validationFailed,
        validationReason: validationResult?.reason || null,
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
    <div className={`take-lane ${isWinner ? 'take-lane-winner' : ''} ${isLoser ? 'take-lane-loser' : ''} take-lane-${status}`}>
      {/* Lane header */}
      <div className="take-lane-header">
        <span className="take-lane-index">
          {isWinner && <Icon icon="mdi:crown" width="12" className="take-lane-crown" />}
          {isLoser && <Icon icon="mdi:close-circle" width="10" className="take-lane-loser-icon" />}
          S{index}
        </span>
      </div>

      {/* Mutation row */}
      {mutation && (
        <div className="take-lane-row take-lane-mutation">
          <span className="take-lane-row-label">
            <Icon icon="mdi:shuffle-variant" width="10" />
          </span>
          <span className={`take-lane-mutation-badge mutation-${mutation}`}>
            {mutation}
          </span>
        </div>
      )}

      {/* Model row */}
      {model && (
        <div className="take-lane-row take-lane-model">
          <span className="take-lane-row-label">
            <ModelIcon modelId={model} size={10} />
          </span>
          <span
            className="take-lane-model-name"
            title={model}
            style={{ color: getProviderColor(getProvider(model)) }}
          >
            {shortModel}
          </span>
        </div>
      )}

      {/* Turns stack divider */}
      <div className="take-lane-divider" />

      {/* Turns stack */}
      <div className="take-lane-turns">
        {turnSlots.map((slot) => (
          <div
            key={slot.index}
            className={`take-lane-turn ${slot.isUsed ? 'used' : 'unused'} ${slot.isEarlyExit ? 'early-exit' : ''} ${slot.validationFailed ? 'validation-failed' : ''}`}
          >
            <span className="take-lane-turn-index">T{slot.index}</span>

            {/* Tool call badges */}
            {slot.toolCalls.length > 0 && (
              <div className="take-lane-turn-tools">
                {slot.toolCalls.slice(0, 3).map((tc, idx) => (
                  <span key={idx} className="take-lane-tool-badge" title={tc.name || tc}>
                    <Icon icon="mdi:hammer-wrench" width="8" />
                  </span>
                ))}
                {slot.toolCalls.length > 3 && (
                  <span className="take-lane-tool-more">+{slot.toolCalls.length - 3}</span>
                )}
              </div>
            )}

            {/* Turn duration */}
            {slot.duration && (
              <span className="take-lane-turn-duration" title={`Turn ${slot.index} duration`}>
                {formatDuration(slot.duration)}
              </span>
            )}

            {/* Validation marker */}
            {loopUntil && slot.isUsed && (
              <span className={`take-lane-turn-validation ${slot.isEarlyExit ? 'passed' : ''} ${slot.validationFailed ? 'failed' : ''}`}>
                {slot.isEarlyExit ? (
                  <Icon icon="mdi:lightning-bolt" width="10" title="Early exit - validation passed" />
                ) : slot.validationFailed ? (
                  <Icon icon="mdi:close-circle" width="10" title={`Validation failed: ${slot.validationReason || 'Unknown'}`} />
                ) : (
                  <Icon icon="mdi:sync" width="10" title="Loop-until check" />
                )}
              </span>
            )}

            {/* Inline failure reason for loop_until failures */}
            {slot.validationFailed && slot.validationReason && (
              <div className="take-lane-turn-validation-failure">
                <Icon icon="mdi:alert-circle" width="10" />
                <span className="take-lane-turn-validation-reason">
                  {slot.validationReason.length > 50
                    ? slot.validationReason.substring(0, 50) + '...'
                    : slot.validationReason}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Unused turns indicator */}
      {turns.length < maxTurns && maxTurns > 1 && (
        <div className="take-lane-unused">
          <span className="take-lane-unused-label">
            (max {maxTurns})
          </span>
        </div>
      )}

      {/* Lane footer divider */}
      <div className="take-lane-divider" />

      {/* Footer stats */}
      <div className="take-lane-footer">
        {hasExecution ? (
          <>
            {cost > 0 && (
              <span className="take-lane-stat take-lane-cost">
                ${cost < 0.01 ? '<.01' : cost.toFixed(3)}
              </span>
            )}
            {durationDisplay && (
              <span className="take-lane-stat take-lane-duration">
                <Icon icon="mdi:clock-outline" width="10" />
                {durationDisplay}
              </span>
            )}
            <span className="take-lane-stat take-lane-turns-count">
              {turns.filter(t => t.status !== 'pending').length} turns
            </span>
            <span className="take-lane-stat take-lane-tools-count">
              {totalToolCalls} tools
            </span>
          </>
        ) : (
          <span className="take-lane-stat take-lane-tools-count">
            {maxTurns} max turns
          </span>
        )}
      </div>
    </div>
  );
};

export default SoundingLane;
