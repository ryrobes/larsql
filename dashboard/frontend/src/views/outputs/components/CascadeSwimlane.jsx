import React from 'react';
import { Icon } from '@iconify/react';
import CellTile from './CellTile';
import CellGroup from './CellGroup';
import LinkedScrollGrid from './LinkedScrollGrid';
import './CascadeSwimlane.css';

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

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
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
 * CascadeSwimlane - A single cascade row with collapse/expand
 *
 * Collapsed: Shows most recent run as horizontal filmstrip
 * Expanded: Shows all runs in LinkedScrollGrid with synced scroll
 */
/**
 * Group cells by cell_name, preserving order of first occurrence
 * Returns array of { cell_name, cells: [...], cell_index }
 */
const groupCellsByName = (cells) => {
  if (!cells || cells.length === 0) return [];

  const groups = [];
  const groupMap = new Map();

  for (const cell of cells) {
    const name = cell.cell_name;
    if (groupMap.has(name)) {
      groupMap.get(name).cells.push(cell);
    } else {
      const group = {
        cell_name: name,
        cells: [cell],
        cell_index: groups.length, // Order of first occurrence
      };
      groups.push(group);
      groupMap.set(name, group);
    }
  }

  return groups;
};

const CascadeSwimlane = ({
  cascade,
  isExpanded,
  expandedData,
  expandedLoading,
  onToggleExpand,
  onCellClick,
}) => {
  const { cascade_id, run_count, runs, total_cost } = cascade;
  const latestRun = runs && runs.length > 0 ? runs[0] : null;

  // Group cells by name for the latest run
  const cellGroups = latestRun ? groupCellsByName(latestRun.cells) : [];

  return (
    <div className={`cascade-swimlane ${isExpanded ? 'expanded' : ''}`}>
      {/* Cascade Header */}
      <div className="swimlane-header" onClick={onToggleExpand}>
        <div className="swimlane-header-left">
          <Icon
            icon={isExpanded ? "mdi:chevron-down" : "mdi:chevron-right"}
            width="18"
            className="swimlane-chevron"
          />
          <Icon icon="mdi:sitemap" width="16" className="swimlane-icon" />
          <span className="swimlane-title">{cascade_id}</span>
          <span className="swimlane-run-count">{run_count} runs</span>
        </div>
        <div className="swimlane-header-right">
          <span className="swimlane-cost">{formatCost(total_cost)}</span>
        </div>
      </div>

      {/* Content - Collapsed or Expanded */}
      <div className="swimlane-content">
        {isExpanded ? (
          // Expanded: LinkedScrollGrid
          <div className="swimlane-expanded">
            {expandedLoading ? (
              <div className="swimlane-loading">
                <Icon icon="mdi:loading" className="spinning" width="20" />
                <span>Loading runs...</span>
              </div>
            ) : expandedData ? (
              <LinkedScrollGrid
                cellNames={expandedData.cell_names || []}
                runs={expandedData.runs || []}
                onCellClick={onCellClick}
              />
            ) : null}
          </div>
        ) : (
          // Collapsed: Single run filmstrip
          <div className="swimlane-collapsed">
            {latestRun ? (
              <>
                <div className="swimlane-run-meta">
                  <span className="run-session">{latestRun.session_id}</span>
                  <span className="run-time">{formatTimeAgo(latestRun.timestamp)}</span>
                </div>
                <div className="swimlane-filmstrip">
                  {cellGroups.map((group, idx) => {
                    const hasMultiple = group.cells.length > 1;

                    return (
                      <React.Fragment key={group.cell_name}>
                        {hasMultiple ? (
                          // Multiple outputs: show as attached tiles
                          <CellGroup
                            cellName={group.cell_name}
                            cellIndex={group.cell_index}
                            cells={group.cells}
                            onCellClick={(messageId) => onCellClick(messageId)}
                          />
                        ) : (
                          // Single output: use regular tile
                          <CellTile
                            cell={{ ...group.cells[0], cell_index: group.cell_index }}
                            onClick={() => onCellClick(group.cells[0].message_id)}
                          />
                        )}
                        {idx < cellGroups.length - 1 && (
                          <div className="filmstrip-arrow">
                            <Icon icon="mdi:arrow-right" width="14" />
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
                {/* Stack indicator */}
                {run_count > 1 && (
                  <div className="stack-indicator" title={`${run_count} runs total`}>
                    <div className="stack-layer" />
                    <div className="stack-layer" />
                  </div>
                )}
              </>
            ) : (
              <div className="swimlane-empty">No runs</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default CascadeSwimlane;
