import React, { useRef, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import useStudioQueryStore from '../stores/studioQueryStore';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount } from '../utils/monacoTheme';
import './SqlEditor.css';

function SqlEditor() {
  const editorRef = useRef(null);
  const monacoRef = useRef(null);

  const {
    tabs,
    activeTabId,
    updateTab
  } = useStudioQueryStore();

  const activeTab = tabs.find(t => t.id === activeTabId);

  // Store editor instance and set up keybindings
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Ensure custom fonts are applied
    handleEditorMount(editor, monaco);

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
            // Execute selected text as query
            state.updateTab(tab.id, { sql: selectedText });
            state.executeQuery(tab.id);
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

  // Editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 14,
    fontFamily: "'Google Sans Code', 'Google Sans Code', 'Menlo', monospace",
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
        theme={STUDIO_THEME_NAME}
        value={activeTab.sql}
        onChange={handleEditorChange}
        onMount={handleEditorDidMount}
        beforeMount={configureMonacoTheme}
        options={editorOptions}
      />
    </div>
  );
}

export default SqlEditor;
