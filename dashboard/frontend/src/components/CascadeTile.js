import React, { useState, useEffect } from 'react';
import mermaid from 'mermaid';
import { Icon } from '@iconify/react';
import './CascadeTile.css';

// Initialize mermaid with Midnight Fjord theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background: 'transparent',
    primaryColor: '#2DD4BF',      // Glacial Ice
    primaryTextColor: '#F0F4F8',  // Frosted White
    primaryBorderColor: '#2DD4BF',
    lineColor: '#2C3B4B',         // Storm Cloud
    secondaryColor: '#D9A553',    // Compass Brass
    tertiaryColor: '#a78bfa',     // Purple
    nodePadding: 12,              // Padding inside nodes
    nodeTextColor: '#F0F4F8',     // Text color
  },
  flowchart: {
    useMaxWidth: false,
    htmlLabels: true,
    padding: 16,                  // Padding around flowchart
    nodeSpacing: 50,              // Space between nodes
    rankSpacing: 50,              // Space between ranks
  }
});

/**
 * Calculate tile dimensions based on cascade complexity
 * NEW LAYOUT: Title on top, mermaid on left, metrics column on right
 * @param {Object} cascade - Cascade definition with phases and graph_complexity
 * @returns {Object} - {w, h} in pixels (potpack format)
 */
export function calculateTileDimensions(cascade) {
  const TITLE_HEIGHT = 50; // Fixed height for title + description at top
  const METRICS_WIDTH = 70; // Fixed width for metrics column on right (compact)
  const METRICS_GAP = 16; // Gap between mermaid and metrics
  const PADDING = 20; // Padding around everything
  const GAP = 12; // Gap between tiles

  const hasRuns = cascade.metrics?.run_count > 0;

  // Cascades without runs get varied sizes for more interesting packing
  if (!hasRuns) {
    // Add variety based on phase count or cascade_id hash
    const phaseCount = cascade.phases?.length || 0;
    const hash = cascade.cascade_id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);

    // Generate varied sizes (200-350px)
    const variance = (hash % 150); // 0-149
    const size = 200 + variance + (phaseCount * 10);

    return {
      w: size + GAP,
      h: size + GAP
    };
  }

  // Estimate mermaid diagram size based on graph complexity
  let mermaidWidth, mermaidHeight;

  if (cascade.graph_complexity) {
    // Use actual graph node count to estimate size
    const nodeCount = cascade.graph_complexity.total_nodes || 10;
    const phaseCount = cascade.graph_complexity.total_phases || 2;

    // Base estimation: each phase adds width, each node adds height
    // Mermaid diagrams are typically wide (phases horizontal) and tall (nodes vertical)
    const baseWidth = 400 + (phaseCount * 200);
    const baseHeight = 300 + (nodeCount * 30);

    // Apply 0.5 scale factor (mermaid diagrams are big)
    mermaidWidth = baseWidth * 0.5;
    mermaidHeight = baseHeight * 0.5;

    // Clamp to reasonable bounds
    mermaidWidth = Math.min(Math.max(mermaidWidth, 300), 800);
    mermaidHeight = Math.min(Math.max(mermaidHeight, 250), 600);
  } else {
    // Fallback: estimate from phase count
    const numPhases = cascade.phases?.length || 2;
    mermaidWidth = 400 + (numPhases * 100);
    mermaidHeight = 300 + (numPhases * 50);

    // Apply 0.5 scale
    mermaidWidth *= 0.5;
    mermaidHeight *= 0.5;

    // Clamp
    mermaidWidth = Math.min(Math.max(mermaidWidth, 300), 800);
    mermaidHeight = Math.min(Math.max(mermaidHeight, 250), 600);
  }

  // Calculate final box dimensions
  // NEW LAYOUT: Width = padding + mermaid + gap + metrics + padding
  //             Height = padding + title(40) + mermaid + padding
  const boxWidth = PADDING + mermaidWidth + METRICS_GAP + METRICS_WIDTH + PADDING;
  const boxHeight = PADDING + TITLE_HEIGHT + mermaidHeight + PADDING;

  console.log(`[TILE] ${cascade.cascade_id}: mermaid=${mermaidWidth}x${mermaidHeight}, box=${boxWidth}x${boxHeight}`);

  return {
    w: boxWidth + GAP,
    h: boxHeight + GAP
  };
}

