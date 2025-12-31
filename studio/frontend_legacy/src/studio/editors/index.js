/**
 * Cell Editors Index
 *
 * Registers all custom cell editors.
 * Import this file to initialize the registry.
 */

import { registerCellEditor } from './cellEditorRegistry';
import RabbitizeRecorderEditor from './RabbitizeRecorderEditor';

// Register Rabbitize Recorder Editor
registerCellEditor({
  id: 'rabbitize-recorder',
  label: 'Browser Recorder',
  icon: 'mdi:record-circle',
  match: (cell) => {
    // Match cells that are linux_shell or linux_shell_dangerous running npx rabbitize
    if (cell?.tool !== 'linux_shell' && cell?.tool !== 'linux_shell_dangerous') return false;

    const command = cell?.inputs?.command || '';
    return (
      command.includes('npx rabbitize') &&
      command.includes('--batch-commands')
    );
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
