import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './LinearInfluenceView.css';

/**
 * Assign consistent colors to each generation's winner for tracking influence
 * Expanded palette for 20+ generations
 */
const generationColors = [
  '#34d399', // green
  '#00e5ff', // cyan
  '#9333ea', // purple
  '#f59e0b', // amber
  '#ef4444', // red
  '#06b6d4', // sky
  '#ec4899', // pink
  '#a855f7', // violet
  '#10b981', // emerald
  '#3b82f6', // blue
  '#f97316', // orange
  '#14b8a6', // teal
  '#8b5cf6', // indigo
  '#84cc16', // lime
  '#f43f5e', // rose
  '#6366f1', // indigo-500
  '#22d3ee', // cyan-400
  '#a3e635', // lime-400
  '#fb7185', // rose-400
  '#c084fc', // purple-400
];

/**
 * TrainingSnippet - Shows a training prompt snippet with colored badge
 */
function TrainingSnippet({ snippet, color, generation, onClick, isHighlighted }) {
  return (
    <div
      className={`training-snippet ${isHighlighted ? 'highlighted' : ''}`}
      onClick={onClick}
      style={{ borderLeftColor: color }}
    >
      <div className="training-badge" style={{ backgroundColor: color }}>
        Gen {generation}
      </div>
      <div className="training-text">
        {snippet}
      </div>
    </div>
  );
}

/**
 * GenerationBlock - Single generation showing winner + training sources
 */
