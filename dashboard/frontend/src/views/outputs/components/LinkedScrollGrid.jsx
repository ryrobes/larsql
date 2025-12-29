import React, { useRef, useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import CellTile from './CellTile';
import CellGroup from './CellGroup';
import './LinkedScrollGrid.css';

/**
 * Format relative time
 */
const formatTimeAgo = (timestamp) => {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

/**
 * Format cost
 */
const formatCost = (cost) => {
  if (!cost || cost === 0) return '$0.00';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
};

/**
 * LinkedScrollGrid - Stacked runs with synchronized horizontal scroll
 *
 * All rows scroll together so cell columns stay aligned.
 */
const LinkedScrollGrid = ({ cellNames, runs, onCellClick, navigate }) => {
  const scrollContainerRef = useRef(null);
  const [scrollLeft, setScrollLeft] = useState(0);

  // Handle scroll - sync all rows
  const handleScroll = useCallback((e) => {
    setScrollLeft(e.target.scrollLeft);
  }, []);

  if (!runs || runs.length === 0) {
    return (
      <div className="linked-scroll-empty">
        <Icon icon="mdi:inbox-outline" width="24" />
        <span>No runs found</span>
      </div>
    );
  }

  return (
    <div className="linked-scroll-grid">
      {/* Column headers (cell names) */}
      <div className="linked-scroll-header">
        <div className="header-time-col">Time</div>
        <div
          className="header-cells-row"
          style={{ transform: `translateX(-${scrollLeft}px)` }}
        >
          {cellNames.map((name, idx) => (
            <div key={name} className="header-cell">
              <span className="header-cell-index">{idx + 1}</span>
              <span className="header-cell-name">{name}</span>
            </div>
          ))}
        </div>
        <div className="header-session-col">Session</div>
      </div>

      {/* Scrollable rows container */}
      <div
        className="linked-scroll-rows"
        ref={scrollContainerRef}
        onScroll={handleScroll}
      >
        {runs.map((run) => (
          <div key={run.session_id} className="linked-scroll-row">
            {/* Time column (fixed) */}
            <div className="row-time-col">
              <span className="row-time">{formatTimeAgo(run.timestamp)}</span>
              <span className="row-cost">{formatCost(run.cost)}</span>
            </div>

            {/* Cells (scrolls with container) */}
            <div className="row-cells">
              {cellNames.map((cellName, cellIdx) => {
                const cellOutputs = run.cells[cellName];
                if (!cellOutputs || cellOutputs.length === 0) {
                  return (
                    <div key={cellName} className="row-cell-empty">
                      <Icon icon="mdi:minus" width="14" />
                    </div>
                  );
                }

                const hasMultiple = cellOutputs.length > 1;

                return (
                  <div key={cellName} className="row-cell">
                    {hasMultiple ? (
                      // Multiple outputs: show as attached tiles
                      <CellGroup
                        cellName={cellName}
                        cellIndex={cellIdx}
                        cells={cellOutputs}
                        onCellClick={(messageId) => onCellClick(messageId)}
                      />
                    ) : (
                      // Single output: use compact tile
                      <CellTile
                        cell={cellOutputs[0]}
                        compact
                        onClick={() => onCellClick(cellOutputs[0].message_id)}
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Session ID column (fixed) */}
            <div className="row-session-col">
              <span
                className="row-session"
                onClick={() => navigate && navigate('studio', { session: run.session_id })}
                title={`Open ${run.session_id} in Studio`}
              >
                {run.session_id}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Scroll indicator */}
      <div className="linked-scroll-indicator">
        <Icon icon="mdi:gesture-swipe-horizontal" width="14" />
        <span>Scroll to compare cells across runs</span>
      </div>
    </div>
  );
};

export default LinkedScrollGrid;
