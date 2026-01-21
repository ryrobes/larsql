import React, { useMemo, useRef, useEffect, useState } from 'react';
import './SparklinePanel.css';

/**
 * SparklinePanel - Renders a sparkline chart with optional metric display
 *
 * SQL format (array in single row):
 * SELECT
 *   'sparkline' as format,
 *   [12, 15, 18, 14, 22, 19, 25] as values,  -- array of numbers
 *   'Revenue Trend' as label,                 -- optional label
 *   '$1.2M' as metric,                        -- optional big number to display
 *   'line' as type,                           -- optional: 'line', 'bar', 'area'
 *   '#00e5ff' as color                        -- optional color
 *
 * OR data-driven format (multiple rows):
 * SELECT
 *   'sparkline' as format,
 *   month as x,        -- optional x label
 *   revenue as value   -- y value
 * FROM monthly_data
 * ORDER BY month
 *
 * @param {array} content - Sparkline configuration
 */
const SparklinePanel = ({ content }) => {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 200, height: 60 });

  // Extract sparkline config from content
  const config = useMemo(() => {
    if (!Array.isArray(content) || content.length === 0) {
      return { values: [] };
    }

    // Single row with values array
    if (content.length === 1 && content[0].values) {
      return content[0];
    }

    // Multiple rows - extract values from 'value' column
    if (content.length > 1 || (content.length === 1 && content[0].value !== undefined)) {
      const values = content.map(row => {
        const val = row.value ?? row.y ?? row.v;
        return typeof val === 'number' ? val : parseFloat(val) || 0;
      });
      return {
        values,
        label: content[0].label,
        metric: content[0].metric,
        type: content[0].type,
        color: content[0].color
      };
    }

    return { values: [] };
  }, [content]);

  const {
    values = [],
    label,
    metric,
    type = 'line',
    color = '#00e5ff'
  } = config;

  // Parse values if string (e.g., "[1,2,3]")
  const parsedValues = useMemo(() => {
    if (Array.isArray(values)) {
      return values.map(v => typeof v === 'number' ? v : parseFloat(v) || 0);
    }
    if (typeof values === 'string') {
      try {
        const parsed = JSON.parse(values);
        return Array.isArray(parsed) ? parsed.map(v => parseFloat(v) || 0) : [];
      } catch {
        return [];
      }
    }
    return [];
  }, [values]);

  // Calculate trend
  const trend = useMemo(() => {
    if (parsedValues.length < 2) return null;
    const first = parsedValues[0];
    const last = parsedValues[parsedValues.length - 1];
    if (first === 0) return null;
    const change = ((last - first) / Math.abs(first)) * 100;
    return {
      direction: change >= 0 ? 'up' : 'down',
      percent: Math.abs(change).toFixed(1)
    };
  }, [parsedValues]);

  // Observe container size
  useEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDimensions({
        width: Math.max(100, width - 32),
        height: Math.max(40, Math.min(80, height - (metric ? 60 : 30)))
      });
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [metric]);

  // Generate SVG path
  const pathData = useMemo(() => {
    if (parsedValues.length < 2) return null;

    const { width, height } = dimensions;
    const padding = 2;
    const chartWidth = width - padding * 2;
    const chartHeight = height - padding * 2;

    const min = Math.min(...parsedValues);
    const max = Math.max(...parsedValues);
    const range = max - min || 1;

    const points = parsedValues.map((val, i) => {
      const x = padding + (i / (parsedValues.length - 1)) * chartWidth;
      const y = padding + chartHeight - ((val - min) / range) * chartHeight;
      return { x, y };
    });

    if (type === 'bar') {
      const barWidth = chartWidth / parsedValues.length * 0.8;
      const gap = chartWidth / parsedValues.length * 0.2;
      return {
        type: 'bar',
        bars: parsedValues.map((val, i) => {
          const barHeight = ((val - min) / range) * chartHeight;
          return {
            x: padding + i * (barWidth + gap),
            y: padding + chartHeight - barHeight,
            width: barWidth,
            height: barHeight
          };
        })
      };
    }

    // Line or area
    const linePath = points.map((p, i) =>
      i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`
    ).join(' ');

    if (type === 'area') {
      const areaPath = linePath +
        ` L ${points[points.length - 1].x} ${padding + chartHeight}` +
        ` L ${points[0].x} ${padding + chartHeight} Z`;
      return { type: 'area', linePath, areaPath, points };
    }

    return { type: 'line', linePath, points };
  }, [parsedValues, dimensions, type]);

  if (parsedValues.length === 0) {
    return (
      <div className="sparkline-panel">
        <div className="sparkline-panel-empty">No data</div>
      </div>
    );
  }

  return (
    <div className="sparkline-panel" ref={containerRef}>
      <div className="sparkline-panel-content">
        {/* Metric display */}
        {metric && (
          <div className="sparkline-panel-metric" style={{ color }}>
            {metric}
            {trend && (
              <span className={`sparkline-panel-trend sparkline-panel-trend-${trend.direction}`}>
                {trend.direction === 'up' ? '↑' : '↓'} {trend.percent}%
              </span>
            )}
          </div>
        )}

        {/* Sparkline SVG */}
        <svg
          ref={svgRef}
          className="sparkline-panel-svg"
          width={dimensions.width}
          height={dimensions.height}
          viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        >
          {pathData?.type === 'bar' && pathData.bars.map((bar, i) => (
            <rect
              key={i}
              x={bar.x}
              y={bar.y}
              width={bar.width}
              height={bar.height}
              fill={color}
              opacity={0.8}
              rx={1}
            />
          ))}

          {pathData?.type === 'area' && (
            <>
              <path
                d={pathData.areaPath}
                fill={color}
                fillOpacity={0.2}
              />
              <path
                d={pathData.linePath}
                fill="none"
                stroke={color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </>
          )}

          {pathData?.type === 'line' && (
            <>
              <path
                d={pathData.linePath}
                fill="none"
                stroke={color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {/* End point dot */}
              {pathData.points && (
                <circle
                  cx={pathData.points[pathData.points.length - 1].x}
                  cy={pathData.points[pathData.points.length - 1].y}
                  r={3}
                  fill={color}
                />
              )}
            </>
          )}
        </svg>

        {/* Label */}
        {label && <div className="sparkline-panel-label">{label}</div>}
      </div>
    </div>
  );
};

export default SparklinePanel;
