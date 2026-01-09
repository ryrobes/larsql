/**
 * Cascade Layout Utilities
 *
 * Shared layout algorithms for rendering cascade graphs.
 * Used by both CascadeTimeline (Studio) and CascadeSpecGraph (read-only views).
 */

// Input parameter color palette (warm/pastel to avoid clash with context colors)
export const INPUT_COLORS = [
  '#ffd700', // Gold
  '#ffa94d', // Amber
  '#ff9d76', // Coral
  '#fb7185', // Rose
  '#f472b6', // Hot pink
  '#d4a8ff', // Lavender
  '#fde047', // Lemon
  '#a7f3d0', // Mint
];

// Edge context type colors
export const EDGE_COLORS = {
  data: '#00e5ff',      // Direct data flow ({{ outputs.X }})
  selective: '#a78bfa', // Selective context (context.from)
  execution: '#64748b', // Execution order only
  branch: '#ff006e',    // Branch/merge points
};

// Card dimensions
export const CARD_WIDTH = 240;
export const CARD_HEIGHT = 90;
export const BASE_CARD_HEIGHT = 130; // For layout calculations

// Input node dimensions (for spec graph visualization)
export const INPUT_NODE_WIDTH = 120;
export const INPUT_NODE_X = 20;
export const INPUT_NODE_Y = 40;
export const INPUT_NODE_GAP = 20; // Gap between input node and first cell

/**
 * Build FBP-style layered graph layout
 * Returns positioned nodes and edges for rendering
 *
 * @param {Array} cells - Array of cell definitions
 * @param {Object} inputsSchema - Input parameter schema
 * @param {boolean} linearMode - If true, arrange in single row instead of DAG layers
 * @param {Object} cellCostMetrics - Optional cost metrics for scaling (default: {})
 * @param {boolean} hasInputsNode - If true, account for inputs node in layout (default: false)
 * @returns {Object} { nodes, edges, width, height, inputPositions, inputColorMap }
 */
