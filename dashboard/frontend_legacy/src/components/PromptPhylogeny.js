import React, { useState, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import './PromptPhylogeny.css';

/**
 * PromptNode - Custom node component for displaying prompts
 */
function PromptNode({ data }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Show more of the prompt (150 chars for narrower cards)
  const promptPreview = data.prompt.length > 150
    ? data.prompt.substring(0, 150) + '...'
    : data.prompt;

  const nodeClasses = [
    'prompt-node',
    data.is_winner ? 'winner' : '',
    data.is_current_session ? 'current-session' : '',
    data.is_future ? 'future' : '',
    data.in_training_set ? 'in-training' : ''
  ].filter(Boolean).join(' ');

  const mutationBadgeColor = {
    'rewrite': '#3b82f6',    // blue
    'augment': '#eab308',    // yellow
    'approach': '#a855f7',   // purple
    null: '#6b7280'          // gray (baseline)
  }[data.mutation_type];

  // Generate DNA bar colors (one color per parent winner)
  const parentWinners = data.parent_winners || [];
  const dnaColors = ['#22c55e', '#3b82f6', '#a855f7', '#eab308', '#ef4444', '#06b6d4', '#f59e0b', '#ec4899'];

  return (
    <div className={nodeClasses} onClick={() => setIsExpanded(!isExpanded)}>
      {/* Connection handles for edges */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      <div className="node-header">
        <span className="generation-label">Gen {data.generation}</span>
        {data.is_winner && <span className="winner-crown">👑</span>}
        {data.is_current_session && <span className="current-marker">📍</span>}
        {data.in_training_set && <span className="training-badge" title="In active training set (last 5 winners)">🎓</span>}
      </div>

      {/* DNA Inheritance Bar */}
      {parentWinners.length > 0 && (
        <div className="dna-bar-container" title={`Trained by ${parentWinners.length} winner(s)`}>
          <div className="dna-bar">
            {parentWinners.map((parent, idx) => (
              <div
                key={`${parent.session_id}_${parent.candidate_index}`}
                className="dna-segment"
                style={{
                  backgroundColor: dnaColors[idx % dnaColors.length],
                  width: `${100 / parentWinners.length}%`
                }}
                title={`Gen ${parent.generation} #${parent.candidate_index}: ${parent.prompt_snippet}...`}
              />
            ))}
          </div>
          <div className="gene-pool-label">
            🧬 {parentWinners.length} parent{parentWinners.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}

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
        <span className="sounding-index">#{data.candidate_index}</span>
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
 * Apply dagre layout algorithm to position nodes based on edges
 */
const getLayoutedElements = (nodes, edges, direction = 'LR') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  const nodeWidth = 350;
  const nodeHeight = 200;

  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 80,      // Horizontal spacing between nodes
    ranksep: 300,     // Vertical spacing between ranks (generations)
    edgesep: 50,      // Spacing between edges
    marginx: 50,
    marginy: 50
  });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
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
  const [winnersOnly, setWinnersOnly] = useState(false);
  const [allNodes, setAllNodes] = useState([]);  // Store unfiltered nodes
  const [allEdges, setAllEdges] = useState([]);  // Store unfiltered edges

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

        // Store original data
        setAllNodes(data.nodes || []);
        setAllEdges(data.edges || []);

        // Apply dagre auto-layout based on edges
        const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
          data.nodes || [],
          data.edges || [],
          'LR'  // Left-to-Right flow (generations go left to right)
        );

        setNodes(layoutedNodes);
        setEdges(layoutedEdges);
        setMetadata(data.metadata || {});
      } catch (err) {
        console.error('Failed to fetch evolution data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchEvolution();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, showFuture]);

  // Filter and re-layout when winnersOnly changes
  useEffect(() => {
    if (!allNodes.length || !allEdges.length) return;

    let filteredNodes = allNodes;
    let filteredEdges = allEdges;

    if (winnersOnly) {
      // Keep only winner nodes
      const winnerNodeIds = new Set(
        allNodes.filter(n => n.data.is_winner).map(n => n.id)
      );

      filteredNodes = allNodes.filter(n => winnerNodeIds.has(n.id));

      // Keep only edges between winners
      filteredEdges = allEdges.filter(e =>
        winnerNodeIds.has(e.source) && winnerNodeIds.has(e.target)
      );
    }

    // Re-apply dagre layout with filtered data
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      filteredNodes,
      filteredEdges,
      'LR'
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [winnersOnly, allNodes, allEdges, setNodes, setEdges]);

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
          <span className="stat" title="Each generation runs the same number of parallel soundings (factor). Learning happens via rewrite - winners train the next generation.">
            ℹ️ <strong>{metadata.total_soundings / metadata.session_count}</strong> soundings per gen
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
          <label className="winners-toggle">
            <input
              type="checkbox"
              checked={winnersOnly}
              onChange={(e) => setWinnersOnly(e.target.checked)}
            />
            👑 Winners Only
          </label>
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
          fitViewOptions={{ padding: 0.3, maxZoom: 0.8 }}
          minZoom={0.1}
          maxZoom={2}
          defaultZoom={0.7}
        >
          <Background color="#2d3139" gap={16} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              if (node.data.in_training_set) return '#f59e0b';  // Gold for training set
              if (node.data.is_winner) return '#22c55e';
              if (node.data.is_current_session) return '#3b82f6';
              if (node.data.is_future) return '#6b7280';
              return '#4b5563';
            }}
            maskColor="rgba(26, 29, 36, 0.7)"
          />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="phylogeny-legend">
        <div className="legend-item">
          <span className="legend-icon">🧬</span>
          <span>DNA Bar = Training Sources</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon winner">👑</span>
          <span>Winner (enters gene pool)</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon">🎓</span>
          <span>Active Training Set (last 5)</span>
        </div>
        <div className="legend-item">
          <div className="legend-line winner-line"></div>
          <span>Green = Last Gen Winner</span>
        </div>
        <div className="legend-item">
          <div className="legend-line" style={{background: '#8b5cf6', height: '2px', width: '24px', opacity: 0.5}}></div>
          <span>Purple = Gene Pool Ancestor</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon current">📍</span>
          <span>Current Session</span>
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
