import React from 'react';

/**
 * TokenSparkline - Lightweight SVG sparkline showing token usage trends
 * Displays tokens_in and tokens_out as two lines
 */
function TokenSparkline({ data, width = 60, height = 30 }) {
  if (!data || data.length === 0) {
    return <div style={{ width, height }} />;
  }

  // Extract max values for scaling
  const maxTokensIn = Math.max(...data.map(d => d.tokens_in || 0));
  const maxTokensOut = Math.max(...data.map(d => d.tokens_out || 0));
  const maxValue = Math.max(maxTokensIn, maxTokensOut, 1); // Avoid division by zero

  // Create SVG path data
  const padding = 2;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const createPath = (values) => {
    if (values.length === 0) return '';

    const points = values.map((value, index) => {
      const x = padding + (index / (values.length - 1 || 1)) * chartWidth;
      const y = padding + chartHeight - (value / maxValue) * chartHeight;
      return `${x},${y}`;
    });

    return `M ${points.join(' L ')}`;
  };

  const tokensInPath = createPath(data.map(d => d.tokens_in || 0));
  const tokensOutPath = createPath(data.map(d => d.tokens_out || 0));

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {/* Tokens In - Glacial Ice */}
      <path
        d={tokensInPath}
        fill="none"
        stroke="#2DD4BF"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* Tokens Out - Compass Brass */}
      <path
        d={tokensOutPath}
        fill="none"
        stroke="#D9A553"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default TokenSparkline;
