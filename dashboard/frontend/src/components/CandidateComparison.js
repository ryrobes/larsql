import React, { useState } from 'react';
import RichMarkdown from './RichMarkdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { studioDarkPrismTheme } from '../styles/studioPrismTheme';
import { Icon } from '@iconify/react';
import './CandidateComparison.css';

/**
 * SoundingComparison - UI for comparing sounding attempts and selecting a winner
 *
 * Supports multiple presentation modes:
 * - side_by_side: Cards in a grid
 * - tabbed: Tab per attempt
 * - carousel: Swipe through
 * - tournament: Pairwise elimination
 *
 * And selection modes:
 * - pick_one: Select single winner
 * - rank_all: Order all from best to worst
 * - rate_each: Give score to each
 */
function SoundingComparison({ spec, outputs, metadata, onSubmit, isLoading }) {
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [rankings, setRankings] = useState([]);
  const [ratings, setRatings] = useState({});

  const presentation = spec?.presentation || 'side_by_side';
  const selectionMode = spec?.selection_mode || 'pick_one';
  const options = spec?.options || {};

  // Build attempts array with images
  const attempts = outputs.map((output, idx) => ({
    index: idx,
    output,
    metadata: metadata?.[idx] || {},
    mutation: metadata?.[idx]?.mutation_applied,
    images: metadata?.[idx]?.images || []
  }));

  const handleSubmit = () => {
    const response = {
      winner_index: selectedIndex,
      rankings: selectionMode === 'rank_all' ? rankings : undefined,
      ratings: selectionMode === 'rate_each' ? ratings : undefined
      // Note: reasoning is collected by CheckpointView wrapper
    };
    onSubmit(response);
  };

  const handleRejectAll = () => {
    onSubmit({ reject_all: true });
  };

  const canSubmit = () => {
    if (selectionMode === 'pick_one') return selectedIndex !== null;
    if (selectionMode === 'rank_all') return rankings.length === attempts.length;
    if (selectionMode === 'rate_each') return Object.keys(ratings).length === attempts.length;
    return false;
  };

  // Ranking helpers
  const addToRanking = (idx) => {
    if (!rankings.includes(idx)) {
      setRankings([...rankings, idx]);
    }
  };

  const removeFromRanking = (idx) => {
    setRankings(rankings.filter(i => i !== idx));
  };

  const getRankPosition = (idx) => {
    const pos = rankings.indexOf(idx);
    return pos >= 0 ? pos + 1 : null;
  };

  return (
    <div className="sounding-comparison">
      {/* Header */}
      <div className="comparison-header">
        <h2 className="comparison-title">Compare Outputs</h2>
        <span className="attempt-count">{attempts.length} attempts to compare</span>
      </div>

      {/* Selection Mode Hint */}
      <div className="selection-hint">
        {selectionMode === 'pick_one' && 'Click to select the best output'}
        {selectionMode === 'rank_all' && `Click outputs in order from best (1) to worst (${attempts.length})`}
        {selectionMode === 'rate_each' && 'Rate each output using the stars'}
      </div>

      {/* Comparison Grid */}
      {presentation === 'side_by_side' && (
        <SideBySideView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
          selectionMode={selectionMode}
          ratings={ratings}
          onRate={(idx, rating) => setRatings(prev => ({ ...prev, [idx]: rating }))}
          rankings={rankings}
          onAddRanking={addToRanking}
          onRemoveRanking={removeFromRanking}
          getRankPosition={getRankPosition}
        />
      )}

      {presentation === 'tabbed' && (
        <TabbedView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
          selectionMode={selectionMode}
        />
      )}

      {presentation === 'carousel' && (
        <CarouselView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
          selectionMode={selectionMode}
        />
      )}

      {/* Ranking Display */}
      {selectionMode === 'rank_all' && rankings.length > 0 && (
        <div className="ranking-display">
          <h4>Your Ranking:</h4>
          <div className="ranking-list">
            {rankings.map((idx, pos) => (
              <div key={idx} className="ranking-item">
                <span className="rank-number">{pos + 1}</span>
                <span className="rank-label">Attempt {idx + 1}</span>
                <button
                  type="button"
                  onClick={() => removeFromRanking(idx)}
                  className="rank-remove"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          {rankings.length < attempts.length && (
            <span className="ranking-hint">
              Click {attempts.length - rankings.length} more to complete ranking
            </span>
          )}
        </div>
      )}

      {/* Note: Reasoning input is handled by CheckpointView wrapper */}

      {/* Actions */}
      <div className="comparison-actions">
        {options.allow_reject_all && (
          <button
            type="button"
            onClick={handleRejectAll}
            disabled={isLoading}
            className="reject-all-btn"
          >
            Reject All & Retry
          </button>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit() || isLoading}
          className="submit-btn"
        >
          {isLoading ? 'Submitting...' : 'Confirm Selection'}
        </button>
      </div>
    </div>
  );
}

/**
 * Side-by-side grid view
 */
function SideBySideView({
  attempts,
  options,
  selectedIndex,
  onSelect,
  selectionMode,
  ratings,
  onRate,
  rankings,
  onAddRanking,
  getRankPosition
}) {
  const gridCols = attempts.length === 2 ? 2 : attempts.length === 3 ? 3 : 2;

  return (
    <div
      className="side-by-side-view"
      style={{ gridTemplateColumns: `repeat(${Math.min(gridCols, attempts.length)}, 1fr)` }}
    >
      {attempts.map((attempt, idx) => (
        <AttemptCard
          key={idx}
          attempt={attempt}
          index={idx}
          isSelected={selectedIndex === idx}
          onSelect={() => selectionMode === 'pick_one' ? onSelect(idx) : onAddRanking(idx)}
          showMetadata={options.show_metadata}
          showMutation={options.show_mutations}
          showIndex={options.show_index}
          previewRender={options.preview_render}
          maxLength={options.max_preview_length}
          selectionMode={selectionMode}
          rating={ratings[idx]}
          onRate={(r) => onRate(idx, r)}
          rankPosition={getRankPosition ? getRankPosition(idx) : null}
        />
      ))}
    </div>
  );
}

/**
 * Tabbed view
 */
function TabbedView({ attempts, options, selectedIndex, onSelect, selectionMode }) {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="tabbed-view">
      <div className="tabs">
        {attempts.map((attempt, idx) => (
          <button
            key={idx}
            onClick={() => setActiveTab(idx)}
            className={`tab ${activeTab === idx ? 'active' : ''} ${selectedIndex === idx ? 'selected' : ''}`}
          >
            {options.show_index ? `#${idx + 1}` : `Option ${String.fromCharCode(65 + idx)}`}
            {selectedIndex === idx && <span className="selected-badge">✓</span>}
          </button>
        ))}
      </div>
      <div className="tab-content">
        <AttemptCard
          attempt={attempts[activeTab]}
          index={activeTab}
          isSelected={selectedIndex === activeTab}
          onSelect={() => onSelect(activeTab)}
          showMetadata={options.show_metadata}
          showMutation={options.show_mutations}
          showIndex={false}
          previewRender={options.preview_render}
          maxLength={options.max_preview_length}
          selectionMode={selectionMode}
          fullWidth
        />
      </div>
    </div>
  );
}

/**
 * Carousel view
 */
function CarouselView({ attempts, options, selectedIndex, onSelect, selectionMode }) {
  const [currentIdx, setCurrentIdx] = useState(0);

  const goNext = () => setCurrentIdx((prev) => (prev + 1) % attempts.length);
  const goPrev = () => setCurrentIdx((prev) => (prev - 1 + attempts.length) % attempts.length);

  return (
    <div className="carousel-view">
      <button onClick={goPrev} className="carousel-nav prev">←</button>

      <div className="carousel-content">
        <div className="carousel-counter">
          {currentIdx + 1} / {attempts.length}
        </div>
        <AttemptCard
          attempt={attempts[currentIdx]}
          index={currentIdx}
          isSelected={selectedIndex === currentIdx}
          onSelect={() => onSelect(currentIdx)}
          showMetadata={options.show_metadata}
          showMutation={options.show_mutations}
          showIndex={options.show_index}
          previewRender={options.preview_render}
          maxLength={options.max_preview_length}
          selectionMode={selectionMode}
          fullWidth
        />
      </div>

      <button onClick={goNext} className="carousel-nav next">→</button>

      <div className="carousel-dots">
        {attempts.map((_, idx) => (
          <button
            key={idx}
            onClick={() => setCurrentIdx(idx)}
            className={`dot ${idx === currentIdx ? 'active' : ''} ${selectedIndex === idx ? 'selected' : ''}`}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Single attempt card
 */
function AttemptCard({
  attempt,
  index,
  isSelected,
  onSelect,
  showMetadata,
  showMutation,
  showIndex,
  previewRender,
  maxLength,
  selectionMode,
  rating,
  onRate,
  rankPosition,
  fullWidth
}) {
  const output = maxLength && attempt.output.length > maxLength
    ? attempt.output.slice(0, maxLength) + '...'
    : attempt.output;

  // Auto-detect render type - default to markdown for better formatting
  const detectRenderType = (text) => {
    if (!text) return 'markdown';
    const trimmed = text.trim();
    if (trimmed.startsWith('```') || trimmed.startsWith('def ') || trimmed.startsWith('function ')) return 'code';
    // Default to markdown - it handles plain text gracefully
    return 'markdown';
  };

  const actualRender = previewRender === 'auto' ? detectRenderType(output) : (previewRender || 'markdown');

  // Check for images in attempt
  const images = attempt.images || [];

  const renderContent = () => {
    return (
      <>
        {/* Render images if present */}
        {images.length > 0 && (
          <div className="attempt-images">
            {images.map((img, imgIdx) => (
              <img
                key={imgIdx}
                src={img.startsWith('/') ? img : `/api/images/${img}`}
                alt={`Output ${index + 1} - Image ${imgIdx + 1}`}
                className="attempt-image"
                onClick={(e) => {
                  e.stopPropagation();
                  window.open(img.startsWith('/') ? img : `/api/images/${img}`, '_blank');
                }}
              />
            ))}
          </div>
        )}

        {/* Render text content */}
        {output && (
          actualRender === 'code' ? (
            <SyntaxHighlighter
              language="javascript"
              style={studioDarkPrismTheme}
              customStyle={{ margin: 0, borderRadius: '6px', fontSize: '0.85em' }}
            >
              {output}
            </SyntaxHighlighter>
          ) : (
            <div className="attempt-markdown">
              <RichMarkdown>{output}</RichMarkdown>
            </div>
          )
        )}
      </>
    );
  };

  return (
    <div
      onClick={selectionMode === 'pick_one' ? onSelect : undefined}
      className={`attempt-card ${isSelected ? 'selected' : ''} ${fullWidth ? 'full-width' : ''} ${selectionMode === 'pick_one' ? 'clickable' : ''}`}
    >
      {/* Header */}
      <div className="attempt-header">
        {showIndex && (
          <span className="attempt-index">#{index + 1}</span>
        )}
        {rankPosition && (
          <span className="rank-badge">Rank {rankPosition}</span>
        )}
        {isSelected && selectionMode === 'pick_one' && (
          <span className="selected-label">Selected</span>
        )}
      </div>

      {/* Content */}
      <div className="attempt-content">
        {renderContent()}
      </div>

      {/* Metadata */}
      {showMetadata && attempt.metadata && (
        <div className="attempt-metadata">
          {attempt.metadata.cost !== undefined && (
            <span className="meta-item">
              <span className="meta-icon">$</span>
              {attempt.metadata.cost?.toFixed(4) || '0.0000'}
            </span>
          )}
          {attempt.metadata.tokens && (
            <span className="meta-item">
              <span className="meta-icon"><Icon icon="mdi:lightning-bolt" width="12" /></span>
              {attempt.metadata.tokens} tokens
            </span>
          )}
          {attempt.metadata.duration_ms && (
            <span className="meta-item">
              <span className="meta-icon"><Icon icon="mdi:timer-outline" width="12" /></span>
              {(attempt.metadata.duration_ms / 1000).toFixed(1)}s
            </span>
          )}
          {attempt.metadata.model && (
            <span className="meta-item model">
              {attempt.metadata.model.split('/').pop()}
            </span>
          )}
        </div>
      )}

      {/* Mutation Info */}
      {showMutation && attempt.mutation && (
        <div className="attempt-mutation">
          <span className="mutation-icon"><Icon icon="mdi:shuffle-variant" width="14" /></span>
          <span className="mutation-text">{attempt.mutation}</span>
        </div>
      )}

      {/* Rating (for rate_each mode) */}
      {selectionMode === 'rate_each' && (
        <div className="attempt-rating">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRate(star);
              }}
              className={`rating-star ${rating >= star ? 'filled' : ''}`}
            >
              {rating >= star ? '★' : '☆'}
            </button>
          ))}
        </div>
      )}

      {/* Ranking Button (for rank_all mode) */}
      {selectionMode === 'rank_all' && !rankPosition && (
        <button
          type="button"
          onClick={onSelect}
          className="add-to-ranking-btn"
        >
          Add to Ranking
        </button>
      )}
    </div>
  );
}

export default SoundingComparison;
