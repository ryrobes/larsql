import React, { useState, useMemo, useCallback } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../../stores/workshopStore';
import TacklePills from '../components/TacklePills';
import ModelSelect from '../components/ModelSelect';
import ContextBuilder from '../components/ContextBuilder';
import ContextDropPicker from '../components/ContextDropPicker';
import FlowBuilder from '../components/FlowBuilder';
import { JinjaEditor, getAvailableVariables } from '../jinja-editor';
import './PhaseBlock.css';

/**
 * PhaseBlock - Individual phase container with collapsible drawers
 *
 * Features:
 * - Drag handle for reordering
 * - Editable name and instructions
 * - Collapsible config drawers
 * - Visual indicators for configured sections
 * - Droppable target for models
 */
function PhaseBlock({ phase, index, isSelected, onSelect }) {
  const {
    updatePhase,
    removePhase,
    expandedDrawers,
    toggleDrawer,
    cascade,
  } = useWorkshopStore();

  const [isEditing, setIsEditing] = useState(false);
  const [isContextDragOver, setIsContextDragOver] = useState(false);
  const [contextDropPicker, setContextDropPicker] = useState(null); // { phaseName, position }

  // Get available variables for the Jinja editor
  const availableVariables = useMemo(
    () => getAvailableVariables(cascade, index),
    [cascade, index]
  );

  // Sortable setup for reordering phases
  const {
    attributes,
    listeners,
    setNodeRef: setSortableRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: `phase-${phase.name}` });

  // Droppable setup for accepting models and config blocks
  const { setNodeRef: setDroppableRef, isOver } = useDroppable({
    id: `phase-${phase.name}`,
    data: {
      type: 'phase',
      phaseIndex: index,
      phaseName: phase.name,
    },
  });

  // Combine refs
  const setNodeRef = (node) => {
    setSortableRef(node);
    setDroppableRef(node);
  };

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  // Check which configs are present
  const hasSoundings = phase.soundings && phase.soundings.factor > 1;
  const hasReforge = phase.soundings?.reforge?.steps > 0;
  const hasRules = phase.rules && (phase.rules.max_turns || phase.rules.loop_until);
  const hasContext = phase.context && phase.context.from?.length > 0;
  const hasWards = phase.wards && (phase.wards.pre?.length > 0 || phase.wards.post?.length > 0);
  const hasHandoffs = phase.handoffs && phase.handoffs.length > 0;
  const hasTackle = phase.tackle && phase.tackle.length > 0;

  // Drawer expansion state for this phase
  const isDrawerOpen = (drawer) => expandedDrawers[index]?.includes(drawer);

  const handleNameChange = (e) => {
    const value = e.target.value
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, '_')
      .replace(/_+/g, '_');
    updatePhase(index, { name: value });
  };

  const handleInstructionsChange = (e) => {
    updatePhase(index, { instructions: e.target.value });
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    if (window.confirm(`Delete phase "${phase.name}"?`)) {
      removePhase(index);
    }
  };

  // Handle dropping a phase output variable onto the Context drawer toggle
  const handleContextDragOver = (e) => {
    // Check if this is a variable we can accept (outputs.*)
    const types = e.dataTransfer.types;
    if (types.includes('application/x-variable')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setIsContextDragOver(true);
    }
  };

  const handleContextDragLeave = (e) => {
    // Only set to false if we're actually leaving (not entering a child)
    if (!e.currentTarget.contains(e.relatedTarget)) {
      setIsContextDragOver(false);
    }
  };

  const handleContextDrop = (e) => {
    e.preventDefault();
    setIsContextDragOver(false);

    const variablePath = e.dataTransfer.getData('application/x-variable');
    if (!variablePath) return;

    // Only accept outputs.* variables
    if (!variablePath.startsWith('outputs.')) {
      return;
    }

    // Extract the phase name from "outputs.phase_name"
    const sourcePhaseName = variablePath.replace('outputs.', '');

    // Check if already present
    const currentContext = phase.context || {};
    const currentFrom = currentContext.from || [];
    const alreadyPresent = currentFrom.some(
      (s) => (typeof s === 'string' ? s === sourcePhaseName : s.phase === sourcePhaseName)
    );

    if (alreadyPresent) {
      // Already present, just open the drawer
      if (!isDrawerOpen('context')) {
        toggleDrawer(index, 'context');
      }
      return;
    }

    // Show the picker at the drop position
    setContextDropPicker({
      phaseName: sourcePhaseName,
      position: { x: e.clientX, y: e.clientY },
    });
  };

  // Handle selection from the context drop picker
  const handleContextPickerSelect = useCallback((includeOptions) => {
    if (!contextDropPicker) return;

    const { phaseName: sourcePhaseName } = contextDropPicker;
    const currentContext = phase.context || {};
    const currentFrom = currentContext.from || [];

    // Build the source config
    const sourceConfig = {
      phase: sourcePhaseName,
      include: includeOptions,
    };

    // If currently set to "all", switch to custom mode with the dropped phase
    let newFrom;
    if (currentFrom.includes('all')) {
      newFrom = [sourceConfig];
    } else {
      newFrom = [...currentFrom, sourceConfig];
    }

    updatePhase(index, {
      context: { ...currentContext, from: newFrom },
    });

    // Close picker and open drawer
    setContextDropPicker(null);
    if (!isDrawerOpen('context')) {
      toggleDrawer(index, 'context');
    }
  }, [contextDropPicker, phase.context, index, updatePhase, isDrawerOpen, toggleDrawer]);

  const handleContextPickerCancel = useCallback(() => {
    setContextDropPicker(null);
  }, []);

  // Drawer toggle handlers
  const drawerConfigs = [
    { id: 'execution', label: 'Execution', icon: 'mdi:cog', hasContent: hasTackle || phase.model },
    { id: 'soundings', label: 'Soundings', icon: 'mdi:source-branch', hasContent: hasSoundings },
    { id: 'rules', label: 'Rules', icon: 'mdi:repeat', hasContent: hasRules },
    { id: 'validation', label: 'Validation', icon: 'mdi:check-decagram', hasContent: hasWards },
    { id: 'context', label: 'Context', icon: 'mdi:link-variant', hasContent: hasContext },
    { id: 'flow', label: 'Flow', icon: 'mdi:arrow-decision', hasContent: hasHandoffs },
  ];

  // Build class names
  const classNames = [
    'phase-block',
    isSelected && 'selected',
    isDragging && 'dragging',
    isOver && 'drop-over',
  ].filter(Boolean).join(' ');

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={classNames}
      onClick={onSelect}
    >
      {/* Phase Header */}
      <div className="phase-header">
        {/* Drag Handle */}
        <div className="drag-handle" {...attributes} {...listeners}>
          <Icon icon="mdi:drag-vertical" width="20" />
        </div>

        {/* Phase Number */}
        <div className="phase-number">
          {index + 1}
        </div>

        {/* Phase Name */}
        <div className="phase-name-container">
          {isEditing ? (
            <input
              type="text"
              className="phase-name-input"
              value={phase.name}
              onChange={handleNameChange}
              onBlur={() => setIsEditing(false)}
              onKeyDown={(e) => e.key === 'Enter' && setIsEditing(false)}
              autoFocus
              spellCheck={false}
            />
          ) : (
            <span
              className="phase-name"
              onDoubleClick={() => setIsEditing(true)}
              title="Double-click to edit"
            >
              {phase.name || 'unnamed_phase'}
            </span>
          )}
        </div>

        {/* Config Indicators */}
        <div className="config-indicators">
          {hasSoundings && (
            <span
              className={`indicator soundings ${hasReforge ? 'with-reforge' : ''}`}
              title={`Soundings: ${phase.soundings.factor}x${hasReforge ? ` + Reforge: ${phase.soundings.reforge.steps} steps` : ''}`}
            >
              <Icon icon="mdi:source-branch" width="14" />
              {phase.soundings.factor}
              {hasReforge && (
                <>
                  <Icon icon="mdi:hammer-wrench" width="12" className="reforge-icon" />
                  {phase.soundings.reforge.steps}
                </>
              )}
            </span>
          )}
          {hasRules && phase.rules.loop_until && (
            <span className="indicator rules" title={`Loop until: ${phase.rules.loop_until}`}>
              <Icon icon="mdi:repeat" width="14" />
            </span>
          )}
          {hasHandoffs && (
            <span className="indicator handoffs" title={`Handoffs: ${phase.handoffs.join(', ')}`}>
              <Icon icon="mdi:arrow-decision" width="14" />
              {phase.handoffs.length}
            </span>
          )}
        </div>

        {/* Delete Button */}
        <button className="phase-delete-btn" onClick={handleDelete} title="Delete phase">
          <Icon icon="mdi:close" width="16" />
        </button>
      </div>

      {/* Instructions Field */}
      <div className="phase-instructions">
        <label className="instructions-label">Instructions</label>
        <JinjaEditor
          value={phase.instructions || ''}
          onChange={(text) => updatePhase(index, { instructions: text })}
          availableVariables={availableVariables}
          placeholder="Enter phase instructions..."
          showPalette={true}
          className="compact"
        />
      </div>

      {/* Drawer Toggles */}
      <div className="drawer-toggles">
        {drawerConfigs.map(({ id, label, icon, hasContent }) => {
          // Special handling for context drawer - make it a drop target
          const isContext = id === 'context';
          const extraProps = isContext
            ? {
                onDragOver: handleContextDragOver,
                onDragLeave: handleContextDragLeave,
                onDrop: handleContextDrop,
              }
            : {};

          return (
            <button
              key={id}
              className={`drawer-toggle ${isDrawerOpen(id) ? 'open' : ''} ${hasContent ? 'has-content' : ''} ${isContext && isContextDragOver ? 'drop-target-active' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                toggleDrawer(index, id);
              }}
              {...extraProps}
            >
              <Icon icon={isDrawerOpen(id) ? 'mdi:chevron-down' : 'mdi:chevron-right'} width="14" />
              <Icon icon={icon} width="14" />
              <span>{label}</span>
              {hasContent && <span className="content-dot" />}
              {isContext && isContextDragOver && (
                <span className="drop-hint">Drop to add</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Drawer Contents */}
      <div className="drawer-contents">
        {isDrawerOpen('execution') && (
          <ExecutionDrawer phase={phase} index={index} />
        )}
        {isDrawerOpen('soundings') && (
          <SoundingsDrawer phase={phase} index={index} />
        )}
        {isDrawerOpen('rules') && (
          <RulesDrawer phase={phase} index={index} />
        )}
        {isDrawerOpen('validation') && (
          <ValidationDrawer phase={phase} index={index} />
        )}
        {isDrawerOpen('context') && (
          <ContextDrawer phase={phase} index={index} />
        )}
        {isDrawerOpen('flow') && (
          <FlowDrawer phase={phase} index={index} />
        )}
      </div>

      {/* Context Drop Picker (shown when dropping an output variable on Context toggle) */}
      {contextDropPicker && (
        <ContextDropPicker
          phaseName={contextDropPicker.phaseName}
          position={contextDropPicker.position}
          onSelect={handleContextPickerSelect}
          onCancel={handleContextPickerCancel}
        />
      )}
    </div>
  );
}

/**
 * ExecutionDrawer - Tackle and model configuration
 */
function ExecutionDrawer({ phase, index }) {
  const { updatePhase } = useWorkshopStore();

  const handleTackleChange = (tackle) => {
    updatePhase(index, { tackle });
  };

  const handleModelChange = (value) => {
    // Setting undefined will delete the key from the phase
    updatePhase(index, { model: value || undefined });
  };

  return (
    <div className="drawer-content execution-drawer">
      <div className="drawer-intro">
        <Icon icon="mdi:information-outline" width="14" />
        <p>
          <strong>Tackle</strong> are tools the LLM can use during this phase.
          Drag from the palette or type <code>manifest</code> for auto-selection.
          Override the <strong>model</strong> for specialized tasks.
        </p>
      </div>

      <div className="drawer-field">
        <label>
          <Icon icon="mdi:wrench" width="14" />
          Tackle (tools)
        </label>
        <TacklePills
          value={phase.tackle || []}
          onChange={handleTackleChange}
          phaseIndex={index}
        />
        <span className="field-hint">
          Drag tools from the palette, or use "manifest" for Quartermaster auto-selection
        </span>
      </div>

      <div className="drawer-field">
        <label>
          <Icon icon="mdi:brain" width="14" />
          Model (optional)
        </label>
        <ModelSelect
          value={phase.model || ''}
          onChange={handleModelChange}
          placeholder="Use default model"
          allowClear={true}
        />
        <span className="field-hint">
          Override default model for this phase - drag from palette or select below
        </span>
      </div>
    </div>
  );
}

/**
 * SoundingsDrawer - Tree of Thought configuration
 */
function SoundingsDrawer({ phase, index }) {
  const { updatePhaseField, cascade } = useWorkshopStore();
  const [isReforgeExpanded, setIsReforgeExpanded] = React.useState(false);

  const soundings = phase.soundings || {};
  const reforge = soundings.reforge || {};
  const hasReforge = reforge.steps > 0;

  const handleChange = (field, value) => {
    updatePhaseField(index, `soundings.${field}`, value);
  };

  const handleReforgeChange = (field, value) => {
    updatePhaseField(index, `soundings.reforge.${field}`, value);
  };

  const handleEnableReforge = (enabled) => {
    if (enabled) {
      // Initialize with defaults
      updatePhaseField(index, 'soundings.reforge', {
        steps: 2,
        honing_prompt: '',
        factor_per_step: 2,
      });
      setIsReforgeExpanded(true);
    } else {
      // Remove reforge config
      updatePhaseField(index, 'soundings.reforge', undefined);
    }
  };

  const factor = soundings.factor || 3;
  const mode = soundings.mode || 'evaluate';

  // Get validator names for threshold
  const validatorNames = Object.keys(cascade.validators || {});

  return (
    <div className="drawer-content soundings-drawer">
      <div className="drawer-intro">
        <Icon icon="mdi:information-outline" width="14" />
        <p>
          Run multiple parallel attempts of this phase.
          An evaluator picks the best result or combines all outputs.
        </p>
      </div>

      {/* Factor Slider */}
      <div className="drawer-field slider-field">
        <label>
          <span>Parallel Attempts</span>
          <span className="slider-value">{factor}×</span>
        </label>
        <input
          type="range"
          min="2"
          max="12"
          value={factor}
          onChange={(e) => handleChange('factor', parseInt(e.target.value))}
          className="slider"
        />
        <div className="slider-labels">
          <span>2</span>
          <span>6</span>
          <span>12</span>
        </div>
      </div>

      {/* Mode Toggle */}
      <div className="drawer-field">
        <label>Mode</label>
        <div className="mode-toggle">
          <button
            className={`mode-option ${mode === 'evaluate' ? 'active' : ''}`}
            onClick={() => handleChange('mode', 'evaluate')}
          >
            <Icon icon="mdi:trophy" width="16" />
            <span>Pick Best</span>
          </button>
          <button
            className={`mode-option ${mode === 'aggregate' ? 'active' : ''}`}
            onClick={() => handleChange('mode', 'aggregate')}
          >
            <Icon icon="mdi:merge" width="16" />
            <span>Combine All</span>
          </button>
        </div>
      </div>

      {/* Evaluator Instructions - only show for evaluate mode */}
      {mode === 'evaluate' && (
        <div className="drawer-field">
          <label>Evaluator Instructions</label>
          <textarea
            value={soundings.evaluator_instructions || ''}
            onChange={(e) => handleChange('evaluator_instructions', e.target.value)}
            placeholder="Optional: How should the evaluator pick the best result?"
            rows={2}
          />
        </div>
      )}

      {/* Aggregator Instructions - only show for aggregate mode */}
      {mode === 'aggregate' && (
        <div className="drawer-field">
          <label>Aggregator Instructions</label>
          <textarea
            value={soundings.aggregator_instructions || ''}
            onChange={(e) => handleChange('aggregator_instructions', e.target.value)}
            placeholder="Optional: How should results be combined?"
            rows={2}
          />
        </div>
      )}

      {/* Mutations toggle */}
      <div className="drawer-field checkbox">
        <label>
          <input
            type="checkbox"
            checked={soundings.mutate !== false}
            onChange={(e) => handleChange('mutate', e.target.checked)}
          />
          <span>Vary prompts between attempts</span>
        </label>
        <span className="field-hint">Adds slight variations to increase diversity</span>
      </div>

      {/* Reforge Section - only for evaluate mode */}
      {mode === 'evaluate' && (
        <div className={`reforge-section ${hasReforge ? 'enabled' : ''}`}>
          <div
            className="reforge-header"
            onClick={() => hasReforge && setIsReforgeExpanded(!isReforgeExpanded)}
          >
            <div className="reforge-header-left">
              <Icon
                icon={hasReforge && isReforgeExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                width="14"
                className={`expand-icon ${!hasReforge ? 'hidden' : ''}`}
              />
              <Icon icon="mdi:hammer-wrench" width="16" />
              <span>Reforge</span>
              {hasReforge && (
                <span className="reforge-badge">
                  {reforge.steps} step{reforge.steps > 1 ? 's' : ''} × {reforge.factor_per_step || 2}
                </span>
              )}
            </div>
            <label className="reforge-toggle" onClick={(e) => e.stopPropagation()}>
              <input
                type="checkbox"
                checked={hasReforge}
                onChange={(e) => handleEnableReforge(e.target.checked)}
              />
              <span className="toggle-slider"></span>
            </label>
          </div>

          {hasReforge && isReforgeExpanded && (
            <div className="reforge-content">
              <div className="reforge-intro">
                <p>
                  Iteratively refine the winning result. Each step takes the current best
                  and runs additional attempts with your honing instructions.
                </p>
              </div>

              {/* Steps Slider */}
              <div className="drawer-field slider-field">
                <label>
                  <span>Refinement Steps</span>
                  <span className="slider-value">{reforge.steps || 2}</span>
                </label>
                <input
                  type="range"
                  min="1"
                  max="5"
                  value={reforge.steps || 2}
                  onChange={(e) => handleReforgeChange('steps', parseInt(e.target.value))}
                  className="slider"
                />
                <div className="slider-labels">
                  <span>1</span>
                  <span>3</span>
                  <span>5</span>
                </div>
              </div>

              {/* Honing Prompt */}
              <div className="drawer-field">
                <label>Honing Prompt</label>
                <textarea
                  value={reforge.honing_prompt || ''}
                  onChange={(e) => handleReforgeChange('honing_prompt', e.target.value)}
                  placeholder="Refine and improve: focus on clarity, correctness, and completeness..."
                  rows={2}
                />
                <span className="field-hint">Instructions for refining the winner at each step</span>
              </div>

              {/* Factor Per Step Slider */}
              <div className="drawer-field slider-field">
                <label>
                  <span>Attempts Per Step</span>
                  <span className="slider-value">{reforge.factor_per_step || 2}×</span>
                </label>
                <input
                  type="range"
                  min="1"
                  max="5"
                  value={reforge.factor_per_step || 2}
                  onChange={(e) => handleReforgeChange('factor_per_step', parseInt(e.target.value))}
                  className="slider"
                />
                <div className="slider-labels">
                  <span>1</span>
                  <span>3</span>
                  <span>5</span>
                </div>
              </div>

              {/* Reforge Mutations */}
              <div className="drawer-field checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={reforge.mutate || false}
                    onChange={(e) => handleReforgeChange('mutate', e.target.checked)}
                  />
                  <span>Vary prompts during refinement</span>
                </label>
              </div>

              {/* Optional: Evaluator Override */}
              <div className="drawer-field">
                <label>Evaluator Override (optional)</label>
                <textarea
                  value={reforge.evaluator_override || ''}
                  onChange={(e) => handleReforgeChange('evaluator_override', e.target.value || undefined)}
                  placeholder="Custom evaluator for refinement steps (uses main evaluator if empty)"
                  rows={2}
                />
              </div>

              {/* Optional: Early Stopping Threshold */}
              {validatorNames.length > 0 && (
                <div className="drawer-field">
                  <label>Early Stop Threshold (optional)</label>
                  <select
                    value={reforge.threshold?.validator || ''}
                    onChange={(e) => {
                      if (e.target.value) {
                        handleReforgeChange('threshold', {
                          validator: e.target.value,
                          mode: 'advisory'
                        });
                      } else {
                        handleReforgeChange('threshold', undefined);
                      }
                    }}
                  >
                    <option value="">None - run all steps</option>
                    {validatorNames.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                  <span className="field-hint">Stop early when validator passes</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * RulesDrawer - Execution rules configuration
 */
function RulesDrawer({ phase, index }) {
  const { updatePhaseField } = useWorkshopStore();

  const rules = phase.rules || {};

  const handleChange = (field, value) => {
    updatePhaseField(index, `rules.${field}`, value);
  };

  const maxTurns = rules.max_turns || 0;
  const hasMaxTurns = maxTurns > 0;

  return (
    <div className="drawer-content rules-drawer">
      <div className="drawer-intro">
        <Icon icon="mdi:information-outline" width="14" />
        <p>
          Constrain phase execution with turn limits or retry validators.
        </p>
      </div>

      {/* Max Turns Slider */}
      <div className="drawer-field slider-field">
        <label>
          <span>Max Turns</span>
          <span className="slider-value">{hasMaxTurns ? maxTurns : '1'}</span>
        </label>
        <input
          type="range"
          min="0"
          max="20"
          value={maxTurns}
          onChange={(e) => {
            const val = parseInt(e.target.value);
            handleChange('max_turns', val === 0 ? undefined : val);
          }}
          className="slider"
        />
        <div className="slider-labels">
          <span>Default (1)</span>
          <span>10</span>
          <span>20</span>
        </div>
      </div>

      {/* Loop Until */}
      <div className="drawer-field">
        <label>Loop Until (validator)</label>
        <input
          type="text"
          value={rules.loop_until || ''}
          onChange={(e) => handleChange('loop_until', e.target.value || undefined)}
          placeholder="validator_name"
          spellCheck={false}
        />
        <span className="field-hint">Retry until this validator passes</span>
      </div>

      {rules.loop_until && (
        <div className="drawer-field checkbox">
          <label>
            <input
              type="checkbox"
              checked={rules.loop_until_silent || false}
              onChange={(e) => handleChange('loop_until_silent', e.target.checked)}
            />
            <span>Silent loop</span>
          </label>
          <span className="field-hint">Don't show validator feedback to LLM</span>
        </div>
      )}
    </div>
  );
}

/**
 * FlowDrawer - Handoffs and sub-cascades configuration using FlowBuilder
 */
function FlowDrawer({ phase, index }) {
  const { updatePhase, cascade } = useWorkshopStore();

  // Get all phase names for handoff selection
  const allPhases = (cascade.phases || []).map(p => p.name);

  const handleFlowChange = (updates) => {
    // Merge flow-related updates into the phase
    const phaseUpdates = {};
    if ('handoffs' in updates) {
      phaseUpdates.handoffs = updates.handoffs;
    }
    if ('sub_cascades' in updates) {
      phaseUpdates.sub_cascades = updates.sub_cascades;
    }
    if ('async_cascades' in updates) {
      phaseUpdates.async_cascades = updates.async_cascades;
    }
    updatePhase(index, phaseUpdates);
  };

  return (
    <div className="drawer-content flow-drawer">
      <FlowBuilder
        value={{
          handoffs: phase.handoffs,
          sub_cascades: phase.sub_cascades,
          async_cascades: phase.async_cascades,
        }}
        onChange={handleFlowChange}
        allPhases={allPhases}
        currentPhaseName={phase.name}
        availableCascades={[]} // Could be populated from API
      />
    </div>
  );
}

/**
 * ValidationDrawer - Wards configuration (pre/post/turn validation)
 */
function ValidationDrawer({ phase, index }) {
  const { updatePhaseField, cascade } = useWorkshopStore();

  const wards = phase.wards || {};

  // Get list of validators from cascade
  const validatorNames = Object.keys(cascade.validators || {});

  const handleAddWard = (wardType) => {
    const existing = wards[wardType] || [];
    updatePhaseField(index, `wards.${wardType}`, [...existing, { validator: '', mode: 'blocking' }]);
  };

  const handleRemoveWard = (wardType, wardIndex) => {
    const existing = wards[wardType] || [];
    updatePhaseField(index, `wards.${wardType}`, existing.filter((_, i) => i !== wardIndex));
  };

  const renderWardSection = (wardType, label, description) => {
    const wardList = wards[wardType] || [];

    return (
      <div className="ward-section">
        <div className="ward-section-header">
          <span className="ward-label">{label}</span>
          <span className="ward-desc">{description}</span>
        </div>

        {wardList.map((ward, wardIndex) => (
          <div key={wardIndex} className="ward-item">
            <select
              value={ward.validator || ''}
              onChange={(e) => {
                const newWards = [...wardList];
                newWards[wardIndex] = { ...ward, validator: e.target.value };
                updatePhaseField(index, `wards.${wardType}`, newWards);
              }}
              className="ward-validator"
            >
              <option value="">Select validator...</option>
              {validatorNames.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>

            <div className="ward-mode-toggle">
              {[
                { value: 'blocking', icon: 'mdi:hand-back-left', label: 'Block' },
                { value: 'retry', icon: 'mdi:refresh', label: 'Retry' },
                { value: 'advisory', icon: 'mdi:information-outline', label: 'Warn' },
              ].map(({ value, icon, label }) => (
                <button
                  key={value}
                  type="button"
                  className={`ward-mode-btn ${(ward.mode || 'blocking') === value ? 'active' : ''}`}
                  onClick={() => {
                    const newWards = [...wardList];
                    newWards[wardIndex] = { ...ward, mode: value };
                    updatePhaseField(index, `wards.${wardType}`, newWards);
                  }}
                  title={label}
                >
                  <Icon icon={icon} width="14" />
                </button>
              ))}
            </div>

            <button
              className="ward-remove"
              onClick={() => handleRemoveWard(wardType, wardIndex)}
              title="Remove ward"
              type="button"
            >
              <Icon icon="mdi:close" width="14" />
            </button>
          </div>
        ))}

        <button
          className="ward-add"
          onClick={() => handleAddWard(wardType)}
          type="button"
        >
          <Icon icon="mdi:plus" width="14" />
          <span>Add {label.toLowerCase()} ward</span>
        </button>
      </div>
    );
  };

  return (
    <div className="drawer-content validation-drawer">
      <div className="drawer-intro">
        <Icon icon="mdi:information-outline" width="14" />
        <p>
          <strong>Wards</strong> are validation checkpoints.
          <strong>Pre</strong> runs before the phase, <strong>post</strong> after completion, <strong>turn</strong> after each LLM response.
          Modes: <code>blocking</code> (halt), <code>retry</code> (try again), <code>advisory</code> (warn only).
        </p>
      </div>

      {validatorNames.length === 0 && (
        <div className="validation-hint">
          <Icon icon="mdi:information" width="16" />
          <span>Add validators to the cascade first to use wards</span>
        </div>
      )}

      {renderWardSection('pre', 'Pre-execution', 'Run before the phase starts')}
      {renderWardSection('post', 'Post-execution', 'Run after phase completes')}
      {renderWardSection('turn', 'Per-turn', 'Run after each LLM turn')}
    </div>
  );
}

/**
 * ContextDrawer - Selective context configuration using ContextBuilder
 */
function ContextDrawer({ phase, index }) {
  const { updatePhase, cascade } = useWorkshopStore();

  // Get list of other phase names (for the builder to show available sources)
  const otherPhases = (cascade.phases || [])
    .map((p) => p.name)
    .filter((name) => name !== phase.name);

  const handleContextChange = (newContext) => {
    updatePhase(index, { context: newContext });
  };

  return (
    <div className="drawer-content context-drawer">
      <ContextBuilder
        value={phase.context}
        onChange={handleContextChange}
        otherPhases={otherPhases}
        phaseName={phase.name}
      />
    </div>
  );
}

export default PhaseBlock;
