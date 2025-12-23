import React, { useRef, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { configureMonacoTheme, STUDIO_THEME_NAME } from '../../studio/utils/monacoTheme';
import './MonacoYamlEditor.css';

/**
 * MonacoYamlEditor - Full YAML editor with Monaco
 *
 * Features:
 * - YAML syntax highlighting and validation
 * - Dark theme matching the app
 * - Real-time editing with debounced sync
 * - Line numbers, minimap, word wrap
 */
function MonacoYamlEditor({
  value,
  onChange,
  onFocus,
  onBlur,
  onValidationError,
  readOnly = false
}) {
  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  // Store editor instance
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    window.__activeMonacoEditor = editor; // Enable drag-and-drop

    // Configure YAML-specific settings
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });

    // Add focus handler
    editor.onDidFocusEditorText(() => {
      window.__activeMonacoEditor = editor; // Update on focus
      if (onFocus) {
        onFocus();
      }
    });

    // Add blur handler
    editor.onDidBlurEditorText(() => {
      if (onBlur) {
        const content = editor.getValue();
        onBlur(content);
      }
    });

    // Add custom keybindings
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      // Trigger save - handled by parent
      const content = editor.getValue();
      onChange?.(content);
    });
  }, [onChange, onFocus, onBlur]);

  // Handle content changes with validation
  const handleEditorChange = useCallback((newValue) => {
    onChange?.(newValue);
  }, [onChange]);

  // Monaco editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 12,
    fontFamily: "'Monaco', 'Menlo', monospace",
    lineNumbers: 'off',
    renderLineHighlight: 'line',
    renderLineHighlightOnlyWhenFocus: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    wrappingStrategy: 'advanced',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    foldingStrategy: 'indentation',
    showFoldingControls: 'mouseover',
    bracketPairColorization: { enabled: true },
    guides: {
      indentation: true,
      bracketPairs: true,
    },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    cursorBlinking: 'smooth',
    cursorSmoothCaretAnimation: 'on',
    readOnly,
  };


  return (
    <div className="monaco-yaml-editor">
      <div className="editor-container">
        <Editor
          height="100%"
          defaultLanguage="yaml"
          value={value}
          onChange={handleEditorChange}
          onMount={handleEditorDidMount}
          beforeMount={configureMonacoTheme}
          theme={STUDIO_THEME_NAME}
          options={editorOptions}
          loading={
            <div className="editor-loading">
              <Icon icon="mdi:loading" width="24" className="spin" />
              <span>Loading editor...</span>
            </div>
          }
        />
      </div>
    </div>
  );
}

export default MonacoYamlEditor;
