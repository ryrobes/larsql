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
  onCockpit,
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
      setCascadeInputs(null); // Will be fetched from session data if available
      setCheckpoint(null);
      setTimeline([]);
      setCheckpointHistory([]); // Clear checkpoint history for new session
      setGhostMessages([]); // Clear ghost messages for new session
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
  const [checkpointHistory, setCheckpointHistory] = useState([]); // ALL checkpoints for live session (both pending and responded)
  const [savedSessionData, setSavedSessionData] = useState(null); // Full saved session with checkpoints
  const [isSavedSession, setIsSavedSession] = useState(false);
  const [ghostMessages, setGhostMessages] = useState([]); // Live thinking/tool messages (cleared on checkpoint)
  const [cascadeInputs, setCascadeInputs] = useState(null); // Initial inputs when cascade started
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
  const [roundEvents, setRoundEvents] = useState([]); // Events accumulated during current agent round

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

            // Check if this is a new branch (has parent but no checkpoints yet)
            const isNewBranch = detailData.parent_session_id &&
                               (!detailData.checkpoints_data || detailData.checkpoints_data.length === 0);

            if (isNewBranch) {
              console.log('[ResearchCockpit] Detected new branch - cascade is starting');
            }

            setSavedSessionData(detailData);
            setIsSavedSession(true);
            return;
          }
        }
      }

      // Not a saved session (yet) - might be a very new branch
      // Keep retrying for a bit
      setIsSavedSession(false);
      setSavedSessionData(null);

    } catch (err) {
      console.error('[ResearchCockpit] Failed to fetch saved session:', err);
    }
  }, [sessionId]);

  // Extract ghost messages from session data (messages since last checkpoint)
  const extractGhostMessages = useCallback((entries) => {
    if (!entries || entries.length === 0) return [];

    const ghosts = [];

    // Process entries in reverse to find messages since last checkpoint response
    for (let i = entries.length - 1; i >= 0; i--) {
      const entry = entries[i];

      // Stop when we hit a checkpoint response (start of current thinking cycle)
      if (entry.content && typeof entry.content === 'string' &&
          entry.content.includes('checkpoint_responded')) {
        break;
      }

      // Capture interesting events
      if (entry.role === 'assistant' && entry.content) {
        // Tool calls
        if (entry.tool_calls && entry.tool_calls.length > 0) {
          entry.tool_calls.forEach(tc => {
            ghosts.unshift({
              type: 'tool_call',
              tool: tc.function?.name || 'unknown',
              timestamp: entry.timestamp,
              id: `${entry.timestamp}_${tc.id}`
            });
          });
        }

        // Text responses
        if (entry.content && !entry.tool_calls) {
          ghosts.unshift({
            type: 'thinking',
            content: entry.content.substring(0, 200),
            timestamp: entry.timestamp,
            id: `${entry.timestamp}_text`
          });
        }
      }

      // Tool results
      if (entry.role === 'tool' && entry.tool_call_id) {
        ghosts.unshift({
          type: 'tool_result',
          tool: entry.name || 'tool',
          content: entry.content?.substring(0, 100),
          timestamp: entry.timestamp,
          id: `${entry.timestamp}_result`
        });
      }
    }

    return ghosts.slice(-10); // Keep last 10 messages
  }, []);

  // Fetch session data
  const fetchSessionData = useCallback(async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const data = await res.json();

      if (!data.error && data.entries) {
        setSessionData(data);

        // Extract ghost messages for live sessions
        if (!isSavedSession) {
          const ghosts = extractGhostMessages(data.entries);
          setGhostMessages(ghosts);
        }

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
  }, [sessionId, isSavedSession, extractGhostMessages]);

  // Fetch pending checkpoint
  const fetchCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      // Request ALL checkpoints (pending + responded) for timeline visualization
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}&include_all=true`);
      const data = await res.json();

      console.log('[ResearchCockpit] Checkpoint fetch result:', {
        sessionId,
        checkpointCount: data.checkpoints?.length,
        hasPending: data.checkpoints?.some(cp => cp.status === 'pending')
      });

      if (!data.error) {
        const allCheckpoints = data.checkpoints || [];
        const pending = allCheckpoints.find(cp => cp.status === 'pending');

        // Update checkpoint history (ALL checkpoints - for timeline display)
        // Sort by created_at to show in chronological order
        const sortedCheckpoints = [...allCheckpoints].sort((a, b) =>
          new Date(a.created_at) - new Date(b.created_at)
        );
        setCheckpointHistory(sortedCheckpoints);

        const respondedCount = sortedCheckpoints.filter(cp => cp.status === 'responded').length;
        const pendingCount = sortedCheckpoints.filter(cp => cp.status === 'pending').length;
        console.log('[ResearchCockpit] Updated checkpoint history:', {
          total: sortedCheckpoints.length,
          responded: respondedCount,
          pending: pendingCount,
          checkpointIds: sortedCheckpoints.map(c => c.id.slice(0, 8))
        });

        // Set current pending checkpoint (if any)
        if (pending && (!checkpoint || pending.id !== checkpoint.id)) {
          console.log('[ResearchCockpit] ✓ Setting checkpoint:', pending.id);
          setCheckpoint(pending);

          // Update status
          setOrchestrationState(prev => ({
            ...prev,
            status: 'waiting_human'
          }));
        } else if (pending) {
          console.log('[ResearchCockpit] Checkpoint unchanged:', pending.id);
        } else {
          console.log('[ResearchCockpit] No pending checkpoint found');
          setCheckpoint(null); // Clear if no pending
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
            // Clear round events at start of new turn
            setRoundEvents([]);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'llm_request':
            console.log('[ResearchCockpit] LLM request:', event.data);
            setRoundEvents(prev => [...prev, {
              type: 'llm_request',
              model: event.data.model?.split('/').pop() || 'LLM',
              timestamp: Date.now(),
              id: `llm_${Date.now()}`
            }]);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking',
              currentModel: event.data.model
            }));
            break;

          case 'llm_response':
            console.log('[ResearchCockpit] LLM response received');
            setRoundEvents(prev => [...prev, {
              type: 'llm_response',
              timestamp: Date.now(),
              id: `llm_resp_${Date.now()}`
            }]);
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
            setRoundEvents(prev => [...prev, {
              type: 'tool_call',
              tool: event.data.tool_name,
              timestamp: Date.now(),
              id: `tool_${Date.now()}_${event.data.tool_name}`
            }]);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'tool_running',
              lastToolCall: event.data.tool_name
            }));
            break;

          case 'tool_result':
            console.log('[ResearchCockpit] Tool result received');
            setRoundEvents(prev => [...prev, {
              type: 'tool_result',
              tool: event.data.tool_name,
              timestamp: Date.now(),
              id: `result_${Date.now()}`
            }]);
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
            console.log('[ResearchCockpit] Checkpoint created/waiting - clearing ghost messages');
            // Clear ghost messages and round events when checkpoint arrives
            setGhostMessages([]);
            setRoundEvents([]); // Clear round events - checkpoint marks end of agent work
            fetchCheckpoint();
            setOrchestrationState(prev => ({
              ...prev,
              status: 'waiting_human'
            }));
            break;

          case 'checkpoint_responded':
            console.log('[ResearchCockpit] Checkpoint responded');
            // Refresh checkpoint history to show the newly responded checkpoint as collapsed
            fetchCheckpoint();
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'cascade_complete':
            console.log('[ResearchCockpit] Cascade complete');
            setRoundEvents([]); // Clear round events on cascade complete
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

    // Poll saved session more frequently (for branches that are loading)
    const savedSessionInterval = setInterval(() => {
      fetchSavedSession();
    }, 2000);

    // Poll live data every second
    const liveDataInterval = setInterval(() => {
      fetchSessionData();
      fetchCheckpoint();
    }, 1000);

    return () => {
      clearInterval(savedSessionInterval);
      clearInterval(liveDataInterval);
    };
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
      setCascadeInputs(input); // Store the initial inputs
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

      // Clear checkpoint, ghost messages, and update status
      setCheckpoint(null);
      setGhostMessages([]); // Clear any residual ghost messages
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

      // CRITICAL: Refresh checkpoint history to include the newly responded checkpoint
      // This will show it as a collapsed card in the timeline
      setTimeout(() => {
        fetchCheckpoint();
      }, 500); // Small delay to ensure backend has processed the response

    } catch (err) {
      console.error('[ResearchCockpit] Failed to submit response:', err);
    }
  };

  // Handle new cascade
  const handleNewCascade = () => {
    setSessionId(null);
    setCascadeId(null);
    setCascadeInputs(null); // Clear cascade inputs
    setCheckpoint(null);
    setSessionData(null);
    setTimeline([]);
    setCheckpointHistory([]); // Clear checkpoint history
    setGhostMessages([]); // Clear ghost messages
    setRoundEvents([]); // Clear round events
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

  // Handle branch creation from checkpoint (works for both saved and live sessions)
  const handleCreateBranch = async (checkpointIndex, newResponse) => {
    console.log('[ResearchCockpit] Creating branch from checkpoint', checkpointIndex, 'with response:', newResponse);

    try {
      // If this is a live session (not saved yet), trigger a save first
      let researchSessionId = savedSessionData?.id;

      if (!researchSessionId) {
        console.log('[ResearchCockpit] Live session - fetching/creating saved session first...');

        // Check if session was auto-saved already
        const checkRes = await fetch(`http://localhost:5001/api/research-sessions?limit=100`);
        const checkData = await checkRes.json();

        if (!checkData.error && checkData.sessions) {
          const existing = checkData.sessions.find(s => s.original_session_id === sessionId);
          if (existing) {
            researchSessionId = existing.id;
            console.log('[ResearchCockpit] Found auto-saved session:', researchSessionId);
          }
        }

        // If still not found, session hasn't been saved yet - can't branch
        if (!researchSessionId) {
          alert('Cannot branch from live session - session not saved yet. Try again after the next interaction.');
          return;
        }
      }

      const res = await fetch('http://localhost:5001/api/research-sessions/branch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parent_research_session_id: researchSessionId,
          branch_checkpoint_index: checkpointIndex,
          new_response: newResponse
        })
      });

      const data = await res.json();

      if (data.error) {
        alert('Failed to create branch: ' + data.error);
        return;
      }

      console.log('[ResearchCockpit] ✓ Branch created:', data.new_session_id);

      // Navigate to the new branch
      window.location.hash = `#/cockpit/${data.new_session_id}`;

      // Show toast/notification
      alert(`🌿 Branch created!\n\nNew session: ${data.new_session_id}\nBranching from checkpoint ${checkpointIndex + 1}`);

    } catch (err) {
      console.error('[ResearchCockpit] Failed to create branch:', err);
      alert('Failed to create branch: ' + err.message);
    }
  };

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
        onCockpit={onCockpit}
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
            {/* Sticky Context Header - Shows initial inputs and latest checkpoint feedback */}
            <CascadeContextHeader
              cascadeInputs={cascadeInputs}
              checkpointHistory={checkpointHistory}
              cascadeId={cascadeId}
              savedSessionData={savedSessionData}
            />

            {console.log('[ResearchCockpit] Render decision:', {
              isSavedSession,
              savedStatus: savedSessionData?.status,
              hasCheckpoint: !!checkpoint,
              checkpointId: checkpoint?.id,
              savedCheckpointsCount: savedSessionData?.checkpoints_data?.length,
              checkpointHistoryCount: checkpointHistory.length,
              willShowSavedTimeline: isSavedSession && savedSessionData?.status === 'completed',
              willShowLiveTimeline: (!isSavedSession || savedSessionData?.status === 'active') && checkpointHistory.length > 0
            })}
            {/* Saved Session Timeline (ONLY for completed sessions) */}
            {isSavedSession && savedSessionData && savedSessionData.status === 'completed' && savedSessionData.checkpoints_data && savedSessionData.checkpoints_data.length > 0 && (
              <div className="saved-session-timeline">
                <div className="timeline-header-section">
                  <Icon icon="mdi:history" width="24" />
                  <div className="timeline-header-text">
                    <h2>Saved Research Session</h2>
                    <p>{savedSessionData.title}</p>
                    {savedSessionData.parent_session_id && (
                      <div className="branch-badge">
                        <Icon icon="mdi:source-fork" width="14" />
                        <span>Branch of {savedSessionData.parent_session_id.slice(0, 12)}...</span>
                      </div>
                    )}
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
                    savedSessionData={savedSessionData}
                    onBranch={handleCreateBranch}
                  />
                ))}
              </div>
            )}

            {/* Ghost Messages - Show live thinking/tool activity */}
            {!isSavedSession && ghostMessages.length > 0 && (
              <div className="ghost-messages">
                {ghostMessages.map(ghost => (
                  <GhostMessage key={ghost.id} ghost={ghost} />
                ))}
              </div>
            )}

            {/* Live Session Checkpoint Timeline - show ALL checkpoints (responded + pending) */}
            {/* Show for: unsaved sessions OR active saved sessions */}
            {(!isSavedSession || savedSessionData?.status === 'active') && checkpointHistory.length > 0 && (
              <div className="live-checkpoint-timeline">
                {console.log('[ResearchCockpit] RENDER TIME - Live timeline:', {
                  totalCheckpoints: checkpointHistory.length,
                  respondedCheckpoints: checkpointHistory.filter(cp => cp.status === 'responded').length,
                  pendingCheckpoints: checkpointHistory.filter(cp => cp.status === 'pending').length,
                  allStatuses: checkpointHistory.map(cp => ({
                    id: cp.id?.slice(0, 8),
                    status: cp.status,
                    created: cp.created_at
                  }))
                })}
                {/* Responded checkpoints (collapsed by default, expandable for branching) */}
                {checkpointHistory
                  .filter(cp => cp.status === 'responded')
                  .map((checkpointData, idx) => {
                    console.log('[ResearchCockpit] Rendering responded checkpoint:', {
                      id: checkpointData.id?.slice(0, 8),
                      status: checkpointData.status,
                      index: idx
                    });
                    return (
                      <ExpandableCheckpoint
                        key={checkpointData.id || idx}
                        checkpoint={checkpointData}
                        index={idx}
                        sessionId={sessionId}
                        savedSessionData={null}
                        onBranch={handleCreateBranch}
                      />
                    );
                  })}

                {/* Current pending checkpoint (expanded, at bottom) */}
                {checkpoint && checkpoint.ui_spec && (
                  <div className="checkpoint-container current">
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
                      }

                      return null;
                    })()}
                  </div>
                )}
              </div>
            )}

            {/* Fallback: Old single checkpoint view (deprecated - keeping for safety) */}
            {!isSavedSession && checkpointHistory.length === 0 && checkpoint && checkpoint.ui_spec && (
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

            {/* Empty state - ONLY for brand new sessions with no checkpoints or timeline */}
            {!checkpoint &&
             checkpointHistory.length === 0 &&
             timeline.length === 0 &&
             (!savedSessionData || (savedSessionData.checkpoints_data && savedSessionData.checkpoints_data.length === 0)) && (
              <div className="cockpit-empty-state">
                {savedSessionData?.parent_session_id && savedSessionData?.status === 'active' ? (
                  <>
                    <Icon icon="mdi:source-fork" width="80" className="empty-icon spinning" />
                    <h2>Branch Starting...</h2>
                    <p>Restoring context from parent and initializing cascade...</p>
                    <div className="branch-info">
                      <Icon icon="mdi:information-outline" width="16" />
                      <span>Parent: {savedSessionData.parent_session_id.slice(0, 12)}...</span>
                    </div>
                  </>
                ) : (
                  <>
                    <Icon icon="mdi:compass" width="80" className="empty-icon" />
                    <h2>Session Active</h2>
                    <p>Cascade is executing. Results will appear here.</p>
                  </>
                )}
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
            roundEvents={roundEvents}
          />
        </div>
      )}
    </div>
  );
}

