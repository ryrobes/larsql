import React, { useState } from 'react';
import Editor from '@monaco-editor/react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js/dist/plotly';
import RichMarkdown from '../../../components/RichMarkdown';
import AnsiRenderer from '../../../components/AnsiRenderer';
import { Modal } from '../../../components';
import { configureMonacoTheme, STUDIO_THEME_NAME } from '../../utils/monacoTheme';

// Create Plot component
const Plot = createPlotlyComponent(Plotly);

/**
 * Detect if string content looks like markdown
 *
 * Checks for common markdown patterns:
 * - Headers (# ## ###)
 * - Bold/italic (**text** or *text*)
 * - Lists (- or * or 1.)
 * - Links ([text](url))
 * - Code blocks (``` or ~~~)
 * - Blockquotes (>)
 * - Tables (|)
 */
function isMarkdown(text) {
  if (!text || typeof text !== 'string') return false;

  // Ignore very short strings (likely not markdown)
  if (text.trim().length < 20) return false;

  const markdownPatterns = [
    /^#{1,6}\s+.+$/m,           // Headers: # Header
    /\*\*.+\*\*/,                // Bold: **text**
    /\*.+\*/,                    // Italic: *text*
    /^[-*+]\s+.+$/m,             // Unordered lists: - item
    /^\d+\.\s+.+$/m,             // Ordered lists: 1. item
    /\[.+\]\(.+\)/,              // Links: [text](url)
    /^```/m,                     // Code blocks: ```
    /^~~~/m,                     // Alt code blocks: ~~~
    /^>\s+.+$/m,                 // Blockquotes: > quote
    /\|.+\|/,                    // Tables: | cell |
  ];

  // Count how many patterns match
  let matches = 0;
  for (const pattern of markdownPatterns) {
    if (pattern.test(text)) {
      matches++;
    }
  }

  // If 2+ markdown patterns detected, treat as markdown
  return matches >= 2;
}

/**
 * Detect if string content contains ANSI escape codes
 *
 * Checks for ANSI escape sequences like:
 * - Color codes: \x1b[31m (red), \x1b[0m (reset)
 * - Cursor movement: \x1b[2J, \x1b[H
 * - Text formatting: \x1b[1m (bold), \x1b[4m (underline)
 */
