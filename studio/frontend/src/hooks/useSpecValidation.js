/**
 * useSpecValidation - Custom hook for cascade spec validation
 *
 * Validates YAML content against the spec validator API with debouncing.
 * Returns validation issues for display in the editor UI.
 *
 * Supports two modes:
 * - Cascade mode: Full cascade YAML with cascade_id and cells
 * - Cell mode: Single cell YAML with cascade context for accurate validation
 */

import { useState, useEffect, useRef, useCallback } from 'react';

const VALIDATION_DEBOUNCE_MS = 500;
const VALIDATE_CASCADE_URL = '/api/spec/validate';
const VALIDATE_CELL_URL = '/api/spec/validate-cell';

/**
 * Detect if YAML is a single cell or full cascade
 */
function isCellYaml(yaml) {
  if (!yaml || typeof yaml !== 'string') return false;
  // Cell YAML has 'name' and 'instructions' or 'tool', but no 'cascade_id' or 'cells'
  const hasCascadeId = /^cascade_id\s*:/m.test(yaml);
  const hasCells = /^cells\s*:/m.test(yaml);
  const hasName = /^name\s*:/m.test(yaml);
  const hasInstructions = /^instructions\s*:/m.test(yaml);
  const hasTool = /^tool\s*:/m.test(yaml);

  return !hasCascadeId && !hasCells && hasName && (hasInstructions || hasTool);
}

/**
 * Wrap cell YAML in a minimal cascade for validation (fallback when no context)
 */
function wrapCellInCascade(cellYaml) {
  return `cascade_id: _validation_temp
cells:
  - ${cellYaml.split('\n').join('\n    ')}
`;
}

/**
 * Validate cascade YAML and return issues
 *
 * @param {string} yamlContent - The YAML content to validate (cascade or cell)
 * @param {Object} options - Options
 * @param {boolean} options.enabled - Whether validation is enabled (default: true)
 * @param {number} options.debounceMs - Debounce delay in ms (default: 500)
 * @param {boolean} options.cellMode - Force cell mode even if content looks like cascade
 * @param {Object} options.cascadeContext - Context for cell-mode validation
 * @param {string[]} options.cascadeContext.cellNames - All cell names in the cascade
 * @param {string} options.cascadeContext.cascadeId - The cascade ID
 *
 * @returns {Object} Validation state
 * @returns {boolean} isValidating - True while validation is in progress
 * @returns {Array} errors - Array of error-level issues
 * @returns {Array} warnings - Array of warning-level issues
 * @returns {boolean} isValid - True if no errors (warnings ok)
 * @returns {string|null} parseError - YAML/schema parse error if any
 */
export function useSpecValidation(yamlContent, options = {}) {
  const {
    enabled = true,
    debounceMs = VALIDATION_DEBOUNCE_MS,
    cellMode = false,
    cascadeContext = null,
  } = options;

  const [isValidating, setIsValidating] = useState(false);
  const [result, setResult] = useState({
    valid: true,
    issues: [],
    parseError: null,
  });

  const debounceRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Validate function
  const validate = useCallback(async (yaml) => {
    if (!yaml || !enabled) {
      setResult({ valid: true, issues: [], parseError: null });
      return;
    }

    // Abort previous request if still pending
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    setIsValidating(true);

    const isCell = cellMode || isCellYaml(yaml);

    try {
      let response;

      if (isCell && cascadeContext) {
        // Use cell-specific endpoint with cascade context
        response = await fetch(VALIDATE_CELL_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cell_yaml: yaml,
            cascade_context: {
              cell_names: cascadeContext.cellNames || [],
              cascade_id: cascadeContext.cascadeId || '_temp',
            },
          }),
          signal: abortControllerRef.current.signal,
        });
      } else if (isCell) {
        // Fallback: wrap in minimal cascade (less accurate for handoffs)
        const yamlToValidate = wrapCellInCascade(yaml);
        response = await fetch(VALIDATE_CASCADE_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cascade_yaml: yamlToValidate }),
          signal: abortControllerRef.current.signal,
        });
      } else {
        // Full cascade validation
        response = await fetch(VALIDATE_CASCADE_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cascade_yaml: yaml }),
          signal: abortControllerRef.current.signal,
        });
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      setResult({
        valid: data.valid,
        issues: data.issues || [],
        parseError: data.parse_error || null,
      });
    } catch (err) {
      if (err.name === 'AbortError') {
        // Ignore aborted requests
        return;
      }
      console.error('Validation error:', err);
      setResult({
        valid: false,
        issues: [],
        parseError: `Validation API error: ${err.message}`,
      });
    } finally {
      setIsValidating(false);
    }
  }, [enabled, cellMode, cascadeContext]);

  // Debounced validation effect
  useEffect(() => {
    if (!enabled) return;

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      validate(yamlContent);
    }, debounceMs);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [yamlContent, validate, debounceMs, enabled]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Derived values
  const errors = result.issues.filter(i => i.level === 'error');
  const warnings = result.issues.filter(i => i.level === 'warning');
  const suggestions = result.issues.filter(i => i.level === 'suggestion');

  return {
    isValidating,
    isValid: result.valid,
    parseError: result.parseError,
    errors,
    warnings,
    suggestions,
    issues: result.issues,
    errorCount: errors.length,
    warningCount: warnings.length,
  };
}

export default useSpecValidation;
