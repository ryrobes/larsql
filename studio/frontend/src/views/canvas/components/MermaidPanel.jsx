import React, { useRef, useEffect, useState } from 'react';
import { Icon } from '@iconify/react';
import './MermaidPanel.css';

// Lazy load mermaid
let mermaidInstance = null;
const getMermaid = async () => {
  if (!mermaidInstance) {
    const mermaid = await import('mermaid');
    mermaidInstance = mermaid.default;
    mermaidInstance.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        primaryColor: '#00e5ff',
        primaryTextColor: '#e0e0e0',
        primaryBorderColor: '#00e5ff',
        lineColor: '#64ffda',
        secondaryColor: '#1e3a5f',
        tertiaryColor: '#0d2137',
        background: '#0a1929',
        mainBkg: '#0a1929',
        secondBkg: '#1e3a5f',
        nodeBorder: '#00e5ff',
        clusterBkg: '#1e3a5f',
        clusterBorder: '#00e5ff',
        titleColor: '#e0e0e0',
        edgeLabelBackground: '#0a1929',
      },
      flowchart: {
        htmlLabels: true,
        curve: 'basis',
      },
    });
  }
  return mermaidInstance;
};

/**
 * MermaidPanel - Renders Mermaid diagrams
 *
 * Accepts content in two formats:
 * - Object with 'mermaid' key: { mermaid: "graph LR...", format: "..." }
 * - Raw mermaid string: "graph LR..."
 */
const MermaidPanel = ({ content }) => {
  const containerRef = useRef(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const renderMermaid = async () => {
      if (!containerRef.current) return;

      // Extract mermaid code
      let mermaidCode = null;
      if (typeof content === 'string') {
        mermaidCode = content;
      } else if (content && typeof content === 'object' && content.mermaid) {
        mermaidCode = content.mermaid;
      }

      if (!mermaidCode) {
        setError('No mermaid content provided');
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const mermaid = await getMermaid();

        // Generate unique ID
        const id = `mermaid-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        // Render the diagram
        const { svg } = await mermaid.render(id, mermaidCode);

        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      } catch (err) {
        console.error('Mermaid render error:', err);
        setError(err.message || 'Failed to render diagram');
      } finally {
        setLoading(false);
      }
    };

    renderMermaid();
  }, [content]);

  if (loading) {
    return (
      <div className="mermaid-panel-loading">
        <Icon icon="mdi:loading" width="24" className="spinning" />
        <span>Rendering diagram...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mermaid-panel-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="mermaid-panel-container"
    />
  );
};

export default MermaidPanel;
