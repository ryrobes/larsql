import React, { useMemo } from 'react';
import RichMarkdown from '../../../components/RichMarkdown';
import './MarkdownPanel.css';

/**
 * MarkdownPanel - Renders markdown content in canvas panels
 *
 * Accepts content in several formats:
 * - Single-row array with 'code' key: [{ format: "markdown", code: "# Title..." }]
 * - Single-row array with 'content' key: [{ format: "markdown", content: "# Title..." }]
 * - Single-row array with 'markdown' key: [{ format: "markdown", markdown: "# Title..." }]
 * - Raw markdown string: "# Title..."
 * - Object with any of the above keys
 *
 * Uses RichMarkdown for full GFM support including:
 * - Tables, strikethrough, task lists
 * - Syntax-highlighted code blocks
 * - LaTeX math equations
 * - Emoji shortcuts
 */
const MarkdownPanel = ({ content }) => {
  // Extract markdown from various input formats
  const markdown = useMemo(() => {
    // Handle null/undefined
    if (content === null || content === undefined) {
      return '';
    }

    // Raw string
    if (typeof content === 'string') {
      return content;
    }

    // Single-row array (common from SQL results)
    if (Array.isArray(content) && content.length > 0) {
      const row = content[0];
      if (row) {
        // Check for various key names in order of preference
        if (row.code !== undefined) return String(row.code);
        if (row.content !== undefined) return String(row.content);
        if (row.markdown !== undefined) return String(row.markdown);
        if (row.text !== undefined) return String(row.text);
        if (row.body !== undefined) return String(row.body);
      }
    }

    // Object with direct keys
    if (typeof content === 'object' && content !== null) {
      if (content.code !== undefined) return String(content.code);
      if (content.content !== undefined) return String(content.content);
      if (content.markdown !== undefined) return String(content.markdown);
      if (content.text !== undefined) return String(content.text);
      if (content.body !== undefined) return String(content.body);
    }

    // Fallback: stringify
    return String(content);
  }, [content]);

  return (
    <div className="markdown-panel">
      <RichMarkdown>{markdown}</RichMarkdown>
    </div>
  );
};

export default MarkdownPanel;
