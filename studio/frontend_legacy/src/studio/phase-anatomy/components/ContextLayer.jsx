import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * ContextLayer - Shows context injection from other phases
 */
const ContextLayer = ({ context }) => {
  if (!context) return null;

  const from = context.from || [];
  const include = context.include || ['output'];

  return (
    <div className="cell-anatomy-layer cell-anatomy-layer-context">
      <div className="cell-anatomy-layer-header">
        <div className="cell-anatomy-layer-icon layer-icon-context">
          <Icon icon="mdi:link-variant" width="14" />
        </div>
        <span className="cell-anatomy-layer-title">Context Injection</span>
      </div>

      <div className="cell-anatomy-layer-content">
        {/* From phases */}
        <div className="layer-context-sources">
          <span className="layer-context-label">from:</span>
          <div className="layer-context-chips">
            {(Array.isArray(from) ? from : [from]).map((source, idx) => (
              <span key={idx} className="layer-context-chip layer-context-chip-source">
                <Icon icon="mdi:chevron-right" width="12" />
                {source}
              </span>
            ))}
          </div>
        </div>

        {/* Include types */}
        <div className="layer-context-includes">
          <span className="layer-context-label">include:</span>
          <div className="layer-context-chips">
            {(Array.isArray(include) ? include : [include]).map((type, idx) => (
              <span key={idx} className="layer-context-chip layer-context-chip-type">
                {type === 'output' && <Icon icon="mdi:export" width="12" />}
                {type === 'images' && <Icon icon="mdi:image" width="12" />}
                {type === 'messages' && <Icon icon="mdi:message" width="12" />}
                {type === 'state' && <Icon icon="mdi:database" width="12" />}
                {type}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ContextLayer;
