import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import yaml from 'js-yaml';
import paletteConfig from '../palette/palette.json';

/**
 * Playground Store - Manages React Flow graph state and execution
 *
 * Stores the visual graph (nodes/edges) and generates cascade YAML for execution.
 */

// Generate unique IDs
let nodeIdCounter = 0;
const generateNodeId = (type) => `${type}_${++nodeIdCounter}`;

const usePlaygroundStore = create(
  immer((set, get) => ({
    // ============================================
    // REACT FLOW STATE
    // ============================================
    nodes: [],
    edges: [],

    // Palette configuration
    palette: paletteConfig.palette || [],

    // ============================================
    // EXECUTION STATE
    // ============================================
    sessionId: null,
    executionStatus: 'idle', // 'idle' | 'running' | 'completed' | 'error'
    executionError: null,
    phaseResults: {}, // nodeId -> { status, images: [], cost, duration }

    // ============================================
    // UI STATE
    // ============================================
    selectedNodeId: null,
    viewport: { x: 0, y: 0, zoom: 1 },

    // ============================================
    // NODE OPERATIONS
    // ============================================

    // Add a node from palette
    addNode: (paletteId, position) => set((state) => {
      const paletteItem = state.palette.find(p => p.id === paletteId);
      if (!paletteItem) return;

      const nodeType = paletteItem.category === 'generator' || paletteItem.category === 'transformer' || paletteItem.category === 'tool'
        ? 'image'
        : paletteItem.category === 'utility' && paletteItem.id === 'compose'
        ? 'compose'
        : 'image';

      const nodeId = generateNodeId(nodeType);

      const newNode = {
        id: nodeId,
        type: nodeType,
        position,
        data: {
          paletteId,
          paletteName: paletteItem.name,
          paletteIcon: paletteItem.icon,
          paletteColor: paletteItem.color,
          paletteConfig: paletteItem,
          status: 'idle', // 'idle' | 'running' | 'completed' | 'error'
          images: [],
          prompt: '', // For storing connected prompt text
        },
      };

      state.nodes.push(newNode);
      state.selectedNodeId = nodeId;
    }),

    // Add a prompt node
    addPromptNode: (position) => set((state) => {
      const nodeId = generateNodeId('prompt');

      const newNode = {
        id: nodeId,
        type: 'prompt',
        position,
        data: {
          text: '',
        },
      };

      state.nodes.push(newNode);
      state.selectedNodeId = nodeId;
    }),

    // Remove a node
    removeNode: (nodeId) => set((state) => {
      state.nodes = state.nodes.filter(n => n.id !== nodeId);
      // Also remove connected edges
      state.edges = state.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
      if (state.selectedNodeId === nodeId) {
        state.selectedNodeId = null;
      }
    }),

    // Update node data
    updateNodeData: (nodeId, data) => set((state) => {
      const node = state.nodes.find(n => n.id === nodeId);
      if (node) {
        node.data = { ...node.data, ...data };
      }
    }),

    // Update node position
    updateNodePosition: (nodeId, position) => set((state) => {
      const node = state.nodes.find(n => n.id === nodeId);
      if (node) {
        node.position = position;
      }
    }),

    // Set nodes (from React Flow)
    setNodes: (nodes) => set((state) => {
      state.nodes = nodes;
    }),

    // ============================================
    // EDGE OPERATIONS
    // ============================================

    // Add an edge
    addEdge: (edge) => set((state) => {
      // Check for duplicates
      const exists = state.edges.some(
        e => e.source === edge.source && e.target === edge.target
      );
      if (!exists) {
        state.edges.push({
          id: `${edge.source}-${edge.target}`,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          animated: true,
        });
      }
    }),

    // Remove an edge
    removeEdge: (edgeId) => set((state) => {
      state.edges = state.edges.filter(e => e.id !== edgeId);
    }),

    // Set edges (from React Flow)
    setEdges: (edges) => set((state) => {
      state.edges = edges;
    }),

    // ============================================
    // CASCADE GENERATION
    // ============================================

    // Generate cascade YAML from the graph
    generateCascade: () => {
      const state = get();
      const { nodes, edges } = state;

      // Build dependency graph and topological sort
      const nodeMap = new Map(nodes.map(n => [n.id, n]));
      const inDegree = new Map(nodes.map(n => [n.id, 0]));
      const adjacency = new Map(nodes.map(n => [n.id, []]));

      edges.forEach(edge => {
        adjacency.get(edge.source)?.push(edge.target);
        inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
      });

      // Kahn's algorithm for topological sort
      const queue = [...nodes.filter(n => (inDegree.get(n.id) || 0) === 0)];
      const sortedNodes = [];

      while (queue.length > 0) {
        const node = queue.shift();
        sortedNodes.push(node);

        adjacency.get(node.id)?.forEach(targetId => {
          inDegree.set(targetId, (inDegree.get(targetId) || 0) - 1);
          if (inDegree.get(targetId) === 0) {
            const targetNode = nodeMap.get(targetId);
            if (targetNode) queue.push(targetNode);
          }
        });
      }

      // Build inputs from prompt nodes
      const inputs = {};
      const promptNodes = sortedNodes.filter(n => n.type === 'prompt');
      promptNodes.forEach(node => {
        inputs[node.id] = node.data.text || '';
      });

      // Build phases from image nodes (generators, transformers, tools)
      const phases = [];
      const imageNodes = sortedNodes.filter(n => n.type === 'image');

      imageNodes.forEach(node => {
        const paletteConfig = node.data.paletteConfig;
        if (!paletteConfig) return;

        // Find connected prompt node
        const promptEdge = edges.find(e => e.target === node.id);
        const promptNode = promptEdge ? nodeMap.get(promptEdge.source) : null;
        const promptRef = promptNode?.type === 'prompt'
          ? `{{ input.${promptNode.id} }}`
          : '';

        if (paletteConfig.openrouter) {
          // OpenRouter image model - use model-based phase (same as LLM phases)
          // Runner detects image models (FLUX, SDXL) and routes to Agent.generate_image()
          phases.push({
            name: node.id,
            model: paletteConfig.openrouter.model,
            instructions: promptRef || 'Generate a beautiful image',
            image_config: {
              width: 1024,
              height: 1024,
            },
          });
        } else if (paletteConfig.harbor) {
          // Harbor tool (HuggingFace Space) - deterministic phase
          // Find connected image node for input
          const imageEdge = edges.find(e => e.target === node.id);
          const sourceNode = imageEdge ? nodeMap.get(imageEdge.source) : null;
          const imageRef = sourceNode?.type === 'image'
            ? `{{ state.output_${sourceNode.id}.images[0] }}`
            : '';

          phases.push({
            name: node.id,
            tool: paletteConfig.harbor.tool,
            tool_inputs: {
              input_image: imageRef,
              // Use defaults for other params
            },
          });
        } else if (paletteConfig.local) {
          // Local tool - deterministic phase
          phases.push({
            name: node.id,
            tool: paletteConfig.local.tool,
            tool_inputs: {
              // Tool-specific inputs would go here
            },
          });
        }
      });

      // Build cascade object
      const cascade = {
        cascade_id: `playground_${Date.now().toString(36)}`,
        description: 'Generated from Image Playground',
        inputs_schema: Object.fromEntries(
          promptNodes.map(n => [n.id, `Prompt text for ${n.id}`])
        ),
        phases,

        // Embed playground state for UI persistence
        _playground: {
          version: 1,
          viewport: state.viewport,
          nodes: nodes.map(n => ({
            id: n.id,
            type: n.type,
            position: n.position,
            data: {
              paletteId: n.data.paletteId,
              text: n.data.text,
            },
          })),
          edges: edges.map(e => ({
            source: e.source,
            target: e.target,
          })),
        },
      };

      return {
        yaml: yaml.dump(cascade, { lineWidth: -1 }),
        inputs,
      };
    },

    // ============================================
    // EXECUTION
    // ============================================

    // Run the cascade
    runCascade: async () => {
      const state = get();
      const { yaml: cascadeYaml, inputs } = state.generateCascade();

      if (!cascadeYaml) {
        return { success: false, error: 'Failed to generate cascade' };
      }

      // Set all image nodes to 'pending' status
      set((state) => {
        state.nodes.forEach(node => {
          if (node.type === 'image') {
            node.data.status = 'pending';
            node.data.images = [];
          }
        });
        state.executionStatus = 'running';
        state.executionError = null;
      });

      try {
        const response = await fetch('http://localhost:5001/api/run-cascade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cascade_yaml: cascadeYaml,
            inputs,
          }),
        });

        const data = await response.json();

        if (data.error) {
          set((state) => {
            state.executionStatus = 'error';
            state.executionError = data.error;
          });
          return { success: false, error: data.error };
        }

        set((state) => {
          state.sessionId = data.session_id;
        });

        return { success: true, sessionId: data.session_id };

      } catch (err) {
        set((state) => {
          state.executionStatus = 'error';
          state.executionError = err.message;
        });
        return { success: false, error: err.message };
      }
    },

    // Handle phase completion from SSE
    handlePhaseComplete: (phaseName, result) => set((state) => {
      const node = state.nodes.find(n => n.id === phaseName);
      if (node) {
        node.data.status = 'completed';
        node.data.images = result.images || [];
        node.data.cost = result.cost;
        node.data.duration = result.duration;
      }

      state.phaseResults[phaseName] = result;
    }),

    // Handle cascade completion
    handleCascadeComplete: () => set((state) => {
      state.executionStatus = 'completed';
    }),

    // Handle cascade error
    handleCascadeError: (error) => set((state) => {
      state.executionStatus = 'error';
      state.executionError = error;
    }),

    // Clear execution state
    clearExecution: () => set((state) => {
      state.sessionId = null;
      state.executionStatus = 'idle';
      state.executionError = null;
      state.phaseResults = {};
      state.nodes.forEach(node => {
        if (node.type === 'image') {
          node.data.status = 'idle';
          node.data.images = [];
        }
      });
    }),

    // Reset the entire playground
    resetPlayground: () => set((state) => {
      state.nodes = [];
      state.edges = [];
      state.sessionId = null;
      state.executionStatus = 'idle';
      state.executionError = null;
      state.phaseResults = {};
      state.selectedNodeId = null;
      nodeIdCounter = 0;
    }),

    // ============================================
    // SELECTION
    // ============================================

    setSelectedNodeId: (nodeId) => set((state) => {
      state.selectedNodeId = nodeId;
    }),

    // ============================================
    // VIEWPORT
    // ============================================

    setViewport: (viewport) => set((state) => {
      state.viewport = viewport;
    }),
  }))
);

export default usePlaygroundStore;
