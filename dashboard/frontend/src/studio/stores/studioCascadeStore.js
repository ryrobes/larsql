import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';
import { autoGenerateSessionId } from '../../utils/sessionNaming';
import { deriveCellState } from '../utils/deriveCellState';

const API_BASE_URL = 'http://localhost:5001/api/studio';

/**
 * Simple hash function for cell caching.
 * Creates a fingerprint of the cell's inputs to detect changes.
 */
function hashCellInputs(cell, cascadeInputs, priorOutputHashes) {
  // Combine relevant inputs into a string
  const inputStr = JSON.stringify({
    tool: cell.tool,
    inputs: cell.inputs,
    cascadeInputs,
    // Include hashes of prior outputs to invalidate if upstream changed
    priorOutputHashes
  });

  // Simple hash function (djb2)
  let hash = 5381;
  for (let i = 0; i < inputStr.length; i++) {
    hash = ((hash << 5) + hash) + inputStr.charCodeAt(i);
    hash = hash & hash; // Convert to 32-bit integer
  }
  return hash.toString(16);
}

/**
 * Studio Cascade Store - State management for cascade builder
 *
 * Manages cascade editing, execution, and state for the Studio view.
 * Supports both LLM-powered and deterministic cells (sql_data, python_data,
 * js_data, clojure_data, windlass_data) that can be edited, run, and saved.
 *
 * Polyglot support: Data flows between languages via JSON serialization.
 * - SQL: rows as array of objects, accessed via _cell_name tables
 * - Python: data.cell_name returns DataFrame
 * - JavaScript: data.cell_name returns array of objects
 * - Clojure: (:cell-name data) returns vector of maps
 */
