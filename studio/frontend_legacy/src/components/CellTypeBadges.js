import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import PromptPhylogeny from './PromptPhylogeny';
import './CellTypeBadges.css';

/**
 * CellSpeciesBadges - Compact per-cell species training info
 *
 * Shows for each cell:
 * - Cell name
 * - DNA icon
 * - Training generation (Gen X/Y)
 * - Hash preview on hover
 * - Click to open evolution modal
 */
export default function CellSpeciesBadges({ sessionId }) {
  const [speciesData, setSpeciesData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showEvolution, setShowEvolution] = useState(false);

  useEffect(() => {
    if (!sessionId) return;

    const fetchSpeciesInfo = async () => {
      setLoading(true);

      try {
        const res = await fetch(`/api/sextant/species/${sessionId}`);

        // Silently ignore 404s - many sessions won't have species data
        if (res.status === 404) {
          setLoading(false);
          return;
        }

        const data = await res.json();

        if (!data.error && data.cells && data.cells.length > 0) {
          setSpeciesData(data);
        }
      } catch (err) {
        // Silently fail - species data is optional
      } finally {
        setLoading(false);
      }
    };

    fetchSpeciesInfo();
  }, [sessionId]);

  if (loading || !speciesData || !speciesData.cells) return null;

  // Check if any cell has evolution (Gen 2+)
  const hasEvolution = speciesData.cells.some(p => p.evolution_depth > 1);

  return (
    <>
      <div className="cell-species-badges">
        {speciesData.cells.map((cell, idx) => {
          const isNewSpecies = cell.current_generation === 1;
          const hasTraining = cell.evolution_depth > 1;

          return (
            <div
              key={idx}
              className={`cell-species-badge ${isNewSpecies ? 'new-species' : ''} ${hasEvolution ? 'clickable' : ''}`}
              onClick={(e) => {
                if (hasEvolution) {
                  e.stopPropagation();
                  setShowEvolution(true);
                }
              }}
              title={`Species: ${cell.species_hash}\nCell: ${cell.cell_name}\nEvolution: Gen ${cell.current_generation}/${cell.evolution_depth}\n${hasTraining ? `Trained on ${cell.evolution_depth - 1} previous run${cell.evolution_depth > 2 ? 's' : ''}` : 'First generation - no training'}${hasEvolution ? '\n\nClick to view evolution tree' : ''}`}
            >
              <Icon icon="mdi:dna" width="11" className="dna-icon" />
              <span className="cell-name">{cell.cell_name}</span>
              <span className={`gen-info ${isNewSpecies ? 'new' : ''}`}>
                {cell.current_generation}/{cell.evolution_depth}
              </span>
            </div>
          );
        })}
      </div>

      {/* Evolution Modal */}
      {showEvolution && createPortal(
        <div className="species-evolution-modal-overlay" onClick={() => setShowEvolution(false)}>
          <div className="species-evolution-modal" onClick={(e) => e.stopPropagation()}>
            <div className="species-evolution-header">
              <h2>🧬 Prompt Evolution</h2>
              <button onClick={() => setShowEvolution(false)} className="close-modal-btn">
                <Icon icon="mdi:close" width="24" />
              </button>
            </div>
            <div className="species-evolution-content">
              <PromptPhylogeny sessionId={sessionId} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
