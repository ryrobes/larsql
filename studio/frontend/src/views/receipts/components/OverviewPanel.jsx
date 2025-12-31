import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import KPICard from './KPICard';
import InsightCard from './InsightCard';
import CostTrendChart from './CostTrendChart';
import CostBreakdownChart from './CostBreakdownChart';
import RunsActivityChart from './RunsActivityChart';
import ContextValueChart from './ContextValueChart';
import TopExpensiveList from './TopExpensiveList';
import { useCredits } from '../../../hooks/useCredits';
import './OverviewPanel.css';

/**
 * OverviewPanel - Dashboard with KPIs, charts, and insights
 */
const OverviewPanel = ({
  data,
  timeSeriesData = [],
  cascadeData = { cascades: [], grand_total: 0 },
  modelData = { models: [], grand_total: 0 },
  topExpensive = [],
  contextEfficiency = null,
  chartsLoading = false,
  onSessionClick = null,
  granularity = 'daily',
  onGranularityChange = null
}) => {
  const [insightsExpanded, setInsightsExpanded] = useState(false);
  const credits = useCredits({ pollInterval: 60000 });

  if (!data) {
    return (
      <div className="overview-panel">
        <VideoLoader
          size="small"
          message="Loading overview data..."
          className="video-loader--inline"
        />
      </div>
    );
  }

  const { kpis, trends, insights } = data;

  const sortedInsights = [...(insights || [])].sort((a, b) => {
    const severityOrder = { critical: 0, warning: 1, major: 2, info: 3, normal: 4 };
    return (severityOrder[a.severity] || 4) - (severityOrder[b.severity] || 4);
  });
  const visibleInsights = insightsExpanded ? sortedInsights : sortedInsights.slice(0, 3);
  const hasMoreInsights = sortedInsights.length > 3;

  const granularityOptions = [
    { value: 'hourly', label: 'Hourly' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' }
  ];

  return (
    <div className="overview-panel">
      {/* KPI Cards Row */}
      <div className="overview-kpi-row">
        <KPICard
          title="Total Cost"
          value={`$${kpis.total_cost?.toFixed(4) || '0.0000'}`}
          trend={trends?.cost_change_pct}
          icon="mdi:currency-usd"
          color="#34d399"
        />
        <KPICard
          title="Avg per Run"
          value={`$${kpis.avg_cost?.toFixed(6) || '0.000000'}`}
          subtitle={`${kpis.session_count || 0} sessions`}
          icon="mdi:chart-line"
          color="#60a5fa"
        />
        <KPICard
          title="Context Cost"
          value={`${kpis.avg_context_pct?.toFixed(1) || '0.0'}%`}
          subtitle="hidden overhead"
          trend={trends?.context_change_pct}
          icon="mdi:file-document-multiple"
          color="#a78bfa"
        />
        <KPICard
          title="Context Efficiency"
          value={contextEfficiency?.efficiency_score ? `${contextEfficiency.efficiency_score.toFixed(0)}%` : '—'}
          subtitle={contextEfficiency?.wasted_cost ? `$${contextEfficiency.wasted_cost.toFixed(4)} wasted` : 'no data'}
          trend={contextEfficiency?.efficiency_trend}
          icon="mdi:target"
          color={contextEfficiency?.efficiency_score >= 60 ? '#34d399' : contextEfficiency?.efficiency_score >= 40 ? '#fbbf24' : '#ff006e'}
        />
        <KPICard
          title="Outliers"
          value={kpis.outlier_count || 0}
          subtitle="anomalies"
          icon="mdi:alert-circle"
          color={kpis.outlier_count > 0 ? '#ff006e' : '#34d399'}
        />
        <KPICard
          title="OR Balance"
          value={credits.balance !== null ? `$${credits.balance.toFixed(2)}` : '—'}
          subtitle={credits.runwayDays !== null ? `~${credits.runwayDays}d runway` : credits.loading ? 'loading...' : null}
          trend={credits.delta24h !== null ? (credits.delta24h / (credits.balance || 1)) * 100 : undefined}
          icon="mdi:wallet"
          color={credits.balance === null ? '#64748b' : credits.balance > 20 ? '#34d399' : credits.balance > 5 ? '#fbbf24' : '#f87171'}
        />
      </div>

      {/* Cost Analytics Section */}
      <div className="overview-section">
        <div className="overview-section-header">
          <Icon icon="mdi:chart-box" width={14} />
          <span className="section-title">Cost Analytics</span>
        </div>

        {/* Cost Trend with granularity selector */}
        <div className="overview-trend-section">
          <div className="trend-header">
            <Icon icon="mdi:chart-timeline-variant" width={14} />
            <span className="trend-title">Cost Trend</span>
            <div className="granularity-selector">
              {granularityOptions.map(opt => (
                <button
                  key={opt.value}
                  className={`granularity-btn ${granularity === opt.value ? 'active' : ''}`}
                  onClick={() => onGranularityChange && onGranularityChange(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="trend-stats">
              <span className="trend-stat">
                <span className="stat-label">Total:</span>
                <span className="stat-value">${kpis.total_cost?.toFixed(2) || '0.00'}</span>
              </span>
              <span className="trend-stat">
                <span className="stat-label">Avg/{granularity === 'hourly' ? 'Hr' : granularity === 'daily' ? 'Day' : granularity === 'weekly' ? 'Wk' : 'Mo'}:</span>
                <span className="stat-value">${(kpis.total_cost / (timeSeriesData.length || 1)).toFixed(2)}</span>
              </span>
            </div>
          </div>
          <CostTrendChart
            data={timeSeriesData}
            loading={chartsLoading}
            granularity={granularity}
          />
        </div>

        {/* Breakdown Charts Grid - 2x2 layout */}
        <div className="overview-breakdown-grid">
          <div className="breakdown-cell">
            <CostBreakdownChart
              data={cascadeData.cascades}
              type="cascade"
              chartType="bar"
              loading={chartsLoading}
              grandTotal={cascadeData.grand_total}
            />
          </div>
          <div className="breakdown-cell">
            <CostBreakdownChart
              data={modelData.models}
              type="model"
              chartType="pie"
              loading={chartsLoading}
              grandTotal={modelData.grand_total}
            />
          </div>
          <div className="breakdown-cell">
            <RunsActivityChart
              data={timeSeriesData}
              loading={chartsLoading}
              granularity={granularity}
            />
          </div>
          <div className="breakdown-cell">
            <ContextValueChart
              data={contextEfficiency}
              loading={chartsLoading}
            />
          </div>
        </div>

        {/* Top Expensive */}
        <TopExpensiveList
          sessions={topExpensive}
          loading={chartsLoading}
          onSessionClick={onSessionClick}
        />
      </div>

      {/* Operational Intelligence Section */}
      {insights && insights.length > 0 && (
        <div className="overview-section">
          <div
            className="overview-section-header clickable"
            onClick={() => setInsightsExpanded(!insightsExpanded)}
          >
            <Icon icon="mdi:lightbulb-on" width={14} />
            <span className="section-title">Operational Intelligence</span>
            <span className="section-count">{insights.length} insights</span>
            <Icon
              icon={insightsExpanded ? 'mdi:chevron-up' : 'mdi:chevron-down'}
              width={14}
              className="expand-icon"
            />
          </div>

          <div className="overview-insights-list">
            {visibleInsights.map((insight, idx) => (
              <InsightCard key={idx} insight={insight} />
            ))}
          </div>

          {!insightsExpanded && hasMoreInsights && (
            <div className="insights-more">
              +{sortedInsights.length - 3} more
            </div>
          )}
        </div>
      )}

      {/* Empty insights state */}
      {(!insights || insights.length === 0) && (
        <div className="overview-section">
          <div className="overview-section-header">
            <Icon icon="mdi:lightbulb-on" width={14} />
            <span className="section-title">Operational Intelligence</span>
          </div>
          <div className="overview-empty">
            <Icon icon="mdi:check-circle" width={16} style={{ color: '#34d399' }} />
            <span>No anomalies detected</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default OverviewPanel;