export const buildFBPLayout = (cells, inputsSchema, linearMode = false, cellCostMetrics = {}, hasInputsNode = false) => {
  if (!cells || cells.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0, inputPositions: {}, inputColorMap: {} };
  }

  // Calculate input parameter positions and colors
  const inputPositions = {};
  const inputColorMap = {};
  if (inputsSchema) {
    const inputNames = Object.keys(inputsSchema);
    // Sidebar layout (from top):
    // - Cascade header: ~50px
    // - First input field center (right after PARAMETERS header): ~50px
    // - Each input field: ~55px tall (with padding)
    const BASE_OFFSET = 50; // Center of first input field (param 1)
    const INPUT_HEIGHT = 55;

    inputNames.forEach((name, idx) => {
      // Center of each input field based on its index in inputs_schema
      inputPositions[name] = BASE_OFFSET + (idx * INPUT_HEIGHT);
      // Assign color deterministically
      inputColorMap[name] = INPUT_COLORS[idx % INPUT_COLORS.length];
    });
  }

  // Build dependency graph
  const graph = {};
  const inDegree = {};
  const outDegree = {};

  cells.forEach((cell, idx) => {
    graph[idx] = {
      cell,
      name: cell.name,
      handoffs: cell.handoffs || [],
      targets: [],
      sources: [],
      implicitDeps: [],
      inputDeps: [], // Track {{ input.X }} references
    };
    inDegree[idx] = 0;
    outDegree[idx] = 0;
  });

  // Extract dependencies from {{ outputs.X }} AND {{ input.X }} AND context.from
  cells.forEach((cell, idx) => {
    const cellYaml = JSON.stringify(cell);
    const outputDeps = new Set();
    const inputRefs = new Set();

    // {{ outputs.cell_name }} references
    const outputsPattern = /\{\{\s*outputs\.(\w+)/g;
    let match;
    while ((match = outputsPattern.exec(cellYaml)) !== null) {
      const matchedName = match[1]; // Capture to avoid loop-func warning
      const depIdx = cells.findIndex(c => c.name === matchedName);
      if (depIdx !== -1 && depIdx !== idx) outputDeps.add(depIdx);
    }

    // {{ input.param_name }} references
    const inputPattern = /\{\{\s*input\.(\w+)/g;
    while ((match = inputPattern.exec(cellYaml)) !== null) {
      inputRefs.add(match[1]);
    }

    // context.from dependencies (explicit cell context imports)
    if (cell.context && cell.context.from) {
      const contextFrom = Array.isArray(cell.context.from)
        ? cell.context.from
        : [cell.context.from];

      contextFrom.forEach(cellName => {
        const depIdx = cells.findIndex(c => c.name === cellName);
        if (depIdx !== -1 && depIdx !== idx) outputDeps.add(depIdx);
      });
    }

    graph[idx].implicitDeps = Array.from(outputDeps);
    graph[idx].inputDeps = Array.from(inputRefs);
  });

  // Build edges from BOTH handoffs (explicit) AND implicit deps
  cells.forEach((cell, idx) => {
    // Explicit handoffs
    const handoffs = cell.handoffs || [];
    handoffs.forEach(targetName => {
      const targetIdx = cells.findIndex(c => c.name === targetName);
      if (targetIdx !== -1) {
        if (!graph[idx].targets.includes(targetIdx)) {
          graph[idx].targets.push(targetIdx);
          outDegree[idx]++;
        }
        if (!graph[targetIdx].sources.includes(idx)) {
          graph[targetIdx].sources.push(idx);
          inDegree[targetIdx]++;
        }
      }
    });

    // Implicit dependencies (reverse direction: this cell depends ON others)
    graph[idx].implicitDeps.forEach(depIdx => {
      // depIdx → idx (dependency feeds into this cell)
      if (!graph[depIdx].targets.includes(idx)) {
        graph[depIdx].targets.push(idx);
        outDegree[depIdx]++;
      }
      if (!graph[idx].sources.includes(depIdx)) {
        graph[idx].sources.push(depIdx);
        inDegree[idx]++;
      }
    });
  });

  const BASE_CARD_WIDTH = 240;
  const MIN_HORIZONTAL_GAP = linearMode ? 60 : 120; // Minimum gap between cards
  const VERTICAL_GAP = 0; // No vertical spacing - cards touch
  // Calculate left padding - account for inputs node if present
  const INPUT_NODE_SPACE = hasInputsNode ? (INPUT_NODE_X + INPUT_NODE_WIDTH + INPUT_NODE_GAP) : 0;
  const BASE_PADDING_LEFT = linearMode ? 40 : 160;
  const PADDING_LEFT = hasInputsNode ? Math.max(INPUT_NODE_SPACE, BASE_PADDING_LEFT) : BASE_PADDING_LEFT;
  const PADDING_TOP = linearMode ? 20 : 40; // Less vertical padding in linear
  const PADDING_RIGHT = 40;
  const ANNOTATION_CLEARANCE = 25; // Extra space below for annotations

  // Topological layering (columns)
  const layers = [];
  const nodeLayer = {};
  const remaining = new Set(cells.map((_, i) => i));

  while (remaining.size > 0) {
    const layer = [];
    for (const idx of remaining) {
      // Can place if all sources already placed
      if (graph[idx].sources.every(s => nodeLayer[s] !== undefined)) {
        layer.push(idx);
      }
    }

    if (layer.length === 0) break; // Finished or cycle
    layer.forEach(idx => {
      nodeLayer[idx] = layers.length;
      remaining.delete(idx);
    });
    layers.push(layer);
  }

  // Position nodes
  const nodes = [];

  if (linearMode) {
    // Linear mode: single horizontal row (array order)
    let xPos = PADDING_LEFT;

    cells.forEach((cell, idx) => {
      const scale = cellCostMetrics[cell.name]?.scale || 1.0;

      nodes.push({
        cellIdx: idx,
        cell: cells[idx],
        x: xPos,
        y: PADDING_TOP,
        layer: 0,
        isBranch: outDegree[idx] > 1,
        isMerge: inDegree[idx] > 1,
        inputDeps: graph[idx].inputDeps,
      });

      // Calculate visual right edge after center-origin scaling
      // Card at xPos, width 240, center at (xPos + 120)
      // After scale S, visual right edge: (xPos + 120) + (120 * S)
      const visualRightEdge = xPos + 120 * (1 + scale);

      // Next card starts after this card's visual right edge + gap + annotation clearance
      xPos = visualRightEdge + MIN_HORIZONTAL_GAP + 20; // Extra 20px for annotation text
    });
  } else {
    // FBP mode: layered graph with collision-aware positioning
    const layerXPositions = []; // Track x position for each layer

    layers.forEach((layer, layerIdx) => {
      // Calculate max width in previous layer to determine this layer's X
      let layerX = PADDING_LEFT;
      if (layerIdx > 0 && layerXPositions[layerIdx - 1] !== undefined) {
        // Find max scaled width in previous layer
        const prevLayer = layers[layerIdx - 1];
        const prevLayerMaxScale = Math.max(...prevLayer.map(cellIdx => {
          const scale = cellCostMetrics[cells[cellIdx].name]?.scale || 1.0;
          return scale;
        }), 1.0);
        const prevLayerMaxWidth = BASE_CARD_WIDTH * prevLayerMaxScale;

        layerX = layerXPositions[layerIdx - 1] + prevLayerMaxWidth + MIN_HORIZONTAL_GAP;
      } else if (layerIdx > 0) {
        layerX = PADDING_LEFT + (layerIdx * (BASE_CARD_WIDTH + MIN_HORIZONTAL_GAP));
      }

      layerXPositions[layerIdx] = layerX;

      // Accumulate Y positions accounting for each cell's scaled height
      let yPos = PADDING_TOP;

      layer.forEach((cellIdx, posInLayer) => {
        const scale = cellCostMetrics[cells[cellIdx].name]?.scale || 1.0;
        const scaledHeight = BASE_CARD_HEIGHT * scale;

        nodes.push({
          cellIdx,
          cell: cells[cellIdx],
          x: layerX,
          y: yPos,
          layer: layerIdx,
          isBranch: outDegree[cellIdx] > 1,
          isMerge: inDegree[cellIdx] > 1,
          inputDeps: graph[cellIdx].inputDeps,
        });

        // Move Y position for next card in this layer
        yPos += scaledHeight + VERTICAL_GAP + ANNOTATION_CLEARANCE;
      });
    });
  }

  // Build edges with context-aware coloring
  const edges = [];
  nodes.forEach(node => {
    graph[node.cellIdx].targets.forEach(targetIdx => {
      const targetNode = nodes.find(n => n.cellIdx === targetIdx);
      if (!targetNode) return;

      const sourceCell = cells[node.cellIdx];
      const targetCell = cells[targetIdx];

      // Determine edge context type
      let contextType = 'execution'; // Default: just execution order

      // Check for selective context array
      const hasSelectiveContext = targetCell.context?.from;
      if (hasSelectiveContext) {
        const contextFrom = targetCell.context.from || [];
        if (contextFrom.includes(sourceCell.name) || contextFrom.includes('all')) {
          contextType = 'selective';
        }
      }

      // Check for direct output reference {{ outputs.source_name }}
      const targetYaml = JSON.stringify(targetCell);
      const outputsPattern = new RegExp(`\\{\\{\\s*outputs\\.${sourceCell.name}`, 'g');
      if (outputsPattern.test(targetYaml)) {
        contextType = 'data'; // Direct data flow
      }

      edges.push({
        source: node,
        target: targetNode,
        contextType, // 'data', 'selective', 'execution'
        isBranch: node.isBranch,
        isMerge: targetNode.isMerge,
      });
    });
  });

  // Calculate canvas dimensions accounting for scales
  const width = linearMode
    ? nodes.reduce((sum, node) => {
        const scale = cellCostMetrics[node.cell.name]?.scale || 1.0;
        return sum + (BASE_CARD_WIDTH * scale) + MIN_HORIZONTAL_GAP;
      }, PADDING_LEFT + PADDING_RIGHT)
    : nodes.reduce((maxX, node) => {
        const scale = cellCostMetrics[node.cell.name]?.scale || 1.0;
        const nodeRight = node.x + (BASE_CARD_WIDTH * scale);
        return Math.max(maxX, nodeRight);
      }, 0) + PADDING_RIGHT;

  const height = linearMode
    ? (BASE_CARD_HEIGHT * 1.3) + (PADDING_TOP * 2) + ANNOTATION_CLEARANCE // Account for max scale
    : nodes.reduce((maxY, node) => {
        const scale = cellCostMetrics[node.cell.name]?.scale || 1.0;
        const nodeBottom = node.y + (BASE_CARD_HEIGHT * scale) + ANNOTATION_CLEARANCE;
        return Math.max(maxY, nodeBottom);
      }, 0) + PADDING_TOP;

  return { nodes, edges, width, height, inputPositions, inputColorMap };
};

/**
 * Generate SVG path for an edge between two nodes
 *
 * @param {Object} source - Source node with x, y
 * @param {Object} target - Target node with x, y
 * @param {Object} cellCostMetrics - Optional cost metrics for scaling
 * @returns {string} SVG path d attribute
 */
export const generateEdgePath = (source, target, cellCostMetrics = {}) => {
  const sourceScale = cellCostMetrics[source.cell?.name]?.scale || 1.0;
  const targetScale = cellCostMetrics[target.cell?.name]?.scale || 1.0;

  // Calculate visual offsets due to scaling
  const sourceRightOffset = (sourceScale - 1) * CARD_WIDTH / 2;
  const targetLeftOffset = (targetScale - 1) * CARD_WIDTH / 2;

  // Adjust edge endpoints to match visual card boundaries
  const x1 = source.x + CARD_WIDTH + sourceRightOffset; // Source right edge
  const y1 = source.y + CARD_HEIGHT / 2;                 // Source vertical center
  const x2 = target.x - targetLeftOffset;                // Target left edge
  const y2 = target.y + CARD_HEIGHT / 2;                 // Target vertical center

  const dx = x2 - x1;
  const cx1 = x1 + dx * 0.5;
  const cx2 = x2 - dx * 0.5;

  return `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`;
};

/**
 * Get edge color based on context type
 *
 * @param {string} contextType - 'data', 'selective', 'execution'
 * @param {boolean} isSpecial - Is this a branch/merge edge
 * @returns {string} Hex color
 */
export const getEdgeColor = (contextType, isSpecial = false) => {
  if (isSpecial) return EDGE_COLORS.branch;
  return EDGE_COLORS[contextType] || EDGE_COLORS.execution;
};

/**
 * Get edge opacity based on context type
 *
 * @param {string} contextType - 'data', 'selective', 'execution'
 * @returns {number} Opacity value 0-1
 */
export const getEdgeOpacity = (contextType) => {
  return contextType === 'execution' ? 0.3 : 0.6;
};
