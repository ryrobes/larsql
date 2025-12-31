import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Split from 'react-split';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import { Button, Badge, CheckpointRenderer, AppPreview, useToast } from '../../components';
import RichMarkdown from '../../components/RichMarkdown';
import CascadeSpecGraph from '../../components/CascadeSpecGraph';
import useExplorePolling from '../explore/hooks/useExplorePolling';
import { ROUTES } from '../../routes.helpers';
import './CalliopeView.css';

const STORAGE_KEY = 'calliope_last_session';
const STORAGE_TIME_KEY = 'calliope_last_session_time';

/**
 * CalliopeView - The Muse of App Building
 */
const CalliopeView = () => {
  const { sessionId: urlSessionId } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const chatEndRef = useRef(null);
  const hasAutoRestored = useRef(false);

  // Session state
  const [sessionId, setSessionId] = useState(urlSessionId || null);
  const [isStarting, setIsStarting] = useState(false);
  const [goalInput, setGoalInput] = useState('');

  // Cascade being built
  const [builtCascade, setBuiltCascade] = useState(null);
  const [builtCells, setBuiltCells] = useState([]);
  const [builtInputsSchema, setBuiltInputsSchema] = useState({});

  // Spawned cascade tracking (now uses AppPreview iframe)
  const [spawnedSessionId, setSpawnedSessionId] = useState(null);
  const [spawnedState, setSpawnedState] = useState(null);  // State from iframe postMessage
  const [spawnedCurrentCell, setSpawnedCurrentCell] = useState(null);  // Current cell from iframe

  // UI state
  const [splitSizes, setSplitSizes] = useState([35, 65]); // Chat narrower by default
  const [rightPanelSizes, setRightPanelSizes] = useState([40, 60]); // Graph / Live preview split
  const [showYaml, setShowYaml] = useState(false);

  // Use the explore polling hook for Calliope session
  const {
    logs,
    checkpoint: calliopeCheckpoint,
    ghostMessages,
    orchestrationState,
    sessionStatus,
    totalCost,
    isPolling,
    error
  } = useExplorePolling(sessionId);

  // Cell status derived from iframe postMessage events (no more log polling)
  const cellStatus = useMemo(() => {
    if (!builtCells || builtCells.length === 0 || !spawnedCurrentCell) {
      return {};
    }

    const status = {};
    const cellNames = builtCells.map(c => c.name);
    const currentCellIndex = cellNames.indexOf(spawnedCurrentCell);

    for (let i = 0; i < cellNames.length; i++) {
      const cellName = cellNames[i];
      if (i < currentCellIndex) {
        status[cellName] = 'completed';
      } else if (cellName === spawnedCurrentCell) {
        status[cellName] = 'current';
      } else {
        status[cellName] = 'pending';
      }
    }

    return status;
  }, [builtCells, spawnedCurrentCell]);

  // Auto-restore last session on mount
  useEffect(() => {
    if (urlSessionId || hasAutoRestored.current) return;
    hasAutoRestored.current = true;

    const lastSession = localStorage.getItem(STORAGE_KEY);
    const lastTime = localStorage.getItem(STORAGE_TIME_KEY);

    if (!lastSession || !lastTime) return;

    const elapsed = Date.now() - parseInt(lastTime, 10);
    const ONE_HOUR = 60 * 60 * 1000;

    if (elapsed >= ONE_HOUR) {
      console.log('[CalliopeView] Session expired');
      return;
    }

    // Validate session still exists
    fetch('http://localhost:5050/api/sessions?limit=100')
      .then(r => r.json())
      .then(data => {
        const session = data.sessions?.find(s => s.session_id === lastSession);
        if (session && (session.status === 'running' || session.status === 'blocked')) {
          console.log('[CalliopeView] Auto-restoring session:', lastSession);
          setSessionId(lastSession);
          navigate(ROUTES.calliopeWithSession(lastSession));
        }
      })
      .catch(err => console.error('[CalliopeView] Failed to validate session:', err));
  }, [urlSessionId, navigate]);

  // Persist session to localStorage
  useEffect(() => {
    if (sessionId) {
      localStorage.setItem(STORAGE_KEY, sessionId);
      localStorage.setItem(STORAGE_TIME_KEY, Date.now().toString());
    }
  }, [sessionId]);

  // Scroll to bottom on new messages - only if user is near bottom
  const chatContainerRef = useRef(null);
  const isUserScrolledUp = useRef(false);

  // Track if user has scrolled up
  const handleChatScroll = useCallback(() => {
    const container = chatContainerRef.current;
    if (!container) return;

    // Consider "at bottom" if within 100px of bottom
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    isUserScrolledUp.current = !atBottom;
  }, []);

  // Auto-scroll only when user hasn't scrolled up
  useEffect(() => {
    if (!isUserScrolledUp.current) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, calliopeCheckpoint]);

  // Extract cascade_write results from logs
  useEffect(() => {
    if (!logs || logs.length === 0) return;

    console.log('[CalliopeView] Processing', logs.length, 'logs for cascade_write');

    // Look for cascade_write results - check ALL logs (most recent first)
    // Prompt-based tools can appear in various log types, so we check content broadly
    for (const log of [...logs].reverse()) {
      // Tool results can be stored with various node_types/roles depending on how the tool was invoked
      // Check broadly: tool_result, deterministic, tool role, OR any content containing cascade_write
      const hasCascadeWriteContent = log.content_json && (
        log.content_json.includes('cascade_write') ||
        log.content_json.includes("'cascade_id'") ||
        log.content_json.includes('"cascade_id"')
      );
      const isToolResult = log.node_type === 'tool_result' || log.node_type === 'deterministic' ||
                          log.role === 'tool' || hasCascadeWriteContent;

      // DEBUG: Log all potential tool results
      if (log.node_type || log.role === 'tool') {
        console.log('[CalliopeView] Candidate log:', {
          role: log.role,
          node_type: log.node_type,
          isToolResult,
          hasContent: !!log.content_json,
          contentLen: log.content_json?.length,
        });
      }

      if (isToolResult) {
        // Check tool name from metadata
        let toolName = null;
        if (log.metadata_json) {
          try {
            const metadata = typeof log.metadata_json === 'string'
              ? JSON.parse(log.metadata_json)
              : log.metadata_json;
            toolName = metadata.tool_name || metadata.name || metadata.tool;
          } catch (e) {}
        }

        console.log('[CalliopeView] Tool result log:', {
          toolName,
          role: log.role,
          node_type: log.node_type,
          hasContent: !!log.content_json,
          contentPreview: log.content_json?.substring(0, 200),
          metadata: log.metadata_json
        });

        if (log.content_json) {
          try {
            // Try to parse the content as JSON (may be double-encoded or in Python repr format)
            let result = log.content_json;

            // First parse: content_json may be stringified
            if (typeof result === 'string') {
              try {
                result = JSON.parse(result);
              } catch (e) {
                // Not JSON, keep as string
              }
            }

            // Check for "Tool Result (tool_name):\n{...}" format from prompt-based tools
            if (typeof result === 'string' && result.startsWith('Tool Result (')) {
              // Extract the JSON/Python repr part after the prefix
              const match = result.match(/^Tool Result \([^)]+\):\n(.+)$/s);
              if (match) {
                let pyRepr = match[1];
                console.log('[CalliopeView] Extracted tool result body:', pyRepr.substring(0, 100));

                // Python repr is hard to parse due to nested quotes. Extract key fields directly.
                try {
                  // Extract cascade_id
                  const cascadeIdMatch = pyRepr.match(/'cascade_id':\s*'([^']+)'/);
                  // Extract success
                  const successMatch = pyRepr.match(/'success':\s*(True|False)/);
                  // Extract path
                  const pathMatch = pyRepr.match(/'path':\s*'([^']+)'/);
                  // Extract cell_count
                  const cellCountMatch = pyRepr.match(/'cell_count':\s*(\d+)/);

                  // Extract cells array - look for the cells list
                  const cellsMatch = pyRepr.match(/'cells':\s*\[(.*?)\],\s*'graph'/s);
                  let cells = [];
                  if (cellsMatch && cellsMatch[1].trim()) {
                    // Parse individual cell objects from the cells array
                    const cellsStr = cellsMatch[1];
                    // Match each cell dict: {'name': '...', 'type': '...', ...}
                    const cellMatches = cellsStr.matchAll(/\{'name':\s*'([^']+)',\s*'type':\s*'([^']+)'[^}]*'handoffs':\s*\[([^\]]*)\][^}]*\}/g);
                    for (const cm of cellMatches) {
                      const handoffsStr = cm[3];
                      const handoffs = handoffsStr.match(/'([^']+)'/g)?.map(h => h.replace(/'/g, '')) || [];
                      cells.push({
                        name: cm[1],
                        type: cm[2],
                        handoffs: handoffs,
                      });
                    }
                  }

                  // Extract graph nodes
                  const nodesMatch = pyRepr.match(/'nodes':\s*\[(.*?)\],\s*'edges'/s);
                  let nodes = [];
                  if (nodesMatch && nodesMatch[1].trim()) {
                    const nodesStr = nodesMatch[1];
                    // Match each node: {'id': '...', 'label': '...', 'type': '...', ...}
                    const nodeMatches = nodesStr.matchAll(/\{'id':\s*'([^']+)',\s*'label':\s*'([^']+)',\s*'type':\s*'([^']+)'/g);
                    for (const nm of nodeMatches) {
                      nodes.push({
                        id: nm[1],
                        label: nm[2],
                        type: nm[3],
                      });
                    }
                  }

                  // Extract graph edges
                  const edgesMatch = pyRepr.match(/'edges':\s*\[(.*?)\]/s);
                  let edges = [];
                  if (edgesMatch && edgesMatch[1].trim()) {
                    const edgesStr = edgesMatch[1];
                    const edgeMatches = edgesStr.matchAll(/\{'source':\s*'([^']+)',\s*'target':\s*'([^']+)'\}/g);
                    for (const em of edgeMatches) {
                      edges.push({ source: em[1], target: em[2] });
                    }
                  }

                  // Extract yaml_preview (for display)
                  const yamlMatch = pyRepr.match(/'yaml_preview':\s*["']([^]*?)["'],\s*'cell_count'/);
                  let yamlPreview = '';
                  if (yamlMatch) {
                    yamlPreview = yamlMatch[1].replace(/\\n/g, '\n').replace(/\\'/g, "'");
                  }

                  // Build result object
                  if (cascadeIdMatch) {
                    result = {
                      cascade_id: cascadeIdMatch[1],
                      success: successMatch ? successMatch[1] === 'True' : false,
                      path: pathMatch ? pathMatch[1] : null,
                      cell_count: cellCountMatch ? parseInt(cellCountMatch[1]) : cells.length,
                      cells: cells,
                      graph: { nodes, edges },
                      yaml_preview: yamlPreview,
                    };
                    console.log('[CalliopeView] Parsed Python repr via regex:', {
                      cascade_id: result.cascade_id,
                      cells: cells.length,
                      nodes: nodes.length,
                    });
                  }
                } catch (e) {
                  console.log('[CalliopeView] Failed to extract from Python repr:', e.message);
                }
              }
            }

            // Second parse: result might be str(dict) from Python - try to parse it
            if (typeof result === 'string' && (result.startsWith('{') || result.startsWith('['))) {
              // Try converting Python repr format
              let converted = result
                .replace(/'/g, '"')
                .replace(/\bTrue\b/g, 'true')
                .replace(/\bFalse\b/g, 'false')
                .replace(/\bNone\b/g, 'null');
              try {
                result = JSON.parse(converted);
              } catch (e) {
                // Still can't parse
              }
            }

            // Check if this is a cascade_write result (by structure or tool name)
            const isCascadeWrite = (
              (result && typeof result === 'object' && result.cascade_id && result.success !== undefined) ||
              toolName === 'cascade_write'
            );

            if (isCascadeWrite && result && typeof result === 'object') {
              console.log('[CalliopeView] ✓ Found cascade_write result!', {
                cascade_id: result.cascade_id,
                success: result.success,
                path: result.path,
                cell_count: result.cell_count,
                has_graph: !!result.graph,
                has_cells: !!result.cells,
                graph_nodes: result.graph?.nodes?.length,
                cells_len: result.cells?.length,
              });
              setBuiltCascade(result);

              // Build cells from graph data (preferred)
              if (result.graph?.nodes && result.graph.nodes.length > 0) {
                const cells = result.graph.nodes.map(node => ({
                  name: node.label || node.id,
                  tool: node.tool,
                  instructions: node.type === 'llm' ? 'LLM cell' : undefined,
                  hitl: node.type === 'hitl' ? '<hitl>' : undefined,
                  handoffs: (result.graph.edges || [])
                    .filter(e => e.source === node.id)
                    .map(e => e.target),
                }));
                setBuiltCells(cells);
                console.log('[CalliopeView] Set builtCells from graph:', cells);
              }
              // Fallback to cells summary
              else if (result.cells && result.cells.length > 0) {
                const cells = result.cells.map(cell => ({
                  name: cell.name,
                  tool: cell.tool,
                  hitl: cell.type === 'hitl' ? '<hitl>' : undefined,
                  instructions: cell.type === 'llm' ? 'LLM cell' : undefined,
                  handoffs: cell.handoffs || [],
                }));
                setBuiltCells(cells);
                console.log('[CalliopeView] Set builtCells from cells:', cells);
              }
              // Fallback: create minimal cell representation if we have cell_count
              else if (result.cell_count && result.cell_count > 0) {
                console.log('[CalliopeView] No graph/cells data, but cell_count:', result.cell_count);
                // We can still show the cascade exists, just without graph details
              }

              break; // Found the latest cascade_write result
            }

            // Also check for spawn_cascade results
            // Can be object format or plain text: "Spawned cascade '...' with Session ID: xxx"
            if (result && typeof result === 'object' && result.session_id && result.status === 'started') {
              console.log('[CalliopeView] Found spawn_cascade result (object):', result.session_id);
              setSpawnedSessionId(result.session_id);
            } else if (toolName === 'spawn_cascade' && typeof result === 'string') {
              // Parse from plain text: "Spawned cascade '...' with Session ID: xxx"
              const sessionMatch = result.match(/Session ID: (\S+)/);
              if (sessionMatch) {
                console.log('[CalliopeView] Found spawn_cascade result (text):', sessionMatch[1]);
                setSpawnedSessionId(sessionMatch[1]);
              }
            } else if (typeof log.content_json === 'string' && log.content_json.includes('spawn_cascade')) {
              // Also try original content_json for spawn_cascade
              const sessionMatch = log.content_json.match(/Session ID: (\S+)/);
              if (sessionMatch) {
                console.log('[CalliopeView] Found spawn_cascade session ID from raw:', sessionMatch[1]);
                setSpawnedSessionId(sessionMatch[1]);
              }
            }
          } catch (e) {
            console.log('[CalliopeView] Failed to parse tool result:', e);
          }
        }
      }
    }
  }, [logs]);

  // Track which sessions we've sent feedback for
  const feedbackSentRef = useRef(new Set());

  // Handle app preview session complete (from iframe postMessage)
  const handleAppSessionComplete = useCallback(async (data) => {
    console.log('[CalliopeView] App session completed:', data);

    // Auto-feedback to Calliope when spawned cascade completes
    if (calliopeCheckpoint && !feedbackSentRef.current.has(data.sessionId)) {
      feedbackSentRef.current.add(data.sessionId);

      const feedback = {
        spawned_session: data.sessionId,
        spawned_status: data.status,
        spawned_state: data.state,
      };

      console.log('[CalliopeView] Auto-sending feedback to Calliope:', feedback);

      try {
        await fetch(`http://localhost:5050/api/checkpoints/${calliopeCheckpoint.id}/respond`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            response: {
              feedback: `Spawned cascade ${data.status}`,
              ...feedback,
            }
          }),
        });
        showToast('Feedback sent to Calliope', { type: 'info' });
      } catch (e) {
        console.error('[CalliopeView] Failed to send feedback:', e);
      }
    }
  }, [calliopeCheckpoint, showToast]);

  // Handle cell change from iframe
  const handleAppCellChange = useCallback((cellName, state) => {
    console.log('[CalliopeView] App cell changed:', cellName);
    setSpawnedCurrentCell(cellName);
    if (state) {
      setSpawnedState(state);
    }
  }, []);

  // Handle app error from iframe
  const handleAppError = useCallback((error) => {
    console.error('[CalliopeView] App error:', error);
    showToast(`App error: ${error.message}`, { type: 'error' });
  }, [showToast]);

  // Known tool names to filter out
  const KNOWN_TOOLS = ['cascade_write', 'cascade_read', 'spawn_cascade', 'request_decision', 'set_state', 'route_to'];

  // Extract displayable messages from logs - include assistant messages and tool calls
  const messages = useMemo(() => {
    const msgs = [];
    let pendingToolCalls = []; // Collect tool calls to group them

    for (const log of logs) {
      // Tool call - collect for grouping
      if (log.node_type === 'tool_result' || log.node_type === 'deterministic' || log.node_type === 'tool_call') {
        let toolName = 'tool';
        if (log.metadata_json) {
          try {
            const metadata = typeof log.metadata_json === 'string'
              ? JSON.parse(log.metadata_json)
              : log.metadata_json;
            toolName = metadata.tool_name || metadata.name || metadata.tool || 'tool';
          } catch (e) {}
        }

        pendingToolCalls.push({
          id: log.message_id || `tool_${msgs.length}_${pendingToolCalls.length}`,
          tool: toolName,
          timestamp: log.timestamp,
        });
        continue;
      }

      // LLM text responses (assistant role)
      if (log.role === 'assistant' && log.content_json) {
        // First, flush any pending tool calls as a group
        if (pendingToolCalls.length > 0) {
          msgs.push({
            id: `toolgroup_${msgs.length}`,
            type: 'tool_group',
            tools: [...pendingToolCalls],
            timestamp: pendingToolCalls[0].timestamp,
          });
          pendingToolCalls = [];
        }

        try {
          let content = log.content_json;

          // Skip if raw content looks like a tool call (before any parsing)
          if (typeof content === 'string') {
            // Check for common tool call patterns in raw string
            if (content.includes('"tool"') || content.includes('"function"') ||
                content.includes('"arguments"') || content.includes('"tool_calls"') ||
                content.includes("'tool'") || content.includes("'arguments'") ||
                content.includes('"type": "function"') || content.includes("'type': 'function'")) {
              continue;
            }
            // Check for known tool names
            if (KNOWN_TOOLS.some(t => content.includes(`"${t}"`) || content.includes(`'${t}'`))) {
              continue;
            }
            // Skip JSON-like content
            const trimmed = content.trim();
            if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
              continue;
            }
          }

          // Try to parse if it's JSON-encoded
          try {
            const parsed = JSON.parse(content);
            // Skip if it's a tool call object
            if (parsed && typeof parsed === 'object') {
              // Tool call format: {"tool": "name", "arguments": {...}}
              if (parsed.tool || parsed.function || parsed.name || parsed.tool_calls ||
                  parsed.arguments || parsed.type === 'function') {
                continue;
              }
              // Check if it's an array of tool calls
              if (Array.isArray(parsed) && parsed.some(item => item.tool || item.function || item.name)) {
                continue;
              }
              // Extract text content if present
              if (parsed.content && typeof parsed.content === 'string') {
                content = parsed.content;
              } else if (parsed.text && typeof parsed.text === 'string') {
                content = parsed.text;
              } else {
                // It's some other object, skip it
                continue;
              }
            } else if (typeof parsed === 'string') {
              content = parsed;
            }
          } catch (e) {
            // Not JSON, use as-is
          }

          // Skip if it still looks like JSON, tool call, or structured data
          if (typeof content === 'string') {
            const trimmed = content.trim();
            if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
              continue;
            }
            // Also skip if it contains tool call markers
            if (content.includes('"tool"') || content.includes('"arguments"') ||
                content.includes("'tool'") || content.includes("'arguments'")) {
              continue;
            }
            // Skip if it has the structure of a tool definition/call
            if (content.includes('"type":') && content.includes('"name":')) {
              continue;
            }
          }

          // Skip very short messages
          if (typeof content !== 'string' || content.length < 10) {
            continue;
          }

          msgs.push({
            id: log.message_id || `msg_${msgs.length}`,
            type: 'assistant',
            content: content,
            timestamp: log.timestamp,
          });
        } catch (e) {
          console.log('[CalliopeView] Failed to parse assistant message:', e);
        }
      }
    }

    // Flush remaining tool calls
    if (pendingToolCalls.length > 0) {
      msgs.push({
        id: `toolgroup_${msgs.length}`,
        type: 'tool_group',
        tools: [...pendingToolCalls],
        timestamp: pendingToolCalls[0].timestamp,
      });
    }

    // Post-process: merge consecutive tool_groups together
    const mergedMsgs = [];
    for (const msg of msgs) {
      if (msg.type === 'tool_group') {
        // Check if last message is also a tool_group - merge them
        const lastMsg = mergedMsgs[mergedMsgs.length - 1];
        if (lastMsg && lastMsg.type === 'tool_group') {
          lastMsg.tools = [...lastMsg.tools, ...msg.tools];
        } else {
          mergedMsgs.push({ ...msg, tools: [...msg.tools] });
        }
      } else {
        mergedMsgs.push(msg);
      }
    }

    return mergedMsgs;
  }, [logs]);

  // State for expanded tool groups
  const [expandedToolGroups, setExpandedToolGroups] = useState(new Set());

  const toggleToolGroup = useCallback((groupId) => {
    setExpandedToolGroups(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }, []);

  // Start a new session with Calliope
  const handleStart = async () => {
    setIsStarting(true);

    try {
      const res = await fetch('http://localhost:5050/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_path: 'cascades/calliope.yaml',
          inputs: goalInput ? { goal: goalInput } : {},
        }),
      });

      const data = await res.json();

      if (data.error) {
        showToast(data.error, { type: 'error' });
        setIsStarting(false);
        return;
      }

      setSessionId(data.session_id);
      navigate(ROUTES.calliopeWithSession(data.session_id));
      showToast('Calliope is ready!', { type: 'success' });

    } catch (err) {
      showToast(`Failed to start: ${err.message}`, { type: 'error' });
    } finally {
      setIsStarting(false);
    }
  };

  // Handle Calliope checkpoint response
  const handleCalliopeResponse = async (response) => {
    if (!calliopeCheckpoint) return;

    try {
      const res = await fetch(`http://localhost:5050/api/checkpoints/${calliopeCheckpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      });

      const data = await res.json();

      if (data.error) {
        showToast(`Failed: ${data.error}`, { type: 'error' });
        return;
      }

      showToast('Response sent', { type: 'success' });
    } catch (err) {
      showToast(`Error: ${err.message}`, { type: 'error' });
    }
  };

  // Test the built cascade
  const handleTestCascade = async () => {
    if (!builtCascade?.path) {
      showToast('No cascade to test yet', { type: 'warning' });
      return;
    }

    showToast('Starting test cascade...', { type: 'info' });

    try {
      const res = await fetch('http://localhost:5050/api/run-cascade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_path: builtCascade.path,
          inputs: {},
        }),
      });

      const data = await res.json();

      if (data.error) {
        showToast(data.error, { type: 'error' });
        return;
      }

      setSpawnedSessionId(data.session_id);
      showToast('Test started!', { type: 'success' });
    } catch (err) {
      showToast(`Failed: ${err.message}`, { type: 'error' });
    }
  };

  // Start new session
  const handleNewSession = () => {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(STORAGE_TIME_KEY);
    setSessionId(null);
    setBuiltCascade(null);
    setBuiltCells([]);
    setSpawnedSessionId(null);
    setSpawnedState(null);
    setSpawnedCurrentCell(null);
    navigate(ROUTES.CALLIOPE);
  };

  // Welcome screen (no session yet)
  if (!sessionId) {
    return (
      <div className="calliope-welcome" style={{zoom:1.3}}>
        <div className="welcome-content">
          <div className="welcome-avatar">
            <img src="/Calliope.jpg" alt="Calliope" className="calliope-avatar-img" />
          </div>
          <h1 style={{color: '#fc0fc0', fontFamily:'Homemade Apple', fontSize:28}}>Meet Calliope</h1>
          <p className="welcome-tagline">
            Muse of Cascade Building
          </p>
          <p className="welcome-description">
            Describe what you want to build, and I'll help you create it.
            We'll design your app together through conversation.
          </p>

          <div className="welcome-input-area">
            <input
              type="text"
              value={goalInput}
              onChange={(e) => setGoalInput(e.target.value)}
              placeholder="What would you like to build? (optional)"
              className="goal-input"
              onKeyDown={(e) => e.key === 'Enter' && handleStart()}
            />
            <Button
              variant="primary"
              size="lg"
              icon={isStarting ? 'mdi:loading' : 'mdi:message-text'}
              iconClass={isStarting ? 'spinning' : ''}
              onClick={handleStart}
              disabled={isStarting}
            >
              {isStarting ? 'Starting...' : 'Start Building'}
            </Button>
          </div>

          <div className="welcome-hints">
            <h3>Example ideas:</h3>
            <ul>
              <li>"A feedback review app where I can approve or reject items"</li>
              <li>"A multi-step onboarding wizard for new users"</li>
              <li>"A data review dashboard with approve/escalate actions"</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // Main split view
  return (
    <div className="calliope-view">
      <Split
        className="calliope-split"
        sizes={splitSizes}
        onDragEnd={(sizes) => setSplitSizes(sizes)}
        minSize={[300, 300]}
        gutterSize={4}
        gutterAlign="center"
        direction="horizontal"
      >
        {/* Left Panel - Chat */}
        <div className="calliope-chat-panel">
          <div className="chat-header">
            <div className="chat-avatar">
              <img src="/Calliope.jpg" alt="Calliope" className="calliope-avatar-img" />
            </div>
            <div className="chat-title">
              <h2>Calliope</h2>
              <span className="chat-subtitle">
                {sessionStatus === 'running' ? 'Building your app...' :
                 sessionStatus === 'blocked' ? 'Waiting for input...' :
                 sessionStatus === 'completed' ? 'Session complete' :
                 'Ready'}
              </span>
            </div>
            <div className="chat-header-actions">
              {sessionStatus === 'running' && !calliopeCheckpoint && (
                <Badge variant="label" color="purple" size="sm" pulse>
                  <Icon icon="mdi:loading" className="spinning" width="12" />
                  Thinking
                </Badge>
              )}
              {totalCost > 0 && (
                <Badge variant="label" color="green" size="sm">
                  ${totalCost.toFixed(4)}
                </Badge>
              )}
              <Button
                variant="ghost"
                size="sm"
                icon="mdi:plus"
                onClick={handleNewSession}
                title="New Session"
              />
            </div>
          </div>

          <div
            className="chat-messages"
            ref={chatContainerRef}
            onScroll={handleChatScroll}
          >
            {/* Welcome message */}
            <div className="message assistant">
              <div className="message-avatar">
                <img src="/Calliope.jpg" alt="Calliope" className="calliope-avatar-img chat-avatar-tinted" />
              </div>
              <div className="message-content">
                <RichMarkdown>
                  {`Hello! I'm **Calliope**, your creative partner in app building.${
                    goalInput
                      ? ` Let's build: *"${goalInput}"*`
                      : " What would you like to create today?"
                  }`}
                </RichMarkdown>
              </div>
            </div>

            {/* Message history */}
            <AnimatePresence>
              {messages.map((msg) => {
                // Tool group - collapsible
                if (msg.type === 'tool_group') {
                  const isExpanded = expandedToolGroups.has(msg.id);
                  return (
                    <motion.div
                      key={msg.id}
                      className="message tool-group"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                    >
                      <div
                        className="tool-group-header"
                        onClick={() => toggleToolGroup(msg.id)}
                      >
                        <Icon
                          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                          width="16"
                        />
                        <Icon icon="mdi:tools" width="14" />
                        <span>{msg.tools.length} tool{msg.tools.length !== 1 ? 's' : ''} used</span>
                      </div>
                      {isExpanded && (
                        <div className="tool-group-list">
                          {msg.tools.map(tool => (
                            <div key={tool.id} className="tool-group-item">
                              <Icon icon="mdi:play-circle-outline" width="12" />
                              <span>{tool.tool}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </motion.div>
                  );
                }

                // Regular assistant message
                return (
                  <motion.div
                    key={msg.id}
                    className="message assistant"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    <div className="message-avatar">
                      <img src="/Calliope.jpg" alt="Calliope" className="calliope-avatar-img chat-avatar-tinted" />
                    </div>
                    <div className="message-content">
                      <RichMarkdown>{msg.content}</RichMarkdown>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>

            {/* Ghost messages (live activity) - only show when no cascade built yet */}
            {!builtCascade && (
              <AnimatePresence>
                {ghostMessages.slice(-3).map(ghost => (
                  <motion.div
                    key={ghost.id}
                    className="message ghost"
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 0.7, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                  >
                    <div className="ghost-indicator">
                      <Icon
                        icon={ghost.type === 'tool_call' ? 'mdi:play' : ghost.type === 'tool_result' ? 'mdi:check' : 'mdi:thought-bubble'}
                        width="12"
                      />
                      <span>{ghost.tool || 'thinking...'}</span>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}

            {/* Thinking indicator */}
            {sessionStatus === 'running' && !calliopeCheckpoint && messages.length === 0 && (
              <motion.div
                className="message assistant thinking"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                <div className="message-avatar">
                  <img src="/Calliope.jpg" alt="Calliope" className="calliope-avatar-img chat-avatar-tinted" />
                </div>
                <div className="thinking-dots">
                  <span></span><span></span><span></span>
                </div>
              </motion.div>
            )}

            {/* Current Calliope checkpoint (inline) */}
            {calliopeCheckpoint && (
              <motion.div
                className="chat-checkpoint"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className="checkpoint-label">
                  <Icon icon="mdi:hand-back-right" width="12" />
                  <span>Calliope needs your input</span>
                </div>
                <CheckpointRenderer
                  checkpoint={calliopeCheckpoint}
                  onSubmit={handleCalliopeResponse}
                  variant="inline"
                  showCellOutput={false}
                />
              </motion.div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Right Panel - Cascade Visualization */}
        <div className="calliope-cascade-panel">
          <div className="cascade-header">
            <div className="cascade-title">
              <Icon icon="mdi:sitemap" width="16" />
              <h3>{builtCascade?.cascade_id || 'Your App'}</h3>
              {builtCascade && (
                <Badge variant="label" color={builtCascade.success ? 'green' : 'yellow'} size="sm">
                  {builtCascade.cell_count || builtCells.length || 0} screens
                </Badge>
              )}
            </div>
            <div className="cascade-actions">
              {builtCascade && (builtCells.length > 0 || builtCascade.yaml_preview) && (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={showYaml ? 'mdi:graph' : 'mdi:code-braces'}
                  onClick={() => setShowYaml(!showYaml)}
                  title={showYaml ? 'View Graph' : 'View YAML'}
                >
                  {showYaml ? 'Graph' : 'YAML'}
                </Button>
              )}
              {spawnedSessionId && (
                <Badge variant="label" color="green" size="sm">
                  <Icon icon="mdi:play-circle" width="12" />
                  Live
                </Badge>
              )}
            </div>
          </div>

          {/* Draggable vertical split between graph and preview */}
          {spawnedSessionId && builtCascade ? (
            <Split
              className="cascade-vertical-split"
              sizes={rightPanelSizes}
              onDragEnd={(sizes) => setRightPanelSizes(sizes)}
              minSize={[100, 100]}
              gutterSize={6}
              gutterAlign="center"
              direction="vertical"
            >
              <div className="cascade-content">
                {builtCells.length === 0 && !builtCascade ? (
                  <div className="cascade-empty">
                    <Icon icon="mdi:sitemap" width="40" />
                    <p>Your app will appear here as we build it together</p>
                    {logs.length > 0 && (
                      <p className="cascade-empty-hint">
                        <Icon icon="mdi:information" width="14" />
                        Waiting for Calliope to create screens...
                      </p>
                    )}
                  </div>
                ) : builtCells.length === 0 && builtCascade ? (
                  showYaml && builtCascade.yaml_preview ? (
                    <pre className="cascade-yaml">{builtCascade.yaml_preview}</pre>
                  ) : (
                    <div className="cascade-empty">
                      <Icon icon="mdi:file-document-check" width="40" />
                      <p>Cascade created: <strong>{builtCascade.cascade_id}</strong></p>
                      {builtCascade.path && (
                        <p className="cascade-empty-hint">
                          <Icon icon="mdi:folder" width="14" />
                          {builtCascade.path}
                        </p>
                      )}
                      {builtCascade.cell_count === 0 && (
                        <p className="cascade-empty-hint">
                          <Icon icon="mdi:information" width="14" />
                          No screens added yet...
                        </p>
                      )}
                      {builtCascade.cell_count > 0 && (
                        <p className="cascade-empty-hint">
                          <Icon icon="mdi:check" width="14" />
                          {builtCascade.cell_count} screens ready
                        </p>
                      )}
                    </div>
                  )
                ) : showYaml ? (
                  <pre className="cascade-yaml">{builtCascade?.yaml_preview || 'No YAML preview available'}</pre>
                ) : (
                  <div className="cascade-graph-wrapper">
                    <CascadeSpecGraph
                      cells={builtCells}
                      inputsSchema={builtInputsSchema}
                      cascadeId={builtCascade?.cascade_id}
                      cellStatus={cellStatus}
                    />
                  </div>
                )}
              </div>

              {/* Live App Preview - Uses iframe with App API */}
              {/* Note: We don't pass spawn_cascade's sessionId - apps_api creates its own session */}
              <AppPreview
                cascadeId={builtCascade.cascade_id}
                onSessionComplete={handleAppSessionComplete}
                onCellChange={handleAppCellChange}
                onError={handleAppError}
                onStateChange={setSpawnedState}
              />
            </Split>
          ) : (
            /* No spawned session - just show cascade content */
            <div className="cascade-content">
              {builtCells.length === 0 && !builtCascade ? (
                <div className="cascade-empty">
                  <Icon icon="mdi:sitemap" width="40" />
                  <p>Your app will appear here as we build it together</p>
                  {logs.length > 0 && (
                    <p className="cascade-empty-hint">
                      <Icon icon="mdi:information" width="14" />
                      Waiting for Calliope to create screens...
                    </p>
                  )}
                </div>
              ) : builtCells.length === 0 && builtCascade ? (
                showYaml && builtCascade.yaml_preview ? (
                  <pre className="cascade-yaml">{builtCascade.yaml_preview}</pre>
                ) : (
                  <div className="cascade-empty">
                    <Icon icon="mdi:file-document-check" width="40" />
                    <p>Cascade created: <strong>{builtCascade.cascade_id}</strong></p>
                    {builtCascade.path && (
                      <p className="cascade-empty-hint">
                        <Icon icon="mdi:folder" width="14" />
                        {builtCascade.path}
                      </p>
                    )}
                    {builtCascade.cell_count === 0 && (
                      <p className="cascade-empty-hint">
                        <Icon icon="mdi:information" width="14" />
                        No screens added yet...
                      </p>
                    )}
                    {builtCascade.cell_count > 0 && (
                      <p className="cascade-empty-hint">
                        <Icon icon="mdi:check" width="14" />
                        {builtCascade.cell_count} screens ready
                      </p>
                    )}
                  </div>
                )
              ) : showYaml ? (
                <pre className="cascade-yaml">{builtCascade?.yaml_preview || 'No YAML preview available'}</pre>
              ) : (
                <div className="cascade-graph-wrapper">
                  <CascadeSpecGraph
                    cells={builtCells}
                    inputsSchema={builtInputsSchema}
                    cascadeId={builtCascade?.cascade_id}
                    cellStatus={cellStatus}
                  />
                </div>
              )}
            </div>
          )}

          {/* Validation warnings */}
          {builtCascade?.validation && !builtCascade.validation.valid && (
            <div className="cascade-validation">
              <Icon icon="mdi:alert" width="16" />
              <span>
                {builtCascade.validation.errors?.length || 0} errors,{' '}
                {builtCascade.validation.warnings?.length || 0} warnings
              </span>
            </div>
          )}
        </div>
      </Split>
    </div>
  );
};

export default CalliopeView;
