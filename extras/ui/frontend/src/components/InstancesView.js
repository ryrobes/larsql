import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import PhaseBar from './PhaseBar';
import CascadeBar from './CascadeBar';
import DebugModal from './DebugModal';
import SoundingsExplorer from './SoundingsExplorer';
import MermaidPreview from './MermaidPreview';
import ImageGallery from './ImageGallery';
import HumanInputDisplay from './HumanInputDisplay';
import VideoSpinner from './VideoSpinner';
import TokenSparkline from './TokenSparkline';
import ModelCostBar, { ModelTags } from './ModelCostBar';
import RunPercentile from './RunPercentile';
import windlassErrorImg from '../assets/windlass-error.png';
import './InstancesView.css';

// Calculate minimum height for phase bars container to prevent layout shift
// Heights based on actual CSS measurements
const calculatePhaseBarsMinHeight = (phases) => {
  if (!phases || phases.length === 0) return 80; // Minimum fallback

  let totalHeight = 0;

  // CascadeBar (only shown when > 1 phase): ~80px
  if (phases.length > 1) {
    totalHeight += 80;
  }

  // Each PhaseBar
  phases.forEach(phase => {
    // Base phase bar: padding (12px) + header (24px) + track (18px) + border (1px) = ~55px
    totalHeight += 55;

    // Sounding rows (when > 1 sounding)
    const soundingCount = phase.sounding_attempts?.length || 0;
    if (soundingCount > 1) {
      // Margin: 8px top + 4px bottom = 12px
      // Each row: 20px height + 4px gap (except last)
      totalHeight += 12 + (soundingCount * 20) + ((soundingCount - 1) * 4);
    }
  });

  return totalHeight;
};

// Live duration counter that updates every second for running instances
function LiveDuration({ startTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (isRunning && startTime) {
      // Calculate initial elapsed time
      const start = new Date(startTime).getTime();
      const updateElapsed = () => {
        const now = Date.now();
        setElapsed((now - start) / 1000);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 1000);

      return () => {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      };
    } else {
      // Not running, use static duration
      setElapsed(staticDuration || 0);
    }
  }, [isRunning, startTime, staticDuration]);

  const formatDuration = (seconds) => {
    if (!seconds || seconds < 0) return '0.0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  return (
    <span className={isRunning ? 'live-duration' : ''}>
      {formatDuration(elapsed)}
    </span>
  );
}

