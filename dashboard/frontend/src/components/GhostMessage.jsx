import React from 'react';
import { Icon } from '@iconify/react';
import './GhostMessage.css';

/**
 * GhostMessage - Live activity indicator showing LLM's work-in-progress
 *
 * Displays tool calls, tool results, and thinking messages.
 * Auto-removed by parent after timeout.
 *
 * Uses Framer Motion for enter/exit animations (applied by parent).
 */
const GhostMessage = ({ ghost }) => {
  const getIcon = () => {
    switch (ghost.type) {
      case 'tool_call':
        return 'mdi:hammer-wrench';
      case 'tool_result':
        return 'mdi:check-circle';
      case 'thinking':
        return 'mdi:brain';
      default:
        return 'mdi:dots-horizontal';
    }
  };

  const getTitle = () => {
    switch (ghost.type) {
      case 'tool_call':
        return ghost.tool ? `Calling ${ghost.tool}` : 'Tool Call';
      case 'tool_result':
        return ghost.tool ? `${ghost.tool} result` : 'Tool Result';
      case 'thinking':
        return 'Thinking...';
      default:
        return 'Activity';
    }
  };

  const getBorderColor = () => {
    switch (ghost.type) {
      case 'tool_call':
        return 'var(--color-accent-cyan)';
      case 'tool_result':
        return 'var(--color-accent-green)';
      case 'thinking':
        return 'var(--color-accent-purple)';
      default:
        return 'var(--color-border-dim)';
    }
  };

  // Parse JSON from content (simplified - full version can be added later)
  const tryParseJSON = (text) => {
    if (!text) return null;
    try {
      // Extract from markdown code blocks
      const match = text.match(/```(?:json)?\s*\n?({[\s\S]*?})\s*\n?```/);
      if (match) {
        return JSON.parse(match[1]);
      }
      // Try direct parse if starts with {
      if (text.trim().startsWith('{')) {
        return JSON.parse(text);
      }
    } catch (e) {
      // Not JSON
    }
    return null;
  };

  // Truncate long content
  const truncate = (text, maxLength = 200) => {
    if (!text) return '';
    const str = typeof text === 'string' ? text : JSON.stringify(text);
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
  };

  const parsedContent = ghost.arguments || tryParseJSON(ghost.content);
  const displayContent = ghost.content || ghost.result || '';

  // For thinking type, extract text content even from JSON
  const thinkingText = React.useMemo(() => {
    if (ghost.type !== 'thinking') return null;

    // First try raw content
    if (ghost.content) {
      // If it's a string that looks like plain text, use it
      if (typeof ghost.content === 'string' && !ghost.content.trim().startsWith('{')) {
        return ghost.content;
      }
      // Try to extract text from JSON
      try {
        const parsed = JSON.parse(ghost.content);
        // Handle various content formats
        if (typeof parsed === 'string') return parsed;
        if (parsed.content) return typeof parsed.content === 'string' ? parsed.content : JSON.stringify(parsed.content);
        if (parsed.text) return parsed.text;
        if (parsed.thinking) return parsed.thinking;
        if (parsed.message) return parsed.message;
        // Fall back to stringified version
        return JSON.stringify(parsed, null, 2);
      } catch (e) {
        return ghost.content;
      }
    }
    return displayContent;
  }, [ghost.type, ghost.content, displayContent]);

  // For tool results, parse and format
  const toolResultContent = React.useMemo(() => {
    if (ghost.type !== 'tool_result') return null;

    const result = ghost.result || ghost.content;
    if (!result) return null;

    try {
      const parsed = typeof result === 'string' ? JSON.parse(result) : result;
      // Extract meaningful content from tool results
      if (parsed.content) return typeof parsed.content === 'string' ? parsed.content : JSON.stringify(parsed.content, null, 2);
      if (parsed.result) return typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result, null, 2);
      if (parsed.output) return typeof parsed.output === 'string' ? parsed.output : JSON.stringify(parsed.output, null, 2);
      return JSON.stringify(parsed, null, 2);
    } catch (e) {
      return result;
    }
  }, [ghost.type, ghost.result, ghost.content]);

  return (
    <div
      className={`ghost-message ghost-${ghost.type}`}
      style={{ borderLeftColor: getBorderColor() }}
    >
      <div className="ghost-header">
        <Icon icon={getIcon()} width="14" />
        <span className="ghost-title">{getTitle()}</span>
        <span className="ghost-timestamp">
          {new Date(ghost.timestamp).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
          })}
        </span>
      </div>

      <div className="ghost-content">
        {/* Tool call: show tool name and arguments */}
        {ghost.type === 'tool_call' && (
          <>
            {parsedContent && (
              <details className="ghost-args" open>
                <summary>Arguments</summary>
                <pre>{JSON.stringify(parsedContent, null, 2)}</pre>
              </details>
            )}
            {!parsedContent && displayContent && (
              <div className="ghost-text">{truncate(displayContent)}</div>
            )}
          </>
        )}

        {/* Thinking: always show content */}
        {ghost.type === 'thinking' && thinkingText && (
          <div className="ghost-text ghost-thinking-text">
            {truncate(thinkingText, 500)}
          </div>
        )}

        {/* Tool result: show formatted result */}
        {ghost.type === 'tool_result' && (
          <pre className="ghost-result-json">
            {truncate(toolResultContent || displayContent, 400)}
          </pre>
        )}
      </div>
    </div>
  );
};

export default GhostMessage;
