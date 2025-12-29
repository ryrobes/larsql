import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { studioDarkPrismTheme } from '../../styles/studioPrismTheme';
import './CodeSection.css';

/**
 * CodeSection - Display code with syntax highlighting and optional diff view
 *
 * Supports:
 * - Syntax highlighting for multiple languages
 * - Line numbers
 * - Line highlighting
 * - Side-by-side or unified diff view
 */
function CodeSection({ spec }) {
  const {
    content,
    language,
    line_numbers = true,
    highlight_lines = [],
    max_height = 400,
    wrap_lines = false,
    diff_with,
    diff_mode = 'split',
    label,
    diff_label
  } = spec;

  // Detect language if not specified
  const detectLanguage = (code) => {
    if (!code) return 'text';
    const firstLine = code.trim().split('\n')[0];

    if (firstLine.startsWith('def ') || firstLine.startsWith('import ') || firstLine.startsWith('class ')) {
      return 'python';
    }
    if (firstLine.startsWith('function ') || firstLine.startsWith('const ') || firstLine.startsWith('let ')) {
      return 'javascript';
    }
    if (firstLine.startsWith('{') || firstLine.startsWith('[')) {
      return 'json';
    }
    if (firstLine.startsWith('<!DOCTYPE') || firstLine.startsWith('<html')) {
      return 'html';
    }
    if (firstLine.includes('{') && firstLine.includes(':')) {
      return 'css';
    }

    return 'text';
  };

  const lang = language || detectLanguage(content);

  // Render code with highlighting
  const renderCode = (code, isHighlighted = false) => (
    <SyntaxHighlighter
      language={lang}
      style={studioDarkPrismTheme}
      showLineNumbers={line_numbers}
      wrapLines={true}
      wrapLongLines={wrap_lines}
      lineProps={(lineNumber) => {
        const style = { display: 'block' };
        if (highlight_lines.includes(lineNumber)) {
          style.backgroundColor = 'rgba(167, 139, 250, 0.2)';
        }
        return { style };
      }}
      customStyle={{
        margin: 0,
        borderRadius: '8px',
        maxHeight: max_height,
        fontSize: '0.85rem'
      }}
    >
      {code}
    </SyntaxHighlighter>
  );

  // Render diff view
  if (diff_with) {
    if (diff_mode === 'split') {
      return (
        <div className="ui-section code-section diff-view split">
          <div className="diff-pane">
            {diff_label && <div className="pane-label">{diff_label}</div>}
            <div className="code-wrapper" style={{ maxHeight: max_height }}>
              {renderCode(diff_with)}
            </div>
          </div>
          <div className="diff-pane">
            {label && <div className="pane-label">{label}</div>}
            <div className="code-wrapper" style={{ maxHeight: max_height }}>
              {renderCode(content)}
            </div>
          </div>
        </div>
      );
    } else {
      // Unified diff view
      const unifiedDiff = createUnifiedDiff(diff_with, content);
      return (
        <div className="ui-section code-section diff-view unified">
          <div className="diff-header">
            <span className="removed-label">{diff_label || 'Before'}</span>
            <span className="arrow">→</span>
            <span className="added-label">{label || 'After'}</span>
          </div>
          <div className="code-wrapper" style={{ maxHeight: max_height }}>
            <pre className="unified-diff">
              {unifiedDiff.map((line, idx) => (
                <div
                  key={idx}
                  className={`diff-line ${line.type}`}
                >
                  <span className="diff-indicator">
                    {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
                  </span>
                  <span className="diff-content">{line.content}</span>
                </div>
              ))}
            </pre>
          </div>
        </div>
      );
    }
  }

  // Regular code view
  return (
    <div className="ui-section code-section">
      {label && <div className="code-label">{label}</div>}
      <div className="code-wrapper" style={{ maxHeight: max_height }}>
        {renderCode(content)}
      </div>
    </div>
  );
}

// Simple diff algorithm for unified view
function createUnifiedDiff(before, after) {
  const beforeLines = before.split('\n');
  const afterLines = after.split('\n');
  const result = [];

  // Very simple line-by-line diff (not a real diff algorithm)
  const maxLines = Math.max(beforeLines.length, afterLines.length);

  for (let i = 0; i < maxLines; i++) {
    const beforeLine = beforeLines[i];
    const afterLine = afterLines[i];

    if (beforeLine === afterLine) {
      result.push({ type: 'unchanged', content: beforeLine || '' });
    } else {
      if (beforeLine !== undefined) {
        result.push({ type: 'removed', content: beforeLine });
      }
      if (afterLine !== undefined) {
        result.push({ type: 'added', content: afterLine });
      }
    }
  }

  return result;
}

export default CodeSection;
