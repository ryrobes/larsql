/**
 * CascadeFlowModal - React Flow based cascade visualization
 *
 * Two modes:
 * 1. Spec View: Visualize from YAML/JSON spec (before execution)
 *    - Shows all possible paths
 *    - Shows configured features (soundings, reforge, wards, tools)
 *    - "Ghost" appearance - what COULD happen
 *
 * 2. Execution View: Enriched with run data (after execution)
 *    - Highlights actual path taken
 *    - Shows real costs, durations, sounding winners
 *    - "Solid" appearance - what DID happen
 */

import React, { useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  MarkerType,
} from 'reactflow';
import dagre from 'dagre';
import { Icon } from '@iconify/react';
import 'reactflow/dist/style.css';
import './CascadeFlowModal.css';

// Layout configuration
const NODE_WIDTH = 280;
const NODE_HEIGHT_BASE = 80;
const NODE_HEIGHT_EXPANDED = 200;

/**
 * Calculate automatic layout using dagre
 */
function getLayoutedElements(nodes, edges, direction = 'LR') {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 80,
    ranksep: 120,
    marginx: 50,
    marginy: 50,
  });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: NODE_WIDTH,
      height: node.data.isExpanded ? NODE_HEIGHT_EXPANDED : NODE_HEIGHT_BASE,
    });
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
        x: nodeWithPosition.x - NODE_WIDTH / 2,
        y: nodeWithPosition.y - (node.data.isExpanded ? NODE_HEIGHT_EXPANDED : NODE_HEIGHT_BASE) / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

/**
 * PhaseNode - Custom node for rendering a phase
 */
