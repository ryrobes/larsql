import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import { motion } from 'framer-motion';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useTimelinePolling from '../hooks/useTimelinePolling';
import CellCard from './CellCard';
import CellDetailPanel from './CellDetailPanel';
import { CellAnatomyPanel } from '../phase-anatomy';
import SessionMessagesLog from '../components/SessionMessagesLog';
import { Tooltip } from '../../components/RichTooltip';
import { Button } from '../../components';
import './CascadeTimeline.css';

/**
 * InputEdgesSVG - Memoized SVG layer for input parameter connections
 * Only re-renders when layout, positions, or viewport changes
 * Uses Framer Motion to animate edge path changes
 */
const InputEdgesSVG = React.memo(({
  nodes,
  inputPositions,
  inputColorMap,
  timelineOffset,
  timelineHeight,
  scrollOffset
}) => {
  if (process.env.NODE_ENV === 'development') {
    console.log('[InputEdgesSVG] Rendering', { timelineHeight });
  }

  // Shared animation config (matches cell edges)
  const edgeTransition = {
    type: 'spring',
    stiffness: 300,
    damping: 30,
    mass: 0.8,
  };

  return (
    <svg
      className="cascade-input-edges"
      style={{
        position: 'fixed',
        left: 0,
        top: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 5,
      }}
    >
      <defs>
        <clipPath id="timeline-clip">
          <rect
            x="0"
            y={timelineOffset.top}
            width="100%"
            height={timelineHeight || 400} // Use measured height, fallback to 400
          />
        </clipPath>
      </defs>

      <g clipPath="url(#timeline-clip)">
        {nodes.map(node => {
          if (!node.inputDeps || node.inputDeps.length === 0) return null;

          return node.inputDeps.map(inputName => {
            const inputY = inputPositions[inputName] || 50;
            const inputColor = inputColorMap[inputName] || '#ffd700';

            const x1 = timelineOffset.left;
            const SIDEBAR_TOP = 0;
            const y1 = SIDEBAR_TOP + inputY + 52;
            const x2 = timelineOffset.left + (node.x - scrollOffset.x);
            const y2 = timelineOffset.top + (node.y + 50 - scrollOffset.y);

            // Don't draw if target is off-screen
            if (x2 < timelineOffset.left - 240 || x2 > window.innerWidth) return null;

            const dx = x2 - x1;
            const cx1 = x1 + Math.min(60, dx * 0.3);
            const cx2 = x2 - Math.min(60, dx * 0.3);

            const pathD = `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`;
            const pathKey = `input-${node.cellIdx}-${inputName}`;

            return (
              <motion.path
                key={pathKey}
                d={pathD}
                stroke={inputColor}
                strokeWidth="2.5"
                fill="none"
                opacity="0.75"
                strokeLinecap="round"
                strokeDasharray="5 5"
                initial={{ d: pathD }}
                animate={{ d: pathD }}
                transition={edgeTransition}
              />
            );
          });
        })}
      </g>
    </svg>
  );
});

InputEdgesSVG.displayName = 'InputEdgesSVG';

/**
 * CellEdgesSVG - Memoized SVG layer for cell-to-cell connections
 * Only re-renders when layout changes
 * Uses Framer Motion to animate edge path changes
 */
const CellEdgesSVG = React.memo(({ edges, width, height }) => {
  if (process.env.NODE_ENV === 'development') {
    console.log('[CellEdgesSVG] Rendering');
  }

  // Shared animation config for smooth edge transitions
  const edgeTransition = {
    type: 'spring',
    stiffness: 300,
    damping: 30,
    mass: 0.8,
  };

  return (
    <svg
      className="cascade-edges"
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: `${width + 100}px`,
        height: `${height + 100}px`,
        pointerEvents: 'none',
        zIndex: 0,
        overflow: 'visible',
      }}
    >
      {edges.map((edge, idx) => {
        const { source, target, contextType, isBranch, isMerge } = edge;

        const x1 = source.x + 240;
        const y1 = source.y + 65;
        const x2 = target.x;
        const y2 = target.y + 65;

        const colorMap = {
          data: '#00e5ff',
          selective: '#a78bfa',
          execution: '#64748b',
        };
        const color = colorMap[contextType] || '#64748b';
        const isSpecial = isBranch || isMerge;
        const finalColor = isSpecial ? '#ff006e' : color;
        const opacity = contextType === 'execution' ? 0.3 : 0.6;

        const dx = x2 - x1;
        const cx1 = x1 + dx * 0.5;
        const cx2 = x2 - dx * 0.5;

        const pathD = `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`;

        // Use stable key based on source and target cell indices
        const edgeKey = `edge-${source.cellIdx}-${target.cellIdx}`;

        return (
          <motion.path
            key={edgeKey}
            d={pathD}
            stroke={finalColor}
            strokeWidth="3"
            fill="none"
            opacity={opacity}
            strokeLinecap="round"
            initial={{ d: pathD }}
            animate={{ d: pathD }}
            transition={edgeTransition}
          />
        );
      })}
    </svg>
  );
});

