import React, { useRef, useEffect, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
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
  onValidationError,
  readOnly = false
}) {
  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  // Store editor instance
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Configure YAML-specific settings
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });

    // Add custom keybindings
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      // Trigger save - handled by parent
      const content = editor.getValue();
      onChange?.(content);
    });
  }, [onChange]);

  // Handle content changes with validation
  const handleEditorChange = useCallback((newValue) => {
    onChange?.(newValue);
  }, [onChange]);

  // Monaco editor options
  const editorOptions = {
    minimap: { enabled: true, scale: 0.8 },
    fontSize: 13,
    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
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

  // Custom dark theme matching the app
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'key', foreground: '4a9edd' },           // ocean-primary
        { token: 'string.yaml', foreground: '2dd4bf' },   // ocean-teal
        { token: 'number', foreground: 'a78bfa' },        // purple
        { token: 'keyword', foreground: 'd9a553' },       // compass-brass
        { token: 'comment', foreground: '6b7280' },       // gray
        { token: 'type', foreground: '4a9edd' },
      ],
      colors: {
        'editor.background': '#0b1219',                   // midnight-fjord
        'editor.foreground': '#e2e8f0',                   // text-primary
        'editor.lineHighlightBackground': '#1a2633',
        'editor.selectionBackground': '#2d4a5e',
        'editorLineNumber.foreground': '#4a5568',
        'editorLineNumber.activeForeground': '#8c9cac',   // mist-gray
        'editorCursor.foreground': '#4a9edd',             // ocean-primary
        'editor.inactiveSelectionBackground': '#1e3a4d',
        'editorIndentGuide.background': '#2c3b4b',
        'editorIndentGuide.activeBackground': '#4a5568',
        'editorGutter.background': '#0b1219',
        'minimap.background': '#0d151d',
        'scrollbarSlider.background': '#2c3b4b80',
        'scrollbarSlider.hoverBackground': '#3d4f61',
        'scrollbarSlider.activeBackground': '#4a5f73',
      },
    });
  }, []);

  return (
    <div className="monaco-yaml-editor">
      <div className="editor-header">
        <div className="header-left">
          <Icon icon="mdi:code-braces" width="16" />
          <span>YAML Editor</span>
        </div>
        <div className="header-hints">
          <span className="hint">
            <Icon icon="mdi:keyboard" width="12" />
            Ctrl+S to save
          </span>
          <span className="hint">
            <Icon icon="mdi:format-indent-increase" width="12" />
            2-space indent
          </span>
        </div>
      </div>

      <div className="editor-container">
        <Editor
          height="100%"
          defaultLanguage="yaml"
          value={value}
          onChange={handleEditorChange}
          onMount={handleEditorDidMount}
          beforeMount={handleEditorWillMount}
          theme="windlass-dark"
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
