import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import RagSearchTab from './RagSearchTab';
import SqlSearchTab from './SqlSearchTab';
import MemorySearchTab from './MemorySearchTab';
import MessageSearchTab from './MessageSearchTab';
import RagTestTab from './RagTestTab';
import Header from './Header';
import './SearchView.css';

function SearchView({
  onBack,
  searchTab,
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onStudio,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
  sseConnected
}) {
  const [activeTab, setActiveTab] = useState(searchTab || 'rag');

  // Update active tab when searchTab prop changes (from URL hash)
  useEffect(() => {
    if (searchTab) {
      setActiveTab(searchTab);
    }
  }, [searchTab]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    // Update URL hash
    window.location.hash = `#/search/${tab}`;
  };

  const tabs = [
    { id: 'rag', label: 'RAG Documents', icon: 'mdi:file-document-multiple' },
    { id: 'sql', label: 'SQL Schemas', icon: 'mdi:database-search' },
    { id: 'memory', label: 'Memory', icon: 'mdi:brain' },
    { id: 'messages', label: 'Messages', icon: 'mdi:message-text-outline' },
    { id: 'ragtest', label: 'RAG Test', icon: 'mdi:flask-outline' }
  ];

  return (
    <div className="search-view-container">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:database-search" width="24" />
            <span className="header-stat">Search & RAG Testing</span>
            <span className="header-divider">·</span>
            <span className="header-stat stat-dim">Semantic search</span>
          </>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onPlayground={onPlayground}
        onTools={onTools}
        onSearch={onSearch}
        onStudio={onStudio}
        onArtifacts={onArtifacts}
        onBrowser={onBrowser}
        onSessions={onSessions}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {/* Tab Navigation */}
      <div className="search-tabs">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`search-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => handleTabChange(tab.id)}
          >
            <Icon icon={tab.icon} width="18" />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="search-tab-content">
        {activeTab === 'rag' && <RagSearchTab />}
        {activeTab === 'sql' && <SqlSearchTab />}
        {activeTab === 'memory' && <MemorySearchTab />}
        {activeTab === 'messages' && <MessageSearchTab />}
        {activeTab === 'ragtest' && <RagTestTab />}
      </div>
    </div>
  );
}

export default SearchView;