function isAnsi(text) {
  if (!text || typeof text !== 'string') return false;

  // ANSI escape sequence patterns
  // Check both actual escape characters AND escaped string representations
  // eslint-disable-next-line no-control-regex -- intentional ANSI escape sequence parsing
  const ansiPatterns = [
    /\x1b\[[0-9;]*m/,                // Color/format codes: \x1b[31m (actual escape)
    /\u001b\[[0-9;]*m/,              // Unicode variant: \u001b[31m (actual escape)
    /\x1b\[[0-9;]*[A-HJKSTfmsu]/,   // Cursor/erase codes (actual escape)
    /\\x1b\[[0-9;]*m/,               // Escaped string: "\\x1b[31m"
    /\\u001b\[[0-9;]*m/,             // Escaped unicode: "\\u001b[31m"
    /\\033\[[0-9;]*m/,               // Escaped octal: "\\033[31m"
  ];

  // Check if any ANSI pattern exists
  const hasAnsi = ansiPatterns.some(pattern => pattern.test(text));

  // Debug logging
  if (hasAnsi) {
    console.log('[isAnsi] Detected ANSI in text (first 100 chars):', text.substring(0, 100));
    console.log('[isAnsi] Has actual \\x1b?', text.includes('\x1b'));
    console.log('[isAnsi] Has escaped \\\\x1b?', text.includes('\\x1b'));
  }

  return hasAnsi;
}

// Dark AG Grid theme - pure black with purple undertones
const detailGridTheme = themeQuartz.withParams({
  backgroundColor: '#000000',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0a0510',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#050410',
  borderColor: '#1a1628',
  rowBorder: true,
  headerFontSize: 11,
  fontFamily: "'Google Sans Code', monospace",
  fontSize: 12,
  accentColor: '#00e5ff',
});

/**
 * ResultRenderer - Displays cell execution results
 *
 * Handles multiple result types:
 * - Errors
 * - Plain text (LLM output)
 * - Images (matplotlib, PIL, from metadata_json)
 * - Plotly charts
 * - DataFrames (tables)
 * - JSON objects
 * - LLM lineage output (legacy)
 *
 * NOTE: This component contains brittle type detection logic.
 * Extracted as-is for separation. Internals should be refactored later.
 */
const ResultRenderer = ({ result, error, images }) => {
  // Image modal state
  const [modalImage, setModalImage] = useState(null);
  // Prepare data for AG Grid
  const gridColumnDefs = React.useMemo(() => {
    if (!result?.columns) return [];
    return result.columns.map((col) => ({
      field: col,
      headerName: col,
      sortable: true,
      filter: true,
      resizable: true,
      minWidth: 80,
      flex: 1,
    }));
  }, [result?.columns]);

  const gridRowData = React.useMemo(() => result?.rows || [], [result?.rows]);

  // === Render logic ===

  // Debug
  React.useEffect(() => {
    console.log('[ResultRenderer] result type:', typeof result);
    console.log('[ResultRenderer] has rows?', result?.rows);
    console.log('[ResultRenderer] has columns?', result?.columns);
    console.log('[ResultRenderer] result:', result);
  }, [result]);

  if (error) {
    // Convert \n to actual newlines if error is a string
    const errorText = typeof error === 'string'
      ? error.replace(/\\n/g, '\n')
      : JSON.stringify(error, null, 2);

    return (
      <div className="cell-detail-error">
        <span className="cell-detail-error-label">Error:</span>
        <pre className="cell-detail-error-message">{errorText}</pre>
      </div>
    );
  }

  // Images from metadata_json (check FIRST before other types)
  if (images && images.length > 0) {
    return (
      <>
        <div className="cell-detail-images">
          {images.map((rawImagePath, idx) => {
            // Guard against non-string imagePath
            const imagePath = typeof rawImagePath === 'string' ? rawImagePath : '';
            if (!imagePath) return null;

            // imagePath is like: "/api/images/shy-pika-4e58df/riverflow_v2_max_preview/image_0.png"
            const imageUrl = imagePath.startsWith('http')
              ? imagePath
              : `http://localhost:5050${imagePath}`;

            return (
              <div key={idx} className="cell-detail-image">
                <img
                  src={imageUrl}
                  alt={`Output ${idx + 1}`}
                  style={{ maxWidth: '100%', height: 'auto', borderRadius: '4px', cursor: 'pointer' }}
                  onClick={() => setModalImage({ url: imageUrl, path: imagePath })}
                  title="Click to view full size"
                  onError={(e) => {
                    console.error('[ResultRenderer] Image load failed:', imageUrl);
                    e.target.style.display = 'none';
                  }}
                />
              </div>
            );
          })}
          {/* Also show result data if present */}
          {result && (
            <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
              <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px' }}>
                Additional Output:
              </div>
              {typeof result === 'string' && <pre style={{ fontSize: '12px', color: '#cbd5e1' }}>{result}</pre>}
              {typeof result === 'object' && result?.rows && (
                <div style={{ fontSize: '11px', color: '#888' }}>
                  {result.rows.length} rows returned
                </div>
              )}
            </div>
          )}
        </div>

        {/* Image Modal */}
        <Modal
          isOpen={!!modalImage}
          onClose={() => setModalImage(null)}
          size="full"
          closeOnBackdrop={true}
          closeOnEscape={true}
          className="result-image-modal"
        >
          {modalImage && (
            <div className="result-modal-image-container">
              <div className="result-modal-image-header">
                <span className="result-modal-image-title">{modalImage.path}</span>
              </div>
              <div className="result-modal-image-body">
                <img
                  src={modalImage.url}
                  alt="Full size"
                  className="result-modal-image"
                  onClick={() => setModalImage(null)}
                />
              </div>
            </div>
          )}
        </Modal>
      </>
    );
  }

  // DataFrame result (SQL/Python tables) - CHECK FIRST before string check
  if (result?.rows && result?.columns) {
    return (
      <div className="cell-detail-grid">
        <AgGridReact
          rowData={gridRowData}
          columnDefs={gridColumnDefs}
          theme={detailGridTheme}
          animateRows={false}
          enableCellTextSelection={true}
          headerHeight={36}
          rowHeight={28}
        />
      </div>
    );
  }

  // String result (LLM output from standard execution)
  if (typeof result === 'string') {
    // Check for ANSI FIRST (before markdown)
    // This is important because ANSI output might contain # or * characters
    // that could trigger markdown detection
    const isAnsiContent = isAnsi(result);

    if (isAnsiContent) {
      return (
        <div className="cell-detail-ansi">
          <AnsiRenderer>{result}</AnsiRenderer>
        </div>
      );
    }

    // Then check for markdown
    const isMarkdownContent = isMarkdown(result);

    if (isMarkdownContent) {
      return (
        <div className="cell-detail-markdown">
          <RichMarkdown>{result}</RichMarkdown>
        </div>
      );
    }

    // Fallback: Plain text - show in editor
    return (
      <div className="cell-detail-text">
        <Editor
          height="100%"
          language="markdown"
          value={result}
          theme={STUDIO_THEME_NAME}
          beforeMount={configureMonacoTheme}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            fontFamily: "'Google Sans Code', monospace",
            lineNumbers: 'off',
            renderLineHighlightOnlyWhenFocus: true,
            wordWrap: 'on',
            padding: { top: 12, bottom: 12 },
          }}
        />
      </div>
    );
  }

  // Image result (matplotlib, PIL)
  if (result?.type === 'image' && (result?.api_url || result?.base64)) {
    const imageUrl = result.api_url || `data:image/${result.format || 'png'};base64,${result.base64}`;
    const imageName = result.content || 'Generated output';

    return (
      <>
        <div className="cell-detail-image">
          <img
            src={imageUrl}
            alt={imageName}
            style={{ maxWidth: '100%', height: 'auto', cursor: 'pointer' }}
            onClick={() => setModalImage({ url: imageUrl, path: imageName })}
            title="Click to view full size"
          />
          {result.width && result.height && (
            <div className="cell-detail-image-info">
              {result.width} × {result.height}
            </div>
          )}
        </div>

        {/* Image Modal */}
        <Modal
          isOpen={!!modalImage}
          onClose={() => setModalImage(null)}
          size="full"
          closeOnBackdrop={true}
          closeOnEscape={true}
          className="result-image-modal"
        >
          {modalImage && (
            <div className="result-modal-image-container">
              <div className="result-modal-image-header">
                <span className="result-modal-image-title">{modalImage.path}</span>
              </div>
              <div className="result-modal-image-body">
                <img
                  src={modalImage.url}
                  alt="Full size"
                  className="result-modal-image"
                  onClick={() => setModalImage(null)}
                />
              </div>
            </div>
          )}
        </Modal>
      </>
    );
  }

  // Plotly chart result
  if (result?.type === 'plotly' && result?.data) {
    return (
      <div className="cell-detail-plotly">
        <Plot
          data={JSON.parse(JSON.stringify(result.data))}
          layout={{
            ...JSON.parse(JSON.stringify(result.layout || {})),
            paper_bgcolor: '#000000',
            plot_bgcolor: '#000000',
            font: { color: '#cbd5e1' },
            xaxis: { gridcolor: '#1a1628', zerolinecolor: '#1a1628' },
            yaxis: { gridcolor: '#1a1628', zerolinecolor: '#1a1628' },
          }}
          config={{ responsive: true, displayModeBar: true }}
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    );
  }


  // Native browser tool result (has images as base64 data URLs)
  // Detect: success field + images array with base64 or data URL strings
  if (result?.success !== undefined && Array.isArray(result?.images)) {
    const browserImages = result.images || [];
    const domSnapshots = result.dom_snapshots || [];
    const domCoords = result.dom_coords || [];
    const sessionId = result.session_id;
    const url = result.url;
    const videoPath = result.video;
    const conversationHistory = result.conversation_history || [];

    return (
      <div className="cell-detail-browser-result">
        {/* Header with session info */}
        <div className="browser-result-header">
          {sessionId && (
            <div className="browser-result-info">
              <span className="browser-result-label">Session:</span>
              <span className="browser-result-value">{sessionId}</span>
            </div>
          )}
          {url && (
            <div className="browser-result-info">
              <span className="browser-result-label">URL:</span>
              <a href={url} target="_blank" rel="noopener noreferrer" className="browser-result-link">
                {url}
              </a>
            </div>
          )}
          <div className="browser-result-info">
            <span className="browser-result-label">Status:</span>
            <span className="browser-result-value" style={{ color: result.success ? '#34d399' : '#f87171' }}>
              {result.success ? 'Success' : 'Failed'}
            </span>
          </div>
        </div>

        {/* Images Grid - base64 data URLs */}
        {browserImages.length > 0 && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">Screenshots ({browserImages.length})</h4>
            <div className="browser-result-thumbnails">
              {browserImages.map((imageData, idx) => {
                // imageData is a base64 data URL like "data:image/jpeg;base64,..."
                const isDataUrl = typeof imageData === 'string' && imageData.startsWith('data:');
                const imageUrl = isDataUrl ? imageData : `http://localhost:5050${imageData}`;
                return (
                  <div
                    key={idx}
                    className="browser-result-thumbnail"
                    onClick={() => setModalImage({ url: imageUrl, path: `Screenshot ${idx + 1}` })}
                    title={`Screenshot ${idx + 1}`}
                  >
                    <img src={imageUrl} alt={`Screenshot ${idx + 1}`} />
                    <span className="browser-result-thumbnail-label">Screenshot {idx + 1}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* DOM Snapshots - shown as expandable sections */}
        {domSnapshots.length > 0 && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">DOM Snapshots ({domSnapshots.length})</h4>
            <div className="browser-result-dom-snapshots">
              {domSnapshots.map((snapshot, idx) => (
                <details key={idx} className="browser-result-dom-detail">
                  <summary>DOM Snapshot {idx + 1}</summary>
                  <pre className="browser-result-dom-content">{snapshot}</pre>
                </details>
              ))}
            </div>
          </div>
        )}

        {/* Video */}
        {videoPath && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">Video Recording</h4>
            <a
              href={`http://localhost:5050/api/browser-media/${videoPath}`}
              target="_blank"
              rel="noopener noreferrer"
              className="browser-result-video-link"
            >
              Download Video
            </a>
          </div>
        )}

        {/* Image Modal */}
        <Modal
          isOpen={!!modalImage}
          onClose={() => setModalImage(null)}
          size="full"
          closeOnBackdrop={true}
          closeOnEscape={true}
          className="result-image-modal"
        >
          {modalImage && (
            <div className="result-modal-image-container">
              <div className="result-modal-image-header">
                <span className="result-modal-image-title">{modalImage.path}</span>
              </div>
              <div className="result-modal-image-body">
                <img
                  src={modalImage.url}
                  alt="Full size"
                  className="result-modal-image"
                  onClick={() => setModalImage(null)}
                />
              </div>
            </div>
          )}
        </Modal>
      </div>
    );
  }

  // Legacy browser batch result (rabbitize/lars browser batch with file paths)
  if (result?.screenshots || result?.dom_snapshots || result?.artifacts?.basePath) {
    const screenshots = result.screenshots || [];
    const domSnapshots = result.dom_snapshots || [];
    const videoPath = result.video_path;
    const sessionId = result.session_id;
    const clientId = result.client_id;
    const testId = result.test_id;

    return (
      <div className="cell-detail-browser-result">
        {/* Header with session info */}
        <div className="browser-result-header">
          <div className="browser-result-info">
            <span className="browser-result-label">Session:</span>
            <span className="browser-result-value">{sessionId}</span>
          </div>
          {result.url && (
            <div className="browser-result-info">
              <span className="browser-result-label">URL:</span>
              <a href={result.url} target="_blank" rel="noopener noreferrer" className="browser-result-link">
                {result.url}
              </a>
            </div>
          )}
          <div className="browser-result-info">
            <span className="browser-result-label">Commands:</span>
            <span className="browser-result-value">{result.command_count || 0}</span>
          </div>
        </div>

        {/* Screenshots Grid */}
        {screenshots.length > 0 && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">Screenshots ({screenshots.length})</h4>
            <div className="browser-result-thumbnails">
              {screenshots.map((screenshot, idx) => {
                const imageUrl = screenshot.path
                  ? `http://localhost:5050/api/browser-media/${screenshot.path}`
                  : screenshot.full_path;
                return (
                  <div
                    key={idx}
                    className="browser-result-thumbnail"
                    onClick={() => setModalImage({ url: imageUrl, path: screenshot.name })}
                    title={screenshot.name}
                  >
                    <img src={imageUrl} alt={screenshot.name} />
                    <span className="browser-result-thumbnail-label">{screenshot.name}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* DOM Snapshots */}
        {domSnapshots.length > 0 && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">DOM Snapshots ({domSnapshots.length})</h4>
            <div className="browser-result-pills">
              {domSnapshots.map((snapshot, idx) => (
                <a
                  key={idx}
                  href={`http://localhost:5050/api/browser-media/${snapshot.path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="browser-result-pill"
                  title={snapshot.name}
                >
                  {snapshot.name}
                </a>
              ))}
            </div>
          </div>
        )}

        {/* Video */}
        {videoPath && (
          <div className="browser-result-section">
            <h4 className="browser-result-section-title">Video Recording</h4>
            <a
              href={`http://localhost:5050/api/browser-media/${videoPath}`}
              target="_blank"
              rel="noopener noreferrer"
              className="browser-result-video-link"
            >
              Download Video
            </a>
          </div>
        )}

        {/* Image Modal */}
        <Modal
          isOpen={!!modalImage}
          onClose={() => setModalImage(null)}
          size="full"
          closeOnBackdrop={true}
          closeOnEscape={true}
          className="result-image-modal"
        >
          {modalImage && (
            <div className="result-modal-image-container">
              <div className="result-modal-image-header">
                <span className="result-modal-image-title">{modalImage.path}</span>
              </div>
              <div className="result-modal-image-body">
                <img
                  src={modalImage.url}
                  alt="Full size"
                  className="result-modal-image"
                  onClick={() => setModalImage(null)}
                />
              </div>
            </div>
          )}
        </Modal>
      </div>
    );
  }

  // LLM output from lineage (legacy API)
  if (result?.result?.lineage?.[0]?.output) {
    const llmOutput = result.result.lineage[0].output;
    const outputString = typeof llmOutput === 'string'
      ? llmOutput
      : JSON.stringify(llmOutput, null, 2);

    const isMarkdownContent = isMarkdown(outputString);

    if (isMarkdownContent) {
      return (
        <div className="cell-detail-markdown">
          <RichMarkdown>{outputString}</RichMarkdown>
        </div>
      );
    }

    return (
      <div className="cell-detail-text">
        <Editor
          height="100%"
          language="markdown"
          value={outputString}
          theme={STUDIO_THEME_NAME}
          beforeMount={configureMonacoTheme}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            fontFamily: "'Google Sans Code', monospace",
            lineNumbers: 'off',
            renderLineHighlightOnlyWhenFocus: true,
            wordWrap: 'on',
            padding: { top: 12, bottom: 12 },
          }}
        />
      </div>
    );
  }

  // Generic JSON result (fallback)
  if (result?.result !== undefined) {
    return (
      <div className="cell-detail-json">
        <Editor
          height="100%"
          language="json"
          value={JSON.stringify(result.result, null, 2)}
          theme={STUDIO_THEME_NAME}
          beforeMount={configureMonacoTheme}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            fontFamily: "'Google Sans Code', monospace",
            lineNumbers: 'off',
            renderLineHighlightOnlyWhenFocus: true,
            wordWrap: 'on',
          }}
        />
      </div>
    );
  }

  // No result
  return null;
};

export default ResultRenderer;
