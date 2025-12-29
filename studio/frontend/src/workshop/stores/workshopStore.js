import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import yaml from 'js-yaml';

/**
 * Workshop Store - Manages cascade editing and execution state
 *
 * The cascade state mirrors the YAML structure exactly for bidirectional sync.
 */

// Default empty cascade template
const createEmptyCascade = () => ({
  cascade_id: 'new_cascade',
  description: '',
  inputs_schema: {},
  validators: {},
  phases: [],
});

// Default empty phase template
const createEmptyPhase = (name = 'new_phase') => ({
  name,
  instructions: '',
  tackle: [],
  handoffs: [],
  // Optional configs (added when user enables them)
  // model: undefined,
  // soundings: undefined,
  // rules: undefined,
  // context: undefined,
  // wards: undefined,
  // human_input: undefined,
});

const useWorkshopStore = create(
  immer((set, get) => ({
    // ============================================
    // CASCADE STATE (mirrors YAML structure)
    // ============================================
    cascade: createEmptyCascade(),

    // Set entire cascade (e.g., when loading from YAML)
    setCascade: (cascade) => set((state) => {
      state.cascade = cascade;
      state.isDirty = true;
      // Reset execution state for new cascade - all phases start as ghosts
      state.executionStatus = 'idle';
      state.sessionId = null;
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.phaseResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedPhases = [];
      state.lastExecutedHandoffs = {};
    }),

    // Reset to empty cascade
    resetCascade: () => set((state) => {
      state.cascade = createEmptyCascade();
      state.isDirty = false;
      state.selectedPhaseIndex = null;
      // Reset execution state - all phases start as ghosts
      state.executionStatus = 'idle';
      state.sessionId = null;
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.phaseResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedPhases = [];
      state.lastExecutedHandoffs = {};
    }),

    // Update cascade header fields
    updateCascadeHeader: (field, value) => set((state) => {
      state.cascade[field] = value;
      state.isDirty = true;
    }),

    // ============================================
    // PHASE OPERATIONS
    // ============================================

    // Add a new phase
    addPhase: (phase = null, afterIndex = null) => set((state) => {
      const newPhase = phase || createEmptyPhase(`phase_${state.cascade.cells.length + 1}`);

      if (afterIndex !== null && afterIndex >= 0) {
        state.cascade.cells.splice(afterIndex + 1, 0, newPhase);
        state.selectedPhaseIndex = afterIndex + 1;
      } else {
        state.cascade.cells.push(newPhase);
        state.selectedPhaseIndex = state.cascade.cells.length - 1;
      }
      state.isDirty = true;
    }),

    // Update a phase by index
    // Keys with undefined values will be deleted from the phase
    updatePhase: (cellIndex, updates) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        const phase = state.cascade.cells[cellIndex];
        for (const [key, value] of Object.entries(updates)) {
          if (value === undefined) {
            delete phase[key];
          } else {
            phase[key] = value;
          }
        }
        state.isDirty = true;
      }
    }),

    // Update a specific nested field in a phase
    updatePhaseField: (cellIndex, path, value) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        const phase = state.cascade.cells[cellIndex];

        // Handle nested paths like 'soundings.factor' or 'rules.max_turns'
        const parts = path.split('.');
        let current = phase;

        for (let i = 0; i < parts.length - 1; i++) {
          if (current[parts[i]] === undefined) {
            current[parts[i]] = {};
          }
          current = current[parts[i]];
        }

        current[parts[parts.length - 1]] = value;
        state.isDirty = true;
      }
    }),

    // Remove a phase
    removePhase: (cellIndex) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        state.cascade.cells.splice(cellIndex, 1);

        // Adjust selection
        if (state.selectedPhaseIndex >= state.cascade.cells.length) {
          state.selectedPhaseIndex = state.cascade.cells.length > 0
            ? state.cascade.cells.length - 1
            : null;
        }
        state.isDirty = true;
      }
    }),

    // Reorder phases (for drag and drop)
    reorderPhases: (fromIndex, toIndex) => set((state) => {
      if (fromIndex === toIndex) return;

      const phases = state.cascade.cells;
      const [removed] = phases.splice(fromIndex, 1);
      phases.splice(toIndex, 0, removed);

      // Update selection to follow the moved phase
      if (state.selectedPhaseIndex === fromIndex) {
        state.selectedPhaseIndex = toIndex;
      } else if (
        state.selectedPhaseIndex > fromIndex &&
        state.selectedPhaseIndex <= toIndex
      ) {
        state.selectedPhaseIndex -= 1;
      } else if (
        state.selectedPhaseIndex < fromIndex &&
        state.selectedPhaseIndex >= toIndex
      ) {
        state.selectedPhaseIndex += 1;
      }

      state.isDirty = true;
    }),

    // ============================================
    // VALIDATORS OPERATIONS
    // ============================================

    addValidator: (name, config = { instructions: '' }) => set((state) => {
      state.cascade.validators[name] = config;
      state.isDirty = true;
    }),

    updateValidator: (name, config) => set((state) => {
      if (state.cascade.validators[name]) {
        Object.assign(state.cascade.validators[name], config);
        state.isDirty = true;
      }
    }),

    removeValidator: (name) => set((state) => {
      delete state.cascade.validators[name];
      state.isDirty = true;
    }),

    // ============================================
    // INPUTS SCHEMA OPERATIONS
    // ============================================

    addInput: (name, description = '') => set((state) => {
      state.cascade.inputs_schema[name] = description;
      state.isDirty = true;
    }),

    updateInput: (oldName, newName, description) => set((state) => {
      if (oldName !== newName) {
        delete state.cascade.inputs_schema[oldName];
      }
      state.cascade.inputs_schema[newName] = description;
      state.isDirty = true;
    }),

    removeInput: (name) => set((state) => {
      delete state.cascade.inputs_schema[name];
      state.isDirty = true;
    }),

    // ============================================
    // UI STATE
    // ============================================

    selectedPhaseIndex: null,
    setSelectedPhase: (index) => set({ selectedPhaseIndex: index }),

    // Track which drawers are expanded per phase
    expandedDrawers: {}, // { cellIndex: ['execution', 'soundings', ...] }

    toggleDrawer: (cellIndex, drawerName) => set((state) => {
      if (!state.expandedDrawers[cellIndex]) {
        state.expandedDrawers[cellIndex] = [];
      }

      const drawers = state.expandedDrawers[cellIndex];
      const idx = drawers.indexOf(drawerName);

      if (idx >= 0) {
        drawers.splice(idx, 1);
      } else {
        drawers.push(drawerName);
      }
    }),

    isDrawerExpanded: (cellIndex, drawerName) => {
      const state = get();
      return state.expandedDrawers[cellIndex]?.includes(drawerName) || false;
    },

    // Editor mode: 'visual' or 'yaml'
    editorMode: 'visual',
    setEditorMode: (mode) => set((state) => {
      state.editorMode = mode;
    }),

    // YAML content for Monaco (synced with cascade state)
    yamlContent: '',
    setYamlContent: (content) => set((state) => {
      state.yamlContent = content;
    }),

    // Sync visual state TO yaml content
    syncToYaml: () => set((state) => {
      const yamlStr = get().exportToYaml();
      state.yamlContent = yamlStr;
    }),

    // Sync yaml content TO visual state (returns error if invalid)
    syncFromYaml: () => {
      const state = get();
      const result = state.loadFromYaml(state.yamlContent);
      return result;
    },

    // YAML panel visibility (legacy - keeping for now)
    yamlPanelOpen: false,
    toggleYamlPanel: () => set((state) => {
      state.yamlPanelOpen = !state.yamlPanelOpen;
    }),

    // Dirty state (unsaved changes)
    isDirty: false,
    setDirty: (dirty) => set({ isDirty: dirty }),

    // ============================================
    // EXECUTION STATE
    // ============================================

    sessionId: null,
    executionStatus: 'idle', // 'idle' | 'running' | 'completed' | 'error'
    executionError: null,
    executionStartTime: null,
    executionEndTime: null,
    totalCost: 0,

    // Phase-level tracking
    // { phaseName: { status, cost, duration, startTime, turnCount, soundings: { index: {status, cost} } } }
    phaseResults: {},

    // Active soundings tracking: { phaseName: [0, 1, 2] }
    activeSoundings: {},

    // Messages/events log for display
    executionLog: [], // [{ type, timestamp, phaseName, data }]

    // ============================================
    // GHOST PHASE TRACKING
    // ============================================

    // Snapshot of phase names from the last successful execution
    // Used to determine which phases are "real" vs "ghost" (preview)
    lastExecutedPhases: [], // ['phase_1', 'phase_2', ...]

    // Executed handoffs from last run: { sourcePhaseName: targetPhaseName }
    lastExecutedHandoffs: {},

    // Check if a phase is a ghost (wasn't in the last execution)
    // This returns a function that can be called with state for reactivity
    isPhaseGhost: (phaseName) => {
      const {
        lastExecutedPhases,
        executionStatus,
        phaseResults,
      } = get();

      // If no execution has happened, all phases are ghosts (preview mode)
      if (lastExecutedPhases.length === 0 && executionStatus === 'idle') {
        return true;
      }
      // During execution, phases that haven't started yet are ghosts
      if (executionStatus === 'running') {
        const result = phaseResults[phaseName];
        return !result || result.status === 'pending';
      }
      // After execution, phases not in lastExecutedPhases are ghosts
      return !lastExecutedPhases.includes(phaseName);
    },

    // Get the executed handoff for a phase (if any)
    getExecutedHandoff: (phaseName) => {
      const state = get();
      return state.lastExecutedHandoffs[phaseName] || null;
    },

    // ============================================
    // EXECUTION EVENT HANDLERS (for SSE)
    // ============================================

    handleCascadeStart: (sessionId) => set((state) => {
      state.sessionId = sessionId;
      state.executionStatus = 'running';
      state.executionStartTime = Date.now();
      state.executionEndTime = null;
      state.executionError = null;
      state.totalCost = 0;
      state.phaseResults = {};
      state.activeSoundings = {};
      state.executionLog = [];

      // Initialize all phases as pending
      state.cascade.cells.forEach((phase) => {
        state.phaseResults[phase.name] = {
          status: 'pending',
          cost: 0,
          turnCount: 0,
          startTime: null,
          endTime: null,
          soundings: {},
        };
      });
    }),

    handlePhaseStart: (phaseName, soundingIndex = null) => set((state) => {
      if (!state.phaseResults[phaseName]) {
        state.phaseResults[phaseName] = {
          status: 'running',
          cost: 0,
          turnCount: 0,
          startTime: Date.now(),
          soundings: {},
        };
      } else {
        state.phaseResults[phaseName].status = 'running';
        state.phaseResults[phaseName].startTime = Date.now();
      }

      // Track sounding if present
      if (soundingIndex !== null && soundingIndex !== undefined) {
        if (!state.activeSoundings[phaseName]) {
          state.activeSoundings[phaseName] = [];
        }
        if (!state.activeSoundings[phaseName].includes(soundingIndex)) {
          state.activeSoundings[phaseName].push(soundingIndex);
        }

        state.phaseResults[phaseName].soundings[soundingIndex] = {
          status: 'running',
          cost: 0,
          startTime: Date.now(),
        };
      }

      state.executionLog.push({
        type: 'phase_start',
        timestamp: Date.now(),
        phaseName,
        soundingIndex,
      });
    }),

    handlePhaseComplete: (phaseName, result = {}, soundingIndex = null) => set((state) => {
      if (!state.phaseResults[phaseName]) return;

      const phase = state.phaseResults[phaseName];

      if (soundingIndex !== null && soundingIndex !== undefined) {
        // Complete specific sounding
        if (phase.candidates[soundingIndex]) {
          const sounding = phase.candidates[soundingIndex];
          sounding.status = 'completed';
          sounding.endTime = Date.now();
          if (sounding.startTime) {
            sounding.duration = (sounding.endTime - sounding.startTime) / 1000;
          }
          if (result.cost) sounding.cost = result.cost;
          if (result.is_winner) sounding.isWinner = true;

          // Store sounding output
          if (result.output !== undefined) {
            sounding.output = result.output;
          } else if (result.content !== undefined) {
            sounding.output = result.content;
          } else if (typeof result === 'string') {
            sounding.output = result;
          }
        }

        // Remove from active
        if (state.activeSoundings[phaseName]) {
          const idx = state.activeSoundings[phaseName].indexOf(soundingIndex);
          if (idx >= 0) {
            state.activeSoundings[phaseName].splice(idx, 1);
          }
          if (state.activeSoundings[phaseName].length === 0) {
            delete state.activeSoundings[phaseName];
          }
        }
      } else {
        // Complete entire phase
        phase.status = 'completed';
        phase.endTime = Date.now();
        if (phase.startTime) {
          phase.duration = (phase.endTime - phase.startTime) / 1000;
        }
      }

      if (result.cost) {
        phase.cost = (phase.cost || 0) + result.cost;
      }

      // Store the output content
      console.log('[Store] Phase complete result:', result);
      if (result.output !== undefined) {
        console.log('[Store] Setting phase.output to:', result.output);
        phase.output = result.output;
      } else if (result.content !== undefined) {
        console.log('[Store] Setting phase.output from content:', result.content);
        phase.output = result.content;
      } else if (typeof result === 'string') {
        console.log('[Store] Setting phase.output from string result:', result);
        phase.output = result;
      } else {
        console.log('[Store] No output found in result');
      }

      state.executionLog.push({
        type: 'phase_complete',
        timestamp: Date.now(),
        phaseName,
        soundingIndex,
        result,
      });
    }),

    handleSoundingStart: (phaseName, soundingIndex) => set((state) => {
      if (!state.activeSoundings[phaseName]) {
        state.activeSoundings[phaseName] = [];
      }
      if (!state.activeSoundings[phaseName].includes(soundingIndex)) {
        state.activeSoundings[phaseName].push(soundingIndex);
      }

      if (!state.phaseResults[phaseName]) {
        state.phaseResults[phaseName] = {
          status: 'running',
          cost: 0,
          turnCount: 0,
          soundings: {},
        };
      }

      state.phaseResults[phaseName].soundings[soundingIndex] = {
        status: 'running',
        cost: 0,
        startTime: Date.now(),
      };
    }),

    handleSoundingComplete: (phaseName, soundingIndex, output = null, isWinner = false) => set((state) => {
      if (state.activeSoundings[phaseName]) {
        const idx = state.activeSoundings[phaseName].indexOf(soundingIndex);
        if (idx >= 0) {
          state.activeSoundings[phaseName].splice(idx, 1);
        }
        if (state.activeSoundings[phaseName].length === 0) {
          delete state.activeSoundings[phaseName];
        }
      }

      if (state.phaseResults[phaseName]?.soundings[soundingIndex]) {
        const sounding = state.phaseResults[phaseName].soundings[soundingIndex];
        sounding.status = 'completed';
        sounding.endTime = Date.now();
        if (sounding.startTime) {
          sounding.duration = (sounding.endTime - sounding.startTime) / 1000;
        }
        if (output) {
          sounding.output = output;
        }
        if (isWinner) {
          sounding.isWinner = true;
        }
      }
    }),

    handleTurnStart: (phaseName, turnNumber, soundingIndex = null) => set((state) => {
      if (state.phaseResults[phaseName]) {
        state.phaseResults[phaseName].turnCount = turnNumber + 1;

        // Track turns per sounding if applicable
        if (soundingIndex !== null && soundingIndex !== undefined) {
          const sounding = state.phaseResults[phaseName].soundings[soundingIndex];
          if (sounding) {
            sounding.turnCount = (sounding.turnCount || 0) + 1;
          }
        }
      }

      state.executionLog.push({
        type: 'turn_start',
        timestamp: Date.now(),
        phaseName,
        turnNumber,
        soundingIndex,
      });
    }),

    handleToolCall: (phaseName, toolName, args) => set((state) => {
      state.executionLog.push({
        type: 'tool_call',
        timestamp: Date.now(),
        phaseName,
        toolName,
        args,
      });
    }),

    handleToolResult: (phaseName, toolName, result) => set((state) => {
      state.executionLog.push({
        type: 'tool_result',
        timestamp: Date.now(),
        phaseName,
        toolName,
        result,
      });
    }),

    handleHandoff: (fromPhase, toPhase) => set((state) => {
      // Track handoffs as they happen during execution
      state.lastExecutedHandoffs[fromPhase] = toPhase;

      state.executionLog.push({
        type: 'handoff',
        timestamp: Date.now(),
        fromPhase,
        toPhase,
      });
    }),

    handleCostUpdate: (cost, phaseName = null, soundingIndex = null) => set((state) => {
      state.totalCost += cost;

      if (phaseName && state.phaseResults[phaseName]) {
        state.phaseResults[phaseName].cost =
          (state.phaseResults[phaseName].cost || 0) + cost;

        // Track cost per sounding if applicable
        if (soundingIndex !== null && soundingIndex !== undefined) {
          const sounding = state.phaseResults[phaseName].soundings[soundingIndex];
          if (sounding) {
            sounding.cost = (sounding.cost || 0) + cost;
          }
        }
      }
    }),

    handleCascadeComplete: (result = {}) => set((state) => {
      state.executionStatus = 'completed';
      state.executionEndTime = Date.now();

      // Mark any still-running phases as completed
      Object.keys(state.phaseResults).forEach((phaseName) => {
        if (state.phaseResults[phaseName].status === 'running') {
          state.phaseResults[phaseName].status = 'completed';
          state.phaseResults[phaseName].endTime = Date.now();
        }
      });

      // Save executed phases for ghost tracking
      // Only include phases that actually ran (completed status)
      state.lastExecutedPhases = Object.keys(state.phaseResults).filter(
        (name) => state.phaseResults[name].status === 'completed'
      );

      // Extract executed handoffs from the result or lineage if available
      if (result.lineage && Array.isArray(result.lineage)) {
        const handoffs = {};
        for (let i = 0; i < result.lineage.length - 1; i++) {
          const current = result.lineage[i];
          const next = result.lineage[i + 1];
          if (current.phase && next.phase) {
            handoffs[current.phase] = next.phase;
          }
        }
        state.lastExecutedHandoffs = handoffs;
      }

      state.executionLog.push({
        type: 'cascade_complete',
        timestamp: Date.now(),
        result,
      });
    }),

    handleCascadeError: (error) => set((state) => {
      state.executionStatus = 'error';
      state.executionError = error;
      state.executionEndTime = Date.now();

      // Mark current running phase as error
      Object.keys(state.phaseResults).forEach((phaseName) => {
        if (state.phaseResults[phaseName].status === 'running') {
          state.phaseResults[phaseName].status = 'error';
        }
      });

      state.executionLog.push({
        type: 'cascade_error',
        timestamp: Date.now(),
        error,
      });
    }),

    // Legacy setters (for backward compatibility)
    setExecutionStatus: (status, sessionId = null, error = null) => set((state) => {
      state.executionStatus = status;
      if (sessionId) state.sessionId = sessionId;
      if (error) state.executionError = error;
    }),

    updatePhaseResult: (phaseName, result) => set((state) => {
      state.phaseResults[phaseName] = {
        ...state.phaseResults[phaseName],
        ...result,
      };
    }),

    clearExecution: () => set((state) => {
      state.sessionId = null;
      state.executionStatus = 'idle';
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.phaseResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      // Note: We keep lastExecutedPhases and lastExecutedHandoffs for ghost tracking
      // They represent the last successful run and help show what's "real" vs "preview"
    }),

    // Clear all execution history including ghost tracking
    clearExecutionHistory: () => set((state) => {
      state.sessionId = null;
      state.executionStatus = 'idle';
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.phaseResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedPhases = [];
      state.lastExecutedHandoffs = {};
    }),

    // ============================================
    // YAML IMPORT/EXPORT
    // ============================================

    loadFromYaml: (yamlString) => {
      try {
        const parsed = yaml.load(yamlString);

        // Normalize field names (handle Pydantic aliases)
        const normalized = normalizeFromYaml(parsed);

        set((state) => {
          state.cascade = normalized;
          state.isDirty = false;
          state.selectedPhaseIndex = normalized.cells?.length > 0 ? 0 : null;
        });

        return { success: true };
      } catch (error) {
        return { success: false, error: error.message };
      }
    },

    exportToYaml: () => {
      const state = get();
      const denormalized = denormalizeForYaml(state.cascade);

      return yaml.dump(denormalized, {
        indent: 2,
        lineWidth: 120,
        noRefs: true,
        sortKeys: false,
        quotingType: '"',
        forceQuotes: false,
      });
    },

    // ============================================
    // CASCADE EXECUTION
    // ============================================

    runCascade: async (inputValues = {}) => {
      const state = get();
      const cascade = state.cascade;

      if (!cascade.cascade_id) {
        return { success: false, error: 'Cascade ID is required' };
      }

      set((s) => {
        s.executionStatus = 'running';
        s.executionError = null;
        s.phaseResults = {};
      });

      try {
        // Export to YAML for execution
        const yamlContent = get().exportToYaml();

        const response = await fetch('http://localhost:5050/api/run-cascade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cascade_yaml: yamlContent,
            inputs: inputValues,
          }),
        });

        const result = await response.json();

        if (result.error) {
          set((s) => {
            s.executionStatus = 'error';
            s.executionError = result.error;
          });
          return { success: false, error: result.error };
        }

        set((s) => {
          s.sessionId = result.session_id;
        });

        return { success: true, sessionId: result.session_id };
      } catch (error) {
        set((s) => {
          s.executionStatus = 'error';
          s.executionError = error.message;
        });
        return { success: false, error: error.message };
      }
    },
  }))
);

