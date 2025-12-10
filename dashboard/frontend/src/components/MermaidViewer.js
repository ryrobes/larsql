import React, { useEffect, useRef, useState, useCallback } from 'react';
import mermaid from 'mermaid';

function MermaidViewer({ content, sessionId }) {
  const mermaidRef = useRef(null);
  const containerRef = useRef(null);
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  useEffect(() => {
    mermaid.initialize({
      startOnLoad: true,
      theme: 'dark',
      securityLevel: 'loose',
      fontFamily: 'monospace',
      themeVariables: {
        // Force black text on all elements
        primaryTextColor: '#000',
        secondaryTextColor: '#000',
        tertiaryTextColor: '#000',
        textColor: '#000',
        nodeTextColor: '#000',
        clusterTextColor: '#000',
        labelTextColor: '#000',
      }
    });
  }, []);

  const renderMermaid = useCallback(async () => {
    if (!mermaidRef.current || !content) return;

    try {
      // Mutate old diagrams to add black text color
      let modifiedContent = content;

      // Add color:#000 to classDef statements that don't have it
      modifiedContent = modifiedContent.replace(
        /classDef\s+(\w+)\s+([^;]+);/g,
        (match, className, styles) => {
          // Only add color if it's not already present
          if (!styles.includes('color:')) {
            return `classDef ${className} ${styles},color:#000;`;
          }
          return match;
        }
      );

      mermaidRef.current.innerHTML = modifiedContent;
      mermaidRef.current.removeAttribute('data-processed');
      await mermaid.run({
        nodes: [mermaidRef.current],
      });
    } catch (error) {
      console.error('Error rendering Mermaid:', error);
      if (mermaidRef.current) {
        mermaidRef.current.innerHTML = '<div class="error">Error rendering graph</div>';
      }
    }
  }, [content]);

  useEffect(() => {
    if (content && mermaidRef.current) {
      renderMermaid();
    }
  }, [content, sessionId, renderMermaid]);

  const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY * -0.001;
    const newScale = Math.min(Math.max(0.1, scale + delta), 10);
    setScale(newScale);
  };

  const handleMouseDown = (e) => {
    if (e.button === 0) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
    }
  };

  const handleMouseMove = (e) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const resetView = () => {
    setScale(1);
    setPosition({ x: 0, y: 0 });
  };

  const zoomIn = () => {
    setScale(Math.min(scale + 0.5, 10));
  };

  const zoomOut = () => {
    setScale(Math.max(scale - 0.5, 0.1));
  };

  if (!content) {
    return (
      <div className="mermaid-container">
        <div className="empty-state">
          Select a cascade to view its graph
        </div>
      </div>
    );
  }

  return (
    <div
      className="mermaid-container"
      ref={containerRef}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{
        cursor: isDragging ? 'grabbing' : 'grab',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        MozUserSelect: 'none',
        msUserSelect: 'none'
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '10px',
          right: '10px',
          display: 'flex',
          gap: '0.5rem',
          zIndex: 1000,
        }}
      >
        <button
          onClick={zoomIn}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#4a9eff',
            border: 'none',
            borderRadius: '4px',
            color: 'white',
            cursor: 'pointer',
          }}
        >
          +
        </button>
        <button
          onClick={zoomOut}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#4a9eff',
            border: 'none',
            borderRadius: '4px',
            color: 'white',
            cursor: 'pointer',
          }}
        >
          -
        </button>
        <button
          onClick={resetView}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#4a9eff',
            border: 'none',
            borderRadius: '4px',
            color: 'white',
            cursor: 'pointer',
          }}
        >
          Reset
        </button>
      </div>

      <div
        className="mermaid-wrapper"
        style={{
          transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
          transformOrigin: 'center center',
          transition: isDragging ? 'none' : 'transform 0.1s',
        }}
      >
        <div ref={mermaidRef} className="mermaid"></div>
      </div>
    </div>
  );
}

export default MermaidViewer;
