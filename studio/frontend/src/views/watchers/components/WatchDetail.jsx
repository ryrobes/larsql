import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import { ROUTES } from '../../../routes.helpers';
import './WatchDetail.css';

// Status configuration
const STATUS_CONFIG = {
  enabled: { icon: 'mdi:play-circle', color: '#34d399' },
  disabled: { icon: 'mdi:pause-circle', color: '#64748b' },
  error: { icon: 'mdi:alert-circle', color: '#f87171' },
};

// Action type colors
const ACTION_TYPE_COLORS = {
  cascade: '#a78bfa',
  signal: '#818cf8',
  sql: '#f59e0b',
  default: '#94a3b8',
};

// Execution status colors
const EXEC_STATUS_COLORS = {
  success: '#34d399',
  failed: '#f87171',
  running: '#fbbf24',
  skipped: '#64748b',
};

/**
 * Format duration in ms to human readable
 */
const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

/**
 * Format relative time
 */
const formatRelativeTime = (isoString) => {
  if (!isoString) return '-';
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now - date;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
};

/**
 * Extract cascade_id from action_spec path
 * e.g., "cascades/my_handler.yaml" -> "my_handler"
 */
const extractCascadeId = (actionSpec) => {
  if (!actionSpec) return null;
  // Remove path and extension
  const filename = actionSpec.split('/').pop();
  return filename?.replace(/\.(yaml|yml|json)$/i, '') || null;
};

/**
 * WatchDetail - Detail panel for a selected watch
 */
