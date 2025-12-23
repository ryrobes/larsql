import React from 'react';
import { Icon } from '@iconify/react';
import './PhaseCard.css';

/**
 * Format milliseconds to human-readable time
 * Examples: <1s, 1s, 1m 12s, 5m 30s
 */
const formatDuration = (ms) => {
  if (!ms) return null;

  if (ms < 1000) return '<1s';

  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  if (minutes === 0) {
    return `${seconds}s`;
  }

  if (remainingSeconds === 0) {
    return `${minutes}m`;
  }

  return `${minutes}m ${remainingSeconds}s`;
};

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
const PhaseCard = ({ phase, index, cellState, phaseLogs = [], isSelected, onSelect }) => {
  const status = cellState?.status || 'pending';
  const isCached = cellState?.cached === true;
  const autoFixed = cellState?.autoFixed;
  const hasImages = cellState?.images && cellState.images.length > 0;

  // Extract sounding info from logs
  const soundingInfo = React.useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return null;

    const soundingIndices = new Set();
    let winningIndex = null;

    for (const log of phaseLogs) {
      if (log.sounding_index !== null && log.sounding_index !== undefined) {
        soundingIndices.add(log.sounding_index);
      }
      if (log.winning_sounding_index !== null && log.winning_sounding_index !== undefined) {
        winningIndex = log.winning_sounding_index;
      }
    }

    if (soundingIndices.size === 0) return null;

    return {
      soundings: Array.from(soundingIndices).sort((a, b) => a - b),
      winner: winningIndex
    };
  }, [phaseLogs]);

  // Type info - check for tool field or if it's a regular LLM phase
  const typeInfo = {
    sql_data: { label: 'SQL', icon: 'mdi:database', color: '#60a5fa' },
    python_data: { label: 'Python', icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { label: 'JS', icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { label: 'Clj', icon: 'simple-icons:clojure', color: '#63b132' },
    llm_phase: { label: 'LLM', icon: 'mdi:brain', color: '#a78bfa' },
    windlass_data: { label: 'LLM (Data)', icon: 'mdi:sail-boat', color: '#2dd4bf' },
    linux_shell: { label: 'Browser', icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize
    linux_shell_dangerous: { label: 'Browser', icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize (host)
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
      data-phase-name={phase.name}
    >
      {/* Top row: Type (Icon + Label) + Status */}
      <div className="phase-card-top-row">
        <div className="phase-card-type-row">
          <Icon icon={info.icon} width="16" style={{ color: info.color }} />
          <span className="phase-card-type-label" style={{ color: info.color }}>
            {info.label}
          </span>
          {hasImages && (
            <Icon icon="mdi:image" width="14" style={{ color: '#a78bfa', marginLeft: '4px' }} title="Contains images" />
          )}
        </div>
        <StatusIcon />
      </div>

      {/* Name */}
      <div className="phase-card-name" title={phase.name}>
        {phase.name}
      </div>

      {/* Bottom row: Stats + Badges (all horizontal) */}
      <div className="phase-card-bottom-row">
        {cellState?.duration !== undefined && cellState.duration !== null && (
          <span className="phase-card-stat">
            <Icon icon="mdi:clock-outline" width="12" />
            {formatDuration(cellState.duration)}
          </span>
        )}
        {cellState?.result?.row_count !== undefined && (
          <span className="phase-card-stat phase-card-stat-rows">
            <Icon icon="mdi:table" width="12" />
            {cellState.result.row_count}
          </span>
        )}
        {cellState?.cost > 0 && (
          <span className="phase-card-stat phase-card-stat-cost" title="LLM cost">
            <Icon icon="mdi:currency-usd" width="12" />
            {cellState.cost < 0.01 ? '<$0.01' : `$${cellState.cost.toFixed(4)}`}
          </span>
        )}
        {cellState?.model && (
          <span className="phase-card-stat phase-card-stat-model" title={cellState.model}>
            <Icon icon="mdi:chip" width="12" />
            {cellState.model.split('/').pop().slice(0, 15)}
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

      {/* Soundings indicator row */}
      {soundingInfo && (
        <div className="phase-card-soundings-row">
          {soundingInfo.soundings.map((idx) => (
            <div
              key={idx}
              className={`phase-card-sounding-dot ${idx === soundingInfo.winner ? 'winner' : ''}`}
              title={idx === soundingInfo.winner ? `Sounding ${idx} (WINNER)` : `Sounding ${idx}`}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default React.memo(PhaseCard);
