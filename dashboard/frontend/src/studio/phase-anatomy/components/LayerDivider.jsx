import React from 'react';
import './layers.css';

/**
 * LayerDivider - Visual separator between layers
 */
const LayerDivider = ({ type = 'minor', label }) => {
  return (
    <div className={`phase-anatomy-divider phase-anatomy-divider-${type}`}>
      {label && (
        <span className="phase-anatomy-divider-label">{label}</span>
      )}
    </div>
  );
};

export default LayerDivider;
