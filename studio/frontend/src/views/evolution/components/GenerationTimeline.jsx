import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './GenerationTimeline.css';

/**
 * ParentSnippet - Shows a snippet from a parent winner with colored badge
 */
function ParentSnippet({ parent, color, index }) {
  return (
    <div className="parent-snippet">
      <div className="parent-badge" style={{ backgroundColor: color }}>
        Gen {parent.generation}
      </div>
      <div className="parent-text">
        "{parent.prompt_snippet}..."
      </div>
    </div>
  );
}

/**
 * TakeChip - Clickable chip for a single take
 */
function TakeChip({ take, onClick, isHighlighted }) {
  return (
    <button
      className={`take-chip ${take.is_winner ? 'winner' : ''} ${isHighlighted ? 'highlighted' : ''}`}
      onClick={onClick}
      title={`Take #${take.take_index}${take.is_winner ? ' (Winner)' : ''}\nModel: ${take.model}\nCost: $${take.cost?.toFixed(4) || '0'}`}
    >
      #{take.take_index}
      {take.is_winner && <Icon icon="mdi:trophy" width="10" />}
      {take.in_training_set && <span className="training-dot">🎓</span>}
    </button>
  );
}

/**
 * GenerationCard - Shows the lineage story for a single generation
 */
function GenerationCard({ generation, isCurrentSession, onTakeClick, highlightedNode }) {
  const [showFullPrompt, setShowFullPrompt] = useState(false);
  const [showParents, setShowParents] = useState(true);

  const winner = generation.takes.find(c => c.is_winner);
  const totalCost = generation.takes.reduce((sum, c) => sum + (c.cost || 0), 0);

  // DNA bar colors (same as in graph)
  const dnaColors = ['#34d399', '#00e5ff', '#9333ea', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#a855f7'];
  const parents = generation.parent_winners || [];

  // Get prompt to display (winner if exists, otherwise first take)
  const displayTake = winner || generation.takes[0];
  const prompt = displayTake?.prompt || '';
  const promptPreview = prompt.length > 300 ? prompt.substring(0, 300) + '...' : prompt;
  const hasMore = prompt.length > 300;

  return (
    <div className={`gen-lineage-card ${isCurrentSession ? 'current-session' : ''}`}>
      {/* Compact Header */}
      <div className="gen-lineage-header">
        <div className="gen-lineage-header-left">
          <span className="gen-number">Gen {generation.generation}</span>
          {winner && <Icon icon="mdi:trophy" width="14" className="winner-icon" />}
          {isCurrentSession && <Icon icon="mdi:map-marker" width="14" className="current-marker" />}
        </div>
        <div className="gen-lineage-header-right">
          {displayTake?.model && (
            <span className="gen-model">{displayTake.model.split('/').pop().substring(0, 12)}</span>
          )}
          <span className="gen-cost">${totalCost.toFixed(4)}</span>
        </div>
      </div>

      {/* Parent Lineage (DNA) */}
      {parents.length > 0 && (
        <div className="gen-lineage-section">
          <div
            className="lineage-section-header"
            onClick={() => setShowParents(!showParents)}
          >
            <Icon icon="mdi:dna" width="14" />
            <span>Trained by {parents.length} parent{parents.length !== 1 ? 's' : ''}</span>
            <Icon
              icon={showParents ? 'mdi:chevron-up' : 'mdi:chevron-down'}
              width="14"
              className="section-toggle"
            />
          </div>
          {showParents && (
            <div className="parent-snippets">
              {parents.map((parent, idx) => (
                <ParentSnippet
                  key={`${parent.session_id}_${parent.take_index}`}
                  parent={parent}
                  color={dnaColors[idx % dnaColors.length]}
                  index={idx}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Mutation Info */}
      {displayTake?.mutation_type && (
        <div className="gen-lineage-section mutation-section">
          <div className="mutation-header">
            <Icon icon="mdi:auto-fix" width="14" />
            <span className="mutation-type-label">{displayTake.mutation_type}</span>
          </div>
          {displayTake.mutation_template && (
            <div className="mutation-template-preview">
              "{displayTake.mutation_template.substring(0, 100)}{displayTake.mutation_template.length > 100 ? '...' : ''}"
            </div>
          )}
        </div>
      )}

      {/* Prompt Content */}
      <div className="gen-lineage-section prompt-section">
        <div className="prompt-section-header">
          <Icon icon="mdi:text-box" width="14" />
          <span>Prompt</span>
        </div>
        <div className="prompt-content-timeline">
          {showFullPrompt ? prompt : promptPreview}
        </div>
        {hasMore && (
          <button
            className="show-more-btn"
            onClick={() => setShowFullPrompt(!showFullPrompt)}
          >
            <Icon icon={showFullPrompt ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="12" />
            {showFullPrompt ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>

      {/* Take Chips */}
      <div className="gen-lineage-section takes-section">
        <div className="takes-chips">
          {generation.takes.map(take => {
            const nodeId = `${generation.session_id}_${take.take_index}`;
            const isHighlighted = highlightedNode === nodeId;

            return (
              <TakeChip
                key={take.take_index}
                take={take}
                onClick={() => onTakeClick(nodeId, take)}
                isHighlighted={isHighlighted}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * GenerationTimeline - Right sidebar showing chronological lineage story
 *
 * Props:
 * - metadata: Evolution metadata from API
 * - nodes: React Flow nodes array
 * - onNodeFocus: Callback when a node should be focused (nodeId)
 * - highlightedNode: Currently highlighted node ID
 * - currentSessionId: Current session ID for highlighting
 */
const GenerationTimeline = ({ metadata, nodes, onNodeFocus, highlightedNode, currentSessionId }) => {
  // Group nodes by generation with parent info
  const generations = useMemo(() => {
    if (!nodes || nodes.length === 0) return [];

    // Group by session_id
    const sessionMap = {};

    nodes.forEach(node => {
      const sessionId = node.data.session_id;
      if (!sessionMap[sessionId]) {
        sessionMap[sessionId] = {
          session_id: sessionId,
          generation: node.data.generation,
          timestamp: node.data.timestamp,
          takes: [],
          parent_winners: node.data.parent_winners || [], // All takes in a gen have same parents
        };
      }

      sessionMap[sessionId].takes.push({
        take_index: node.data.take_index,
        is_winner: node.data.is_winner,
        in_training_set: node.data.in_training_set,
        mutation_type: node.data.mutation_type,
        mutation_template: node.data.mutation_template,
        model: node.data.model,
        prompt: node.data.prompt,
        cost: node.data.cost || 0,
      });
    });

    // Convert to array and sort by generation
    return Object.values(sessionMap).sort((a, b) => a.generation - b.generation);
  }, [nodes]);

  const handleTakeClick = (nodeId, take) => {
    console.log('[Timeline] Take clicked:', nodeId);
    if (onNodeFocus) {
      onNodeFocus(nodeId);
    }
  };

  if (!generations || generations.length === 0) {
    return (
      <div className="generation-timeline-empty">
        <Icon icon="mdi:timeline-clock-outline" width="32" />
        <p>No generations to display</p>
      </div>
    );
  }

  return (
    <div className="generation-timeline">
      <div className="timeline-header">
        <Icon icon="mdi:timeline-text" width="18" />
        <h3>Lineage</h3>
        <span className="timeline-count">{generations.length} gen{generations.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="timeline-content">
        {generations.map((gen, idx) => (
          <React.Fragment key={gen.session_id}>
            <GenerationCard
              generation={gen}
              isCurrentSession={gen.session_id === currentSessionId}
              onTakeClick={handleTakeClick}
              highlightedNode={highlightedNode}
            />

            {/* Connection Arrow between generations */}
            {idx < generations.length - 1 && (
              <div className="generation-connector">
                <Icon icon="mdi:arrow-down" width="16" className="connector-arrow" />
              </div>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Stats Footer */}
      <div className="timeline-footer">
        <div className="footer-stat">
          <Icon icon="mdi:trophy" width="14" />
          <span>{generations.filter(g => g.takes.some(c => c.is_winner)).length} winners</span>
        </div>
        <div className="footer-stat">
          <Icon icon="mdi:graph-outline" width="14" />
          <span>{generations.reduce((sum, g) => sum + g.takes.length, 0)} attempts</span>
        </div>
      </div>
    </div>
  );
};

export default GenerationTimeline;
