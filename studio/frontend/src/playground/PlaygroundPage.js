import React, { useCallback, useState, useEffect, useRef } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import { ReactFlowProvider } from 'reactflow';
import usePlaygroundStore from './stores/playgroundStore';
import usePlaygroundSSE from './execution/usePlaygroundSSE';
import Palette from './palette/Palette';
import PlaygroundCanvas from './canvas/PlaygroundCanvas';
import CascadeBrowser from './components/CascadeBrowser';
import './PlaygroundPage.css';

/**
 * PlaygroundPage - Visual node-based editor for image generation workflows
 *
 * Split-pane layout:
 * - Left: Palette of draggable node types
 * - Right: React Flow canvas for building workflows
 */
function PlaygroundPage() {
  const {
    nodes,
    sessionId,
    executionStatus,
    runCascade,
    clearExecution,
    resetPlayground,
    loadCascade,
    loadCascadeFromFile,
    loadFromUrl,
    totalSessionCost,
    loadedSessionId,
    loadedCascadeId,
    saveCascadeAs,
  } = usePlaygroundStore();

  // Cascade browser modal state
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Subscribe to SSE events for real-time updates
  usePlaygroundSSE();

  // Load cascade from URL on mount
  useEffect(() => {
    loadFromUrl();
  }, [loadFromUrl]);

  // Save As dialog state
  const [isSaveAsOpen, setIsSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState('');
  const [saveAsDescription, setSaveAsDescription] = useState('');
  const [saveAsLocation, setSaveAsLocation] = useState('tackle');
  const [saveAsKeepMetadata, setSaveAsKeepMetadata] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  // Handle file selection from browser modal
  const handleBrowserLoad = useCallback(async (file) => {
    // Determine how to load based on file location
    if (file.has_playground) {
      // Has playground metadata - use loadCascade with session ID
      const sessionId = file.filename.replace('.yaml', '').replace('.json', '');
      const result = await loadCascade(sessionId);
      if (!result.success) {
        alert(`Failed to load cascade: ${result.error}`);
      }
    } else {
      // No playground metadata - use introspection via loadCascadeFromFile
      const result = await loadCascadeFromFile(file.filepath);
      if (!result.success) {
        alert(`Failed to load cascade: ${result.error}`);
      }
    }
  }, [loadCascade, loadCascadeFromFile]);

  // Run the cascade
  const handleRun = useCallback(async () => {
    const result = await runCascade();
    if (!result.success) {
      alert(`Failed to run cascade: ${result.error}`);
    }
  }, [runCascade]);

  // Clear execution results
  const handleClear = useCallback(() => {
    clearExecution();
  }, [clearExecution]);

  // Reset the entire playground
  const handleNew = useCallback(() => {
    if (nodes.length > 0) {
      if (!window.confirm('Clear the playground and start fresh?')) {
        return;
      }
    }
    resetPlayground();
  }, [nodes.length, resetPlayground]);

  // Check if we can run (need at least one prompt node connected to a generator)
  const canRun = nodes.length > 0;

  // Open Save As dialog
  const handleOpenSaveAs = useCallback(() => {
    // Pre-fill name from loaded cascade if available
    setSaveAsName(loadedCascadeId || '');
    setSaveAsDescription('');
    setSaveAsLocation('tackle');
    setSaveAsKeepMetadata(true);
    setSaveError(null);
    setIsSaveAsOpen(true);
  }, [loadedCascadeId]);

  // Close Save As dialog
  const handleCloseSaveAs = useCallback(() => {
    setIsSaveAsOpen(false);
    setSaveError(null);
  }, []);

  // Handle Save As submit
  const handleSaveAs = useCallback(async (e) => {
    e.preventDefault();
    setSaveError(null);
    setIsSaving(true);

    const result = await saveCascadeAs({
      cascadeId: saveAsName.trim(),
      description: saveAsDescription.trim(),
      saveTo: saveAsLocation,
      keepMetadata: saveAsKeepMetadata,
    });

    setIsSaving(false);

    if (result.success) {
      setIsSaveAsOpen(false);
      // Show success message
      const locationLabel = saveAsLocation === 'tackle' ? 'Tool' : 'Cascade';
      alert(`Saved as ${locationLabel}: ${result.cascadeId}\n\nPath: ${result.filepath}`);
    } else {
      setSaveError(result.error);
    }
  }, [saveAsName, saveAsDescription, saveAsLocation, saveAsKeepMetadata, saveCascadeAs]);

  // Format cost for display
  const formatCost = (cost) => {
    if (!cost || cost === 0) return null;
    if (cost < 0.001) return '<$0.001';
    if (cost < 0.01) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  return (
    <ReactFlowProvider>
      <div className="playground-page">
        {/* Header Toolbar */}
        <header className="playground-header">
          <div className="playground-header-left">
            <button
              className="toolbar-btn home-btn"
              onClick={() => window.location.hash = '#/'}
              title="Back to Dashboard"
            >
              <Icon icon="mdi:home" width="20" />
            </button>
            <Icon icon="mdi:image-multiple" width="24" className="playground-logo" />
            <h1 className="playground-title">Image Playground</h1>
          </div>

          <div className="playground-header-center">
            <button className="toolbar-btn" onClick={handleNew} title="New Playground">
              <Icon icon="mdi:file-plus" width="18" />
              <span>New</span>
            </button>

            <button
              className="toolbar-btn"
              onClick={() => setIsBrowserOpen(true)}
              title="Open Cascade"
            >
              <Icon icon="mdi:folder-open" width="18" />
              <span>Open</span>
            </button>

            <button className="toolbar-btn" onClick={handleClear} title="Clear Results">
              <Icon icon="mdi:eraser" width="18" />
              <span>Clear</span>
            </button>

            <div className="toolbar-divider" />

            <button
              className="toolbar-btn"
              onClick={handleOpenSaveAs}
              disabled={!canRun}
              title="Save as named tool or cascade"
            >
              <Icon icon="mdi:content-save-edit" width="18" />
              <span>Save As...</span>
            </button>
          </div>

          <div className="playground-header-right">
            {executionStatus === 'running' ? (
              <button className="toolbar-btn running" disabled>
                <Icon icon="mdi:loading" width="18" className="spinning" />
                <span>Running...</span>
              </button>
            ) : (
              <button
                className="toolbar-btn primary"
                onClick={handleRun}
                disabled={!canRun}
                title="Run Workflow"
              >
                <Icon icon="mdi:play" width="18" />
                <span>Run</span>
              </button>
            )}

            {(loadedSessionId || sessionId) && (
              <span
                className={`session-badge ${loadedSessionId ? 'loaded' : ''}`}
                title={loadedSessionId || sessionId}
              >
                <Icon icon={loadedSessionId ? 'mdi:folder-open' : 'mdi:identifier'} width="14" />
                {(loadedSessionId || sessionId).slice(0, 12)}...
              </span>
            )}

            {(executionStatus === 'running' || executionStatus === 'completed') && totalSessionCost > 0 && (
              <span
                className={`cost-badge ${executionStatus === 'running' ? 'updating' : ''}`}
                title={`Total session cost: $${totalSessionCost.toFixed(4)}${executionStatus === 'running' ? ' (updating...)' : ''}`}
              >
                <Icon icon="mdi:currency-usd" width="14" />
                {formatCost(totalSessionCost)}
              </span>
            )}
          </div>
        </header>

        {/* Main Split Pane */}
        <Split
          className="playground-split"
          sizes={[15, 85]}
          minSize={[200, 400]}
          gutterSize={8}
          gutterAlign="center"
          direction="horizontal"
        >
          {/* Left Pane: Palette */}
          <div className="playground-pane palette-pane">
            <Palette />
          </div>

          {/* Right Pane: Canvas */}
          <div className="playground-pane canvas-pane">
            <PlaygroundCanvas />
          </div>
        </Split>

        {/* Save As Modal */}
        {isSaveAsOpen && (
          <div className="modal-overlay" onClick={handleCloseSaveAs}>
            <div className="modal-dialog save-as-dialog" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h2>
                  <Icon icon="mdi:content-save-edit" width="20" />
                  Save As
                </h2>
                <button className="modal-close" onClick={handleCloseSaveAs}>
                  <Icon icon="mdi:close" width="20" />
                </button>
              </div>

              <form onSubmit={handleSaveAs}>
                <div className="modal-body">
                  {saveError && (
                    <div className="save-as-error">
                      <Icon icon="mdi:alert-circle" width="16" />
                      {saveError}
                    </div>
                  )}

                  <div className="form-group">
                    <label htmlFor="save-as-name">
                      Name <span className="required">*</span>
                    </label>
                    <input
                      id="save-as-name"
                      type="text"
                      value={saveAsName}
                      onChange={(e) => setSaveAsName(e.target.value)}
                      placeholder="my_image_workflow"
                      pattern="^[a-zA-Z][a-zA-Z0-9_]*$"
                      required
                      autoFocus
                    />
                    <span className="form-hint">
                      Letters, numbers, underscores. Must start with a letter.
                    </span>
                  </div>

                  <div className="form-group">
                    <label htmlFor="save-as-description">Description</label>
                    <textarea
                      id="save-as-description"
                      value={saveAsDescription}
                      onChange={(e) => setSaveAsDescription(e.target.value)}
                      placeholder="What does this workflow do?"
                      rows={2}
                    />
                  </div>

                  <div className="form-group">
                    <label>Save To</label>
                    <div className="radio-group">
                      <label className="radio-option">
                        <input
                          type="radio"
                          name="save-as-location"
                          value="tackle"
                          checked={saveAsLocation === 'tackle'}
                          onChange={(e) => setSaveAsLocation(e.target.value)}
                        />
                        <div className="radio-content">
                          <Icon icon="mdi:tools" width="18" />
                          <div>
                            <strong>Tool</strong>
                            <span>Callable from other cascades via tackle</span>
                          </div>
                        </div>
                      </label>
                      <label className="radio-option">
                        <input
                          type="radio"
                          name="save-as-location"
                          value="cascades"
                          checked={saveAsLocation === 'cascades'}
                          onChange={(e) => setSaveAsLocation(e.target.value)}
                        />
                        <div className="radio-content">
                          <Icon icon="mdi:file-document" width="18" />
                          <div>
                            <strong>Cascade</strong>
                            <span>Standalone runnable workflow</span>
                          </div>
                        </div>
                      </label>
                    </div>
                  </div>

                  <div className="form-group checkbox-group">
                    <label className="checkbox-option">
                      <input
                        type="checkbox"
                        checked={saveAsKeepMetadata}
                        onChange={(e) => setSaveAsKeepMetadata(e.target.checked)}
                      />
                      <span>Keep playground metadata (allows re-editing in playground)</span>
                    </label>
                  </div>
                </div>

                <div className="modal-footer">
                  <button type="button" className="btn-secondary" onClick={handleCloseSaveAs}>
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={isSaving || !saveAsName.trim()}
                  >
                    {isSaving ? (
                      <>
                        <Icon icon="mdi:loading" className="spinning" width="16" />
                        Saving...
                      </>
                    ) : (
                      <>
                        <Icon icon="mdi:content-save" width="16" />
                        Save
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Cascade Browser Modal */}
        <CascadeBrowser
          isOpen={isBrowserOpen}
          onClose={() => setIsBrowserOpen(false)}
          onLoad={handleBrowserLoad}
        />
      </div>
    </ReactFlowProvider>
  );
}

export default PlaygroundPage;
