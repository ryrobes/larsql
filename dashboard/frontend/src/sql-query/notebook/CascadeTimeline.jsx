import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Icon } from '@iconify/react';
import useNotebookStore from '../stores/notebookStore';
import PhaseCard from './PhaseCard';
import PhaseDetailPanel from './PhaseDetailPanel';
import './CascadeTimeline.css';

/**
 * CascadeTimeline - Horizontal cascade builder (DAW-style)
 *
 * Layout:
 * - Top bar: Cascade controls + metadata
 * - Middle strip: Horizontal scrolling phase cards (left→right)
 * - Bottom panel: Selected phase details (config, code, outputs)
 */
const CascadeTimeline = () => {
  const {
    notebook,
    notebookPath,
    notebookDirty,
    cellStates,
    isRunningAll,
    sessionId,
    notebooks,
    fetchNotebooks,
    loadNotebook,
    newNotebook,
    addCell,
    runAllCells,
    restartSession,
    updateNotebook,
    saveNotebook,
  } = useNotebookStore();

  const [selectedPhaseIndex, setSelectedPhaseIndex] = useState(null);
  const [showAddMenu, setShowAddMenu] = useState(false);
  const timelineRef = useRef(null);

  const handleTitleChange = (e) => {
    updateNotebook({ cascade_id: e.target.value });
  };

  const handleDescriptionChange = (e) => {
    updateNotebook({ description: e.target.value });
  };

  const handleRunAll = async () => {
    await runAllCells();
  };

  const handleSave = async () => {
    if (!notebookPath) {
      const path = window.prompt('Save cascade as:', `cascades/${notebook?.cascade_id || 'cascade'}.yaml`);
      if (path) {
        await saveNotebook(path);
      }
    } else {
      await saveNotebook();
    }
  };

  const handleSaveAsTool = async () => {
    const toolName = notebook?.cascade_id?.replace(/[^a-z0-9_]/gi, '_') || 'cascade';
    const path = `tackle/${toolName}.yaml`;

    if (window.confirm(`Save as tool: ${toolName}?\n\nThis will make it callable from other cascades.`)) {
      await saveNotebook(path);
    }
  };

  const handleRestart = async () => {
    if (window.confirm('Restart session? This will clear all outputs.')) {
      await restartSession();
    }
  };

  const handleLoad = async (path) => {
    try {
      await loadNotebook(path);
    } catch (err) {
      console.error('Load failed:', err);
    }
  };

  // Fetch notebooks on mount
  useEffect(() => {
    fetchNotebooks();
  }, [fetchNotebooks]);

  // Create new notebook if none exists (same pattern as NotebookEditor)
  useEffect(() => {
    if (!notebook) {
      newNotebook();
    }
  }, [notebook, newNotebook]);

  const handleAddPhase = (type) => {
    addCell(type);
    setShowAddMenu(false);
    // Auto-select newly added phase
    setTimeout(() => {
      const newIndex = (notebook?.phases?.length || 0);
      setSelectedPhaseIndex(newIndex);
      // Scroll to end
      if (timelineRef.current) {
        timelineRef.current.scrollLeft = timelineRef.current.scrollWidth;
      }
    }, 100);
  };

  const handleSelectPhase = (index) => {
    setSelectedPhaseIndex(index);
  };

  if (!notebook) {
    return (
      <div className="cascade-timeline cascade-loading">
        <div className="cascade-spinner" />
        Loading cascade...
      </div>
    );
  }

  const phases = notebook.phases || [];
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
            value={notebook.cascade_id || ''}
            onChange={handleTitleChange}
            placeholder="cascade_name"
          />
          {notebookDirty && <span className="cascade-dirty-dot" title="Unsaved changes" />}
          <input
            className="cascade-description-input"
            value={notebook.description || ''}
            onChange={handleDescriptionChange}
            placeholder="Description..."
          />
        </div>

        <div className="cascade-control-right">
          <span className="cascade-stats">
            {completedCount}/{cellCount} phases
          </span>

          {/* Cascade selector dropdown */}
          <select
            className="cascade-selector"
            value={notebookPath || ''}
            onChange={(e) => e.target.value && handleLoad(e.target.value)}
          >
            <option value="">Load cascade...</option>
            {notebooks.map(nb => (
              <option key={nb.path} value={nb.path}>
                {nb.cascade_id} ({nb.path})
              </option>
            ))}
          </select>

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
            disabled={!notebookDirty && notebookPath}
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

          <button
            className="cascade-btn cascade-btn-primary"
            onClick={handleRunAll}
            disabled={isRunningAll || cellCount === 0}
          >
            {isRunningAll ? (
              <>
                <span className="cascade-spinner-sm" />
                Running
              </>
            ) : (
              <>
                <Icon icon="mdi:play" width="16" />
                Run All
              </>
            )}
          </button>
        </div>
      </div>

      {/* Horizontal Phase Timeline */}
      <div className="cascade-timeline-strip" ref={timelineRef}>
        <div className="cascade-timeline-track">
          {phases.map((phase, index) => (
            <React.Fragment key={phase.name}>
              <PhaseCard
                phase={phase}
                index={index}
                cellState={cellStates[phase.name]}
                isSelected={selectedPhaseIndex === index}
                onSelect={() => handleSelectPhase(index)}
              />
              {index < phases.length - 1 && (
                <div className="cascade-connector">
                  <Icon icon="mdi:arrow-right" width="20" />
                </div>
              )}
            </React.Fragment>
          ))}

          {/* Add Phase Button */}
          <div className="cascade-add-phase">
            <button
              className="cascade-add-btn"
              onClick={() => setShowAddMenu(!showAddMenu)}
            >
              <Icon icon="mdi:plus" width="20" />
              Add Phase
            </button>

            {showAddMenu && (
              <div className="cascade-add-menu">
                <button onClick={() => handleAddPhase('sql_data')}>
                  <Icon icon="mdi:database" width="16" />
                  SQL
                </button>
                <button onClick={() => handleAddPhase('python_data')}>
                  <Icon icon="mdi:language-python" width="16" />
                  Python
                </button>
                <button onClick={() => handleAddPhase('js_data')}>
                  <Icon icon="mdi:language-javascript" width="16" />
                  JavaScript
                </button>
                <button onClick={() => handleAddPhase('clojure_data')}>
                  <Icon icon="simple-icons:clojure" width="16" />
                  Clojure
                </button>
                <hr />
                <button onClick={() => handleAddPhase('windlass_data')} className="cascade-add-llm">
                  <Icon icon="mdi:sail-boat" width="16" />
                  LLM Phase
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Detail Panel */}
      {selectedPhase ? (
        <PhaseDetailPanel
          phase={selectedPhase}
          index={selectedPhaseIndex}
          cellState={cellStates[selectedPhase.name]}
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
