import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import { useExecutionSSE } from '../hooks/useExecutionSSE';
import './ExecutionNotebook.css';

/**
 * ExecutionNotebook - Real-time cascade execution visualization
 *
 * Shows cascade execution as a horizontal timeline of phase columns.
 * Each phase displays:
 * - Phase status (pending/running/completed/error)
 * - Turn count and cost accumulation
 * - Soundings progress with parallel indicators
 * - Live updates via SSE
 */
function ExecutionNotebook() {
  const {
    cascade,
    sessionId,
    executionStatus,
    executionError,
    executionStartTime,
    executionEndTime,
    totalCost,
    phaseResults,
    activeSoundings,
    executionLog,
    clearExecution,
  } = useWorkshopStore();

  // Connect to SSE for real-time updates
  useExecutionSSE();

  // Live duration counter
  const [liveDuration, setLiveDuration] = useState(0);

  useEffect(() => {
    if (executionStatus === 'running' && executionStartTime) {
      const interval = setInterval(() => {
        setLiveDuration((Date.now() - executionStartTime) / 1000);
      }, 100);
      return () => clearInterval(interval);
    } else if (executionEndTime && executionStartTime) {
      setLiveDuration((executionEndTime - executionStartTime) / 1000);
    }
  }, [executionStatus, executionStartTime, executionEndTime]);

  const phases = cascade.phases || [];

  // Count recent log entries for activity indicator
  const recentLogCount = executionLog.filter(
    (log) => Date.now() - log.timestamp < 2000
  ).length;

  return (
    <div className="execution-notebook">
      {/* Notebook Header */}
      <div className="notebook-header">
        <div className="notebook-header-left">
          <Icon icon="mdi:play-box-multiple" width="20" />
          <span>Execution Timeline</span>
          {recentLogCount > 0 && (
            <span className="activity-indicator" title="Events flowing">
              <Icon icon="mdi:broadcast" width="14" className="pulse" />
            </span>
          )}
        </div>

        <div className="notebook-header-right">
          {sessionId && (
            <>
              <span className="session-id">
                <Icon icon="mdi:identifier" width="14" />
                {sessionId}
              </span>
              <button
                className="clear-btn"
                onClick={clearExecution}
                title="Clear execution"
              >
                <Icon icon="mdi:close" width="16" />
              </button>
            </>
          )}
        </div>
      </div>

      {/* Status Bar */}
      {executionStatus !== 'idle' && (
        <div className={`status-bar status-${executionStatus}`}>
          <div className="status-left">
            {executionStatus === 'running' && (
              <>
                <Icon icon="mdi:loading" width="16" className="spinning" />
                <span>Executing cascade...</span>
              </>
            )}
            {executionStatus === 'completed' && (
              <>
                <Icon icon="mdi:check-circle" width="16" />
                <span>Execution completed</span>
              </>
            )}
            {executionStatus === 'error' && (
              <>
                <Icon icon="mdi:alert-circle" width="16" />
                <span>Error: {executionError}</span>
              </>
            )}
          </div>

          <div className="status-right">
            {liveDuration > 0 && (
              <span className="stat">
                <Icon icon="mdi:timer-outline" width="14" />
                {liveDuration.toFixed(1)}s
              </span>
            )}
            {totalCost > 0 && (
              <span className="stat cost">
                <Icon icon="mdi:currency-usd" width="14" />
                ${totalCost.toFixed(4)}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Timeline Content */}
      <div className="notebook-content">
        {phases.length === 0 ? (
          <div className="notebook-empty">
            <Icon icon="mdi:chart-timeline-variant" width="64" />
            <h3>No Phases Yet</h3>
            <p>Add phases to your cascade to see the execution timeline</p>
          </div>
        ) : sessionId ? (
          <div className="timeline-scroll">
            <div className="timeline-track">
              {phases.map((phase, idx) => (
                <PhaseColumn
                  key={phase.name}
                  phase={phase}
                  index={idx}
                  result={phaseResults[phase.name]}
                  activeSoundingsSet={activeSoundings[phase.name]}
                  isLast={idx === phases.length - 1}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="notebook-ready">
            <Icon icon="mdi:rocket-launch" width="64" />
            <h3>Ready to Run</h3>
            <p>{phases.length} phase{phases.length !== 1 ? 's' : ''} configured</p>
            <p className="ready-hint">Click "Run" to execute your cascade</p>
          </div>
        )}
      </div>

      {/* Execution Log (collapsible) */}
      {executionLog.length > 0 && (
        <ExecutionLog log={executionLog} />
      )}
    </div>
  );
}

/**
 * PhaseColumn - Single phase in the timeline with real-time updates
 *
 * When soundings are active, shows ghost blocks descending below the main phase
 * like nautical depth soundings. The winner "rises" back up to the main block.
 */
function PhaseColumn({ phase, index, result, activeSoundingsSet, isLast }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedSounding, setSelectedSounding] = useState(null);
  const status = result?.status || 'pending';
  const soundingsConfig = phase.soundings;
  const hasSoundings = soundingsConfig?.factor > 1;
  const soundingsCount = soundingsConfig?.factor || 1;
  const hasOutput = result?.output !== undefined;

  // Get sounding statuses from result
  const soundings = result?.soundings || {};
  const activeSoundingIndices = activeSoundingsSet || [];

  // Find winner sounding
  const winnerIndex = Object.entries(soundings).find(([_, s]) => s?.isWinner)?.[0];

  const handleClick = (e) => {
    // Don't toggle if clicking on a ghost block
    if (e.target.closest('.ghost-block')) return;
    if (hasOutput) {
      setExpanded(!expanded);
    }
  };

  const handleGhostClick = (e, soundingIndex) => {
    e.stopPropagation();
    setSelectedSounding(selectedSounding === soundingIndex ? null : soundingIndex);
  };

  return (
    <div className="phase-column-wrapper">
      {/* Main Phase Block */}
      <div
        className={`phase-column status-${status} ${hasOutput ? 'has-output' : ''} ${expanded ? 'expanded' : ''} ${hasSoundings ? 'has-soundings' : ''}`}
        onClick={handleClick}
      >
        {/* Connector to next phase */}
        {!isLast && (
          <div className="column-connector">
            <div className="connector-line-h" />
            <Icon icon="mdi:chevron-right" width="16" className="connector-arrow-h" />
          </div>
        )}

        <div className="column-header">
          <span className="column-number">{index + 1}</span>
          <span className="column-name">{phase.name}</span>
          {hasSoundings && (
            <span className="soundings-badge" title={`${soundingsCount} soundings`}>
              <Icon icon="mdi:source-branch" width="12" />
              {soundingsCount}
            </span>
          )}
          <StatusIcon status={status} />
        </div>

        <div className="column-body">
          {status === 'pending' && (
            <div className="column-pending">
              <Icon icon="mdi:clock-outline" width="24" />
              <span>Waiting...</span>
            </div>
          )}

          {status === 'running' && !hasSoundings && (
            <div className="column-running">
              <Icon icon="mdi:loading" width="24" className="spinning" />
              <span>Executing...</span>
              {result?.turnCount > 0 && (
                <span className="turn-counter">Turn {result.turnCount}</span>
              )}
              {result?.cost > 0 && (
                <span className="live-cost">${result.cost.toFixed(4)}</span>
              )}
            </div>
          )}

          {status === 'running' && hasSoundings && (
            <div className="column-running soundings-mode">
              <Icon icon="mdi:waves" width="24" className="wave-icon" />
              <span>Taking soundings...</span>
              <span className="soundings-progress">
                {activeSoundingIndices.length}/{soundingsCount} active
              </span>
            </div>
          )}

          {status === 'completed' && result && (
            <div className="column-completed">
              {hasSoundings && winnerIndex !== undefined && (
                <div className="result-stat winner-badge">
                  <Icon icon="mdi:trophy" width="14" />
                  <span>Sounding {winnerIndex}</span>
                </div>
              )}
              {result.cost > 0 && (
                <div className="result-stat">
                  <Icon icon="mdi:currency-usd" width="14" />
                  <span>${result.cost.toFixed(4)}</span>
                </div>
              )}
              {result.duration > 0 && (
                <div className="result-stat">
                  <Icon icon="mdi:clock-outline" width="14" />
                  <span>{result.duration.toFixed(1)}s</span>
                </div>
              )}
            </div>
          )}

          {status === 'error' && (
            <div className="column-error">
              <Icon icon="mdi:alert-circle" width="24" />
              <span>Failed</span>
            </div>
          )}
        </div>

        {/* Output preview/expand indicator */}
        {hasOutput && !expanded && (
          <div className="output-hint">
            <Icon icon="mdi:chevron-down" width="14" />
            <span>Click to view output</span>
          </div>
        )}

        {/* Expanded output view */}
        {expanded && hasOutput && (
          <div className="phase-output">
            <div className="output-header">
              <Icon icon="mdi:text-box-outline" width="14" />
              <span>Output</span>
              <Icon icon="mdi:chevron-up" width="14" />
            </div>
            <div className="output-content">
              <pre>{typeof result.output === 'string' ? result.output : JSON.stringify(result.output, null, 2)}</pre>
            </div>
          </div>
        )}
      </div>

      {/* Ghost Sounding Blocks - Descend below the main phase */}
      {hasSoundings && (status === 'running' || status === 'completed') && (
        <div className="soundings-depth">
          <div className="depth-line" />
          <div className="ghost-blocks">
            {Array.from({ length: soundingsCount }).map((_, i) => {
              const sounding = soundings[i];
              const isActive = activeSoundingIndices.includes(i);
              const isCompleted = sounding?.status === 'completed';
              const isWinner = sounding?.isWinner;
              const isSelected = selectedSounding === i;

              let ghostStatus = 'pending';
              if (isWinner) ghostStatus = 'winner';
              else if (isCompleted) ghostStatus = 'completed';
              else if (isActive) ghostStatus = 'running';

              return (
                <div
                  key={i}
                  className={`ghost-block ghost-${ghostStatus} ${isSelected ? 'selected' : ''}`}
                  style={{ '--depth': i, '--total': soundingsCount }}
                  onClick={(e) => handleGhostClick(e, i)}
                  title={`Sounding ${i}${isWinner ? ' (winner)' : ''}`}
                >
                  <div className="ghost-header">
                    <span className="ghost-index">S{i}</span>
                    {isWinner && <Icon icon="mdi:crown" width="12" className="crown" />}
                    {isActive && <Icon icon="mdi:loading" width="10" className="spinning" />}
                    {isCompleted && !isWinner && <Icon icon="mdi:check" width="10" />}
                  </div>

                  {/* Ghost body with live stats */}
                  <div className="ghost-body">
                    {sounding?.turnCount > 0 && (
                      <span className="ghost-stat">
                        <Icon icon="mdi:message-reply" width="10" />
                        {sounding.turnCount}
                      </span>
                    )}
                    {sounding?.cost > 0 && (
                      <span className="ghost-stat">
                        ${sounding.cost.toFixed(3)}
                      </span>
                    )}
                  </div>

                  {/* Output preview - always show brief, expand on click */}
                  {sounding?.output && (
                    <div className={`ghost-output ${isSelected ? 'expanded' : ''}`}>
                      <pre>{typeof sounding.output === 'string'
                        ? sounding.output.slice(0, isSelected ? 500 : 80) + (sounding.output.length > (isSelected ? 500 : 80) ? '...' : '')
                        : JSON.stringify(sounding.output, null, 2).slice(0, isSelected ? 500 : 80)
                      }</pre>
                    </div>
                  )}

                  {/* Rising effect for winner */}
                  {isWinner && (
                    <div className="winner-glow" />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * ExecutionLog - Collapsible event log
 */
function ExecutionLog({ log }) {
  const [expanded, setExpanded] = useState(false);

  // Show last 5 entries when collapsed, all when expanded
  const visibleLog = expanded ? log : log.slice(-5);

  const formatTime = (timestamp) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getEventIcon = (type) => {
    const icons = {
      phase_start: 'mdi:play-circle',
      phase_complete: 'mdi:check-circle',
      turn_start: 'mdi:message-reply',
      tool_call: 'mdi:wrench',
      tool_result: 'mdi:clipboard-check',
      cascade_complete: 'mdi:flag-checkered',
      cascade_error: 'mdi:alert-circle',
    };
    return icons[type] || 'mdi:circle';
  };

  const getEventColor = (type) => {
    const colors = {
      phase_start: 'var(--ocean-primary)',
      phase_complete: 'var(--success-green)',
      turn_start: 'var(--slate-blue-light)',
      tool_call: 'var(--compass-brass)',
      tool_result: 'var(--ocean-teal)',
      cascade_complete: 'var(--success-green)',
      cascade_error: 'var(--bloodaxe-red)',
    };
    return colors[type] || 'var(--mist-gray)';
  };

  const formatEvent = (entry) => {
    switch (entry.type) {
      case 'phase_start':
        return `Phase "${entry.phaseName}" started${entry.soundingIndex !== null ? ` (sounding ${entry.soundingIndex})` : ''}`;
      case 'phase_complete':
        return `Phase "${entry.phaseName}" completed`;
      case 'turn_start':
        return `Turn ${entry.turnNumber + 1} in "${entry.phaseName}"`;
      case 'tool_call':
        return `Tool call: ${entry.toolName}`;
      case 'tool_result':
        return `Tool result: ${entry.toolName}`;
      case 'cascade_complete':
        return 'Cascade completed successfully';
      case 'cascade_error':
        return `Error: ${entry.error}`;
      default:
        return entry.type;
    }
  };

  return (
    <div className={`execution-log ${expanded ? 'expanded' : ''}`}>
      <div
        className="log-header"
        onClick={() => setExpanded(!expanded)}
      >
        <Icon
          icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="16"
        />
        <Icon icon="mdi:text-box-outline" width="14" />
        <span>Event Log ({log.length})</span>
      </div>

      {(expanded || log.length <= 5) && (
        <div className="log-entries">
          {visibleLog.map((entry, idx) => (
            <div key={idx} className="log-entry">
              <span className="log-time">{formatTime(entry.timestamp)}</span>
              <Icon
                icon={getEventIcon(entry.type)}
                width="12"
                style={{ color: getEventColor(entry.type) }}
              />
              <span className="log-message">{formatEvent(entry)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusIcon({ status }) {
  const config = {
    pending: { icon: 'mdi:circle-outline', color: 'var(--mist-gray)' },
    running: { icon: 'mdi:loading', color: 'var(--compass-brass)', spin: true },
    completed: { icon: 'mdi:check-circle', color: 'var(--success-green)' },
    error: { icon: 'mdi:alert-circle', color: 'var(--bloodaxe-red)' },
  };

  const { icon, color, spin } = config[status] || config.pending;

  return (
    <Icon
      icon={icon}
      width="16"
      style={{ color }}
      className={spin ? 'spinning' : ''}
    />
  );
}

export default ExecutionNotebook;
