import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import Button from '../../../components/Button/Button';
import Badge from '../../../components/Badge/Badge';
import './SimpleSidebar.css';

/**
 * SimpleSidebar - Rich orchestration sidebar for ExploreView
 *
 * Now displays:
 * - Status badge with session state
 * - Quick stats (messages, tokens, cost)
 * - Live activity feed (recent tool calls)
 * - Cell progress timeline
 * - Token breakdown (in/out)
 * - Model usage distribution
 * - Tool activity counts
 * - Analytics insights (outliers, performance)
 * - Child sessions (sub-cascades)
 * - Action buttons
 */
const SimpleSidebar = ({
  sessionId,
  cascadeId,
  orchestrationState,
  totalCost,
  sessionStatus,
  toolCounts = {},
  // NEW: Rich analytics
  sessionStats = {},
  cellAnalytics = {},
  cascadeAnalytics = null,
  childSessions = [],
  onEnd,
  onNewCascade
}) => {
  // Status config
  const sessionStatusMap = {
    running: { color: 'cyan', icon: 'mdi:play-circle', label: 'Running' },
    blocked: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Waiting' },
    completed: { color: 'green', icon: 'mdi:check-circle', label: 'Complete' },
    cancelled: { color: 'gray', icon: 'mdi:cancel', label: 'Cancelled' },
    error: { color: 'red', icon: 'mdi:alert-circle', label: 'Error' },
    orphaned: { color: 'orange', icon: 'mdi:ghost', label: 'Orphaned' },
  };

  const displayStatus = sessionStatusMap[sessionStatus] || { color: 'gray', icon: 'mdi:circle', label: 'Idle' };
  const isActive = sessionStatus === 'running' || sessionStatus === 'blocked';

  // Derive cell timeline from cellAnalytics
  const cellTimeline = useMemo(() => {
    if (!cellAnalytics || Object.keys(cellAnalytics).length === 0) return [];

    return Object.entries(cellAnalytics)
      .map(([name, data]) => ({
        name,
        cost: data.cell_cost || 0,
        duration: data.cell_duration_ms || 0,
        costPct: data.cell_cost_pct || 0,
        durationPct: data.cell_duration_pct || 0,
        isCostOutlier: data.is_cost_outlier,
        isDurationOutlier: data.is_duration_outlier,
      }))
      .sort((a, b) => b.costPct - a.costPct); // Sort by cost contribution
  }, [cellAnalytics]);

  // Format duration helper
  const formatDuration = (ms) => {
    if (!ms || ms < 1000) return `${Math.round(ms || 0)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  // Format token count helper
  const formatTokens = (count) => {
    if (!count) return '0';
    if (count < 1000) return String(count);
    if (count < 1000000) return `${(count / 1000).toFixed(1)}k`;
    return `${(count / 1000000).toFixed(2)}M`;
  };

  // Calculate elapsed time
  const elapsedTime = useMemo(() => {
    if (!sessionStats.startTime) return null;
    const start = new Date(sessionStats.startTime);
    const end = sessionStats.lastActivityTime ? new Date(sessionStats.lastActivityTime) : new Date();
    return end - start;
  }, [sessionStats.startTime, sessionStats.lastActivityTime]);

  // Get activity icon
  const getActivityIcon = (type) => {
    switch (type) {
      case 'tool_call': return 'mdi:arrow-right-bold';
      case 'tool_result': return 'mdi:check';
      case 'checkpoint': return 'mdi:checkbox-marked-circle';
      default: return 'mdi:circle';
    }
  };

  // Get activity color
  const getActivityColor = (type) => {
    switch (type) {
      case 'tool_call': return '#60a5fa';
      case 'tool_result': return '#34d399';
      case 'checkpoint': return '#fbbf24';
      default: return '#94a3b8';
    }
  };

  return (
    <div className="simple-sidebar">
      {/* Header: Status + Cascade */}
      <div className="sidebar-header">
        <div className="sidebar-status">
          <Badge
            variant="status"
            color={displayStatus.color}
            icon={displayStatus.icon}
            pulse={isActive}
            size="sm"
          >
            {displayStatus.label}
          </Badge>
        </div>
        <div className="cascade-name">{cascadeId || 'Cascade'}</div>
      </div>

      {/* Session ID (compact) */}
      <div className="session-id-row">
        <Icon icon="mdi:identifier" width="12" />
        <span title={sessionId}>{sessionId ? sessionId.slice(0, 20) + (sessionId.length > 20 ? '...' : '') : '-'}</span>
      </div>

      {/* Quick Stats Grid */}
      <div className="stats-grid">
        <div className="stat-item stat-cost">
          <div className="stat-value">${(totalCost || 0).toFixed(4)}</div>
          <div className="stat-label">Cost</div>
        </div>
        <div className="stat-item stat-messages">
          <div className="stat-value">{sessionStats.messageCount || 0}</div>
          <div className="stat-label">Messages</div>
        </div>
        <div className="stat-item stat-tokens">
          <div className="stat-value">{formatTokens((sessionStats.tokensIn || 0) + (sessionStats.tokensOut || 0))}</div>
          <div className="stat-label">Tokens</div>
        </div>
        <div className="stat-item stat-time">
          <div className="stat-value">{elapsedTime ? formatDuration(elapsedTime) : '-'}</div>
          <div className="stat-label">Elapsed</div>
        </div>
      </div>

      {/* Current Execution Info */}
      {orchestrationState.currentCell && (
        <div className="current-execution">
          <div className="exec-header">
            <Icon icon="mdi:play" width="12" />
            <span>Executing</span>
          </div>
          <div className="exec-cell">{orchestrationState.currentCell}</div>
          {orchestrationState.currentModel && (
            <div className="exec-model">
              {orchestrationState.currentModel.split('/').pop()}
            </div>
          )}
        </div>
      )}

      {/* Live Activity Feed */}
      {sessionStats.recentActivity && sessionStats.recentActivity.length > 0 && (
        <div className="activity-feed">
          <div className="section-header">
            <Icon icon="mdi:pulse" width="14" />
            <span>Activity</span>
          </div>
          <div className="activity-list">
            {sessionStats.recentActivity.slice(-5).reverse().map((activity, idx) => (
              <div key={idx} className="activity-item">
                <Icon
                  icon={getActivityIcon(activity.type)}
                  width="12"
                  style={{ color: getActivityColor(activity.type) }}
                />
                <span className="activity-text">
                  {activity.type === 'checkpoint' ? 'Checkpoint' : activity.tool}
                </span>
                {activity.cell && (
                  <span className="activity-cell">@{activity.cell}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Token Breakdown */}
      {(sessionStats.tokensIn > 0 || sessionStats.tokensOut > 0) && (
        <div className="token-breakdown">
          <div className="section-header">
            <Icon icon="mdi:counter" width="14" />
            <span>Tokens</span>
          </div>
          <div className="token-bar-container">
            <div
              className="token-bar token-bar-in"
              style={{
                width: `${(sessionStats.tokensIn / Math.max(sessionStats.tokensIn + sessionStats.tokensOut, 1)) * 100}%`
              }}
            />
            <div
              className="token-bar token-bar-out"
              style={{
                width: `${(sessionStats.tokensOut / Math.max(sessionStats.tokensIn + sessionStats.tokensOut, 1)) * 100}%`
              }}
            />
          </div>
          <div className="token-labels">
            <span className="token-in">{formatTokens(sessionStats.tokensIn)} in</span>
            <span className="token-out">{formatTokens(sessionStats.tokensOut)} out</span>
          </div>
        </div>
      )}

      {/* Model Usage with Cost Bars */}
      {sessionStats.modelUsage && Object.keys(sessionStats.modelUsage).length > 0 && (
        <div className="model-usage">
          <div className="section-header">
            <Icon icon="mdi:brain" width="14" />
            <span>Models</span>
            {sessionStats.modelCosts && Object.keys(sessionStats.modelCosts).length > 0 && (
              <span className="section-total">
                ${Object.values(sessionStats.modelCosts).reduce((a, b) => a + b, 0).toFixed(4)}
              </span>
            )}
          </div>
          <div className="model-list">
            {(() => {
              // Sort by cost (if available) or by count
              const modelCosts = sessionStats.modelCosts || {};
              const maxCost = Math.max(...Object.values(modelCosts), 0.0001);

              return Object.entries(sessionStats.modelUsage)
                .sort((a, b) => (modelCosts[b[0]] || 0) - (modelCosts[a[0]] || 0))
                .slice(0, 4)
                .map(([model, count]) => {
                  const cost = modelCosts[model] || 0;
                  const barWidth = (cost / maxCost) * 100;

                  return (
                    <div key={model} className="model-item">
                      <div className="model-info">
                        <span className="model-name" title={model}>{model}</span>
                        <span className="model-stats">
                          <span className="model-count">{count}×</span>
                          {cost > 0 && <span className="model-cost">${cost.toFixed(4)}</span>}
                        </span>
                      </div>
                      {cost > 0 && (
                        <div className="model-bar-container">
                          <div className="model-bar" style={{ width: `${barWidth}%` }} />
                        </div>
                      )}
                    </div>
                  );
                });
            })()}
          </div>
        </div>
      )}

      {/* Tool Counts */}
      {Object.keys(toolCounts).length > 0 && (
        <div className="tool-activity">
          <div className="section-header">
            <Icon icon="mdi:hammer-wrench" width="14" />
            <span>Tools</span>
            <span className="section-total">
              {Object.values(toolCounts).reduce((a, b) => a + b, 0)}
            </span>
          </div>
          <div className="tool-list">
            {Object.entries(toolCounts)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 6)
              .map(([tool, count]) => {
                const maxCount = Math.max(...Object.values(toolCounts));
                const barWidth = (count / maxCount) * 100;
                return (
                  <div key={tool} className="tool-item">
                    <span className="tool-name">{tool}</span>
                    <div className="tool-bar-container">
                      <div className="tool-bar" style={{ width: `${barWidth}%` }} />
                    </div>
                    <span className="tool-count">{count}</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* Cell Progress */}
      {cellTimeline.length > 0 && (
        <div className="cell-progress">
          <div className="section-header">
            <Icon icon="mdi:chart-timeline-variant" width="14" />
            <span>Cells</span>
          </div>
          <div className="cell-list">
            {cellTimeline.slice(0, 5).map((cell) => (
              <div
                key={cell.name}
                className={`cell-item ${cell.isCostOutlier ? 'cost-outlier' : ''} ${cell.isDurationOutlier ? 'duration-outlier' : ''}`}
              >
                <div className="cell-header">
                  <span className="cell-name">{cell.name}</span>
                  {(cell.isCostOutlier || cell.isDurationOutlier) && (
                    <Icon icon="mdi:alert" width="12" className="outlier-icon" />
                  )}
                </div>
                <div className="cell-metrics">
                  <span className="cell-cost">${cell.cost.toFixed(4)}</span>
                  <span className="cell-duration">{formatDuration(cell.duration)}</span>
                </div>
                <div className="cell-bar-container">
                  <div
                    className="cell-bar"
                    style={{ width: `${cell.costPct}%` }}
                    title={`${cell.costPct.toFixed(1)}% of cost`}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Analytics Insights */}
      {cascadeAnalytics && (cascadeAnalytics.is_cost_outlier || cascadeAnalytics.is_duration_outlier) && (
        <div className="analytics-insights">
          <div className="section-header">
            <Icon icon="mdi:lightbulb-on" width="14" />
            <span>Insights</span>
          </div>
          <div className="insights-list">
            {cascadeAnalytics.is_cost_outlier && (
              <div className="insight-item insight-warning">
                <Icon icon="mdi:currency-usd" width="12" />
                <span>Cost {cascadeAnalytics.cost_z_score > 0 ? 'above' : 'below'} average</span>
              </div>
            )}
            {cascadeAnalytics.is_duration_outlier && (
              <div className="insight-item insight-warning">
                <Icon icon="mdi:clock-alert" width="12" />
                <span>Duration {cascadeAnalytics.duration_z_score > 0 ? 'above' : 'below'} average</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Child Sessions */}
      {childSessions.length > 0 && (
        <div className="child-sessions">
          <div className="section-header">
            <Icon icon="mdi:source-branch" width="14" />
            <span>Sub-cascades</span>
            <span className="section-total">{childSessions.length}</span>
          </div>
          <div className="child-list">
            {childSessions.slice(0, 3).map((child) => (
              <div key={child.session_id} className="child-item">
                <span className="child-cell">{child.parent_cell || 'spawn'}</span>
                <span className="child-id">{child.session_id.slice(0, 12)}...</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Message Type Distribution (compact) */}
      {sessionStats.roleCounts && Object.keys(sessionStats.roleCounts).length > 0 && (
        <div className="role-distribution">
          <div className="section-header">
            <Icon icon="mdi:chart-pie" width="14" />
            <span>Messages</span>
          </div>
          <div className="role-chips">
            {Object.entries(sessionStats.roleCounts)
              .filter(([role]) => ['assistant', 'user', 'tool'].includes(role))
              .map(([role, count]) => (
                <span key={role} className={`role-chip role-${role}`}>
                  {role}: {count}
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Prominent Status Indicator */}
      {sessionStatus && (
        <div className={`status-indicator status-${sessionStatus}`}>
          <div className="status-indicator-content">
            {sessionStatus === 'running' && (
              <>
                <div className="status-spinner">
                  <Icon icon="mdi:loading" width="24" className="spinning" />
                </div>
                <div className="status-text">
                  <span className="status-label">Working</span>
                  <span className="status-detail">
                    {orchestrationState.currentCell || 'Processing...'}
                  </span>
                </div>
              </>
            )}
            {sessionStatus === 'blocked' && (
              <>
                <div className="status-pulse">
                  <Icon icon="mdi:hand-back-right" width="24" />
                </div>
                <div className="status-text">
                  <span className="status-label">Waiting for Input</span>
                  <span className="status-detail">
                    {orchestrationState.currentCell || 'Human response needed'}
                  </span>
                </div>
              </>
            )}
            {sessionStatus === 'completed' && (
              <>
                <div className="status-check">
                  <Icon icon="mdi:check-circle" width="24" />
                </div>
                <div className="status-text">
                  <span className="status-label">Complete</span>
                  <span className="status-detail">Cascade finished successfully</span>
                </div>
              </>
            )}
            {sessionStatus === 'error' && (
              <>
                <div className="status-error">
                  <Icon icon="mdi:alert-circle" width="24" />
                </div>
                <div className="status-text">
                  <span className="status-label">Error</span>
                  <span className="status-detail">Cascade encountered an error</span>
                </div>
              </>
            )}
            {sessionStatus === 'cancelled' && (
              <>
                <div className="status-cancelled">
                  <Icon icon="mdi:cancel" width="24" />
                </div>
                <div className="status-text">
                  <span className="status-label">Cancelled</span>
                  <span className="status-detail">Cascade was stopped</span>
                </div>
              </>
            )}
            {sessionStatus === 'orphaned' && (
              <>
                <div className="status-orphaned">
                  <Icon icon="mdi:ghost" width="24" />
                </div>
                <div className="status-text">
                  <span className="status-label">Orphaned</span>
                  <span className="status-detail">Session lost connection</span>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="sidebar-actions">
        {sessionStatus && !['completed', 'cancelled', 'error', 'orphaned'].includes(sessionStatus) && onEnd && (
          <Button
            variant="danger"
            size="sm"
            icon="mdi:stop-circle"
            onClick={onEnd}
          >
            End
          </Button>
        )}
        {['completed', 'cancelled', 'error', 'orphaned'].includes(sessionStatus) && onNewCascade && (
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
