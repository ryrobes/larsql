import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import './RunPercentile.css';

function RunPercentile({ instance, allInstances }) {
  // Calculate percentiles for this instance vs all instances
  const percentiles = useMemo(() => {
    if (!instance || !allInstances || allInstances.length < 2) {
      return null;
    }

    // Filter to only instances with valid numeric data (cost or duration > 0)
    const validInstances = allInstances.filter(i =>
      (i.total_cost != null && i.total_cost > 0) ||
      (i.duration_seconds != null && i.duration_seconds > 0)
    );

    if (validInstances.length < 2) return null;

    // Check if current instance has valid data
    const hasValidCost = instance.total_cost != null && instance.total_cost > 0;
    const hasValidDuration = instance.duration_seconds != null && instance.duration_seconds > 0;
    if (!hasValidCost && !hasValidDuration) return null;

    // Calculate percentile for a value in a sorted array (lower is better for cost/duration)
    const calculatePercentile = (value, allValues, lowerIsBetter = true) => {
      const sorted = [...allValues].sort((a, b) => a - b);
      const rank = sorted.findIndex(v => v >= value);
      const percentile = ((rank + 1) / sorted.length) * 100;
      return lowerIsBetter ? percentile : 100 - percentile;
    };

    const costs = validInstances.map(i => i.total_cost || 0);
    const durations = validInstances.map(i => i.duration_seconds || 0);
    const tokensOut = validInstances.map(i => i.total_tokens_out || 0);

    const costPercentile = calculatePercentile(instance.total_cost || 0, costs, true);
    const durationPercentile = calculatePercentile(instance.duration_seconds || 0, durations, true);
    const tokensPercentile = calculatePercentile(instance.total_tokens_out || 0, tokensOut, false);

    // Calculate averages for comparison
    const avgCost = costs.reduce((a, b) => a + b, 0) / costs.length;
    const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length;

    const costVsAvg = avgCost > 0 ? (((instance.total_cost || 0) - avgCost) / avgCost) * 100 : 0;
    const durationVsAvg = avgDuration > 0 ? (((instance.duration_seconds || 0) - avgDuration) / avgDuration) * 100 : 0;

    return {
      cost: {
        percentile: costPercentile,
        vsAvg: costVsAvg,
        label: costPercentile <= 25 ? 'Low' : costPercentile <= 75 ? 'Avg' : 'High'
      },
      duration: {
        percentile: durationPercentile,
        vsAvg: durationVsAvg,
        label: durationPercentile <= 25 ? 'Fast' : durationPercentile <= 75 ? 'Avg' : 'Slow'
      },
      tokens: {
        percentile: tokensPercentile,
        label: tokensPercentile >= 75 ? 'High' : tokensPercentile >= 25 ? 'Avg' : 'Low'
      },
      totalRuns: validInstances.length
    };
  }, [instance, allInstances]);

  if (!percentiles) {
    return null;
  }

  const getPercentileColor = (percentile, lowerIsBetter = true) => {
    const effective = lowerIsBetter ? percentile : 100 - percentile;
    if (effective <= 25) return '#34d399'; // Green - good
    if (effective <= 75) return '#60a5fa'; // Blue - average
    return '#f87171'; // Red - needs attention
  };

  const formatVsAvg = (vsAvg) => {
    if (Math.abs(vsAvg) < 1) return '~avg';
    const sign = vsAvg > 0 ? '+' : '';
    return `${sign}${vsAvg.toFixed(0)}%`;
  };

  return (
    <div className="run-percentile">
      <div className="percentile-header">
        <Icon icon="mdi:chart-box-outline" width="14" />
        <span>vs {percentiles.totalRuns} runs</span>
      </div>

      {/* Cost Percentile */}
      <div className="percentile-row">
        <div className="percentile-label">
          <Icon icon="mdi:currency-usd" width="12" />
          <span>Cost</span>
        </div>
        <div className="percentile-bar-container">
          <div className="percentile-bar-track">
            <div
              className="percentile-bar-marker"
              style={{
                left: `${percentiles.cost.percentile}%`,
                backgroundColor: getPercentileColor(percentiles.cost.percentile, true)
              }}
            />
          </div>
        </div>
        <div
          className="percentile-value"
          style={{ color: getPercentileColor(percentiles.cost.percentile, true) }}
        >
          {formatVsAvg(percentiles.cost.vsAvg)}
        </div>
      </div>

      {/* Duration Percentile */}
      <div className="percentile-row">
        <div className="percentile-label">
          <Icon icon="mdi:timer-outline" width="12" />
          <span>Time</span>
        </div>
        <div className="percentile-bar-container">
          <div className="percentile-bar-track">
            <div
              className="percentile-bar-marker"
              style={{
                left: `${percentiles.duration.percentile}%`,
                backgroundColor: getPercentileColor(percentiles.duration.percentile, true)
              }}
            />
          </div>
        </div>
        <div
          className="percentile-value"
          style={{ color: getPercentileColor(percentiles.duration.percentile, true) }}
        >
          {formatVsAvg(percentiles.duration.vsAvg)}
        </div>
      </div>

      {/* Legend */}
      <div className="percentile-legend">
        <span className="legend-low">Best</span>
        <span className="legend-high">Worst</span>
      </div>
    </div>
  );
}

export default RunPercentile;
