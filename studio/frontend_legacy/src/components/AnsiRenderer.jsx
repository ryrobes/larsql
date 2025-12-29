/**
 * AnsiRenderer - Renders text with ANSI escape codes as colored HTML
 *
 * Supports:
 * - 256 colors (via anser's RGB conversion)
 * - Text formatting (bold, dim, italic, underline)
 * - Background colors
 * - Preserves terminal-like appearance
 * - Unicode box-drawing characters (via terminal font stack)
 *
 * Uses the 'anser' library to parse ANSI escape sequences into RGB colors.
 * Colors are applied via inline styles for accurate rendering.
 */
import React from 'react';
import Anser from 'anser';
import './AnsiRenderer.css';

/**
 * AnsiRenderer Component
 *
 * @param {string} children - Text content with ANSI escape codes
 */
function AnsiRenderer({ children }) {
  // Debug logging
  React.useEffect(() => {
    console.log('[AnsiRenderer] Raw input (first 200 chars):', children?.substring(0, 200));
    console.log('[AnsiRenderer] Contains \\x1b?', children?.includes('\x1b'));
    console.log('[AnsiRenderer] Contains \\u001b?', children?.includes('\u001b'));

    // Try ansiToJson
    if (children) {
      const json = Anser.ansiToJson(children, { use_classes: false });
      console.log('[AnsiRenderer] ansiToJson output (first 5):', json.slice(0, 5));

      // Try ansiToHtml
      const html = Anser.ansiToHtml(children, { use_classes: false });
      console.log('[AnsiRenderer] ansiToHtml output (first 200 chars):', html.substring(0, 200));
    }
  }, [children]);

  const ansiHtml = React.useMemo(() => {
    if (!children || typeof children !== 'string') return '';

    // Handle escaped ANSI codes (e.g., "\\x1b[31m" as literal string)
    // Convert them to actual escape characters
    let processedText = children;

    // Check if we have escaped codes
    if (processedText.includes('\\x1b')) {
      console.log('[AnsiRenderer] Found escaped \\x1b codes, unescaping...');
      processedText = processedText.replace(/\\x1b/g, '\x1b');
    }
    if (processedText.includes('\\u001b')) {
      console.log('[AnsiRenderer] Found escaped \\u001b codes, unescaping...');
      processedText = processedText.replace(/\\u001b/g, '\u001b');
    }
    if (processedText.includes('\\033')) {
      console.log('[AnsiRenderer] Found escaped \\033 codes, unescaping...');
      // Use hex \x1b instead of octal \033 (strict mode doesn't allow octal)
      processedText = processedText.replace(/\\033/g, '\x1b');
    }

    // Also handle literal newlines
    processedText = processedText.replace(/\\n/g, '\n');
    processedText = processedText.replace(/\\r/g, '\r');
    processedText = processedText.replace(/\\t/g, '\t');

    // Use anser's ansiToHtml method which returns styled HTML
    let htmlString = Anser.ansiToHtml(processedText, {
      use_classes: false,  // Use inline styles
      remove_empty: false, // Keep empty spans to preserve spacing
    });

    // CRITICAL: Replace all spaces with non-breaking spaces to prevent HTML collapse
    // But only OUTSIDE of HTML tags (to not break the tags themselves)
    htmlString = htmlString.replace(/ (?![^<]*>)/g, '&nbsp;');

    return htmlString;
  }, [children]);

  return (
    <div className="ansi-output">
      <pre dangerouslySetInnerHTML={{ __html: ansiHtml }} />
    </div>
  );
}

export default React.memo(AnsiRenderer);
