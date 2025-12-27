import React, { useMemo } from 'react';
import Editor from '@monaco-editor/react';
import { configureMonacoTheme, STUDIO_THEME_NAME } from '../utils/monacoTheme';
import './MessageContentViewer.css';

/**
 * MessageContentViewer - Intelligent content renderer with Monaco
 *
 * Features:
 * - Auto-detects content type (JSON, markdown, plain text)
 * - Properly unescapes strings (removes quotes, converts \n to newlines)
 * - Monaco editor with syntax highlighting (read-only)
 * - Clean, componentized design
 *
 * @param {string|object} content - Content to display (can be JSON string or object)
 * @param {string} className - Additional CSS classes
 */
const MessageContentViewer = ({ content, className = '' }) => {
  // Process and detect content type
  const { text, language } = useMemo(() => {
    if (!content) {
      return { text: '', language: 'plaintext' };
    }

    let rawText = content;

    // If it's an object, stringify it
    if (typeof content === 'object') {
      return {
        text: JSON.stringify(content, null, 2),
        language: 'json'
      };
    }

    // If it's a string, we need to intelligently process it
    if (typeof content === 'string') {
      // Try to parse as JSON (might be double-encoded)
      try {
        const parsed = JSON.parse(content);

        // Check if parsed result is a string (double-encoded JSON string)
        if (typeof parsed === 'string') {
          // This was a JSON string containing text - use the inner string
          rawText = parsed;
        } else {
          // This was actual JSON data - pretty print it
          return {
            text: JSON.stringify(parsed, null, 2),
            language: 'json'
          };
        }
      } catch {
        // Not valid JSON, treat as raw string
        rawText = content;
      }

      // At this point, rawText is a string (possibly with escaped characters)
      // Unescape common escape sequences
      let unescaped = rawText;

      // Remove wrapping quotes if present (from JSON string encoding)
      if ((unescaped.startsWith('"') && unescaped.endsWith('"')) ||
          (unescaped.startsWith("'") && unescaped.endsWith("'"))) {
        unescaped = unescaped.slice(1, -1);
      }

      // Replace escape sequences
      unescaped = unescaped
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\r/g, '\r')
        .replace(/\\"/g, '"')
        .replace(/\\'/g, "'")
        .replace(/\\\\/g, '\\'); // Do this last to avoid double-unescaping

      // Detect language from unescaped content
      const detectedLanguage = detectLanguage(unescaped);

      return {
        text: unescaped,
        language: detectedLanguage
      };
    }

    // Fallback
    return {
      text: String(content),
      language: 'plaintext'
    };
  }, [content]);

  return (
    <div className={`message-content-viewer ${className}`}>
      <Editor
        height="100%"
        language={language}
        value={text}
        theme={STUDIO_THEME_NAME}
        beforeMount={configureMonacoTheme}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: 'on',
          fontSize: 12,
          lineNumbers: 'on',
          glyphMargin: false,
          folding: true,
          lineDecorationsWidth: 0,
          lineNumbersMinChars: 3,
          renderLineHighlight: 'none',
          contextmenu: false,
          scrollbar: {
            vertical: 'auto',
            horizontal: 'auto',
            verticalScrollbarSize: 10,
            horizontalScrollbarSize: 10,
          },
          padding: {
            top: 12,
            bottom: 12,
          },
        }}
      />
    </div>
  );
};

/**
 * Detect language from content
 *
 * @param {string} text - Text to analyze
 * @returns {string} - Monaco language identifier
 */
function detectLanguage(text) {
  if (!text || typeof text !== 'string') {
    return 'plaintext';
  }

  const trimmed = text.trim();

  // Check for JSON
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      JSON.parse(trimmed);
      return 'json';
    } catch {
      // Not valid JSON, continue checking
    }
  }

  // Check for markdown indicators
  const markdownPatterns = [
    /^#{1,6}\s/m,           // Headers
    /^\*\*.*\*\*$/m,        // Bold
    /^[-*+]\s/m,            // Lists
    /^\d+\.\s/m,            // Numbered lists
    /\[.*\]\(.*\)/,         // Links
    /```/,                  // Code blocks
    /^>\s/m,                // Blockquotes
  ];

  for (const pattern of markdownPatterns) {
    if (pattern.test(trimmed)) {
      return 'markdown';
    }
  }

  // Check for code-like patterns (SQL, Python, JavaScript)
  if (/^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)/i.test(trimmed)) {
    return 'sql';
  }

  if (/^(def |class |import |from |if __name__|#!\/)/m.test(trimmed)) {
    return 'python';
  }

  if (/^(function|const |let |var |=>|import |export |class )/m.test(trimmed)) {
    return 'javascript';
  }

  // Default to plain text
  return 'plaintext';
}

export default MessageContentViewer;
