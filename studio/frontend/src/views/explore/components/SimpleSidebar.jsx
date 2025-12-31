import React from 'react';
import { Icon } from '@iconify/react';
import Button from '../../../components/Button/Button';
import Badge from '../../../components/Badge/Badge';
import './SimpleSidebar.css';

/**
 * SimpleSidebar - Lightweight orchestration sidebar for ExploreView MVP
 *
 * Displays:
 * - Status badge (thinking, tool_running, waiting_human, idle)
 * - Total cost (prominent display)
 * - Session info (cascade, cell, model)
 * - END button (if running)
 *
 * Extension points:
 * - Cell timeline (commented out for Iteration 2)
 * - Research tree (commented out for Iteration 2)
 * - Previous sessions (commented out for Iteration 2)
 */
const SimpleSidebar = ({
  sessionId,
  cascadeId,
  orchestrationState,
  totalCost,
  sessionStatus,
  toolCounts = {},
  onEnd,
  onNewCascade
}) => {
  const statusConfig = {
    thinking: { color: 'cyan', icon: 'mdi:brain', label: 'Thinking' },
    tool_running: { color: 'green', icon: 'mdi:hammer-wrench', label: 'Using Tools' },
    waiting_human: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Waiting' },
    idle: { color: 'gray', icon: 'mdi:circle', label: 'Idle' },
  };

  // Map sessionStatus (from DB) to display
  const sessionStatusMap = {
    running: { color: 'cyan', icon: 'mdi:play-circle', label: 'Running' },
    blocked: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Blocked' },
    completed: { color: 'green', icon: 'mdi:check-circle', label: 'Complete' },
    cancelled: { color: 'gray', icon: 'mdi:cancel', label: 'Cancelled' },
    error: { color: 'red', icon: 'mdi:alert-circle', label: 'Error' },
  };

  // Use sessionStatus (authoritative from DB) if available, otherwise orchestrationState
  const displayStatus = sessionStatus && sessionStatusMap[sessionStatus]
    ? sessionStatusMap[sessionStatus]
    : statusConfig[orchestrationState.status] || statusConfig.idle;

  return (
    <div className="simple-sidebar">
      {/* Header: Cascade name + status badges */}
      <div className="sidebar-header">
        <div className="cascade-name">{cascadeId || 'Unknown Cascade'}</div>
        <div className="status-badges">
          <Badge
            variant="status"
            color={displayStatus.color}
            icon={displayStatus.icon}
            pulse={sessionStatus === 'running' || sessionStatus === 'blocked'}
            size="sm"
          >
            {displayStatus.label}
          </Badge>
        </div>
      </div>

      {/* Session ID */}
      <div className="session-id-compact">
        <Icon icon="mdi:identifier" width="12" />
        <span>{sessionId || '-'}</span>
      </div>

      {/* Cost Display - Prominent */}
      <div className="cost-section">
        <div className="cost-value">${(totalCost || 0).toFixed(4)}</div>
        <div className="cost-label">Total Cost</div>
      </div>

      {/* Execution Info - Compact grid */}
      <div className="execution-grid">
        <div className="exec-item">
          <div className="exec-label">Cell</div>
          <div className="exec-value">{orchestrationState.currentCell || '-'}</div>
        </div>
        <div className="exec-item">
          <div className="exec-label">Model</div>
          <div className="exec-value">
            {orchestrationState.currentModel?.split('/').pop()?.replace('claude-', '').replace('grok-', '') || '-'}
          </div>
        </div>
      </div>

      {/* Tool Counts - Live tracking */}
      {Object.keys(toolCounts).length > 0 && (
        <div className="tool-counts-section">
          <div className="section-label">
            <Icon icon="mdi:hammer-wrench" width="14" />
            <span>Tool Calls</span>
            <span className="total-count">
              {Object.values(toolCounts).reduce((a, b) => a + b, 0)}
            </span>
          </div>
          <div className="tool-counts-list">
            {Object.entries(toolCounts)
              .sort((a, b) => b[1] - a[1])  // Sort by count descending
              .map(([tool, count]) => (
                <div key={tool} className="tool-count-item">
                  <span className="tool-name">{tool}</span>
                  <span className="tool-count">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* EXTENSION POINT: Cell Timeline */}
      {/* {orchestrationState.cellHistory && (
        <div className="sidebar-section">
          <div className="sidebar-label">Recent Cells</div>
          <CellTimeline cells={orchestrationState.cellHistory} />
        </div>
      )} */}

      {/* EXTENSION POINT: Research Tree */}
      {/* <CompactResearchTree sessionId={sessionId} currentSessionId={sessionId} /> */}

      {/* EXTENSION POINT: Previous Sessions */}
      {/* <div className="sidebar-section">
        <div className="sidebar-label">Previous Sessions</div>
        <PreviousSessionsList cascadeId={cascadeId} />
      </div> */}

      {/* Actions */}
      <div className="sidebar-actions">
        {/* End button shows for: running, blocked, or any non-terminal state */}
        {sessionStatus && !['completed', 'cancelled', 'error'].includes(sessionStatus) && onEnd && (
          <Button
            variant="danger"
            size="sm"
            icon="mdi:stop-circle"
            onClick={onEnd}
          >
            End Cascade
          </Button>
        )}

        {/* New Cascade button for terminal states */}
        {(sessionStatus === 'completed' || sessionStatus === 'cancelled' || sessionStatus === 'error') && onNewCascade && (
          <Button
            variant="primary"
            size="sm"
            icon="mdi:plus-circle"
            onClick={onNewCascade}
          >
            New Cascade
          </Button>
        )}
      </div>

    </div>
  );
};

export default SimpleSidebar;
