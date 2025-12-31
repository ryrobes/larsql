import React, { useRef, useEffect, useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './WasteScatterPlot.css';

const WasteScatterPlot = ({ sessionId, onMessageSelect }) => {
  const canvasRef = useRef(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [threshold, setThreshold] = useState(40);

  // Fetch scatter data
  useEffect(() => {
    if (!sessionId) return;

    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/relevance-scatter/${sessionId}`
        );
        if (!res.ok) throw new Error('Failed to fetch scatter data');
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [sessionId]);

  // Calculate waste stats
  const wasteStats = useMemo(() => {
    if (!data?.messages) return null;

    const wasteMessages = data.messages.filter(
      m => m.was_included && m.composite_score < threshold
    );
    const wasteTokens = wasteMessages.reduce((sum, m) => sum + m.tokens, 0);
    const totalTokens = data.messages.reduce((sum, m) => sum + m.tokens, 0);

    return {
      wasteCount: wasteMessages.length,
      wasteTokens,
      wastePct: totalTokens > 0 ? (wasteTokens / totalTokens * 100) : 0,
      estimatedSavings: wasteTokens * 0.000003 // ~$3 per 1M tokens
    };
  }, [data, threshold]);

  // Draw scatter plot
  useEffect(() => {
    if (!canvasRef.current || !data?.messages?.length) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const rect = canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, width, height);

    // Margins
    const margin = { top: 30, right: 30, bottom: 50, left: 60 };
    const chartWidth = width - margin.left - margin.right;
    const chartHeight = height - margin.top - margin.bottom;

    // Scales
    const maxTokens = Math.max(...data.messages.map(m => m.tokens), 100);
    const xScale = (tokens) => margin.left + (tokens / maxTokens) * chartWidth;
    const yScale = (score) => margin.top + chartHeight - (score / 100) * chartHeight;

    // Draw waste zone background
    ctx.fillStyle = 'rgba(248, 113, 113, 0.08)';
    ctx.fillRect(
      margin.left,
      yScale(threshold),
      chartWidth,
      chartHeight - (chartHeight - (yScale(threshold) - margin.top))
    );

    // Draw threshold line
    ctx.strokeStyle = 'rgba(248, 113, 113, 0.5)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(margin.left, yScale(threshold));
    ctx.lineTo(width - margin.right, yScale(threshold));
    ctx.stroke();
    ctx.setLineDash([]);

    // Threshold label
    ctx.fillStyle = '#f87171';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`Waste threshold: ${threshold}`, width - margin.right - 5, yScale(threshold) - 5);

    // Grid lines
    ctx.strokeStyle = '#1e1e24';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = margin.top + (i / 4) * chartHeight;
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(width - margin.right, y);
      ctx.stroke();
    }

    // Draw points
    data.messages.forEach((msg, idx) => {
      const x = xScale(msg.tokens);
      const y = yScale(msg.composite_score);
      const isWaste = msg.was_included && msg.composite_score < threshold;
      const isHovered = hoveredPoint === idx;

      // Point size based on tokens
      const baseRadius = Math.max(3, Math.min(8, msg.tokens / 200));
      const radius = isHovered ? baseRadius + 2 : baseRadius;

      // Color based on status
      let color;
      if (isWaste) {
        color = 'rgba(248, 113, 113, 0.8)'; // Red for waste
      } else if (msg.was_included) {
        color = 'rgba(52, 211, 153, 0.7)'; // Green for included, high relevance
      } else {
        color = 'rgba(100, 116, 139, 0.5)'; // Gray for excluded
      }

      ctx.beginPath();
      ctx.fillStyle = color;
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();

      if (isHovered) {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    });

    // Axes
    ctx.strokeStyle = '#2a2a32';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, height - margin.bottom);
    ctx.lineTo(width - margin.right, height - margin.bottom);
    ctx.stroke();

    // Y-axis labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const score = 100 - i * 25;
      const y = margin.top + (i / 4) * chartHeight;
      ctx.fillText(score.toString(), margin.left - 8, y);
    }

    // X-axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= 4; i++) {
      const tokens = Math.round(maxTokens * i / 4);
      const x = margin.left + (i / 4) * chartWidth;
      ctx.fillText(tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : tokens.toString(), x, height - margin.bottom + 8);
    }

    // Axis titles
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Tokens (Cost)', width / 2, height - 10);

    ctx.save();
    ctx.translate(15, height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Relevance Score', 0, 0);
    ctx.restore();

  }, [data, hoveredPoint, threshold]);

  // Handle mouse move for hover
  const handleMouseMove = (e) => {
    if (!data?.messages?.length || !canvasRef.current) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const margin = { top: 30, right: 30, bottom: 50, left: 60 };
    const chartWidth = rect.width - margin.left - margin.right;
    const chartHeight = rect.height - margin.top - margin.bottom;
    const maxTokens = Math.max(...data.messages.map(m => m.tokens), 100);

    // Find closest point
    let closestIdx = null;
    let closestDist = 20; // Max detection distance

    data.messages.forEach((msg, idx) => {
      const px = margin.left + (msg.tokens / maxTokens) * chartWidth;
      const py = margin.top + chartHeight - (msg.composite_score / 100) * chartHeight;
      const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
      if (dist < closestDist) {
        closestDist = dist;
        closestIdx = idx;
      }
    });

    setHoveredPoint(closestIdx);
  };

  const handleClick = () => {
    if (hoveredPoint !== null && onMessageSelect) {
      onMessageSelect(data.messages[hoveredPoint]);
    }
  };

  if (loading) {
    return (
      <div className="waste-scatter loading">
        <Icon icon="mdi:loading" className="spin" width={24} />
        <span>Loading scatter data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="waste-scatter error">
        <Icon icon="mdi:alert-circle" width={24} />
        <span>{error}</span>
      </div>
    );
  }

  if (!data?.messages?.length) {
    return (
      <div className="waste-scatter empty">
        <Icon icon="mdi:scatter-plot" width={32} />
        <span>No message data available for scatter plot</span>
      </div>
    );
  }

  const hoveredMsg = hoveredPoint !== null ? data.messages[hoveredPoint] : null;

  return (
    <div className="waste-scatter">
      <div className="scatter-header">
        <div className="header-left">
          <h4>Relevance vs. Cost Analysis</h4>
          <p>Identify waste: high-cost messages with low relevance</p>
        </div>
        <div className="threshold-control">
          <label>Waste threshold:</label>
          <input
            type="range"
            min={10}
            max={70}
            value={threshold}
            onChange={(e) => setThreshold(parseInt(e.target.value))}
          />
          <span>{threshold}</span>
        </div>
      </div>

      {wasteStats && (
        <div className="waste-summary">
          <div className="summary-item waste">
            <Icon icon="mdi:alert-circle" width={16} />
            <span className="value">{wasteStats.wasteCount}</span>
            <span className="label">waste messages</span>
          </div>
          <div className="summary-item tokens">
            <Icon icon="mdi:text" width={16} />
            <span className="value">{wasteStats.wasteTokens.toLocaleString()}</span>
            <span className="label">wasted tokens</span>
          </div>
          <div className="summary-item pct">
            <Icon icon="mdi:percent" width={16} />
            <span className="value">{wasteStats.wastePct.toFixed(1)}%</span>
            <span className="label">of context</span>
          </div>
          <div className="summary-item savings">
            <Icon icon="mdi:currency-usd" width={16} />
            <span className="value">${wasteStats.estimatedSavings.toFixed(4)}</span>
            <span className="label">potential savings</span>
          </div>
        </div>
      )}

      <div className="scatter-container">
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredPoint(null)}
          onClick={handleClick}
          style={{ width: '100%', height: 300, cursor: hoveredPoint !== null ? 'pointer' : 'default' }}
        />
      </div>

      {hoveredMsg && (
        <div className="hover-tooltip">
          <div className="tooltip-role">
            <span className={`role-badge ${hoveredMsg.role}`}>{hoveredMsg.role}</span>
            <span className="source">from {hoveredMsg.source_cell}</span>
          </div>
          <div className="tooltip-stats">
            <span><strong>{hoveredMsg.tokens}</strong> tokens</span>
            <span><strong>{Math.round(hoveredMsg.composite_score)}</strong> relevance</span>
            <span className={hoveredMsg.was_included ? 'included' : 'excluded'}>
              {hoveredMsg.was_included ? 'Included' : 'Excluded'}
            </span>
          </div>
          <div className="tooltip-preview">{hoveredMsg.preview}</div>
        </div>
      )}

      <div className="scatter-legend">
        <span className="legend-item included">
          <span className="dot"></span> High relevance (keep)
        </span>
        <span className="legend-item waste">
          <span className="dot"></span> Low relevance (waste)
        </span>
        <span className="legend-item excluded">
          <span className="dot"></span> Already excluded
        </span>
      </div>
    </div>
  );
};

export default WasteScatterPlot;
