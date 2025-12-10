import React from 'react';
import { Icon } from '@iconify/react';
import { getSequentialColor } from './CascadeBar';
import './PhaseBar.css';

function PhaseBar({ phase, maxCost, status = null, onClick, phaseIndex = null }) {
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
        </div>
        <div className="phase-metrics">
          <span className="phase-cost">{formatCost(phase.avg_cost)}</span>
          {status && <StatusIndicator status={status} />}
        </div>
      </div>

      <div className="phase-bar-track">
        <div
          className={barClass}
          style={{ width: `${barWidth}%` }}
        />
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
            const maxSoundingCost = Math.max(...uniqueAttempts.map(a => a.cost || 0), 0.001);

            // Check if there's a mix of models (more than one unique model)
            const uniqueModels = new Set(uniqueAttempts.map(a => a.model).filter(Boolean));
            const hasMultipleModels = uniqueModels.size > 1;

            // Helper to get short model name
            const getShortModel = (model) => {
              if (!model) return null;
              const parts = model.split('/');
              return parts[parts.length - 1];
            };

            return uniqueAttempts.map((attempt) => {
              const isWinner = attempt.is_winner;
              // Sounding is running if phase is running and no winner has been determined yet
              const isRunning = status === 'running' && (isWinner === null || isWinner === undefined);
              const widthPercent = maxSoundingCost > 0 ? ((attempt.cost || 0) / maxSoundingCost) * 100 : 10;
              const soundingBarWidth = Math.max(widthPercent, isRunning ? 30 : 5);

              // Determine class: running > winner > loser
              let soundingBarClass = 'individual-sounding-bar';
              if (isRunning) {
                soundingBarClass += ' running';
              } else if (isWinner) {
                soundingBarClass += ' winner';
              } else {
                soundingBarClass += ' loser';
              }

              const shortModel = hasMultipleModels ? getShortModel(attempt.model) : null;

              // Determine if the bar extends far enough to overlap the model label
              // Label is positioned at right: 4px with max-width ~120px
              // Track width varies, but text typically starts around 65-75% from left
              // Use 70% threshold to avoid false positives on shorter bars
              const barOverlapsText = soundingBarWidth > 70;
              const needsDarkText = isWinner && barOverlapsText;

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
                      className={soundingBarClass}
                      style={{ width: `${soundingBarWidth}%` }}
                      title={`Sounding ${attempt.index}: ${isRunning ? 'Running...' : formatCost(attempt.cost)}${attempt.model ? ` (${attempt.model})` : ''}`}
                    >
                      <span className="sounding-cost-label">{isRunning ? '...' : formatCost(attempt.cost)}</span>
                    </div>
                    {shortModel && (
                      <span
                        className={`sounding-model-label ${needsDarkText ? 'on-winner-bar' : ''}`}
                        title={attempt.model}
                      >
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

export default PhaseBar;
