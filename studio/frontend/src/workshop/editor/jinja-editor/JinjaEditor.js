/**
 * JinjaEditor - Rich text editor for Jinja2 templated instructions
 *
 * Features:
 * - Inline variable pills ({{ input.foo }} rendered as chips)
 * - Drag-and-drop from variable palette
 * - Two-way serialization (pills <-> Jinja2 text)
 * - Autocomplete for variables (triggered by {{)
 */

import React, { useCallback, useEffect, useMemo } from 'react';
import { LexicalComposer } from '@lexical/react/LexicalComposer';
import { ContentEditable } from '@lexical/react/LexicalContentEditable';
import { LexicalErrorBoundary } from '@lexical/react/LexicalErrorBoundary';
import { HistoryPlugin } from '@lexical/react/LexicalHistoryPlugin';
import { OnChangePlugin } from '@lexical/react/LexicalOnChangePlugin';
import { RichTextPlugin } from '@lexical/react/LexicalRichTextPlugin';
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext';
import {
  $getRoot,
  $createTextNode,
  $createParagraphNode,
  $getSelection,
  $isRangeSelection,
  COMMAND_PRIORITY_HIGH,
  KEY_ENTER_COMMAND,
  PASTE_COMMAND,
} from 'lexical';

import { VariableNode, $createVariableNode, $isVariableNode } from './VariableNode';
import VariablePalette from './VariablePalette';
import './JinjaEditor.css';

// Regex to match Jinja2 variable expressions
const JINJA_VAR_REGEX = /\{\{\s*([^}]+?)\s*\}\}/g;

/**
 * Parse Jinja2 text into segments (text and variables)
 */
function parseJinjaText(text) {
  const segments = [];
  let lastIndex = 0;
  let match;

  while ((match = JINJA_VAR_REGEX.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      segments.push({
        type: 'text',
        content: text.slice(lastIndex, match.index),
      });
    }

    // Add the variable
    segments.push({
      type: 'variable',
      path: match[1].trim(),
    });

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    segments.push({
      type: 'text',
      content: text.slice(lastIndex),
    });
  }

  return segments;
}

/**
 * Serialize Lexical state to Jinja2 text
 */
function serializeToJinja(editorState) {
  let result = '';

  editorState.read(() => {
    const root = $getRoot();
    const paragraphs = root.getChildren();

    paragraphs.forEach((paragraph, pIndex) => {
      if (pIndex > 0) {
        result += '\n';
      }

      const children = paragraph.getChildren();
      children.forEach((child) => {
        if ($isVariableNode(child)) {
          result += `{{ ${child.getPath()} }}`;
        } else {
          result += child.getTextContent();
        }
      });
    });
  });

  return result;
}

/**
 * Plugin to handle initial value and external updates
 */
function InitialValuePlugin({ value, onChange }) {
  const [editor] = useLexicalComposerContext();

  // Load initial value
  useEffect(() => {
    if (value === undefined || value === null) return;

    editor.update(() => {
      const root = $getRoot();

      // Check if content already matches to avoid infinite loops
      const currentText = serializeToJinja(editor.getEditorState());
      if (currentText === value) return;

      root.clear();

      // Split by newlines to create paragraphs
      const lines = value.split('\n');

      lines.forEach((line, lineIndex) => {
        const paragraph = $createParagraphNode();
        const segments = parseJinjaText(line);

        segments.forEach((segment) => {
          if (segment.type === 'variable') {
            paragraph.append($createVariableNode(segment.path));
          } else {
            paragraph.append($createTextNode(segment.content));
          }
        });

        // If empty paragraph, add empty text node
        if (paragraph.getChildrenSize() === 0) {
          paragraph.append($createTextNode(''));
        }

        root.append(paragraph);
      });
    });
  }, []); // Only run on mount

  return null;
}

/**
 * Plugin to handle onChange
 */
function ChangePlugin({ onChange }) {
  const handleChange = useCallback(
    (editorState) => {
      const text = serializeToJinja(editorState);
      onChange?.(text);
    },
    [onChange]
  );

  return <OnChangePlugin onChange={handleChange} />;
}

/**
 * Plugin to handle keyboard shortcuts and special behaviors
 */
