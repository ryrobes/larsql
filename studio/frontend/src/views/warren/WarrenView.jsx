import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import { Button, Badge, CheckpointRenderer, useToast, VideoLoader } from '../../components';
import RichMarkdown from '../../components/RichMarkdown';
import useExplorePolling from '../explore/hooks/useExplorePolling';
import { ROUTES } from '../../routes.helpers';
import './WarrenView.css';
import { API_BASE_URL } from '../../config/api';

const STORAGE_KEY = 'warren_last_session';
const STORAGE_TIME_KEY = 'warren_last_session_time';

// Personas mapped by take_index (0-4)
const PERSONAS = [
  { name: 'Skeptic', icon: 'mdi:shield-alert', color: '#f87171' },
  { name: 'Visionary', icon: 'mdi:lightbulb', color: '#fbbf24' },
  { name: 'Pragmatist', icon: 'mdi:hammer-wrench', color: '#34d399' },
  { name: 'Advocate', icon: 'mdi:account-heart', color: '#a78bfa' },
  { name: 'Contrarian', icon: 'mdi:swap-horizontal', color: '#60a5fa' },
];

/**
 * WarrenView - Multi-Perspective Deliberation Chat
 *
 * Left: 5 columns (one per advisor), messages stack vertically within each
 * Right: Chat between User and Hazel (the aggregator/Owsla)
 */
