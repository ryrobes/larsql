import React, { memo } from 'react';
import { Icon } from '@iconify/react';
import './KPICard.css';

/**
 * KPICard - Flat, inline metric display
 * Matches ReceiptsView styling
 */
const KPICard = ({ title, value, subtitle, trend, icon, color = '#00e5ff' }) => {
  const trendColor = trend > 0 ? '#ff006e' : trend < 0 ? '#34d399' : '#64748b';
  const trendIcon = trend > 0 ? 'mdi:trending-up' : 'mdi:trending-down';

  return (
    <div className="training-kpi-card">
      <div className="training-kpi-icon">
        <Icon icon={icon} width={14} style={{ color: '#475569' }} />
      </div>
      <div className="training-kpi-content">
        <span className="training-kpi-label">{title}</span>
        <span className="training-kpi-value" style={{ color }}>{value}</span>
        {subtitle && <span className="training-kpi-unit">{subtitle}</span>}
      </div>
      {trend !== undefined && trend !== 0 && (
        <div className="training-kpi-trend" style={{ color: trendColor }}>
          <Icon icon={trendIcon} width={12} />
          <span>{Math.abs(trend).toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
};

export default memo(KPICard);
