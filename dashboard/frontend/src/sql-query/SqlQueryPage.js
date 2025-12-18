import React, { useEffect } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import useSqlQueryStore from './stores/sqlQueryStore';
import SchemaTree from './components/SchemaTree';
import QueryTabManager from './components/QueryTabManager';
import SqlEditor from './components/SqlEditor';
import QueryResultsGrid from './components/QueryResultsGrid';
import QueryHistoryPanel from './components/QueryHistoryPanel';
import Header from '../components/Header';
import './SqlQueryPage.css';

function SqlQueryPage({
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
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
  const {
    historyPanelOpen,
    fetchConnections,
    connections
  } = useSqlQueryStore();

  // Fetch connections on mount
  useEffect(() => {
    fetchConnections();
  }, [fetchConnections]);

  // Set default connection for first tab when connections load
  useEffect(() => {
    if (connections.length > 0) {
      const state = useSqlQueryStore.getState();
      const activeTab = state.tabs.find(t => t.id === state.activeTabId);
      if (activeTab && !activeTab.connection) {
        state.updateTab(activeTab.id, { connection: connections[0].name });
      }
    }
  }, [connections]);

  return (
    <div className="sql-query-page">
      <Header
        centerContent={
          <>
            <Icon icon="mdi:database-search" width="24" />
            <span className="header-stat">SQL Query IDE</span>
            <span className="header-divider">·</span>
            <span className="header-stat">{connections.length} <span className="stat-dim">connections</span></span>
          </>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
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

      {/* Main horizontal split: Schema Browser | Editor+Results */}
      <Split
        className="sql-query-horizontal-split"
        sizes={[20, 80]}
        minSize={[180, 400]}
        maxSize={[500, Infinity]}
        gutterSize={6}
        gutterAlign="center"
        direction="horizontal"
      >
        {/* Left Sidebar - Schema Browser */}
        <div className="sql-query-schema-panel">
          <div className="sql-query-schema-header">
            <span className="sql-query-schema-title">Schema Browser</span>
          </div>
          <SchemaTree />
        </div>

        {/* Main Area with vertical split: Editor | Results */}
        <Split
          className="sql-query-vertical-split"
          sizes={[60, 40]}
          minSize={[150, 100]}
          gutterSize={6}
          gutterAlign="center"
          direction="vertical"
        >
          {/* Tabs + Editor */}
          <div className="sql-query-editor-area">
            <QueryTabManager />
            <SqlEditor />
          </div>

          {/* Results Panel */}
          <div className="sql-query-results-panel">
            <QueryResultsGrid />
          </div>
        </Split>
      </Split>

      {/* History Panel (collapsible) */}
      {historyPanelOpen && (
        <div className="sql-query-history-panel">
          <QueryHistoryPanel />
        </div>
      )}
    </div>
  );
}

export default SqlQueryPage;
