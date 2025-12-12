import React, { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../../stores/workshopStore';
import TackleChips from '../components/TackleChips';
import ModelSelect from '../components/ModelSelect';
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
  } = useWorkshopStore();

  const [isEditing, setIsEditing] = useState(false);

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

  // Drawer toggle handlers
  const drawerConfigs = [
    { id: 'execution', label: 'Execution', icon: 'mdi:cog', hasContent: hasTackle || phase.model },
    { id: 'soundings', label: 'Soundings', icon: 'mdi:source-branch', hasContent: hasSoundings },
    { id: 'rules', label: 'Rules', icon: 'mdi:repeat', hasContent: hasRules },
    { id: 'validation', label: 'Validation', icon: 'mdi:check-decagram', hasContent: hasWards },
    { id: 'context', label: 'Context', icon: 'mdi:link-variant', hasContent: hasContext },
    { id: 'flow', label: 'Flow', icon: 'mdi:arrow-decision', hasContent: hasHandoffs },
  ];

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`phase-block ${isSelected ? 'selected' : ''} ${isDragging ? 'dragging' : ''} ${isOver ? 'drop-over' : ''}`}
      onClick={onSelect}
    >
      {/* Phase Header */}
      <div className="phase-header">
        {/* Drag Handle */}
        <div className="drag-handle" {...attributes} {...listeners}>
          <Icon icon="mdi:drag-vertical" width="20" />
        </div>

        {/* Phase Number */}
        <div className="phase-number">{index + 1}</div>

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
            <span className="indicator soundings" title={`Soundings: ${phase.soundings.factor}x`}>
              <Icon icon="mdi:source-branch" width="14" />
              {phase.soundings.factor}
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
        <textarea
          className="instructions-textarea"
          value={phase.instructions || ''}
          onChange={handleInstructionsChange}
          placeholder="Enter phase instructions (Jinja2 supported)..."
          rows={4}
        />
      </div>

      {/* Drawer Toggles */}
      <div className="drawer-toggles">
        {drawerConfigs.map(({ id, label, icon, hasContent }) => (
          <button
            key={id}
            className={`drawer-toggle ${isDrawerOpen(id) ? 'open' : ''} ${hasContent ? 'has-content' : ''}`}
            onClick={(e) => {
              e.stopPropagation();
              toggleDrawer(index, id);
            }}
          >
            <Icon icon={isDrawerOpen(id) ? 'mdi:chevron-down' : 'mdi:chevron-right'} width="14" />
            <Icon icon={icon} width="14" />
            <span>{label}</span>
            {hasContent && <span className="content-dot" />}
          </button>
        ))}
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
      <div className="drawer-field">
        <label>Tackle (tools)</label>
        <TackleChips
          value={phase.tackle || []}
          onChange={handleTackleChange}
          placeholder="Search tools or type 'manifest'..."
        />
        <span className="field-hint">Select tools or use "manifest" for auto-selection</span>
      </div>

      <div className="drawer-field">
        <label>Model (optional)</label>
        <ModelSelect
          value={phase.model || ''}
          onChange={handleModelChange}
          placeholder="Use default model"
          allowClear={true}
        />
        <span className="field-hint">Override default model for this phase</span>
      </div>
    </div>
  );
}

/**
 * SoundingsDrawer - Tree of Thought configuration
 */
