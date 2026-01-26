/**
 * useTabs - Tab management for Hyper SQL workspaces
 *
 * Each tab maintains its own:
 * - SQL content
 * - Execution results
 * - Panel layout state
 * - Database selection
 *
 * Special "system" tabs (like Cost Analysis) generate SQL dynamically.
 *
 * Tab naming priority:
 * 1. Explicit name from --- HYPER 'Name' comment in SQL
 * 2. File name if loaded from file
 * 3. Default "Query" or "Query 2", etc.
 */

import { useState, useCallback, useRef } from 'react';

// Generate unique tab IDs
let tabIdCounter = 0;
const generateTabId = () => `tab-${++tabIdCounter}`;

// Default query for new tabs
const DEFAULT_NEW_TAB_SQL = `--- HYPER 'New Query'
SELECT 'Hello, Hyper!' as greeting;
`;

/**
 * Parse tab name from SQL content
 * Looks for: --- HYPER 'Name' or --- HYPER (col, row) 'Name'
 */
function parseTabNameFromSql(sql) {
  if (!sql) return null;

  // Match: --- HYPER 'Name' or --- HYPER (1,2) 'Name' or --- HYPER (1,2,3,4) 'Name'
  const match = sql.match(/^---\s*HYPER\s*(?:\([^)]*\))?\s*['"]([^'"]+)['"]/m);
  return match ? match[1] : null;
}

/**
 * Create a new tab object
 */
function createTab(overrides = {}) {
  // Try to extract name from SQL if not explicitly provided
  let name = overrides.name;
  if (!name && overrides.sql) {
    name = parseTabNameFromSql(overrides.sql);
  }
  if (!name) {
    name = 'Query';
  }

  return {
    id: generateTabId(),
    name,
    sql: DEFAULT_NEW_TAB_SQL,
    database: 'memory',
    result: null,
    error: null,
    panelLayout: null,
    panelResults: new Map(),
    executionTime: null,
    lastExecutionCallerId: null,
    isSystem: false, // System tabs are special (cost analysis, etc.)
    systemType: null, // 'cost-analysis' | null
    icon: null, // Custom icon for the tab
    fileName: null, // Original file name if loaded from file
    filePath: null, // Original file path if loaded from file
    isDirty: false, // Has unsaved changes
    ...overrides,
  };
}

// Export for use in components
export { parseTabNameFromSql };

/**
 * useTabs hook - manages multiple query workspaces
 */
