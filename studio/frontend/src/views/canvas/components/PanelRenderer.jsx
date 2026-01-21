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
 *
 * @param {object} panel - Panel configuration (name, content, type, on_select, multi_select, etc.)
 * @param {object} style - CSS styles for positioning
 * @param {function} onInteraction - Callback for panel interactions
 */
const PanelRenderer = ({ panel, style, onInteraction }) => {
  const { name, content, type, on_select, multi_select, selected_values, select_field } = panel;

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

  // Handle row click from DataGridPanel
  const handleRowClick = (rowData) => {
    if (onInteraction && on_select) {
      onInteraction({
        panelName: name,
        panelType: type,
        eventType: 'select',
        data: rowData,
        onSelectTemplate: on_select,
      });
    }
  };

  // Render content based on type
  const renderContent = () => {
    switch (type) {
      case 'mermaid-graph':
      case 'mermaid-timeline':
        return <MermaidPanel content={content} />;

      case 'data-grid':
        return (
          <DataGridPanel
            content={content}
            onRowClick={on_select ? handleRowClick : null}
            interactive={!!on_select}
            multiSelect={!!multi_select}
            selectedValues={selected_values}
            selectField={select_field}
          />
        );

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
