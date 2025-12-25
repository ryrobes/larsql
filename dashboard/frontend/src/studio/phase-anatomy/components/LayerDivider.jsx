import React from 'react';
import './layers.css';

/**
 * LayerDivider - Visual separator between layers
 */
const LayerDivider = ({ type = 'minor', label }) => {
  return (
    <div className={`cell-anatomy-divider cell-anatomy-divider-${type}`}>
      {label && (
        <span className="cell-anatomy-divider-label">{label}</span>
      )}
    </div>
  );
};

export default LayerDivider;