export function useTabs(initialSql = '') {
  // Create initial tab with provided SQL
  const [tabs, setTabs] = useState(() => [
    createTab({
      name: 'Queries',
      sql: initialSql || DEFAULT_NEW_TAB_SQL,
    }),
  ]);

  const [activeTabId, setActiveTabId] = useState(tabs[0].id);

  // Ref to track last active tab for cost analysis context
  const lastQueryTabIdRef = useRef(tabs[0].id);

  // Get active tab
  const activeTab = tabs.find(t => t.id === activeTabId) || tabs[0];

  // Get the last query tab (non-system) for cost analysis context
  const lastQueryTab = tabs.find(t => t.id === lastQueryTabIdRef.current && !t.isSystem);

  // Update active tab's state
  const updateActiveTab = useCallback((updates) => {
    setTabs(prevTabs =>
      prevTabs.map(tab =>
        tab.id === activeTabId
          ? { ...tab, ...(typeof updates === 'function' ? updates(tab) : updates) }
          : tab
      )
    );
  }, [activeTabId]);

  // Switch to a tab
  const switchTab = useCallback((tabId) => {
    // Before switching, if current tab is a query tab, remember it
    const currentTab = tabs.find(t => t.id === activeTabId);
    if (currentTab && !currentTab.isSystem) {
      lastQueryTabIdRef.current = activeTabId;
    }
    setActiveTabId(tabId);
  }, [activeTabId, tabs]);

  // Add a new tab
  const addTab = useCallback((overrides = {}) => {
    const newTab = createTab(overrides);
    setTabs(prevTabs => [...prevTabs, newTab]);
    setActiveTabId(newTab.id);
    return newTab.id;
  }, []);

  // Close a tab
  const closeTab = useCallback((tabId) => {
    setTabs(prevTabs => {
      const newTabs = prevTabs.filter(t => t.id !== tabId);

      // Don't allow closing the last tab
      if (newTabs.length === 0) {
        return prevTabs;
      }

      // If we're closing the active tab, switch to another
      if (tabId === activeTabId) {
        const closedIndex = prevTabs.findIndex(t => t.id === tabId);
        const newActiveIndex = Math.min(closedIndex, newTabs.length - 1);
        setActiveTabId(newTabs[newActiveIndex].id);
      }

      return newTabs;
    });
  }, [activeTabId]);

  // Rename a tab
  const renameTab = useCallback((tabId, newName) => {
    setTabs(prevTabs =>
      prevTabs.map(tab =>
        tab.id === tabId ? { ...tab, name: newName } : tab
      )
    );
  }, []);

  // Duplicate a tab
  const duplicateTab = useCallback((tabId) => {
    const sourcetab = tabs.find(t => t.id === tabId);
    if (!sourcetab || sourcetab.isSystem) return null;

    const newTab = createTab({
      name: `${sourcetab.name} (copy)`,
      sql: sourcetab.sql,
      database: sourcetab.database,
    });

    setTabs(prevTabs => [...prevTabs, newTab]);
    setActiveTabId(newTab.id);
    return newTab.id;
  }, [tabs]);

  // Open Cost Analysis tab for the current query tab
  // Each query tab gets its own analysis tab (linked by sourceTabId)
  const openCostAnalysisTab = useCallback((explainData, actualCostData, callerId) => {
    const sourceTabId = lastQueryTabIdRef.current;
    const sourceTab = tabs.find(t => t.id === sourceTabId);
    const sourceTabName = sourceTab?.name || 'Query';

    // Check if an analysis tab for THIS source tab already exists
    const existingTab = tabs.find(t =>
      t.isSystem &&
      t.systemType === 'cost-analysis' &&
      t.sourceTabId === sourceTabId
    );

    if (existingTab) {
      // Update existing tab with new data
      setTabs(prevTabs =>
        prevTabs.map(tab =>
          tab.id === existingTab.id
            ? {
                ...tab,
                explainData,
                actualCostData,
                callerId,
              }
            : tab
        )
      );
      setActiveTabId(existingTab.id);
      return existingTab.id;
    }

    // Create new cost analysis tab for this source
    const newTab = createTab({
      name: `${sourceTabName} - Analysis`,
      isSystem: true,
      systemType: 'cost-analysis',
      icon: 'mdi:chart-timeline-variant',
      explainData,
      actualCostData,
      callerId,
      sourceTabId,
    });

    setTabs(prevTabs => [...prevTabs, newTab]);
    setActiveTabId(newTab.id);
    return newTab.id;
  }, [tabs]);

  // Open a file as a new tab (or switch to existing if already open)
  const openFileAsTab = useCallback((sql, fileName, filePath) => {
    // Check if this file is already open
    const existingTab = tabs.find(t => t.filePath === filePath && !t.isSystem);

    if (existingTab) {
      // Switch to existing tab
      setActiveTabId(existingTab.id);
      return existingTab.id;
    }

    // Parse name from SQL or use file name
    const tabName = parseTabNameFromSql(sql) || fileName.replace(/\.sql$/i, '');

    // Create new tab for this file
    const newTab = createTab({
      name: tabName,
      sql,
      fileName,
      filePath,
      isDirty: false,
    });

    setTabs(prevTabs => [...prevTabs, newTab]);
    setActiveTabId(newTab.id);
    return newTab.id;
  }, [tabs]);

  // Mark current tab as dirty (has unsaved changes)
  const markDirty = useCallback((isDirty = true) => {
    setTabs(prevTabs =>
      prevTabs.map(tab =>
        tab.id === activeTabId ? { ...tab, isDirty } : tab
      )
    );
  }, [activeTabId]);

  // Get all query tabs (non-system)
  const queryTabs = tabs.filter(t => !t.isSystem);

  // Get all system tabs
  const systemTabs = tabs.filter(t => t.isSystem);

  return {
    // State
    tabs,
    activeTab,
    activeTabId,
    queryTabs,
    systemTabs,
    lastQueryTab,

    // Actions
    updateActiveTab,
    switchTab,
    addTab,
    closeTab,
    renameTab,
    duplicateTab,
    openCostAnalysisTab,
    openFileAsTab,
    markDirty,
  };
}

export default useTabs;
