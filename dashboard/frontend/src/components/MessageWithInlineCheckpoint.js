import React from 'react';
import RichMarkdown from './RichMarkdown';
import HTMLSection from './sections/HTMLSection';
import './MessageWithInlineCheckpoint.css';

/**
 * MessageWithInlineCheckpoint - Renders assistant message with inline checkpoint UI
 *
 * Shows the LLM's message text with the HTMX form appearing inline where the
 * tool call occurred, maintaining conversational flow and positional context.
 *
 * Structure:
 * 1. Assistant message text (markdown rendered)
 * 2. HTMX form (inline, at position of tool call)
 * 3. Any text after the tool call (if present)
 */
function MessageWithInlineCheckpoint({ checkpoint, onSubmit, isLoading, checkpointId, sessionId }) {
  const { phase_output, ui_spec } = checkpoint;

  // Find HTML sections in the UI spec
  const htmlSections = [];
  const otherSections = [];

  (ui_spec?.sections || []).forEach(section => {
    if (section.type === 'html') {
      htmlSections.push(section);
    } else if (section.type !== 'submit') {
      // Skip submit sections, collect others
      otherSections.push(section);
    }
  });

  const hasHTMLSection = htmlSections.length > 0;

  // Extract message text (remove tool call markers if present)
  const cleanMessageText = React.useMemo(() => {
    if (!phase_output) return '';

    // Strip common tool call patterns that might appear in the output
    let cleaned = phase_output;

    // Remove code fences with tool calls
    cleaned = cleaned.replace(/```[\w_]*\s*\n?\{[\s\S]*?"tool"[\s\S]*?\n?```/g, '');

    // Remove XML tool calls
    cleaned = cleaned.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, '');
    cleaned = cleaned.replace(/<function_call>[\s\S]*?<\/function_call>/g, '');

    // Remove function call syntax
    cleaned = cleaned.replace(/\brequest_decision\s*\([^)]*\)/g, '');

    return cleaned.trim();
  }, [phase_output]);

  console.log('[MessageWithInlineCheckpoint] checkpoint:', checkpoint);
  console.log('[MessageWithInlineCheckpoint] phase_output:', phase_output);
  console.log('[MessageWithInlineCheckpoint] cleanMessageText:', cleanMessageText);
  console.log('[MessageWithInlineCheckpoint] htmlSections:', htmlSections);
  console.log('[MessageWithInlineCheckpoint] ui_spec:', ui_spec);

  // Extract header/text sections that might contain the message
  const headerSections = ui_spec?.sections?.filter(s => s.type === 'header') || [];
  const textSections = ui_spec?.sections?.filter(s => s.type === 'text' && s.content) || [];

  return (
    <div className="message-with-inline-checkpoint">
      {/* Render headers (question, context) */}
      {headerSections.map((section, idx) => (
        <div key={`header-${idx}`} className="checkpoint-header-section">
          <h2 className="checkpoint-question">{section.text}</h2>
        </div>
      ))}

      {/* Render text sections (context) */}
      {textSections.map((section, idx) => (
        <div key={`text-${idx}`} className="checkpoint-text-section">
          <p className="checkpoint-context">{section.content}</p>
        </div>
      ))}

      {/* Render the assistant's message text if available */}
      {cleanMessageText && (
        <div className="assistant-message-content">
          <RichMarkdown>{cleanMessageText}</RichMarkdown>
        </div>
      )}

      {/* Render HTML sections inline (where tool call appeared) */}
      {htmlSections.map((section, idx) => (
        <div key={idx} className="inline-checkpoint-ui">
          <HTMLSection
            spec={section}
            checkpointId={checkpointId}
            sessionId={sessionId}
          />
        </div>
      ))}

      {/* If there are other section types (header, text_input, etc), show them after */}
      {otherSections.length > 0 && (
        <div className="additional-sections">
          {otherSections.map((section, idx) => (
            <div key={idx} className="additional-section">
              {/* Could render these via DynamicUI if needed, but typically HTML is self-contained */}
              <p className="section-placeholder">
                [Section type: {section.type}]
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default MessageWithInlineCheckpoint;
