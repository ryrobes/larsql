import React, { useRef, useEffect, useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './HITLContentRenderer.css';

/**
 * HITLContentRenderer - Renders HITL HTML content in an isolated iframe (read-only)
 *
 * This is a lightweight version of HTMLSection designed for rendering historical
 * checkpoint content in detail panels and message logs. It does NOT support:
 * - Form submission (forms are displayed but disabled)
 * - Annotations
 * - Branching
 *
 * Features:
 * - Iframe isolation (prevents CSS/layout conflicts)
 * - Base LARS theme CSS
 * - Auto-resizing based on content height
 * - Template variable replacement
 * - HTMX support (for display only, not interaction)
 * - Mermaid.js diagram rendering
 *
 * @param {Object} uiSpec - The ui_spec from a checkpoint, containing content, options, etc.
 * @param {string} checkpointId - The checkpoint ID (for template variables)
 * @param {string} sessionId - The session ID (for template variables)
 * @param {boolean} compact - If true, uses more compact styling for detail panels
 */
function HITLContentRenderer({ uiSpec, checkpointId, sessionId, compact = false }) {
  const iframeRef = useRef(null);
  const [error, setError] = useState(null);
  const [iframeHeight, setIframeHeight] = useState(compact ? '200px' : '300px');

  // Extract content from ui_spec (handles different formats)
  const content = useMemo(() => {
    if (!uiSpec) return null;

    // Direct HTML content
    if (typeof uiSpec === 'string') return uiSpec;

    // Object with content field
    if (uiSpec.content) return uiSpec.content;

    // Object with html field
    if (uiSpec.html) return uiSpec.html;

    // Object with question/options (build display HTML)
    if (uiSpec.question || uiSpec.options) {
      return buildDisplayHTML(uiSpec);
    }

    // Try to stringify if object
    if (typeof uiSpec === 'object') {
      return `<pre style="color: #94a3b8; font-size: 12px;">${JSON.stringify(uiSpec, null, 2)}</pre>`;
    }

    return null;
  }, [uiSpec]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !content) return;

    try {
      // Process template variables
      const processedHTML = processTemplateVariables(content, {
        checkpoint_id: checkpointId || '',
        session_id: sessionId || '',
      });

      // Build iframe document with embedded base theme
      const iframeDoc = buildIframeDocument(processedHTML, compact);

      // Set iframe content
      iframe.srcdoc = iframeDoc;

      // Wait for iframe to load, then set up resize
      const handleLoad = () => {
        const iframeDocument = iframe.contentDocument;

        if (!iframeDocument) {
          setError('Failed to access iframe document');
          return;
        }

        // Disable all forms (read-only mode)
        disableForms(iframeDocument);

        // Auto-resize iframe to content height
        let resizeCount = 0;
        const MAX_RESIZES = 5;
        const PADDING = 16;

        const resizeIframe = () => {
          if (resizeCount >= MAX_RESIZES) return;
          resizeCount++;

          try {
            const body = iframeDocument.body;
            const contentHeight = body.offsetHeight;
            const targetHeight = Math.min(Math.max(contentHeight + PADDING, 100), compact ? 500 : 800);
            setIframeHeight(`${targetHeight}px`);
          } catch (err) {
            console.warn('[HITLContentRenderer] Could not resize iframe:', err);
          }
        };

        // Initial resize after a short delay
        setTimeout(resizeIframe, 100);
        setTimeout(resizeIframe, 300); // Second attempt for slow-loading content

        // Initialize Mermaid if present
        if (iframe.contentWindow?.mermaid) {
          try {
            iframe.contentWindow.mermaid.run();
          } catch (e) {
            console.warn('[HITLContentRenderer] Mermaid init failed:', e);
          }
        }
      };

      iframe.addEventListener('load', handleLoad);

      return () => {
        iframe.removeEventListener('load', handleLoad);
      };
    } catch (err) {
      console.error('[HITLContentRenderer] iframe setup error:', err);
      setError(`Failed to render HITL content: ${err.message}`);
    }
  }, [content, checkpointId, sessionId, compact]);

  if (error) {
    return (
      <div className="hitl-renderer-error">
        <Icon icon="mdi:alert-circle-outline" width="16" />
        <span>{error}</span>
      </div>
    );
  }

  if (!content) {
    return (
      <div className="hitl-renderer-empty">
        <Icon icon="mdi:file-document-outline" width="16" />
        <span>No HITL content available</span>
      </div>
    );
  }

  return (
    <div className={`hitl-renderer-wrapper ${compact ? 'hitl-renderer-compact' : ''}`}>
      <div className="hitl-renderer-badge">
        <Icon icon="mdi:checkbox-marked-circle-outline" width="12" />
        <span>Checkpoint (Read-Only)</span>
      </div>
      <iframe
        ref={iframeRef}
        className="hitl-renderer-iframe"
        style={{
          height: iframeHeight,
          width: '100%',
          border: 'none',
          display: 'block',
          backgroundColor: 'transparent',
          borderRadius: '8px',
        }}
        sandbox="allow-same-origin allow-scripts"
        title="HITL Checkpoint Content"
      />
    </div>
  );
}

/**
 * Disable all forms in the iframe (read-only mode)
 */
