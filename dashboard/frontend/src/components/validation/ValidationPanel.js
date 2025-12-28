/**
 * ValidationPanel - Displays spec validation issues
 *
 * Shows errors, warnings, and suggestions from cascade spec validation.
 * Used in the Playground card editor.
 */

import React from 'react';
import { Icon } from '@iconify/react';
import './ValidationPanel.css';

/**
 * Get icon and color for issue level
 */
function getIssueStyle(level) {
  switch (level) {
    case 'error':
      return { icon: 'mdi:alert-circle', color: '#f87171', label: 'Error' };
    case 'warning':
      return { icon: 'mdi:alert', color: '#fbbf24', label: 'Warning' };
    case 'suggestion':
      return { icon: 'mdi:lightbulb', color: '#60a5fa', label: 'Suggestion' };
    default:
      return { icon: 'mdi:information', color: '#888', label: 'Info' };
  }
}

/**
 * Single validation issue row
 */
function ValidationIssue({ issue, onClick }) {
  const style = getIssueStyle(issue.level);

  return (
    <div
      className={`validation-issue validation-issue-${issue.level}`}
      onClick={() => onClick?.(issue)}
      title={issue.fix_hint || issue.message}
    >
      <Icon icon={style.icon} width="14" style={{ color: style.color }} />
      <span className="issue-code">{issue.code}</span>
      <span className="issue-message">{issue.message}</span>
      {issue.cell_name && (
        <span className="issue-cell">{issue.cell_name}</span>
      )}
    </div>
  );
}

/**
 * ValidationPanel component
 *
 * @param {Object} props
 * @param {Array} props.errors - Error-level issues
 * @param {Array} props.warnings - Warning-level issues
 * @param {Array} props.suggestions - Suggestion-level issues
 * @param {boolean} props.isValidating - True while validation in progress
 * @param {string|null} props.parseError - Parse error if any
 * @param {Function} props.onIssueClick - Called when an issue is clicked
 * @param {boolean} props.collapsed - Start collapsed (default: false)
 */
function ValidationPanel({
  errors = [],
  warnings = [],
  suggestions = [],
  isValidating = false,
  parseError = null,
  onIssueClick,
  collapsed = false,
}) {
  const [isCollapsed, setIsCollapsed] = React.useState(collapsed);

  const totalIssues = errors.length + warnings.length + suggestions.length;
  const hasErrors = errors.length > 0;
  const hasWarnings = warnings.length > 0;

  // If no issues and no parse error, don't show panel
  if (!parseError && totalIssues === 0 && !isValidating) {
    return null;
  }

  return (
    <div className={`validation-panel ${isCollapsed ? 'collapsed' : ''}`}>
      {/* Header */}
      <div
        className="validation-header"
        onClick={() => setIsCollapsed(!isCollapsed)}
      >
        <div className="validation-summary">
          {isValidating ? (
            <>
              <Icon icon="mdi:loading" width="14" className="spinning" />
              <span>Validating...</span>
            </>
          ) : parseError ? (
            <>
              <Icon icon="mdi:alert-circle" width="14" style={{ color: '#f87171' }} />
              <span>Parse Error</span>
            </>
          ) : (
            <>
              {hasErrors && (
                <span className="issue-count error-count">
                  <Icon icon="mdi:alert-circle" width="12" />
                  {errors.length}
                </span>
              )}
              {hasWarnings && (
                <span className="issue-count warning-count">
                  <Icon icon="mdi:alert" width="12" />
                  {warnings.length}
                </span>
              )}
              {!hasErrors && !hasWarnings && totalIssues === 0 && (
                <span className="validation-ok">
                  <Icon icon="mdi:check-circle" width="14" style={{ color: '#34d399' }} />
                  Valid
                </span>
              )}
            </>
          )}
        </div>
        <Icon
          icon={isCollapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'}
          width="16"
          className="collapse-icon"
        />
      </div>

      {/* Issues list */}
      {!isCollapsed && (
        <div className="validation-issues">
          {parseError && (
            <div className="validation-issue validation-issue-error parse-error">
              <Icon icon="mdi:alert-circle" width="14" style={{ color: '#f87171' }} />
              <span className="issue-message">{parseError}</span>
            </div>
          )}

          {errors.map((issue, idx) => (
            <ValidationIssue
              key={`error-${idx}`}
              issue={issue}
              onClick={onIssueClick}
            />
          ))}

          {warnings.map((issue, idx) => (
            <ValidationIssue
              key={`warning-${idx}`}
              issue={issue}
              onClick={onIssueClick}
            />
          ))}

          {suggestions.map((issue, idx) => (
            <ValidationIssue
              key={`suggestion-${idx}`}
              issue={issue}
              onClick={onIssueClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default ValidationPanel;
