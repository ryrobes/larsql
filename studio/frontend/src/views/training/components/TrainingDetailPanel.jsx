import React from 'react';
import { Icon } from '@iconify/react';
import { useNavigate } from 'react-router-dom';
import { ROUTES } from '../../../routes.helpers';
import './TrainingDetailPanel.css';

/**
 * TrainingDetailPanel - Detail view for selected training example
 * Shows full input/output, metadata, and actions
 */
const TrainingDetailPanel = ({ example, onClose }) => {
  const navigate = useNavigate();

  if (!example) return null;

  // Parse user_input JSON if it's JSON
  const formatUserInput = () => {
    try {
      const parsed = JSON.parse(example.user_input);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return example.user_input;
    }
  };

  // Parse assistant_output if it's JSON
  const formatAssistantOutput = () => {
    const output = example.assistant_output;
    // Strip quotes if simple quoted string
    if (output.startsWith('"') && output.endsWith('"')) {
      const unquoted = output.slice(1, -1);
      // Try to parse as JSON
      try {
        const parsed = JSON.parse(unquoted);
        return JSON.stringify(parsed, null, 2);
      } catch {
        return unquoted;
      }
    }
    // Try to parse as JSON
    try {
      const parsed = JSON.parse(output);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return output;
    }
  };

  // Navigate to session
  const handleNavigateToSession = () => {
    if (example.session_id && example.cascade_id) {
      navigate(ROUTES.studioWithSession(example.cascade_id, example.session_id));
    }
  };

  // Extract TEXT and CRITERION from user_input if it's semantic SQL
  const extractSemanticParams = () => {
    const input = formatUserInput();
    const textMatch = input.match(/TEXT:\s*([^\n]+)/);
    const criterionMatch = input.match(/CRITERION:\s*([^\n]+)/);

    if (textMatch && criterionMatch) {
      return {
        text: textMatch[1].trim(),
        criterion: criterionMatch[1].trim(),
        isSemanticSQL: true
      };
    }
    return { isSemanticSQL: false };
  };

  const semanticParams = extractSemanticParams();

  return (
    <div className="training-detail-panel">
      {/* Header */}
      <div className="training-detail-header">
        <div className="training-detail-title">
          <Icon icon="mdi:information" width={16} style={{ color: '#00e5ff' }} />
          <span className="training-detail-cascade">{example.cascade_id}</span>
          <span className="training-detail-sep">·</span>
          <span className="training-detail-cell">{example.cell_name}</span>
          {example.model && (
            <>
              <span className="training-detail-sep">·</span>
              <span className="training-detail-model">{example.model}</span>
            </>
          )}
        </div>
        <div className="training-detail-meta">
          {example.cost > 0 && (
            <span className="training-detail-cost">${example.cost.toFixed(4)}</span>
          )}
          {example.tokens_in > 0 && (
            <span className="training-detail-tokens">{example.tokens_in.toLocaleString()} in</span>
          )}
          {example.tokens_out > 0 && (
            <span className="training-detail-tokens">{example.tokens_out.toLocaleString()} out</span>
          )}
          <button className="training-detail-close" onClick={onClose} title="Close detail panel">
            <Icon icon="mdi:close" width={16} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="training-detail-body">
        {/* Semantic SQL Parameters (if applicable) */}
        {semanticParams.isSemanticSQL && (
          <div className="training-detail-section training-detail-section-semantic">
            <div className="training-detail-section-header">
              <Icon icon="mdi:database-search" width={14} />
              <span>Semantic SQL Parameters</span>
            </div>
            <div className="training-semantic-params">
              <div className="training-semantic-param">
                <span className="training-semantic-label">TEXT:</span>
                <code className="training-semantic-value">{semanticParams.text}</code>
              </div>
              <div className="training-semantic-param">
                <span className="training-semantic-label">CRITERION:</span>
                <code className="training-semantic-value">{semanticParams.criterion}</code>
              </div>
            </div>
          </div>
        )}

        {/* User Input Section */}
        <div className="training-detail-section">
          <div className="training-detail-section-header">
            <Icon icon="mdi:code-braces" width={14} />
            <span>User Input (Full Request)</span>
            <span className="training-detail-section-size">{example.user_input.length} chars</span>
          </div>
          <div className="training-detail-code-container">
            <pre className="training-detail-code">{formatUserInput()}</pre>
          </div>
        </div>

        {/* Assistant Output Section */}
        <div className="training-detail-section">
          <div className="training-detail-section-header">
            <Icon icon="mdi:message-reply" width={14} />
            <span>Assistant Output</span>
            {example.assistant_output.startsWith('"') && example.assistant_output.endsWith('"') && (
              <span className="training-detail-badge" style={{ background: 'rgba(52, 211, 153, 0.1)', color: '#34d399' }}>
                Quoted String
              </span>
            )}
          </div>
          <div className="training-detail-code-container">
            <pre className="training-detail-code training-detail-code-output">{formatAssistantOutput()}</pre>
          </div>
        </div>

        {/* Metadata Section */}
        <div className="training-detail-section">
          <div className="training-detail-section-header">
            <Icon icon="mdi:tag" width={14} />
            <span>Metadata</span>
          </div>
          <div className="training-detail-metadata">
            <div className="training-metadata-item">
              <span className="training-metadata-label">Trace ID:</span>
              <code className="training-metadata-value">{example.trace_id}</code>
            </div>
            <div className="training-metadata-item">
              <span className="training-metadata-label">Session ID:</span>
              <code className="training-metadata-value training-metadata-link" onClick={handleNavigateToSession}>
                {example.session_id}
                <Icon icon="mdi:open-in-new" width={12} />
              </code>
            </div>
            {example.caller_id && (
              <div className="training-metadata-item">
                <span className="training-metadata-label">Caller ID:</span>
                <code className="training-metadata-value">{example.caller_id}</code>
              </div>
            )}
            <div className="training-metadata-item">
              <span className="training-metadata-label">Timestamp:</span>
              <span className="training-metadata-value">
                {new Date(example.timestamp).toLocaleString()}
              </span>
            </div>
            {example.confidence !== null && example.confidence !== undefined && (
              <div className="training-metadata-item">
                <span className="training-metadata-label">Confidence:</span>
                <span className="training-metadata-value" style={{
                  color: example.confidence >= 0.9 ? '#34d399' : example.confidence >= 0.7 ? '#fbbf24' : '#ff006e'
                }}>
                  {example.confidence.toFixed(2)}
                </span>
              </div>
            )}
            {example.notes && (
              <div className="training-metadata-item">
                <span className="training-metadata-label">Notes:</span>
                <span className="training-metadata-value">{example.notes}</span>
              </div>
            )}
            {example.tags && example.tags.length > 0 && (
              <div className="training-metadata-item">
                <span className="training-metadata-label">Tags:</span>
                <div className="training-metadata-tags">
                  {example.tags.map(tag => (
                    <span key={tag} className="training-tag">{tag}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TrainingDetailPanel;
