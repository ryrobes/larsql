/**
 * TabBar - Tab navigation for Hyper workspaces
 *
 * Features:
 * - Clickable tabs with icons
 * - Close button on non-system tabs
 * - "+" button to add new tabs
 * - Double-click to rename
 * - Visual distinction for system tabs (cost analysis)
 */

import React, { useState, useRef, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './TabBar.css';

const TabBar = ({
  tabs,
  activeTabId,
  onTabClick,
  onTabClose,
  onTabAdd,
  onTabRename,
}) => {
  const [editingTabId, setEditingTabId] = useState(null);
  const [editingName, setEditingName] = useState('');
  const inputRef = useRef(null);

  // Focus input when editing starts
  useEffect(() => {
    if (editingTabId && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingTabId]);

  const handleDoubleClick = (tab) => {
    if (tab.isSystem) return; // Can't rename system tabs
    setEditingTabId(tab.id);
    setEditingName(tab.name);
  };

  const handleRenameSubmit = () => {
    if (editingTabId && editingName.trim()) {
      onTabRename(editingTabId, editingName.trim());
    }
    setEditingTabId(null);
    setEditingName('');
  };

  const handleRenameKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleRenameSubmit();
    } else if (e.key === 'Escape') {
      setEditingTabId(null);
      setEditingName('');
    }
  };

  const getTabIcon = (tab) => {
    if (tab.icon) return tab.icon;
    if (tab.isSystem) {
      switch (tab.systemType) {
        case 'cost-analysis':
          return 'mdi:chart-timeline-variant';
        default:
          return 'mdi:cog';
      }
    }
    // File-based tabs show file icon
    if (tab.filePath) {
      return 'mdi:file-document-outline';
    }
    return 'mdi:database-search';
  };

  return (
    <div className="tab-bar">
      <div className="tab-bar-tabs">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`tab-bar-tab ${tab.id === activeTabId ? 'active' : ''} ${tab.isSystem ? 'system' : ''} ${tab.isDirty ? 'dirty' : ''} ${tab.filePath ? 'file-tab' : ''}`}
            onClick={() => onTabClick(tab.id)}
            onDoubleClick={() => handleDoubleClick(tab)}
            title={tab.isSystem ? `${tab.name} (System)` : (tab.isDirty ? `${tab.name} (unsaved)` : tab.name)}
          >
            <Icon
              icon={getTabIcon(tab)}
              width="14"
              className="tab-icon"
            />

            {editingTabId === tab.id ? (
              <input
                ref={inputRef}
                type="text"
                className="tab-name-input"
                value={editingName}
                onChange={(e) => setEditingName(e.target.value)}
                onBlur={handleRenameSubmit}
                onKeyDown={handleRenameKeyDown}
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="tab-name">
                {tab.name}
                {tab.isDirty && <span className="tab-dirty-dot" title="Unsaved changes">●</span>}
              </span>
            )}

            {/* Close button - only for non-system tabs and if more than one tab */}
            {!tab.isSystem && tabs.filter(t => !t.isSystem).length > 1 && (
              <button
                className="tab-close-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  onTabClose(tab.id);
                }}
                title="Close tab"
              >
                <Icon icon="mdi:close" width="12" />
              </button>
            )}

            {/* System tab indicator */}
            {tab.isSystem && (
              <span className="tab-system-badge" title="System tab">
                <Icon icon="mdi:auto-fix" width="10" />
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Add new tab button */}
      <button
        className="tab-bar-add-btn"
        onClick={() => onTabAdd()}
        title="New query tab"
      >
        <Icon icon="mdi:plus" width="16" />
      </button>
    </div>
  );
};

export default TabBar;
