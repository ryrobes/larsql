import React from 'react';
import Editor from '@monaco-editor/react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js/dist/plotly';

// Create Plot component
const Plot = createPlotlyComponent(Plotly);

// Dark AG Grid theme
const detailGridTheme = themeQuartz.withParams({
  backgroundColor: '#080c12',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0b1219',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#0a0e14',
  borderColor: '#1a2028',
  rowBorder: true,
  headerFontSize: 11,
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 12,
  accentColor: '#2dd4bf',
});

/**
 * ResultRenderer - Displays phase execution results
 *
 * Handles multiple result types:
 * - Errors
 * - Plain text (LLM output)
 * - Images (matplotlib, PIL)
 * - Plotly charts
 * - DataFrames (tables)
 * - JSON objects
 * - LLM lineage output (legacy)
 *
 * NOTE: This component contains brittle type detection logic.
 * Extracted as-is for separation. Internals should be refactored later.
 */
const ResultRenderer = ({ result, error, handleMonacoBeforeMount }) => {
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
    return (
      <div className="phase-detail-error">
        <span className="phase-detail-error-label">Error:</span>
        <pre className="phase-detail-error-message">{error}</pre>
      </div>
    );
  }

  // DataFrame result (SQL/Python tables) - CHECK FIRST before string check
  if (result?.rows && result?.columns) {
    return (
      <div className="phase-detail-grid">
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
    return (
      <div className="phase-detail-text">
        <Editor
          height="100%"
          language="markdown"
          value={result}
          theme="detail-dark"
          beforeMount={handleMonacoBeforeMount}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'off',
            wordWrap: 'on',
            padding: { top: 12, bottom: 12 },
          }}
        />
      </div>
    );
  }

  // Image result (matplotlib, PIL)
  if (result?.type === 'image' && (result?.api_url || result?.base64)) {
    return (
      <div className="phase-detail-image">
        <img
          src={result.api_url || `data:image/${result.format || 'png'};base64,${result.base64}`}
          alt={result.content || "Phase output"}
          style={{ maxWidth: '100%', height: 'auto' }}
        />
        {result.width && result.height && (
          <div className="phase-detail-image-info">
            {result.width} × {result.height}
          </div>
        )}
      </div>
    );
  }

  // Plotly chart result
  if (result?.type === 'plotly' && result?.data) {
    return (
      <div className="phase-detail-plotly">
        <Plot
          data={JSON.parse(JSON.stringify(result.data))}
          layout={{
            ...JSON.parse(JSON.stringify(result.layout || {})),
            paper_bgcolor: '#080c12',
            plot_bgcolor: '#080c12',
            font: { color: '#cbd5e1' },
            xaxis: { gridcolor: '#1a2028', zerolinecolor: '#1a2028' },
            yaxis: { gridcolor: '#1a2028', zerolinecolor: '#1a2028' },
          }}
          config={{ responsive: true, displayModeBar: true }}
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    );
  }


  // LLM output from lineage (legacy notebook API)
  if (result?.result?.lineage?.[0]?.output) {
    const llmOutput = result.result.lineage[0].output;
    return (
      <div className="phase-detail-text">
        <Editor
          height="100%"
          language="markdown"
          value={typeof llmOutput === 'string'
            ? llmOutput
            : JSON.stringify(llmOutput, null, 2)}
          theme="detail-dark"
          beforeMount={handleMonacoBeforeMount}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'off',
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
      <div className="phase-detail-json">
        <Editor
          height="100%"
          language="json"
          value={JSON.stringify(result.result, null, 2)}
          theme="detail-dark"
          beforeMount={handleMonacoBeforeMount}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'off',
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
