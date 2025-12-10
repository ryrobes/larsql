import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './CascadeBar.css';

// Curated color palette - vibrant pastels that work on dark backgrounds
// Colors are ordered for visual appeal when adjacent
export const PHASE_COLORS = [
  '#2DD4BF', // Teal (primary theme color)
  '#a78bfa', // Purple
  '#60a5fa', // Blue
  '#f472b6', // Pink
  '#fbbf24', // Amber
  '#34d399', // Emerald
  '#fb923c', // Orange
  '#22d3ee', // Cyan
  '#818cf8', // Indigo
  '#f87171', // Coral
  '#84cc16', // Lime
  '#e879f9', // Fuchsia
];

// Get a consistent color for a phase name (hash-based for consistency across renders)
export function getPhaseColor(phaseName, index) {
  // Simple hash of phase name for consistent color assignment
  let hash = 0;
  for (let i = 0; i < phaseName.length; i++) {
    hash = ((hash << 5) - hash) + phaseName.charCodeAt(i);
    hash |= 0;
  }
  // Use absolute value and modulo to get index
  const colorIndex = Math.abs(hash) % PHASE_COLORS.length;
  return PHASE_COLORS[colorIndex];
}

// Sequential assignment for more predictable coloring (matches cascade bar order)
export function getSequentialColor(index) {
  return PHASE_COLORS[index % PHASE_COLORS.length];
}

function CascadeBar({ phases, totalCost, isRunning = false, mode = 'cost' }) {
  const [hoveredPhase, setHoveredPhase] = useState(null);
  const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 });

  // Calculate phase data with colors and percentages
  const phaseData = useMemo(() => {
    if (!phases || phases.length === 0) return [];

    // Use sequential colors for more pleasing adjacent color combinations
    return phases.map((phase, idx) => {
      const value = mode === 'cost'
        ? (phase.avg_cost || phase.total_cost || 0)
        : (phase.avg_duration || phase.duration || 0);

      return {
        ...phase,
        color: getSequentialColor(idx),
        value,
        index: idx
      };
    });
  }, [phases, mode]);

  // Calculate total for percentage calculation
  const total = useMemo(() => {
    return phaseData.reduce((sum, p) => sum + p.value, 0) || 0.01;
  }, [phaseData]);

  // Calculate percentage for each phase
  const phasesWithPercent = useMemo(() => {
    return phaseData.map(p => ({
      ...p,
      percent: (p.value / total) * 100,
      displayPercent: Math.max((p.value / total) * 100, 2) // Minimum 2% for visibility
    }));
  }, [phaseData, total]);

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
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const handleMouseMove = (e, phase) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltipPosition({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    });
    setHoveredPhase(phase);
  };

  if (!phases || phases.length === 0) return null;

  return (
    <div className={`cascade-bar-container ${isRunning ? 'is-running' : ''}`}>
      {/* Main stacked bar */}
      <div className="cascade-bar-track">
        <div className="cascade-bar-segments">
          {phasesWithPercent.map((phase) => {
            const isPhaseRunning = phase.status === 'running';
            const isHovered = hoveredPhase?.index === phase.index;

            return (
              <div
                key={phase.index}
                className={`cascade-segment ${isPhaseRunning ? 'running' : ''} ${isHovered ? 'hovered' : ''}`}
                style={{
                  width: `${phase.displayPercent}%`,
                  backgroundColor: phase.color,
                  '--phase-color': phase.color
                }}
                onMouseMove={(e) => handleMouseMove(e, phase)}
                onMouseLeave={() => setHoveredPhase(null)}
              >
                {/* Inner glow effect */}
                <div className="segment-glow" />

                {/* Show cost label if segment is wide enough */}
                {phase.displayPercent > 12 && (
                  <span className="segment-label">
                    {mode === 'cost' ? formatCost(phase.value) : formatDuration(phase.value)}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Tooltip */}
        {hoveredPhase && (
          <div
            className="cascade-bar-tooltip"
            style={{
              left: `${tooltipPosition.x}px`,
              top: '-60px'
            }}
          >
            <div className="tooltip-phase-name">
              <span
                className="tooltip-color-dot"
                style={{ backgroundColor: hoveredPhase.color }}
              />
              {hoveredPhase.name}
            </div>
            <div className="tooltip-stats">
              <span className="tooltip-cost">{formatCost(hoveredPhase.value)}</span>
              <span className="tooltip-percent">{hoveredPhase.percent.toFixed(1)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* Legend row */}
      <div className="cascade-bar-legend">
        {phasesWithPercent.map((phase) => {
          const isPhaseRunning = phase.status === 'running';
          const isCompleted = phase.status === 'completed';
          const isError = phase.status === 'error';

          return (
            <div
              key={phase.index}
              className={`legend-item ${isPhaseRunning ? 'running' : ''} ${hoveredPhase?.index === phase.index ? 'hovered' : ''}`}
              onMouseEnter={() => setHoveredPhase(phase)}
              onMouseLeave={() => setHoveredPhase(null)}
            >
              <span
                className="legend-color"
                style={{ backgroundColor: phase.color }}
              />
              <span className="legend-name">{phase.name}</span>
              {isPhaseRunning && (
                <Icon icon="mdi:loading" width="12" className="spinning legend-status" />
              )}
              {isCompleted && (
                <Icon icon="mdi:check" width="12" className="legend-status completed" />
              )}
              {isError && (
                <Icon icon="mdi:alert-circle" width="12" height="12" className="legend-status error" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default CascadeBar;
