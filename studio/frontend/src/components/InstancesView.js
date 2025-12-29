import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
// PhaseBar removed - now only shown in SplitDetailView
import CascadeBar from './CascadeBar';
import DebugModal from './DebugModal';
import SoundingsExplorer from './CandidatesExplorer';
import InstanceGridView from './InstanceGridView';
import CascadeFlowModal from './CascadeFlowModal';
// MermaidPreview, ImageGallery, HumanInputDisplay removed - now only shown in SplitDetailView
import VideoSpinner from './VideoSpinner';
import TokenSparkline from './TokenSparkline';
import ModelCostBar, { ModelTags } from './ModelCostBar';
import RunPercentile from './RunPercentile';
import PhaseSpeciesBadges from './CellTypeBadges';
import Header from './Header';
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
          // Parse timestamp as UTC (ClickHouse returns timestamps without timezone info)
          const normalized = timeSource.includes('Z') || timeSource.includes('+')
            ? timeSource
            : timeSource.replace(' ', 'T') + 'Z';
          parsed = new Date(normalized).getTime();
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

function InstancesView({ cascadeId, onBack, onSelectInstance, onFreezeInstance, onRunCascade, onInstanceComplete, cascadeData, refreshTrigger, runningCascades, runningSessions, finalizingSessions, sessionMetadata, sessionUpdates, sessionStartTimes, sseConnected, onBlocked, onMessageFlow, onCockpit, onSextant, onWorkshop, onPlayground, onTools, onSearch, onStudio, onArtifacts, onBrowser, onSessions, blockedCount }) {
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [debugSessionId, setDebugSessionId] = useState(null);
  const [soundingsExplorerSession, setSoundingsExplorerSession] = useState(null);
  const [expandedParents, setExpandedParents] = useState(new Set());
  const [viewMode, setViewMode] = useState('card'); // 'card' or 'grid'

  // Flow visualization modal state
  const [flowModalData, setFlowModalData] = useState(null); // { cascade, executionData, sessionId }

  // Audible state - track per session since multiple can be running
  const [audibleSignaled, setAudibleSignaled] = useState({});  // { sessionId: boolean }
  const [audibleSending, setAudibleSending] = useState({});    // { sessionId: boolean }

  // Cancel state - track per session
  const [cancelSending, setCancelSending] = useState({});      // { sessionId: boolean }
  const [cancelRequested, setCancelRequested] = useState({});  // { sessionId: timestamp } - when cancel was requested
  const FORCE_CANCEL_TIMEOUT_MS = 10000; // Show force cancel after 10 seconds

  // Latest messages for running sessions - track per session
  const [latestMessages, setLatestMessages] = useState({});    // { sessionId: { text, metadata } }

  // Session states from durable execution API - source of truth for running/blocked/cancelled
  const [sessionStates, setSessionStates] = useState({});      // { sessionId: { status, blocked_type, cancel_requested, etc } }

  const fetchInstances = useCallback(async () => {
    try {
      const response = await fetch(`http://localhost:5050/api/cascade-instances/${cascadeId}`);
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
            const allPhasesComplete = instance.cells?.every(p =>
              p.status === 'completed' || p.status === 'error'
            );
            const hasData = instance.total_cost > 0 || instance.cells?.length > 0;

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

  // Fetch session states from durable execution API
  // This is the source of truth for running/blocked/cancelled status
  const fetchSessionStates = useCallback(async (sessionIds) => {
    if (!sessionIds || sessionIds.length === 0) return;

    try {
      const response = await fetch('http://localhost:5050/api/sessions');
      if (!response.ok) return;

      const data = await response.json();
      if (!data.sessions) return;

      // Convert to map keyed by session_id
      const statesMap = {};
      data.sessions.forEach(session => {
        if (sessionIds.includes(session.session_id)) {
          statesMap[session.session_id] = session;
        }
      });

      setSessionStates(prev => ({ ...prev, ...statesMap }));
    } catch (err) {
      console.error('Error fetching session states:', err);
    }
  }, []);

  // Poll session states for displayed instances
  useEffect(() => {
    if (!instances || instances.length === 0) return;

    // Collect all session IDs (parents and children)
    const sessionIds = [];
    instances.forEach(inst => {
      sessionIds.push(inst.session_id);
      if (inst.children) {
        inst.children.forEach(child => sessionIds.push(child.session_id));
      }
    });

    // Initial fetch
    fetchSessionStates(sessionIds);

    // Poll every 2 seconds to keep session states fresh
    const interval = setInterval(() => {
      fetchSessionStates(sessionIds);
    }, 2000);

    return () => clearInterval(interval);
  }, [instances, fetchSessionStates]);

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
          const response = await fetch(`http://localhost:5050/api/session/${sessionId}`);
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
              if (entry.cell_name) {
                metaParts.push(`phase: ${entry.cell_name}`);
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
    if (!isoString) return 'N/A';
    // Parse timestamp as UTC by normalizing to ISO 8601 format
    // ClickHouse returns: "2025-12-11 04:12:56.055490" (no timezone)
    // We need to treat this as UTC, not local time
    const normalized = isoString.includes('Z') || isoString.includes('+')
      ? isoString  // Already has timezone info
      : isoString.replace(' ', 'T') + 'Z';  // Convert to ISO 8601 UTC format

    const date = new Date(normalized);
    // toLocaleString() will display in user's local timezone
    return date.toLocaleString();
  };

  const formatTimeAgo = (isoString) => {
    if (!isoString) return '';
    // Parse timestamp as UTC
    const normalized = isoString.includes('Z') || isoString.includes('+')
      ? isoString
      : isoString.replace(' ', 'T') + 'Z';

    const timestamp = new Date(normalized).getTime();
    const now = Date.now();
    const diffMs = now - timestamp;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
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
      const response = await fetch(`http://localhost:5050/api/audible/signal/${sessionId}`, {
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

  // Handle cancel button click for a specific session
  const handleCancelClick = async (e, sessionId, force = false) => {
    e.stopPropagation();

    // Don't cancel if already sending (but allow if already requested and forcing)
    if (cancelSending[sessionId]) return;
    if (cancelRequested[sessionId] && !force) return;

    setCancelSending(prev => ({ ...prev, [sessionId]: true }));

    try {
      const response = await fetch(`http://localhost:5050/api/sessions/${sessionId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: force ? 'Force cancelled via UI' : 'Cancelled via UI',
          force: force
        })
      });
      const data = await response.json();

      if (data.message) {
        // Store timestamp when cancel was requested (or clear if force succeeded)
        if (force || data.was_zombie || data.was_forced) {
          // Force cancel succeeded - clear the requested state
          setCancelRequested(prev => ({ ...prev, [sessionId]: null }));
        } else {
          // Regular cancel - store timestamp for force cancel timeout
          setCancelRequested(prev => ({ ...prev, [sessionId]: Date.now() }));
        }
        console.log(`[CANCEL] ${sessionId}: ${data.message}`);
      }
      if (data.error) {
        console.error(`[CANCEL] ${sessionId}: ${data.error}`);
      }
    } catch (err) {
      console.error('Failed to cancel session:', err);
    } finally {
      setCancelSending(prev => ({ ...prev, [sessionId]: false }));
    }
  };

  // Check if force cancel should be available (cancel requested > timeout ago)
  const shouldShowForceCancel = (sessionId) => {
    const requestedAt = cancelRequested[sessionId];
    if (!requestedAt) return false;
    return (Date.now() - requestedAt) > FORCE_CANCEL_TIMEOUT_MS;
  };

  // Handle visualize button click - fetch cascade spec and execution data, then show modal
  const handleVisualize = useCallback(async (sessionId, cascadeIdToFetch) => {
    try {
      // Fetch cascade spec and execution data in parallel
      const [cascadesResponse, executionResponse] = await Promise.all([
        fetch('http://localhost:5050/api/cascade-definitions'),
        fetch(`http://localhost:5050/api/session/${sessionId}/execution-flow`)
      ]);

      const cascades = await cascadesResponse.json();
      const executionData = await executionResponse.json();

      // Find the cascade spec
      const cascade = cascades.find(c => c.cascade_id === cascadeIdToFetch);

      if (!cascade) {
        console.error(`Cascade ${cascadeIdToFetch} not found`);
        return;
      }

      setFlowModalData({
        cascade,
        executionData: executionData.error ? null : executionData,
        sessionId
      });
    } catch (err) {
      console.error('Failed to fetch flow visualization data:', err);
    }
  }, []);

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

  // Clear cancel state when session is terminated (using session states as source of truth)
  useEffect(() => {
    setCancelRequested(prev => {
      const updated = { ...prev };
      let changed = false;
      for (const sessionId of Object.keys(updated)) {
        if (updated[sessionId]) {
          // Check session state for terminal status
          const sessionState = sessionStates[sessionId];
          const isTerminated = sessionState && ['cancelled', 'completed', 'failed', 'orphaned'].includes(sessionState.status);
          if (isTerminated) {
            updated[sessionId] = null;
            changed = true;
          }
        }
      }
      return changed ? updated : prev;
    });
  }, [sessionStates]);

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

  // Real-time updates for flow modal when viewing a running session
  useEffect(() => {
    if (!flowModalData?.sessionId) return;

    const sessionId = flowModalData.sessionId;
    const isRunning = runningSessions?.has(sessionId);

    // Only poll if the session is running
    if (!isRunning) return;

    const refreshExecutionData = async () => {
      try {
        const response = await fetch(`http://localhost:5050/api/session/${sessionId}/execution-flow`);
        const executionData = await response.json();

        if (!executionData.error) {
          setFlowModalData(prev => prev?.sessionId === sessionId
            ? { ...prev, executionData }
            : prev
          );
        }
      } catch (err) {
        console.error('Failed to refresh execution data:', err);
      }
    };

    // Poll every 1 second for running sessions
    const interval = setInterval(refreshExecutionData, 1000);
    refreshExecutionData(); // Initial fetch

    return () => clearInterval(interval);
  }, [flowModalData?.sessionId, runningSessions]);


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
    const isCompleted = instance.cells?.every(p => p.status === 'completed');
    const hasRunning = instance.cells?.some(p => p.status === 'running');
    const sseIsRunning = runningSessions && runningSessions.has(instance.session_id);
    const isFinalizing = finalizingSessions && finalizingSessions.has(instance.session_id);

    // Get durable execution session state (source of truth)
    const sessionState = sessionStates[instance.session_id];
    const durableStatus = sessionState?.status; // 'running', 'blocked', 'completed', 'cancelled', 'failed', 'orphaned'
    const isBlocked = durableStatus === 'blocked';
    const isCancelled = durableStatus === 'cancelled';
    const isOrphaned = durableStatus === 'orphaned';
    const cancelPending = sessionState?.cancel_requested && durableStatus === 'running';

    // Determine actual running state - use durable state as source of truth when available
    // If durable state says cancelled/completed/failed/orphaned, don't show as running
    const isTerminated = isCancelled || isOrphaned || durableStatus === 'completed' || durableStatus === 'failed';
    const isSessionRunning = !isTerminated && (sseIsRunning || durableStatus === 'running');

    // Calculate historical average for running sessions based on cascade + inputs
    const historicalAvg = getHistoricalAverage(instance.cascade_id, instance.input_data, instance.session_id);
    const showProgress = (isSessionRunning || hasRunning) && historicalAvg && !isFinalizing && !isBlocked;

    // Calculate current duration for running sessions
    let currentDuration = instance.duration_seconds || 0;
    if (isSessionRunning || hasRunning) {
      const sseStart = sessionStartTimes?.[instance.session_id];
      const dbStart = instance.start_time;
      const startTime = sseStart || dbStart;

      if (startTime) {
        let startMs;
        if (typeof startTime === 'number') {
          startMs = startTime < 10000000000 ? startTime * 1000 : startTime;
        } else {
          // Parse timestamp as UTC (ClickHouse returns timestamps without timezone info)
          const normalized = startTime.includes('Z') || startTime.includes('+')
            ? startTime
            : startTime.replace(' ', 'T') + 'Z';
          startMs = new Date(normalized).getTime();
        }

        if (!isNaN(startMs) && startMs > 0) {
          const now = Date.now();
          currentDuration = Math.max((now - startMs) / 1000, 0);
        }
      }
    }

    // Determine visual state - priority: cancelled > blocked > finalizing > running
    let stateClass = '';
    let stateBadge = null;

    if (isCancelled) {
      stateClass = 'cancelled';
      stateBadge = <span className="cancelled-badge"><Icon icon="mdi:cancel" width="14" style={{ marginRight: '4px' }} />Cancelled</span>;
    } else if (isOrphaned) {
      stateClass = 'orphaned';
      stateBadge = <span className="orphaned-badge"><Icon icon="mdi:ghost" width="14" style={{ marginRight: '4px' }} />Orphaned</span>;
    } else if (cancelPending) {
      stateClass = 'cancel-pending';
      stateBadge = <span className="cancel-pending-badge"><Icon icon="mdi:timer-sand" width="14" className="spinning" style={{ marginRight: '4px' }} />Cancelling...</span>;
    } else if (isBlocked) {
      const blockedType = sessionState?.blocked_type || 'signal';
      const blockedIcon = blockedType === 'human' ? 'mdi:account-clock' : 'mdi:clock-alert';
      stateClass = 'blocked';
      stateBadge = <span className="blocked-badge"><Icon icon={blockedIcon} width="14" style={{ marginRight: '4px' }} />Blocked ({blockedType})</span>;
    } else if (isFinalizing) {
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
          {(isSessionRunning || (hasRunning && !isFinalizing)) && !isBlocked && (
            <button
              className={`btn-compact audible ${audibleSignaled[instance.session_id] ? 'signaled' : ''}`}
              onClick={(e) => handleAudibleClick(e, instance.session_id)}
              disabled={audibleSending[instance.session_id] || audibleSignaled[instance.session_id]}
              title={audibleSignaled[instance.session_id] ? 'Audible signaled' : 'Call audible'}
            >
              <Icon icon="mdi:bullhorn" width="14" />
            </button>
          )}
          {/* Show cancel button for running, blocked, or finalizing sessions that aren't already terminated */}
          {(isSessionRunning || isBlocked || hasRunning || isFinalizing) && !isTerminated && (
            shouldShowForceCancel(instance.session_id) ? (
              // Force cancel button - shown after timeout when graceful cancel hasn't worked
              <button
                className="btn-compact cancel force"
                onClick={(e) => handleCancelClick(e, instance.session_id, true)}
                disabled={cancelSending[instance.session_id]}
                title="Force cancel - process may be unresponsive"
              >
                <Icon icon={cancelSending[instance.session_id] ? "mdi:loading" : "mdi:skull"} width="14" className={cancelSending[instance.session_id] ? 'spinning' : ''} />
              </button>
            ) : (
              // Regular cancel button
              <button
                className={`btn-compact cancel ${cancelRequested[instance.session_id] || cancelPending ? 'requested' : ''}`}
                onClick={(e) => handleCancelClick(e, instance.session_id)}
                disabled={cancelSending[instance.session_id] || cancelRequested[instance.session_id] || cancelPending}
                title={cancelRequested[instance.session_id] || cancelPending ? 'Cancel requested - waiting for process...' : 'Cancel cascade'}
              >
                <Icon icon={cancelSending[instance.session_id] ? "mdi:loading" : (cancelRequested[instance.session_id] || cancelPending) ? "mdi:timer-sand" : "mdi:stop-circle"} width="14" className={cancelSending[instance.session_id] || cancelRequested[instance.session_id] || cancelPending ? 'spinning' : ''} />
              </button>
            )
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
              <span className="timestamp-compact" title={formatTimestamp(instance.start_time)}>
                {formatTimeAgo(instance.start_time)}
              </span>
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
                    instance.cells
                      ?.filter(p => p.sounding_total > 1)
                      .flatMap(p => (p.sounding_attempts || []).filter(a => a.is_winner && a.model).map(a => a.model))
                      .filter((m, i, arr) => arr.indexOf(m) === i) // unique
                  }
                />
              )}
            </div>

            {/* Middle section: CascadeBar with inputs (~55%) */}
            <div className="cascade-section-compact">
              {instance.cells && instance.cells.length > 1 && (
                <CascadeBar
                  phases={instance.cells}
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
      <Header
        onBack={onBack}
        backLabel="Back to Cascades"
        centerContent={
          <>
            <div className="cascade-title-block">
              <span className="cascade-title">{cascadeId}</span>
              {cascadeData?.cascade_file && (
                <span className="cascade-file-path">{cascadeData.cascade_file}</span>
              )}
            </div>
            <span className="header-divider">·</span>
            <span className="header-stat">{instances.length} <span className="stat-dim">{instances.length === 1 ? 'instance' : 'instances'}</span></span>
            <span className="header-divider">·</span>
            <span className="header-stat cost"><AnimatedCost value={totalCost} formatFn={formatCost} /></span>
          </>
        }
        customButtons={
          <>
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
          </>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onPlayground={onPlayground}
        onTools={onTools}
        onSearch={onSearch}
        onStudio={onStudio}
        onArtifacts={onArtifacts}
        onBrowser={onBrowser}
        onSessions={onSessions}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {viewMode === 'card' ? (
        <>
          <div className="instances-list">
            {(() => {
              // Parse timestamps as UTC by appending 'Z' if not already present
              const parseUTC = (timeStr) => {
                if (!timeStr) return 0;
                // If timestamp doesn't have timezone info, treat as UTC
                const normalized = timeStr.includes('Z') || timeStr.includes('+')
                  ? timeStr
                  : timeStr.replace(' ', 'T') + 'Z';
                return new Date(normalized).getTime();
              };

              // Group instances by compound species signature
              // Multi-phase cascades have multiple species_hashes (one per phase with soundings)
              const groups = new Map();
              instances.forEach((instance) => {
                // Create compound key from sorted species_hashes array
                const hashes = instance.species_hashes || [];
                const key = hashes.length > 0 ? hashes.sort().join('+') : 'no_species';
                if (!groups.has(key)) {
                  groups.set(key, []);
                }
                groups.get(key).push(instance);
              });

              // Convert to array and sort by most recent activity (latest run in group)
              const sortedGroups = Array.from(groups.entries())
                .map(([speciesHash, instances]) => ({
                  speciesHash,
                  instances: instances.sort((a, b) => parseUTC(b.start_time) - parseUTC(a.start_time)), // Newest first (DESC)
                  latestTime: Math.max(...instances.map(i => parseUTC(i.start_time)))
                }))
                .sort((a, b) => b.latestTime - a.latestTime); // Groups by most recent activity

              return sortedGroups.map(({ speciesHash, instances: groupInstances }) => {
                const isNoSpecies = speciesHash === 'no_species';

                return (
                  <div key={speciesHash} className={`species-group ${isNoSpecies ? 'no-species' : ''}`}>
                    {!isNoSpecies && (
                      <div className="species-group-header">
                        <div className="species-info">
                          {/* Show multiple DNA icons for multi-phase cascades */}
                          {speciesHash.split('+').map((hash, idx) => (
                            <React.Fragment key={hash}>
                              <Icon icon="mdi:dna" width="14" className="species-icon" />
                              <span className="species-hash" title={hash}>
                                {hash.substring(0, 8)}...
                              </span>
                              {idx < speciesHash.split('+').length - 1 && (
                                <span className="species-separator">+</span>
                              )}
                            </React.Fragment>
                          ))}
                          <span className="species-count">
                            {groupInstances.length} generation{groupInstances.length !== 1 ? 's' : ''}
                          </span>
                        </div>
                        <div className="species-age">
                          {(() => {
                            // Parse timestamps as UTC by appending 'Z' if not already present
                            const parseUTC = (timeStr) => {
                              if (!timeStr) return 0;
                              // If timestamp doesn't have timezone info, treat as UTC
                              const normalized = timeStr.includes('Z') || timeStr.includes('+')
                                ? timeStr
                                : timeStr.replace(' ', 'T') + 'Z';
                              return new Date(normalized).getTime();
                            };

                            const latest = Math.max(...groupInstances.map(i => parseUTC(i.start_time)));
                            const now = Date.now();
                            const diffMs = now - latest;
                            const diffMins = Math.floor(diffMs / 60000);
                            const diffHours = Math.floor(diffMs / 3600000);
                            const diffDays = Math.floor(diffMs / 86400000);

                            if (diffMins < 1) return 'Just now';
                            if (diffMins < 60) return `${diffMins}m ago`;
                            if (diffHours < 24) return `${diffHours}h ago`;
                            return `${diffDays}d ago`;
                          })()}
                        </div>
                      </div>
                    )}

                    <div className="species-group-content">
                      {groupInstances.map((instance) => {
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
                  </div>
                );
              });
            })()}
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
          onVisualize={handleVisualize}
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

      {/* Flow Visualization Modal */}
      {flowModalData && (
        <CascadeFlowModal
          cascade={flowModalData.cascade}
          executionData={flowModalData.executionData}
          sessionId={flowModalData.sessionId}
          onClose={() => setFlowModalData(null)}
        />
      )}
    </div>
  );
}

export default InstancesView;
