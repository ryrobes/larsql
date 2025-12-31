import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import useWorkshopStore from '../stores/workshopStore';
import './YamlPanel.css';

/**
 * YamlPanel - Read-only YAML preview panel
 *
 * Shows the current cascade state as YAML with:
 * - Syntax highlighting (basic)
 * - Copy button
 * - Line numbers
 *
 * Cell 6 will add Monaco for proper editing and bidirectional sync.
 */
function YamlPanel() {
  const { exportToYaml, toggleYamlPanel } = useWorkshopStore();

  const yamlContent = useMemo(() => {
    try {
      return exportToYaml();
    } catch (e) {
      return `# Error generating YAML\n# ${e.message}`;
    }
  }, [exportToYaml]);

  const handleCopy = () => {
    navigator.clipboard.writeText(yamlContent).then(() => {
      // Could show a toast
      console.log('YAML copied');
    });
  };

  // Basic syntax highlighting
  // Order matters! Process in sequence to avoid regex conflicts
  const highlightedLines = useMemo(() => {
    return yamlContent.split('\n').map((line, idx) => {
      // Comments - escape and return early
      if (line.trim().startsWith('#')) {
        return { num: idx + 1, html: `<span class="yaml-comment">${escapeHtml(line)}</span>` };
      }

      // Escape HTML first for safety
      let escaped = escapeHtml(line);

      // List items (dash)
      escaped = escaped.replace(
        /^(\s*)-\s/,
        '$1<span class="yaml-dash">-</span> '
      );

      // Key-value pairs - use placeholder to avoid conflicts
      escaped = escaped.replace(
        /^(\s*)([a-zA-Z_][a-zA-Z0-9_]*):/,
        '$1<span class="yaml-key">$2</span>:'
      );

      // Strings in quotes (only match actual YAML string values, not inside tags)
      // Match quotes that appear after : or at start of value
      escaped = escaped.replace(
        /: (&quot;[^&]*&quot;)/g,
        ': <span class="yaml-string">$1</span>'
      );

      // Numbers (at end of line after colon)
      escaped = escaped.replace(
        /: (\d+)(\s*)$/,
        ': <span class="yaml-number">$1</span>$2'
      );

      // Booleans
      escaped = escaped.replace(
        /: (true|false)(\s*)$/i,
        ': <span class="yaml-boolean">$1</span>$2'
      );

      return { num: idx + 1, html: escaped };
    });
  }, [yamlContent]);

  return (
    <div className="yaml-panel">
      <div className="yaml-header">
        <div className="yaml-header-left">
          <Icon icon="mdi:code-braces" width="16" />
          <span>YAML Preview</span>
        </div>
        <div className="yaml-header-right">
          <button className="yaml-btn" onClick={handleCopy} title="Copy YAML">
            <Icon icon="mdi:content-copy" width="16" />
          </button>
          <button className="yaml-btn" onClick={toggleYamlPanel} title="Close">
            <Icon icon="mdi:close" width="16" />
          </button>
        </div>
      </div>

      <div className="yaml-content">
        <pre className="yaml-code">
          {highlightedLines.map((line) => (
            <div key={line.num} className="yaml-line">
              <span className="line-number">{line.num}</span>
              <span
                className="line-content"
                dangerouslySetInnerHTML={{ __html: line.html }}
              />
            </div>
          ))}
        </pre>
      </div>

      <div className="yaml-footer">
        <span className="yaml-stats">
          {yamlContent.split('\n').length} lines
        </span>
      </div>
    </div>
  );
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export default YamlPanel;
