import React, { useCallback, useState, useEffect, useRef } from 'react';
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
    availableCascades,
    isLoadingCascades,
    fetchCascadeList,
    loadCascade,
    loadFromUrl,
    totalSessionCost,
    loadedSessionId,
  } = usePlaygroundStore();

  // Subscribe to SSE events for real-time updates
  usePlaygroundSSE();

  // Load cascade from URL on mount
  useEffect(() => {
    loadFromUrl();
  }, [loadFromUrl]);

  // Dropdown state
  const [isLoadDropdownOpen, setIsLoadDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsLoadDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Fetch cascade list when dropdown opens
  const handleOpenLoadDropdown = useCallback(async () => {
    setIsLoadDropdownOpen(!isLoadDropdownOpen);
    if (!isLoadDropdownOpen) {
      await fetchCascadeList();
    }
  }, [isLoadDropdownOpen, fetchCascadeList]);

  // Load a cascade
  const handleLoadCascade = useCallback(async (cascadeSessionId) => {
    const result = await loadCascade(cascadeSessionId);
    if (result.success) {
      setIsLoadDropdownOpen(false);
    } else {
      alert(`Failed to load cascade: ${result.error}`);
    }
  }, [loadCascade]);

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
            <Icon icon="mdi:image-multiple" width="24" className="playground-logo" />
            <h1 className="playground-title">Image Playground</h1>
          </div>

          <div className="playground-header-center">
            <button className="toolbar-btn" onClick={handleNew} title="New Playground">
              <Icon icon="mdi:file-plus" width="18" />
              <span>New</span>
            </button>

            {/* Load Dropdown */}
            <div className="load-dropdown-container" ref={dropdownRef}>
              <button
                className={`toolbar-btn ${isLoadDropdownOpen ? 'active' : ''}`}
                onClick={handleOpenLoadDropdown}
                title="Load Saved Cascade"
              >
                <Icon icon="mdi:folder-open" width="18" />
                <span>Load</span>
                <Icon icon="mdi:chevron-down" width="14" />
              </button>
              {isLoadDropdownOpen && (
                <div className="load-dropdown-menu">
                  {isLoadingCascades ? (
                    <div className="load-dropdown-loading">
                      <Icon icon="mdi:loading" className="spinning" width="16" />
                      <span>Loading...</span>
                    </div>
                  ) : availableCascades.length === 0 ? (
                    <div className="load-dropdown-empty">
                      <Icon icon="mdi:file-hidden" width="16" />
                      <span>No saved cascades</span>
                    </div>
                  ) : (
                    availableCascades.map((cascade) => (
                      <button
                        key={cascade.session_id}
                        className="load-dropdown-item"
                        onClick={() => handleLoadCascade(cascade.session_id)}
                      >
                        <div className="load-dropdown-item-main">
                          <Icon icon="mdi:graph" width="14" />
                          <span className="load-dropdown-item-id">{cascade.session_id}</span>
                        </div>
                        <div className="load-dropdown-item-meta">
                          <span>{cascade.image_node_count} nodes</span>
                          <span className="load-dropdown-item-date">
                            {new Date(cascade.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>

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

            {(loadedSessionId || sessionId) && (
              <span
                className={`session-badge ${loadedSessionId ? 'loaded' : ''}`}
                title={loadedSessionId || sessionId}
              >
                <Icon icon={loadedSessionId ? 'mdi:folder-open' : 'mdi:identifier'} width="14" />
                {(loadedSessionId || sessionId).slice(0, 12)}...
              </span>
            )}

            {executionStatus === 'completed' && totalSessionCost > 0 && (
              <span className="cost-badge" title={`Total session cost: $${totalSessionCost.toFixed(4)}`}>
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
      </div>
    </ReactFlowProvider>
  );
}

export default PlaygroundPage;
