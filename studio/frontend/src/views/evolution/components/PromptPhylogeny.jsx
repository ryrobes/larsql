import React, { useState, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
} from 'reactflow';
import dagre from 'dagre';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import 'reactflow/dist/style.css';
import './PromptPhylogeny.css';

/**
 * PromptNode - Custom node component for displaying prompts in the phylogeny graph
 *
 * Shows:
 * - Generation number
 * - DNA inheritance bar (which parent winners trained this prompt)
 * - Prompt preview (expandable)
 * - Mutation badge
 * - Model info
 * - Winner/current session indicators
 */
function PromptNode({ data }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const promptPreview = data.prompt?.length > 150
    ? data.prompt.substring(0, 150) + '...'
    : data.prompt;

  const nodeClasses = [
    'prompt-node',
    data.is_winner ? 'winner' : '',
    data.is_current_session ? 'current-session' : '',
    data.is_future ? 'future' : '',
    data.in_training_set ? 'in-training' : '',
    data.isHighlighted ? 'highlighted' : ''
  ].filter(Boolean).join(' ');

  const mutationColors = {
    'rewrite': '#9333ea',    // purple
    'augment': '#0ea5e9',    // sky
    'approach': '#f59e0b',   // amber
    null: '#475569'          // gray (baseline)
  };

  const mutationColor = mutationColors[data.mutation_type] || mutationColors[null];

  // DNA bar colors (one per parent winner)
  const dnaColors = ['#34d399', '#00e5ff', '#9333ea', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#a855f7'];
  const parentWinners = data.parent_winners || [];

  return (
    <div className={nodeClasses} onClick={() => setIsExpanded(!isExpanded)}>
      {/* React Flow connection handles */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      {/* Header */}
      <div className="prompt-node-header">
        <span className="generation-label">Gen {data.generation}</span>
        <div className="prompt-node-badges">
          {data.is_winner && <span className="winner-badge" title="Winner">👑</span>}
          {data.is_current_session && <span className="current-badge" title="Current session">📍</span>}
          {data.in_training_set && (
            <span className="training-badge" title="Active training set (last 5 winners)">
              🎓
            </span>
          )}
        </div>
      </div>

      {/* DNA Inheritance Bar */}
      {parentWinners.length > 0 && (
        <div className="dna-bar-container">
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
          <div className="dna-label">
            🧬 {parentWinners.length} parent{parentWinners.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}

      {/* Prompt Content */}
      <div className="prompt-content">
        {isExpanded ? data.prompt : promptPreview}
      </div>

      {/* Mutation Badge */}
      {data.mutation_type && (
        <div className="mutation-badge" style={{ backgroundColor: mutationColor }}>
          {data.mutation_type}
        </div>
      )}

      {/* Model Label */}
      {data.model && (
        <div className="model-label">
          {data.model.split('/').pop()}
        </div>
      )}

      {/* Footer */}
      <div className="prompt-node-footer">
        <span className="candidate-index">#{data.candidate_index}</span>
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
 * Apply dagre layout algorithm to position nodes
 */
const getLayoutedElements = (nodes, edges, direction = 'LR') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  const nodeWidth = 320;
  const nodeHeight = 220;

  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 80,
    ranksep: 300,
    edgesep: 50,
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
 *
 * Props:
 * - nodes: Pre-loaded nodes from parent (required)
 * - edges: Pre-loaded edges from parent (required)
 * - metadata: Pre-loaded metadata (optional)
 * - loading: Loading state from parent (optional)
 * - error: Error state from parent (optional)
 * - highlightedNode: Node ID to highlight (optional)
 */
function PromptPhylogenyInner({ nodes: rawNodes, edges: rawEdges, metadata, loading, error, highlightedNode }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [winnersOnly, setWinnersOnly] = useState(false);
  const reactFlowInstance = useReactFlow();

  // Apply layout to raw nodes/edges when they change
  useEffect(() => {
    if (!rawNodes || rawNodes.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }

    let filteredNodes = rawNodes;
    let filteredEdges = rawEdges;

    // Apply winners-only filter if enabled
    if (winnersOnly) {
      const winnerNodeIds = new Set(
        rawNodes.filter(n => n.data?.is_winner).map(n => n.id)
      );

      filteredNodes = rawNodes.filter(n => winnerNodeIds.has(n.id));
      filteredEdges = rawEdges.filter(e =>
        winnerNodeIds.has(e.source) && winnerNodeIds.has(e.target)
      );
    }

    // Apply dagre layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      filteredNodes,
      filteredEdges,
      'LR'
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [rawNodes, rawEdges, winnersOnly, setNodes, setEdges]);

  // Apply highlighting and zoom when highlightedNode changes
  useEffect(() => {
    if (!nodes.length) return;

    const updatedNodes = nodes.map(node => ({
      ...node,
      data: {
        ...node.data,
        isHighlighted: node.id === highlightedNode
      }
    }));

    setNodes(updatedNodes);

    // Zoom and pan to the highlighted node
    if (highlightedNode && reactFlowInstance) {
      setTimeout(() => {
        reactFlowInstance.fitView({
          padding: 0.3,
          duration: 800,
          nodes: [{ id: highlightedNode }],
        });
      }, 50); // Small delay to let the node update first
    }
  }, [highlightedNode, reactFlowInstance]); // Only depend on highlightedNode and instance

  if (loading) {
    return (
      <div className="phylogeny-loading">
        <VideoLoader size="medium" message="Loading prompt evolution..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="phylogeny-error">
        <Icon icon="mdi:alert-circle" width="32" />
        <p>⚠️ Error loading evolution data</p>
        <p className="error-detail">{error}</p>
      </div>
    );
  }

  if (!nodes.length) {
    // Check if we have metadata to provide a better error message
    const errorMessage = error || (metadata && metadata.message);

    return (
      <div className="phylogeny-empty">
        <Icon icon="mdi:chart-timeline" width="48" />
        <p>📊 No evolution data available</p>
        {errorMessage && errorMessage.includes('species_hash') ? (
          <div className="empty-detail">
            <p><strong>Missing species_hash data</strong></p>
            <p>This session doesn't have species_hash logged. This field is required for evolution tracking.</p>
            <p>Make sure you're running a recent version of RVBBIT that logs species_hash.</p>
            <details style={{ marginTop: '12px', fontSize: '12px', color: '#64748b' }}>
              <summary style={{ cursor: 'pointer' }}>What is species_hash?</summary>
              <p style={{ marginTop: '8px', lineHeight: '1.5' }}>
                Species hash is a unique identifier for your cell configuration (instructions, rules, candidates settings).
                It ensures we only compare prompts with the same "DNA" template for fair analysis.
              </p>
            </details>
          </div>
        ) : (
          <p className="empty-detail">
            Run this cascade multiple times with candidates (candidates) to see prompt evolution!
            {errorMessage && <><br/><br/><strong>Error:</strong> {errorMessage}</>}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="prompt-phylogeny-container">
      {/* Header with metadata and controls */}
      <div className="phylogeny-header">
        <div className="phylogeny-title">
          <h3>🧬 Prompt Evolution</h3>
          {metadata.species_hash && (
            <span className="species-hash" title={metadata.species_hash}>
              Species: {metadata.species_hash.substring(0, 8)}...
            </span>
          )}
        </div>

        <div className="phylogeny-stats">
          <span className="stat">
            <strong>{metadata.session_count}</strong> generations
          </span>
          <span className="stat">
            <strong>{metadata.total_candidates}</strong> total attempts
          </span>
          {metadata.total_candidates && metadata.session_count && (
            <span className="stat" title="Candidates per generation">
              <Icon icon="mdi:information-outline" width="14" />
              <strong>{Math.round(metadata.total_candidates / metadata.session_count)}</strong> per gen
            </span>
          )}
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
          <label className="control-toggle">
            <input
              type="checkbox"
              checked={winnersOnly}
              onChange={(e) => setWinnersOnly(e.target.checked)}
            />
            <Icon icon="mdi:trophy" width="14" />
            <span>Winners Only</span>
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
          <Background color="#1a1628" gap={16} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              if (node.data?.in_training_set) return '#f59e0b';
              if (node.data?.is_winner) return '#34d399';
              if (node.data?.is_current_session) return '#00e5ff';
              if (node.data?.is_future) return '#475569';
              return '#334155';
            }}
            maskColor="rgba(0, 0, 0, 0.7)"
          />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="phylogeny-legend">
        <div className="legend-item">
          <Icon icon="mdi:dna" width="16" />
          <span>DNA Bar = Training Sources</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon">👑</span>
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
          <div className="legend-line gene-pool-line"></div>
          <span>Purple = Gene Pool Ancestor</span>
        </div>
        <div className="legend-item">
          <span className="legend-icon">📍</span>
          <span>Current Session</span>
        </div>
      </div>
    </div>
  );
}

// Wrap with ReactFlowProvider to enable useReactFlow hook
export default function PromptPhylogeny(props) {
  return (
    <ReactFlowProvider>
      <PromptPhylogenyInner {...props} />
    </ReactFlowProvider>
  );
}
