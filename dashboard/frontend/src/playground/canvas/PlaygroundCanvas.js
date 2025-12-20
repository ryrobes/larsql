import React, { useCallback, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow,
} from 'reactflow';
import usePlaygroundStore from '../stores/playgroundStore';
import PromptNode from './nodes/PromptNode';
import ImageNode from './nodes/ImageNode';
import 'reactflow/dist/style.css';
import './PlaygroundCanvas.css';

// Register custom node types
const nodeTypes = {
  prompt: PromptNode,
  image: ImageNode,
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
  } = usePlaygroundStore();

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

  // Handle new connections
  const onConnect = useCallback((params) => {
    storeAddEdge(params);
  }, [storeAddEdge]);

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

    const { paletteId, type } = JSON.parse(data);

    // Get position relative to the canvas
    const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
    if (!reactFlowBounds) return;

    const position = project({
      x: event.clientX - reactFlowBounds.left,
      y: event.clientY - reactFlowBounds.top,
    });

    // Add the node
    if (type === 'prompt') {
      addPromptNode(position);
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

  return (
    <div
      ref={reactFlowWrapper}
      className="playground-canvas-wrapper"
      onKeyDown={onKeyDown}
      tabIndex={0}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        defaultEdgeOptions={{
          animated: true,
          style: { stroke: 'var(--ocean-primary)', strokeWidth: 2 },
        }}
      >
        <Background
          variant="dots"
          gap={16}
          size={1}
          color="var(--border-default)"
        />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            if (node.type === 'prompt') return '#10b981';
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
            <span role="img" aria-label="palette">🎨</span>
          </div>
          <h3>Start Building</h3>
          <p>Drag nodes from the palette to create your image workflow</p>
        </div>
      )}
    </div>
  );
}

export default PlaygroundCanvas;
