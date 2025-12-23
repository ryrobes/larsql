/**
 * Shared Monaco theme configuration for Studio
 *
 * All Monaco editors in Studio should use this theme for consistency.
 * Import and use `configureMonacoTheme` as the `beforeMount` prop.
 */

export const STUDIO_THEME_NAME = 'studio-dark';

/**
 * Studio dark theme - Purple/Cyan/Pink on pure black
 * Matches the overall Studio UI aesthetic
 */
export const studioThemeDefinition = {
  base: 'vs-dark',
  inherit: true,
  rules: [
    // YAML/JSON keys
    { token: 'key', foreground: '00e5ff' },              // cyan
    { token: 'key.json', foreground: '00e5ff' },

    // Strings
    { token: 'string', foreground: 'a78bfa' },           // purple
    { token: 'string.yaml', foreground: 'a78bfa' },
    { token: 'string.json', foreground: 'a78bfa' },
    { token: 'string.sql', foreground: 'a78bfa' },

    // Numbers
    { token: 'number', foreground: '34d399' },           // green
    { token: 'number.json', foreground: '34d399' },

    // Keywords
    { token: 'keyword', foreground: 'f472b6' },          // pink
    { token: 'keyword.sql', foreground: 'f472b6' },

    // SQL-specific
    { token: 'predefined.sql', foreground: '00e5ff' },   // cyan (functions)
    { token: 'operator.sql', foreground: 'cbd5e1' },     // light gray

    // Python-specific
    { token: 'keyword.python', foreground: 'f472b6' },   // pink
    { token: 'identifier.python', foreground: 'cbd5e1' },

    // JavaScript-specific
    { token: 'keyword.js', foreground: 'f472b6' },       // pink

    // Comments
    { token: 'comment', foreground: '64748b', fontStyle: 'italic' },

    // Types
    { token: 'type', foreground: '00e5ff' },             // cyan

    // Jinja2 template syntax (common in YAML)
    { token: 'delimiter.bracket', foreground: 'fbbf24' }, // yellow for {{ }}
  ],
  colors: {
    'editor.background': '#050508',                      // match page bg
    'editor.foreground': '#cbd5e1',                      // light gray text
    'editor.lineHighlightBackground': '#0a0614',
    'editor.selectionBackground': '#1a1628',
    'editorLineNumber.foreground': '#64748b',
    'editorLineNumber.activeForeground': '#cbd5e1',
    'editorCursor.foreground': '#00e5ff',                // cyan cursor
    'editor.inactiveSelectionBackground': '#0f0a1a',
    'editorIndentGuide.background': '#1a1628',
    'editorIndentGuide.activeBackground': '#2d2640',
    'editorGutter.background': '#050508',
    'minimap.background': '#050508',
    'scrollbarSlider.background': '#1a162880',
    'scrollbarSlider.hoverBackground': '#2d264080',
    'scrollbarSlider.activeBackground': '#3d3650',
    'editorWidget.background': '#0a0614',
    'editorWidget.border': '#1a1628',
    'editorSuggestWidget.background': '#0a0614',
    'editorSuggestWidget.border': '#1a1628',
    'editorSuggestWidget.selectedBackground': '#1a1628',
    'editorHoverWidget.background': '#0a0614',
    'editorHoverWidget.border': '#1a1628',
  },
};

/**
 * Configure Monaco with Studio theme
 * Use this as the `beforeMount` prop on Monaco Editor components
 *
 * @example
 * <Editor beforeMount={configureMonacoTheme} theme="studio-dark" ... />
 */
export function configureMonacoTheme(monaco) {
  monaco.editor.defineTheme(STUDIO_THEME_NAME, studioThemeDefinition);
}

/**
 * Standard Monaco editor options for Studio
 * Override as needed for specific use cases
 */
export const studioEditorOptions = {
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
  padding: { top: 8, bottom: 8 },
  smoothScrolling: true,
  cursorBlinking: 'smooth',
  cursorSmoothCaretAnimation: 'on',
};
