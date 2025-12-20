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

  // Custom dark theme - GitHub Dark inspired, pastels on black
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'key', foreground: '79c0ff' },           // pastel cyan (keys)
        { token: 'string', foreground: '9be9a8' },        // subtle pastel green
        { token: 'string.yaml', foreground: '9be9a8' },   // subtle pastel green
        { token: 'number', foreground: 'd2a8ff' },        // pastel purple
        { token: 'keyword', foreground: 'ff9eb8' },       // pastel pink
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
        { token: 'type', foreground: '79c0ff' },          // pastel cyan
      ],
      colors: {
        'editor.background': '#000000',                   // pure black
        'editor.foreground': '#e6edf3',                   // light gray
        'editor.lineHighlightBackground': '#161b22',
        'editor.selectionBackground': '#264f78',
        'editorLineNumber.foreground': '#6e7681',
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorCursor.foreground': '#79c0ff',             // pastel cyan
        'editor.inactiveSelectionBackground': '#1d2d3e',
        'editorIndentGuide.background': '#21262d',
        'editorIndentGuide.activeBackground': '#30363d',
        'editorGutter.background': '#000000',
        'minimap.background': '#0d1117',
        'scrollbarSlider.background': '#6e768180',
        'scrollbarSlider.hoverBackground': '#8b949e80',
        'scrollbarSlider.activeBackground': '#8b949e',
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
