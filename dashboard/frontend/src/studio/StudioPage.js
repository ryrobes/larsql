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
import { CascadeNavigator } from './timeline';
import CascadeTimeline from './timeline/CascadeTimeline';
import Header from '../components/Header';
import CascadeBrowserModal from './components/CascadeBrowserModal';
import ContextExplorerSidebar from './components/ContextExplorerSidebar';
import './editors'; // Initialize cell editor registry
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
  sseConnected, // Only used for Header in query mode (not used in AppShell/timeline mode)
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
    updateCascade,
    setReplayMode,
    cascade,
    viewMode,
    replaySessionId,
    cascadeSessionId,
    fetchDefaultModel,
    fetchCellTypes,
    joinLiveSession
  } = useStudioCascadeStore();

  // DEBUG: Log mode and cascade state (runs on EVERY render)
  // console.log('[StudioPage] RENDER:', {
  //   mode,
  //   hasCascade: !!cascade,
  //   cascadeId: cascade?.cascade_id,
  //   cellsLength: cascade?.cells?.length || 0,
  //   isTimelineMode: mode === 'timeline'
  // });

  // Note: Running sessions and sidebar navigation now handled by AppShell
  // StudioPage just renders the main content area

  // Persist split sizes in state
  const [timelineSplitSizes, setTimelineSplitSizes] = React.useState([20, 80]);

  // Track what's being dragged for overlay
  const [activeDragItem, setActiveDragItem] = useState(null);

  // Cascade browser modal state
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Context explorer state
  const [selectedContextMessage, setSelectedContextMessage] = useState(null);
  const [allSessionLogs, setAllSessionLogs] = useState([]);
  const [isMessagesViewVisible, setIsMessagesViewVisible] = useState(false);
  const [hoveredHash, setHoveredHash] = useState(null); // Cross-component hover highlighting
  const [gridSelectedMessage, setGridSelectedMessage] = useState(null); // Grid selection state

  // Handle cascade load from browser
  const handleBrowserLoad = useCallback(async (file) => {
    try {
      await loadCascade(file.filepath);
    } catch (err) {
      console.error('[StudioPage] Load failed:', err);
    }
  }, [loadCascade]);

  // Handle message selection with context
  const handleMessageContextSelect = useCallback((message) => {
    console.log('[StudioPage] Message selected:', message);
    console.log('[StudioPage] Has context_hashes?', message?.context_hashes, 'Length:', message?.context_hashes?.length);

    // Handle deselection (null message)
    if (!message) {
      console.log('[StudioPage] Message deselected, clearing context explorer');
      setSelectedContextMessage(null);
      return;
    }

    // Only show context explorer if message has context
    if (message.context_hashes && message.context_hashes.length > 0) {
      console.log('[StudioPage] Showing context explorer for message');
      setSelectedContextMessage(message);
    } else {
      console.log('[StudioPage] Message has no context, not showing explorer');
      setSelectedContextMessage(null);
    }
  }, []);

  // Clear context explorer when messages view becomes invisible
  useEffect(() => {
    if (!isMessagesViewVisible && selectedContextMessage) {
      console.log('[StudioPage] Messages view hidden, clearing context explorer');
      setSelectedContextMessage(null);
    }
  }, [isMessagesViewVisible, selectedContextMessage]);

  // Close context explorer
  const handleCloseContextExplorer = useCallback(() => {
    setSelectedContextMessage(null);
  }, []);

  // Navigate to message (from matrix or blocks list)
  // This is for browsing context - scroll to message without changing selection
  const handleNavigateToMessage = useCallback((message) => {
    console.log('[StudioPage] Navigate to message (scroll only):', message);
    // Just trigger scroll/flash in grid, don't change selection
    // The grid will handle scrolling and flash effect via scrollToMessage prop
    if (message) {
      setGridSelectedMessage({ ...message, _scrollOnly: true });
    }
  }, []);

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

    // Handle cell type drops
    if (dragType === 'cell-type') {
      const cellType = active.data.current.cellType;
      const dropTarget = over.data.current;

      // Drop on cell card → Create new cell with handoff from that card
      if (dropTarget?.type === 'cell-card') {
        const sourceCellName = dropTarget.cellName;
        const sourceCellIndex = dropTarget.cellIndex;

        // Get current cell count to predict new name (matches addCell logic)
        const cascadeStore = useStudioCascadeStore.getState();
        const cellsBefore = cascadeStore.cascade?.cells || [];
        const cellCount = cellsBefore.length + 1;

        // Get cell type definition to match naming
        const cellTypeDef = cascadeStore.cellTypes.find(ct => ct.type_id === cellType);
        const baseName = cellTypeDef?.name_prefix || cellType.replace(/_data$/, '');

        // Find unique name with counter
        let predictedName = `${baseName}_${cellCount}`;
        let counter = cellCount;
        while (cellsBefore.some(c => c.name === predictedName)) {
          counter++;
          predictedName = `${baseName}_${counter}`;
        }

        // Add new cell after source
        // Pass autoChain=false to prevent creating linear chain (only set parent handoff)
        addCell(cellType, sourceCellIndex, null, false);

        return;
      }

      // Drop on canvas background → Create independent cell (no handoffs)
      if (dropTarget?.type === 'canvas-background') {
        // Add at end with no auto-chaining
        addCell(cellType, null, null, false);
        return;
      }

      // Drop on drop zone → Insert at position
      const dropPosition = dropTarget?.position;
      if (dropPosition !== undefined) {
        addCell(cellType, dropPosition);
      }
    }

    // Handle model drops
    if (dragType === 'model') {
      const modelId = active.data.current.modelId;
      const dropTarget = over.data.current;

      // Drop on cell card → Update that cell's model
      if (dropTarget?.type === 'cell-card') {
        const cellIndex = dropTarget.cellIndex;
        const cascadeStore = useStudioCascadeStore.getState();
        const cellToUpdate = cascadeStore.cascade?.cells[cellIndex];

        if (cellToUpdate) {
          const updatedCells = [...cascadeStore.cascade.cells];
          updatedCells[cellIndex] = {
            ...cellToUpdate,
            model: modelId
          };

          updateCascade({ cells: updatedCells });
        }
        return;
      }

      // Drop on canvas → Create new llm_phase with this model
      if (dropTarget?.type === 'canvas-background') {
        // Sanitize model name for cell name
        const sanitizeName = (modelId) => {
          return modelId
            .split('/').pop() // Get model name after provider
            .replace(/[^a-z0-9_]/gi, '_') // Replace non-alphanumeric with underscore
            .toLowerCase()
            .slice(0, 30); // Max 30 chars
        };

        const baseName = sanitizeName(modelId);
        const cascadeStore = useStudioCascadeStore.getState();
        const existingCells = cascadeStore.cascade?.cells || [];

        // Find unique name
        let cellName = baseName;
        let counter = 1;
        while (existingCells.some(c => c.name === cellName)) {
          cellName = `${baseName}_${counter}`;
          counter++;
        }

        // Create llm_phase cell
        const newCell = {
          name: cellName,
          instructions: "{{ input.prompt }}",
          model: modelId,
        };

        const updatedCells = [...existingCells, newCell];
        updateCascade({ cells: updatedCells });
        return;
      }
    }

    // Handle tool/trait drops
    if (dragType === 'tool') {
      const toolId = active.data.current.toolId;
      const dropTarget = over.data.current;

      // Drop on cell card → Append to traits array
      if (dropTarget?.type === 'cell-card') {
        const cellIndex = dropTarget.cellIndex;
        const cascadeStore = useStudioCascadeStore.getState();
        const cellToUpdate = cascadeStore.cascade?.cells[cellIndex];

        if (cellToUpdate) {
          const existingTraits = cellToUpdate.traits || [];
          const updatedTraits = existingTraits.includes(toolId)
            ? existingTraits // Don't add duplicate
            : [...existingTraits, toolId];

          const updatedCells = [...cascadeStore.cascade.cells];
          updatedCells[cellIndex] = {
            ...cellToUpdate,
            traits: updatedTraits
          };

          updateCascade({ cells: updatedCells });
        }
        return;
      }

      // Drop on canvas → Create new llm_phase with this trait
      if (dropTarget?.type === 'canvas-background') {
        const cascadeStore = useStudioCascadeStore.getState();
        const existingCells = cascadeStore.cascade?.cells || [];

        // Find unique name
        let cellName = `use_${toolId}`;
        let counter = 1;
        while (existingCells.some(c => c.name === cellName)) {
          cellName = `use_${toolId}_${counter}`;
          counter++;
        }

        // Create llm_phase cell with trait
        const newCell = {
          name: cellName,
          instructions: "{{ input.prompt }}",
          traits: [toolId],
        };

        const updatedCells = [...existingCells, newCell];
        updateCascade({ cells: updatedCells });
        return;
      }
    }

    // Handle input placeholder drops
    if (dragType === 'input-placeholder') {
      const dropTarget = over.data.current;

      // Helper: Add input to top-level inputs_schema and return the input name
      const addInputToSchema = () => {
        const cascadeStore = useStudioCascadeStore.getState();
        const existingInputs = cascadeStore.cascade?.inputs_schema || {};

        // Find unique input name (input_1, input_2, etc.)
        let inputName = 'input_1';
        let counter = 1;
        while (existingInputs[inputName]) {
          counter++;
          inputName = `input_${counter}`;
        }

        // Add to top-level inputs_schema
        const updatedInputsSchema = {
          ...existingInputs,
          [inputName]: 'Describe this input parameter'
        };

        return { inputName, updatedInputsSchema };
      };

      // Drop on canvas → Create llm_phase with input placeholder
      if (dropTarget?.type === 'canvas-background') {
        const cascadeStore = useStudioCascadeStore.getState();
        const existingCells = cascadeStore.cascade?.cells || [];

        // Add to inputs_schema first
        const { inputName, updatedInputsSchema } = addInputToSchema();

        // Find unique cell name
        let cellName = 'with_input';
        let counter = 1;
        while (existingCells.some(c => c.name === cellName)) {
          cellName = `with_input_${counter}`;
          counter++;
        }

        // Create llm_phase cell with input reference
        const newCell = {
          name: cellName,
          instructions: `Process this data:\n\n{{ input.${inputName} }}`,
        };

        const updatedCells = [...existingCells, newCell];
        updateCascade({
          inputs_schema: updatedInputsSchema,
          cells: updatedCells
        });
        return;
      }

      // Drop on cell → Add to inputs_schema and inject into instructions/code
      if (dropTarget?.type === 'cell-card') {
        const cellIndex = dropTarget.cellIndex;
        const cascadeStore = useStudioCascadeStore.getState();
        const cellToUpdate = cascadeStore.cascade?.cells[cellIndex];

        if (cellToUpdate) {
          // Add to inputs_schema first
          const { inputName, updatedInputsSchema } = addInputToSchema();

          const jinjaRef = `{{ input.${inputName} }}`;

          // Inject into instructions (preferred) or code field
          const updatedCells = [...cascadeStore.cascade.cells];

          if (cellToUpdate.instructions !== undefined) {
            // Add to instructions field
            const currentInstructions = cellToUpdate.instructions || '';
            updatedCells[cellIndex] = {
              ...cellToUpdate,
              instructions: currentInstructions + (currentInstructions ? '\n\n' : '') + jinjaRef
            };
          } else if (cellToUpdate.inputs?.code !== undefined) {
            // Add to code field (for deterministic cells like python_data, sql_data)
            const currentCode = cellToUpdate.inputs.code || '';
            updatedCells[cellIndex] = {
              ...cellToUpdate,
              inputs: {
                ...cellToUpdate.inputs,
                code: currentCode + (currentCode ? '\n\n' : '') + `# Input: ${jinjaRef}\n`
              }
            };
          } else {
            // Fallback: create instructions field
            updatedCells[cellIndex] = {
              ...cellToUpdate,
              instructions: jinjaRef
            };
          }

          updateCascade({
            inputs_schema: updatedInputsSchema,
            cells: updatedCells
          });
        }
        return;
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
    fetchCellTypes();
  }, [fetchConnections, fetchDefaultModel, fetchCellTypes]);

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

      // Priority 1: If session provided, check if it's running or finished
      if (initialSession) {
        console.log('[StudioPage] Loading session from URL:', initialSession);

        try {
          // First, check if this session is currently running
          const statusRes = await fetch(`http://localhost:5001/api/sessions/${initialSession}`);
          const statusData = await statusRes.json();

          const isActiveSession = statusData.session_id &&
                                   ['starting', 'running', 'blocked'].includes(statusData.status?.toLowerCase());

          if (isActiveSession) {
            console.log('[StudioPage] ⚡ Session is RUNNING, joining as live session');
            // Join as live session (not replay)
            await joinLiveSession(initialSession, statusData.cascade_id, statusData.cascade_file || null);
          } else {
            console.log('[StudioPage] 📖 Session is finished, loading in replay mode');
            // Step 1: Load cascade definition
            await setReplayMode(initialSession);

            // Step 2: Fetch session data BEFORE activating UI
            console.log('[StudioPage] Fetching replay data...');
            const result = await useStudioCascadeStore.getState().fetchReplayData(initialSession);

            if (result.success) {
              console.log('[StudioPage] ✓ Replay data loaded:', result.cellCount, 'cells');
            } else {
              console.warn('[StudioPage] ⚠ Replay data fetch failed:', result.error);
            }
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
          cells: []
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

  //console.log('[StudioPage] About to render. Mode check:', mode, 'isTimeline?', mode === 'timeline');

  return (
    <div className="studio-page">
      {mode === 'timeline' ? (
        /* Timeline Mode - Drag-drop context without sidebar (AppShell provides it) */
        <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="studio-timeline-layout">
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
              {/* Left Sidebar - Conditional: Context Explorer or Cascade Navigator */}
              <div className="studio-schema-panel timeline-mode">
                {selectedContextMessage && isMessagesViewVisible ? (
                  <ContextExplorerSidebar
                    selectedMessage={selectedContextMessage}
                    allLogs={allSessionLogs}
                    hoveredHash={hoveredHash}
                    onHoverHash={setHoveredHash}
                    onClose={handleCloseContextExplorer}
                    onNavigateToMessage={handleNavigateToMessage}
                  />
                ) : (
                  <CascadeNavigator />
                )}
              </div>

              {/* Timeline Area */}
              <div className="studio-timeline-area">
                <CascadeTimeline
                  key="timeline-mode"
                  onOpenBrowser={() => setIsBrowserOpen(true)}
                  onMessageContextSelect={handleMessageContextSelect}
                  onLogsUpdate={setAllSessionLogs}
                  onMessagesViewVisibleChange={setIsMessagesViewVisible}
                  hoveredHash={hoveredHash}
                  onHoverHash={setHoveredHash}
                  gridSelectedMessage={gridSelectedMessage}
                  onGridMessageSelect={setGridSelectedMessage}
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
                {activeDragItem.type === 'cell-type' && (
                  <div className="studio-drag-cell">
                    Adding {activeDragItem.cellType}...
                  </div>
                )}
                {activeDragItem.type === 'input-placeholder' && (
                  <div className="studio-drag-input">
                    <Icon icon="mdi:textbox" width="14" style={{ color: '#34d399' }} />
                    <span style={{ color: '#34d399' }}>Input</span>
                  </div>
                )}
                {activeDragItem.type === 'tool' && (
                  <div className="studio-drag-tool">
                    <Icon icon="mdi:tools" width="14" />
                    {activeDragItem.toolId}
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
