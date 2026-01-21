/**
 * Cascade Template Utilities
 *
 * Handles filling cascade templates with data from panel interactions.
 */

/**
 * Fill a cascade template with values from the clicked element's data.
 *
 * Template: @param_set('region', region)
 * Data:     { region: 'US', sales: 1000 }
 * Result:   @param_set('region', 'US')
 *
 * @param {string} template - The cascade template (e.g. "@param_set('key', column)")
 * @param {object} data - The data object from the clicked element
 * @returns {string} The filled cascade expression
 */
export function fillCascadeTemplate(template, data) {
  // Match: @cascade_name(arg1, arg2, ...)
  return template.replace(
    /@(\w+)\(([^)]*)\)/,
    (match, cascadeName, argsStr) => {
      const filledArgs = argsStr.split(',').map(arg => {
        const trimmed = arg.trim();

        // Already a string literal - keep as-is
        if (/^['"].*['"]$/.test(trimmed)) {
          return trimmed;
        }

        // * means entire row as JSON
        if (trimmed === '*') {
          return `'${JSON.stringify(data).replace(/'/g, "''")}'`;
        }

        // Field reference - look up in data
        if (Object.prototype.hasOwnProperty.call(data, trimmed)) {
          const value = data[trimmed];
          if (value === null || value === undefined) return 'NULL';
          if (typeof value === 'number') return String(value);
          if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
          // String value - escape single quotes
          return `'${String(value).replace(/'/g, "''")}'`;
        }

        // Unknown - keep as-is (might be a literal or number)
        return trimmed;
      }).join(', ');

      return `@${cascadeName}(${filledArgs})`;
    }
  );
}

/**
 * Check if a panel has any interaction handlers defined.
 *
 * @param {object} panel - Panel object with potential on_select, on_click, etc.
 * @returns {boolean} True if panel has at least one interaction handler
 */
export function hasInteractions(panel) {
  return !!(panel?.on_select || panel?.on_click || panel?.on_hover);
}
