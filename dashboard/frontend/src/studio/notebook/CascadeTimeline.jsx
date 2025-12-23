import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useTimelinePolling from '../hooks/useTimelinePolling';
import PhaseCard from './PhaseCard';
import PhaseDetailPanel from './PhaseDetailPanel';
import './CascadeTimeline.css';

/**
 * Analyze cascade DAG structure to detect parallelism and branching
 * Handles BOTH explicit handoffs AND implicit dependencies from {{ outputs.X }}
 * Returns flow bar metadata for visualization
 */
const analyzeFlowStructure = (phases) => {
  if (!phases || phases.length === 0) return [];

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
    };
    inDegree[idx] = 0;
    outDegree[idx] = 0;
  });

  // Extract implicit dependencies from Jinja2 {{ outputs.phase_name }} references
  phases.forEach((phase, idx) => {
    const phaseYaml = JSON.stringify(phase); // Convert to string to search
    const outputsPattern = /\{\{\s*outputs\.(\w+)/g;
    let match;
    const deps = new Set();

    while ((match = outputsPattern.exec(phaseYaml)) !== null) {
      const referencedPhaseName = match[1];
      const depIdx = phases.findIndex(p => p.name === referencedPhaseName);
      if (depIdx !== -1 && depIdx !== idx) {
        deps.add(depIdx);
      }
    }

    graph[idx].implicitDeps = Array.from(deps);
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

  // Assign lanes - default is lane 0 (sequential), branch when parallelism detected
  const lanes = phases.map(() => 0); // Default: all lane 0
  const visited = new Set();

  // Identify parallel branches and assign lanes
  phases.forEach((_, idx) => {
    if (outDegree[idx] > 1) {
      // This phase branches to multiple targets - assign unique lanes
      const targets = graph[idx].targets.sort((a, b) => a - b);

      targets.forEach((targetIdx, laneOffset) => {
        // Assign lane to this target
        lanes[targetIdx] = laneOffset;
        visited.add(targetIdx);

        // Propagate lane to descendants until merge point
        const propagateLane = (nodeIdx, lane) => {
          if (visited.has(nodeIdx)) return; // Already processed
          visited.add(nodeIdx);
          lanes[nodeIdx] = lane;

          // Continue propagation if linear path (single target, single source)
          if (outDegree[nodeIdx] === 1) {
            const nextTarget = graph[nodeIdx].targets[0];
            if (inDegree[nextTarget] === 1) {
              // Linear continuation - keep same lane
              propagateLane(nextTarget, lane);
            }
          }
        };

        // Start propagation from branch target
        if (inDegree[targetIdx] === 1) {
          propagateLane(targetIdx, laneOffset);
        }
      });
    }
  });

  console.log('[FlowStructure] Lane assignments:', phases.map((p, i) => `${p.name}:L${lanes[i]}`).join(', '));

  // Build flow bar metadata
  return phases.map((phase, idx) => {
    const isBranch = outDegree[idx] > 1;
    const isMerge = inDegree[idx] > 1;
    const isParallel = graph[idx].sources.length > 0 &&
                       graph[idx].sources.some(s => outDegree[s] > 1);

    return {
      index: idx,
      name: phase.name,
      lane: lanes[idx] || 0,
      isBranch,
      isMerge,
      isParallel,
      targets: graph[idx].targets,
      sources: graph[idx].sources,
    };
  });
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

  // Analyze flow structure for visualization (must be before early returns)
  const phases = cascade?.phases || [];
  const flowStructure = useMemo(() => analyzeFlowStructure(phases), [phases]);
  const maxLane = flowStructure.length > 0 ? Math.max(...flowStructure.map(f => f.lane)) : 0;

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

      {/* Horizontal Phase Timeline */}
      <div className="cascade-timeline-strip" ref={timelineRef}>
        <div className="cascade-timeline-track">
          {/* Flow visualization - shows DAG structure */}
          {phases.length > 0 && (
            <>
              {/* For linear flows: single continuous line */}
              {maxLane === 0 && (
                <div className="cascade-track-line" />
              )}

              {/* For DAG flows: multi-lane parallel tracks */}
              {maxLane > 0 && (
                <div className="cascade-flow-bars">
                  {/* Draw continuous tracks for each lane */}
                  {(() => {
                    const CARD_WIDTH = 240;
                    const CARD_GAP = 56;
                    const TRACK_PADDING = 20;
                    const BAR_HEIGHT = 6;
                    const LANE_SPACING = 20;

                    // Group phases by lane
                    const lanePhases = {};
                    flowStructure.forEach((flow, idx) => {
                      if (!lanePhases[flow.lane]) lanePhases[flow.lane] = [];
                      lanePhases[flow.lane].push(idx);
                    });

                    // Draw continuous track for each lane
                    return Object.entries(lanePhases).flatMap(([lane, phaseIndices]) => {
                      const laneNum = parseInt(lane);
                      const yOffset = (laneNum - maxLane / 2) * LANE_SPACING;

                      const segments = [];

                      // Draw bars under cards
                      phaseIndices.forEach(idx => {
                        const flow = flowStructure[idx];
                        const xPos = TRACK_PADDING + (idx * (CARD_WIDTH + CARD_GAP));
                        const isSpecial = flow.isBranch || flow.isMerge;
                        const barColor = isSpecial ? '#ff006e' : '#00e5ff';

                        segments.push(
                          <div
                            key={`bar-${lane}-${idx}`}
                            className={`flow-bar ${isSpecial ? 'flow-bar-special' : ''}`}
                            style={{
                              left: `${xPos}px`,
                              top: `calc(50% + ${yOffset}px - ${BAR_HEIGHT / 2}px)`,
                              width: `${CARD_WIDTH}px`,
                              height: `${BAR_HEIGHT}px`,
                              backgroundColor: barColor,
                              opacity: isSpecial ? 0.7 : 0.4,
                              boxShadow: isSpecial
                                ? '0 0 16px rgba(255, 0, 110, 0.5)'
                                : '0 0 8px rgba(0, 229, 255, 0.3)',
                            }}
                          />
                        );
                      });

                      // Draw gaps between consecutive phases in same lane
                      for (let i = 0; i < phaseIndices.length - 1; i++) {
                        const currentIdx = phaseIndices[i];
                        const nextIdxInLane = phaseIndices[i + 1];
                        const currentFlow = flowStructure[currentIdx];
                        const nextFlowInLane = flowStructure[nextIdxInLane];

                        const gapStartX = TRACK_PADDING + (currentIdx * (CARD_WIDTH + CARD_GAP)) + CARD_WIDTH;
                        const gapEndX = TRACK_PADDING + (nextIdxInLane * (CARD_WIDTH + CARD_GAP));
                        const gapWidth = gapEndX - gapStartX;

                        const isSpecial = currentFlow.isBranch || nextFlowInLane.isMerge;
                        const gapColor = isSpecial ? '#ff006e' : '#00e5ff';

                        segments.push(
                          <div
                            key={`gap-${lane}-${currentIdx}-${nextIdxInLane}`}
                            className="flow-gap"
                            style={{
                              position: 'absolute',
                              left: `${gapStartX}px`,
                              top: `calc(50% + ${yOffset}px - ${BAR_HEIGHT / 2}px)`,
                              width: `${gapWidth}px`,
                              height: `${BAR_HEIGHT}px`,
                              backgroundColor: gapColor,
                              opacity: isSpecial ? 0.6 : 0.3,
                              boxShadow: isSpecial
                                ? '0 0 10px rgba(255, 0, 110, 0.4)'
                                : '0 0 6px rgba(0, 229, 255, 0.3)',
                              borderRadius: '2px',
                            }}
                          />
                        );
                      }

                      return segments;
                    });
                  })()}
                </div>
              )}
            </>
          )}

          {/* Drop zone at start */}
          <DropZone position={0} />

          {phases.map((phase, index) => (
            <React.Fragment key={phase.name}>
              <PhaseCard
                phase={phase}
                index={index}
                cellState={cellStates[phase.name]}
                phaseLogs={logs.filter(log => log.phase_name === phase.name)}
                isSelected={selectedPhaseIndex === index}
                onSelect={() => handleSelectPhase(index)}
                defaultModel={defaultModel}
              />
              {/* Drop zone after this phase */}
              <DropZone position={index + 1} />
            </React.Fragment>
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
