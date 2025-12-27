import React from 'react';
import { Icon } from '@iconify/react';
import './MetricsCards.css';

function MetricsCards({ instance }) {
  if (!instance) return null;

  // Calculate metrics
  const totalCost = instance.total_cost || 0;
  const totalTime = instance.duration_seconds || 0;
  const toolCount = instance.cells?.reduce((sum, p) => sum + (p.tool_calls?.length || 0), 0) || 0;
  const wardCount = instance.cells?.reduce((sum, p) => sum + (p.ward_count || 0), 0) || 0;
  const soundingCount = instance.cells?.reduce((sum, p) => sum + (p.sounding_attempts?.length || 0), 0) || 0;
  const totalTokens = (instance.total_tokens_in || 0) + (instance.total_tokens_out || 0);

  // Only show metrics that are applicable (non-zero)
  const metrics = [];

  // Cost is always shown
  metrics.push({
    icon: 'mdi:currency-usd',
    label: 'Total Cost',
    value: `$${totalCost.toFixed(4)}`,
    color: '#34d399'
  });

  // Time (if available)
  if (totalTime > 0) {
    const minutes = Math.floor(totalTime / 60);
    const seconds = Math.floor(totalTime % 60);
    const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;

    metrics.push({
      icon: 'mdi:clock-outline',
      label: 'Duration',
      value: timeStr,
      color: '#60a5fa'
    });
  }

  // Tool calls (if any)
  if (toolCount > 0) {
    metrics.push({
      icon: 'mdi:hammer-wrench',
      label: 'Tools',
      value: toolCount,
      color: '#f472b6'
    });
  }

  // Wards (if any)
  if (wardCount > 0) {
    metrics.push({
      icon: 'mdi:shield-alert',
      label: 'Wards',
      value: wardCount,
      color: '#fbbf24'
    });
  }

  // Soundings (if any)
  if (soundingCount > 0) {
    metrics.push({
      icon: 'mdi:chart-tree',
      label: 'Soundings',
      value: soundingCount,
      color: '#fb923c'
    });
  }

  // Tokens (if available)
  if (totalTokens > 0) {
    metrics.push({
      icon: 'mdi:counter',
      label: 'Tokens',
      value: totalTokens.toLocaleString(),
      color: '#a78bfa'
    });
  }

  // Models (if multiple)
  if (instance.models_used && instance.models_used.length > 0) {
    metrics.push({
      icon: 'mdi:robot',
      label: 'Models',
      value: instance.models_used.length,
      color: '#2dd4bf'
    });
  }

  // Error count (if any)
  if (instance.error_count > 0) {
    metrics.push({
      icon: 'mdi:alert-circle',
      label: 'Errors',
      value: instance.error_count,
      color: '#f87171'
    });
  }

  return (
    <div className="metrics-section">
      <h3 className="section-title">
        <Icon icon="mdi:chart-box" width="20" />
        Metrics
      </h3>
      <div className="metrics-grid" style={{ gridTemplateColumns: `repeat(${Math.min(metrics.length, 4)}, 1fr)` }}>
        {metrics.map((metric, idx) => (
          <div key={idx} className="metric-card">
            <div className="metric-icon" style={{ color: metric.color }}>
              <Icon icon={metric.icon} width="24" />
            </div>
            <div className="metric-value">{metric.value}</div>
            <div className="metric-label">{metric.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default React.memo(MetricsCards);
