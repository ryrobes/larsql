import React, { useState, useEffect, useCallback } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import ToolList from './ToolList';
import ToolDetailPanel from './ToolDetailPanel';
import Header from './Header';
import './ToolBrowserView.css';

const API_BASE_URL = 'http://localhost:5001/api';

function ToolBrowserView({
  onBack,
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
  sseConnected
}) {
  const [tools, setTools] = useState({});
  const [selectedTool, setSelectedTool] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterText, setFilterText] = useState('');
  const [filterType, setFilterType] = useState('all');

  // Load tools manifest on mount
  useEffect(() => {
    loadTools();
  }, []);

  const loadTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/tools/manifest`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setTools(data.tools || {});
      }
    } catch (err) {
      setError('Failed to load tools: ' + err.message);
    }
    setLoading(false);
  };

  const handleSelectTool = (toolName) => {
    setSelectedTool(toolName);
  };

  // Filter tools
  const filteredTools = Object.entries(tools).filter(([name, tool]) => {
    const matchesText = name.toLowerCase().includes(filterText.toLowerCase()) ||
                       (tool.description && tool.description.toLowerCase().includes(filterText.toLowerCase()));

    const matchesType = filterType === 'all' ||
                       tool.type === filterType ||
                       tool.type.startsWith(filterType + ':');

    return matchesText && matchesType;
  });

  return (
    <div className="tool-browser-container">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:toolbox" width="24" />
            <span className="header-stat">Tool Browser</span>
            <span className="header-divider">·</span>
            <span className="header-stat">{Object.keys(tools).length} <span className="stat-dim">tools</span></span>
            <span className="header-divider">·</span>
            <span className="header-stat">{filteredTools.length} <span className="stat-dim">visible</span></span>
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

      {/* Main Split Pane */}
      <Split
        className="tool-browser-split"
        sizes={[35, 65]}
        minSize={[300, 400]}
        gutterSize={8}
        direction="horizontal"
      >
        {/* Left: Tool List */}
        <div className="tool-browser-pane list-pane">
          <ToolList
            tools={filteredTools}
            selectedTool={selectedTool}
            onSelectTool={handleSelectTool}
            filterText={filterText}
            filterType={filterType}
            onFilterTextChange={setFilterText}
            onFilterTypeChange={setFilterType}
            loading={loading}
            error={error}
          />
        </div>

        {/* Right: Tool Detail & Execution */}
        <div className="tool-browser-pane detail-pane">
          {selectedTool ? (
            <ToolDetailPanel
              toolName={selectedTool}
              toolInfo={tools[selectedTool]}
              onRefresh={loadTools}
            />
          ) : (
            <div className="empty-state">
              <Icon icon="mdi:hand-pointing-left" width="64" />
              <h2>Select a tool to test</h2>
              <p>Choose a tool from the list to view its parameters and execute it</p>
            </div>
          )}
        </div>
      </Split>
    </div>
  );
}

export default ToolBrowserView;
