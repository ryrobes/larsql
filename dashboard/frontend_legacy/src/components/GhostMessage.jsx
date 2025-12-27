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
        {/* Tool arguments (if JSON parsed) */}
        {parsedContent && ghost.type === 'tool_call' && (
          <details className="ghost-args">
            <summary>Arguments</summary>
            <pre>{JSON.stringify(parsedContent, null, 2)}</pre>
          </details>
        )}

        {/* Content display */}
        {!parsedContent && (
          <div className="ghost-text">
            {truncate(displayContent)}
          </div>
        )}

        {/* Tool result (simplified - can add data grid later) */}
        {ghost.type === 'tool_result' && parsedContent && (
          <pre className="ghost-result-json">
            {JSON.stringify(parsedContent, null, 2).substring(0, 300)}
            {JSON.stringify(parsedContent).length > 300 && '...'}
          </pre>
        )}
      </div>
    </div>
  );
};

export default GhostMessage;
