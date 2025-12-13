import React, { useCallback, useRef, useState, useEffect } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import useWorkshopStore from './stores/workshopStore';
import BlockEditor from './editor/BlockEditor';
import MonacoYamlEditor from './editor/MonacoYamlEditor';
import ExecutionNotebook from './notebook/ExecutionNotebook';
import InputDialog from './components/InputDialog';
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
  const [showInputDialog, setShowInputDialog] = useState(false);

  const {
    cascade,
    isDirty,
    editorMode,
    setEditorMode,
    yamlContent,
    setYamlContent,
    syncToYaml,
    syncFromYaml,
    executionStatus,
    sessionId,
    loadFromYaml,
    exportToYaml,
    resetCascade,
    runCascade,
    clearExecution,
  } = useWorkshopStore();

  // Keep YAML content in sync when in visual mode
  useEffect(() => {
    if (editorMode === 'visual') {
      syncToYaml();
    }
  }, [cascade, editorMode, syncToYaml]);

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

  const handleRun = useCallback(() => {
    setShowInputDialog(true);
  }, []);

  const handleConfirmRun = useCallback(async (inputs) => {
    setShowInputDialog(false);
    const result = await runCascade(inputs);
    if (!result.success) {
      alert(`Failed to run cascade: ${result.error}`);
    }
  }, [runCascade]);

  // Handle mode switch between Visual and YAML editor
  const handleModeSwitch = useCallback((newMode) => {
    if (newMode === editorMode) return;

    if (newMode === 'yaml') {
      // Switching TO yaml mode - sync current state to YAML
      syncToYaml();
    } else {
      // Switching TO visual mode - parse YAML and update state
      const result = syncFromYaml();
      if (!result.success) {
        alert(`YAML has errors:\n${result.error}\n\nFix the YAML before switching to Visual mode.`);
        return;
      }
    }
    setEditorMode(newMode);
  }, [editorMode, syncToYaml, syncFromYaml, setEditorMode]);

  // Handle YAML changes in Monaco editor
  const handleYamlChange = useCallback((newYaml) => {
    setYamlContent(newYaml);
  }, [setYamlContent]);

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

          {/* Editor Mode Toggle */}
          <div className="editor-mode-toggle">
            <button
              className={`mode-btn ${editorMode === 'visual' ? 'active' : ''}`}
              onClick={() => handleModeSwitch('visual')}
              title="Visual Editor"
            >
              <Icon icon="mdi:puzzle" width="16" />
              <span>Visual</span>
            </button>
            <button
              className={`mode-btn ${editorMode === 'yaml' ? 'active' : ''}`}
              onClick={() => handleModeSwitch('yaml')}
              title="YAML Editor"
            >
              <Icon icon="mdi:code-braces" width="16" />
              <span>YAML</span>
            </button>
          </div>

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
              disabled={!cascade.phases || cascade.phases.length === 0}
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
        {/* Left Pane: Block Editor or YAML Editor */}
        <div className="workshop-pane editor-pane">
          {editorMode === 'visual' ? (
            <BlockEditor />
          ) : (
            <MonacoYamlEditor
              value={yamlContent}
              onChange={handleYamlChange}
            />
          )}
        </div>

        {/* Right Pane: Execution Notebook */}
        <div className="workshop-pane notebook-pane">
          <ExecutionNotebook />
        </div>
      </Split>

      {/* Input Dialog */}
      <InputDialog
        isOpen={showInputDialog}
        onClose={() => setShowInputDialog(false)}
        onRun={handleConfirmRun}
        inputsSchema={cascade.inputs_schema}
        cascadeId={cascade.cascade_id}
      />
    </div>
  );
}

export default WorkshopPage;
