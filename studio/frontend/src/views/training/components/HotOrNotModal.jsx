import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import SwipeCard from './SwipeCard';
import './HotOrNotModal.css';

/**
 * HotOrNotModal - Tinder-style card swiping interface for training curation
 *
 * Keyboard Controls:
 * - D: HOT (trainable=true)
 * - W: NOT (trainable=false)
 * - S: SKIP (no change)
 * - Escape: Exit and submit
 * - Cmd/Ctrl+Z: Undo last action
 */
const HotOrNotModal = ({ isOpen, examples, onClose, onComplete }) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [decisions, setDecisions] = useState([]);
  const [exitDirection, setExitDirection] = useState(null);
  const [isAnimating, setIsAnimating] = useState(false);
  const [undoStack, setUndoStack] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSummary, setShowSummary] = useState(false);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setCurrentIndex(0);
      setDecisions([]);
      setExitDirection(null);
      setIsAnimating(false);
      setUndoStack([]);
      setIsSubmitting(false);
      setShowSummary(false);
    }
  }, [isOpen]);

  // Prevent body scroll when modal open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  // Submit decisions to API
  const submitDecisions = useCallback(async (decisionsToSubmit) => {
    if (decisionsToSubmit.length === 0) return;

    setIsSubmitting(true);

    try {
      const hotIds = decisionsToSubmit.filter((d) => d.decision === 'hot').map((d) => d.trace_id);
      const notIds = decisionsToSubmit.filter((d) => d.decision === 'not').map((d) => d.trace_id);

      // Batch mark HOT (trainable + verified)
      if (hotIds.length > 0) {
        await fetch('http://localhost:5050/api/training/mark-trainable', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trace_ids: hotIds,
            trainable: true,
            verified: true,
            confidence: 1.0,
            notes: 'Marked via Hot or Not',
          }),
        });
      }

      // Batch mark NOT
      if (notIds.length > 0) {
        await fetch('http://localhost:5050/api/training/mark-trainable', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trace_ids: notIds,
            trainable: false,
          }),
        });
      }
    } catch (err) {
      console.error('Failed to submit decisions:', err);
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  // Handle closing modal
  const handleClose = useCallback(async () => {
    // Submit any pending decisions
    if (decisions.length > 0) {
      await submitDecisions(decisions);
    }
    onComplete?.(decisions);
    onClose();
  }, [decisions, submitDecisions, onComplete, onClose]);

  // Trigger swipe action
  const triggerAction = useCallback(
    (action) => {
      if (isAnimating || currentIndex >= examples.length) return;

      setIsAnimating(true);

      const example = examples[currentIndex];
      const decision = {
        trace_id: example.trace_id,
        decision: action,
        timestamp: Date.now(),
      };

      // Add to decisions (skip actions are tracked but not submitted)
      setDecisions((prev) => [...prev, decision]);

      // Add to undo stack
      setUndoStack((prev) => [...prev, { decision, index: currentIndex }]);

      // Set exit direction for animation
      const direction = action === 'hot' ? 'right' : action === 'not' ? 'left' : 'down';
      setExitDirection(direction);

      // Advance after animation
      setTimeout(() => {
        setExitDirection(null);
        setCurrentIndex((prev) => prev + 1);
        setIsAnimating(false);

        // Check if complete
        if (currentIndex >= examples.length - 1) {
          setShowSummary(true);
        }
      }, 300);
    },
    [isAnimating, currentIndex, examples]
  );

  // Handle undo
  const handleUndo = useCallback(() => {
    if (undoStack.length === 0 || isAnimating) return;

    setIsAnimating(true);

    const lastAction = undoStack[undoStack.length - 1];

    // Remove from undo stack
    setUndoStack((prev) => prev.slice(0, -1));

    // Remove from decisions
    setDecisions((prev) => prev.slice(0, -1));

    // Go back to previous card
    setCurrentIndex(lastAction.index);
    setShowSummary(false);

    setTimeout(() => {
      setIsAnimating(false);
    }, 200);
  }, [undoStack, isAnimating]);

  // Keyboard controls
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      // Ignore when typing in input fields
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (isAnimating && e.key.toLowerCase() !== 'escape') return;

      switch (e.key.toLowerCase()) {
        case 'w':
          e.preventDefault();
          if (!showSummary) triggerAction('not');
          break;
        case 's':
          e.preventDefault();
          if (!showSummary) triggerAction('skip');
          break;
        case 'd':
          e.preventDefault();
          if (!showSummary) triggerAction('hot');
          break;
        case 'escape':
          e.preventDefault();
          handleClose();
          break;
        case 'z':
          if (e.metaKey || e.ctrlKey) {
            e.preventDefault();
            handleUndo();
          }
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isAnimating, showSummary, triggerAction, handleUndo, handleClose]);

  // Calculate stats
  const stats = {
    hot: decisions.filter((d) => d.decision === 'hot').length,
    not: decisions.filter((d) => d.decision === 'not').length,
    skip: decisions.filter((d) => d.decision === 'skip').length,
    total: decisions.length,
  };

  // Progress percentage
  const progress = examples.length > 0 ? (currentIndex / examples.length) * 100 : 0;

  // Get visible cards (current + 2 behind)
  const visibleCards = examples.slice(currentIndex, currentIndex + 3);

  if (!isOpen) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="hon-modal-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        onClick={handleClose}
      >
        <motion.div
          className="hon-modal"
          onClick={(e) => e.stopPropagation()}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.2 }}
        >
          {/* Header */}
          <div className="hon-header">
            <div className="hon-header-left">
              <Icon icon="mdi:fire" width={20} className="hon-header-icon" />
              <span className="hon-title">Hot or Not</span>
            </div>

            {/* Progress Bar */}
            <div className="hon-progress-container">
              <div className="hon-progress-bar">
                <motion.div
                  className="hon-progress-fill"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <span className="hon-progress-text">
                {currentIndex} / {examples.length}
              </span>
            </div>

            <div className="hon-header-right">
              {undoStack.length > 0 && (
                <button
                  className="hon-undo-btn"
                  onClick={handleUndo}
                  disabled={isAnimating}
                  title="Undo (Cmd+Z)"
                >
                  <Icon icon="mdi:undo" width={16} />
                </button>
              )}
              <button className="hon-close-btn" onClick={handleClose} title="Close (Escape)">
                <Icon icon="mdi:close" width={20} />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="hon-content">
            {examples.length === 0 ? (
              <div className="hon-empty">
                <Icon icon="mdi:filter-off" width={48} />
                <h3>No examples match filters</h3>
                <p>Adjust your filters to see training examples</p>
              </div>
            ) : showSummary ? (
              <motion.div
                className="hon-summary"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Icon icon="mdi:check-circle" width={64} className="hon-summary-icon" />
                <h2>Review Complete</h2>
                <div className="hon-summary-stats">
                  <div className="hon-stat hon-stat--hot">
                    <Icon icon="mdi:fire" width={24} />
                    <span className="hon-stat-value">{stats.hot}</span>
                    <span className="hon-stat-label">Hot</span>
                  </div>
                  <div className="hon-stat hon-stat--not">
                    <Icon icon="mdi:close-thick" width={24} />
                    <span className="hon-stat-value">{stats.not}</span>
                    <span className="hon-stat-label">Not</span>
                  </div>
                  <div className="hon-stat hon-stat--skip">
                    <Icon icon="mdi:debug-step-over" width={24} />
                    <span className="hon-stat-value">{stats.skip}</span>
                    <span className="hon-stat-label">Skipped</span>
                  </div>
                </div>
                <button
                  className="hon-done-btn"
                  onClick={handleClose}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <Icon icon="mdi:loading" width={16} className="hon-spinner" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Icon icon="mdi:check" width={16} />
                      Done
                    </>
                  )}
                </button>
              </motion.div>
            ) : (
              <div className="hon-card-stack">
                <AnimatePresence mode="popLayout">
                  {visibleCards.map((example, idx) => (
                    <SwipeCard
                      key={example.trace_id}
                      example={example}
                      isActive={idx === 0}
                      stackIndex={idx}
                      exitDirection={idx === 0 ? exitDirection : null}
                      onSwipe={triggerAction}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}
          </div>

          {/* Footer - Keyboard Hints */}
          {!showSummary && examples.length > 0 && (
            <div className="hon-footer">
              <div className="hon-hint hon-hint--not">
                <kbd>W</kbd>
                <span>NOT</span>
              </div>
              <div className="hon-hint hon-hint--skip">
                <kbd>S</kbd>
                <span>SKIP</span>
              </div>
              <div className="hon-hint hon-hint--hot">
                <kbd>D</kbd>
                <span>HOT</span>
              </div>
            </div>
          )}

          {/* Stats Bar */}
          {!showSummary && decisions.length > 0 && (
            <div className="hon-stats-bar">
              <span className="hon-mini-stat hon-mini-stat--hot">
                <Icon icon="mdi:fire" width={12} /> {stats.hot}
              </span>
              <span className="hon-mini-stat hon-mini-stat--not">
                <Icon icon="mdi:close-thick" width={12} /> {stats.not}
              </span>
              <span className="hon-mini-stat hon-mini-stat--skip">
                <Icon icon="mdi:debug-step-over" width={12} /> {stats.skip}
              </span>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
};

export default HotOrNotModal;
