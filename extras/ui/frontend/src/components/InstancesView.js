import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import PhaseBar from './PhaseBar';
import DebugModal from './DebugModal';
import MermaidPreview from './MermaidPreview';
import './InstancesView.css';

function InstancesView({ cascadeId, onBack, onFreezeInstance, onRunCascade, cascadeData, refreshTrigger, runningCascades, runningSessions, sessionUpdates, sseConnected }) {
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [debugSessionId, setDebugSessionId] = useState(null);

  useEffect(() => {
    if (cascadeId) {
      fetchInstances();
    }
  }, [cascadeId, refreshTrigger]);

  // Add polling for running sessions (every 2 seconds)
  useEffect(() => {
    if (!runningSessions || runningSessions.size === 0) {
      return;
    }

    const interval = setInterval(() => {
      console.log('[POLL] Refreshing instances (running sessions detected)');
      fetchInstances();
    }, 2000); // Poll every 2 seconds when sessions are running

    return () => clearInterval(interval);
  }, [runningSessions]);

  const fetchInstances = async () => {
    try {
      const response = await fetch(`http://localhost:5001/api/cascade-instances/${cascadeId}`);
      const data = await response.json();

      // Handle error response
      if (data.error) {
        setError(data.error);
        setInstances([]);
        setLoading(false);
        return;
      }

      // Ensure data is an array
      if (Array.isArray(data)) {
        setInstances(data);
      } else {
        console.error('API returned non-array:', data);
        setInstances([]);
      }

      setLoading(false);
    } catch (err) {
      setError(err.message);
      setInstances([]);
      setLoading(false);
    }
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0.0000';
    if (cost < 0.0001) return `$${(cost * 1000).toFixed(4)}‰`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 1) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatTimestamp = (isoString) => {
    const date = new Date(isoString);
    return date.toLocaleString();
  };

  const getPhaseStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return '#34d399';  // Green pastel
      case 'running':
        return '#fbbf24';  // Yellow pastel
      case 'error':
        return '#f87171';  // Red pastel
      case 'pending':
      default:
        return '#4b5563';  // Gray
    }
  };

  if (loading) {
    return (
      <div className="instances-container">
        <div className="loading">
          <div className="spinner"></div>
          <p>Loading instances...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="instances-container">
        <div className="error">
          <h2>Error Loading Instances</h2>
          <p>{error}</p>
          <button onClick={onBack} className="back-button">← Back to Cascades</button>
        </div>
      </div>
    );
  }

  const totalCost = instances.reduce((sum, i) => sum + (i.total_cost || 0), 0);

  return (
    <div className="instances-container">
      <header className="app-header">
        <div className="header-left">
          <button onClick={onBack} className="back-button">
            <Icon icon="mdi:arrow-left" width="18" />
          </button>
          <span className="cascade-title">{cascadeId}</span>
        </div>
        <div className="header-center">
          <span className="header-stat">{instances.length} <span className="stat-dim">{instances.length === 1 ? 'instance' : 'instances'}</span></span>
          <span className="header-divider">·</span>
          <span className="header-stat cost">{formatCost(totalCost)}</span>
        </div>
        <div className="header-right">
          {cascadeData && onRunCascade && (
            <button
              className="run-button"
              onClick={() => onRunCascade(cascadeData)}
              title="Run this cascade"
            >
              <Icon icon="mdi:play" width="18" />
              Run
            </button>
          )}
          <span className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`} title={sseConnected ? 'Connected' : 'Disconnected'} />
        </div>
      </header>

      <div className="instances-list">
        {instances.map((instance) => {
          const isCompleted = instance.phases?.every(p => p.status === 'completed');
          const hasRunning = instance.phases?.some(p => p.status === 'running');
          const isSessionRunning = runningSessions && runningSessions.has(instance.session_id);

          return (
            <div
              key={instance.session_id}
              className={`instance-row ${hasRunning || isSessionRunning ? 'running' : ''}`}
            >
            {/* Left: Instance Info */}
            <div className="instance-info">
              <h3 className="session-id">
                {instance.session_id}
                {(hasRunning || isSessionRunning) && (
                  <span className="running-badge">Running</span>
                )}
                {instance.status === 'failed' && (
                  <span className="failed-badge">
                    <Icon icon="mdi:alert-circle" width="14" />
                    Failed ({instance.error_count})
                  </span>
                )}
              </h3>
              <p className="timestamp">{formatTimestamp(instance.start_time)}</p>

              <div className="instance-actions-row">
                {instance.models_used.length > 0 && (
                  <div className="models-used">
                    {instance.models_used.map((model, idx) => (
                      <span key={idx} className="model-tag">
                        <Icon icon="mdi:robot" width="12" />
                        {model.split('/').pop()}
                      </span>
                    ))}
                  </div>
                )}
                <button
                  className="rerun-button-small"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRunCascade && onRunCascade({
                      ...cascadeData,
                      prefilled_inputs: instance.input_data || {}
                    });
                  }}
                  title="Re-run with these inputs"
                >
                  <Icon icon="mdi:replay" width="14" />
                </button>
              </div>

              {instance.input_data && Object.keys(instance.input_data).length > 0 && (
                <div className="input-params">
                  <span className="input-label">Inputs:</span>
                  <div className="input-fields">
                    {Object.entries(instance.input_data).map(([key, value]) => (
                      <div key={key} className="input-field-display">
                        <span className="input-key">{key}:</span>
                        <span className="input-value">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Mermaid Graph Preview - under inputs on left side */}
              <div className="mermaid-wrapper">
                <MermaidPreview
                  sessionId={instance.session_id}
                  size="small"
                  showMetadata={false}
                  lastUpdate={sessionUpdates?.[instance.session_id]}
                />
              </div>
            </div>

            {/* Middle: Phase Bars with Status */}
            <div className="phase-bars-container">
              {(() => {
                // Calculate max cost for relative bar widths
                // Use a softer normalization: max cost OR average*2 (whichever is higher)
                // This prevents one expensive phase from making all others tiny
                const costs = (instance.phases || []).map(p => p.avg_cost || 0);
                const maxCost = Math.max(...costs, 0.01);
                const avgCost = costs.reduce((sum, c) => sum + c, 0) / (costs.length || 1);
                const normalizedMax = Math.max(maxCost, avgCost * 2, 0.01);

                return (instance.phases || []).map((phase, idx) => (
                  <PhaseBar
                    key={idx}
                    phase={phase}
                    maxCost={normalizedMax}
                    status={phase.status}
                  />
                ));
              })()}

              {/* Final Output */}
              {instance.final_output && (
                <div className="final-output">
                  <div className="final-output-label">Final Output:</div>
                  <div className="final-output-content">{instance.final_output}</div>
                </div>
              )}
            </div>

            {/* Right: Instance Metrics */}
            <div className="instance-metrics">
              <div className="metric">
                <span className="metric-value">
                  {formatDuration(instance.duration_seconds)}
                </span>
                <span className="metric-label">duration</span>
              </div>

              <div className="metric metric-cost-small">
                <span className="metric-value cost-highlight">
                  {formatCost(instance.total_cost)}
                </span>
                <span className="metric-label">cost</span>
              </div>

              <button
                className="debug-button"
                onClick={(e) => {
                  e.stopPropagation();
                  setDebugSessionId(instance.session_id);
                }}
                title="Debug: view all messages"
              >
                <Icon icon="mdi:bug" width="18" />
                Debug
              </button>

              {isCompleted && onFreezeInstance && (
                <button
                  className="freeze-button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onFreezeInstance(instance);
                  }}
                  title="Freeze as test snapshot"
                >
                  <Icon icon="mdi:snowflake" width="18" />
                  Freeze
                </button>
              )}
            </div>
          </div>
          );
        })}
      </div>

      {instances.length === 0 && (
        <div className="empty-state">
          <p>No instances found for this cascade</p>
          <p className="empty-hint">This cascade hasn't been run yet</p>
        </div>
      )}

      {/* Debug Modal */}
      {debugSessionId && (
        <DebugModal
          sessionId={debugSessionId}
          onClose={() => setDebugSessionId(null)}
          lastUpdate={sessionUpdates?.[debugSessionId]}
        />
      )}
    </div>
  );
}

export default InstancesView;
