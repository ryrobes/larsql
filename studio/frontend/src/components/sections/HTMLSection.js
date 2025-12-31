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
 * - Base RVBBIT theme CSS (colors, fonts) inherited
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
      const response = await fetch(`http://localhost:5050/api/checkpoints/${checkpointId}/annotated-screenshot`, {
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
        '[RVBBIT HTMX] Rendering unsanitized HTML in iframe. ' +
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
      console.log('[HTMLSection] ===== NEW RENDER =====');
      console.log('[HTMLSection] checkpointId:', checkpointId);
      console.log('[HTMLSection] sessionId:', sessionId);
      console.log('[HTMLSection] cellName:', spec.cell_name);
      console.log('[HTMLSection] cascadeId:', spec.cascade_id);
      console.log('[HTMLSection] spec.content (first 200 chars):', spec.content?.substring(0, 200));

      // Process template variables
      const processedHTML = processTemplateVariables(spec.content, {
        checkpoint_id: checkpointId,
        session_id: sessionId,
        cell_name: spec.cell_name || '',
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
          console.log('[RVBBIT HTMX] iframe HTMX loaded:', !!iframeWindow.htmx);
        }, 100);

        // Auto-resize iframe to content height
        // FIXED: Prevent "creeping height" bug by:
        // 1. Measuring actual content bounds (not scrollHeight which includes our padding)
        // 2. Using a "skip" flag to ignore resize events triggered by our own height changes
        // 3. Capping max height and reducing resize attempts
        let lastContentHeight = 0;
        let resizeCount = 0;
        let skipNextResize = false; // Flag to break feedback loop
        const MAX_RESIZES = 8;
        const PADDING = 16;

        let resizeTimeout;
        const resizeIframe = () => {
          // Skip if this resize was triggered by our own height change
          if (skipNextResize) {
            skipNextResize = false;
            return;
          }

          clearTimeout(resizeTimeout);
          resizeTimeout = setTimeout(() => {
            try {
              const body = iframeDocument.body;

              // Use offsetHeight for more stable measurement
              // offsetHeight = content + padding + border (no scroll issues)
              const contentHeight = body.offsetHeight;

              // Only resize if content height changed significantly (15px threshold)
              const contentDelta = Math.abs(contentHeight - lastContentHeight);
              if (contentDelta < 15) {
                return; // No significant change
              }

              resizeCount++;
              if (resizeCount > MAX_RESIZES) {
                console.warn('[HTMX iframe] Max resize attempts reached');
                if (resizeObserver) resizeObserver.disconnect();
                return;
              }

              // Calculate target, capped at reasonable max
              const targetHeight = Math.min(Math.max(contentHeight + PADDING, 100), 1500);

              // Set flag to skip the resize event this will trigger
              skipNextResize = true;
              lastContentHeight = contentHeight;
              setIframeHeight(`${targetHeight}px`);
            } catch (err) {
              console.warn('[RVBBIT HTMX] Could not resize iframe:', err);
            }
          }, 150); // Longer debounce for stability
        };

        // Initial resize
        resizeIframe();

        // Resize after HTMX swaps (debounced)
        iframeDocument.addEventListener('htmx:afterSwap', () => {
          setTimeout(resizeIframe, 100); // Delay to let DOM settle
        });

        // Resize on content changes (throttled ResizeObserver)
        let resizeObserver;
        let lastObserverCall = 0;
        const OBSERVER_THROTTLE_MS = 300; // Throttle to max 3 calls/second

        resizeObserver = new ResizeObserver((entries) => {
          const now = Date.now();
          if (now - lastObserverCall < OBSERVER_THROTTLE_MS) {
            return; // Throttled
          }
          lastObserverCall = now;

          // Only trigger if we haven't hit the limit
          if (resizeCount < MAX_RESIZES && !skipNextResize) {
            resizeIframe();
          }
        });
        resizeObserver.observe(iframeDocument.body);

        // Inject checkpoint headers on HTMX requests
        iframeDocument.addEventListener('htmx:configRequest', (e) => {
          e.detail.headers['X-Checkpoint-Id'] = checkpointId;
          e.detail.headers['X-Session-Id'] = sessionId;
          console.log('[RVBBIT HTMX iframe] Request:', e.detail.path);
        });

        // Handle errors
        iframeDocument.addEventListener('htmx:responseError', (e) => {
          console.error('[RVBBIT HTMX iframe] Request error:', e.detail);
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
      console.error('[RVBBIT HTMX] iframe setup error:', err);
      setError(`Failed to render HTML: ${err.message}`);
    }
  }, [spec.content, checkpointId, sessionId, spec.cell_name, spec.cascade_id]);

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
  // RVBBIT Basecoat Theme - Complete styling for all components
  // Matches the AppShell design system with cyberpunk aesthetic
  const baseCSS = `
/**
 * RVBBIT Basecoat Theme - AppShell Design System
 * Pure black backgrounds, neon cyan/purple accents, glass morphism
 */

/* =============================================================================
   CSS VARIABLES - Design Tokens
   ============================================================================= */

:root {
  /* Backgrounds */
  --color-bg-primary: #000000;
  --color-bg-secondary: #0a0a0a;
  --color-bg-tertiary: #0f0e21;
  --color-bg-card: #000000;
  --color-bg-input: #000000;

  /* Borders (Cyan-based with varying opacity) */
  --color-border-dim: rgba(0, 229, 255, 0.15);
  --color-border-medium: rgba(0, 229, 255, 0.25);
  --color-border-bright: rgba(0, 229, 255, 0.4);

  /* Text Colors (Slate-based grayscale) */
  --color-text-primary: #f1f5f9;
  --color-text-secondary: #cbd5e1;
  --color-text-muted: #94a3b8;
  --color-text-dim: #64748b;

  /* Accent Colors (Neon cyberpunk palette) */
  --color-accent-cyan: #00e5ff;
  --color-accent-purple: #a78bfa;
  --color-accent-pink: #ff006e;
  --color-accent-green: #34d399;
  --color-accent-yellow: #fbbf24;
  --color-accent-teal: #14b8a6;
  --color-accent-red: #f87171;
  --color-accent-blue: #60a5fa;

  /* Semantic Colors */
  --color-success: #34d399;
  --color-error: #ff006e;
  --color-warning: #fbbf24;
  --color-info: #60a5fa;

  /* shadcn/Basecoat HSL Variables */
  --background: 0 0% 0%;
  --foreground: 210 40% 96%;
  --card: 240 6% 4%;
  --card-foreground: 210 40% 96%;
  --primary: 186 100% 50%;
  --primary-foreground: 0 0% 0%;
  --secondary: 263 70% 77%;
  --secondary-foreground: 0 0% 0%;
  --muted: 215 16% 47%;
  --muted-foreground: 215 20% 65%;
  --destructive: 339 100% 50%;
  --destructive-foreground: 0 0% 100%;
  --border: 186 100% 50%;
  --input: 186 100% 50%;
  --ring: 186 100% 50%;
  --radius: 6px;

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;

  /* Typography */
  --font-sans: 'Quicksand', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'Google Sans Mono', 'IBM Plex Mono', monospace;
  --font-size-xs: 10px;
  --font-size-sm: 11px;
  --font-size-base: 12px;
  --font-size-md: 13px;
  --font-size-lg: 14px;

  /* Shadows & Glows */
  --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.5);
  --shadow-glow-cyan: 0 0 12px rgba(0, 229, 255, 0.4);
  --shadow-glow-purple: 0 0 12px rgba(167, 139, 250, 0.4);
  --shadow-glow-green: 0 0 12px rgba(52, 211, 153, 0.4);
  --shadow-glow-pink: 0 0 12px rgba(255, 0, 110, 0.4);

  /* Transitions */
  --transition-fast: 0.1s ease;
  --transition-normal: 0.15s ease;
}

/* =============================================================================
   BASE STYLES
   ============================================================================= */

body {
  margin: 0;
  padding: var(--space-md);
  font-family: var(--font-sans);
  font-size: var(--font-size-base);
  line-height: 1.5;
  color: var(--color-text-secondary);
  background: var(--color-bg-primary);
  -webkit-font-smoothing: antialiased;
}

*, *::before, *::after { box-sizing: border-box; }

/* =============================================================================
   BUTTONS - .btn variants
   ============================================================================= */

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  font-family: var(--font-sans);
  font-size: var(--font-size-sm);
  font-weight: 600;
  line-height: 1;
  text-decoration: none;
  border-radius: var(--radius);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-normal);
  white-space: nowrap;
  min-height: 32px;
}

.btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--color-bg-primary), 0 0 0 4px var(--color-accent-cyan);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.btn-primary {
  background: var(--color-accent-cyan);
  color: #000000;
  border-color: var(--color-accent-cyan);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-accent-teal);
  border-color: var(--color-accent-teal);
  box-shadow: var(--shadow-glow-cyan);
  transform: translateY(-1px);
}

.btn-secondary {
  background: rgba(167, 139, 250, 0.15);
  color: var(--color-accent-purple);
  border-color: rgba(167, 139, 250, 0.3);
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(167, 139, 250, 0.25);
  border-color: var(--color-accent-purple);
  box-shadow: var(--shadow-glow-purple);
}

.btn-destructive {
  background: rgba(255, 0, 110, 0.15);
  color: var(--color-accent-pink);
  border-color: rgba(255, 0, 110, 0.3);
}

.btn-destructive:hover:not(:disabled) {
  background: rgba(255, 0, 110, 0.25);
  border-color: var(--color-accent-pink);
  box-shadow: var(--shadow-glow-pink);
}

.btn-outline {
  background: transparent;
  color: var(--color-text-secondary);
  border-color: var(--color-border-dim);
}

.btn-outline:hover:not(:disabled) {
  color: var(--color-accent-cyan);
  border-color: var(--color-accent-cyan);
  background: rgba(0, 229, 255, 0.08);
}

.btn-ghost {
  background: transparent;
  color: var(--color-text-muted);
  border-color: transparent;
}

.btn-ghost:hover:not(:disabled) {
  color: var(--color-accent-cyan);
  background: rgba(0, 229, 255, 0.08);
}

.btn-link {
  background: transparent;
  color: var(--color-accent-cyan);
  border-color: transparent;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.btn-sm { padding: 4px 8px; font-size: var(--font-size-xs); min-height: 28px; }
.btn-lg { padding: 10px 16px; font-size: var(--font-size-md); min-height: 40px; }
.btn-icon { padding: 6px; aspect-ratio: 1; }

/* =============================================================================
   CARDS - .card variants
   ============================================================================= */

.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-dim);
  border-radius: calc(var(--radius) + 2px);
  overflow: hidden;
}

.card-header {
  padding: var(--space-md) var(--space-lg);
  border-bottom: 1px solid var(--color-border-dim);
}

.card-title {
  margin: 0;
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-text-primary);
}

.card-description {
  margin: 4px 0 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.card-content { padding: var(--space-lg); }

.card-footer {
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border-dim);
  background: rgba(0, 229, 255, 0.02);
}

.card-hover:hover {
  border-color: var(--color-border-bright);
  box-shadow: var(--shadow-md), var(--shadow-glow-cyan);
  transform: translateY(-2px);
  cursor: pointer;
}

/* =============================================================================
   FORM INPUTS - .input, .textarea, .select, .checkbox, .radio, .label
   ============================================================================= */

.input, .textarea, .select {
  width: 100%;
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  background: var(--color-bg-input);
  border: 1px solid var(--color-border-dim);
  border-radius: var(--radius);
  transition: all var(--transition-normal);
}

.input::placeholder, .textarea::placeholder { color: var(--color-text-dim); }

.input:hover, .textarea:hover, .select:hover { border-color: var(--color-border-medium); }

.input:focus, .textarea:focus, .select:focus {
  outline: none;
  border-color: var(--color-accent-cyan);
  box-shadow: 0 0 0 3px rgba(0, 229, 255, 0.15);
}

.textarea { resize: vertical; min-height: 80px; line-height: 1.5; }

.select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2300e5ff' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

.checkbox, .radio {
  width: 16px;
  height: 16px;
  accent-color: var(--color-accent-cyan);
  cursor: pointer;
}

.checkbox:focus, .radio:focus { box-shadow: 0 0 0 3px rgba(0, 229, 255, 0.2); }

.label {
  display: block;
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.input-sm { padding: 4px 8px; font-size: var(--font-size-xs); }
.input-lg { padding: 12px 16px; font-size: var(--font-size-md); }

/* =============================================================================
   BADGES - .badge variants
   ============================================================================= */

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  font-weight: 600;
  line-height: 1;
  border-radius: 9999px;
  white-space: nowrap;
  background: rgba(0, 229, 255, 0.15);
  color: var(--color-accent-cyan);
  border: 1px solid rgba(0, 229, 255, 0.3);
}

.badge-secondary {
  background: rgba(167, 139, 250, 0.15);
  color: var(--color-accent-purple);
  border-color: rgba(167, 139, 250, 0.3);
}

.badge-destructive {
  background: rgba(255, 0, 110, 0.15);
  color: var(--color-accent-pink);
  border-color: rgba(255, 0, 110, 0.3);
}

.badge-success {
  background: rgba(52, 211, 153, 0.15);
  color: var(--color-accent-green);
  border-color: rgba(52, 211, 153, 0.3);
}

.badge-warning {
  background: rgba(251, 191, 36, 0.15);
  color: var(--color-accent-yellow);
  border-color: rgba(251, 191, 36, 0.3);
}

.badge-outline {
  background: transparent;
  color: var(--color-text-muted);
  border-color: var(--color-border-dim);
}

/* =============================================================================
   ALERTS - .alert variants
   ============================================================================= */

.alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-md);
  border-radius: var(--radius);
  border: 1px solid var(--color-border-dim);
  background: rgba(0, 229, 255, 0.05);
}

.alert p { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }

.alert-destructive {
  background: rgba(255, 0, 110, 0.08);
  border-color: rgba(255, 0, 110, 0.3);
}
.alert-destructive p { color: var(--color-accent-pink); }

.alert-success {
  background: rgba(52, 211, 153, 0.08);
  border-color: rgba(52, 211, 153, 0.3);
}
.alert-success p { color: var(--color-accent-green); }

.alert-warning {
  background: rgba(251, 191, 36, 0.08);
  border-color: rgba(251, 191, 36, 0.3);
}
.alert-warning p { color: var(--color-accent-yellow); }

/* =============================================================================
   TABLES - .table
   ============================================================================= */

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.table th, .table td {
  padding: var(--space-sm) var(--space-md);
  text-align: left;
  border-bottom: 1px solid var(--color-border-dim);
}

.table th {
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: rgba(0, 229, 255, 0.03);
}

.table td { color: var(--color-text-secondary); }
.table tbody tr:hover { background: rgba(0, 229, 255, 0.05); }
.table tbody tr:last-child td { border-bottom: none; }

/* =============================================================================
   TABS - data-bc-tabs
   ============================================================================= */

[data-bc-tabs] { display: flex; flex-direction: column; }

.tabs-list, [data-bc-tabs] > div:first-child {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--color-border-dim);
  margin-bottom: var(--space-md);
}

.tab, [data-bc-tab] {
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all var(--transition-normal);
  margin-bottom: -1px;
}

.tab:hover, [data-bc-tab]:hover { color: var(--color-text-primary); }

.tab.active, .tab[aria-selected="true"], [data-bc-tab].active, [data-bc-tab][aria-selected="true"] {
  color: var(--color-accent-cyan);
  border-bottom-color: var(--color-accent-cyan);
}

[data-bc-tab-panel] { padding: var(--space-md) 0; }

/* =============================================================================
   ACCORDION - data-bc-accordion
   ============================================================================= */

[data-bc-accordion] {
  border: 1px solid var(--color-border-dim);
  border-radius: var(--radius);
  overflow: hidden;
}

.accordion-item, [data-bc-accordion-item] { border-bottom: 1px solid var(--color-border-dim); }
.accordion-item:last-child, [data-bc-accordion-item]:last-child { border-bottom: none; }

.accordion-trigger, [data-bc-accordion-trigger] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-md);
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-normal);
}

.accordion-trigger:hover, [data-bc-accordion-trigger]:hover { background: rgba(0, 229, 255, 0.05); }

.accordion-content, [data-bc-accordion-content] {
  padding: 0 var(--space-md) var(--space-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

/* =============================================================================
   DROPDOWN - data-bc-dropdown
   ============================================================================= */

[data-bc-dropdown] { position: relative; display: inline-block; }

.dropdown-content, [data-bc-dropdown-content] {
  position: absolute;
  top: 100%;
  left: 0;
  min-width: 180px;
  margin-top: 4px;
  padding: 4px;
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border-dim);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  z-index: 100;
}

.dropdown-item, [data-bc-dropdown-content] a, [data-bc-dropdown-content] button {
  display: block;
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.dropdown-item:hover, [data-bc-dropdown-content] a:hover, [data-bc-dropdown-content] button:hover {
  background: rgba(0, 229, 255, 0.1);
  color: var(--color-accent-cyan);
}

/* =============================================================================
   DIALOG/MODAL
   ============================================================================= */

.dialog, dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  max-width: 90vw;
  max-height: 85vh;
  padding: 0;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border-medium);
  border-radius: calc(var(--radius) + 4px);
  box-shadow: var(--shadow-lg), var(--shadow-glow-cyan);
  overflow: hidden;
}

dialog::backdrop { background: rgba(0, 0, 0, 0.85); backdrop-filter: blur(8px); }

.dialog-header { padding: var(--space-lg); border-bottom: 1px solid var(--color-border-dim); }
.dialog-title { margin: 0; font-size: var(--font-size-lg); font-weight: 600; color: var(--color-text-primary); }
.dialog-content { padding: var(--space-lg); overflow-y: auto; }
.dialog-footer { padding: var(--space-md) var(--space-lg); border-top: 1px solid var(--color-border-dim); display: flex; justify-content: flex-end; gap: var(--space-sm); }

/* =============================================================================
   PROGRESS, SPINNER, SEPARATOR, SKELETON
   ============================================================================= */

.progress { height: 8px; background: rgba(0, 229, 255, 0.1); border-radius: 9999px; overflow: hidden; }
.progress-bar, .progress > div { height: 100%; background: linear-gradient(90deg, var(--color-accent-cyan), var(--color-accent-purple)); border-radius: 9999px; transition: width 0.3s ease; }

.spinner { width: 20px; height: 20px; border: 2px solid var(--color-border-dim); border-top-color: var(--color-accent-cyan); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.separator, hr { border: none; height: 1px; background: var(--color-border-dim); margin: var(--space-md) 0; }

.skeleton { background: linear-gradient(90deg, rgba(0, 229, 255, 0.05) 0%, rgba(0, 229, 255, 0.1) 50%, rgba(0, 229, 255, 0.05) 100%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: var(--radius); }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* =============================================================================
   AVATAR, TOOLTIP, SWITCH
   ============================================================================= */

.avatar { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; background: rgba(167, 139, 250, 0.2); color: var(--color-accent-purple); font-size: var(--font-size-sm); font-weight: 600; overflow: hidden; }
.avatar img { width: 100%; height: 100%; object-fit: cover; }

.tooltip { position: absolute; padding: 4px 8px; font-size: var(--font-size-xs); color: var(--color-text-primary); background: var(--color-bg-tertiary); border: 1px solid var(--color-border-dim); border-radius: var(--radius); box-shadow: var(--shadow-md); z-index: 1000; pointer-events: none; }

.switch { position: relative; display: inline-block; width: 36px; height: 20px; }
.switch input { opacity: 0; width: 0; height: 0; }
.switch-slider { position: absolute; cursor: pointer; inset: 0; background: var(--color-border-dim); border-radius: 20px; transition: var(--transition-normal); }
.switch-slider::before { content: ""; position: absolute; height: 16px; width: 16px; left: 2px; bottom: 2px; background: var(--color-text-muted); border-radius: 50%; transition: var(--transition-normal); }
.switch input:checked + .switch-slider { background: var(--color-accent-cyan); }
.switch input:checked + .switch-slider::before { transform: translateX(16px); background: #000; }

/* =============================================================================
   SCROLLBAR
   ============================================================================= */

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(0, 229, 255, 0.2); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(0, 229, 255, 0.3); }

/* =============================================================================
   TYPOGRAPHY
   ============================================================================= */

h1, h2, h3, h4, h5, h6 { margin: 0 0 var(--space-sm) 0; font-weight: 600; color: var(--color-text-primary); line-height: 1.3; }
h1 { font-size: 24px; }
h2 { font-size: 18px; }
h3 { font-size: 14px; }
h4 { font-size: 13px; }

p { margin: 0 0 var(--space-sm) 0; color: var(--color-text-secondary); }

a { color: var(--color-accent-cyan); text-decoration: none; transition: color var(--transition-fast); }
a:hover { color: var(--color-accent-teal); text-decoration: underline; }

code { font-family: var(--font-mono); font-size: 0.9em; padding: 2px 6px; background: rgba(167, 139, 250, 0.1); color: var(--color-accent-purple); border-radius: 4px; }

pre { font-family: var(--font-mono); font-size: var(--font-size-sm); padding: var(--space-md); background: var(--color-bg-secondary); border: 1px solid var(--color-border-dim); border-radius: var(--radius); overflow-x: auto; margin: 0; }

ul, ol { margin: 0 0 var(--space-sm) 0; padding-left: 20px; }
li { margin-bottom: 4px; color: var(--color-text-secondary); }

/* =============================================================================
   FORM LAYOUT HELPERS
   ============================================================================= */

form { display: flex; flex-direction: column; gap: var(--space-md); }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-row { display: flex; gap: var(--space-md); }
.form-row > * { flex: 1; }

/* =============================================================================
   UTILITY CLASSES
   ============================================================================= */

.text-primary { color: var(--color-text-primary) !important; }
.text-secondary { color: var(--color-text-secondary) !important; }
.text-muted { color: var(--color-text-muted) !important; }
.text-cyan { color: var(--color-accent-cyan) !important; }
.text-purple { color: var(--color-accent-purple) !important; }
.text-green { color: var(--color-accent-green) !important; }
.text-pink { color: var(--color-accent-pink) !important; }
.text-yellow { color: var(--color-accent-yellow) !important; }

.bg-primary { background: var(--color-bg-primary) !important; }
.bg-card { background: var(--color-bg-card) !important; }

.border-cyan { border-color: var(--color-accent-cyan) !important; }
.border-purple { border-color: var(--color-accent-purple) !important; }
.border-dim { border-color: var(--color-border-dim) !important; }

.glow-cyan { box-shadow: var(--shadow-glow-cyan); }
.glow-purple { box-shadow: var(--shadow-glow-purple); }
.glow-green { box-shadow: var(--shadow-glow-green); }
.glow-pink { box-shadow: var(--shadow-glow-pink); }

.text-center { text-align: center; }
.text-right { text-align: right; }
.font-mono { font-family: var(--font-mono); }

@media (max-width: 640px) { .form-row { flex-direction: column; } }
  `;

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&family=Google+Sans+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

  <!-- 1. Tailwind CSS Play CDN FIRST -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            border: 'hsl(var(--border))',
            input: 'hsl(var(--input))',
            ring: 'hsl(var(--ring))',
            background: 'hsl(var(--background))',
            foreground: 'hsl(var(--foreground))',
            primary: {
              DEFAULT: 'hsl(var(--primary))',
              foreground: 'hsl(var(--primary-foreground))',
            },
            secondary: {
              DEFAULT: 'hsl(var(--secondary))',
              foreground: 'hsl(var(--secondary-foreground))',
            },
            destructive: {
              DEFAULT: 'hsl(var(--destructive))',
              foreground: 'hsl(var(--destructive-foreground))',
            },
            muted: {
              DEFAULT: 'hsl(var(--muted))',
              foreground: 'hsl(var(--muted-foreground))',
            },
            accent: {
              DEFAULT: 'hsl(var(--accent))',
              foreground: 'hsl(var(--accent-foreground))',
            },
            card: {
              DEFAULT: 'hsl(var(--card))',
              foreground: 'hsl(var(--card-foreground))',
            },
          },
          borderRadius: {
            lg: 'var(--radius)',
            md: 'calc(var(--radius) - 2px)',
            sm: 'calc(var(--radius) - 4px)',
          },
        },
      },
    }
  </script>

  <!-- 2. Basecoat UI (shadcn/ui for HTMX) SECOND -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/basecoat-css@0.3.9/dist/basecoat.cdn.min.css">
  <script src="https://cdn.jsdelivr.net/npm/basecoat-css@0.3.9/dist/js/all.min.js" defer></script>

  <!-- 3. RVBBIT Theme Overrides LAST (variables + minimal resets) -->
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

      // FIX: Repair malformed HTMX URLs before HTMX processes them
      // This handles cases where template variables weren't replaced properly
      const checkpointId = document.body.getAttribute('data-checkpoint-id');
      const sessionId = document.body.getAttribute('data-session-id');
      console.log('[HTMX iframe] Checkpoint context from body:', {checkpointId, sessionId});

      // DEBUG: Check form structure
      const forms = document.querySelectorAll('form');
      console.log('[HTMX iframe] Forms found:', forms.length);
      forms.forEach((form, idx) => {
        console.log('[HTMX iframe] Form', idx, ':', {
          hasHxPost: form.hasAttribute('hx-post'),
          hxPost: form.getAttribute('hx-post'),
          hasHxExt: form.hasAttribute('hx-ext'),
          hxExt: form.getAttribute('hx-ext'),
          buttonCount: form.querySelectorAll('button').length
        });
      });

      if (checkpointId) {
        document.querySelectorAll('[hx-post]').forEach(el => {
          const url = el.getAttribute('hx-post');
          // Fix malformed URLs like '/api/checkpoints//respond'
          if (url && url.includes('//respond')) {
            const fixedUrl = '/api/checkpoints/' + checkpointId + '/respond';
            el.setAttribute('hx-post', fixedUrl);
            console.log('[HTMX iframe] Fixed malformed URL:', url, '->', fixedUrl);
          }
        });
      }

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

        // Track which button was clicked (needed for FormData since e.submitter isn't always available)
        let lastClickedButton = null;

        // DEBUG: Log all clicks and track the clicked button for form submission
        document.addEventListener('click', (e) => {
          // Track any button or submit input click
          if (e.target.matches('button, input[type="submit"]')) {
            lastClickedButton = e.target;
            console.log('[HTMX iframe] Tracked clicked button:', e.target.name, '=', e.target.value, 'type:', e.target.type);
          }

          if (e.target.tagName === 'BUTTON') {
            console.log('[HTMX iframe] Button clicked:', e.target.textContent.trim(), 'type:', e.target.type);

            const form = e.target.closest('form');
            if (form) {
              console.log('[HTMX iframe] Button is inside form');

              // For type="button", the onclick should handle submission
              // But if requestSubmit() doesn't fire submit event, we need a backup
              if (e.target.type === 'button') {
                console.log('[HTMX iframe] Button type is "button" - relying on onclick');

                // BACKUP: Manually trigger submit after onclick executes
                setTimeout(() => {
                  console.log('[HTMX iframe] Manually triggering submit event as backup');
                  const submitEvent = new Event('submit', { bubbles: true, cancelable: true });
                  form.dispatchEvent(submitEvent);
                }, 150);
              } else if (e.target.type === 'submit') {
                console.log('[HTMX iframe] Button type is "submit" - will trigger submit automatically');
              }
            } else {
              console.log('[HTMX iframe] Button is NOT inside form');
            }
          }
        }, true);

        // WORKAROUND: Intercept form submissions and use fetch with JSON instead of HTMX
        document.addEventListener('submit', (e) => {
          console.log('[HTMX iframe] Submit event fired on:', e.target.tagName);
          const form = e.target;

          // Check if this form has hx-post and json-enc
          if (form.hasAttribute('hx-post') && form.getAttribute('hx-ext')?.includes('json-enc')) {
            console.log('[HTMX iframe] Intercepting form submit for manual JSON POST');
            e.preventDefault();
            e.stopPropagation();

            // Reuse checkpoint context from outer scope
            const cpId = checkpointId;
            const sessId = sessionId;

            // Build URL from context (fallback to form attribute if context missing)
            let url;
            if (cpId) {
              url = 'http://localhost:5050/api/checkpoints/' + cpId + '/respond';
              console.log('[HTMX iframe] Using checkpoint context for URL:', url);
            } else {
              url = form.getAttribute('hx-post');
              if (url.startsWith('/')) {
                url = 'http://localhost:5050' + url;
              }
              console.log('[HTMX iframe] Using form hx-post attribute:', url);
            }

            // Build JSON from form data
            // Use e.submitter if available (native submit), otherwise use tracked button
            const submitter = e.submitter || lastClickedButton;
            console.log('[HTMX iframe] Submitter:', submitter?.name, '=', submitter?.value);

            // FormData with submitter to include the clicked button's name/value
            let formData;
            try {
              formData = submitter ? new FormData(form, submitter) : new FormData(form);
            } catch (err) {
              // Some browsers don't support FormData with submitter
              console.log('[HTMX iframe] FormData with submitter failed, using fallback');
              formData = new FormData(form);
              // Manually add the submitter if present
              if (submitter && submitter.name) {
                formData.append(submitter.name, submitter.value || '');
              }
            }

            console.log('[HTMX iframe] FormData entries:', Array.from(formData.entries()));

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
            console.log('[HTMX iframe] Checkpoint context - checkpointId:', cpId, 'sessionId:', sessId);

            // Submit via fetch
            fetch(url, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Checkpoint-Id': cpId || '',
                'X-Session-Id': sessId || ''
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

          // If path is relative, convert to absolute pointing to backend (port 5050)
          if (path && path.startsWith('/')) {
            const absoluteURL = 'http://localhost:5050' + path;
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
<body class="dark" data-checkpoint-id="${checkpointId}" data-session-id="${sessionId}">
${bodyHTML}
</body>
</html>`;
}

/**
 * Replace template variables in HTML string
 * Supports: {{ checkpoint_id }}, {{ session_id }}, {{ cell_name }}, {{ cascade_id }}
 */
function processTemplateVariables(html, context) {
  return html.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, key) => {
    const value = context[key];
    if (value !== undefined) {
      return value;
    }
    // Keep unmatched placeholders and log warning
    console.warn(`[RVBBIT HTMX] Unknown template variable: ${key}`);
    return match;
  });
}

export default HTMLSection;
