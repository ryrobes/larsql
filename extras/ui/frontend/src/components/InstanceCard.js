import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import PhaseBar from './PhaseBar';
import CascadeBar from './CascadeBar';
import MermaidPreview from './MermaidPreview';
import ImageGallery from './ImageGallery';
import AudioGallery from './AudioGallery';
import HumanInputDisplay from './HumanInputDisplay';
import TokenSparkline from './TokenSparkline';
import ModelCostBar, { ModelTags } from './ModelCostBar';
import VideoSpinner from './VideoSpinner';
import './InstanceCard.css';

// Live duration counter that updates every second for running instances
// (Matches InstancesView's implementation for consistency)
function LiveDuration({ startTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);

  // Sanity check: duration should be reasonable (< 7 days = 604800 seconds)
  // This catches epoch timestamp issues that produce millions of minutes
  const MAX_REASONABLE_DURATION = 604800;

  useEffect(() => {
    if (isRunning && startTime) {
      // Calculate initial elapsed time
      const start = new Date(startTime).getTime();

      // Validate: start time must be reasonable (after year 2020)
      const minValidTime = new Date('2020-01-01').getTime();
      if (isNaN(start) || start < minValidTime) {
        // Invalid timestamp, fall back to static duration
        const duration = staticDuration || 0;
        setElapsed(duration >= 0 && duration < MAX_REASONABLE_DURATION ? duration : 0);
        return;
      }

      const updateElapsed = () => {
        const now = Date.now();
        const diff = (now - start) / 1000;
        // Sanity check - if unreasonable, show 0
        setElapsed(diff >= 0 && diff < MAX_REASONABLE_DURATION ? diff : 0);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 1000);

      return () => {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      };
    } else {
      // Not running, use static duration (with sanity check)
      const duration = staticDuration || 0;
      setElapsed(duration >= 0 && duration < MAX_REASONABLE_DURATION ? duration : 0);
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

function InstanceCard({ sessionId, runningSessions = new Set(), finalizingSessions = new Set(), sessionUpdates = {}, compact = false, hideOutput = false }) {
  const [instance, setInstance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [wideChart, setWideChart] = useState(false);
  const [waitingForData, setWaitingForData] = useState(false); // Running but no data yet

  const isSessionRunning = runningSessions.has(sessionId);
  const isFinalizing = finalizingSessions.has(sessionId);

  const fetchInstance = useCallback(async () => {
    try {
      // We need to get instance data from the cascade-instances endpoint
      // First, get session info to find cascade_id
      const sessionResp = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const sessionData = await sessionResp.json();

      if (sessionData.error) {
        // If session is running, treat as "waiting for data" not error
        if (isSessionRunning || isFinalizing) {
          setWaitingForData(true);
          setError(null);
          setLoading(false);
        } else {
          setError(sessionData.error);
          setLoading(false);
        }
        return;
      }

      // Parse instance data from entries
      const entries = sessionData.entries || [];
      if (entries.length === 0) {
        // If session is running, show waiting state instead of error
        if (isSessionRunning || isFinalizing) {
          setWaitingForData(true);
          setError(null);
          setLoading(false);
        } else {
          setError('No data found');
          setLoading(false);
        }
        return;
      }

      // Clear waiting/error states on successful data load
      setWaitingForData(false);
      setError(null);

      const cascadeEntry = entries.find(e => e.node_type === 'cascade');
      const firstEntry = entries[0];
      const lastEntry = entries[entries.length - 1];

      // Group entries by phase
      const phaseMap = {};
      entries.forEach(entry => {
        const phaseName = entry.phase_name || 'Initialization';
        if (!phaseMap[phaseName]) {
          phaseMap[phaseName] = {
            name: phaseName,
            entries: [],
            totalCost: 0,
            soundingAttempts: new Map(),
            toolCalls: new Set(),
            wardCount: 0,
            status: 'pending'
          };
        }
        phaseMap[phaseName].entries.push(entry);
        // Safely add cost, handling NaN and undefined
        const entryCost = typeof entry.cost === 'number' && !isNaN(entry.cost) ? entry.cost : 0;
        if (entryCost > 0) {
          phaseMap[phaseName].totalCost += entryCost;
        }
        if (entry.node_type === 'tool_call') {
          try {
            const meta = typeof entry.metadata === 'string' ? JSON.parse(entry.metadata) : entry.metadata;
            if (meta?.tool_name) {
              phaseMap[phaseName].toolCalls.add(meta.tool_name);
            }
          } catch (e) {}
        }
        if (entry.node_type && entry.node_type.includes('ward')) {
          phaseMap[phaseName].wardCount++;
        }
        if (entry.sounding_index !== null && entry.sounding_index !== undefined) {
          const idx = entry.sounding_index;
          if (!phaseMap[phaseName].soundingAttempts.has(idx)) {
            phaseMap[phaseName].soundingAttempts.set(idx, {
              index: idx,
              cost: 0,
              is_winner: false,
              model: null
            });
          }
          phaseMap[phaseName].soundingAttempts.get(idx).cost += entryCost;
          // Track winner status - if ANY entry has is_winner: true, mark as winner
          if (entry.is_winner === true) {
            phaseMap[phaseName].soundingAttempts.get(idx).is_winner = true;
          }
          // Track model for this sounding (use first non-null model found)
          if (entry.model && !phaseMap[phaseName].soundingAttempts.get(idx).model) {
            phaseMap[phaseName].soundingAttempts.get(idx).model = entry.model;
          }
        }
        // Track max turns
        if (entry.turn_number !== null && entry.turn_number !== undefined) {
          if (!phaseMap[phaseName].maxTurnSeen) {
            phaseMap[phaseName].maxTurnSeen = 0;
          }
          phaseMap[phaseName].maxTurnSeen = Math.max(phaseMap[phaseName].maxTurnSeen, entry.turn_number + 1);
        }
      });

      // Find the last phase with entries - if session is running, this is the active phase
      const phaseNames = Object.keys(phaseMap);
      const phasesWithEntries = phaseNames.filter(name => phaseMap[name].entries.length > 0);
      const lastActivePhase = phasesWithEntries.length > 0 ? phasesWithEntries[phasesWithEntries.length - 1] : null;

      const phases = Object.values(phaseMap).map(phase => {
        const lastEntryInPhase = phase.entries[phase.entries.length - 1];
        const hasError = phase.entries.some(e => e.node_type === 'error');
        const hasPhaseComplete = phase.entries.some(e => e.node_type === 'phase_complete');

        let outputSnippet = '';
        if (lastEntryInPhase?.content) {
          const content = lastEntryInPhase.content;
          if (typeof content === 'string') {
            outputSnippet = content.substring(0, 100);
          } else {
            outputSnippet = JSON.stringify(content).substring(0, 100);
          }
        }

        // Find the winning sounding index
        const soundingAttempts = Array.from(phase.soundingAttempts.values());
        const winnerAttempt = soundingAttempts.find(a => a.is_winner === true);
        const soundingWinner = winnerAttempt ? winnerAttempt.index : null;

        // Determine phase status:
        // - 'error' if any error entries
        // - 'running' if session is running AND this is the last active phase AND no phase_complete
        // - 'completed' if has entries and either has phase_complete or session is done
        // - 'pending' if no entries
        let status = 'pending';
        if (hasError) {
          status = 'error';
        } else if (phase.entries.length > 0) {
          const isActivePhase = (isSessionRunning || isFinalizing) && phase.name === lastActivePhase && !hasPhaseComplete;
          status = isActivePhase ? 'running' : 'completed';
        }

        return {
          name: phase.name,
          status,
          avg_cost: phase.totalCost,
          avg_duration: 0,
          message_count: phase.entries.length,
          sounding_attempts: soundingAttempts,
          sounding_total: phase.soundingAttempts.size,
          sounding_winner: soundingWinner,
          max_turns_actual: phase.maxTurnSeen || 1,
          max_turns: phase.maxTurnSeen || 1,
          tool_calls: Array.from(phase.toolCalls),
          ward_count: phase.wardCount,
          output_snippet: outputSnippet
        };
      });

      // Helper to safely get numeric value
      const safeNum = (val) => (typeof val === 'number' && !isNaN(val)) ? val : 0;

      const totalCost = entries.reduce((sum, e) => sum + safeNum(e.cost), 0);
      const totalTokensIn = entries.reduce((sum, e) => sum + safeNum(e.tokens_in), 0);
      const totalTokensOut = entries.reduce((sum, e) => sum + safeNum(e.tokens_out), 0);

      const modelsSet = new Set();
      const modelCostsMap = new Map();

      // First pass: find winning sounding indices per phase
      // is_winner is only set to true on specific entries, so we need to find which indices won
      const winningSoundingsByPhase = new Map(); // phase_name -> Set of winning sounding indices
      entries.forEach(e => {
        if (e.is_winner === true && e.sounding_index !== null && e.sounding_index !== undefined) {
          const phase = e.phase_name || 'unknown';
          if (!winningSoundingsByPhase.has(phase)) {
            winningSoundingsByPhase.set(phase, new Set());
          }
          winningSoundingsByPhase.get(phase).add(e.sounding_index);
        }
      });

      // Second pass: calculate costs
      let usedCost = 0;
      let explorationCost = 0;

      entries.forEach(e => {
        if (e.model) {
          modelsSet.add(e.model);
          const currentCost = modelCostsMap.get(e.model) || 0;
          modelCostsMap.set(e.model, currentCost + safeNum(e.cost));
        }

        // Track used vs exploration costs for soundings
        const entryCost = safeNum(e.cost);
        if (entryCost > 0) {
          const hasSounding = e.sounding_index !== null && e.sounding_index !== undefined;
          if (hasSounding) {
            const phase = e.phase_name || 'unknown';
            const winningIndices = winningSoundingsByPhase.get(phase);
            const isFromWinningSounding = winningIndices && winningIndices.has(e.sounding_index);
            if (isFromWinningSounding) {
              usedCost += entryCost;
            } else {
              explorationCost += entryCost;
            }
          } else {
            // Non-sounding entry - always used
            usedCost += entryCost;
          }
        }
      });

      const modelCosts = Array.from(modelCostsMap.entries()).map(([model, cost]) => ({ model, cost }));

      // Build token timeseries for sparkline
      const tokenTimeseries = entries
        .filter(e => e.tokens_in > 0)
        .map(e => ({
          timestamp: e.timestamp,
          tokens_in: e.tokens_in,
          tokens_out: e.tokens_out || 0
        }));

      const inputData = cascadeEntry?.metadata ?
        (typeof cascadeEntry.metadata === 'string' ? JSON.parse(cascadeEntry.metadata).input : cascadeEntry.metadata.input)
        : {};

      // Get final output from last assistant message
      const lastAssistant = [...entries].reverse().find(e => e.role === 'assistant' && e.content);
      const finalOutput = lastAssistant?.content || '';

      const hasRunningPhase = phases.some(p => p.status === 'running');

      // Helper to parse timestamps that could be ISO strings, Unix seconds, or Unix milliseconds
      const parseTimestamp = (ts) => {
        if (!ts) return null;
        // If it's a number or numeric string
        if (typeof ts === 'number' || /^\d+$/.test(ts)) {
          const num = typeof ts === 'number' ? ts : parseInt(ts, 10);
          // If it looks like seconds (< year 3000 in seconds), convert to ms
          // Unix seconds for year 3000 would be ~32503680000
          if (num < 32503680000) {
            return new Date(num * 1000);
          }
          return new Date(num);
        }
        // Otherwise treat as ISO string
        return new Date(ts);
      };

      const startDate = parseTimestamp(firstEntry?.timestamp);
      const endDate = parseTimestamp(lastEntry?.timestamp);

      // Calculate duration in seconds
      let durationSeconds = 0;
      if (startDate && endDate && !isNaN(startDate.getTime()) && !isNaN(endDate.getTime())) {
        durationSeconds = (endDate.getTime() - startDate.getTime()) / 1000;
        // Sanity check: duration should be positive and reasonable
        if (durationSeconds < 0 || durationSeconds > 604800) {
          durationSeconds = 0;
        }
      }

      setInstance({
        session_id: sessionId,
        cascade_id: cascadeEntry?.cascade_id || 'unknown',
        status: (isSessionRunning || isFinalizing) ? 'running' : (hasRunningPhase ? 'running' : 'completed'),
        start_time: startDate ? startDate.toISOString() : null,
        total_cost: totalCost,
        total_tokens_in: totalTokensIn,
        total_tokens_out: totalTokensOut,
        models_used: Array.from(modelsSet),
        model_costs: modelCosts,
        used_cost: usedCost,
        exploration_cost: explorationCost,
        input_data: inputData,
        final_output: finalOutput,
        phases: phases,
        token_timeseries: tokenTimeseries,
        duration_seconds: durationSeconds,
        error_count: entries.filter(e => e.node_type === 'error').length,
        has_soundings: phases.some(p => p.sounding_total > 1)
      });

      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }, [sessionId, isSessionRunning, isFinalizing]);

  useEffect(() => {
    if (sessionId) {
      fetchInstance();
    }
  }, [sessionId, fetchInstance]);

  // Polling for running sessions or waiting for data
  useEffect(() => {
    if (isSessionRunning || isFinalizing || waitingForData) {
      const interval = setInterval(fetchInstance, 2000);
      return () => clearInterval(interval);
    }
  }, [isSessionRunning, isFinalizing, waitingForData, fetchInstance]);

  const handleLayoutDetected = useCallback(({ isWide }) => {
    setWideChart(isWide);
  }, []);

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatTimestamp = (isoString) => {
    const date = new Date(isoString);
    return date.toLocaleString();
  };

  if (loading) {
    return (
      <div className="instance-card loading-state">
        <VideoSpinner
          message="Loading instance..."
          size="80%"
          opacity={0.6}
          messageStyle={{
            fontFamily: "'Julius Sans One', sans-serif",
            fontSize: 'clamp(1rem, 4vw, 2rem)',
            fontWeight: 'bold',
            letterSpacing: '0.1em',
            marginTop: '1.5rem'
          }}
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="instance-card error-state">
        <Icon icon="mdi:alert-circle" width="24" />
        <span>{error}</span>
      </div>
    );
  }

  // Waiting for data from running session
  if (waitingForData) {
    return (
      <div className="instance-card loading-state">
        <VideoSpinner
          message="Waiting for data..."
          size="80%"
          opacity={0.6}
          messageStyle={{
            fontFamily: "'Julius Sans One', sans-serif",
            fontSize: 'clamp(1rem, 4vw, 2rem)',
            fontWeight: 'bold',
            letterSpacing: '0.1em',
            marginTop: '1.5rem'
          }}
        />
      </div>
    );
  }

  if (!instance) return null;

  const hasRunning = instance.phases?.some(p => p.status === 'running');

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
    <div className={`instance-card ${stateClass} ${wideChart ? 'has-wide-chart' : ''} ${compact ? 'compact' : ''}`}>
      {/* Header */}
      <div className="instance-card-header">
        <div className="instance-card-header-left">
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
        <div className="instance-card-metrics-inline">
          <div className="metric-inline">
            <span className="metric-value">
              <LiveDuration
                startTime={instance.start_time}
                isRunning={isSessionRunning || isFinalizing}
                staticDuration={instance.duration_seconds}
              />
            </span>
          </div>
          <div className="metric-inline cost">
            <span className="metric-value cost-highlight">
              {formatCost(instance.total_cost)}
            </span>
          </div>
          {instance.token_timeseries && instance.token_timeseries.length > 0 && (
            <div className="token-sparkline-inline">
              <TokenSparkline data={instance.token_timeseries} width={80} height={20} />
            </div>
          )}
        </div>
      </div>

      {/* Wide Mermaid Chart - at top when wide */}
      {wideChart && (
        <div className="mermaid-wrapper-top">
          <MermaidPreview
            sessionId={instance.session_id}
            size="small"
            showMetadata={false}
            lastUpdate={sessionUpdates?.[instance.session_id]}
            onLayoutDetected={handleLayoutDetected}
          />
        </div>
      )}

      {/* Main content */}
      <div className="instance-card-content">
        {/* Left side: Info + Mermaid */}
        <div className="instance-card-info">
          {/* Model tags */}
          {instance.model_costs?.length <= 1 && instance.models_used?.length > 0 && (
            <div className="model-tags-row">
              <ModelTags modelsUsed={instance.models_used} />
            </div>
          )}

          {/* Multi-model cost breakdown */}
          {instance.model_costs?.length > 1 && (
            <ModelCostBar
              modelCosts={instance.model_costs}
              totalCost={instance.total_cost}
              usedCost={instance.used_cost}
              explorationCost={instance.exploration_cost}
            />
          )}

          {/* Input params */}
          {instance.input_data && Object.keys(instance.input_data).length > 0 && (
            <div className="input-params">
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

          {/* Mermaid Graph - under inputs (when not wide) */}
          {!wideChart && (
            <div className="mermaid-wrapper">
              <MermaidPreview
                sessionId={instance.session_id}
                size="small"
                showMetadata={false}
                lastUpdate={sessionUpdates?.[instance.session_id]}
                onLayoutDetected={handleLayoutDetected}
              />
            </div>
          )}
        </div>

        {/* Right side: Phase bars + Output */}
        <div className="instance-card-phases">
          {/* Cascade Bar - Sticky at top, outside scroll */}
          {instance.phases && instance.phases.length > 1 && (
            <div className="cascade-bar-sticky">
              <CascadeBar
                phases={instance.phases}
                totalCost={instance.total_cost}
                isRunning={isSessionRunning || hasRunning}
              />
            </div>
          )}

          {/* Scrollable phase bars container */}
          <div className="phase-bars-scroll">
            {/* Phase bars with images */}
            {(() => {
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
                  <ImageGallery
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                  <AudioGallery
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                  <HumanInputDisplay
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                </React.Fragment>
              ));
            })()}

            {/* Final Output */}
            {!hideOutput && instance.final_output && (
              <div className="final-output">
                <div className="final-output-content">
                  <ReactMarkdown>{instance.final_output}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default InstanceCard;
