import React, { useState, useEffect, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import { Tooltip } from '../../components/RichTooltip';

/**
 * ToolBrowserPalette - Draggable trait browser for cascade building
 *
 * Features:
 * - Fetches traits from tool_manifest_vectors and hf_spaces tables
 * - Groups by trait type (function, cascade, memory, validator, hf_space)
 * - Special "manifest" trait for dynamic trait selection
 * - Draggable trait pills
 * - Separate sections for built-in traits and HuggingFace Spaces
 */

// Trait type metadata for icons and colors
const TRAIT_TYPE_CONFIG = {
  function: { icon: 'mdi:function-variant', color: '#60a5fa', label: 'Function' },
  cascade: { icon: 'mdi:water', color: '#a78bfa', label: 'Cascade' },
  memory: { icon: 'mdi:database-outline', color: '#34d399', label: 'Memory' },
  validator: { icon: 'mdi:shield-check', color: '#f472b6', label: 'Validator' },
  hf_space: { icon: 'mdi:cube-outline', color: '#fbbf24', label: 'HF Space' },
  manifest: { icon: 'mdi:auto-fix', color: '#ff006e', label: 'Manifest (Auto)' },
};

/**
 * Special Manifest pill - magic trait that auto-selects tools based on context
 */
const ManifestPill = React.memo(() => {
  const config = TRAIT_TYPE_CONFIG.manifest;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: 'trait-manifest',
    data: { type: 'tool', toolId: 'manifest', toolType: 'manifest' },
  });

  return (
    <Tooltip
      label="manifest (Quartermaster)"
      description="Magic trait that analyzes your cell's instructions and conversation context to automatically inject the most relevant tools. The Quartermaster intelligently selects tools based on what the LLM is trying to accomplish."
      placement="right"
    >
      <div
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        className={`model-pill model-pill-manifest ${isDragging ? 'dragging' : ''}`}
        style={{
          borderColor: config.color + '44',
          background: `linear-gradient(135deg, rgba(255, 0, 110, 0.08), rgba(167, 139, 250, 0.08))`,
          borderWidth: '1.5px',
        }}
      >
        <Icon icon={config.icon} width="14" style={{ color: config.color, opacity: 0.9 }} />
        <span className="model-pill-name" style={{ color: config.color, fontWeight: 600 }}>
          manifest
        </span>
        <span
          className="model-pill-context"
          style={{
            fontSize: '8px',
            color: config.color,
            opacity: 0.7,
            fontWeight: 500,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
          }}
        >
          AUTO
        </span>
      </div>
    </Tooltip>
  );
});

ManifestPill.displayName = 'ManifestPill';

/**
 * Draggable trait pill
 */
function TraitPill({ tool, isHfSpace = false }) {
  const traitType = isHfSpace ? 'hf_space' : tool.type;
  const config = TRAIT_TYPE_CONFIG[traitType] || TRAIT_TYPE_CONFIG.function;

  const traitName = isHfSpace ? tool.name : tool.name;
  const traitId = isHfSpace ? tool.id : tool.name;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `trait-${traitId}`,
    data: { type: 'tool', toolId: traitId, toolType: traitType },
  });

  // Build tooltip content with proper label/description split
  let tooltipLabel, tooltipDescription;

  if (isHfSpace) {
    tooltipLabel = `${tool.author}/${tool.name}`;
    tooltipDescription = `HuggingFace Space • SDK: ${tool.sdk || 'unknown'} • Status: ${tool.status || 'unknown'}`;
  } else {
    tooltipLabel = traitName;
    tooltipDescription = tool.description || 'No description available';
  }

  // Status indicator color for HF Spaces
  const statusColor = isHfSpace
    ? tool.status === 'RUNNING' ? '#34d399'
      : tool.status === 'SLEEPING' ? '#fbbf24'
      : tool.status === 'PAUSED' ? '#94a3b8'
      : '#f87171'
    : null;

  return (
    <Tooltip
      label={tooltipLabel}
      description={tooltipDescription}
      placement="right"
    >
      <div
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        className={`model-pill model-pill-${traitType} ${isDragging ? 'dragging' : ''}`}
        style={{ borderColor: config.color + '34' }}
      >
        <Icon icon={config.icon} width="12" style={{ color: config.color, opacity: 0.8 }} />
        <span className="model-pill-name" style={{ color: config.color }}>
          {traitName}
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
 * Collapsible trait group
 */
function TraitGroup({ title, iconName, iconImage, tools, isHfSpace = false, defaultOpen = true }) {
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
            <TraitPill key={isHfSpace ? t.id : t.name} tool={t} isHfSpace={isHfSpace} />
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
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-traits-expanded');
      return saved !== null ? saved === 'true' : false;
    } catch {
      return false;
    }
  });

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-traits-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

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
          <Icon icon="mdi:rabbit" className="nav-section-icon" />
          <span className="nav-section-title">Traits</span>
        </div>
        {isExpanded && (
          <div className="model-browser-loading">
            <Icon icon="mdi:loading" className="spinning" width="16" />
            <span>Loading traits...</span>
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
          <Icon icon="mdi:rabbit" className="nav-section-icon" />
          <span className="nav-section-title">Traits</span>
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

  const totalTraits = filteredTools.length + filteredHfSpaces.length + 1; // +1 for manifest

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
        <Icon icon="mdi:rabbit" className="nav-section-icon" />
        <span className="nav-section-title">Traits</span>
        <span className="nav-section-count">{totalTraits}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content model-browser-content">
          {/* Search bar */}
          <div className="model-search-bar">
            <Icon icon="mdi:magnify" width="14" className="model-search-icon" />
            <input
              type="text"
              placeholder="Search traits..."
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

          {/* Trait groups by type */}
          <div className="model-groups-container">
            {/* Special Manifest pill - always at top */}
            {!searchText && (
              <div style={{ padding: '8px 8px 12px', borderBottom: '1px solid rgba(26, 22, 40, 0.5)' }}>
                <ManifestPill />
              </div>
            )}

            {groupedTools.length === 0 && filteredHfSpaces.length === 0 && searchText && (
              <div className="model-browser-empty">
                <Icon icon="mdi:folder-open-outline" width="24" />
                <span>No traits found</span>
              </div>
            )}

            {/* Built-in/Cascade traits grouped by type */}
            {groupedTools.map(({ type, tools }) => (
              <TraitGroup
                key={type}
                title={TRAIT_TYPE_CONFIG[type]?.label || type}
                iconName={TRAIT_TYPE_CONFIG[type]?.icon || 'mdi:function-variant'}
                tools={tools}
                defaultOpen={type === 'function'}
              />
            ))}

            {/* HuggingFace Spaces */}
            {filteredHfSpaces.length > 0 && (
              <TraitGroup
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
