/**
 * Monaco CodeLens Provider for SQL Query Execution
 *
 * Shows "▶ Run" links above each query block with metadata
 */

/**
 * Create and register CodeLens provider for SQL queries
 */
export function createQueryCodeLensProvider(getQueries, onRunQuery, getQueryExplains) {
  return {
    provideCodeLenses: function (model, token) {
      const queries = getQueries();
      const explains = getQueryExplains();

      const lenses = [];

      queries.forEach((query, idx) => {
        // Get explain data for this query if available
        const queryHash = hashQuery(query.text);
        const explain = explains?.get?.(queryHash);

        // Build CodeLens title with metadata
        const costText = explain?.estimatedCost > 0
          ? ` · ${formatCost(explain.estimatedCost)}`
          : '';

        const linesText = query.endLine > query.startLine
          ? ` · Lines ${query.startLine}-${query.endLine}`
          : ` · Line ${query.startLine}`;

        const errorText = explain?.queryType === 'error'
          ? ' · ⚠ Error'
          : '';

        const title = `▶ Run this query${linesText}${costText}${errorText}`;

        lenses.push({
          range: {
            startLineNumber: query.startLine,
            startColumn: 1,
            endLineNumber: query.startLine,
            endColumn: 1,
          },
          id: `run-query-${idx}`,
          command: {
            id: `hyper.runSingleQuery.${idx}`,
            title: title,
            arguments: [query, idx],
          },
        });
      });

      return {
        lenses: lenses,
        dispose: () => {},
      };
    },

    resolveCodeLens: function (model, codeLens, token) {
      return codeLens;
    },
  };
}

/**
 * Simple hash function for query text
 */
function hashQuery(queryText) {
  const normalized = queryText.trim().replace(/\s+/g, ' ');
  let hash = 0;
  for (let i = 0; i < normalized.length; i++) {
    const char = normalized.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return hash.toString(36);
}

/**
 * Format cost for display
 */
function formatCost(cost) {
  if (cost === 0) return '$0.00';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(3)}`;
}