const WarrenView = () => {
  const { sessionId: urlSessionId } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const chatEndRef = useRef(null);
  const hasAutoRestored = useRef(false);

  // Session state
  const [sessionId, setSessionId] = useState(urlSessionId || null);
  const [isStarting, setIsStarting] = useState(false);
  const [messageInput, setMessageInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');

  // Polling
  const {
    logs,
    checkpoint,
    sessionStatus,
    totalCost,
  } = useExplorePolling(sessionId);

  // Auto-restore
  useEffect(() => {
    if (urlSessionId || hasAutoRestored.current) return;
    hasAutoRestored.current = true;

    const lastSession = localStorage.getItem(STORAGE_KEY);
    const lastTime = localStorage.getItem(STORAGE_TIME_KEY);
    if (!lastSession || !lastTime) return;

    const elapsed = Date.now() - parseInt(lastTime, 10);
    if (elapsed >= 60 * 60 * 1000) return;

    fetch(`${API_BASE_URL}/api/sessions?limit=100`)
      .then(r => r.json())
      .then(data => {
        const session = data.sessions?.find(s => s.session_id === lastSession);
        if (session && (session.status === 'running' || session.status === 'blocked')) {
          setSessionId(lastSession);
          navigate(ROUTES.warrenWithSession(lastSession));
        }
      })
      .catch(() => {});
  }, [urlSessionId, navigate]);

  // Persist session
  useEffect(() => {
    if (sessionId) {
      localStorage.setItem(STORAGE_KEY, sessionId);
      localStorage.setItem(STORAGE_TIME_KEY, Date.now().toString());
    }
  }, [sessionId]);

  // Auto-scroll
  const chatContainerRef = useRef(null);
  const isUserScrolledUp = useRef(false);

  const handleChatScroll = useCallback(() => {
    const container = chatContainerRef.current;
    if (!container) return;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    isUserScrolledUp.current = !atBottom;
  }, []);

  useEffect(() => {
    if (!isUserScrolledUp.current) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, checkpoint]);

  /**
   * Parse logs into:
   * 1. columns: { 0: [...], 1: [...], 2: [...], 3: [...], 4: [...] } - messages grouped by take_index
   * 2. hazelMessages: [...] - User messages + aggregator/synthesis messages (NOT takes)
   */
  const { columns, hazelMessages } = useMemo(() => {
    // Group take messages by their index (0-4)
    const cols = { 0: [], 1: [], 2: [], 3: [], 4: [] };
    const hazel = [];

    for (const log of logs) {
      // Check if this is a take message
      // The take_index field is returned directly from the query (more reliable)
      // Also check metadata_json as fallback
      let metadata = null;
      let isTake = false;
      let takeIndex = null;

      // First try the direct field (from ClickHouse unified_logs schema)
      if (log.take_index !== null && log.take_index !== undefined) {
        isTake = true;
        takeIndex = log.take_index;
      }

      // Fallback: check metadata_json
      if (!isTake && log.metadata_json) {
        try {
          metadata = typeof log.metadata_json === 'string'
            ? JSON.parse(log.metadata_json)
            : log.metadata_json;

          if (metadata.take_index !== undefined && metadata.take_index !== null) {
            isTake = true;
            takeIndex = metadata.take_index;
          } else if (metadata.is_take) {
            isTake = true;
            takeIndex = metadata.take_index ?? 0;
          }
        } catch (e) {}
      }

      // Extract content
      let content = log.content_json;
      if (typeof content === 'string') {
        try {
          const parsed = JSON.parse(content);
          if (typeof parsed === 'string') {
            content = parsed;
          } else if (parsed && typeof parsed === 'object') {
            // Skip tool calls
            if (parsed.tool || parsed.function || parsed.tool_calls) continue;
            content = parsed.content || parsed.text || JSON.stringify(parsed);
          }
        } catch (e) {
          // Not JSON, use as-is
        }
      }

      // Skip empty or very short content
      if (!content || typeof content !== 'string' || content.length < 10) continue;

      // Skip system role messages entirely
      if (log.role === 'system') continue;

      // Skip framework/system messages and prompts
      const isSystemMessage = (
        content.startsWith('## New Task') ||
        content.startsWith('## Input Data:') ||
        content.startsWith('## Context') ||
        content.startsWith('## Topic for Deliberation') ||
        content.startsWith('## Your Task') ||
        content.startsWith('## Synthesis') ||
        content.startsWith('## Previous Exchanges') ||
        content.startsWith('## Perspectives Received') ||
        content.includes('You are an AI assistant') ||
        content.includes('You are an advisor in **The Warren**') ||
        content.includes('You are the **Owsla**') ||
        content.includes('council that deliberates') ||
        content.includes('council that synthesizes') ||
        content.includes('You have access to research tools') ||
        content.includes('Respond thoughtfully from your perspective') ||
        content.includes('Synthesize these perspectives') ||
        content.includes('The Warren has completed its deliberation') ||
        content.includes('Present this synthesis to the user') ||
        content.includes('Call `request_decision`') ||
        content.includes('wait for their response')
      );
      if (isSystemMessage) continue;

      // If it's a take message, add to the appropriate column
      if (isTake && takeIndex !== null && takeIndex >= 0 && takeIndex <= 4) {
        // Skip tool results (role: 'tool')
        if (log.role === 'tool') continue;

        // Skip tool calls from assistants
        const isTakeToolCall = (
          content.includes('"tool"') ||
          content.includes('"function"') ||
          content.includes('brave_web_search') ||
          content.includes('sql_data') ||
          content.includes('read_file') ||
          content.includes('"name":') && content.includes('"arguments":') ||
          content.startsWith('{"') && (content.includes('"tool"') || content.includes('"arguments"')) ||
          content.startsWith('Calling ') ||
          content.startsWith('Tool Result')
        );
        if (isTakeToolCall) continue;

        // Use direct model field from query, fallback to metadata
        const model = log.model || metadata?.model || metadata?.model_id || 'unknown';
        cols[takeIndex].push({
          id: log.message_id || `c${takeIndex}_${cols[takeIndex].length}`,
          content: content,
          model: model.split('/').pop(),
          timestamp: log.timestamp,
          role: log.role,
        });
        continue;
      }

      // Check for checkpoint responses (HITL or request_decision) - these are user messages
      // Patterns:
      //   - Tool Result (request_decision): {'message': '...'}
      //   - HITL checkpoint: {'message': '...', 'action': '...'}
      //   - set_state logs showing user message being stored
      const isCheckpointResponse = (
        (log.role === 'tool' && content.includes('request_decision')) ||
        (log.role === 'tool' && content.includes("'message':")) ||
        (log.phase_name === 'interact' && content.includes('message'))
      );

      if (isCheckpointResponse) {
        let userMessage = null;

        // Try various patterns to extract the message
        // Pattern 1: Python dict format 'message': 'value'
        const pyMatch = content.match(/'message':\s*'([^']+)'/);
        if (pyMatch) {
          userMessage = pyMatch[1];
        }

        // Pattern 2: JSON format "message": "value"
        if (!userMessage) {
          const jsonMatch = content.match(/"message":\s*"([^"]+)"/);
          if (jsonMatch) {
            userMessage = jsonMatch[1];
          }
        }

        // Pattern 3: Multiline message with escaped quotes
        if (!userMessage) {
          const multiMatch = content.match(/'message':\s*'([\s\S]*?)(?<!\\)',/);
          if (multiMatch) {
            userMessage = multiMatch[1].replace(/\\'/g, "'");
          }
        }

        if (userMessage && userMessage.length > 5) {
          hazel.push({
            id: log.message_id || `user_decision_${hazel.length}`,
            type: 'user',
            content: userMessage,
            timestamp: log.timestamp,
          });
        }
        continue;
      }

      // Not a take - check if it's a user message or Hazel's response
      if (log.role === 'user') {
        // Skip internal turn prompts
        if (content.includes('The user responded:') ||
            content.includes('Store this in state')) continue;

        hazel.push({
          id: log.message_id || `user_${hazel.length}`,
          type: 'user',
          content: content,
          timestamp: log.timestamp,
        });
      } else if (log.role === 'assistant') {
        // Skip tool calls, context selection metadata, and internal framework messages
        const isToolCall = (
          content.includes('"tool"') ||
          content.includes('"function"') ||
          content.includes('request_decision') ||
          content.includes('set_state') ||
          content.includes('route_to') ||
          content.includes('"name":') && content.includes('"arguments":') ||
          content.startsWith('{"') && content.includes('function') ||
          content.includes('```python') && content.includes('request_decision(')
        );
        if (isToolCall) continue;

        // Skip context selection metadata (JSON with "selected" and "reasoning")
        const isContextSelection = (
          content.includes('"selected"') && content.includes('"reasoning"') ||
          content.startsWith('{') && content.includes('"selected":')
        );
        if (isContextSelection) continue;

        // This should be Hazel's synthesis (aggregator output)
        // Only include substantial responses
        if (content.length > 100) {
          hazel.push({
            id: log.message_id || `hazel_${hazel.length}`,
            type: 'hazel',
            content: content,
            timestamp: log.timestamp,
          });
        }
      }
    }

    return { columns: cols, hazelMessages: hazel };
  }, [logs]);

  // Count total messages across all columns
  const totalBurrowMessages = Object.values(columns).reduce((sum, col) => sum + col.length, 0);

  // Start session
  const handleStart = async () => {
    if (!messageInput.trim()) {
      showToast('Please enter a message', { type: 'warning' });
      return;
    }

    setIsStarting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/run-cascade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_path: 'cascades/warren.yaml',
          inputs: {
            message: messageInput,
            system_prompt: systemPrompt || undefined,
          },
        }),
      });

      const data = await res.json();
      if (data.error) {
        showToast(data.error, { type: 'error' });
        setIsStarting(false);
        return;
      }

      setSessionId(data.session_id);
      setMessageInput('');
      navigate(ROUTES.warrenWithSession(data.session_id));
      showToast('The Warren gathers...', { type: 'success' });
    } catch (err) {
      showToast(`Failed: ${err.message}`, { type: 'error' });
    } finally {
      setIsStarting(false);
    }
  };

  // Checkpoint response
  const handleWarrenResponse = async (response) => {
    if (!checkpoint) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/checkpoints/${checkpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      });
      const data = await res.json();
      if (data.error) showToast(`Failed: ${data.error}`, { type: 'error' });
    } catch (err) {
      showToast(`Error: ${err.message}`, { type: 'error' });
    }
  };

  // New session
  const handleNewSession = () => {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(STORAGE_TIME_KEY);
    setSessionId(null);
    setMessageInput('');
    navigate(ROUTES.WARREN);
  };

  // Welcome screen
  if (!sessionId) {
    return (
      <div className="warren-welcome">
        <div className="welcome-content">
          <div className="welcome-avatar">
            <Icon icon="mdi:rabbit" width="32" />
          </div>
          <h1>The Warren</h1>
          <p className="welcome-tagline">Multi-Perspective Deliberation</p>
          <p className="welcome-description">
            A council of AI advisors deliberate together, then Hazel synthesizes their perspectives.
          </p>

          <div className="welcome-input-area">
            <textarea
              value={messageInput}
              onChange={(e) => setMessageInput(e.target.value)}
              placeholder="What should the Warren deliberate on?"
              className="message-input"
              rows={3}
              onKeyDown={(e) => e.key === 'Enter' && e.ctrlKey && handleStart()}
            />

            <details className="context-details">
              <summary>
                <Icon icon="mdi:cog" width="14" />
                <span>Context</span>
              </summary>
              <div className="context-content">
                <input
                  type="text"
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="e.g., We're discussing software architecture"
                  className="context-input"
                />
              </div>
            </details>

            <Button
              variant="primary"
              size="lg"
              icon={isStarting ? 'mdi:loading' : 'mdi:rabbit'}
              iconClass={isStarting ? 'spinning' : ''}
              onClick={handleStart}
              disabled={isStarting || !messageInput.trim()}
            >
              {isStarting ? 'Gathering...' : 'Begin Deliberation'}
            </Button>
          </div>

          <div className="welcome-personas">
            <h3>The Council</h3>
            <div className="persona-list">
              {PERSONAS.map((p, i) => (
                <div key={i} className="persona-chip" style={{ borderColor: p.color }}>
                  <Icon icon={p.icon} width="12" style={{ color: p.color }} />
                  <span>{p.name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Main view - using CSS Grid for layout stability
  return (
    <div className="warren-view">
      {/* LEFT: The Burrows - 5 columns, messages stack within each */}
      <div className="warren-burrows-panel">
          <div className="burrows-header">
            <div className="burrows-title">
              <Icon icon="mdi:account-group" width="16" />
              <h3>The Burrows</h3>
              {totalBurrowMessages > 0 && (
                <Badge variant="label" color="purple" size="sm">
                  {totalBurrowMessages}
                </Badge>
              )}
            </div>
            {sessionStatus === 'running' && (
              <Badge variant="label" color="yellow" size="sm" pulse>
                <Icon icon="mdi:loading" className="spinning" width="12" />
                Deliberating
              </Badge>
            )}
          </div>

          <div className="burrows-columns">
            {PERSONAS.map((persona, idx) => (
              <div
                key={idx}
                className={`burrow-column ${columns[idx].length === 0 ? 'empty' : ''}`}
                style={{ '--persona-color': persona.color }}
              >
                <div className="burrow-column-header">
                  <Icon icon={persona.icon} width="14" style={{ color: persona.color }} />
                  <span className="burrow-persona-name">{persona.name}</span>
                </div>

                <div className="burrow-column-messages">
                  {columns[idx].length === 0 ? (
                    <div className="burrow-empty-state">
                      {sessionStatus === 'running' ? (
                        <VideoLoader size="small" className="burrow-loader" />
                      ) : (
                        <Icon icon="mdi:thought-bubble-outline" width="14" />
                      )}
                    </div>
                  ) : (
                    columns[idx].map((msg, msgIdx) => (
                      <div key={msg.id} className="burrow-message">
                        {msgIdx === 0 && msg.model && (
                          <span className="burrow-model">{msg.model}</span>
                        )}
                        <div className="burrow-message-content">
                          <RichMarkdown>{msg.content}</RichMarkdown>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT: Hazel's Chat - User <-> Owsla synthesis only */}
        <div className="warren-chat-panel">
          <div className="chat-header">
            <div className="chat-avatar">
              <Icon icon="mdi:rabbit" width="18" />
            </div>
            <div className="chat-title">
              <h2>Hazel</h2>
              <span className="chat-subtitle">
                {sessionStatus === 'running' ? 'Synthesizing...' :
                 sessionStatus === 'blocked' ? 'Awaiting response' :
                 sessionStatus === 'completed' ? 'Complete' : 'The Owsla'}
              </span>
            </div>
            <div className="chat-header-actions">
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
            {hazelMessages.length === 0 && sessionStatus === 'running' && (
              <div className="hazel-thinking">
                <VideoLoader size="medium" className="hazel-loader" />
                <span className="hazel-thinking-text">The Warren deliberates...</span>
              </div>
            )}

            {hazelMessages.map((msg) => (
              <div key={msg.id} className={`message ${msg.type}`}>
                <div className="message-avatar">
                  <Icon icon={msg.type === 'user' ? 'mdi:account' : 'mdi:rabbit'} width="16" />
                </div>
                <div className="message-content">
                  <RichMarkdown>{msg.content}</RichMarkdown>
                </div>
              </div>
            ))}

            {/* Checkpoint */}
            {checkpoint && (
              <div className="chat-checkpoint">
                <CheckpointRenderer
                  checkpoint={checkpoint}
                  onSubmit={handleWarrenResponse}
                  variant="inline"
                  showCellOutput={false}
                />
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>
    </div>
  );
};

export default WarrenView;
