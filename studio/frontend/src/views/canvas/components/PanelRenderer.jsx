import React from 'react';
import { Icon } from '@iconify/react';
import MermaidPanel from './MermaidPanel';
import DataGridPanel from './DataGridPanel';
import TextPanel from './TextPanel';
import './PanelRenderer.css';

/**
 * PanelRenderer - Renders a single panel based on its type
 *
 * Supports:
 * - mermaid-graph: Mermaid flowchart/graph diagrams
 * - mermaid-timeline: Mermaid timeline diagrams
 * - data-grid: Tabular data
 * - text: Plain text content
 */
const PanelRenderer = ({ panel, style }) => {
  const { name, content, type } = panel;

  // Get icon for panel type
  const getIcon = () => {
    switch (type) {
      case 'mermaid-graph':
        return 'mdi:graph';
      case 'mermaid-timeline':
        return 'mdi:timeline';
      case 'data-grid':
        return 'mdi:table';
      default:
        return 'mdi:text';
    }
  };

  // Render content based on type
  const renderContent = () => {
    switch (type) {
      case 'mermaid-graph':
      case 'mermaid-timeline':
        return <MermaidPanel content={content} />;

      case 'data-grid':
        return <DataGridPanel content={content} />;

      case 'text':
      default:
        return <TextPanel content={content} />;
    }
  };

  return (
    <div className="canvas-panel" style={style}>
      <div className="canvas-panel-header">
        <Icon icon={getIcon()} width="14" />
        <span className="canvas-panel-title">{name}</span>
        <span className="canvas-panel-type">{type}</span>
      </div>
      <div className="canvas-panel-content">
        {renderContent()}
      </div>
    </div>
  );
};

export default PanelRenderer;
