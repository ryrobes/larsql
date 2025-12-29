/**
 * Shared Monaco theme configuration for Studio
 *
 * All Monaco editors in Studio should use this theme for consistency.
 * Import and use `configureMonacoTheme` as the `beforeMount` prop.
 */

export const STUDIO_THEME_NAME = 'studio-dark';

// Track if we've already set up font loading
let fontLoadingInitialized = false;

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

// Store monaco reference for remeasureFonts
let monacoInstance = null;

/**
 * Configure Monaco with Studio theme
 * Use this as the `beforeMount` prop on Monaco Editor components
 *
 * @example
 * <Editor beforeMount={configureMonacoTheme} theme="studio-dark" ... />
 */
export function configureMonacoTheme(monaco) {
  monacoInstance = monaco;
  monaco.editor.defineTheme(STUDIO_THEME_NAME, studioThemeDefinition);

  // Set up font loading handler (only once)
  if (!fontLoadingInitialized && typeof document !== 'undefined') {
    fontLoadingInitialized = true;

    // Wait for Google Sans Code font to load, then tell Monaco to remeasure
    document.fonts.ready.then(() => {
      // Check if our font is loaded
      if (document.fonts.check("12px 'Google Sans Code'")) {
        monaco.editor.remeasureFonts();
      } else {
        // Font not loaded yet, wait for it
        document.fonts.load("12px 'Google Sans Code'").then(() => {
          monaco.editor.remeasureFonts();
        }).catch(() => {
          // Font failed to load, Monaco will use fallback
          console.warn('[Monaco] Google Sans Code font failed to load, using fallback');
        });
      }
    });
  }
}

/**
 * Call this after editor mounts to ensure fonts are applied
 * Use as: onMount={(editor, monaco) => handleEditorMount(editor, monaco)}
 */
export function handleEditorMount(editor, monaco) {
  // Ensure fonts are measured after editor is ready
  if (typeof document !== 'undefined' && document.fonts) {
    document.fonts.ready.then(() => {
      monaco.editor.remeasureFonts();
    });
  }
}

/**
 * Standard Monaco editor options for Studio
 * Override as needed for specific use cases
 */
export const studioEditorOptions = {
  minimap: { enabled: false },
  fontSize: 12,
  fontFamily: "'Google Sans Code', 'Menlo', monospace",
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
