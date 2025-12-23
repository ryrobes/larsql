import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useTimelinePolling from '../hooks/useTimelinePolling';
import PhaseCard from './PhaseCard';
import PhaseDetailPanel from './PhaseDetailPanel';
import './CascadeTimeline.css';

/**
 * Build FBP-style layered graph layout
 * Returns positioned nodes and edges for rendering
 *
 * @param {boolean} linearMode - If true, arrange in single row instead of DAG layers
 */
const buildFBPLayout = (phases, inputsSchema, linearMode = false) => {
  if (!phases || phases.length === 0) return { nodes: [], edges: [], width: 0, height: 0, inputPositions: {} };

  // Calculate input parameter positions in sidebar
  const inputPositions = {};
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
    });

    console.log('[FBP] Input positions:', inputPositions);
  }

  // Build dependency graph
  const graph = {};
  const inDegree = {};
  const outDegree = {};

  phases.forEach((phase, idx) => {
    graph[idx] = {
      phase,
      name: phase.name,
      handoffs: phase.handoffs || [],
      targets: [],
      sources: [],
      implicitDeps: [],
      inputDeps: [], // Track {{ input.X }} references
    };
    inDegree[idx] = 0;
    outDegree[idx] = 0;
  });

  // Extract dependencies from {{ outputs.X }} AND {{ input.X }}
  phases.forEach((phase, idx) => {
    const phaseYaml = JSON.stringify(phase);
    const outputDeps = new Set();
    const inputRefs = new Set();

    // {{ outputs.phase_name }} references
    const outputsPattern = /\{\{\s*outputs\.(\w+)/g;
    let match;
    while ((match = outputsPattern.exec(phaseYaml)) !== null) {
      const depIdx = phases.findIndex(p => p.name === match[1]);
      if (depIdx !== -1 && depIdx !== idx) outputDeps.add(depIdx);
    }

    // {{ input.param_name }} references
    const inputPattern = /\{\{\s*input\.(\w+)/g;
    while ((match = inputPattern.exec(phaseYaml)) !== null) {
      inputRefs.add(match[1]);
    }

    graph[idx].implicitDeps = Array.from(outputDeps);
    graph[idx].inputDeps = Array.from(inputRefs);
  });

  // Build edges from BOTH handoffs (explicit) AND implicit deps
  phases.forEach((phase, idx) => {
    // Explicit handoffs
    const handoffs = phase.handoffs || [];
    handoffs.forEach(targetName => {
      const targetIdx = phases.findIndex(p => p.name === targetName);
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

    // Implicit dependencies (reverse direction: this phase depends ON others)
    graph[idx].implicitDeps.forEach(depIdx => {
      // depIdx → idx (dependency feeds into this phase)
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
  const remaining = new Set(phases.map((_, i) => i));

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

  console.log('[FBP] Layers:', layers.map((l, i) => `L${i}:[${l.map(idx => phases[idx].name).join(',')}]`));

  // Position nodes
  const nodes = [];

  if (linearMode) {
    // Linear mode: single horizontal row (array order)
    phases.forEach((phase, idx) => {
      const x = PADDING_LEFT + (idx * (CARD_WIDTH + HORIZONTAL_GAP));
      const y = PADDING_TOP;

      nodes.push({
        phaseIdx: idx,
        phase: phases[idx],
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

      layer.forEach((phaseIdx, posInLayer) => {
        const y = PADDING_TOP + (posInLayer * (CARD_HEIGHT + VERTICAL_GAP));

        nodes.push({
          phaseIdx,
          phase: phases[phaseIdx],
          x,
          y,
          layer: layerIdx,
          isBranch: outDegree[phaseIdx] > 1,
          isMerge: inDegree[phaseIdx] > 1,
          inputDeps: graph[phaseIdx].inputDeps,
        });
      });
    });
  }

  // Build edges
  const edges = [];
  nodes.forEach(node => {
    graph[node.phaseIdx].targets.forEach(targetIdx => {
      const targetNode = nodes.find(n => n.phaseIdx === targetIdx);
      if (targetNode) {
        edges.push({
          source: node,
          target: targetNode,
          isSpecial: node.isBranch || targetNode.isMerge,
        });
      }
    });
  });

  // Calculate canvas dimensions
  const width = linearMode
    ? phases.length * (CARD_WIDTH + HORIZONTAL_GAP) + PADDING_LEFT + PADDING_RIGHT
    : layers.length * (CARD_WIDTH + HORIZONTAL_GAP) + PADDING_LEFT + PADDING_RIGHT;

  const maxNodesInLayer = linearMode ? 1 : Math.max(...layers.map(l => l.length), 1);
  const height = linearMode
    ? CARD_HEIGHT + (PADDING_TOP * 2) // Compact height for linear
    : maxNodesInLayer * (CARD_HEIGHT + VERTICAL_GAP) + PADDING_TOP * 2;

  return { nodes, edges, width, height, inputPositions };
};

/**
 * DropZone - Visual drop target between phases
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
 * CascadeTimeline - Horizontal cascade builder (DAW-style)
 *
 * Layout:
 * - Top bar: Cascade controls + metadata
 * - Middle strip: Horizontal scrolling phase cards (left→right) with drop zones
 * - Bottom panel: Selected phase details (config, code, outputs)
 */
const CascadeTimeline = ({ onOpenBrowser }) => {
  const {
    cascade,
    cascadePath,
    cascadeDirty,
    cellStates,
    isRunningAll,
    cascadeSessionId,
    viewMode,
    replaySessionId,
    sessionId,
    cascades,
    fetchCascades,
    loadCascade,
    newCascade,
    addCell,
    restartSession,
    updateCascade,
    saveCascade,
    selectedPhaseIndex,
    setSelectedPhaseIndex,
    setLiveMode,
    updateCellStatesFromPolling,
    defaultModel,
  } = useStudioCascadeStore();

  // Poll for execution updates - either live or replay session
  const sessionToPoll = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

  // SMART POLLING: In replay mode, poll once to get historical data
  // In live mode, use isRunningAll flag (which is now data-driven from the store)
  const shouldPoll = viewMode === 'replay'
    ? !!replaySessionId
    : !!(cascadeSessionId && isRunningAll);

  const { logs, phaseStates, totalCost } = useTimelinePolling(sessionToPoll, shouldPoll);

  console.log('[CascadeTimeline] Polling decision:', {
    viewMode,
    sessionToPoll,
    isRunningAll,
    shouldPoll,
    phaseCount: Object.keys(phaseStates || {}).length
  });

  // Debug polling state
  React.useEffect(() => {
    if (sessionToPoll) {
      console.log('[CascadeTimeline] Polling state:', {
        viewMode,
        sessionToPoll,
        shouldPoll,
        logsCount: logs.length,
        phaseStatesKeys: Object.keys(phaseStates || {}),
        totalCost
      });
    }
  }, [viewMode, sessionToPoll, shouldPoll, logs.length, phaseStates, totalCost]);

  // Update cellStates when polling returns new data
  const prevPhaseStatesHashRef = useRef('');
  useEffect(() => {
    if (!phaseStates || Object.keys(phaseStates).length === 0) {
      //console.log('[CascadeTimeline] No phaseStates to update');
      return;
    }

    // Only update if data actually changed (cheap hash check)
    const currentHash = JSON.stringify(phaseStates);
    if (currentHash === prevPhaseStatesHashRef.current) {
      //console.log('[CascadeTimeline] phaseStates unchanged, skipping update');
      return;
    }

    //console.log('[CascadeTimeline] Updating cellStates from polling:', Object.keys(phaseStates));
    prevPhaseStatesHashRef.current = currentHash;
    updateCellStatesFromPolling(phaseStates);
  }, [phaseStates, updateCellStatesFromPolling]);

  const timelineRef = useRef(null);
  const [layoutMode, setLayoutMode] = useState('linear'); // 'linear' or 'graph'
  const [scrollOffset, setScrollOffset] = useState({ x: 0, y: 0 });
  const [timelineOffset, setTimelineOffset] = useState({ left: 0, top: 0 });

  // Measure timeline position relative to viewport (for input lines)
  useEffect(() => {
    const stripEl = timelineRef.current;
    if (!stripEl) return;

    const updateOffset = () => {
      const rect = stripEl.getBoundingClientRect();
      setTimelineOffset({
        left: rect.left, // Distance from viewport left (vertical sidebar + left panel)
        top: rect.top,   // Distance from viewport top (control bar)
      });
    };

    updateOffset();

    // Update on resize and when split panel moves
    window.addEventListener('resize', updateOffset);

    // Use ResizeObserver to detect split panel changes
    const resizeObserver = new ResizeObserver(updateOffset);
    const parent = stripEl.parentElement;
    if (parent) resizeObserver.observe(parent);

    return () => {
      window.removeEventListener('resize', updateOffset);
      resizeObserver.disconnect();
    };
  }, []);

  // Track scroll position for input edges
  useEffect(() => {
    const stripEl = timelineRef.current;
    if (!stripEl) return;

    const handleScroll = () => {
      setScrollOffset({
        x: stripEl.scrollLeft,
        y: stripEl.scrollTop,
      });
    };

    stripEl.addEventListener('scroll', handleScroll, { passive: true });
    return () => stripEl.removeEventListener('scroll', handleScroll);
  }, []);

  // Build FBP layout (must be before early returns)
  const phases = cascade?.phases || [];
  const inputsSchema = cascade?.inputs_schema || {};
  const layout = useMemo(
    () => buildFBPLayout(phases, inputsSchema, layoutMode === 'linear'),
    [phases, inputsSchema, layoutMode]
  );

  const handleTitleChange = (e) => {
    updateCascade({ cascade_id: e.target.value });
  };

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

  // Create new cascade if none exists (same pattern as NotebookEditor)
  useEffect(() => {
    if (!cascade) {
      newCascade();
    }
  }, [cascade, newCascade]);

  const handleSelectPhase = (index) => {
    setSelectedPhaseIndex(index);
  };

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

  const selectedPhase = selectedPhaseIndex !== null ? phases[selectedPhaseIndex] : null;
  const cellCount = phases.length;
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
        {/* Top Control Bar */}
        <div className="cascade-control-bar">
        <div className="cascade-control-left">
          <input
            className="cascade-title-input"
            value={cascade.cascade_id || ''}
            onChange={handleTitleChange}
            placeholder="cascade_name"
          />
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
            <button
              className={`cascade-view-btn ${layoutMode === 'linear' ? 'active' : ''}`}
              onClick={() => setLayoutMode('linear')}
              title="Linear view (IDE mode)"
            >
              <Icon icon="mdi:view-sequential" width="16" />
            </button>
            <button
              className={`cascade-view-btn ${layoutMode === 'graph' ? 'active' : ''}`}
              onClick={() => setLayoutMode('graph')}
              title="Graph view (DAG structure)"
            >
              <Icon icon="mdi:graph" width="16" />
            </button>
          </div>

          <div className="cascade-control-divider" />

          <span className="cascade-stats">
            {completedCount}/{cellCount} phases
          </span>

          {/* Open Cascade Button */}
          <button
            className="cascade-btn cascade-btn-secondary"
            onClick={() => onOpenBrowser && onOpenBrowser()}
            title="Open cascade file"
          >
            <Icon icon="mdi:folder-open" width="16" />
            Open
          </button>

          <button
            className="cascade-btn cascade-btn-secondary"
            onClick={handleRestart}
            title="Restart session"
          >
            <Icon icon="mdi:restart" width="16" />
          </button>

          <button
            className="cascade-btn cascade-btn-secondary"
            onClick={handleSave}
            disabled={!cascadeDirty && cascadePath}
          >
            <Icon icon="mdi:content-save" width="16" />
            Save
          </button>

          <button
            className="cascade-btn cascade-btn-tool"
            onClick={handleSaveAsTool}
            title="Save to tackle/ as reusable tool"
          >
            <Icon icon="mdi:package" width="16" />
            As Tool
          </button>

        </div>
      </div>

      {/* Fixed overlay for input parameter connections */}
      <svg
        className="cascade-input-edges"
        style={{
          position: 'fixed',
          left: 0,
          top: 0,
          width: '100vw',
          height: '100vh',
          pointerEvents: 'none',
          zIndex: 5, // Above background
        }}
      >
        {/* Clip path to cut off lines at editor panel boundary */}
        <defs>
          <clipPath id="timeline-clip">
            <rect
              x="0"
              y="0"
              width="100%"
              height={timelineOffset.top + (timelineRef.current?.clientHeight || 0)}
            />
          </clipPath>
        </defs>

        <g clipPath="url(#timeline-clip)">
          {/* Input parameter edges - from sidebar to phases (stays fixed during scroll) */}
          {layout.nodes.map(node => {
          if (!node.inputDeps || node.inputDeps.length === 0) return null;

          return node.inputDeps.map(inputName => {
            // Get calculated Y position for this input in sidebar
            const inputY = layout.inputPositions[inputName] || 50;

            // VIEWPORT coordinates (since SVG is position:fixed)
            // x1: Right edge of left panel (timelineOffset.left = left edge of timeline)
            const x1 = timelineOffset.left;

            // y1: Input field position in viewport
            // Left panel starts at viewport top (y=0)
            const y1 = inputY + 90; // Source: move down more

            // x2: Phase card left edge, y2: connection point on card
            const x2 = timelineOffset.left + (node.x - scrollOffset.x);
            // Connect to upper portion of card
            const y2 = timelineOffset.top + (node.y + 40 - scrollOffset.y); // Destination: move up more

            // Don't draw if target is off-screen
            if (x2 < timelineOffset.left - 240 || x2 > window.innerWidth) return null;

            const dx = x2 - x1;
            const cx1 = x1 + Math.min(60, dx * 0.3);
            const cx2 = x2 - Math.min(60, dx * 0.3);

            return (
              <path
                key={`input-${node.phaseIdx}-${inputName}`}
                d={`M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`}
                stroke="#ffd700"
                strokeWidth="2.5"
                fill="none"
                opacity="0.7"
                strokeLinecap="round"
                strokeDasharray="5 5"
              />
            );
          });
        })}
        </g>
      </svg>

      {/* FBP Graph Layout */}
      <div
        className="cascade-timeline-strip"
        ref={timelineRef}
        style={{
          minHeight: layoutMode === 'linear' ? '180px' : '150px',
          maxHeight: layoutMode === 'linear' ? '180px' : '400px',
        }}
      >
        <div
          className="cascade-fbp-canvas"
          style={{
            width: `${layout.width}px`,
            height: `${layout.height}px`,
            position: 'relative',
            minHeight: '100%',
          }}
        >
          {/* SVG layer for phase-to-phase edges (scrolls with content) */}
          <svg
            className="cascade-edges"
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              zIndex: 0,
            }}
          >
            {/* Phase-to-phase edges */}
            {layout.edges.map((edge, idx) => {
              const { source, target, isSpecial } = edge;

              // Connection points: right side of source to left side of target
              const x1 = source.x + 240; // Right edge of source card
              const y1 = source.y + 65;  // Center of source card
              const x2 = target.x;       // Left edge of target card
              const y2 = target.y + 65;  // Center of target card

              const color = isSpecial ? '#ff006e' : '#00e5ff';
              const opacity = isSpecial ? 0.7 : 0.5;

              // Bezier curve for smooth connections
              const dx = x2 - x1;
              const cx1 = x1 + dx * 0.5;
              const cx2 = x2 - dx * 0.5;

              return (
                <path
                  key={`edge-${idx}`}
                  d={`M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`}
                  stroke={color}
                  strokeWidth="3"
                  fill="none"
                  opacity={opacity}
                  strokeLinecap="round"
                />
              );
            })}
          </svg>

          {/* Positioned phase cards */}
          {layout.nodes.map(node => (
            <div
              key={`node-${node.phaseIdx}`}
              className="fbp-node"
              style={{
                position: 'absolute',
                left: `${node.x}px`,
                top: `${node.y}px`,
                width: '240px',
                zIndex: selectedPhaseIndex === node.phaseIdx ? 100 : 50, // Raised above input edges
              }}
            >
              <PhaseCard
                phase={node.phase}
                index={node.phaseIdx}
                cellState={cellStates[node.phase.name]}
                phaseLogs={logs.filter(log => log.phase_name === node.phase.name)}
                isSelected={selectedPhaseIndex === node.phaseIdx}
                onSelect={() => handleSelectPhase(node.phaseIdx)}
                defaultModel={defaultModel}
              />
            </div>
          ))}

          {/* Empty state hint */}
          {phases.length === 0 && (
            <div className="cascade-empty-hint">
              <Icon icon="mdi:hand-back-left" width="24" />
              <span>Drag phase types from the sidebar to start</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Detail Panel */}
      {selectedPhase ? (
        <PhaseDetailPanel
          phase={selectedPhase}
          index={selectedPhaseIndex}
          cellState={cellStates[selectedPhase.name]}
          phaseLogs={logs.filter(log => log.phase_name === selectedPhase.name)}
          allSessionLogs={logs}
          onClose={() => setSelectedPhaseIndex(null)}
        />
      ) : (
        <div className="cascade-empty-detail">
          <Icon icon="mdi:cursor-pointer" width="32" />
          <p>Select a phase above to view details</p>
        </div>
      )}

    </div>
  );
};

export default CascadeTimeline;
