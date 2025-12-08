import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import { getSequentialColor } from './CascadeBar';
import './PhaseBar.css';

function PhaseBar({ phase, maxCost, status = null, onClick, phaseIndex = null }) {
  const [hoveredSegment, setHoveredSegment] = useState(null);
  // Calculate bar width based on cost (relative to max)
  // Apply logarithmic scaling to prevent extreme ratios
  const costPercent = maxCost > 0 ? (phase.avg_cost / maxCost) * 100 : 10;

  // Use square root scaling for better visual distribution
  // This prevents tiny bars when costs vary widely
  const scaledPercent = Math.sqrt(costPercent / 100) * 100;

  const barWidth = Math.max(scaledPercent, 10); // Minimum 10% for visibility

  // Determine bar color based on status (for instances) or default (for definitions)
  let barClass = 'phase-bar-fill';
  if (status) {
    barClass += ` status-${status}`;
  }

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    return `${seconds.toFixed(1)}s`;
  };

  // Get phase color for the legend indicator
  const phaseColor = phaseIndex !== null ? getSequentialColor(phaseIndex) : null;

  return (
    <div className="phase-bar-container" onClick={onClick}>
      <div className="phase-bar-header">
        <div className="phase-title">
          {phaseColor && (
            <span
              className="phase-color-indicator"
              style={{ backgroundColor: phaseColor }}
              title={`Phase ${phaseIndex + 1}`}
            />
          )}
          <span className="phase-name">{phase.name}</span>
          {phase.message_count > 0 && (
            <span className="message-count">({phase.message_count} messages)</span>
          )}
        </div>
        <div className="phase-metrics">
          <span className="phase-cost">{formatCost(phase.avg_cost)}</span>
          {phase.avg_duration > 0 && (
            <span className="phase-duration">{formatDuration(phase.avg_duration)}</span>
          )}
          {status && <StatusIndicator status={status} />}
        </div>
      </div>

      <div className="phase-bar-track">
        <div
          className={barClass}
          style={{ width: `${barWidth}%` }}
        >
          {/* Segmented bar for soundings - sized by actual cost */}
          {phase.sounding_attempts && phase.sounding_attempts.length > 1 ? (
            <div className="sounding-segments">
              {(() => {
                // Deduplicate by index (backend might return duplicates)
                const uniqueAttempts = Array.from(
                  new Map(phase.sounding_attempts.map(a => [a.index, a])).values()
                ).sort((a, b) => a.index - b.index);

                // Calculate total cost across all attempts
                const totalCost = uniqueAttempts.reduce((sum, a) => sum + (a.cost || 0), 0);
                const hasAnyCost = totalCost > 0;

                return uniqueAttempts.map((attempt) => {
                  const isWinner = attempt.is_winner;
                  // Width based on actual cost if available, otherwise equal
                  const widthPercent = hasAnyCost
                    ? ((attempt.cost || 0) / totalCost) * 100
                    : 100 / phase.sounding_attempts.length;

                  const turnCount = attempt.turns ? attempt.turns.length : 0;

                  const segmentWidth = Math.max(widthPercent, 5);
                  const hasRoomForCost = segmentWidth > 15;  // Only show if segment is >15% wide

                  return (
                    <div
                      key={attempt.index}
                      className={`segment ${isWinner ? 'winner' : 'loser'}`}
                      style={{ width: `${segmentWidth}%` }}
                      onMouseEnter={() => setHoveredSegment(attempt)}
                      onMouseLeave={() => setHoveredSegment(null)}
                      title={`Sounding ${attempt.index + 1}: ${formatCost(attempt.cost)}`}
                    >
                      {turnCount > 1 && (
                        <span className="turn-count">{turnCount}</span>
                      )}
                      {hasRoomForCost && attempt.cost > 0 && (
                        <span className="segment-cost">{formatCost(attempt.cost)}</span>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          ) : phase.soundings_factor > 1 ? (
            <div className="bar-segments" style={{ '--segments': phase.soundings_factor }}></div>
          ) : phase.turn_costs && phase.turn_costs.length > 1 ? (
            // Non-sounding phase with multiple turns - show as segments
            <div className="sounding-segments">
              {(() => {
                console.log('Rendering retry segments for', phase.name, phase.turn_costs);
                const totalCost = phase.turn_costs.reduce((sum, t) => sum + (t.cost || 0), 0);
                const hasAnyCost = totalCost > 0;
                console.log('Total cost:', totalCost, 'hasAnyCost:', hasAnyCost);

                return phase.turn_costs.map((turn, idx) => {
                  const widthPercent = hasAnyCost
                    ? ((turn.cost || 0) / totalCost) * 100
                    : 100 / phase.turn_costs.length;

                  const isLast = idx === phase.turn_costs.length - 1;
                  const segmentWidth = Math.max(widthPercent, 5);
                  const hasRoomForCost = segmentWidth > 15;

                  console.log(`Retry attempt ${idx}: width=${segmentWidth}%, hasRoom=${hasRoomForCost}, cost=${turn.cost}`);

                  return (
                    <div
                      key={idx}
                      className={`segment ${isLast ? 'winner' : 'loser'}`}
                      style={{ width: `${segmentWidth}%` }}
                      onMouseEnter={() => setHoveredSegment({
                        turns: [turn],
                        cost: turn.cost,
                        index: idx,
                        is_retry: true,
                        is_winner: isLast
                      })}
                      onMouseLeave={() => setHoveredSegment(null)}
                      title={`Attempt ${idx + 1}: ${formatCost(turn.cost)}`}
                    >
                      <span className="turn-count">{idx + 1}</span>
                      {hasRoomForCost && turn.cost > 0 && (
                        <span className="segment-cost">{formatCost(turn.cost)}</span>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          ) : null}

          {/* Tool call indicators at bottom */}
          {phase.tool_calls && phase.tool_calls.length > 0 && (
            <div className="tool-indicators">
              {phase.tool_calls.slice(0, 5).map((tool, idx) => (
                <div key={idx} className="tool-dot" title={tool}></div>
              ))}
              {phase.tool_calls.length > 5 && (
                <span className="tool-overflow">+{phase.tool_calls.length - 5}</span>
              )}
            </div>
          )}

          {/* Tooltip for hovered segment */}
          {hoveredSegment && (
            <div className="segment-tooltip">
              <div className="tooltip-header">
                {hoveredSegment.is_retry ? (
                  `Attempt ${hoveredSegment.index + 1}`
                ) : hoveredSegment.index !== undefined ? (
                  `Sounding ${hoveredSegment.index + 1} ${hoveredSegment.is_winner ? '(Winner)' : ''}`
                ) : (
                  phase.name
                )}
              </div>
              <div className="tooltip-total">
                Total: {formatCost(hoveredSegment.cost || 0)}
              </div>
              {hoveredSegment.turns && hoveredSegment.turns.length > 0 && (
                <div className="tooltip-turns">
                  {hoveredSegment.turns.map((turn, idx) => (
                    <div key={idx} className="tooltip-turn">
                      <span>Turn {idx + 1}:</span>
                      <span>{formatCost(turn.cost)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

      </div>

      {/* Individual sounding bars - normalized view */}
      {phase.sounding_attempts && phase.sounding_attempts.length > 1 && (
        <div className="individual-soundings">
          {(() => {
            // Deduplicate by index
            const uniqueAttempts = Array.from(
              new Map(phase.sounding_attempts.map(a => [a.index, a])).values()
            ).sort((a, b) => a.index - b.index);

            // Find max cost for normalization
            const maxCost = Math.max(...uniqueAttempts.map(a => a.cost || 0), 0.001);

            // Check if there's a mix of models (more than one unique model)
            const uniqueModels = new Set(uniqueAttempts.map(a => a.model).filter(Boolean));
            const hasMultipleModels = uniqueModels.size > 1;

            // Helper to get short model name
            const getShortModel = (model) => {
              if (!model) return null;
              // Extract just the model name after the provider prefix
              const parts = model.split('/');
              return parts[parts.length - 1];
            };

            return uniqueAttempts.map((attempt) => {
              const isWinner = attempt.is_winner;
              // Sounding is running if phase is running and no winner has been determined yet
              const isRunning = status === 'running' && (isWinner === null || isWinner === undefined);
              const widthPercent = maxCost > 0 ? ((attempt.cost || 0) / maxCost) * 100 : 10;
              const barWidth = Math.max(widthPercent, isRunning ? 30 : 5); // Running bars get minimum 30% for visibility

              // Determine class: running > winner > loser
              let barClass = 'individual-sounding-bar';
              if (isRunning) {
                barClass += ' running';
              } else if (isWinner) {
                barClass += ' winner';
              } else {
                barClass += ' loser';
              }

              const shortModel = hasMultipleModels ? getShortModel(attempt.model) : null;

              return (
                <div key={attempt.index} className="individual-sounding-row">
                  <span className="sounding-index-label">
                    <span className="source-badge" style={{background: isRunning ? '#D9A553' : '#4ec9b0', color: '#1e1e1e', padding: '1px 5px', borderRadius: '3px', fontSize: '10px'}}>
                      S{attempt.index}
                    </span>
                    {isWinner && <span className="winner-icon" title="Winner"><Icon icon="mdi:trophy" width="14" style={{ color: '#fbbf24' }} /></span>}
                    {isRunning && <span className="running-icon" title="Running"><Icon icon="mdi:progress-clock" width="14" style={{ color: '#fbbf24' }} /></span>}
                  </span>
                  <div className="individual-sounding-track">
                    <div
                      className={barClass}
                      style={{ width: `${barWidth}%` }}
                      title={`Sounding ${attempt.index}: ${isRunning ? 'Running...' : formatCost(attempt.cost)}${attempt.model ? ` (${attempt.model})` : ''}`}
                    >
                      <span className="sounding-cost-label">{isRunning ? '...' : formatCost(attempt.cost)}</span>
                    </div>
                    {shortModel && (
                      <span className="sounding-model-label" title={attempt.model}>
                        {shortModel}
                      </span>
                    )}
                  </div>
                </div>
              );
            });
          })()}
        </div>
      )}

      <div className="phase-badges">
        <ComplexityBadges phase={phase} />

        {/* Tool calls indicator */}
        {phase.tool_calls && phase.tool_calls.length > 0 && (
          <span className="complexity-badge tools" title={phase.tool_calls.join(', ')}>
            <Icon icon="mdi:wrench" width="14" />
            {phase.tool_calls.length}
          </span>
        )}

        {/* Show error message for failed phases */}
        {phase.error_message ? (
          <span className="phase-snippet error">
            <Icon icon="mdi:alert-circle" width="14" style={{ flexShrink: 0 }} />
            {phase.error_message}
          </span>
        ) : phase.output_snippet ? (
          <span className="phase-snippet output">{phase.output_snippet}</span>
        ) : phase.instructions ? (
          <span className="phase-snippet instructions">"{phase.instructions}"</span>
        ) : null}
      </div>
    </div>
  );
}

function StatusIndicator({ status }) {
  const statusConfig = {
    completed: { icon: 'mdi:check-circle', color: '#34d399' },
    running: { icon: 'mdi:loading', color: '#fbbf24' },
    error: { icon: 'mdi:alert-circle', color: '#f87171' },
    pending: { icon: 'mdi:circle-outline', color: '#4b5563' }
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <Icon
      icon={config.icon}
      width="16"
      style={{ color: config.color }}
      className={status === 'running' ? 'spinning' : ''}
    />
  );
}

function ComplexityBadges({ phase }) {
  const badges = [];

  // Soundings (with winner indication for instances)
  if (phase.sounding_total > 1) {
    // Instance view - show total→winner, plus turns if multiple
    const winnerNum = phase.sounding_winner !== null ? phase.sounding_winner + 1 : '?';
    let badgeText = `${phase.sounding_total}→${winnerNum}`;
    if (phase.max_turns_actual > 1) {
      badgeText += ` x${phase.max_turns_actual}`;
    }
    badges.push(
      <span key="soundings" className="complexity-badge soundings">
        <Icon icon="mdi:sign-direction" width="14" />
        {badgeText}
      </span>
    );
  } else if (phase.soundings_factor > 1) {
    // Definition view - show just factor
    badges.push(
      <span key="soundings" className="complexity-badge soundings">
        <Icon icon="mdi:sign-direction" width="14" />
        {phase.soundings_factor}
      </span>
    );
  }

  // Reforge
  if (phase.reforge_steps > 0) {
    badges.push(
      <span key="reforge" className="complexity-badge reforge">
        <Icon icon="mdi:hammer" width="14" />
        {phase.reforge_steps}
      </span>
    );
  }

  // Wards
  if (phase.ward_count > 0) {
    badges.push(
      <span key="wards" className="complexity-badge wards">
        <Icon icon="mdi:shield" width="14" />
        {phase.ward_count}
      </span>
    );
  }

  // Loop/retry - show actual turns for instances, max_turns for definitions
  const actualTurns = phase.turn_costs ? phase.turn_costs.length : phase.max_turns_actual;
  const maxTurns = phase.max_turns;

  if (actualTurns > 0 && maxTurns && maxTurns > 1) {
    // Instance view - show actual/max
    badges.push(
      <span key="loop" className="complexity-badge loop">
        <Icon icon="mdi:repeat" width="14" />
        {actualTurns}/{maxTurns}
      </span>
    );
  } else if (maxTurns > 1) {
    // Definition view or just max
    badges.push(
      <span key="loop" className="complexity-badge loop">
        <Icon icon="mdi:repeat" width="14" />
        {maxTurns}
      </span>
    );
  } else if (phase.has_loop_until) {
    // Unbounded loop
    badges.push(
      <span key="loop" className="complexity-badge loop">
        <Icon icon="mdi:repeat" width="14" />
        ∞
      </span>
    );
  }

  // Audibles - show count of audible injections
  if (phase.audible_count > 0) {
    badges.push(
      <span key="audible" className="complexity-badge audible" title={`${phase.audible_count} audible${phase.audible_count > 1 ? 's' : ''} called`}>
        <Icon icon="mdi:bullhorn" width="14" />
        {phase.audible_count}
      </span>
    );
  }

  return <>{badges}</>;
}

export default PhaseBar;
