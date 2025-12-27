import React from 'react';
import { Icon } from '@iconify/react';
import KPICard from './KPICard';
import InsightCard from './InsightCard';
import './OverviewPanel.css';

/**
 * OverviewPanel - Overview section with KPIs and insights
 * Displays high-level metrics and human-readable operational intelligence
 *
 * @param {Object} data - Overview data from backend
 * @param {Object} data.kpis - Key performance indicators
 * @param {Object} data.trends - Trend data (percentage changes)
 * @param {Array} data.insights - Array of insight objects
 */
const OverviewPanel = ({ data }) => {
  if (!data) {
    return (
      <div className="overview-panel">
        <div className="overview-loading">Loading overview data...</div>
      </div>
    );
  }

  const { kpis, trends, insights } = data;

  return (
    <div className="overview-panel">
      {/* KPI Cards Row */}
      <div className="overview-kpi-grid">
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
          title="Outliers"
          value={kpis.outlier_count || 0}
          subtitle="anomalies"
          icon="mdi:alert-circle"
          color={kpis.outlier_count > 0 ? '#ff006e' : '#34d399'}
        />
      </div>

      {/* Insights Section */}
      {insights && insights.length > 0 && (
        <div className="overview-insights-section">
          <div className="overview-section-header">
            <Icon icon="mdi:lightbulb-on" width={18} />
            <h2>Operational Intelligence</h2>
            <span className="overview-insights-count">{insights.length} insights</span>
          </div>

          <div className="overview-insights-list">
            {insights.map((insight, idx) => (
              <InsightCard key={idx} insight={insight} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {(!insights || insights.length === 0) && (
        <div className="overview-insights-section">
          <div className="overview-section-header">
            <Icon icon="mdi:lightbulb-on" width={18} />
            <h2>Operational Intelligence</h2>
          </div>
          <div className="overview-empty-state">
            <Icon icon="mdi:check-circle" width={32} style={{ color: '#34d399' }} />
            <p>No anomalies detected. All sessions performing within normal parameters.</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default OverviewPanel;
