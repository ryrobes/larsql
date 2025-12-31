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
  cells: [],
});

// Default empty cell template
const createEmptyCell = (name = 'new_cell') => ({
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
      // Reset execution state for new cascade - all cells start as ghosts
      state.executionStatus = 'idle';
      state.sessionId = null;
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.cellResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedCells = [];
      state.lastExecutedHandoffs = {};
    }),

    // Reset to empty cascade
    resetCascade: () => set((state) => {
      state.cascade = createEmptyCascade();
      state.isDirty = false;
      state.selectedCellIndex = null;
      // Reset execution state - all cells start as ghosts
      state.executionStatus = 'idle';
      state.sessionId = null;
      state.executionError = null;
      state.executionStartTime = null;
      state.executionEndTime = null;
      state.totalCost = 0;
      state.cellResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedCells = [];
      state.lastExecutedHandoffs = {};
    }),

    // Update cascade header fields
    updateCascadeHeader: (field, value) => set((state) => {
      state.cascade[field] = value;
      state.isDirty = true;
    }),

    // ============================================
    // CELL OPERATIONS
    // ============================================

    // Add a new cell
    addCell: (cell = null, afterIndex = null) => set((state) => {
      const newCell = cell || createEmptyCell(`cell_${state.cascade.cells.length + 1}`);

      if (afterIndex !== null && afterIndex >= 0) {
        state.cascade.cells.splice(afterIndex + 1, 0, newCell);
        state.selectedCellIndex = afterIndex + 1;
      } else {
        state.cascade.cells.push(newCell);
        state.selectedCellIndex = state.cascade.cells.length - 1;
      }
      state.isDirty = true;
    }),

    // Update a cell by index
    // Keys with undefined values will be deleted from the cell
    updateCell: (cellIndex, updates) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        const cell = state.cascade.cells[cellIndex];
        for (const [key, value] of Object.entries(updates)) {
          if (value === undefined) {
            delete cell[key];
          } else {
            cell[key] = value;
          }
        }
        state.isDirty = true;
      }
    }),

    // Update a specific nested field in a cell
    updateCellField: (cellIndex, path, value) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        const cell = state.cascade.cells[cellIndex];

        // Handle nested paths like 'soundings.factor' or 'rules.max_turns'
        const parts = path.split('.');
        let current = cell;

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

    // Remove a cell
    removeCell: (cellIndex) => set((state) => {
      if (cellIndex >= 0 && cellIndex < state.cascade.cells.length) {
        state.cascade.cells.splice(cellIndex, 1);

        // Adjust selection
        if (state.selectedCellIndex >= state.cascade.cells.length) {
          state.selectedCellIndex = state.cascade.cells.length > 0
            ? state.cascade.cells.length - 1
            : null;
        }
        state.isDirty = true;
      }
    }),

    // Reorder cells (for drag and drop)
    reorderCells: (fromIndex, toIndex) => set((state) => {
      if (fromIndex === toIndex) return;

      const cells = state.cascade.cells;
      const [removed] = cells.splice(fromIndex, 1);
      cells.splice(toIndex, 0, removed);

      // Update selection to follow the moved cell
      if (state.selectedCellIndex === fromIndex) {
        state.selectedCellIndex = toIndex;
      } else if (
        state.selectedCellIndex > fromIndex &&
        state.selectedCellIndex <= toIndex
      ) {
        state.selectedCellIndex -= 1;
      } else if (
        state.selectedCellIndex < fromIndex &&
        state.selectedCellIndex >= toIndex
      ) {
        state.selectedCellIndex += 1;
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

    selectedCellIndex: null,
    setSelectedCell: (index) => set({ selectedCellIndex: index }),

    // Track which drawers are expanded per cell
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

    // Cell-level tracking
    // { cellName: { status, cost, duration, startTime, turnCount, soundings: { index: {status, cost} } } }
    cellResults: {},

    // Active soundings tracking: { cellName: [0, 1, 2] }
    activeSoundings: {},

    // Messages/events log for display
    executionLog: [], // [{ type, timestamp, cellName, data }]

    // ============================================
    // GHOST CELL TRACKING
    // ============================================

    // Snapshot of cell names from the last successful execution
    // Used to determine which cells are "real" vs "ghost" (preview)
    lastExecutedCells: [], // ['cell_1', 'cell_2', ...]

    // Executed handoffs from last run: { sourceCellName: targetCellName }
    lastExecutedHandoffs: {},

    // Check if a cell is a ghost (wasn't in the last execution)
    // This returns a function that can be called with state for reactivity
    isCellGhost: (cellName) => {
      const {
        lastExecutedCells,
        executionStatus,
        cellResults,
      } = get();

      // If no execution has happened, all cells are ghosts (preview mode)
      if (lastExecutedCells.length === 0 && executionStatus === 'idle') {
        return true;
      }
      // During execution, cells that haven't started yet are ghosts
      if (executionStatus === 'running') {
        const result = cellResults[cellName];
        return !result || result.status === 'pending';
      }
      // After execution, cells not in lastExecutedCells are ghosts
      return !lastExecutedCells.includes(cellName);
    },

    // Get the executed handoff for a cell (if any)
    getExecutedHandoff: (cellName) => {
      const state = get();
      return state.lastExecutedHandoffs[cellName] || null;
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
      state.cellResults = {};
      state.activeSoundings = {};
      state.executionLog = [];

      // Initialize all cells as pending
      state.cascade.cells.forEach((cell) => {
        state.cellResults[cell.name] = {
          status: 'pending',
          cost: 0,
          turnCount: 0,
          startTime: null,
          endTime: null,
          soundings: {},
        };
      });
    }),

    handleCellStart: (cellName, soundingIndex = null) => set((state) => {
      if (!state.cellResults[cellName]) {
        state.cellResults[cellName] = {
          status: 'running',
          cost: 0,
          turnCount: 0,
          startTime: Date.now(),
          soundings: {},
        };
      } else {
        state.cellResults[cellName].status = 'running';
        state.cellResults[cellName].startTime = Date.now();
      }

      // Track sounding if present
      if (soundingIndex !== null && soundingIndex !== undefined) {
        if (!state.activeSoundings[cellName]) {
          state.activeSoundings[cellName] = [];
        }
        if (!state.activeSoundings[cellName].includes(soundingIndex)) {
          state.activeSoundings[cellName].push(soundingIndex);
        }

        state.cellResults[cellName].soundings[soundingIndex] = {
          status: 'running',
          cost: 0,
          startTime: Date.now(),
        };
      }

      state.executionLog.push({
        type: 'cell_start',
        timestamp: Date.now(),
        cellName,
        soundingIndex,
      });
    }),

    handleCellComplete: (cellName, result = {}, soundingIndex = null) => set((state) => {
      if (!state.cellResults[cellName]) return;

      const cell = state.cellResults[cellName];

      if (soundingIndex !== null && soundingIndex !== undefined) {
        // Complete specific sounding
        if (cell.candidates[soundingIndex]) {
          const sounding = cell.candidates[soundingIndex];
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
        if (state.activeSoundings[cellName]) {
          const idx = state.activeSoundings[cellName].indexOf(soundingIndex);
          if (idx >= 0) {
            state.activeSoundings[cellName].splice(idx, 1);
          }
          if (state.activeSoundings[cellName].length === 0) {
            delete state.activeSoundings[cellName];
          }
        }
      } else {
        // Complete entire cell
        cell.status = 'completed';
        cell.endTime = Date.now();
        if (cell.startTime) {
          cell.duration = (cell.endTime - cell.startTime) / 1000;
        }
      }

      if (result.cost) {
        cell.cost = (cell.cost || 0) + result.cost;
      }

      // Store the output content
      console.log('[Store] Cell complete result:', result);
      if (result.output !== undefined) {
        console.log('[Store] Setting cell.output to:', result.output);
        cell.output = result.output;
      } else if (result.content !== undefined) {
        console.log('[Store] Setting cell.output from content:', result.content);
        cell.output = result.content;
      } else if (typeof result === 'string') {
        console.log('[Store] Setting cell.output from string result:', result);
        cell.output = result;
      } else {
        console.log('[Store] No output found in result');
      }

      state.executionLog.push({
        type: 'cell_complete',
        timestamp: Date.now(),
        cellName,
        soundingIndex,
        result,
      });
    }),

    handleSoundingStart: (cellName, soundingIndex) => set((state) => {
      if (!state.activeSoundings[cellName]) {
        state.activeSoundings[cellName] = [];
      }
      if (!state.activeSoundings[cellName].includes(soundingIndex)) {
        state.activeSoundings[cellName].push(soundingIndex);
      }

      if (!state.cellResults[cellName]) {
        state.cellResults[cellName] = {
          status: 'running',
          cost: 0,
          turnCount: 0,
          soundings: {},
        };
      }

      state.cellResults[cellName].soundings[soundingIndex] = {
        status: 'running',
        cost: 0,
        startTime: Date.now(),
      };
    }),

    handleSoundingComplete: (cellName, soundingIndex, output = null, isWinner = false) => set((state) => {
      if (state.activeSoundings[cellName]) {
        const idx = state.activeSoundings[cellName].indexOf(soundingIndex);
        if (idx >= 0) {
          state.activeSoundings[cellName].splice(idx, 1);
        }
        if (state.activeSoundings[cellName].length === 0) {
          delete state.activeSoundings[cellName];
        }
      }

      if (state.cellResults[cellName]?.soundings[soundingIndex]) {
        const sounding = state.cellResults[cellName].soundings[soundingIndex];
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

    handleTurnStart: (cellName, turnNumber, soundingIndex = null) => set((state) => {
      if (state.cellResults[cellName]) {
        state.cellResults[cellName].turnCount = turnNumber + 1;

        // Track turns per sounding if applicable
        if (soundingIndex !== null && soundingIndex !== undefined) {
          const sounding = state.cellResults[cellName].soundings[soundingIndex];
          if (sounding) {
            sounding.turnCount = (sounding.turnCount || 0) + 1;
          }
        }
      }

      state.executionLog.push({
        type: 'turn_start',
        timestamp: Date.now(),
        cellName,
        turnNumber,
        soundingIndex,
      });
    }),

    handleToolCall: (cellName, toolName, args) => set((state) => {
      state.executionLog.push({
        type: 'tool_call',
        timestamp: Date.now(),
        cellName,
        toolName,
        args,
      });
    }),

    handleToolResult: (cellName, toolName, result) => set((state) => {
      state.executionLog.push({
        type: 'tool_result',
        timestamp: Date.now(),
        cellName,
        toolName,
        result,
      });
    }),

    handleHandoff: (fromCell, toCell) => set((state) => {
      // Track handoffs as they happen during execution
      state.lastExecutedHandoffs[fromCell] = toCell;

      state.executionLog.push({
        type: 'handoff',
        timestamp: Date.now(),
        fromCell,
        toCell,
      });
    }),

    handleCostUpdate: (cost, cellName = null, soundingIndex = null) => set((state) => {
      state.totalCost += cost;

      if (cellName && state.cellResults[cellName]) {
        state.cellResults[cellName].cost =
          (state.cellResults[cellName].cost || 0) + cost;

        // Track cost per sounding if applicable
        if (soundingIndex !== null && soundingIndex !== undefined) {
          const sounding = state.cellResults[cellName].soundings[soundingIndex];
          if (sounding) {
            sounding.cost = (sounding.cost || 0) + cost;
          }
        }
      }
    }),

    handleCascadeComplete: (result = {}) => set((state) => {
      state.executionStatus = 'completed';
      state.executionEndTime = Date.now();

      // Mark any still-running cells as completed
      Object.keys(state.cellResults).forEach((cellName) => {
        if (state.cellResults[cellName].status === 'running') {
          state.cellResults[cellName].status = 'completed';
          state.cellResults[cellName].endTime = Date.now();
        }
      });

      // Save executed cells for ghost tracking
      // Only include cells that actually ran (completed status)
      state.lastExecutedCells = Object.keys(state.cellResults).filter(
        (name) => state.cellResults[name].status === 'completed'
      );

      // Extract executed handoffs from the result or lineage if available
      if (result.lineage && Array.isArray(result.lineage)) {
        const handoffs = {};
        for (let i = 0; i < result.lineage.length - 1; i++) {
          const current = result.lineage[i];
          const next = result.lineage[i + 1];
          if (current.cell && next.cell) {
            handoffs[current.cell] = next.cell;
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

      // Mark current running cell as error
      Object.keys(state.cellResults).forEach((cellName) => {
        if (state.cellResults[cellName].status === 'running') {
          state.cellResults[cellName].status = 'error';
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

    updateCellResult: (cellName, result) => set((state) => {
      state.cellResults[cellName] = {
        ...state.cellResults[cellName],
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
      state.cellResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      // Note: We keep lastExecutedCells and lastExecutedHandoffs for ghost tracking
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
      state.cellResults = {};
      state.activeSoundings = {};
      state.executionLog = [];
      state.lastExecutedCells = [];
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
          state.selectedCellIndex = normalized.cells?.length > 0 ? 0 : null;
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
        s.cellResults = {};
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
export { createEmptyCascade, createEmptyCell };
