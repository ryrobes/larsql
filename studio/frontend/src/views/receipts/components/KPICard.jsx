import React, { memo } from 'react';
import { Icon } from '@iconify/react';
import './KPICard.css';

/**
 * KPICard - Value-first vertical metric display
 * Value prominently at top, label/icon below
 */
const KPICard = ({ title, value, subtitle, trend, icon, color = '#00e5ff' }) => {
  const trendColor = trend > 0 ? '#ff006e' : trend < 0 ? '#34d399' : '#64748b';
  const trendIcon = trend > 0 ? 'mdi:trending-up' : 'mdi:trending-down';

  return (
    <div className="kpi-card">
      <div className="kpi-value-row">
        <span className="kpi-value" style={{ color }}>{value}</span>
        {trend !== undefined && trend !== 0 && (
          <div className="kpi-trend" style={{ color: trendColor }}>
            <Icon icon={trendIcon} width={12} />
            <span>{Math.abs(trend).toFixed(0)}%</span>
          </div>
        )}
      </div>
      <div className="kpi-label-row">
        <Icon icon={icon} width={12} style={{ color: '#475569' }} />
        <span className="kpi-label">{title}</span>
        {subtitle && <span className="kpi-unit">{subtitle}</span>}
      </div>
    </div>
  );
};

export default memo(KPICard);
