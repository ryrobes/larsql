/**
 * SQL Query Splitter - Parse editor content into individual queries
 *
 * Handles:
 * - Semicolon delimiters
 * - Respects semicolons inside strings/comments
 * - Returns position info for Monaco decorations
 */

/**
 * Split SQL editor content into individual queries with position info.
 *
 * @param {string} sql - Full SQL text from editor
 * @returns {Array<{text: string, startLine: number, endLine: number, startCol: number, endCol: number}>}
 */
export function parseQueries(sql) {
  if (!sql || !sql.trim()) return [];

  const queries = [];
  const lines = sql.split('\n');

  // Debug logging
  const debugMode = false; // Set to true to debug parsing

  let currentQuery = '';
  let startLine = 1; // Monaco uses 1-based indexing
  let startCol = 1;
  let inString = false;
  let stringChar = null;
  let inLineComment = false;
  let inBlockComment = false;

  for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
    const line = lines[lineIdx];
    const lineNum = lineIdx + 1;

    let charIdx = 0;
    while (charIdx < line.length) {
      const char = line[charIdx];
      const nextChar = line[charIdx + 1];

      // Handle line comments (including --- PANEL markers)
      if (!inString && !inBlockComment && char === '-' && nextChar === '-') {
        inLineComment = true;
        currentQuery += line.substring(charIdx); // Include rest of line
        break; // Rest of line is comment
      }

      // Handle block comments
      if (!inString && !inLineComment && char === '/' && nextChar === '*') {
        inBlockComment = true;
        currentQuery += '/*';
        charIdx += 2;
        continue;
      }

      if (inBlockComment && char === '*' && nextChar === '/') {
        inBlockComment = false;
        currentQuery += '*/';
        charIdx += 2;
        continue;
      }

      // Handle strings
      if (!inLineComment && !inBlockComment) {
        if ((char === "'" || char === '"') && !inString) {
          inString = true;
          stringChar = char;
        } else if (inString && char === stringChar) {
          // Check for escaped quote (doubled quote in SQL)
          if (nextChar === stringChar) {
            currentQuery += char + nextChar;
            charIdx += 2;
            continue;
          } else {
            inString = false;
            stringChar = null;
          }
        }
      }

      // Handle semicolon (query delimiter)
      if (!inString && !inLineComment && !inBlockComment && char === ';') {
        currentQuery += char;

        // Query complete - record it
        const trimmed = currentQuery.trim();
        const commentOnly = isCommentOnly(trimmed);

        if (debugMode) {
          console.log(`[parser] Query ended at line ${lineNum}: "${trimmed.substring(0, 60)}..." commentOnly: ${commentOnly}`);
        }

        if (trimmed && !commentOnly) {
          queries.push({
            text: currentQuery,
            startLine,
            endLine: lineNum,
            startCol,
            endCol: charIdx + 2, // Position after semicolon
          });

          if (debugMode) {
            console.log(`[parser] Added query from line ${startLine} to ${lineNum}`);
          }
        }

        // Reset for next query
        currentQuery = '';
        startLine = lineNum;
        startCol = charIdx + 2;
        charIdx++;
        continue;
      }

      currentQuery += char;
      charIdx++;
    }

    // End of line
    if (lineIdx < lines.length - 1) {
      currentQuery += '\n';
    }

    // Reset line comment flag at end of line
    if (inLineComment) {
      inLineComment = false;
    }

    // If we finished a line and haven't started a query yet, update start position
    if (!currentQuery.trim() && lineIdx < lines.length - 1) {
      startLine = lineNum + 1;
      startCol = 1;
    }
  }

  // Handle final query (no semicolon)
  const trimmed = currentQuery.trim();
  const commentOnly = isCommentOnly(trimmed);

  if (debugMode) {
    console.log(`[parser] Final query: "${trimmed.substring(0, 40)}..." commentOnly: ${commentOnly}`);
  }

  if (trimmed && !commentOnly) {
    queries.push({
      text: currentQuery,
      startLine,
      endLine: lines.length,
      startCol,
      endCol: lines[lines.length - 1].length + 1,
    });
  }

  if (debugMode) {
    console.log(`[parser] Total valid queries found: ${queries.length}`);
  }

  return queries;
}

/**
 * Check if text is only comments (no actual SQL)
 */
function isCommentOnly(text) {
  const lines = text.split('\n');
  let inBlockComment = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Check for block comment markers
    if (trimmed.startsWith('/*')) inBlockComment = true;
    if (trimmed.endsWith('*/')) {
      inBlockComment = false;
      continue;
    }
    if (inBlockComment) continue;

    // Check for line comments
    if (trimmed.startsWith('--')) continue;

    // If we got here, this line has actual SQL
    return false;
  }
  return true;
}

/**
 * Get a stable hash for a query (for caching explain results)
 */
export function hashQuery(queryText) {
  const normalized = queryText.trim().replace(/\s+/g, ' ');
  let hash = 0;
  for (let i = 0; i < normalized.length; i++) {
    const char = normalized.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return hash.toString(36);
}
