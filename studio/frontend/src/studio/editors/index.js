/**
 * Cell Editors Index
 *
 * Registers all custom cell editors.
 * Import this file to initialize the registry.
 */

import { registerCellEditor } from './cellEditorRegistry';
import RabbitizeRecorderEditor from './RabbitizeRecorderEditor';

// Register Browser Recorder Editor
// Matches both native `browser` tool and legacy shell-based approaches
registerCellEditor({
  id: 'browser-recorder',
  label: 'Browser Recorder',
  icon: 'mdi:record-circle',
  match: (cell) => {
    // Native browser tool (preferred)
    if (cell?.tool === 'browser') {
      return true;
    }

    // Legacy: shell commands running browser batch
    if (cell?.tool === 'linux_shell' || cell?.tool === 'linux_shell_dangerous') {
      const command = cell?.inputs?.command || '';
      const isRvbbitBatch = command.includes('rvbbit browser batch') && command.includes('--commands');
      const isLegacyRabbitize = command.includes('npx rabbitize') && command.includes('--batch-commands');
      return isRvbbitBatch || isLegacyRabbitize;
    }

    return false;
  },
  component: RabbitizeRecorderEditor
});

// Future editors can be registered here
// registerCellEditor({
//   id: 'sql-editor',
//   label: 'SQL Editor',
//   icon: 'mdi:database',
//   match: (cell) => cell?.tool === 'sql_data',
//   component: SQLEditor
// });

export * from './cellEditorRegistry';
