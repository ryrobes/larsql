import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

const API_BASE_URL = 'http://localhost:5001/api';

/**
 * Simple hash function for cell caching.
 * Creates a fingerprint of the cell's inputs to detect changes.
 */
function hashCellInputs(phase, cascadeInputs, priorOutputHashes) {
  // Combine relevant inputs into a string
  const inputStr = JSON.stringify({
    tool: phase.tool,
    inputs: phase.inputs,
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
 * Notebook Store - State management for Data Cascade notebooks
 *
 * A notebook is a cascade with only deterministic phases (sql_data, python_data,
 * js_data, clojure_data) that can be edited, run, and saved as reusable tools.
 *
 * Polyglot support: Data flows between languages via JSON serialization.
 * - SQL: rows as array of objects, accessed via _cell_name tables
 * - Python: data.cell_name returns DataFrame
 * - JavaScript: data.cell_name returns array of objects
 * - Clojure: (:cell-name data) returns vector of maps
 */
const useCascadeStore = create(
  persist(
    immer((set, get) => ({
      // ============================================
      // MODE STATE
      // ============================================
      mode: 'query',  // 'query' | 'notebook'

      // ============================================
      // CASCADE STATE
      // ============================================
      cascade: null,  // Current cascade object
      cascadePath: null,  // Path to loaded cascade
      cascadeDirty: false,  // Unsaved changes

      // Cascade structure:
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
      cascadeInputs: {},  // User-provided input values

      // ============================================
      // CELL EXECUTION STATE
      // ============================================
      cellStates: {},  // { [phaseName]: { status, result, error, duration } }
      // status: 'pending' | 'running' | 'success' | 'error' | 'stale'

      isRunningAll: false,  // Full notebook execution in progress
      cascadeSessionId: null,  // Session ID when running full cascade (for SSE tracking)

      // Session ID for temp table persistence across cell executions
      // Generated when notebook loads, persists until restart/reload
      sessionId: null,

      // ============================================
      // UI STATE
      // ============================================
      selectedPhaseIndex: null,  // Currently selected phase in timeline view

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
      // Per-cell auto-fix overrides: { [phaseName]: { enabled, model, prompt } }
      cellAutoFixOverrides: {},

      // ============================================
      // UNDO/REDO HISTORY
      // ============================================
      undoStack: [],  // Stack of previous cascade states (phases snapshots)
      redoStack: [],  // Stack of undone states
      maxHistorySize: 50,  // Maximum history entries

      // ============================================
      // CASCADE LIST
      // ============================================
      cascades: [],  // List of available cascades
      cascadesLoading: false,
      cascadesError: null,

      // ============================================
      // UNDO/REDO HELPERS
      // ============================================
      _saveToUndoStack: () => {
        const state = get();
        if (!state.cascade?.phases) return;

        // Create a deep copy of phases for the undo stack
        const phasesSnapshot = JSON.parse(JSON.stringify(state.cascade.phases));

        set(s => {
          // Push current state to undo stack
          s.undoStack.push(phasesSnapshot);

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
          const currentSnapshot = JSON.parse(JSON.stringify(s.cascade.phases));
          s.redoStack.push(currentSnapshot);

          // Pop previous state from undo stack
          const previousState = s.undoStack.pop();
          s.cascade.phases = previousState;
          s.cascadeDirty = true;
        });

        return true;
      },

      redo: () => {
        const state = get();
        if (!state.cascade || state.redoStack.length === 0) return false;

        set(s => {
          // Save current state to undo stack
          const currentSnapshot = JSON.parse(JSON.stringify(s.cascade.phases));
          s.undoStack.push(currentSnapshot);

          // Pop next state from redo stack
          const nextState = s.redoStack.pop();
          s.cascade.phases = nextState;
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

      setSelectedPhaseIndex: (index) => {
        set(state => {
          state.selectedPhaseIndex = index;
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
          if (s.cascade?.phases) {
            s.cascade.phases.forEach(phase => {
              s.cellStates[phase.name] = { status: 'pending' };
            });
          }
        });
      },

      // ============================================
      // CASCADE CRUD
      // ============================================
      newCascade: () => {
        set(state => {
          state.cascade = {
            cascade_id: 'new_cascade',
            description: 'New cascade',
            inputs_schema: {},
            phases: []
          };
          state.cascadePath = null;
          state.cascadeDirty = false;
          state.cascadeInputs = {};
          state.cellStates = {};
          // Generate fresh session for new cascade
          state.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          // Clear undo/redo history
          state.undoStack = [];
          state.redoStack = [];
        });
      },

      loadCascade: async (path) => {
        try {
          const res = await fetch(`${API_BASE_URL}/notebook/load?path=${encodeURIComponent(path)}`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.cascade = data.cascade || data.notebook;
            state.cascadePath = path;
            state.cascadeDirty = false;
            state.cascadeInputs = {};
            state.cellStates = {};
            // Generate fresh session for loaded notebook
            state.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
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

        try {
          const res = await fetch(`${API_BASE_URL}/notebook/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              path: savePath,
              cascade: state.cascade
            })
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
      addCell: (type = 'sql_data', afterIndex = null, templateCode = null) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade) return;

          const phases = state.cascade.phases;
          const cellCount = phases.length + 1;

          // Default code templates by language
          const defaultTemplates = {
            sql_data: '-- Enter SQL here\n-- Reference prior cells with: SELECT * FROM _cell_name\nSELECT 1',
            python_data: '# Access prior cell outputs as DataFrames:\n# df = data.cell_name\n#\n# Set result to a DataFrame or dict:\nresult = {"message": "Hello"}',
            js_data: '// Access prior cell outputs:\n// const rows = data.cell_name;\n//\n// Set result to an array of objects or value:\nresult = [{ message: "Hello" }];',
            clojure_data: '; Access prior cell outputs:\n; (:cell-name data)\n;\n; Return a vector of maps or value:\n[{:message "Hello"}]',
            llm_phase: `You are a helpful assistant analyzing data.

Use Jinja2 templates to reference data:
- Inputs: {{ input.param_name }}
- Prior phases: {{ outputs.phase_name }}
- State: {{ state.var_name }}

Provide your analysis below:
`,
            windlass_data: `# LLM Phase Cell (Data Tool)
# Access prior cells with: {{outputs.cell_name}}
# Full Windlass power: soundings, reforge, wards, model selection

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
`
          };
          const defaultCode = defaultTemplates[type] || defaultTemplates.python_data;

          // Create phase based on type
          const newCell = type === 'llm_phase' ? {
            name: `phase_${cellCount}`,
            instructions: templateCode || defaultCode,
            model: 'anthropic/claude-sonnet-4',
            tackle: [],
          } : {
            name: `cell_${cellCount}`,
            tool: type,
            inputs: type === 'sql_data'
              ? { query: templateCode || defaultCode }
              : { code: templateCode || defaultCode }
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

          state.cascadeDirty = true;
          state.cellStates[newCell.name] = { status: 'pending' };
        });
      },

      updateCell: (index, updates) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade || !state.cascade.phases[index]) return;

          const cell = state.cascade.phases[index];
          const oldName = cell.name;

          // Handle name change - update references
          if (updates.name && updates.name !== oldName) {
            // Update handoffs in other phases that reference this cell
            state.cascade.phases.forEach(phase => {
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
          if (!state.cascade || state.cascade.phases.length <= 1) return;

          const phases = state.cascade.phases;
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
          state.cascadeDirty = true;
        });
      },

      moveCell: (fromIndex, toIndex) => {
        // Save state before modification
        get()._saveToUndoStack();

        set(state => {
          if (!state.cascade) return;

          const phases = state.cascade.phases;
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
          if (!state.cascade) return;

          // Mark all cells after fromIndex as stale
          for (let i = fromIndex + 1; i < state.cascade.phases.length; i++) {
            const phaseName = state.cascade.phases[i].name;
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
      // AUTO-FIX ACTIONS
      // ============================================
      setGlobalAutoFix: (config) => {
        set(state => {
          state.autoFixConfig = { ...state.autoFixConfig, ...config };
        });
      },

      setCellAutoFix: (phaseName, config) => {
        set(state => {
          state.cellAutoFixOverrides[phaseName] = {
            ...(state.cellAutoFixOverrides[phaseName] || {}),
            ...config
          };
        });
      },

      clearCellAutoFix: (phaseName) => {
        set(state => {
          delete state.cellAutoFixOverrides[phaseName];
        });
      },

      // Get effective auto-fix config for a cell (merges global + per-cell overrides)
      getEffectiveAutoFixConfig: (phaseName) => {
        const state = get();
        const override = state.cellAutoFixOverrides[phaseName];
        if (override) {
          return { ...state.autoFixConfig, ...override };
        }
        return state.autoFixConfig;
      },

      // ============================================
      // EXECUTION ACTIONS
      // ============================================
      runCell: async (phaseName, forceRun = false) => {
        const state = get();
        if (!state.cascade) return;

        const phaseIndex = state.cascade.phases.findIndex(p => p.name === phaseName);
        if (phaseIndex === -1) return;

        const phase = state.cascade.phases[phaseIndex];

        // Ensure we have a session ID
        let sessionId = state.sessionId;
        if (!sessionId) {
          sessionId = get().generateSessionId();
        }

        // Collect prior output hashes for cache invalidation
        const priorOutputHashes = {};
        for (let i = 0; i < phaseIndex; i++) {
          const priorPhase = state.cascade.phases[i];
          const priorState = state.cellStates[priorPhase.name];
          if (priorState?.inputHash) {
            priorOutputHashes[priorPhase.name] = priorState.inputHash;
          }
        }

        // Compute hash of current inputs
        const currentHash = hashCellInputs(phase, state.cascadeInputs, priorOutputHashes);
        const existingState = state.cellStates[phaseName];

        // Check cache: if hash matches and we have a successful result, skip execution
        if (!forceRun &&
            existingState?.status === 'success' &&
            existingState?.inputHash === currentHash &&
            existingState?.result) {
          // Cache hit - mark as cached and return
          set(s => {
            s.cellStates[phaseName] = {
              ...existingState,
              cached: true
            };
          });
          console.log(`[Cache] Hit for ${phaseName} (hash: ${currentHash})`);
          return;
        }

        set(s => {
          s.cellStates[phaseName] = { status: 'running', result: null, error: null, cached: false };
        });

        const startTime = performance.now();

        try {
          // Collect outputs from prior phases for python_data
          const priorOutputs = {};
          for (let i = 0; i < phaseIndex; i++) {
            const priorPhase = state.cascade.phases[i];
            const priorState = state.cellStates[priorPhase.name];
            if (priorState?.result) {
              priorOutputs[priorPhase.name] = priorState.result;
            }
          }

          // Get effective auto-fix config for this cell
          const autoFixConfig = get().getEffectiveAutoFixConfig(phaseName);

          const res = await fetch(`${API_BASE_URL}/notebook/run-cell`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cell: phase,
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
              s.cellStates[phaseName] = {
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
              s.cellStates[phaseName] = {
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
            get().markDownstreamStale(phaseIndex);
          }
        } catch (err) {
          const duration = Math.round(performance.now() - startTime);
          set(s => {
            s.cellStates[phaseName] = {
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

        // Generate session ID
        const sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

        set(s => {
          s.isRunningAll = true;
          s.cascadeSessionId = sessionId;
          // Reset all cell states to pending
          s.cascade.phases.forEach(phase => {
            s.cellStates[phase.name] = { status: 'pending' };
          });
        });

        try {
          // Export notebook to YAML
          const yaml = require('js-yaml');
          const cascadeYaml = yaml.dump(state.cascade, { indent: 2, lineWidth: -1 });

          // POST to standard run-cascade endpoint
          const res = await fetch('http://localhost:5001/api/run-cascade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cascade_yaml: cascadeYaml,
              inputs: state.cascadeInputs,
              session_id: sessionId,
            }),
          });

          const result = await res.json();

          if (result.error) {
            throw new Error(result.error);
          }

          console.log('[runCascadeStandard] Execution started, session:', sessionId);
          // SSE events will update cell states as phases complete
          // Note: Don't set isRunningAll = false here - wait for cascade_complete event

        } catch (err) {
          console.error('[runCascadeStandard] Error:', err);
          set(s => {
            s.isRunningAll = false;
            s.cascadeSessionId = null;
          });
        }
      },

      // Handle SSE events for standard cascade execution
      handleSSEPhaseStart: (sessionId, phaseName) => {
        const state = get();
        if (state.cascadeSessionId !== sessionId) return;

        console.log('[NotebookStore SSE] Phase start:', phaseName);

        set(s => {
          if (!s.cellStates[phaseName]) {
            s.cellStates[phaseName] = {};
          }
          s.cellStates[phaseName].status = 'running';
        });
      },

      handleSSEPhaseComplete: (sessionId, phaseName, result) => {
        const state = get();
        if (state.cascadeSessionId !== sessionId) return;

        console.log('[NotebookStore SSE] Phase complete:', phaseName, 'result:', result);

        // Extract the actual output from SSE result structure
        // SSE sends: {output: {...}, duration_ms: ...}
        // Note: We get TWO phase_complete events per phase:
        //   1. First with actual data: {output: {rows, columns}, duration_ms}
        //   2. Second with just handoff: {output: 'next_phase_name', duration_ms}
        const actualResult = result?.output || result;
        const duration = result?.duration_ms;

        // Skip if this looks like a handoff-only event:
        // Handoffs are simple phase names (single word, short, no spaces usually)
        // Real output is longer or has special chars or is an object
        const isLikelyHandoff = typeof actualResult === 'string'
          && actualResult.length < 30
          && !actualResult.includes(' ')
          && !actualResult.includes('\n');

        if (isLikelyHandoff) {
          console.log('[NotebookStore SSE] Skipping handoff event for:', phaseName, '(output:', actualResult, ')');
          return;
        }

        console.log('[NotebookStore SSE] Storing result for:', phaseName);

        set(s => {
          s.cellStates[phaseName] = {
            status: 'success',
            result: actualResult,
            duration: duration,
          };
        });
      },

      handleSSECascadeComplete: (sessionId) => {
        const state = get();
        if (state.cascadeSessionId !== sessionId) return;

        set(s => {
          s.isRunningAll = false;
          s.cascadeSessionId = null;
        });
      },

      handleSSECascadeError: (sessionId, phaseName, error) => {
        const state = get();
        if (state.cascadeSessionId !== sessionId) return;

        set(s => {
          if (phaseName && s.cellStates[phaseName]) {
            s.cellStates[phaseName] = {
              status: 'error',
              error: error,
            };
          }
          s.isRunningAll = false;
          s.cascadeSessionId = null;
        });
      },

      // Legacy: Run cells sequentially via notebook API (for isolated testing)
      runAllCells: async () => {
        const state = get();
        if (!state.cascade || state.isRunningAll) return;

        // Ensure we have a session ID (generate fresh for run all)
        set(s => {
          s.isRunningAll = true;
          s.sessionId = `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          // Reset all cell states to pending
          s.cascade.phases.forEach(phase => {
            s.cellStates[phase.name] = { status: 'pending' };
          });
        });

        try {
          // Run cells sequentially using runCell to maintain session
          for (const phase of get().cascade.phases) {
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
        if (!state.cascade) return;

        const startIndex = state.cascade.phases.findIndex(p => p.name === phaseName);
        if (startIndex === -1) return;

        // Ensure session ID exists
        if (!state.sessionId) {
          get().generateSessionId();
        }

        // Run cells sequentially from startIndex
        for (let i = startIndex; i < state.cascade.phases.length; i++) {
          const phase = state.cascade.phases[i];
          await get().runCell(phase.name);

          // Stop if cell failed
          if (get().cellStates[phase.name]?.status === 'error') {
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
          const res = await fetch(`${API_BASE_URL}/notebook/list`);
          const data = await res.json();

          if (data.error) {
            throw new Error(data.error);
          }

          set(state => {
            state.cascades = data.cascades || data.notebooks || [];
            state.cascadesLoading = false;
          });
        } catch (err) {
          set(state => {
            state.cascadesError = err.message;
            state.cascadesLoading = false;
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

export default useCascadeStore;
