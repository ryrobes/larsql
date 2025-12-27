import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { studioDarkPrismTheme } from '../styles/studioPrismTheme';
import './ParametersCard.css';

function ParametersCard({ instance }) {
  const [showInput, setShowInput] = useState(true);
  const [showOutput, setShowOutput] = useState(true);

  if (!instance) return null;

  const hasInput = instance.input_data && Object.keys(instance.input_data).length > 0;
  const hasOutput = instance.final_output && instance.final_output.trim().length > 0;

  if (!hasInput && !hasOutput) return null;

  return (
    <div className="parameters-section">
      <h3 className="section-title">
        <Icon icon="mdi:code-braces" width="20" />
        Input / Output
      </h3>

      {/* Input Parameters */}
      {hasInput && (
        <div className="parameter-card">
          <div className="parameter-header" onClick={() => setShowInput(!showInput)}>
            <div className="header-left">
              <Icon icon="mdi:import" width="18" />
              <span className="parameter-title">Input Parameters</span>
            </div>
            <button className="toggle-button" title={showInput ? 'Collapse' : 'Expand'}>
              <Icon icon={showInput ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="20" />
            </button>
          </div>
          {showInput && (
            <div className="parameter-content">
              <SyntaxHighlighter
                language="json"
                style={studioDarkPrismTheme}
                customStyle={{ margin: 0, borderRadius: '4px', fontSize: '13px' }}
              >
                {JSON.stringify(instance.input_data, null, 2)}
              </SyntaxHighlighter>
            </div>
          )}
        </div>
      )}

      {/* Output */}
      {hasOutput && (
        <div className="parameter-card">
          <div className="parameter-header" onClick={() => setShowOutput(!showOutput)}>
            <div className="header-left">
              <Icon icon="mdi:export" width="18" />
              <span className="parameter-title">Final Output</span>
            </div>
            <button className="toggle-button" title={showOutput ? 'Collapse' : 'Expand'}>
              <Icon icon={showOutput ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="20" />
            </button>
          </div>
          {showOutput && (
            <div className="parameter-content">
              {/* Try to render as markdown first */}
              <div className="output-markdown">
                <RichMarkdown>
                  {instance.final_output}
                </RichMarkdown>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default React.memo(ParametersCard);
