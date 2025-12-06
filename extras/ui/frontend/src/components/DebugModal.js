import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import MermaidPreview from './MermaidPreview';
import VideoSpinner from './VideoSpinner';
import './DebugModal.css';

function DebugModal({ sessionId, onClose, lastUpdate = null }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [entries, setEntries] = useState([]);
  const [groupedEntries, setGroupedEntries] = useState([]);
  const [viewMode, setViewMode] = useState('conversation'); // 'all', 'conversation', 'structural'
  const [showStructural, setShowStructural] = useState(false);

  const fetchSessionData = async () => {
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Deduplicate entries (remove turn_output duplicates)
      const deduplicated = deduplicateEntries(data.entries || []);
      setEntries(deduplicated);

      const filtered = filterEntriesByViewMode(deduplicated);
      groupEntriesByPhase(filtered);
      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const deduplicateEntries = (entries) => {
    const filtered = [];
    const seenAgentContent = new Map();

    for (const entry of entries) {
      // Track agent entries by timestamp + content hash
      if (entry.node_type === 'agent') {
        const contentKey = `${entry.timestamp}-${entry.content?.substring(0, 100)}`;
        seenAgentContent.set(contentKey, true);
        filtered.push(entry);
        continue;
      }

      // Skip turn_output if we've already seen this content from agent
      if (entry.node_type === 'turn_output') {
        const contentKey = `${entry.timestamp}-${entry.content?.substring(0, 100)}`;
        if (seenAgentContent.has(contentKey)) {
          continue; // Skip duplicate
        }
      }

      filtered.push(entry);
    }

    return filtered;
  };

  const isStructural = (entry) => {
    const structuralTypes = ['cascade', 'phase', 'turn', 'soundings'];
    const structuralRoles = ['structure', 'phase_start', 'soundings_start', 'turn_start'];

    return structuralTypes.includes(entry.node_type) ||
           structuralRoles.includes(entry.role);
  };

  const isConversational = (entry) => {
    // Filter out debug-only messages (not sent to LLM)
    const meta = entry.metadata;
    if (meta) {
      const metaObj = typeof meta === 'string' ? JSON.parse(meta) : meta;
      if (metaObj?.not_sent_to_llm === true || metaObj?.debug_only === true) {
        return false; // Filter out debug-only messages
      }
    }

    // Filter out "Initialization" phase entries (duplicates logged before phase assignment)
    if (entry.phase_name === 'Initialization' || entry.phase_name === null) {
      // Allow structural messages, but not conversation messages from Initialization
      const conversationalTypes = ['user', 'agent', 'assistant', 'tool_call', 'tool_result', 'system'];
      if (conversationalTypes.includes(entry.node_type)) {
        return false; // Filter out Initialization conversation messages
      }
    }

    // Core conversation messages
    const conversationalTypes = ['user', 'agent', 'assistant', 'tool_call', 'tool_result', 'follow_up', 'injection'];
    const conversationalSystemRoles = ['system']; // System prompts sent to LLM

    // Include validation/ward messages - these are part of the conversation flow
    const validationTypes = ['validation', 'validation_start', 'validation_error', 'validation_retry',
                            'ward_blocking', 'ward_retry', 'ward_advisory',
                            'pre_ward', 'post_ward', 'schema_validation', 'schema_validation_failed',
                            'sub_cascade_ref', 'sub_cascade_start', 'sub_cascade_complete'];

    // Include soundings/evaluation messages - critical for understanding workflow decisions
    const soundingsTypes = ['evaluation', 'evaluator', 'soundings_result', 'sounding_attempt',
                           'sounding_evaluation', 'soundings_start', 'reforge_start', 'reforge_result'];

    return conversationalTypes.includes(entry.node_type) ||
           (entry.node_type === 'system' && conversationalSystemRoles.includes(entry.role)) ||
           validationTypes.includes(entry.node_type) ||
           soundingsTypes.includes(entry.node_type);
  };

  const filterEntriesByViewMode = (entries) => {
    if (viewMode === 'all') {
      return showStructural ? entries : entries.filter(e => !isStructural(e));
    } else if (viewMode === 'conversation') {
      return entries.filter(e => isConversational(e));
    } else if (viewMode === 'structural') {
      return entries.filter(e => isStructural(e));
    }
    return entries;
  };

  const groupEntriesByPhase = (entries) => {
    const grouped = [];
    let currentPhase = null;
    let currentSoundingIndex = null;
    let currentGroup = null;

    entries.forEach((entry, idx) => {
      const phaseName = entry.phase_name || 'Initialization';
      const soundingIndex = entry.sounding_index;

      // Start new phase group when EITHER phase name OR sounding index changes
      if (phaseName !== currentPhase || soundingIndex !== currentSoundingIndex) {
        if (currentGroup) {
          grouped.push(currentGroup);
        }
        currentPhase = phaseName;
        currentSoundingIndex = soundingIndex;
        currentGroup = {
          phase: phaseName,
          entries: [],
          totalCost: 0,
          soundingIndex: soundingIndex
        };
      }

      // Add entry to current group with time gap info
      const enrichedEntry = { ...entry };

      // Calculate time gap from previous entry
      if (idx > 0) {
        const prevEntry = entries[idx - 1];
        const timeDiff = entry.timestamp - prevEntry.timestamp;
        enrichedEntry.timeDiff = timeDiff;
      }

      if (currentGroup) {
        currentGroup.entries.push(enrichedEntry);
        if (entry.cost) {
          currentGroup.totalCost += entry.cost;
        }
      }
    });

    // Add final group
    if (currentGroup) {
      grouped.push(currentGroup);
    }

    setGroupedEntries(grouped);
  };

  // Fetch session data when sessionId changes
  useEffect(() => {
    if (sessionId) {
      fetchSessionData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Re-group entries when view mode or entries change
  useEffect(() => {
    if (entries.length > 0) {
      const filtered = filterEntriesByViewMode(entries);
      groupEntriesByPhase(filtered);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, showStructural, entries]);

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString();
  };

  const getDirectionBadge = (entry) => {
    // SENT to LLM
    if (entry.node_type === 'user' ||
        (entry.node_type === 'system' && entry.role === 'system')) {
      return <span className="direction-badge sent">→ SENT</span>;
    }

    // RECEIVED from LLM
    if (entry.node_type === 'agent' ||
        entry.node_type === 'assistant' ||
        entry.role === 'agent' ||
        entry.role === 'assistant') {
      return <span className="direction-badge received">← RECEIVED</span>;
    }

    return null;
  };

  const getNodeIcon = (nodeType) => {
    switch (nodeType) {
      case 'user':
        return 'mdi:account';
      case 'agent':
      case 'assistant':
        return 'mdi:robot';
      case 'tool_call':
        return 'mdi:hammer-wrench';
      case 'tool_result':
        return 'mdi:check-circle';
      case 'injection':
        return 'mdi:image-multiple';
      case 'system':
        return 'mdi:cog';
      case 'phase_start':
        return 'mdi:play-circle';
      case 'phase_complete':
        return 'mdi:check-circle-outline';
      case 'error':
        return 'mdi:alert-circle';
      case 'cost_update':
        return 'mdi:currency-usd';
      case 'validation':
      case 'validation_start':
      case 'validation_error':
      case 'validation_retry':
        return 'mdi:shield-check';
      case 'pre_ward':
      case 'post_ward':
      case 'ward_blocking':
      case 'ward_retry':
      case 'ward_advisory':
        return 'mdi:shield-alert';
      case 'sub_cascade_ref':
      case 'sub_cascade_start':
      case 'sub_cascade_complete':
        return 'mdi:file-tree';
      case 'evaluation':
      case 'evaluator':
      case 'sounding_evaluation':
        return 'mdi:scale-balance';
      case 'soundings_result':
      case 'sounding_attempt':
        return 'mdi:chart-tree';
      case 'soundings_start':
        return 'mdi:chart-multiple';
      case 'reforge_start':
      case 'reforge_result':
        return 'mdi:hammer';
      default:
        return 'mdi:message';
    }
  };

  const getNodeColor = (nodeType) => {
    switch (nodeType) {
      case 'user':
        return '#60a5fa'; // Blue
      case 'agent':
      case 'assistant':
        return '#a78bfa'; // Purple
      case 'tool_call':
      case 'tool_result':
        return '#f472b6'; // Pink
      case 'injection':
        return '#34d399'; // Green (images injected into context)
      case 'system':
        return '#666'; // Gray
      case 'phase_start':
      case 'phase_complete':
        return '#34d399'; // Green
      case 'error':
      case 'validation_error':
        return '#f87171'; // Red
      case 'cost_update':
        return '#34d399'; // Green
      case 'validation':
      case 'validation_start':
      case 'validation_retry':
        return '#fbbf24'; // Yellow
      case 'pre_ward':
      case 'post_ward':
      case 'ward_blocking':
      case 'ward_retry':
      case 'ward_advisory':
        return '#60a5fa'; // Blue (wards)
      case 'sub_cascade_ref':
      case 'sub_cascade_start':
      case 'sub_cascade_complete':
        return '#a78bfa'; // Purple (sub-cascades)
      case 'evaluation':
      case 'evaluator':
      case 'sounding_evaluation':
        return '#fbbf24'; // Yellow (evaluation/decision)
      case 'soundings_result':
      case 'sounding_attempt':
        return '#fb923c'; // Orange (soundings)
      case 'soundings_start':
        return '#fb923c'; // Orange
      case 'reforge_start':
      case 'reforge_result':
        return '#fb923c'; // Orange (reforge)
      default:
        return '#666';
    }
  };

  // Helper to detect and render images from content
  const renderImagesFromContent = (content) => {
    // Handle multi-modal array format (OpenAI/Anthropic style)
    if (Array.isArray(content)) {
      const images = [];
      const textParts = [];

      content.forEach((part, idx) => {
        if (part.type === 'image_url' && part.image_url?.url) {
          images.push(
            <div key={`img-${idx}`} className="inline-image-container">
              <img
                src={part.image_url.url}
                alt={`Inline ${idx}`}
                className="inline-image"
                loading="lazy"
              />
            </div>
          );
        } else if (part.type === 'text' && part.text) {
          textParts.push(part.text);
        }
      });

      if (images.length > 0) {
        return {
          hasImages: true,
          images,
          text: textParts.join('\n')
        };
      }
    }

    // Handle string content with embedded base64 data URLs
    if (typeof content === 'string') {
      // Match data URLs for images
      const base64Pattern = /data:image\/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=]+/g;
      const matches = content.match(base64Pattern);

      if (matches && matches.length > 0) {
        const images = matches.map((url, idx) => (
          <div key={`img-${idx}`} className="inline-image-container">
            <img
              src={url}
              alt={`Inline ${idx}`}
              className="inline-image"
              loading="lazy"
            />
          </div>
        ));

        // Remove base64 data from text (it's very long)
        let cleanedText = content;
        matches.forEach(url => {
          cleanedText = cleanedText.replace(url, '[image]');
        });

        return {
          hasImages: true,
          images,
          text: cleanedText
        };
      }
    }

    return { hasImages: false, images: [], text: content };
  };

  const renderContent = (entry) => {
    const { content, node_type, metadata } = entry;

    // First check for images in content
    const imageResult = renderImagesFromContent(content);
    if (imageResult.hasImages) {
      return (
        <div className="content-with-images">
          <div className="inline-images-grid">
            {imageResult.images}
          </div>
          {imageResult.text && imageResult.text.trim() && (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {String(imageResult.text)}
              </ReactMarkdown>
            </div>
          )}
        </div>
      );
    }

    // For soundings evaluation/results, show with special highlighting
    if (node_type === 'evaluation' || node_type === 'evaluator' || node_type === 'sounding_evaluation') {
      return (
        <div className="evaluation-content">
          <div className="evaluation-header">
            <Icon icon="mdi:scale-balance" width="20" />
            <span className="evaluation-title">⚖️ Soundings Evaluator Decision</span>
          </div>
          <div className="evaluation-reasoning">
            {String(content)}
          </div>
        </div>
      );
    }

    // For soundings results, show winner announcement
    if (node_type === 'soundings_result') {
      try {
        const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
        const winnerIndex = meta?.winner_index;

        return (
          <div className="soundings-result-content">
            <div className="soundings-result-header">
              <Icon icon="mdi:trophy" width="20" />
              <span className="result-title">🏆 Winner Selected</span>
            </div>
            {winnerIndex !== undefined && (
              <div className="winner-info">
                Sounding #{winnerIndex} chosen as best attempt
              </div>
            )}
            {content && <div className="result-note">{String(content)}</div>}
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content)}</div>;
      }
    }

    // For sounding attempts, show attempt info
    if (node_type === 'sounding_attempt') {
      try {
        const soundingIndex = entry.sounding_index;
        const isWinner = entry.is_winner;

        return (
          <div className={`sounding-attempt-content ${isWinner ? 'winner' : ''}`}>
            <div className="attempt-header">
              <Icon icon={isWinner ? "mdi:trophy" : "mdi:chart-line"} width="16" />
              <span className="attempt-title">
                Sounding #{soundingIndex} {isWinner ? '(Winner)' : ''}
              </span>
            </div>
            {content && (
              <div className="attempt-summary">
                {String(content).substring(0, 150)}
                {String(content).length > 150 && '...'}
              </div>
            )}
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content)}</div>;
      }
    }

    // For cost updates, show special format
    if (node_type === 'cost_update') {
      return (
        <div className="cost-update-content">
          <div className="cost-amount">{formatCost(entry.cost)}</div>
          {entry.tokens_in && (
            <div className="token-info">
              {entry.tokens_in} in / {entry.tokens_out} out
            </div>
          )}
        </div>
      );
    }

    // For sub-cascade references, show with link to sub-session
    if (node_type === 'sub_cascade_ref' || node_type === 'sub_cascade_start' || node_type === 'sub_cascade_complete') {
      try {
        const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
        const subSessionId = meta?.sub_session_id || 'unknown';
        const validatorName = meta?.validator || meta?.cascade_name || 'sub-cascade';

        return (
          <div className="sub-cascade-content">
            <div className="sub-cascade-header">
              <Icon icon="mdi:file-tree" width="16" />
              <span className="sub-cascade-name">{validatorName}</span>
              <span className="sub-cascade-session">{subSessionId}</span>
            </div>
            <div className="sub-cascade-note">
              {node_type === 'sub_cascade_ref' && 'Sub-cascade execution started'}
              {node_type === 'sub_cascade_complete' && 'Sub-cascade completed'}
              {!node_type.includes('ref') && !node_type.includes('complete') && content}
            </div>
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content)}</div>;
      }
    }

    // For validation/ward messages, show with special styling
    if (node_type === 'validation' || node_type === 'validation_error' || node_type === 'validation_retry' ||
        node_type === 'validation_start' || node_type.includes('ward')) {
      try {
        const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
        const validatorName = meta?.validator || 'unknown';
        const isValid = meta?.valid;
        const reason = meta?.reason || content;

        return (
          <div className="validation-content">
            <div className="validation-header">
              <span className="validator-name">{validatorName}</span>
              {isValid !== undefined && (
                <span className={`validation-status ${isValid ? 'passed' : 'failed'}`}>
                  {isValid ? '✓ PASSED' : '✗ FAILED'}
                </span>
              )}
            </div>
            {reason && reason.length > 0 && reason !== content && (
              <div className="validation-reason">{reason}</div>
            )}
            {node_type === 'validation_start' && (
              <div className="validation-note">Running validator...</div>
            )}
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content)}</div>;
      }
    }

    // For tool calls, show tool name and arguments with syntax highlighting
    if (node_type === 'tool_call') {
      try {
        const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
        const toolName = meta?.tool_name || 'unknown';
        const args = meta?.arguments || content;
        const argsStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);

        return (
          <div className="tool-call-content">
            <div className="tool-name">{toolName}</div>
            <SyntaxHighlighter language="json" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px'}}>
              {argsStr}
            </SyntaxHighlighter>
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content)}</div>;
      }
    }

    // For tool results, show with syntax highlighting if it looks like code
    if (node_type === 'tool_result') {
      try {
        const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
        const toolName = meta?.tool_name || 'unknown';
        const contentStr = String(content);

        // Detect if content looks like code (has traceback, python syntax, etc.)
        const looksLikeCode = contentStr.includes('Traceback') ||
                             contentStr.includes('def ') ||
                             contentStr.includes('import ') ||
                             contentStr.includes('Error:');

        return (
          <div className="tool-result-content">
            <div className="tool-name">{toolName} result</div>
            {looksLikeCode ? (
              <SyntaxHighlighter language="python" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px', maxHeight: '400px', overflow: 'auto'}}>
                {contentStr}
              </SyntaxHighlighter>
            ) : (
              <pre className="tool-output">{contentStr.substring(0, 500)}{contentStr.length > 500 ? '...' : ''}</pre>
            )}
          </div>
        );
      } catch (e) {
        return <div className="message-content">{String(content).substring(0, 500)}</div>;
      }
    }

    // Default: Render as markdown for agent/assistant/user messages
    if (!content) return <div className="message-content empty">(empty)</div>;

    // For agent, assistant, user, system messages - render as markdown
    const shouldRenderMarkdown = ['agent', 'assistant', 'user', 'system', 'turn_output'].includes(node_type);

    if (shouldRenderMarkdown) {
      let contentStr = String(content);

      // Check if entire content is JSON (starts with { or [)
      if (contentStr.trim().startsWith('{') || contentStr.trim().startsWith('[')) {
        try {
          const parsed = JSON.parse(contentStr);
          return (
            <SyntaxHighlighter language="json" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px'}}>
              {JSON.stringify(parsed, null, 2)}
            </SyntaxHighlighter>
          );
        } catch (e) {
          // Not valid JSON, render as markdown
        }
      }

      // Detect inline {"tool": "...", "arguments": {...}} blocks and wrap them in code fences
      // This makes them render as syntax-highlighted JSON blocks
      // More robust pattern that handles nested objects in arguments
      const toolCallPattern = /\{"tool":\s*"[^"]+",\s*"arguments":\s*\{[^]*?\}\s*\}/g;

      // Find all tool call JSON blocks
      const matches = [...contentStr.matchAll(toolCallPattern)];

      if (matches.length > 0) {
        // Replace each match with a formatted code block
        let offset = 0;
        let modifiedContent = contentStr;

        for (const match of matches) {
          const originalJson = match[0];
          const startIndex = match.index + offset;

          try {
            // Try to parse and pretty-print
            const parsed = JSON.parse(originalJson);
            const formatted = JSON.stringify(parsed, null, 2);
            const replacement = `\n\`\`\`json\n${formatted}\n\`\`\`\n`;

            modifiedContent =
              modifiedContent.substring(0, startIndex) +
              replacement +
              modifiedContent.substring(startIndex + originalJson.length);

            offset += replacement.length - originalJson.length;
          } catch (e) {
            // If parsing fails, just wrap as-is
            const replacement = `\n\`\`\`json\n${originalJson}\n\`\`\`\n`;

            modifiedContent =
              modifiedContent.substring(0, startIndex) +
              replacement +
              modifiedContent.substring(startIndex + originalJson.length);

            offset += replacement.length - originalJson.length;
          }
        }

        contentStr = modifiedContent;
      }

      // Render as markdown with code syntax highlighting
      return (
        <div className="markdown-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({node, inline, className, children, ...props}) {
                const match = /language-(\w+)/.exec(className || '');
                const language = match ? match[1] : '';

                return !inline && language ? (
                  <SyntaxHighlighter
                    style={vscDarkPlus}
                    language={language}
                    PreTag="div"
                    customStyle={{margin: 0, borderRadius: '4px'}}
                    {...props}
                  >
                    {String(children).replace(/\n$/, '')}
                  </SyntaxHighlighter>
                ) : (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              }
            }}
          >
            {contentStr}
          </ReactMarkdown>
        </div>
      );
    }

    // Fallback: plain text for other node types
    return (
      <pre className="message-content">{String(content)}</pre>
    );
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  // Calculate stats based on all entries (before filtering)
  const structuralCount = entries.filter(e => isStructural(e)).length;
  const conversationalCount = entries.filter(e => isConversational(e)).length;

  if (!sessionId) return null;

  return createPortal(
    <div className="debug-modal-backdrop" onClick={handleBackdropClick}>
      <div className="debug-modal">
        <div className="debug-modal-header">
          <h2>
            <Icon icon="mdi:bug" width="24" />
            Debug: {sessionId}
          </h2>
          <div className="header-actions">
            {/* View mode selector */}
            <select
              className="view-mode-select"
              value={viewMode}
              onChange={e => setViewMode(e.target.value)}
              title="Filter message types"
            >
              <option value="conversation">💬 Conversation ({conversationalCount})</option>
              <option value="all">📋 All Entries ({entries.length})</option>
              <option value="structural">⚙️ Structural ({structuralCount})</option>
            </select>

            {/* Structural toggle (only show in 'all' mode) */}
            {viewMode === 'all' && (
              <button
                className={`toggle-structural ${showStructural ? 'active' : ''}`}
                onClick={() => setShowStructural(!showStructural)}
                title="Toggle framework/structural messages"
              >
                <Icon icon="mdi:cog" width="16" />
                {showStructural ? 'Hide' : 'Show'} Framework
              </button>
            )}

            <button
              className="dump-button"
              onClick={async () => {
                try {
                  const response = await fetch(`http://localhost:5001/api/session/${sessionId}/dump`, {
                    method: 'POST'
                  });
                  const data = await response.json();
                  if (data.success) {
                    alert(`Session dumped to: ${data.dump_path}\n${data.entry_count} entries saved`);
                  } else {
                    alert(`Error: ${data.error}`);
                  }
                } catch (err) {
                  alert(`Failed to dump: ${err.message}`);
                }
              }}
              title="Dump session to JSON file"
            >
              <Icon icon="mdi:download" width="20" />
              Dump
            </button>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
        </div>

        <div className="debug-modal-body">
          {/* Mermaid Graph at top */}
          {!loading && !error && (
            <div className="debug-mermaid-section">
              <MermaidPreview
                sessionId={sessionId}
                size="medium"
                showMetadata={false}
                lastUpdate={lastUpdate}
              />
            </div>
          )}

          {loading && (
            <div className="loading-state">
              <VideoSpinner message="Loading session data..." size={320} opacity={0.6} />
            </div>
          )}

          {error && (
            <div className="error-state">
              <Icon icon="mdi:alert-circle" width="32" />
              <p>{error}</p>
            </div>
          )}

          {!loading && !error && groupedEntries.length === 0 && (
            <div className="empty-state">
              <p>No data found for this session</p>
            </div>
          )}

          {!loading && !error && groupedEntries.map((group, groupIdx) => (
            <div key={groupIdx} className="phase-group">
              <div className="phase-header">
                <div className="phase-title">
                  <Icon icon="mdi:layers" width="20" />
                  <span className="phase-name">{group.phase}</span>
                  {group.soundingIndex !== null && group.soundingIndex !== undefined && (
                    <span className="sounding-badge">Sounding #{group.soundingIndex}</span>
                  )}
                </div>
                <div className="phase-cost">
                  {formatCost(group.totalCost)}
                </div>
              </div>

              <div className="phase-entries">
                {group.entries.map((entry, entryIdx) => (
                  <React.Fragment key={entryIdx}>
                    {/* Time gap indicator */}
                    {entry.timeDiff && entry.timeDiff > 2 && (
                      <div className="time-gap-indicator">
                        <Icon icon="mdi:clock-outline" width="14" />
                        <span>{entry.timeDiff.toFixed(1)}s gap</span>
                        <span className="gap-reason">(LLM processing)</span>
                      </div>
                    )}

                    <div
                      className={`entry-row ${entry.node_type}`}
                      style={{ '--node-color': getNodeColor(entry.node_type) }}
                    >
                      <div className="entry-meta">
                        <div className="entry-icon">
                          <Icon icon={getNodeIcon(entry.node_type)} width="18" />
                        </div>
                        <div className="entry-type">{entry.node_type}</div>
                        {entry.sounding_index !== null && entry.sounding_index !== undefined && (
                          <span className="entry-sounding-badge" title="Sounding index">
                            #{entry.sounding_index}
                          </span>
                        )}
                        <div className="entry-time">{formatTimestamp(entry.timestamp)}</div>
                        {entry.cost > 0 && (
                          <div className="entry-cost">{formatCost(entry.cost)}</div>
                        )}
                        {getDirectionBadge(entry)}
                      </div>
                      <div className="entry-content">
                        {renderContent(entry)}
                      </div>
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="debug-modal-footer">
          <div className="footer-stats">
            <span className="stat">
              <strong>{entries.length}</strong> total entries
            </span>
            <span className="stat">
              <strong>{conversationalCount}</strong> conversation
            </span>
            <span className="stat">
              <strong>{structuralCount}</strong> structural
            </span>
            <span className="stat">
              <strong>{groupedEntries.length}</strong> phases
            </span>
            <span className="stat">
              <strong>{formatCost(groupedEntries.reduce((sum, g) => sum + g.totalCost, 0))}</strong> total cost
            </span>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default DebugModal;
