import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import './TraitPills.css';

/**
 * TacklePills - Droppable zone displaying tools as removable pills
 *
 * Features:
 * - Drop zone for tools from the palette
 * - Displays selected tools as removable pills
 * - Special styling for "manifest" (Quartermaster)
 * - Visual feedback when hovering with a tool
 */
function TacklePills({ value = [], onChange, cellIndex }) {
  const { setNodeRef, isOver, active } = useDroppable({
    id: `tackle-zone-${cellIndex}`,
    data: {
      type: 'tackle-zone',
      cellIndex,
    },
  });

  // Check if dragging a tool over us
  const isDraggingTool = active?.data?.current?.type === 'palette-tool';
  const isDropTarget = isOver && isDraggingTool;

  const handleRemoveTool = (toolName) => {
    onChange(value.filter((t) => t !== toolName));
  };

  // Known built-in tools for matching
  const KNOWN_TOOLS = [
    'manifest', 'linux_shell', 'run_code', 'smart_sql_run', 'take_screenshot',
    'ask_human', 'ask_human_custom', 'set_state', 'spawn_cascade', 'create_chart',
    'memory' // memory is special, actual tool names are bank names
  ];

  const isMemoryTool = (toolName) => {
    // Memory tools are named after bank names - lowercase with underscores
    // and don't match known tool patterns
    if (KNOWN_TOOLS.includes(toolName)) return false;
    if (toolName.includes('shell') || toolName.includes('code') ||
        toolName.includes('sql') || toolName.includes('screenshot') ||
        toolName.includes('human') || toolName.includes('ask') ||
        toolName.includes('chart') || toolName.includes('state') ||
        toolName.includes('cascade') || toolName.includes('rabbit')) {
      return false;
    }
    // Likely a memory bank name
    return /^[a-z][a-z0-9_]*$/.test(toolName);
  };

  const getToolIcon = (toolName) => {
    if (toolName === 'manifest') return 'mdi:auto-fix';
    if (isMemoryTool(toolName)) return 'mdi:brain';
    // Could extend with more specific icons based on tool name
    if (toolName.includes('shell') || toolName.includes('linux')) return 'mdi:console';
    if (toolName.includes('python') || toolName.includes('code')) return 'mdi:language-python';
    if (toolName.includes('sql')) return 'mdi:database-search';
    if (toolName.includes('screenshot')) return 'mdi:monitor-screenshot';
    if (toolName.includes('human') || toolName.includes('ask')) return 'mdi:account-question';
    if (toolName.includes('chart')) return 'mdi:chart-line';
    if (toolName.includes('state')) return 'mdi:database-edit';
    if (toolName.includes('spawn') || toolName.includes('cascade')) return 'mdi:sitemap';
    if (toolName.includes('rabbit')) return 'mdi:rabbit';
    return 'mdi:wrench';
  };

  const getToolColor = (toolName) => {
    if (toolName === 'manifest') return 'manifest';
    if (isMemoryTool(toolName)) return 'memory';
    if (toolName.includes('shell') || toolName.includes('linux')) return 'teal';
    if (toolName.includes('python') || toolName.includes('code')) return 'teal';
    if (toolName.includes('sql')) return 'ocean';
    if (toolName.includes('cascade')) return 'ocean';
    if (toolName.includes('human') || toolName.includes('ask')) return 'brass';
    return 'default';
  };

  const isManifest = value.includes('manifest');

  return (
    <div
      ref={setNodeRef}
      className={`tackle-pills ${isDropTarget ? 'drop-over' : ''} ${value.length === 0 ? 'empty' : ''}`}
    >
      {value.length === 0 ? (
        <div className="pills-placeholder">
          <Icon icon="mdi:drag" width="14" />
          <span>Drag tools here from the palette</span>
        </div>
      ) : (
        <div className="pills-container">
          {value.map((toolName) => (
            <div
              key={toolName}
              className={`tool-pill ${getToolColor(toolName)}`}
              title={
                toolName === 'manifest'
                  ? 'Quartermaster auto-selects tools based on context'
                  : isMemoryTool(toolName)
                  ? `Memory recall: "${toolName}" bank`
                  : toolName
              }
            >
              <Icon icon={getToolIcon(toolName)} width="14" />
              <span className="pill-name">{toolName}</span>
              <button
                className="pill-remove"
                onClick={() => handleRemoveTool(toolName)}
                type="button"
                title="Remove tool"
              >
                <Icon icon="mdi:close" width="12" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Drop indicator */}
      {isDropTarget && (
        <div className="drop-indicator">
          <Icon icon="mdi:plus-circle" width="16" />
          <span>Drop to add tool</span>
        </div>
      )}

      {/* Manifest indicator */}
      {isManifest && (
        <div className="manifest-indicator">
          <Icon icon="mdi:auto-fix" width="12" />
          <span>Quartermaster will auto-select tools</span>
        </div>
      )}
    </div>
  );
}

export default TacklePills;
