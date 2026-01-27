/**
 * Parse --- PANEL metadata from SQL editor content (frontend version)
 *
 * This mirrors the backend parse_multi_panel_query() but runs in the browser
 * to show panel layout BEFORE executing queries.
 */

/**
 * Extract param key and field name from an on_select template.
 * Handles both @param_set (single) and @params_set (multi) formats.
 *
 * @param {string} template - e.g., "@param_set('level', level)" or "@params_set('depts', dept)"
 * @returns {Object} { paramKey, selectField } or { paramKey: null, selectField: null }
 */
export function extractParamInfo(template) {
  if (!template) return { paramKey: null, selectField: null };

  // Match @param_set('key', field) or @params_set('key', field) or with * wildcard
  const match = template.match(/@params?_set\(['"]([^'"]+)['"],\s*(\w+|\*)\)/);
  if (match) {
    return { paramKey: match[1], selectField: match[2] };
  }
  return { paramKey: null, selectField: null };
}

/**
 * Extract panel metadata from SQL editor content
 *
 * @param {string} sql - Full SQL text from editor
 * @returns {Object} { panels: Array<{name, position, query, ...}>, hasSetup, setupLineCount, setupSql }
 */
export function parsePanelMetadata(sql) {
  if (!sql) return { panels: [], hasSetup: false, setupLineCount: 0, setupSql: '' };

  const panels = [];
  const lines = sql.split('\n');

  // Pattern: --- PANEL 'name' (col, row, colspan, rowspan) ON_SELECT[] @cascade(...) HIDE_BORDER HIDE_TITLE etc.
  // Groups: 1=name, 2=col, 3=row, 4=colspan, 5=rowspan
  const panelPattern = /^---\s*PANEL\s+['"]([^'"]+)['"](?:\s*\((\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?\))?/i;

  // Pattern for ON_SELECT with optional [] and cascade template
  // Matches: ON_SELECT @param_set('key', field) or ON_SELECT[] @params_set('key', field)
  const onSelectPattern = /ON_SELECT(\[\])?\s+(@\w+\([^)]*\))/i;

  let currentPanel = null;
  let currentPanelQueryLines = [];
  let firstPanelLine = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmedLine = line.trim();
    const match = trimmedLine.match(panelPattern);

    if (match) {
      // Save previous panel if exists
      if (currentPanel) {
        currentPanel.query = currentPanelQueryLines.join('\n').trim();
        currentPanel.endLine = i;
        panels.push(currentPanel);
        currentPanelQueryLines = [];
      }

      if (firstPanelLine === null) {
        firstPanelLine = i;
      }

      // Parse new panel
      const name = match[1];
      const col = match[2] ? parseInt(match[2]) : null;
      const row = match[3] ? parseInt(match[3]) : null;
      const colspan = match[4] ? parseInt(match[4]) : 1;
      const rowspan = match[5] ? parseInt(match[5]) : 1;

      // Parse optional modifiers
      const lineUpper = trimmedLine.toUpperCase();
      const opacityMatch = trimmedLine.match(/OPACITY\(([0-9.]+)\)/i);
      const blurMatch = trimmedLine.match(/BLUR\((\d+(?:px)?)\)/i);

      // Parse ON_SELECT with template
      const onSelectMatch = trimmedLine.match(onSelectPattern);
      const hasOnSelect = !!onSelectMatch;
      const multiSelect = hasOnSelect && !!onSelectMatch[1]; // [1] is the [] group
      const onSelectTemplate = hasOnSelect ? onSelectMatch[2] : null; // [2] is the cascade template

      // Extract param key and select field from template
      const { paramKey, selectField } = extractParamInfo(onSelectTemplate);

      currentPanel = {
        name,
        position: (col !== null && row !== null) ? { col, row, colspan, rowspan } : null,
        startLine: i + 1, // Next line after marker (1-indexed for display)
        lineIndex: i,      // 0-indexed for array access
        hide_border: lineUpper.includes('HIDE_BORDER'),
        hide_title: lineUpper.includes('HIDE_TITLE'),
        hasOnSelect,
        on_select: onSelectTemplate,    // Full template: @param_set('key', field)
        multi_select: multiSelect,       // true if ON_SELECT[]
        param_key: paramKey,             // Extracted param key for lookups
        select_field: selectField,       // Field name to match for selection
        isBackground: col === 0 && row === 0, // Background panels at (0,0)
        opacity: opacityMatch ? parseFloat(opacityMatch[1]) : null,
        blur: blurMatch ? blurMatch[1] : null,
        object_fit: lineUpper.includes('CONTAIN') ? 'contain' :
                    lineUpper.includes('COVER') ? 'cover' : null,
        panelMarkerLine: line, // Full --- PANEL line for hash matching with parseQueries
      };
    } else if (currentPanel) {
      // Collect query lines for current panel
      currentPanelQueryLines.push(line);
    }
  }

  // Save last panel
  if (currentPanel) {
    currentPanel.query = currentPanelQueryLines.join('\n').trim();
    currentPanel.endLine = lines.length;
    panels.push(currentPanel);
  }

  // Extract setup SQL (lines before first panel)
  const hasSetup = firstPanelLine !== null && firstPanelLine > 0;
  const setupLineCount = hasSetup ? firstPanelLine : 0;
  const setupSql = hasSetup ? lines.slice(0, firstPanelLine).join('\n').trim() : '';

  return {
    panels,
    hasSetup,
    setupLineCount,
    setupSql,
  };
}

