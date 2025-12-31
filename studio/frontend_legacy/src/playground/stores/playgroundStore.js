import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import yaml from 'js-yaml';
import paletteConfig from '../palette/palette.json';

/**
 * Playground Store - Manages React Flow graph state and execution
 *
 * Stores the visual graph (nodes/edges) and generates cascade YAML for execution.
 */

// ============================================
// NAMING UTILITIES
// ============================================

/**
 * Convert any string to a safe cell name (lowercase, underscores, alphanumeric)
 * Examples:
 *   "FLUX.1 Schnell" -> "flux_1_schnell"
 *   "google/gemini-2.5-flash" -> "gemini_2_5_flash"
 *   "My Prompt" -> "my_prompt"
 */
const toSafeName = (name) => {
  if (!name) return 'unnamed';

  // Extract just the model name if it's a path like "google/gemini-2.5-flash"
  const baseName = name.includes('/') ? name.split('/').pop() : name;

  return baseName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')  // Replace non-alphanumeric with underscores
    .replace(/^_+|_+$/g, '')       // Trim leading/trailing underscores
    .replace(/_+/g, '_')           // Collapse multiple underscores
    || 'unnamed';
};

/**
 * Generate a unique name by appending _1, _2, etc. if needed
 * @param {string} baseName - The base name to use
 * @param {Set<string>} existingNames - Set of names already in use
 * @returns {string} A unique name
 */
const generateUniqueName = (baseName, existingNames) => {
  const safeName = toSafeName(baseName);

  if (!existingNames.has(safeName)) {
    return safeName;
  }

  // Find the next available number
  let counter = 1;
  while (existingNames.has(`${safeName}_${counter}`)) {
    counter++;
  }
  return `${safeName}_${counter}`;
};

/**
 * Get all node names currently in use
 * @param {Array} nodes - Current nodes array
 * @returns {Set<string>} Set of names in use
 */
const getExistingNames = (nodes) => {
  const names = new Set();
  nodes.forEach(node => {
    // Use custom name if set, otherwise use node id
    const name = node.data?.name || node.id;
    names.add(name);
  });
  return names;
};

// Generate unique IDs (internal, not the display name)
let nodeIdCounter = 0;
const generateNodeId = (type) => `${type}_${++nodeIdCounter}`;

