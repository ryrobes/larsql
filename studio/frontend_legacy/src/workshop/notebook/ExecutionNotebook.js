import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import { useExecutionSSE } from '../hooks/useExecutionSSE';
import './ExecutionNotebook.css';

// Constants for layout calculations
const CELL_COLUMN_WIDTH = 220;
const CELL_COLUMN_WIDTH_EXPANDED = 400;
const CELL_COLUMN_GAP = 60; // Horizontal gap between cells
const CELL_ROW_GAP = 60; // Minimum vertical gap between rows
const CELL_HEADER_HEIGHT = 44;
const CELL_BASE_HEIGHT = 140; // Base height of a cell column (compact stats row)
const CELL_EXPANDED_EXTRA = 200; // Extra height when cell output is expanded
const SOUNDING_BLOCK_HEIGHT = 85; // Height per sounding block (vertical stack)
const SOUNDING_DEPTH_PADDING = 30; // Extra padding for soundings area
const TIMELINE_PADDING = 16;
const LEFT_MARGIN = 50; // Space on left for row wrap connectors

/**
 * ExecutionNotebook - Real-time cascade execution visualization
 *
 * Shows cascade execution as a horizontal timeline of cell columns.
 * Each cell displays:
 * - Cell status (pending/running/completed/error)
 * - Turn count and cost accumulation
 * - Soundings progress with parallel indicators
 * - Live updates via SSE
 * - Handoff arrows showing routing between cells
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
    cellResults,
    activeSoundings,
    executionLog,
    clearExecution,
    lastExecutedHandoffs,
  } = useWorkshopStore();

  // Connect to SSE for real-time updates
  useExecutionSSE();

  // Track which cells are COLLAPSED (default is expanded to show output)
  const [collapsedCells, setCollapsedCells] = useState(new Set());

  const toggleCellExpanded = (cellName) => {
    setCollapsedCells((prev) => {
      const next = new Set(prev);
      if (next.has(cellName)) {
        next.delete(cellName); // Uncollapse = expand
      } else {
        next.add(cellName); // Collapse
      }
      return next;
    });
  };

  // Helper: is cell expanded? (default true unless collapsed)
  const isCellExpanded = (cellName) => !collapsedCells.has(cellName);

  // Track container width for row wrapping
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(800);

  // Get cells early so we can use them in layout calculation
  const cells = cascade.cells || [];

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

  // Calculate cell layout with row wrapping and dynamic row heights
  const cellLayout = useMemo(() => {
    const layout = [];
    let currentX = 0;
    let currentRow = 0;
    let maxRowWidth = 0;

    // Account for left margin in available width
    const availableWidth = containerWidth - LEFT_MARGIN;

    // Helper to calculate cell height including soundings and expansion
    const getCellHeight = (cell, isExpanded) => {
      let height = CELL_BASE_HEIGHT;

      // Add extra height if cell output is expanded
      if (isExpanded) {
        height += CELL_EXPANDED_EXTRA;
      }

      // Add height for soundings (vertical stack - each sounding adds height)
      const soundingsFactor = cell.candidates?.factor || 0;
      if (soundingsFactor > 1) {
        height += (soundingsFactor * SOUNDING_BLOCK_HEIGHT) + SOUNDING_DEPTH_PADDING;
      }

      return height;
    };

    // First pass: assign cells to rows
    const rowAssignments = [];
    cells.forEach((cell, idx) => {
      const isExpanded = isCellExpanded(cell.name);
      const width = isExpanded ? CELL_COLUMN_WIDTH_EXPANDED : CELL_COLUMN_WIDTH;
      const totalWidth = width + CELL_COLUMN_GAP;

      // Check if we need to wrap to next row
      if (currentX + width > availableWidth && idx > 0) {
        currentRow++;
        currentX = 0;
      }

      rowAssignments.push({
        cell,
        index: idx,
        row: currentRow,
        x: currentX + LEFT_MARGIN,
        width,
        isExpanded,
        height: getCellHeight(cell, isExpanded),
      });

      currentX += totalWidth;
      maxRowWidth = Math.max(maxRowWidth, currentX + LEFT_MARGIN);
    });

    // Second pass: calculate row heights (max height of cells in each row)
    const rowHeights = {};
    rowAssignments.forEach((item) => {
      const currentMax = rowHeights[item.row] || CELL_BASE_HEIGHT;
      rowHeights[item.row] = Math.max(currentMax, item.height);
    });

    // Third pass: calculate cumulative Y positions
    const rowYPositions = {};
    let cumulativeY = 0;
    const totalRows = currentRow + 1;
    for (let r = 0; r < totalRows; r++) {
      rowYPositions[r] = cumulativeY;
      cumulativeY += (rowHeights[r] || CELL_BASE_HEIGHT) + CELL_ROW_GAP;
    }

    // Final pass: assign Y positions to cells
    rowAssignments.forEach((item) => {
      layout.push({
        ...item,
        y: rowYPositions[item.row],
        rowHeight: rowHeights[item.row],
      });
    });

    const totalHeight = cumulativeY;

    return { positions: layout, totalRows, totalHeight, maxRowWidth, rowHeights, rowYPositions };
  }, [cells, collapsedCells, containerWidth, isCellExpanded]);

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
        {cells.length === 0 ? (
          <div className="notebook-empty">
            <Icon icon="mdi:chart-timeline-variant" width="64" />
            <h3>No Cells Yet</h3>
            <p>Add cells to your cascade to see the execution timeline</p>
          </div>
        ) : (
          <div className="timeline-scroll">
            <div
              className="timeline-track timeline-track-wrapped"
              style={{
                width: Math.max(cellLayout.maxRowWidth, containerWidth),
                height: cellLayout.totalHeight,
              }}
            >
              {/* Handoff arrows SVG overlay */}
              <HandoffArrows
                cells={cells}
                cellResults={cellResults}
                lastExecutedHandoffs={lastExecutedHandoffs}
                sessionId={sessionId}
                cellLayout={cellLayout}
              />

              {/* Row connectors for wrapped rows (only for sequential cells without handoffs) */}
              {cellLayout.totalRows > 1 && (
                <RowConnectors cellLayout={cellLayout} cells={cells} />
              )}

              {cellLayout.positions.map((pos, idx) => {
                const { cell, x, y, width, row } = pos;
                const hasExecutionData = sessionId && cellResults[cell.name];
                const isLastInRow = !cellLayout.positions[idx + 1] || cellLayout.positions[idx + 1].row !== row;
                const hasHandoffs = cell.handoffs && cell.handoffs.length > 0;

                return (
                  <div
                    key={cell.name}
                    className="cell-position-wrapper"
                    style={{
                      position: 'absolute',
                      left: x,
                      top: y,
                      width: width,
                    }}
                  >
                    {hasExecutionData ? (
                      <CellColumn
                        cell={cell}
                        index={idx}
                        result={cellResults[cell.name]}
                        activeSoundingsSet={activeSoundings[cell.name]}
                        isLast={isLastInRow}
                        hasHandoffs={hasHandoffs}
                        isExpanded={isCellExpanded(cell.name)}
                        onToggleExpand={() => toggleCellExpanded(cell.name)}
                      />
                    ) : (
                      <GhostCellColumn
                        cell={cell}
                        index={idx}
                        allCells={cells}
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
 * CellColumn - Single cell in the timeline with real-time updates
 *
 * When soundings are active, shows ghost blocks descending below the main cell
 * like nautical depth soundings. The winner "rises" back up to the main block.
 */
function CellColumn({ cell, index, result, activeSoundingsSet, isLast, hasHandoffs, isExpanded, onToggleExpand }) {
  const [selectedSounding, setSelectedSounding] = useState(null);
  const status = result?.status || 'pending';
  const soundingsConfig = cell.candidates;
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
    <div className="cell-column-wrapper">
      {/* Main Cell Block */}
      <div
        className={`cell-column status-${status} ${hasOutput ? 'has-output' : ''} ${isExpanded ? 'expanded' : ''} ${hasSoundings ? 'has-soundings' : ''}`}
        onClick={handleClick}
      >
        {/* Connector to next cell (only if no handoffs - handoffs use SVG arrows) */}
        {!isLast && !hasHandoffs && (
          <div className="column-connector">
            <div className="connector-line-h" />
            <Icon icon="mdi:chevron-right" width="16" className="connector-arrow-h" />
          </div>
        )}

        <div className="column-header">
          <span className="column-number">{index + 1}</span>
          <span className="column-name">{cell.name}</span>
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
          <div className="cell-output">
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

      {/* Ghost Sounding Blocks - Descend below the main cell */}
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
 * Only shows for SEQUENTIAL cells (no handoffs) that wrap to a new row.
 * Cells with handoffs are handled by HandoffArrows instead.
 */
function RowConnectors({ cellLayout, cells }) {
  const { positions, totalRows } = cellLayout;

  if (totalRows <= 1) return null;

  // Find row transitions - only for sequential cells WITHOUT handoffs
  const transitions = [];
  for (let i = 0; i < positions.length - 1; i++) {
    const currentCell = cells[i];
    const hasHandoffs = currentCell?.handoffs && currentCell.handoffs.length > 0;

    // Only show row connector for sequential cells (no handoffs)
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
        const fromY = trans.from.y + CELL_HEADER_HEIGHT + 40;
        const toX = trans.to.x;
        const toY = trans.to.y + CELL_HEADER_HEIGHT + 40;

        // "Carriage return" style path:
        // 1. Exit right edge of last cell on row 1
        // 2. Go down to below row 1 (accounting for soundings)
        // 3. Go left to the left margin area
        // 4. Go down to row 2
        // 5. Enter first cell on row 2
        const r = 12; // Consistent curve radius for all corners
        const wrapMargin = 20; // Position in the LEFT_MARGIN area (left of cells)
        // Use the actual row height to position the connector below any soundings
        const fromRowHeight = cellLayout.rowHeights?.[trans.from.row] || CELL_BASE_HEIGHT;
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
 * HandoffArrows - SVG overlay showing routing between cells
 *
 * Draws arrows from cells to their handoff targets.
 * Ghost mode: dashed lines to all possible targets
 * Realized mode: solid line to executed target, dashed for others
 */
function HandoffArrows({ cells, cellResults, lastExecutedHandoffs, sessionId, cellLayout }) {
  // Build list of all handoff connections
  const connections = useMemo(() => {
    const conns = [];

    cells.forEach((cell, sourceIdx) => {
      if (!cell.handoffs || cell.handoffs.length === 0) return;

      const isCellExecuted = sessionId && cellResults[cell.name]?.status === 'completed';
      const executedTarget = lastExecutedHandoffs?.[cell.name];

      cell.handoffs.forEach((handoff) => {
        const targetName = typeof handoff === 'string' ? handoff : handoff.target;
        const description = typeof handoff === 'object' ? handoff.description : null;
        const targetIdx = cells.findIndex((p) => p.name === targetName);

        if (targetIdx === -1) return; // Target not found

        // Get context info from source cell
        const contextInfo = cell.context?.from
          ? `ctx: ${cell.context.from.join(', ')}`
          : null;

        conns.push({
          sourceIdx,
          targetIdx,
          sourceName: cell.name,
          targetName,
          description,
          contextInfo,
          isExecuted: isCellExecuted && executedTarget === targetName,
          isGhost: !isCellExecuted,
        });
      });
    });

    return conns;
  }, [cells, cellResults, lastExecutedHandoffs, sessionId]);

  const { positions, maxRowWidth, totalHeight } = cellLayout;

  // Get position info for a cell by index
  const getCellPos = (idx) => positions[idx] || { x: 0, y: 0, width: CELL_COLUMN_WIDTH };

  if (connections.length === 0) return null;

  const svgWidth = maxRowWidth || 800;
  const svgHeight = totalHeight || 300;

  // Calculate path for a connection (handles cross-row connections)
  const getPath = (sourceIdx, targetIdx) => {
    const sourcePos = getCellPos(sourceIdx);
    const targetPos = getCellPos(targetIdx);

    const sourceX = sourcePos.x + sourcePos.width;
    const sourceY = sourcePos.y + CELL_HEADER_HEIGHT + 40;
    const targetX = targetPos.x;
    const targetY = targetPos.y + CELL_HEADER_HEIGHT + 40;

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
    const sourcePos = getCellPos(sourceIdx);
    const targetPos = getCellPos(targetIdx);

    const sourceX = sourcePos.x + sourcePos.width;
    const sourceY = sourcePos.y + CELL_HEADER_HEIGHT + 40;
    const targetX = targetPos.x;
    const targetY = targetPos.y + CELL_HEADER_HEIGHT + 40;

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
          // Not executed but cell was run (alternative path)
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
 * GhostCellColumn - Preview of a cell before execution
 *
 * Shows a ghost representation of what this cell will look like when run.
 * Includes ghost soundings lanes, handoff indicators, etc.
 */
function GhostCellColumn({ cell, index, allCells, isLast, hasHandoffs }) {
  const soundingsConfig = cell.candidates;
  const hasSoundings = soundingsConfig?.factor > 1;
  const soundingsCount = soundingsConfig?.factor || 1;
  const hasReforge = soundingsConfig?.reforge?.steps > 0;
  const mode = soundingsConfig?.mode || 'evaluate';

  return (
    <div className="cell-column-wrapper ghost-wrapper">
      {/* Main Ghost Cell Block */}
      <div className={`cell-column ghost-cell ${hasSoundings ? 'has-soundings' : ''}`}>
        {/* Connector to next cell (only if no handoffs - handoffs use SVG arrows) */}
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
          <span className="column-name">{cell.name}</span>
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
          {cell.model && (
            <div className="ghost-model" title={cell.model}>
              <Icon icon="mdi:brain" width="10" />
              {cell.model.split('/').pop()}
            </div>
          )}
          {cell.instructions && (
            <div className="ghost-instructions" title={cell.instructions}>
              <Icon icon="mdi:text" width="10" />
              <span>{cell.instructions.slice(0, 60)}{cell.instructions.length > 60 ? '...' : ''}</span>
            </div>
          )}
        </div>

        {/* Tackle preview */}
        {cell.traits && cell.traits.length > 0 && (
          <div className="ghost-tackle">
            <Icon icon="mdi:wrench" width="10" />
            <span>{cell.traits.length} tool{cell.traits.length !== 1 ? 's' : ''}</span>
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
          <span>{cell.handoffs.length} route{cell.handoffs.length !== 1 ? 's' : ''}</span>
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
      cell_start: 'mdi:play-circle',
      cell_complete: 'mdi:check-circle',
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
      cell_start: 'var(--ocean-primary)',
      cell_complete: 'var(--success-green)',
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
      case 'cell_start':
        return `Cell "${entry.cellName}" started${entry.soundingIndex !== null ? ` (sounding ${entry.soundingIndex})` : ''}`;
      case 'cell_complete':
        return `Cell "${entry.cellName}" completed`;
      case 'turn_start':
        return `Turn ${entry.turnNumber + 1} in "${entry.cellName}"`;
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