function InstancesView({ cascadeId, onBack, onSelectInstance, onFreezeInstance, onRunCascade, onInstanceComplete, cascadeData, refreshTrigger, runningCascades, runningSessions, finalizingSessions, sessionMetadata, sessionUpdates, sseConnected }) {
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [debugSessionId, setDebugSessionId] = useState(null);
  const [soundingsExplorerSession, setSoundingsExplorerSession] = useState(null);
  const [expandedParents, setExpandedParents] = useState(new Set());

  // Audible state - track per session since multiple can be running
  const [audibleSignaled, setAudibleSignaled] = useState({});  // { sessionId: boolean }
  const [audibleSending, setAudibleSending] = useState({});    // { sessionId: boolean }

  // Track which sessions have wide mermaid charts (for adaptive positioning)
  const [wideCharts, setWideCharts] = useState({});  // { sessionId: boolean }

  useEffect(() => {
    if (cascadeId) {
      fetchInstances();
    }
  }, [cascadeId, refreshTrigger]);

  // Fallback polling ONLY when SSE is disconnected (SSE events trigger refreshTrigger for real-time updates)
  useEffect(() => {
    // If SSE is connected, rely on events (no polling needed!)
    if (sseConnected) {
      console.log('[POLL] SSE connected - relying on events, no polling');
      return;
    }

    // SSE disconnected - use slow fallback polling
    const activeSessions = new Set([
      ...(runningSessions || []),
      ...(finalizingSessions || [])
    ]);

    if (activeSessions.size === 0) {
      console.log('[POLL] No active sessions and SSE disconnected - no polling needed');
      return;
    }

    console.log('[POLL] SSE DISCONNECTED - using fallback polling for', activeSessions.size, 'active sessions');

    const interval = setInterval(() => {
      console.log('[POLL] Fallback poll (SSE disconnected)');
      fetchInstances();
    }, 5000); // Slow fallback: 5 seconds when SSE down

    return () => clearInterval(interval);
  }, [runningSessions, finalizingSessions, sseConnected]);

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
      let instances = [];
      if (Array.isArray(data)) {
        instances = data;
      } else {
        console.error('API returned non-array:', data);
        instances = [];
      }

      // LiveStore now provides real-time data, so we don't need ghost rows
      // The backend serves from LiveStore first, then falls back to SQL for completed sessions
      setInstances(instances);
      setLoading(false);

      // Auto-expand parents with active children (running or finalizing)
      const autoExpand = new Set();
      instances.forEach(parent => {
        if (parent.children && parent.children.length > 0) {
          const hasActiveChildren = parent.children.some(child =>
            runningSessions?.has(child.session_id) ||
            finalizingSessions?.has(child.session_id)
          );
          if (hasActiveChildren) {
            autoExpand.add(parent.session_id);
            console.log('[EXPAND] Auto-expanding parent with active children:', parent.session_id);
          }
        }
      });

      // Merge with existing expanded state (don't collapse manually expanded parents)
      if (autoExpand.size > 0) {
        setExpandedParents(prev => {
          const merged = new Set([...prev, ...autoExpand]);
          console.log('[EXPAND] Updated expandedParents:', Array.from(merged));
          return merged;
        });
      }

      // SQL-driven completion detection: check if any finalizing sessions are now truly complete
      // Check both parents AND children recursively
      if (finalizingSessions && onInstanceComplete) {
        const checkCompletion = (instance) => {
          if (finalizingSessions.has(instance.session_id)) {
            // Check if this instance is REALLY done
            const allPhasesComplete = instance.phases?.every(p =>
              p.status === 'completed' || p.status === 'error'
            );
            const hasData = instance.total_cost > 0 || instance.phases?.length > 0;

            if (allPhasesComplete && hasData) {
              console.log(`[SQL] Instance ${instance.session_id} is truly complete, notifying parent`);
              // SQL data is ready! Trigger completion callback
              onInstanceComplete(instance.session_id);
            }
          }

          // Check children recursively
          if (instance.children && instance.children.length > 0) {
            instance.children.forEach(checkCompletion);
          }
        };

        instances.forEach(checkCompletion);
      }
    } catch (err) {
      setError(err.message);
      setInstances([]);
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

  const toggleExpanded = (sessionId) => {
    setExpandedParents(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const getChildrenSummary = (children) => {
    if (!children || children.length === 0) return null;

    const runningCount = children.filter(c => runningSessions?.has(c.session_id)).length;
    const finalizingCount = children.filter(c => finalizingSessions?.has(c.session_id)).length;
    const failedCount = children.filter(c => c.status === 'failed').length;

    const parts = [];
    if (runningCount > 0) parts.push(`${runningCount} running`);
    if (finalizingCount > 0) parts.push(`${finalizingCount} processing`);
    if (failedCount > 0) parts.push(`${failedCount} failed`);

    const statusText = parts.length > 0 ? ` (${parts.join(', ')})` : '';
    return `${children.length} sub-cascade${children.length > 1 ? 's' : ''}${statusText}`;
  };

  // Handle audible button click for a specific session
  const handleAudibleClick = async (e, sessionId) => {
    e.stopPropagation();

    // Don't signal if already signaled or sending
    if (audibleSending[sessionId] || audibleSignaled[sessionId]) return;

    setAudibleSending(prev => ({ ...prev, [sessionId]: true }));

    try {
      const response = await fetch(`http://localhost:5001/api/audible/signal/${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await response.json();

      if (data.status === 'signaled') {
        setAudibleSignaled(prev => ({ ...prev, [sessionId]: true }));
        // Don't auto-clear - will be cleared when session stops running
      }
    } catch (err) {
      console.error('Failed to signal audible:', err);
    } finally {
      setAudibleSending(prev => ({ ...prev, [sessionId]: false }));
    }
  };

  // Clear signaled state when session stops running
  useEffect(() => {
    setAudibleSignaled(prev => {
      const updated = { ...prev };
      let changed = false;
      for (const sessionId of Object.keys(updated)) {
        if (updated[sessionId] && !runningSessions?.has(sessionId)) {
          updated[sessionId] = false;
          changed = true;
        }
      }
      return changed ? updated : prev;
    });
  }, [runningSessions]);

  // Handle mermaid layout detection - track which charts are wide
  const handleLayoutDetected = useCallback((sessionId, { isWide }) => {
    setWideCharts(prev => {
      // Only update if the value changed to prevent unnecessary rerenders
      if (prev[sessionId] === isWide) return prev;
      return { ...prev, [sessionId]: isWide };
    });
  }, []);

  // Helper function to render an instance row (for both parents and children)
  const renderInstanceRow = (instance, isChild = false) => {
    const isCompleted = instance.phases?.every(p => p.status === 'completed');
    const hasRunning = instance.phases?.some(p => p.status === 'running');
    const isSessionRunning = runningSessions && runningSessions.has(instance.session_id);
    const isFinalizing = finalizingSessions && finalizingSessions.has(instance.session_id);

    // Check if this instance has a wide mermaid chart
    const isWideChart = !isChild && wideCharts[instance.session_id];

    // Determine visual state
    let stateClass = '';
    let stateBadge = null;

    if (isFinalizing) {
      stateClass = 'finalizing';
      stateBadge = <span className="finalizing-badge"><Icon icon="mdi:sync" width="14" className="spinning" style={{ marginRight: '4px' }} />Processing...</span>;
    } else if (hasRunning || isSessionRunning) {
      stateClass = 'running';
      stateBadge = <span className="running-badge"><Icon icon="mdi:lightning-bolt" width="14" style={{ marginRight: '4px' }} />Running</span>;
    }

    return (
      <div
        key={instance.session_id}
        className={`instance-row ${stateClass} ${isChild ? 'child-row' : ''} ${isWideChart ? 'has-wide-chart' : ''}`}
        onClick={() => onSelectInstance && onSelectInstance(instance.session_id)}
        style={{ cursor: onSelectInstance ? 'pointer' : 'default' }}
      >
        {/* For wide charts: Show header at very top of the box */}
        {isWideChart && (
          <div className="instance-header-top">
            {isChild && (
              <div className="child-connector">
                <span className="connector-line">└─</span>
                <span className="child-label">[{instance.cascade_id || 'Child'}]</span>
              </div>
            )}
            <div className="instance-header-left">
              <h3 className="session-id">
                {instance.session_id}
                {stateBadge}
                {instance.status === 'failed' && (
                  <span className="failed-badge">
                    <Icon icon="mdi:alert-circle" width="14" />
                    Failed ({instance.error_count})
                  </span>
                )}
              </h3>
              <p className="timestamp">{formatTimestamp(instance.start_time)}</p>
            </div>
          </div>
        )}

        {/* Wide Mermaid Chart - rendered after header when chart is wide */}
        {isWideChart && (
          <div
            className="mermaid-wrapper-top"
            onClick={(e) => e.stopPropagation()}
          >
            <MermaidPreview
              key={`mermaid-top-${instance.session_id}`}
              sessionId={instance.session_id}
              size="small"
              showMetadata={false}
              lastUpdate={sessionUpdates?.[instance.session_id]}
              onLayoutDetected={(layout) => handleLayoutDetected(instance.session_id, layout)}
            />
          </div>
        )}

        {/* Main content row */}
        <div className="instance-row-content">
          {/* Left: Instance Info */}
          <div className="instance-info">
            {/* For non-wide: show child connector here */}
            {!isWideChart && isChild && (
              <div className="child-connector">
                <span className="connector-line">└─</span>
                <span className="child-label">[{instance.cascade_id || 'Child'}]</span>
              </div>
            )}

            {/* Header row - only for non-wide charts (wide charts show header at top) */}
            {!isWideChart && (
              <div className="instance-header-row">
                <div className="instance-header-left">
                  <h3 className="session-id">
                    {instance.session_id}
                    {stateBadge}
                    {instance.status === 'failed' && (
                      <span className="failed-badge">
                        <Icon icon="mdi:alert-circle" width="14" />
                        Failed ({instance.error_count})
                      </span>
                    )}
                  </h3>
                  <p className="timestamp">{formatTimestamp(instance.start_time)}</p>
                </div>
              </div>
            )}

          {/* Model tags row - only for single model */}
          {instance.model_costs?.length <= 1 && instance.models_used?.length > 0 && (
            <div className="instance-actions-row">
              <ModelTags modelsUsed={instance.models_used} />
            </div>
          )}

          {/* Multi-model cost breakdown - full width like input box */}
          {instance.model_costs?.length > 1 && (
            <ModelCostBar
              modelCosts={instance.model_costs}
              totalCost={instance.total_cost}
            />
          )}

          {instance.input_data && Object.keys(instance.input_data).length > 0 && (
            <div className="input-params">
              {/* <span className="input-label">Inputs:</span> */}
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

          {/* Mermaid Graph Preview - under inputs on left side (only when NOT wide) */}
          {!isChild && !isWideChart && (
            <div
              className="mermaid-wrapper"
              onClick={(e) => e.stopPropagation()}
            >
              <MermaidPreview
                key={`mermaid-${instance.session_id}`}
                sessionId={instance.session_id}
                size="small"
                showMetadata={false}
                lastUpdate={sessionUpdates?.[instance.session_id]}
                onLayoutDetected={(layout) => handleLayoutDetected(instance.session_id, layout)}
              />
            </div>
          )}

          {/* Children collapse indicator (for parent rows only) - below mermaid */}
          {!isChild && instance.children && instance.children.length > 0 && (
            <div
              className="children-toggle"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpanded(instance.session_id);
              }}
            >
              <Icon
                icon={expandedParents.has(instance.session_id) ? "mdi:chevron-down" : "mdi:chevron-right"}
                width="20"
                className="chevron-icon"
              />
              <span className="children-summary">{getChildrenSummary(instance.children)}</span>
            </div>
          )}

          {/* Run Percentile - shows how this run compares to others */}
          {!isChild && instances.length >= 2 && (
            <RunPercentile
              instance={instance}
              allInstances={instances}
            />
          )}
        </div>

        {/* Middle: Phase Bars with Status */}
        <div
          className="phase-bars-container"
          style={{ minHeight: calculatePhaseBarsMinHeight(instance.phases) }}
        >
          {/* Cascade Bar - stacked overview of all phase costs */}
          {instance.phases && instance.phases.length > 1 && (
            <CascadeBar
              phases={instance.phases}
              totalCost={instance.total_cost}
              isRunning={isSessionRunning || hasRunning}
            />
          )}

          {(() => {
            // Calculate max cost for relative bar widths
            const costs = (instance.phases || []).map(p => p.avg_cost || 0);
            const maxCost = Math.max(...costs, 0.01);
            const avgCost = costs.reduce((sum, c) => sum + c, 0) / (costs.length || 1);
            const normalizedMax = Math.max(maxCost, avgCost * 2, 0.01);

            return (instance.phases || []).map((phase, idx) => (
              <React.Fragment key={idx}>
                <PhaseBar
                  phase={phase}
                  maxCost={normalizedMax}
                  status={phase.status}
                  phaseIndex={idx}
                />
                {/* Image Gallery - under each phase bar, filtered to that phase */}
                <ImageGallery
                  sessionId={instance.session_id}
                  phaseName={phase.name}
                  isRunning={runningSessions?.has(instance.session_id) || finalizingSessions?.has(instance.session_id)}
                  sessionUpdate={sessionUpdates?.[instance.session_id]}
                />
                {/* Human Input Display - under each phase bar, filtered to that phase */}
                <HumanInputDisplay
                  sessionId={instance.session_id}
                  phaseName={phase.name}
                  isRunning={runningSessions?.has(instance.session_id) || finalizingSessions?.has(instance.session_id)}
                  sessionUpdate={sessionUpdates?.[instance.session_id]}
                />
              </React.Fragment>
            ));
          })()}

          {/* Final Output */}
          {instance.final_output && (
            <div className="final-output">
              {/* <div className="final-output-label">Final Output:</div> */}
              <div className="final-output-content">
                <ReactMarkdown>{instance.final_output}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>

        {/* Right: Instance Metrics */}
        <div className="instance-metrics">
          <div className="metric">
            <span className="metric-value">
              <LiveDuration
                startTime={instance.start_time}
                isRunning={isSessionRunning || isFinalizing}
                staticDuration={instance.duration_seconds}
              />
            </span>
            <span className="metric-label">duration</span>
          </div>

          <div className="metric metric-cost-small">
            <span className="metric-value cost-highlight">
              {formatCost(instance.total_cost)}
            </span>
            <span className="metric-label">cost</span>
            {instance.token_timeseries && instance.token_timeseries.length > 0 && (
              <div className="token-sparkline-container">
                <TokenSparkline data={instance.token_timeseries} width={95} height={24} />
              </div>
            )}
          </div>

          {/* Action buttons - grouped together in metrics panel */}
          {/* Soundings Explorer Button */}
          {instance.has_soundings && (
            <button
              className="soundings-button"
              onClick={(e) => {
                e.stopPropagation();
                setSoundingsExplorerSession(instance.session_id);
              }}
              title="Explore all soundings across all phases in this cascade"
            >
              <Icon icon="mdi:sign-direction" width="16" />
              Soundings
              <span className="soundings-count">
                {instance.phases?.filter(p => p.sounding_total > 1).length || 0}
              </span>
            </button>
          )}

          {/* Re-run button */}
          <button
            className="rerun-button"
            onClick={(e) => {
              e.stopPropagation();
              onRunCascade && onRunCascade({
                ...cascadeData,
                prefilled_inputs: instance.input_data || {}
              });
            }}
            title="Re-run with these inputs"
          >
            <Icon icon="mdi:replay" width="16" />
            Re-run
          </button>

          {/* Audible Button - only shown when instance is running */}
          {(isSessionRunning || (hasRunning && !isFinalizing)) && (
            <button
              className={`audible-button-compact ${audibleSignaled[instance.session_id] ? 'signaled' : ''}`}
              onClick={(e) => handleAudibleClick(e, instance.session_id)}
              disabled={audibleSending[instance.session_id] || audibleSignaled[instance.session_id]}
              title={audibleSignaled[instance.session_id] ? 'Audible signaled - waiting for safe point' : 'Call audible - inject feedback mid-phase'}
            >
              <Icon icon="mdi:bullhorn" width="16" />
              {audibleSending[instance.session_id] ? 'Signaling...' : audibleSignaled[instance.session_id] ? 'Signaled!' : 'Audible'}
            </button>
          )}

          {/* Debug button - commented out, redundant with SplitDetailView
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
          */}

          {isCompleted && onFreezeInstance && !isChild && (
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
        </div> {/* Close instance-row-content */}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="instances-container">
        <div className="loading">
          <VideoSpinner message="Loading instances..." size={500} opacity={0.6} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="instances-container">
        <div className="error">
          <img src={windlassErrorImg} alt="" className="error-background-img" />
          <h2>Error Loading Instances</h2>
          <p>{error}</p>
          <button onClick={onBack} className="back-button"><Icon icon="mdi:arrow-left" width="16" style={{ marginRight: '4px' }} />Back to Cascades</button>
        </div>
      </div>
    );
  }

  const totalCost = instances.reduce((sum, i) => sum + (i.total_cost || 0), 0);

  return (
    <div className="instances-container">
      <header className="app-header">
        <div className="header-left">
          <img
            src="/windlass-transparent-square.png"
            alt="Windlass"
            className="brand-logo"
            onClick={onBack}
            style={{ cursor: 'pointer' }}
            title="Back to cascades"
          />
          <div className="cascade-title-block">
            <span className="cascade-title">{cascadeId}</span>
            {cascadeData?.cascade_file && (
              <span className="cascade-file-path">{cascadeData.cascade_file}</span>
            )}
          </div>
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
          const isExpanded = expandedParents.has(instance.session_id);
          const hasChildren = instance.children && instance.children.length > 0;

          // if (hasChildren) {
          //   console.log('[RENDER] Parent:', instance.session_id, 'has', instance.children.length, 'children, expanded:', isExpanded);
          // }

          return (
            <React.Fragment key={instance.session_id}>
              {/* Render parent instance */}
              {renderInstanceRow(instance, false)}

              {/* Render child instances (only if expanded) */}
              {hasChildren && isExpanded && (
                instance.children.map(child => renderInstanceRow(child, true))
              )}
            </React.Fragment>
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

      {/* Soundings Explorer Modal */}
      {soundingsExplorerSession && (
        <SoundingsExplorer
          sessionId={soundingsExplorerSession}
          onClose={() => setSoundingsExplorerSession(null)}
        />
      )}
    </div>
  );
}

export default InstancesView;
