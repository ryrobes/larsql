import React from 'react';
import { Icon } from '@iconify/react';
import './SpeciesSelector.css';

/**
 * SpeciesCard - Individual species card
 */
function SpeciesCard({ species, isSelected, onClick }) {
  const shortHash = species.species_hash?.slice(0, 8) || 'unknown';

  return (
    <div
      className={`species-card ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <div className="species-card-header">
        <Icon icon="mdi:dna" width="16" className="dna-icon" />
        <span className="species-hash">{shortHash}</span>
        {isSelected && <Icon icon="mdi:check-circle" width="14" className="selected-icon" />}
      </div>

      {/* Instructions preview */}
      {species.instructions_preview && (
        <div className="species-instructions-preview">
          <Icon icon="mdi:text-box-outline" width="12" />
          <span>{species.instructions_preview}</span>
        </div>
      )}

      {/* Input preview */}
      {species.input_preview && (
        <div className="species-input-preview">
          <Icon icon="mdi:code-json" width="12" />
          <span>{species.input_preview}</span>
        </div>
      )}

      <div className="species-card-stats">
        <span className="stat">
          <Icon icon="mdi:trophy" width="12" />
          {species.winner_count} wins
        </span>
        <span className="stat">
          <Icon icon="mdi:counter" width="12" />
          {species.session_count} sessions
        </span>
        <span
          className="stat win-rate"
          style={{
            color: species.win_rate >= 50 ? '#34d399' : species.win_rate >= 25 ? '#fbbf24' : '#64748b'
          }}
        >
          {species.win_rate?.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

/**
 * SpeciesSelector - Shows available species for selection
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
    <div className="species-selector">
      <div className="species-selector-header">
        <Icon icon="mdi:dna" width="16" />
        <span>Select Species (Prompt DNA)</span>
        <span className="species-count">{species.length} species</span>
      </div>

      <div className="species-grid">
        {species.map(s => (
          <SpeciesCard
            key={s.species_hash}
            species={s}
            isSelected={selected === s.species_hash}
            onClick={() => onSelect(s.species_hash)}
          />
        ))}
      </div>

      {species.length > 1 && (
        <div className="species-hint">
          <Icon icon="mdi:information-outline" width="14" />
          <span>Multiple species detected. Select one for apples-to-apples comparison.</span>
        </div>
      )}
    </div>
  );
};

export default SpeciesSelector;