function SoundingsDrawer({ phase, index }) {
  const { updatePhaseField } = useWorkshopStore();

  const soundings = phase.soundings || {};

  const handleChange = (field, value) => {
    updatePhaseField(index, `soundings.${field}`, value);
  };

  return (
    <div className="drawer-content soundings-drawer">
      <div className="drawer-field">
        <label>Factor (parallel attempts)</label>
        <input
          type="number"
          min="1"
          max="20"
          value={soundings.factor || 1}
          onChange={(e) => handleChange('factor', parseInt(e.target.value) || 1)}
        />
      </div>

      <div className="drawer-field">
        <label>Mode</label>
        <select
          value={soundings.mode || 'evaluate'}
          onChange={(e) => handleChange('mode', e.target.value)}
        >
          <option value="evaluate">Evaluate (pick best)</option>
          <option value="aggregate">Aggregate (combine all)</option>
        </select>
      </div>

      <div className="drawer-field">
        <label>Evaluator Instructions</label>
        <textarea
          value={soundings.evaluator_instructions || ''}
          onChange={(e) => handleChange('evaluator_instructions', e.target.value)}
          placeholder="Instructions for the evaluator to pick the best sounding..."
          rows={3}
        />
      </div>

      <div className="drawer-field checkbox">
        <label>
          <input
            type="checkbox"
            checked={soundings.mutate !== false}
            onChange={(e) => handleChange('mutate', e.target.checked)}
          />
          <span>Enable prompt mutations</span>
        </label>
      </div>

      {/* Reforge section placeholder - will be expanded in Phase 4 */}
      <div className="drawer-subsection">
        <span className="subsection-label">
          <Icon icon="mdi:hammer-wrench" width="14" />
          Reforge (iterative refinement)
        </span>
        <span className="coming-soon">Configure in Phase 4</span>
      </div>
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

  return (
    <div className="drawer-content rules-drawer">
      <div className="drawer-field">
        <label>Max Turns</label>
        <input
          type="number"
          min="1"
          max="50"
          value={rules.max_turns || ''}
          onChange={(e) => handleChange('max_turns', parseInt(e.target.value) || undefined)}
          placeholder="No limit"
        />
        <span className="field-hint">Maximum conversation turns in this phase</span>
      </div>

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

      <div className="drawer-field checkbox">
        <label>
          <input
            type="checkbox"
            checked={rules.loop_until_silent || false}
            onChange={(e) => handleChange('loop_until_silent', e.target.checked)}
          />
          <span>Silent loop (don't show validator to LLM)</span>
        </label>
      </div>
    </div>
  );
}

/**
 * FlowDrawer - Handoffs configuration
 */
function FlowDrawer({ phase, index }) {
  const { updatePhase } = useWorkshopStore();

  const handleHandoffsChange = (e) => {
    const value = e.target.value;
    const handoffs = value.split(',').map(h => h.trim()).filter(Boolean);
    updatePhase(index, { handoffs });
  };

  return (
    <div className="drawer-content flow-drawer">
      <div className="drawer-field">
        <label>Handoffs (next phases)</label>
        <input
          type="text"
          value={(phase.handoffs || []).join(', ')}
          onChange={handleHandoffsChange}
          placeholder="next_phase, alternative_phase"
          spellCheck={false}
        />
        <span className="field-hint">Comma-separated phase names. Multiple enables route_to tool.</span>
      </div>
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

            <select
              value={ward.mode || 'blocking'}
              onChange={(e) => {
                const newWards = [...wardList];
                newWards[wardIndex] = { ...ward, mode: e.target.value };
                updatePhaseField(index, `wards.${wardType}`, newWards);
              }}
              className="ward-mode"
            >
              <option value="blocking">Blocking</option>
              <option value="retry">Retry</option>
              <option value="advisory">Advisory</option>
            </select>

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
 * ContextDrawer - Context.from configuration (selective context from other phases)
 */
function ContextDrawer({ phase, index }) {
  const { updatePhaseField, cascade } = useWorkshopStore();

  const context = phase.context || {};
  const contextFrom = context.from || [];

  // Get list of other phase names
  const otherPhases = (cascade.phases || [])
    .map((p) => p.name)
    .filter((name) => name !== phase.name);

  const handleAddPhase = (phaseName) => {
    if (!contextFrom.includes(phaseName)) {
      updatePhaseField(index, 'context.from', [...contextFrom, phaseName]);
    }
  };

  const handleRemovePhase = (phaseName) => {
    updatePhaseField(index, 'context.from', contextFrom.filter((p) => p !== phaseName));
  };

  const handleDirectChange = (checked) => {
    updatePhaseField(index, 'context.direct', checked);
  };

  return (
    <div className="drawer-content context-drawer">
      <div className="drawer-field">
        <label>Include context from phases</label>
        <div className="context-phases">
          {contextFrom.map((phaseName) => (
            <div key={phaseName} className="context-phase-chip">
              <Icon icon="mdi:view-sequential" width="12" />
              <span>{phaseName}</span>
              <button
                className="chip-remove"
                onClick={() => handleRemovePhase(phaseName)}
                type="button"
              >
                <Icon icon="mdi:close" width="12" />
              </button>
            </div>
          ))}

          {otherPhases.length > contextFrom.length && (
            <select
              className="context-add-select"
              value=""
              onChange={(e) => {
                if (e.target.value) {
                  handleAddPhase(e.target.value);
                }
              }}
            >
              <option value="">Add phase...</option>
              {otherPhases
                .filter((name) => !contextFrom.includes(name))
                .map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
            </select>
          )}
        </div>
        <span className="field-hint">
          Select phases whose output/context should be available to this phase
        </span>
      </div>

      <div className="drawer-field checkbox">
        <label>
          <input
            type="checkbox"
            checked={context.direct || false}
            onChange={(e) => handleDirectChange(e.target.checked)}
          />
          <span>Direct context (pass full message history, not just output)</span>
        </label>
      </div>

      {contextFrom.length === 0 && (
        <div className="context-hint">
          <Icon icon="mdi:information" width="16" />
          <span>
            By default, phases only receive context from the immediate previous phase.
            Use this to pull context from other specific phases.
          </span>
        </div>
      )}
    </div>
  );
}

export default PhaseBlock;
