import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './FilterPanel.css';

/**
 * Content type definitions with icons and colors
 *
 * Note: 'tool_call' is a hierarchical type - filtering by it will match
 * all subtypes like 'tool_call:request_decision', 'tool_call:brave_web_search', etc.
 */
const CONTENT_TYPES = [
  { type: 'image', icon: 'mdi:image', color: 'var(--color-accent-pink)', label: 'Image' },
  { type: 'chart', icon: 'mdi:chart-line', color: 'var(--color-accent-green)', label: 'Chart' },
  { type: 'table', icon: 'mdi:table', color: 'var(--color-accent-yellow)', label: 'Table' },
  { type: 'tool_call', icon: 'mdi:tools', color: 'var(--color-accent-orange)', label: 'Tool Call', expandable: true },
  { type: 'markdown', icon: 'mdi:language-markdown', color: 'var(--color-accent-purple)', label: 'Markdown' },
  { type: 'json', icon: 'mdi:code-json', color: 'var(--color-accent-blue)', label: 'JSON' },
  { type: 'text', icon: 'mdi:text', color: 'var(--color-accent-cyan)', label: 'Text' },
  { type: 'error', icon: 'mdi:alert-circle', color: 'var(--color-error)', label: 'Error' },
];

/**
 * Format tool name for display (e.g., 'brave_web_search' -> 'brave web search')
 */
const formatToolName = (toolName) => {
  return toolName.replace(/_/g, ' ');
};

/**
 * FilterPanel - Left sidebar with filter controls
 */
