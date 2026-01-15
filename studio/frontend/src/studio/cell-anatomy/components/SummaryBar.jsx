import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * SummaryBar - Bottom bar with execution stats
 *
 * Now includes analytics-based metrics:
 * - Context cost % (from cascadeAnalytics)
 * - Cell cost comparison vs historical avg (from cellAnalytics)
 */
const SummaryBar = ({ cellState = {}, executionData, config, cascadeAnalytics, cellAnalytics }) => {
  const { duration: cellDuration, cost, tokens_in, tokens_out, status } = cellState;

  // Calculate totals from execution data if available
  const totalToolCalls = executionData?.toolCalls?.length || 0;
  const totalTurns = executionData?.takes?.reduce(
    (sum, c) => sum + (c.turns?.filter(t => t.status !== 'pending').length || 0),
    0
  ) || 0;

  // Calculate total duration from takes if cellState.duration isn't available
  const takesDuration = executionData?.takes?.reduce(
    (max, c) => Math.max(max, c.duration || 0),
    0
  ) || 0;
  const duration = cellDuration || takesDuration;

  // Format duration
  const formatDuration = (ms) => {
    if (!ms) return null;
    if (ms < 1000) return '<1s';
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    if (minutes === 0) return `${seconds}s`;
    const remainingSeconds = seconds % 60;
    return remainingSeconds === 0 ? `${minutes}m` : `${minutes}m ${remainingSeconds}s`;
  };

  return (
    <div className="cell-anatomy-summary">
      <div className="cell-anatomy-summary-left">
        {/* Config summary */}
        <span className="cell-anatomy-summary-stat">
          <Icon icon="mdi:layers-triple" width="12" />
          <span>factor:</span>
          <span className="cell-anatomy-summary-stat-value">{config?.factor || 1}</span>
        </span>

        <span className="cell-anatomy-summary-stat">
          <Icon icon="mdi:repeat" width="12" />
          <span>max_turns:</span>
          <span className="cell-anatomy-summary-stat-value">{config?.maxTurns || 1}</span>
        </span>

        {/* Execution stats */}
        {duration && (
          <span className="cell-anatomy-summary-stat">
            <Icon icon="mdi:clock-outline" width="12" />
            <span className="cell-anatomy-summary-stat-value">{formatDuration(duration)}</span>
          </span>
        )}

        {cost > 0 && (
          <span className="cell-anatomy-summary-stat cell-anatomy-summary-stat-cost">
            <Icon icon="mdi:currency-usd" width="12" />
            <span className="cell-anatomy-summary-stat-value">
              ${cost < 0.01 ? '<0.01' : cost.toFixed(4)}
            </span>
            {/* Show cost multiplier if historical comparison available */}
            {cellAnalytics?.species_avg_cost > 0 && (
              <span
                style={{
                  marginLeft: '4px',
                  fontSize: '10px',
                  color: (cost / cellAnalytics.species_avg_cost) >= 1.5 ? '#f87171'
                       : (cost / cellAnalytics.species_avg_cost) >= 1.2 ? '#fbbf24'
                       : (cost / cellAnalytics.species_avg_cost) <= 0.7 ? '#34d399'
                       : '#94a3b8'
                }}
                title={`vs avg $${cellAnalytics.species_avg_cost.toFixed(4)} (n=${cellAnalytics.species_run_count} runs)`}
              >
                ({(cost / cellAnalytics.species_avg_cost).toFixed(1)}x avg)
              </span>
            )}
          </span>
        )}

        {/* Cell cost % of cascade (bottleneck indicator) */}
        {cellAnalytics?.cell_cost_pct >= 25 && (
          <span
            className="cell-anatomy-summary-stat"
            style={{
              color: cellAnalytics.cell_cost_pct > 60 ? '#f87171'
                   : cellAnalytics.cell_cost_pct > 40 ? '#fbbf24'
                   : '#94a3b8'
            }}
            title="Percentage of total cascade cost consumed by this cell"
          >
            <Icon icon="mdi:chart-pie" width="12" />
            <span className="cell-anatomy-summary-stat-value">
              {cellAnalytics.cell_cost_pct.toFixed(0)}% of cascade
            </span>
          </span>
        )}

        {/* Context cost % (cascade-level) */}
        {cascadeAnalytics?.context_cost_pct >= 30 && (
          <span
            className="cell-anatomy-summary-stat"
            style={{ color: cascadeAnalytics.context_cost_pct > 60 ? '#fbbf24' : '#94a3b8' }}
            title={`${cascadeAnalytics.context_cost_pct.toFixed(0)}% of cascade cost from context injection`}
          >
            <Icon icon="mdi:database-import" width="12" />
            <span className="cell-anatomy-summary-stat-value">
              {cascadeAnalytics.context_cost_pct.toFixed(0)}% ctx
            </span>
          </span>
        )}

        {(tokens_in > 0 || tokens_out > 0) && (
          <span className="cell-anatomy-summary-stat cell-anatomy-summary-stat-tokens">
            <Icon icon="mdi:dice-multiple" width="12" />
            <span className="cell-anatomy-summary-stat-value">
              {tokens_in || 0} / {tokens_out || 0}
            </span>
          </span>
        )}

        {totalToolCalls > 0 && (
          <span className="cell-anatomy-summary-stat">
            <Icon icon="mdi:hammer-wrench" width="12" />
            <span className="cell-anatomy-summary-stat-value">{totalToolCalls} tools</span>
          </span>
        )}

        {totalTurns > 0 && (
          <span className="cell-anatomy-summary-stat">
            <Icon icon="mdi:sync" width="12" />
            <span className="cell-anatomy-summary-stat-value">{totalTurns} turns</span>
          </span>
        )}
      </div>

      <div className="cell-anatomy-summary-right">
        {/* Winner badge */}
        {executionData?.winnerIndex !== null && executionData?.winnerIndex !== undefined && (
          <div className="cell-anatomy-winner-badge">
            <Icon icon="mdi:crown" width="12" />
            <span>S{executionData.winnerIndex}</span>
          </div>
        )}

        {/* Status indicator */}
        {status && (
          <span className={`cell-anatomy-summary-status status-${status}`}>
            {status === 'running' && <Icon icon="mdi:loading" width="12" className="spin" />}
            {status === 'success' && <Icon icon="mdi:check-circle" width="12" />}
            {status === 'error' && <Icon icon="mdi:alert-circle" width="12" />}
            {status === 'pending' && <Icon icon="mdi:circle-outline" width="12" />}
            {status}
          </span>
        )}
      </div>
    </div>
  );
};

export default SummaryBar;
