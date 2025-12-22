import React, { useEffect, useState, useCallback, useRef } from 'react';
import { DndContext, DragOverlay } from '@dnd-kit/core';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import useStudioQueryStore from './stores/studioQueryStore';
import useStudioCascadeStore from './stores/studioCascadeStore';
import SchemaTree from './components/SchemaTree';
import QueryTabManager from './components/QueryTabManager';
import SqlEditor from './components/SqlEditor';
import QueryResultsGrid from './components/QueryResultsGrid';
import QueryHistoryPanel from './components/QueryHistoryPanel';
import { CascadeNavigator } from './notebook';
import CascadeTimeline from './notebook/CascadeTimeline';
import VerticalSidebar from './notebook/VerticalSidebar';
import Header from '../components/Header';
import CascadeBrowserModal from './components/CascadeBrowserModal';
import './StudioPage.css';

function StudioPage({
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
  sseConnected,
  initialCascade,
  initialSession,
  onCascadeLoaded
}) {
  const {
    historyPanelOpen,
    fetchConnections,
    connections
  } = useStudioQueryStore();

  const {
    mode,
    setMode,
    cascades,
    fetchCascades,
    loadCascade,
    addCell,
    setReplayMode,
    cascade,
    viewMode,
    replaySessionId,
    cascadeSessionId
  } = useStudioCascadeStore();

  // Persist split sizes in state
  const [timelineSplitSizes, setTimelineSplitSizes] = React.useState([20, 80]);

  // Track what's being dragged for overlay
  const [activeDragItem, setActiveDragItem] = useState(null);

  // Cascade browser modal state
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Handle cascade load from browser
  const handleBrowserLoad = useCallback(async (file) => {
    try {
      await loadCascade(file.filepath);
    } catch (err) {
      console.error('[StudioPage] Load failed:', err);
    }
  }, [loadCascade]);

  // Drag and drop handlers for timeline mode
  const handleDragStart = (event) => {
    const { active } = event;
    setActiveDragItem(active.data.current);
  };

  const handleDragEnd = (event) => {
    setActiveDragItem(null);
    const { active, over } = event;

    if (!over) return;

    const dragType = active.data.current?.type;

    // Handle phase type drops
    if (dragType === 'phase-type') {
      const phaseType = active.data.current.phaseType;
      const dropPosition = over.data.current?.position;

      if (dropPosition !== undefined) {
        // Insert at specific position
        addCell(phaseType, dropPosition);
      }
    }

    // Handle variable drops into Monaco editor
    if (dragType === 'variable' && over?.data?.current?.type === 'monaco-editor') {
      const variablePath = active.data.current.variablePath;
      const editor = window.__activeMonacoEditor;

      if (editor && variablePath) {
        // Insert at cursor position
        const position = editor.getPosition();
        const jinjaText = `{{ ${variablePath} }}`;

        editor.executeEdits('insert-variable', [
          {
            range: {
              startLineNumber: position.lineNumber,
              startColumn: position.column,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            },
            text: jinjaText,
          },
        ]);

        // Move cursor after inserted text
        editor.setPosition({
          lineNumber: position.lineNumber,
          column: position.column + jinjaText.length,
        });

        editor.focus();
      }
    }
  };

  // Fetch connections on mount
  useEffect(() => {
    fetchConnections();
  }, [fetchConnections]);

  // Set default connection for first tab when connections load
  useEffect(() => {
    if (connections.length > 0) {
      const state = useStudioQueryStore.getState();
      const activeTab = state.tabs.find(t => t.id === state.activeTabId);
      if (activeTab && !activeTab.connection) {
        state.updateTab(activeTab.id, { connection: connections[0].name });
      }
    }
  }, [connections]);

  // Track if we've already loaded from URL to prevent multiple loads
  const urlLoadedRef = useRef(false);

  // Load cascade or session from URL parameter
  useEffect(() => {
    // Only load once per mount
    if (urlLoadedRef.current) {
      console.log('[StudioPage] URL already loaded, skipping');
      return;
    }

    const loadFromUrl = async () => {
      // Small delay to ensure component is fully mounted and CascadeTimeline is ready
      await new Promise(resolve => setTimeout(resolve, 100));

      // Priority 1: If session provided, load it in replay mode (includes cascade)
      if (initialSession) {
        console.log('[StudioPage] Loading session from URL:', initialSession);
        urlLoadedRef.current = true;
        try {
          await setReplayMode(initialSession);
          setMode('timeline');
          console.log('[StudioPage] ✓ Replay mode activated, polling should start');
        } catch (err) {
          console.error('[StudioPage] Failed to load session:', err);
        }
        if (onCascadeLoaded) onCascadeLoaded();
        return;
      }

      // Priority 2: If only cascade provided (no session), load cascade file
      if (initialCascade) {
        console.log('[StudioPage] Loading cascade from URL:', initialCascade);
        urlLoadedRef.current = true;
        await fetchCascades();
        const state = useStudioCascadeStore.getState();
        const nb = state.cascades.find(n => n.cascade_id === initialCascade);
        if (nb) {
          await loadCascade(nb.path);
          setMode('timeline');
          console.log('[StudioPage] ✓ Cascade loaded');
        } else {
          console.warn('[StudioPage] Cascade not found:', initialCascade);
        }
        if (onCascadeLoaded) onCascadeLoaded();
        return;
      }

      console.log('[StudioPage] No URL parameters to load');
    };

    loadFromUrl();
  }, [initialCascade, initialSession, fetchCascades, loadCascade, setReplayMode, setMode, onCascadeLoaded]);

  // Update URL hash when cascade or session changes (timeline mode only)
  useEffect(() => {
    if (mode !== 'timeline' || !cascade) return;

    const cascadeId = cascade.cascade_id;
    const activeSession = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

    // Build new hash
    let newHash = '#/studio';
    if (cascadeId) {
      newHash += `/${cascadeId}`;
      if (activeSession) {
        newHash += `/${activeSession}`;
      }
    }

    // Only update if different (avoid infinite loops)
    if (window.location.hash !== newHash) {
      window.location.hash = newHash;
      console.log('[StudioPage] Updated URL:', newHash);
    }
  }, [mode, cascade, viewMode, replaySessionId, cascadeSessionId]);

  return (
    <div className="studio-page">
      {mode === 'timeline' ? (
        /* Timeline Mode - Vertical sidebar with drag-drop context */
        <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="studio-timeline-layout">
            <VerticalSidebar
              onMessageFlow={onMessageFlow}
              onCockpit={onCockpit}
              onSextant={onSextant}
              onWorkshop={onWorkshop}
              onPlayground={onPlayground}
              onTools={onTools}
              onSearch={onSearch}
              onSqlQuery={onSqlQuery}
              onArtifacts={onArtifacts}
              onBrowser={onBrowser}
              onSessions={onSessions}
              onBlocked={onBlocked}
              blockedCount={blockedCount}
              sseConnected={sseConnected}
            />
            <Split
              className="studio-horizontal-split"
              sizes={timelineSplitSizes}
              onDragEnd={(sizes) => setTimelineSplitSizes(sizes)}
              minSize={[180, 400]}
              maxSize={[500, Infinity]}
              gutterSize={6}
              gutterAlign="center"
              direction="horizontal"
            >
              {/* Left Sidebar - Cascade Navigator */}
              <div className="studio-schema-panel timeline-mode">
                <CascadeNavigator />
              </div>

              {/* Timeline Area */}
              <div className="studio-timeline-area">
                <CascadeTimeline
                  key="timeline-mode"
                  onOpenBrowser={() => setIsBrowserOpen(true)}
                />
              </div>
            </Split>
          </div>

          {/* Drag Overlay */}
          <DragOverlay>
            {activeDragItem && (
              <div className="studio-drag-overlay">
                {activeDragItem.type === 'variable' && (
                  <div className="studio-drag-variable">
                    <Icon icon="mdi:code-braces" width="14" />
                    {`{{ ${activeDragItem.variablePath} }}`}
                  </div>
                )}
                {activeDragItem.type === 'phase-type' && (
                  <div className="studio-drag-phase">
                    Adding {activeDragItem.phaseType}...
                  </div>
                )}
              </div>
            )}
          </DragOverlay>
        </DndContext>
      ) : (
        <>
          <Header
            centerContent={
              <>
                <Icon icon="mdi:database-search" width="24" />
                <span className="header-stat">SQL Query IDE</span>
                <span className="header-divider">·</span>

                {/* Mode Toggle */}
                <div className="sql-mode-toggle">
                  <button
                    className={`sql-mode-btn ${mode === 'query' ? 'active' : ''}`}
                    onClick={() => setMode('query')}
                  >
                    Query
                  </button>
                  <button
                    className={`sql-mode-btn ${mode === 'timeline' ? 'active' : ''}`}
                    onClick={() => setMode('timeline')}
                    title="Horizontal cascade builder (experimental)"
                  >
                    Timeline
                  </button>
                </div>

                <span className="header-divider">·</span>
                <span className="header-stat">{connections.length} <span className="stat-dim">connections</span></span>
              </>
            }
            onMessageFlow={onMessageFlow}
            onCockpit={onCockpit}
            onSextant={onSextant}
            onWorkshop={onWorkshop}
            onPlayground={onPlayground}
            onTools={onTools}
            onSearch={onSearch}
            onSqlQuery={onSqlQuery}
            onArtifacts={onArtifacts}
            onBrowser={onBrowser}
            onSessions={onSessions}
            onBlocked={onBlocked}
            blockedCount={blockedCount}
            sseConnected={sseConnected}
          />
        </>
      )}

      {mode === 'timeline' ? null : (
        /* Query Mode (original) */
        <>
          <Split
            className="studio-horizontal-split"
            sizes={[20, 80]}
            minSize={[180, 400]}
            maxSize={[500, Infinity]}
            gutterSize={6}
            gutterAlign="center"
            direction="horizontal"
          >
            {/* Left Sidebar - Schema Browser */}
            <div className="studio-schema-panel">
              <div className="studio-schema-header">
                <span className="studio-schema-title">Schema Browser</span>
              </div>
              <SchemaTree />
            </div>

            {/* Main Area with vertical split: Editor | Results */}
            <Split
              className="studio-vertical-split"
              sizes={[60, 40]}
              minSize={[150, 100]}
              gutterSize={6}
              gutterAlign="center"
              direction="vertical"
            >
              {/* Tabs + Editor */}
              <div className="studio-editor-area">
                <QueryTabManager />
                <SqlEditor />
              </div>

              {/* Results Panel */}
              <div className="studio-results-panel">
                <QueryResultsGrid />
              </div>
            </Split>
          </Split>

          {/* History Panel (collapsible) */}
          {historyPanelOpen && (
            <div className="studio-history-panel">
              <QueryHistoryPanel />
            </div>
          )}
        </>
      )}

      {/* Cascade Browser Modal */}
      <CascadeBrowserModal
        isOpen={isBrowserOpen}
        onClose={() => setIsBrowserOpen(false)}
        onLoad={handleBrowserLoad}
      />
    </div>
  );
}

export default StudioPage;
