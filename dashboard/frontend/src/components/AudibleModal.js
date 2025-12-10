import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import './AudibleModal.css';

const API_BASE_URL = 'http://localhost:5001/api';

/**
 * AudibleModal - Modal for submitting audible feedback mid-phase
 *
 * Features:
 * - Shows current output from the agent
 * - Text feedback input
 * - Continue vs Retry mode selection
 * - Display of recent images (if any)
 * - Budget tracking
 */
function AudibleModal({ isOpen, checkpoint, onClose, onSubmit }) {
  const [feedback, setFeedback] = useState('');
  const [mode, setMode] = useState('continue');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Extract UI spec data
  const uiSpec = checkpoint?.ui_spec || {};
  const currentOutput = uiSpec.current_output || '';
  const turnNumber = uiSpec.turn_number ?? 0;
  const maxTurns = uiSpec.max_turns ?? 1;
  const turnsRemaining = uiSpec.turns_remaining ?? 0;
  const audiblesRemaining = uiSpec.audibles_remaining ?? 0;
  const allowRetry = uiSpec.allow_retry ?? true;
  const recentImages = uiSpec.recent_images || [];

  useEffect(() => {
    if (isOpen) {
      setFeedback('');
      setMode('continue');
      setError(null);
    }
  }, [isOpen]);

  const handleSubmit = async () => {
    if (!feedback.trim()) {
      setError('Please provide some feedback');
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const response = await axios.post(
        `${API_BASE_URL}/checkpoints/${checkpoint.id}/respond`,
        {
          response: {
            feedback: feedback.trim(),
            mode: mode
          }
        }
      );

      if (onSubmit) {
        onSubmit(response.data);
      }
      onClose();
    } catch (err) {
      console.error('Error submitting audible feedback:', err);
      setError(err.response?.data?.error || 'Failed to submit feedback');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    try {
      await axios.post(`${API_BASE_URL}/checkpoints/${checkpoint.id}/cancel`, {
        reason: 'User cancelled audible'
      });
    } catch (err) {
      console.error('Error cancelling audible:', err);
    }
    onClose();
  };

  if (!isOpen || !checkpoint) return null;

  return (
    <div className="audible-overlay" onClick={handleCancel}>
      <div className="audible-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="audible-header">
          <div className="audible-title">
            <span className="audible-icon"><Icon icon="mdi:bullhorn" width="20" /></span>
            <h2>Call Audible</h2>
          </div>
          <div className="audible-meta">
            <span className="turn-badge">
              Turn {turnNumber + 1}/{maxTurns}
            </span>
            <span className="audibles-badge">
              {audiblesRemaining} audibles left
            </span>
          </div>
          <button className="audible-close" onClick={handleCancel}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Error Display */}
        {error && (
          <div className="audible-error">
            <Icon icon="mdi:alert-circle" width="16" />
            {error}
          </div>
        )}

        {/* Main Content */}
        <div className="audible-body">
          {/* Current Output Section */}
          <div className="audible-section">
            <h3>Current Output</h3>
            <div className="current-output-box">
              {currentOutput ? (
                <ReactMarkdown>{currentOutput.slice(0, 2000)}</ReactMarkdown>
              ) : (
                <p className="no-output">(No output yet)</p>
              )}
              {currentOutput && currentOutput.length > 2000 && (
                <p className="output-truncated">... (output truncated)</p>
              )}
            </div>
          </div>

          {/* Recent Images */}
          {recentImages.length > 0 && (
            <div className="audible-section">
              <h3>Recent Images</h3>
              <div className="recent-images-grid">
                {recentImages.slice(-3).map((imgPath, idx) => (
                  <div key={idx} className="recent-image-item">
                    <img
                      src={imgPath.startsWith('/api/') ? `http://localhost:5001${imgPath}` : imgPath}
                      alt={`Recent ${idx + 1}`}
                      onClick={() => window.open(imgPath.startsWith('/api/') ? `http://localhost:5001${imgPath}` : imgPath, '_blank')}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Feedback Input */}
          <div className="audible-section">
            <h3>Your Feedback</h3>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="What should change? Describe what's wrong or needs adjustment..."
              rows={4}
              autoFocus
            />
          </div>

          {/* Mode Selection */}
          <div className="audible-section">
            <h3>Action</h3>
            <div className="mode-options">
              <label className={`mode-option ${mode === 'continue' ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="mode"
                  value="continue"
                  checked={mode === 'continue'}
                  onChange={() => setMode('continue')}
                />
                <span className="mode-icon"><Icon icon="mdi:arrow-right" width="16" /></span>
                <span className="mode-label">Continue</span>
                <span className="mode-description">
                  Keep current output, apply feedback in next turn
                </span>
              </label>

              {allowRetry && turnsRemaining > 0 && (
                <label className={`mode-option ${mode === 'retry' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="mode"
                    value="retry"
                    checked={mode === 'retry'}
                    onChange={() => setMode('retry')}
                  />
                  <span className="mode-icon"><Icon icon="mdi:refresh" width="16" /></span>
                  <span className="mode-label">Retry</span>
                  <span className="mode-description">
                    Discard current output, redo this turn with feedback
                  </span>
                </label>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="audible-footer">
          <button className="button-secondary" onClick={handleCancel} disabled={submitting}>
            Cancel
          </button>
          <button className="button-primary" onClick={handleSubmit} disabled={submitting || !feedback.trim()}>
            {submitting ? 'Submitting...' : 'Submit Feedback'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default AudibleModal;
