import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import { useExecutionSSE } from '../hooks/useExecutionSSE';
import './ExecutionNotebook.css';

// Constants for layout calculations
const PHASE_COLUMN_WIDTH = 220;
const PHASE_COLUMN_WIDTH_EXPANDED = 400;
const PHASE_COLUMN_GAP = 60; // Horizontal gap between phases
const PHASE_ROW_GAP = 60; // Minimum vertical gap between rows
const PHASE_HEADER_HEIGHT = 44;
const PHASE_BASE_HEIGHT = 140; // Base height of a phase column (compact stats row)
const PHASE_EXPANDED_EXTRA = 200; // Extra height when phase output is expanded
const SOUNDING_BLOCK_HEIGHT = 85; // Height per sounding block (vertical stack)
const SOUNDING_DEPTH_PADDING = 30; // Extra padding for soundings area
const TIMELINE_PADDING = 16;
const LEFT_MARGIN = 50; // Space on left for row wrap connectors

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

  // Track which phases are COLLAPSED (default is expanded to show output)
  const [collapsedPhases, setCollapsedPhases] = useState(new Set());

  const togglePhaseExpanded = (phaseName) => {
    setCollapsedPhases((prev) => {
      const next = new Set(prev);
      if (next.has(phaseName)) {
        next.delete(phaseName); // Uncollapse = expand
      } else {
        next.add(phaseName); // Collapse
      }
      return next;
    });
  };

  // Helper: is phase expanded? (default true unless collapsed)
  const isPhaseExpanded = (phaseName) => !collapsedPhases.has(phaseName);

  // Track container width for row wrapping
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(800);

  // Get phases early so we can use them in layout calculation
  const phases = cascade.phases || [];

  useEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width - TIMELINE_PADDING * 2);
      }
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Calculate phase layout with row wrapping and dynamic row heights
  const phaseLayout = useMemo(() => {
    const layout = [];
    let currentX = 0;
    let currentRow = 0;
    let maxRowWidth = 0;

    // Account for left margin in available width
    const availableWidth = containerWidth - LEFT_MARGIN;

    // Helper to calculate phase height including soundings and expansion
    const getPhaseHeight = (phase, isExpanded) => {
      let height = PHASE_BASE_HEIGHT;

      // Add extra height if phase output is expanded
      if (isExpanded) {
        height += PHASE_EXPANDED_EXTRA;
      }

      // Add height for soundings (vertical stack - each sounding adds height)
      const soundingsFactor = phase.soundings?.factor || 0;
      if (soundingsFactor > 1) {
        height += (soundingsFactor * SOUNDING_BLOCK_HEIGHT) + SOUNDING_DEPTH_PADDING;
      }

      return height;
    };

    // First pass: assign phases to rows
    const rowAssignments = [];
    phases.forEach((phase, idx) => {
      const isExpanded = isPhaseExpanded(phase.name);
      const width = isExpanded ? PHASE_COLUMN_WIDTH_EXPANDED : PHASE_COLUMN_WIDTH;
      const totalWidth = width + PHASE_COLUMN_GAP;

      // Check if we need to wrap to next row
      if (currentX + width > availableWidth && idx > 0) {
        currentRow++;
        currentX = 0;
      }

      rowAssignments.push({
        phase,
        index: idx,
        row: currentRow,
        x: currentX + LEFT_MARGIN,
        width,
        isExpanded,
        height: getPhaseHeight(phase, isExpanded),
      });

      currentX += totalWidth;
      maxRowWidth = Math.max(maxRowWidth, currentX + LEFT_MARGIN);
    });

    // Second pass: calculate row heights (max height of phases in each row)
    const rowHeights = {};
    rowAssignments.forEach((item) => {
      const currentMax = rowHeights[item.row] || PHASE_BASE_HEIGHT;
      rowHeights[item.row] = Math.max(currentMax, item.height);
    });

    // Third pass: calculate cumulative Y positions
    const rowYPositions = {};
    let cumulativeY = 0;
    const totalRows = currentRow + 1;
    for (let r = 0; r < totalRows; r++) {
      rowYPositions[r] = cumulativeY;
      cumulativeY += (rowHeights[r] || PHASE_BASE_HEIGHT) + PHASE_ROW_GAP;
    }

    // Final pass: assign Y positions to phases
    rowAssignments.forEach((item) => {
      layout.push({
        ...item,
        y: rowYPositions[item.row],
        rowHeight: rowHeights[item.row],
      });
    });

    const totalHeight = cumulativeY;

    return { positions: layout, totalRows, totalHeight, maxRowWidth, rowHeights, rowYPositions };
  }, [phases, collapsedPhases, containerWidth, isPhaseExpanded]);

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
      <div className="notebook-content" ref={containerRef}>
        {phases.length === 0 ? (
          <div className="notebook-empty">
            <Icon icon="mdi:chart-timeline-variant" width="64" />
            <h3>No Phases Yet</h3>
            <p>Add phases to your cascade to see the execution timeline</p>
          </div>
        ) : (
          <div className="timeline-scroll">
            <div
              className="timeline-track timeline-track-wrapped"
              style={{
                width: Math.max(phaseLayout.maxRowWidth, containerWidth),
                height: phaseLayout.totalHeight,
              }}
            >
              {/* Handoff arrows SVG overlay */}
              <HandoffArrows
                phases={phases}
                phaseResults={phaseResults}
                lastExecutedHandoffs={lastExecutedHandoffs}
                sessionId={sessionId}
                phaseLayout={phaseLayout}
              />

              {/* Row connectors for wrapped rows (only for sequential phases without handoffs) */}
              {phaseLayout.totalRows > 1 && (
                <RowConnectors phaseLayout={phaseLayout} phases={phases} />
              )}

              {phaseLayout.positions.map((pos, idx) => {
                const { phase, x, y, width, row } = pos;
                const hasExecutionData = sessionId && phaseResults[phase.name];
                const isLastInRow = !phaseLayout.positions[idx + 1] || phaseLayout.positions[idx + 1].row !== row;
                const hasHandoffs = phase.handoffs && phase.handoffs.length > 0;

                return (
                  <div
                    key={phase.name}
                    className="phase-position-wrapper"
                    style={{
                      position: 'absolute',
                      left: x,
                      top: y,
                      width: width,
                    }}
                  >
                    {hasExecutionData ? (
                      <PhaseColumn
                        phase={phase}
                        index={idx}
                        result={phaseResults[phase.name]}
                        activeSoundingsSet={activeSoundings[phase.name]}
                        isLast={isLastInRow}
                        hasHandoffs={hasHandoffs}
                        isExpanded={isPhaseExpanded(phase.name)}
                        onToggleExpand={() => togglePhaseExpanded(phase.name)}
                      />
                    ) : (
                      <GhostPhaseColumn
                        phase={phase}
                        index={idx}
                        allPhases={phases}
                        isLast={isLastInRow}
                        hasHandoffs={hasHandoffs}
                      />
                    )}
                  </div>
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
function PhaseColumn({ phase, index, result, activeSoundingsSet, isLast, hasHandoffs, isExpanded, onToggleExpand }) {
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
                  onClick={(e) => handleGhostClick(e, i)}
                  title={`Sounding ${i}${isWinner ? ' (winner)' : ''}`}
                >
                  {/* Compact single-row header with all info */}
                  <div className="ghost-header">
                    <span className="ghost-index">S{i}</span>
                    {isWinner && <Icon icon="mdi:crown" width="12" className="crown" />}
                    {isActive && <Icon icon="mdi:loading" width="10" className="spinning" />}
                    {isCompleted && !isWinner && <Icon icon="mdi:check" width="10" />}
                    {/* Inline stats */}
                    {sounding?.turnCount > 0 && (
                      <span className="ghost-stat">
                        <Icon icon="mdi:message-reply" width="10" />
                        {sounding.turnCount}
                      </span>
                    )}
                    {sounding?.cost > 0 && (
                      <span className="ghost-stat">${sounding.cost.toFixed(3)}</span>
                    )}
                  </div>

                  {/* Output preview - only show if has output */}
                  {sounding?.output && (
                    <div className={`ghost-output ${isSelected ? 'expanded' : ''}`}>
                      <pre>{typeof sounding.output === 'string'
                        ? sounding.output.slice(0, isSelected ? 500 : 60) + (sounding.output.length > (isSelected ? 500 : 60) ? '...' : '')
                        : JSON.stringify(sounding.output, null, 2).slice(0, isSelected ? 500 : 60)
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
 * RowConnectors - Visual connectors between rows when timeline wraps
 *
 * Only shows for SEQUENTIAL phases (no handoffs) that wrap to a new row.
 * Phases with handoffs are handled by HandoffArrows instead.
 */
function RowConnectors({ phaseLayout, phases }) {
  const { positions, totalRows } = phaseLayout;

  if (totalRows <= 1) return null;

  // Find row transitions - only for sequential phases WITHOUT handoffs
  const transitions = [];
  for (let i = 0; i < positions.length - 1; i++) {
    const currentPhase = phases[i];
    const hasHandoffs = currentPhase?.handoffs && currentPhase.handoffs.length > 0;

    // Only show row connector for sequential phases (no handoffs)
    if (positions[i].row !== positions[i + 1].row && !hasHandoffs) {
      transitions.push({
        from: positions[i],
        to: positions[i + 1],
        fromIdx: i,
        toIdx: i + 1,
      });
    }
  }

  if (transitions.length === 0) return null;

  return (
    <svg
      className="row-connectors-svg"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    >
      <defs>
        <marker
          id="arrow-row"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--ocean-primary)" />
        </marker>
        <marker
          id="arrow-row-ghost"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--storm-cloud)" />
        </marker>
      </defs>
      {transitions.map((trans, idx) => {
        const fromX = trans.from.x + trans.from.width;
        const fromY = trans.from.y + PHASE_HEADER_HEIGHT + 40;
        const toX = trans.to.x;
        const toY = trans.to.y + PHASE_HEADER_HEIGHT + 40;

        // "Carriage return" style path:
        // 1. Exit right edge of last phase on row 1
        // 2. Go down to below row 1 (accounting for soundings)
        // 3. Go left to the left margin area
        // 4. Go down to row 2
        // 5. Enter first phase on row 2
        const r = 12; // Consistent curve radius for all corners
        const wrapMargin = 20; // Position in the LEFT_MARGIN area (left of phases)
        // Use the actual row height to position the connector below any soundings
        const fromRowHeight = phaseLayout.rowHeights?.[trans.from.row] || PHASE_BASE_HEIGHT;
        const rowBottomY = trans.from.y + fromRowHeight + 20; // Just below the row (including soundings)

        // All curves use the same radius for consistency
        const path = `
          M ${fromX} ${fromY}
          L ${fromX + r} ${fromY}
          A ${r} ${r} 0 0 1 ${fromX + r + r} ${fromY + r}
          L ${fromX + r + r} ${rowBottomY - r}
          A ${r} ${r} 0 0 1 ${fromX + r} ${rowBottomY}
          L ${wrapMargin + r} ${rowBottomY}
          A ${r} ${r} 0 0 0 ${wrapMargin} ${rowBottomY + r}
          L ${wrapMargin} ${toY - r}
          A ${r} ${r} 0 0 0 ${wrapMargin + r} ${toY}
          L ${toX} ${toY}
        `;

        return (
          <path
            key={idx}
            d={path}
            fill="none"
            stroke="var(--ocean-secondary)"
            strokeWidth="2"
            strokeDasharray="6,4"
            opacity="0.5"
            markerEnd="url(#arrow-row)"
          />
        );
      })}
    </svg>
  );
}

/**
 * HandoffArrows - SVG overlay showing routing between phases
 *
 * Draws arrows from phases to their handoff targets.
 * Ghost mode: dashed lines to all possible targets
 * Realized mode: solid line to executed target, dashed for others
 */
function HandoffArrows({ phases, phaseResults, lastExecutedHandoffs, sessionId, phaseLayout }) {
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

  const { positions, maxRowWidth, totalHeight } = phaseLayout;

  // Get position info for a phase by index
  const getPhasePos = (idx) => positions[idx] || { x: 0, y: 0, width: PHASE_COLUMN_WIDTH };

  if (connections.length === 0) return null;

  const svgWidth = maxRowWidth || 800;
  const svgHeight = totalHeight || 300;

  // Calculate path for a connection (handles cross-row connections)
  const getPath = (sourceIdx, targetIdx) => {
    const sourcePos = getPhasePos(sourceIdx);
    const targetPos = getPhasePos(targetIdx);

    const sourceX = sourcePos.x + sourcePos.width;
    const sourceY = sourcePos.y + PHASE_HEADER_HEIGHT + 40;
    const targetX = targetPos.x;
    const targetY = targetPos.y + PHASE_HEADER_HEIGHT + 40;

    const sameRow = sourcePos.row === targetPos.row;
    const distance = targetIdx - sourceIdx;

    if (sameRow) {
      if (distance === 1) {
        // Adjacent on same row: simple horizontal line
        return `M ${sourceX} ${sourceY} L ${targetX} ${targetY}`;
      } else if (distance > 1) {
        // Forward skip on same row: curve above
        const midX = (sourceX + targetX) / 2;
        const curveHeight = Math.min(30 + distance * 15, 80);
        return `M ${sourceX} ${sourceY} Q ${midX} ${sourceY - curveHeight} ${targetX} ${targetY}`;
      } else {
        // Backward on same row: curve below
        const midX = (sourceX + targetX) / 2;
        const curveHeight = Math.min(30 + Math.abs(distance) * 15, 80);
        return `M ${sourceX} ${sourceY} Q ${midX} ${sourceY + curveHeight} ${targetX} ${targetY}`;
      }
    } else {
      // Cross-row connection: use a more complex path
      const midY = (sourceY + targetY) / 2;

      if (targetPos.row > sourcePos.row) {
        // Going to a lower row
        if (targetX >= sourceX) {
          // Target is to the right or same column
          return `M ${sourceX} ${sourceY}
                  Q ${sourceX + 40} ${sourceY} ${sourceX + 40} ${sourceY + 40}
                  L ${sourceX + 40} ${midY}
                  Q ${sourceX + 40} ${targetY} ${targetX} ${targetY}`;
        } else {
          // Target is to the left
          return `M ${sourceX} ${sourceY}
                  Q ${sourceX + 40} ${sourceY} ${sourceX + 40} ${sourceY + 40}
                  L ${sourceX + 40} ${midY}
                  L ${targetX - 40} ${midY}
                  Q ${targetX - 40} ${targetY} ${targetX} ${targetY}`;
        }
      } else {
        // Going to an upper row (backward jump)
        return `M ${sourceX} ${sourceY}
                Q ${sourceX + 60} ${sourceY} ${sourceX + 60} ${sourceY - 40}
                L ${sourceX + 60} ${midY}
                L ${targetX - 40} ${midY}
                Q ${targetX - 40} ${targetY} ${targetX} ${targetY}`;
      }
    }
  };

  // Calculate label position
  const getLabelPos = (sourceIdx, targetIdx) => {
    const sourcePos = getPhasePos(sourceIdx);
    const targetPos = getPhasePos(targetIdx);

    const sourceX = sourcePos.x + sourcePos.width;
    const sourceY = sourcePos.y + PHASE_HEADER_HEIGHT + 40;
    const targetX = targetPos.x;
    const targetY = targetPos.y + PHASE_HEADER_HEIGHT + 40;

    const sameRow = sourcePos.row === targetPos.row;
    const distance = targetIdx - sourceIdx;

    if (sameRow) {
      const midX = (sourceX + targetX) / 2;
      if (distance === 1) {
        return { x: midX, y: sourceY - 12 };
      } else if (distance > 1) {
        const curveHeight = Math.min(30 + distance * 15, 80);
        return { x: midX, y: sourceY - curveHeight - 8 };
      } else {
        const curveHeight = Math.min(30 + Math.abs(distance) * 15, 80);
        return { x: midX, y: sourceY + curveHeight + 14 };
      }
    } else {
      // Cross-row: place label at midpoint
      const midX = (sourceX + targetX) / 2;
      const midY = (sourceY + targetY) / 2;
      return { x: Math.max(midX, sourceX + 60), y: midY };
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
function GhostPhaseColumn({ phase, index, allPhases, isLast, hasHandoffs }) {
  const soundingsConfig = phase.soundings;
  const hasSoundings = soundingsConfig?.factor > 1;
  const soundingsCount = soundingsConfig?.factor || 1;
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
