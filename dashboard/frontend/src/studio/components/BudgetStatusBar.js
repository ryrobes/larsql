import React, { useRef, useEffect } from 'react';
import { useBudgetData } from '../hooks/useBudgetData';
import './BudgetStatusBar.css';

/**
 * BudgetStatusBar - Displays real-time token budget status
 *
 * Shows:
 * - Live token usage that increases with each LLM call
 * - Progress bar with color-coded thresholds
 * - Enforcement events when budget is pruned
 * - Total tokens pruned
 *
 * The bar updates in real-time as tokens accumulate during cascade execution.
 */
export function BudgetStatusBar({ sessionId, shouldPoll = true }) {
  const { budgetConfig, usageHistory, totalEnforcements, totalPruned, currentUsage, loading, error } = useBudgetData(sessionId, shouldPoll);
  const prevUsageRef = useRef(null);

  // Track if usage changed to show animation
  const usageChanged = prevUsageRef.current !== null && prevUsageRef.current !== currentUsage;
  const usageIncreased = usageChanged && currentUsage > prevUsageRef.current;
  const usageDecreased = usageChanged && currentUsage < prevUsageRef.current;

  useEffect(() => {
    prevUsageRef.current = currentUsage;
  }, [currentUsage]);

  // Don't render anything if no sessionId
  if (!sessionId) {
    return null;
  }

  // Don't show loading state - just wait silently
  if (loading) {
    return null;
  }

  // Silently ignore errors - they're expected when session doesn't exist yet
  if (error) {
    return null;
  }

  // No budget configured for this cascade - don't render
  if (!budgetConfig) {
    return null;
  }

  // Calculate metrics
  const maxTokens = budgetConfig.max_total || 100000;
  const reserve = budgetConfig.reserve_for_output || 4000;
  const limit = maxTokens - reserve;
  const warningThreshold = budgetConfig.warning_threshold || 0.8;
  const strategy = budgetConfig.strategy || 'sliding_window';

  // Current usage from live token tracking
  const usage = currentUsage || 0;
  const percentage = limit > 0 ? usage / limit : 0;

  // Count LLM calls from usage history
  const llmCallCount = usageHistory?.filter(e => e.event_type === 'llm_call').length || 0;

  // Determine color based on percentage
  const color =
    percentage > 0.95 ? 'red' :
    percentage > warningThreshold ? 'yellow' : 'green';

  // Format numbers with commas
  const formatNumber = (num) => {
    if (num == null) return '0';
    return num.toLocaleString();
  };

  // Animation class for usage changes
  const usageAnimationClass = usageIncreased ? 'usage-increased' : usageDecreased ? 'usage-decreased' : '';

  return (
    <div className={`budget-status-bar budget-${color}`}>
      <div className="budget-header">
        <div className="budget-header-main">
          <span className="budget-title">Token Budget:</span>
          <span className={`budget-percentage ${usageAnimationClass}`}>
            {formatNumber(usage)} / {formatNumber(limit)} tokens
            ({(percentage * 100).toFixed(0)}%)
          </span>
        </div>
        <div className="budget-header-stats">
          {llmCallCount > 0 && (
            <div className="llm-call-count" title="Number of LLM calls in this session">
              🔄 {llmCallCount} call{llmCallCount > 1 ? 's' : ''}
            </div>
          )}
          {totalEnforcements > 0 && (
            <div className="enforcement-count">
              💥 {totalEnforcements} enforcement{totalEnforcements > 1 ? 's' : ''}
            </div>
          )}
        </div>
      </div>

      <div className="budget-progress-bar">
        <div
          className={`budget-progress-fill ${usageAnimationClass}`}
          style={{ width: `${Math.min(percentage * 100, 100)}%` }}
        />
        {/* Warning threshold marker */}
        <div
          className="budget-threshold-marker"
          style={{ left: `${warningThreshold * 100}%` }}
          title={`Warning threshold: ${(warningThreshold * 100).toFixed(0)}%`}
        />
      </div>

      <div className="budget-details">
        <div className="budget-detail-item">
          <span className="budget-detail-label">Strategy:</span>
          <span className="budget-detail-value">{strategy}</span>
        </div>
        {totalPruned > 0 && (
          <div className="budget-detail-item budget-detail-pruned">
            <span className="budget-detail-label">Pruned:</span>
            <span className="budget-detail-value">{formatNumber(totalPruned)} tokens</span>
          </div>
        )}
        <div className="budget-detail-item">
          <span className="budget-detail-label">Reserve:</span>
          <span className="budget-detail-value">{formatNumber(reserve)} tokens</span>
        </div>
        <div className="budget-detail-item">
          <span className="budget-detail-label">Limit:</span>
          <span className="budget-detail-value">{formatNumber(limit)} tokens</span>
        </div>
      </div>
    </div>
  );
}
