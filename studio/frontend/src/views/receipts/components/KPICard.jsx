import React, { memo } from 'react';
import { Icon } from '@iconify/react';
import './KPICard.css';

/**
 * KPICard - Flat, inline metric display
 * Data-dense design without card wrapper
 */
const KPICard = ({ title, value, subtitle, trend, icon, color = '#00e5ff' }) => {
  const trendColor = trend > 0 ? '#ff006e' : trend < 0 ? '#34d399' : '#64748b';
  const trendIcon = trend > 0 ? 'mdi:trending-up' : 'mdi:trending-down';

  return (
    <div className="kpi-card">
      <div className="kpi-icon">
        <Icon icon={icon} width={14} style={{ color: '#475569' }} />
      </div>
      <div className="kpi-content">
        <span className="kpi-label">{title}</span>
        <span className="kpi-value" style={{ color }}>{value}</span>
        {subtitle && <span className="kpi-unit">{subtitle}</span>}
      </div>
      {trend !== undefined && trend !== 0 && (
        <div className="kpi-trend" style={{ color: trendColor }}>
          <Icon icon={trendIcon} width={12} />
          <span>{Math.abs(trend).toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
};

export default memo(KPICard);
