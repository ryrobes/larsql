import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import VideoSpinner from './VideoSpinner';
import './HotOrNotView.css';

// Helper to render phase images from the filesystem (via API)
const renderPhaseImages = (images) => {
  if (!images || images.length === 0) return null;

  return (
    <div className="phase-images">
      {images.map((img, idx) => (
        <img
          key={img.filename || idx}
          src={`http://localhost:5001${img.url}`}
          alt={img.filename || `Image ${idx + 1}`}
          className="phase-image"
        />
      ))}
    </div>
  );
};

function HotOrNotView({ onBack }) {
  const [queue, setQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [soundingGroup, setSoundingGroup] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [rating, setRating] = useState(null);
  const [showComparison, setShowComparison] = useState(false);
  const [selectedSounding, setSelectedSounding] = useState(null);
  const [showAllSoundings, setShowAllSoundings] = useState(true); // Show all soundings by default for thorough review

  // Swipe animation state
  const [swipeDirection, setSwipeDirection] = useState(null); // 'left', 'right', 'up', or null
  const [isEntering, setIsEntering] = useState(false);

  // Button bump animation state (triggered by keyboard)
  const [bumpingButton, setBumpingButton] = useState(null); // 'good', 'bad', or null

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch('http://localhost:5001/api/hotornot/stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Error fetching stats:', err);
    }
  }, []);

  // Fetch queue
  const fetchQueue = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/hotornot/queue?limit=50&show_all=${showAllSoundings}`);
      const data = await response.json();
      setQueue(data);
      setCurrentIndex(0);
      // Trigger enter animation for first card
      setIsEntering(true);
      setTimeout(() => setIsEntering(false), 400);
    } catch (err) {
      console.error('Error fetching queue:', err);
    } finally {
      setLoading(false);
    }
  }, [showAllSoundings]);

  // Fetch sounding group for current item
  const fetchSoundingGroup = useCallback(async (sessionId, phaseName) => {
    try {
      const response = await fetch(
        `http://localhost:5001/api/hotornot/sounding-group/${sessionId}/${phaseName}`
      );
      const data = await response.json();
      if (!data.error) {
        setSoundingGroup(data);
      }
    } catch (err) {
      console.error('Error fetching sounding group:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchStats();
    fetchQueue();
  }, [fetchStats, fetchQueue]);

  // Load sounding group when current item changes
  useEffect(() => {
    if (queue.length > 0 && currentIndex < queue.length) {
      const current = queue[currentIndex];
      fetchSoundingGroup(current.session_id, current.phase_name);
      setRating(null);
      setShowComparison(false);
      setSelectedSounding(null);
    }
  }, [currentIndex, queue, fetchSoundingGroup]);

  // Trigger bump animation for a button
  const triggerBump = (buttonType) => {
    setBumpingButton(buttonType);
    setTimeout(() => setBumpingButton(null), 250);
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore if typing in an input or during animation
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || swipeDirection) {
        return;
      }

      switch (e.key.toLowerCase()) {
        case 'd':
        case 'arrowright':
          triggerBump('good');
          handleRate(true);  // Good (right swipe)
          break;
        case 'a':
        case 'arrowleft':
          triggerBump('bad');
          handleRate(false); // Bad (left swipe)
          break;
        case 's':
        case 'arrowdown':
          handleSkip();      // Skip (up swipe)
          break;
        case 'w':
        case 'arrowup':
          handlePrev();      // Previous
          break;
        case 'c':
          setShowComparison(!showComparison);
          break;
        case 'f':
          handleFlag();
          break;
        case '1':
        case '2':
        case '3':
        case '4':
        case '5':
          if (showComparison && soundingGroup) {
            const idx = parseInt(e.key) - 1;
            if (idx < soundingGroup.soundings.length) {
              handlePrefer(idx);
            }
          }
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showComparison, soundingGroup, currentIndex, queue, swipeDirection]);

  const handleRate = async (isGood) => {
    if (queue.length === 0 || currentIndex >= queue.length || swipeDirection) return;

    const current = queue[currentIndex];
    setRating(isGood);

    // Trigger swipe animation
    setSwipeDirection(isGood ? 'right' : 'left');

    try {
      await fetch('http://localhost:5001/api/hotornot/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: current.session_id,
          phase_name: current.phase_name,
          is_good: isGood,
          cascade_id: current.cascade_id,
          cascade_file: current.cascade_file,
          output_text: current.content_preview,
          sounding_index: current.sounding_index
        })
      });

      // Wait for swipe animation then move to next
      setTimeout(() => {
        setSwipeDirection(null);
        setRating(null);
        moveNext();
        fetchStats();
        // Trigger enter animation for next card
        setIsEntering(true);
        setTimeout(() => setIsEntering(false), 400);
      }, 450);

    } catch (err) {
      console.error('Error submitting rating:', err);
      setSwipeDirection(null);
      setRating(null);
    }
  };

  const handlePrefer = async (preferredIndex) => {
    if (!soundingGroup || swipeDirection) return;

    const current = queue[currentIndex];
    setSelectedSounding(preferredIndex);
    setSwipeDirection('right');

    try {
      await fetch('http://localhost:5001/api/hotornot/prefer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: current.session_id,
          phase_name: current.phase_name,
          preferred_index: preferredIndex,
          system_winner_index: soundingGroup.system_winner_index,
          sounding_outputs: soundingGroup.soundings,
          cascade_id: current.cascade_id,
          cascade_file: current.cascade_file
        })
      });

      setTimeout(() => {
        setSwipeDirection(null);
        moveNext();
        fetchStats();
        setIsEntering(true);
        setTimeout(() => setIsEntering(false), 400);
      }, 450);

    } catch (err) {
      console.error('Error submitting preference:', err);
      setSwipeDirection(null);
    }
  };

  const handleFlag = async () => {
    if (queue.length === 0 || currentIndex >= queue.length || swipeDirection) return;

    const current = queue[currentIndex];
    const reason = window.prompt('Flag reason (or cancel to skip):');
    if (!reason) return;

    try {
      await fetch('http://localhost:5001/api/hotornot/flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: current.session_id,
          phase_name: current.phase_name,
          flag_reason: reason,
          cascade_id: current.cascade_id,
          output_text: current.content_preview
        })
      });

      setSwipeDirection('left');
      setTimeout(() => {
        setSwipeDirection(null);
        moveNext();
        fetchStats();
        setIsEntering(true);
        setTimeout(() => setIsEntering(false), 400);
      }, 450);

    } catch (err) {
      console.error('Error flagging:', err);
    }
  };

  const handleSkip = () => {
    if (swipeDirection) return;

    setSwipeDirection('up');
    setTimeout(() => {
      setSwipeDirection(null);
      moveNext();
      setIsEntering(true);
      setTimeout(() => setIsEntering(false), 400);
    }, 350);
  };

  const handlePrev = () => {
    if (currentIndex > 0 && !swipeDirection) {
      setCurrentIndex(currentIndex - 1);
      setIsEntering(true);
      setTimeout(() => setIsEntering(false), 400);
    }
  };

  const moveNext = () => {
    if (currentIndex < queue.length - 1) {
      setCurrentIndex(currentIndex + 1);
    } else {
      // Refresh queue when exhausted
      fetchQueue();
    }
  };

  const currentItem = queue[currentIndex];

  // Get swipe class based on direction
  const getSwipeClass = () => {
    if (swipeDirection === 'left') return 'swiping-left';
    if (swipeDirection === 'right') return 'swiping-right';
    if (swipeDirection === 'up') return 'swiping-up';
    if (isEntering) return 'entering';
    return '';
  };

  if (loading) {
    return (
      <div className="hotornot-view">
        <div className="loading-state">
          <VideoSpinner message="Loading evaluations..." size={400} opacity={0.6} />
        </div>
      </div>
    );
  }

  return (
    <div className="hotornot-view">
      {/* Spicy background */}
      <div
        className="spicy-background"
        style={{ backgroundImage: 'url(/windlass-spicy.png)' }}
      />

      {/* Header */}
      <div className="hotornot-header">
        <div className="header-left">
          <img
            src="/windlass-transparent-square.png"
            alt="Windlass"
            className="brand-logo"
            onClick={onBack}
            title="Back to cascades"
          />

          <div className="hotornot-title">
            <Icon icon="mdi:fire" width={28} className="fire-icon" />
            {/* <h1>Hot or Not</h1> */}
          </div>
        </div>

        {stats && (
          <div className="stats-bar">
            <span className="stat good">
              <Icon icon="mdi:heart" width={16} />
              {stats.binary_good}
            </span>
            <span className="stat bad">
              <Icon icon="mdi:close" width={16} />
              {stats.binary_bad}
            </span>
            <span className="stat agreement">
              <Icon icon="mdi:handshake" width={16} />
              {stats.agreement_rate}%
            </span>
            <span className="stat total">
              <Icon icon="mdi:counter" width={16} />
              {stats.total_evaluations}
            </span>
          </div>
        )}
      </div>

      {/* Context bar - shows current item info */}
      {currentItem && (
        <div className="context-bar">
          <span className="cascade-id">{currentItem.cascade_id}</span>
          <span className="phase-name">{currentItem.phase_name}</span>
          <div className="queue-indicator">
            <span className="position">{currentIndex + 1} / {queue.length}</span>
          </div>
          <span className="session-id">{currentItem.session_id}</span>
        </div>
      )}

      {/* Main content area */}
      <div className="hotornot-main">
        {/* Card stack */}
        {currentItem ? (
          <div className="card-stack">
            <div className={`swipe-card ${getSwipeClass()}`}>

              {/* Cards container */}
              {!showComparison ? (
                <div className="cards-container">
                  {(() => {
                    // Get the sounding for THIS queue item (by sounding_index), not the winner
                    const queueSoundingIndex = currentItem.sounding_index;
                    const currentSounding = soundingGroup?.soundings?.find(s => s.index === queueSoundingIndex)
                      || soundingGroup?.soundings?.find(s => s.is_winner)
                      || soundingGroup?.soundings?.[0];
                    const instructions = currentSounding?.instructions;
                    const content = currentSounding?.content || currentItem.content_preview || 'No content';

                    return (
                      <>
                        {/* Prompt card */}
                        {instructions && (
                          <div className="evaluation-card prompt-card">
                            <div className="card-header">
                              <div className="card-label">
                                <Icon icon="mdi:text-box-outline" width={16} />
                                Prompt
                              </div>
                              {currentSounding?.mutation_applied && (
                                <span className="info-badge mutation-badge">
                                  <Icon icon="mdi:dna" width={12} />
                                  Mutated
                                </span>
                              )}
                            </div>
                            <div className="card-content">
                              <div className="markdown-content">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                  {instructions}
                                </ReactMarkdown>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Output card */}
                        <div className={`evaluation-card output-card ${rating === true ? 'rated-good' : rating === false ? 'rated-bad' : ''}`}>
                          <div className="card-header">
                            <div className="card-label">
                              <Icon icon="mdi:robot-outline" width={16} />
                              Response
                            </div>
                            {soundingGroup && (
                              <span className="info-badge sounding-badge">
                                <Icon icon="mdi:trident" width={12} />
                                {/* In blind mode (showAllSoundings), don't reveal winner status to avoid bias */}
                                {showAllSoundings
                                  ? `Sounding ${(currentSounding?.index ?? 0) + 1}/${soundingGroup.soundings.length}`
                                  : currentSounding?.is_winner
                                    ? `Winner ${currentSounding.index + 1}/${soundingGroup.soundings.length}`
                                    : `Sounding ${(currentSounding?.index ?? 0) + 1}/${soundingGroup.soundings.length}`
                                }
                              </span>
                            )}
                          </div>
                          <div className="card-content">
                            {/* Render images for this specific sounding */}
                            {renderPhaseImages(currentSounding?.images)}

                            <div className="markdown-content">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {typeof content === 'string' ? content : JSON.stringify(content, null, 2)}
                              </ReactMarkdown>
                            </div>
                          </div>
                        </div>
                      </>
                    );
                  })()}
                </div>
              ) : (
                /* Comparison mode */
                <div className="comparison-grid">
                  {soundingGroup?.soundings?.map((sounding, idx) => (
                    <div
                      key={idx}
                      className={`comparison-card ${sounding.is_winner ? 'system-winner' : ''} ${selectedSounding === idx ? 'selected' : ''}`}
                      onClick={() => handlePrefer(idx)}
                    >
                      <div className="comparison-header">
                        <span className="sounding-number">{idx + 1}</span>
                        {sounding.is_winner && (
                          <span className="winner-badge">
                            <Icon icon="mdi:trophy" width={12} />
                            System Pick
                          </span>
                        )}
                        {sounding.mutation_applied && (
                          <span className="info-badge mutation-badge" title={sounding.mutation_applied}>
                            <Icon icon="mdi:dna" width={12} />
                          </span>
                        )}
                      </div>
                      <div className="comparison-content">
                        {/* Render images for this specific sounding */}
                        {renderPhaseImages(sounding.images)}

                        <div className="markdown-content">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {typeof sounding.content === 'string'
                              ? sounding.content
                              : JSON.stringify(sounding.content, null, 2)}
                          </ReactMarkdown>
                        </div>
                      </div>
                      <div className="comparison-footer">
                        {sounding.cost && (
                          <span className="cost">${sounding.cost.toFixed(5)}</span>
                        )}
                        {sounding.tokens && (
                          <span className="tokens">{sounding.tokens} tok</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <Icon icon="mdi:check-decagram" width={64} className="empty-icon" />
            <h2>All caught up!</h2>
            <p>No more responses to evaluate right now.</p>
          </div>
        )}
      </div>

      {/* Controls area */}
      {currentItem && (
        <div className="controls-area">
          {!showComparison ? (
            <div className="main-controls">
              {/* Rewind/Previous button */}
              <button
                className="action-btn small"
                onClick={handlePrev}
                disabled={currentIndex === 0 || swipeDirection}
              >
                <Icon icon="mdi:undo" width={22} />
                <span className="key-hint">W</span>
              </button>

              {/* Bad/Nope button */}
              <button
                className={`action-btn large bad ${bumpingButton === 'bad' ? 'bumping' : ''}`}
                onClick={() => handleRate(false)}
                disabled={swipeDirection}
              >
                <Icon icon="mdi:close-thick" width={32} />
                <span className="key-hint">A</span>
              </button>

              {/* Skip button */}
              <button
                className="action-btn skip"
                onClick={handleSkip}
                disabled={swipeDirection}
              >
                <Icon icon="mdi:debug-step-over" width={24} />
                <span className="key-hint">S</span>
              </button>

              {/* Good/Like button */}
              <button
                className={`action-btn large good ${bumpingButton === 'good' ? 'bumping' : ''}`}
                onClick={() => handleRate(true)}
                disabled={swipeDirection}
              >
                <Icon icon="mdi:heart" width={32} />
                <span className="key-hint">D</span>
              </button>

              {/* Flag button */}
              <button
                className="action-btn small"
                onClick={handleFlag}
                disabled={swipeDirection}
              >
                <Icon icon="mdi:flag" width={22} />
                <span className="key-hint">F</span>
              </button>
            </div>
          ) : (
            <div className="comparison-hint">
              Click a card or press <kbd>1</kbd>-<kbd>{soundingGroup?.soundings?.length || 3}</kbd> to pick your preferred response
            </div>
          )}

          {/* Secondary controls */}
          <div className="secondary-controls">
            {soundingGroup && soundingGroup.soundings.length > 1 && (
              <button
                className={`secondary-btn ${showComparison ? 'active' : ''}`}
                onClick={() => setShowComparison(!showComparison)}
                title="Compare all soundings"
              >
                <Icon icon="mdi:compare" width={20} />
                <span className="key">C</span>
              </button>
            )}
            <button
              className={`secondary-btn ${showAllSoundings ? 'active' : ''}`}
              onClick={() => setShowAllSoundings(!showAllSoundings)}
              title={showAllSoundings ? "Showing all soundings individually (blind mode)" : "Grouped by session/phase"}
            >
              <Icon icon={showAllSoundings ? "mdi:format-list-bulleted" : "mdi:group"} width={20} />
            </button>
          </div>
        </div>
      )}

      {/* Keyboard shortcuts footer */}
      <div className="shortcuts-footer">
        <span><kbd>A</kbd> Nope</span>
        <span><kbd>D</kbd> Like</span>
        <span><kbd>S</kbd> Skip</span>
        <span><kbd>W</kbd> Previous</span>
        <span><kbd>C</kbd> Compare</span>
        <span><kbd>F</kbd> Flag</span>
      </div>
    </div>
  );
}

export default HotOrNotView;
