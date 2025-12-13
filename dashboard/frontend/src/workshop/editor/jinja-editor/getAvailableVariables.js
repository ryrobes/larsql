/**
 * getAvailableVariables - Introspect cascade to find all available Jinja2 variables
 *
 * Analyzes the cascade definition and current phase index to determine
 * which variables are available for use in the instructions template.
 */

/**
 * Built-in variables available in all phases
 */
const BUILTIN_VARIABLES = [
  {
    path: 'lineage',
    description: 'Execution path through phases',
  },
  {
    path: 'history',
    description: 'Full conversation history',
  },
  {
    path: 'sounding_index',
    description: 'Current sounding index (0, 1, 2...) when running soundings',
  },
  {
    path: 'sounding_factor',
    description: 'Total number of parallel soundings',
  },
  {
    path: 'is_sounding',
    description: 'True when phase is running as a sounding',
  },
];

/**
 * Get all available variables for a phase
 *
 * @param {Object} cascade - The cascade definition
 * @param {number} currentPhaseIndex - Index of the current phase
 * @returns {Array} - Array of variable objects with path, description, and template
 */
function getAvailableVariables(cascade, currentPhaseIndex) {
  const variables = [];

  // 1. Input schema variables
  if (cascade.inputs_schema) {
    Object.entries(cascade.inputs_schema).forEach(([key, description]) => {
      variables.push({
        path: `input.${key}`,
        description: typeof description === 'string' ? description : `Input: ${key}`,
        template: `{{ input.${key} }}`,
      });
    });
  }

  // 2. Previous phase outputs
  if (cascade.phases && currentPhaseIndex > 0) {
    cascade.phases.slice(0, currentPhaseIndex).forEach((phase) => {
      if (phase.name) {
        variables.push({
          path: `outputs.${phase.name}`,
          description: `Output from phase "${phase.name}"`,
          template: `{{ outputs.${phase.name} }}`,
        });
      }
    });
  }

  // 3. State variables (scan for set_state usage in previous phases)
  const stateVars = extractStateVariables(cascade, currentPhaseIndex);
  stateVars.forEach((varName) => {
    variables.push({
      path: `state.${varName}`,
      description: `State variable: ${varName}`,
      template: `{{ state.${varName} }}`,
    });
  });

  // 4. Built-in variables
  BUILTIN_VARIABLES.forEach((builtin) => {
    variables.push({
      ...builtin,
      template: `{{ ${builtin.path} }}`,
    });
  });

  return variables;
}

/**
 * Extract state variables from cascade phases
 *
 * Looks for patterns like:
 * - set_state tool calls in tackle
 * - state.* references in instructions
 */
function extractStateVariables(cascade, upToIndex) {
  const stateVars = new Set();

  if (!cascade.phases) return Array.from(stateVars);

  // Simple pattern matching for state.* references in instructions
  const statePattern = /state\.(\w+)/g;

  cascade.phases.slice(0, upToIndex).forEach((phase) => {
    if (phase.instructions) {
      let match;
      while ((match = statePattern.exec(phase.instructions)) !== null) {
        stateVars.add(match[1]);
      }
    }

    // Check if set_state is in tackle (user might be setting state)
    if (phase.tackle && phase.tackle.includes('set_state')) {
      // We can't know the exact keys without more info,
      // but we can flag that state is being used
    }
  });

  return Array.from(stateVars);
}

/**
 * Get variables grouped by type
 */
function getGroupedVariables(cascade, currentPhaseIndex) {
  const variables = getAvailableVariables(cascade, currentPhaseIndex);

  return {
    input: variables.filter((v) => v.path.startsWith('input.')),
    output: variables.filter((v) => v.path.startsWith('outputs.')),
    state: variables.filter((v) => v.path.startsWith('state.')),
    builtin: variables.filter(
      (v) =>
        !v.path.startsWith('input.') &&
        !v.path.startsWith('outputs.') &&
        !v.path.startsWith('state.')
    ),
  };
}

export default getAvailableVariables;
export { getGroupedVariables, BUILTIN_VARIABLES };