const FilterPanel = ({
  timeFilter,
  onTimeFilterChange,
  allCascadeIds,
  selectedCascades,
  onSelectedCascadesChange,
  selectedTags,
  onSelectedTagsChange,
  availableTags,
  selectedContentTypes,
  onSelectedContentTypesChange,
}) => {
  // Content type statistics from API
  const [contentTypeStats, setContentTypeStats] = useState({});
  const [toolCallSubtypes, setToolCallSubtypes] = useState([]);
  const [toolCallExpanded, setToolCallExpanded] = useState(false);

  // Fetch content type statistics
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await fetch(`http://localhost:5050/api/outputs/content-types?time_filter=${timeFilter}`);
        const data = await response.json();

        if (data.content_types) {
          // Build stats lookup
          const stats = {};
          const subtypes = [];

          for (const ct of data.content_types) {
            stats[ct.type] = ct.count;
            if (ct.is_subtype && ct.base_type === 'tool_call') {
              subtypes.push({
                type: ct.type,
                toolName: ct.type.split(':')[1],
                count: ct.count
              });
            }
          }

          setContentTypeStats(stats);
          setToolCallSubtypes(subtypes);
        }
      } catch (err) {
        console.error('[FilterPanel] Error fetching content type stats:', err);
      }
    };

    fetchStats();
  }, [timeFilter]);

  const handleContentTypeToggle = (type) => {
    if (selectedContentTypes.includes(type)) {
      // If deselecting a base type, also deselect its subtypes
      if (type === 'tool_call') {
        const filtered = selectedContentTypes.filter(t => t !== type && !t.startsWith('tool_call:'));
        onSelectedContentTypesChange(filtered);
      } else {
        onSelectedContentTypesChange(selectedContentTypes.filter(t => t !== type));
      }
    } else {
      // If selecting a subtype, remove the base type (more specific filter)
      if (type.startsWith('tool_call:')) {
        const filtered = selectedContentTypes.filter(t => t !== 'tool_call');
        onSelectedContentTypesChange([...filtered, type]);
      } else if (type === 'tool_call') {
        // If selecting base type, remove all subtypes (broader filter)
        const filtered = selectedContentTypes.filter(t => !t.startsWith('tool_call:'));
        onSelectedContentTypesChange([...filtered, type]);
      } else {
        onSelectedContentTypesChange([...selectedContentTypes, type]);
      }
    }
  };

  const handleClearContentTypes = () => {
    onSelectedContentTypesChange([]);
  };

  const handleCascadeToggle = (cascadeId) => {
    if (selectedCascades.includes(cascadeId)) {
      onSelectedCascadesChange(selectedCascades.filter(id => id !== cascadeId));
    } else {
      onSelectedCascadesChange([...selectedCascades, cascadeId]);
    }
  };

  const handleClearCascades = () => {
    onSelectedCascadesChange([]);
  };

  const handleTagToggle = (tagName) => {
    if (selectedTags.includes(tagName)) {
      onSelectedTagsChange(selectedTags.filter(t => t !== tagName));
    } else {
      onSelectedTagsChange([...selectedTags, tagName]);
    }
  };

  const handleClearTags = () => {
    onSelectedTagsChange([]);
  };

  // Check if any tool_call subtype is selected
  const hasToolCallSubtypeSelected = selectedContentTypes.some(t => t.startsWith('tool_call:'));

  return (
    <div className="outputs-filter-panel">
      {/* Time Filter */}
      <div className="filter-section">
        <div className="filter-section-header">
          <Icon icon="mdi:clock-outline" width="14" />
          <span>Time</span>
        </div>
        <div className="filter-options">
          <button
            className={`filter-chip ${timeFilter === 'today' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('today')}
          >
            Today
          </button>
          <button
            className={`filter-chip ${timeFilter === 'week' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('week')}
          >
            This Week
          </button>
          <button
            className={`filter-chip ${timeFilter === 'month' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('month')}
          >
            This Month
          </button>
          <button
            className={`filter-chip ${timeFilter === 'all' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('all')}
          >
            All Time
          </button>
        </div>
      </div>

      {/* Tags Filter */}
      <div className="filter-section">
        <div className="filter-section-header">
          <Icon icon="mdi:tag-multiple" width="14" />
          <span>Tags</span>
          {selectedTags.length > 0 && (
            <button className="filter-clear-btn" onClick={handleClearTags}>
              Clear ({selectedTags.length})
            </button>
          )}
        </div>
        <div className="filter-tags-list">
          {(!availableTags || availableTags.length === 0) ? (
            <div className="filter-empty">No tags yet</div>
          ) : (
            availableTags.map(tag => (
              <label
                key={tag.tag_name}
                className={`filter-tag-item ${selectedTags.includes(tag.tag_name) ? 'active' : ''}`}
                style={{ '--tag-color': tag.tag_color }}
              >
                <input
                  type="checkbox"
                  checked={selectedTags.includes(tag.tag_name)}
                  onChange={() => handleTagToggle(tag.tag_name)}
                />
                <div className="tag-color-dot" />
                <span className="tag-name">{tag.tag_name}</span>
                {tag.count > 0 && <span className="tag-count">{tag.count}</span>}
              </label>
            ))
          )}
        </div>
      </div>

      {/* Content Type Filter */}
      <div className="filter-section">
        <div className="filter-section-header">
          <Icon icon="mdi:palette" width="14" />
          <span>Content Types</span>
          {selectedContentTypes.length > 0 && (
            <button className="filter-clear-btn" onClick={handleClearContentTypes}>
              Clear ({selectedContentTypes.length})
            </button>
          )}
        </div>
        <div className="filter-content-types">
          {CONTENT_TYPES.map(({ type, icon, color, label, expandable }) => {
            const count = contentTypeStats[type] || 0;
            const isSelected = selectedContentTypes.includes(type);
            const isToolCall = type === 'tool_call';
            const showExpander = isToolCall && toolCallSubtypes.length > 0;

            return (
              <React.Fragment key={type}>
                <label
                  className={`content-type-item ${isSelected ? 'active' : ''} ${count === 0 ? 'disabled' : ''}`}
                  style={{ '--type-color': color }}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => handleContentTypeToggle(type)}
                    disabled={count === 0}
                  />
                  <div className="type-color-indicator" />
                  <Icon icon={icon} width="12" className="type-icon" />
                  <span className="type-label">{label}</span>
                  {count > 0 && <span className="type-count">{count}</span>}
                  {showExpander && (
                    <button
                      className={`type-expander ${toolCallExpanded ? 'expanded' : ''}`}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setToolCallExpanded(!toolCallExpanded);
                      }}
                      title={toolCallExpanded ? 'Collapse tool types' : 'Expand tool types'}
                    >
                      <Icon icon="mdi:chevron-down" width="14" />
                    </button>
                  )}
                </label>

                {/* Tool Call Subtypes */}
                {isToolCall && toolCallExpanded && toolCallSubtypes.length > 0 && (
                  <div className="tool-call-subtypes">
                    {toolCallSubtypes.map(({ type: subtype, toolName, count: subtypeCount }) => {
                      const isSubtypeSelected = selectedContentTypes.includes(subtype);
                      return (
                        <label
                          key={subtype}
                          className={`content-type-item subtype ${isSubtypeSelected ? 'active' : ''}`}
                          style={{ '--type-color': color }}
                        >
                          <input
                            type="checkbox"
                            checked={isSubtypeSelected}
                            onChange={() => handleContentTypeToggle(subtype)}
                          />
                          <div className="type-color-indicator" />
                          <span className="type-label">{formatToolName(toolName)}</span>
                          <span className="type-count">{subtypeCount}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* Cascade Filter */}
      <div className="filter-section cascades-filter">
        <div className="filter-section-header">
          <Icon icon="mdi:sitemap" width="14" />
          <span>Cascades</span>
          {selectedCascades.length > 0 && (
            <button className="filter-clear-btn" onClick={handleClearCascades}>
              Clear ({selectedCascades.length})
            </button>
          )}
        </div>
        <div className="filter-cascades-list">
          {allCascadeIds.length === 0 ? (
            <div className="filter-empty">No cascades</div>
          ) : (
            allCascadeIds.map(cascadeId => (
              <label key={cascadeId} className="filter-cascade-item">
                <input
                  type="checkbox"
                  checked={selectedCascades.includes(cascadeId)}
                  onChange={() => handleCascadeToggle(cascadeId)}
                />
                <span className="cascade-name">{cascadeId}</span>
              </label>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default FilterPanel;