function KeyboardPlugin() {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    // Handle Shift+Enter for line breaks (Enter creates new paragraph by default)
    return editor.registerCommand(
      KEY_ENTER_COMMAND,
      (event) => {
        // Allow default paragraph behavior
        return false;
      },
      COMMAND_PRIORITY_HIGH
    );
  }, [editor]);

  useEffect(() => {
    // Handle paste - convert Jinja2 syntax to pills
    return editor.registerCommand(
      PASTE_COMMAND,
      (event) => {
        const clipboardData = event.clipboardData;
        if (!clipboardData) return false;

        const text = clipboardData.getData('text/plain');
        if (!text) return false;

        // Check if text contains Jinja2 variables
        if (JINJA_VAR_REGEX.test(text)) {
          event.preventDefault();

          editor.update(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;

            const segments = parseJinjaText(text);
            segments.forEach((segment) => {
              if (segment.type === 'variable') {
                const node = $createVariableNode(segment.path);
                selection.insertNodes([node]);
              } else {
                selection.insertText(segment.content);
              }
            });
          });

          return true;
        }

        return false;
      },
      COMMAND_PRIORITY_HIGH
    );
  }, [editor]);

  return null;
}

/**
 * Plugin to handle drag-and-drop from the palette
 */
function DragDropPlugin() {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    const editorElement = editor.getRootElement();
    if (!editorElement) return;

    const handleDragOver = (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    };

    const handleDrop = (e) => {
      e.preventDefault();

      const variablePath = e.dataTransfer.getData('application/x-variable');
      if (!variablePath) return;

      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          const node = $createVariableNode(variablePath);
          selection.insertNodes([node]);
        } else {
          // If no selection, append to end
          const root = $getRoot();
          const lastParagraph = root.getLastChild();
          if (lastParagraph) {
            const node = $createVariableNode(variablePath);
            lastParagraph.append(node);
          }
        }
      });
    };

    editorElement.addEventListener('dragover', handleDragOver);
    editorElement.addEventListener('drop', handleDrop);

    return () => {
      editorElement.removeEventListener('dragover', handleDragOver);
      editorElement.removeEventListener('drop', handleDrop);
    };
  }, [editor]);

  return null;
}

/**
 * Plugin to insert a variable at cursor position (called from palette)
 */
function InsertVariablePlugin({ insertRef }) {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    insertRef.current = (variablePath) => {
      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          const node = $createVariableNode(variablePath);
          selection.insertNodes([node]);
        } else {
          // Focus and insert at end
          const root = $getRoot();
          const lastParagraph = root.getLastChild() || $createParagraphNode();
          const node = $createVariableNode(variablePath);
          lastParagraph.append(node);
          if (!root.getLastChild()) {
            root.append(lastParagraph);
          }
        }
        editor.focus();
      });
    };
  }, [editor, insertRef]);

  return null;
}

/**
 * Main JinjaEditor component
 */
function JinjaEditor({
  value,
  onChange,
  placeholder = 'Enter instructions...',
  availableVariables = [],
  showPalette = true,
  className = '',
}) {
  const insertRef = React.useRef(null);

  const initialConfig = useMemo(
    () => ({
      namespace: 'JinjaEditor',
      theme: {
        paragraph: 'jinja-editor-paragraph',
        text: {
          base: 'jinja-editor-text',
        },
      },
      nodes: [VariableNode],
      onError: (error) => {
        console.error('Lexical error:', error);
      },
    }),
    []
  );

  const handleInsertVariable = useCallback((variablePath) => {
    insertRef.current?.(variablePath);
  }, []);

  return (
    <div className={`jinja-editor-container ${className}`}>
      {showPalette && availableVariables.length > 0 && (
        <VariablePalette
          variables={availableVariables}
          onInsert={handleInsertVariable}
        />
      )}

      <LexicalComposer initialConfig={initialConfig}>
        <div className="jinja-editor-wrapper">
          <RichTextPlugin
            contentEditable={
              <ContentEditable className="jinja-editor-content" />
            }
            placeholder={
              <div className="jinja-editor-placeholder">{placeholder}</div>
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
          <HistoryPlugin />
          <InitialValuePlugin value={value} onChange={onChange} />
          <ChangePlugin onChange={onChange} />
          <KeyboardPlugin />
          <DragDropPlugin />
          <InsertVariablePlugin insertRef={insertRef} />
        </div>
      </LexicalComposer>
    </div>
  );
}

export default JinjaEditor;
export { parseJinjaText, serializeToJinja };
