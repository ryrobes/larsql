import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './ContextBuilder.css';

/**
 * ContextBuilder - Visual UI for configuring selective context
 *
 * Features:
 * - Quick presets (clean slate, previous, all, custom)
 * - Visual source builder with cell selection
 * - Include options (images, output, messages, state)
 * - Filter configurations for images and messages
 * - Exclusion list for "all" mode
 */
function ContextBuilder({ value, onChange, otherCells = [], cellName }) {
  const [expandedSource, setExpandedSource] = useState(null);

  // Normalize value to ensure consistent structure
  const context = useMemo(() => ({
    from: value?.from || [],
    exclude: value?.exclude || [],
    include_input: value?.include_input !== false, // Default true
  }), [value]);

  // Determine current mode based on context.from
  const currentMode = useMemo(() => {
    const from = context.from;
    if (!from || from.length === 0) return 'clean';
    if (from.length === 1 && (from[0] === 'previous' || from[0] === 'prev')) return 'previous';
    if (from.length === 1 && from[0] === 'all') return 'all';
    return 'custom';
  }, [context.from]);

  // Update context
  const updateContext = (updates) => {
    const newContext = { ...context, ...updates };
    // Clean up empty arrays
    if (newContext.from?.length === 0) delete newContext.from;
    if (newContext.exclude?.length === 0) delete newContext.exclude;
    // Clean up default value
    if (newContext.include_input === true) delete newContext.include_input;
    // If empty, return undefined
    if (Object.keys(newContext).length === 0) {
      onChange(undefined);
    } else {
      onChange(newContext);
    }
  };

  // Preset handlers
  const handlePreset = (preset) => {
    switch (preset) {
      case 'clean':
        onChange(undefined);
        break;
      case 'previous':
        onChange({ from: ['previous'] });
        break;
      case 'all':
        onChange({ from: ['all'] });
        break;
      case 'custom':
        // Keep existing or start with previous
        if (currentMode === 'clean') {
          onChange({ from: ['previous'] });
        }
        break;
      default:
        break;
    }
  };

  // Add a source to the from list
  const addSource = (source) => {
    const currentFrom = context.from || [];
    // If source is already a keyword like 'all', replace
    if (source === 'all') {
      updateContext({ from: ['all'] });
    } else if (source === 'first' || source === 'previous') {
      // Add keyword if not already present
      if (!currentFrom.includes(source)) {
        updateContext({ from: [...currentFrom.filter(s => s !== 'all'), source] });
      }
    } else {
      // Add cell name
      const existing = currentFrom.filter(s =>
        typeof s === 'string' ? s !== source : s.cell !== source
      );
      updateContext({ from: [...existing.filter(s => s !== 'all'), source] });
    }
  };

  // Remove a source from the list
  const removeSource = (sourceIndex) => {
    const newFrom = [...context.from];
    newFrom.splice(sourceIndex, 1);
    updateContext({ from: newFrom });
  };

  // Update a specific source's configuration
  const updateSource = (sourceIndex, updates) => {
    const newFrom = [...context.from];
    const current = newFrom[sourceIndex];

    // If it's a string, convert to object
    if (typeof current === 'string') {
      newFrom[sourceIndex] = { cell: current, ...updates };
    } else {
      newFrom[sourceIndex] = { ...current, ...updates };
    }

    // If updates result in default config, simplify back to string
    const source = newFrom[sourceIndex];
    if (typeof source === 'object') {
      const isDefault = (
        (!source.include || JSON.stringify(source.include) === '["images","output"]') &&
        (!source.images_filter || source.images_filter === 'all') &&
        (!source.messages_filter || source.messages_filter === 'all') &&
        (!source.as_role || source.as_role === 'user')
      );
      if (isDefault) {
        newFrom[sourceIndex] = source.cell;
      }
    }

    updateContext({ from: newFrom });
  };

  // Toggle exclusion
  const toggleExclude = (cellName) => {
    const exclude = context.exclude || [];
    if (exclude.includes(cellName)) {
      updateContext({ exclude: exclude.filter(p => p !== cellName) });
    } else {
      updateContext({ exclude: [...exclude, cellName] });
    }
  };

  // Get display name for a source
  const getSourceDisplay = (source) => {
    if (typeof source === 'string') {
      if (source === 'previous' || source === 'prev') return { name: 'previous', icon: 'mdi:arrow-left', color: 'ocean' };
      if (source === 'first') return { name: 'first', icon: 'mdi:ray-start', color: 'teal' };
      if (source === 'all') return { name: 'all', icon: 'mdi:select-all', color: 'brass' };
      return { name: source, icon: 'mdi:view-sequential', color: 'default' };
    }
    return { name: source.cell, icon: 'mdi:view-sequential', color: 'default', config: source };
  };

  // Available cells to add (not already in from)
  const availableCells = useMemo(() => {
    const usedCells = (context.from || []).map(s =>
      typeof s === 'string' ? s : s.cell
    );
    return otherCells.filter(p => !usedCells.includes(p));
  }, [otherCells, context.from]);

  return (
    <div className="context-builder">
      {/* Intro */}
      <div className="drawer-intro">
        <Icon icon="mdi:information-outline" width="14" />
        <p>
          <strong>Context</strong> controls what information flows into this cell from prior cells.
          By default cells start clean. Use <strong>previous</strong> for linear chains or <strong>custom</strong> for fine-grained control.
        </p>
      </div>

      {/* Quick Presets */}
      <div className="context-presets">
        <button
          className={`preset-btn ${currentMode === 'clean' ? 'active' : ''}`}
          onClick={() => handlePreset('clean')}
          title="Cell starts with no prior context"
        >
          <Icon icon="mdi:broom" width="14" />
          <span>Clean Slate</span>
        </button>
        <button
          className={`preset-btn ${currentMode === 'previous' ? 'active' : ''}`}
          onClick={() => handlePreset('previous')}
          title="Receive context from the previous cell only"
        >
          <Icon icon="mdi:arrow-left" width="14" />
          <span>Previous</span>
        </button>
        <button
          className={`preset-btn ${currentMode === 'all' ? 'active' : ''}`}
          onClick={() => handlePreset('all')}
          title="Receive context from all prior cells (snowball)"
        >
          <Icon icon="mdi:select-all" width="14" />
          <span>All</span>
        </button>
        <button
          className={`preset-btn ${currentMode === 'custom' ? 'active' : ''}`}
          onClick={() => handlePreset('custom')}
          title="Select specific cells and configure what to include"
        >
          <Icon icon="mdi:tune" width="14" />
          <span>Custom</span>
        </button>
      </div>

      {/* Mode Description */}
      <div className="mode-description">
        {currentMode === 'clean' && (
          <>
            <Icon icon="mdi:information-outline" width="14" />
            <span>This cell starts fresh with no context from prior cells.</span>
          </>
        )}
        {currentMode === 'previous' && (
          <>
            <Icon icon="mdi:link-variant" width="14" />
            <span>This cell receives output and images from the immediately previous cell.</span>
          </>
        )}
        {currentMode === 'all' && (
          <>
            <Icon icon="mdi:source-merge" width="14" />
            <span>This cell receives context from all prior cells (explicit snowball).</span>
          </>
        )}
        {currentMode === 'custom' && (
          <>
            <Icon icon="mdi:tune-variant" width="14" />
            <span>Configure exactly which cells and what content to include.</span>
          </>
        )}
      </div>

      {/* Source List (for non-clean modes) */}
      {currentMode !== 'clean' && (
        <div className="sources-section">
          <div className="section-header">
            <Icon icon="mdi:source-branch" width="14" />
            <span>Context Sources</span>
          </div>

          <div className="sources-list">
            {(context.from || []).map((source, idx) => {
              const display = getSourceDisplay(source);
              const isExpanded = expandedSource === idx;
              const config = typeof source === 'object' ? source : null;

              return (
                <div key={idx} className={`source-item ${display.color}`}>
                  <div className="source-header">
                    <Icon icon={display.icon} width="14" className="source-icon" />
                    <span className="source-name">{display.name}</span>

                    {/* Include badges */}
                    {config && config.include && (
                      <div className="include-badges">
                        {config.include.map(inc => (
                          <span key={inc} className="include-badge" title={`Includes ${inc}`}>
                            {inc === 'images' && <Icon icon="mdi:image" width="10" />}
                            {inc === 'output' && <Icon icon="mdi:text" width="10" />}
                            {inc === 'messages' && <Icon icon="mdi:message-text" width="10" />}
                            {inc === 'state' && <Icon icon="mdi:database" width="10" />}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="source-actions">
                      {/* Only show config for cell sources, not keywords */}
                      {display.name !== 'all' && (
                        <button
                          className={`action-btn ${isExpanded ? 'active' : ''}`}
                          onClick={() => setExpandedSource(isExpanded ? null : idx)}
                          title="Configure source"
                        >
                          <Icon icon="mdi:cog" width="14" />
                        </button>
                      )}
                      <button
                        className="action-btn remove"
                        onClick={() => removeSource(idx)}
                        title="Remove source"
                      >
                        <Icon icon="mdi:close" width="14" />
                      </button>
                    </div>
                  </div>

                  {/* Expanded configuration */}
                  {isExpanded && display.name !== 'all' && (
                    <SourceConfig
                      source={source}
                      onChange={(updates) => updateSource(idx, updates)}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {/* Add Source */}
          {currentMode === 'custom' && (
            <div className="add-source">
              <div className="add-source-row">
                <span className="add-label">Add source:</span>
                <div className="add-buttons">
                  {!context.from?.some(s => s === 'first' || s?.cell === 'first') && (
                    <button className="add-btn keyword" onClick={() => addSource('first')}>
                      <Icon icon="mdi:ray-start" width="12" />
                      first
                    </button>
                  )}
                  {!context.from?.some(s => s === 'previous' || s === 'prev') && (
                    <button className="add-btn keyword" onClick={() => addSource('previous')}>
                      <Icon icon="mdi:arrow-left" width="12" />
                      previous
                    </button>
                  )}
                  {availableCells.length > 0 && (
                    <select
                      className="add-cell-select"
                      value=""
                      onChange={(e) => {
                        if (e.target.value) addSource(e.target.value);
                      }}
                    >
                      <option value="">+ Cell...</option>
                      {availableCells.map(p => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Exclusions (only for "all" mode) */}
      {currentMode === 'all' && otherCells.length > 0 && (
        <div className="exclusions-section">
          <div className="section-header">
            <Icon icon="mdi:filter-remove" width="14" />
            <span>Exclude Cells</span>
          </div>
          <div className="exclusions-list">
            {otherCells.map(cell => (
              <label key={cell} className="exclusion-item">
                <input
                  type="checkbox"
                  checked={context.exclude?.includes(cell) || false}
                  onChange={() => toggleExclude(cell)}
                />
                <span>{cell}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Include Input Toggle */}
      {currentMode !== 'clean' && (
        <div className="include-input-section">
          <label className="toggle-option">
            <input
              type="checkbox"
              checked={context.include_input !== false}
              onChange={(e) => updateContext({ include_input: e.target.checked })}
            />
            <Icon icon="mdi:application-import" width="14" />
            <span>Include original cascade input</span>
          </label>
        </div>
      )}
    </div>
  );
}

/**
 * SourceConfig - Configuration panel for a single context source
 */
function SourceConfig({ source, onChange }) {
  const config = typeof source === 'object' ? source : { cell: source };
  const include = config.include || ['images', 'output'];

  const toggleInclude = (item) => {
    const newInclude = include.includes(item)
      ? include.filter(i => i !== item)
      : [...include, item];
    onChange({ include: newInclude.length > 0 ? newInclude : ['output'] });
  };

  return (
    <div className="source-config">
      {/* What to include */}
      <div className="config-group">
        <span className="config-label">Include:</span>
        <div className="config-toggles">
          {[
            { id: 'output', icon: 'mdi:text', label: 'Output' },
            { id: 'images', icon: 'mdi:image', label: 'Images' },
            { id: 'messages', icon: 'mdi:message-text', label: 'Messages' },
            { id: 'state', icon: 'mdi:database', label: 'State' },
          ].map(opt => (
            <button
              key={opt.id}
              className={`config-toggle ${include.includes(opt.id) ? 'active' : ''}`}
              onClick={() => toggleInclude(opt.id)}
              title={opt.label}
            >
              <Icon icon={opt.icon} width="12" />
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Image filter (only if images included) */}
      {include.includes('images') && (
        <div className="config-group">
          <span className="config-label">Images:</span>
          <select
            value={config.images_filter || 'all'}
            onChange={(e) => onChange({ images_filter: e.target.value })}
            className="config-select"
          >
            <option value="all">All images</option>
            <option value="last">Last image only</option>
            <option value="last_n">Last N images</option>
          </select>
          {config.images_filter === 'last_n' && (
            <input
              type="number"
              min="1"
              max="10"
              value={config.images_count || 1}
              onChange={(e) => onChange({ images_count: parseInt(e.target.value) || 1 })}
              className="config-number"
            />
          )}
        </div>
      )}

      {/* Message filter (only if messages included) */}
      {include.includes('messages') && (
        <div className="config-group">
          <span className="config-label">Messages:</span>
          <select
            value={config.messages_filter || 'all'}
            onChange={(e) => onChange({ messages_filter: e.target.value })}
            className="config-select"
          >
            <option value="all">All messages</option>
            <option value="assistant_only">Assistant only</option>
            <option value="last_turn">Last turn only</option>
          </select>
        </div>
      )}

      {/* Injection role */}
      <div className="config-group">
        <span className="config-label">Inject as:</span>
        <select
          value={config.as_role || 'user'}
          onChange={(e) => onChange({ as_role: e.target.value })}
          className="config-select"
        >
          <option value="user">User message</option>
          <option value="system">System message</option>
        </select>
      </div>
    </div>
  );
}

export default ContextBuilder;
