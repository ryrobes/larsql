import React from 'react';
import { Icon } from '@iconify/react';
import './CascadeSelector.css';

/**
 * CascadeSelector - Dropdown to select cascade for evolution analysis
 *
 * Props:
 * - cascades: Array of cascade objects
 * - selected: Selected cascade ID
 * - onSelect: Callback when cascade selected
 * - loading: Loading state
 */
const CascadeSelector = ({ cascades, selected, onSelect, loading }) => {
  return (
    <div className="cascade-selector">
      <Icon icon="mdi:ship-wheel" width="20" className="selector-icon" />
      <select
        value={selected || ''}
        onChange={(e) => onSelect(e.target.value)}
        disabled={loading}
        className="cascade-select"
      >
        <option value="">Select a cascade to analyze...</option>
        {cascades.map(c => (
          <option key={c.cascade_id} value={c.cascade_id}>
            {c.cascade_id} ({c.session_count} runs{c.analysis_ready ? ' - Ready' : ''})
          </option>
        ))}
      </select>
    </div>
  );
};

export default CascadeSelector;
