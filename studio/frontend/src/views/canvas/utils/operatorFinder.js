/**
 * Find positions of semantic operators in SQL query
 *
 * Given an explain result with operations, find where each operator
 * appears in the query text for inline highlighting.
 */

/**
 * Find all occurrences of semantic operators in query text
 *
 * @param {string} queryText - The SQL query
 * @param {Array} operations - Operations from explain result
 * @returns {Array<{operation, startPos, endPos, startLine, startCol, endLine, endCol}>}
 */
export function findOperatorPositions(queryText, operations) {
  if (!queryText || !operations || operations.length === 0) {
    return [];
  }

  console.log('[operator-finder] Looking for operations:', operations.map(op => op.function));

  const positions = [];
  const lines = queryText.split('\n');

  // Track which text positions we've already used to avoid duplicates
  const usedPositions = new Set();

  // Common semantic operator patterns
  const operatorPatterns = [
    // Infix operators
    { regex: /\bMEANS\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'MEANS' },
    { regex: /\bNOT\s+MEANS\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'NOT_MEANS' },
    { regex: /\bABOUT\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'ABOUT' },
    { regex: /\b~\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'MEANS' }, // ~ is shorthand for MEANS
    { regex: /\bIMPLIES\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'IMPLIES' },
    { regex: /\bCONTRADICTS\s+(['"])((?:\\.|(?!\1).)*)\1/gi, type: 'CONTRADICTS' },

    // Function calls (scalar)
    { regex: /\bsemantic_matches\s*\(/gi, type: 'semantic_matches' },
    { regex: /\bsmart_json\s*\(/gi, type: 'smart_json' },
    { regex: /\bcascade\s*\(/gi, type: 'cascade' },
    { regex: /\bASK\s*\(/gi, type: 'ASK' },
    { regex: /\bEXTRACTS\s*\(/gi, type: 'EXTRACTS' },
    { regex: /\bPARSE\s*\(/gi, type: 'PARSE' },
    { regex: /\bNORMALIZE\s*\(/gi, type: 'NORMALIZE' },
    { regex: /\bCLASSIFY_SINGLE\s*\(/gi, type: 'CLASSIFY_SINGLE' },

    // Aggregates
    { regex: /\bSUMMARIZE\s*\(/gi, type: 'SUMMARIZE' },
    { regex: /\bSENTIMENT\s*\(/gi, type: 'SENTIMENT' },
    { regex: /\bTHEMES\s*\(/gi, type: 'THEMES' },
    { regex: /\bthemes\s*\(/gi, type: 'themes' }, // lowercase version
    { regex: /\bCONSENSUS\s*\(/gi, type: 'CONSENSUS' },
    { regex: /\bOUTLIERS\s*\(/gi, type: 'OUTLIERS' },
    { regex: /\bCLUSTER\s*\(/gi, type: 'CLUSTER' },
    { regex: /\bDEDUPE\s*\(/gi, type: 'DEDUPE' },
    { regex: /\bRANK_AGG\s*\(/gi, type: 'RANK_AGG' },
    { regex: /\bGOLDEN_RECORD_AGG\s*\(/gi, type: 'GOLDEN_RECORD_AGG' },
  ];

  // Find each operation's position
  // Strategy: Each operation in the explain result represents ONE instance
  // We need to find unused text positions and match them 1:1

  operations.forEach((op, opIdx) => {
    const functionName = op.function.toLowerCase();
    let foundPosition = null;

    // Strategy 1: Check if this is an infix operator (MEANS, IMPLIES, etc.)
    const infixKeywords = ['means', 'not_means', 'about', 'implies', 'contradicts'];
    if (infixKeywords.some(kw => functionName.includes(kw))) {
      let keyword = functionName.replace('semantic_', '').replace('_', ' ');
      const infixPattern = new RegExp(`\\b${escapeRegex(keyword)}\\b`, 'gi');
      const matches = [...queryText.matchAll(infixPattern)];

      // Find first UNUSED match
      for (const match of matches) {
        const matchStart = match.index;
        const matchEnd = matchStart + match[0].length;
        const posKey = `${matchStart}:${matchEnd}`;

        if (!usedPositions.has(posKey)) {
          const pos = getLineColFromOffset(queryText, matchStart);
          const endPos = getLineColFromOffset(queryText, matchEnd);

          foundPosition = {
            operation: op,
            text: match[0],
            startPos: matchStart,
            endPos: matchEnd,
            startLine: pos.line,
            startCol: pos.col,
            endLine: endPos.line,
            endCol: endPos.col,
            operatorType: keyword,
          };

          usedPositions.add(posKey);
          break; // Found it, move to next operation
        }
      }
    }

    // Strategy 2: Try predefined patterns
    if (!foundPosition) {
      for (const pattern of operatorPatterns) {
        if (foundPosition) break;

        if (pattern.type.toLowerCase() === functionName ||
            functionName.includes(pattern.type.toLowerCase()) ||
            pattern.type.toLowerCase().includes(functionName)) {
          const matches = [...queryText.matchAll(pattern.regex)];

          // Find first UNUSED match
          for (const match of matches) {
            const matchStart = match.index;
            const matchEnd = matchStart + match[0].length;
            const posKey = `${matchStart}:${matchEnd}`;

            if (!usedPositions.has(posKey)) {
              const pos = getLineColFromOffset(queryText, matchStart);
              const endPos = getLineColFromOffset(queryText, matchEnd);

              foundPosition = {
                operation: op,
                text: match[0],
                startPos: matchStart,
                endPos: matchEnd,
                startLine: pos.line,
                startCol: pos.col,
                endLine: endPos.line,
                endCol: endPos.col,
                operatorType: pattern.type,
              };

              usedPositions.add(posKey);
              break;
            }
          }
        }
      }
    }

    // Strategy 3: Direct function name search
    if (!foundPosition) {
      const funcPattern = new RegExp(`\\b${escapeRegex(op.function)}\\s*\\(`, 'gi');
      const matches = [...queryText.matchAll(funcPattern)];

      // Find first UNUSED match
      for (const match of matches) {
        const matchStart = match.index;
        const matchEnd = matchStart + match[0].length - 1;
        const posKey = `${matchStart}:${matchEnd}`;

        if (!usedPositions.has(posKey)) {
          const pos = getLineColFromOffset(queryText, matchStart);
          const endPos = getLineColFromOffset(queryText, matchEnd);

          foundPosition = {
            operation: op,
            text: match[0].trim(),
            startPos: matchStart,
            endPos: matchEnd,
            startLine: pos.line,
            startCol: pos.col,
            endLine: endPos.line,
            endCol: endPos.col,
            operatorType: op.function,
          };

          usedPositions.add(posKey);
          break;
        }
      }
    }

    if (foundPosition) {
      positions.push(foundPosition);
    } else {
      console.log(`[operator-finder] Could not find unused position for operation ${opIdx + 1}: ${op.function}`);
    }
  });

  console.log(`[operator-finder] Returning ${positions.length} positions for ${operations.length} operations`);

  return positions;
}

/**
 * Escape special regex characters
 */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Convert absolute character offset to line/column (1-indexed for Monaco)
 */
function getLineColFromOffset(text, offset) {
  const lines = text.substring(0, offset).split('\n');
  return {
    line: lines.length,
    col: lines[lines.length - 1].length + 1,
  };
}

/**
 * Get cost tier for an operator cost
 */
export function getOperatorCostTier(cost) {
  if (cost === 0) return 'free';
  if (cost < 0.001) return 'free';
  if (cost < 0.01) return 'low';
  if (cost < 0.1) return 'medium';
  if (cost < 1.0) return 'high';
  return 'very-high';
}
