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
 * - Session info (cascade, phase, model)
 * - END button (if running)
 *
 * Extension points:
 * - Phase timeline (commented out for Iteration 2)
 * - Research tree (commented out for Iteration 2)
 * - Previous sessions (commented out for Iteration 2)
 */
const SimpleSidebar = ({
  sessionId,
  cascadeId,
  orchestrationState,
  totalCost,
  sessionStatus,
  onEnd
}) => {
  const statusConfig = {
    thinking: { color: 'cyan', icon: 'mdi:brain', label: 'Thinking' },
    tool_running: { color: 'green', icon: 'mdi:hammer-wrench', label: 'Using Tools' },
    waiting_human: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Waiting' },
    idle: { color: 'gray', icon: 'mdi:circle', label: 'Idle' },
  };

  const currentStatus = statusConfig[orchestrationState.status] || statusConfig.idle;

  return (
    <div className="simple-sidebar">
      {/* Status Section */}
      <div className="sidebar-section">
        <div className="sidebar-label">Status</div>
        <div className="status-display">
          <Badge
            variant="status"
            color={currentStatus.color}
            icon={currentStatus.icon}
            pulse={sessionStatus === 'running'}
          >
            {currentStatus.label}
          </Badge>
        </div>
      </div>

      {/* Cost Section */}
      <div className="sidebar-section">
        <div className="sidebar-label">Total Cost</div>
        <div className="cost-display">
          ${(totalCost || 0).toFixed(4)}
        </div>
      </div>

      {/* Session Info */}
      <div className="sidebar-section">
        <div className="sidebar-label">Session</div>
        <div className="session-info">
          <div className="info-row">
            <span className="info-label">Cascade</span>
            <span className="info-value">{cascadeId || 'Unknown'}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Phase</span>
            <span className="info-value">{orchestrationState.currentPhase || '-'}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Model</span>
            <span className="info-value">
              {orchestrationState.currentModel?.split('/').pop() || '-'}
            </span>
          </div>
        </div>
      </div>

      {/* EXTENSION POINT: Phase Timeline */}
      {/* {orchestrationState.phaseHistory && (
        <div className="sidebar-section">
          <div className="sidebar-label">Recent Phases</div>
          <PhaseTimeline phases={orchestrationState.phaseHistory} />
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
      {sessionStatus === 'running' && onEnd && (
        <div className="sidebar-actions">
          <Button
            variant="danger"
            size="sm"
            icon="mdi:stop-circle"
            onClick={onEnd}
          >
            End Cascade
          </Button>
        </div>
      )}

      {/* Session ID (small, at bottom) */}
      <div className="sidebar-footer">
        <div className="session-id-label">Session ID</div>
        <div className="session-id-value">{sessionId || '-'}</div>
      </div>
    </div>
  );
};

export default SimpleSidebar;
