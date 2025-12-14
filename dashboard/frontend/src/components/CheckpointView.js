import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import DynamicUI from './DynamicUI';
import SoundingComparison from './SoundingComparison';
import './CheckpointView.css';

/**
 * CheckpointView - Full page view for responding to a checkpoint
 *
 * Features:
 * - Timeout countdown
 * - DynamicUI for phase input checkpoints
 * - SoundingComparison for sounding evaluation checkpoints
 * - Reasoning capture
 * - Confidence rating
 */
function CheckpointView({ checkpointId, onComplete, onBack }) {
  const [checkpoint, setCheckpoint] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [reasoning, setReasoning] = useState('');
  const [confidence, setConfidence] = useState(null);

  // Get the return path from sessionStorage (set when navigating to checkpoint)
  const getReturnPath = useCallback(() => {
    const stored = sessionStorage.getItem('checkpointReturnPath');
    // Clear it after reading so it doesn't persist across sessions
    if (stored) {
      sessionStorage.removeItem('checkpointReturnPath');
    }
    return stored || '';
  }, []);

  // Go back handler
  const handleGoBack = useCallback(() => {
    if (onBack) {
      onBack();
    } else {
      // Try to return to where we came from, or fall back to session detail view
      const returnPath = sessionStorage.getItem('checkpointReturnPath');
      if (returnPath) {
        sessionStorage.removeItem('checkpointReturnPath');
        window.location.hash = returnPath;
      } else if (checkpoint?.cascade_id && checkpoint?.session_id) {
        // Fall back to session detail view
        window.location.hash = `#/${checkpoint.cascade_id}/${checkpoint.session_id}`;
      } else {
        // Last resort: go to cascades view
        window.location.hash = '';
      }
    }
  }, [onBack, checkpoint]);

  // Fetch checkpoint data
  useEffect(() => {
    if (!checkpointId) {
      setError('No checkpoint ID provided');
      setLoading(false);
      return;
    }

    fetch(`http://localhost:5001/api/checkpoints/${checkpointId}`)
      .then(r => {
        if (!r.ok) throw new Error('Checkpoint not found');
        return r.json();
      })
      .then(data => {
        setCheckpoint(data);
        setError(null);
      })
      .catch(err => {
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [checkpointId]);

  // Handle submission
  const handleSubmit = useCallback(async (response) => {
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          response,
          reasoning: reasoning || undefined,
          confidence: confidence || undefined
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to submit response');
      }

      const result = await res.json();

      if (onComplete) {
        onComplete(result);
      } else {
        // Navigate back to where we came from, or to session detail view
        const returnPath = sessionStorage.getItem('checkpointReturnPath');
        if (returnPath) {
          sessionStorage.removeItem('checkpointReturnPath');
          window.location.hash = returnPath;
        } else {
          // Fall back to session detail view
          window.location.hash = `#/${checkpoint?.cascade_id}/${checkpoint?.session_id}`;
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }, [checkpointId, reasoning, confidence, onComplete, checkpoint]);

  // Handle cancel
  const handleCancel = async () => {
    setSubmitting(true);
    try {
      await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'User cancelled' })
      });
      handleGoBack();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="checkpoint-view loading">
        <div className="loading-spinner" />
        <p>Loading checkpoint...</p>
      </div>
    );
  }

  if (error && !checkpoint) {
    return (
      <div className="checkpoint-view error">
        <div className="error-icon">!</div>
        <h2>Error</h2>
        <p>{error}</p>
        <button onClick={handleGoBack} className="back-btn">
          Go Back
        </button>
      </div>
    );
  }

  if (checkpoint?.status !== 'pending') {
    return (
      <div className="checkpoint-view resolved">
        <div className="resolved-icon">
          {checkpoint?.status === 'responded' ? '✓' : '✕'}
        </div>
        <h2>Checkpoint {checkpoint?.status === 'responded' ? 'Resolved' : 'Expired'}</h2>
        <p>
          This checkpoint was {checkpoint?.status} at{' '}
          {new Date(checkpoint?.responded_at).toLocaleString()}
        </p>
        <button onClick={handleGoBack} className="back-btn">
          Go Back
        </button>
      </div>
    );
  }

  const isSoundingEval = checkpoint?.checkpoint_type === 'sounding_eval';
  const isAudible = checkpoint?.checkpoint_type === 'audible';
  const uiSpec = checkpoint?.ui_spec || {};
  const requireReasoning = uiSpec.capture_reasoning || uiSpec.options?.require_reasoning;
  const requireConfidence = uiSpec.capture_confidence;

  return (
    <div className="checkpoint-view">
      {/* Header */}
      <div className="checkpoint-view-header">
        <button onClick={handleGoBack} className="back-btn">
          ← Back
        </button>
        <div className="checkpoint-breadcrumb">
          <span className="cascade-name">{checkpoint?.cascade_id}</span>
          <span className="separator">→</span>
          <span className="phase-name">{checkpoint?.phase_name}</span>
        </div>
        <div className="checkpoint-type-badge">
          {isSoundingEval ? (
            <><Icon icon="mdi:scale-balance" width="16" /> Compare Outputs</>
          ) : isAudible ? (
            <><Icon icon="mdi:bullhorn" width="16" /> Audible</>
          ) : (
            <><Icon icon="mdi:hand-back-left" width="16" /> Input Required</>
          )}
        </div>
      </div>

      {/* Timeout Warning */}
      {checkpoint?.timeout_at && (
        <TimeoutWarning
          timeout={checkpoint.timeout_at}
          onTimeout={() => setError('Checkpoint timed out')}
        />
      )}

      {/* Error Message */}
      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}

      {/* Main Content */}
      <div className="checkpoint-view-content">
        {isSoundingEval ? (
          <SoundingComparison
            spec={uiSpec}
            outputs={checkpoint?.sounding_outputs || []}
            metadata={checkpoint?.sounding_metadata || []}
            onSubmit={handleSubmit}
            isLoading={submitting}
          />
        ) : (
          <DynamicUI
            spec={uiSpec}
            phaseOutput={checkpoint?.phase_output}
            onSubmit={handleSubmit}
            isLoading={submitting}
            checkpointId={checkpointId}
            sessionId={checkpoint?.session_id}
          />
        )}

        {/* Reasoning & Confidence Section */}
        {(requireReasoning || requireConfidence) && (
          <div className="checkpoint-extras">
            {requireReasoning && (
              <div className="reasoning-section">
                <label className="reasoning-label">
                  Explain your choice
                  {uiSpec.require_reasoning && <span className="required">*</span>}
                </label>
                <textarea
                  value={reasoning}
                  onChange={(e) => setReasoning(e.target.value)}
                  placeholder="Why did you make this choice?"
                  rows={3}
                  className="reasoning-input"
                />
              </div>
            )}

            {requireConfidence && (
              <div className="confidence-section">
                <label className="confidence-label">
                  How confident are you?
                </label>
                <div className="confidence-options">
                  {[
                    { value: 0.25, label: 'Not sure' },
                    { value: 0.5, label: 'Somewhat' },
                    { value: 0.75, label: 'Confident' },
                    { value: 1.0, label: 'Very confident' }
                  ].map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setConfidence(opt.value)}
                      className={`confidence-btn ${confidence === opt.value ? 'selected' : ''}`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="checkpoint-view-footer">
        <button
          onClick={handleCancel}
          disabled={submitting}
          className="cancel-btn"
        >
          Cancel
        </button>
        <span className="checkpoint-id">ID: {checkpoint?.id}</span>
      </div>
    </div>
  );
}

/**
 * Timeout countdown component
 */
function TimeoutWarning({ timeout, onTimeout }) {
  const [remaining, setRemaining] = useState(null);

  useEffect(() => {
    const update = () => {
      const diff = new Date(timeout) - new Date();
      const seconds = Math.max(0, Math.floor(diff / 1000));
      setRemaining(seconds);

      if (seconds === 0 && onTimeout) {
        onTimeout();
      }
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [timeout, onTimeout]);

  if (remaining === null || remaining > 3600) return null;

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const isUrgent = remaining < 60;

  return (
    <div className={`timeout-warning ${isUrgent ? 'urgent' : ''}`}>
      <span className="timeout-icon">⏱</span>
      <span className="timeout-text">
        Time remaining: {minutes}:{seconds.toString().padStart(2, '0')}
      </span>
      {isUrgent && <span className="timeout-urgent">Respond now!</span>}
    </div>
  );
}

export default CheckpointView;
