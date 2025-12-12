import React, { useCallback, useRef } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import useWorkshopStore from './stores/workshopStore';
import BlockEditor from './editor/BlockEditor';
import ExecutionNotebook from './notebook/ExecutionNotebook';
import './WorkshopPage.css';

/**
 * WorkshopPage - Main container for the cascade workshop
 *
 * Split-pane layout:
 * - Left: Block-based cascade editor
 * - Right: Execution notebook (horizontal timeline)
 */
function WorkshopPage() {
  const fileInputRef = useRef(null);

  const {
    cascade,
    isDirty,
    yamlPanelOpen,
    executionStatus,
    sessionId,
    loadFromYaml,
    exportToYaml,
    resetCascade,
    toggleYamlPanel,
    runCascade,
    clearExecution,
  } = useWorkshopStore();

  // File operations
  const handleNew = useCallback(() => {
    if (isDirty) {
      if (!window.confirm('You have unsaved changes. Create new cascade anyway?')) {
        return;
      }
    }
    resetCascade();
    clearExecution();
  }, [isDirty, resetCascade, clearExecution]);

  const handleOpen = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileSelect = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const result = loadFromYaml(event.target.result);
      if (!result.success) {
        alert(`Failed to load cascade: ${result.error}`);
      }
      clearExecution();
    };
    reader.readAsText(file);

    // Reset input so same file can be selected again
    e.target.value = '';
  }, [loadFromYaml, clearExecution]);

  const handleSave = useCallback(() => {
    const yamlContent = exportToYaml();
    const blob = new Blob([yamlContent], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${cascade.cascade_id || 'cascade'}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  }, [exportToYaml, cascade.cascade_id]);

  const handleCopyYaml = useCallback(() => {
    const yamlContent = exportToYaml();
    navigator.clipboard.writeText(yamlContent).then(() => {
      // Could show a toast here
      console.log('YAML copied to clipboard');
    });
  }, [exportToYaml]);

  const handleRun = useCallback(async () => {
    // For now, run with empty input - later we'll add input modal
    const result = await runCascade({});
    if (!result.success) {
      alert(`Failed to run cascade: ${result.error}`);
    }
  }, [runCascade]);

  return (
    <div className="workshop-page">
      {/* Hidden file input for open */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".yaml,.yml,.json"
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />

      {/* Header Toolbar */}
      <header className="workshop-header">
        <div className="workshop-header-left">
          <Icon icon="mdi:anchor" width="24" className="workshop-logo" />
          <h1 className="workshop-title">Windlass Workshop</h1>
          {isDirty && <span className="dirty-indicator" title="Unsaved changes">*</span>}
        </div>

        <div className="workshop-header-center">
          <button className="toolbar-btn" onClick={handleNew} title="New Cascade">
            <Icon icon="mdi:file-plus" width="18" />
            <span>New</span>
          </button>
          <button className="toolbar-btn" onClick={handleOpen} title="Open YAML">
            <Icon icon="mdi:folder-open" width="18" />
            <span>Open</span>
          </button>
          <button className="toolbar-btn" onClick={handleSave} title="Save YAML">
            <Icon icon="mdi:content-save" width="18" />
            <span>Save</span>
          </button>
          <div className="toolbar-divider" />
          <button
            className={`toolbar-btn ${yamlPanelOpen ? 'active' : ''}`}
            onClick={toggleYamlPanel}
            title="Toggle YAML Preview"
          >
            <Icon icon="mdi:code-braces" width="18" />
            <span>YAML</span>
          </button>
          <button className="toolbar-btn" onClick={handleCopyYaml} title="Copy YAML">
            <Icon icon="mdi:content-copy" width="18" />
          </button>
        </div>

        <div className="workshop-header-right">
          {executionStatus === 'running' ? (
            <button className="toolbar-btn running" disabled>
              <Icon icon="mdi:loading" width="18" className="spinning" />
              <span>Running...</span>
            </button>
          ) : (
            <button
              className="toolbar-btn primary"
              onClick={handleRun}
              disabled={cascade.phases.length === 0}
              title="Run Cascade"
            >
              <Icon icon="mdi:play" width="18" />
              <span>Run</span>
            </button>
          )}

          {sessionId && (
            <span className="session-badge" title={sessionId}>
              <Icon icon="mdi:identifier" width="14" />
              {sessionId.slice(0, 8)}...
            </span>
          )}
        </div>
      </header>

      {/* Main Split Pane */}
      <Split
        className="workshop-split"
        sizes={[45, 55]}
        minSize={[300, 400]}
        gutterSize={8}
        gutterAlign="center"
        direction="horizontal"
      >
        {/* Left Pane: Block Editor */}
        <div className="workshop-pane editor-pane">
          <BlockEditor />
        </div>

        {/* Right Pane: Execution Notebook */}
        <div className="workshop-pane notebook-pane">
          <ExecutionNotebook />
        </div>
      </Split>
    </div>
  );
}

export default WorkshopPage;
