import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import './EvolveModal.css';

/**
 * DiffView - Shows before/after of prompt evolution
 */
function DiffView({ before, after }) {
  return (
    <div className="diff-view">
      <div className="diff-section before">
        <div className="diff-header">
          <Icon icon="mdi:minus-circle" width="14" />
          <span>Current Baseline</span>
        </div>
        <div className="diff-content">
          {before}
        </div>
      </div>

      <div className="diff-arrow">
        <Icon icon="mdi:arrow-down" width="24" />
      </div>

      <div className="diff-section after">
        <div className="diff-header">
          <Icon icon="mdi:plus-circle" width="14" />
          <span>New Baseline (Evolved)</span>
        </div>
        <div className="diff-content evolved">
          {after}
        </div>
      </div>
    </div>
  );
}

/**
 * EvolveModal - Modal for promoting a winning prompt to baseline
 *
 * Props:
 * - isOpen: Modal visibility
 * - onClose: Close handler
 * - generation: Generation object with winner data
 * - currentBaseline: Current baseline prompt
 * - cascadeId: Cascade ID
 * - cellName: Cell name
 * - onEvolve: Callback when evolution confirmed
 */
const EvolveModal = ({ isOpen, onClose, generation, currentBaseline, cascadeId, cellName, onEvolve }) => {
  const [evolving, setEvolving] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen || !generation) return null;

  const winner = generation.candidates.find(c => c.is_winner) || generation.candidates[0];
  const newPrompt = winner?.prompt || '';

  const handleEvolve = async () => {
    setEvolving(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:5050/api/sextant/evolve-species', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cascade_id: cascadeId,
          cell_name: cellName,
          new_instructions: newPrompt,
          promoted_from: {
            session_id: generation.session_id,
            generation: generation.generation,
            candidate_index: winner.candidate_index,
            old_species_hash: generation.parent_winners?.[0]?.session_id || null, // Track lineage
          }
        })
      });

      const result = await response.json();

      if (result.error) {
        throw new Error(result.error);
      }

      console.log('[EvolveModal] Species evolved:', result);

      // Call success callback
      if (onEvolve) {
        onEvolve(result);
      }

      onClose();
    } catch (err) {
      console.error('[EvolveModal] Failed to evolve:', err);
      setError(err.message);
    } finally {
      setEvolving(false);
    }
  };

  return (
    <div className="evolve-modal-overlay" onClick={onClose}>
      <div className="evolve-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="evolve-modal-header">
          <Icon icon="mdi:dna" width="24" className="modal-icon" />
          <div className="modal-title-section">
            <h2>⚡ Evolve Species</h2>
            <p className="modal-subtitle">
              Create new baseline from Gen {generation.generation} winner
            </p>
          </div>
          <button className="close-modal-btn" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Diff Preview */}
        <div className="evolve-modal-body">
          <DiffView before={currentBaseline} after={newPrompt} />

          {/* Metadata Info */}
          <div className="evolve-metadata">
            <div className="metadata-item">
              <Icon icon="mdi:tag" width="14" />
              <span>Cascade: <code>{cascadeId}</code></span>
            </div>
            <div className="metadata-item">
              <Icon icon="mdi:hexagon-outline" width="14" />
              <span>Cell: <code>{cellName}</code></span>
            </div>
            <div className="metadata-item">
              <Icon icon="mdi:counter" width="14" />
              <span>Generation: <strong>{generation.generation}</strong></span>
            </div>
            {winner?.model && (
              <div className="metadata-item">
                <Icon icon="mdi:robot" width="14" />
                <span>Model: <code>{winner.model.split('/').pop()}</code></span>
              </div>
            )}
          </div>

          {/* Warning */}
          <div className="evolve-warning">
            <Icon icon="mdi:alert" width="16" />
            <div className="warning-text">
              <strong>This will update your cascade YAML file</strong> and create a new species.
              Future runs will use this evolved prompt as the baseline.
            </div>
          </div>

          {error && (
            <div className="evolve-error">
              <Icon icon="mdi:alert-circle" width="16" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="evolve-modal-footer">
          <button className="cancel-btn" onClick={onClose} disabled={evolving}>
            Cancel
          </button>
          <button className="evolve-btn" onClick={handleEvolve} disabled={evolving}>
            {evolving ? (
              <>
                <Icon icon="mdi:loading" width="16" className="spin" />
                <span>Evolving...</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:dna" width="16" />
                <span>⚡ Evolve Species</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default EvolveModal;
