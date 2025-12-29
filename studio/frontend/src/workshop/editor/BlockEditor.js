import React, { useState } from 'react';
import { DndContext, DragOverlay, rectIntersection, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import CascadeCanvas from './CascadeCanvas';
import BlockPalette from './BlockPalette';
import YamlPanel from '../yaml/YamlPanel';
import './BlockEditor.css';

/**
 * DragOverlayContent - Visual preview of what's being dragged
 */
function DragOverlayContent({ activeData }) {
  if (!activeData) return null;

  // Model overlay
  if (activeData.type === 'palette-model') {
    const getProviderIcon = (provider) => {
      const icons = {
        anthropic: 'simple-icons:anthropic',
        openai: 'simple-icons:openai',
        google: 'simple-icons:google',
        'meta-llama': 'simple-icons:meta',
        deepseek: 'mdi:robot',
      };
      return icons[provider] || 'mdi:cube-outline';
    };

    return (
      <div className="drag-overlay-model">
        <Icon icon={getProviderIcon(activeData.provider)} width="14" />
        <span>{activeData.modelId}</span>
      </div>
    );
  }

  // Tool overlay
  if (activeData.type === 'palette-tool') {
    const getToolIcon = (type, name) => {
      if (name === 'manifest') return 'mdi:auto-fix';
      const icons = {
        python: 'mdi:language-python',
        cascade: 'mdi:sitemap',
        special: 'mdi:star-four-points',
      };
      return icons[type] || 'mdi:wrench';
    };

    return (
      <div className={`drag-overlay-tool ${activeData.toolName === 'manifest' ? 'manifest' : ''}`}>
        <Icon icon={getToolIcon(activeData.toolType, activeData.toolName)} width="14" />
        <span>{activeData.toolName}</span>
      </div>
    );
  }

  // Block overlay
  return (
    <div className={`drag-overlay-block color-${activeData.color}`}>
      <Icon icon={activeData.icon} width="16" />
      <span>{activeData.label}</span>
    </div>
  );
}

/**
 * BlockEditor - Main editor container with DnD context
 *
 * Contains:
 * - BlockPalette (collapsible sidebar)
 * - CascadeCanvas (main editing area)
 * - YamlPanel (collapsible preview)
 */
function BlockEditor() {
  const { yamlPanelOpen, addPhase, toggleDrawer } = useWorkshopStore();
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [activeData, setActiveData] = useState(null);

  // DnD sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px movement before drag starts
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Handle drag start - store active item data for overlay
  const handleDragStart = (event) => {
    const { active } = event;
    const dataType = active.data.current?.type;
    console.log('[DnD] Drag start:', { id: active.id, dataType, data: active.data.current });
    if (dataType === 'palette-block' || dataType === 'palette-model' || dataType === 'palette-tool') {
      setActiveData(active.data.current);
    }
  };

  // Handle drag end - create new items or reorder
  const handleDragEnd = (event) => {
    const { active, over } = event;
    setActiveData(null);

    console.log('[DnD] Drag end:', {
      activeId: active.id,
      overId: over?.id,
      activeType: active.data.current?.type,
      overType: over?.data?.current?.type,
    });

    if (!over) return;

    const activeType = active.data.current?.type;
    const blockType = active.data.current?.blockType;

    // Check if this is a palette drag (creating new item)
    if (activeType === 'palette-block') {
      const store = useWorkshopStore.getState();

      // Handle INPUT drops
      if (blockType === 'input') {
        if (over.id === 'inputs-drop-zone') {
          const inputCount = Object.keys(store.cascade.inputs_schema || {}).length;
          store.addInput(`param_${inputCount + 1}`, 'Description');
        }
        return;
      }

      // Handle VALIDATOR drops
      if (blockType === 'validator') {
        if (over.id === 'validators-drop-zone') {
          const validatorCount = Object.keys(store.cascade.validators || {}).length;
          store.addValidator(`validator_${validatorCount + 1}`, { instructions: '' });
        }
        return;
      }

      // Handle PHASE drops
      if (blockType === 'phase') {
        if (over.id === 'phases-drop-zone' || over.id.startsWith('phase-')) {
          addPhase();
        }
        return;
      }

      // Handle CONFIG block drops (soundings, rules, etc.) - must drop on a specific phase
      if (over.id.startsWith('phase-')) {
        const phaseName = over.id.replace('phase-', '');
        const phases = store.cascade.cells;
        const cellIndex = phases.findIndex(p => p.name === phaseName);
        if (cellIndex >= 0) {
          // Map block types to drawer names
          const drawerMap = {
            soundings: 'soundings',
            reforge: 'soundings', // Reforge is part of soundings drawer
            rules: 'rules',
            ward: 'validation',
            context: 'context',
            handoff: 'flow',
          };
          const drawerName = drawerMap[blockType];
          if (drawerName) {
            toggleDrawer(cellIndex, drawerName);
          }
        }
      }
      return;
    }

    // Handle MODEL drops from models palette
    if (activeType === 'palette-model') {
      const modelId = active.data.current?.modelId;
      const store = useWorkshopStore.getState();
      console.log('[DnD] Model drop:', { modelId, overId: over.id });

      if (modelId && over.id.startsWith('phase-')) {
        const phaseName = over.id.replace('phase-', '');
        const phases = store.cascade.cells;
        const cellIndex = phases.findIndex(p => p.name === phaseName);
        console.log('[DnD] Updating phase:', { phaseName, cellIndex });
        if (cellIndex >= 0) {
          store.updatePhase(cellIndex, { model: modelId });
        }
      }
      return;
    }

    // Handle TOOL drops from tools palette
    if (activeType === 'palette-tool') {
      const toolName = active.data.current?.toolName;
      const store = useWorkshopStore.getState();
      console.log('[DnD] Tool drop:', { toolName, overId: over.id });

      // Find the target phase - can drop on phase or tackle drop zone
      let cellIndex = -1;
      if (over.id.startsWith('phase-')) {
        const phaseName = over.id.replace('phase-', '');
        cellIndex = store.cascade.cells.findIndex(p => p.name === phaseName);
      } else if (over.id.startsWith('tackle-zone-')) {
        cellIndex = parseInt(over.id.replace('tackle-zone-', ''), 10);
      }

      if (toolName && cellIndex >= 0) {
        const phase = store.cascade.cells[cellIndex];
        const currentTackle = phase.traits || [];

        // Special handling for "manifest" - replaces all other tools
        if (toolName === 'manifest') {
          store.updatePhase(cellIndex, { tackle: ['manifest'] });
        }
        // Special handling for "memory" - prompt for bank name
        else if (toolName === 'memory') {
          const bankName = window.prompt(
            'Enter a name for this memory tool:\n\n' +
            'This creates a tool that lets the agent query stored memories from\n' +
            'this session. The name identifies which memory bank to recall from\n' +
            '(e.g., "research_notes", "decisions", "context").\n\n' +
            'Note: To enable memory storage, set the "memory" field in the\n' +
            'Cascade Definition to match this name.',
            'session_memory'
          );
          if (bankName && bankName.trim()) {
            const sanitizedName = bankName.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');
            if (!currentTackle.includes(sanitizedName)) {
              if (currentTackle.includes('manifest')) {
                store.updatePhase(cellIndex, { tackle: [sanitizedName] });
              } else {
                store.updatePhase(cellIndex, { tackle: [...currentTackle, sanitizedName] });
              }
            }
          }
        } else {
          // If manifest is already there, replace it with the new tool
          if (currentTackle.includes('manifest')) {
            store.updatePhase(cellIndex, { tackle: [toolName] });
          } else if (!currentTackle.includes(toolName)) {
            // Add tool if not already present
            store.updatePhase(cellIndex, { tackle: [...currentTackle, toolName] });
          }
        }

        // Open the execution drawer to show the tools
        if (!store.expandedDrawers[cellIndex]?.includes('execution')) {
          store.toggleDrawer(cellIndex, 'execution');
        }
      }
      return;
    }

    // Handle phase reordering (sortable items)
    if (active.id !== over.id && active.id.startsWith('phase-') && over.id.startsWith('phase-')) {
      const phases = useWorkshopStore.getState().cascade.cells;
      const oldIndex = phases.findIndex((p) => `phase-${p.name}` === active.id);
      const newIndex = phases.findIndex((p) => `phase-${p.name}` === over.id);

      if (oldIndex !== -1 && newIndex !== -1) {
        useWorkshopStore.getState().reorderPhases(oldIndex, newIndex);
      }
    }
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={rectIntersection}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="block-editor">
        {/* Block Palette - Collapsible */}
        <div className={`palette-container ${paletteOpen ? 'open' : 'closed'}`}>
          <button
            className="palette-toggle"
            onClick={() => setPaletteOpen(!paletteOpen)}
            title={paletteOpen ? 'Hide Palette' : 'Show Palette'}
          >
            <Icon icon={paletteOpen ? 'mdi:chevron-left' : 'mdi:chevron-right'} width="20" />
          </button>
          {paletteOpen && <BlockPalette />}
        </div>

        {/* Main Canvas */}
        <div className="canvas-container">
          <CascadeCanvas />
        </div>

        {/* YAML Panel - Collapsible */}
        {yamlPanelOpen && (
          <div className="yaml-panel-container">
            <YamlPanel />
          </div>
        )}
      </div>

      {/* Drag Overlay - shows preview while dragging */}
      <DragOverlay>
        {activeData && <DragOverlayContent activeData={activeData} />}
      </DragOverlay>
    </DndContext>
  );
}

export default BlockEditor;
