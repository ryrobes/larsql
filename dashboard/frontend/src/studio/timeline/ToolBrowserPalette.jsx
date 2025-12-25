import React, { useState, useEffect, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import { Tooltip } from '../../components/RichTooltip';

/**
 * ToolBrowserPalette - Draggable tool browser for cascade building
 *
 * Features:
 * - Fetches tools from tool_manifest_vectors and hf_spaces tables
 * - Groups by tool type (function, cascade, memory, validator, hf_space)
 * - Draggable tool pills (not functional yet)
 * - Separate sections for built-in tools and HuggingFace Spaces
 */

// Tool type metadata for icons and colors
const TOOL_TYPE_CONFIG = {
  function: { icon: 'mdi:function-variant', color: '#60a5fa', label: 'Function' },
  cascade: { icon: 'mdi:water', color: '#a78bfa', label: 'Cascade' },
  memory: { icon: 'mdi:database-outline', color: '#34d399', label: 'Memory' },
  validator: { icon: 'mdi:shield-check', color: '#f472b6', label: 'Validator' },
  hf_space: { icon: 'mdi:cube-outline', color: '#fbbf24', label: 'HF Space' },
};

/**
 * Draggable tool pill
 */
function ToolPill({ tool, isHfSpace = false }) {
  const toolType = isHfSpace ? 'hf_space' : tool.type;
  const config = TOOL_TYPE_CONFIG[toolType] || TOOL_TYPE_CONFIG.function;

  const toolName = isHfSpace ? tool.name : tool.name;
  const toolId = isHfSpace ? tool.id : tool.name;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `tool-${toolId}`,
    data: { type: 'tool', toolId: toolId, toolType: toolType },
  });

  // Build tooltip content
  const tooltipContent = isHfSpace
    ? `${tool.author}/${tool.name}\nSDK: ${tool.sdk || 'unknown'}\nStatus: ${tool.status || 'unknown'}`
    : tool.description;

  // Status indicator color for HF Spaces
  const statusColor = isHfSpace
    ? tool.status === 'RUNNING' ? '#34d399'
      : tool.status === 'SLEEPING' ? '#fbbf24'
      : tool.status === 'PAUSED' ? '#94a3b8'
      : '#f87171'
    : null;

  return (
    <Tooltip label={tooltipContent}>
      <div
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        className={`model-pill model-pill-${toolType} ${isDragging ? 'dragging' : ''}`}
        style={{ borderColor: config.color + '34' }}
      >
        <Icon icon={config.icon} width="12" style={{ color: config.color, opacity: 0.8 }} />
        <span className="model-pill-name" style={{ color: config.color }}>
          {toolName}
        </span>
        {isHfSpace && (
          <span
            className="model-pill-context"
            style={{
              fontSize: '9px',
              opacity: 0.7,
              color: statusColor,
              fontWeight: tool.status === 'RUNNING' ? '600' : '400'
            }}
          >
            {tool.status || '?'}
          </span>
        )}
      </div>
    </Tooltip>
  );
}

/**
 * Collapsible tool group
 */