/**
 * ExpandableCheckpoint - Single checkpoint in the saved session timeline
 * Shows collapsed summary, expands to show full HTMX UI + user response
 * Can create branches by re-submitting with different responses
 */
function ExpandableCheckpoint({ checkpoint, index, sessionId, savedSessionData, onBranch }) {
  const [expanded, setExpanded] = useState(false);

  // Handle form submission from HTMX iframe - create branch!
  const handleBranchSubmit = (response) => {
    console.log('[ExpandableCheckpoint] Form submitted, creating branch!', response);

    if (onBranch) {
      onBranch(index, response);
    }
  };

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
          <h3>{checkpoint.summary || checkpoint.phase_output || 'Interaction'}</h3>
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
                <div className="branch-hint">
                  <Icon icon="mdi:source-fork" width="14" />
                  <span>Submit to create branch</span>
                </div>
              </div>
              <HTMLSection
                spec={htmlSection}
                checkpointId={checkpoint.id}
                sessionId={sessionId}
                isSavedCheckpoint={true}
                onBranchSubmit={handleBranchSubmit}
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

/**
 * CascadeContextHeader - Sticky header showing initial inputs and latest checkpoint feedback
 * Provides persistent context for the user about the current cascade session
 */
function CascadeContextHeader({ cascadeInputs, checkpointHistory, cascadeId, savedSessionData }) {
  // Combine checkpoints from live session and saved session
  const allCheckpoints = savedSessionData?.checkpoints_data?.length > 0
    ? savedSessionData.checkpoints_data
    : checkpointHistory;

  // Get the latest responded checkpoint feedback
  const respondedCheckpoints = allCheckpoints.filter(cp => cp.status === 'responded');
  const latestCheckpoint = respondedCheckpoints.length > 0
    ? respondedCheckpoints[respondedCheckpoints.length - 1]
    : null;

  // Get feedback message (phase_output or summary)
  const latestFeedback = latestCheckpoint?.summary || latestCheckpoint?.phase_output;

  // Don't render if no inputs and no feedback
  if (!cascadeInputs && !latestFeedback) {
    return null;
  }

  // Format inputs nicely
  const formatInputs = (inputs) => {
    if (!inputs) return null;
    if (typeof inputs === 'string') return inputs;

    // Handle object inputs
    return Object.entries(inputs).map(([key, value]) => {
      const displayValue = typeof value === 'object'
        ? JSON.stringify(value)
        : String(value);
      // Truncate long values
      const truncated = displayValue.length > 150
        ? displayValue.slice(0, 150) + '...'
        : displayValue;
      return { key, value: truncated };
    });
  };

  const formattedInputs = formatInputs(cascadeInputs);

  return (
    <div className="cascade-context-header">
      {/* Initial Inputs Section */}
      {cascadeInputs && (
        <div className="context-inputs-section">
          <div className="context-label">
            <Icon icon="mdi:input" width="14" />
            <span>Initial Input</span>
          </div>
          <div className="context-inputs">
            {Array.isArray(formattedInputs) ? (
              formattedInputs.map(({ key, value }) => (
                <div key={key} className="input-item">
                  <span className="input-key">{key}:</span>
                  <span className="input-value">{value}</span>
                </div>
              ))
            ) : (
              <span className="input-value single">{formattedInputs}</span>
            )}
          </div>
        </div>
      )}

      {/* Latest Feedback Section */}
      {latestFeedback && (
        <div className="context-feedback-section">
          <div className="feedback-label">
            <Icon icon="mdi:message-text-clock" width="12" />
            <span>Latest Checkpoint</span>
            {latestCheckpoint?.created_at && (
              <span className="feedback-time">
                {new Date(latestCheckpoint.created_at).toLocaleTimeString()}
              </span>
            )}
          </div>
          <div className="feedback-text">
            {latestFeedback.length > 200 ? latestFeedback.slice(0, 200) + '...' : latestFeedback}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * GhostMessage - Translucent message showing LLM's work in progress
 * Displays tool calls, thinking, phase transitions
 * Cleared when checkpoint arrives
 */
function GhostMessage({ ghost }) {
  const getIcon = () => {
    switch (ghost.type) {
      case 'tool_call':
        return 'mdi:tools';
      case 'tool_result':
        return 'mdi:check-circle';
      case 'thinking':
        return 'mdi:brain';
      default:
        return 'mdi:dots-horizontal';
    }
  };

  const getLabel = () => {
    switch (ghost.type) {
      case 'tool_call':
        return `${ghost.tool || 'Tool'}`;
      case 'tool_result':
        return `${ghost.tool || 'Tool'} result`;
      case 'thinking':
        return 'Thinking';
      default:
        return 'Working';
    }
  };

  // Parse and format content (handle JSON, markdown code blocks, etc.)
  const formatContent = (content) => {
    if (!content) return null;

    let jsonContent = content;

    // Try to extract JSON from markdown code blocks (with or without closing ```)
    // Match: ```json {...} or ```json {...}``` or ``` {...}
    const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)(?:```|$)/);
    if (codeBlockMatch) {
      jsonContent = codeBlockMatch[1].trim();
    }

    // Also try stripping just the opening ``` marker if present
    if (jsonContent.startsWith('```')) {
      jsonContent = jsonContent.replace(/^```(?:json)?\s*/, '').trim();
    }

    // Try to find JSON object in the content (starts with { )
    const jsonObjectMatch = jsonContent.match(/(\{[\s\S]*)/);
    if (jsonObjectMatch) {
      jsonContent = jsonObjectMatch[1];
    }

    // Try to parse as JSON (may be truncated, so try to fix common issues)
    try {
      // First try direct parse
      let parsed;
      try {
        parsed = JSON.parse(jsonContent);
      } catch {
        // If truncated, try to extract just the tool and arguments we can see
        const toolMatch = jsonContent.match(/"tool"\s*:\s*"([^"]+)"/);
        const argsMatch = jsonContent.match(/"arguments"\s*:\s*\{([^}]*)/);

        if (toolMatch) {
          // Build a partial parsed object from what we can extract
          parsed = { tool: toolMatch[1], arguments: {} };

          if (argsMatch) {
            // Try to extract key-value pairs from arguments
            const argsStr = argsMatch[1];
            const kvMatches = argsStr.matchAll(/"([^"]+)"\s*:\s*(?:"([^"]*)"|([\d.]+)|(\[[^\]]*\]?))/g);
            for (const kv of kvMatches) {
              const key = kv[1];
              const value = kv[2] || kv[3] || kv[4] || '';
              parsed.arguments[key] = value;
            }
          }
        } else {
          throw new Error('Not valid JSON');
        }
      }

      // Handle tool call format: {"tool": "name", "arguments": {...}}
      if (parsed.tool) {
        const args = parsed.arguments || {};
        // Extract key info from arguments
        const keyArgs = Object.entries(args).slice(0, 4).map(([k, v]) => {
          const strVal = typeof v === 'string' ? v : JSON.stringify(v);
          const truncated = strVal.length > 80 ? strVal.slice(0, 80) + '...' : strVal;
          return { key: k, value: truncated };
        });

        return (
          <div className="ghost-tool-call">
            <span className="ghost-tool-name">{parsed.tool}</span>
            {keyArgs.length > 0 && (
              <div className="ghost-tool-args">
                {keyArgs.map(({ key, value }) => (
                  <div key={key} className="ghost-arg">
                    <span className="ghost-arg-key">{key}:</span>
                    <span className="ghost-arg-value">{value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      }

      // Generic JSON - show formatted
      return (
        <pre className="ghost-json">
          {JSON.stringify(parsed, null, 2).slice(0, 200)}
        </pre>
      );
    } catch {
      // Not JSON - show as text (truncated)
      const truncated = content.length > 150 ? content.slice(0, 150) + '...' : content;
      return <span className="ghost-text">{truncated}</span>;
    }
  };

  return (
    <div className={`ghost-message ghost-${ghost.type}`}>
      <div className="ghost-header">
        <Icon icon={getIcon()} width="14" className="ghost-icon" />
        <span className="ghost-label">{getLabel()}</span>
        {ghost.timestamp && (
          <span className="ghost-time">
            {new Date(ghost.timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>
      {ghost.content && (
        <div className="ghost-body">
          {formatContent(ghost.content)}
        </div>
      )}
    </div>
  );
}

export default ResearchCockpit;
