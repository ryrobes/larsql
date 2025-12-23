import React, { useRef, useCallback, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import useStudioQueryStore from '../stores/studioQueryStore';
import './SqlEditor.css';

function SqlEditor() {
  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  const {
    tabs,
    activeTabId,
    updateTab,
    executeQuery,
    schemas
  } = useStudioQueryStore();

  const activeTab = tabs.find(t => t.id === activeTabId);

  // Store editor instance and set up keybindings
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Configure SQL-specific settings
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });

    // Ctrl+Enter to execute
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      const state = useStudioQueryStore.getState();
      const tab = state.tabs.find(t => t.id === state.activeTabId);
      if (tab && tab.connection && tab.sql.trim()) {
        state.executeQuery(tab.id);
      }
    });

    // Ctrl+Shift+Enter to execute selected text
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter,
      () => {
        const selection = editor.getSelection();
        const selectedText = editor.getModel().getValueInRange(selection);
        if (selectedText.trim()) {
          const state = useStudioQueryStore.getState();
          const tab = state.tabs.find(t => t.id === state.activeTabId);
          if (tab && tab.connection) {
            // Temporarily update SQL, execute, then restore
            const originalSql = tab.sql;
            state.updateTab(tab.id, { sql: selectedText });
            state.executeQuery(tab.id);
            // Note: This will save the selected text as the query
          }
        }
      }
    );

    // Register SQL completion provider
    registerCompletionProvider(monaco);
  }, []);

  // Register completion provider for SQL
  const registerCompletionProvider = useCallback((monaco) => {
    // SQL keywords
    const keywords = [
      'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
      'ORDER BY', 'GROUP BY', 'HAVING', 'LIMIT', 'OFFSET', 'JOIN', 'LEFT JOIN',
      'RIGHT JOIN', 'INNER JOIN', 'OUTER JOIN', 'ON', 'AS', 'DISTINCT', 'COUNT',
      'SUM', 'AVG', 'MIN', 'MAX', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'NULL',
      'IS NULL', 'IS NOT NULL', 'ASC', 'DESC', 'UNION', 'INTERSECT', 'EXCEPT',
      'INSERT INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE FROM', 'CREATE TABLE',
      'DROP TABLE', 'ALTER TABLE', 'WITH', 'CTE'
    ];

    monaco.languages.registerCompletionItemProvider('sql', {
      provideCompletionItems: (model, position) => {
        const suggestions = [];

        // Add keywords
        keywords.forEach(kw => {
          suggestions.push({
            label: kw,
            kind: monaco.languages.CompletionItemKind.Keyword,
            insertText: kw,
            detail: 'SQL keyword'
          });
        });

        // Add tables and columns from loaded schemas
        const state = useStudioQueryStore.getState();
        Object.values(state.schemas).forEach(schemaData => {
          schemaData.schemas?.forEach(schema => {
            schema.tables?.forEach(table => {
              // Add table
              suggestions.push({
                label: table.qualified_name || table.name,
                kind: monaco.languages.CompletionItemKind.Class,
                insertText: table.qualified_name || table.name,
                detail: `Table (${table.row_count || 0} rows)`
              });

              // Add columns
              table.columns?.forEach(col => {
                suggestions.push({
                  label: col.name,
                  kind: monaco.languages.CompletionItemKind.Field,
                  insertText: col.name,
                  detail: `Column (${col.type})`
                });
              });
            });
          });
        });

        return { suggestions };
      }
    });
  }, []);

  // Handle content changes
  const handleEditorChange = useCallback((newValue) => {
    if (activeTab) {
      updateTab(activeTab.id, { sql: newValue });
    }
  }, [activeTab, updateTab]);

  // Define custom dark theme - Deep purple-black with pastels
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-sql-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        // SQL Keywords
        { token: 'keyword', foreground: 'ff9eb8', fontStyle: 'bold' },
        { token: 'keyword.sql', foreground: 'ff9eb8', fontStyle: 'bold' },

        // SQL Strings - bright cyan
        { token: 'string', foreground: '00e5ff' },
        { token: 'string.sql', foreground: '00e5ff' },
        { token: 'string.double', foreground: '00e5ff' },
        { token: 'string.single', foreground: '00e5ff' },
        { token: 'string.quoted', foreground: '00e5ff' },
        { token: 'string.quoted.single', foreground: '00e5ff' },
        { token: 'string.quoted.double', foreground: '00e5ff' },
        { token: 'string.quoted.single.sql', foreground: '00e5ff' },
        { token: 'string.quoted.double.sql', foreground: '00e5ff' },
        { token: 'string.escape', foreground: '00e5ff' },

        // SQL Functions
        { token: 'predefined', foreground: 'ffd700' },
        { token: 'predefined.sql', foreground: 'ffd700' },

        // Numbers
        { token: 'number', foreground: 'd2a8ff' },
        { token: 'number.sql', foreground: 'd2a8ff' },

        // Comments
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
        { token: 'comment.sql', foreground: '8b949e', fontStyle: 'italic' },

        // Operators
        { token: 'operator', foreground: 'ffc9e3' },
        { token: 'operator.sql', foreground: 'ffc9e3' },

        // Identifiers & Types
        { token: 'identifier', foreground: 'e6edf3' },
        { token: 'identifier.sql', foreground: 'e6edf3' },
        { token: 'type', foreground: '79c0ff' },
        { token: 'type.sql', foreground: '79c0ff' },

        // Delimiters
        { token: 'delimiter', foreground: '94a3b8' },
        { token: 'delimiter.sql', foreground: '94a3b8' },
      ],
      colors: {
        'editor.background': '#000000',                                 // pure black
        'editor.foreground': '#e6edf3',
        'editor.lineHighlightBackground': '#0a0510',
        'editor.selectionBackground': '#1a0f2f',
        'editorLineNumber.foreground': '#6e7681',
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorCursor.foreground': '#00e5ff',                           // bright cyan
        'editor.inactiveSelectionBackground': '#0f0a1e',
        'editorIndentGuide.background': '#0f0a16',
        'editorIndentGuide.activeBackground': '#1a1428',
        'editorGutter.background': '#000000',
        'scrollbarSlider.background': '#6e768180',
        'scrollbarSlider.hoverBackground': '#8b949e80',
        'scrollbarSlider.activeBackground': '#8b949e',
      },
    });
  }, []);

  // Editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 14,
    fontFamily: "'Google Sans Code', 'Monaco', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    renderLineHighlightOnlyWhenFocus: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    bracketPairColorization: { enabled: true },
    guides: {
      indentation: true,
      bracketPairs: true,
    },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    cursorBlinking: 'smooth',
    cursorSmoothCaretAnimation: 'on',
    suggestOnTriggerCharacters: true,
    quickSuggestions: true,
    parameterHints: { enabled: true },
    formatOnPaste: true,
  };

  if (!activeTab) {
    return (
      <div className="sql-editor-empty">
        No active query tab
      </div>
    );
  }

  return (
    <div className="sql-editor">
      <Editor
        height="100%"
        language="sql"
        theme="windlass-sql-dark"
        value={activeTab.sql}
        onChange={handleEditorChange}
        onMount={handleEditorDidMount}
        beforeMount={handleEditorWillMount}
        options={editorOptions}
      />
    </div>
  );
}

export default SqlEditor;
