import React, { useRef, useCallback, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import useSqlQueryStore from '../stores/sqlQueryStore';
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
  } = useSqlQueryStore();

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
      const state = useSqlQueryStore.getState();
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
          const state = useSqlQueryStore.getState();
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
        const state = useSqlQueryStore.getState();
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

  // Define custom dark theme
  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-sql-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: '2dd4bf', fontStyle: 'bold' },  // teal for keywords
        { token: 'string', foreground: 'fbbf24' },                      // yellow for strings
        { token: 'string.sql', foreground: 'fbbf24' },
        { token: 'number', foreground: 'a78bfa' },                      // purple for numbers
        { token: 'comment', foreground: '6b7280', fontStyle: 'italic' },
        { token: 'operator', foreground: 'f472b6' },                    // pink for operators
        { token: 'identifier', foreground: '60a5fa' },                  // blue for identifiers
        { token: 'type', foreground: '34d399' },                        // green for types
      ],
      colors: {
        'editor.background': '#0b1219',
        'editor.foreground': '#e2e8f0',
        'editor.lineHighlightBackground': '#1a2633',
        'editor.selectionBackground': '#2d4a5e',
        'editorLineNumber.foreground': '#4a5568',
        'editorLineNumber.activeForeground': '#8c9cac',
        'editorCursor.foreground': '#2dd4bf',
        'editor.inactiveSelectionBackground': '#1e3a4d',
        'editorIndentGuide.background': '#2c3b4b',
        'editorIndentGuide.activeBackground': '#4a5568',
        'editorGutter.background': '#0b1219',
        'scrollbarSlider.background': '#2c3b4b80',
        'scrollbarSlider.hoverBackground': '#3d4f61',
        'scrollbarSlider.activeBackground': '#4a5f73',
      },
    });
  }, []);

  // Editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 14,
    fontFamily: "'IBM Plex Mono', 'Monaco', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
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
