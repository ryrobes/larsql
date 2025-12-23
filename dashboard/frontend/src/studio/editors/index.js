/**
 * Phase Editors Index
 *
 * Registers all custom phase editors.
 * Import this file to initialize the registry.
 */

import { registerPhaseEditor } from './phaseEditorRegistry';
import RabbitizeRecorderEditor from './RabbitizeRecorderEditor';

// Register Rabbitize Recorder Editor
registerPhaseEditor({
  id: 'rabbitize-recorder',
  label: 'Browser Recorder',
  icon: 'mdi:record-circle',
  match: (phase) => {
    // Match phases that are linux_shell or linux_shell_dangerous running npx rabbitize
    if (phase?.tool !== 'linux_shell' && phase?.tool !== 'linux_shell_dangerous') return false;

    const command = phase?.inputs?.command || '';
    return (
      command.includes('npx rabbitize') &&
      command.includes('--batch-commands')
    );
  },
  component: RabbitizeRecorderEditor
});

// Future editors can be registered here
// registerPhaseEditor({
//   id: 'sql-editor',
//   label: 'SQL Editor',
//   icon: 'mdi:database',
//   match: (phase) => phase?.tool === 'sql_data',
//   component: SQLEditor
// });

export * from './phaseEditorRegistry';
