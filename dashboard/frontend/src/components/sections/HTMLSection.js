import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import html2canvas from 'html2canvas';
import AnnotationCanvas from './AnnotationCanvas';
import AnnotationToolbar from './AnnotationToolbar';
import './HTMLSection.css';

/**
 * HTMLSection - Renders raw HTML with HTMX support in an isolated iframe
 *
 * SECURITY WARNING: This component renders unsanitized HTML in an iframe.
 * Only use in trusted development environments. Never deploy to production without
 * adding DOMPurify sanitization.
 *
 * Features:
 * - Iframe isolation (prevents CSS/layout conflicts)
 * - Base Windlass theme CSS (colors, fonts) inherited
 * - Auto-resizing based on content height
 * - Template variable replacement ({{ checkpoint_id }}, {{ session_id }})
 * - HTMX initialization and lifecycle management
 * - Auto-injection of checkpoint context headers
 * - Error handling and source display
 * - Branching: Can intercept form submissions to create research branches
 * - Annotation: Draw on top of rendered content (TLDRAW-style)
 */
function HTMLSection({ spec, checkpointId, sessionId, isSavedCheckpoint, onBranchSubmit, onAnnotationSave }) {
  const iframeRef = useRef(null);
  const annotationCanvasRef = useRef(null);
  const [error, setError] = useState(null);
  const [iframeHeight, setIframeHeight] = useState('400px');

  // Annotation state
  const [annotationMode, setAnnotationMode] = useState(false);
  const [brushColor, setBrushColor] = useState('#ef4444'); // Red default
  const [brushSize, setBrushSize] = useState(5); // Medium default
  const [strokeCount, setStrokeCount] = useState(0);
  const [isSavingScreenshot, setIsSavingScreenshot] = useState(false);
  const [savedScreenshotUrl, setSavedScreenshotUrl] = useState(null);
  const wrapperRef = useRef(null);

  // Annotation handlers
  const handleStrokesChange = useCallback((strokes) => {
    setStrokeCount(strokes.length);
  }, []);

  const handleUndo = useCallback(() => {
    annotationCanvasRef.current?.undo();
  }, []);

  const handleClear = useCallback(() => {
    annotationCanvasRef.current?.clear();
  }, []);

  const handleAnnotationDone = useCallback(() => {
    // Exit annotation mode but keep strokes visible
    setAnnotationMode(false);

    // If there are annotations, notify parent
    if (annotationCanvasRef.current?.hasStrokes()) {
      const dataURL = annotationCanvasRef.current.toDataURL();
      console.log('[HTMLSection] Annotation done, strokes:', strokeCount);
      onAnnotationSave?.(dataURL);
    }
  }, [strokeCount, onAnnotationSave]);

  // Save annotated screenshot using html2canvas
  const handleSaveScreenshot = useCallback(async () => {
    if (!wrapperRef.current || !checkpointId) {
      console.error('[HTMLSection] Cannot save screenshot: missing wrapper ref or checkpoint ID');
      return;
    }

    setIsSavingScreenshot(true);

    try {
      console.log('[HTMLSection] Capturing screenshot with html2canvas...');

      // Capture the wrapper (iframe + annotation canvas)
      const canvas = await html2canvas(wrapperRef.current, {
        backgroundColor: '#1a1a1a',
        scale: 2, // Higher quality
        useCORS: true,
        allowTaint: true,
        logging: false,
        // Ignore the toolbar during capture
        ignoreElements: (element) => {
          return element.classList.contains('annotation-toolbar') ||
                 element.classList.contains('annotate-toggle-btn');
        }
      });

      const dataURL = canvas.toDataURL('image/png');
      console.log('[HTMLSection] Screenshot captured, size:', dataURL.length);

      // Send to backend
      const response = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/annotated-screenshot`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ image_data: dataURL }),
      });

      if (!response.ok) {
        throw new Error(`Failed to save screenshot: ${response.status}`);
      }

      const result = await response.json();
      console.log('[HTMLSection] Screenshot saved:', result);

      setSavedScreenshotUrl(result.url);

      // Hide the screenshot checkbox in the iframe and show annotation note
      hideScreenshotCheckboxInIframe(result.url);

      // Notify parent if callback provided
      onAnnotationSave?.(result.url, result);

    } catch (err) {
      console.error('[HTMLSection] Screenshot capture failed:', err);
      alert(`Failed to save screenshot: ${err.message}`);
    } finally {
      setIsSavingScreenshot(false);
    }
  }, [checkpointId, onAnnotationSave]);

  const toggleAnnotationMode = useCallback(() => {
    setAnnotationMode(prev => !prev);
  }, []);

  // Hide the screenshot checkbox in iframe and replace with annotation note
  const hideScreenshotCheckboxInIframe = useCallback((screenshotUrl) => {
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentDocument) return;

    try {
      const iframeDoc = iframe.contentDocument;

      // Find the screenshot checkbox by name
      const checkbox = iframeDoc.querySelector('input[name="response[include_screenshot]"]');
      if (checkbox) {
        // Find the parent label
        const label = checkbox.closest('label');
        if (label) {
          // Hide the checkbox label
          label.style.display = 'none';

          // Create and insert annotation note
          const note = iframeDoc.createElement('div');
          note.className = 'annotation-included-note';
          note.innerHTML = `
            <span style="color: #10b981; font-size: 0.875rem; display: flex; align-items: center; gap: 6px;">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
              </svg>
              Annotated screenshot will be included
            </span>
          `;
          label.parentNode.insertBefore(note, label);

          console.log('[HTMLSection] Replaced screenshot checkbox with annotation note');
        }
      }

      // Also add a hidden input to ensure the response knows annotation is included
      const existingHidden = iframeDoc.querySelector('input[name="response[has_annotation]"]');
      if (!existingHidden) {
        const form = iframeDoc.querySelector('form');
        if (form) {
          const hiddenInput = iframeDoc.createElement('input');
          hiddenInput.type = 'hidden';
          hiddenInput.name = 'response[has_annotation]';
          hiddenInput.value = 'true';
          form.appendChild(hiddenInput);
        }
      }
    } catch (err) {
      console.warn('[HTMLSection] Could not modify iframe for annotation note:', err);
    }
  }, []);

  useEffect(() => {
    // Security warning in development
    if (process.env.NODE_ENV === 'development') {
      console.warn(
        '[Windlass HTMX] Rendering unsanitized HTML in iframe. ' +
        'This is a security risk and should only be used in trusted development environments.'
      );
    }

    const iframe = iframeRef.current;
    if (!iframe || !spec.content) return;

    // Check if HTMX is loaded in parent
    if (!window.htmx) {
      setError('HTMX library not loaded in parent window. Check index.html script tags.');
      return;
    }

    try {
      console.log('[HTMLSection] checkpointId:', checkpointId);
      console.log('[HTMLSection] sessionId:', sessionId);
      console.log('[HTMLSection] spec.content (first 200 chars):', spec.content?.substring(0, 200));

      // Process template variables
      const processedHTML = processTemplateVariables(spec.content, {
        checkpoint_id: checkpointId,
        session_id: sessionId,
        phase_name: spec.phase_name || '',
        cascade_id: spec.cascade_id || ''
      });

      console.log('[HTMLSection] processedHTML (first 200 chars):', processedHTML.substring(0, 200));

      // Build iframe document with embedded base theme
      const iframeDoc = buildIframeDocument(processedHTML, checkpointId, sessionId);

      // Set iframe content
      iframe.srcdoc = iframeDoc;

      // Wait for iframe to load, then set up resize and header injection
      const handleLoad = () => {
        const iframeWindow = iframe.contentWindow;
        const iframeDocument = iframe.contentDocument;

        if (!iframeWindow || !iframeDocument) {
          setError('Failed to access iframe window');
          return;
        }

        // BRANCHING: Intercept form submissions for saved checkpoints
        if (isSavedCheckpoint && onBranchSubmit) {
          console.log('[HTMLSection] Setting up branch interception for saved checkpoint');

          iframeDocument.addEventListener('submit', (e) => {
            const form = e.target;

            // Check if this form has hx-post (HTMX form)
            if (form.hasAttribute('hx-post')) {
              console.log('[HTMLSection] BRANCH INTERCEPT: Form submit detected on saved checkpoint');
              e.preventDefault();
              e.stopPropagation();

              // Extract form data
              const formData = new FormData(form);
              const response = {};

              for (let [key, value] of formData.entries()) {
                // Parse response[field] or response[field} (handle LLM typos with curly braces)
                const match = key.match(/response\[(.+?)[\]\}]/);  // Match ] or }
                if (match) {
                  response[match[1]] = value;
                } else {
                  response[key] = value;
                }
              }

              console.log('[HTMLSection] Extracted response for branch:', response);
              console.log('[HTMLSection] Raw form keys:', Array.from(formData.keys()));

              // Call branch handler
              onBranchSubmit(response);

              // Show visual feedback
              form.innerHTML = '<div style="background: rgba(167, 139, 250, 0.2); border: 2px solid #a78bfa; padding: 20px; border-radius: 8px; text-align: center; color: #a78bfa; font-weight: 600;"><div style="font-size: 2rem; margin-bottom: 8px;">🌿</div>Creating branch...</div>';

              return false;
            }
          }, true); // Use capture to intercept before HTMX
        }

        // HTMX is now loaded via script tag in iframe, no manual init needed
        // Just wait a moment for it to auto-initialize
        setTimeout(() => {
          console.log('[Windlass HTMX] iframe HTMX loaded:', !!iframeWindow.htmx);
        }, 100);

        // Auto-resize iframe to full content height (no scrollbars!)
        let lastHeight = 0;
        let resizeCount = 0;
        const MAX_RESIZES = 30; // Stop after 30 resize attempts to prevent infinite loops

        let resizeTimeout;
        const resizeIframe = () => {
          clearTimeout(resizeTimeout);
          resizeTimeout = setTimeout(() => {
            try {
              // Get the full scrollHeight including all nested content
              const contentHeight = iframeDocument.body.scrollHeight;
              // Add generous padding to ensure no scrollbars (40px buffer)
              const newHeight = Math.max(contentHeight + 40, 100);

              // Only update if height changed by more than 5px (avoid tiny fluctuations)
              const heightDelta = Math.abs(newHeight - lastHeight);
              if (heightDelta > 5) {
                resizeCount++;

                // Stop resizing if we've hit the limit (prevents infinite loops)
                if (resizeCount > MAX_RESIZES) {
                  console.warn('[HTMX iframe] Stopped auto-resize after', MAX_RESIZES, 'attempts');
                  if (resizeObserver) resizeObserver.disconnect();
                  return;
                }

                setIframeHeight(`${newHeight}px`);
                lastHeight = newHeight;
                //console.log('[HTMX iframe] Resized to', newHeight, 'px (attempt', resizeCount, ')');
              }
            } catch (err) {
              console.warn('[Windlass HTMX] Could not resize iframe:', err);
            }
          }, 50); // Debounce by 50ms
        };

        // Initial resize
        resizeIframe();

        // Resize after HTMX swaps (debounced)
        iframeDocument.addEventListener('htmx:afterSwap', () => {
          setTimeout(resizeIframe, 100); // Delay to let DOM settle
        });

        // Resize on content changes (debounced via ResizeObserver)
        let resizeObserver;
        resizeObserver = new ResizeObserver((entries) => {
          // Throttle ResizeObserver calls
          requestAnimationFrame(() => {
            if (resizeCount < MAX_RESIZES) {
              resizeIframe();
            }
          });
        });
        resizeObserver.observe(iframeDocument.body);

        // Inject checkpoint headers on HTMX requests
        iframeDocument.addEventListener('htmx:configRequest', (e) => {
          e.detail.headers['X-Checkpoint-Id'] = checkpointId;
          e.detail.headers['X-Session-Id'] = sessionId;
          console.log('[Windlass HTMX iframe] Request:', e.detail.path);
        });

        // Handle errors
        iframeDocument.addEventListener('htmx:responseError', (e) => {
          console.error('[Windlass HTMX iframe] Request error:', e.detail);
          const status = e.detail.xhr?.status || 'unknown';
          const statusText = e.detail.xhr?.statusText || 'error';
          setError(`HTMX request failed: ${status} ${statusText}`);
        });

        // Store cleanup functions
        iframe._windlassCleanup = () => {
          resizeObserver.disconnect();
        };
      };

      iframe.addEventListener('load', handleLoad);

      // Cleanup
      return () => {
        iframe.removeEventListener('load', handleLoad);
        if (iframe._windlassCleanup) {
          iframe._windlassCleanup();
        }
      };
    } catch (err) {
      console.error('[Windlass HTMX] iframe setup error:', err);
      setError(`Failed to render HTML: ${err.message}`);
    }
  }, [spec.content, checkpointId, sessionId, spec.phase_name, spec.cascade_id]);

  if (error) {
    return (
      <div className="html-section-error">
        <h3>HTML Rendering Error</h3>
        <p>{error}</p>
        <details>
          <summary>Show HTML Source</summary>
          <pre>{spec.content}</pre>
        </details>
      </div>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className={`html-section-wrapper ${annotationMode ? 'annotating' : ''} ${savedScreenshotUrl ? 'has-saved-screenshot' : ''}`}
    >
      {process.env.NODE_ENV === 'development_ZOO' && ( // commented out for now. ugly.
        <div className="html-section-dev-warning">
          ⚠️ Development Mode: Unsanitized HTML in iframe. Never use in production without DOMPurify.
        </div>
      )}

      {/* Annotate toggle button - visible when not annotating */}
      {!annotationMode && (
        <button
          className={`annotate-toggle-btn ${strokeCount > 0 ? 'has-annotations' : ''} ${savedScreenshotUrl ? 'screenshot-saved' : ''}`}
          onClick={toggleAnnotationMode}
          title={savedScreenshotUrl ? "Screenshot saved! Click to annotate more" : "Draw annotations on this content"}
        >
          <Icon icon={savedScreenshotUrl ? "mdi:check-circle" : "mdi:draw"} width="16" />
          <span>{savedScreenshotUrl ? "Saved" : "Annotate"}</span>
          {strokeCount > 0 && !savedScreenshotUrl && (
            <span className="annotation-badge">{strokeCount}</span>
          )}
        </button>
      )}

      {/* Annotation toolbar - visible when annotating */}
      {annotationMode && (
        <AnnotationToolbar
          brushColor={brushColor}
          brushSize={brushSize}
          onColorChange={setBrushColor}
          onSizeChange={setBrushSize}
          onUndo={handleUndo}
          onClear={handleClear}
          onDone={handleAnnotationDone}
          onSaveScreenshot={handleSaveScreenshot}
          canUndo={strokeCount > 0}
          strokeCount={strokeCount}
          isSaving={isSavingScreenshot}
          hasSavedScreenshot={!!savedScreenshotUrl}
        />
      )}

      {/* Annotation canvas - always rendered but only active when annotationMode is true */}
      <AnnotationCanvas
        ref={annotationCanvasRef}
        targetRef={iframeRef}
        enabled={annotationMode}
        brushColor={brushColor}
        brushSize={brushSize}
        onStrokesChange={handleStrokesChange}
      />

      <iframe
        ref={iframeRef}
        className="html-section-iframe"
        style={{
          height: iframeHeight,
          width: '100%',
          border: 'none',
          display: 'block',
          backgroundColor: 'transparent'
        }}
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
        title="HTMX Checkpoint UI"
      />
    </div>
  );
}

/**
 * Build complete iframe HTML document with base theme CSS and HTMX
 */
function buildIframeDocument(bodyHTML, checkpointId, sessionId) {
  // Inline the lite theme CSS
  const baseCSS = `
/* Windlass Lite Theme - Minimal base styles for HTMX iframes */
:root {
  --bg-darkest: #0a0a0a;
  --bg-dark: #121212;
  --bg-card: #1a1a1a;
  --border-default: #333;
  --border-subtle: #222;
  --text-primary: #e5e7eb;
  --text-secondary: #9ca3af;
  --text-muted: #6b7280;
  --accent-purple: #a78bfa;
  --accent-blue: #4A9EDD;
  --accent-green: #10b981;
  --accent-red: #ef4444;
}

body {
  margin: 0;
  padding: 16px;
  font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  background: transparent;
  -webkit-font-smoothing: antialiased;
}

* { box-sizing: border-box; }

h1, h2, h3, h4, h5, h6 {
  color: var(--accent-purple);
  font-weight: 600;
  margin: 0 0 0.75rem 0;
}

h1 { font-size: 1.875rem; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.25rem; }

p { margin: 0 0 0.75rem 0; }

input, select, textarea {
  background: var(--bg-darkest);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: inherit;
  font-size: 0.875rem;
}

input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--accent-purple);
  box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.1);
}

button {
  background: var(--accent-purple);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.875rem;
}

button:hover:not(:disabled) { filter: brightness(1.1); }
button:disabled { opacity: 0.5; cursor: not-allowed; }

code, pre {
  font-family: 'IBM Plex Mono', monospace;
  background: var(--bg-darkest);
  border-radius: 4px;
}

code { padding: 2px 6px; font-size: 0.875em; }
pre { padding: 1rem; overflow-x: auto; border: 1px solid var(--border-default); }
  `;

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>${baseCSS}</style>

  <!-- Visualization libraries for LLM-generated charts and tables -->
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>

  <!-- AG Grid for data tables -->
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community/styles/ag-grid.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community/styles/ag-theme-quartz.css">

  <!-- HTMX loaded directly in iframe context -->
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <script src="https://unpkg.com/htmx.org@1.9.10/dist/ext/json-enc.js"></script>
  <script>
    //console.log('[HTMX iframe INIT] htmx loaded:', typeof htmx !== 'undefined');
    //console.log('[HTMX iframe INIT] htmx.ext:', typeof htmx !== 'undefined' ? htmx.ext : 'N/A');
    //console.log('[HTMX iframe INIT] Plotly loaded:', typeof Plotly !== 'undefined');
    //console.log('[HTMX iframe INIT] Vega loaded:', typeof vega !== 'undefined');
    //console.log('[HTMX iframe INIT] vegaEmbed loaded:', typeof vegaEmbed !== 'undefined');
    //console.log('[HTMX iframe INIT] AG Grid loaded:', typeof agGrid !== 'undefined');

    // Wait for HTMX to fully initialize
    window.addEventListener('DOMContentLoaded', () => {
      //console.log('[HTMX iframe] DOMContentLoaded, htmx available:', typeof htmx !== 'undefined');
      //console.log('[HTMX iframe] Plotly:', typeof Plotly !== 'undefined');
      //console.log('[HTMX iframe] vegaEmbed:', typeof vegaEmbed !== 'undefined');
      //console.log('[HTMX iframe] AG Grid:', typeof agGrid !== 'undefined');

      if (typeof htmx !== 'undefined') {
        // HTMX configuration for iframe
        htmx.config.globalViewTransitions = true;
        htmx.config.defaultSwapStyle = 'innerHTML';

        // Check if json-enc extension is loaded
        //console.log('[HTMX iframe] Extensions available:', htmx.ext);
        //console.log('[HTMX iframe] json-enc extension object:', htmx.ext ? htmx.ext['json-enc'] : 'no ext object');

        // CRITICAL FIX: The json-enc extension loads but doesn't auto-activate
        // We need to manually define it using the extension API
        if (!htmx.ext || !htmx.ext['json-enc']) {
          console.warn('[HTMX iframe] json-enc not registered, attempting manual registration...');

          // Manually define json-enc extension
          htmx.defineExtension('json-enc', {
            onEvent: function(name, evt) {
              if (name === 'htmx:configRequest') {
                const xhr = evt.detail.xhr;
                const headers = evt.detail.headers;
                const elt = evt.detail.elt;

                // Check if this element has json-enc extension
                if (elt.getAttribute && elt.getAttribute('hx-ext')?.includes('json-enc')) {
                  // Convert parameters to JSON
                  headers['Content-Type'] = 'application/json';
                  // evt.detail.parameters will be serialized as JSON by HTMX
                }
              }
              return true;
            }
          });

          console.log('[HTMX iframe] Manually defined json-enc extension');
        }

        console.log('[HTMX iframe] Final check - json-enc available:', htmx.ext && htmx.ext['json-enc']);

        // WORKAROUND: Intercept form submissions and use fetch with JSON instead of HTMX
        document.addEventListener('submit', (e) => {
          const form = e.target;

          // Check if this form has hx-post and json-enc
          if (form.hasAttribute('hx-post') && form.getAttribute('hx-ext')?.includes('json-enc')) {
            console.log('[HTMX iframe] Intercepting form submit for manual JSON POST');
            e.preventDefault();
            e.stopPropagation();

            // Get the URL
            let url = form.getAttribute('hx-post');
            if (url.startsWith('/')) {
              url = 'http://localhost:5001' + url;
            }

            // Build JSON from form data
            const formData = new FormData(form);
            const params = {};

            for (let [key, value] of formData.entries()) {
              const openBracket = key.indexOf('[');
              const closeBracket = key.lastIndexOf(']') !== -1 ? key.lastIndexOf(']') : key.lastIndexOf('}');

              if (openBracket > 0 && closeBracket > openBracket) {
                const parent = key.substring(0, openBracket);
                const child = key.substring(openBracket + 1, closeBracket);

                if (!params[parent]) params[parent] = {};
                params[parent][child] = value;
              } else {
                params[key] = value;
              }
            }

            const jsonBody = JSON.stringify(params);
            console.log('[HTMX iframe] Submitting via fetch:', url);
            console.log('[HTMX iframe] JSON body:', jsonBody);

            // Get checkpoint context from body data attributes
            const checkpointId = document.body.getAttribute('data-checkpoint-id');
            const sessionId = document.body.getAttribute('data-session-id');

            console.log('[HTMX iframe] Checkpoint context - checkpointId:', checkpointId, 'sessionId:', sessionId);

            // Submit via fetch
            fetch(url, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Checkpoint-Id': checkpointId || '',
                'X-Session-Id': sessionId || ''
              },
              body: jsonBody
            })
            .then(response => {
              console.log('[HTMX iframe] fetch response:', response.status);
              return response.json();
            })
            .then(data => {
              console.log('[HTMX iframe] Response data:', data);

              // Show success message
              const swap = form.getAttribute('hx-swap') || 'outerHTML';
              if (swap === 'outerHTML') {
                form.outerHTML = '<div style="background: #10b981; color: white; padding: 16px; border-radius: 8px; text-align: center;">✓ Response submitted successfully!</div>';
              }
            })
            .catch(err => {
              console.error('[HTMX iframe] fetch error:', err);
              alert('Failed to submit: ' + err.message);
            });
          }
        }, true); // Use capture phase to intercept before HTMX

        // CRITICAL: Convert relative URLs to absolute AND handle JSON conversion
        document.addEventListener('htmx:configRequest', (e) => {
          const path = e.detail.path;
          const target = e.detail.elt;

          // If path is relative, convert to absolute pointing to backend (port 5001)
          if (path && path.startsWith('/')) {
            const absoluteURL = 'http://localhost:5001' + path;
            e.detail.path = absoluteURL;
            console.log('[HTMX iframe] Converted relative URL:', path, '→', absoluteURL);
          }

          console.log('[HTMX iframe] Sending request:', e.detail.path);
          console.log('[HTMX iframe] Raw parameters:', e.detail.parameters);
          console.log('[HTMX iframe] Content-Type:', e.detail.headers['Content-Type']);

          // WORKAROUND: json-enc doesn't work in iframes, manually handle JSON encoding
          const hasJsonEnc = target && target.getAttribute && target.getAttribute('hx-ext')?.includes('json-enc');

          if (hasJsonEnc && e.detail.headers['Content-Type'] === 'application/x-www-form-urlencoded') {
            console.warn('[HTMX iframe] json-enc not working in iframe! Manually converting...');

            // Build nested JSON from parameters object
            const params = {};
            const originalKeys = Object.keys(e.detail.parameters);
            console.log('[HTMX iframe] Original parameter keys:', originalKeys);

            for (let key in e.detail.parameters) {
              const value = e.detail.parameters[key];
              console.log('[HTMX iframe] Processing key:', JSON.stringify(key), '=', JSON.stringify(value));

              // Handle nested keys like "response[selected]" using indexOf
              // Also handle typos like "response[selected}" (curly brace instead of square)
              const openBracket = key.indexOf('[');
              let closeBracket = key.indexOf(']');

              // If no ], check for } (common LLM typo)
              if (closeBracket === -1) {
                closeBracket = key.indexOf('}');
                if (closeBracket > 0) {
                  console.warn('[HTMX iframe] ⚠️ Found curly brace } instead of ], fixing...');
                }
              }

              console.log('[HTMX iframe] Bracket positions - open:', openBracket, 'close:', closeBracket);

              if (openBracket > 0 && closeBracket > openBracket) {
                const parent = key.substring(0, openBracket);
                const child = key.substring(openBracket + 1, closeBracket);
                console.log('[HTMX iframe] ✓ Matched nested key - parent:', parent, 'child:', child);

                if (!params[parent]) params[parent] = {};
                params[parent][child] = value;
              } else {
                console.log('[HTMX iframe] ✗ No brackets found, keeping key as-is');
                params[key] = value;
              }
            }

            console.log('[HTMX iframe] Converted params to:', JSON.stringify(params, null, 2));

            // Tell HTMX to send as JSON
            e.detail.headers['Content-Type'] = 'application/json';

            // Store the JSON body on the element so we can use it in xhr:loadstart
            e.detail.elt._jsonBody = JSON.stringify(params);

            console.log('[HTMX iframe] Stored JSON body for XHR override:', e.detail.elt._jsonBody);
          }
        });

        // Intercept XHR before send to override the body with JSON
        document.addEventListener('htmx:xhr:loadstart', (e) => {
          const elt = e.detail.elt;
          const xhr = e.detail.xhr;

          console.log('[HTMX iframe] xhr:loadstart event, xhr:', xhr);
          console.log('[HTMX iframe] Has _jsonBody:', !!elt._jsonBody);

          // If we have a JSON body stored, override the send method
          if (elt && elt._jsonBody && xhr && xhr.send) {
            console.log('[HTMX iframe] XHR loadstart - will override send with JSON body');

            const jsonBody = elt._jsonBody;
            const originalSend = xhr.send;

            // Override send to use our JSON body
            xhr.send = function(body) {
              console.log('[HTMX iframe] XHR.send called - replacing body');
              console.log('[HTMX iframe] HTMX wanted to send (form-encoded):', body);
              console.log('[HTMX iframe] Sending JSON instead:', jsonBody);
              originalSend.call(this, jsonBody);
            };

            console.log('[HTMX iframe] XHR.send method overridden');
          }
        });

        document.addEventListener('htmx:afterRequest', (e) => {
          console.log('[HTMX iframe] Got response:', e.detail.successful, e.detail.xhr.status);
          if (e.detail.xhr.responseText) {
            console.log('[HTMX iframe] Response body:', e.detail.xhr.responseText.substring(0, 200));
          }
        });

        document.addEventListener('htmx:responseError', (e) => {
          console.error('[HTMX iframe] Request error:', e.detail.xhr.status, e.detail.xhr.statusText);
          console.error('[HTMX iframe] Response:', e.detail.xhr.responseText);
        });

        // Log when HTMX processes elements
        document.addEventListener('htmx:load', (e) => {
          console.log('[HTMX iframe] Processed element:', e.target.tagName, e.target.getAttribute('hx-post'));
        });
      } else {
        console.error('[HTMX iframe] HTMX not loaded!');
      }

      // Test button clicks
      document.addEventListener('click', (e) => {
        console.log('[HTMX iframe] Click detected on:', e.target.tagName, e.target.textContent);
      });
    });
  </script>
</head>
<body data-checkpoint-id="${checkpointId}" data-session-id="${sessionId}">
${bodyHTML}
</body>
</html>`;
}

/**
 * Replace template variables in HTML string
 * Supports: {{ checkpoint_id }}, {{ session_id }}, {{ phase_name }}, {{ cascade_id }}
 */
function processTemplateVariables(html, context) {
  return html.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, key) => {
    const value = context[key];
    if (value !== undefined) {
      return value;
    }
    // Keep unmatched placeholders and log warning
    console.warn(`[Windlass HTMX] Unknown template variable: ${key}`);
    return match;
  });
}

export default HTMLSection;
