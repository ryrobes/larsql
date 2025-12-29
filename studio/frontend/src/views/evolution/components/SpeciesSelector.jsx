import React from 'react';
import { Icon } from '@iconify/react';
import './SpeciesSelector.css';

/**
 * SpeciesChip - Compact clickable chip for a species
 */
function SpeciesChip({ species, isSelected, onClick }) {
  const shortHash = species.species_hash?.slice(0, 8) || 'unknown';
  const avgCost = species.avg_cost || 0;

  return (
    <button
      className={`species-chip ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
      title={`Species ${shortHash}\n${species.session_count} generations · ${species.total_attempts || 0} total attempts\nAvg cost per gen: $${avgCost.toFixed(5)}\nTotal cost: $${species.total_cost?.toFixed(4) || '0'}`}
    >
      <Icon icon="mdi:dna" width="12" />
      <span className="chip-hash">{shortHash}</span>
      {isSelected && <Icon icon="mdi:check-circle" width="12" className="check-icon" />}
      <div className="chip-stats-inline">
        <span className="stat-item">{species.session_count}gen</span>
        <span className="stat-item">{species.total_attempts}att</span>
        {avgCost > 0 && (
          <span className="stat-item cost">${avgCost.toFixed(4)}</span>
        )}
      </div>
    </button>
  );
}

/**
 * SpeciesSelector - Compact horizontal chip selector
 *
 * Props:
 * - species: Array of species objects
 * - selected: Selected species hash
 * - onSelect: Callback when species selected
 */
const SpeciesSelector = ({ species, selected, onSelect }) => {
  if (!species || species.length === 0) {
    return null;
  }

  return (
    <div className="species-selector-compact">
      <Icon icon="mdi:dna" width="14" className="selector-label-icon" />
      <span className="selector-label">Species:</span>
      <div className="species-chips">
        {species.map(s => (
          <SpeciesChip
            key={s.species_hash}
            species={s}
            isSelected={selected === s.species_hash}
            onClick={() => onSelect(s.species_hash)}
          />
        ))}
      </div>
      <span className="species-count-compact">{species.length} found</span>
    </div>
  );
};

export default SpeciesSelector;
