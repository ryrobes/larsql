/**
 * JinjaEditor - Rich Jinja2 template editor with variable pills
 *
 * Usage:
 *
 * import { JinjaEditor, getAvailableVariables } from './jinja-editor';
 *
 * const variables = getAvailableVariables(cascade, cellIndex);
 *
 * <JinjaEditor
 *   value={instructions}
 *   onChange={setInstructions}
 *   availableVariables={variables}
 *   placeholder="Enter cell instructions..."
 * />
 */

import JinjaEditor, { parseJinjaText, serializeToJinja } from './JinjaEditor';
import VariablePalette from './VariablePalette';
import getAvailableVariables, { getGroupedVariables, BUILTIN_VARIABLES } from './getAvailableVariables';
import { VariableNode, $createVariableNode, $isVariableNode, VARIABLE_TYPES, getVariableType } from './VariableNode';

export {
  JinjaEditor,
  VariablePalette,
  getAvailableVariables,
  getGroupedVariables,
  BUILTIN_VARIABLES,
  VariableNode,
  $createVariableNode,
  $isVariableNode,
  VARIABLE_TYPES,
  getVariableType,
  parseJinjaText,
  serializeToJinja,
};