/**
 * Generate grid layout from panel metadata
 *
 * @param {Array} panels - Panel metadata from parsePanelMetadata()
 * @returns {Object} Grid layout config {cols, rows, panels: [...]}
 */
export function generateGridLayout(panels) {
  if (!panels || panels.length === 0) {
    return null;
  }

  // Separate background panels (position 0,0) from grid panels
  const backgroundPanels = panels.filter(p => p.position?.col === 0 && p.position?.row === 0);
  const gridPanels = panels.filter(p => !(p.position?.col === 0 && p.position?.row === 0));

  // Calculate grid dimensions from positioned panels
  let maxCol = 0;
  let maxRow = 0;

  gridPanels.forEach(panel => {
    if (panel.position) {
      const { col, row, colspan = 1, rowspan = 1 } = panel.position;
      maxCol = Math.max(maxCol, col + colspan - 1);
      maxRow = Math.max(maxRow, row + rowspan - 1);
    }
  });

  // If no positions specified, calculate auto-layout
  const hasPositions = gridPanels.some(p => p.position);
  if (!hasPositions && gridPanels.length > 0) {
    const panelCount = gridPanels.length;
    maxCol = panelCount <= 2 ? Math.max(1, panelCount) : panelCount <= 4 ? 2 : 3;
    maxRow = Math.max(1, Math.ceil(panelCount / maxCol));
  }

  // Assign auto positions to panels without explicit positions
  let autoIndex = 0;
  const layoutPanels = gridPanels.map((p, idx) => {
    let position = p.position;
    if (!position) {
      const col = (autoIndex % maxCol) + 1;
      const row = Math.floor(autoIndex / maxCol) + 1;
      position = { col, row, colspan: 1, rowspan: 1 };
      autoIndex++;
    }

    return {
      ...p,
      position,
      index: idx,
      status: 'pending', // Initial status for execution tracking
    };
  });

  // Add background panels (keep their original position)
  const allPanels = [
    ...backgroundPanels.map((p, idx) => ({
      ...p,
      index: gridPanels.length + idx,
      status: 'pending',
    })),
    ...layoutPanels,
  ];

  return {
    cols: maxCol || 1,
    rows: maxRow || 1,
    panels: allPanels,
    backgroundPanels: backgroundPanels.length,
  };
}
