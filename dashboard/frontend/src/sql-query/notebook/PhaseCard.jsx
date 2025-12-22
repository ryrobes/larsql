import React from 'react';
import { Icon } from '@iconify/react';
import './PhaseCard.css';

/**
 * PhaseCard - Compact horizontal phase card for timeline
 *
 * Shows:
 * - Type icon + badge
 * - Phase name
 * - Status indicator
 * - Duration/row count
 * - Quick actions
 */
const PhaseCard = ({ phase, index, cellState, isSelected, onSelect }) => {
  const status = cellState?.status || 'pending';
  const isCached = cellState?.cached === true;
  const autoFixed = cellState?.autoFixed;

  // Type info - check for tool field or if it's a regular LLM phase
  const typeInfo = {
    sql_data: { label: 'SQL', icon: 'mdi:database', color: '#60a5fa' },
    python_data: { label: 'Python', icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { label: 'JS', icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { label: 'Clj', icon: 'simple-icons:clojure', color: '#63b132' },
    llm_phase: { label: 'LLM', icon: 'mdi:brain', color: '#a78bfa' },
    windlass_data: { label: 'LLM (Data)', icon: 'mdi:sail-boat', color: '#2dd4bf' },
  };
  const phaseType = phase.tool || (phase.instructions ? 'llm_phase' : 'python_data');
  const info = typeInfo[phaseType] || typeInfo.python_data;

  // Status icon
  const StatusIcon = () => {
    switch (status) {
      case 'running':
        return <span className="phase-card-status-spinner" />;
      case 'success':
        return <Icon icon="mdi:check-circle" className="phase-card-status-success" />;
      case 'error':
        return <Icon icon="mdi:alert-circle" className="phase-card-status-error" />;
      case 'stale':
        return <Icon icon="mdi:circle-outline" className="phase-card-status-stale" />;
      default:
        return <Icon icon="mdi:circle-outline" className="phase-card-status-pending" />;
    }
  };

  return (
    <div
      className={`phase-card phase-card-${status} ${isSelected ? 'phase-card-selected' : ''}`}
      onClick={onSelect}
    >
      {/* Top row: Type (Icon + Label) + Status */}
      <div className="phase-card-top-row">
        <div className="phase-card-type-row">
          <Icon icon={info.icon} width="16" style={{ color: info.color }} />
          <span className="phase-card-type-label" style={{ color: info.color }}>
            {info.label}
          </span>
        </div>
        <StatusIcon />
      </div>

      {/* Name */}
      <div className="phase-card-name" title={phase.name}>
        {phase.name}
      </div>

      {/* Bottom row: Stats + Badges (all horizontal) */}
      <div className="phase-card-bottom-row">
        {cellState?.duration && (
          <span className="phase-card-stat">
            <Icon icon="mdi:clock-outline" width="12" />
            {Math.round(cellState.duration)}ms
          </span>
        )}
        {cellState?.result?.row_count !== undefined && (
          <span className="phase-card-stat phase-card-stat-rows">
            <Icon icon="mdi:table" width="12" />
            {cellState.result.row_count}
          </span>
        )}
        {isCached && status === 'success' && (
          <span className="phase-card-badge phase-card-badge-cached" title="Cached result">
            cached
          </span>
        )}
        {autoFixed && (
          <span className="phase-card-badge phase-card-badge-fixed" title="Auto-fixed">
            🔧 fixed
          </span>
        )}
      </div>
    </div>
  );
};

export default React.memo(PhaseCard);