function disableForms(doc) {
  // Disable all inputs
  doc.querySelectorAll('input, textarea, select').forEach(el => {
    el.disabled = true;
    el.style.opacity = '0.7';
    el.style.cursor = 'not-allowed';
  });

  // Disable all buttons
  doc.querySelectorAll('button').forEach(el => {
    el.disabled = true;
    el.style.opacity = '0.5';
    el.style.cursor = 'not-allowed';
  });

  // Prevent form submissions
  doc.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', e => {
      e.preventDefault();
      e.stopPropagation();
    });
  });
}

/**
 * Build display HTML for question/options format
 */
function buildDisplayHTML(spec) {
  const { question, options, html } = spec;

  let output = '<div class="hitl-display">';

  // Custom HTML content first
  if (html) {
    output += `<div class="hitl-custom-html">${html}</div>`;
  }

  // Question
  if (question) {
    output += `<h3 class="hitl-question">${escapeHtml(question)}</h3>`;
  }

  // Options
  if (options && options.length > 0) {
    output += '<div class="hitl-options">';
    options.forEach((opt, idx) => {
      const label = typeof opt === 'string' ? opt : (opt.label || opt.id || `Option ${idx + 1}`);
      const description = typeof opt === 'object' ? opt.description : null;
      const isSelected = opt.selected || opt.chosen;

      output += `
        <div class="hitl-option ${isSelected ? 'selected' : ''}">
          <div class="hitl-option-label">${escapeHtml(label)}</div>
          ${description ? `<div class="hitl-option-desc">${escapeHtml(description)}</div>` : ''}
        </div>
      `;
    });
    output += '</div>';
  }

  output += '</div>';
  return output;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Process template variables in HTML
 */
function processTemplateVariables(html, vars) {
  let result = html;
  for (const [key, value] of Object.entries(vars)) {
    const regex = new RegExp(`{{\\s*${key}\\s*}}`, 'g');
    result = result.replace(regex, value || '');
  }
  return result;
}

/**
 * Build complete iframe HTML document with base theme CSS
 */
function buildIframeDocument(bodyHTML, compact) {
  const baseCSS = `
    :root {
      --bg-primary: #0a0a0a;
      --bg-secondary: #121212;
      --bg-tertiary: #1a1a1a;
      --text-primary: #f1f5f9;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --accent-cyan: #00e5ff;
      --accent-purple: #a78bfa;
      --accent-green: #10b981;
      --border-color: #333;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: ${compact ? '12px' : '13px'};
      line-height: 1.6;
      color: var(--text-primary);
      background: var(--bg-primary);
      padding: ${compact ? '12px' : '16px'};
    }

    h1, h2, h3, h4, h5, h6 {
      color: var(--text-primary);
      margin-bottom: 0.5em;
      font-weight: 600;
    }

    h3 { font-size: 1.1em; }

    p { margin-bottom: 0.75em; color: var(--text-secondary); }

    a { color: var(--accent-cyan); text-decoration: none; }
    a:hover { text-decoration: underline; }

    code {
      background: var(--bg-tertiary);
      padding: 0.2em 0.4em;
      border-radius: 4px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.9em;
      color: var(--accent-cyan);
    }

    pre {
      background: var(--bg-tertiary);
      padding: 12px;
      border-radius: 8px;
      overflow-x: auto;
      margin-bottom: 1em;
      border: 1px solid var(--border-color);
    }

    pre code {
      background: none;
      padding: 0;
    }

    /* HITL Display Styles */
    .hitl-display {
      padding: 8px 0;
    }

    .hitl-question {
      color: var(--accent-purple);
      margin-bottom: 12px;
    }

    .hitl-options {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .hitl-option {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 10px 14px;
    }

    .hitl-option.selected {
      border-color: var(--accent-green);
      background: rgba(16, 185, 129, 0.1);
    }

    .hitl-option-label {
      font-weight: 500;
      color: var(--text-primary);
    }

    .hitl-option-desc {
      font-size: 0.9em;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* Form elements (disabled state) */
    input, textarea, select {
      background: var(--bg-tertiary);
      border: 1px solid var(--border-color);
      color: var(--text-primary);
      padding: 8px 12px;
      border-radius: 6px;
      width: 100%;
      margin-bottom: 8px;
    }

    button {
      background: var(--accent-purple);
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 500;
      cursor: pointer;
    }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 1em;
    }

    th, td {
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border-color);
    }

    th {
      background: var(--bg-secondary);
      color: var(--text-primary);
      font-weight: 600;
    }

    /* Cards */
    .card {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 12px;
    }

    /* Mermaid diagrams */
    .mermaid {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 16px;
      margin: 12px 0;
    }

    /* Read-only overlay indicator */
    .readonly-badge {
      position: fixed;
      bottom: 8px;
      right: 8px;
      background: rgba(100, 116, 139, 0.8);
      color: white;
      font-size: 10px;
      padding: 4px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
  `;

  return `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>${baseCSS}</style>
      <!-- Mermaid.js for diagrams -->
      <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
      <script>
        if (typeof mermaid !== 'undefined') {
          mermaid.initialize({
            startOnLoad: true,
            theme: 'dark',
            themeVariables: {
              primaryColor: '#1a1a2e',
              primaryTextColor: '#f1f5f9',
              primaryBorderColor: '#00e5ff',
              lineColor: '#a78bfa',
              secondaryColor: '#16213e',
              tertiaryColor: '#0f3460'
            },
            fontFamily: "'Inter', sans-serif"
          });
        }
      </script>
    </head>
    <body>
      ${bodyHTML}
      <div class="readonly-badge">Read Only</div>
    </body>
    </html>
  `;
}

export default HITLContentRenderer;