function GenerationBlock({ generation, generationColor, onSnippetClick, highlightedGen, onEvolveClick }) {
  const [showFullWinner, setShowFullWinner] = useState(false);

  const winner = generation.candidates.find(c => c.is_winner) || generation.candidates[0];

  console.log('[GenerationBlock] Gen', generation.generation, '- Has winner:', !!winner?.is_winner, '- Has evolveClick:', !!onEvolveClick);
  const winnerPrompt = winner?.prompt || '';
  const winnerPreview = winnerPrompt.length > 400 ? winnerPrompt.substring(0, 400) + '...' : winnerPrompt;
  const hasMore = winnerPrompt.length > 400;

  const totalCost = generation.candidates.reduce((sum, c) => sum + (c.cost || 0), 0);
  const parents = generation.parent_winners || [];

  const isHighlighted = highlightedGen === generation.generation;

  return (
    <div className={`gen-block ${isHighlighted ? 'highlighted' : ''}`}>
      {/* Generation Header */}
      <div className="gen-block-header">
        <div className="gen-block-number" style={{ backgroundColor: generationColor }}>
          Gen {generation.generation}
        </div>
        {winner?.is_winner && <Icon icon="mdi:trophy" width="16" className="block-winner-icon" />}
        <div className="gen-block-meta">
          <span className="block-model">{winner?.model?.split('/').pop().substring(0, 15)}</span>
          <span className="block-cost">${totalCost.toFixed(4)}</span>
        </div>
      </div>

      {/* Winner Prompt (Top - Prominent) */}
      <div className="winner-prompt-section">
        <div className="winner-prompt-header">
          <Icon icon="mdi:star" width="14" />
          <span>Winner</span>
          {winner?.mutation_type && (
            <span className="winner-mutation">{winner.mutation_type}</span>
          )}
          {winner?.is_winner && onEvolveClick && (
            <button
              className="evolve-btn-mini"
              onClick={(e) => {
                e.stopPropagation();
                console.log('[GenerationBlock] Evolve clicked!', generation);
                onEvolveClick(generation);
              }}
              title="Evolve: Promote this winner to baseline and create new species"
            >
              <Icon icon="mdi:dna" width="12" />
              ⚡ Evolve
            </button>
          )}
        </div>
        <div
          className="winner-prompt-content"
          style={{ borderLeftColor: generationColor }}
        >
          {showFullWinner ? winnerPrompt : winnerPreview}
        </div>
        {hasMore && (
          <button
            className="toggle-prompt-btn"
            onClick={() => setShowFullWinner(!showFullWinner)}
          >
            <Icon icon={showFullWinner ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="12" />
            {showFullWinner ? 'Less' : 'More'}
          </button>
        )}
      </div>

      {/* Training Sources (Bottom - Parent Winners) */}
      {parents.length > 0 && (
        <div className="training-sources-section">
          <div className="training-sources-header">
            <Icon icon="mdi:dna" width="12" />
            <span>Trained by {parents.length}</span>
          </div>
          <div className="training-sources-list">
            {parents.map((parent, idx) => {
              const parentColor = generationColors[(parent.generation - 1) % generationColors.length];
              const isHighlighted = highlightedGen === parent.generation;

              return (
                <TrainingSnippet
                  key={`${parent.session_id}_${parent.candidate_index}`}
                  snippet={parent.prompt_snippet}
                  color={parentColor}
                  generation={parent.generation}
                  onClick={() => onSnippetClick(parent.generation)}
                  isHighlighted={isHighlighted}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Candidate Chips (All attempts) */}
      <div className="block-candidates">
        {generation.candidates.map((cand, idx) => (
          <span
            key={idx}
            className={`block-candidate-chip ${cand.is_winner ? 'winner' : ''}`}
            title={`#${cand.candidate_index} - ${cand.model} - $${cand.cost?.toFixed(4)}`}
          >
            #{cand.candidate_index}
            {cand.is_winner && '👑'}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * LinearInfluenceView - Horizontal blocks showing prompt evolution and influence flow
 *
 * Props:
 * - nodes: React Flow nodes array
 * - currentSessionId: Current session for highlighting
 * - onEvolveClick: Callback when evolve button clicked (optional)
 */
const LinearInfluenceView = ({ nodes, currentSessionId, onEvolveClick }) => {
  const [highlightedGen, setHighlightedGen] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [startY, setStartY] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const timelineRef = React.useRef(null);

  console.log('[LinearInfluenceView] onEvolveClick prop:', !!onEvolveClick);

  // Group nodes by generation
  const generations = useMemo(() => {
    if (!nodes || nodes.length === 0) return [];

    const sessionMap = {};

    nodes.forEach(node => {
      const sessionId = node.data.session_id;
      if (!sessionMap[sessionId]) {
        sessionMap[sessionId] = {
          session_id: sessionId,
          generation: node.data.generation,
          timestamp: node.data.timestamp,
          candidates: [],
          parent_winners: node.data.parent_winners || [],
        };
      }

      sessionMap[sessionId].candidates.push({
        candidate_index: node.data.candidate_index,
        is_winner: node.data.is_winner,
        in_training_set: node.data.in_training_set,
        mutation_type: node.data.mutation_type,
        mutation_template: node.data.mutation_template,
        model: node.data.model,
        prompt: node.data.prompt,
        cost: node.data.cost || 0,
      });
    });

    return Object.values(sessionMap).sort((a, b) => a.generation - b.generation);
  }, [nodes]);

  const handleSnippetClick = (generation) => {
    console.log('[LinearInfluence] Highlighting generation:', generation);
    setHighlightedGen(highlightedGen === generation ? null : generation);
  };

  // Drag-to-scroll handlers
  const handleMouseDown = (e) => {
    if (!timelineRef.current) return;
    // Don't start drag if clicking on a button or interactive element
    if (e.target.closest('button')) {
      console.log('[LinearInfluence] Clicked button, not dragging');
      return;
    }

    setIsDragging(true);
    setStartX(e.pageX - timelineRef.current.offsetLeft);
    setStartY(e.pageY - timelineRef.current.offsetTop);
    setScrollLeft(timelineRef.current.scrollLeft);
    setScrollTop(timelineRef.current.scrollTop);
  };

  const handleMouseMove = (e) => {
    if (!isDragging || !timelineRef.current) return;

    // Only treat as drag if moved more than 5px (prevents accidental drags on click)
    const x = e.pageX - timelineRef.current.offsetLeft;
    const y = e.pageY - timelineRef.current.offsetTop;
    const deltaX = Math.abs(x - startX);
    const deltaY = Math.abs(y - startY);

    if (deltaX < 5 && deltaY < 5) return; // Not a real drag yet

    e.preventDefault();
    const walkX = (x - startX) * 1.5; // Multiply for faster scroll
    const walkY = (y - startY) * 1.5;
    timelineRef.current.scrollLeft = scrollLeft - walkX;
    timelineRef.current.scrollTop = scrollTop - walkY;
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleMouseLeave = () => {
    setIsDragging(false);
  };

  if (!generations || generations.length === 0) {
    return (
      <div className="linear-influence-empty">
        <Icon icon="mdi:timeline-outline" width="48" />
        <p>No evolution data to display</p>
      </div>
    );
  }

  return (
    <div className="linear-influence-view">
      {/* Header */}
      <div className="linear-influence-header">
        <Icon icon="mdi:arrow-right-bold" width="20" />
        <h3>Influence Flow</h3>
        <span className="influence-hint">Colors show prompt influence across generations</span>
      </div>

      {/* Horizontal Scrolling Container */}
      <div
        ref={timelineRef}
        className={`influence-timeline ${isDragging ? 'dragging' : ''}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        {generations.map((gen, idx) => {
          const genColor = generationColors[(gen.generation - 1) % generationColors.length];

          return (
            <React.Fragment key={gen.session_id}>
              <GenerationBlock
                generation={gen}
                generationColor={genColor}
                onSnippetClick={handleSnippetClick}
                highlightedGen={highlightedGen}
                onEvolveClick={onEvolveClick}
              />

              {/* Arrow Connector */}
              {idx < generations.length - 1 && (
                <div className="block-connector">
                  <Icon icon="mdi:arrow-right" width="24" className="connector-icon" />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Color Legend */}
      <div className="linear-influence-legend">
        <Icon icon="mdi:palette" width="14" />
        <span>Each generation has a unique color. Click training snippets to highlight influence flow.</span>
      </div>
    </div>
  );
};

export default LinearInfluenceView;
