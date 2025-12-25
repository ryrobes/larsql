import React, { useState, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';

/**
 * VariablePalette - Draggable Jinja2 variables for cascade building
 *
 * Introspects cascade to show available variables:
 * - input.* (from inputs_schema)
 * - outputs.* (from previous cells)
 * - state.* (from state usage)
 * - Built-ins (lineage, history, candidate_index, etc.)
 */

// Variable type metadata
const VARIABLE_TYPES = {
  input: { icon: 'mdi:import', color: '#a78bfa', label: 'Input' },
  output: { icon: 'mdi:export-variant', color: '#60a5fa', label: 'Output' },
  state: { icon: 'mdi:database-outline', color: '#34d399', label: 'State' },
  builtin: { icon: 'mdi:cog-outline', color: '#fbbf24', label: 'Built-in' },
};

// Built-in variables available in all cells
const BUILTIN_VARIABLES = [
  { path: 'lineage', description: 'Execution path through cells' },
  { path: 'history', description: 'Full conversation history' },
  { path: 'candidate_index', description: 'Current candidate index (0, 1, 2...)' },
  { path: 'candidate_factor', description: 'Total number of candidates' },
  { path: 'is_candidate', description: 'True when running as candidate' },
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
      style={{ borderColor: config.color + 34 }}
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
function VariableGroup({ title, iconName, variables, defaultOpen = true }) {
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
        <Icon icon={iconName} width="12" className="var-group-icon" />
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
  const { cascade } = useStudioCascadeStore();

  // Introspect cascade for available variables
  const variables = useMemo(() => {
    const vars = [];

    if (!cascade) return vars;

    // 1. Input variables
    if (cascade.inputs_schema) {
      Object.entries(cascade.inputs_schema).forEach(([key, description]) => {
        vars.push({
          path: `input.${key}`,
          description: typeof description === 'string' ? description : `Input: ${key}`,
        });
      });
    }

    // 2. Previous cell outputs
    if (cascade.cells) {
      cascade.cells.forEach((cell) => {
        if (cell.name) {
          vars.push({
            path: `outputs.${cell.name}`,
            description: `Output from cell "${cell.name}"`,
          });
        }
      });
    }

    // 3. State variables (scan for state.* usage)
    const stateVars = new Set();
    const statePattern = /state\.(\w+)/g;
    cascade.cells?.forEach((cell) => {
      const codeToScan = cell.inputs?.code || cell.inputs?.query || cell.instructions || '';
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
  }, [cascade]);

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


        <VariableGroup
          title="Inputs"
          iconName="mdi:import"
          variables={grouped.input}
        />
        <VariableGroup
          title="Previous Cells"
          iconName="mdi:export-variant"
          variables={grouped.output}
        />
        <VariableGroup
          title="State"
          iconName="mdi:database-outline"
          variables={grouped.state}
        />
        <VariableGroup
          title="Built-ins"
          iconName="mdi:cog-outline"
          variables={grouped.builtin}
          defaultOpen={false}
        />
      </div>
    </div>
  );
}

export default VariablePalette;
