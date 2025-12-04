import React, { useState, useEffect } from 'react';
import PhaseBar from './PhaseBar';
import './CascadesView.css';

function CascadesView({ onSelectCascade, onRunCascade, refreshTrigger, runningCascades, finalizingSessions, sseConnected }) {
  const [cascades, setCascades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCascades();
  }, [refreshTrigger]);

  // Add polling for running cascades AND finalizing sessions (every 2 seconds)
  useEffect(() => {
    const hasRunning = runningCascades && runningCascades.size > 0;
    const hasFinalizing = finalizingSessions && finalizingSessions.size > 0;

    if (!hasRunning && !hasFinalizing) {
      return; // No polling if nothing active
    }

    const interval = setInterval(() => {
      console.log('[POLL] Refreshing cascade list (active cascades detected)');
      fetchCascades();
    }, 2000); // Poll every 2 seconds when cascades are active

    return () => clearInterval(interval);
  }, [runningCascades, finalizingSessions]);

  const fetchCascades = async () => {
    try {
      const response = await fetch('http://localhost:5001/api/cascade-definitions');
      const data = await response.json();

      // Handle error response from API
      if (data.error) {
        setError(data.error);
        setCascades([]);
        setLoading(false);
        return;
      }

      // Ensure data is an array
      if (Array.isArray(data)) {
        setCascades(data);
      } else {
        console.error('API returned non-array:', data);
        setCascades([]);
      }

      setLoading(false);
    } catch (err) {
      setError(err.message);
      setCascades([]);
      setLoading(false);
    }
  };

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

  if (loading) {
    return (
      <div className="cascades-container">
        <div className="loading">
          <div className="spinner"></div>
          <p>Loading cascades...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cascades-container">
        <div className="error">
          <h2>Error Loading Cascades</h2>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  const totalRuns = cascades.reduce((sum, c) => sum + (c.metrics?.run_count || 0), 0);
  const totalCost = cascades.reduce((sum, c) => sum + (c.metrics?.total_cost || 0), 0);

  return (
    <div className="cascades-container">
      <header className="app-header">
        <div className="header-brand">
          <img
            src="/windlass-transparent-square.png"
            alt="Windlass"
            className="brand-logo"
          />
        </div>
        <div className="header-center">
          <span className="header-stat">{cascades.length} <span className="stat-dim">cascades</span></span>
          <span className="header-divider">·</span>
          <span className="header-stat">{totalRuns} <span className="stat-dim">runs</span></span>
          <span className="header-divider">·</span>
          <span className="header-stat cost">{formatCost(totalCost)}</span>
        </div>
        <div className="header-right">
          <span className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`} title={sseConnected ? 'Connected' : 'Disconnected'} />
        </div>
      </header>

      <div className="cascades-list">
        {cascades.map((cascade) => {
          const hasRuns = cascade.metrics?.run_count > 0;
          const isRunning = runningCascades && runningCascades.has(cascade.cascade_id);

          return (
            <div
              key={cascade.cascade_id}
              className={`cascade-row ${!hasRuns ? 'no-runs' : ''} ${isRunning ? 'running' : ''}`}
            >
            {/* Left: Cascade Info */}
            <div
              className="cascade-info"
              onClick={() => onSelectCascade(cascade.cascade_id, cascade)}
            >
              <h2 className="cascade-name">
                {cascade.cascade_id || 'Unknown'}
                {isRunning && <span className="running-indicator">Running...</span>}
              </h2>
              {cascade.description && (
                <p className="cascade-description">{cascade.description}</p>
              )}
            </div>

            {/* Middle: Phase Bars */}
            <div className="phase-bars-container">
              {(() => {
                // Calculate max cost for relative bar widths
                const maxCost = Math.max(...(cascade.phases || []).map(p => p.avg_cost || 0), 0.01);

                return (cascade.phases || []).map((phase, idx) => (
                  <PhaseBar
                    key={idx}
                    phase={phase}
                    maxCost={maxCost}
                    onClick={() => onSelectCascade(cascade.cascade_id, cascade)}
                  />
                ));
              })()}
            </div>

            {/* Right: Metrics */}
            <div className="cascade-metrics">
              <div className="metric-group">
                <div className="metric">
                  <span className="metric-value">{cascade.metrics?.run_count || 0}</span>
                  <span className="metric-label">runs</span>
                </div>
                <div className="metric">
                  <span className="metric-value">
                    {formatDuration(cascade.metrics?.avg_duration_seconds || 0)}
                  </span>
                  <span className="metric-label">avg time</span>
                </div>
              </div>

              <div className="metric-cost">
                <span className="cost-label">Total Cost</span>
                <span className="cost-value">{formatCost(cascade.metrics?.total_cost || 0)}</span>
              </div>
            </div>
          </div>
          );
        })}
      </div>

      {cascades.length === 0 && (
        <div className="empty-state">
          <p>No cascades found</p>
          <p className="empty-hint">Run a cascade to see it appear here</p>
        </div>
      )}
    </div>
  );
}

export default CascadesView;
