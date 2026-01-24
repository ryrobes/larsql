/**
 * Parse --- PANEL metadata from SQL editor content (frontend version)
 *
 * This mirrors the backend parse_multi_panel_query() but runs in the browser
 * to show panel layout BEFORE executing queries.
 */

/**
 * Extract panel metadata from SQL editor content
 *
 * @param {string} sql - Full SQL text from editor
 * @returns {Array<{name, position, line, query}>} Panel metadata
 */
export function parsePanelMetadata(sql) {
  if (!sql) return [];

  const panels = [];
  const lines = sql.split('\n');

  // Pattern: --- PANEL 'name' (col, row, colspan, rowspan) ON_SELECT ... HIDE_BORDER HIDE_TITLE etc.
  const panelPattern = /^---\s*PANEL\s+['"]([^'"]+)['"](?:\s*\((\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?\))?/i;

  let currentPanel = null;
  let currentPanelStartLine = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const match = line.match(panelPattern);

    if (match) {
      // Save previous panel if exists
      if (currentPanel) {
        panels.push({
          ...currentPanel,
          endLine: i,
        });
      } else {
        // First panel found - lines before this are "setup SQL"
        // Store how many setup lines exist
        currentPanelStartLine = i;
      }

      // Parse new panel
      const name = match[1];
      const col = match[2] ? parseInt(match[2]) : null;
      const row = match[3] ? parseInt(match[3]) : null;
      const colspan = match[4] ? parseInt(match[4]) : 1;
      const rowspan = match[5] ? parseInt(match[5]) : 1;

      currentPanel = {
        name,
        position: (col !== null && row !== null) ? { col, row, colspan, rowspan } : null,
        startLine: i + 1, // Next line after marker
        hideBorder: line.toUpperCase().includes('HIDE_BORDER'),
        hideTitle: line.toUpperCase().includes('HIDE_TITLE'),
        hasOnSelect: line.toUpperCase().includes('ON_SELECT'),
        isBackground: col === 0 && row === 0, // Background panels at (0,0)
      };
    }
  }

  // Save last panel
  if (currentPanel) {
    panels.push({
      ...currentPanel,
      endLine: lines.length,
    });
  }

  // Add metadata about setup SQL
  const hasSetup = currentPanelStartLine > 0;
  const setupLineCount = hasSetup ? currentPanelStartLine : 0;

  return {
    panels,
    hasSetup,
    setupLineCount,
  };
}

/**
 * Generate grid layout from panel metadata
 *
 * @param {Array} panels - Panel metadata from parsePanelMetadata()
 * @returns {Object} Grid layout config {maxCols, maxRows, panels: [...]}
 */
export function generateGridLayout(panels) {
  if (!panels || panels.length === 0) {
    return null;
  }

  // Calculate grid dimensions
  let maxCol = 0;
  let maxRow = 0;

  panels.forEach(panel => {
    if (panel.position) {
      const { col, row, colspan = 1, rowspan = 1 } = panel.position;
      maxCol = Math.max(maxCol, col + colspan - 1);
      maxRow = Math.max(maxRow, row + rowspan - 1);
    }
  });

  return {
    maxCols: maxCol || 2,
    maxRows: maxRow || Math.ceil(panels.length / 2),
    panels: panels.map(p => ({
      name: p.name,
      position: p.position || { col: 1, row: 1, colspan: 1, rowspan: 1 },
      hideBorder: p.hideBorder,
      hideTitle: p.hideTitle,
      startLine: p.startLine,
      endLine: p.endLine,
    })),
  };
}