function ToolGroup({ title, iconName, iconImage, tools, isHfSpace = false, defaultOpen = true }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);

  if (tools.length === 0) return null;

  return (
    <div className="model-group">
      <div
        className="model-group-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="model-group-chevron"
        />
        {iconImage ? (
          <img
            src={iconImage}
            alt={title}
            className="model-group-icon"
            style={{ width: '12px', height: '12px', objectFit: 'contain', opacity: 0.6 }}
          />
        ) : (
          <Icon icon={iconName} width="12" className="model-group-icon" />
        )}
        <span className="model-group-title">{title}</span>
        <span className="model-group-count">{tools.length}</span>
      </div>

      {isExpanded && (
        <div className="model-group-content">
          {tools.map(t => (
            <ToolPill key={isHfSpace ? t.id : t.name} tool={t} isHfSpace={isHfSpace} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main ToolBrowserPalette component
 */
function ToolBrowserPalette() {
  const [tools, setTools] = useState([]);
  const [hfSpaces, setHfSpaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchText, setSearchText] = useState('');
  const [isExpanded, setIsExpanded] = useState(false); // Default to collapsed

  // Fetch tools from backend
  useEffect(() => {
    let mounted = true;

    const fetchTools = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch('/api/studio/tools');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (mounted) {
          setTools(data.tools || []);
          setHfSpaces(data.hf_spaces || []);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError(err.message);
          setLoading(false);
        }
      }
    };

    fetchTools();

    return () => {
      mounted = false;
    };
  }, []);

  // Filter tools by search text
  const filteredTools = useMemo(() => {
    let filtered = tools;

    if (searchText.trim()) {
      const query = searchText.toLowerCase();
      filtered = filtered.filter(
        t =>
          t.name.toLowerCase().includes(query) ||
          t.description?.toLowerCase().includes(query)
      );
    }

    return filtered;
  }, [tools, searchText]);

  // Filter HF Spaces by search text
  const filteredHfSpaces = useMemo(() => {
    let filtered = hfSpaces;

    if (searchText.trim()) {
      const query = searchText.toLowerCase();
      filtered = filtered.filter(
        s =>
          s.id.toLowerCase().includes(query) ||
          s.name.toLowerCase().includes(query) ||
          s.author.toLowerCase().includes(query)
      );
    }

    return filtered;
  }, [hfSpaces, searchText]);

  // Group tools by type
  const groupedTools = useMemo(() => {
    const groups = {};

    filteredTools.forEach(tool => {
      const type = tool.type || 'function';
      if (!groups[type]) {
        groups[type] = [];
      }
      groups[type].push(tool);
    });

    // Sort by type priority: function, cascade, memory, validator
    const priority = ['function', 'cascade', 'memory', 'validator'];
    const sortedTypes = Object.keys(groups).sort((a, b) => {
      const aIdx = priority.indexOf(a);
      const bIdx = priority.indexOf(b);
      if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
      if (aIdx !== -1) return -1;
      if (bIdx !== -1) return 1;
      return a.localeCompare(b);
    });

    return sortedTypes.map(type => ({
      type,
      tools: groups[type].sort((a, b) => a.name.localeCompare(b.name)),
    }));
  }, [filteredTools]);

  if (loading) {
    return (
      <div className="nav-section model-browser-section">
        <div
          className="nav-section-header"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            className="nav-chevron"
          />
          <Icon icon="mdi:tools" className="nav-section-icon" />
          <span className="nav-section-title">Tools</span>
        </div>
        {isExpanded && (
          <div className="model-browser-loading">
            <Icon icon="mdi:loading" className="spinning" width="16" />
            <span>Loading tools...</span>
          </div>
        )}
      </div>
    );
  }

  if (error) {
    return (
      <div className="nav-section model-browser-section">
        <div
          className="nav-section-header"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            className="nav-chevron"
          />
          <Icon icon="mdi:tools" className="nav-section-icon" />
          <span className="nav-section-title">Tools</span>
        </div>
        {isExpanded && (
          <div className="model-browser-error">
            <Icon icon="mdi:alert-circle" width="16" />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  const totalTools = filteredTools.length + filteredHfSpaces.length;

  return (
    <div className="nav-section model-browser-section">
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:tools" className="nav-section-icon" />
        <span className="nav-section-title">Tools</span>
        <span className="nav-section-count">{totalTools}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content model-browser-content">
          {/* Search bar */}
          <div className="model-search-bar">
            <Icon icon="mdi:magnify" width="14" className="model-search-icon" />
            <input
              type="text"
              placeholder="Search tools..."
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              className="model-search-input"
            />
            {searchText && (
              <Icon
                icon="mdi:close"
                width="14"
                className="model-search-clear"
                onClick={() => setSearchText('')}
              />
            )}
          </div>

          {/* Tool groups by type */}
          <div className="model-groups-container">
            {groupedTools.length === 0 && filteredHfSpaces.length === 0 && (
              <div className="model-browser-empty">
                <Icon icon="mdi:folder-open-outline" width="24" />
                <span>No tools found</span>
              </div>
            )}

            {/* Built-in/Cascade tools grouped by type */}
            {groupedTools.map(({ type, tools }) => (
              <ToolGroup
                key={type}
                title={TOOL_TYPE_CONFIG[type]?.label || type}
                iconName={TOOL_TYPE_CONFIG[type]?.icon || 'mdi:function-variant'}
                tools={tools}
                defaultOpen={type === 'function'}
              />
            ))}

            {/* HuggingFace Spaces */}
            {filteredHfSpaces.length > 0 && (
              <ToolGroup
                title="HuggingFace Spaces"
                iconImage="/huggingface_logo-noborder_greyscale.svg"
                tools={filteredHfSpaces}
                isHfSpace={true}
                defaultOpen={false}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default ToolBrowserPalette;