function CascadeTile({ cascade, onClick, isRunning }) {
  const [mermaidSvg, setMermaidSvg] = useState(null);
  const [mermaidError, setMermaidError] = useState(false);
  const hasRuns = cascade.metrics?.run_count > 0;

  const fetchAndRenderMermaid = React.useCallback(async () => {
    try {
      const response = await fetch(`http://localhost:5001/api/mermaid/${cascade.latest_session_id}`);
      if (!response.ok) throw new Error('Mermaid not found');

      const data = await response.json();
      const mermaidContent = data.mermaid;

      // Generate unique ID for this mermaid diagram
      const id = `mermaid-${cascade.cascade_id}-${Date.now()}`;

      // Render mermaid
      const { svg } = await mermaid.render(id, mermaidContent);

      // Apply color mutations (same as MermaidPreview.js)
      const styledSvg = applyMermaidStyling(svg);
      setMermaidSvg(styledSvg);
      setMermaidError(false);
    } catch (error) {
      console.error('Failed to render mermaid:', error);
      setMermaidError(true);
    }
  }, [cascade.latest_session_id, cascade.cascade_id]);

  const applyMermaidStyling = (svgString) => {
    // Parse SVG string
    const parser = new DOMParser();
    const svgDoc = parser.parseFromString(svgString, 'image/svg+xml');
    const svgElement = svgDoc.querySelector('svg');

    if (!svgElement) return svgString;

    // Remove any background styling from SVG
    svgElement.style.background = 'transparent';
    svgElement.style.backgroundColor = 'transparent';

    // Midnight Fjord color palette
    const colors = {
      cyan: '#2DD4BF',      // Glacial Ice - default stroke
      text: '#F0F4F8'       // Frosted White
    };

    // Remove background rects (mermaid adds these)
    const backgroundRects = svgElement.querySelectorAll('rect[class*="background"], rect:first-child');
    backgroundRects.forEach(rect => {
      const width = parseFloat(rect.getAttribute('width'));
      const height = parseFloat(rect.getAttribute('height'));
      const x = parseFloat(rect.getAttribute('x') || 0);
      const y = parseFloat(rect.getAttribute('y') || 0);

      // If it covers most of the SVG, it's probably a background
      if (x <= 10 && y <= 10 && width > 100 && height > 100) {
        rect.setAttribute('fill', 'transparent');
        rect.setAttribute('fill-opacity', '0');
        rect.setAttribute('stroke', 'none');
      }
    });

    // Make shape fills transparent but PRESERVE stroke colors from Mermaid classes
    // This keeps semantic coloring (winner=green, loser=gray, error=red, etc.)
    const allShapes = svgElement.querySelectorAll('rect, circle, polygon, ellipse');
    allShapes.forEach((shape) => {
      // Skip if we already made it transparent (background rect)
      if (shape.getAttribute('fill') === 'transparent') return;

      // Make fill transparent
      shape.setAttribute('fill', 'none');
      shape.setAttribute('fill-opacity', '0');

      // Only set stroke if none exists (preserve Mermaid class colors)
      if (!shape.getAttribute('stroke') || shape.getAttribute('stroke') === 'none') {
        shape.setAttribute('stroke', colors.cyan);
        shape.setAttribute('stroke-width', '2');
      }
    });

    // Style paths (arrows/lines) - preserve existing strokes or default to cyan
    const allPaths = svgElement.querySelectorAll('path');
    allPaths.forEach(path => {
      path.setAttribute('fill', 'none');
      // Only override if no stroke set
      if (!path.getAttribute('stroke') || path.getAttribute('stroke') === 'none') {
        path.setAttribute('stroke', colors.cyan);
        path.setAttribute('stroke-width', '2');
      }
    });

    // Style lines - preserve existing strokes
    const allLines = svgElement.querySelectorAll('line');
    allLines.forEach(line => {
      if (!line.getAttribute('stroke') || line.getAttribute('stroke') === 'none') {
        line.setAttribute('stroke', colors.cyan);
        line.setAttribute('stroke-width', '2');
      }
    });

    // Make text bright and readable
    const allText = svgElement.querySelectorAll('text, tspan');
    allText.forEach(text => {
      text.setAttribute('fill', colors.text);
      text.setAttribute('stroke', 'none');
    });

    // Style arrowheads - use cyan for visibility
    const allMarkers = svgElement.querySelectorAll('marker path, marker polygon');
    allMarkers.forEach(marker => {
      marker.setAttribute('fill', colors.cyan);
      marker.setAttribute('stroke', colors.cyan);
    });

    // Serialize back to string
    const serializer = new XMLSerializer();
    return serializer.serializeToString(svgElement);
  };

  useEffect(() => {
    // Only fetch mermaid if cascade has runs and mermaid file
    if (hasRuns && cascade.has_mermaid && cascade.latest_session_id) {
      fetchAndRenderMermaid();
    }
  }, [hasRuns, cascade.has_mermaid, cascade.latest_session_id, fetchAndRenderMermaid]);

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const avgCostPerRun = hasRuns
    ? (cascade.metrics.total_cost / cascade.metrics.run_count)
    : 0;

  // Count special features
  const soundingsCount = cascade.phases?.filter(p => p.has_soundings).length || 0;
  const reforgesCount = cascade.phases?.filter(p => p.reforge_steps).length || 0;
  const wardsCount = cascade.phases?.reduce((sum, p) => sum + (p.ward_count || 0), 0) || 0;

  return (
    <div
      className={`cascade-tile ${!hasRuns ? 'no-runs' : ''} ${isRunning ? 'running' : ''}`}
      onClick={onClick}
    >
      {/* Mermaid Background */}
      {hasRuns && mermaidSvg && !mermaidError && (
        <div className="mermaid-background" dangerouslySetInnerHTML={{ __html: mermaidSvg }} />
      )}

      {/* Fallback for no mermaid */}
      {(!hasRuns || !mermaidSvg || mermaidError) && (
        <div className="tile-placeholder">
          <Icon icon="mdi:chart-waterfall" />
          <span className="placeholder-text">
            {!hasRuns ? 'No runs yet' : 'No diagram'}
          </span>
        </div>
      )}

      {/* Title Area - Top */}
      <div className="tile-title-area">
        <div className="tile-title-text">
          <h3 className="tile-title">{cascade.cascade_id}</h3>
          {cascade.description && (
            <p className="tile-description">{cascade.description}</p>
          )}
        </div>
        {isRunning && <span className="running-badge">Running...</span>}
      </div>

      {/* Metrics Column - Right side, vertical */}
      <div className="tile-metrics">
        {/* Phase count */}
        <div className="metric-item">
          <Icon icon="mdi:sitemap" width={16} height={16} />
          <span>{cascade.phases?.length || 0}</span>
        </div>

        {/* Soundings */}
        {soundingsCount > 0 && (
          <div className="metric-item soundings">
            <Icon icon="mdi:brain" width={16} height={16} />
            <span>{soundingsCount}</span>
          </div>
        )}

        {/* Reforges */}
        {reforgesCount > 0 && (
          <div className="metric-item reforges">
            <Icon icon="mdi:hammer-wrench" width={16} height={16} />
            <span>{reforgesCount}</span>
          </div>
        )}

        {/* Wards */}
        {wardsCount > 0 && (
          <div className="metric-item wards">
            <Icon icon="mdi:shield-check" width={16} height={16} />
            <span>{wardsCount}</span>
          </div>
        )}

        <div className="metric-divider"></div>

        {/* Run count */}
        <div className="metric-item">
          <Icon icon="mdi:play-circle" width={16} height={16} />
          <span>{cascade.metrics.run_count}</span>
        </div>

        {/* Avg time */}
        <div className="metric-item">
          <Icon icon="mdi:clock-outline" width={16} height={16} />
          <span>{hasRuns ? formatDuration(cascade.metrics.avg_duration_seconds) : '0s'}</span>
        </div>
      </div>

      {/* Cost Display - Bottom right, overlaps diagram */}
      <div className="tile-cost-display">
        {hasRuns && (
          <span className="cost-avg">(~{formatCost(avgCostPerRun)})</span>
        )}
        <span className="cost-total">{formatCost(cascade.metrics.total_cost)}</span>
      </div>
    </div>
  );
}

export default CascadeTile;
