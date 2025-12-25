import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import ModelIcon, { getProviderColor, getProvider } from '../../components/ModelIcon';
import { Badge } from '../../components';
import './CellCard.css';

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
 * CellCard - Compact horizontal cell card for timeline
 *
 * Shows:
 * - Type icon + badge
 * - Cell name
 * - Status indicator
 * - Duration/row count
 * - Quick actions
 */
const CellCard = ({ cell, index, cellState, cellLogs = [], isSelected, onSelect, defaultModel }) => {
  const status = cellState?.status || 'pending';
  const isCached = cellState?.cached === true;
  const autoFixed = cellState?.autoFixed;
  const hasImages = cellState?.images && cellState.images.length > 0;

  // Make card droppable for creating handoffs
  const { setNodeRef, isOver } = useDroppable({
    id: `cell-card-${cell.name}`,
    data: {
      type: 'cell-card',
      cellName: cell.name,
      cellIndex: index,
    },
  });

  // Extract model - from cell YAML or cellState (executed) or default
  // Only show for LLM cells (deterministic data cells don't use models)
  const isLLMCell = !!(cell.tool === 'windlass_data' || cell.instructions);
  const modelToDisplay = isLLMCell ? (cell.model || cellState?.model || defaultModel) : null;

  // Debug logging
  React.useEffect(() => {
    if (isLLMCell) {
      console.log('[CellCard]', cell.name, {
        isLLMCell,
        cellModel: cell.model,
        cellStateModel: cellState?.model,
        defaultModel,
        modelToDisplay
      });
    }
  }, [cell.name, isLLMCell, cell.model, cellState?.model, defaultModel, modelToDisplay]);

  // Extract candidates config from YAML (before execution)
  const candidatesConfig = cell.candidates;
  const hasCandidates = candidatesConfig && candidatesConfig.factor && candidatesConfig.factor > 1;
  const candidatesFactor = hasCandidates ? candidatesConfig.factor : null;
  const reforgeSteps = hasCandidates && candidatesConfig.reforge ? candidatesConfig.reforge.steps : null;

  // Extract candidate info from logs (after execution)
  const candidateInfo = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    const candidateIndices = new Set();
    let winningIndex = null;

    for (const log of cellLogs) {
      if (log.candidate_index !== null && log.candidate_index !== undefined) {
        candidateIndices.add(log.candidate_index);
      }
      if (log.winning_sounding_index !== null && log.winning_sounding_index !== undefined) {
        winningIndex = log.winning_sounding_index;
      }
    }

    if (candidateIndices.size === 0) return null;

    return {
      candidates: Array.from(candidateIndices).sort((a, b) => a - b),
      winner: winningIndex
    };
  }, [cellLogs]);

  // Type info - check for tool field or if it's a regular LLM cell
  const typeInfo = {
    sql_data: { label: 'SQL', icon: 'mdi:database', color: '#60a5fa' },
    python_data: { label: 'Python', icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { label: 'JS', icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { label: 'Clj', icon: 'simple-icons:clojure', color: '#63b132' },
    llm_cell: { label: 'LLM', icon: 'mdi:brain', color: '#a78bfa' },
    windlass_data: { label: 'LLM (Data)', icon: 'mdi:sail-boat', color: '#2dd4bf' },
    linux_shell: { label: 'Browser', icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize
    linux_shell_dangerous: { label: 'Browser', icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize (host)
  };
  const cellType = cell.tool || (cell.instructions ? 'llm_cell' : 'python_data');
  const info = typeInfo[cellType] || typeInfo.python_data;

  // Status icon
  const StatusIcon = () => {
    switch (status) {
      case 'running':
        return <span className="cell-card-status-spinner" />;
      case 'success':
        return <Icon icon="mdi:check-circle" className="cell-card-status-success" />;
      case 'error':
        return <Icon icon="mdi:alert-circle" className="cell-card-status-error" />;
      case 'stale':
        return <Icon icon="mdi:circle-outline" className="cell-card-status-stale" />;
      default:
        return <Icon icon="mdi:circle-outline" className="cell-card-status-pending" />;
    }
  };

  return (
    <div
      ref={setNodeRef}
      className={`cell-card cell-card-${status} ${isSelected ? 'cell-card-selected' : ''} ${hasCandidates ? 'cell-card-stacked' : ''} ${isOver ? 'cell-card-drop-target' : ''}`}
      onClick={onSelect}
      data-cell-name={cell.name}
    >
      {/* Top row: Type (Icon + Label) + Status */}
      <div className="cell-card-top-row">
        <div className="cell-card-type-row">
          <Icon icon={info.icon} width="16" style={{ color: info.color }} />
          <span className="cell-card-type-label" style={{ color: info.color }}>
            {info.label}
          </span>
          {hasImages && (
            <Icon icon="mdi:image" width="14" style={{ color: '#a78bfa', marginLeft: '4px' }} title="Contains images" />
          )}
        </div>
        <StatusIcon />
      </div>

      {/* Name */}
      <div className="cell-card-name" title={cell.name}>
        {cell.name}
      </div>

      {/* Bottom row: Stats + Badges (all horizontal) */}
      <div className="cell-card-bottom-row">
        {/* Duration (after execution) */}
        {cellState?.duration !== undefined && cellState.duration !== null && (
          <span className="cell-card-stat">
            <Icon icon="mdi:clock-outline" width="12" />
            {formatDuration(cellState.duration)}
          </span>
        )}

        {/* Row count (after execution) */}
        {cellState?.result?.row_count !== undefined && (
          <span className="cell-card-stat cell-card-stat-rows">
            <Icon icon="mdi:table" width="12" />
            {cellState.result.row_count}
          </span>
        )}

        {/* Cost (after execution) */}
        {cellState?.cost > 0 && (
          <span className="cell-card-stat cell-card-stat-cost" title="LLM cost">
            <Icon icon="mdi:currency-usd" width="12" />
            {cellState.cost < 0.01 ? '<$0.01' : `$${cellState.cost.toFixed(4)}`}
          </span>
        )}

        {/* Model - show from YAML or default (BEFORE execution) */}
        {modelToDisplay && (
          <span
            className="cell-card-stat cell-card-stat-model"
            title={modelToDisplay}
            style={{ color: getProviderColor(getProvider(modelToDisplay)) }}
          >
            <ModelIcon modelId={modelToDisplay} size={12} showTooltip={false} />
            {modelToDisplay.split('/').pop().slice(0, 15)}
          </span>
        )}

        {/* Reforge steps - from YAML (BEFORE execution) */}
        {reforgeSteps && !candidateInfo && (
          <Badge variant="label" color="purple" size="sm">
            {reforgeSteps}x reforge
          </Badge>
        )}

        {/* Cached indicator (after execution) */}
        {isCached && status === 'success' && (
          <Badge variant="label" color="purple" size="sm">
            cached
          </Badge>
        )}

        {/* Auto-fix indicator (after execution) */}
        {autoFixed && (
          <Badge variant="label" color="green" size="sm">
            🔧 fixed
          </Badge>
        )}
      </div>

      {/* Candidates indicator row (after execution - shows actual results) */}
      {candidateInfo && (
        <div className="cell-card-candidates-row">
          {candidateInfo.candidates.map((idx) => (
            <div
              key={idx}
              className={`cell-card-candidate-dot ${idx === candidateInfo.winner ? 'winner' : ''}`}
              title={idx === candidateInfo.winner ? `Candidate ${idx} (WINNER)` : `Candidate ${idx}`}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default React.memo(CellCard);
