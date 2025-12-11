import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
// PhaseBar removed - now only shown in SplitDetailView
import CascadeBar from './CascadeBar';
import DebugModal from './DebugModal';
import SoundingsExplorer from './SoundingsExplorer';
import InstanceGridView from './InstanceGridView';
// MermaidPreview, ImageGallery, HumanInputDisplay removed - now only shown in SplitDetailView
import VideoSpinner from './VideoSpinner';
import TokenSparkline from './TokenSparkline';
import ModelCostBar, { ModelTags } from './ModelCostBar';
import RunPercentile from './RunPercentile';
import PhaseSpeciesBadges from './PhaseSpeciesBadges';
import windlassErrorImg from '../assets/windlass-error.png';
import './InstancesView.css';


// Animated cost display that smoothly transitions when value changes
function AnimatedCost({ value, formatFn }) {
  const [displayValue, setDisplayValue] = useState(value || 0);
  const animationRef = useRef(null);
  const startValueRef = useRef(value || 0);
  const startTimeRef = useRef(null);

  useEffect(() => {
    const targetValue = value || 0;
    const startValue = displayValue;

    // Skip animation if values are very close or target is 0
    if (Math.abs(targetValue - startValue) < 0.0000001) {
      return;
    }

    // Cancel any existing animation
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }

    startValueRef.current = startValue;
    startTimeRef.current = performance.now();
    const duration = 2000; // 2000ms animation

    const animate = (currentTime) => {
      const elapsed = currentTime - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);

      // Ease-out cubic for smooth deceleration
      const easeOut = 1 - Math.pow(1 - progress, 3);

      const currentValue = startValueRef.current + (targetValue - startValueRef.current) * easeOut;
      setDisplayValue(currentValue);

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [value]); // Only depend on value, not displayValue

  return <span>{formatFn(displayValue)}</span>;
}

