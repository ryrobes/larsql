import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import PromptPhylogeny from './PromptPhylogeny';
import './PhaseSpeciesBadges.css';

/**
 * PhaseSpeciesBadges - Compact per-phase species training info
 *
 * Shows for each phase:
 * - Phase name
 * - DNA icon
 * - Training generation (Gen X/Y)
 * - Hash preview on hover
 * - Click to open evolution modal
 */
export default function PhaseSpeciesBadges({ sessionId }) {
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

        if (!data.error && data.phases && data.phases.length > 0) {
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

  if (loading || !speciesData || !speciesData.phases) return null;

  // Check if any phase has evolution (Gen 2+)
  const hasEvolution = speciesData.phases.some(p => p.evolution_depth > 1);

  return (
    <>
      <div className="phase-species-badges">
        {speciesData.phases.map((phase, idx) => {
          const isNewSpecies = phase.current_generation === 1;
          const hasTraining = phase.evolution_depth > 1;

          return (
            <div
              key={idx}
              className={`phase-species-badge ${isNewSpecies ? 'new-species' : ''} ${hasEvolution ? 'clickable' : ''}`}
              onClick={(e) => {
                if (hasEvolution) {
                  e.stopPropagation();
                  setShowEvolution(true);
                }
              }}
              title={`Species: ${phase.species_hash}\nPhase: ${phase.phase_name}\nEvolution: Gen ${phase.current_generation}/${phase.evolution_depth}\n${hasTraining ? `Trained on ${phase.evolution_depth - 1} previous run${phase.evolution_depth > 2 ? 's' : ''}` : 'First generation - no training'}${hasEvolution ? '\n\nClick to view evolution tree' : ''}`}
            >
              <Icon icon="mdi:dna" width="11" className="dna-icon" />
              <span className="phase-name">{phase.phase_name}</span>
              <span className={`gen-info ${isNewSpecies ? 'new' : ''}`}>
                {phase.current_generation}/{phase.evolution_depth}
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
