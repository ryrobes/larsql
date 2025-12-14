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

import React, { useEffect, useState, useCallback } from 'react';
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
import PhaseInnerDiagram from './PhaseInnerDiagram';
import 'reactflow/dist/style.css';
import './CascadeFlowModal.css';
import './PhaseInnerDiagram.css';

// Layout configuration
const NODE_WIDTH = 320;
const NODE_WIDTH_EXPANDED = 360;
const NODE_HEIGHT_BASE = 80;
const NODE_HEIGHT_EXPANDED = 220;

/**
 * Calculate node height based on complexity and expansion
 */
function calculateNodeHeight(nodeData) {
  if (!nodeData.isExpanded) {
    return NODE_HEIGHT_BASE;
  }

  let height = NODE_HEIGHT_EXPANDED;

  // Add height for soundings
  if (nodeData.hasSoundings) {
    height += 20;
    if (nodeData.soundingsFactor > 6) {
      height += 20; // Extra row for many soundings
    }
  }

  // Add height for reforge
  if (nodeData.hasReforge) {
    height += 40 + (nodeData.reforgeSteps * 20);
  }

  // Add height for wards
  if (nodeData.hasWards) {
    height += 40;
  }

  return height;
}

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
    const nodeWidth = node.data.isExpanded ? NODE_WIDTH_EXPANDED : NODE_WIDTH;
    const nodeHeight = calculateNodeHeight(node.data);
    dagreGraph.setNode(node.id, {
      width: nodeWidth,
      height: nodeHeight,
    });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const nodeWidth = node.data.isExpanded ? NODE_WIDTH_EXPANDED : NODE_WIDTH;
    const nodeHeight = calculateNodeHeight(node.data);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

/**
 * Categorize tackle tools for display
 */
function categorizeTackle(tackle) {
  if (!tackle) return { isManifest: false, hasHitl: false, hasRabbitize: false, hasCode: false, hasSql: false };
  if (tackle === 'manifest') return { isManifest: true, hasHitl: false, hasRabbitize: false, hasCode: false, hasSql: false };
  if (!Array.isArray(tackle)) return { isManifest: false, hasHitl: false, hasRabbitize: false, hasCode: false, hasSql: false };

  return {
    isManifest: false,
    hasHitl: tackle.some(t => t.includes('ask_human')),
    hasRabbitize: tackle.some(t => t.includes('rabbitize')),
    hasCode: tackle.some(t => ['run_code', 'linux_shell'].includes(t)),
    hasSql: tackle.some(t => t.includes('sql')),
  };
}

/**
 * PhaseNode - Custom node for rendering a phase
 */
