import React from 'react';
import { Icon } from '@iconify/react';
import Card from '../../../components/Card/Card';
import './KPICard.css';

/**
 * KPICard - Displays a single metric with trend indicator
 * Uses Windlass Card component with custom styling
 *
 * @param {string} title - Metric name
 * @param {string|number} value - Metric value
 * @param {string} subtitle - Optional subtitle (e.g., "sessions")
 * @param {number} trend - Percentage change (positive/negative)
 * @param {string} icon - Iconify icon ID
 * @param {string} color - Accent color for icon and value
 */
const KPICard = ({ title, value, subtitle, trend, icon, color = '#00e5ff' }) => {
  const trendColor = trend > 0 ? '#ff006e' : trend < 0 ? '#34d399' : '#64748b';
  const trendIcon = trend > 0 ? 'mdi:trending-up' : 'mdi:trending-down';

  return (
    <Card variant="default" padding="md" className="kpi-card">
      <div className="kpi-card-header">
        <Icon icon={icon} width={20} style={{ color }} />
        <span className="kpi-card-title">{title}</span>
      </div>

      <div className="kpi-card-value" style={{ color }}>
        {value}
      </div>

      {subtitle && (
        <div className="kpi-card-subtitle">{subtitle}</div>
      )}

      {trend !== undefined && trend !== 0 && (
        <div className="kpi-card-trend" style={{ color: trendColor }}>
          <Icon icon={trendIcon} width={14} />
          <span>{Math.abs(trend).toFixed(1)}% vs prev</span>
        </div>
      )}
    </Card>
  );
};

export default KPICard;
