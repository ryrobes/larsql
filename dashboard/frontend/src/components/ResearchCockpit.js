import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import CascadePicker from './CascadePicker';
import LiveOrchestrationSidebar from './LiveOrchestrationSidebar';
import HTMLSection from './sections/HTMLSection';
import RichMarkdown from './RichMarkdown';
import './ResearchCockpit.css';

/**
 * ResearchCockpit - Interactive research interface with live orchestration visualization
 *
 * Inspired by Bret Victor's principle of "making the invisible visible"
 *
 * Features:
 * - Live cascade execution with real-time updates
 * - Interactive decision points rendered inline
 * - Right sidebar showing orchestration state (phases, costs, tools, models)
 * - Timeline of results that grows as cascade executes
 * - Visual indicators for "thinking", tool calls, phase transitions
 *
 * Unlike Perplexity: You SEE the orchestration, costs, tool selection, multi-model thinking
 */
function ResearchCockpit({
  initialSessionId = null,
  onBack,
  onMessageFlow,
  onSextant,
  onWorkshop,
  onTools,
  onSearch,
  onArtifacts,
  onBlocked,
  blockedCount,
  sseConnected
}) {
  // State
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [cascadeId, setCascadeId] = useState(null);
  const [showPicker, setShowPicker] = useState(!initialSessionId);

  // Update sessionId when initialSessionId prop changes (e.g., navigating to saved session)
  useEffect(() => {
    console.log('[ResearchCockpit] initialSessionId changed:', initialSessionId);

    if (initialSessionId) {
      console.log('[ResearchCockpit] Loading session:', initialSessionId);
      setSessionId(initialSessionId);
      setShowPicker(false);
      setCascadeId(null); // Will be fetched from session data
      setCheckpoint(null);
      setTimeline([]);
      setOrchestrationState({
        currentPhase: null,
        currentModel: null,
        totalCost: 0,
        turnCount: 0,
        status: 'idle',
        lastToolCall: null,
        phaseHistory: [],
        soundings: null
      });
    } else {
      console.log('[ResearchCockpit] No initial session, showing picker');
      setShowPicker(true);
    }
  }, [initialSessionId]);

  // Live data
  const [checkpoint, setCheckpoint] = useState(null);
  const [sessionData, setSessionData] = useState(null);
  const [timeline, setTimeline] = useState([]); // History of interactions
  const [savedSessionData, setSavedSessionData] = useState(null); // Full saved session with checkpoints
  const [isSavedSession, setIsSavedSession] = useState(false);
  const [orchestrationState, setOrchestrationState] = useState({
    currentPhase: null,
    currentModel: null,
    totalCost: 0,
    turnCount: 0,
    status: 'idle', // idle, thinking, tool_running, waiting_human
    lastToolCall: null,
    phaseHistory: [],
    soundings: null
  });

  // SSE for real-time updates
  const eventSourceRef = useRef(null);

  // Fetch saved session data (if exists)
  const fetchSavedSession = useCallback(async () => {
    if (!sessionId) return;

    try {
      // Check if this session has been saved
      const res = await fetch(`http://localhost:5001/api/research-sessions?limit=100`);
      const data = await res.json();

      if (!data.error && data.sessions) {
        const saved = data.sessions.find(s => s.original_session_id === sessionId);

        if (saved) {
          console.log('[ResearchCockpit] Found saved session:', saved);

          // Fetch full details
          const detailRes = await fetch(`http://localhost:5001/api/research-sessions/${saved.id}`);
          const detailData = await detailRes.json();

          if (!detailData.error) {
            console.log('[ResearchCockpit] Loaded full saved session with', detailData.checkpoints_data?.length, 'checkpoints');
            setSavedSessionData(detailData);
            setIsSavedSession(true);
            return;
          }
        }
      }

      // Not a saved session
      setIsSavedSession(false);
      setSavedSessionData(null);

    } catch (err) {
      console.error('[ResearchCockpit] Failed to fetch saved session:', err);
    }
  }, [sessionId]);

  // Fetch session data
  const fetchSessionData = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const data = await res.json();

      if (!data.error && data.entries) {
        setSessionData(data);

        // Compute aggregated metrics from entries
        const entries = data.entries || [];

        // Get cascade_id from first entry
        const firstEntry = entries[0];
        if (firstEntry?.cascade_id) {
          setCascadeId(firstEntry.cascade_id);
        }

        // Compute total cost
        const totalCost = entries
          .filter(e => e.cost && e.cost > 0)
          .reduce((sum, e) => sum + e.cost, 0);

        // Get current/last phase
        const lastEntry = entries[entries.length - 1];
        const currentPhase = lastEntry?.phase_name;
        const currentModel = lastEntry?.model;

        // Count turns (assistant messages)
        const turnCount = entries.filter(e => e.role === 'assistant').length;

        // Compute phase costs
        const phaseCosts = {};
        entries.forEach(e => {
          if (e.phase_name && e.cost > 0) {
            phaseCosts[e.phase_name] = (phaseCosts[e.phase_name] || 0) + e.cost;
          }
        });

        // Count tokens
        const totalInputTokens = entries.reduce((sum, e) => sum + (e.input_tokens || 0), 0);
        const totalOutputTokens = entries.reduce((sum, e) => sum + (e.output_tokens || 0), 0);

        // Update sessionData with computed values
        const enrichedData = {
          ...data,
          total_cost: totalCost,
          current_phase: currentPhase,
          model: currentModel,
          total_turns: turnCount,
          phase_costs: phaseCosts,
          total_input_tokens: totalInputTokens,
          total_output_tokens: totalOutputTokens,
          created_at: firstEntry?.timestamp,
          duration_seconds: lastEntry?.timestamp && firstEntry?.timestamp
            ? (new Date(lastEntry.timestamp) - new Date(firstEntry.timestamp)) / 1000
            : 0
        };

        setSessionData(enrichedData);

        // Update orchestration state
        setOrchestrationState(prev => ({
          ...prev,
          currentPhase: currentPhase,
          currentModel: currentModel,
          totalCost: totalCost,
          turnCount: turnCount,
          status: prev.status // Keep current status from SSE events
        }));
      }
    } catch (err) {
      console.error('[ResearchCockpit] Failed to fetch session:', err);
    }
  }, [sessionId]);

  // Fetch pending checkpoint
  const fetchCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}`);
      const data = await res.json();

      if (!data.error) {
        const pending = data.checkpoints?.find(cp => cp.status === 'pending');

        if (pending && (!checkpoint || pending.id !== checkpoint.id)) {
          setCheckpoint(pending);

          // Update status
          setOrchestrationState(prev => ({
            ...prev,
            status: 'waiting_human'
          }));
        }
      }
    } catch (err) {
      console.error('[ResearchCockpit] Failed to fetch checkpoint:', err);
    }
  }, [sessionId, checkpoint]);

  // Setup SSE for real-time events
  useEffect(() => {
    if (!sessionId) return;

    const eventSource = new EventSource('http://localhost:5001/api/events/stream');
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);

        // Only process events for our session
        if (event.session_id !== sessionId) return;

        console.log('[ResearchCockpit] SSE event:', event.type, event.data);

        switch (event.type) {
          case 'cascade_start':
            console.log('[ResearchCockpit] Cascade started');
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'phase_start':
            console.log('[ResearchCockpit] Phase started:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              currentPhase: event.data.phase_name,
              currentModel: event.data.model,
              status: 'thinking',
              phaseHistory: [...prev.phaseHistory, {
                phase: event.data.phase_name,
                startedAt: new Date(),
                model: event.data.model
              }]
            }));
            break;

          case 'turn_start':
            console.log('[ResearchCockpit] Turn started:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'llm_request':
            console.log('[ResearchCockpit] LLM request:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking',
              currentModel: event.data.model
            }));
            break;

          case 'llm_response':
            console.log('[ResearchCockpit] LLM response received');
            setOrchestrationState(prev => ({
              ...prev,
              turnCount: prev.turnCount + 1
            }));
            fetchSessionData(); // Refresh for updated costs/tokens
            break;

          case 'phase_complete':
            console.log('[ResearchCockpit] Phase completed');
            fetchSessionData(); // Refresh for updated costs
            break;

          case 'tool_call':
            console.log('[ResearchCockpit] Tool call:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'tool_running',
              lastToolCall: event.data.tool_name
            }));
            break;

          case 'tool_result':
            console.log('[ResearchCockpit] Tool result received');
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking',
              lastToolCall: null
            }));
            break;

          case 'cost_update':
            console.log('[ResearchCockpit] Cost update:', event.data);
            fetchSessionData(); // Refresh for new cost
            break;

          case 'checkpoint_created':
          case 'checkpoint_waiting':
            console.log('[ResearchCockpit] Checkpoint created/waiting');
            fetchCheckpoint();
            setOrchestrationState(prev => ({
              ...prev,
              status: 'waiting_human'
            }));
            break;

          case 'checkpoint_responded':
            console.log('[ResearchCockpit] Checkpoint responded');
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'cascade_complete':
            console.log('[ResearchCockpit] Cascade complete');
            setOrchestrationState(prev => ({
              ...prev,
              status: 'idle'
            }));
            fetchSessionData();
            break;

          case 'cascade_error':
            console.log('[ResearchCockpit] Cascade error:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'idle'
            }));
            break;

          default:
            console.log('[ResearchCockpit] Unhandled event:', event.type, event.data);
            break;
        }
      } catch (err) {
        console.error('[ResearchCockpit] Failed to parse SSE event:', err);
      }
    };

    return () => {
      eventSource.close();
    };
  }, [sessionId, fetchSessionData, fetchCheckpoint]);

  // Poll for updates (more aggressive for live feel)
  useEffect(() => {
    if (!sessionId) return;

    // Initial fetch
    fetchSavedSession(); // Check if this is a saved session
    fetchSessionData();
    fetchCheckpoint();

    // Poll every second for live updates
    const interval = setInterval(() => {
      fetchSessionData();
      fetchCheckpoint();
    }, 1000);

    return () => clearInterval(interval);
  }, [sessionId, fetchSessionData, fetchCheckpoint, fetchSavedSession]);

  // Handle cascade selection
  const handleCascadeSelected = async (cascade, input) => {
    try {
      // Start new session
      const res = await fetch('http://localhost:5001/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_path: cascade.cascade_file,  // Backend expects cascade_path (file path)
          inputs: input,  // Backend expects 'inputs' not 'input'
          session_id: `research_${Date.now()}`
        })
      });

      const data = await res.json();

      if (data.error) {
        alert('Failed to start cascade: ' + data.error);
        return;
      }

      setSessionId(data.session_id);
      setCascadeId(cascade.cascade_id);
      setShowPicker(false);

      // Initialize orchestration state
      setOrchestrationState({
        currentPhase: null,
        currentModel: null,
        totalCost: 0,
        turnCount: 0,
        status: 'thinking',
        lastToolCall: null,
        phaseHistory: [],
        soundings: null
      });

    } catch (err) {
      console.error('[ResearchCockpit] Failed to start cascade:', err);
      alert('Failed to start cascade: ' + err.message);
    }
  };

  // Handle checkpoint response
  const handleCheckpointResponse = async (values) => {
    if (!checkpoint) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: values })
      });

      const data = await res.json();

      if (data.error) {
        alert('Failed to submit response: ' + data.error);
        return;
      }

      // Clear checkpoint and update status
      setCheckpoint(null);
      setOrchestrationState(prev => ({
        ...prev,
        status: 'thinking'
      }));

      // Add to timeline
      setTimeline(prev => [...prev, {
        type: 'interaction',
        timestamp: new Date(),
        checkpoint: checkpoint,
        response: values
      }]);

    } catch (err) {
      console.error('[ResearchCockpit] Failed to submit response:', err);
    }
  };

  // Handle new cascade
  const handleNewCascade = () => {
    setSessionId(null);
    setCascadeId(null);
    setCheckpoint(null);
    setSessionData(null);
    setTimeline([]);
    setShowPicker(true);
    setOrchestrationState({
      currentPhase: null,
      currentModel: null,
      totalCost: 0,
      turnCount: 0,
      status: 'idle',
      lastToolCall: null,
      phaseHistory: [],
      soundings: null
    });
  };

  // Sessions are now auto-saved! No manual save needed.
  // The backend automatically saves on:
  // - cascade_start (initial record)
  // - checkpoint_resumed (incremental updates)
  // - cascade_complete (finalize)

  return (
    <div className="research-cockpit">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:compass" width="28" style={{ marginRight: '8px' }} />
            <span className="header-stat">Research Cockpit</span>
            {cascadeId && (
              <>
                <span className="header-divider">·</span>
                <span className="header-stat cascade-name">{cascadeId}</span>
              </>
            )}
          </>
        }
        customButtons={
          sessionId && (
            <button
              className="new-session-btn"
              onClick={handleNewCascade}
              style={{
                padding: '8px 14px',
                background: 'linear-gradient(135deg, rgba(167, 139, 250, 0.15), rgba(94, 234, 212, 0.15))',
                border: '1px solid rgba(167, 139, 250, 0.3)',
                borderRadius: '8px',
                color: '#a78bfa',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '0.85rem',
                fontWeight: '500'
              }}
            >
              <Icon icon="mdi:plus-circle" width="18" />
              New Session
            </button>
          )
        }
        onMessageFlow={onMessageFlow}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onTools={onTools}
        onSearch={onSearch}
        onArtifacts={onArtifacts}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {/* Cascade Picker Modal */}
      {showPicker && (
        <CascadePicker
          onSelect={handleCascadeSelected}
          onCancel={() => {
            // If no session loaded, go back to previous view
            if (!sessionId) {
              if (onBack) onBack();
            } else {
              // Has session, just close picker
              setShowPicker(false);
            }
          }}
          onResumeSession={(session) => {
            // Session navigation is handled by CascadePicker changing hash
            // Just close the picker, useEffect will handle the rest
            setShowPicker(false);
          }}
        />
      )}

      {/* Main Layout */}
      {sessionId && !showPicker && (
        <div className="cockpit-layout">
          {/* Main Content Area - Timeline */}
          <div className="cockpit-main">
            {/* Saved Session Timeline (expandable checkpoints) */}
            {isSavedSession && savedSessionData && savedSessionData.checkpoints_data && savedSessionData.checkpoints_data.length > 0 && (
              <div className="saved-session-timeline">
                <div className="timeline-header-section">
                  <Icon icon="mdi:history" width="24" />
                  <div className="timeline-header-text">
                    <h2>Saved Research Session</h2>
                    <p>{savedSessionData.title}</p>
                  </div>
                  <div className="timeline-stats">
                    <span className="stat-badge">
                      <Icon icon="mdi:currency-usd" width="14" />
                      ${savedSessionData.total_cost?.toFixed(4)}
                    </span>
                    <span className="stat-badge">
                      <Icon icon="mdi:counter" width="14" />
                      {savedSessionData.total_turns} turns
                    </span>
                  </div>
                </div>

                {savedSessionData.checkpoints_data.map((checkpointData, idx) => (
                  <ExpandableCheckpoint
                    key={checkpointData.id || idx}
                    checkpoint={checkpointData}
                    index={idx}
                    sessionId={sessionId}
                  />
                ))}
              </div>
            )}

            {/* Current Checkpoint (if any) - for live sessions */}
            {!isSavedSession && checkpoint && checkpoint.ui_spec && (
              <div className="checkpoint-container">
                {(() => {
                  const hasHTMLSection = checkpoint.ui_spec.sections?.some(s => s.type === 'html');
                  const htmlSection = checkpoint.ui_spec.sections?.find(s => s.type === 'html');

                  if (hasHTMLSection && htmlSection) {
                    return (
                      <div className="checkpoint-html-view">
                        <HTMLSection
                          spec={htmlSection}
                          checkpointId={checkpoint.id}
                          sessionId={sessionId}
                        />
                      </div>
                    );
                  } else {
                    // Fallback: render question + simple form
                    return (
                      <div className="checkpoint-simple-view">
                        <h2 className="checkpoint-question">
                          {checkpoint.phase_output || 'Waiting for input...'}
                        </h2>
                        <form onSubmit={(e) => {
                          e.preventDefault();
                          const formData = new FormData(e.target);
                          const values = Object.fromEntries(formData.entries());
                          handleCheckpointResponse(values);
                        }}>
                          <input
                            type="text"
                            name="query"
                            placeholder="Type your response..."
                            className="simple-input"
                            autoFocus
                          />
                          <button type="submit" className="simple-submit">
                            Submit
                          </button>
                        </form>
                      </div>
                    );
                  }
                })()}
              </div>
            )}

            {/* Timeline of previous interactions */}
            {timeline.length > 0 && (
              <div className="timeline-history">
                <h3 className="timeline-header">
                  <Icon icon="mdi:history" width="20" />
                  History
                </h3>
                {timeline.map((item, idx) => (
                  <div key={idx} className="timeline-item">
                    <div className="timeline-item-header">
                      <span className="timeline-timestamp">
                        {item.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="timeline-item-content">
                      <RichMarkdown>{item.checkpoint?.phase_output || 'Interaction'}</RichMarkdown>
                      <div className="timeline-response">
                        Response: {JSON.stringify(item.response)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Empty state */}
            {!checkpoint && timeline.length === 0 && (
              <div className="cockpit-empty-state">
                <Icon icon="mdi:compass" width="80" className="empty-icon" />
                <h2>Session Active</h2>
                <p>Cascade is executing. Results will appear here.</p>
                <div className="status-indicator">
                  {orchestrationState.status === 'thinking' && (
                    <>
                      <Icon icon="mdi:loading" className="spinning" width="24" />
                      <span>Thinking...</span>
                    </>
                  )}
                  {orchestrationState.status === 'tool_running' && (
                    <>
                      <Icon icon="mdi:tools" className="pulsing" width="24" />
                      <span>Running tool: {orchestrationState.lastToolCall}</span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Right Sidebar - Live Orchestration Visualization */}
          <LiveOrchestrationSidebar
            sessionId={sessionId}
            cascadeId={cascadeId}
            orchestrationState={orchestrationState}
            sessionData={sessionData}
          />
        </div>
      )}
    </div>
  );
}

/**
 * ExpandableCheckpoint - Single checkpoint in the saved session timeline
 * Shows collapsed summary, expands to show full HTMX UI + user response
 */
function ExpandableCheckpoint({ checkpoint, index, sessionId }) {
  const [expanded, setExpanded] = useState(false);

  // Parse ui_spec if it's a string
  let uiSpec = checkpoint.ui_spec;
  if (typeof uiSpec === 'string') {
    try {
      uiSpec = JSON.parse(uiSpec);
    } catch (e) {
      console.error('[ExpandableCheckpoint] Failed to parse ui_spec:', e);
      uiSpec = null;
    }
  }

  // Parse response if it's a string
  let response = checkpoint.response;
  if (typeof response === 'string') {
    try {
      response = JSON.parse(response);
    } catch (e) {
      // Keep as string if not valid JSON
    }
  }

  const hasHTMLSection = uiSpec?.sections?.some(s => s.type === 'html');
  const htmlSection = uiSpec?.sections?.find(s => s.type === 'html');

  return (
    <div className={`expandable-checkpoint ${expanded ? 'expanded' : 'collapsed'}`}>
      {/* Collapsed Header - Always Visible */}
      <div
        className="checkpoint-header"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="checkpoint-number">
          {index + 1}
        </div>
        <div className="checkpoint-summary">
          <h3>{checkpoint.phase_output || 'Interaction'}</h3>
          <div className="checkpoint-meta">
            <span className="checkpoint-timestamp">
              <Icon icon="mdi:clock-outline" width="14" />
              {checkpoint.created_at ? new Date(checkpoint.created_at).toLocaleTimeString() : 'N/A'}
            </span>
            <span className="checkpoint-type">
              <Icon icon="mdi:tag" width="14" />
              {checkpoint.checkpoint_type || 'decision'}
            </span>
          </div>
        </div>
        <Icon
          icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'}
          width="24"
          className="expand-icon"
        />
      </div>

      {/* Expanded Content - Full HTMX UI */}
      {expanded && (
        <div className="checkpoint-expanded-content">
          {/* Render the full HTMX UI that was shown */}
          {hasHTMLSection && htmlSection && (
            <div className="checkpoint-html-replay">
              <div className="replay-label">
                <Icon icon="mdi:replay" width="16" />
                <span>Original UI</span>
              </div>
              <HTMLSection
                spec={htmlSection}
                checkpointId={checkpoint.id}
                sessionId={sessionId}
              />
            </div>
          )}

          {/* Show the user's response */}
          {response && (
            <div className="checkpoint-response-section">
              <div className="response-label">
                <Icon icon="mdi:account" width="16" />
                <span>Your Response</span>
              </div>
              <div className="response-content">
                {typeof response === 'object' ? (
                  <pre className="response-json">{JSON.stringify(response, null, 2)}</pre>
                ) : (
                  <div className="response-text">{response}</div>
                )}
              </div>
            </div>
          )}

          {/* No HTML section - show text */}
          {!hasHTMLSection && (
            <div className="checkpoint-text-content">
              <p>{checkpoint.phase_output}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ResearchCockpit;
