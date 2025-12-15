import React, { useState, useEffect, useCallback } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import ToolList from './ToolList';
import ToolDetailPanel from './ToolDetailPanel';
import './ToolBrowserView.css';

const API_BASE_URL = 'http://localhost:5001/api';

function ToolBrowserView({ onBack }) {
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
      {/* Header */}
      <div className="tool-browser-header">
        <div className="header-left">
          <button className="back-button" onClick={onBack}>
            <Icon icon="mdi:arrow-left" width="20" />
          </button>
          <Icon icon="mdi:toolbox" width="32" className="toolbox-icon" />
          <div className="header-title">
            <h1>Tool Browser</h1>
            <span className="subtitle">Test and explore available tools</span>
          </div>
        </div>
        <div className="header-stats">
          <span className="stat">
            <Icon icon="mdi:hammer-wrench" width="16" />
            {Object.keys(tools).length} tools
          </span>
          <span className="stat">
            <Icon icon="mdi:filter" width="16" />
            {filteredTools.length} visible
          </span>
        </div>
      </div>

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
