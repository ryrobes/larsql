import React from 'react';
import { Icon } from '@iconify/react';
import './ToolList.css';

// Tool type icons and labels
const TOOL_TYPE_CONFIG = {
  'function': { icon: 'mdi:function', label: 'Python', color: '#60a5fa' },
  'declarative:shell': { icon: 'mdi:bash', label: 'Shell', color: '#34d399' },
  'declarative:http': { icon: 'mdi:web', label: 'HTTP', color: '#a78bfa' },
  'declarative:python': { icon: 'mdi:language-python', label: 'Python', color: '#fbbf24' },
  'declarative:composite': { icon: 'mdi:vector-combine', label: 'Composite', color: '#fb923c' },
  'declarative:gradio': { icon: 'mdi:robot-outline', label: 'Gradio', color: '#f472b6' },
  'cascade': { icon: 'mdi:ship-wheel', label: 'Cascade', color: '#f87171' },
  'gradio': { icon: 'mdi:robot', label: 'Gradio', color: '#fb923c' },
  'harbor': { icon: 'mdi:harbor', label: 'Harbor', color: '#0ea5e9' },
  'memory': { icon: 'mdi:database', label: 'Memory', color: '#8b5cf6' },
};

function ToolTypeIcon({ type }) {
  // Match type prefix - find the longest matching key
  const configKey = Object.keys(TOOL_TYPE_CONFIG)
    .filter(k => type.startsWith(k))
    .sort((a, b) => b.length - a.length)[0] || 'function';

  const config = TOOL_TYPE_CONFIG[configKey];

  return (
    <span className="tool-type-badge" style={{
      color: config.color,
      borderColor: config.color + '40',
      background: config.color + '15'
    }}>
      <Icon icon={config.icon} width="14" />
      <span>{config.label}</span>
    </span>
  );
}

function ToolList({
  tools,
  selectedTool,
  onSelectTool,
  filterText,
  filterType,
  onFilterTextChange,
  onFilterTypeChange,
  loading,
  error
}) {
  // Count by type - group declarative types together
  const typeCounts = tools.reduce((acc, [name, tool]) => {
    let typeKey;
    if (tool.type.startsWith('declarative:')) {
      typeKey = 'declarative';
    } else {
      typeKey = tool.type;
    }
    acc[typeKey] = (acc[typeKey] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="tool-list-container">
      {/* Filters */}
      <div className="tool-filters">
        <div className="search-box">
          <Icon icon="mdi:magnify" width="18" />
          <input
            type="text"
            placeholder="Search tools..."
            value={filterText}
            onChange={(e) => onFilterTextChange(e.target.value)}
          />
        </div>

        <div className="type-filter">
          <select value={filterType} onChange={(e) => onFilterTypeChange(e.target.value)}>
            <option value="all">All Types ({tools.length})</option>
            <option value="function">Python Functions ({typeCounts.function || 0})</option>
            <option value="declarative">Declarative ({typeCounts.declarative || 0})</option>
            <option value="cascade">Cascades ({typeCounts.cascade || 0})</option>
            <option value="gradio">Gradio Tools ({typeCounts.gradio || 0})</option>
            <option value="harbor">Harbor Tools ({typeCounts.harbor || 0})</option>
            <option value="memory">Memory Banks ({typeCounts.memory || 0})</option>
          </select>
        </div>
      </div>

      {/* Tool List */}
      {loading && (
        <div className="tool-list-loading">
          <Icon icon="mdi:loading" width="24" className="spin" />
          <span>Loading tools...</span>
        </div>
      )}

      {error && (
        <div className="tool-list-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && (
        <div className="tool-items">
          {tools.map(([name, tool]) => (
            <div
              key={name}
              className={`tool-item ${selectedTool === name ? 'selected' : ''}`}
              onClick={() => onSelectTool(name)}
            >
              <div className="tool-item-header">
                <span className="tool-name">{name}</span>
                <ToolTypeIcon type={tool.type} />
              </div>
              <div className="tool-description">
                {tool.description ? tool.description.split('\n')[0].substring(0, 120) : 'No description'}
                {tool.description && tool.description.split('\n')[0].length > 120 ? '...' : ''}
              </div>
            </div>
          ))}

          {tools.length === 0 && (
            <div className="no-tools">
              <Icon icon="mdi:magnify-remove-outline" width="32" />
              <span>No tools match your filters</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ToolList;