function PhaseNode({ data, selected }) {
  const {
    name,
    index,
    // Spec data
    hasSoundings,
    soundingsFactor,
    hasReforge,
    reforgeSteps,
    hasWards,
    wardCount,
    hasHandoffs,
    handoffCount,
    tackleCount,
    model,
    // Execution data (optional)
    executed,
    isOnPath,
    status,
    cost,
    duration,
    soundingWinner,
    turnCount,
  } = data;

  const isGhost = !executed;

  const nodeClasses = [
    'flow-phase-node',
    isGhost ? 'ghost' : 'executed',
    isOnPath ? 'on-path' : '',
    status === 'running' ? 'running' : '',
    status === 'error' ? 'error' : '',
    status === 'completed' ? 'completed' : '',
    selected ? 'selected' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={nodeClasses}>
      <Handle type="target" position={Position.Left} />

      {/* Phase Header */}
      <div className="phase-node-header">
        <span className="phase-index">{index + 1}</span>
        <span className="phase-name">{name}</span>
        {executed && status === 'completed' && (
          <Icon icon="mdi:check-circle" className="status-icon completed" />
        )}
        {status === 'running' && (
          <Icon icon="mdi:loading" className="status-icon running" />
        )}
        {status === 'error' && (
          <Icon icon="mdi:alert-circle" className="status-icon error" />
        )}
      </div>

      {/* Feature Badges */}
      <div className="phase-node-badges">
        {hasSoundings && (
          <span className="badge soundings" title={`${soundingsFactor}x soundings`}>
            <Icon icon="mdi:source-branch" width="12" />
            {soundingsFactor}x
          </span>
        )}
        {hasReforge && (
          <span className="badge reforge" title={`${reforgeSteps} reforge steps`}>
            <Icon icon="mdi:hammer-wrench" width="12" />
            {reforgeSteps}
          </span>
        )}
        {hasWards && (
          <span className="badge wards" title={`${wardCount} wards`}>
            <Icon icon="mdi:shield-check" width="12" />
            {wardCount}
          </span>
        )}
        {tackleCount > 0 && (
          <span className="badge tackle" title={`${tackleCount} tools`}>
            <Icon icon="mdi:wrench" width="12" />
            {tackleCount}
          </span>
        )}
        {hasHandoffs && (
          <span className="badge handoffs" title={`${handoffCount} handoffs`}>
            <Icon icon="mdi:arrow-decision" width="12" />
            {handoffCount}
          </span>
        )}
      </div>

      {/* Execution Stats (if available) */}
      {executed && (
        <div className="phase-node-stats">
          {cost !== undefined && (
            <span className="stat cost">
              <Icon icon="mdi:currency-usd" width="12" />
              {cost < 0.01 ? cost.toFixed(4) : cost.toFixed(3)}
            </span>
          )}
          {duration !== undefined && (
            <span className="stat duration">
              <Icon icon="mdi:timer-outline" width="12" />
              {duration.toFixed(1)}s
            </span>
          )}
          {turnCount !== undefined && (
            <span className="stat turns">
              <Icon icon="mdi:repeat" width="12" />
              {turnCount}
            </span>
          )}
          {soundingWinner !== undefined && (
            <span className="stat winner">
              <Icon icon="mdi:trophy" width="12" />
              S{soundingWinner}
            </span>
          )}
        </div>
      )}

      {/* Model Badge */}
      {model && (
        <div className="phase-node-model">
          <Icon icon="mdi:brain" width="10" />
          <span>{model.split('/').pop()}</span>
        </div>
      )}

      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = {
  phase: PhaseNode,
};

/**
 * Convert cascade spec to React Flow nodes and edges
 */
function specToFlow(cascade, executionData = null) {
  const nodes = [];
  const edges = [];

  const phases = cascade.phases || [];

  // Create nodes for each phase
  phases.forEach((phase, index) => {
    const soundings = phase.soundings || {};
    const reforge = soundings.reforge || {};
    const wards = phase.wards || {};
    const wardCount =
      (wards.pre?.length || 0) +
      (wards.post?.length || 0) +
      (wards.turn?.length || 0);

    // Check if we have execution data for this phase
    const phaseExecution = executionData?.phases?.[phase.name];
    const isOnPath = executionData?.executedPath?.includes(phase.name);

    nodes.push({
      id: phase.name,
      type: 'phase',
      position: { x: 0, y: 0 }, // Will be set by layout
      data: {
        name: phase.name,
        index,
        // Spec data
        hasSoundings: soundings.factor > 1,
        soundingsFactor: soundings.factor || 1,
        hasReforge: reforge.steps > 0,
        reforgeSteps: reforge.steps || 0,
        hasWards: wardCount > 0,
        wardCount,
        hasHandoffs: phase.handoffs?.length > 0,
        handoffCount: phase.handoffs?.length || 0,
        tackleCount: Array.isArray(phase.tackle) ? phase.tackle.length : (phase.tackle ? 1 : 0),
        model: phase.model,
        // Execution data
        executed: !!phaseExecution,
        isOnPath,
        status: phaseExecution?.status,
        cost: phaseExecution?.cost,
        duration: phaseExecution?.duration,
        soundingWinner: phaseExecution?.soundingWinner,
        turnCount: phaseExecution?.turnCount,
      },
    });
  });

  // Create edges
  phases.forEach((phase, index) => {
    if (phase.handoffs && phase.handoffs.length > 0) {
      // Explicit handoffs
      phase.handoffs.forEach((target, hIndex) => {
        const isExecutedEdge = executionData?.executedHandoffs?.[phase.name] === target;
        edges.push({
          id: `${phase.name}-${target}-${hIndex}`,
          source: phase.name,
          target,
          type: 'smoothstep',
          animated: isExecutedEdge,
          style: {
            stroke: isExecutedEdge ? '#34d399' : '#4a5568',
            strokeWidth: isExecutedEdge ? 2 : 1,
            opacity: isExecutedEdge ? 1 : 0.5,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isExecutedEdge ? '#34d399' : '#4a5568',
          },
          label: phase.handoffs.length > 1 ? target : undefined,
          labelStyle: { fill: '#888', fontSize: 10 },
        });
      });
    } else if (index < phases.length - 1) {
      // Default: connect to next phase
      const nextPhase = phases[index + 1];
      const isExecutedEdge =
        executionData?.executedPath?.includes(phase.name) &&
        executionData?.executedPath?.includes(nextPhase.name);
      edges.push({
        id: `${phase.name}-${nextPhase.name}`,
        source: phase.name,
        target: nextPhase.name,
        type: 'smoothstep',
        animated: isExecutedEdge,
        style: {
          stroke: isExecutedEdge ? '#34d399' : '#4a5568',
          strokeWidth: isExecutedEdge ? 2 : 1,
          opacity: isExecutedEdge ? 1 : 0.6,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isExecutedEdge ? '#34d399' : '#4a5568',
        },
      });
    }
  });

  return getLayoutedElements(nodes, edges);
}

/**
 * Main Modal Component
 */
function CascadeFlowModal({ cascade, executionData, onClose }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Convert spec to flow on mount or when data changes
  useEffect(() => {
    if (!cascade) return;

    const { nodes: layoutedNodes, edges: layoutedEdges } = specToFlow(
      cascade,
      executionData
    );
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [cascade, executionData, setNodes, setEdges]);

  const hasExecution = !!executionData;

  return (
    <div className="cascade-flow-modal-overlay" onClick={onClose}>
      <div className="cascade-flow-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="header-left">
            <Icon icon="ph:tree-structure" width="20" />
            <h2>{cascade?.cascade_id || 'Cascade Flow'}</h2>
            <span className={`view-badge ${hasExecution ? 'execution' : 'spec'}`}>
              {hasExecution ? 'Execution View' : 'Spec View'}
            </span>
          </div>
          <div className="header-right">
            <div className="legend">
              <span className="legend-item">
                <span className="legend-dot ghost" />
                Spec (possible)
              </span>
              <span className="legend-item">
                <span className="legend-dot executed" />
                Executed (actual)
              </span>
            </div>
            <button className="close-btn" onClick={onClose}>
              <Icon icon="mdi:close" width="20" />
            </button>
          </div>
        </div>

        {/* Flow Canvas */}
        <div className="flow-container">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.1}
            maxZoom={2}
            defaultEdgeOptions={{
              type: 'smoothstep',
            }}
          >
            <Background color="#333" gap={20} size={1} />
            <Controls />
            <MiniMap
              nodeColor={(node) => {
                if (node.data?.status === 'error') return '#f87171';
                if (node.data?.status === 'completed') return '#34d399';
                if (node.data?.status === 'running') return '#fbbf24';
                if (node.data?.executed) return '#60a5fa';
                return '#4a5568';
              }}
              maskColor="rgba(0,0,0,0.8)"
            />
          </ReactFlow>
        </div>

        {/* Footer with stats */}
        {hasExecution && executionData.summary && (
          <div className="modal-footer">
            <span className="footer-stat">
              <Icon icon="mdi:counter" width="14" />
              {executionData.summary.phaseCount} phases
            </span>
            <span className="footer-stat">
              <Icon icon="mdi:currency-usd" width="14" />
              ${executionData.summary.totalCost?.toFixed(4)}
            </span>
            <span className="footer-stat">
              <Icon icon="mdi:timer-outline" width="14" />
              {executionData.summary.totalDuration?.toFixed(1)}s
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default CascadeFlowModal;
