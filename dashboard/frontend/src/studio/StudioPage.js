import React, { useEffect, useState, useCallback, useRef } from 'react';
import { DndContext, DragOverlay } from '@dnd-kit/core';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import useStudioQueryStore from './stores/studioQueryStore';
import useStudioCascadeStore from './stores/studioCascadeStore';
import useRunningSessions from './hooks/useRunningSessions';
import SchemaTree from './components/SchemaTree';
import QueryTabManager from './components/QueryTabManager';
import SqlEditor from './components/SqlEditor';
import QueryResultsGrid from './components/QueryResultsGrid';
import QueryHistoryPanel from './components/QueryHistoryPanel';
import { CascadeNavigator } from './timeline';
import CascadeTimeline from './timeline/CascadeTimeline';
import VerticalSidebar from '../shell/VerticalSidebar';
import Header from '../components/Header';
import CascadeBrowserModal from './components/CascadeBrowserModal';
import './editors'; // Initialize phase editor registry
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
    cascadeSessionId,
    fetchDefaultModel,
    fetchPhaseTypes,
    joinLiveSession
  } = useStudioCascadeStore();

  // Poll for running sessions
  const { sessions: runningSessions } = useRunningSessions(5000);

  // Handler for joining a running session from the sidebar
  const handleJoinSession = useCallback(async (session) => {
    console.log('[StudioPage] Joining session:', session);
    await joinLiveSession(session.session_id, session.cascade_id, session.cascade_file);
  }, [joinLiveSession]);

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
      const dropTarget = over.data.current;

      // Drop on phase card → Create new phase with handoff from that card
      if (dropTarget?.type === 'phase-card') {
        const sourcePhaseName = dropTarget.phaseName;
        const sourcePhaseIndex = dropTarget.phaseIndex;

        // Get current phase count to predict new name (matches addCell logic)
        const cascadeStore = useStudioCascadeStore.getState();
        const phasesBefore = cascadeStore.cascade?.phases || [];
        const cellCount = phasesBefore.length + 1;

        // Get phase type definition to match naming
        const phaseTypeDef = cascadeStore.phaseTypes.find(pt => pt.type_id === phaseType);
        const baseName = phaseTypeDef?.name_prefix || phaseType.replace(/_data$/, '');

        // Find unique name with counter
        let predictedName = `${baseName}_${cellCount}`;
        let counter = cellCount;
        while (phasesBefore.some(p => p.name === predictedName)) {
          counter++;
          predictedName = `${baseName}_${counter}`;
        }

        // Add new phase after source
        // Pass autoChain=false to prevent creating linear chain (only set parent handoff)
        addCell(phaseType, sourcePhaseIndex, null, false);

        return;
      }

      // Drop on canvas background → Create independent phase (no handoffs)
      if (dropTarget?.type === 'canvas-background') {
        // Add at end with no auto-chaining
        addCell(phaseType, null, null, false);
        return;
      }

      // Drop on drop zone → Insert at position
      const dropPosition = dropTarget?.position;
      if (dropPosition !== undefined) {
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

    // Handle model drops into Monaco editor (no Jinja brackets)
    if (dragType === 'model' && over?.data?.current?.type === 'monaco-editor') {
      const modelId = active.data.current.modelId;
      const editor = window.__activeMonacoEditor;

      if (editor && modelId) {
        // Insert at cursor position (plain string, no quotes)
        const position = editor.getPosition();

        editor.executeEdits('insert-model', [
          {
            range: {
              startLineNumber: position.lineNumber,
              startColumn: position.column,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            },
            text: modelId,
          },
        ]);

        // Move cursor after inserted text
        editor.setPosition({
          lineNumber: position.lineNumber,
          column: position.column + modelId.length,
        });

        editor.focus();
      }
    }
  };

  // Fetch connections, default model, and phase types on mount
  useEffect(() => {
    fetchConnections();
    fetchDefaultModel();
    fetchPhaseTypes();
  }, [fetchConnections, fetchDefaultModel, fetchPhaseTypes]);

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
  const lastLoadedRef = useRef({ cascade: null, session: null });

  // Load cascade or session from URL parameter - reactive to URL changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const loadFromUrl = async () => {
      const state = useStudioCascadeStore.getState();

      // Check if store already has what the URL is asking for
      // This prevents double-loading when Recent Runs updates state AND URL
      // OR when the URL sync effect updates the URL during live execution
      if (initialSession) {
        // Check if we're already in replay mode with this session
        if (state.viewMode === 'replay' && state.replaySessionId === initialSession) {
          console.log('[StudioPage] Store already in replay mode with this session, skipping URL load');
          lastLoadedRef.current = { cascade: initialCascade, session: initialSession };
          return;
        }
        // Check if this session is currently running LIVE (don't switch to replay!)
        if (state.viewMode === 'live' && state.cascadeSessionId === initialSession) {
          console.log('[StudioPage] Session is currently running LIVE, skipping URL load (not switching to replay)');
          lastLoadedRef.current = { cascade: initialCascade, session: initialSession };
          return;
        }
      }

      // Check if we already loaded this exact combination via URL
      if (lastLoadedRef.current.cascade === initialCascade &&
          lastLoadedRef.current.session === initialSession) {
        console.log('[StudioPage] Already loaded this URL combination, skipping');
        return;
      }

      // Small delay to ensure component is fully mounted and CascadeTimeline is ready
      await new Promise(resolve => setTimeout(resolve, 100));

      // Priority 1: If session provided, load it in replay mode (includes cascade)
      if (initialSession) {
        console.log('[StudioPage] Loading session from URL:', initialSession);

        try {
          // Step 1: Load cascade definition
          await setReplayMode(initialSession);

          // Step 2: Fetch session data BEFORE activating UI
          console.log('[StudioPage] Fetching replay data...');
          const result = await useStudioCascadeStore.getState().fetchReplayData(initialSession);

          if (result.success) {
            console.log('[StudioPage] ✓ Replay data loaded:', result.phaseCount, 'phases');
          } else {
            console.warn('[StudioPage] ⚠ Replay data fetch failed:', result.error);
          }

          // Step 3: Activate timeline mode (UI rehydrates from cellStates)
          setMode('timeline');

        } catch (err) {
          console.error('[StudioPage] Failed to load session:', err);
        }

        lastLoadedRef.current = { cascade: initialCascade, session: initialSession };
        if (onCascadeLoaded) onCascadeLoaded();
        return;
      }

      // Priority 2: If only cascade provided (no session), load cascade file
      if (initialCascade) {
        console.log('[StudioPage] Loading cascade from URL:', initialCascade);
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
        lastLoadedRef.current = { cascade: initialCascade, session: null };
        if (onCascadeLoaded) onCascadeLoaded();
        return;
      }

      // Priority 3: No URL parameters - check if store already has a cascade
      console.log('[StudioPage] No URL parameters');
      const currentState = useStudioCascadeStore.getState();

      // Don't auto-create if cascade already exists in store
      if (currentState.cascade && currentState.cascade.cascade_id) {
        console.log('[StudioPage] Store already has cascade, keeping it:', currentState.cascade.cascade_id);
        lastLoadedRef.current = { cascade: currentState.cascade.cascade_id, session: null };
        setMode('timeline');
        return;
      }

      // Otherwise, create a new blank cascade with generated ID
      console.log('[StudioPage] Creating new blank cascade');
      const { autoGenerateSessionId } = await import('../utils/sessionNaming');
      const newCascadeId = `studio_new_${autoGenerateSessionId().split('-').pop()}`; // e.g. studio_new_abc123

      console.log('[StudioPage] Generated new cascade:', newCascadeId);

      // Create a blank cascade (no session yet - that's generated when you click Run)
      useStudioCascadeStore.setState({
        cascade: {
          cascade_id: newCascadeId,
          description: 'New cascade',
          inputs_schema: {},
          phases: []
        },
        cascadePath: null,
        cascadeDirty: false,
        cascadeSessionId: null, // No session until Run is clicked
        replaySessionId: null,
        viewMode: 'live',
        isRunningAll: false,
        cascadeInputs: {},
        cellStates: {},
      });

      setMode('timeline');
      lastLoadedRef.current = { cascade: newCascadeId, session: null };
    };

    loadFromUrl();
  }, [initialCascade, initialSession]); // Only react to URL changes, not function references

  // DISABLED: Auto URL sync creates circular dependency with URL→State effect above
  // The two effects create a race condition loop:
  // 1. User loads cascade → Effect #1 loads → updates store
  // 2. Store update → Effect #2 fires → updates URL
  // 3. URL update → Effect #1 fires again → creates blank cascade
  // 4. User's work disappears! 😱
  //
  // Solution: URL is INPUT-ONLY. Users can manually bookmark/share URLs.
  // If re-enabling, need proper state reconciliation strategy.
  //
  // useEffect(() => {
  //   if (mode !== 'timeline' || !cascade) return;
  //
  //   const cascadeId = cascade.cascade_id;
  //   const activeSession = viewMode === 'replay' ? replaySessionId : cascadeSessionId;
  //
  //   // Build new hash
  //   let newHash = '#/studio';
  //   if (cascadeId) {
  //     newHash += `/${cascadeId}`;
  //     if (activeSession) {
  //       newHash += `/${activeSession}`;
  //     }
  //   }
  //
  //   // Only update if different (avoid infinite loops)
  //   if (window.location.hash !== newHash) {
  //     window.location.hash = newHash;
  //     console.log('[StudioPage] Updated URL:', newHash);
  //   }
  // }, [mode, cascade, viewMode, replaySessionId, cascadeSessionId]);

  return (
    <div className="studio-page">
      {mode === 'timeline' ? (
        /* Timeline Mode - Vertical sidebar with drag-drop context */
        <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="studio-timeline-layout">
            <VerticalSidebar
              currentView="studio"
              onNavigate={null}
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
              runningSessions={runningSessions}
              currentSessionId={cascadeSessionId}
              onJoinSession={handleJoinSession}
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
                {activeDragItem.type === 'model' && (
                  <div className="studio-drag-model">
                    <Icon icon="mdi:robot-outline" width="14" />
                    {activeDragItem.modelId}
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
