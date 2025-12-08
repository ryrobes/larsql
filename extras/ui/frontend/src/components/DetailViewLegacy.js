import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Icon } from '@iconify/react';
import axios from 'axios';
import VideoSpinner from './VideoSpinner';
import LiveDebugLog from './LiveDebugLog';
import InteractiveMermaid from './InteractiveMermaid';
import MetricsCards from './MetricsCards';
import ParametersCard from './ParametersCard';
import PhaseBar from './PhaseBar';
import CascadeBar from './CascadeBar';
import { deduplicateEntries, filterEntriesByViewMode, groupEntriesByPhase } from '../utils/debugUtils';
import './DetailViewLegacy.css';

const API_BASE_URL = 'http://localhost:5001/api';

function DetailViewLegacy({ sessionId, onBack, runningSessions = new Set(), finalizingSessions = new Set() }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [entries, setEntries] = useState([]);
  const [instance, setInstance] = useState(null);
  const [activePhase, setActivePhase] = useState(null);
  const [viewMode, setViewMode] = useState('all'); // 'all', 'conversation', 'structural'
  const [showStructural, setShowStructural] = useState(false);
  const [lastEntryCount, setLastEntryCount] = useState(0); // Track entry count to detect changes

  // Audible system state
  const [audibleSignaled, setAudibleSignaled] = useState(false);
  const [audibleSending, setAudibleSending] = useState(false);

  const isRunning = runningSessions.has(sessionId) || finalizingSessions.has(sessionId);
  const fetchingRef = useRef(false); // Prevent concurrent fetches

  // Handle audible button click
  const handleAudibleClick = useCallback(async () => {
    if (audibleSending || audibleSignaled) return;

    setAudibleSending(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/audible/signal/${sessionId}`);
      if (response.data.status === 'signaled') {
        setAudibleSignaled(true);
        // Clear the signaled state after a timeout (in case checkpoint never shows)
        setTimeout(() => setAudibleSignaled(false), 30000);
      }
    } catch (err) {
      console.error('Failed to signal audible:', err);
    } finally {
      setAudibleSending(false);
    }
  }, [sessionId, audibleSending, audibleSignaled]);

  // Reset audible state when session changes
  useEffect(() => {
    setAudibleSignaled(false);
    setAudibleSending(false);
  }, [sessionId]);

  // Memoize grouped entries to prevent recalculation on every render
  const groupedEntries = useMemo(() => {
    if (entries.length === 0) return [];
    const filtered = filterEntriesByViewMode(entries, viewMode, showStructural);
    return groupEntriesByPhase(filtered);
  }, [entries, viewMode, showStructural]);

  // Parse instance-level metadata from entries
  const parseInstanceFromEntries = useCallback((entries) => {
    if (!entries || entries.length === 0) return null;

    const cascadeEntry = entries.find(e => e.node_type === 'cascade');
    const firstEntry = entries[0];
    const lastEntry = entries[entries.length - 1];

    // Group entries by phase to calculate phase summaries
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
      if (entry.cost) {
        phaseMap[phaseName].totalCost += entry.cost;
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
            is_winner: entry.is_winner,
            model: null
          });
        }
        phaseMap[phaseName].soundingAttempts.get(idx).cost += entry.cost || 0;
        // Track model for this sounding (use first non-null model found)
        if (entry.model && !phaseMap[phaseName].soundingAttempts.get(idx).model) {
          phaseMap[phaseName].soundingAttempts.get(idx).model = entry.model;
        }
      }
    });

    // Convert phase map to array
    const phases = Object.values(phaseMap).map(phase => {
      const lastEntryInPhase = phase.entries[phase.entries.length - 1];
      const hasError = phase.entries.some(e => e.node_type === 'error');

      // Handle content that might be string, object, or array
      let outputSnippet = '';
      if (lastEntryInPhase?.content) {
        const content = lastEntryInPhase.content;
        if (typeof content === 'string') {
          outputSnippet = content.substring(0, 100);
        } else {
          outputSnippet = JSON.stringify(content).substring(0, 100);
        }
      }

      return {
        name: phase.name,
        status: hasError ? 'error' : (phase.entries.length > 0 ? 'completed' : 'pending'),
        avg_cost: phase.totalCost,
        avg_duration: 0,
        message_count: phase.entries.length,
        sounding_attempts: Array.from(phase.soundingAttempts.values()),
        tool_calls: Array.from(phase.toolCalls),
        ward_count: phase.wardCount,
        output_snippet: outputSnippet
      };
    });

    const totalCost = entries.reduce((sum, e) => sum + (e.cost || 0), 0);
    const totalTokensIn = entries.reduce((sum, e) => sum + (e.tokens_in || 0), 0);
    const totalTokensOut = entries.reduce((sum, e) => sum + (e.tokens_out || 0), 0);

    const modelsSet = new Set();
    entries.forEach(e => {
      if (e.model) {
        modelsSet.add(e.model);
      }
    });

    const inputData = cascadeEntry?.metadata ?
      (typeof cascadeEntry.metadata === 'string' ? JSON.parse(cascadeEntry.metadata).input : cascadeEntry.metadata.input)
      : {};
    const finalOutput = lastEntry?.content || '';

    return {
      session_id: sessionId,
      cascade_id: cascadeEntry?.cascade_id || 'unknown',
      status: isRunning ? 'running' : 'completed',
      start_time: firstEntry?.timestamp || null,
      total_cost: totalCost,
      total_tokens_in: totalTokensIn,
      total_tokens_out: totalTokensOut,
      models_used: Array.from(modelsSet),
      input_data: inputData,
      final_output: finalOutput,
      phases: phases,
      error_count: entries.filter(e => e.node_type === 'error').length
    };
  }, [sessionId, isRunning]);

  const fetchData = useCallback(async () => {
    if (fetchingRef.current) return; // Prevent concurrent fetches

    try {
      fetchingRef.current = true;

      // Fetch debug data
      const debugResp = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const debugData = await debugResp.json();

      if (debugData.error) {
        setError(debugData.error);
        setLoading(false);
        fetchingRef.current = false;
        return;
      }

      const newEntries = debugData.entries || [];

      // Only update if entry count changed (new data arrived)
      if (newEntries.length !== lastEntryCount) {
        const deduplicated = deduplicateEntries(newEntries);
        setEntries(deduplicated);
        setLastEntryCount(newEntries.length);

        // Parse instance metadata
        const instanceData = parseInstanceFromEntries(newEntries);
        setInstance(instanceData);
      }

      setLoading(false);
      fetchingRef.current = false;
    } catch (err) {
      setError(err.message);
      setLoading(false);
      fetchingRef.current = false;
    }
  }, [sessionId, lastEntryCount, parseInstanceFromEntries]);

  // Initial fetch
  useEffect(() => {
    if (sessionId) {
      fetchData();
    }
  }, [sessionId, fetchData]);

  // Polling for running cascades
  useEffect(() => {
    if (isRunning) {
      const interval = setInterval(() => {
        fetchData();
      }, 1500); // Poll every 1.5 seconds for live updates
      return () => clearInterval(interval);
    }
  }, [isRunning, fetchData]);

  const handlePhaseClick = useCallback((phaseName) => {
    setActivePhase(phaseName);
  }, []);

  const handlePhaseChange = useCallback((phaseName) => {
    setActivePhase(phaseName);
  }, []);

  // Memoize max cost calculation for PhaseBar
  const maxCost = useMemo(() => {
    if (!instance || !instance.phases || instance.phases.length === 0) return 0;
    return Math.max(...instance.phases.map(p => p.avg_cost));
  }, [instance]);

  if (!sessionId) return null;

  return (
    <div className="detail-view">
      {/* Header */}
      <div className="detail-header">
        <div className="header-left">
          <button className="back-button" onClick={onBack} title="Back to instances">
            <Icon icon="mdi:arrow-left" width="20" />
            Back
          </button>
          <div className="session-info">
            <span className="session-label">Session:</span>
            <span className="session-id">{sessionId.substring(0, 8)}...</span>
          </div>
          {instance && (
            <>
              <span className={`status-badge ${instance.status}`}>
                {instance.status === 'running' && <Icon icon="mdi:loading" width="16" className="spinning" />}
                {instance.status}
              </span>
              <span className="cost-badge">
                <Icon icon="mdi:currency-usd" width="16" />
                ${instance.total_cost.toFixed(4)}
              </span>
            </>
          )}
        </div>
        <div className="header-right">
          {/* Audible button - only shown when cascade is running */}
          {isRunning && (
            <button
              className={`audible-button ${audibleSignaled ? 'signaled' : ''}`}
              onClick={handleAudibleClick}
              disabled={audibleSending || audibleSignaled}
              title={audibleSignaled ? 'Audible signaled - waiting for safe point' : 'Call audible - inject feedback mid-phase'}
            >
              <Icon icon="mdi:bullhorn" width="16" className="audible-icon" />
              {audibleSending ? 'Signaling...' : audibleSignaled ? 'Signaled!' : 'Audible'}
            </button>
          )}

          {/* View mode selector */}
          <select
            className="view-mode-select"
            value={viewMode}
            onChange={e => setViewMode(e.target.value)}
            title="Filter message types"
          >
            <option value="conversation">Conversation</option>
            <option value="all">All Entries</option>
            <option value="structural">Structural</option>
          </select>
        </div>
      </div>

      {/* Main Content */}
      <div className="detail-panes">
        {/* Left Pane */}
        <div className="left-pane">
          {loading ? (
            <div className="loading-state">
              <VideoSpinner message="Loading session data..." size={200} opacity={0.6} />
            </div>
          ) : error ? (
            <div className="error-state">
              <Icon icon="mdi:alert-circle" width="32" />
              <p>{error}</p>
            </div>
          ) : (
            <>
              {/* Mermaid Graph */}
              <div className="detail-mermaid-section">
                <InteractiveMermaid
                  sessionId={sessionId}
                  activePhase={activePhase}
                  onPhaseClick={handlePhaseClick}
                  lastUpdate={lastEntryCount}
                />
              </div>

              {/* Metrics Cards */}
              {instance && (
                <MetricsCards instance={instance} />
              )}

              {/* Phase Timeline */}
              {instance && instance.phases && instance.phases.length > 0 && (
                <div className="phase-timeline-section">
                  <h3 className="section-title">
                    <Icon icon="mdi:timeline" width="20" />
                    Phase Timeline
                  </h3>

                  {/* Cascade Bar - cost distribution overview */}
                  {instance.phases.length > 1 && (
                    <CascadeBar
                      phases={instance.phases}
                      totalCost={instance.total_cost}
                      isRunning={isRunning}
                    />
                  )}

                  <div className="phase-timeline">
                    {instance.phases.map((phase, idx) => (
                      <div
                        key={phase.name}
                        className={`phase-timeline-item ${activePhase === phase.name ? 'active' : ''}`}
                        onClick={() => handlePhaseClick(phase.name)}
                      >
                        <PhaseBar phase={phase} maxCost={maxCost} phaseIndex={idx} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Parameters Card */}
              {instance && (
                <ParametersCard instance={instance} />
              )}
            </>
          )}
        </div>

        {/* Right Pane */}
        <div className="right-pane">
          {!loading && !error && (
            <LiveDebugLog
              sessionId={sessionId}
              groupedEntries={groupedEntries}
              activePhase={activePhase}
              onPhaseChange={handlePhaseChange}
              isRunning={isRunning}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default React.memo(DetailViewLegacy);
