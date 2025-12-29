import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { Icon } from '@iconify/react';
import './InteractiveMermaid.css';

// Initialize mermaid with custom theme (matching MermaidPreview)
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    background: 'transparent',
    primaryColor: 'transparent',
    primaryTextColor: '#e0f0ff',
    primaryBorderColor: '#a78bfa',  // Purple
    lineColor: '#06b6d4',           // Cyan
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
    console.error('[InteractiveMermaid] Queued render failed:', err);
  });
  return renderQueue;
};

const colors = {
  purple: '#a78bfa',
  cyan: '#06b6d4',
  pink: '#f472b6',
  mint: '#34d399',
};

function InteractiveMermaid({ sessionId, activePhase, onPhaseClick, lastUpdate }) {
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [lastMtime, setLastMtime] = useState(null);
  const containerRef = useRef(null);
  const maxRetries = 3;
  const retryDelayMs = 2000;

  useEffect(() => {
    if (!sessionId) return;

    const fetchGraph = async (attempt = 0) => {
      try {
        if (!graphData) {
          setLoading(true);
        }
        console.log(`[InteractiveMermaid] Fetching graph for ${sessionId} (attempt ${attempt + 1}/${maxRetries + 1})`);

        const response = await fetch(`http://localhost:5050/api/mermaid/${sessionId}`);
        const data = await response.json();

        if (data.error) {
          console.warn(`[InteractiveMermaid] API error for ${sessionId}:`, data.error);

          // Retry if we haven't exhausted retries
          if (attempt < maxRetries) {
            console.log(`[InteractiveMermaid] Retrying in ${retryDelayMs}ms...`);
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

        // Check if content actually changed
        const newMtime = data.file_mtime;
        const contentChanged = !lastMtime || newMtime !== lastMtime ||
          !graphData || graphData.mermaid !== data.mermaid;

        if (!contentChanged) {
          console.log(`[InteractiveMermaid] No changes detected for ${sessionId} (mtime=${newMtime})`);
          setLoading(false);
          return;
        }

        // Mutate mermaid colors to match UI theme
        const mutatedMermaid = mutateMermaidColors(data.mermaid);
        console.log(`[InteractiveMermaid] Loaded graph for ${sessionId} (${data.mermaid?.length || 0} chars, mtime=${newMtime})`);

        setLastMtime(newMtime);
        setGraphData({
          mermaid: mutatedMermaid,
          metadata: data.metadata
        });
        setLoading(false);
      } catch (err) {
        console.error(`[InteractiveMermaid] Fetch error for ${sessionId}:`, err);

        // Retry on network errors too
        if (attempt < maxRetries) {
          console.log(`[InteractiveMermaid] Retrying in ${retryDelayMs}ms...`);
          setTimeout(() => {
            setRetryCount(attempt + 1);
            fetchGraph(attempt + 1);
          }, retryDelayMs);
          return;
        }

        setError('Failed to load graph');
        setLoading(false);
      }
    };

    fetchGraph(0);
  }, [sessionId, lastUpdate]);

  // Render mermaid diagram
  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    const renderId = `mermaid-${sessionId}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    queueRender(async () => {
      try {
        // Clear container first
        if (!containerRef.current) return;
        containerRef.current.innerHTML = '';

        console.log(`[InteractiveMermaid] Rendering ${renderId}`);
        const { svg } = await mermaid.render(renderId, graphData.mermaid);

        // Insert SVG first (like MermaidPreview)
        containerRef.current.innerHTML = svg;
        const svgElement = containerRef.current.querySelector('svg');

        if (!svgElement) {
          console.error('[InteractiveMermaid] No SVG element found');
          return;
        }

        // Apply cyberpunk neon theme (matching MermaidPreview pattern)

        // Style shapes - transparent fill, colored strokes
        const allShapes = svgElement.querySelectorAll('rect, circle, polygon, ellipse');
        allShapes.forEach((shape, index) => {
          shape.setAttribute('fill', 'none');
          shape.setAttribute('fill-opacity', '0');
          // Alternate purple and cyan strokes
          const strokeColor = index % 2 === 0 ? colors.purple : colors.cyan;
          shape.setAttribute('stroke', strokeColor);
          shape.setAttribute('stroke-width', '2');
        });

        // Style paths (arrows/lines) with cyan
        const allPaths = svgElement.querySelectorAll('path');
        allPaths.forEach(path => {
          path.setAttribute('stroke', colors.cyan);
          path.setAttribute('fill', 'none');
          path.setAttribute('stroke-width', '2');
        });

        // Style lines
        const allLines = svgElement.querySelectorAll('line');
        allLines.forEach(line => {
          line.setAttribute('stroke', colors.cyan);
          line.setAttribute('stroke-width', '2');
        });

        // Make text bright and readable
        const allText = svgElement.querySelectorAll('text, tspan');
        allText.forEach(text => {
          text.setAttribute('fill', colors.cyan);
          text.setAttribute('stroke', 'none');
        });

        // Style arrowheads - these need fill to be visible
        const allMarkers = svgElement.querySelectorAll('marker path, marker polygon');
        allMarkers.forEach(marker => {
          marker.setAttribute('fill', colors.cyan);
          marker.setAttribute('stroke', colors.cyan);
        });

        // Remove width/height first so getBBox works properly
        const origWidth = svgElement.getAttribute('width');
        const origHeight = svgElement.getAttribute('height');
        svgElement.removeAttribute('width');
        svgElement.removeAttribute('height');

        try {
          const bbox = svgElement.getBBox();
          const padding = 10;
          const x = bbox.x - padding;
          const y = bbox.y - padding;
          const contentWidth = bbox.width + (padding * 2);
          const contentHeight = bbox.height + (padding * 2);

          svgElement.setAttribute('viewBox', `${x} ${y} ${contentWidth} ${contentHeight}`);
        } catch (err) {
          console.warn('[InteractiveMermaid] getBBox failed, using original dimensions:', err);
          if (origWidth && origHeight) {
            svgElement.setAttribute('viewBox', `0 0 ${origWidth} ${origHeight}`);
          }
        }

        svgElement.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        svgElement.style.width = '100%';
        svgElement.style.height = 'auto';

        // Add click handlers to phase nodes
        addClickHandlers();

        // Highlight active phase
        updateActivePhaseHighlight();

        console.log(`[InteractiveMermaid] Rendered ${renderId} successfully`);
      } catch (err) {
        console.error('[InteractiveMermaid] Render error:', err);
        setError('Failed to render diagram');
      }
    });
  }, [graphData, sessionId]);

  // Update active phase highlight when activePhase changes
  useEffect(() => {
    if (graphData && containerRef.current) {
      updateActivePhaseHighlight();
    }
  }, [activePhase, graphData]);

  const mutateMermaidColors = (mermaidContent) => {
    if (!mermaidContent) return '';

    let mutated = mermaidContent;

    const colorMap = {
      // All fills -> transparent
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
      'stroke:#333': 'stroke:#a78bfa',
      'stroke:#666': 'stroke:#06b6d4',
      'stroke:#f44336': 'stroke:#f472b6',
      'stroke:#1976d2': 'stroke:#06b6d4',
      'stroke:#388e3c': 'stroke:#34d399',
    };

    Object.keys(colorMap).forEach(oldColor => {
      const newColor = colorMap[oldColor];
      mutated = mutated.split(oldColor).join(newColor);
    });

    return mutated;
  };

  const addClickHandlers = () => {
    if (!containerRef.current) return;

    const svg = containerRef.current.querySelector('svg');
    if (!svg) return;

    // Find all nodes (g elements with class="node")
    const nodes = svg.querySelectorAll('g.node');

    nodes.forEach(node => {
      // Extract phase name from node ID or text content
      const textElement = node.querySelector('text');
      if (!textElement) return;

      const phaseName = textElement.textContent.trim();

      // Make clickable
      node.style.cursor = 'pointer';
      node.addEventListener('click', () => {
        if (onPhaseClick) {
          onPhaseClick(phaseName);
        }
      });

      // Add hover effect
      node.addEventListener('mouseenter', () => {
        node.style.filter = 'brightness(1.3)';
      });
      node.addEventListener('mouseleave', () => {
        if (phaseName !== activePhase) {
          node.style.filter = 'brightness(1)';
        }
      });
    });
  };

  const updateActivePhaseHighlight = () => {
    if (!containerRef.current || !activePhase) return;

    const svg = containerRef.current.querySelector('svg');
    if (!svg) return;

    // Remove previous highlights
    svg.querySelectorAll('g.node').forEach(node => {
      node.classList.remove('active-phase');
      node.style.filter = 'brightness(1)';
    });

    // Find and highlight active phase node
    const nodes = svg.querySelectorAll('g.node');
    nodes.forEach(node => {
      const textElement = node.querySelector('text');
      if (textElement && textElement.textContent.trim() === activePhase) {
        node.classList.add('active-phase');
        node.style.filter = 'drop-shadow(0 0 12px #2DD4BF) brightness(1.5)';
      }
    });
  };

  return (
    <div className="interactive-mermaid-container">
      {loading && (
        <div className="mermaid-loading">
          <Icon icon="mdi:loading" width="32" className="spinning" />
          <span>Loading diagram...</span>
          {retryCount > 0 && <span className="retry-info">(Retry {retryCount}/{maxRetries})</span>}
        </div>
      )}

      {error && (
        <div className="mermaid-error">
          <Icon icon="mdi:alert-circle" width="32" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && (
        <div className="mermaid-diagram" ref={containerRef}></div>
      )}
    </div>
  );
}

export default React.memo(InteractiveMermaid);
