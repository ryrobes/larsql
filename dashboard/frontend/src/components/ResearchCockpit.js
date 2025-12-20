import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import CascadePicker from './CascadePicker';
import LiveOrchestrationSidebar from './LiveOrchestrationSidebar';
import HTMLSection from './sections/HTMLSection';
import RichMarkdown from './RichMarkdown';
import { useNarrationPlayer } from './NarrationPlayer';
import NarrationCaption from './NarrationCaption';
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

/**
 * Build complete HTML document for artifact (mirrors buildIframeDocument from HTMLSection.js)
 * Shared by ResearchCockpit and ExpandableCheckpoint for saving checkpoints as artifacts
 */
function buildArtifactHTML(bodyHTML) {
  const baseCSS = `
:root {
  --bg-darkest: #0a0a0a;
  --bg-dark: #121212;
  --bg-card: #1a1a1a;
  --border-default: #333;
  --border-subtle: #222;
  --text-primary: #e5e7eb;
  --text-secondary: #9ca3af;
  --text-muted: #6b7280;
  --accent-purple: #a78bfa;
  --accent-blue: #4A9EDD;
  --accent-green: #10b981;
  --accent-red: #ef4444;
}

body {
  margin: 0;
  padding: 16px;
  font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  background: #1a1a1a;
  -webkit-font-smoothing: antialiased;
}

* { box-sizing: border-box; }

h1, h2, h3, h4, h5, h6 {
  color: var(--accent-purple);
  font-weight: 600;
  margin: 0 0 0.75rem 0;
}

h1 { font-size: 1.875rem; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.25rem; }

p { margin: 0 0 0.75rem 0; }

input, select, textarea {
  background: var(--bg-darkest);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: inherit;
  font-size: 0.875rem;
}

button {
  background: var(--accent-purple);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.875rem;
}

code, pre {
  font-family: 'IBM Plex Mono', monospace;
  background: var(--bg-darkest);
  border-radius: 4px;
}

code { padding: 2px 6px; font-size: 0.875em; }
pre { padding: 1rem; overflow-x: auto; border: 1px solid var(--border-default); }
`;

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>${baseCSS}</style>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
</head>
<body>
${bodyHTML}
</body>
</html>`;
}

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
    //console.log('[ResearchCockpit] initialSessionId changed:', initialSessionId);

    if (initialSessionId) {
      //console.log('[ResearchCockpit] Loading session:', initialSessionId);
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
      //console.log('[ResearchCockpit] No initial session, showing picker');
      setShowPicker(true);
    }
  }, [initialSessionId]);

  // Live data
  const [checkpoint, setCheckpoint] = useState(null);
  const [currentCheckpointSaving, setCurrentCheckpointSaving] = useState(false);
  const [currentCheckpointSaved, setCurrentCheckpointSaved] = useState(false);
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
  const [narrationAmplitude, setNarrationAmplitude] = useState(0); // Raw amplitude from narration audio (0-1)
  const [smoothedAmplitude, setSmoothedAmplitude] = useState(0); // Smoothed/tweened amplitude for animation
  const [narrationText, setNarrationText] = useState(''); // Current narration text for captions
  const [narrationDuration, setNarrationDuration] = useState(0); // Duration for word timing
  const [isNarrating, setIsNarrating] = useState(false); // Is audio currently playing

  // SSE for real-time updates
  const eventSourceRef = useRef(null);

  // Refs to track state without causing useCallback recreation (prevents SSE reconnection loops)
  const checkpointRef = useRef(null);
  useEffect(() => {
    checkpointRef.current = checkpoint;
  }, [checkpoint]);

  const savedSessionDataRef = useRef(null);
  useEffect(() => {
    savedSessionDataRef.current = savedSessionData;
  }, [savedSessionData]);

  // Smooth amplitude changes for natural animation (lerp/tween)
  useEffect(() => {
    let animationFrameId;

    const smoothAmplitude = () => {
      setSmoothedAmplitude(current => {
        const delta = narrationAmplitude - current;

        // Adaptive smoothing: fast when far from target, smooth when close
        let smoothingFactor;
        const absDelta = Math.abs(delta);

        if (absDelta > 0.1) {
          // Large change: catch up quickly (0.4 = aggressive)
          smoothingFactor = 0.4;
        } else if (absDelta > 0.05) {
          // Medium change: moderate speed
          smoothingFactor = narrationAmplitude > current ? 0.3 : 0.2; // Rise faster than fall
        } else {
          // Small variations: smooth and responsive
          smoothingFactor = narrationAmplitude > current ? 0.25 : 0.15; // Rise faster than fall
        }

        const newValue = current + delta * smoothingFactor;

        // Stop animating when very close (within 0.005 for tighter tracking)
        if (absDelta < 0.005) {
          return narrationAmplitude;
        }

        return newValue;
      });

      animationFrameId = requestAnimationFrame(smoothAmplitude);
    };

    animationFrameId = requestAnimationFrame(smoothAmplitude);

    return () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }
    };
  }, [narrationAmplitude]);

  // Narration player for browser-based TTS playback
  const narrationPlayer = useNarrationPlayer({
    onAmplitudeChange: (amplitude) => {
      // if (amplitude > 0.01) {
      //   console.log('[ResearchCockpit] Amplitude update:', amplitude);
      // }
      setNarrationAmplitude(amplitude);
    },
    onPlaybackStart: () => {
      console.log('[ResearchCockpit] Narration playback started');
      setIsNarrating(true);
    },
    onPlaybackEnd: () => {
      console.log('[ResearchCockpit] Narration playback ended');
      setNarrationAmplitude(0);
      setIsNarrating(false);
      // Text will fade out after 2s (handled by NarrationCaption)
    }
  });

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
          //console.log('[ResearchCockpit] Found saved session:', saved);

          // Fetch full details
          const detailRes = await fetch(`http://localhost:5001/api/research-sessions/${saved.id}`);
          const detailData = await detailRes.json();

          if (!detailData.error) {
            //console.log('[ResearchCockpit] Loaded full saved session with', detailData.checkpoints_data?.length, 'checkpoints');

            // Check if this is a new branch (has parent but no checkpoints yet)
            const isNewBranch = detailData.parent_session_id &&
                               (!detailData.checkpoints_data || detailData.checkpoints_data.length === 0);

            if (isNewBranch) {
              //console.log('[ResearchCockpit] Detected new branch - cascade is starting');
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
  const extractGhostMessages = useCallback((entries, existingGhosts = []) => {
    if (!entries || entries.length === 0) return [];

    // Build a map of existing ghosts to preserve their createdAt/exiting state
    const existingMap = new Map(existingGhosts.map(g => [g.id, g]));

    const ghosts = [];

    // Helper to get createdAt from timestamp or existing ghost
    const getCreatedAt = (id, timestamp) => {
      const existing = existingMap.get(id);
      if (existing?.createdAt) return existing.createdAt;
      // Parse ISO timestamp if available
      if (timestamp) {
        const parsed = new Date(timestamp).getTime();
        if (!isNaN(parsed)) return parsed;
      }
      return Date.now();
    };

    // Helper to preserve exiting state from existing ghost
    const getExitingState = (id) => {
      const existing = existingMap.get(id);
      return {
        exiting: existing?.exiting || false,
        exitStartedAt: existing?.exitStartedAt
      };
    };

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
            const id = `${entry.timestamp}_${tc.id}`;
            ghosts.unshift({
              type: 'tool_call',
              tool: tc.function?.name || 'unknown',
              timestamp: entry.timestamp,
              id,
              createdAt: getCreatedAt(id, entry.timestamp),
              ...getExitingState(id)
            });
          });
        }

        // Text responses
        if (entry.content && !entry.tool_calls) {
          const id = `${entry.timestamp}_text`;
          ghosts.unshift({
            type: 'thinking',
            content: entry.content.substring(0, 200),
            timestamp: entry.timestamp,
            id,
            createdAt: getCreatedAt(id, entry.timestamp),
            ...getExitingState(id)
          });
        }
      }

      // Tool results
      if (entry.role === 'tool' && entry.tool_call_id) {
        const id = `${entry.timestamp}_result`;
        ghosts.unshift({
          type: 'tool_result',
          tool: entry.name || 'tool',
          content: entry.content?.substring(0, 100),
          timestamp: entry.timestamp,
          id,
          createdAt: getCreatedAt(id, entry.timestamp),
          ...getExitingState(id)
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

        // Extract ghost messages ONLY for COMPLETED saved sessions (historical replay)
        // Live/active sessions receive ghost messages via SSE events - polling would create duplicates
        // with different IDs, causing the "appearing/disappearing repeatedly" bug
        // Note: A session can be saved (auto-saved) but still active - check status!
        // Use ref to avoid dependency that causes SSE reconnection loops
        const currentSavedData = savedSessionDataRef.current;
        const isCompletedSavedSession = isSavedSession && currentSavedData?.status === 'completed';
        if (isCompletedSavedSession) {
          setGhostMessages(prev => extractGhostMessages(data.entries, prev));
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
  }, [sessionId, isSavedSession, extractGhostMessages]); // Note: savedSessionData accessed via ref to prevent SSE reconnection loops

  // Fetch pending checkpoint
  const fetchCheckpoint = useCallback(async () => {
    if (!sessionId) return;

    try {
      // Request ALL checkpoints (pending + responded) for timeline visualization
      const res = await fetch(`http://localhost:5001/api/checkpoints?session_id=${sessionId}&include_all=true`);
      const data = await res.json();

      //console.log('[ResearchCockpit] Checkpoint fetch result:'
      // , 
      // {
      //   sessionId,
      //   checkpointCount: data.checkpoints?.length,
      //   hasPending: data.checkpoints?.some(cp => cp.status === 'pending')
      // });

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
        //console.log('[ResearchCockpit] Updated checkpoint history:', {
        //   total: sortedCheckpoints.length,
        //   responded: respondedCount,
        //   pending: pendingCount,
        //   checkpointIds: sortedCheckpoints.map(c => c.id.slice(0, 8))
        // });

        // Set current pending checkpoint (if any)
        // Use checkpointRef to avoid dependency cycle that causes SSE reconnections
        const currentCheckpoint = checkpointRef.current;
        if (pending && (!currentCheckpoint || pending.id !== currentCheckpoint.id)) {
          //console.log('[ResearchCockpit] ✓ Setting checkpoint:', pending.id);
          setCheckpoint(pending);
          setCurrentCheckpointSaved(false); // Reset saved state for new checkpoint

          // Update status
          setOrchestrationState(prev => ({
            ...prev,
            status: 'waiting_human'
          }));
        } else if (pending) {
          //console.log('[ResearchCockpit] Checkpoint unchanged:', pending.id);
        } else {
          //console.log('[ResearchCockpit] No pending checkpoint found');
          setCheckpoint(null); // Clear if no pending
        }
      }
    } catch (err) {
      console.error('[ResearchCockpit] Failed to fetch checkpoint:', err);
    }
  }, [sessionId]); // Removed checkpoint dependency - use checkpointRef instead

  // Setup SSE for real-time events
  useEffect(() => {
    if (!sessionId) return;

    console.log('[ResearchCockpit] Setting up SSE connection for session:', sessionId);
    const eventSource = new EventSource('http://localhost:5001/api/events/stream');
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      //console.log('[ResearchCockpit] SSE connected');
    };

    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);

        // Debug: show all non-heartbeat events
        if (event.type !== 'heartbeat') {
          //console.log('[ResearchCockpit] SSE:', event.type, 'session match:', event.session_id === sessionId, '(ours:', sessionId, 'event:', event.session_id, ')');
        }

        // Only process events for our session
        if (event.session_id !== sessionId) return;

        //console.log('[ResearchCockpit] ✓ Processing:', event.type);

        switch (event.type) {
          case 'cascade_start':
            //console.log('[ResearchCockpit] Cascade started');
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'phase_start':
            //console.log('[ResearchCockpit] Phase started:', event.data);
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
            //console.log('[ResearchCockpit] Turn started:', event.data);
            // Clear round events at start of new turn
            setRoundEvents([]);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'llm_request':
            //console.log('[ResearchCockpit] LLM request:', event.data);
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
            //console.log('[ResearchCockpit] LLM response received');
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
            //console.log('[ResearchCockpit] Phase completed');
            fetchSessionData(); // Refresh for updated costs
            break;

          case 'tool_call':
            //console.log('[ResearchCockpit] Tool call:', event.data);
            setRoundEvents(prev => [...prev, {
              type: 'tool_call',
              tool: event.data.tool_name,
              timestamp: Date.now(),
              id: `tool_${Date.now()}_${event.data.tool_name}`
            }]);

            // Add to ghost messages with arguments
            if (event.data.tool_name && event.data.args) {
              setGhostMessages(prev => {
                const newGhost = {
                  type: 'tool_call',
                  tool: event.data.tool_name,
                  arguments: event.data.args,
                  timestamp: event.timestamp || new Date().toISOString(),
                  id: `ghost_tool_${Date.now()}_${event.data.tool_name}`,
                  createdAt: Date.now(),
                  exiting: false
                };
                //console.log('[Ghost] + tool_call:', newGhost.id, 'total:', prev.length + 1);
                return [...prev, newGhost];
              });
            }

            setOrchestrationState(prev => ({
              ...prev,
              status: 'tool_running',
              lastToolCall: event.data.tool_name
            }));
            break;

          case 'tool_result':
            //console.log('[ResearchCockpit] Tool result received');
            setRoundEvents(prev => [...prev, {
              type: 'tool_result',
              tool: event.data.tool_name,
              timestamp: Date.now(),
              id: `result_${Date.now()}`
            }]);

            // Add tool result to ghost messages
            if (event.data.tool_name && event.data.result_preview) {
              setGhostMessages(prev => {
                const newGhost = {
                  type: 'tool_result',
                  tool: event.data.tool_name,
                  result: event.data.result_preview,
                  timestamp: event.timestamp || new Date().toISOString(),
                  id: `ghost_result_${Date.now()}_${event.data.tool_name}`,
                  createdAt: Date.now(),
                  exiting: false
                };
                //console.log('[Ghost] + tool_result:', newGhost.id, 'total:', prev.length + 1);
                return [...prev, newGhost];
              });
            }

            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking',
              lastToolCall: null
            }));
            break;

          case 'tool_complete':
            // Tool completed - just update state (ghost message already added on tool_call)
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking',
              lastToolCall: null
            }));
            break;

          case 'turn_complete':
            // Turn completed - refresh data
            fetchSessionData();
            break;

          case 'session_status_changed':
          case 'session_started':
            // Session state changes - refresh
            fetchSessionData();
            break;

          case 'cost_update':
            //console.log('[ResearchCockpit] Cost update:', event.data);
            fetchSessionData(); // Refresh for new cost
            break;

          case 'checkpoint_created':
          case 'checkpoint_waiting':
            //console.log('[Ghost] CLEAR: checkpoint_created/waiting event');
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
            //console.log('[ResearchCockpit] Checkpoint responded');
            // Refresh checkpoint history to show the newly responded checkpoint as collapsed
            fetchCheckpoint();
            setOrchestrationState(prev => ({
              ...prev,
              status: 'thinking'
            }));
            break;

          case 'cascade_complete':
            //console.log('[ResearchCockpit] Cascade complete');
            setRoundEvents([]); // Clear round events on cascade complete
            setOrchestrationState(prev => ({
              ...prev,
              status: 'idle'
            }));
            fetchSessionData();
            break;

          case 'cascade_error':
            //console.log('[ResearchCockpit] Cascade error:', event.data);
            setOrchestrationState(prev => ({
              ...prev,
              status: 'idle'
            }));
            break;

          case 'narration_audio':
            // Browser-based narration playback (research mode)
            console.log('[ResearchCockpit] Narration audio event:', event.data);
            if (event.data.audio_path && narrationPlayer) {
              // Set caption data before playing
              setNarrationText(event.data.text || '');
              setNarrationDuration(event.data.duration_seconds || 0);
              narrationPlayer.play(event.data.audio_path);
            }
            break;

          default:
            //console.log('[ResearchCockpit] Unhandled event:', event.type, event.data);
            break;
        }
      } catch (err) {
        console.error('[ResearchCockpit] Failed to parse SSE event:', err);
      }
    };

    return () => {
      eventSource.close();
    };
    // Note: narrationPlayer is NOT in dependencies - we capture it via closure in the event handler
    // Adding it would cause SSE reconnections on every render since it's a new object each time
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

  // Ghost message auto-cleanup: slide off to the left after 30 seconds
  useEffect(() => {
    const GHOST_LIFETIME_MS = 20000; // 30 seconds before starting exit
    const EXIT_ANIMATION_MS = 600;   // Duration of slide-out animation

    const cleanupInterval = setInterval(() => {
      const now = Date.now();

      setGhostMessages(prev => {
        // Check if any ghosts need to start exiting
        const needsUpdate = prev.some(ghost =>
          !ghost.exiting && ghost.createdAt && (now - ghost.createdAt > GHOST_LIFETIME_MS)
        );

        if (!needsUpdate) return prev;

        // Mark old ghosts as exiting
        return prev.map(ghost => {
          if (!ghost.exiting && ghost.createdAt && (now - ghost.createdAt > GHOST_LIFETIME_MS)) {
            return { ...ghost, exiting: true, exitStartedAt: now };
          }
          return ghost;
        });
      });

      // Remove ghosts that have finished their exit animation
      setGhostMessages(prev => {
        const toRemove = prev.filter(ghost => ghost.exiting && ghost.exitStartedAt && (now - ghost.exitStartedAt) >= EXIT_ANIMATION_MS);
        if (toRemove.length > 0) {
          //console.log('[Ghost] REMOVE (exit animation done):', toRemove.map(g => g.id));
        }
        return prev.filter(ghost => {
          if (ghost.exiting && ghost.exitStartedAt) {
            return (now - ghost.exitStartedAt) < EXIT_ANIMATION_MS;
          }
          return true;
        });
      });
    }, 1000); // Check every second

    return () => clearInterval(cleanupInterval);
  }, []);

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

  // Save current checkpoint as artifact
  const handleSaveCurrentCheckpointAsArtifact = async () => {
    if (!checkpoint || currentCheckpointSaving || currentCheckpointSaved) return;

    setCurrentCheckpointSaving(true);

    try {
      // Parse ui_spec if needed
      let uiSpec = checkpoint.ui_spec;
      if (typeof uiSpec === 'string') {
        try {
          uiSpec = JSON.parse(uiSpec);
        } catch (e) {
          uiSpec = null;
        }
      }

      const htmlSection = uiSpec?.sections?.find(s => s.type === 'html');
      const bodyContent = htmlSection?.html || htmlSection?.content || checkpoint.phase_output || '<div>No content available</div>';

      // Wrap with full HTML document
      const htmlContent = buildArtifactHTML(bodyContent);

      // Compute title
      const phaseName = checkpoint.phase_name || 'decision';
      const summary = checkpoint.summary || checkpoint.phase_output || '';
      const summarySnippet = summary.slice(0, 50).replace(/[^a-zA-Z0-9\s]/g, '').trim();
      const title = summarySnippet ? `${phaseName}: ${summarySnippet}` : `${phaseName} - Decision`;

      const response = await fetch('http://localhost:5001/api/artifacts/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          cascade_id: checkpoint.cascade_id || cascadeId || 'unknown',
          phase_name: checkpoint.phase_name || 'unknown',
          title: title,
          artifact_type: 'decision',
          description: checkpoint.summary || checkpoint.phase_output?.slice(0, 200) || '',
          html_content: htmlContent,
          tags: ['decision', 'checkpoint', checkpoint.checkpoint_type || 'general']
        })
      });

      const data = await response.json();

      if (data.created) {
        setCurrentCheckpointSaved(true);
      } else {
        console.error('Failed to save artifact:', data.error);
      }
    } catch (err) {
      console.error('Error saving artifact:', err);
    } finally {
      setCurrentCheckpointSaving(false);
    }
  };

  // Handle branch creation from checkpoint (works for both saved and live sessions)
  const handleCreateBranch = async (checkpointIndex, newResponse) => {
    //console.log('[ResearchCockpit] Creating branch from checkpoint', checkpointIndex, 'with response:', newResponse);

    try {
      // If this is a live session (not saved yet), trigger a save first
      let researchSessionId = savedSessionData?.id;

      if (!researchSessionId) {
        //console.log('[ResearchCockpit] Live session - fetching/creating saved session first...');

        // Check if session was auto-saved already
        const checkRes = await fetch(`http://localhost:5001/api/research-sessions?limit=100`);
        const checkData = await checkRes.json();

        if (!checkData.error && checkData.sessions) {
          const existing = checkData.sessions.find(s => s.original_session_id === sessionId);
          if (existing) {
            researchSessionId = existing.id;
            //console.log('[ResearchCockpit] Found auto-saved session:', researchSessionId);
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

      //console.log('[ResearchCockpit] ✓ Branch created:', data.new_session_id);

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
            {/* Show session title if available (from auto-save), otherwise show cascade_id */}
            {savedSessionData?.title && savedSessionData.title !== `Research Session - ${sessionId?.slice(0, 12)}` ? (
              <span
                className="header-stat session-title"
                style={{
                  marginLeft: '12px',
                  padding: '4px 12px',
                  background: 'linear-gradient(135deg, rgba(167, 139, 250, 0.15), rgba(139, 92, 246, 0.1))',
                  borderRadius: '6px',
                  border: '1px solid rgba(167, 139, 250, 0.2)',
                  fontSize: '0.9rem',
                  maxWidth: '400px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}
                title={savedSessionData.title}
              >
                {savedSessionData.title}
              </span>
            ) : cascadeId && (
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
          {/* Main Content Column - Header + Scrollable Content */}
          <div className="cockpit-main-column">
            {/* Context Header - Fixed at top, not scrolling */}
            <CascadeContextHeader
              cascadeInputs={cascadeInputs}
              checkpointHistory={checkpointHistory}
              cascadeId={cascadeId}
              savedSessionData={savedSessionData}
            />

            {/* Scrollable Content Area */}
            <div className="cockpit-main">
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

            {/* Sticky "Session Active" header when live session has activity */}
            {!checkpoint &&
             checkpointHistory.length === 0 &&
             timeline.length === 0 &&
             ghostMessages.length > 0 && (
              <div className="cockpit-active-header">
                <Icon icon="mdi:compass" width="40" className="empty-icon" />
                <div>
                  <h3>Session Active</h3>
                  <p>Cascade is executing...</p>
                </div>
              </div>
            )}

            {/* Ghost Messages - Show live thinking/tool activity */}
            {ghostMessages.length > 0 && (
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

                {/* Responded checkpoints (collapsed by default, expandable for branching) */}
                {checkpointHistory
                  .filter(cp => cp.status === 'responded')
                  .map((checkpointData, idx) => {
                    // console.log('[ResearchCockpit] Rendering responded checkpoint:', {
                    //   id: checkpointData.id?.slice(0, 8),
                    //   status: checkpointData.status,
                    //   index: idx
                    // });
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
                  })
                  }

                {/* Current pending checkpoint (expanded, at bottom) */}
                {checkpoint && checkpoint.ui_spec && (
                  <div className="checkpoint-container current">
                    <button
                      className={`checkpoint-save-btn ${currentCheckpointSaved ? 'saved' : ''}`}
                      onClick={handleSaveCurrentCheckpointAsArtifact}
                      disabled={currentCheckpointSaving || currentCheckpointSaved}
                      title={currentCheckpointSaved ? 'Saved to Artifacts' : 'Save as Artifact'}
                    >
                      <Icon
                        icon={currentCheckpointSaved ? 'mdi:check' : currentCheckpointSaving ? 'mdi:loading' : 'mdi:content-save-outline'}
                        width="16"
                        className={currentCheckpointSaving ? 'spinning' : ''}
                      />
                    </button>
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

            {/* Empty state - ONLY for brand new sessions with no checkpoints, timeline, or ghost messages */}
            {!checkpoint &&
             checkpointHistory.length === 0 &&
             timeline.length === 0 &&
             ghostMessages.length === 0 &&
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
          </div>

          {/* Right Sidebar - Live Orchestration Visualization */}
          <LiveOrchestrationSidebar
            sessionId={sessionId}
            cascadeId={cascadeId}
            orchestrationState={orchestrationState}
            sessionData={sessionData}
            roundEvents={roundEvents}
            narrationAmplitude={smoothedAmplitude}
          />
        </div>
      )}

      {/* Live Narration Caption - Fixed at bottom with word-by-word highlighting */}
      <NarrationCaption
        text={narrationText}
        duration={narrationDuration}
        isPlaying={isNarrating}
        amplitude={smoothedAmplitude}
      />
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
  const [isSaving, setIsSaving] = useState(false);
  const [isSaved, setIsSaved] = useState(false);

  // Compute artifact name from checkpoint data
  const computeArtifactName = () => {
    const phaseName = checkpoint.phase_name || 'decision';
    const summary = checkpoint.summary || checkpoint.phase_output || '';
    // Take first 50 chars of summary, clean up
    const summarySnippet = summary.slice(0, 50).replace(/[^a-zA-Z0-9\s]/g, '').trim();
    if (summarySnippet) {
      return `${phaseName}: ${summarySnippet}`;
    }
    return `${phaseName} - Decision ${index + 1}`;
  };

  // Save checkpoint as artifact
  const handleSaveAsArtifact = async (e) => {
    e.stopPropagation(); // Prevent expand toggle

    if (isSaving || isSaved) return;

    setIsSaving(true);

    try {
      // Get the HTML content from the checkpoint
      let uiSpec = checkpoint.ui_spec;
      if (typeof uiSpec === 'string') {
        try {
          uiSpec = JSON.parse(uiSpec);
        } catch (e) {
          uiSpec = null;
        }
      }

      const htmlSection = uiSpec?.sections?.find(s => s.type === 'html');
      const bodyContent = htmlSection?.html || htmlSection?.content || checkpoint.phase_output || '<div>No content available</div>';

      // Wrap with full HTML document (same as artifact viewer expects)
      const htmlContent = buildArtifactHTML(bodyContent);

      const title = computeArtifactName();

      const response = await fetch('http://localhost:5001/api/artifacts/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          cascade_id: checkpoint.cascade_id || savedSessionData?.cascade_id || 'unknown',
          phase_name: checkpoint.phase_name || 'unknown',
          title: title,
          artifact_type: 'decision',
          description: checkpoint.summary || checkpoint.phase_output?.slice(0, 200) || '',
          html_content: htmlContent,
          tags: ['decision', 'checkpoint', checkpoint.checkpoint_type || 'general']
        })
      });

      const data = await response.json();

      if (data.created) {
        setIsSaved(true);
      } else {
        console.error('Failed to save artifact:', data.error);
      }
    } catch (err) {
      console.error('Error saving artifact:', err);
    } finally {
      setIsSaving(false);
    }
  };

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
        <button
          className={`save-artifact-btn ${isSaved ? 'saved' : ''}`}
          onClick={handleSaveAsArtifact}
          disabled={isSaving || isSaved}
          title={isSaved ? 'Saved to Artifacts' : 'Save as Artifact'}
        >
          <Icon
            icon={isSaved ? 'mdi:check' : isSaving ? 'mdi:loading' : 'mdi:content-save-outline'}
            width="16"
            className={isSaving ? 'spinning' : ''}
          />
        </button>
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
  const [isInputsCollapsed, setIsInputsCollapsed] = useState(false);

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
        ? JSON.stringify(value, null, 2)  // Pretty print objects
        : String(value);
      return { key, value: displayValue };
    });
  };

  const formattedInputs = formatInputs(cascadeInputs);

  return (
    <div className="cascade-context-header">
      {/* Initial Inputs Section */}
      {cascadeInputs && (
        <div className={`context-inputs-section ${isInputsCollapsed ? 'collapsed' : ''}`}>
          <div
            className="context-label clickable"
            onClick={() => setIsInputsCollapsed(!isInputsCollapsed)}
          >
            <Icon
              icon="mdi:chevron-down"
              width="16"
              className={`accordion-chevron ${isInputsCollapsed ? 'collapsed' : ''}`}
            />
            <Icon icon="mdi:input" width="14" />
            <span>Input</span>
          </div>
          <div className={`context-inputs ${isInputsCollapsed ? 'collapsed' : ''}`}>
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

  // Render truncated data grid for tool results
  const renderDataGrid = (result) => {
    try {
      // Safety: ensure result is a string
      const resultStr = typeof result === 'string' ? result : JSON.stringify(result);

      // Try to parse as JSON
      let parsed;
      try {
        parsed = JSON.parse(resultStr);
      } catch (e) {
        // Not JSON, show as truncated text
        const truncated = resultStr.slice(0, 200);
        return <div className="ghost-result-text">{truncated}</div>;
      }

      // Handle array of objects (SQL results, etc.)
      if (Array.isArray(parsed) && parsed.length > 0 && typeof parsed[0] === 'object') {
        const headers = Object.keys(parsed[0]);
        const rows = parsed.slice(0, 3); // Show first 3 rows

        return (
          <div className="ghost-data-grid">
            <table>
              <thead>
                <tr>
                  {headers.map(h => <th key={h}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={idx}>
                    {headers.map(h => {
                      // CRITICAL: Convert to string to avoid rendering objects
                      let cellValue = row[h];
                      if (typeof cellValue === 'object' && cellValue !== null) {
                        cellValue = JSON.stringify(cellValue);
                      } else if (cellValue === null || cellValue === undefined) {
                        cellValue = '';
                      } else {
                        cellValue = String(cellValue);
                      }
                      const truncated = cellValue.length > 50 ? cellValue.slice(0, 50) + '...' : cellValue;
                      return <td key={h}>{truncated}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {parsed.length > 3 && (
              <div className="ghost-grid-more">+{parsed.length - 3} more rows</div>
            )}
          </div>
        );
      }

      // Handle single object
      if (typeof parsed === 'object' && parsed !== null) {
        return (
          <pre className="ghost-json">
            {JSON.stringify(parsed, null, 2).slice(0, 300)}
          </pre>
        );
      }

      // Fallback: show as text
      const truncated = String(parsed).slice(0, 200);
      return <div className="ghost-result-text">{truncated}</div>;

    } catch (e) {
      // Catch-all: stringify the result
      const safeStr = typeof result === 'object' ? JSON.stringify(result) : String(result);
      const truncated = safeStr.slice(0, 200);
      return <div className="ghost-result-text">{truncated}</div>;
    }
  };

  return (
    <div className={`ghost-message ghost-${ghost.type}${ghost.exiting ? ' ghost-exiting' : ''}`}>
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
      {ghost.arguments && Object.keys(ghost.arguments).length > 0 && (
        <div className="ghost-tool-args">
          {Object.entries(ghost.arguments).slice(0, 3).map(([key, value]) => {
            // Convert value to string safely
            let displayValue;
            if (typeof value === 'string') {
              displayValue = value;
            } else if (typeof value === 'number' || typeof value === 'boolean') {
              displayValue = String(value);
            } else if (value === null || value === undefined) {
              displayValue = 'null';
            } else {
              // Object or array - stringify it
              try {
                displayValue = JSON.stringify(value);
              } catch (e) {
                displayValue = '[Object]';
              }
            }
            const truncated = displayValue.length > 100 ? displayValue.slice(0, 100) + '...' : displayValue;
            return (
              <div key={key} className="ghost-arg">
                <span className="ghost-arg-key">{key}:</span>
                <span className="ghost-arg-value">{truncated}</span>
              </div>
            );
          })}
        </div>
      )}
      {ghost.result && (
        <div className="ghost-result-body">
          {renderDataGrid(ghost.result)}
        </div>
      )}
    </div>
  );
}

export default ResearchCockpit;
