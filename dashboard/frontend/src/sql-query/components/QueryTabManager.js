import React from 'react';
import { Icon } from '@iconify/react';
import useSqlQueryStore from '../stores/sqlQueryStore';
import './QueryTabManager.css';

function QueryTabManager() {
  const {
    tabs,
    activeTabId,
    setActiveTab,
    createTab,
    closeTab,
    connections,
    updateTab,
    executeQuery,
    toggleHistoryPanel,
    historyPanelOpen
  } = useSqlQueryStore();

  const activeTab = tabs.find(t => t.id === activeTabId);

  const handleCloseTab = (e, tabId) => {
    e.stopPropagation();
    if (tabs.length > 1) {
      closeTab(tabId);
    }
  };

  const handleMiddleClick = (e, tabId) => {
    if (e.button === 1) {
      e.preventDefault();
      handleCloseTab(e, tabId);
    }
  };

  const handleConnectionChange = (e) => {
    if (activeTab) {
      updateTab(activeTab.id, { connection: e.target.value });
    }
  };

  const handleExecute = () => {
    if (activeTab && activeTab.connection && activeTab.sql.trim()) {
      executeQuery(activeTab.id);
    }
  };

  return (
    <div className="query-tab-manager">
      {/* Tab Bar */}
      <div className="query-tab-bar">
        <div className="query-tabs">
          {tabs.map(tab => (
            <div
              key={tab.id}
              className={`query-tab ${tab.id === activeTabId ? 'active' : ''} ${tab.isRunning ? 'running' : ''}`}
              onClick={() => setActiveTab(tab.id)}
              onMouseDown={(e) => handleMiddleClick(e, tab.id)}
            >
              {tab.isDirty && <span className="query-tab-dirty-indicator" />}
              {tab.isRunning && <Icon icon="mdi:loading" className="query-tab-spinner spin" />}
              <span className="query-tab-title">{tab.title}</span>
              {tabs.length > 1 && (
                <button
                  className="query-tab-close"
                  onClick={(e) => handleCloseTab(e, tab.id)}
                  title="Close tab"
                >
                  <Icon icon="mdi:close" />
                </button>
              )}
            </div>
          ))}
        </div>

        <button className="query-tab-new" onClick={() => createTab()} title="New query tab">
          <Icon icon="mdi:plus" />
        </button>
      </div>

      {/* Toolbar */}
      <div className="query-toolbar">
        <div className="query-toolbar-left">
          {/* Connection Selector */}
          <div className="query-connection-selector">
            <Icon icon="mdi:database" className="query-connection-icon" />
            <select
              value={activeTab?.connection || ''}
              onChange={handleConnectionChange}
              disabled={!connections.length}
            >
              {!connections.length && <option value="">No connections</option>}
              {connections.map(conn => (
                <option key={conn.name} value={conn.name}>
                  {conn.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="query-toolbar-right">
          {/* Execution stats */}
          {activeTab?.executionTime !== null && (
            <span className="query-stats">
              {activeTab.rowCount !== null && (
                <span className="query-stat">
                  <Icon icon="mdi:table-row" />
                  {activeTab.rowCount} rows
                </span>
              )}
              <span className="query-stat">
                <Icon icon="mdi:timer-outline" />
                {activeTab.executionTime}ms
              </span>
            </span>
          )}

          {/* History Button */}
          <button
            className={`query-toolbar-btn ${historyPanelOpen ? 'active' : ''}`}
            onClick={toggleHistoryPanel}
            title="Query history"
          >
            <Icon icon="mdi:history" />
          </button>

          {/* Execute Button */}
          <button
            className="query-execute-btn"
            onClick={handleExecute}
            disabled={!activeTab?.connection || !activeTab?.sql.trim() || activeTab?.isRunning}
            title="Execute query (Ctrl+Enter)"
          >
            {activeTab?.isRunning ? (
              <>
                <Icon icon="mdi:loading" className="spin" />
                Running...
              </>
            ) : (
              <>
                <Icon icon="mdi:play" />
                Run
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export default QueryTabManager;
