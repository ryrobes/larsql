/**
 * VariableNode - Lexical DecoratorNode for Jinja2 variable pills
 *
 * Renders {{ input.foo }} as an inline pill that can be:
 * - Displayed inline with text
 * - Deleted with backspace
 * - Dragged from palette
 * - Serialized to/from Jinja2 syntax
 */

import { DecoratorNode } from 'lexical';
import React from 'react';

// Variable type icons and colors
const VARIABLE_TYPES = {
  input: { icon: '📥', color: '#a78bfa', label: 'Input' },
  output: { icon: '📤', color: '#60a5fa', label: 'Output' },
  state: { icon: '📦', color: '#34d399', label: 'State' },
  builtin: { icon: '⚙️', color: '#fbbf24', label: 'Built-in' },
};

/**
 * Determine the type of a variable from its path
 */
function getVariableType(path) {
  if (path.startsWith('input.')) return 'input';
  if (path.startsWith('outputs.')) return 'output';
  if (path.startsWith('state.')) return 'state';
  return 'builtin';
}

/**
 * VariablePill - React component rendered inside the editor
 */
function VariablePill({ path, onDelete }) {
  const type = getVariableType(path);
  const config = VARIABLE_TYPES[type];

  // Format the display label (remove prefix for cleaner look)
  const displayLabel = path
    .replace(/^input\./, '')
    .replace(/^outputs\./, '')
    .replace(/^state\./, '');

  return (
    <span
      className={`variable-pill variable-pill-${type}`}
      style={{ '--pill-color': config.color }}
      title={`{{ ${path} }}`}
      data-variable-path={path}
    >
      <span className="variable-pill-icon">{config.icon}</span>
      <span className="variable-pill-label">{displayLabel}</span>
    </span>
  );
}

/**
 * VariableNode - Lexical node for inline variable pills
 */
export class VariableNode extends DecoratorNode {
  __path;

  static getType() {
    return 'variable';
  }

  static clone(node) {
    return new VariableNode(node.__path, node.__key);
  }

  constructor(path, key) {
    super(key);
    this.__path = path;
  }

  createDOM() {
    const span = document.createElement('span');
    span.className = 'variable-node-wrapper';
    return span;
  }

  updateDOM() {
    return false;
  }

  // Export to JSON for serialization
  static importJSON(serializedNode) {
    const { path } = serializedNode;
    return $createVariableNode(path);
  }

  exportJSON() {
    return {
      type: 'variable',
      path: this.__path,
      version: 1,
    };
  }

  // Text content for copy/paste and serialization
  getTextContent() {
    return `{{ ${this.__path} }}`;
  }

  // Required for DecoratorNode - renders the React component
  decorate() {
    return <VariablePill path={this.__path} />;
  }

  // Mark as inline (not block-level)
  isInline() {
    return true;
  }

  // Not editable directly - the whole pill is atomic
  canInsertTextBefore() {
    return true;
  }

  canInsertTextAfter() {
    return true;
  }

  // Get the path
  getPath() {
    return this.__path;
  }
}

/**
 * Factory function to create a VariableNode
 */
export function $createVariableNode(path) {
  return new VariableNode(path);
}

/**
 * Type guard to check if a node is a VariableNode
 */
export function $isVariableNode(node) {
  return node instanceof VariableNode;
}

export { VARIABLE_TYPES, getVariableType };