const usePlaygroundStore = create(
  immer((set, get) => ({
    // ============================================
    // REACT FLOW STATE
    // ============================================
    nodes: [],
    edges: [],

    // Palette configuration - initially from static config, updated dynamically
    palette: paletteConfig.palette || [],
    paletteLoading: false,
    paletteError: null,

    // ============================================
    // EXECUTION STATE
    // ============================================
    sessionId: null,
    lastSuccessfulSessionId: null, // Cached session for "run from here"
    loadedCascadeId: null, // The cascade_id of the loaded cascade (for updates)
    loadedSessionId: null, // The session_id of the loaded cascade (for URL persistence)
    executionStatus: 'idle', // 'idle' | 'running' | 'completed' | 'error'
    executionError: null,
    cellResults: {}, // nodeId -> { status, images: [], cost, duration }
    totalSessionCost: 0, // Accumulated cost for the current session
    costPollingTimer: null, // Timer ID for cost polling
    costPollingStopTime: null, // When to stop polling after completion

    // Session stream state (derived from unified_logs polling)
    // cellName -> { status, soundingsProgress, winnerIndex, soundingsOutputs, output, cost, ... }
    sessionStreamStates: {},

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

    // Add a node from palette (image generators, transformers, tools)
    addNode: (paletteId, position) => set((state) => {
      const paletteItem = state.palette.find(p => p.id === paletteId);
      if (!paletteItem) return;

      const nodeType = paletteItem.category === 'generator' || paletteItem.category === 'transformer' || paletteItem.category === 'tool'
        ? 'image'
        : paletteItem.category === 'utility' && paletteItem.id === 'compose'
        ? 'compose'
        : 'image';

      const nodeId = generateNodeId(nodeType);

      // Derive base name from model/tool config
      let baseName = paletteItem.name;
      if (paletteItem.openrouter?.model) {
        // Extract model name from "provider/model-name"
        baseName = paletteItem.openrouter.model;
      } else if (paletteItem.harbor?.tool) {
        baseName = paletteItem.harbor.tool;
      } else if (paletteItem.local?.tool) {
        baseName = paletteItem.local.tool;
      }

      // Generate unique name
      const existingNames = getExistingNames(state.nodes);
      const uniqueName = generateUniqueName(baseName, existingNames);

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
          name: uniqueName, // Auto-assigned unique name
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

      // Generate unique name
      const existingNames = getExistingNames(state.nodes);
      const uniqueName = generateUniqueName('prompt', existingNames);

      const newNode = {
        id: nodeId,
        type: 'prompt',
        position,
        data: {
          name: uniqueName, // Auto-assigned unique name
          text: '',
        },
      };

      state.nodes.push(newNode);
      state.selectedNodeId = nodeId;
    }),

    // Add a cell node (LLM Cell with YAML editor)
    addCellNode: (position) => set((state) => {
      const nodeId = generateNodeId('cell');

      // Generate unique name
      const existingNames = getExistingNames(state.nodes);
      const uniqueName = generateUniqueName('llm_cell', existingNames);

      const defaultYaml = `name: ${uniqueName}
instructions: |
  {{ input.prompt }}
model: google/gemini-2.5-flash-lite
rules:
  max_turns: 1
`;

      const newNode = {
        id: nodeId,
        type: 'cell',
        position,
        data: {
          name: uniqueName, // Auto-assigned unique name
          yaml: defaultYaml,
          discoveredInputs: ['prompt'], // Default input from template
          status: 'idle',
          output: '',
        },
      };

      state.nodes.push(newNode);
      state.selectedNodeId = nodeId;
    }),

    // Add a card node (Two-sided CellCard with flip animation)
    addCardNode: (position) => set((state) => {
      const nodeId = generateNodeId('card');

      // Generate unique name
      const existingNames = getExistingNames(state.nodes);
      const uniqueName = generateUniqueName('llm_cell', existingNames);

      const defaultYaml = `name: ${uniqueName}
instructions: |
  {{ input.prompt }}
model: google/gemini-2.5-flash-lite
rules:
  max_turns: 1
`;

      const newNode = {
        id: nodeId,
        type: 'card',  // Uses CellCard component
        position,
        data: {
          name: uniqueName,
          yaml: defaultYaml,
          discoveredInputs: ['prompt'],
          status: 'idle',
          output: '',
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
        const newEdge = {
          id: `${edge.source}-${edge.target}`,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          // animated is computed dynamically in PlaygroundCanvas based on node running status
        };
        state.edges.push(newEdge);
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

      // Helper to get the cell/input name for a node (custom name or fallback to id)
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

      // Build cells from all execution nodes (cell nodes, then image nodes)
      const cells = [];

      // Helper to find text input source for a node
      const findTextSource = (node, targetHandle = null) => {
        const textEdge = edges.find(e =>
          e.target === node.id &&
          (targetHandle
            ? e.targetHandle === targetHandle
            : (e.targetHandle?.startsWith('text-in') || e.targetHandle === 'prompt' || e.targetHandle === 'input' || !e.targetHandle))
        );
        return textEdge ? nodeMap.get(textEdge.source) : null;
      };

      // Helper to find image input source for a node
      const findImageSource = (node) => {
        const imageEdge = edges.find(e =>
          e.target === node.id && (e.targetHandle === 'image-in' || e.targetHandle === 'image')
        );
        return imageEdge ? nodeMap.get(imageEdge.source) : null;
      };

      // Process cell nodes (LLM cells with YAML)
      const cellNodes = sortedNodes.filter(n => n.type === 'cell');
      cellNodes.forEach(node => {
        // Parse the YAML to get the cell definition
        let cellConfig;
        try {
          cellConfig = yaml.load(node.data.yaml);
        } catch {
          // Skip invalid YAML
          console.warn(`[generateCascade] Invalid YAML for cell node ${node.id}`);
          return;
        }

        // Use custom node name if set, otherwise use name from YAML
        const cellName = node.data.name || cellConfig.name || node.id;
        const cell = {
          ...cellConfig,
          name: cellName,
        };

        // Find all text input connections (for context from other cells)
        const textEdges = edges.filter(e =>
          e.target === node.id && e.targetHandle?.startsWith('text-in')
        );

        const contextSources = [];
        textEdges.forEach(edge => {
          const sourceNode = nodeMap.get(edge.source);
          if (!sourceNode) return;

          if (sourceNode.type === 'cell') {
            // Cell → Cell: Add context.from with include: ["output"]
            contextSources.push({
              cell: getNodeName(sourceNode),
              include: ['output'],
            });
          }
          // Prompt → Cell: The YAML already has {{ input.X }} references
          // which will be resolved from cascade inputs
        });

        // Find image input connection (for vision models)
        const imageSource = findImageSource(node);
        if (imageSource) {
          if (imageSource.type === 'image' || imageSource.type === 'cell') {
            contextSources.push({
              cell: getNodeName(imageSource),
              include: ['images'],
            });
          }
        }

        // Add context if we have upstream cell dependencies
        if (contextSources.length > 0) {
          cell.context = {
            from: contextSources,
          };
        }

        cells.push(cell);
      });

      // Process image nodes (generators, transformers, tools)
      const imageNodes = sortedNodes.filter(n => n.type === 'image');

      imageNodes.forEach(node => {
        const paletteConfig = node.data.paletteConfig;
        if (!paletteConfig) return;

        // Find connected text source (prompt or cell)
        const textSource = findTextSource(node);
        let promptRef = '';

        if (textSource?.type === 'prompt') {
          promptRef = `{{ input.${getNodeName(textSource)} }}`;
        } else if (textSource?.type === 'cell') {
          // Cell output - will be set via context
          promptRef = `{{ outputs.${getNodeName(textSource)} }}`;
        }

        // Find connected image input
        const imageSource = findImageSource(node);
        const hasImageInput = imageSource?.type === 'image' || imageSource?.type === 'cell';

        if (paletteConfig.openrouter) {
          // OpenRouter image model - use model-based cell (same as LLM cells)
          // Runner detects image models and routes to _execute_image_generation_cell()
          // which uses normal Agent.run() with modalities=["text", "image"]
          const cell = {
            name: getNodeName(node),
            model: paletteConfig.openrouter.model,
            instructions: promptRef || 'Generate a beautiful image',
            image_config: {
              width: 1024,
              height: 1024,
            },
          };

          // Build context.from for upstream dependencies
          const contextSources = [];

          // If text source is a cell, add context for its output
          if (textSource?.type === 'cell') {
            contextSources.push({
              cell: getNodeName(textSource),
              include: ['output'],
            });
          }

          // If there's an image input, add context.from to inject that image
          if (hasImageInput) {
            contextSources.push({
              cell: getNodeName(imageSource),
              include: ['images'],
            });
          }

          if (contextSources.length > 0) {
            cell.context = { from: contextSources };
          }

          cells.push(cell);
        } else if (paletteConfig.harbor) {
          // Harbor tool (HuggingFace Space) - deterministic cell
          const imageRef = imageSource?.type === 'image'
            ? `{{ state.output_${getNodeName(imageSource)}.images[0] }}`
            : '';

          cells.push({
            name: getNodeName(node),
            tool: paletteConfig.harbor.tool,
            tool_inputs: {
              input_image: imageRef,
              // Use defaults for other params
            },
          });
        } else if (paletteConfig.local) {
          // Local tool - deterministic cell
          cells.push({
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
        cells,

        // Embed playground state for UI persistence
        // NOTE: Don't store yaml string in node data - it's redundant with cells[]
        // When loading, we reconstruct yaml from the cell definition
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
              // Cell node: store discoveredInputs but NOT yaml (reconstructed on load)
              discoveredInputs: n.data.discoveredInputs,
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
        yaml: yaml.dump(cascade, {
          lineWidth: 100,
          noRefs: true,
          quotingType: '"',
          forceQuotes: false,
        }),
        inputs,
      };
    },

    // Save cascade as a named tool or cascade
    saveCascadeAs: async (options) => {
      const { cascadeId, description, saveTo = 'tackle', keepMetadata = true } = options;
      const state = get();
      const { yaml: cascadeYaml } = state.generateCascade();

      if (!cascadeYaml) {
        return { success: false, error: 'Failed to generate cascade' };
      }

      try {
        const response = await fetch('http://localhost:5050/api/playground/save-as', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cascade_id: cascadeId,
            description,
            save_to: saveTo,
            cascade_yaml: cascadeYaml,
            keep_metadata: keepMetadata,
          }),
        });

        const data = await response.json();

        if (data.error) {
          return { success: false, error: data.error };
        }

        // Update the loaded cascade ID so future saves update this cascade
        set((state) => {
          state.loadedCascadeId = cascadeId;
        });

        console.log(`[Store] Saved cascade as '${cascadeId}' to ${data.filepath}`);

        return {
          success: true,
          cascadeId: data.cascade_id,
          filepath: data.filepath,
          saveTo: data.save_to,
        };

      } catch (err) {
        console.error('[Store] Save cascade failed:', err);
        return { success: false, error: err.message };
      }
    },

    // ============================================
    // EXECUTION
    // ============================================

    // Fetch session cost from database
    fetchSessionCost: async () => {
      const state = get();
      const sid = state.sessionId;
      if (!sid) return;

      try {
        const response = await fetch(`http://localhost:5050/api/session-cost/${sid}`);
        const data = await response.json();

        if (data.cost !== null && data.cost !== undefined) {
          set((s) => {
            s.totalSessionCost = data.cost;
          });
        }
      } catch (err) {
        // Silently ignore polling errors
        console.warn('[Store] Cost polling error:', err.message);
      }

      // Check if we should stop polling
      const currentState = get();
      if (currentState.costPollingStopTime && Date.now() >= currentState.costPollingStopTime) {
        get().stopCostPolling();
      }
    },

    // Start polling for session cost
    startCostPolling: () => {
      const state = get();

      // Clear any existing timer
      if (state.costPollingTimer) {
        clearInterval(state.costPollingTimer);
      }

      // Poll every 2 seconds
      const timer = setInterval(() => {
        get().fetchSessionCost();
      }, 2000);

      set((s) => {
        s.costPollingTimer = timer;
        s.costPollingStopTime = null; // Clear stop time while running
      });

      // Also fetch immediately
      get().fetchSessionCost();
    },

    // Stop polling for session cost
    stopCostPolling: () => {
      const state = get();
      if (state.costPollingTimer) {
        clearInterval(state.costPollingTimer);
        set((s) => {
          s.costPollingTimer = null;
          s.costPollingStopTime = null;
        });
      }
    },

    // Schedule polling to stop after a delay (used after cascade completes)
    scheduleCostPollingStop: (delayMs = 10000) => {
      set((s) => {
        s.costPollingStopTime = Date.now() + delayMs;
      });
    },

    // Run the cascade
    runCascade: async () => {
      const state = get();
      const { yaml: cascadeYaml, inputs } = state.generateCascade();

      if (!cascadeYaml) {
        return { success: false, error: 'Failed to generate cascade' };
      }

      // Set all execution nodes (image and cell) to 'pending' status
      set((state) => {
        state.nodes.forEach(node => {
          if (node.type === 'image') {
            node.data.status = 'pending';
            node.data.images = [];
          } else if (node.type === 'cell') {
            node.data.status = 'pending';
            node.data.output = '';
          }
        });
        state.executionStatus = 'running';
        state.executionError = null;
        state.totalSessionCost = 0; // Reset cost for new run
      });

      try {
        const response = await fetch('http://localhost:5050/api/run-cascade', {
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

        // Start polling for session cost from database
        get().startCostPolling();

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

      // Get the cell name for this node (custom name or id)
      const targetNode = state.nodes.find(n => n.id === nodeId);
      const cellName = targetNode?.data?.name || nodeId;

      // Set target node to 'pending', keep upstream nodes completed, clear downstream
      // Include both image and cell nodes in execution order
      const nodeOrder = state.nodes
        .filter(n => n.type === 'image' || n.type === 'cell')
        .map(n => n.id);
      const targetIdx = nodeOrder.indexOf(nodeId);

      set((state) => {
        state.nodes.forEach(node => {
          if (node.type === 'image' || node.type === 'cell') {
            const nodeIdx = nodeOrder.indexOf(node.id);
            if (nodeIdx < targetIdx) {
              // Upstream: keep as completed with cached results
              node.data.status = 'completed';
            } else if (nodeIdx === targetIdx) {
              // Target: mark as pending
              node.data.status = 'pending';
              if (node.type === 'image') {
                node.data.images = [];
              } else {
                node.data.output = '';
              }
            } else {
              // Downstream: mark as pending
              node.data.status = 'pending';
              if (node.type === 'image') {
                node.data.images = [];
              } else {
                node.data.output = '';
              }
            }
          }
        });
        state.executionStatus = 'running';
        state.executionError = null;
        state.totalSessionCost = 0; // Reset cost for new run
      });

      try {
        const response = await fetch('http://localhost:5050/api/playground/run-from', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cell_name: cellName, // Use cell name (custom name or id) to match cascade cells
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

        // Start polling for session cost from database
        get().startCostPolling();

        return { success: true, sessionId: data.session_id, startingFrom: nodeId };

      } catch (err) {
        set((state) => {
          state.executionStatus = 'error';
          state.executionError = err.message;
        });
        return { success: false, error: err.message };
      }
    },

    // Handle cell completion from SSE
    handleCellComplete: (cellName, result) => set((state) => {
      console.log('[Store] handleCellComplete:', cellName, 'images:', result.images, 'output:', result.output);

      // Find node by custom name OR by id (for backwards compatibility)
      // Also check parsed cell name for cell nodes
      const nodeIndex = state.nodes.findIndex(n => {
        if (n.data.name === cellName || n.id === cellName) return true;
        // For cell nodes, also check the name in their YAML
        if (n.type === 'cell' && n.data.parsedCell?.name === cellName) return true;
        return false;
      });

      if (nodeIndex !== -1) {
        const node = state.nodes[nodeIndex];
        // Only update images if this result has them (avoid overwriting with empty)
        const newImages = result.images && result.images.length > 0 ? result.images : node.data.images;

        console.log('[Store] Found node:', node.id, 'type:', node.type, 'current images:', node.data.images, 'new images:', newImages);

        // Create a completely new nodes array to ensure React Flow detects the change
        // Note: runner sends duration_ms, not duration
        state.nodes = state.nodes.map((n, i) => {
          if (i !== nodeIndex) return n;

          const baseUpdate = {
            ...n.data,
            status: 'completed',
            cost: result.cost || n.data.cost,
            duration: result.duration_ms || result.duration || n.data.duration,
          };

          // For cell nodes, store text output; for image nodes, store images
          if (n.type === 'cell') {
            return {
              ...n,
              data: {
                ...baseUpdate,
                output: result.output || result.content || '',
              },
            };
          } else {
            return {
              ...n,
              data: {
                ...baseUpdate,
                images: newImages,
              },
            };
          }
        });

        console.log('[Store] After update, node:', state.nodes[nodeIndex].id);
      } else {
        console.log('[Store] Node not found for cell:', cellName, 'available nodes:', state.nodes.map(n => ({ id: n.id, name: n.data.name, type: n.type })));
      }

      state.cellResults[cellName] = result;
      // Note: Session cost is now polled from database via fetchSessionCost()
      // to avoid double-counting (SSE events can have duplicate cost values)

      // Auto-size image nodes when they receive new images
      if (nodeIndex !== -1 && result.images && result.images.length > 0) {
        const node = state.nodes[nodeIndex];
        if (node.type === 'image') {
          // Schedule async image loading and resizing (can't be done in setter)
          setTimeout(() => {
            get().autoSizeImageNode(node.id, result.images[0]);
          }, 0);
        }
      }
    }),

    // Auto-size image node to fit image aspect ratio
    autoSizeImageNode: (nodeId, imagePath) => {
      const img = new Image();
      img.onload = () => {
        const aspectRatio = img.naturalWidth / img.naturalHeight;
        const state = get();
        const node = state.nodes.find(n => n.id === nodeId);
        if (!node) return;

        // Calculate new dimensions maintaining aspect ratio
        // Use current width as base, adjust height to match aspect
        const currentWidth = node.data.width || 208;
        const GRID_SIZE = 16;
        const HEADER_HEIGHT = 32; // Approximate header height
        const FOOTER_HEIGHT = 28; // Approximate footer height

        // Calculate content area height for the image
        const contentHeight = Math.round(currentWidth / aspectRatio);
        const totalHeight = contentHeight + HEADER_HEIGHT + FOOTER_HEIGHT;

        // Snap to grid
        const snappedHeight = Math.round(totalHeight / GRID_SIZE) * GRID_SIZE;
        const clampedHeight = Math.min(608, Math.max(144, snappedHeight));

        console.log('[Store] Auto-sizing image node:', nodeId, 'aspect:', aspectRatio.toFixed(2), 'new height:', clampedHeight);

        set((state) => {
          state.nodes = state.nodes.map(n => {
            if (n.id !== nodeId) return n;
            return {
              ...n,
              data: {
                ...n.data,
                height: clampedHeight,
                aspectRatio, // Store for aspect-locked resizing
              },
            };
          });
        });
      };
      img.src = `http://localhost:5050${imagePath}`;
    },

    // Handle cascade completion
    handleCascadeComplete: () => {
      set((state) => {
        state.executionStatus = 'completed';
        // Cache session ID for "run from here" feature
        if (state.sessionId) {
          state.lastSuccessfulSessionId = state.sessionId;
        }
      });
      // Continue polling for 10 more seconds to catch final cost data
      get().scheduleCostPollingStop(10000);
      // Also fetch immediately to get any pending costs
      get().fetchSessionCost();
    },

    // Handle cascade error
    handleCascadeError: (error) => {
      set((state) => {
        state.executionStatus = 'error';
        state.executionError = error;
      });
      // Stop polling on error
      get().stopCostPolling();
    },

    // Handle cell start from SSE - set node status to 'running'
    handleCellStart: (cellName) => set((state) => {
      // Find node by custom name, node id, or parsed cell name (same matching as handleCellComplete)
      const nodeIndex = state.nodes.findIndex(n => {
        if (n.data.name === cellName || n.id === cellName) return true;
        if (n.type === 'cell' && n.data.parsedCell?.name === cellName) return true;
        return false;
      });

      if (nodeIndex !== -1) {
        console.log('[Store] Cell start for node:', state.nodes[nodeIndex].id);
        state.nodes = state.nodes.map((n, i) => {
          if (i !== nodeIndex) return n;
          return {
            ...n,
            data: { ...n.data, status: 'running' },
          };
        });
      } else {
        console.log('[Store] Cell start - node not found for cell:', cellName);
      }
    }),

    // Handle cost update from SSE
    handleCostUpdate: (cellName, cost) => set((state) => {
      // Find node by custom name, node id, or parsed cell name (same matching as handleCellComplete)
      const nodeIndex = state.nodes.findIndex(n => {
        if (n.data.name === cellName || n.id === cellName) return true;
        if (n.type === 'cell' && n.data.parsedCell?.name === cellName) return true;
        return false;
      });

      if (nodeIndex !== -1) {
        console.log('[Store] Cost update for node:', state.nodes[nodeIndex].id, 'cost:', cost);
        state.nodes = state.nodes.map((n, i) => {
          if (i !== nodeIndex) return n;
          return {
            ...n,
            data: { ...n.data, cost },
          };
        });
      }
    }),

    // Update session stream states (called by useSessionStream hook)
    // This merges derived cell states from the session log stream
    setSessionStreamStates: (cellStates) => set((state) => {
      state.sessionStreamStates = cellStates;

      // Also update node data based on the derived states
      for (const node of state.nodes) {
        if (node.type !== 'cell') continue;

        // Match by custom name or parsed cell name
        const cellName = node.data.name || node.data.parsedCell?.name;
        if (!cellName) continue;

        const cellState = cellStates[cellName];
        if (!cellState) continue;

        // Update node data with derived state
        node.data.status = cellState.status;
        node.data.output = cellState.output || '';
        node.data.liveLog = cellState.liveLog || [];         // Scrolling log during execution
        node.data.finalOutput = cellState.finalOutput || ''; // Clean winner output after completion
        node.data.lastStatusMessage = cellState.lastStatusMessage || ''; // Short status for footer
        node.data.cost = cellState.cost;
        node.data.duration = cellState.duration;
        node.data.soundingsProgress = cellState.soundingsProgress;
        node.data.winnerIndex = cellState.winnerIndex;
        node.data.currentReforgeStep = cellState.currentReforgeStep;
        node.data.totalReforgeSteps = cellState.totalReforgeSteps;
        node.data.soundingsOutputs = cellState.soundingsOutputs;
        node.data.reforgeOutputs = cellState.reforgeOutputs || {}; // Flattened: step -> winner content
      }
    }),

    // Clear execution state
    clearExecution: () => {
      get().stopCostPolling();
      set((state) => {
        state.sessionId = null;
        state.executionStatus = 'idle';
        state.executionError = null;
        state.cellResults = {};
        state.totalSessionCost = 0;
        state.sessionStreamStates = {};
        state.nodes.forEach(node => {
          if (node.type === 'image') {
            node.data.status = 'idle';
            node.data.images = [];
          } else if (node.type === 'cell') {
            node.data.status = 'idle';
            node.data.output = '';
            node.data.soundingsProgress = [];
            node.data.winnerIndex = null;
            node.data.soundingsOutputs = {};
          }
        });
      });
    },

    // Reset the entire playground
    resetPlayground: () => {
      get().stopCostPolling();
      set((state) => {
        state.nodes = [];
        state.edges = [];
        state.sessionId = null;
        state.lastSuccessfulSessionId = null;
        state.loadedCascadeId = null;
        state.loadedSessionId = null;
        state.executionStatus = 'idle';
        state.executionError = null;
        state.cellResults = {};
        state.sessionStreamStates = {};
        state.selectedNodeId = null;
        state.totalSessionCost = 0;
        state.costPollingTimer = null;
        state.costPollingStopTime = null;
        nodeIdCounter = 0;
      });
      // Clear URL hash
      window.location.hash = '/playground';
    },

    // ============================================
    // DYNAMIC PALETTE
    // ============================================

    // Fetch image generation models from API and merge with static palette items
    refreshPalette: async () => {
      set((state) => {
        state.paletteLoading = true;
        state.paletteError = null;
      });

      try {
        const response = await fetch('http://localhost:5050/api/image-generation-models');
        const data = await response.json();

        if (data.error) {
          console.warn('[Store] Palette API error (using static fallback):', data.error);
        }

        const dynamicModels = data.models || [];

        // Keep static items that are NOT generators (transformers, utilities, agent)
        const staticItems = (paletteConfig.palette || []).filter(
          item => item.category !== 'generator'
        );

        // Merge: static items first, then dynamic generators
        const mergedPalette = [...staticItems, ...dynamicModels];

        set((state) => {
          state.palette = mergedPalette;
          state.paletteLoading = false;
        });

        console.log(`[Store] Palette refreshed: ${staticItems.length} static + ${dynamicModels.length} dynamic models`);
        return { success: true, count: mergedPalette.length };

      } catch (err) {
        console.error('[Store] Failed to refresh palette:', err);
        set((state) => {
          state.paletteLoading = false;
          state.paletteError = err.message;
        });
        // Keep existing palette on error
        return { success: false, error: err.message };
      }
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
        const response = await fetch('http://localhost:5050/api/playground/list');
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
        const response = await fetch(`http://localhost:5050/api/playground/load/${sessionId}`);
        const config = await response.json();

        if (config.error) {
          console.error('[Store] Failed to load cascade:', config.error);
          return { success: false, error: config.error };
        }

        let playground = config._playground;

        // If no _playground metadata, introspect the cascade to infer the graph
        if (!playground) {
          console.log('[Store] No _playground metadata, introspecting cascade...');

          try {
            const introspectResponse = await fetch('http://localhost:5050/api/playground/introspect', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cascade_yaml: yaml.dump(config) }),
            });
            const introspected = await introspectResponse.json();

            if (introspected.error) {
              console.error('[Store] Introspection failed:', introspected.error);
              return { success: false, error: `Introspection failed: ${introspected.error}` };
            }

            console.log('[Store] Introspected cascade:', introspected.nodes.length, 'nodes,', introspected.edges.length, 'edges');

            // Convert introspected result to _playground format
            playground = {
              version: 1,
              viewport: introspected.viewport,
              nodes: introspected.nodes.map(n => ({
                id: n.id,
                type: n.type,
                position: n.position,
                data: n.data,
              })),
              edges: introspected.edges.map(e => ({
                source: e.source,
                target: e.target,
                sourceHandle: e.sourceHandle,
                targetHandle: e.targetHandle,
              })),
            };
          } catch (introErr) {
            console.error('[Store] Introspection request failed:', introErr);
            return { success: false, error: `Introspection failed: ${introErr.message}` };
          }
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
                placeholder: n.data?.placeholder, // Input description as placeholder
                width: n.data?.width,
                height: n.data?.height,
              },
            };
          } else if (n.type === 'cell') {
            // Restore cell node - reconstruct YAML from cell definition
            // Look up the cell by name in config.cells
            const cellName = n.data?.name || 'llm_cell';
            const cellConfig = config.cells?.find(p => p.name === cellName);

            // Reconstruct clean YAML from the cell config (not the stringified blob)
            let cellYaml = n.data?.yaml || '';
            if (cellConfig && !cellYaml) {
              // Build yaml from the cell definition
              cellYaml = yaml.dump(cellConfig, {
                lineWidth: 100,
                noRefs: true,
              });
            }

            return {
              id: n.id,
              type: 'cell',
              position: n.position,
              data: {
                yaml: cellYaml,
                discoveredInputs: n.data?.discoveredInputs || [],
                status: 'idle',
                output: '',
                name: n.data?.name, // Restore custom name
                width: n.data?.width,
                height: n.data?.height,
              },
            };
          } else {
            // Image node
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
            // animated is computed dynamically in PlaygroundCanvas based on node running status
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
          state.cellResults = {};
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

    // Load a cascade directly from a file path (for browsing examples)
    loadCascadeFromFile: async (filepath) => {
      try {
        console.log('[Store] Loading cascade from file:', filepath);

        // Introspect the file to get the graph structure
        const response = await fetch('http://localhost:5050/api/playground/introspect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cascade_file: filepath }),
        });
        const result = await response.json();

        if (result.error) {
          console.error('[Store] Introspection failed:', result.error);
          return { success: false, error: result.error };
        }

        console.log('[Store] Introspected file:', result.nodes.length, 'nodes,', result.edges.length, 'edges');

        const palette = get().palette;

        // Build nodes from introspected result
        const restoredNodes = result.nodes.map(n => {
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
                text: '',
                name: n.data?.name,
                placeholder: n.data?.placeholder, // Input description as placeholder
              },
            };
          } else if (n.type === 'cell') {
            return {
              id: n.id,
              type: 'cell',
              position: n.position,
              data: {
                yaml: n.data?.yaml || '',
                discoveredInputs: [],
                status: 'idle',
                output: '',
                name: n.data?.name,
              },
            };
          } else {
            // Image node - try to match palette item
            const paletteConfig = n.data?.paletteConfig;
            const modelId = paletteConfig?.openrouter?.model;
            const paletteItem = modelId
              ? palette.find(p => p.openrouter?.model === modelId)
              : null;

            return {
              id: n.id,
              type: n.type,
              position: n.position,
              data: {
                paletteId: paletteItem?.id,
                paletteName: paletteItem?.name || n.data?.name || 'Image',
                paletteIcon: paletteItem?.icon || 'mdi:image',
                paletteColor: paletteItem?.color || '#8b5cf6',
                paletteConfig: paletteItem || paletteConfig,
                status: 'idle',
                images: [],
                prompt: '',
                name: n.data?.name,
              },
            };
          }
        });

        // Build edges
        const restoredEdges = result.edges.map(e => ({
          id: e.id || `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          sourceHandle: e.sourceHandle || 'text-out',
          targetHandle: e.targetHandle || 'text-in',
          animated: e.animated,
          style: e.style,
        }));

        set((state) => {
          state.nodes = restoredNodes;
          state.edges = restoredEdges;
          state.sessionId = null; // No session yet - this is a fresh load
          state.lastSuccessfulSessionId = null;
          state.loadedCascadeId = filepath; // Track file path
          state.loadedSessionId = null;
          state.executionStatus = 'idle';
          state.executionError = null;
          state.cellResults = {};
          state.selectedNodeId = null;
          if (result.viewport) {
            state.viewport = result.viewport;
          }
        });

        // Clear URL hash (not a session)
        window.location.hash = '/playground';

        return { success: true, filepath, nodes: restoredNodes.length, edges: restoredEdges.length };
      } catch (err) {
        console.error('[Store] Failed to load cascade from file:', err);
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
