/**
 * VariablePalette - Draggable palette of available Jinja2 variables
 *
 * Features:
 * - Groups variables by type (input, output, state, builtin)
 * - Drag pills into the editor
 * - Click to insert at cursor
 * - Collapsible sections
 */

import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import { VARIABLE_TYPES, getVariableType } from './VariableNode';

/**
 * Single draggable variable pill
 */
function DraggablePill({ variable, onInsert }) {
  const type = getVariableType(variable.path);
  const config = VARIABLE_TYPES[type];

  // Format display label
  const displayLabel = variable.path
    .replace(/^input\./, '')
    .replace(/^outputs\./, '')
    .replace(/^state\./, '');

  const handleDragStart = (e) => {
    e.dataTransfer.setData('application/x-variable', variable.path);
    e.dataTransfer.effectAllowed = 'copy';

    // Create a drag image
    const dragImage = document.createElement('div');
    dragImage.className = 'variable-drag-ghost';
    dragImage.innerHTML = `<span>${config.icon}</span> ${displayLabel}`;
    dragImage.style.cssText = `
      position: absolute;
      top: -1000px;
      padding: 4px 8px;
      background: ${config.color}33;
      border: 1px solid ${config.color};
      border-radius: 4px;
      font-size: 12px;
      color: ${config.color};
    `;
    document.body.appendChild(dragImage);
    e.dataTransfer.setDragImage(dragImage, 0, 0);

    // Clean up
    setTimeout(() => document.body.removeChild(dragImage), 0);
  };

  const handleClick = () => {
    onInsert?.(variable.path);
  };

  return (
    <div
      className={`palette-pill palette-pill-${type}`}
      style={{ '--pill-color': config.color }}
      draggable
      onDragStart={handleDragStart}
      onClick={handleClick}
      title={variable.description || `{{ ${variable.path} }}`}
    >
      <span className="palette-pill-icon">{config.icon}</span>
      <span className="palette-pill-label">{displayLabel}</span>
    </div>
  );
}

/**
 * Collapsible section for a variable group
 */
function VariableSection({ title, icon, variables, onInsert, defaultOpen = true }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  if (variables.length === 0) return null;

  return (
    <div className={`palette-section ${isOpen ? 'open' : ''}`}>
      <button
        className="palette-section-header"
        onClick={() => setIsOpen(!isOpen)}
      >
        <Icon
          icon={isOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="14"
        />
        <span className="section-icon">{icon}</span>
        <span className="section-title">{title}</span>
        <span className="section-count">{variables.length}</span>
      </button>

      {isOpen && (
        <div className="palette-section-content">
          {variables.map((variable) => (
            <DraggablePill
              key={variable.path}
              variable={variable}
              onInsert={onInsert}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main VariablePalette component
 */
function VariablePalette({ variables, onInsert }) {
  // Group variables by type
  const grouped = useMemo(() => {
    const groups = {
      input: [],
      output: [],
      state: [],
      builtin: [],
    };

    variables.forEach((variable) => {
      const type = getVariableType(variable.path);
      groups[type].push(variable);
    });

    return groups;
  }, [variables]);

  return (
    <div className="variable-palette">
      <div className="palette-header">
        <Icon icon="mdi:code-braces" width="14" />
        <span>Variables</span>
      </div>

      <div className="palette-content">
        <VariableSection
          title="Inputs"
          icon="📥"
          variables={grouped.input}
          onInsert={onInsert}
        />
        <VariableSection
          title="Previous Phases"
          icon="📤"
          variables={grouped.output}
          onInsert={onInsert}
        />
        <VariableSection
          title="State"
          icon="📦"
          variables={grouped.state}
          onInsert={onInsert}
        />
        <VariableSection
          title="Built-ins"
          icon="⚙️"
          variables={grouped.builtin}
          onInsert={onInsert}
          defaultOpen={false}
        />
      </div>

      <div className="palette-hint">
        <Icon icon="mdi:gesture-tap" width="12" />
        <span>Click or drag to insert</span>
      </div>
    </div>
  );
}

export default VariablePalette;
