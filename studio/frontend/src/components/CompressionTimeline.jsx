import React, { useRef, useEffect, useMemo } from 'react';
import './CompressionTimeline.css';

const CompressionTimeline = ({ turns, config, height = 200 }) => {
  const canvasRef = useRef(null);

  // Find matching config data for each turn
  const dataPoints = useMemo(() => {
    if (!turns || turns.length === 0) return [];

    return turns.map(turn => {
      const matchingConfig = turn.configs?.find(c =>
        c.window === config.window &&
        c.mask_after === config.mask_after &&
        c.min_size === config.min_size
      );
      return {
        turn: turn.turn_number,
        before: matchingConfig?.tokens_before || turn.full_history_size || 0,
        after: matchingConfig?.tokens_after || turn.full_history_size || 0,
        saved: matchingConfig?.tokens_saved || 0,
        ratio: matchingConfig?.compression_ratio || 1
      };
    }).sort((a, b) => a.turn - b.turn);
  }, [turns, config]);

  // Calculate totals for summary
  const totals = useMemo(() => {
    const totalBefore = dataPoints.reduce((sum, d) => sum + d.before, 0);
    const totalAfter = dataPoints.reduce((sum, d) => sum + d.after, 0);
    const totalSaved = totalBefore - totalAfter;
    const avgRatio = totalBefore > 0 ? totalAfter / totalBefore : 1;
    return { totalBefore, totalAfter, totalSaved, avgRatio };
  }, [dataPoints]);

  useEffect(() => {
    if (!canvasRef.current || dataPoints.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Setup canvas dimensions
    const rect = canvas.getBoundingClientRect();
    const width = rect.width;
    const canvasHeight = height;
    canvas.width = width * dpr;
    canvas.height = canvasHeight * dpr;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, width, canvasHeight);

    // Margins
    const margin = { top: 20, right: 20, bottom: 35, left: 55 };
    const chartWidth = width - margin.left - margin.right;
    const chartHeight = canvasHeight - margin.top - margin.bottom;

    // Scales
    const maxTokens = Math.max(...dataPoints.flatMap(d => [d.before, d.after]), 1000);
    const xScale = (index) => margin.left + (index / Math.max(dataPoints.length - 1, 1)) * chartWidth;
    const yScale = (tokens) => margin.top + chartHeight - (tokens / maxTokens) * chartHeight;

    // Grid lines
    ctx.strokeStyle = '#1e1e24';
    ctx.lineWidth = 1;
    const gridLines = 4;
    for (let i = 0; i <= gridLines; i++) {
      const y = margin.top + (i / gridLines) * chartHeight;
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(width - margin.right, y);
      ctx.stroke();
    }

    // Fill area between lines (savings area)
    if (dataPoints.length > 1) {
      ctx.beginPath();
      ctx.fillStyle = 'rgba(0, 229, 255, 0.1)';
      dataPoints.forEach((d, i) => {
        if (i === 0) ctx.moveTo(xScale(i), yScale(d.before));
        else ctx.lineTo(xScale(i), yScale(d.before));
      });
      for (let i = dataPoints.length - 1; i >= 0; i--) {
        ctx.lineTo(xScale(i), yScale(dataPoints[i].after));
      }
      ctx.closePath();
      ctx.fill();
    }

    // Draw "Before" line (dashed)
    ctx.beginPath();
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    dataPoints.forEach((d, i) => {
      if (i === 0) ctx.moveTo(xScale(i), yScale(d.before));
      else ctx.lineTo(xScale(i), yScale(d.before));
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw "After" line (solid)
    ctx.beginPath();
    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 2;
    dataPoints.forEach((d, i) => {
      if (i === 0) ctx.moveTo(xScale(i), yScale(d.after));
      else ctx.lineTo(xScale(i), yScale(d.after));
    });
    ctx.stroke();

    // Draw points
    dataPoints.forEach((d, i) => {
      // Before point
      ctx.beginPath();
      ctx.fillStyle = '#64748b';
      ctx.arc(xScale(i), yScale(d.before), 3, 0, Math.PI * 2);
      ctx.fill();

      // After point
      ctx.beginPath();
      ctx.fillStyle = '#00e5ff';
      ctx.arc(xScale(i), yScale(d.after), 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.strokeStyle = '#00e5ff';
      ctx.lineWidth = 2;
      ctx.arc(xScale(i), yScale(d.after), 4, 0, Math.PI * 2);
      ctx.stroke();
    });

    // Axes
    ctx.strokeStyle = '#2a2a32';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, canvasHeight - margin.bottom);
    ctx.lineTo(width - margin.right, canvasHeight - margin.bottom);
    ctx.stroke();

    // Y-axis labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Inter, system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= gridLines; i++) {
      const tokenValue = Math.round(maxTokens * (1 - i / gridLines));
      const y = margin.top + (i / gridLines) * chartHeight;
      ctx.fillText(tokenValue >= 1000 ? `${(tokenValue / 1000).toFixed(1)}k` : tokenValue.toString(), margin.left - 8, y);
    }

    // X-axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const labelStep = Math.max(1, Math.floor(dataPoints.length / 8));
    dataPoints.forEach((d, i) => {
      if (i % labelStep === 0 || i === dataPoints.length - 1) {
        ctx.fillText(`T${d.turn}`, xScale(i), canvasHeight - margin.bottom + 8);
      }
    });

    // Axis titles
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Turn', width / 2, canvasHeight - 5);

    ctx.save();
    ctx.translate(12, canvasHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Tokens', 0, 0);
    ctx.restore();

  }, [dataPoints, height]);

  if (dataPoints.length === 0) {
    return (
      <div className="compression-timeline empty">
        <span>No compression data available for this configuration</span>
      </div>
    );
  }

  const savingsPercent = totals.totalBefore > 0
    ? Math.round((1 - totals.avgRatio) * 100)
    : 0;

  return (
    <div className="compression-timeline">
      <div className="timeline-header">
        <div className="timeline-legend">
          <span className="legend-item before">
            <span className="legend-line dashed"></span>
            Before
          </span>
          <span className="legend-item after">
            <span className="legend-line solid"></span>
            After (w={config.window}, m={config.mask_after})
          </span>
        </div>
        <div className="timeline-summary">
          <span className="summary-savings">
            {savingsPercent}% savings
          </span>
          <span className="summary-tokens">
            {totals.totalSaved.toLocaleString()} tokens saved
          </span>
        </div>
      </div>
      <canvas ref={canvasRef} style={{ width: '100%', height }} />
    </div>
  );
};

export default CompressionTimeline;
