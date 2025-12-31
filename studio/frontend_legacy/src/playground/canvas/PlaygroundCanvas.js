import React, { useCallback, useRef, useMemo, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow,
} from 'reactflow';
import usePlaygroundStore from '../stores/playgroundStore';
import { useSessionStream } from '../execution/useSessionStream';
import PromptNode from './nodes/PromptNode';
import ImageNode from './nodes/ImageNode';
import CellCard from './nodes/CellCard';
import 'reactflow/dist/style.css';
import './PlaygroundCanvas.css';

// Register custom node types
// CellCard replaces CellNode - all cells are now two-sided cards
const nodeTypes = {
  prompt: PromptNode,
  image: ImageNode,
  cell: CellCard,  // Two-sided card with flip animation, stacked deck for soundings
  card: CellCard,   // Alias for backwards compatibility
};

/**
 * PlaygroundCanvas - React Flow canvas for building image workflows
 *
 * Supports:
 * - Drag-and-drop from palette
 * - Node connections
 * - Node selection and deletion
 */
function PlaygroundCanvas() {
  const reactFlowWrapper = useRef(null);
  const { project } = useReactFlow();

  const {
    nodes,
    edges,
    addNode,
    addPromptNode,
    addEdge: storeAddEdge,
    removeNode,
    updateNodePosition,
    setSelectedNodeId,
    sessionId,
    setSessionStreamStates,
  } = usePlaygroundStore();

  // Use session stream polling for real-time execution state
  const { cellStates, isPolling } = useSessionStream(sessionId);

  // Update store with derived cell states
  useEffect(() => {
    if (cellStates && Object.keys(cellStates).length > 0) {
      setSessionStreamStates(cellStates);
    }
  }, [cellStates, setSessionStreamStates]);

  // Handle node changes from React Flow
  const onNodesChange = useCallback((changes) => {
    changes.forEach(change => {
      if (change.type === 'remove') {
        removeNode(change.id);
      } else if (change.type === 'position' && change.position) {
        updateNodePosition(change.id, change.position);
      } else if (change.type === 'select') {
        if (change.selected) {
          setSelectedNodeId(change.id);
        }
      }
    });
  }, [removeNode, updateNodePosition, setSelectedNodeId]);

  // Handle edge changes from React Flow
  const onEdgesChange = useCallback((changes) => {
    changes.forEach(change => {
      if (change.type === 'remove') {
        // Handle in store if needed
      }
    });
  }, []);

  // Validate connection types (text → text-in, image → image-in)
  const isValidConnection = useCallback((connection) => {
    const { sourceHandle, targetHandle } = connection;

    // Extract types from handle IDs
    // Source handles: 'text-out', 'image-out'
    // Target handles: 'text-in', 'image-in', 'text-in-prompt', 'text-in-style', etc.
    const sourceType = sourceHandle?.split('-')[0]; // 'text' or 'image'

    // For target handles, extract type: 'text-in' → 'text', 'text-in-prompt' → 'text'
    const targetParts = targetHandle?.split('-');
    const targetType = targetParts?.[0]; // 'text' or 'image'

    // Only allow matching types
    if (sourceType && targetType) {
      return sourceType === targetType;
    }

    // Fallback: allow if we can't determine types
    return true;
  }, []);

  // Handle new connections
  const onConnect = useCallback((params) => {
    if (isValidConnection(params)) {
      storeAddEdge(params);
    }
  }, [storeAddEdge, isValidConnection]);

  // Handle drag over for drop zone
  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop from palette
  const onDrop = useCallback((event) => {
    event.preventDefault();

    const data = event.dataTransfer.getData('application/playground-node');
    if (!data) return;

    const { paletteId, type, nodeType } = JSON.parse(data);

    // Get position relative to the canvas
    const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
    if (!reactFlowBounds) return;

    const position = project({
      x: event.clientX - reactFlowBounds.left,
      y: event.clientY - reactFlowBounds.top,
    });

    // Add the node based on type
    if (type === 'prompt') {
      addPromptNode(position);
    } else if (nodeType === 'cell') {
      // Cell node - use addCellNode from store
      usePlaygroundStore.getState().addCellNode(position);
    } else if (nodeType === 'card') {
      // Card node - new two-sided card with flip animation
      usePlaygroundStore.getState().addCardNode(position);
    } else {
      addNode(paletteId, position);
    }
  }, [project, addNode, addPromptNode]);

  // Handle keyboard events
  const onKeyDown = useCallback((event) => {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      const selectedNode = nodes.find(n => n.selected);
      if (selectedNode) {
        removeNode(selectedNode.id);
      }
    }
  }, [nodes, removeNode]);

  // Compute edges with dynamic animation based on node running status
  // An edge animates when its source or target node is running
  const animatedEdges = useMemo(() => {
    const nodeStatusMap = new Map(
      nodes.map(n => [n.id, n.data?.status])
    );

    return edges.map(edge => ({
      ...edge,
      animated: nodeStatusMap.get(edge.source) === 'running' ||
                nodeStatusMap.get(edge.target) === 'running',
    }));
  }, [nodes, edges]);

  return (
    <div
      ref={reactFlowWrapper}
      className="playground-canvas-wrapper"
      onKeyDown={onKeyDown}
      tabIndex={0}
    >
      <ReactFlow
        nodes={nodes}
        edges={animatedEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        isValidConnection={isValidConnection}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        deleteKeyCode={['Backspace', 'Delete']}
        defaultEdgeOptions={{
          style: { stroke: 'var(--ocean-primary)', strokeWidth: 2 },
        }}
      >
        <Background
          variant="lines"
          gap={16}
          color="rgba(255, 255, 255, 0.08)"
        />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            if (node.type === 'prompt') return '#10b981';
            if (node.type === 'cell') return '#06b6d4';
            if (node.type === 'card') return '#8B5CF6';  // Purple for card nodes
            if (node.data?.paletteColor) return node.data.paletteColor;
            return 'var(--ocean-primary)';
          }}
          maskColor="rgba(0, 0, 0, 0.8)"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-default)',
          }}
        />
      </ReactFlow>

      {/* Empty state */}
      {nodes.length === 0 && (
        <div className="canvas-empty-state">
          <div className="empty-state-icon">
          </div>
          <h3>Start Building</h3>
          <p>Drag nodes from the palette to create your image workflow</p>
        </div>
      )}
    </div>
  );
}

export default PlaygroundCanvas;
