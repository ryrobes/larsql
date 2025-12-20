import React, { useCallback } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import { ReactFlowProvider } from 'reactflow';
import usePlaygroundStore from './stores/playgroundStore';
import usePlaygroundSSE from './execution/usePlaygroundSSE';
import Palette from './palette/Palette';
import PlaygroundCanvas from './canvas/PlaygroundCanvas';
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
  } = usePlaygroundStore();

  // Subscribe to SSE events for real-time updates
  usePlaygroundSSE();

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

  return (
    <ReactFlowProvider>
      <div className="playground-page">
        {/* Header Toolbar */}
        <header className="playground-header">
          <div className="playground-header-left">
            <Icon icon="mdi:image-multiple" width="24" className="playground-logo" />
            <h1 className="playground-title">Image Playground</h1>
          </div>

          <div className="playground-header-center">
            <button className="toolbar-btn" onClick={handleNew} title="New Playground">
              <Icon icon="mdi:file-plus" width="18" />
              <span>New</span>
            </button>
            <button className="toolbar-btn" onClick={handleClear} title="Clear Results">
              <Icon icon="mdi:eraser" width="18" />
              <span>Clear</span>
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
      </div>
    </ReactFlowProvider>
  );
}

export default PlaygroundPage;
