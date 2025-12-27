/**
 * Studio Dark Theme for React Syntax Highlighter (Prism)
 * Matches Monaco Studio Theme exactly
 *
 * Colors sourced from: dashboard/frontend/src/studio/utils/monacoTheme.js
 *
 * Palette:
 * - Keywords: #f472b6 (pink)
 * - Strings: #a78bfa (purple)
 * - Numbers: #34d399 (green)
 * - Comments: #64748b (slate gray)
 * - Functions: #00e5ff (cyan)
 * - Background: #050508 (pure black)
 */
export const studioDarkPrismTheme = {
  'code[class*="language-"]': {
    color: '#cbd5e1',              // Light gray text
    background: '#050508',         // Pure black (match Studio)
    textShadow: 'none',
    fontFamily: "'Google Sans Code', 'Menlo', 'Monaco', 'Consolas', monospace",
    fontSize: '13px',              // Larger font size
    textAlign: 'left',
    whiteSpace: 'pre',
    wordSpacing: 'normal',
    wordBreak: 'normal',
    wordWrap: 'normal',
    lineHeight: '1.6',
    tabSize: '2',
    hyphens: 'none',
  },
  'pre[class*="language-"]': {
    color: '#cbd5e1',
    background: '#050508',
    textShadow: 'none',
    fontFamily: "'Google Sans Code', 'Menlo', 'Monaco', 'Consolas', monospace",
    fontSize: '13px',              // Larger font size
    textAlign: 'left',
    whiteSpace: 'pre',
    wordSpacing: 'normal',
    wordBreak: 'normal',
    wordWrap: 'normal',
    lineHeight: '1.6',
    tabSize: '2',
    hyphens: 'none',
    padding: '1em',
    margin: '1em 0',
    overflow: 'auto',
    borderRadius: '6px',
    border: '1px solid #1a1628',
  },

  // Comments - slate gray italic
  'comment': { color: '#64748b', fontStyle: 'italic' },
  'prolog': { color: '#64748b', fontStyle: 'italic' },
  'doctype': { color: '#64748b', fontStyle: 'italic' },
  'cdata': { color: '#64748b', fontStyle: 'italic' },

  // Keywords - pink
  'keyword': { color: '#f472b6' },
  'selector': { color: '#f472b6' },
  'important': { color: '#f472b6', fontWeight: 'bold' },
  'atrule': { color: '#f472b6' },

  // Strings - purple
  'string': { color: '#a78bfa' },
  'char': { color: '#a78bfa' },
  'attr-value': { color: '#a78bfa' },
  'regex': { color: '#a78bfa' },
  'variable': { color: '#a78bfa' },

  // Numbers - green
  'number': { color: '#34d399' },
  'boolean': { color: '#34d399' },
  'constant': { color: '#34d399' },

  // Functions/Methods - cyan
  'function': { color: '#00e5ff' },
  'class-name': { color: '#00e5ff' },
  'builtin': { color: '#00e5ff' },

  // Properties/Attributes - cyan
  'property': { color: '#00e5ff' },
  'attr-name': { color: '#00e5ff' },
  'tag': { color: '#00e5ff' },

  // Operators - light gray
  'operator': { color: '#cbd5e1' },
  'entity': { color: '#cbd5e1' },
  'url': { color: '#cbd5e1' },

  // Punctuation - muted
  'punctuation': { color: '#94a3b8' },

  // Deleted/Inserted (for diffs)
  'deleted': { color: '#f87171' },
  'inserted': { color: '#34d399' },

  // Special
  'symbol': { color: '#fbbf24' },       // yellow
  'namespace': { color: '#00e5ff' },
};