const WatchDetail = ({
  watch,
  detailData,
  loading,
  onClose,
  onToggle,
  onTrigger,
  onDelete,
}) => {
  const navigate = useNavigate();

  if (!watch) return null;

  const statusConfig = STATUS_CONFIG[watch.status] || STATUS_CONFIG.disabled;
  const actionColor = ACTION_TYPE_COLORS[watch.action_type] || ACTION_TYPE_COLORS.default;

  // Get stats from detail data
  const stats = detailData?.stats || {};
  const executions = detailData?.executions || [];
  const watchDetail = detailData?.watch || watch;

  // Calculate success rate bar width
  const successRate = stats.success_rate || 0;

  // Extract cascade_id for deep linking
  const cascadeId = watch.action_type === 'cascade' ? extractCascadeId(watch.action_spec) : null;

  // Handle navigation to session
  const handleNavigateToSession = (sessionId) => {
    if (cascadeId && sessionId) {
      navigate(ROUTES.studioWithSession(cascadeId, sessionId));
    }
  };

  return (
    <div className="watch-detail">
      {/* Header */}
      <div className="watch-detail-header">
        <div className="watch-detail-header-left">
          <Icon icon={statusConfig.icon} width={18} style={{ color: statusConfig.color }} />
          <span className="watch-detail-status" style={{ color: statusConfig.color }}>
            {watch.status}
          </span>
        </div>
        <div className="watch-detail-header-actions">
          <button
            className="watch-detail-action-btn"
            onClick={onTrigger}
            title="Trigger now"
          >
            <Icon icon="mdi:play" width={16} />
          </button>
          <button
            className="watch-detail-action-btn"
            onClick={onToggle}
            title={watch.enabled ? 'Disable' : 'Enable'}
          >
            <Icon icon={watch.enabled ? 'mdi:pause' : 'mdi:play-circle-outline'} width={16} />
          </button>
          <button
            className="watch-detail-action-btn watch-detail-action-btn--danger"
            onClick={onDelete}
            title="Delete watch"
          >
            <Icon icon="mdi:delete" width={16} />
          </button>
          <button className="watch-detail-close" onClick={onClose}>
            <Icon icon="mdi:close" width={18} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="watch-detail-content">
        {loading ? (
          <div className="watch-detail-loading">
            <VideoLoader size="small" message="Loading details..." />
          </div>
        ) : (
          <>
            {/* Title */}
            <div className="watch-detail-title-section">
              <h2 className="watch-detail-title">{watch.name}</h2>
              <span
                className="watch-detail-action-type"
                style={{
                  color: actionColor,
                  background: `${actionColor}15`,
                }}
              >
                {watch.action_type}
              </span>
            </div>

            {/* Description */}
            {watch.description && (
              <p className="watch-detail-description">{watch.description}</p>
            )}

            {/* Stats Summary */}
            <div className="watch-detail-stats">
              <div className="watch-detail-stat">
                <span className="watch-detail-stat-value">{stats.total_executions || 0}</span>
                <span className="watch-detail-stat-label">Total Runs</span>
              </div>
              <div className="watch-detail-stat">
                <span className="watch-detail-stat-value" style={{ color: '#34d399' }}>
                  {stats.success_count || 0}
                </span>
                <span className="watch-detail-stat-label">Success</span>
              </div>
              <div className="watch-detail-stat">
                <span className="watch-detail-stat-value" style={{ color: '#f87171' }}>
                  {stats.failed_count || 0}
                </span>
                <span className="watch-detail-stat-label">Failed</span>
              </div>
              <div className="watch-detail-stat">
                <span className="watch-detail-stat-value">
                  {formatDuration(stats.avg_duration_ms)}
                </span>
                <span className="watch-detail-stat-label">Avg Duration</span>
              </div>
            </div>

            {/* Success Rate Bar */}
            {stats.total_executions > 0 && (
              <div className="watch-detail-success-bar">
                <div className="watch-detail-success-bar-label">
                  <span>Success Rate</span>
                  <span>{successRate.toFixed(1)}%</span>
                </div>
                <div className="watch-detail-success-bar-track">
                  <div
                    className="watch-detail-success-bar-fill"
                    style={{ width: `${successRate}%` }}
                  />
                </div>
              </div>
            )}

            {/* Watch Configuration */}
            <div className="watch-detail-section">
              <h3 className="watch-detail-section-title">Configuration</h3>
              <div className="watch-detail-fields">
                <div className="watch-detail-field">
                  <span className="watch-detail-field-label">Poll Interval</span>
                  <span className="watch-detail-field-value">
                    {watchDetail.poll_interval_seconds}s
                  </span>
                </div>
                <div className="watch-detail-field">
                  <span className="watch-detail-field-label">Last Checked</span>
                  <span className="watch-detail-field-value">
                    {formatRelativeTime(watchDetail.last_checked_at)}
                  </span>
                </div>
                <div className="watch-detail-field">
                  <span className="watch-detail-field-label">Last Triggered</span>
                  <span className="watch-detail-field-value">
                    {formatRelativeTime(watchDetail.last_triggered_at)}
                  </span>
                </div>
                <div className="watch-detail-field">
                  <span className="watch-detail-field-label">Total Triggers</span>
                  <span className="watch-detail-field-value" style={{ color: '#34d399' }}>
                    {watchDetail.trigger_count || 0}
                  </span>
                </div>
                {watchDetail.consecutive_errors > 0 && (
                  <div className="watch-detail-field">
                    <span className="watch-detail-field-label">Consecutive Errors</span>
                    <span className="watch-detail-field-value" style={{ color: '#f87171' }}>
                      {watchDetail.consecutive_errors}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Query */}
            <div className="watch-detail-section">
              <h3 className="watch-detail-section-title">Query</h3>
              <pre className="watch-detail-code">{watchDetail.query}</pre>
            </div>

            {/* Action Spec */}
            <div className="watch-detail-section">
              <h3 className="watch-detail-section-title">Action</h3>
              <pre className="watch-detail-code">{watchDetail.action_spec}</pre>
            </div>

            {/* Last Error */}
            {watchDetail.last_error && (
              <div className="watch-detail-section">
                <h3 className="watch-detail-section-title" style={{ color: '#f87171' }}>
                  <Icon icon="mdi:alert-circle" width={14} />
                  Last Error
                </h3>
                <div className="watch-detail-error">{watchDetail.last_error}</div>
              </div>
            )}

            {/* Recent Executions */}
            <div className="watch-detail-section">
              <h3 className="watch-detail-section-title">
                Recent Executions ({executions.length})
              </h3>
              {executions.length === 0 ? (
                <div className="watch-detail-empty">No executions yet</div>
              ) : (
                <div className="watch-detail-executions">
                  {executions.slice(0, 20).map((exec, idx) => (
                    <div key={exec.execution_id || idx} className="watch-detail-execution">
                      <div className="watch-detail-execution-header">
                        <span
                          className="watch-detail-execution-status"
                          style={{
                            color: EXEC_STATUS_COLORS[exec.status] || EXEC_STATUS_COLORS.skipped,
                          }}
                        >
                          <Icon
                            icon={exec.status === 'success' ? 'mdi:check-circle' : 'mdi:close-circle'}
                            width={12}
                          />
                          {exec.status}
                        </span>
                        <span className="watch-detail-execution-time">
                          {formatRelativeTime(exec.triggered_at)}
                        </span>
                      </div>
                      <div className="watch-detail-execution-details">
                        {exec.row_count !== null && (
                          <span className="watch-detail-execution-detail">
                            <Icon icon="mdi:table" width={12} />
                            {exec.row_count} rows
                          </span>
                        )}
                        {exec.duration_ms !== null && (
                          <span className="watch-detail-execution-detail">
                            <Icon icon="mdi:timer" width={12} />
                            {formatDuration(exec.duration_ms)}
                          </span>
                        )}
                        {exec.cascade_session_id && cascadeId && (
                          <button
                            className="watch-detail-execution-link"
                            onClick={() => handleNavigateToSession(exec.cascade_session_id)}
                            title={`Open session ${exec.cascade_session_id}`}
                          >
                            <Icon icon="mdi:open-in-new" width={12} />
                            {exec.cascade_session_id.substring(0, 12)}...
                          </button>
                        )}
                        {exec.cascade_session_id && !cascadeId && (
                          <span className="watch-detail-execution-detail">
                            <Icon icon="mdi:file-tree" width={12} />
                            {exec.cascade_session_id.substring(0, 8)}...
                          </span>
                        )}
                        {exec.signal_fired && (
                          <span className="watch-detail-execution-detail" style={{ color: '#818cf8' }}>
                            <Icon icon="mdi:broadcast" width={12} />
                            signal fired
                          </span>
                        )}
                      </div>
                      {exec.error_message && (
                        <div className="watch-detail-execution-error">
                          {exec.error_message}
                        </div>
                      )}
                      {/* Session Output Preview */}
                      {exec.session_output && (
                        <div className="watch-detail-execution-output">
                          <div className="watch-detail-execution-output-header">
                            <Icon icon="mdi:message-text" width={12} />
                            <span>
                              {exec.session_output.cell_name || 'Output'}
                              {exec.session_output.role && ` (${exec.session_output.role})`}
                            </span>
                          </div>
                          <pre className="watch-detail-execution-output-content">
                            {exec.session_output.content}
                          </pre>
                        </div>
                      )}
                      {exec.result_preview && !exec.session_output && (
                        <div className="watch-detail-execution-preview">
                          <pre>{exec.result_preview}</pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default WatchDetail;
