import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import RagSearchTab from './RagSearchTab';
import SqlSearchTab from './SqlSearchTab';
import MemorySearchTab from './MemorySearchTab';
import MessageSearchTab from './MessageSearchTab';
import RagTestTab from './RagTestTab';
import './SearchView.css';

function SearchView({ onBack, searchTab }) {
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
      {/* Header */}
      <div className="search-view-header">
        <div className="header-left">
          <button className="back-button" onClick={onBack}>
            <Icon icon="mdi:arrow-left" width="20" />
          </button>
          <Icon icon="mdi:database-search" width="32" className="search-icon" />
          <div className="header-title">
            <h1>Search & RAG Testing</h1>
            <span className="subtitle">Semantic search across documents, schemas, and conversations</span>
          </div>
        </div>
      </div>

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
