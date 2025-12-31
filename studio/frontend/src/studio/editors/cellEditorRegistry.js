/**
 * Cell Editor Registry
 *
 * Simple rules-based component router for custom cell editors.
 *
 * Each editor is just:
 * - id: Unique identifier
 * - label: Tab label
 * - icon: Optional Material-UI icon name
 * - match: Function that returns true if this editor handles this cell
 * - component: React component that receives (cell, onChange, cellName) props
 *
 * Editors are just form builders - they receive a cell map and return an updated cell map.
 */

// Registry array - add new editors here
const CELL_EDITORS = [];

/**
 * Register a cell editor
 *
 * @param {Object} editor - Editor definition
 * @param {string} editor.id - Unique identifier
 * @param {string} editor.label - Display label for tab
 * @param {string} [editor.icon] - Material-UI icon name
 * @param {Function} editor.match - (cell) => boolean
 * @param {React.Component} editor.component - Editor component
 */
export function registerCellEditor(editor) {
  // Validate required fields
  if (!editor.id || !editor.label || !editor.match || !editor.component) {
    console.error('Invalid cell editor registration:', editor);
    return;
  }

  // Check for duplicate IDs
  if (CELL_EDITORS.find(e => e.id === editor.id)) {
    console.warn(`Cell editor with id "${editor.id}" already registered, skipping`);
    return;
  }

  CELL_EDITORS.push(editor);
}

/**
 * Detect which custom editors are available for a given cell
 *
 * @param {Object} cell - Cell configuration (just a map)
 * @returns {Array<Object>} - Array of matching editor definitions
 */
export function detectCellEditors(cell) {
  if (!cell) return [];

  return CELL_EDITORS.filter(editor => {
    try {
      return editor.match(cell);
    } catch (error) {
      console.error(`Error in match function for editor "${editor.id}":`, error);
      return false;
    }
  });
}

/**
 * Get editor definition by ID
 *
 * @param {string} editorId - Editor ID
 * @returns {Object|null} - Editor definition or null
 */
export function getCellEditor(editorId) {
  return CELL_EDITORS.find(e => e.id === editorId) || null;
}

/**
 * Get all registered editors
 *
 * @returns {Array<Object>} - All editor definitions
 */
export function getAllCellEditors() {
  return [...CELL_EDITORS];
}

// Export the registry for inspection
export { CELL_EDITORS };