const useStudioCascadeStore = create(
  persist(
    immer((set, get) => ({
      // ============================================
      // MODE STATE
      // ============================================
      mode: 'timeline',  // 'query' | 'timeline' | 'notebook'

      // ============================================
      // CASCADE STATE
      // ============================================
      cascade: null,  // Current cascade object
      cascadeYamlText: null,  // Raw YAML text (preserves comments/formatting)
      cascadePath: null,  // Path to loaded cascade
      cascadeDirty: false,  // Unsaved changes

      // Cascade structure:
      // {
      //   cascade_id: string,
      //   description: string,
      //   inputs_schema: { param_name: description },
      //   cells: [
      //     { name, tool, inputs: { query/code, connection? }, handoffs? }
      //   ]
      // }

      // ============================================
      // INPUT VALUES
      // ============================================
      cascadeInputs: {},  // User-provided input values

      // ============================================
      // CELL EXECUTION STATE
      // ============================================
      cellStates: {},  // { [cellName]: { status, result, error, duration } }
      // status: 'pending' | 'running' | 'success' | 'error' | 'stale'

      isRunningAll: false,  // Full cascade execution in progress
      cascadeSessionId: null,  // Session ID when running full cascade (for SSE tracking)

      // Session ID for temp table persistence across cell executions
      // Generated when cascade loads, persists until restart/reload
      sessionId: null,

      // ============================================
      // SUB-CASCADE TRACKING
      // ============================================
      childSessions: {},  // { [child_session_id]: { session_id, parent_cell, first_seen } }
      parentSessionId: null,  // If this is a child session, ID of parent
      parentCell: null,  // If this is a child session, cell in parent that spawned it

      // ============================================
      // UI STATE
      // ============================================
      selectedCellIndex: null,  // Currently selected cell in timeline view
      desiredOutputTab: null,  // Desired output tab when selecting cell (e.g., 'images' from Media section)
      viewMode: 'live',  // 'live' | 'replay' - viewing live execution vs past run
      replaySessionId: null,  // Session ID when in replay mode

      // YAML View Mode (for cascade-level YAML editing)
      yamlViewMode: false,  // false = normal navigator view, true = YAML editor view

      // ============================================
      // AUTO-FIX CONFIGURATION
      // ============================================
      // Global auto-fix settings (can be overridden per-cell)
      autoFixConfig: {
        enabled: true,  // Enable auto-fix by default
        max_attempts: 2,
        model: 'x-ai/grok-4.1-fast',
        prompt: null,  // Use default prompt
      },
      // Per-cell auto-fix overrides: { [cellName]: { enabled, model, prompt } }
      cellAutoFixOverrides: {},

      // ============================================
      // UNDO/REDO HISTORY
      // ============================================
      undoStack: [],  // Stack of previous cascade states (cells snapshots)
      redoStack: [],  // Stack of undone states
      maxHistorySize: 50,  // Maximum history entries

      // ============================================
      // CASCADE LIST
      // ============================================
      cascades: [],  // List of available cascades
      cascadesLoading: false,
      cascadesError: null,

      // ============================================
      // DEFAULT MODEL
      // ============================================
      defaultModel: null,  // Default model from backend config

      // ============================================
      // CELL TYPES (Declarative)
      // ============================================
      cellTypes: [],  // Loaded from phase_types/ YAML files
      cellTypesLoading: false,

      // ============================================
      // UNDO/REDO HELPERS
      // ============================================
      _saveToUndoStack: () => {
        const state = get();
        if (!state.cascade?.cells) return;

        // Create a deep copy of cells for the undo stack
        const cellsSnapshot = JSON.parse(JSON.stringify(state.cascade.cells));

        set(s => {
          // Push current state to undo stack
          s.undoStack.push(cellsSnapshot);

          // Trim if exceeds max size
          if (s.undoStack.length > s.maxHistorySize) {
            s.undoStack.shift();
          }

          // Clear redo stack on new action
          s.redoStack = [];
        });
      },

      undo: () => {
        const state = get();
        if (!state.cascade || state.undoStack.length === 0) return false;

        set(s => {
          // Save current state to redo stack
          const currentSnapshot = JSON.parse(JSON.stringify(s.cascade.cells));
          s.redoStack.push(currentSnapshot);

          // Pop previous state from undo stack
          const previousState = s.undoStack.pop();
          s.cascade.cells = previousState;
          s.cascadeDirty = true;
        });

        return true;
      },

      redo: () => {
        const state = get();
        if (!state.cascade || state.redoStack.length === 0) return false;

        set(s => {
          // Save current state to undo stack
          const currentSnapshot = JSON.parse(JSON.stringify(s.cascade.cells));
          s.undoStack.push(currentSnapshot);

          // Pop next state from redo stack
          const nextState = s.redoStack.pop();
          s.cascade.cells = nextState;
          s.cascadeDirty = true;
        });

        return true;
      },

      canUndo: () => get().undoStack.length > 0,
      canRedo: () => get().redoStack.length > 0,

      clearHistory: () => {
        set(s => {
          s.undoStack = [];
          s.redoStack = [];
        });
      },

      // ============================================
      // MODE ACTIONS
      // ============================================
      setMode: (mode) => {
        set(state => {
          state.mode = mode;
        });
      },

      setSelectedCellIndex: (index) => {
        set(state => {
          state.selectedCellIndex = index;
        });
      },

      setDesiredOutputTab: (tab) => {
        set(state => {
          state.desiredOutputTab = tab;
        });
      },

      setReplayMode: async (sessionId) => {
        // Load historical cascade structure for this session
        try {
          const res = await fetch(`${API_BASE_URL}/session-cascade/${sessionId}`);
          const data = await res.json();

          if (data.error) {
            console.error('[setReplayMode] Failed to load session cascade:', data.error);
            // Continue anyway, use current cascade
          } else if (data.cascade) {
            console.log('[setReplayMode] Loaded historical cascade:', data.cascade);
            if (data.input_data) {
              console.log('[setReplayMode] Loaded historical inputs:', data.input_data);
            }
            if (data.warning) {
              console.warn('[setReplayMode]', data.warning);
            }
            if (data.source === 'cascade_sessions_table') {
              console.log('[setReplayMode] ✓ Full definition from cascade_sessions table');
            } else {
              console.log('[setReplayMode] ⚠ Reconstructed from logs (partial data)');
            }

            console.log('[setReplayMode] Setting cascade in state:');
            console.log('[setReplayMode]   - Cells:', data.cascade.cells?.length);
            if (data.cascade.cells && data.cascade.cells[0]) {
              console.log('[setReplayMode]   - First cell tool:', data.cascade.cells[0].tool);
              console.log('[setReplayMode]   - First cell inputs:', Object.keys(data.cascade.cells[0].inputs || {}));
            }

            set(state => {
              state.viewMode = 'replay';
              state.replaySessionId = sessionId;
              state.cascade = data.cascade;

              // Only update cascadePath if we don't already have one
              // (prevents overwriting original path with temp file path)
              if (!state.cascadePath) {
                const configPath = data.config_path || null;
                // Filter out temp files (session_*.yaml or .tmp_*.yaml in any directory)
                if (configPath &&
                    !configPath.includes('/session_') && !configPath.includes('\\session_') &&
                    !configPath.includes('/.tmp_') && !configPath.includes('\\.tmp_')) {
                  state.cascadePath = configPath;
                }
              }

              state.cascadeDirty = false;
              // Load historical inputs if available
              if (data.input_data && Object.keys(data.input_data).length > 0) {
                state.cascadeInputs = data.input_data;
                console.log('[setReplayMode] Loaded historical inputs into cascadeInputs:', data.input_data);
              }
              // Clear any running execution
              state.isRunningAll = false;
              // Clear cell states - they'll be populated from polling
              state.cellStates = {};
            });

            // Verify it was set correctly
            const newState = get();
            console.log('[setReplayMode] State after set:');
            console.log('[setReplayMode]   - cascade.cells:', newState.cascade?.cells?.length);
            if (newState.cascade?.cells?.[0]) {
              console.log('[setReplayMode]   - First cell tool:', newState.cascade.cells[0].tool);
            }
            return;
          }
        } catch (err) {
          console.error('[setReplayMode] Error loading session cascade:', err);
        }

        // Fallback if loading failed
        set(state => {
          state.viewMode = 'replay';
          state.replaySessionId = sessionId;
          state.isRunningAll = false;
        });
      },

      // Fetch session data immediately (for URL loading)
      fetchReplayData: async (sessionId) => {
        console.log('[fetchReplayData] Fetching session data:', sessionId);

        try {
          // Use same endpoint as polling
          const url = `http://localhost:5001/api/playground/session-stream/${sessionId}?after=1970-01-01 00:00:00`;
          const response = await fetch(url);

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }

          const data = await response.json();

          if (data.error) {
            throw new Error(data.error);
          }

          console.log('[fetchReplayData] Got', data.rows?.length || 0, 'rows');
          console.log('[fetchReplayData] Child sessions:', data.child_sessions?.length || 0);

          // Derive cell states using shared logic (only for parent session)
          const logs = data.rows || [];
          const parentLogs = logs.filter(r => r.session_id === sessionId);
          const cellNames = [...new Set(parentLogs.map(r => r.cell_name).filter(Boolean))];
          const cellStates = {};

          for (const cellName of cellNames) {
            cellStates[cellName] = deriveCellState(parentLogs, cellName);
          }

          // Update cellStates immediately
          get().updateCellStatesFromPolling(cellStates);

          // Update child sessions
          if (data.child_sessions && data.child_sessions.length > 0) {
            set(state => {
              state.childSessions = {};
              data.child_sessions.forEach(child => {
                state.childSessions[child.session_id] = child;
              });
            });
            console.log('[fetchReplayData] ✓ Child sessions updated:', Object.keys(get().childSessions));
          }

          // Check if this session has a parent (look for parent_session_id in any row)
          const parentRow = logs.find(r => r.parent_session_id && r.session_id === sessionId);
          if (parentRow && parentRow.parent_session_id) {
            set(state => {
              state.parentSessionId = parentRow.parent_session_id;
              // We don't know parent_phase from child's perspective - would need separate query
            });
            console.log('[fetchReplayData] ✓ This is a child session, parent:', parentRow.parent_session_id);
          }

          console.log('[fetchReplayData] ✓ Cell states updated:', Object.keys(cellStates));

          return { success: true, cellCount: cellNames.length };

        } catch (err) {
          console.error('[fetchReplayData] Error:', err);
          return { success: false, error: err.message };
        }
      },

      setLiveMode: () => {
        set(state => {
          state.viewMode = 'live';
          state.replaySessionId = null;
        });
      },

      // Join a currently running session (switch to live view of an active cascade)
      joinLiveSession: async (sessionId, cascadeId, cascadeFile) => {
        console.log('[joinLiveSession] Joining session:', sessionId, 'cascade:', cascadeId);

        try {
          // First, try to load the cascade structure from the session
          const res = await fetch(`${API_BASE_URL}/session-cascade/${sessionId}`);
          const data = await res.json();

          if (data.error) {
            console.error('[joinLiveSession] Failed to load session cascade:', data.error);
            // Still proceed - we can view the session without the cascade definition
          }

          set(state => {
            // Set to live mode watching this session
            state.viewMode = 'live';
            state.cascadeSessionId = sessionId;
            state.replaySessionId = null;
            state.isRunningAll = true; // Enable polling

            // Load cascade if available
            if (data.cascade) {
              state.cascade = data.cascade;

              // Only update cascadePath if we don't already have one
              // (prevents overwriting original path with temp file path)
              if (!state.cascadePath) {
                const configPath = data.config_path || cascadeFile || null;
                // Filter out temp files (session_*.yaml or .tmp_*.yaml in any directory)
                if (configPath &&
                    !configPath.includes('/session_') && !configPath.includes('\\session_') &&
                    !configPath.includes('/.tmp_') && !configPath.includes('\\.tmp_')) {
                  state.cascadePath = configPath;
                }
              }

              state.cascadeDirty = false;

              // Load inputs if available
              if (data.input_data && Object.keys(data.input_data).length > 0) {
                state.cascadeInputs = data.input_data;
              }
            }

            // Clear cell states - they'll be populated from polling
            state.cellStates = {};
          });

          // Trigger immediate data fetch
          const state = get();
          if (state.fetchReplayData) {
            await state.fetchReplayData(sessionId);
          }

          console.log('[joinLiveSession] Successfully joined session:', sessionId);
          return { success: true };

        } catch (err) {
          console.error('[joinLiveSession] Error:', err);

          // Still set up the session even if cascade load failed
          set(state => {
            state.viewMode = 'live';
            state.cascadeSessionId = sessionId;
            state.replaySessionId = null;
            state.isRunningAll = true;
            state.cellStates = {};
          });

          return { success: false, error: err.message };
        }
      },

      // ============================================
      // SESSION MANAGEMENT
      // ============================================
      generateSessionId: () => {
        const id = autoGenerateSessionId();
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
            await fetch(`${API_BASE_URL}/cleanup-session`, {
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
          s.sessionId = autoGenerateSessionId();
          s.cellStates = {};
          // Reset all cells to pending
          if (s.cascade?.cells) {
            s.cascade.cells.forEach(cell => {
              s.cellStates[cell.name] = { status: 'pending' };
            });
          }
        });
      },

      // ============================================
      // CASCADE CRUD
      // ============================================
      newCascade: () => {
        // Generate a unique cascade ID for new cascades
        const uniqueId = `studio_new_${autoGenerateSessionId().split('-').pop()}`;
        console.log('[newCascade] Creating blank cascade with ID:', uniqueId);

        set(state => {
          state.cascade = {
            cascade_id: uniqueId,
            description: 'New cascade',
            inputs_schema: {},
            cells: []
          };
          state.cascadePath = null;
          state.cascadeDirty = false;
          state.cascadeInputs = {};
          state.cellStates = {};
          // Generate fresh session ID for individual cell executions
          state.sessionId = autoGenerateSessionId();
          // Clear cascade-level session (generated when Run All is clicked)
          state.cascadeSessionId = null;
          state.replaySessionId = null;
          state.viewMode = 'live';
          state.isRunningAll = false;
          // Clear undo/redo history
          state.undoStack = [];
          state.redoStack = [];
        });
      },

      loadCascade: async (path) => {
        try {
          const res = await fetch(`${API_BASE_URL}/load?path=${encodeURIComponent(path)}`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.cascade = data.cascade || data.notebook;
            state.cascadeYamlText = data.raw_yaml || null;  // NEW: Store raw YAML (preserves comments/formatting)
            state.cascadePath = path;
            state.cascadeDirty = false;
            state.cascadeInputs = {};
            state.cellStates = {};
            // Generate fresh session for loaded cascade
            state.sessionId = autoGenerateSessionId();
            // Clear undo/redo history
            state.undoStack = [];
            state.redoStack = [];
          });

          return data.notebook;
        } catch (err) {
          console.error('Failed to load cascade:', err);
          throw err;
        }
      },

      saveCascade: async (path = null) => {
        const state = get();
        const savePath = path || state.cascadePath;

        if (!savePath) {
          throw new Error('No path specified for saving');
        }

        if (!state.cascade) {
          throw new Error('No cascade to save');
        }

        try {
          const payload = {
            path: savePath,
            notebook: state.cascade  // Backend expects 'notebook' not 'cascade'
          };

          // If we have raw YAML text, include it (preserves comments/formatting)
          if (state.cascadeYamlText) {
            payload.raw_yaml = state.cascadeYamlText;
          }

          const res = await fetch(`${API_BASE_URL}/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });

          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.cascadePath = savePath;
            state.cascadeDirty = false;
          });

          return data;
        } catch (err) {
          console.error('Failed to save cascade:', err);
          throw err;
        }
      },

      updateCascade: (updates) => {
        set(state => {
          if (state.cascade) {
            Object.assign(state.cascade, updates);
            state.cascadeDirty = true;
          }
        });
      },

      // ============================================
      // CELL CRUD
      // ============================================
      addCell: (type = 'sql_data', afterIndex = null, templateCode = null, autoChain = true) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade) return;

          const cells = state.cascade.cells;
          const cellCount = cells.length + 1;

          // Default code templates by language
          const defaultTemplates = {
            sql_data: '-- Enter SQL here\n-- Reference prior cells with: SELECT * FROM _cell_name\nSELECT 1',
            python_data: '# Access prior cell outputs as DataFrames:\n# df = data.cell_name\n#\n# Set result to a DataFrame or dict:\nresult = {"message": "Hello"}',
            js_data: '// Access prior cell outputs:\n// const rows = data.cell_name;\n//\n// Set result to an array of objects or value:\nresult = [{ message: "Hello" }];',
            clojure_data: '; Access prior cell outputs:\n; (:cell-name data)\n;\n; Return a vector of maps or value:\n[{:message "Hello"}]',
            llm_phase: `You are a helpful assistant analyzing data.

Use Jinja2 templates to reference data:
- Inputs: {{ input.param_name }}
- Prior phases: {{ outputs.cell_name }}
- State: {{ state.var_name }}

Provide your analysis below:
`,
            windlass_data: `# LLM Phase Cell (Data Tool)
# Access prior cells with: {{outputs.cell_name}}
# Full RVBBIT power: soundings, reforge, wards, model selection

instructions: |
  Analyze the data and return structured results.

  Available data:
  - {{outputs.cell_name}}

model: google/gemini-2.5-flash

output_schema:
  type: array
  items:
    type: object
    properties:
      id: { type: string }
      result: { type: string }

# Optional: Add soundings for best-of-N attempts
# soundings:
#   factor: 3
#   evaluator_instructions: Pick the most accurate result
`,
            rabbitize_batch: `npx rabbitize \\
  --client-id "studio" \\
  --test-id "browser_task_${cellCount}" \\
  --exit-on-end true \\
  --process-video true \\
  --batch-url "https://example.com" \\
  --batch-commands='[]'`
          };
          const defaultCode = defaultTemplates[type] || defaultTemplates.python_data;

          // Get cell type definition (declarative from YAML)
          const cellTypeDef = state.cellTypes.find(pt => pt.type_id === type);

          if (!cellTypeDef) {
            console.error(`Cell type not found: ${type}`);
            return;
          }

          // Generate unique name using prefix from type definition
          const baseName = cellTypeDef.name_prefix || type.replace(/_data$/, '');
          let cellName = `${baseName}_${cellCount}`;
          let counter = cellCount;
          while (cells.some(p => p.name === cellName)) {
            counter++;
            cellName = `${baseName}_${counter}`;
          }

          // Clone template and set name
          const template = JSON.parse(JSON.stringify(cellTypeDef.template));
          const newCell = {
            name: cellName,
            ...template
          };

          // Apply template variable substitutions
          const applyTemplateVars = (obj) => {
            if (typeof obj === 'string') {
              return obj
                .replace(/\{\{PHASE_NAME\}\}/g, cellName)
                .replace(/\{\{CASCADE_ID\}\}/g, state.cascade?.cascade_id || 'untitled');
            }
            if (Array.isArray(obj)) {
              return obj.map(applyTemplateVars);
            }
            if (obj && typeof obj === 'object') {
              const result = {};
              for (const [key, value] of Object.entries(obj)) {
                result[key] = applyTemplateVars(value);
              }
              return result;
            }
            return obj;
          };

          // Apply substitutions to entire cell
          Object.keys(newCell).forEach(key => {
            newCell[key] = applyTemplateVars(newCell[key]);
          });

          // Add handoff to previous cell if exists
          if (afterIndex === null) {
            // Add at end
            if (autoChain && cells.length > 0) {
              cells[cells.length - 1].handoffs = [newCell.name];
            }
            cells.push(newCell);
          } else {
            // Insert after specific index
            if (autoChain) {
              // Auto-chain mode: create linear flow
              if (afterIndex >= 0 && cells[afterIndex]) {
                cells[afterIndex].handoffs = [newCell.name];
              }
              // Update new cell to point to next cell if exists
              if (afterIndex + 1 < cells.length) {
                newCell.handoffs = [cells[afterIndex + 1].name];
              }
            } else {
              // Manual mode: only set parent handoff, no forward chain
              if (afterIndex >= 0 && cells[afterIndex]) {
                const existing = cells[afterIndex].handoffs || [];
                cells[afterIndex].handoffs = existing.includes(newCell.name)
                  ? existing
                  : [...existing, newCell.name];
              }
            }
            cells.splice(afterIndex + 1, 0, newCell);
          }

          state.cascadeDirty = true;
          state.cellStates[newCell.name] = { status: 'pending' };
        });
      },

      updateCell: (index, updates) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade || !state.cascade.cells[index]) return;

          const cell = state.cascade.cells[index];
          const oldName = cell.name;

          // Handle name change - update references
          if (updates.name && updates.name !== oldName) {
            // Update handoffs in other cells that reference this cell
            state.cascade.cells.forEach(cell => {
              if (cell.handoffs) {
                cell.handoffs = cell.handoffs.map(h =>
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
          state.cascadeDirty = true;

          // Mark downstream cells as stale
          if (updates.inputs) {
            get().markDownstreamStale(index);
          }
        });
      },

      removeCell: (index) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade || state.cascade.cells.length <= 1) return;

          const cells = state.cascade.cells;
          const removedName = cells[index].name;

          // Update previous cell's handoffs to skip the removed cell
          if (index > 0 && cells[index - 1].handoffs) {
            const nextCell = cells[index + 1];
            cells[index - 1].handoffs = nextCell
              ? [nextCell.name]
              : [];
          }

          // Remove cell state
          delete state.cellStates[removedName];

          // Remove the cell
          cells.splice(index, 1);
          state.cascadeDirty = true;
        });
      },

      moveCell: (fromIndex, toIndex) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade) return;

          const cells = state.cascade.cells;
          if (fromIndex < 0 || fromIndex >= cells.length) return;
          if (toIndex < 0 || toIndex >= cells.length) return;

          const [removed] = cells.splice(fromIndex, 1);
          cells.splice(toIndex, 0, removed);

          // Rebuild handoffs
          cells.forEach((cell, idx) => {
            if (idx < cells.length - 1) {
              cell.handoffs = [cells[idx + 1].name];
            } else {
              delete cell.handoffs;
            }
          });

          state.cascadeDirty = true;
        });
      },

      // ============================================
      // INPUT ACTIONS
      // ============================================
      setCascadeInput: (key, value) => {
        set(state => {
          state.cascadeInputs[key] = value;
        });
      },

      clearCascadeInputs: () => {
        set(state => {
          state.cascadeInputs = {};
        });
      },

      // ============================================
      // CELL STATE ACTIONS
      // ============================================
      setCellState: (cellName, cellState) => {
        set(state => {
          state.cellStates[cellName] = {
            ...state.cellStates[cellName],
            ...cellState
          };
        });
      },

      markDownstreamStale: (fromIndex) => {
        set(state => {
          if (!state.cascade) return;

          // Mark all cells after fromIndex as stale
          for (let i = fromIndex + 1; i < state.cascade.cells.length; i++) {
            const cellName = state.cascade.cells[i].name;
            if (state.cellStates[cellName]?.status === 'success') {
              state.cellStates[cellName].status = 'stale';
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
      // AUTO-FIX ACTIONS
      // ============================================
      setGlobalAutoFix: (config) => {
        set(state => {
          state.autoFixConfig = { ...state.autoFixConfig, ...config };
        });
      },

      setCellAutoFix: (cellName, config) => {
        set(state => {
          state.cellAutoFixOverrides[cellName] = {
            ...(state.cellAutoFixOverrides[cellName] || {}),
            ...config
          };
        });
      },

      clearCellAutoFix: (cellName) => {
        set(state => {
          delete state.cellAutoFixOverrides[cellName];
        });
      },

      // Get effective auto-fix config for a cell (merges global + per-cell overrides)
      getEffectiveAutoFixConfig: (cellName) => {
        const state = get();
        const override = state.cellAutoFixOverrides[cellName];
        if (override) {
          return { ...state.autoFixConfig, ...override };
        }
        return state.autoFixConfig;
      },

      // ============================================
      // EXECUTION ACTIONS
      // ============================================
      runCell: async (cellName, forceRun = false) => {
        const state = get();
        if (!state.cascade) return;

        const cellIndex = state.cascade.cells.findIndex(c => c.name === cellName);
        if (cellIndex === -1) return;

        const cell = state.cascade.cells[cellIndex];

        // Ensure we have a session ID
        let sessionId = state.sessionId;
        if (!sessionId) {
          sessionId = get().generateSessionId();
        }

        // Collect prior output hashes for cache invalidation
        const priorOutputHashes = {};
        for (let i = 0; i < cellIndex; i++) {
          const priorCell = state.cascade.cells[i];
          const priorState = state.cellStates[priorCell.name];
          if (priorState?.inputHash) {
            priorOutputHashes[priorCell.name] = priorState.inputHash;
          }
        }

        // Compute hash of current inputs
        const currentHash = hashCellInputs(cell, state.cascadeInputs, priorOutputHashes);
        const existingState = state.cellStates[cellName];

        // Check cache: if hash matches and we have a successful result, skip execution
        if (!forceRun &&
            existingState?.status === 'success' &&
            existingState?.inputHash === currentHash &&
            existingState?.result) {
          // Cache hit - mark as cached and return
          set(s => {
            s.cellStates[cellName] = {
              ...existingState,
              cached: true
            };
          });
          console.log(`[Cache] Hit for ${cellName} (hash: ${currentHash})`);
          return;
        }

        set(s => {
          s.cellStates[cellName] = { status: 'running', result: null, error: null, cached: false };
        });

        const startTime = performance.now();

        try {
          // Collect outputs from prior cells
          const priorOutputs = {};
          for (let i = 0; i < cellIndex; i++) {
            const priorCell = state.cascade.cells[i];
            const priorState = state.cellStates[priorCell.name];
            if (priorState?.result) {
              priorOutputs[priorCell.name] = priorState.result;
            }
          }

          // Get effective auto-fix config for this cell
          const autoFixConfig = get().getEffectiveAutoFixConfig(cellName);

          const res = await fetch(`${API_BASE_URL}/run-cell`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cell: cell,
              inputs: state.cascadeInputs,
              prior_outputs: priorOutputs,
              session_id: sessionId,
              auto_fix: autoFixConfig
            })
          });

          const data = await res.json();
          const duration = Math.round(performance.now() - startTime);

          if (data.error || data._route === 'error') {
            set(s => {
              s.cellStates[cellName] = {
                status: 'error',
                error: data.error,
                autoFixError: data.auto_fix_error,
                duration,
                inputHash: currentHash,
                cached: false
              };
            });
          } else {
            set(s => {
              s.cellStates[cellName] = {
                status: 'success',
                result: data,
                duration,
                inputHash: currentHash,
                cached: false,
                // Track if this result came from auto-fix
                autoFixed: data._auto_fixed || false,
                fixAttempts: data._fix_attempts || null,
                fixedCode: data._fixed_code || null,
                originalError: data._original_error || null
              };
            });

            // Mark downstream cells as stale
            get().markDownstreamStale(cellIndex);
          }
        } catch (err) {
          const duration = Math.round(performance.now() - startTime);
          set(s => {
            s.cellStates[cellName] = {
              status: 'error',
              error: err.message,
              duration,
              inputHash: currentHash,
              cached: false
            };
          });
        }
      },

      // Run full cascade via standard execution (NEW - replaces sequential cell execution)
      runCascadeStandard: async () => {
        const state = get();
        if (!state.cascade || state.isRunningAll) return;

        console.log('[runCascadeStandard] Starting. Current state:', {
          viewMode: state.viewMode,
          replaySessionId: state.replaySessionId,
          cascadeSessionId: state.cascadeSessionId,
        });

        // Generate session ID
        const sessionId = autoGenerateSessionId();

        set(s => {
          s.isRunningAll = true;
          s.cascadeSessionId = sessionId;
          s.sessionId = sessionId; // Keep sessionId in sync
          s.viewMode = 'live'; // Force live mode when running new cascade
          s.replaySessionId = null; // Clear any replay session

          // CRITICAL: Clear child sessions to prevent stale data
          s.childSessions = {};

          // Reset all cell states to pending
          s.cascade.cells.forEach(cell => {
            s.cellStates[cell.name] = { status: 'pending' };
          });
        });

        const newState = get();
        console.log('[runCascadeStandard] State after set:', {
          viewMode: newState.viewMode,
          replaySessionId: newState.replaySessionId,
          cascadeSessionId: newState.cascadeSessionId,
          sessionId: newState.sessionId,
          isRunningAll: newState.isRunningAll,
        });

        try {
          // Export cascade to YAML (prefer raw text to preserve comments/formatting)
          const yaml = require('js-yaml');
          const cascadeYaml = state.cascadeYamlText || yaml.dump(state.cascade, { indent: 2, lineWidth: -1 });

          // POST to standard run-cascade endpoint
          const res = await fetch('http://localhost:5001/api/run-cascade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cascade_yaml: cascadeYaml,
              cascade_path: state.cascadePath,  // Include original path for sub-cascade resolution
              inputs: state.cascadeInputs,
              session_id: sessionId,
            }),
          });

          const result = await res.json();

          if (result.error) {
            throw new Error(result.error);
          }

          console.log('[runCascadeStandard] Execution started, session:', sessionId);
          console.log('[runCascadeStandard] Polling will update cell states');
          console.log('[runCascadeStandard] isRunningAll should still be true:', get().isRunningAll);
          // Polling (via useTimelinePolling) will update cellStates automatically
          // isRunningAll will be set to false when all phases complete
          // Note: Running does NOT save the file - user must explicitly click Save

        } catch (err) {
          console.error('[runCascadeStandard] Error:', err);
          set(s => {
            console.log('[runCascadeStandard] Setting isRunningAll = false due to error');
            s.isRunningAll = false;
            // Keep cascadeSessionId even on error so it stays visible in header
            // s.cascadeSessionId = null;
          });
        }
      },

      // Update cell states from polling data (replaces SSE handlers)
      updateCellStatesFromPolling: (cellStates) => {
        set(s => {
          for (const [cellName, state] of Object.entries(cellStates)) {
            // Parse result if it's a JSON string (double-encoded from DB)
            let result = state.result;
            if (typeof result === 'string') {
              try {
                result = JSON.parse(result);
              } catch (e) {
                // Not JSON, keep as string
              }
            }

            s.cellStates[cellName] = {
              ...state,
              result: result,
            };

            // Log only when we have meaningful metrics
            if (state.duration || state.cost || state.tokens_in) {
              console.log('[updateCellStatesFromPolling]', cellName, '- Duration:', state.duration, 'Cost:', state.cost, 'Tokens:', state.tokens_in, '/', state.tokens_out);
            }
          }

          // SMART COMPLETION DETECTION: Use the data we just received to determine if execution is done
          // This is data-driven, not flag-driven!
          if (s.cascade?.cells && s.cascadeSessionId) {
            const cells = s.cascade.cells;

            // Check what cells are actually doing based on the cellStates we just updated
            const cellStatuses = cells.map(c => ({
              name: c.name,
              status: s.cellStates[c.name]?.status || 'pending'
            }));

            const hasAnyRunning = cells.some(c => {
              const status = s.cellStates[c.name]?.status;
              return status === 'running';
            });

            const allComplete = cells.every(c => {
              const status = s.cellStates[c.name]?.status;
              return status === 'success' || status === 'error';
            });

            console.log('[updateCellStatesFromPolling] Data-driven execution check:', {
              totalCells: cells.length,
              hasAnyRunning,
              allComplete,
              cellStatuses,
              currentIsRunningAll: s.isRunningAll
            });

            // Update isRunningAll based on the DATA
            // ONLY set to false if we have actual completion data (not just pending)
            if (hasAnyRunning) {
              // Cells are actively running
              if (!s.isRunningAll) {
                console.log('[updateCellStatesFromPolling] Cells are running, setting isRunningAll = true');
                s.isRunningAll = true;
              }
            } else if (allComplete) {
              // All cells have terminal states (success or error)
              if (s.isRunningAll) {
                console.log('[updateCellStatesFromPolling] ✓ All cells complete! Setting isRunningAll = false');
                s.isRunningAll = false;
              }
            }
            // If all pending (no running, not complete), keep isRunningAll as-is
            // This prevents stopping polling when execution just started
          }
        });
      },

      // Legacy: Run cells sequentially via cell API (for isolated testing)
      runAllCells: async () => {
        const state = get();
        if (!state.cascade || state.isRunningAll) return;

        // Generate fresh session ID for this run
        const newSessionId = autoGenerateSessionId();

        // CRITICAL: Transition from replay to live mode
        set(s => {
          // Clear replay mode state
          s.viewMode = 'live';
          s.replaySessionId = null;

          // Set up for live execution
          s.isRunningAll = true;
          s.sessionId = newSessionId;
          s.cascadeSessionId = newSessionId;  // CRITICAL: This is what polling uses!

          // Reset all cell states to pending
          s.cascade.cells.forEach(cell => {
            s.cellStates[cell.name] = { status: 'pending' };
          });

          console.log('[runAllCells] Transitioning to live mode. Session:', newSessionId);
        });

        try {
          // Run cells sequentially using runCell to maintain session
          for (const cell of get().cascade.cells) {
            await get().runCell(cell.name);

            // Stop if cell failed
            if (get().cellStates[cell.name]?.status === 'error') {
              break;
            }
          }
        } finally {
          set(s => {
            s.isRunningAll = false;
          });
        }
      },

      runFromCell: async (cellName) => {
        const state = get();
        if (!state.cascade) return;

        const startIndex = state.cascade.cells.findIndex(c => c.name === cellName);
        if (startIndex === -1) return;

        // Ensure session ID exists
        if (!state.sessionId) {
          get().generateSessionId();
        }

        // Run cells sequentially from startIndex
        for (let i = startIndex; i < state.cascade.cells.length; i++) {
          const cell = state.cascade.cells[i];
          await get().runCell(cell.name);

          // Stop if cell failed
          if (get().cellStates[cell.name]?.status === 'error') {
            break;
          }
        }
      },

      // ============================================
      // CASCADE LIST ACTIONS
      // ============================================
      fetchCascades: async () => {
        set(state => {
          state.cascadesLoading = true;
          state.cascadesError = null;
        });

        try {
          const res = await fetch(`${API_BASE_URL}/list`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.cascades = data.cascades || data.notebooks || []; // Backend may return 'notebooks' key
            state.cascadesLoading = false;
          });
        } catch (err) {
          set(state => {
            state.cascadesError = err.message;
            state.cascadesLoading = false;
          });
        }
      },

      // Fetch default model from backend
      fetchDefaultModel: async () => {
        console.log('[fetchDefaultModel] Starting fetch...');
        try {
          const res = await fetch(`${API_BASE_URL}/models`);
          console.log('[fetchDefaultModel] Response status:', res.status);

          const data = await res.json();
          console.log('[fetchDefaultModel] Response data:', data);

          if (data.default_model) {
            console.log('[fetchDefaultModel] Setting default model:', data.default_model);
            set(state => {
              state.defaultModel = data.default_model;
            });
          } else {
            console.warn('[fetchDefaultModel] No default_model in response, using fallback');
            set(state => {
              state.defaultModel = 'google/gemini-2.5-flash-lite';
            });
          }
        } catch (err) {
          console.error('[fetchDefaultModel] Failed to fetch:', err);
          // Fallback to known default
          set(state => {
            state.defaultModel = 'google/gemini-2.5-flash-lite';
          });
        }
      },

      // Fetch cell types from backend
      fetchCellTypes: async () => {
        set(state => { state.cellTypesLoading = true; });

        try {
          const res = await fetch(`${API_BASE_URL}/phase-types`);
          const data = await res.json();

          set(state => {
            state.cellTypes = data || [];
            state.cellTypesLoading = false;
          });

          console.log('[fetchCellTypes] Loaded types:', data.length);
        } catch (err) {
          console.error('[fetchCellTypes] Failed:', err);
          set(state => {
            state.cellTypes = [];
            state.cellTypesLoading = false;
          });
        }
      },

      // ============================================
      // YAML VIEW MODE ACTIONS
      // ============================================
      setYamlViewMode: (enabled) => {
        set(state => {
          state.yamlViewMode = enabled;
        });
      },

      updateCascadeFromYaml: (yamlString) => {
        try {
          // Parse YAML
          const yaml = require('js-yaml');
          const parsed = yaml.load(yamlString);

          // Validate required fields
          if (!parsed.cascade_id || !Array.isArray(parsed.cells)) {
            throw new Error('Invalid cascade: missing cascade_id or cells array');
          }

          // Validate cells have required fields
          for (const cell of parsed.cells) {
            if (!cell.name) {
              throw new Error(`Cell missing required field: name`);
            }
          }

          set(state => {
            // Update cascade object
            state.cascade = {
              cascade_id: parsed.cascade_id,
              description: parsed.description || '',
              inputs_schema: parsed.inputs_schema || {},
              phases: parsed.cells
            };

            // Store raw YAML text (preserves comments and formatting)
            state.cascadeYamlText = yamlString;

            // Mark as dirty (unsaved changes)
            state.cascadeDirty = true;

            // Invalidate cell states (cascade structure changed)
            // Keep existing results but mark as stale
            Object.keys(state.cellStates).forEach(cellName => {
              if (!parsed.cells.find(c => c.name === cellName)) {
                // Cell was removed
                delete state.cellStates[cellName];
              } else {
                // Cell still exists but may have changed - mark stale
                if (state.cellStates[cellName]) {
                  state.cellStates[cellName].status = 'stale';
                }
              }
            });

            // Clear undo/redo (major structural change)
            state.undoStack = [];
            state.redoStack = [];
          });

          return { success: true };
        } catch (error) {
          return { success: false, error: error.message };
        }
      }
    })),
    {
      name: 'studio-cascade-storage',
      version: 2, // Increment this to force migration on next load
      partialize: (state) => ({
        // Persist mode preference and running state (for page refresh resilience)
        mode: state.mode,
        cascadeSessionId: state.cascadeSessionId,
        isRunningAll: state.isRunningAll,
      }),
      migrate: (persistedState, version) => {
        console.log('[Migration] Migrating from version', version, 'to version 2');

        // If upgrading from version 0 or 1, force timeline mode
        if (version < 2) {
          console.log('[Migration] Forcing mode to timeline (from version', version, ')');
          return {
            ...persistedState,
            mode: 'timeline',
          };
        }

        return persistedState;
      },
      onRehydrateStorage: () => (state) => {
        // Migration: Copy old data if new key is empty
        const oldData = localStorage.getItem('notebook-storage');
        const newData = localStorage.getItem('studio-cascade-storage');

        if (oldData && !newData) {
          console.log('[Migration] Copying notebook-storage → studio-cascade-storage');
          localStorage.setItem('studio-cascade-storage', oldData);
        }

        // CRITICAL MIGRATION: Fix old persisted state after rename
        if (state) {
          console.log('[Migration] Checking for old property names in persisted state...');

          // Force mode to 'timeline' if it was 'query' (old SQL mode)
          if (state.mode === 'query' || state.mode === 'notebook') {
            console.log('[Migration] Updating mode: query/notebook → timeline');
            state.mode = 'timeline';
          }

          // Migrate old property names to new ones
          if (state.selectedPhaseIndex !== undefined) {
            console.log('[Migration] Renaming: selectedPhaseIndex → selectedCellIndex');
            state.selectedCellIndex = state.selectedPhaseIndex;
            delete state.selectedPhaseIndex;
          }

          if (state.phaseTypes !== undefined) {
            console.log('[Migration] Renaming: phaseTypes → cellTypes');
            state.cellTypes = state.phaseTypes;
            delete state.phaseTypes;
          }

          if (state.phaseTypesLoading !== undefined) {
            console.log('[Migration] Renaming: phaseTypesLoading → cellTypesLoading');
            state.cellTypesLoading = state.phaseTypesLoading;
            delete state.phaseTypesLoading;
          }

          if (state.parentPhase !== undefined) {
            console.log('[Migration] Renaming: parentPhase → parentCell');
            state.parentCell = state.parentPhase;
            delete state.parentPhase;
          }

          console.log('[Migration] Migration complete. Final mode:', state.mode);
        }
      }
    }
  )
);

export default useStudioCascadeStore;
