import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useTimelinePolling from '../hooks/useTimelinePolling';
import PhaseCard from './PhaseCard';
import PhaseDetailPanel from './PhaseDetailPanel';
import './CascadeTimeline.css';

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

  if (!cascade) {
    return (
      <div className="cascade-timeline cascade-loading">
        <div className="cascade-spinner" />
        Loading cascade...
      </div>
    );
  }

  const phases = cascade.phases || [];
  const selectedPhase = selectedPhaseIndex !== null ? phases[selectedPhaseIndex] : null;
  const cellCount = phases.length;
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;

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
          {/* Continuous track line (metro map style) */}
          {phases.length > 0 && <div className="cascade-track-line" />}

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
