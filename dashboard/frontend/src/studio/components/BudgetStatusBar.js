import React from 'react';
import { useBudgetData } from '../hooks/useBudgetData';
import './BudgetStatusBar.css';

/**
 * BudgetStatusBar - Displays token budget status and enforcement events
 *
 * Shows:
 * - Current usage vs limit
 * - Progress bar with color-coded thresholds
 * - Enforcement count and strategy
 * - Total tokens pruned
 */
export function BudgetStatusBar({ sessionId }) {
  const { budgetConfig, events, totalEnforcements, totalPruned, currentUsage, loading, error } = useBudgetData(sessionId);

  // Debug logging
  console.log('[BudgetStatusBar] Render check:', {
    sessionId,
    hasBudgetConfig: !!budgetConfig,
    strategy: budgetConfig?.strategy,
    totalEnforcements,
    totalPruned,
    eventsLength: events.length,
    loading,
    error,
    willRender: !(!sessionId || loading || error || !budgetConfig)
  });

  // Don't render anything if no sessionId
  if (!sessionId) {
    console.log('[BudgetStatusBar] Not rendering: no sessionId');
    return null;
  }

  // Don't show loading state - just wait silently
  if (loading) {
    console.log('[BudgetStatusBar] Not rendering: loading');
    return null;
  }

  // Silently ignore errors - they're expected when session doesn't exist yet
  if (error) {
    console.log('[BudgetStatusBar] Not rendering: error', error);
    return null;
  }

  // No budget configured for this cascade - don't render
  if (!budgetConfig) {
    console.log('[BudgetStatusBar] Not rendering: no budgetConfig');
    return null;
  }

  console.log('[BudgetStatusBar] RENDERING with config:', budgetConfig);

  // Calculate metrics
  const maxTokens = budgetConfig.max_total || 100000;
  const reserve = budgetConfig.reserve_for_output || 4000;
  const limit = maxTokens - reserve;
  const warningThreshold = budgetConfig.warning_threshold || 0.8;
  const strategy = budgetConfig.strategy || 'sliding_window';

  // Estimate current usage from last event or use 0
  const usage = currentUsage || 0;
  const percentage = limit > 0 ? usage / limit : 0;

  // Determine color based on percentage
  const color =
    percentage > 0.95 ? 'red' :
    percentage > warningThreshold ? 'yellow' : 'green';

  // Format numbers with commas
  const formatNumber = (num) => {
    if (num == null) return '0';
    return num.toLocaleString();
  };

  return (
    <div className={`budget-status-bar budget-${color}`}>
      <div className="budget-header">
        <div className="budget-header-main">
          <span className="budget-title">Token Budget:</span>
          <span className="budget-percentage">
            {formatNumber(usage)} / {formatNumber(limit)} tokens
            ({(percentage * 100).toFixed(0)}%)
          </span>
        </div>
        {totalEnforcements > 0 && (
          <div className="enforcement-count">
            💥 {totalEnforcements} enforcement{totalEnforcements > 1 ? 's' : ''}
          </div>
        )}
      </div>

      <div className="budget-progress-bar">
        <div
          className="budget-progress-fill"
          style={{ width: `${Math.min(percentage * 100, 100)}%` }}
        />
      </div>

      <div className="budget-details">
        <div className="budget-detail-item">
          <span className="budget-detail-label">Strategy:</span>
          <span className="budget-detail-value">{strategy}</span>
        </div>
        {totalPruned > 0 && (
          <div className="budget-detail-item">
            <span className="budget-detail-label">Pruned:</span>
            <span className="budget-detail-value">{formatNumber(totalPruned)} tokens</span>
          </div>
        )}
        <div className="budget-detail-item">
          <span className="budget-detail-label">Reserve:</span>
          <span className="budget-detail-value">{formatNumber(reserve)} tokens</span>
        </div>
        <div className="budget-detail-item">
          <span className="budget-detail-label">Warning:</span>
          <span className="budget-detail-value">{(warningThreshold * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}
