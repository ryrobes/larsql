import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './FlowBuilder.css';

/**
 * FlowBuilder - Visual UI for configuring phase flow and handoffs
 *
 * Flow modes:
 * - Terminal: Phase ends cascade (no handoffs)
 * - Linear: Single next phase (automatic transition)
 * - Branching: Multiple targets with route_to tool (LLM decides)
 *
 * Also supports:
 * - Sub-cascades: Spawn nested cascades with input mapping
 * - Async cascades: Fire-and-forget background cascades
 */
function FlowBuilder({
  value, // { handoffs, sub_cascades, async_cascades }
  onChange,
  allPhases = [],
  currentPhaseName,
  availableCascades = []
}) {
  const [expandedHandoff, setExpandedHandoff] = useState(null);

  // Normalize handoffs to consistent format
  const handoffs = useMemo(() => {
    if (!value?.handoffs) return [];
    return value.handoffs.map(h =>
      typeof h === 'string' ? { target: h, description: null } : h
    );
  }, [value?.handoffs]);

  const subCascades = value?.sub_cascades || [];
  const asyncCascades = value?.async_cascades || [];

  // Determine flow mode
  const flowMode = useMemo(() => {
    if (handoffs.length === 0) return 'terminal';
    if (handoffs.length === 1 && !handoffs[0].description) return 'linear';
    return 'branching';
  }, [handoffs]);

  // Available phases for handoffs (excluding current)
  const availablePhases = useMemo(() => {
    const usedTargets = handoffs.map(h => h.target);
    return allPhases
      .filter(p => p !== currentPhaseName && !usedTargets.includes(p));
  }, [allPhases, currentPhaseName, handoffs]);

  // Update handlers
  const updateHandoffs = (newHandoffs) => {
    // Simplify handoffs without descriptions back to strings
    const simplified = newHandoffs.map(h =>
      h.description ? h : h.target
    );
    onChange({ ...value, handoffs: simplified.length > 0 ? simplified : undefined });
  };

  const addHandoff = (target) => {
    const newHandoffs = [...handoffs, { target, description: null }];
    updateHandoffs(newHandoffs);
  };

  const removeHandoff = (index) => {
    const newHandoffs = handoffs.filter((_, i) => i !== index);
    updateHandoffs(newHandoffs);
  };

  const updateHandoff = (index, updates) => {
    const newHandoffs = [...handoffs];
    newHandoffs[index] = { ...newHandoffs[index], ...updates };
    updateHandoffs(newHandoffs);
  };

  const setFlowMode = (mode) => {
    switch (mode) {
      case 'terminal':
        // Clear all handoffs
        onChange({ ...value, handoffs: undefined });
        break;

      case 'linear':
        if (handoffs.length === 0) {
          // No handoffs - add first available phase
          if (availablePhases.length > 0) {
            onChange({ ...value, handoffs: [availablePhases[0]] });
          }
          // If no phases available, do nothing (can't create linear without a target)
        } else if (handoffs.length === 1) {
          // Already one handoff - ensure no description (makes it linear)
          onChange({ ...value, handoffs: [handoffs[0].target] });
        } else {
          // Multiple handoffs - keep only first, remove description
          onChange({ ...value, handoffs: [handoffs[0].target] });
        }
        break;

      case 'branching':
        if (handoffs.length === 0) {
          // No handoffs - add first available phase with description
          if (availablePhases.length > 0) {
            onChange({ ...value, handoffs: [{ target: availablePhases[0], description: 'Default path' }] });
          }
          // If no phases available, do nothing
        } else if (handoffs.length === 1 && !handoffs[0].description) {
          // One handoff without description - add description to make it branching
          onChange({ ...value, handoffs: [{ target: handoffs[0].target, description: 'Primary path' }] });
        }
        // If already has descriptions or multiple handoffs, already in branching mode
        break;

      default:
        break;
    }
  };

  // Sub-cascade handlers
  const addSubCascade = () => {
    const newSub = { ref: '', input_map: {}, context_in: true, context_out: true };
    onChange({ ...value, sub_cascades: [...subCascades, newSub] });
  };

  const removeSubCascade = (index) => {
    const newSubs = subCascades.filter((_, i) => i !== index);
    onChange({ ...value, sub_cascades: newSubs.length > 0 ? newSubs : undefined });
  };

  const updateSubCascade = (index, updates) => {
    const newSubs = [...subCascades];
    newSubs[index] = { ...newSubs[index], ...updates };
    onChange({ ...value, sub_cascades: newSubs });
  };

  return (
    <div className="flow-builder">
      {/* Flow Mode Selector */}
      <div className="flow-mode-section">
        <div className="section-header">
          <Icon icon="mdi:call-split" width="14" />
          <span>Flow Mode</span>
        </div>

        <div className="flow-mode-buttons">
          <button
            className={`mode-btn ${flowMode === 'terminal' ? 'active' : ''}`}
            onClick={() => setFlowMode('terminal')}
            title="Phase ends the cascade"
          >
            <Icon icon="mdi:stop-circle-outline" width="16" />
            <span>Terminal</span>
            <small>Ends cascade</small>
          </button>
          <button
            className={`mode-btn ${flowMode === 'linear' ? 'active' : ''}`}
            onClick={() => setFlowMode('linear')}
            disabled={availablePhases.length === 0 && handoffs.length === 0}
            title={availablePhases.length === 0 && handoffs.length === 0
              ? "Add more phases to enable linear flow"
              : "Automatically proceed to next phase"
            }
          >
            <Icon icon="mdi:arrow-right" width="16" />
            <span>Linear</span>
            <small>Auto-proceed</small>
          </button>
          <button
            className={`mode-btn ${flowMode === 'branching' ? 'active' : ''}`}
            onClick={() => setFlowMode('branching')}
            disabled={availablePhases.length === 0 && handoffs.length === 0}
            title={availablePhases.length === 0 && handoffs.length === 0
              ? "Add more phases to enable branching flow"
              : "LLM decides which path using route_to tool"
            }
          >
            <Icon icon="mdi:source-fork" width="16" />
            <span>Branching</span>
            <small>LLM decides</small>
          </button>
        </div>

        {/* Mode description */}
        <div className="mode-info">
          {flowMode === 'terminal' && (
            <>
              <Icon icon="mdi:information-outline" width="14" />
              <span>This phase will end the cascade. No subsequent phases will execute.</span>
            </>
          )}
          {flowMode === 'linear' && (
            <>
              <Icon icon="mdi:arrow-right-circle" width="14" />
              <span>Execution automatically proceeds to the next phase after completion.</span>
            </>
          )}
          {flowMode === 'branching' && (
            <>
              <Icon icon="mdi:robot" width="14" />
              <span>A <code>route_to</code> tool is injected. The LLM decides which path based on context.</span>
            </>
          )}
        </div>
      </div>

      {/* Handoffs List */}
      {flowMode !== 'terminal' && (
        <div className="handoffs-section">
          <div className="section-header">
            <Icon icon="mdi:arrow-decision" width="14" />
            <span>Handoff Targets</span>
            {flowMode === 'branching' && (
              <span className="route-badge">
                <Icon icon="mdi:tools" width="10" />
                route_to
              </span>
            )}
          </div>

          <div className="handoffs-list">
            {handoffs.map((handoff, idx) => (
              <div
                key={idx}
                className={`handoff-item ${flowMode === 'branching' ? 'branching' : 'linear'}`}
              >
                <div className="handoff-header">
                  <div className="handoff-index">
                    {flowMode === 'branching' ? (
                      <Icon icon="mdi:numeric-1-circle" width="16" style={{ opacity: 0 }} />
                    ) : (
                      <Icon icon="mdi:arrow-right" width="14" />
                    )}
                  </div>

                  <div className="handoff-target">
                    <Icon icon="mdi:view-sequential" width="14" />
                    <span>{handoff.target}</span>
                  </div>

                  {flowMode === 'branching' && (
                    <button
                      className={`expand-btn ${expandedHandoff === idx ? 'active' : ''}`}
                      onClick={() => setExpandedHandoff(expandedHandoff === idx ? null : idx)}
                      title="Edit description"
                    >
                      <Icon icon="mdi:pencil" width="14" />
                    </button>
                  )}

                  <button
                    className="remove-btn"
                    onClick={() => removeHandoff(idx)}
                    title="Remove handoff"
                  >
                    <Icon icon="mdi:close" width="14" />
                  </button>
                </div>

                {/* Description (for branching mode) */}
                {flowMode === 'branching' && expandedHandoff === idx && (
                  <div className="handoff-description">
                    <label>
                      <Icon icon="mdi:text-box-outline" width="12" />
                      Description for LLM
                    </label>
                    <textarea
                      value={handoff.description || ''}
                      onChange={(e) => updateHandoff(idx, { description: e.target.value || null })}
                      placeholder="When should the LLM choose this path? (shown in route_to menu)"
                      rows={2}
                    />
                  </div>
                )}

                {/* Show description preview if set */}
                {flowMode === 'branching' && handoff.description && expandedHandoff !== idx && (
                  <div className="handoff-preview">
                    <Icon icon="mdi:format-quote-open" width="12" />
                    <span>{handoff.description}</span>
                  </div>
                )}
              </div>
            ))}

            {/* Add handoff */}
            {availablePhases.length > 0 && (
              <div className="add-handoff">
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) addHandoff(e.target.value);
                  }}
                  className="add-handoff-select"
                >
                  <option value="">+ Add handoff target...</option>
                  {availablePhases.map(p => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
            )}

            {availablePhases.length === 0 && handoffs.length === 0 && (
              <div className="no-phases-hint">
                <Icon icon="mdi:information-outline" width="14" />
                <span>Add more phases to the cascade to create handoffs.</span>
              </div>
            )}
          </div>

          {/* Branching tips */}
          {flowMode === 'branching' && handoffs.length > 0 && (
            <div className="branching-tips">
              <Icon icon="mdi:lightbulb-on-outline" width="14" />
              <span>
                Add descriptions to help the LLM choose. If only one target has no description,
                it becomes the default fallback.
              </span>
            </div>
          )}
        </div>
      )}

      {/* Sub-Cascades Section */}
      <div className="subcascades-section">
        <div className="section-header">
          <Icon icon="mdi:sitemap" width="14" />
          <span>Sub-Cascades</span>
          <button className="add-btn" onClick={addSubCascade} title="Add sub-cascade">
            <Icon icon="mdi:plus" width="14" />
          </button>
        </div>

        {subCascades.length === 0 ? (
          <div className="empty-subcascades">
            <span>No sub-cascades configured.</span>
            <button className="link-btn" onClick={addSubCascade}>
              <Icon icon="mdi:plus-circle-outline" width="14" />
              Add sub-cascade
            </button>
          </div>
        ) : (
          <div className="subcascades-list">
            {subCascades.map((sub, idx) => (
              <SubCascadeItem
                key={idx}
                value={sub}
                onChange={(updates) => updateSubCascade(idx, updates)}
                onRemove={() => removeSubCascade(idx)}
                availableCascades={availableCascades}
              />
            ))}
          </div>
        )}
      </div>

      {/* Flow Visualization (mini) */}
      {flowMode !== 'terminal' && handoffs.length > 0 && (
        <div className="flow-preview">
          <div className="preview-label">
            <Icon icon="mdi:eye-outline" width="12" />
            <span>Preview</span>
          </div>
          <div className="preview-diagram">
            <div className="preview-node current">
              <Icon icon="mdi:circle" width="8" />
              <span>{currentPhaseName}</span>
            </div>
            <div className={`preview-arrows ${flowMode}`}>
              {flowMode === 'linear' ? (
                <Icon icon="mdi:arrow-right" width="16" />
              ) : (
                <Icon icon="mdi:source-fork" width="16" />
              )}
            </div>
            <div className="preview-targets">
              {handoffs.map((h, idx) => (
                <div key={idx} className="preview-node target">
                  <Icon icon="mdi:circle-outline" width="8" />
                  <span>{h.target}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * SubCascadeItem - Individual sub-cascade configuration
 */
function SubCascadeItem({ value, onChange, onRemove, availableCascades }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="subcascade-item">
      <div className="subcascade-header">
        <Icon icon="mdi:sitemap" width="14" className="subcascade-icon" />

        <input
          type="text"
          value={value.ref || ''}
          onChange={(e) => onChange({ ref: e.target.value })}
          placeholder="cascade_id or path/to/cascade.json"
          className="subcascade-ref"
        />

        <button
          className={`expand-btn ${expanded ? 'active' : ''}`}
          onClick={() => setExpanded(!expanded)}
          title="Configure options"
        >
          <Icon icon="mdi:cog" width="14" />
        </button>

        <button className="remove-btn" onClick={onRemove} title="Remove">
          <Icon icon="mdi:close" width="14" />
        </button>
      </div>

      {expanded && (
        <div className="subcascade-config">
          <div className="config-row">
            <label>
              <input
                type="checkbox"
                checked={value.context_in !== false}
                onChange={(e) => onChange({ context_in: e.target.checked })}
              />
              <Icon icon="mdi:import" width="12" />
              <span>Pass context in</span>
            </label>
            <label>
              <input
                type="checkbox"
                checked={value.context_out !== false}
                onChange={(e) => onChange({ context_out: e.target.checked })}
              />
              <Icon icon="mdi:export" width="12" />
              <span>Bring context out</span>
            </label>
          </div>

          <div className="input-map-section">
            <span className="config-label">
              <Icon icon="mdi:swap-horizontal" width="12" />
              Input Mapping
            </span>
            <InputMapEditor
              value={value.input_map || {}}
              onChange={(input_map) => onChange({ input_map })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * InputMapEditor - Key-value editor for sub-cascade input mapping
 */
function InputMapEditor({ value, onChange }) {
  const entries = Object.entries(value);

  const addEntry = () => {
    onChange({ ...value, [`param_${entries.length + 1}`]: '' });
  };

  const updateKey = (oldKey, newKey) => {
    const newMap = {};
    Object.entries(value).forEach(([k, v]) => {
      newMap[k === oldKey ? newKey : k] = v;
    });
    onChange(newMap);
  };

  const updateValue = (key, newValue) => {
    onChange({ ...value, [key]: newValue });
  };

  const removeEntry = (key) => {
    const newMap = { ...value };
    delete newMap[key];
    onChange(newMap);
  };

  return (
    <div className="input-map-editor">
      {entries.length === 0 ? (
        <div className="empty-map">
          <span>No input mapping (uses state directly)</span>
        </div>
      ) : (
        entries.map(([key, val], idx) => (
          <div key={idx} className="map-entry">
            <input
              type="text"
              value={key}
              onChange={(e) => updateKey(key, e.target.value)}
              placeholder="param_name"
              className="map-key"
            />
            <Icon icon="mdi:arrow-right" width="12" />
            <input
              type="text"
              value={val}
              onChange={(e) => updateValue(key, e.target.value)}
              placeholder="state.value or {{ expr }}"
              className="map-value"
            />
            <button className="remove-entry" onClick={() => removeEntry(key)}>
              <Icon icon="mdi:close" width="12" />
            </button>
          </div>
        ))
      )}
      <button className="add-entry-btn" onClick={addEntry}>
        <Icon icon="mdi:plus" width="12" />
        Add mapping
      </button>
    </div>
  );
}

export default FlowBuilder;