CellEdgesSVG.displayName = 'CellEdgesSVG';

/**
 * Build FBP-style layered graph layout
 * Returns positioned nodes and edges for rendering
 *
 * @param {boolean} linearMode - If true, arrange in single row instead of DAG layers
 */
const buildFBPLayout = (cells, inputsSchema, linearMode = false) => {
  if (!cells || cells.length === 0) return { nodes: [], edges: [], width: 0, height: 0, inputPositions: {} };

  // Input parameter color palette (warm/pastel to avoid clash with context colors)
  const inputColors = [
    '#ffd700', // Gold
    '#ffa94d', // Amber
    '#ff9d76', // Coral
    '#fb7185', // Rose
    '#f472b6', // Hot pink
    '#d4a8ff', // Lavender
    '#fde047', // Lemon
    '#a7f3d0', // Mint
  ];

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
      inputColorMap[name] = inputColors[idx % inputColors.length];
    });

    console.log('[FBP] Input positions:', inputPositions);
    console.log('[FBP] Input colors:', inputColorMap);
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
      const depIdx = cells.findIndex(c => c.name === match[1]);
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

  const CARD_WIDTH = 240;
  const CARD_HEIGHT = 130;
  const HORIZONTAL_GAP = linearMode ? 60 : 120; // Tighter in linear mode
  const VERTICAL_GAP = 0; // No vertical spacing - cards touch
  const PADDING_LEFT = 160; // More space from sidebar
  const PADDING_TOP = linearMode ? 20 : 40; // Less vertical padding in linear
  const PADDING_RIGHT = 40;

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

  console.log('[FBP] Layers:', layers.map((l, i) => `L${i}:[${l.map(idx => cells[idx].name).join(',')}]`));

  // Position nodes
  const nodes = [];

  if (linearMode) {
    // Linear mode: single horizontal row (array order)
    cells.forEach((cell, idx) => {
      const x = PADDING_LEFT + (idx * (CARD_WIDTH + HORIZONTAL_GAP));
      const y = PADDING_TOP;

      nodes.push({
        cellIdx: idx,
        cell: cells[idx],
        x,
        y,
        layer: 0,
        isBranch: outDegree[idx] > 1,
        isMerge: inDegree[idx] > 1,
        inputDeps: graph[idx].inputDeps,
      });
    });
  } else {
    // FBP mode: layered graph
    layers.forEach((layer, layerIdx) => {
      const x = PADDING_LEFT + (layerIdx * (CARD_WIDTH + HORIZONTAL_GAP));

      layer.forEach((cellIdx, posInLayer) => {
        const y = PADDING_TOP + (posInLayer * (CARD_HEIGHT + VERTICAL_GAP));

        nodes.push({
          cellIdx,
          cell: cells[cellIdx],
          x,
          y,
          layer: layerIdx,
          isBranch: outDegree[cellIdx] > 1,
          isMerge: inDegree[cellIdx] > 1,
          inputDeps: graph[cellIdx].inputDeps,
        });
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

  // Calculate canvas dimensions
  const width = linearMode
    ? cells.length * (CARD_WIDTH + HORIZONTAL_GAP) + PADDING_LEFT + PADDING_RIGHT
    : layers.length * (CARD_WIDTH + HORIZONTAL_GAP) + PADDING_LEFT + PADDING_RIGHT;

  const maxNodesInLayer = linearMode ? 1 : Math.max(...layers.map(l => l.length), 1);
  const height = linearMode
    ? CARD_HEIGHT + (PADDING_TOP * 2) // Compact height for linear
    : maxNodesInLayer * (CARD_HEIGHT + VERTICAL_GAP) + PADDING_TOP * 2;

  return { nodes, edges, width, height, inputPositions, inputColorMap };
};

/**
 * DropZone - Visual drop target between cells
 */
const DropZone = ({ position }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: `drop-zone-${position}`,
    data: { position },
  });

  return (
    <div
      ref={setNodeRef}
      className={`cascade-drop-zone ${isOver ? 'cascade-drop-zone-active' : ''}`}
    >
      <div className="cascade-drop-zone-indicator">
        {isOver && <Icon icon="mdi:plus-circle" width="20" />}
      </div>
    </div>
  );
};

/**
 * CanvasDropZone - Background drop target for creating independent cells
 */
const CanvasDropZone = () => {
  const { isOver, setNodeRef } = useDroppable({
    id: 'canvas-background',
    data: { type: 'canvas-background' },
  });

  return (
    <div
      ref={setNodeRef}
      className={`cascade-canvas-drop-zone ${isOver ? 'cascade-canvas-drop-active' : ''}`}
    />
  );
};

/**
 * CascadeTimeline - Horizontal cascade builder (DAW-style)
 *
 * Layout:
 * - Top bar: Cascade controls + metadata
 * - Middle strip: Horizontal scrolling cell cards (left→right) with drop zones
 * - Bottom panel: Selected cell details (config, code, outputs)
 */
const CascadeTimeline = ({ onOpenBrowser }) => {
  console.log('[CascadeTimeline] Component mounting/rendering');

  // Optimized store selectors - only subscribe to what we need
  const cascade = useStudioCascadeStore(state => state.cascade);
  const cascadePath = useStudioCascadeStore(state => state.cascadePath);
  const cascadeDirty = useStudioCascadeStore(state => state.cascadeDirty);
  const cellStates = useStudioCascadeStore(state => state.cellStates);
  const isRunningAll = useStudioCascadeStore(state => state.isRunningAll);
  const cascadeSessionId = useStudioCascadeStore(state => state.cascadeSessionId);
  const viewMode = useStudioCascadeStore(state => state.viewMode);
  const replaySessionId = useStudioCascadeStore(state => state.replaySessionId);
  const sessionId = useStudioCascadeStore(state => state.sessionId);
  const cascades = useStudioCascadeStore(state => state.cascades);
  const selectedCellIndex = useStudioCascadeStore(state => state.selectedCellIndex);
  const defaultModel = useStudioCascadeStore(state => state.defaultModel);

  // Actions
  const fetchCascades = useStudioCascadeStore(state => state.fetchCascades);
  const loadCascade = useStudioCascadeStore(state => state.loadCascade);
  const newCascade = useStudioCascadeStore(state => state.newCascade);
  const addCell = useStudioCascadeStore(state => state.addCell);
  const restartSession = useStudioCascadeStore(state => state.restartSession);
  const updateCascade = useStudioCascadeStore(state => state.updateCascade);
  const saveCascade = useStudioCascadeStore(state => state.saveCascade);
  const setSelectedCellIndex = useStudioCascadeStore(state => state.setSelectedCellIndex);
  const setLiveMode = useStudioCascadeStore(state => state.setLiveMode);
  const updateCellStatesFromPolling = useStudioCascadeStore(state => state.updateCellStatesFromPolling);

  console.log('[CascadeTimeline] Store data:', {
    hasCascade: !!cascade,
    cascadeId: cascade?.cascade_id,
    cellsInCascade: cascade?.cells?.length || 0
  });

  // Poll for execution updates - either live or replay session
  const sessionToPoll = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

  // SMART POLLING: In replay mode, poll once to get historical data
  // In live mode, use isRunningAll flag (which is now data-driven from the store)
  const shouldPoll = viewMode === 'replay'
    ? !!replaySessionId
    : !!(cascadeSessionId && isRunningAll);

  console.log('[CascadeTimeline] Polling logic:', {
    viewMode,
    replaySessionId,
    cascadeSessionId,
    isRunningAll,
    sessionToPoll,
    shouldPoll,
  });

  const { logs, cellStates: polledCellStates, totalCost, sessionStatus, sessionStatusFor, sessionError, childSessions } = useTimelinePolling(sessionToPoll, shouldPoll, viewMode === 'replay');

  // console.log('[CascadeTimeline] Polling decision:', {
  //   viewMode,
  //   sessionToPoll,
  //   isRunningAll,
  //   shouldPoll,
  //   cellCount: Object.keys(polledCellStates || {}).length
  // });

  // Handle session terminal states (error, completed, cancelled, orphaned)
  // This is the authoritative check from session_state table
  useEffect(() => {
    console.log('[CascadeTimeline] Terminal state check:', {
      sessionStatus,
      sessionStatusFor,
      cascadeSessionId,
      isRunningAll,
      sessionToPoll,
    });

    if (!sessionStatus || !cascadeSessionId) return;

    // CRITICAL: Only react if sessionStatus is for the CURRENT cascadeSessionId
    // Prevents stale status from old session killing new runs
    if (sessionStatusFor !== cascadeSessionId) {
      console.log('[CascadeTimeline] Ignoring stale sessionStatus:', {
        statusFor: sessionStatusFor,
        currentSession: cascadeSessionId,
        status: sessionStatus
      });
      return;
    }

    const terminalStatuses = ['completed', 'error', 'cancelled', 'orphaned'];
    if (terminalStatuses.includes(sessionStatus) && isRunningAll) {
      console.log(`[CascadeTimeline] ⚠️ SETTING isRunningAll = FALSE due to terminal status:`, {
        sessionId: cascadeSessionId,
        sessionStatus,
        sessionError
      });

      // Update the store to stop execution
      useStudioCascadeStore.setState({ isRunningAll: false });
    }
  }, [sessionStatus, sessionStatusFor, cascadeSessionId, isRunningAll, sessionError, sessionToPoll]);

  // Debug polling state
  React.useEffect(() => {
    if (sessionToPoll) {
      // console.log('[CascadeTimeline] Polling state:', {
      //   viewMode,
      //   sessionToPoll,
      //   shouldPoll,
      //   logsCount: logs.length,
      //   cellStatesKeys: Object.keys(polledCellStates || {}),
      //   totalCost
      // });
    }
  }, [viewMode, sessionToPoll, shouldPoll, logs.length, polledCellStates, totalCost]);

  // Update cellStates when polling returns new data
  const prevCellStatesHashRef = useRef('');
  useEffect(() => {
    if (!polledCellStates || Object.keys(polledCellStates).length === 0) {
      //console.log('[CascadeTimeline] No polledCellStates to update');
      return;
    }

    // Only update if data actually changed (cheap hash check)
    const currentHash = JSON.stringify(polledCellStates);
    if (currentHash === prevCellStatesHashRef.current) {
      //console.log('[CascadeTimeline] polledCellStates unchanged, skipping update');
      return;
    }

    //console.log('[CascadeTimeline] Updating cellStates from polling:', Object.keys(polledCellStates));
    prevCellStatesHashRef.current = currentHash;
    updateCellStatesFromPolling(polledCellStates);
  }, [polledCellStates, updateCellStatesFromPolling]);

  // Update childSessions when polling returns new data
  const prevChildSessionsHashRef = useRef('');
  useEffect(() => {
    if (!childSessions || Object.keys(childSessions).length === 0) return;

    const currentHash = JSON.stringify(childSessions);
    if (currentHash === prevChildSessionsHashRef.current) return;

    console.log('[CascadeTimeline] Updating childSessions from polling:', Object.keys(childSessions));
    prevChildSessionsHashRef.current = currentHash;
    useStudioCascadeStore.setState({ childSessions });
  }, [childSessions]);

  const timelineRef = useRef(null);
  const [layoutMode, setLayoutMode] = useState('linear'); // 'linear' or 'graph'
  const [scrollOffset, setScrollOffset] = useState({ x: 0, y: 0 });
  const [timelineOffset, setTimelineOffset] = useState({ left: 0, top: 0 });
  const [timelineHeight, setTimelineHeight] = useState(0); // Actual measured height for clipping
  const [showAnatomyPanel, setShowAnatomyPanel] = useState(false); // Phase anatomy visualization

  // Split panel resize state
  const [graphPanelHeight, setGraphPanelHeight] = useState(null); // null = use default heights
  const [isResizing, setIsResizing] = useState(false);
  const resizeStartRef = useRef({ y: 0, initialHeight: 0 });

  // Grab-to-scroll state
  const [isGrabbing, setIsGrabbing] = useState(false);
  const grabStartRef = useRef({ x: 0, y: 0, scrollLeft: 0, scrollTop: 0 });
  const scrollRafRef = useRef(null);

  // Grab-to-scroll handlers
  const handleGrabStart = useCallback((e) => {
    // Only grab on left mouse button, and not on interactive elements
    if (e.button !== 0) return;
    const target = e.target;
    // Don't grab if clicking on a card, button, input, or other interactive element
    if (target.closest('.phase-card, button, input, textarea, .cascade-drop-zone')) return;

    const strip = timelineRef.current;
    if (!strip) return;

    setIsGrabbing(true);
    grabStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      scrollLeft: strip.scrollLeft,
      scrollTop: strip.scrollTop,
    };

    // Prevent text selection while dragging
    e.preventDefault();
  }, []);

  const handleGrabMove = useCallback((e) => {
    if (!isGrabbing) return;

    const strip = timelineRef.current;
    if (!strip) return;

    const dx = e.clientX - grabStartRef.current.x;
    const dy = e.clientY - grabStartRef.current.y;

    strip.scrollLeft = grabStartRef.current.scrollLeft - dx;
    strip.scrollTop = grabStartRef.current.scrollTop - dy;
  }, [isGrabbing]);

  const handleGrabEnd = useCallback(() => {
    setIsGrabbing(false);
  }, []);

  // Split panel resize handlers
  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
    const stripEl = timelineRef.current;
    if (!stripEl) return;

    const currentHeight = stripEl.clientHeight;
    resizeStartRef.current = {
      y: e.clientY,
      initialHeight: currentHeight,
    };
  }, []);

  const handleResizeMove = useCallback((e) => {
    if (!isResizing) return;

    const dy = e.clientY - resizeStartRef.current.y;
    const newHeight = resizeStartRef.current.initialHeight + dy;

    // Clamp height between 150px and 600px
    const clampedHeight = Math.max(150, Math.min(600, newHeight));
    setGraphPanelHeight(clampedHeight);

    // Auto-switch layout mode based on height threshold
    // Threshold: 280px (between linear's 180px and graph's 400px)
    // Add hysteresis: switch to graph at 290px, back to linear at 270px
    const GRAPH_THRESHOLD = 290;
    const LINEAR_THRESHOLD = 270;

    if (clampedHeight >= GRAPH_THRESHOLD && layoutMode === 'linear') {
      console.log('[CascadeTimeline] Auto-switching to graph mode at', clampedHeight);
      setLayoutMode('graph');
    } else if (clampedHeight <= LINEAR_THRESHOLD && layoutMode === 'graph') {
      console.log('[CascadeTimeline] Auto-switching to linear mode at', clampedHeight);
      setLayoutMode('linear');
    }
  }, [isResizing, layoutMode]);

  const handleResizeEnd = useCallback(() => {
    setIsResizing(false);
  }, []);

  // Attach grab-to-scroll listeners
  useEffect(() => {
    if (isGrabbing) {
      // Listen on window so we can track mouse even outside the element
      window.addEventListener('mousemove', handleGrabMove);
      window.addEventListener('mouseup', handleGrabEnd);
      return () => {
        window.removeEventListener('mousemove', handleGrabMove);
        window.removeEventListener('mouseup', handleGrabEnd);
      };
    }
  }, [isGrabbing, handleGrabMove, handleGrabEnd]);

  // Attach resize listeners
  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', handleResizeMove);
      window.addEventListener('mouseup', handleResizeEnd);
      // Prevent text selection while resizing
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'ns-resize';

      return () => {
        window.removeEventListener('mousemove', handleResizeMove);
        window.removeEventListener('mouseup', handleResizeEnd);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
      };
    }
  }, [isResizing, handleResizeMove, handleResizeEnd]);

  // Measure timeline position relative to viewport (for input lines)
  // AND track scroll position for input edges
  useEffect(() => {
    const stripEl = timelineRef.current;
    if (!stripEl) return;

    const updateOffset = () => {
      const rect = stripEl.getBoundingClientRect();
      const newOffset = {
        left: rect.left, // Distance from viewport left (vertical sidebar + left panel)
        top: rect.top,   // Distance from viewport top (control bar)
      };
      setTimelineOffset(newOffset);
      setTimelineHeight(rect.height); // Track actual height for clipping

      if (process.env.NODE_ENV === 'development') {
        console.log('[Timeline Offset & Height]', { ...newOffset, height: rect.height });
      }
    };

    // Handle scroll on the timeline strip (horizontal scroll)
    // Throttled with requestAnimationFrame to reduce re-renders
    const handleStripScroll = () => {
      if (scrollRafRef.current) return; // Already scheduled

      scrollRafRef.current = requestAnimationFrame(() => {
        setScrollOffset({
          x: stripEl.scrollLeft,
          y: stripEl.scrollTop,
        });
        scrollRafRef.current = null;
      });
    };

    // Handle window/document scroll (vertical page scroll)
    const handleWindowScroll = () => {
      // Re-measure timeline position when page scrolls
      updateOffset();
    };

    // Immediate update
    updateOffset();
    handleStripScroll();

    // Update on resize and when split panel moves
    window.addEventListener('resize', updateOffset);
    window.addEventListener('scroll', handleWindowScroll, { passive: true });

    // Listen for scroll on the timeline strip itself
    stripEl.addEventListener('scroll', handleStripScroll, { passive: true });

    // Use ResizeObserver to detect split panel changes
    const resizeObserver = new ResizeObserver(updateOffset);
    const parent = stripEl.parentElement;
    if (parent) resizeObserver.observe(parent);

    // Delayed updates to handle async DOM changes
    const timeout1 = setTimeout(updateOffset, 100);
    const timeout2 = setTimeout(updateOffset, 300);
    const timeout3 = setTimeout(updateOffset, 600);

    return () => {
      window.removeEventListener('resize', updateOffset);
      window.removeEventListener('scroll', handleWindowScroll);
      stripEl.removeEventListener('scroll', handleStripScroll);
      resizeObserver.disconnect();
      clearTimeout(timeout1);
      clearTimeout(timeout2);
      clearTimeout(timeout3);
      // Cancel any pending RAF
      if (scrollRafRef.current) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [layoutMode, cascade?.cascade_id, graphPanelHeight]); // Re-measure when layout, cascade, or height changes

  // Build FBP layout (must be before early returns)
  const cells = cascade?.cells || [];
  const inputsSchema = cascade?.inputs_schema || {};

  // DEBUG: Log cascade data
  React.useEffect(() => {
    console.log('[CascadeTimeline] Cascade data:', {
      hasCascade: !!cascade,
      cascadeId: cascade?.cascade_id,
      cellsLength: cells.length,
      cellNames: cells.map(c => c.name),
      inputsSchema: Object.keys(inputsSchema)
    });
  }, [cascade, cells, inputsSchema]);

  const layout = useMemo(
    () => {
      const result = buildFBPLayout(cells, inputsSchema, layoutMode === 'linear');
      console.log('[CascadeTimeline] FBP Layout built:', {
        cellsInput: cells.length,
        nodesOutput: result.nodes.length,
        edgesOutput: result.edges.length,
        width: result.width,
        height: result.height
      });
      return result;
    },
    [cells, inputsSchema, layoutMode]
  );

  const handleDescriptionChange = (e) => {
    updateCascade({ description: e.target.value });
  };


  const handleSave = async () => {
    if (!cascadePath) {
      const path = window.prompt('Save cascade as:', `cascades/${cascade?.cascade_id || 'cascade'}.yaml`);
      if (path) {
        await saveCascade(path);
      }
    } else {
      await saveCascade();
    }
  };

  const handleSaveAsTool = async () => {
    const toolName = cascade?.cascade_id?.replace(/[^a-z0-9_]/gi, '_') || 'cascade';
    const path = `tackle/${toolName}.yaml`;

    if (window.confirm(`Save as tool: ${toolName}?\n\nThis will make it callable from other cascades.`)) {
      await saveCascade(path);
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all outputs.')) {
      await restartSession();
    }
  };

  const handleLoad = async (path) => {
    try {
      await loadCascade(path);
    } catch (err) {
      console.error('Load failed:', err);
    }
  };

  // Fetch cascades on mount
  useEffect(() => {
    fetchCascades();
  }, [fetchCascades]);

  // Create new cascade if none exists
  useEffect(() => {
    if (!cascade) {
      newCascade();
    }
  }, [cascade, newCascade]);

  // Memoized cell selection callback
  const handleSelectCell = useCallback((index) => {
    setSelectedCellIndex(index);
  }, [setSelectedCellIndex]);

  // Memoize cell logs grouped by cell name to avoid filtering on every render
  // Also create a stable empty array to prevent || [] from creating new arrays
  const EMPTY_LOGS_ARRAY = useMemo(() => [], []);

  const cellLogsByName = useMemo(() => {
    const logMap = {};
    logs.forEach(log => {
      if (!log.cell_name) return;
      if (!logMap[log.cell_name]) logMap[log.cell_name] = [];
      logMap[log.cell_name].push(log);
    });
    return logMap;
  }, [logs]);

  // Stabilize individual cell state references - only update when content actually changes
  // This prevents CellCard from re-rendering when other cells' states change
  const stableCellStatesRef = useRef({});
  const stableCellStates = useMemo(() => {
    const newStableStates = {};

    Object.keys(cellStates).forEach(cellName => {
      const currentState = cellStates[cellName];
      const previousState = stableCellStatesRef.current[cellName];

      // Deep comparison: only create new reference if state actually changed
      if (!previousState || JSON.stringify(currentState) !== JSON.stringify(previousState)) {
        newStableStates[cellName] = currentState;
      } else {
        // Reuse previous reference - prevents unnecessary re-renders
        newStableStates[cellName] = previousState;
      }
    });

    stableCellStatesRef.current = newStableStates;
    return newStableStates;
  }, [cellStates]);

  // Count messages by role, filtering out system messages (phase_*)
  let messageCounts = null;
  if (logs && logs.length > 0) {
    const counts = {};
    let total = 0;
    for (const log of logs) {
      const role = log.role;
      // Skip system messages (phase_start, phase_complete, etc.)
      if (role && !role.startsWith('phase_')) {
        counts[role] = (counts[role] || 0) + 1;
        total++;
      }
    }
    if (total > 0) {
      messageCounts = { ...counts, total };
    }
  }

  const selectedCell = selectedCellIndex !== null ? cells[selectedCellIndex] : null;
  const cellCount = cells.length;
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;

  if (!cascade) {
    return (
      <div className="cascade-timeline cascade-loading">
        <div className="cascade-spinner" />
        Loading cascade...
      </div>
    );
  }

  return (
    <div className="cascade-timeline">
        {/* DEBUG BANNER - TEMPORARY */}
        {/* <div style={{ background: '#ff0066', color: '#fff', padding: '8px', fontSize: '11px', fontFamily: 'monospace' }}>
          DEBUG: cells={cells.length} | cascade.cells={cascade?.cells?.length} | nodes={layout.nodes.length} |
          cascadeId={cascade?.cascade_id} | cellNames={cells.map(c => c.name).join(', ')}
        </div> */}

        {/* Top Control Bar */}
        <div className="cascade-control-bar">
        <div className="cascade-control-left">
          {cascadeDirty && <span className="cascade-dirty-dot" title="Unsaved changes" />}
          {viewMode === 'replay' && (
            <span className="cascade-replay-badge" title="Viewing past execution">
              <Icon icon="mdi:history" width="14" />
              Replay
            </span>
          )}
          <input
            className="cascade-description-input"
            value={cascade.description || ''}
            onChange={handleDescriptionChange}
            placeholder="Description..."
          />

          {/* Session ID + Cost - Moved to left side for better visibility */}
          {sessionToPoll && (
            <>
              <div className="cascade-control-divider" />
              <div className="cascade-session-id-compact" title={`Session: ${sessionToPoll}`}>
                <Icon icon="mdi:identifier" width="14" />
                <span className="cascade-session-id-value">{sessionToPoll}</span>
              </div>
              {/* Always show cost when session exists, even if $0.00 */}
              <div className="cascade-total-cost-compact" title={`Total cascade cost (polling: ${shouldPoll ? 'active' : 'inactive'})`}>
                <Icon icon="mdi:currency-usd" width="14" />
                <span className="cascade-total-cost-value">
                  {totalCost === 0 ? '$0.00' : (totalCost < 0.01 ? '<$0.01' : `$${totalCost.toFixed(4)}`)}
                </span>
              </div>
              {/* Message counts by role */}
              {messageCounts && (
                <div
                  className="cascade-message-counts-compact"
                  title={Object.entries(messageCounts)
                    .filter(([key]) => key !== 'total')
                    .map(([role, count]) => `${role}: ${count}`)
                    .join(', ')}
                >
                  <Icon icon="mdi:message-text" width="14" />
                  <span className="cascade-message-counts-value">
                    {/* Show roles in preferred order: user, assistant, tool, then others alphabetically */}
                    {['user', 'assistant', 'tool']
                      .filter(role => messageCounts[role])
                      .map(role => `${messageCounts[role]}${role[0]}`)
                      .join(' ')}
                    {Object.keys(messageCounts)
                      .filter(key => key !== 'total' && !['user', 'assistant', 'tool'].includes(key))
                      .sort()
                      .map(role => ` ${messageCounts[role]}${role[0]}`)
                      .join('')}
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="cascade-control-right">
          <div className="cascade-control-divider" />

          {/* Layout Toggle */}
          <div className="cascade-view-toggle">
            <Tooltip label="Linear view" description="IDE-style sequential layout">
              <button
                className={`cascade-view-btn ${layoutMode === 'linear' ? 'active' : ''}`}
                onClick={() => setLayoutMode('linear')}
              >
                <Icon icon="mdi:view-sequential" width="16" />
              </button>
            </Tooltip>
            <Tooltip label="Graph view" description="DAG structure visualization">
              <button
                className={`cascade-view-btn ${layoutMode === 'graph' ? 'active' : ''}`}
                onClick={() => setLayoutMode('graph')}
              >
                <Icon icon="mdi:graph" width="16" />
              </button>
            </Tooltip>
          </div>

          {/* Edge Legend */}
          <Tooltip
            label="Edge Legend"
            description="Cyan: Data flow • Purple: Context • Gray: Execution order • Pink: Branch/merge • Warm: Input params"
          >
            <div className="cascade-edge-legend">
              <Icon icon="mdi:information-outline" width="14" />
              <div className="legend-dots">
                <div className="legend-dot" style={{ backgroundColor: '#00e5ff' }} />
                <div className="legend-dot" style={{ backgroundColor: '#a78bfa' }} />
                <div className="legend-dot" style={{ backgroundColor: '#64748b' }} />
                <div className="legend-dot" style={{ backgroundColor: '#ff006e' }} />
                <div className="legend-dot legend-dot-gradient" />
              </div>
            </div>
          </Tooltip>

          {/* Anatomy Panel Toggle */}
          <Tooltip label="Cell Anatomy" description="Internal structure visualization">
            <Button
              variant="secondary"
              active={showAnatomyPanel}
              icon="mdi:cpu"
              onClick={() => setShowAnatomyPanel(!showAnatomyPanel)}
            >
              Anatomy
            </Button>
          </Tooltip>

          <div className="cascade-control-divider" />

          <span className="cascade-stats">
            {completedCount}/{cellCount} cells
          </span>

          {/* Open Cascade Button */}
          <Tooltip label="Open" description="Open cascade file">
            <Button
              variant="secondary"
              icon="mdi:folder-open"
              onClick={() => onOpenBrowser && onOpenBrowser()}
            >
              Open
            </Button>
          </Tooltip>

          {/* <Tooltip label="Restart" description="Clear session and start fresh">
            <Button
              variant="secondary"
              icon="mdi:restart"
              onClick={handleRestart}
            />
          </Tooltip> */}

          <Tooltip label="Save" description="Save cascade changes">
            <Button
              variant="secondary"
              icon="mdi:content-save"
              onClick={handleSave}
              disabled={!cascadeDirty && cascadePath}
            >
              Save
            </Button>
          </Tooltip>

          <Tooltip label="Save as Tool" description="Save to tackle/ as reusable tool">
            <Button
              variant="tool"
              icon="mdi:package"
              onClick={handleSaveAsTool}
            >
              As Tool
            </Button>
          </Tooltip>

        </div>
      </div>

      {/* Fixed overlay for input parameter connections - only if inputs exist */}
      {Object.keys(inputsSchema).length > 0 && (
        <InputEdgesSVG
          nodes={layout.nodes}
          inputPositions={layout.inputPositions}
          inputColorMap={layout.inputColorMap}
          timelineOffset={timelineOffset}
          timelineHeight={timelineHeight}
          scrollOffset={scrollOffset}
        />
      )}

      {/* FBP Graph Layout */}
      <div
        className={`cascade-timeline-strip ${isGrabbing ? 'grabbing' : ''}`}
        ref={timelineRef}
        onMouseDown={handleGrabStart}
        style={{
          // Use custom height if set by resize, otherwise use defaults
          height: graphPanelHeight
            ? `${graphPanelHeight}px`
            : (cells.length === 0 ? '100%' : (layoutMode === 'linear' ? '180px' : '400px')),
          minHeight: graphPanelHeight ? undefined : (cells.length === 0 ? '100%' : (layoutMode === 'linear' ? '180px' : '150px')),
          maxHeight: graphPanelHeight ? undefined : (cells.length === 0 ? 'none' : (layoutMode === 'linear' ? '180px' : '400px')),
          flex: cells.length === 0 ? 1 : undefined, // Expand to fill when empty
          cursor: isGrabbing ? 'grabbing' : 'grab',
        }}
      >
        <div
          className="cascade-fbp-canvas"
          style={{
            width: cells.length === 0 ? '100%' : `${layout.width}px`,
            height: cells.length === 0 ? '100%' : `${layout.height}px`,
            position: 'relative',
            minHeight: '100%',
            overflow: 'visible', // Allow SVG edges to extend beyond
          }}
        >
          {/* Background drop zone - always available for creating independent cells */}
          <CanvasDropZone />

          {/* SVG layer for cell-to-cell edges (scrolls with content) */}
          <CellEdgesSVG
            edges={layout.edges}
            width={layout.width}
            height={layout.height}
          />

          {/* Positioned cell cards */}
          {layout.nodes.map(node => {
            // Animation config for cell position changes
            const nodeTransition = {
              type: 'spring',
              stiffness: 300,
              damping: 30,
              mass: 0.8,
            };

            return (
              <motion.div
                key={`node-${node.cellIdx}`}
                className="fbp-node"
                style={{
                  position: 'absolute',
                  width: '240px',
                  zIndex: selectedCellIndex === node.cellIdx ? 100 : 50, // Raised above input edges
                }}
                initial={{ left: node.x, top: node.y }}
                animate={{ left: node.x, top: node.y }}
                transition={nodeTransition}
              >
                <CellCard
                  cell={node.cell}
                  index={node.cellIdx}
                  cellState={stableCellStates[node.cell.name]}
                  cellLogs={cellLogsByName[node.cell.name] || EMPTY_LOGS_ARRAY}
                  isSelected={selectedCellIndex === node.cellIdx}
                  onSelect={handleSelectCell}
                  defaultModel={defaultModel}
                />
              </motion.div>
            );
          })}

          {/* Empty state hint */}
          {cells.length === 0 && (
            <div className="cascade-empty-hint">
              <Icon icon="mdi:hand-back-left" width="32" />
              <span>Drag cell types from the sidebar to start</span>
            </div>
          )}
        </div>
      </div>

      {/* Resize handle for split panel */}
      {cells.length > 0 && (
        <div
          className="cascade-resize-handle"
          onMouseDown={handleResizeStart}
          style={{
            height: '4px',
            background: isResizing ? 'rgba(167, 139, 250, 0.5)' : 'transparent',
            cursor: 'ns-resize',
            position: 'relative',
            zIndex: 10,
            transition: isResizing ? 'none' : 'background 0.15s ease',
          }}
          onMouseEnter={(e) => {
            if (!isResizing) {
              e.currentTarget.style.background = 'rgba(167, 139, 250, 0.3)';
            }
          }}
          onMouseLeave={(e) => {
            if (!isResizing) {
              e.currentTarget.style.background = 'transparent';
            }
          }}
        >
          {/* Visual indicator dots */}
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            display: 'flex',
            gap: '4px',
            pointerEvents: 'none',
          }}>
            <div style={{ width: '3px', height: '3px', borderRadius: '50%', background: '#64748b' }} />
            <div style={{ width: '3px', height: '3px', borderRadius: '50%', background: '#64748b' }} />
            <div style={{ width: '3px', height: '3px', borderRadius: '50%', background: '#64748b' }} />
          </div>
        </div>
      )}

      {/* Bottom Detail Panel - hide completely when no cells */}
      {cells.length > 0 && (
        selectedCell ? (
          <CellDetailPanel
            cell={selectedCell}
            index={selectedCellIndex}
            cellState={stableCellStates[selectedCell.name]}
            cellLogs={cellLogsByName[selectedCell.name] || EMPTY_LOGS_ARRAY}
            allSessionLogs={logs}
            currentSessionId={sessionToPoll}
            onClose={() => setSelectedCellIndex(null)}
          />
        ) : logs.length > 0 ? (
          <SessionMessagesLog
            logs={logs}
            currentSessionId={sessionToPoll}
            onSelectCell={(cellName) => {
              const idx = cells.findIndex(c => c.name === cellName);
              if (idx !== -1) setSelectedCellIndex(idx);
            }}
          />
        ) : (
          <div className="cascade-empty-detail">
            <Icon icon="mdi:cursor-pointer" width="32" />
            <p>Select a cell above to view details</p>
          </div>
        )
      )}

      {/* Right Side Panel - Cell Anatomy */}
      {showAnatomyPanel && selectedCell && (
        <div className="cascade-anatomy-panel-container">
          <CellAnatomyPanel
            cell={selectedCell}
            cellLogs={cellLogsByName[selectedCell.name] || EMPTY_LOGS_ARRAY}
            cellState={stableCellStates[selectedCell.name]}
            onClose={() => setShowAnatomyPanel(false)}
          />
        </div>
      )}

    </div>
  );
};

export default CascadeTimeline;
