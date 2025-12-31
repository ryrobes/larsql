import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import { motion } from 'framer-motion';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useTimelinePolling from '../hooks/useTimelinePolling';
import { useBudgetData } from '../hooks/useBudgetData';
import CellCard from './CellCard';
import CellDetailPanel from './CellDetailPanel';
import { CellAnatomyPanel } from '../cell-anatomy';
import SessionMessagesLog from '../components/SessionMessagesLog';
import { Tooltip } from '../../components/RichTooltip';
import { Button, Modal, ModalHeader, ModalContent, ModalFooter, useToast } from '../../components';
import {
  buildFBPLayout,
  CARD_WIDTH,
  CARD_HEIGHT,
  INPUT_COLORS,
  getEdgeColor,
  getEdgeOpacity,
} from '../../utils/cascadeLayout';
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
  scrollOffset,
  cellCostMetrics = {}
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

  // Card dimensions imported from cascadeLayout

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
          {/* Clip to timeline bounds - excludes sidebar on left, header on top, content below */}
          <rect
            x={timelineOffset.left}
            y={timelineOffset.top}
            width={10000}
            height={timelineHeight || 400}
          />
        </clipPath>
      </defs>

      <g clipPath="url(#timeline-clip)">
        {nodes.map(node => {
          if (!node.inputDeps || node.inputDeps.length === 0) return null;

          return node.inputDeps.map(inputName => {
            const inputY = inputPositions[inputName] || 50;
            const inputColor = inputColorMap[inputName] || '#ffd700';

            // Get scale for this cell
            const cellMetrics = cellCostMetrics[node.cell?.name] || {};
            const scale = cellMetrics.scale || 1.0;

            // Calculate visual offset due to scaling
            // Scale grows from center, so card extends (scale - 1) * width / 2 on left side
            const scaleOffset = (scale - 1) * CARD_WIDTH / 2;

            const x1 = timelineOffset.left;
            const SIDEBAR_TOP = 0;
            const y1 = SIDEBAR_TOP + inputY + 52;

            // Adjust x2 to account for visual position after scaling
            const baseX2 = timelineOffset.left + (node.x - scrollOffset.x);
            const x2 = baseX2 - scaleOffset; // Move left by offset (card grew left)

            // Adjust y2 to account for vertical scaling (card center height)
            const baseY2 = timelineOffset.top + (node.y + 50 - scrollOffset.y);
            const y2 = baseY2; // Y offset is minimal for our case, keep simple

            // Don't draw if target is off-screen
            if (x2 < timelineOffset.left - 300 || x2 > window.innerWidth) return null;

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
const CellEdgesSVG = React.memo(({ edges, width, height, cellCostMetrics = {} }) => {
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

  // Card dimensions imported from cascadeLayout

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

        // Get scales for source and target cells
        const sourceMetrics = cellCostMetrics[source.cell?.name] || {};
        const targetMetrics = cellCostMetrics[target.cell?.name] || {};
        const sourceScale = sourceMetrics.scale || 1.0;
        const targetScale = targetMetrics.scale || 1.0;

        // Calculate visual offsets due to scaling
        const sourceRightOffset = (sourceScale - 1) * CARD_WIDTH / 2;
        const targetLeftOffset = (targetScale - 1) * CARD_WIDTH / 2;

        // Adjust edge endpoints to match visual card boundaries
        const x1 = source.x + CARD_WIDTH + sourceRightOffset; // Source right edge
        const y1 = source.y + CARD_HEIGHT / 2;                 // Source vertical center
        const x2 = target.x - targetLeftOffset;                // Target left edge
        const y2 = target.y + CARD_HEIGHT / 2;                 // Target vertical center

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
const CascadeTimeline = ({ onOpenBrowser, onMessageContextSelect, onLogsUpdate, onMessagesViewVisibleChange, hoveredHash, onHoverHash, gridSelectedMessage, onGridMessageSelect, onMessageFiltersChange }) => {
  //console.log('[CascadeTimeline] Component mounting/rendering');

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
  const updateAnalyticsFromPolling = useStudioCascadeStore(state => state.updateAnalyticsFromPolling);

  // Screen wipe transition state
  const [isWiping, setIsWiping] = useState(false);

  // New cascade confirmation modal
  const [showNewModal, setShowNewModal] = useState(false);

  // Save cascade modal state
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveModalPath, setSaveModalPath] = useState('');
  const [saveModalCascadeId, setSaveModalCascadeId] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // Checkpoint/blocked cell state
  const [blockedCellName, setBlockedCellName] = useState(null);

  // Toast notifications
  const { showToast } = useToast();

  // console.log('[CascadeTimeline] Store data:', {
  //   hasCascade: !!cascade,
  //   cascadeId: cascade?.cascade_id,
  //   cellsInCascade: cascade?.cells?.length || 0
  // });

  // Poll for execution updates - either live or replay session
  const sessionToPoll = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

  // SMART POLLING: In replay mode, poll once to get historical data
  // In live mode, use isRunningAll flag (which is now data-driven from the store)
  const shouldPoll = viewMode === 'replay'
    ? !!replaySessionId
    : !!(cascadeSessionId && isRunningAll);

  // console.log('[CascadeTimeline] Polling logic:', {
  //   viewMode,
  //   replaySessionId,
  //   cascadeSessionId,
  //   isRunningAll,
  //   sessionToPoll,
  //   shouldPoll,
  // });

  const { logs, cellStates: polledCellStates, totalCost, sessionStatus, sessionStatusFor, sessionError, childSessions, cascadeAnalytics, cellAnalytics } = useTimelinePolling(sessionToPoll, shouldPoll, viewMode === 'replay');

  // Get budget data for this session (use sessionToPoll and shouldPoll to match timeline polling logic)
  const { events: budgetEvents } = useBudgetData(sessionToPoll, shouldPoll);

  // Debug: Check if logs now include context data & notify parent
  useEffect(() => {
    if (logs && logs.length > 0) {
      const withContext = logs.filter(l => l.context_hashes?.length > 0);
      console.log('[CascadeTimeline] Logs with context:', {
        total: logs.length,
        withContext: withContext.length,
        sampleWithContext: withContext[0]
      });

      // Notify parent of logs update
      if (onLogsUpdate) {
        onLogsUpdate(logs);
      }
    }
  }, [logs, onLogsUpdate]);

  // Track if messages view is visible
  // True when: (no cell selected AND logs exist) OR (cell IS selected - CellDetailPanel shows messages)
  useEffect(() => {
    const hasLogs = logs && logs.length > 0;
    const isMessagesViewVisible = hasLogs && (selectedCellIndex === null || selectedCellIndex !== null);
    // Simplified: messages are visible whenever we have logs (either SessionMessagesLog or CellDetailPanel)
    console.log('[CascadeTimeline] Messages view visible:', isMessagesViewVisible, {
      selectedCellIndex,
      logsLength: logs?.length
    });

    if (onMessagesViewVisibleChange) {
      onMessagesViewVisibleChange(hasLogs);
    }
  }, [selectedCellIndex, logs, onMessagesViewVisibleChange]);

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
    if (terminalStatuses.includes(sessionStatus)) {
      // Clear blocked cell indicator when session terminates
      if (blockedCellName) {
        console.log('[CascadeTimeline] Clearing blocked cell indicator (session terminal)');
        setBlockedCellName(null);
      }

      if (isRunningAll) {
        console.log(`[CascadeTimeline] ⚠️ SETTING isRunningAll = FALSE due to terminal status:`, {
          sessionId: cascadeSessionId,
          sessionStatus,
          sessionError
        });

        // Update the store to stop execution
        useStudioCascadeStore.setState({ isRunningAll: false });
      }
    }
  }, [sessionStatus, sessionStatusFor, cascadeSessionId, isRunningAll, sessionError, sessionToPoll, blockedCellName]);

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

  // Poll for pending checkpoints to detect blocked cells
  // Use cascadeSessionId (live) or replaySessionId (replay mode)
  const checkpointSessionId = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

  useEffect(() => {
    console.log('[CascadeTimeline] Checkpoint polling setup:', { checkpointSessionId, cascadeSessionId, viewMode });

    if (!checkpointSessionId) {
      setBlockedCellName(null);
      return;
    }

    const fetchCheckpoint = async () => {
      try {
        const res = await fetch('http://localhost:5050/api/checkpoints');
        const data = await res.json();

        if (data.error) return;

        // Find pending checkpoint for current session
        const pending = (data.checkpoints || []).find(
          cp => cp.status === 'pending' && cp.session_id === checkpointSessionId
        );

        console.log('[CascadeTimeline] Checkpoint check:', {
          checkpointSessionId,
          foundCell: pending?.cell_name,
          pendingCount: (data.checkpoints || []).filter(cp => cp.status === 'pending').length
        });

        setBlockedCellName(pending?.cell_name || null);
      } catch (err) {
        // Silently ignore - not critical
      }
    };

    // Initial fetch
    fetchCheckpoint();

    // Poll every 2 seconds while running, 5 seconds otherwise
    const interval = setInterval(fetchCheckpoint, isRunningAll ? 2000 : 5000);

    return () => clearInterval(interval);
  }, [checkpointSessionId, isRunningAll]);

  // Update analytics when polling returns new data
  const prevAnalyticsHashRef = useRef('');
  useEffect(() => {
    if (!cascadeAnalytics && (!cellAnalytics || Object.keys(cellAnalytics).length === 0)) return;

    const currentHash = JSON.stringify({ cascadeAnalytics, cellAnalytics });
    if (currentHash === prevAnalyticsHashRef.current) return;

    console.log('[CascadeTimeline] Updating analytics from polling:', {
      hasCascadeAnalytics: !!cascadeAnalytics,
      cellAnalyticsCount: Object.keys(cellAnalytics || {}).length
    });
    prevAnalyticsHashRef.current = currentHash;
    updateAnalyticsFromPolling(cascadeAnalytics, cellAnalytics);
  }, [cascadeAnalytics, cellAnalytics, updateAnalyticsFromPolling]);

  const timelineRef = useRef(null);
  const [layoutMode, setLayoutMode] = useState('linear'); // 'linear' or 'graph'
  const [scrollOffset, setScrollOffset] = useState({ x: 0, y: 0 });
  const [timelineOffset, setTimelineOffset] = useState({ left: 0, top: 0 });
  const [timelineHeight, setTimelineHeight] = useState(0); // Actual measured height for clipping
  const [showAnatomyPanel, setShowAnatomyPanel] = useState(false); // Cell anatomy visualization

  // Split panel resize state (with localStorage persistence)
  const [graphPanelHeight, setGraphPanelHeight] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-graph-panel-height');
      return saved ? parseInt(saved, 10) : null;
    } catch {
      return null; // null = use default heights
    }
  });
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
    if (target.closest('.cell-card, button, input, textarea, .cascade-drop-zone')) return;

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
    // Save to localStorage
    if (graphPanelHeight !== null) {
      try {
        localStorage.setItem('studio-graph-panel-height', String(graphPanelHeight));
      } catch (e) {
        console.warn('Failed to save graph panel height to localStorage:', e);
      }
    }
  }, [graphPanelHeight]);

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

  const handleDescriptionChange = (e) => {
    updateCascade({ description: e.target.value });
  };


  // Open save modal (for both new and existing cascades)
  const handleSave = () => {
    // Set default path: existing path or cascades/<cascade_id>.yaml
    const defaultPath = cascadePath || `cascades/${cascade?.cascade_id || 'cascade'}.yaml`;
    setSaveModalPath(defaultPath);
    setSaveModalCascadeId(cascade?.cascade_id || '');
    setShowSaveModal(true);
  };

  // Execute the actual save with error handling
  const executeSave = async () => {
    if (!saveModalPath.trim()) {
      showToast('Please enter a file path', { type: 'error' });
      return;
    }

    if (!saveModalCascadeId.trim()) {
      showToast('Please enter a cascade ID', { type: 'error' });
      return;
    }

    setIsSaving(true);

    try {
      // Update cascade_id if it changed
      if (saveModalCascadeId !== cascade?.cascade_id) {
        updateCascade({ cascade_id: saveModalCascadeId });
      }

      // Perform save
      await saveCascade(saveModalPath);

      showToast(`Saved to ${saveModalPath}`, { type: 'success' });
      setShowSaveModal(false);
    } catch (err) {
      console.error('Failed to save cascade:', err);
      showToast(`Failed to save: ${err.message}`, { type: 'error', duration: 6000 });
    } finally {
      setIsSaving(false);
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all outputs.')) {
      await restartSession();
    }
  };

  const handleNew = async () => {
    // If dirty, show confirmation modal
    if (cascadeDirty) {
      setShowNewModal(true);
      return;
    }

    // No unsaved changes, proceed directly
    executeNewCascade();
  };

  const executeNewCascade = () => {
    setShowNewModal(false);

    // Trigger screen wipe effect
    setIsWiping(true);

    // Wait for wipe animation to cover screen
    setTimeout(() => {
      newCascade();
      // Wait for new cascade to load, then reverse wipe
      setTimeout(() => {
        setIsWiping(false);
      }, 100);
    }, 500); // Duration of wipe animation
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

  // Memoized cell selection callback - toggle behavior
  const handleSelectCell = useCallback((index) => {
    // Toggle: if already selected, deselect (set to null)
    setSelectedCellIndex(selectedCellIndex === index ? null : index);
  }, [selectedCellIndex, setSelectedCellIndex]);

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

  // Calculate cost metrics for each cell (needs stableCellStates, before layout)
  // Uses pre-computed cellAnalytics when available, falls back to per-run calculation
  const cellCostMetrics = useMemo(() => {
    if (!cells || cells.length === 0) return {};

    console.log('[CascadeTimeline] Calculating cellCostMetrics, cellAnalytics:', cellAnalytics);

    const metrics = {};
    let totalCascadeCost = 0;

    // First pass: collect costs
    cells.forEach(cell => {
      const cost = stableCellStates[cell.name]?.cost || 0;
      metrics[cell.name] = { cost };
      totalCascadeCost += cost;
    });

    // Second pass: enhance with analytics data when available
    Object.keys(metrics).forEach(cellName => {
      const cost = metrics[cellName].cost;
      const duration = stableCellStates[cellName]?.duration || 0;

      // Check if we have pre-computed cell analytics
      const analytics = cellAnalytics?.[cellName];
      if (analytics) {
        console.log(`[CascadeTimeline] Using analytics for ${cellName}:`, analytics);
      }

      let costMultiplier = null;  // vs species avg (historical comparison)
      let cellCostPct = 0;        // % of cascade cost (bottleneck indicator)
      let isOutlier = false;
      let speciesAvgCost = 0;
      let speciesRunCount = 0;

      if (analytics && analytics.species_avg_cost > 0) {
        // Use pre-computed analytics
        costMultiplier = cost / analytics.species_avg_cost;
        cellCostPct = analytics.cell_cost_pct || 0;
        isOutlier = analytics.is_cost_outlier || false;
        speciesAvgCost = analytics.species_avg_cost;
        speciesRunCount = analytics.species_run_count || 0;
      } else {
        // Fall back to per-run calculation (% of cascade cost)
        cellCostPct = totalCascadeCost > 0 ? (cost / totalCascadeCost) * 100 : 0;
      }

      // Scale based on cell_cost_pct (bottleneck detection)
      // High % of cascade = larger card
      let scale = 1.0;
      if (cellCostPct > 60) scale = 1.3;       // Major bottleneck
      else if (cellCostPct > 40) scale = 1.2;  // Significant bottleneck
      else if (cellCostPct > 25) scale = 1.1;  // Notable
      else if (cellCostPct < 10) scale = 0.9;  // Cheap
      else if (cellCostPct < 5) scale = 0.85;  // Very cheap

      // Color based on historical comparison or bottleneck status
      let color = 'cyan';
      if (isOutlier) {
        color = 'red';  // Statistical outlier (vs history)
      } else if (costMultiplier && costMultiplier >= 1.5) {
        color = 'red';  // 1.5x+ more expensive than usual
      } else if (costMultiplier && costMultiplier >= 1.2) {
        color = 'orange';  // 1.2x+ more expensive
      } else if (costMultiplier && costMultiplier <= 0.7) {
        color = 'green';  // 0.7x or cheaper than usual
      } else if (cellCostPct > 50) {
        color = 'orange';  // Major bottleneck (no historical data)
      }

      metrics[cellName] = {
        cost,
        duration,
        scale,
        color,
        // New analytics-based metrics (for CellCard to display)
        cellCostPct,              // "42% of cascade" (bottleneck indicator)
        costMultiplier,           // "1.5x avg" (vs historical)
        isOutlier,                // true/false (statistical outlier)
        speciesAvgCost,           // Avg cost for this cell config
        speciesRunCount,          // How many runs in the comparison
        // Legacy field for backwards compatibility
        costDeltaPct: costMultiplier ? (costMultiplier - 1) * 100 : 0,
      };
    });

    return metrics;
  }, [cells, stableCellStates, cellAnalytics]);

  // Layout must come after cellCostMetrics
  const layout = useMemo(
    () => {
      const result = buildFBPLayout(cells, inputsSchema, layoutMode === 'linear', cellCostMetrics);
      console.log('[CascadeTimeline] FBP Layout built:', {
        cellsInput: cells.length,
        nodesOutput: result.nodes.length,
        edgesOutput: result.edges.length,
        width: result.width,
        height: result.height
      });
      return result;
    },
    [cells, inputsSchema, layoutMode, cellCostMetrics]
  );

  // Count messages by role, filtering out system messages (cell_*)
  let messageCounts = null;
  if (logs && logs.length > 0) {
    const counts = {};
    let total = 0;
    for (const log of logs) {
      const role = log.role;
      // Skip system messages (cell_start, cell_complete, etc.)
      if (role && !role.startsWith('cell_')) {
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
          {/* <div className="cascade-view-toggle">
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
          </div> */}

          {/* Edge Legend */}
          <Tooltip
            label="Edge Legend"
            description="Cyan: Data flow • Purple: Context • Gray: Execution order • Pink: Branch/merge • Warm: Input params"
          >
            <div className="cascade-edge-legend">
              {/* <Icon icon="mdi:information-outline" width="14" /> */}
              <div className="legend-dots">
                <div className="legend-dot" style={{ backgroundColor: '#00e5ff' }} />
                <div className="legend-dot" style={{ backgroundColor: '#a78bfa' }} />
                <div className="legend-dot" style={{ backgroundColor: '#64748b' }} />
                <div className="legend-dot" style={{ backgroundColor: '#ff006e' }} />
                <div className="legend-dot legend-dot-gradient" />
              </div>
            </div>
          </Tooltip>

          <div className="cascade-control-divider" />

          {/* <span className="cascade-stats">
            {completedCount}/{cellCount} cells
          </span> */}

          {/* New Cascade Button */}
          <Tooltip label="New" description="Create blank cascade">
            <Button
              variant="secondary"
              icon="mdi:file-plus-outline"
              onClick={handleNew}
            >
              New
            </Button>
          </Tooltip>

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

          <Tooltip label="Clear" description="Clear session and start fresh">
            <Button
              variant="secondary"
              icon="mdi:restart"
              onClick={handleRestart}
            > Clear </Button>
          </Tooltip>

          <Tooltip label="Save" description="Save cascade changes">
            <Button
              variant="tool"
              icon="mdi:content-save"
              onClick={handleSave}
              disabled={!cascadeDirty && cascadePath}
            >
              Save
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
          cellCostMetrics={cellCostMetrics}
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
            cellCostMetrics={cellCostMetrics}
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
                  costMetrics={cellCostMetrics[node.cell.name]}
                  isBlocked={blockedCellName === node.cell.name}
                />
                {/* Budget Enforcement Annotation - above node, right-aligned (like cost below) */}
                {budgetEvents && budgetEvents.filter(e => e.cell_name === node.cell.name).length > 0 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: '-32px',
                      right: '0',
                      fontSize: '11px',
                      fontFamily: 'IBM Plex Mono, monospace',
                      fontWeight: '700',
                      color: '#fbbf24',
                      whiteSpace: 'nowrap',
                      textShadow: '0 0 6px rgba(0, 0, 0, 0.9), 0 0 3px rgba(0, 0, 0, 1)',
                      cursor: 'help',
                    }}
                    title={`Budget enforced: ${budgetEvents.filter(e => e.cell_name === node.cell.name).map(e => `-${((e.budget_tokens_pruned || 0) / 1000).toFixed(1)}K tokens`).join(', ')}`}
                  >
                    💥 {budgetEvents.filter(e => e.cell_name === node.cell.name).reduce((sum, e) => sum + (e.budget_tokens_pruned || 0), 0) >= 1000
                      ? `-${(budgetEvents.filter(e => e.cell_name === node.cell.name).reduce((sum, e) => sum + (e.budget_tokens_pruned || 0), 0) / 1000).toFixed(1)}K`
                      : `-${budgetEvents.filter(e => e.cell_name === node.cell.name).reduce((sum, e) => sum + (e.budget_tokens_pruned || 0), 0)}`
                    }
                  </div>
                )}
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
            hoveredHash={hoveredHash}
            onHoverHash={onHoverHash}
            externalSelectedMessage={gridSelectedMessage}
            onMessageClick={(message) => {
              // Update grid selection state
              if (onGridMessageSelect) {
                onGridMessageSelect(message);
              }
              // Notify parent for context explorer
              if (onMessageContextSelect) {
                onMessageContextSelect(message);
              }
            }}
          />
        ) : logs.length > 0 ? (
          <SessionMessagesLog
            logs={logs}
            currentSessionId={sessionToPoll}
            shouldPollBudget={shouldPoll}
            hoveredHash={hoveredHash}
            onHoverHash={onHoverHash}
            externalSelectedMessage={gridSelectedMessage}
            onSelectCell={(cellName) => {
              const idx = cells.findIndex(c => c.name === cellName);
              if (idx !== -1) setSelectedCellIndex(idx);
            }}
            onMessageClick={(message) => {
              // Update grid selection state
              if (onGridMessageSelect) {
                onGridMessageSelect(message);
              }
              // Always notify parent (handles deselect and non-context messages)
              if (onMessageContextSelect) {
                onMessageContextSelect(message);
              }
            }}
            onFiltersChange={onMessageFiltersChange}
          />
        ) : (
          <div className="cascade-empty-detail">
            <Icon icon="mdi:cursor-pointer" width="32" />
            <p>Select a cell above to view details</p>
          </div>
        )
      )}

      {/* Right Edge Anatomy Tab - Only show when cell is selected */}
      {selectedCell && (
        <div
          className={`cascade-anatomy-edge-tab ${showAnatomyPanel ? 'active' : ''}`}
          onClick={() => setShowAnatomyPanel(!showAnatomyPanel)}
          title="Cell Anatomy - Internal structure visualization"
        >
          <Icon icon="mdi:cogs" width="20" />
          <span className="cascade-anatomy-edge-label">Anatomy</span>
        </div>
      )}

      {/* Right Side Panel - Cell Anatomy */}
      {showAnatomyPanel && selectedCell && (
        <div className="cascade-anatomy-panel-container">
          <CellAnatomyPanel
            cell={selectedCell}
            cellLogs={cellLogsByName[selectedCell.name] || EMPTY_LOGS_ARRAY}
            cellState={stableCellStates[selectedCell.name]}
            onClose={() => setShowAnatomyPanel(false)}
            cascadeAnalytics={cascadeAnalytics}
            cellAnalytics={cellAnalytics?.[selectedCell.name]}
          />
        </div>
      )}

      {/* Screen Wipe Transition - Cyberpunk GPU Effect */}
      {isWiping && (
        <>
          {/* Main gradient wipe */}
          <motion.div
            className="cascade-screen-wipe"
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{
              duration: 0.5,
              ease: [0.87, 0, 0.13, 1]
            }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              background: 'linear-gradient(90deg, #000000 0%, #001a1a 20%, #003366 60%, #00e5ff 100%)',
              transformOrigin: 'left',
              zIndex: 9998,
              pointerEvents: 'none'
            }}
          />

          {/* Scanlines overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2, delay: 0.1 }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              background: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0, 229, 255, 0.03) 2px, rgba(0, 229, 255, 0.03) 4px)',
              zIndex: 9999,
              pointerEvents: 'none'
            }}
          />

          {/* Grid overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.15 }}
            transition={{ duration: 0.3, delay: 0.15 }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              backgroundImage: `
                linear-gradient(rgba(0, 229, 255, 0.1) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 229, 255, 0.1) 1px, transparent 1px)
              `,
              backgroundSize: '50px 50px',
              zIndex: 10000,
              pointerEvents: 'none'
            }}
          />

          {/* Glowing edge accent */}
          <motion.div
            initial={{ scaleX: 0, opacity: 0 }}
            animate={{ scaleX: 1, opacity: 1 }}
            transition={{
              duration: 0.5,
              ease: [0.87, 0, 0.13, 1]
            }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              boxShadow: 'inset -3px 0 20px rgba(0, 229, 255, 0.8), inset -10px 0 60px rgba(167, 139, 250, 0.4)',
              transformOrigin: 'left',
              zIndex: 10001,
              pointerEvents: 'none'
            }}
          />
        </>
      )}

      {/* Confirmation Modal for New Cascade */}
      <Modal
        isOpen={showNewModal}
        onClose={() => setShowNewModal(false)}
        size="small"
      >
        <ModalHeader
          icon="mdi:alert-circle-outline"
          title="Unsaved Changes"
          iconColor="#fbbf24"
        />
        <ModalContent>
          <p style={{ marginBottom: '12px', color: '#cbd5e1' }}>
            You have unsaved changes to the current cascade.
          </p>
          <p style={{ color: '#94a3b8' }}>
            Creating a new cascade will discard these changes.
          </p>
        </ModalContent>
        <ModalFooter align="right">
          <Button
            variant="secondary"
            onClick={() => setShowNewModal(false)}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            icon="mdi:file-plus-outline"
            onClick={executeNewCascade}
          >
            Create New
          </Button>
        </ModalFooter>
      </Modal>

      {/* Save Cascade Modal */}
      <Modal
        isOpen={showSaveModal}
        onClose={() => setShowSaveModal(false)}
        size="sm"
      >
        <ModalHeader
          icon="mdi:content-save"
          title="Save Cascade"
        />
        <ModalContent>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Cascade ID field */}
            <div>
              <label style={{
                display: 'block',
                marginBottom: '6px',
                color: '#94a3b8',
                fontSize: '12px',
                fontWeight: 500
              }}>
                Cascade ID
              </label>
              <input
                type="text"
                value={saveModalCascadeId}
                onChange={(e) => setSaveModalCascadeId(e.target.value)}
                placeholder="my_cascade"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  backgroundColor: '#0a0818',
                  border: '1px solid #1e1b4b',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontSize: '14px',
                  fontFamily: 'monospace'
                }}
              />
              <p style={{
                marginTop: '4px',
                color: '#64748b',
                fontSize: '11px'
              }}>
                Unique identifier for this cascade. Change if saving a copy.
              </p>
            </div>

            {/* File path field */}
            <div>
              <label style={{
                display: 'block',
                marginBottom: '6px',
                color: '#94a3b8',
                fontSize: '12px',
                fontWeight: 500
              }}>
                File Path
              </label>
              <input
                type="text"
                value={saveModalPath}
                onChange={(e) => setSaveModalPath(e.target.value)}
                placeholder="cascades/my_cascade.yaml"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  backgroundColor: '#0a0818',
                  border: '1px solid #1e1b4b',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontSize: '14px',
                  fontFamily: 'monospace'
                }}
              />
              <p style={{
                marginTop: '4px',
                color: '#64748b',
                fontSize: '11px'
              }}>
                Relative to RVBBIT root. Use <code style={{ color: '#a78bfa' }}>cascades/</code> for cascades or <code style={{ color: '#a78bfa' }}>traits/</code> for reusable tools.
              </p>
            </div>

            {/* Warning about duplicate IDs */}
            {cascadePath && saveModalPath !== cascadePath && (
              <div style={{
                padding: '10px 12px',
                backgroundColor: 'rgba(251, 191, 36, 0.1)',
                border: '1px solid rgba(251, 191, 36, 0.3)',
                borderRadius: '6px',
                display: 'flex',
                gap: '8px',
                alignItems: 'flex-start'
              }}>
                <Icon icon="mdi:alert" style={{ color: '#fbbf24', flexShrink: 0, marginTop: '2px' }} />
                <p style={{ color: '#fbbf24', fontSize: '12px', margin: 0 }}>
                  Saving to a different path. Consider changing the Cascade ID to avoid duplicates.
                </p>
              </div>
            )}
          </div>
        </ModalContent>
        <ModalFooter align="right">
          <Button
            variant="secondary"
            onClick={() => setShowSaveModal(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={isSaving ? "mdi:loading" : "mdi:content-save"}
            onClick={executeSave}
            disabled={isSaving}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </Button>
        </ModalFooter>
      </Modal>

    </div>
  );
};

export default CascadeTimeline;