function PhaseNode({ data, selected }) {
  const {
    name,
    index,
    // Full phase spec for inner diagram
    phaseSpec,
    // Spec data (summary)
    hasSoundings,
    soundingsFactor,
    hasReforge,
    reforgeSteps,
    hasWards,
    wardCount,
    hasHandoffs,
    handoffCount,
    tackle,
    tackleCount,
    model,
    // Rules
    maxTurns,
    maxAttempts,
    hasLoopUntil,
    hasTurnPrompt,
    // Deterministic
    isDeterministic,
    deterministicTool,
    deterministicInputs,
    hasRouting,
    // Prompt
    instructions,
    // Features
    hasOutputSchema,
    hasSubCascades,
    hasAsyncCascades,
    hasOnError,
    // Soundings details
    soundingsMode,
    hasMultiModel,
    hasMutations,
    // Execution data (optional)
    executed,
    isOnPath,
    status,
    cost,
    duration,
    soundingWinner,
    turnCount,
    executionDetails,
    // Rich execution data
    executionOutput,
    executionImages,
    executionModel,
    executionTokensIn,
    executionTokensOut,
    // UI state
    isExpanded,
    onToggleExpand,
  } = data;

  const isGhost = !executed;
  const hasInnerComplexity = hasSoundings || hasWards;
  const tackleInfo = categorizeTackle(tackle);

  const nodeClasses = [
    'flow-phase-node',
    isGhost ? 'ghost' : 'executed',
    isOnPath ? 'on-path' : '',
    status === 'running' ? 'running' : '',
    status === 'error' ? 'error' : '',
    status === 'completed' ? 'completed' : '',
    selected ? 'selected' : '',
    isExpanded ? 'expanded' : '',
    hasInnerComplexity ? 'has-complexity' : '',
    isDeterministic ? 'deterministic' : '',
  ].filter(Boolean).join(' ');

  const handleExpandClick = (e) => {
    e.stopPropagation();
    if (onToggleExpand && hasInnerComplexity) {
      onToggleExpand(name);
    }
  };

  return (
    <div className={nodeClasses}>
      <Handle type="target" position={Position.Left} />

      {/* Phase Header */}
      <div className="phase-node-header">
        <span className="phase-index">{index + 1}</span>
        {isDeterministic && (
          <Icon icon="mdi:cog" className="deterministic-icon" width="14" title="Deterministic (tool-only, no LLM)" />
        )}
        <span className="phase-name" title={name}>{name}</span>
        {executed && status === 'completed' && (
          <Icon icon="mdi:check-circle" className="status-icon completed" />
        )}
        {status === 'running' && (
          <Icon icon="mdi:loading" className="status-icon running" />
        )}
        {status === 'error' && (
          <Icon icon="mdi:alert-circle" className="status-icon error" />
        )}
        {hasInnerComplexity && (
          <button className="expand-btn" onClick={handleExpandClick} title={isExpanded ? 'Collapse' : 'Expand inner structure'}>
            <Icon icon={isExpanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="14" />
          </button>
        )}
      </div>

      {/* Feature Badges - Row 1: Execution patterns */}
      <div className="phase-node-badges">
        {hasSoundings && (
          <span className="badge soundings" title={`${soundingsFactor}x soundings${soundingsMode === 'aggregate' ? ' (aggregate)' : ''}${hasMultiModel ? ' (multi-model)' : ''}`}>
            <Icon icon={soundingsMode === 'aggregate' ? 'mdi:call-merge' : 'mdi:source-branch'} width="12" />
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
        {maxTurns > 1 && (
          <span className="badge turns" title={`${maxTurns} max turns${hasTurnPrompt ? ' with turn_prompt' : ''}`}>
            <Icon icon="mdi:rotate-right" width="12" />
            {maxTurns}
          </span>
        )}
        {hasLoopUntil && (
          <span className="badge loop" title={`Validation loop${maxAttempts ? ` (max ${maxAttempts} attempts)` : ''}`}>
            <Icon icon="mdi:sync" width="12" />
            {maxAttempts || '∞'}
          </span>
        )}
        {hasOutputSchema && (
          <span className="badge schema" title="JSON schema validation">
            <Icon icon="mdi:code-braces" width="12" />
          </span>
        )}
      </div>

      {/* Feature Badges - Row 2: Tools & integrations */}
      <div className="phase-node-badges">
        {isDeterministic && (
          <span className="badge deterministic" title={`Direct tool: ${deterministicTool}`}>
            <Icon icon="mdi:function" width="12" />
            {deterministicTool?.split(':').pop()?.split('.').pop() || 'tool'}
          </span>
        )}
        {hasRouting && (
          <span className="badge routing" title="Conditional routing based on output">
            <Icon icon="mdi:source-fork" width="12" />
          </span>
        )}
        {tackleInfo.isManifest && (
          <span className="badge manifest" title="Quartermaster auto-selects tools">
            <Icon icon="mdi:auto-fix" width="12" />
            QM
          </span>
        )}
        {tackleInfo.hasHitl && (
          <span className="badge hitl" title="Human-in-the-loop">
            <Icon icon="mdi:account-question" width="12" />
          </span>
        )}
        {tackleInfo.hasRabbitize && (
          <span className="badge rabbitize" title="Browser automation">
            <Icon icon="mdi:web" width="12" />
          </span>
        )}
        {tackleInfo.hasCode && (
          <span className="badge code" title="Code execution">
            <Icon icon="mdi:console" width="12" />
          </span>
        )}
        {tackleInfo.hasSql && (
          <span className="badge sql" title="SQL/Data access">
            <Icon icon="mdi:database" width="12" />
          </span>
        )}
        {!isDeterministic && tackleCount > 0 && !tackleInfo.isManifest && (
          <span className="badge tackle" title={`${tackleCount} tools`}>
            <Icon icon="mdi:wrench" width="12" />
            {tackleCount}
          </span>
        )}
        {hasHandoffs && handoffCount > 1 && (
          <span className="badge handoffs" title={`${handoffCount} possible handoffs`}>
            <Icon icon="mdi:arrow-decision" width="12" />
            {handoffCount}
          </span>
        )}
        {(hasSubCascades || hasAsyncCascades) && (
          <span className="badge subcascade" title={hasAsyncCascades ? 'Spawns async cascade' : 'Calls sub-cascade'}>
            <Icon icon={hasAsyncCascades ? 'mdi:rocket-launch' : 'mdi:arrow-down-bold-box'} width="12" />
          </span>
        )}
        {hasOnError && (
          <span className="badge onerror" title="Has error recovery path">
            <Icon icon="mdi:lifebuoy" width="12" />
          </span>
        )}
      </div>

      {/* Prompt Snippet (for LLM phases) */}
      {!isDeterministic && instructions && (
        <div className="phase-node-prompt" title={instructions}>
          <Icon icon="mdi:text" width="10" className="prompt-icon" />
          <span className="prompt-text">{instructions.length > 80 ? instructions.slice(0, 80) + '...' : instructions}</span>
        </div>
      )}

      {/* Deterministic Inputs (for tool-only phases) */}
      {isDeterministic && deterministicInputs && (
        <div className="phase-node-deterministic">
          <div className="deterministic-header">
            <Icon icon="mdi:arrow-right-bold" width="10" />
            <span>Inputs</span>
          </div>
          <div className="deterministic-inputs">
            {Object.entries(deterministicInputs).map(([key, value]) => (
              <div key={key} className="input-mapping">
                <span className="input-key">{key}:</span>
                <span className="input-value" title={value}>{
                  typeof value === 'string' && value.length > 30
                    ? value.slice(0, 30) + '...'
                    : String(value)
                }</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Inner Diagram (show when has complexity, expandable for detail) */}
      {hasInnerComplexity && phaseSpec && (
        <PhaseInnerDiagram
          phase={phaseSpec}
          executionData={executionDetails}
          expanded={isExpanded}
        />
      )}

      {/* Execution Output Preview (when executed and has output) */}
      {executed && executionOutput && (
        <div className="phase-node-output">
          <div className="output-header">
            <Icon icon="mdi:text-box-check" width="10" />
            <span>Output</span>
          </div>
          <div className="output-content" title={executionOutput}>
            {executionOutput.length > 150 ? executionOutput.slice(0, 150) + '...' : executionOutput}
          </div>
        </div>
      )}

      {/* Execution Images (thumbnails) */}
      {executed && executionImages && executionImages.length > 0 && (
        <div className="phase-node-images">
          <div className="images-header">
            <Icon icon="mdi:image-multiple" width="10" />
            <span>{executionImages.length} image{executionImages.length > 1 ? 's' : ''}</span>
          </div>
          <div className="images-thumbnails">
            {executionImages.slice(0, 3).map((img, i) => (
              <div key={i} className="image-thumb" title={img}>
                <Icon icon="mdi:image" width="16" />
              </div>
            ))}
            {executionImages.length > 3 && (
              <span className="more-images">+{executionImages.length - 3}</span>
            )}
          </div>
        </div>
      )}

      {/* Execution Stats (if available) */}
      {executed && (
        <div className="phase-node-stats">
          {cost !== undefined && cost > 0 && (
            <span className="stat cost">
              <Icon icon="mdi:currency-usd" width="12" />
              {cost < 0.01 ? cost.toFixed(4) : cost.toFixed(3)}
            </span>
          )}
          {duration !== undefined && duration > 0 && (
            <span className="stat duration">
              <Icon icon="mdi:timer-outline" width="12" />
              {duration.toFixed(1)}s
            </span>
          )}
          {executionTokensIn > 0 && (
            <span className="stat tokens" title={`${executionTokensIn} in / ${executionTokensOut || 0} out`}>
              <Icon icon="mdi:format-letter-case" width="12" />
              {Math.round((executionTokensIn + (executionTokensOut || 0)) / 1000)}k
            </span>
          )}
          {turnCount > 1 && (
            <span className="stat turns">
              <Icon icon="mdi:repeat" width="12" />
              {turnCount}
            </span>
          )}
          {soundingWinner !== undefined && soundingWinner !== null && (
            <span className="stat winner">
              <Icon icon="mdi:trophy" width="12" />
              #{soundingWinner + 1}
            </span>
          )}
        </div>
      )}

      {/* Model Badge - show actual model used if different from configured */}
      {(model || executionModel) && (
        <div className={`phase-node-model ${executionModel && model && executionModel !== model ? 'different' : ''}`}>
          <Icon icon="mdi:brain" width="10" />
          <span title={executionModel || model}>
            {(executionModel || model).split('/').pop()}
          </span>
          {executionModel && model && executionModel !== model && (
            <span className="model-configured" title={`Configured: ${model}`}>
              (was {model.split('/').pop()})
            </span>
          )}
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
function specToFlow(cascade, executionData = null, expandedNodes = {}, onToggleExpand = null) {
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
    const isExpanded = expandedNodes[phase.name] || false;

    // Determine if this is a deterministic (tool-only) phase
    const isDeterministic = phase.is_deterministic || (phase.deterministic_tool && !phase.instructions);

    nodes.push({
      id: phase.name,
      type: 'phase',
      position: { x: 0, y: 0 }, // Will be set by layout
      data: {
        name: phase.name,
        index,
        // Full phase spec for inner diagram
        phaseSpec: phase,
        // Spec data (summary)
        hasSoundings: soundings.factor > 1,
        soundingsFactor: soundings.factor || 1,
        hasReforge: reforge.steps > 0,
        reforgeSteps: reforge.steps || 0,
        hasWards: wardCount > 0,
        wardCount,
        hasHandoffs: phase.handoffs?.length > 0,
        handoffCount: phase.handoffs?.length || 0,
        tackle: phase.tackle,
        tackleCount: Array.isArray(phase.tackle) ? phase.tackle.length : (phase.tackle ? 1 : 0),
        model: phase.model,
        // Rules
        maxTurns: phase.max_turns || 1,
        maxAttempts: phase.max_attempts,
        hasLoopUntil: phase.has_loop_until || !!phase.loop_until,
        hasTurnPrompt: phase.has_turn_prompt,
        // Deterministic phases
        isDeterministic,
        deterministicTool: phase.deterministic_tool || phase.tool,
        deterministicInputs: phase.deterministic_inputs || phase.inputs,
        hasRouting: !!phase.routing,
        // Prompt snippet
        instructions: phase.instructions,
        // Features
        hasOutputSchema: !!phase.output_schema,
        hasSubCascades: !!phase.sub_cascades?.length,
        hasAsyncCascades: !!phase.async_cascades?.length,
        hasOnError: !!phase.on_error,
        // Soundings details
        soundingsMode: soundings.mode,
        hasMultiModel: !!soundings.models?.length,
        hasMutations: soundings.mutate || !!soundings.mutations?.length,
        // Execution data
        executed: !!phaseExecution,
        isOnPath,
        status: phaseExecution?.status,
        cost: phaseExecution?.cost,
        duration: phaseExecution?.duration,
        soundingWinner: phaseExecution?.soundingWinner,
        turnCount: phaseExecution?.turnCount,
        executionDetails: phaseExecution?.details,
        // Rich execution data
        executionOutput: phaseExecution?.output,
        executionImages: phaseExecution?.images || [],
        executionModel: phaseExecution?.model,
        executionTokensIn: phaseExecution?.tokensIn,
        executionTokensOut: phaseExecution?.tokensOut,
        // UI state
        isExpanded,
        onToggleExpand,
      },
    });
  });

  // Helper to format context label for an edge
  const getContextLabel = (targetPhase, sourcePhase) => {
    const context = targetPhase.context;
    // No explicit context config means default snowball (all previous context)
    if (!context) return { label: '← auto', title: 'Default context (snowball)', dim: true };

    const from = context.from;
    if (!from || !Array.isArray(from)) return { label: '← auto', title: 'Default context', dim: true };

    // Check if this edge's source is in the context.from
    // Handle both simple format: ["previous", "phase_name", "all"]
    // And complex format: [{"phase": "name", "include": ["output"]}]
    let isFromAll = false;
    let isFromPrevious = false;
    let isFromSpecific = false;
    let specificInclude = null;

    for (const entry of from) {
      if (typeof entry === 'string') {
        if (entry === 'all') isFromAll = true;
        else if (entry === 'previous') isFromPrevious = true;
        else if (entry === sourcePhase.name) isFromSpecific = true;
      } else if (typeof entry === 'object' && entry.phase) {
        if (entry.phase === sourcePhase.name) {
          isFromSpecific = true;
          specificInclude = entry.include;
        }
      }
    }

    if (!isFromAll && !isFromPrevious && !isFromSpecific) {
      // This source isn't in the target's context - show "no context" indicator
      return { label: '⊘', title: 'No context passed from this phase', dim: true };
    }

    // Determine the include type
    const include = specificInclude || context.include || 'output';
    let includeLabel = '';
    if (include === 'all' || include === 'messages' || (Array.isArray(include) && include.includes('messages'))) {
      includeLabel = ' (full)';
    } else if (include === 'output_with_images' || (Array.isArray(include) && include.includes('images'))) {
      includeLabel = ' (+img)';
    }

    if (isFromAll) {
      return { label: `← all${includeLabel}`, title: 'Context from all phases' };
    } else if (isFromPrevious) {
      return { label: `← prev${includeLabel}`, title: 'Context from previous phase' };
    } else if (isFromSpecific) {
      return { label: `← ctx${includeLabel}`, title: `Selective context from ${sourcePhase.name}` };
    }

    return null;
  };

  // Create a map of phases by name for quick lookup
  const phasesByName = {};
  phases.forEach(p => { phasesByName[p.name] = p; });

  // Create edges
  phases.forEach((phase, index) => {
    if (phase.handoffs && phase.handoffs.length > 0) {
      // Explicit handoffs
      phase.handoffs.forEach((target, hIndex) => {
        const isExecutedEdge = executionData?.executedHandoffs?.[phase.name] === target;
        const targetPhase = phasesByName[target];
        const contextInfo = targetPhase ? getContextLabel(targetPhase, phase) : null;

        edges.push({
          id: `${phase.name}-${target}-${hIndex}`,
          source: phase.name,
          target,
          type: 'smoothstep',
          animated: isExecutedEdge,
          style: {
            stroke: isExecutedEdge ? '#34d399' : (contextInfo?.dim ? '#333' : '#4a5568'),
            strokeWidth: isExecutedEdge ? 2 : 1,
            opacity: isExecutedEdge ? 1 : (contextInfo?.dim ? 0.3 : 0.5),
            strokeDasharray: contextInfo?.dim ? '4 4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isExecutedEdge ? '#34d399' : (contextInfo?.dim ? '#333' : '#4a5568'),
          },
          label: contextInfo?.label,
          labelStyle: {
            fill: contextInfo?.dim ? '#666' : '#aaa',
            fontSize: 10,
            fontWeight: 500,
          },
          labelBgStyle: {
            fill: '#151515',
            fillOpacity: 0.95,
          },
          labelBgPadding: [6, 3],
          labelBgBorderRadius: 4,
        });
      });
    } else if (index < phases.length - 1) {
      // Default: connect to next phase
      const nextPhase = phases[index + 1];
      const isExecutedEdge =
        executionData?.executedPath?.includes(phase.name) &&
        executionData?.executedPath?.includes(nextPhase.name);
      const contextInfo = getContextLabel(nextPhase, phase);

      edges.push({
        id: `${phase.name}-${nextPhase.name}`,
        source: phase.name,
        target: nextPhase.name,
        type: 'smoothstep',
        animated: isExecutedEdge,
        style: {
          stroke: isExecutedEdge ? '#34d399' : (contextInfo?.dim ? '#333' : '#4a5568'),
          strokeWidth: isExecutedEdge ? 2 : 1,
          opacity: isExecutedEdge ? 1 : (contextInfo?.dim ? 0.3 : 0.6),
          strokeDasharray: contextInfo?.dim ? '4 4' : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isExecutedEdge ? '#34d399' : (contextInfo?.dim ? '#333' : '#4a5568'),
        },
        label: contextInfo?.label,
        labelStyle: {
          fill: contextInfo?.dim ? '#666' : '#aaa',
          fontSize: 10,
          fontWeight: 500,
        },
        labelBgStyle: {
          fill: '#151515',
          fillOpacity: 0.95,
        },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 4,
      });
    }
  });

  return getLayoutedElements(nodes, edges);
}

/**
 * Main Modal Component
 */
function CascadeFlowModal({ cascade, executionData, sessionId, onClose }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Initialize expanded nodes - expand all nodes with complexity by default
  const getInitialExpandedState = useCallback((cascade) => {
    const expanded = {};
    (cascade?.phases || []).forEach(phase => {
      const soundings = phase.soundings || {};
      const wards = phase.wards || {};
      const hasComplexity = (soundings.factor > 1) ||
        ((wards.pre?.length || 0) + (wards.post?.length || 0) + (wards.turn?.length || 0) > 0);
      if (hasComplexity) {
        expanded[phase.name] = true;
      }
    });
    return expanded;
  }, []);

  const [expandedNodes, setExpandedNodes] = useState(() => getInitialExpandedState(cascade));

  // Reset expanded state when cascade changes
  useEffect(() => {
    setExpandedNodes(getInitialExpandedState(cascade));
  }, [cascade, getInitialExpandedState]);

  // Toggle node expansion
  const handleToggleExpand = useCallback((nodeName) => {
    setExpandedNodes(prev => ({
      ...prev,
      [nodeName]: !prev[nodeName]
    }));
  }, []);

  // Convert spec to flow on mount or when data/expansion changes
  useEffect(() => {
    if (!cascade) return;

    const { nodes: layoutedNodes, edges: layoutedEdges } = specToFlow(
      cascade,
      executionData,
      expandedNodes,
      handleToggleExpand
    );
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [cascade, executionData, expandedNodes, handleToggleExpand, setNodes, setEdges]);

  const hasExecution = !!executionData;

  // Root-level features
  const hasMemory = !!cascade?.memory;
  const hasToolCaching = !!cascade?.tool_caching;
  const hasTriggers = !!cascade?.triggers?.length;
  const hasCascadeSoundings = !!cascade?.cascade_soundings;

  return (
    <div className="cascade-flow-modal-overlay" onClick={onClose}>
      <div className="cascade-flow-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="header-left">
            <Icon icon="ph:tree-structure" width="20" />
            <h2>{cascade?.cascade_id || 'Cascade Flow'}</h2>
            {sessionId && (
              <span className="session-badge" title={`Session: ${sessionId}`}>
                <Icon icon="mdi:identifier" width="12" />
                {sessionId.length > 20 ? sessionId.slice(0, 20) + '...' : sessionId}
              </span>
            )}
            <span className={`view-badge ${hasExecution ? 'execution' : 'spec'}`}>
              {hasExecution ? 'Execution View' : 'Spec View'}
            </span>
            {/* Root-level feature badges */}
            {hasCascadeSoundings && (
              <span className="feature-badge cascade-soundings" title={`Cascade-level soundings: ${cascade.cascade_soundings.factor}x`}>
                <Icon icon="mdi:source-branch" width="12" />
                {cascade.cascade_soundings.factor}x cascade
              </span>
            )}
            {hasMemory && (
              <span className="feature-badge memory" title={`Memory: ${cascade.memory}`}>
                <Icon icon="mdi:brain" width="12" />
                memory
              </span>
            )}
            {hasToolCaching && (
              <span className="feature-badge caching" title="Tool result caching enabled">
                <Icon icon="mdi:cached" width="12" />
                cache
              </span>
            )}
            {hasTriggers && (
              <span className="feature-badge triggers" title={`${cascade.triggers.length} trigger(s)`}>
                <Icon icon="mdi:clock-outline" width="12" />
                scheduled
              </span>
            )}
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
            <span className={`footer-stat status ${executionData.summary.status || ''}`}>
              <Icon
                icon={
                  executionData.summary.status === 'completed' ? 'mdi:check-circle' :
                  executionData.summary.status === 'running' ? 'mdi:loading' :
                  executionData.summary.status === 'error' ? 'mdi:alert-circle' :
                  'mdi:help-circle'
                }
                width="14"
                className={executionData.summary.status === 'running' ? 'spinning' : ''}
              />
              {executionData.summary.status || 'unknown'}
            </span>
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