// Live duration counter that updates smoothly for running instances
// sseStartTime is tracked from SSE cascade_start (instant), startTime comes from DB (may have delay)
function LiveDuration({ startTime, sseStartTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(staticDuration || 0);
  const intervalRef = useRef(null);
  const lockedStartRef = useRef(null); // Lock in start time to prevent jumps

  useEffect(() => {
    // Clear interval on any change
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isRunning) {
      // Not running - show static duration, clear locked start
      lockedStartRef.current = null;
      setElapsed(staticDuration || 0);
      return;
    }

    // Running - determine start time
    // Priority: use already locked time > sseStartTime > startTime from DB
    // Once locked, don't change (prevents jumps from slightly different timestamps)
    if (!lockedStartRef.current) {
      const timeSource = sseStartTime || startTime;
      if (timeSource) {
        let parsed;
        if (typeof timeSource === 'number') {
          parsed = timeSource < 10000000000 ? timeSource * 1000 : timeSource;
        } else {
          parsed = new Date(timeSource).getTime();
        }

        if (!isNaN(parsed) && parsed > 0) {
          lockedStartRef.current = parsed;
        }
      }
    }

    // If we have a locked start time, run the counter
    if (lockedStartRef.current) {
      const start = lockedStartRef.current;

      const updateElapsed = () => {
        const now = Date.now();
        const diff = (now - start) / 1000;
        setElapsed(diff >= 0 ? diff : 0);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 100);
    } else {
      // No valid start time yet, show 0
      setElapsed(0);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning, startTime, sseStartTime, staticDuration]);

  const formatDuration = (seconds) => {
    if (!seconds || seconds < 0) return '0.0s';
    if (seconds < 60) {
      return `${seconds.toFixed(1)}s`;
    }
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

function InstancesView({ cascadeId, onBack, onSelectInstance, onFreezeInstance, onRunCascade, onInstanceComplete, cascadeData, refreshTrigger, runningCascades, runningSessions, finalizingSessions, sessionMetadata, sessionUpdates, sessionStartTimes, sseConnected }) {
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [debugSessionId, setDebugSessionId] = useState(null);
  const [soundingsExplorerSession, setSoundingsExplorerSession] = useState(null);
  const [expandedParents, setExpandedParents] = useState(new Set());
  const [viewMode, setViewMode] = useState('card'); // 'card' or 'grid'

  // Audible state - track per session since multiple can be running
  const [audibleSignaled, setAudibleSignaled] = useState({});  // { sessionId: boolean }
  const [audibleSending, setAudibleSending] = useState({});    // { sessionId: boolean }

  // Latest messages for running sessions - track per session
  const [latestMessages, setLatestMessages] = useState({});    // { sessionId: { text, metadata } }

  const fetchInstances = useCallback(async () => {
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
  }, [cascadeId, runningSessions, finalizingSessions, onInstanceComplete]);

  useEffect(() => {
    if (cascadeId) {
      fetchInstances();
    }
  }, [cascadeId, refreshTrigger, fetchInstances]);

  // Fast polling for running sessions to pick up species_hash and other metadata
  useEffect(() => {
    const activeSessions = new Set([
      ...(runningSessions || []),
      ...(finalizingSessions || [])
    ]);

    if (activeSessions.size === 0) {
      return;
    }

    // Fast polling: 2 seconds when sessions are active
    const interval = setInterval(() => {
      fetchInstances();
    }, 2000);

    return () => clearInterval(interval);
  }, [runningSessions, finalizingSessions, fetchInstances]);

  // Fetch latest message for running sessions
  const fetchLatestMessages = useCallback(async () => {
    if (!runningSessions || runningSessions.size === 0) {
      return;
    }

    const sessionIds = Array.from(runningSessions);
    const newMessages = {};

    // Fetch session details for each running session to get latest message
    await Promise.all(
      sessionIds.map(async (sessionId) => {
        try {
          const response = await fetch(`http://localhost:5001/api/session/${sessionId}`);
          const data = await response.json();

          if (data.error || !data.entries || data.entries.length === 0) {
            return;
          }

          // Find the latest message (non-structural entry with content)
          const entries = data.entries;
          // Reverse to get latest first
          for (let i = entries.length - 1; i >= 0; i--) {
            const entry = entries[i];

            // Skip structural entries
            const structuralTypes = [
              'cascade', 'cascade_start', 'cascade_complete', 'cascade_completed',
              'cascade_error', 'cascade_failed', 'cascade_killed',
              'phase', 'phase_start', 'phase_complete',
              'turn', 'turn_start', 'turn_input',
              'cost_update', 'checkpoint_start', 'checkpoint_complete'
            ];

            if (structuralTypes.includes(entry.node_type)) {
              continue;
            }

            // Skip entries without content
            if (!entry.content) {
              continue;
            }

            // Extract text from content (could be string or object)
            let messageText = '';
            if (typeof entry.content === 'string') {
              messageText = entry.content;
            } else if (typeof entry.content === 'object') {
              // Handle various content formats
              if (entry.content.content) {
                messageText = typeof entry.content.content === 'string'
                  ? entry.content.content
                  : JSON.stringify(entry.content.content);
              } else {
                messageText = JSON.stringify(entry.content);
              }
            }

            // Clean up and truncate
            if (messageText) {
              // Remove excessive whitespace
              messageText = messageText.replace(/\s+/g, ' ').trim();
              // Get first line only (up to first newline or max length)
              const firstLine = messageText.split('\n')[0];

              // Build metadata string
              const metaParts = [];

              // Add role/type info
              if (entry.role) {
                metaParts.push(entry.role);
              }
              if (entry.node_type && entry.node_type !== entry.role) {
                metaParts.push(entry.node_type);
              }

              // Add model info if it's an LLM call
              if (entry.model || entry.model_requested) {
                const modelName = entry.model_requested || entry.model;
                metaParts.push(`model: ${modelName}`);
              }

              // Add token info if available
              if (entry.tokens_in > 0 || entry.tokens_out > 0) {
                const tokensIn = entry.tokens_in || 0;
                const tokensOut = entry.tokens_out || 0;
                metaParts.push(`${tokensIn.toLocaleString()} → ${tokensOut.toLocaleString()} tokens`);
              }

              // Add cost if available
              if (entry.cost > 0) {
                metaParts.push(`$${entry.cost.toFixed(6)}`);
              }

              // Add phase name if available
              if (entry.phase_name) {
                metaParts.push(`phase: ${entry.phase_name}`);
              }

              newMessages[sessionId] = {
                text: firstLine,
                metadata: metaParts.length > 0 ? metaParts.join(' • ') : null
              };
              break; // Found the latest message
            }
          }
        } catch (err) {
          console.error(`Error fetching latest message for ${sessionId}:`, err);
        }
      })
    );

    setLatestMessages(prev => ({ ...prev, ...newMessages }));
  }, [runningSessions]);

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

  // Fetch latest messages for running sessions
  useEffect(() => {
    if (runningSessions && runningSessions.size > 0) {
      fetchLatestMessages();
      // Poll for updates while sessions are running
      const interval = setInterval(fetchLatestMessages, 2000);
      return () => clearInterval(interval);
    } else {
      // Clear messages when no sessions are running
      setLatestMessages({});
    }
  }, [runningSessions, fetchLatestMessages]);

  // Force re-render frequently for running sessions to update progress bar smoothly
  const [, setTick] = useState(0);
  useEffect(() => {
    if (runningSessions && runningSessions.size > 0) {
      const interval = setInterval(() => {
        setTick(t => t + 1);
      }, 100); // Update every 100ms for smooth animation
      return () => clearInterval(interval);
    }
  }, [runningSessions]);


  // Outlined progress bar component with Tron aesthetic
  // Shows progress based on historical runs with same cascade + inputs
  const HistoricalProgressBar = ({ currentDuration, avgDuration, sampleSize }) => {
    const progress = Math.min((currentDuration / avgDuration) * 100, 100);

    return (
      <div className="species-progress-container">
        <div className="species-progress-bar">
          <div
            className="species-progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="species-progress-info">
          <span className="species-progress-percent">{Math.round(progress)}%</span>
          <span className="species-progress-stats">avg: {formatDuration(avgDuration)} ({sampleSize} runs)</span>
        </div>
      </div>
    );
  };

  // Create a hash from cascade_id + inputs for matching similar runs
  const getRunSignature = useCallback((cascadeId, inputData) => {
    if (!cascadeId) return null;
    // Create signature from cascade_id + sorted input keys/values
    const inputStr = inputData && Object.keys(inputData).length > 0
      ? JSON.stringify(inputData, Object.keys(inputData).sort())
      : 'no_inputs';
    return `${cascadeId}::${inputStr}`;
  }, []);

  // Calculate average duration for completed runs with same cascade + inputs
  const getHistoricalAverage = useCallback((cascadeId, inputData, currentSessionId) => {
    if (!cascadeId || !instances || instances.length < 1) {
      return null;
    }

    const signature = getRunSignature(cascadeId, inputData);
    if (!signature) return null;

    // Collect all instances (including children)
    const allInstances = [];
    instances.forEach(inst => {
      allInstances.push(inst);
      if (inst.children && inst.children.length > 0) {
        allInstances.push(...inst.children);
      }
    });

    // Find completed instances with matching cascade_id and inputs
    const matchingRuns = allInstances.filter(inst => {
      if (inst.session_id === currentSessionId) return false; // Don't include current run
      if (inst.status === 'failed') return false;
      if (inst.duration_seconds <= 0) return false;
      if (runningSessions?.has(inst.session_id)) return false;
      if (finalizingSessions?.has(inst.session_id)) return false;

      const instSignature = getRunSignature(inst.cascade_id, inst.input_data);
      return instSignature === signature;
    });

    if (matchingRuns.length === 0) {
      return null;
    }

    // Calculate average duration
    const totalDuration = matchingRuns.reduce((sum, inst) => sum + inst.duration_seconds, 0);
    const avgDuration = totalDuration / matchingRuns.length;

    return {
      avgDuration,
      sampleSize: matchingRuns.length
    };
  }, [instances, runningSessions, finalizingSessions, getRunSignature]);

  // Helper function to render an instance row (for both parents and children)
  const renderInstanceRow = (instance, isChild = false) => {
    const isCompleted = instance.phases?.every(p => p.status === 'completed');
    const hasRunning = instance.phases?.some(p => p.status === 'running');
    const isSessionRunning = runningSessions && runningSessions.has(instance.session_id);
    const isFinalizing = finalizingSessions && finalizingSessions.has(instance.session_id);

    // Calculate historical average for running sessions based on cascade + inputs
    const historicalAvg = getHistoricalAverage(instance.cascade_id, instance.input_data, instance.session_id);
    const showProgress = (isSessionRunning || hasRunning) && historicalAvg && !isFinalizing;

    // Debug: log when historical data is found
    if ((isSessionRunning || hasRunning) && !isFinalizing) {
      const signature = getRunSignature(instance.cascade_id, instance.input_data);
      if (!historicalAvg) {
        console.log(`[PROGRESS] ${instance.session_id}: No historical data for ${signature}`);
      } else {
        console.log(`[PROGRESS] ${instance.session_id}: Progress bar active - avg ${historicalAvg.avgDuration.toFixed(1)}s from ${historicalAvg.sampleSize} runs`);
      }
    }

    // Calculate current duration for running sessions
    let currentDuration = instance.duration_seconds || 0;
    if (isSessionRunning || hasRunning) {
      const sseStart = sessionStartTimes?.[instance.session_id];
      const dbStart = instance.start_time;
      const startTime = sseStart || dbStart;

      if (startTime) {
        const startMs = typeof startTime === 'number'
          ? (startTime < 10000000000 ? startTime * 1000 : startTime)
          : new Date(startTime).getTime();

        if (!isNaN(startMs) && startMs > 0) {
          const now = Date.now();
          currentDuration = Math.max((now - startMs) / 1000, 0);
        }
      }
    }

    // Debug: log sessionStartTimes for running sessions
    // if (isSessionRunning || isFinalizing) {
    //   console.log('[renderInstanceRow] Running instance:', {
    //     session_id: instance.session_id,
    //     start_time: instance.start_time,
    //     duration_seconds: instance.duration_seconds,
    //     sessionStartTimes_keys: Object.keys(sessionStartTimes || {}),
    //     sseStartTime: sessionStartTimes?.[instance.session_id],
    //     runningSessions: Array.from(runningSessions || []),
    //   });
    // }

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
        className={`instance-row-compact ${stateClass} ${isChild ? 'child-row' : ''}`}
        onClick={() => onSelectInstance && onSelectInstance(instance.session_id)}
        style={{ cursor: onSelectInstance ? 'pointer' : 'default' }}
      >
        {/* Stacked buttons on far left */}
        <div className="buttons-stacked">
          {instance.has_soundings && (
            <button
              className="btn-compact soundings"
              onClick={(e) => {
                e.stopPropagation();
                setSoundingsExplorerSession(instance.session_id);
              }}
              title="Explore soundings"
            >
              <Icon icon="mdi:sign-direction" width="14" />
            </button>
          )}
          <button
            className="btn-compact rerun"
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
          {(isSessionRunning || (hasRunning && !isFinalizing)) && (
            <button
              className={`btn-compact audible ${audibleSignaled[instance.session_id] ? 'signaled' : ''}`}
              onClick={(e) => handleAudibleClick(e, instance.session_id)}
              disabled={audibleSending[instance.session_id] || audibleSignaled[instance.session_id]}
              title={audibleSignaled[instance.session_id] ? 'Audible signaled' : 'Call audible'}
            >
              <Icon icon="mdi:bullhorn" width="14" />
            </button>
          )}
          {isCompleted && onFreezeInstance && !isChild && (
            <button
              className="btn-compact freeze"
              onClick={(e) => {
                e.stopPropagation();
                onFreezeInstance(instance);
              }}
              title="Freeze as test snapshot"
            >
              <Icon icon="mdi:snowflake" width="14" />
            </button>
          )}
        </div>

        {/* Main content area */}
        <div className="instance-main-content">
          {/* Row 1: Header with session info and metrics */}
          <div className="instance-header-compact">
            {/* Left: Session ID, badge, timestamp */}
            <div className="header-left-compact">
              {isChild && (
                <span className="child-indicator">└─ [{instance.cascade_id || 'Child'}]</span>
              )}
              <h3 className="session-id-compact">
                {instance.session_id}
                {stateBadge}
                {instance.status === 'failed' && (
                  <span className="failed-badge">
                    <Icon icon="mdi:alert-circle" width="14" />
                    Failed ({instance.error_count})
                  </span>
                )}
              </h3>
              <span className="timestamp-compact">{formatTimestamp(instance.start_time)}</span>
              <PhaseSpeciesBadges sessionId={instance.session_id} />
            </div>

            {/* Sparkline positioned to align with cascade bar */}
            {instance.token_timeseries && instance.token_timeseries.length > 0 && (
              <div className="sparkline-header-positioned">
                <TokenSparkline data={instance.token_timeseries} width={60} height={18} />
              </div>
            )}

            {/* Duration positioned to align left edge with cascade bar right edge */}
            <span className="metric-duration-positioned">
              <LiveDuration
                startTime={instance.start_time}
                sseStartTime={sessionStartTimes?.[instance.session_id]}
                isRunning={isSessionRunning || isFinalizing}
                staticDuration={instance.duration_seconds}
              />
            </span>

            {/* Right: Cost on far right */}
            <div className="header-right-compact">
              <span className="metric-cost-large">
                <AnimatedCost value={instance.total_cost} formatFn={formatCost} />
              </span>
            </div>
          </div>

          {/* Row 2: 3 columns - Models | CascadeBar+Inputs+Sparkline | RunPercentile */}
          <div className="instance-content-compact">
            {/* Left section: Models (~20%) */}
            <div className="models-section-compact">
              {instance.model_costs?.length > 0 && (
                <ModelCostBar
                  modelCosts={instance.model_costs}
                  totalCost={instance.total_cost}
                  winnerModel={
                    // Compute winner models from phases with soundings
                    instance.phases
                      ?.filter(p => p.sounding_total > 1)
                      .flatMap(p => (p.sounding_attempts || []).filter(a => a.is_winner && a.model).map(a => a.model))
                      .filter((m, i, arr) => arr.indexOf(m) === i) // unique
                  }
                />
              )}
            </div>

            {/* Middle section: CascadeBar with inputs (~55%) */}
            <div className="cascade-section-compact">
              {instance.phases && instance.phases.length > 1 && (
                <CascadeBar
                  phases={instance.phases}
                  totalCost={instance.total_cost}
                  isRunning={isSessionRunning || hasRunning}
                />
              )}
              {/* Historical progress bar for running cascades */}
              {showProgress && (
                <HistoricalProgressBar
                  currentDuration={currentDuration}
                  avgDuration={historicalAvg.avgDuration}
                  sampleSize={historicalAvg.sampleSize}
                />
              )}
              {/* Input params below cascade bar */}
              {instance.input_data && Object.keys(instance.input_data).length > 0 ? (
                <div className="input-params-under-cascade">
                  {Object.entries(instance.input_data).map(([key, value]) => (
                    <div key={key} className="input-field-compact">
                      <span className="input-key">{key}:</span>
                      <span className="input-value">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="input-params-under-cascade no-inputs">
                  <span className="no-inputs-text">no inputs</span>
                </div>
              )}
              {/* Latest message for running cascades */}
              {(isSessionRunning || hasRunning) && latestMessages[instance.session_id] && (
                <>
                  <div className="latest-message-display">
                    <span className="latest-message-text">{latestMessages[instance.session_id].text}</span>
                  </div>
                  {latestMessages[instance.session_id].metadata && (
                    <div className="latest-message-metadata">
                      {latestMessages[instance.session_id].metadata}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Right section: RunPercentile + Children toggle (~25%) */}
            <div className="meta-section-compact">
              {!isChild && instances.length >= 2 && (
                <RunPercentile
                  instance={instance}
                  allInstances={instances}
                />
              )}
              {!isChild && instance.children && instance.children.length > 0 && (
                <div
                  className="children-toggle-compact"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpanded(instance.session_id);
                  }}
                >
                  <Icon
                    icon={expandedParents.has(instance.session_id) ? "mdi:chevron-down" : "mdi:chevron-right"}
                    width="16"
                  />
                  <span>{instance.children.length} sub</span>
                </div>
              )}
            </div>
          </div>
        </div>
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
          <span className="header-stat cost"><AnimatedCost value={totalCost} formatFn={formatCost} /></span>
        </div>
        <div className="header-right">
          {/* View mode toggle */}
          <div className="view-mode-toggle">
            <button
              className={`view-mode-btn ${viewMode === 'card' ? 'active' : ''}`}
              onClick={() => setViewMode('card')}
              title="Card View"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
            </button>
            <button
              className={`view-mode-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
              title="Grid View"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
          </div>
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

      {viewMode === 'card' ? (
        <>
          <div className="instances-list">
            {instances.map((instance) => {
              const isExpanded = expandedParents.has(instance.session_id);
              const hasChildren = instance.children && instance.children.length > 0;

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
        </>
      ) : (
        <InstanceGridView
          instances={instances}
          onSelectInstance={onSelectInstance}
          onFreezeInstance={onFreezeInstance}
          onRunCascade={onRunCascade}
          cascadeData={cascadeData}
          runningSessions={runningSessions}
          finalizingSessions={finalizingSessions}
          sessionStartTimes={sessionStartTimes}
          onSoundingsExplorer={(sessionId) => setSoundingsExplorerSession(sessionId)}
          onAudibleClick={handleAudibleClick}
          audibleSignaled={audibleSignaled}
          audibleSending={audibleSending}
          allInstances={instances}
        />
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
