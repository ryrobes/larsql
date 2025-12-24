import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * InputLayer - Shows the phase inputs (instructions or tool config)
 */
const InputLayer = ({ inputsSchema, instructions, tool }) => {
  const hasInputs = inputsSchema && Object.keys(inputsSchema).length > 0;
  const hasInstructions = instructions && instructions.length > 0;

  return (
    <div className="phase-anatomy-layer phase-anatomy-layer-input">
      <div className="phase-anatomy-layer-header">
        <div className="phase-anatomy-layer-icon layer-icon-input">
          <Icon icon="mdi:import" width="14" />
        </div>
        <span className="phase-anatomy-layer-title">Input</span>
      </div>

      <div className="phase-anatomy-layer-content">
        {/* Tool invocation */}
        {tool && (
          <div className="layer-input-tool">
            <Icon icon="mdi:function" width="14" />
            <span className="layer-input-tool-name">{tool}</span>
            <span className="layer-input-tool-type">Deterministic</span>
          </div>
        )}

        {/* Instructions preview */}
        {hasInstructions && (
          <div className="layer-input-instructions">
            <div className="layer-input-instructions-label">
              <Icon icon="mdi:text" width="12" />
              Instructions
            </div>
            <div className="layer-input-instructions-preview">
              {instructions.length > 500
                ? instructions.substring(0, 500) + '...'
                : instructions}
            </div>
          </div>
        )}

        {/* Input schema params */}
        {hasInputs && (
          <div className="layer-input-params">
            {Object.entries(inputsSchema).map(([key, desc]) => (
              <div key={key} className="layer-input-param">
                <span className="layer-input-param-key">{'{{ input.' + key + ' }}'}</span>
                <span className="layer-input-param-desc">{desc}</span>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!hasInputs && !hasInstructions && !tool && (
          <div className="layer-empty">
            <Icon icon="mdi:arrow-collapse-down" width="14" />
            <span>No explicit inputs</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default InputLayer;