// ============================================
// YAML NORMALIZATION HELPERS
// ============================================

function normalizeFromYaml(obj, isRoot = true) {
  if (Array.isArray(obj)) {
    return obj.map((item) => normalizeFromYaml(item, false));
  }
  if (obj && typeof obj === 'object') {
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
      // Handle 'from' in context (reserved word in Python/Pydantic)
      // In YAML it's 'from', in our state we keep it as 'from' too
      result[key] = normalizeFromYaml(value, false);
    }

    // Ensure root cascade object has required fields with defaults
    if (isRoot) {
      result.cascade_id = result.cascade_id || 'new_cascade';
      result.description = result.description || '';
      result.cells = result.cells || [];
      result.inputs_schema = result.inputs_schema || {};
      result.validators = result.validators || {};
    }

    return result;
  }
  return obj;
}

function denormalizeForYaml(obj) {
  if (Array.isArray(obj)) {
    return obj.map(denormalizeForYaml);
  }
  if (obj && typeof obj === 'object') {
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
      // Skip undefined/null values to keep YAML clean
      if (value === undefined || value === null) continue;

      // Skip empty objects and arrays
      if (typeof value === 'object' && Object.keys(value).length === 0) continue;
      if (Array.isArray(value) && value.length === 0) continue;

      result[key] = denormalizeForYaml(value);
    }
    return result;
  }
  return obj;
}

export default useWorkshopStore;
export { createEmptyCascade, createEmptyPhase };
