/**
 * getAvailableVariables - Introspect cascade to find all available Jinja2 variables
 *
 * Analyzes the cascade definition and current cell index to determine
 * which variables are available for use in the instructions template.
 */

/**
 * Built-in variables available in all cells
 */
const BUILTIN_VARIABLES = [
  {
    path: 'lineage',
    description: 'Execution path through cells',
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
    description: 'True when cell is running as a sounding',
  },
];

/**
 * Get all available variables for a cell
 *
 * @param {Object} cascade - The cascade definition
 * @param {number} currentCellIndex - Index of the current cell
 * @returns {Array} - Array of variable objects with path, description, and template
 */
function getAvailableVariables(cascade, currentCellIndex) {
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

  // 2. Previous cell outputs
  if (cascade.cells && currentCellIndex > 0) {
    cascade.cells.slice(0, currentCellIndex).forEach((cell) => {
      if (cell.name) {
        variables.push({
          path: `outputs.${cell.name}`,
          description: `Output from cell "${cell.name}"`,
          template: `{{ outputs.${cell.name} }}`,
        });
      }
    });
  }

  // 3. State variables (scan for set_state usage in previous cells)
  const stateVars = extractStateVariables(cascade, currentCellIndex);
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
 * Extract state variables from cascade cells
 *
 * Looks for patterns like:
 * - set_state tool calls in tackle
 * - state.* references in instructions
 */
function extractStateVariables(cascade, upToIndex) {
  const stateVars = new Set();

  if (!cascade.cells) return Array.from(stateVars);

  // Simple pattern matching for state.* references in instructions
  const statePattern = /state\.(\w+)/g;

  cascade.cells.slice(0, upToIndex).forEach((cell) => {
    if (cell.instructions) {
      let match;
      while ((match = statePattern.exec(cell.instructions)) !== null) {
        stateVars.add(match[1]);
      }
    }

    // Check if set_state is in tackle (user might be setting state)
    if (cell.traits && cell.traits.includes('set_state')) {
      // We can't know the exact keys without more info,
      // but we can flag that state is being used
    }
  });

  return Array.from(stateVars);
}

/**
 * Get variables grouped by type
 */
function getGroupedVariables(cascade, currentCellIndex) {
  const variables = getAvailableVariables(cascade, currentCellIndex);

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
