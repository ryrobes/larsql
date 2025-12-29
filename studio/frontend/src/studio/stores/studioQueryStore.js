import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

const API_BASE_URL = 'http://localhost:5050/api/studio';

const useStudioQueryStore = create(
  persist(
    immer((set, get) => ({
      // ============================================
      // CONNECTIONS & SCHEMA STATE
      // ============================================
      connections: [],           // List of available connections
      connectionsLoading: false,
      connectionsError: null,

      schemas: {},               // { connectionName: schemaData }
      schemasLoading: {},        // { connectionName: boolean }
      schemasError: {},          // { connectionName: error }

      expandedNodes: [],         // Array of expanded node IDs

      // ============================================
      // TAB STATE
      // ============================================
      tabs: [
        {
          id: 'tab_1',
          title: 'Query 1',
          connection: null,       // Selected connection
          sql: '',
          cursorPosition: { line: 1, column: 1 },
          results: null,
          error: null,
          isRunning: false,
          isDirty: false,
          executionTime: null,
          rowCount: null
        }
      ],
      activeTabId: 'tab_1',
      tabCounter: 1,

      // ============================================
      // HISTORY STATE
      // ============================================
      history: [],
      historyTotal: 0,
      historyLoading: false,
      historyError: null,

      // ============================================
      // UI STATE (persisted)
      // ============================================
      schemaPanelWidth: 250,
      resultsPanelHeight: 300,
      historyPanelOpen: false,

      // ============================================
      // CONNECTION ACTIONS
      // ============================================
      fetchConnections: async () => {
        set(state => {
          state.connectionsLoading = true;
          state.connectionsError = null;
        });

        try {
          const res = await fetch(`${API_BASE_URL}/connections`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.connections = data.connections;
            state.connectionsLoading = false;
          });
        } catch (err) {
          set(state => {
            state.connectionsError = err.message;
            state.connectionsLoading = false;
          });
        }
      },

      fetchSchema: async (connectionName) => {
        set(state => {
          state.schemasLoading[connectionName] = true;
          state.schemasError[connectionName] = null;
        });

        try {
          const res = await fetch(`${API_BASE_URL}/schema/${connectionName}`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.schemas[connectionName] = data;
            state.schemasLoading[connectionName] = false;
          });
        } catch (err) {
          set(state => {
            state.schemasError[connectionName] = err.message;
            state.schemasLoading[connectionName] = false;
          });
        }
      },

      toggleNodeExpanded: (nodeId) => {
        set(state => {
          const idx = state.expandedNodes.indexOf(nodeId);
          if (idx === -1) {
            state.expandedNodes.push(nodeId);
          } else {
            state.expandedNodes.splice(idx, 1);
          }
        });
      },

      isNodeExpanded: (nodeId) => {
        return get().expandedNodes.includes(nodeId);
      },

      // ============================================
      // TAB ACTIONS
      // ============================================
      createTab: (initialState = {}) => {
        set(state => {
          const newCounter = state.tabCounter + 1;
          const newTab = {
            id: `tab_${newCounter}`,
            title: `Query ${newCounter}`,
            connection: initialState.connection || (state.connections[0]?.name || null),
            sql: initialState.sql || '',
            cursorPosition: { line: 1, column: 1 },
            results: null,
            error: null,
            isRunning: false,
            isDirty: false,
            executionTime: null,
            rowCount: null
          };
          state.tabs.push(newTab);
          state.activeTabId = newTab.id;
          state.tabCounter = newCounter;
        });
      },

      closeTab: (tabId) => {
        set(state => {
          const idx = state.tabs.findIndex(t => t.id === tabId);
          if (idx === -1 || state.tabs.length <= 1) return; // Don't close last tab

          state.tabs.splice(idx, 1);

          // If closing active tab, switch to previous or next
          if (state.activeTabId === tabId) {
            const newIdx = Math.min(idx, state.tabs.length - 1);
            state.activeTabId = state.tabs[newIdx].id;
          }
        });
      },

      setActiveTab: (tabId) => {
        set(state => {
          state.activeTabId = tabId;
        });
      },

      updateTab: (tabId, updates) => {
        set(state => {
          const tab = state.tabs.find(t => t.id === tabId);
          if (tab) {
            Object.assign(tab, updates);
            // Mark dirty if SQL changed
            if ('sql' in updates && updates.sql !== '') {
              tab.isDirty = true;
            }
          }
        });
      },

      getActiveTab: () => {
        const state = get();
        return state.tabs.find(t => t.id === state.activeTabId);
      },

      // ============================================
      // QUERY EXECUTION
      // ============================================
      executeQuery: async (tabId) => {
        const state = get();
        const tab = state.tabs.find(t => t.id === tabId);
        if (!tab || !tab.connection || !tab.sql.trim()) return;

        set(state => {
          const t = state.tabs.find(t => t.id === tabId);
          if (t) {
            t.isRunning = true;
            t.error = null;
            t.results = null;
          }
        });

        const startTime = performance.now();

        try {
          const res = await fetch(`${API_BASE_URL}/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              connection: tab.connection,
              sql: tab.sql,
              limit: 1000
            })
          });

          const data = await res.json();
          const executionTime = Math.round(performance.now() - startTime);

          if (data.error) {
            set(state => {
              const t = state.tabs.find(t => t.id === tabId);
              if (t) {
                t.isRunning = false;
                t.error = data.error;
                t.executionTime = executionTime;
              }
            });

            // Save error to history
            await get().saveToHistory({
              connection: tab.connection,
              sql: tab.sql,
              row_count: null,
              duration_ms: executionTime,
              error: data.error
            });
          } else {
            set(state => {
              const t = state.tabs.find(t => t.id === tabId);
              if (t) {
                t.isRunning = false;
                t.results = {
                  columns: data.columns,
                  rows: data.rows || data.results
                };
                t.rowCount = data.row_count;
                t.executionTime = executionTime;
                t.isDirty = false;
              }
            });

            // Save success to history
            await get().saveToHistory({
              connection: tab.connection,
              sql: tab.sql,
              row_count: data.row_count,
              duration_ms: executionTime,
              error: null
            });
          }
        } catch (err) {
          const executionTime = Math.round(performance.now() - startTime);
          set(state => {
            const t = state.tabs.find(t => t.id === tabId);
            if (t) {
              t.isRunning = false;
              t.error = err.message;
              t.executionTime = executionTime;
            }
          });
        }
      },

      // ============================================
      // HISTORY ACTIONS
      // ============================================
      fetchHistory: async (params = {}) => {
        set(state => {
          state.historyLoading = true;
          state.historyError = null;
        });

        try {
          const queryParams = new URLSearchParams();
          if (params.limit) queryParams.set('limit', params.limit);
          if (params.offset) queryParams.set('offset', params.offset);
          if (params.connection) queryParams.set('connection', params.connection);
          if (params.search) queryParams.set('search', params.search);

          const res = await fetch(`${API_BASE_URL}/history?${queryParams}`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.history = data.history;
            state.historyTotal = data.total;
            state.historyLoading = false;
          });
        } catch (err) {
          set(state => {
            state.historyError = err.message;
            state.historyLoading = false;
          });
        }
      },

      saveToHistory: async (entry) => {
        try {
          await fetch(`${API_BASE_URL}/history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(entry)
          });

          // Refresh history if panel is open
          if (get().historyPanelOpen) {
            get().fetchHistory({ limit: 50 });
          }
        } catch (err) {
          console.error('Failed to save history:', err);
        }
      },

      deleteHistoryEntry: async (id) => {
        try {
          await fetch(`${API_BASE_URL}/history/${id}`, {
            method: 'DELETE'
          });

          set(state => {
            state.history = state.history.filter(h => h.id !== id);
            state.historyTotal -= 1;
          });
        } catch (err) {
          console.error('Failed to delete history:', err);
        }
      },

      loadFromHistory: (entry) => {
        set(state => {
          const tab = state.tabs.find(t => t.id === state.activeTabId);
          if (tab) {
            tab.sql = entry.sql;
            tab.connection = entry.connection;
            tab.isDirty = true;
            tab.results = null;
            tab.error = null;
          }
        });
      },

      // ============================================
      // UI ACTIONS
      // ============================================
      setSchemaPanelWidth: (width) => {
        set(state => {
          state.schemaPanelWidth = width;
        });
      },

      setResultsPanelHeight: (height) => {
        set(state => {
          state.resultsPanelHeight = height;
        });
      },

      toggleHistoryPanel: () => {
        set(state => {
          state.historyPanelOpen = !state.historyPanelOpen;
          if (state.historyPanelOpen) {
            // Fetch history when opening
            get().fetchHistory({ limit: 50 });
          }
        });
      }
    })),
    {
      name: 'studio-query-storage',
      partialize: (state) => ({
        // Only persist UI preferences
        schemaPanelWidth: state.schemaPanelWidth,
        resultsPanelHeight: state.resultsPanelHeight,
        expandedNodes: state.expandedNodes
      }),
      onRehydrateStorage: () => (state) => {
        // Migration: Copy old data if new key is empty
        const oldData = localStorage.getItem('sql-query-storage');
        const newData = localStorage.getItem('studio-query-storage');

        if (oldData && !newData) {
          console.log('[Migration] Copying sql-query-storage → studio-query-storage');
          localStorage.setItem('studio-query-storage', oldData);
        }
      }
    }
  )
);

export default useStudioQueryStore;
