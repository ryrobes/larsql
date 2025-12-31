import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import CellsRail from './CellsRail';
import './CascadeCanvas.css';

/**
 * CascadeCanvas - Main editing area for cascade definition
 *
 * Contains:
 * - Cascade header (cascade_id, description, memory)
 * - Inputs schema slot (future)
 * - Validators slot (future)
 * - Cells rail (sortable list of cells)
 */
function CascadeCanvas() {
  const [isHeaderExpanded, setIsHeaderExpanded] = React.useState(false);

  const {
    cascade,
    updateCascadeHeader,
    addInput,
    updateInput,
    removeInput,
    addValidator,
    updateValidator,
    removeValidator,
  } = useWorkshopStore();

  // Droppable zones for inputs and validators
  const { setNodeRef: setInputsRef, isOver: isOverInputs } = useDroppable({
    id: 'inputs-drop-zone',
    data: { accepts: ['input'] },
  });

  const { setNodeRef: setValidatorsRef, isOver: isOverValidators } = useDroppable({
    id: 'validators-drop-zone',
    data: { accepts: ['validator'] },
  });

  const handleIdChange = (e) => {
    // Sanitize cascade_id: lowercase, underscores only
    const value = e.target.value
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, '_')
      .replace(/_+/g, '_');
    updateCascadeHeader('cascade_id', value);
  };

  const inputsSchema = cascade.inputs_schema || {};
  const validators = cascade.validators || {};

  return (
    <div className="cascade-canvas">
      {/* Cascade Header Block */}
      <div className={`cascade-header-block ${isHeaderExpanded ? 'expanded' : 'collapsed'}`}>
        <div
          className="cascade-header-title"
          onClick={() => setIsHeaderExpanded(!isHeaderExpanded)}
        >
          <Icon
            icon={isHeaderExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            width="16"
            className="expand-chevron"
          />
          <Icon icon="mdi:anchor" width="20" />
          <span>Cascade Definition</span>
          {!isHeaderExpanded && (
            <span className="collapsed-summary">{cascade.cascade_id}</span>
          )}
        </div>

        {isHeaderExpanded && (
          <div className="cascade-fields">
            <div className="field-row">
              <label className="field-label">
                <span className="required">*</span>
                cascade_id
              </label>
              <input
                type="text"
                className="field-input"
                value={cascade.cascade_id}
                onChange={handleIdChange}
                placeholder="my_cascade_name"
                spellCheck={false}
              />
            </div>

            <div className="field-row">
              <label className="field-label">description</label>
              <textarea
                className="field-textarea"
                value={cascade.description || ''}
                onChange={(e) => updateCascadeHeader('description', e.target.value)}
                placeholder="What does this cascade do?"
                rows={2}
              />
            </div>

            <div className="field-row">
              <label className="field-label">memory</label>
              <input
                type="text"
                className="field-input"
                value={cascade.memory || ''}
                onChange={(e) => updateCascadeHeader('memory', e.target.value)}
                placeholder="Memory bank name (optional)"
                spellCheck={false}
              />
              <span className="field-hint">
                Creates a memory tool that lets the agent store and recall information across the session
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Inputs Schema Slot */}
      <div
        ref={setInputsRef}
        className={`slot-container inputs-slot ${isOverInputs ? 'drop-active' : ''}`}
      >
        <div className="slot-header">
          <Icon icon="mdi:form-textbox" width="16" />
          <span>Inputs Schema</span>
          <span className="slot-hint">
            {Object.keys(inputsSchema).length} inputs
          </span>
          <button
            className="slot-add-btn"
            onClick={() => addInput(`param_${Object.keys(inputsSchema).length + 1}`, 'Description')}
            title="Add input parameter"
          >
            <Icon icon="mdi:plus" width="14" />
          </button>
        </div>
        {Object.keys(inputsSchema).length > 0 ? (
          <div className="slot-items">
            {Object.entries(inputsSchema).map(([name, description]) => (
              <InputItem
                key={name}
                name={name}
                description={description}
                onUpdate={(newName, newDesc) => updateInput(name, newName, newDesc)}
                onRemove={() => removeInput(name)}
              />
            ))}
          </div>
        ) : (
          <div className={`slot-content empty ${isOverInputs ? 'drop-highlight' : ''}`}>
            <Icon icon="mdi:plus-circle-outline" width="20" />
            <span>{isOverInputs ? 'Drop to add input' : 'Drag Input Param here or click +'}</span>
          </div>
        )}
      </div>

      {/* Validators Slot */}
      <div
        ref={setValidatorsRef}
        className={`slot-container validators-slot ${isOverValidators ? 'drop-active' : ''}`}
      >
        <div className="slot-header">
          <Icon icon="mdi:check-decagram" width="16" />
          <span>Validators</span>
          <span className="slot-hint">
            {Object.keys(validators).length} validators
          </span>
          <button
            className="slot-add-btn"
            onClick={() => addValidator(`validator_${Object.keys(validators).length + 1}`, { instructions: '' })}
            title="Add validator"
          >
            <Icon icon="mdi:plus" width="14" />
          </button>
        </div>
        {Object.keys(validators).length > 0 ? (
          <div className="slot-items">
            {Object.entries(validators).map(([name, config]) => (
              <ValidatorItem
                key={name}
                name={name}
                config={config}
                onUpdate={(newConfig) => updateValidator(name, newConfig)}
                onRemove={() => removeValidator(name)}
              />
            ))}
          </div>
        ) : (
          <div className={`slot-content empty ${isOverValidators ? 'drop-highlight' : ''}`}>
            <Icon icon="mdi:plus-circle-outline" width="20" />
            <span>{isOverValidators ? 'Drop to add validator' : 'Drag Validator here or click +'}</span>
          </div>
        )}
      </div>

      {/* Cells Rail */}
      <div className="cells-section">
        <div className="cells-header">
          <Icon icon="mdi:view-sequential" width="20" />
          <span>Cells</span>
          <span className="cells-count">{cascade.cells?.length || 0} cells</span>
        </div>
        <CellsRail />
      </div>
    </div>
  );
}

/**
 * InputItem - Editable input parameter
 */
function InputItem({ name, description, onUpdate, onRemove }) {
  const [isEditing, setIsEditing] = React.useState(false);
  const [editName, setEditName] = React.useState(name);
  const [editDesc, setEditDesc] = React.useState(description);

  const handleSave = () => {
    const sanitizedName = editName.toLowerCase().replace(/[^a-z0-9_]/g, '_');
    onUpdate(sanitizedName || name, editDesc);
    setIsEditing(false);
  };

  if (isEditing) {
    return (
      <div className="slot-item editing">
        <input
          type="text"
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
          placeholder="param_name"
          className="item-name-input"
          autoFocus
        />
        <input
          type="text"
          value={editDesc}
          onChange={(e) => setEditDesc(e.target.value)}
          placeholder="Description"
          className="item-desc-input"
        />
        <button className="item-save-btn" onClick={handleSave}>
          <Icon icon="mdi:check" width="14" />
        </button>
        <button className="item-cancel-btn" onClick={() => setIsEditing(false)}>
          <Icon icon="mdi:close" width="14" />
        </button>
      </div>
    );
  }

  return (
    <div className="slot-item" onDoubleClick={() => setIsEditing(true)}>
      <Icon icon="mdi:form-textbox" width="14" className="item-icon" />
      <span className="item-name">{name}</span>
      <span className="item-desc">{description}</span>
      <button className="item-remove-btn" onClick={onRemove}>
        <Icon icon="mdi:close" width="12" />
      </button>
    </div>
  );
}

/**
 * ValidatorItem - Editable validator with instructions
 */
function ValidatorItem({ name, config, onUpdate, onRemove }) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  return (
    <div className="slot-item validator-item">
      <div className="validator-header" onClick={() => setIsExpanded(!isExpanded)}>
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="14"
          className="expand-icon"
        />
        <Icon icon="mdi:check-decagram" width="14" className="item-icon teal" />
        <span className="item-name">{name}</span>
        <button
          className="item-remove-btn"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <Icon icon="mdi:close" width="12" />
        </button>
      </div>
      {isExpanded && (
        <div className="validator-content">
          <textarea
            className="validator-instructions"
            value={config.instructions || ''}
            onChange={(e) => onUpdate({ ...config, instructions: e.target.value })}
            placeholder="Validator instructions (Jinja2 supported)..."
            rows={3}
          />
        </div>
      )}
    </div>
  );
}

export default CascadeCanvas;
