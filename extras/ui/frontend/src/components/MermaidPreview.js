import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import mermaid from 'mermaid';
import './MermaidPreview.css';

// Initialize mermaid with base theme (we'll mutate colors)
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    background: 'transparent',
    primaryColor: 'transparent',
    primaryTextColor: '#e0e0e0',
    primaryBorderColor: '#60a5fa',
    lineColor: '#60a5fa',
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

function MermaidPreview({ sessionId, size = 'small', showMetadata = true }) {
  const containerRef = useRef(null);
  const [graphData, setGraphData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!sessionId) return;

    const fetchGraph = async () => {
      try {
        setLoading(true);
        const response = await fetch(`http://localhost:5001/api/mermaid/${sessionId}`);
        const data = await response.json();

        if (data.error) {
          setError(data.error);
          setLoading(false);
          return;
        }

        // Mutate mermaid colors to match UI theme
        const mutatedMermaid = mutateMermaidColors(data.mermaid);

        setGraphData({
          mermaid: mutatedMermaid,
          metadata: data.metadata
        });
        setLoading(false);
      } catch (err) {
        console.error('Error fetching mermaid graph:', err);
        setError('Failed to load graph');
        setLoading(false);
      }
    };

    fetchGraph();
  }, [sessionId]);

  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    const renderGraph = async () => {
      try {
        // Generate unique ID for this graph
        const id = `mermaid-${sessionId}-${Date.now()}`;

        // Clear container
        containerRef.current.innerHTML = '';

        // Render mermaid
        const { svg } = await mermaid.render(id, graphData.mermaid);

        // Insert SVG first
        containerRef.current.innerHTML = svg;
        const svgElement = containerRef.current.querySelector('svg');

        if (svgElement) {
          // Remove ALL fill colors - we want outline-only
          const allShapes = svgElement.querySelectorAll('rect, circle, polygon, path, ellipse');
          allShapes.forEach(shape => {
            // Make fills transparent
            shape.setAttribute('fill', 'none');
            shape.setAttribute('fill-opacity', '0');

            // Make strokes bright and visible
            const currentStroke = shape.getAttribute('stroke');
            if (!currentStroke || currentStroke === 'none') {
              shape.setAttribute('stroke', '#60a5fa');
            } else {
              // Keep stroke but make it brighter
              shape.setAttribute('stroke', '#60a5fa');
            }
            shape.setAttribute('stroke-width', '2.5');
          });

          // Make text bright
          const allText = svgElement.querySelectorAll('text, tspan');
          allText.forEach(text => {
            text.setAttribute('fill', '#e0e0e0');
            text.setAttribute('stroke', 'none');
          });

          // Remove width/height first so getBBox works properly
          const origWidth = svgElement.getAttribute('width');
          const origHeight = svgElement.getAttribute('height');
          svgElement.removeAttribute('width');
          svgElement.removeAttribute('height');

          try {
            // Get bounding box for tight crop (needs to be in DOM)
            const bbox = svgElement.getBBox();
            const padding = 10; // Small fixed padding
            const x = bbox.x - padding;
            const y = bbox.y - padding;
            const width = bbox.width + (padding * 2);
            const height = bbox.height + (padding * 2);

            // Set tight viewBox
            svgElement.setAttribute('viewBox', `${x} ${y} ${width} ${height}`);
          } catch (err) {
            // Fallback to original dimensions
            console.warn('getBBox failed, using original dimensions:', err);
            if (origWidth && origHeight) {
              svgElement.setAttribute('viewBox', `0 0 ${origWidth} ${origHeight}`);
            }
          }

          // Use 'slice' for small/medium (fill and clip), 'meet' for large (fit everything)
          const aspectRatio = size === 'large' ? 'xMidYMid meet' : 'xMidYMid slice';
          svgElement.setAttribute('preserveAspectRatio', aspectRatio);
          svgElement.style.width = '100%';
          svgElement.style.height = '100%';
          svgElement.style.minWidth = '100%';
          svgElement.style.minHeight = '100%';
        }
      } catch (err) {
        console.error('Error rendering mermaid:', err);
        setError('Failed to render graph');
      }
    };

    renderGraph();
  }, [graphData, sessionId]);

  const mutateMermaidColors = (mermaidContent) => {
    // Replace default mermaid colors with UI dark theme colors
    let mutated = mermaidContent;

    // Replace class definitions with brighter, more visible dark theme colors
    const colorMap = {
      // Fill colors - use darker backgrounds with visible contrast
      'fill:#f9f9f9': 'fill:#1a2332',
      'fill:#e1f5fe': 'fill:#1a2a42',  // system - dark blue
      'fill:#fff9c4': 'fill:#3a3428',  // user - dark yellow
      'fill:#dcedc8': 'fill:#1a3a2a',  // agent - dark green
      'fill:#ffccbc': 'fill:#3a2428',  // tool - dark red/pink
      'fill:#ffcdd2': 'fill:#4a2328',  // error - darker red
      'fill:#eeeeee': 'fill:#2a2a2a',  // structure - dark gray
      'fill:#ffffff': 'fill:#1a1a1a',  // cascade - dark background
      'fill:#e3f2fd': 'fill:#1a2842',  // soundings - dark blue
      'fill:#bbdefb': 'fill:#2a3858',  // sounding attempt - medium blue
      'fill:#c8e6c9': 'fill:#2a4a3a',  // winner - dark green

      // Stroke colors - use bright, visible pastels
      'stroke:#333': 'stroke:#60a5fa',  // borders - bright blue
      'stroke:#666': 'stroke:#a78bfa',  // dashed borders - bright purple
      'stroke:#f44336': 'stroke:#f87171',  // error stroke - bright red
      'stroke:#1976d2': 'stroke:#60a5fa',  // soundings stroke - bright blue
      'stroke:#388e3c': 'stroke:#34d399',  // winner stroke - bright green

      // Additional stroke widths for visibility
      'stroke-width:1px': 'stroke-width:2px',
      'stroke-width:2px': 'stroke-width:2.5px',
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

  if (error) {
    return null; // Don't show anything if graph doesn't exist
  }

  if (loading) {
    return (
      <div className={`mermaid-preview ${size}`}>
        <div className="mermaid-loading">
          <div className="spinner-small"></div>
        </div>
      </div>
    );
  }

  if (!graphData) {
    return null;
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
              ✕
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
