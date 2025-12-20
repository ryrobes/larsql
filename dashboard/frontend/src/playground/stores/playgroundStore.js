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
    lastSuccessfulSessionId: null, // Cached session for "run from here"
    loadedCascadeId: null, // The cascade_id of the loaded cascade (for updates)
    loadedSessionId: null, // The session_id of the loaded cascade (for URL persistence)
    executionStatus: 'idle', // 'idle' | 'running' | 'completed' | 'error'
    executionError: null,
    phaseResults: {}, // nodeId -> { status, images: [], cost, duration }
    totalSessionCost: 0, // Accumulated cost for the current session

    // ============================================
    // UI STATE
    // ============================================
    selectedNodeId: null,
    viewport: { x: 0, y: 0, zoom: 1 },

    // Cascade browser state
    availableCascades: [],
    isLoadingCascades: false,

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
      // Create new nodes array to ensure React Flow detects change
      state.nodes = state.nodes.map(n => {
        if (n.id !== nodeId) return n;
        return {
          ...n,
          data: { ...n.data, ...data },
        };
      });
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

      // Helper to get the phase/input name for a node (custom name or fallback to id)
      const getNodeName = (node) => node.data.name || node.id;

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

      // Build inputs from prompt nodes (using custom names)
      const inputs = {};
      const promptNodes = sortedNodes.filter(n => n.type === 'prompt');
      promptNodes.forEach(node => {
        const inputName = getNodeName(node);
        inputs[inputName] = node.data.text || '';
      });

      // Build phases from image nodes (generators, transformers, tools)
      const phases = [];
      const imageNodes = sortedNodes.filter(n => n.type === 'image');

      imageNodes.forEach(node => {
        const paletteConfig = node.data.paletteConfig;
        if (!paletteConfig) return;

        // Find connected prompt node (via 'text-in' handle or legacy 'prompt'/'input' handles)
        const promptEdge = edges.find(e =>
          e.target === node.id &&
          (e.targetHandle === 'text-in' || e.targetHandle === 'prompt' || e.targetHandle === 'input' || !e.targetHandle)
        );
        const promptNode = promptEdge ? nodeMap.get(promptEdge.source) : null;
        const promptRef = promptNode?.type === 'prompt'
          ? `{{ input.${getNodeName(promptNode)} }}`
          : '';

        // Find connected image input (via 'image-in' handle or legacy 'image' handle)
        const imageEdge = edges.find(e =>
          e.target === node.id && (e.targetHandle === 'image-in' || e.targetHandle === 'image')
        );
        const sourceImageNode = imageEdge ? nodeMap.get(imageEdge.source) : null;
        const hasImageInput = sourceImageNode?.type === 'image';

        if (paletteConfig.openrouter) {
          // OpenRouter image model - use model-based phase (same as LLM phases)
          // Runner detects image models and routes to _execute_image_generation_phase()
          // which uses normal Agent.run() with modalities=["text", "image"]
          const phase = {
            name: getNodeName(node),
            model: paletteConfig.openrouter.model,
            instructions: promptRef || 'Generate a beautiful image',
            image_config: {
              width: 1024,
              height: 1024,
            },
          };

          // If there's an image input, add context.from to inject that image
          if (hasImageInput) {
            phase.context = {
              from: [getNodeName(sourceImageNode)],
            };
          }

          phases.push(phase);
        } else if (paletteConfig.harbor) {
          // Harbor tool (HuggingFace Space) - deterministic phase
          // For harbor tools, use the image handle connection
          const inputImageEdge = imageEdge || edges.find(e => e.target === node.id);
          const inputSourceNode = inputImageEdge ? nodeMap.get(inputImageEdge.source) : null;
          const imageRef = inputSourceNode?.type === 'image'
            ? `{{ state.output_${getNodeName(inputSourceNode)}.images[0] }}`
            : '';

          phases.push({
            name: getNodeName(node),
            tool: paletteConfig.harbor.tool,
            tool_inputs: {
              input_image: imageRef,
              // Use defaults for other params
            },
          });
        } else if (paletteConfig.local) {
          // Local tool - deterministic phase
          phases.push({
            name: getNodeName(node),
            tool: paletteConfig.local.tool,
            tool_inputs: {
              // Tool-specific inputs would go here
            },
          });
        }
      });

      // Build cascade object - reuse loaded cascade_id if available
      const cascade = {
        cascade_id: state.loadedCascadeId || `playground_${Date.now().toString(36)}`,
        description: 'Generated from Image Playground',
        inputs_schema: Object.fromEntries(
          promptNodes.map(n => [getNodeName(n), `Prompt text for ${getNodeName(n)}`])
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
              name: n.data.name, // Persist custom names
              width: n.data.width,
              height: n.data.height,
            },
          })),
          edges: edges.map(e => ({
            source: e.source,
            target: e.target,
            sourceHandle: e.sourceHandle,
            targetHandle: e.targetHandle,
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
        state.totalSessionCost = 0; // Reset cost for new run
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

    // Run cascade starting from a specific node (uses cached images for upstream)
    runFromNode: async (nodeId) => {
      const state = get();
      const { yaml: cascadeYaml, inputs } = state.generateCascade();

      if (!cascadeYaml) {
        return { success: false, error: 'Failed to generate cascade' };
      }

      if (!state.lastSuccessfulSessionId) {
        return { success: false, error: 'No cached session - run full cascade first' };
      }

      // Get the phase name for this node (custom name or id)
      const targetNode = state.nodes.find(n => n.id === nodeId);
      const phaseName = targetNode?.data?.name || nodeId;

      // Set target node to 'pending', keep upstream nodes completed, clear downstream
      const nodeOrder = state.nodes
        .filter(n => n.type === 'image')
        .map(n => n.id);
      const targetIdx = nodeOrder.indexOf(nodeId);

      set((state) => {
        state.nodes.forEach(node => {
          if (node.type === 'image') {
            const nodeIdx = nodeOrder.indexOf(node.id);
            if (nodeIdx < targetIdx) {
              // Upstream: keep as completed with cached images
              node.data.status = 'completed';
            } else if (nodeIdx === targetIdx) {
              // Target: mark as pending
              node.data.status = 'pending';
              node.data.images = [];
            } else {
              // Downstream: mark as pending
              node.data.status = 'pending';
              node.data.images = [];
            }
          }
        });
        state.executionStatus = 'running';
        state.executionError = null;
        state.totalSessionCost = 0; // Reset cost for new run
      });

      try {
        const response = await fetch('http://localhost:5001/api/playground/run-from', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phase_name: phaseName, // Use phase name (custom name or id) to match cascade phases
            cached_session_id: state.lastSuccessfulSessionId,
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

        return { success: true, sessionId: data.session_id, startingFrom: nodeId };

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
      console.log('[Store] handlePhaseComplete:', phaseName, 'images:', result.images);

      // Find node by custom name OR by id (for backwards compatibility)
      const nodeIndex = state.nodes.findIndex(n =>
        n.data.name === phaseName || n.id === phaseName
      );
      if (nodeIndex !== -1) {
        const node = state.nodes[nodeIndex];
        // Only update images if this result has them (avoid overwriting with empty)
        const newImages = result.images && result.images.length > 0 ? result.images : node.data.images;

        console.log('[Store] Found node:', node.id, 'current images:', node.data.images, 'new images:', newImages);

        // Create a completely new nodes array to ensure React Flow detects the change
        // Note: runner sends duration_ms, not duration
        state.nodes = state.nodes.map((n, i) => {
          if (i !== nodeIndex) return n;
          return {
            ...n,
            data: {
              ...n.data,
              status: 'completed',
              images: newImages,
              cost: result.cost || n.data.cost,
              duration: result.duration_ms || result.duration || n.data.duration,
            },
          };
        });

        console.log('[Store] After update, node images:', state.nodes[nodeIndex].data.images);
      } else {
        console.log('[Store] Node not found for phase:', phaseName, 'available nodes:', state.nodes.map(n => n.id));
      }

      state.phaseResults[phaseName] = result;

      // Accumulate session cost
      if (result.cost && typeof result.cost === 'number') {
        state.totalSessionCost += result.cost;
      }
    }),

    // Handle cascade completion
    handleCascadeComplete: () => set((state) => {
      state.executionStatus = 'completed';
      // Cache session ID for "run from here" feature
      if (state.sessionId) {
        state.lastSuccessfulSessionId = state.sessionId;
      }
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
    resetPlayground: () => {
      set((state) => {
        state.nodes = [];
        state.edges = [];
        state.sessionId = null;
        state.lastSuccessfulSessionId = null;
        state.loadedCascadeId = null;
        state.loadedSessionId = null;
        state.executionStatus = 'idle';
        state.executionError = null;
        state.phaseResults = {};
        state.selectedNodeId = null;
        state.totalSessionCost = 0;
        nodeIdCounter = 0;
      });
      // Clear URL hash
      window.location.hash = '/playground';
    },

    // ============================================
    // CASCADE BROWSER
    // ============================================

    // Load cascade from URL hash if present (e.g., #/playground/workshop_abc123)
    loadFromUrl: async () => {
      const hash = window.location.hash;
      const match = hash.match(/^#\/playground\/(.+)$/);
      if (match) {
        const sessionId = match[1];
        console.log('[Store] Loading cascade from URL:', sessionId);
        return await get().loadCascade(sessionId);
      }
      return { success: false, error: 'No cascade in URL' };
    },

    // Fetch list of available playground cascades
    fetchCascadeList: async () => {
      set((state) => {
        state.isLoadingCascades = true;
      });

      try {
        const response = await fetch('http://localhost:5001/api/playground/list');
        const cascades = await response.json();

        set((state) => {
          state.availableCascades = cascades;
          state.isLoadingCascades = false;
        });

        return cascades;
      } catch (err) {
        console.error('[Store] Failed to fetch cascade list:', err);
        set((state) => {
          state.isLoadingCascades = false;
        });
        return [];
      }
    },

    // Load a cascade by session ID and restore the graph
    loadCascade: async (sessionId) => {
      try {
        const response = await fetch(`http://localhost:5001/api/playground/load/${sessionId}`);
        const config = await response.json();

        if (config.error) {
          console.error('[Store] Failed to load cascade:', config.error);
          return { success: false, error: config.error };
        }

        const playground = config._playground;
        if (!playground) {
          console.error('[Store] Cascade has no _playground metadata');
          return { success: false, error: 'No playground metadata found' };
        }

        const palette = get().palette;

        // Restore nodes with full palette config
        const restoredNodes = playground.nodes.map(n => {
          const paletteItem = n.data?.paletteId
            ? palette.find(p => p.id === n.data.paletteId)
            : null;

          // Update nodeIdCounter to prevent ID collisions
          const idNum = parseInt(n.id.split('_').pop());
          if (!isNaN(idNum) && idNum >= nodeIdCounter) {
            nodeIdCounter = idNum + 1;
          }

          if (n.type === 'prompt') {
            return {
              id: n.id,
              type: 'prompt',
              position: n.position,
              data: {
                text: n.data?.text || '',
                name: n.data?.name, // Restore custom name
                width: n.data?.width,
                height: n.data?.height,
              },
            };
          } else {
            return {
              id: n.id,
              type: n.type,
              position: n.position,
              data: {
                paletteId: n.data?.paletteId,
                paletteName: paletteItem?.name || n.data?.paletteId,
                paletteIcon: paletteItem?.icon || 'mdi:image',
                paletteColor: paletteItem?.color || '#8b5cf6',
                paletteConfig: paletteItem,
                status: 'idle',
                images: [],
                prompt: '',
                name: n.data?.name, // Restore custom name
                width: n.data?.width,
                height: n.data?.height,
              },
            };
          }
        });

        // Restore edges with handle ID migration
        const restoredEdges = (playground.edges || []).map(e => {
          // Migrate old handle IDs to new typed IDs
          let sourceHandle = e.sourceHandle;
          let targetHandle = e.targetHandle;

          // Migrate source handles
          if (sourceHandle === 'output') {
            // Determine type based on source node
            const sourceNode = restoredNodes.find(n => n.id === e.source);
            sourceHandle = sourceNode?.type === 'prompt' ? 'text-out' : 'image-out';
          }

          // Migrate target handles
          if (targetHandle === 'prompt' || targetHandle === 'input') {
            targetHandle = 'text-in';
          } else if (targetHandle === 'image') {
            targetHandle = 'image-in';
          }

          return {
            id: `${e.source}-${e.target}`,
            source: e.source,
            target: e.target,
            sourceHandle,
            targetHandle,
            animated: true,
          };
        });

        set((state) => {
          state.nodes = restoredNodes;
          state.edges = restoredEdges;
          state.sessionId = sessionId;
          state.lastSuccessfulSessionId = sessionId;
          state.loadedCascadeId = config.cascade_id; // Track for updates
          state.loadedSessionId = sessionId; // Track for URL
          state.executionStatus = 'idle';
          state.executionError = null;
          state.phaseResults = {};
          state.selectedNodeId = null;
          if (playground.viewport) {
            state.viewport = playground.viewport;
          }
        });

        // Update URL hash for persistence
        window.location.hash = `/playground/${sessionId}`;

        return { success: true, cascade: config };
      } catch (err) {
        console.error('[Store] Failed to load cascade:', err);
        return { success: false, error: err.message };
      }
    },

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
