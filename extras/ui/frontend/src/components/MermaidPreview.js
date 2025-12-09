import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import mermaid from 'mermaid';
import { Icon } from '@iconify/react';
import './MermaidPreview.css';

// Initialize mermaid with cyberpunk/vaporwave theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    background: 'transparent',
    primaryColor: 'transparent',
    primaryTextColor: '#e0f0ff',
    primaryBorderColor: '#a78bfa',
    lineColor: '#06b6d4',
    secondaryColor: 'transparent',
    tertiaryColor: 'transparent',
    fontSize: '14px',
    fontFamily: 'Monaco, Courier New, monospace'
  },
  flowchart: {
    useMaxWidth: false,
    htmlLabels: true,
    curve: 'basis'
  }
});

// Global render queue to serialize mermaid renders (prevents race conditions)
let renderQueue = Promise.resolve();
const queueRender = async (renderFn) => {
  renderQueue = renderQueue.then(renderFn).catch(err => {
    console.error('[MermaidPreview] Queued render failed:', err);
  });
  return renderQueue;
};

function MermaidPreview({ sessionId, size = 'small', showMetadata = true, lastUpdate = null, onLayoutDetected = null }) {
  const containerRef = useRef(null);
  const prevSessionIdRef = useRef(null);
  const [graphData, setGraphData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [lastMtime, setLastMtime] = useState(null); // Track file modification time
  const [lastRawContent, setLastRawContent] = useState(null); // Track raw content for comparison
  const maxRetries = 3;
  const retryDelayMs = 2000; // 2 seconds between retries

  useEffect(() => {
    if (!sessionId) return;

    // AbortController to cancel in-flight requests when effect re-runs
    const abortController = new AbortController();

    const fetchGraph = async (attempt = 0) => {
      try {
        // Only show loading on first fetch, not on updates
        if (!graphData) {
          setLoading(true);
        }
        console.log(`[MermaidPreview] Fetching graph for ${sessionId} (attempt ${attempt + 1}/${maxRetries + 1}, lastUpdate=${lastUpdate})`);

        const response = await fetch(`http://localhost:5001/api/mermaid/${sessionId}`, {
          signal: abortController.signal
        });
        const data = await response.json();

        if (data.error) {
          console.warn(`[MermaidPreview] API error for ${sessionId}:`, data.error);

          // Retry if we haven't exhausted retries (data might not be flushed to parquet yet)
          if (attempt < maxRetries) {
            console.log(`[MermaidPreview] Retrying in ${retryDelayMs}ms...`);
            setTimeout(() => {
              setRetryCount(attempt + 1);
              fetchGraph(attempt + 1);
            }, retryDelayMs);
            return;
          }

          setError(data.error);
          setLoading(false);
          return;
        }

        // Success! Clear any error state and retry count
        setError(null);
        setRetryCount(0);

        // Check if content actually changed (by file mtime or raw content comparison)
        const newMtime = data.file_mtime;
        const rawContent = data.mermaid;

        // Compare raw content against stored raw content (not mutated version)
        // This handles cases where mtime has 1-second granularity and misses rapid updates
        const contentChanged = !lastMtime || newMtime !== lastMtime ||
          !graphData || lastRawContent !== rawContent;

        if (!contentChanged) {
          console.log(`[MermaidPreview] No changes detected for ${sessionId} (mtime=${newMtime})`);
          setLoading(false);
          return;
        }

        // Mutate mermaid colors to match UI theme
        const mutatedMermaid = mutateMermaidColors(data.mermaid);
        console.log(`[MermaidPreview] Loaded graph for ${sessionId} (${data.mermaid?.length || 0} chars, source=${data.source}, mtime=${newMtime})`);

        setLastMtime(newMtime);
        setLastRawContent(rawContent); // Store raw content for accurate comparison
        setGraphData({
          mermaid: mutatedMermaid,
          metadata: data.metadata,
          source: data.source
        });
        setLoading(false);
      } catch (err) {
        // Ignore abort errors (expected when effect re-runs)
        if (err.name === 'AbortError') {
          console.log(`[MermaidPreview] Fetch aborted for ${sessionId} (superseded by newer request)`);
          return;
        }

        console.error(`[MermaidPreview] Fetch error for ${sessionId}:`, err);

        // Retry on network errors too (but not if aborted)
        if (attempt < maxRetries && !abortController.signal.aborted) {
          console.log(`[MermaidPreview] Retrying in ${retryDelayMs}ms...`);
          setTimeout(() => {
            if (!abortController.signal.aborted) {
              setRetryCount(attempt + 1);
              fetchGraph(attempt + 1);
            }
          }, retryDelayMs);
          return;
        }

        setError('Failed to load graph');
        setLoading(false);
      }
    };

    // Reset state only when sessionId actually changes (not on lastUpdate triggers)
    const sessionChanged = prevSessionIdRef.current !== sessionId;
    if (sessionChanged) {
      console.log(`[MermaidPreview] Session changed from ${prevSessionIdRef.current} to ${sessionId}`);
      setGraphData(null);
      setError(null);
      setRetryCount(0);
      setLastMtime(null);
      setLastRawContent(null);
      prevSessionIdRef.current = sessionId;
    }

    fetchGraph(0);

    // Cleanup: abort in-flight fetch when effect re-runs or component unmounts
    return () => {
      abortController.abort();
    };
  }, [sessionId, lastUpdate]); // Refetch when session gets updated via SSE

  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    // Use a unique render ID
    const renderId = `mermaid-${sessionId}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // Queue the render to serialize all mermaid renders globally
    queueRender(async () => {
      try {
        // Clear container
        if (!containerRef.current) return; // Check if still mounted
        containerRef.current.innerHTML = '';

        //console.log(`[MermaidPreview] Rendering graph for ${sessionId} with id ${renderId}`);

        // Render mermaid (now serialized via queue)
        const { svg } = await mermaid.render(renderId, graphData.mermaid);

        // Insert SVG first
        containerRef.current.innerHTML = svg;
        const svgElement = containerRef.current.querySelector('svg');

        if (svgElement) {
          // Neon cyberpunk color palette - brighter, more vibrant
          const colors = {
            teal: '#2DD4BF',      // Primary accent (matches theme)
            purple: '#a78bfa',    // Secondary - boxes
            cyan: '#22d3ee',      // Brighter cyan for lines
            pink: '#f472b6',      // Accent
            text: '#F0F4F8'       // Crisp white text
          };

          // Style shapes - transparent fill, colored strokes with varying colors
          const allShapes = svgElement.querySelectorAll('rect, circle, polygon, ellipse');
          allShapes.forEach((shape, index) => {
            shape.setAttribute('fill', 'none');
            shape.setAttribute('fill-opacity', '0');
            // Cycle through teal, purple, cyan for variety
            const strokeColors = [colors.teal, colors.purple, colors.cyan];
            const strokeColor = strokeColors[index % strokeColors.length];
            shape.setAttribute('stroke', strokeColor);
            shape.setAttribute('stroke-width', '1.5');
          });

          // Style paths (arrows/lines) with teal (matches theme accent)
          const allPaths = svgElement.querySelectorAll('path');
          allPaths.forEach(path => {
            // Don't override marker paths
            if (!path.closest('marker')) {
              path.setAttribute('stroke', colors.teal);
              path.setAttribute('fill', 'none');
              path.setAttribute('stroke-width', '1.5');
            }
          });

          // Style lines
          const allLines = svgElement.querySelectorAll('line');
          allLines.forEach(line => {
            line.setAttribute('stroke', colors.teal);
            line.setAttribute('stroke-width', '1.5');
          });

          // Make text bright and readable
          const allText = svgElement.querySelectorAll('text, tspan');
          allText.forEach(text => {
            text.setAttribute('fill', colors.text);
            text.setAttribute('stroke', 'none');
            text.style.textShadow = '0 0 4px rgba(45, 212, 191, 0.5)';
          });

          // Style arrowheads - these need fill to be visible
          const allMarkers = svgElement.querySelectorAll('marker path, marker polygon');
          allMarkers.forEach(marker => {
            marker.setAttribute('fill', colors.teal);
            marker.setAttribute('stroke', colors.teal);
          });

          // Remove width/height first so getBBox works properly
          const origWidth = svgElement.getAttribute('width');
          const origHeight = svgElement.getAttribute('height');
          svgElement.removeAttribute('width');
          svgElement.removeAttribute('height');

          let contentWidth = parseFloat(origWidth) || 400;
          let contentHeight = parseFloat(origHeight) || 300;

          try {
            // Get bounding box for tight crop (needs to be in DOM)
            const bbox = svgElement.getBBox();
            const padding = 10; // Small fixed padding
            const x = bbox.x - padding;
            const y = bbox.y - padding;
            contentWidth = bbox.width + (padding * 2);
            contentHeight = bbox.height + (padding * 2);

            // Set tight viewBox
            svgElement.setAttribute('viewBox', `${x} ${y} ${contentWidth} ${contentHeight}`);
          } catch (err) {
            // Fallback to original dimensions
            console.warn('getBBox failed, using original dimensions:', err);
            if (origWidth && origHeight) {
              svgElement.setAttribute('viewBox', `0 0 ${origWidth} ${origHeight}`);
            }
          }

          // Notify parent of layout dimensions (for adaptive positioning)
          // Only flag as "wide" if width is more than 2.5x the height (truly wide horizontal flowcharts)
          // aspectRatio < 0.4 means width is 2.5x+ the height
          const aspectRatio = contentHeight / contentWidth;
          const isWide = aspectRatio < 0.4;
          if (onLayoutDetected && size === 'small') {
            onLayoutDetected({
              isWide,
              aspectRatio,
              width: contentWidth,
              height: contentHeight
            });
          }

          // For small size: expand container to fit the full diagram
          if (size === 'small') {
            // Find wrapper - could be .mermaid-wrapper (left panel) or .mermaid-wrapper-top (wide at top)
            const wrapper = containerRef.current.closest('.mermaid-wrapper, .mermaid-wrapper-top');
            const containerWidth = wrapper?.offsetWidth || 400;

            // Calculate exact height needed to show full diagram at this width
            const aspectRatio = contentHeight / contentWidth;
            const exactHeight = containerWidth * aspectRatio;

            // Clamp to reasonable bounds (min 100px, max 400px)
            const finalHeight = Math.min(400, Math.max(100, exactHeight));

            if (wrapper) {
              wrapper.style.height = `${finalHeight}px`;
            }

            // Use 'none' to fill the container exactly - no gaps, no clipping
            // This works because we sized the container to match the aspect ratio
            svgElement.setAttribute('preserveAspectRatio', 'xMidYMid meet');
            svgElement.style.width = '100%';
            svgElement.style.height = `${finalHeight}px`;
          } else {
            // For medium/large: show entire diagram
            svgElement.setAttribute('preserveAspectRatio', 'xMidYMid meet');
            svgElement.style.width = '100%';
            svgElement.style.height = '100%';
          }
        }
      } catch (err) {
        console.error('Error rendering mermaid:', err);
        setError('Failed to render graph');
      }
    });
  }, [graphData, sessionId, size, onLayoutDetected]);

  const mutateMermaidColors = (mermaidContent) => {
    // Replace default mermaid colors with cyberpunk/vaporwave theme
    // All fills become transparent, strokes become neon colors
    let mutated = mermaidContent;

    const colorMap = {
      // All fills -> none (transparent)
      'fill:#f9f9f9': 'fill:none',
      'fill:#e1f5fe': 'fill:none',
      'fill:#fff9c4': 'fill:none',
      'fill:#dcedc8': 'fill:none',
      'fill:#ffccbc': 'fill:none',
      'fill:#ffcdd2': 'fill:none',
      'fill:#eeeeee': 'fill:none',
      'fill:#ffffff': 'fill:none',
      'fill:#e3f2fd': 'fill:none',
      'fill:#bbdefb': 'fill:none',
      'fill:#c8e6c9': 'fill:none',

      // Stroke colors - cyberpunk neons
      'stroke:#333': 'stroke:#a78bfa',     // purple
      'stroke:#666': 'stroke:#06b6d4',     // cyan
      'stroke:#f44336': 'stroke:#f472b6',  // pink
      'stroke:#1976d2': 'stroke:#06b6d4',  // cyan
      'stroke:#388e3c': 'stroke:#34d399',  // mint
    };

    Object.entries(colorMap).forEach(([oldColor, newColor]) => {
      mutated = mutated.replace(new RegExp(oldColor.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), newColor);
    });

    return mutated;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
  };

  // Show loading state (including during retries)
  if (loading) {
    return (
      <div className={`mermaid-preview ${size}`}>
        <div className="mermaid-loading">
          <div className="spinner-small"></div>
          {retryCount > 0 && (
            <div className="retry-indicator" style={{ fontSize: '10px', color: '#666', marginTop: '4px' }}>
              Retry {retryCount}/{maxRetries}...
            </div>
          )}
        </div>
      </div>
    );
  }

  // Show error state after all retries exhausted (but still show something)
  if (error) {
    // For 'small' size, just show a minimal placeholder
    if (size === 'small') {
      return (
        <div className={`mermaid-preview ${size}`} style={{ opacity: 0.5 }}>
          <div className="mermaid-error-placeholder" style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '60px',
            color: '#666',
            fontSize: '11px'
          }}>
            Graph loading...
          </div>
        </div>
      );
    }
    // For larger sizes, show more info
    return (
      <div className={`mermaid-preview ${size}`}>
        <div className="mermaid-error" style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px',
          color: '#888'
        }}>
          <span style={{ fontSize: '12px' }}>Graph unavailable</span>
          <span style={{ fontSize: '10px', color: '#555', marginTop: '4px' }}>{error}</span>
        </div>
      </div>
    );
  }

  if (!graphData) {
    return (
      <div className={`mermaid-preview ${size}`} style={{ opacity: 0.3 }}>
        <div style={{ padding: '10px', color: '#555', fontSize: '11px', textAlign: 'center' }}>
          No graph data
        </div>
      </div>
    );
  }

  // Don't show modal if we're already in large size (prevents recursion)
  const canOpenModal = size !== 'large';

  return (
    <>
      <div
        className={`mermaid-preview ${size}`}
        onClick={() => canOpenModal && setShowModal(true)}
        style={{ cursor: canOpenModal ? 'pointer' : 'default' }}
      >
        <div className="mermaid-container" ref={containerRef}></div>

        {showMetadata && graphData.metadata && size !== 'small' && (
          <div className="mermaid-metadata">
            <div className="metadata-row">
              <span className="metadata-label">Cascade:</span>
              <span className="metadata-value">{graphData.metadata.cascade_id}</span>
            </div>
            <div className="metadata-row">
              <span className="metadata-label">File:</span>
              <span className="metadata-value">{graphData.metadata.cascade_file}</span>
            </div>
            <div className="metadata-row">
              <span className="metadata-label">Executed:</span>
              <span className="metadata-value">
                {formatTimestamp(graphData.metadata.start_time)}
              </span>
            </div>
            <div className="metadata-row">
              <span className="metadata-label">Duration:</span>
              <span className="metadata-value">
                {formatDuration(graphData.metadata.duration_seconds)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Full screen modal - rendered via portal at document root */}
      {showModal && canOpenModal && createPortal(
        <div
          className="mermaid-modal-backdrop"
          onClick={() => setShowModal(false)}
        >
          <div
            className="mermaid-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="mermaid-modal-close"
              onClick={(e) => {
                e.stopPropagation();
                setShowModal(false);
              }}
            >
              <Icon icon="mdi:close" width="24" />
            </button>
            <div className="mermaid-modal-content">
              <MermaidPreview sessionId={sessionId} size="large" showMetadata={false} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

export default MermaidPreview;
