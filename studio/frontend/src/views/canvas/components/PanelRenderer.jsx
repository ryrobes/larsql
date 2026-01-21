import React from 'react';
import { Icon } from '@iconify/react';
import MermaidPanel from './MermaidPanel';
import DataGridPanel from './DataGridPanel';
import MetricPanel from './MetricPanel';
import PlotlyPanel from './PlotlyPanel';
import VegaLitePanel from './VegaLitePanel';
import SliderPanel from './SliderPanel';
import DropdownPanel from './DropdownPanel';
import DateRangePanel from './DateRangePanel';
import TogglePanel from './TogglePanel';
import SparklinePanel from './SparklinePanel';
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
  const { name, content, type, on_select, multi_select, selected_values, selected_value, select_field, isAutoMetric, hide_border, hide_title } = panel;

  // Get icon for panel type
  const getIcon = () => {
    switch (type) {
      case 'mermaid-graph':
        return 'mdi:graph';
      case 'mermaid-timeline':
        return 'mdi:timeline';
      case 'data-grid':
        return 'mdi:table';
      case 'metric':
        return 'mdi:counter';
      case 'plotly':
        return 'mdi:chart-line';
      case 'vega-lite':
        return 'mdi:chart-bar';
      case 'slider':
        return 'mdi:tune-vertical';
      case 'dropdown':
        return 'mdi:form-dropdown';
      case 'daterange':
        return 'mdi:calendar-range';
      case 'toggle':
        return 'mdi:toggle-switch';
      case 'sparkline':
        return 'mdi:chart-timeline-variant';
      default:
        return 'mdi:text';
    }
  };

  // Handle data click from DataGridPanel or chart panels
  const handleDataClick = (rowData) => {
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

      case 'metric':
        // For auto-metric, extract the single value from the data
        if (isAutoMetric && Array.isArray(content) && content.length === 1) {
          const row = content[0];
          const keys = Object.keys(row).filter(k => k !== 'format');
          const value = row[keys[0]];
          return <MetricPanel content={value} isAuto={true} />;
        }
        return <MetricPanel content={content} isAuto={false} />;

      case 'plotly':
        return (
          <PlotlyPanel
            content={content}
            onClick={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
            selectField={select_field}
          />
        );

      case 'vega-lite':
        return (
          <VegaLitePanel
            content={content}
            onClick={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
            selectField={select_field}
          />
        );

      case 'data-grid':
        return (
          <DataGridPanel
            content={content}
            onRowClick={on_select ? handleDataClick : null}
            interactive={!!on_select}
            multiSelect={!!multi_select}
            selectedValues={selected_values}
            selectedValue={selected_value}
            selectField={select_field}
          />
        );

      case 'slider':
        return (
          <SliderPanel
            content={content}
            onChange={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
          />
        );

      case 'dropdown':
        return (
          <DropdownPanel
            content={content}
            onChange={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
          />
        );

      case 'daterange':
        return (
          <DateRangePanel
            content={content}
            onChange={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
          />
        );

      case 'toggle':
        return (
          <TogglePanel
            content={content}
            onChange={on_select ? handleDataClick : null}
            interactive={!!on_select}
            selectedValue={selected_value}
          />
        );

      case 'sparkline':
        return <SparklinePanel content={content} />;

      case 'text':
      default:
        return <TextPanel content={content} />;
    }
  };

  // Build class names based on display options
  const panelClasses = [
    'canvas-panel',
    hide_border && 'canvas-panel-no-border',
    hide_title && 'canvas-panel-no-title',
  ].filter(Boolean).join(' ');

  return (
    <div className={panelClasses} style={style}>
      {!hide_title && (
        <div className="canvas-panel-header">
          <Icon icon={getIcon()} width="14" />
          <span className="canvas-panel-title">{name}</span>
          <span className="canvas-panel-type">{type}</span>
        </div>
      )}
      <div className="canvas-panel-content">
        {renderContent()}
      </div>
    </div>
  );
};

export default PanelRenderer;
