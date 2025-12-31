import React, { useState, memo } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './TopExpensiveList.css';

/**
 * TopExpensiveList - Ranked list of most expensive sessions
 * Shows cost, cascade, model, and outlier status
 */
const TopExpensiveList = ({
  sessions = [],
  loading = false,
  onSessionClick = null
}) => {
  const [hoveredIndex, setHoveredIndex] = useState(null);

  // Format currency
  const formatCost = (value) => {
    if (value >= 1) return `$${value.toFixed(2)}`;
    if (value >= 0.01) return `$${value.toFixed(3)}`;
    return `$${value.toFixed(4)}`;
  };

  // Format duration
  const formatDuration = (ms) => {
    if (!ms) return '-';
    if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms.toFixed(0)}ms`;
  };

  // Format timestamp
  const formatTime = (isoString) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Truncate model name
  const formatModel = (model) => {
    if (!model) return '-';
    const name = model.includes('/') ? model.split('/').pop() : model;
    return name.length > 18 ? name.substring(0, 15) + '...' : name;
  };

  if (loading) {
    return (
      <div className="top-expensive-list loading">
        <div className="list-header">
          <span className="list-title">
            <Icon icon="mdi:podium" width={16} />
            Top Expensive Runs
          </span>
        </div>
        <VideoLoader size="small" showMessage={false} />
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="top-expensive-list empty">
        <div className="list-header">
          <span className="list-title">
            <Icon icon="mdi:podium" width={16} />
            Top Expensive Runs
          </span>
        </div>
        <div className="list-empty">
          <Icon icon="mdi:trophy-outline" width={32} />
          <span>No sessions yet</span>
        </div>
      </div>
    );
  }

  return (
    <div className="top-expensive-list">
      <div className="list-header">
        <span className="list-title">
          <Icon icon="mdi:podium" width={16} />
          Top Expensive Runs
        </span>
        <span className="list-subtitle">{sessions.length} sessions</span>
      </div>

      <div className="list-content">
        {sessions.map((session, index) => (
          <div
            key={session.session_id}
            className={`list-item ${hoveredIndex === index ? 'hovered' : ''} ${session.is_outlier ? 'outlier' : ''}`}
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex(null)}
            onClick={() => onSessionClick && onSessionClick(session)}
          >
            <div className="item-rank">
              {index === 0 && <Icon icon="mdi:medal" className="gold" width={16} />}
              {index === 1 && <Icon icon="mdi:medal" className="silver" width={16} />}
              {index === 2 && <Icon icon="mdi:medal" className="bronze" width={16} />}
              {index > 2 && <span className="rank-number">#{index + 1}</span>}
            </div>

            <div className="item-main">
              <div className="item-top-row">
                <span className="item-cascade">{session.cascade_id}</span>
                {session.is_outlier && (
                  <span className="outlier-badge" title={`Z-score: ${session.z_score?.toFixed(1)}`}>
                    <Icon icon="mdi:alert-circle" width={12} />
                    Outlier
                  </span>
                )}
              </div>
              <div className="item-meta">
                <span className="meta-item">
                  <Icon icon="mdi:chip" width={12} />
                  {formatModel(session.model)}
                </span>
                <span className="meta-item">
                  <Icon icon="mdi:clock-outline" width={12} />
                  {formatDuration(session.duration_ms)}
                </span>
                {session.candidates > 0 && (
                  <span className="meta-item">
                    <Icon icon="mdi:source-branch" width={12} />
                    {session.candidates} candidates
                  </span>
                )}
              </div>
            </div>

            <div className="item-cost">
              <span className="cost-value">{formatCost(session.cost)}</span>
              {session.context_pct > 50 && (
                <span className="context-indicator" title={`${session.context_pct.toFixed(0)}% context`}>
                  <Icon icon="mdi:file-document-multiple" width={10} />
                  {session.context_pct.toFixed(0)}%
                </span>
              )}
            </div>

            <div className="item-time">
              {formatTime(session.created_at)}
            </div>

            <div className="item-action">
              <Icon icon="mdi:chevron-right" width={16} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default memo(TopExpensiveList);
