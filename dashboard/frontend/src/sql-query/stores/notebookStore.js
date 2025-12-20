import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

const API_BASE_URL = 'http://localhost:5001/api';

/**
 * Notebook Store - State management for Data Cascade notebooks
 *
 * A notebook is a cascade with only deterministic phases (sql_data, python_data)
 * that can be edited, run, and saved as reusable tools.
 */
const useNotebookStore = create(
  persist(
    immer((set, get) => ({
      // ============================================
      // MODE STATE
      // ============================================
      mode: 'query',  // 'query' | 'notebook'

      // ============================================
      // NOTEBOOK STATE
      // ============================================
      notebook: null,  // Current notebook object
      notebookPath: null,  // Path to loaded notebook
      notebookDirty: false,  // Unsaved changes

      // Notebook structure:
      // {
      //   cascade_id: string,
      //   description: string,
      //   inputs_schema: { param_name: description },
      //   phases: [
      //     { name, tool, inputs: { query/code, connection? }, handoffs? }
      //   ]
      // }

      // ============================================
      // INPUT VALUES
      // ============================================
      notebookInputs: {},  // User-provided input values

      // ============================================
      // CELL EXECUTION STATE
      // ============================================
      cellStates: {},  // { [phaseName]: { status, result, error, duration } }
      // status: 'pending' | 'running' | 'success' | 'error' | 'stale'

      isRunningAll: false,  // Full notebook execution in progress

      // Session ID for temp table persistence across cell executions
      // Generated when notebook loads, persists until restart/reload
      sessionId: null,

      // ============================================
      // NOTEBOOK LIST
      // ============================================
      notebooks: [],  // List of available notebooks
      notebooksLoading: false,
      notebooksError: null,

      // ============================================
      // MODE ACTIONS
      // ============================================
      setMode: (mode) => {
        set(state => {
          state.mode = mode;
        });
      },

      // ============================================
      // SESSION MANAGEMENT
      // ============================================
      generateSessionId: () => {
        const id = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
        set(state => {
          state.sessionId = id;
        });
        return id;
      },

      restartSession: async () => {
        const state = get();
        const oldSessionId = state.sessionId;

        // Clean up old session on backend
        if (oldSessionId) {
          try {
            await fetch(`${API_BASE_URL}/notebook/cleanup-session`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: oldSessionId })
            });
          } catch (err) {
            console.warn('Failed to cleanup old session:', err);
          }
        }

        // Generate new session and clear states
        set(s => {
          s.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          s.cellStates = {};
          // Reset all cells to pending
          if (s.notebook?.phases) {
            s.notebook.phases.forEach(phase => {
              s.cellStates[phase.name] = { status: 'pending' };
            });
          }
        });
      },

      // ============================================
      // NOTEBOOK CRUD
      // ============================================
      newNotebook: () => {
        set(state => {
          state.notebook = {
            cascade_id: 'new_notebook',
            description: 'New data notebook',
            inputs_schema: {},
            phases: []
          };
          state.notebookPath = null;
          state.notebookDirty = false;
          state.notebookInputs = {};
          state.cellStates = {};
          // Generate fresh session for new notebook
          state.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
        });
      },

      loadNotebook: async (path) => {
        try {
          const res = await fetch(`${API_BASE_URL}/notebook/load?path=${encodeURIComponent(path)}`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.notebook = data.notebook;
            state.notebookPath = path;
            state.notebookDirty = false;
            state.notebookInputs = {};
            state.cellStates = {};
            // Generate fresh session for loaded notebook
            state.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          });

          return data.notebook;
        } catch (err) {
          console.error('Failed to load notebook:', err);
          throw err;
        }
      },

      saveNotebook: async (path = null) => {
        const state = get();
        const savePath = path || state.notebookPath;

        if (!savePath) {
          throw new Error('No path specified for saving');
        }

        try {
          const res = await fetch(`${API_BASE_URL}/notebook/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              path: savePath,
              notebook: state.notebook
            })
          });

          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.notebookPath = savePath;
            state.notebookDirty = false;
          });

          return data;
        } catch (err) {
          console.error('Failed to save notebook:', err);
          throw err;
        }
      },

      updateNotebook: (updates) => {
        set(state => {
          if (state.notebook) {
            Object.assign(state.notebook, updates);
            state.notebookDirty = true;
          }
        });
      },

      // ============================================
      // CELL CRUD
      // ============================================
      addCell: (type = 'sql_data', afterIndex = null) => {
        set(state => {
          if (!state.notebook) return;

          const phases = state.notebook.phases;
          const cellCount = phases.length + 1;

          const newCell = {
            name: `cell_${cellCount}`,
            tool: type,
            inputs: type === 'sql_data'
              ? { query: '-- Enter SQL here\n-- Reference prior cells with: SELECT * FROM _cell_name\nSELECT 1' }
              : { code: '# Access prior cell outputs as DataFrames:\n# df = data.cell_name\n#\n# Set result to a DataFrame or dict:\nresult = {"message": "Hello"}' }
          };

          // Add handoff to previous cell if exists
          if (afterIndex === null) {
            // Add at end
            if (phases.length > 0) {
              phases[phases.length - 1].handoffs = [newCell.name];
            }
            phases.push(newCell);
          } else {
            // Insert after specific index
            if (afterIndex >= 0 && phases[afterIndex]) {
              phases[afterIndex].handoffs = [newCell.name];
            }
            // Update new cell to point to next cell if exists
            if (afterIndex + 1 < phases.length) {
              newCell.handoffs = [phases[afterIndex + 1].name];
            }
            phases.splice(afterIndex + 1, 0, newCell);
          }

          state.notebookDirty = true;
          state.cellStates[newCell.name] = { status: 'pending' };
        });
      },

      updateCell: (index, updates) => {
        set(state => {
          if (!state.notebook || !state.notebook.phases[index]) return;

          const cell = state.notebook.phases[index];
          const oldName = cell.name;

          // Handle name change - update references
          if (updates.name && updates.name !== oldName) {
            // Update handoffs in other phases that reference this cell
            state.notebook.phases.forEach(phase => {
              if (phase.handoffs) {
                phase.handoffs = phase.handoffs.map(h =>
                  h === oldName ? updates.name : h
                );
              }
            });

            // Update cellStates key
            if (state.cellStates[oldName]) {
              state.cellStates[updates.name] = state.cellStates[oldName];
              delete state.cellStates[oldName];
            }
          }

          Object.assign(cell, updates);
          state.notebookDirty = true;

          // Mark downstream cells as stale
          if (updates.inputs) {
            get().markDownstreamStale(index);
          }
        });
      },

      removeCell: (index) => {
        set(state => {
          if (!state.notebook || state.notebook.phases.length <= 1) return;

          const phases = state.notebook.phases;
          const removedName = phases[index].name;

          // Update previous cell's handoffs to skip the removed cell
          if (index > 0 && phases[index - 1].handoffs) {
            const nextPhase = phases[index + 1];
            phases[index - 1].handoffs = nextPhase
              ? [nextPhase.name]
              : [];
          }

          // Remove cell state
          delete state.cellStates[removedName];

          // Remove the cell
          phases.splice(index, 1);
          state.notebookDirty = true;
        });
      },

      moveCell: (fromIndex, toIndex) => {
        set(state => {
          if (!state.notebook) return;

          const phases = state.notebook.phases;
          if (fromIndex < 0 || fromIndex >= phases.length) return;
          if (toIndex < 0 || toIndex >= phases.length) return;

          const [removed] = phases.splice(fromIndex, 1);
          phases.splice(toIndex, 0, removed);

          // Rebuild handoffs
          phases.forEach((phase, idx) => {
            if (idx < phases.length - 1) {
              phase.handoffs = [phases[idx + 1].name];
            } else {
              delete phase.handoffs;
            }
          });

          state.notebookDirty = true;
        });
      },

      // ============================================
      // INPUT ACTIONS
      // ============================================
      setNotebookInput: (key, value) => {
        set(state => {
          state.notebookInputs[key] = value;
        });
      },

      clearNotebookInputs: () => {
        set(state => {
          state.notebookInputs = {};
        });
      },

      // ============================================
      // CELL STATE ACTIONS
      // ============================================
      setCellState: (phaseName, cellState) => {
        set(state => {
          state.cellStates[phaseName] = {
            ...state.cellStates[phaseName],
            ...cellState
          };
        });
      },

      markDownstreamStale: (fromIndex) => {
        set(state => {
          if (!state.notebook) return;

          // Mark all cells after fromIndex as stale
          for (let i = fromIndex + 1; i < state.notebook.phases.length; i++) {
            const phaseName = state.notebook.phases[i].name;
            if (state.cellStates[phaseName]?.status === 'success') {
              state.cellStates[phaseName].status = 'stale';
            }
          }
        });
      },

      clearCellStates: () => {
        set(state => {
          state.cellStates = {};
        });
      },

      // ============================================
      // EXECUTION ACTIONS
      // ============================================
      runCell: async (phaseName) => {
        const state = get();
        if (!state.notebook) return;

        const phaseIndex = state.notebook.phases.findIndex(p => p.name === phaseName);
        if (phaseIndex === -1) return;

        const phase = state.notebook.phases[phaseIndex];

        // Ensure we have a session ID
        let sessionId = state.sessionId;
        if (!sessionId) {
          sessionId = get().generateSessionId();
        }

        set(s => {
          s.cellStates[phaseName] = { status: 'running', result: null, error: null };
        });

        const startTime = performance.now();

        try {
          // Collect outputs from prior phases for python_data
          const priorOutputs = {};
          for (let i = 0; i < phaseIndex; i++) {
            const priorPhase = state.notebook.phases[i];
            const priorState = state.cellStates[priorPhase.name];
            if (priorState?.result) {
              priorOutputs[priorPhase.name] = priorState.result;
            }
          }

          const res = await fetch(`${API_BASE_URL}/notebook/run-cell`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cell: phase,
              inputs: state.notebookInputs,
              prior_outputs: priorOutputs,
              session_id: sessionId
            })
          });

          const data = await res.json();
          const duration = Math.round(performance.now() - startTime);

          if (data.error || data._route === 'error') {
            set(s => {
              s.cellStates[phaseName] = {
                status: 'error',
                error: data.error,
                duration
              };
            });
          } else {
            set(s => {
              s.cellStates[phaseName] = {
                status: 'success',
                result: data,
                duration
              };
            });

            // Mark downstream cells as stale
            get().markDownstreamStale(phaseIndex);
          }
        } catch (err) {
          const duration = Math.round(performance.now() - startTime);
          set(s => {
            s.cellStates[phaseName] = {
              status: 'error',
              error: err.message,
              duration
            };
          });
        }
      },

      runAllCells: async () => {
        const state = get();
        if (!state.notebook || state.isRunningAll) return;

        // Ensure we have a session ID (generate fresh for run all)
        set(s => {
          s.isRunningAll = true;
          s.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          // Reset all cell states to pending
          s.notebook.phases.forEach(phase => {
            s.cellStates[phase.name] = { status: 'pending' };
          });
        });

        try {
          // Run cells sequentially using runCell to maintain session
          for (const phase of get().notebook.phases) {
            await get().runCell(phase.name);

            // Stop if cell failed
            if (get().cellStates[phase.name]?.status === 'error') {
              break;
            }
          }
        } finally {
          set(s => {
            s.isRunningAll = false;
          });
        }
      },

      runFromCell: async (phaseName) => {
        const state = get();
        if (!state.notebook) return;

        const startIndex = state.notebook.phases.findIndex(p => p.name === phaseName);
        if (startIndex === -1) return;

        // Ensure session ID exists
        if (!state.sessionId) {
          get().generateSessionId();
        }

        // Run cells sequentially from startIndex
        for (let i = startIndex; i < state.notebook.phases.length; i++) {
          const phase = state.notebook.phases[i];
          await get().runCell(phase.name);

          // Stop if cell failed
          if (get().cellStates[phase.name]?.status === 'error') {
            break;
          }
        }
      },

      // ============================================
      // NOTEBOOK LIST ACTIONS
      // ============================================
      fetchNotebooks: async () => {
        set(state => {
          state.notebooksLoading = true;
          state.notebooksError = null;
        });

        try {
          const res = await fetch(`${API_BASE_URL}/notebook/list`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.notebooks = data.notebooks || [];
            state.notebooksLoading = false;
          });
        } catch (err) {
          set(state => {
            state.notebooksError = err.message;
            state.notebooksLoading = false;
          });
        }
      }
    })),
    {
      name: 'notebook-storage',
      partialize: (state) => ({
        // Only persist mode preference
        mode: state.mode
      })
    }
  )
);

export default useNotebookStore;
