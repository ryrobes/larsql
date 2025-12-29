/**
 * Phase Editor Registry
 *
 * Simple rules-based component router for custom phase editors.
 *
 * Each editor is just:
 * - id: Unique identifier
 * - label: Tab label
 * - icon: Optional Material-UI icon name
 * - match: Function that returns true if this editor handles this phase
 * - component: React component that receives (phase, onChange, phaseName) props
 *
 * Editors are just form builders - they receive a phase map and return an updated phase map.
 */

// Registry array - add new editors here
const PHASE_EDITORS = [];

/**
 * Register a phase editor
 *
 * @param {Object} editor - Editor definition
 * @param {string} editor.id - Unique identifier
 * @param {string} editor.label - Display label for tab
 * @param {string} [editor.icon] - Material-UI icon name
 * @param {Function} editor.match - (phase) => boolean
 * @param {React.Component} editor.component - Editor component
 */
export function registerPhaseEditor(editor) {
  // Validate required fields
  if (!editor.id || !editor.label || !editor.match || !editor.component) {
    console.error('Invalid phase editor registration:', editor);
    return;
  }

  // Check for duplicate IDs
  if (PHASE_EDITORS.find(e => e.id === editor.id)) {
    console.warn(`Phase editor with id "${editor.id}" already registered, skipping`);
    return;
  }

  PHASE_EDITORS.push(editor);
}

/**
 * Detect which custom editors are available for a given phase
 *
 * @param {Object} phase - Phase configuration (just a map)
 * @returns {Array<Object>} - Array of matching editor definitions
 */
export function detectPhaseEditors(phase) {
  if (!phase) return [];

  return PHASE_EDITORS.filter(editor => {
    try {
      return editor.match(phase);
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
export function getPhaseEditor(editorId) {
  return PHASE_EDITORS.find(e => e.id === editorId) || null;
}

/**
 * Get all registered editors
 *
 * @returns {Array<Object>} - All editor definitions
 */
export function getAllPhaseEditors() {
  return [...PHASE_EDITORS];
}

// Export the registry for inspection
export { PHASE_EDITORS };
