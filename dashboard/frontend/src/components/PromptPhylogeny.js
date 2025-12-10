import React, { useState, useEffect, useCallback } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import './PromptPhylogeny.css';

/**
 * PromptNode - Custom node component for displaying prompts
 */
function PromptNode({ data }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const promptPreview = data.prompt.length > 80
    ? data.prompt.substring(0, 80) + '...'
    : data.prompt;

  const nodeClasses = [
    'prompt-node',
    data.is_winner ? 'winner' : '',
    data.is_current_session ? 'current-session' : '',
    data.is_future ? 'future' : ''
  ].filter(Boolean).join(' ');

  const mutationBadgeColor = {
    'rewrite': '#3b82f6',    // blue
    'augment': '#eab308',    // yellow
    'approach': '#a855f7',   // purple
    null: '#6b7280'          // gray (baseline)
  }[data.mutation_type];

  return (
    <div className={nodeClasses} onClick={() => setIsExpanded(!isExpanded)}>
      <div className="node-header">
        <span className="generation-label">Gen {data.generation}</span>
        {data.is_winner && <span className="winner-crown">👑</span>}
        {data.is_current_session && <span className="current-marker">📍</span>}
      </div>

      <div className="prompt-preview">
        {isExpanded ? data.prompt : promptPreview}
      </div>

      {data.mutation_type && (
        <div
          className="mutation-badge"
          style={{ backgroundColor: mutationBadgeColor }}
        >
          {data.mutation_type}
        </div>
      )}

      {data.model && (
        <div className="model-label">
          {data.model.split('/').pop()}
        </div>
      )}

      <div className="node-footer">
        <span className="sounding-index">#{data.sounding_index}</span>
        {isExpanded && data.mutation_template && (
          <div className="mutation-template">
            Template: {data.mutation_template}
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = {
  promptNode: PromptNode,
};

/**
 * PromptPhylogeny - Visualization of prompt evolution across runs
 */
export default function PromptPhylogeny({ sessionId }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [metadata, setMetadata] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showFuture, setShowFuture] = useState(false);

  // Fetch evolution data
  useEffect(() => {
    if (!sessionId) return;

    const fetchEvolution = async () => {
      setLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({
          as_of: 'session',  // Show tree as it was at session time
          include_future: showFuture.toString()
        });

        const response = await fetch(
          `/api/sextant/evolution/${sessionId}?${params}`
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.error) {
          throw new Error(data.error);
        }

        setNodes(data.nodes || []);
        setEdges(data.edges || []);
        setMetadata(data.metadata || {});
      } catch (err) {
        console.error('Failed to fetch evolution data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchEvolution();
  }, [sessionId, showFuture]);

  if (loading) {
    return (
      <div className="phylogeny-loading">
        <div className="spinner"></div>
        <p>Loading prompt evolution...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="phylogeny-error">
        <p>⚠️ Error loading evolution data</p>
        <p className="error-detail">{error}</p>
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div className="phylogeny-empty">
        <p>📊 No evolution data available</p>
        <p className="empty-detail">
          Run this cascade multiple times to see prompt evolution!
        </p>
      </div>
    );
  }

  return (
    <div className="prompt-phylogeny-container">
      {/* Header with metadata */}
      <div className="phylogeny-header">
        <div className="phylogeny-title">
          <h3>🧬 Prompt Evolution</h3>
          <span className="species-hash" title={metadata.species_hash}>
            Species: {metadata.species_hash ? metadata.species_hash.substring(0, 8) : ''}...
          </span>
        </div>

        <div className="phylogeny-stats">
          <span className="stat">
            <strong>{metadata.session_count}</strong> generations
          </span>
          <span className="stat">
            <strong>{metadata.total_soundings}</strong> total attempts
          </span>
          <span className="stat">
            <strong>{metadata.winner_count}</strong> winners
          </span>
          {metadata.current_session_generation && (
            <span className="stat current-gen">
              You are at Gen <strong>{metadata.current_session_generation}</strong>
            </span>
          )}
        </div>

        <div className="phylogeny-controls">
          <label className="future-toggle">
            <input
              type="checkbox"
              checked={showFuture}
              onChange={(e) => setShowFuture(e.target.checked)}
            />
            Show future runs
          </label>
        </div>
      </div>

      {/* React Flow Canvas */}
      <div className="phylogeny-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.1}
          maxZoom={1.5}
        >
          <Background color="#aaa" gap={16} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              if (node.data.is_winner) return '#22c55e';
              if (node.data.is_current_session) return '#3b82f6';
              if (node.data.is_future) return '#9ca3af';
              return '#d1d5db';
            }}
            maskColor="rgba(0, 0, 0, 0.1)"
          />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="phylogeny-legend">
        <div className="legend-item">
          <span className="legend-icon winner">👑</span>
          <span>Winner</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon current">📍</span>
          <span>Current Session</span>
        </div>
        <div className="legend-item">
          <div className="legend-line winner-line"></div>
          <span>Winner Path</span>
        </div>
        <div className="legend-item">
          <div className="legend-line explored-line"></div>
          <span>Explored Path</span>
        </div>
        {showFuture && (
          <div className="legend-item">
            <div className="legend-box future-box"></div>
            <span>Future Runs</span>
          </div>
        )}
      </div>
    </div>
  );
}
