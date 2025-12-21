import React, { useState, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useNotebookStore from '../stores/notebookStore';

/**
 * VariablePalette - Draggable Jinja2 variables for cascade building
 *
 * Introspects cascade to show available variables:
 * - input.* (from inputs_schema)
 * - outputs.* (from previous phases)
 * - state.* (from state usage)
 * - Built-ins (lineage, history, sounding_index, etc.)
 */

// Variable type metadata
const VARIABLE_TYPES = {
  input: { icon: 'mdi:import', color: '#a78bfa', label: 'Input' },
  output: { icon: 'mdi:export', color: '#60a5fa', label: 'Output' },
  state: { icon: 'mdi:database', color: '#34d399', label: 'State' },
  builtin: { icon: 'mdi:cog', color: '#fbbf24', label: 'Built-in' },
};

// Built-in variables available in all phases
const BUILTIN_VARIABLES = [
  { path: 'lineage', description: 'Execution path through phases' },
  { path: 'history', description: 'Full conversation history' },
  { path: 'sounding_index', description: 'Current sounding index (0, 1, 2...)' },
  { path: 'sounding_factor', description: 'Total number of soundings' },
  { path: 'is_sounding', description: 'True when running as sounding' },
];

/**
 * Determine variable type from path
 */
function getVariableType(path) {
  if (path.startsWith('input.')) return 'input';
  if (path.startsWith('outputs.')) return 'output';
  if (path.startsWith('state.')) return 'state';
  return 'builtin';
}

/**
 * Draggable variable pill
 */
function VariablePill({ variable }) {
  const type = getVariableType(variable.path);
  const config = VARIABLE_TYPES[type];

  // Short display label (remove prefix)
  const displayLabel = variable.path
    .replace(/^input\./, '')
    .replace(/^outputs\./, '')
    .replace(/^state\./, '');

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `variable-${variable.path}`,
    data: { type: 'variable', variablePath: variable.path },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`var-pill var-pill-${type} ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: config.color }}
      title={variable.description || `{{ ${variable.path} }}`}
    >
      <Icon icon={config.icon} width="12" style={{ color: config.color }} />
      <span style={{ color: config.color }}>{displayLabel}</span>
    </div>
  );
}

/**
 * Collapsible variable group
 */
function VariableGroup({ title, icon, variables, defaultOpen = true }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);

  if (variables.length === 0) return null;

  return (
    <div className="var-group">
      <div
        className="var-group-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="var-group-chevron"
        />
        <span className="var-group-icon">{icon}</span>
        <span className="var-group-title">{title}</span>
        <span className="var-group-count">{variables.length}</span>
      </div>

      {isExpanded && (
        <div className="var-group-content">
          {variables.map(v => (
            <VariablePill key={v.path} variable={v} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main VariablePalette component
 */
function VariablePalette() {
  const { notebook } = useNotebookStore();

  // Introspect cascade for available variables
  const variables = useMemo(() => {
    const vars = [];

    if (!notebook) return vars;

    // 1. Input variables
    if (notebook.inputs_schema) {
      Object.entries(notebook.inputs_schema).forEach(([key, description]) => {
        vars.push({
          path: `input.${key}`,
          description: typeof description === 'string' ? description : `Input: ${key}`,
        });
      });
    }

    // 2. Previous phase outputs
    if (notebook.phases) {
      notebook.phases.forEach((phase) => {
        if (phase.name) {
          vars.push({
            path: `outputs.${phase.name}`,
            description: `Output from phase "${phase.name}"`,
          });
        }
      });
    }

    // 3. State variables (scan for state.* usage)
    const stateVars = new Set();
    const statePattern = /state\.(\w+)/g;
    notebook.phases?.forEach((phase) => {
      const codeToScan = phase.inputs?.code || phase.inputs?.query || phase.instructions || '';
      let match;
      while ((match = statePattern.exec(codeToScan)) !== null) {
        stateVars.add(match[1]);
      }
    });
    stateVars.forEach(varName => {
      vars.push({
        path: `state.${varName}`,
        description: `State variable: ${varName}`,
      });
    });

    // 4. Built-ins
    BUILTIN_VARIABLES.forEach(builtin => {
      vars.push(builtin);
    });

    return vars;
  }, [notebook]);

  // Group by type
  const grouped = useMemo(() => {
    return {
      input: variables.filter(v => v.path.startsWith('input.')),
      output: variables.filter(v => v.path.startsWith('outputs.')),
      state: variables.filter(v => v.path.startsWith('state.')),
      builtin: variables.filter(v =>
        !v.path.startsWith('input.') &&
        !v.path.startsWith('outputs.') &&
        !v.path.startsWith('state.')
      ),
    };
  }, [variables]);

  if (variables.length === 0) return null;

  return (
    <div className="nav-section var-palette-section">
      <div className="nav-section-header">
        <Icon icon="mdi:code-braces" className="nav-section-icon" />
        <span className="nav-section-title">Variables</span>
      </div>

      <div className="nav-section-content var-palette-content">
        <div className="var-palette-hint">
          Drag to code editor →
        </div>

        <VariableGroup
          title="Inputs"
          icon="📥"
          variables={grouped.input}
        />
        <VariableGroup
          title="Previous Phases"
          icon="📤"
          variables={grouped.output}
        />
        <VariableGroup
          title="State"
          icon="📦"
          variables={grouped.state}
        />
        <VariableGroup
          title="Built-ins"
          icon="⚙️"
          variables={grouped.builtin}
          defaultOpen={false}
        />
      </div>
    </div>
  );
}

export default VariablePalette;
