import React, { useState, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import { useExecutionSSE } from '../hooks/useExecutionSSE';
import './ExecutionNotebook.css';

// Constants for layout calculations
const PHASE_COLUMN_WIDTH = 220;
const PHASE_COLUMN_WIDTH_EXPANDED = 400;
const PHASE_COLUMN_GAP = 80; // Increased for handoff arrows
const PHASE_HEADER_HEIGHT = 44;

/**
 * ExecutionNotebook - Real-time cascade execution visualization
 *
 * Shows cascade execution as a horizontal timeline of phase columns.
 * Each phase displays:
 * - Phase status (pending/running/completed/error)
 * - Turn count and cost accumulation
 * - Soundings progress with parallel indicators
 * - Live updates via SSE
 * - Handoff arrows showing routing between phases
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
    lastExecutedHandoffs,
  } = useWorkshopStore();

  // Connect to SSE for real-time updates
  useExecutionSSE();

  // Track which phases are expanded (for arrow positioning)
  const [expandedPhases, setExpandedPhases] = useState(new Set());

  const togglePhaseExpanded = (phaseName) => {
    setExpandedPhases((prev) => {
      const next = new Set(prev);
      if (next.has(phaseName)) {
        next.delete(phaseName);
      } else {
        next.add(phaseName);
      }
      return next;
    });
  };

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
        ) : (
          <div className="timeline-scroll">
            <div className="timeline-track">
              {/* Handoff arrows SVG overlay */}
              <HandoffArrows
                phases={phases}
                phaseResults={phaseResults}
                lastExecutedHandoffs={lastExecutedHandoffs}
                sessionId={sessionId}
                expandedPhases={expandedPhases}
              />

              {phases.map((phase, idx) => {
                const hasExecutionData = sessionId && phaseResults[phase.name];
                return hasExecutionData ? (
                  <PhaseColumn
                    key={phase.name}
                    phase={phase}
                    index={idx}
                    result={phaseResults[phase.name]}
                    activeSoundingsSet={activeSoundings[phase.name]}
                    isLast={idx === phases.length - 1}
                    isExpanded={expandedPhases.has(phase.name)}
                    onToggleExpand={() => togglePhaseExpanded(phase.name)}
                  />
                ) : (
                  <GhostPhaseColumn
                    key={phase.name}
                    phase={phase}
                    index={idx}
                    allPhases={phases}
                    isLast={idx === phases.length - 1}
                  />
                );
              })}
            </div>
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
function PhaseColumn({ phase, index, result, activeSoundingsSet, isLast, isExpanded, onToggleExpand }) {
  const [selectedSounding, setSelectedSounding] = useState(null);
  const status = result?.status || 'pending';
  const soundingsConfig = phase.soundings;
  const hasSoundings = soundingsConfig?.factor > 1;
  const soundingsCount = soundingsConfig?.factor || 1;
  const hasOutput = result?.output !== undefined;
  const hasHandoffs = phase.handoffs && phase.handoffs.length > 0;

  // Get sounding statuses from result
  const soundings = result?.soundings || {};
  const activeSoundingIndices = activeSoundingsSet || [];

  // Find winner sounding
  const winnerIndex = Object.entries(soundings).find(([_, s]) => s?.isWinner)?.[0];

  const handleClick = (e) => {
    // Don't toggle if clicking on a ghost block
    if (e.target.closest('.ghost-block')) return;
    if (hasOutput && onToggleExpand) {
      onToggleExpand();
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
        className={`phase-column status-${status} ${hasOutput ? 'has-output' : ''} ${isExpanded ? 'expanded' : ''} ${hasSoundings ? 'has-soundings' : ''}`}
        onClick={handleClick}
      >
        {/* Connector to next phase (only if no handoffs - handoffs use SVG arrows) */}
        {!isLast && !hasHandoffs && (
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
        {hasOutput && !isExpanded && (
          <div className="output-hint">
            <Icon icon="mdi:chevron-down" width="14" />
            <span>Click to view output</span>
          </div>
        )}

        {/* Expanded output view */}
        {isExpanded && hasOutput && (
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
 * HandoffArrows - SVG overlay showing routing between phases
 *
 * Draws arrows from phases to their handoff targets.
 * Ghost mode: dashed lines to all possible targets
 * Realized mode: solid line to executed target, dashed for others
 */
function HandoffArrows({ phases, phaseResults, lastExecutedHandoffs, sessionId, expandedPhases }) {
  // Build list of all handoff connections
  const connections = useMemo(() => {
    const conns = [];

    phases.forEach((phase, sourceIdx) => {
      if (!phase.handoffs || phase.handoffs.length === 0) return;

      const isPhaseExecuted = sessionId && phaseResults[phase.name]?.status === 'completed';
      const executedTarget = lastExecutedHandoffs?.[phase.name];

      phase.handoffs.forEach((handoff) => {
        const targetName = typeof handoff === 'string' ? handoff : handoff.target;
        const description = typeof handoff === 'object' ? handoff.description : null;
        const targetIdx = phases.findIndex((p) => p.name === targetName);

        if (targetIdx === -1) return; // Target not found

        // Get context info from source phase
        const contextInfo = phase.context?.from
          ? `ctx: ${phase.context.from.join(', ')}`
          : null;

        conns.push({
          sourceIdx,
          targetIdx,
          sourceName: phase.name,
          targetName,
          description,
          contextInfo,
          isExecuted: isPhaseExecuted && executedTarget === targetName,
          isGhost: !isPhaseExecuted,
        });
      });
    });

    return conns;
  }, [phases, phaseResults, lastExecutedHandoffs, sessionId]);

  // Calculate X position for a phase index, accounting for expanded phases
  const getPhaseX = (idx) => {
    let x = 0;
    for (let i = 0; i < idx; i++) {
      const phaseName = phases[i]?.name;
      const isExp = expandedPhases?.has(phaseName);
      x += (isExp ? PHASE_COLUMN_WIDTH_EXPANDED : PHASE_COLUMN_WIDTH) + PHASE_COLUMN_GAP;
    }
    return x;
  };

  // Get width of a specific phase
  const getPhaseWidth = (idx) => {
    const phaseName = phases[idx]?.name;
    return expandedPhases?.has(phaseName) ? PHASE_COLUMN_WIDTH_EXPANDED : PHASE_COLUMN_WIDTH;
  };

  if (connections.length === 0) return null;

  // Calculate SVG dimensions based on expanded states
  let totalWidth = 0;
  phases.forEach((phase) => {
    const isExp = expandedPhases?.has(phase.name);
    totalWidth += (isExp ? PHASE_COLUMN_WIDTH_EXPANDED : PHASE_COLUMN_WIDTH) + PHASE_COLUMN_GAP;
  });
  const svgWidth = totalWidth;
  const svgHeight = 300; // Enough height for curved paths

  // Calculate path for a connection
  const getPath = (sourceIdx, targetIdx) => {
    const sourceX = getPhaseX(sourceIdx) + getPhaseWidth(sourceIdx);
    const targetX = getPhaseX(targetIdx);
    const y = PHASE_HEADER_HEIGHT + 40; // Middle of phase body

    const distance = targetIdx - sourceIdx;

    if (distance === 1) {
      // Adjacent: simple horizontal line
      return `M ${sourceX} ${y} L ${targetX} ${y}`;
    } else if (distance > 1) {
      // Forward skip: curve above
      const midX = (sourceX + targetX) / 2;
      const curveHeight = Math.min(30 + distance * 15, 80);
      return `M ${sourceX} ${y} Q ${midX} ${y - curveHeight} ${targetX} ${y}`;
    } else {
      // Backward: curve below
      const midX = (sourceX + targetX) / 2;
      const curveHeight = Math.min(30 + Math.abs(distance) * 15, 80);
      return `M ${sourceX} ${y} Q ${midX} ${y + curveHeight} ${targetX} ${y}`;
    }
  };

  // Calculate label position
  const getLabelPos = (sourceIdx, targetIdx) => {
    const sourceX = getPhaseX(sourceIdx) + getPhaseWidth(sourceIdx);
    const targetX = getPhaseX(targetIdx);
    const y = PHASE_HEADER_HEIGHT + 40;

    const midX = (sourceX + targetX) / 2;
    const distance = targetIdx - sourceIdx;

    if (distance === 1) {
      return { x: midX, y: y - 12 };
    } else if (distance > 1) {
      const curveHeight = Math.min(30 + distance * 15, 80);
      return { x: midX, y: y - curveHeight - 8 };
    } else {
      const curveHeight = Math.min(30 + Math.abs(distance) * 15, 80);
      return { x: midX, y: y + curveHeight + 14 };
    }
  };

  return (
    <svg
      className="handoff-arrows-svg"
      width={svgWidth}
      height={svgHeight}
      style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
    >
      <defs>
        {/* Arrow markers */}
        <marker
          id="arrow-ghost"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--storm-cloud)" />
        </marker>
        <marker
          id="arrow-executed"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--teal-primary)" />
        </marker>
        <marker
          id="arrow-potential"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--compass-brass)" />
        </marker>
      </defs>

      {connections.map((conn, idx) => {
        const path = getPath(conn.sourceIdx, conn.targetIdx);
        const labelPos = getLabelPos(conn.sourceIdx, conn.targetIdx);
        const label = conn.description || conn.contextInfo;

        let strokeColor, markerEnd, strokeDasharray, opacity;
        if (conn.isExecuted) {
          strokeColor = 'var(--teal-primary)';
          markerEnd = 'url(#arrow-executed)';
          strokeDasharray = 'none';
          opacity = 1;
        } else if (conn.isGhost) {
          strokeColor = 'var(--storm-cloud)';
          markerEnd = 'url(#arrow-ghost)';
          strokeDasharray = '6,4';
          opacity = 0.6;
        } else {
          // Not executed but phase was run (alternative path)
          strokeColor = 'var(--compass-brass)';
          markerEnd = 'url(#arrow-potential)';
          strokeDasharray = '4,4';
          opacity = 0.4;
        }

        return (
          <g key={`${conn.sourceName}-${conn.targetName}-${idx}`}>
            <path
              d={path}
              fill="none"
              stroke={strokeColor}
              strokeWidth={conn.isExecuted ? 2.5 : 2}
              strokeDasharray={strokeDasharray}
              opacity={opacity}
              markerEnd={markerEnd}
              className={conn.isExecuted ? 'handoff-path executed' : 'handoff-path'}
            />
            {label && (
              <g transform={`translate(${labelPos.x}, ${labelPos.y})`}>
                <rect
                  x={-label.length * 3.5 - 6}
                  y={-9}
                  width={label.length * 7 + 12}
                  height={18}
                  rx={4}
                  fill="var(--bg-card)"
                  stroke={conn.isExecuted ? 'var(--teal-primary)' : 'var(--storm-cloud)'}
                  strokeWidth={1}
                  opacity={conn.isGhost ? 0.7 : 0.9}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize="9"
                  fontFamily="Monaco, Menlo, monospace"
                  fill={conn.isExecuted ? 'var(--teal-primary)' : 'var(--mist-gray)'}
                >
                  {label.length > 20 ? label.slice(0, 20) + '...' : label}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * GhostPhaseColumn - Preview of a phase before execution
 *
 * Shows a ghost representation of what this phase will look like when run.
 * Includes ghost soundings lanes, handoff indicators, etc.
 */
function GhostPhaseColumn({ phase, index, allPhases, isLast }) {
  const soundingsConfig = phase.soundings;
  const hasSoundings = soundingsConfig?.factor > 1;
  const soundingsCount = soundingsConfig?.factor || 1;
  const hasHandoffs = phase.handoffs && phase.handoffs.length > 0;
  const hasReforge = soundingsConfig?.reforge?.steps > 0;
  const mode = soundingsConfig?.mode || 'evaluate';

  return (
    <div className="phase-column-wrapper ghost-wrapper">
      {/* Main Ghost Phase Block */}
      <div className={`phase-column ghost-phase ${hasSoundings ? 'has-soundings' : ''}`}>
        {/* Connector to next phase (only if no handoffs - handoffs use SVG arrows) */}
        {!isLast && !hasHandoffs && (
          <div className="column-connector ghost-connector">
            <div className="connector-line-h" />
            <Icon icon="mdi:chevron-right" width="16" className="connector-arrow-h" />
          </div>
        )}

        <div className="column-header">
          <span className="column-number ghost-number">
            {index + 1}
            <span className="ghost-indicator">?</span>
          </span>
          <span className="column-name">{phase.name}</span>
          {hasSoundings && (
            <span className="soundings-badge ghost-badge" title={`${soundingsCount} soundings configured`}>
              <Icon icon="mdi:source-branch" width="12" />
              {soundingsCount}
              {hasReforge && (
                <Icon icon="mdi:hammer-wrench" width="10" className="reforge-icon" />
              )}
            </span>
          )}
          <Icon icon="mdi:eye-outline" width="14" className="ghost-eye" title="Preview - not yet executed" />
        </div>

        <div className="column-body ghost-body">
          <div className="ghost-preview-content">
            <Icon icon="mdi:ghost-outline" width="20" className="ghost-icon" />
            <span className="ghost-label">Preview</span>
          </div>
          {phase.model && (
            <div className="ghost-model" title={phase.model}>
              <Icon icon="mdi:brain" width="10" />
              {phase.model.split('/').pop()}
            </div>
          )}
          {phase.instructions && (
            <div className="ghost-instructions" title={phase.instructions}>
              <Icon icon="mdi:text" width="10" />
              <span>{phase.instructions.slice(0, 60)}{phase.instructions.length > 60 ? '...' : ''}</span>
            </div>
          )}
        </div>

        {/* Tackle preview */}
        {phase.tackle && phase.tackle.length > 0 && (
          <div className="ghost-tackle">
            <Icon icon="mdi:wrench" width="10" />
            <span>{phase.tackle.length} tool{phase.tackle.length !== 1 ? 's' : ''}</span>
          </div>
        )}
      </div>

      {/* Ghost Soundings Preview */}
      {hasSoundings && (
        <div className="soundings-depth ghost-soundings-depth">
          <div className="depth-line ghost-depth-line" />
          <div className="ghost-blocks">
            {Array.from({ length: soundingsCount }).map((_, i) => (
              <div
                key={i}
                className="ghost-block ghost-preview-block"
                style={{ '--depth': i, '--total': soundingsCount }}
                title={`Sounding ${i + 1} (preview)`}
              >
                <div className="ghost-header">
                  <span className="ghost-index">S{i}</span>
                </div>
                <div className="ghost-body">
                  <Icon icon="mdi:help" width="12" className="ghost-question" />
                </div>
              </div>
            ))}
          </div>
          {/* Mode indicator */}
          <div className="ghost-mode-indicator">
            {mode === 'evaluate' ? (
              <>
                <Icon icon="mdi:trophy-outline" width="12" />
                <span>Pick best</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:merge" width="12" />
                <span>Combine all</span>
              </>
            )}
          </div>
        </div>
      )}

      {/* Handoffs indicator - arrows are shown via SVG overlay */}
      {hasHandoffs && (
        <div className="ghost-handoffs-indicator">
          <Icon icon="mdi:arrow-decision" width="12" />
          <span>{phase.handoffs.length} route{phase.handoffs.length !== 1 ? 's' : ''}</span>
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
