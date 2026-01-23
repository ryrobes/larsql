/**
 * SQL Panel Layout Utilities
 *
 * Parse and update panel positions in SQL comments.
 * Format: --- PANEL 'Name' (col, row, colspan, rowspan) [options]
 */

/**
 * Parse panel layout information from SQL
 *
 * @param {string} sql - SQL with panel comments
 * @returns {Object} { panels: Array<{name, col, row, w, h, lineIndex}>, gridSize: {cols, rows}, hasLayout: boolean }
 */
export function parsePanelLayout(sql) {
  const lines = sql.split('\n');
  const panels = [];

  // Pattern: --- PANEL 'name' (col, row, colspan, rowspan) [rest...]
  // We capture: name, col, row, colspan, rowspan
  // Note: Allow optional leading whitespace with ^\s*
  const panelPattern = /^\s*---\s*PANEL\s+['"]([^'"]+)['"](?:\s*\((\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?\))?/;

  lines.forEach((line, index) => {
    const match = line.match(panelPattern);
    if (match) {
      const name = match[1];
      const col = match[2] ? parseInt(match[2], 10) : null;
      const row = match[3] ? parseInt(match[3], 10) : null;
      const colspan = match[4] ? parseInt(match[4], 10) : 1;
      const rowspan = match[5] ? parseInt(match[5], 10) : 1;

      panels.push({
        name,
        // react-grid-layout uses x, y (0-based), w, h
        // SQL uses col, row (1-based)
        x: col !== null ? col - 1 : null,
        y: row !== null ? row - 1 : null,
        w: colspan,
        h: rowspan,
        lineIndex: index,
        // Store original values for comparison
        hasPosition: col !== null && row !== null,
      });
    }
  });

  // Calculate implied grid size
  let cols = 2; // default
  let rows = 2; // default

  const positionedPanels = panels.filter(p => p.hasPosition);
  if (positionedPanels.length > 0) {
    cols = Math.max(...positionedPanels.map(p => p.x + p.w));
    rows = Math.max(...positionedPanels.map(p => p.y + p.h));
  } else if (panels.length > 0) {
    // Auto-layout: calculate based on panel count
    cols = panels.length <= 2 ? panels.length : panels.length <= 4 ? 2 : 3;
    rows = Math.ceil(panels.length / cols);
  }

  // Assign positions to panels without explicit positions
  let nextX = 0;
  let nextY = 0;
  panels.forEach(panel => {
    if (!panel.hasPosition) {
      panel.x = nextX;
      panel.y = nextY;
      nextX += panel.w;
      if (nextX >= cols) {
        nextX = 0;
        nextY += 1;
      }
    }
  });

  return {
    panels,
    gridSize: { cols, rows },
    hasLayout: panels.length > 0,
  };
}

/**
 * Update SQL with new panel positions
 *
 * @param {string} sql - Original SQL
 * @param {Array} layout - Array of { i: name, x, y, w, h }
 * @returns {string} Updated SQL
 */
export function updatePanelPositions(sql, layout) {
  const lines = sql.split('\n');

  // Build a map of panel name -> new position
  const positionMap = {};
  layout.forEach(item => {
    // Convert from 0-based to 1-based
    positionMap[item.i] = {
      col: item.x + 1,
      row: item.y + 1,
      colspan: item.w,
      rowspan: item.h,
    };
  });

  // Pattern to match and replace panel definitions
  // Captures: leading whitespace, prefix, name, optional position, rest of line
  // Note: Allow optional leading whitespace with ^(\s*)
  const panelPattern = /^(\s*)(---\s*PANEL\s+['"])([^'"]+)(['"])(?:\s*\(\d+\s*,\s*\d+(?:\s*,\s*\d+\s*,\s*\d+)?\))?(.*)$/;

  const updatedLines = lines.map(line => {
    const match = line.match(panelPattern);
    if (match) {
      const [, leadingWhitespace, prefix, name, quote, rest] = match;
      const newPos = positionMap[name];

      if (newPos) {
        // Always include all 4 values for consistency
        const posStr = `(${newPos.col}, ${newPos.row}, ${newPos.colspan}, ${newPos.rowspan})`;
        return `${leadingWhitespace}${prefix}${name}${quote} ${posStr}${rest}`;
      }
    }
    return line;
  });

  return updatedLines.join('\n');
}

/**
 * Update grid size comment in SQL
 * If no grid comment exists, adds one at the start
 *
 * @param {string} sql - Original SQL
 * @param {number} cols - Number of columns
 * @param {number} rows - Number of rows
 * @returns {string} Updated SQL
 */
export function updateGridSize(sql, cols, rows) {
  const gridPattern = /^---\s*HYPER\s+GRID\s+\d+x\d+/m;
  const gridComment = `--- HYPER GRID ${cols}x${rows}`;

  if (gridPattern.test(sql)) {
    return sql.replace(gridPattern, gridComment);
  }

  // Add grid comment at the start if not present
  return `${gridComment}\n${sql}`;
}

/**
 * Parse grid size from SQL comment
 *
 * @param {string} sql - SQL with optional grid comment
 * @returns {Object|null} { cols, rows } or null if not specified
 */
export function parseGridSize(sql) {
  const match = sql.match(/^---\s*HYPER\s+GRID\s+(\d+)x(\d+)/m);
  if (match) {
    return {
      cols: parseInt(match[1], 10),
      rows: parseInt(match[2], 10),
    };
  }
  return null;
}

/**
 * Convert react-grid-layout format to our internal format
 *
 * @param {Array} rglLayout - react-grid-layout layout array
 * @returns {Array} Our format with panel names
 */
export function fromRGLLayout(rglLayout) {
  return rglLayout.map(item => ({
    name: item.i,
    x: item.x,
    y: item.y,
    w: item.w,
    h: item.h,
  }));
}

/**
 * Convert our panel format to react-grid-layout format
 *
 * @param {Array} panels - Parsed panels
 * @returns {Array} react-grid-layout layout array
 */
export function toRGLLayout(panels) {
  return panels.map(panel => ({
    i: panel.name,
    x: panel.x,
    y: panel.y,
    w: panel.w,
    h: panel.h,
    // Allow resize/drag
    static: false,
  }));
}

/**
 * Inject RENDER dimensions based on panel layout and container size
 *
 * Finds `THEN RENDER` without explicit args and injects calculated dimensions
 * based on the grid layout and container size.
 *
 * @param {string} sql - SQL with potential RENDER pipeline stage
 * @param {number} containerWidth - Container width in pixels (or null for default)
 * @param {number} containerHeight - Container height in pixels (or null for default)
 * @returns {string} SQL with RENDER dimensions injected (if applicable)
 */
export function injectRenderDimensions(sql, containerWidth, containerHeight) {
  // Match "THEN RENDER" not followed by "(" (case insensitive)
  // This avoids matching RENDER that already has explicit args
  const renderPattern = /\bTHEN\s+RENDER\b(?!\s*\()/gi;

  if (!renderPattern.test(sql)) {
    return sql; // No bare RENDER found
  }

  // Reset regex lastIndex after test()
  renderPattern.lastIndex = 0;

  // Parse layout to determine grid and panel sizes
  const layout = parsePanelLayout(sql);
  const explicitGrid = parseGridSize(sql);
  const cols = explicitGrid?.cols || layout.gridSize.cols || 2;
  const rows = explicitGrid?.rows || layout.gridSize.rows || 2;

  // Use provided dimensions or sensible defaults
  // Defaults: assume ~1200px wide container, ~600px tall
  const width = containerWidth || 1200;
  const height = containerHeight || 600;

  // Grid gap (matches CanvasRenderer.jsx)
  const gap = 16;

  // Calculate single cell dimensions
  // Formula: (totalWidth - (cols-1)*gap) / cols
  const cellWidth = Math.floor((width - (cols - 1) * gap) / cols);
  const cellHeight = Math.floor((height - (rows - 1) * gap) / rows);

  // For now, assume RENDER is in a 1x1 panel (most common case)
  // TODO: Could parse which panel contains RENDER and use its colspan/rowspan
  let renderWidth = cellWidth;
  let renderHeight = cellHeight;

  // Ensure minimum dimensions
  renderWidth = Math.max(renderWidth, 400);
  renderHeight = Math.max(renderHeight, 300);

  // Device pixel ratio for crisp rendering
  const scale = typeof window !== 'undefined' ? Math.min(window.devicePixelRatio || 2, 3) : 2;

  // Inject dimensions into RENDER
  const injectedSql = sql.replace(
    renderPattern,
    `THEN RENDER(${renderWidth}, ${renderHeight}, ${scale})`
  );

  return injectedSql;
}
