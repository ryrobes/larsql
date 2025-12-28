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
const CellCard = ({ cell, index, cellState, cellLogs = [], isSelected, onSelect, defaultModel, costMetrics }) => {
  // Development-only render logging
  if (process.env.NODE_ENV === 'development') {
    console.log(`[CellCard] Rendering ${cell.name}`, { status: cellState?.status, logsCount: cellLogs.length });
  }

  const status = cellState?.status || 'pending';
  const isCached = cellState?.cached === true;
  const autoFixed = cellState?.autoFixed;
  const hasImages = cellState?.images && cellState.images.length > 0;

  // Get first image for background decoration
  const firstImage = hasImages ? cellState.images[0] : null;
  const imageUrl = firstImage ? `http://localhost:5001${firstImage}` : null;

  // Cost metrics for scaling and annotations
  const scale = costMetrics?.scale || 1.0;
  const costDeltaPct = costMetrics?.costDeltaPct || 0;
  const duration = costMetrics?.duration || 0;
  const costColor = costMetrics?.color || 'cyan';

  // New analytics-based metrics
  const cellCostPct = costMetrics?.cellCostPct || 0;
  const costMultiplier = costMetrics?.costMultiplier;
  const isOutlier = costMetrics?.isOutlier || false;
  const speciesRunCount = costMetrics?.speciesRunCount || 0;

  // Show annotation if:
  // 1. Historical comparison available and significantly different (1.2x+)
  // 2. OR bottleneck (>25% of cascade cost)
  // 3. OR statistical outlier
  const showAnnotation = costMetrics && (
    (costMultiplier && Math.abs(costMultiplier - 1) >= 0.2) ||
    cellCostPct >= 25 ||
    isOutlier
  );

  // Format duration
  const formatDurationShort = (ms) => {
    if (!ms) return null;
    if (ms < 1000) return '<1s';
    const seconds = Math.floor(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return remainingSeconds > 0 ? `${minutes}m${remainingSeconds}s` : `${minutes}m`;
  };

  // Make card droppable for creating handoffs
  const { setNodeRef, isOver } = useDroppable({
    id: `cell-card-${cell.name}`,
    data: {
      type: 'cell-card',
      cellName: cell.name,
      cellIndex: index,
    },
  });

  // Memoized click handler to prevent creating new functions on every render
  const handleClick = React.useCallback(() => {
    onSelect(index);
  }, [onSelect, index]);

  // Extract model - from cell YAML or cellState (executed) or default
  // Only show for LLM cells (deterministic data cells don't use models)
  const isLLMCell = !!(cell.tool === 'windlass_data' || cell.instructions);
  const modelToDisplay = isLLMCell ? (cell.model || cellState?.model || defaultModel) : null;

  // Extract candidates config from YAML (before execution)
  const candidatesConfig = cell.candidates;
  const hasCandidates = candidatesConfig && candidatesConfig.factor && candidatesConfig.factor > 1;
  const candidatesFactor = hasCandidates ? candidatesConfig.factor : null;
  const reforgeSteps = hasCandidates && candidatesConfig.reforge ? candidatesConfig.reforge.steps : null;

  // Extract candidate info from logs (after execution)
  const candidateInfo = React.useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    const candidatesMap = new Map(); // candidate_index -> { status, maxTurn, maxTurnsAllowed }
    let winningIndex = null;
    let maxTurnsForCell = null;

    // Helper to parse metadata_json
    const parseMetadata = (meta) => {
      if (!meta) return {};
      if (typeof meta === 'string') {
        try { return JSON.parse(meta); } catch { return {}; }
      }
      return meta;
    };

    for (const log of cellLogs) {
      const metadata = parseMetadata(log.metadata_json);

      // Track winning candidate index
      if (log.winning_sounding_index !== null && log.winning_sounding_index !== undefined) {
        winningIndex = log.winning_sounding_index;
      }

      // Track max_turns for the cell (same for all candidates)
      if (metadata.max_turns && maxTurnsForCell === null) {
        maxTurnsForCell = metadata.max_turns;
      }

      // Track candidate status based on log entries
      if (log.candidate_index !== null && log.candidate_index !== undefined) {
        const idx = log.candidate_index;

        if (!candidatesMap.has(idx)) {
          candidatesMap.set(idx, { status: 'running', maxTurn: 0, maxTurnsAllowed: null });
        }

        const candidate = candidatesMap.get(idx);

        // Track the highest turn number we've seen for this candidate
        if (metadata.turn_number && metadata.turn_number > candidate.maxTurn) {
          candidate.maxTurn = metadata.turn_number;
        }

        // Track max_turns from metadata
        if (metadata.max_turns && !candidate.maxTurnsAllowed) {
          candidate.maxTurnsAllowed = metadata.max_turns;
        }

        // COMPLETION DETECTION - check multiple indicators
        // 1. Final turn reached (turn_number >= max_turns)
        if (candidate.maxTurn > 0 && candidate.maxTurnsAllowed &&
            candidate.maxTurn >= candidate.maxTurnsAllowed &&
            candidate.status === 'running') {
          candidate.status = 'complete';
        }

        // 2. Explicit completion markers
        if (log.role === 'sounding_attempt' || log.node_type === 'sounding_attempt') {
          candidate.status = 'complete';
        }

        // 3. Error indicator
        if (log.role === 'error') {
          candidate.status = 'error';
        }
      }
    }

    if (candidatesMap.size === 0) return null;

    // Convert to array with status information
    const candidates = Array.from(candidatesMap.entries())
      .sort((a, b) => a[0] - b[0])  // Sort by index
      .map(([index, data]) => ({
        index,
        status: data.status,
        isWinner: index === winningIndex
      }));

    return {
      candidates,
      winner: winningIndex,
      maxTurns: maxTurnsForCell
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
    <div className="cell-card-wrapper" style={{ transform: `scale(${scale})`, transformOrigin: 'center center' }}>
      <div
        ref={setNodeRef}
        className={`cell-card cell-card-${status} ${isSelected ? 'cell-card-selected' : ''} ${hasCandidates ? 'cell-card-stacked' : ''} ${isOver ? 'cell-card-drop-target' : ''} ${imageUrl ? 'has-image-bg' : ''}`}
        onClick={handleClick}
        data-cell-name={cell.name}
        style={imageUrl ? { '--bg-image-url': `url(${imageUrl})` } : undefined}
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

        {/* Model - floated to the right */}
        {modelToDisplay && (
          <span
            className="cell-card-stat cell-card-stat-model"
            title={modelToDisplay}
            style={{ color: getProviderColor(getProvider(modelToDisplay)), marginLeft: 'auto' }}
          >
            <ModelIcon modelId={modelToDisplay} size={12} showTooltip={false} />
            {modelToDisplay.split('/').pop().slice(0, 15)}
          </span>
        )}

        {/* Cost (after execution) - no icon, just text */}
        {cellState?.cost > 0 && (
          <span className="cell-card-stat cell-card-stat-cost" title="LLM cost">
            {cellState.cost < 0.01 ? '<$0.01' : `$${cellState.cost.toFixed(4)}`}
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

      {/* Candidates indicator row */}
      {/* Show during execution (from logs) or before execution (from config) */}
      {(candidateInfo || (hasCandidates && candidatesFactor)) && (
        <div className="cell-card-candidates-row">
          {candidateInfo ? (
            // Execution mode - show actual candidate statuses
            candidateInfo.candidates.map((candidate) => (
              <div
                key={candidate.index}
                className={`cell-card-candidate-dot ${candidate.status} ${candidate.isWinner ? 'winner' : ''}`}
                title={
                  candidate.isWinner
                    ? `Candidate ${candidate.index} (WINNER)`
                    : `Candidate ${candidate.index} - ${candidate.status}`
                }
              />
            ))
          ) : (
            // Spec mode - show placeholder dots
            Array.from({ length: candidatesFactor }, (_, idx) => (
              <div
                key={idx}
                className="cell-card-candidate-dot pending"
                title={`Candidate ${idx} - pending`}
              />
            ))
          )}
        </div>
      )}
      </div>

      {/* Blueprint-style cost annotation */}
      {showAnnotation && (
        <div className={`cell-cost-annotation ${costColor}`}>
          {/* Show outlier badge if statistical outlier */}
          {isOutlier && (
            <span style={{ marginRight: '4px' }} title="Statistical outlier vs historical runs">⚠</span>
          )}
          {/* Primary metric: multiplier vs avg OR bottleneck % */}
          {costMultiplier && speciesRunCount > 0 ? (
            // Historical comparison available
            <>
              {costMultiplier >= 1.1
                ? `${costMultiplier.toFixed(1)}x avg`
                : costMultiplier <= 0.9
                  ? `${costMultiplier.toFixed(1)}x avg`
                  : null}
              {cellCostPct >= 25 && (
                <span style={{ marginLeft: '4px' }}>{cellCostPct.toFixed(0)}% of cascade</span>
              )}
            </>
          ) : (
            // No historical data, show bottleneck %
            cellCostPct >= 25 && `${cellCostPct.toFixed(0)}% of cascade`
          )}
          {duration > 0 && (
            <span className="annotation-duration"> · {formatDurationShort(duration)}</span>
          )}
        </div>
      )}
    </div>
  );
};

// Custom comparison function for React.memo
// Prevents re-renders when props haven't actually changed
const arePropsEqual = (prevProps, nextProps) => {
  // Primitives - direct comparison
  if (prevProps.index !== nextProps.index) return false;
  if (prevProps.isSelected !== nextProps.isSelected) return false;
  if (prevProps.defaultModel !== nextProps.defaultModel) return false;
  if (prevProps.onSelect !== nextProps.onSelect) return false;

  // Cost metrics - compare by reference first, then by key fields
  // If references differ, check if values actually changed
  if (prevProps.costMetrics !== nextProps.costMetrics) {
    // Quick reference check - different objects, need to compare values
    const prev = prevProps.costMetrics || {};
    const next = nextProps.costMetrics || {};

    // Check all fields that affect rendering
    if (prev.cost !== next.cost) return false;
    if (prev.cellCostPct !== next.cellCostPct) return false;
    if (prev.costMultiplier !== next.costMultiplier) return false;
    if (prev.isOutlier !== next.isOutlier) return false;
    if (prev.speciesRunCount !== next.speciesRunCount) return false;
    if (prev.speciesAvgCost !== next.speciesAvgCost) return false;
    if (prev.duration !== next.duration) return false;
    if (prev.scale !== next.scale) return false;
    if (prev.color !== next.color) return false;
  }

  // Cell config - compare by reference (should be stable from layout memoization)
  if (prevProps.cell !== nextProps.cell) {
    // If references differ, do deep comparison as fallback
    if (JSON.stringify(prevProps.cell) !== JSON.stringify(nextProps.cell)) {
      return false;
    }
  }

  // CellState - compare by reference first (we stabilize these in parent)
  if (prevProps.cellState !== nextProps.cellState) {
    // If references differ, check if both are undefined/null
    if (!prevProps.cellState && !nextProps.cellState) {
      // Both undefined/null - no change
    } else if (!prevProps.cellState || !nextProps.cellState) {
      // One is undefined/null, the other isn't - changed
      return false;
    } else {
      // Both exist but different references - do deep comparison
      if (JSON.stringify(prevProps.cellState) !== JSON.stringify(nextProps.cellState)) {
        return false;
      }
    }
  }

  // CellLogs - compare by reference (should be stable from parent memoization)
  if (prevProps.cellLogs !== nextProps.cellLogs) {
    // If references differ, compare length as quick check
    if (prevProps.cellLogs.length !== nextProps.cellLogs.length) {
      return false;
    }
  }

  // All checks passed - props are equal, prevent re-render
  return true;
};

export default React.memo(CellCard, arePropsEqual);
