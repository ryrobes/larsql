import React from 'react';
import RichMarkdown from './RichMarkdown';
import HTMLSection from './sections/HTMLSection';
import './MessageContent.css';

/**
 * MessageContent - Universal message renderer with inline UI support
 *
 * Automatically detects and renders:
 * - Markdown content (text, code, lists, etc.)
 * - Inline HTML/HTMX UIs (from show_ui or request_decision)
 * - Collapsible UIs (if specified)
 *
 * Works everywhere: MessageFlowView, DetailView, CheckpointPanel, DebugModal
 *
 * Usage:
 *   <MessageContent message={msg} sessionId={sessionId} />
 *
 * Where message can have:
 *   - content: Markdown text
 *   - ui_spec: {type: "html_display", content: "<html>...", title: "...", collapsible: true}
 *   - node_type: "ui_display" (optional, for styling)
 */
function MessageContent({ message, sessionId, compact = false, checkpointId = null }) {
  const { content, node_type, metadata } = message;

  // Check for ui_spec in message (direct) or message.metadata (from database)
  const ui_spec = message.ui_spec || (metadata && metadata.ui_spec);

  // Check if this message has an HTML UI to display
  const hasHTMLUI = ui_spec && (ui_spec.type === 'html' || ui_spec.type === 'html_display');

  // Extract checkpoint ID (from message, ui_spec, or prop)
  const effectiveCheckpointId = checkpointId || message.checkpoint_id || ui_spec?.checkpoint_id || 'no-checkpoint';

  // Parse content to find show_ui tool calls and extract HTML
  const { cleanContent, inlineUIs } = React.useMemo(() => {
    if (typeof content !== 'string') {
      return { cleanContent: content, inlineUIs: [] };
    }

    const uis = [];
    let cleaned = content;

    // Debug: Check if content has show_ui mentions
    if (content.includes('show_ui')) {
      console.log('[MessageContent] Content has show_ui, parsing...', content.substring(0, 500));
    }

    // Pattern: Look for show_ui tool calls in JSON code blocks (```json or just ```)
    const patterns = [
      /```json\s*\n\{[\s\S]*?"tool":\s*"show_ui"[\s\S]*?\}\s*```/g,
      /```\s*\n\{[\s\S]*?"tool":\s*"show_ui"[\s\S]*?\}\s*```/g,
      /\{[\s\S]*?"tool":\s*"show_ui"[\s\S]*?\}/g  // Also try without code fences
    ];

    patterns.forEach((pattern, patternIdx) => {
      const matches = [...cleaned.matchAll(pattern)];

      if (matches.length > 0) {
        console.log(`[MessageContent] Pattern ${patternIdx} matched ${matches.length} times`);
      }

      matches.forEach((match, idx) => {
        try {
          // Extract JSON from code block or direct
          let jsonStr = match[0];
          console.log('[MessageContent] Raw match:', jsonStr.substring(0, 200));

          // Remove code fences if present
          jsonStr = jsonStr.replace(/```(?:json)?\s*\n?/g, '').replace(/```/g, '').trim();

          console.log('[MessageContent] Cleaned JSON:', jsonStr.substring(0, 200));

          const toolCall = JSON.parse(jsonStr);
          console.log('[MessageContent] Parsed tool call:', toolCall);

          if (toolCall.tool === 'show_ui' && toolCall.arguments) {
            const args = toolCall.arguments;
            console.log('[MessageContent] ✓ Found show_ui with args:', {title: args.title, html_length: args.html?.length});

            // Only add if we haven't already found this one
            if (!uis.some(u => u.html === args.html)) {
              uis.push({
                html: args.html,
                title: args.title,
                description: args.description,
                collapsible: args.collapsible,
                index: idx
              });

              // Remove the tool call from content
              cleaned = cleaned.replace(match[0], `\n_[UI: ${args.title || 'Interactive Display'}]_\n`);
              console.log('[MessageContent] Replaced tool call with marker');
            }
          }
        } catch (err) {
          console.warn('[MessageContent] Failed to parse match:', err.message);
        }
      });
    });

    return { cleanContent: cleaned, inlineUIs: uis };
  }, [content]);

  // Debug logging
  if (node_type === 'ui_display' || inlineUIs.length > 0) {
    console.log('[MessageContent] Message with UI:', {
      node_type,
      hasUISpec: hasHTMLUI,
      inlineUIsFromToolCalls: inlineUIs.length,
      content: typeof content === 'string' ? content.substring(0, 200) : content
    });
  }

  // Collapsible state for display UIs
  const [isExpanded, setIsExpanded] = React.useState(!ui_spec?.collapsible);

  // Check if this is a tool_result for show_ui - hide it (UI is rendered inline with the call)
  const isShowUIResult = (node_type === 'tool_result' || message.role === 'tool') &&
                         content &&
                         typeof content === 'string' &&
                         (content.includes("'displayed': True") ||
                          content.includes('"displayed": true') ||
                          content.includes('show_ui'));

  if (isShowUIResult) {
    console.log('[MessageContent] Hiding show_ui tool result');
    // Hide show_ui tool results - the UI is already rendered inline where it was called
    return null;
  }

  return (
    <div className={`message-content-universal ${hasHTMLUI || inlineUIs.length > 0 ? 'has-inline-ui' : ''} ${node_type || ''}`}>
      {/* Render markdown content (with tool calls stripped) */}
      {(cleanContent || content) && (
        <div className="message-text">
          <RichMarkdown>{cleanContent || content}</RichMarkdown>
        </div>
      )}

      {/* Render UIs extracted from tool calls */}
      {inlineUIs.map((ui, idx) => (
        <div key={`inline-ui-${idx}`} className="message-inline-ui">
          <div className="ui-header-section">
            {ui.title && (
              <h3 className="ui-display-title">{ui.title}</h3>
            )}
            {ui.description && (
              <p className="ui-display-description">{ui.description}</p>
            )}
          </div>
          <HTMLSection
            spec={{
              type: 'html_display',
              content: ui.html
            }}
            checkpointId={effectiveCheckpointId}
            sessionId={sessionId}
          />
        </div>
      ))}

      {/* Render inline UI if present from ui_spec */}
      {hasHTMLUI && (
        <div className="message-inline-ui">
          {/* Title/description for display UIs (not shown for checkpoints) */}
          {ui_spec.type === 'html_display' && !compact && (
            <div className="ui-header-section">
              {ui_spec.title && (
                <h3 className="ui-display-title">{ui_spec.title}</h3>
              )}
              {ui_spec.description && (
                <p className="ui-display-description">{ui_spec.description}</p>
              )}
              {ui_spec.collapsible && (
                <button
                  className="ui-collapse-toggle"
                  onClick={() => setIsExpanded(!isExpanded)}
                >
                  {isExpanded ? '▼ Collapse' : '▶ Expand'}
                </button>
              )}
            </div>
          )}

          {/* Render HTML content if expanded (or not collapsible) */}
          {isExpanded && (
            <HTMLSection
              spec={ui_spec}
              checkpointId={effectiveCheckpointId}
              sessionId={sessionId}
            />
          )}
        </div>
      )}
    </div>
  );
}

export default MessageContent;
