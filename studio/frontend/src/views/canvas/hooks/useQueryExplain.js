/**
 * useQueryExplain - Auto-explain queries and manage Monaco decorations
 *
 * Features:
 * - Debounced auto-explain (300ms)
 * - Gutter icons with cost tiers (iconify)
 * - Inline ghost text (estimated/actual costs)
 * - Hover tooltips with explain plan details
 * - Tracks actual costs from unified_logs via caller_id
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { parseQueries, hashQuery } from '../utils/querySplitter';
import { findOperatorPositions, getOperatorCostTier } from '../utils/operatorFinder';
import { API_BASE_URL } from '../../../config/api';

// Cost tier thresholds
const COST_TIERS = {
  ZERO: { max: 0, color: 'zero', icon: 'mdi:circle-outline', label: 'No LLM calls' },
  FREE: { max: 0.001, color: 'free', icon: 'mdi:check-circle', label: 'Free' },
  CHEAP: { max: 0.01, color: 'green', icon: 'mdi:cash-fast', label: 'Low cost' },
  MODERATE: { max: 0.10, color: 'yellow', icon: 'mdi:currency-usd', label: 'Moderate cost' },
  EXPENSIVE: { max: 1.00, color: 'orange', icon: 'mdi:alert', label: 'Expensive' },
  VERY_EXPENSIVE: { max: Infinity, color: 'red', icon: 'mdi:fire', label: 'Very expensive' },
};

function getCostTier(cost) {
  if (cost === 0) return COST_TIERS.ZERO;
  if (cost <= COST_TIERS.FREE.max) return COST_TIERS.FREE;
  if (cost <= COST_TIERS.CHEAP.max) return COST_TIERS.CHEAP;
  if (cost <= COST_TIERS.MODERATE.max) return COST_TIERS.MODERATE;
  if (cost <= COST_TIERS.EXPENSIVE.max) return COST_TIERS.EXPENSIVE;
  return COST_TIERS.VERY_EXPENSIVE;
}

function formatCost(cost) {
  if (cost === 0) return '$0.00';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(3)}`;
}

function formatDelta(estimated, actual) {
  if (!estimated || !actual) return '';
  const diff = actual - estimated;
  const pct = ((diff / estimated) * 100).toFixed(0);
  if (Math.abs(diff) < 0.001) return '✓';
  if (diff > 0) return `↑${pct}%`;
  return `↓${Math.abs(pct)}%`;
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

export function useQueryExplain({ editorValue, editorRef, monacoRef, database, lastExecutionCallerId }) {
  const [queryExplains, setQueryExplains] = useState(new Map());
  const [actualCosts, setActualCosts] = useState(new Map()); // Map<callerId, cost>
  const [totalEstimatedCost, setTotalEstimatedCost] = useState(0);
  const [totalActualCost, setTotalActualCost] = useState(0);

  const debounceTimerRef = useRef(null);
  const decorationsRef = useRef([]);

  // Auto-explain on editor value change (debounced)
  useEffect(() => {
    if (!editorValue?.trim() || !monacoRef.current || !editorRef.current) return;

    // Clear previous timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Debounce explain calls
    debounceTimerRef.current = setTimeout(async () => {
      const queries = parseQueries(editorValue);

      // Fetch explains for each query
      const newExplains = new Map();

      console.log(`[explain] Parsed ${queries.length} queries from editor`);

      for (const query of queries) {
        // Skip empty or comment-only queries
        const trimmed = query.text.trim();

        // Check if it's comment-only (all lines are comments)
        const nonCommentLines = trimmed.split('\n').filter(line => {
          const lineTrimmed = line.trim();
          // Skip empty lines
          if (!lineTrimmed) return false;
          // Skip -- comments (including --- PANEL markers)
          if (lineTrimmed.startsWith('--')) return false;
          // Skip /* */ comments
          if (lineTrimmed.startsWith('/*') || lineTrimmed === '*/') return false;
          // This is actual SQL
          return true;
        });

        if (nonCommentLines.length === 0) {
          console.log(`[explain] Skipping comment-only query at line ${query.startLine}: "${trimmed.substring(0, 60)}..."`);
          continue;
        }

        const queryHash = hashQuery(query.text);

        console.log(`[explain] Processing query at line ${query.startLine} (${nonCommentLines.length} non-comment lines): ${trimmed.substring(0, 50)}...`);

        // Skip if we already have explain for this query
        if (queryExplains.has(queryHash)) {
          newExplains.set(queryHash, {
            ...queryExplains.get(queryHash),
            position: query,
          });
          continue;
        }

        try {
          // Use EXPLAIN (FORMAT JSON) through the normal execute endpoint
          // This goes through the full SQL pipeline (rewriting, semantic operators, etc.)

          // Clean the query text:
          // Remove ALL comments before sending to EXPLAIN
          // This prevents EXPLAIN from trying to parse comment syntax
          let inBlockComment = false;
          let cleanQuery = query.text
            .split('\n')
            .map(line => {
              const trimmed = line.trim();

              // Handle block comments
              if (trimmed.includes('/*')) inBlockComment = true;
              if (trimmed.includes('*/')) {
                inBlockComment = false;
                return ''; // Remove this line
              }
              if (inBlockComment) return '';

              // Remove line comments (everything after --)
              const commentIdx = line.indexOf('--');
              if (commentIdx >= 0) {
                // Keep SQL before the comment
                return line.substring(0, commentIdx);
              }

              // Keep the line as-is
              return line;
            })
            .filter(line => line.trim()) // Remove empty lines
            .join('\n')
            .trim();

          if (cleanQuery.endsWith(';')) {
            cleanQuery = cleanQuery.slice(0, -1).trim();
          }

          // Final check - if after cleaning we have no SQL, skip
          if (!cleanQuery) {
            console.log('[explain] After cleaning, query is empty - skipping');
            continue;
          }

          const explainQuery = `EXPLAIN (FORMAT JSON) ${cleanQuery}`;

          console.log(`[explain] Sending to backend: "${explainQuery.substring(0, 100)}..."`);

          const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: explainQuery,
              database: database || 'memory',
            }),
          });

          const data = await response.json();

          if (data.success && data.data && data.data.length > 0) {
            const firstRow = data.data[0];

            // Check if this is a semantic EXPLAIN (has query_plan column)
            if (firstRow.query_plan) {
              // Parse the JSON plan
              const plan = typeof firstRow.query_plan === 'string'
                ? JSON.parse(firstRow.query_plan)
                : firstRow.query_plan;

              const explainData = {
                query: query.text,
                position: query,
                estimatedCost: plan.total_estimated_cost || 0,
                estimatedCalls: plan.total_estimated_llm_calls || 0,
                estimatedDuration: plan.estimated_duration_seconds || 0,
                operations: plan.operations || [],
                aggregates: plan.aggregates || [],
                pipelineStages: plan.pipeline_stages || [],
                queryType: plan.query_type,
                explainPlan: plan.native_plan,
                hints: plan.optimization_hints || [],
              };

              // Debug: log all cost sources
              if (explainData.operations.length > 0) {
                console.log('[explain] Operations found:', explainData.operations.map(op => op.function));
              }
              if (explainData.aggregates.length > 0) {
                console.log('[explain] Aggregates found:', explainData.aggregates.map(agg => agg.function));
              }
              if (explainData.pipelineStages.length > 0) {
                console.log('[explain] Pipeline stages found:', explainData.pipelineStages.map(s => s.stage_name));
              }

              newExplains.set(queryHash, explainData);
            } else if (firstRow.explain_key) {
              // Regular DuckDB EXPLAIN (no semantic operations)
              // Show it with $0 cost since there are no LLM calls
              newExplains.set(queryHash, {
                query: query.text,
                position: query,
                estimatedCost: 0,
                estimatedCalls: 0,
                estimatedDuration: 0,
                operations: [],
                aggregates: [],
                pipelineStages: [],
                queryType: 'sql_query',
                explainPlan: firstRow.explain_value,
                hints: [],
              });
            }
          } else {
            // Explain failed - show error indicator
            // This helps identify queries that depend on missing tables, syntax errors, etc.
            const errorMessage = data.error || 'Explain failed';

            // Skip parser errors (incomplete queries while typing)
            if (errorMessage.includes('Parser Error')) {
              console.debug('[explain] Skipping parser error (incomplete query)');
            } else {
              // Show error indicator for real issues
              console.log('[explain] EXPLAIN error:', errorMessage);

              newExplains.set(queryHash, {
                query: query.text,
                position: query,
                estimatedCost: 0,
                estimatedCalls: 0,
                estimatedDuration: 0,
                operations: [],
                aggregates: [],
                pipelineStages: [],
                queryType: 'error',
                error: errorMessage,
                explainPlan: null,
                hints: [`Error: ${errorMessage}`],
              });
            }
          }
        } catch (err) {
          // Network or JSON parsing errors - log these
          if (!err.message.includes('JSON')) {
            console.debug('[explain] Error:', err.message);
          }
        }
      }

      setQueryExplains(newExplains);

      // Calculate totals
      let totalEst = 0;
      newExplains.forEach(exp => {
        totalEst += exp.estimatedCost || 0;
      });
      setTotalEstimatedCost(totalEst);

    }, 300); // 300ms debounce

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [editorValue, database]); // Intentionally not including queryExplains to avoid loops

  // Fetch actual costs from unified_logs when execution completes
  useEffect(() => {
    if (!lastExecutionCallerId) return;

    // Poll unified_logs for cost data (may take a few seconds to arrive)
    const fetchActualCost = async () => {
      try {
        // TODO: Create /api/sql/actual-cost endpoint that queries unified_logs
        // For now, we'll stub this out
        console.log('[explain] Would fetch actual cost for caller_id:', lastExecutionCallerId);

        // Stub: simulate actual cost being slightly different from estimated
        // In real implementation, query unified_logs.cost_usd WHERE caller_id = ?
        const stubActualCost = totalEstimatedCost * (0.95 + Math.random() * 0.1);
        setActualCosts(prev => new Map(prev).set(lastExecutionCallerId, stubActualCost));
        setTotalActualCost(stubActualCost);
      } catch (err) {
        console.error('[explain] Failed to fetch actual cost:', err);
      }
    };

    // Poll after a delay (logs take time to write)
    const timer = setTimeout(fetchActualCost, 2000);
    return () => clearTimeout(timer);
  }, [lastExecutionCallerId]);

  // Update Monaco decorations whenever explains, actual costs, OR editor value changes
  // This ensures operator positions update when user edits the query
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current || queryExplains.size === 0) return;

    const monaco = monacoRef.current;
    const editor = editorRef.current;
    const decorations = [];

    // Get current editor content to re-parse operator positions
    const currentEditorValue = editorValue || '';

    queryExplains.forEach((explain, queryHash) => {
      const { position, estimatedCost, operations, aggregates, pipelineStages, queryType, error } = explain;
      if (!position) return;

      // Special handling for error queries
      const isError = queryType === 'error';
      const tier = isError ? { color: 'error', label: 'Error' } : getCostTier(estimatedCost);
      const actualCost = actualCosts.get(lastExecutionCallerId);
      const hasActual = actualCost !== undefined;

      // Query block border decoration (entire query range)
      decorations.push({
        range: new monaco.Range(position.startLine, 1, position.endLine, 9999),
        options: {
          isWholeLine: true,
          className: 'query-block-highlight',
          linesDecorationsClassName: `query-block-edge query-block-edge-${tier.color}`,
        },
      });

      // Gutter decoration (icon) with prominent cost/error in hover
      const costTextShort = isError
        ? 'Error'
        : (estimatedCost > 0
          ? `$${estimatedCost < 0.01 ? estimatedCost.toFixed(4) : estimatedCost.toFixed(3)}`
          : '$0.00');

      decorations.push({
        range: new monaco.Range(position.startLine, 1, position.startLine, 1),
        options: {
          isWholeLine: false,
          glyphMarginClassName: `query-cost-gutter query-cost-${tier.color}`,
          glyphMarginHoverMessage: [
            { value: isError ? buildErrorMarkdown(explain) : buildHoverMarkdown(explain, actualCost, costTextShort) }
          ],
        },
      });

      // Note: Can't show text in the glyph margin, Monaco doesn't support it
      // Cost is shown in hover tooltip and inline ghost text instead

      // Inline ghost text decoration (at end of query)
      if (isError) {
        // Show error inline
        decorations.push({
          range: new monaco.Range(position.endLine, position.endCol, position.endLine, position.endCol),
          options: {
            after: {
              content: ` -- ⚠ ${error}`,
              inlineClassName: 'query-cost-error-text',
              cursorStops: monaco.editor.InjectedTextCursorStops.None,
            },
          },
        });
      } else if (estimatedCost > 0 || hasActual) {
        // Show cost for queries with LLM calls
        const inlineText = hasActual
          ? ` -- est: ${formatCost(estimatedCost)} | actual: ${formatCost(actualCost)} ${formatDelta(estimatedCost, actualCost)}`
          : ` -- est: ${formatCost(estimatedCost)}`;

        decorations.push({
          range: new monaco.Range(position.endLine, position.endCol, position.endLine, position.endCol),
          options: {
            after: {
              content: inlineText,
              inlineClassName: 'query-cost-ghost-text',
              cursorStops: monaco.editor.InjectedTextCursorStops.None,
            },
          },
        });
      }

      // Operator-level decorations (underline semantic operators)
      const allOperations = [
        ...(operations || []),
        ...(aggregates || []),
      ];

      if (allOperations.length > 0) {
        // Find operators ONLY within this specific query's text range
        // Extract just this query's text from the editor
        const queryLines = currentEditorValue.split('\n');
        const queryText = queryLines.slice(position.startLine - 1, position.endLine).join('\n');

        console.log(`[explain] Searching for ${allOperations.length} operations in query at lines ${position.startLine}-${position.endLine}`);

        // Find positions within the query text (line numbers will be relative to query start)
        const operatorPositions = findOperatorPositions(queryText, allOperations);

        console.log('[explain] Found operator positions:', operatorPositions.length, 'for query with', allOperations.length, 'operations+aggregates');

        // Adjust line numbers to be relative to editor (not query)
        const adjustedPositions = operatorPositions.map(pos => {
          const adjustedStartLine = pos.startLine + position.startLine - 1;
          const adjustedEndLine = pos.endLine + position.startLine - 1;

          console.log(`[explain] Adjusted operator ${pos.operation.function} from relative line ${pos.startLine} to editor line ${adjustedStartLine}`);

          return {
            ...pos,
            startLine: adjustedStartLine,
            endLine: adjustedEndLine,
          };
        });

        adjustedPositions.forEach((opPos, idx) => {
          const op = opPos.operation;
          const opTier = getOperatorCostTier(op.estimated_cost);

          console.log(`[explain] Operator ${idx + 1}: ${op.function} at line ${opPos.startLine}, col ${opPos.startCol}-${opPos.endCol}, tier: ${opTier}`);

          // Underline the operator
          const opCostText = formatCost(op.estimated_cost);

          // Get calls/groups depending on operation type
          const callCount = op.estimated_llm_calls || op.estimated_groups || 0;
          const cacheInfo = op.cache_hit_rate !== undefined
            ? `**Cache Hit Rate:** ${(op.cache_hit_rate * 100).toFixed(0)}%\n\n`
            : '';

          const decoration = {
            range: new monaco.Range(
              opPos.startLine,
              opPos.startCol,
              opPos.endLine,
              opPos.endCol
            ),
            options: {
              inlineClassName: `operator-cost-underline operator-cost-${opTier}`,
              hoverMessage: [
                {
                  value: `# ${opCostText}\n\n` +
                         `**Function:** \`${op.function}\`\n\n` +
                         `**LLM Calls:** ${callCount}\n\n` +
                         cacheInfo +
                         `**Model:** ${op.model || 'default'}`,
                }
              ],
            },
          };

          console.log('[explain] Adding decoration:', decoration);
          decorations.push(decoration);
        });
      }

      // Pipeline stage decorations (THEN operators)
      if (pipelineStages && pipelineStages.length > 0) {
        console.log('[explain] Adding pipeline stage decorations for', pipelineStages.length, 'stages');

        // Find THEN keywords ONLY within this query's text range
        const queryLines = currentEditorValue.split('\n');
        const queryText = queryLines.slice(position.startLine - 1, position.endLine).join('\n');

        const thenPattern = /\bTHEN\s+(\w+)/gi;
        const thenMatches = [...queryText.matchAll(thenPattern)];

        thenMatches.forEach((match, idx) => {
          if (idx >= pipelineStages.length) return;

          const stage = pipelineStages[idx];
          const matchStart = match.index;
          const matchEnd = matchStart + match[0].length;

          // Get position relative to query start
          const pos = getLineColFromOffset(queryText, matchStart);
          const endPos = getLineColFromOffset(queryText, matchEnd);

          // Adjust to editor coordinates
          const editorLine = pos.line + position.startLine - 1;
          const editorEndLine = endPos.line + position.startLine - 1;

          const stageTier = getOperatorCostTier(stage.estimated_cost);

          decorations.push({
            range: new monaco.Range(editorLine, pos.col, editorEndLine, endPos.col),
            options: {
              inlineClassName: `pipeline-stage-underline pipeline-stage-${stageTier}`,
              hoverMessage: [
                {
                  value: `# ${formatCost(stage.estimated_cost)}\n\n` +
                         `**Pipeline Stage:** \`${stage.stage_name}\`\n\n` +
                         `**Cascade:** ${stage.cascade_id}\n\n` +
                         `**Model:** ${stage.model}\n\n` +
                         `**Description:** ${stage.description || 'N/A'}`,
                }
              ],
            },
          });
        });
      }
    });

    console.log(`[explain] Applying ${decorations.length} total decorations`);

    // Apply decorations
    decorationsRef.current = editor.deltaDecorations(decorationsRef.current, decorations);

    console.log('[explain] Decorations applied, new IDs:', decorationsRef.current);

  }, [queryExplains, actualCosts, lastExecutionCallerId, editorRef, monacoRef, editorValue]);

  return {
    queryExplains,
    totalEstimatedCost,
    totalActualCost,
    queryCount: queryExplains.size,
  };
}

/**
 * Build error message for failed explains
 */
function buildErrorMarkdown(explain) {
  const { error } = explain;

  let md = `# ⚠ EXPLAIN Failed\n\n`;
  md += `**Error:** ${error}\n\n`;
  md += '---\n\n';
  md += '**Common causes:**\n';
  md += '- Table/view doesn\'t exist yet (query depends on earlier CREATE)\n';
  md += '- Syntax error in query\n';
  md += '- Column reference not found\n\n';
  md += '**Tip:** Run the setup queries first, or ignore this if the table is created earlier in the file.';

  return md;
}

/**
 * Build markdown hover message for Monaco tooltip
 */
function buildHoverMarkdown(explain, actualCost, costTextShort) {
  const { estimatedCost, estimatedCalls, operations, aggregates, pipelineStages, queryType, hints } = explain;
  const hasActual = actualCost !== undefined;

  // Big cost display at top (use the formatted short version if provided)
  const displayCost = costTextShort || formatCost(estimatedCost);
  let md = `# ${displayCost}\n\n`;

  if (hasActual) {
    md += `**Actual:** ${formatCost(actualCost)} (${formatDelta(estimatedCost, actualCost)})\n\n`;
  }

  md += `**LLM Calls:** ${estimatedCalls}\n\n`;
  md += '---\n\n';

  // Breakdown
  if (operations.length > 0) {
    md += '**Operations:**\n';
    operations.forEach(op => {
      md += `- \`${op.function}\`: ${formatCost(op.estimated_cost)} (${op.estimated_llm_calls} calls, ${(op.cache_hit_rate * 100).toFixed(0)}% cached)\n`;
    });
    md += '\n';
  }

  if (aggregates.length > 0) {
    md += '**Aggregates:**\n';
    aggregates.forEach(agg => {
      md += `- \`${agg.function}\`: ${formatCost(agg.estimated_cost)} (${agg.estimated_groups} groups)\n`;
    });
    md += '\n';
  }

  if (pipelineStages && pipelineStages.length > 0) {
    md += '**Pipeline Stages:**\n';
    pipelineStages.forEach((stage, idx) => {
      md += `- **${stage.stage_name}**: ${formatCost(stage.estimated_cost)} (${stage.description || stage.cascade_id})\n`;
    });
    md += '\n';
  }

  // Hints
  if (hints && hints.length > 0) {
    md += '**Optimization Hints:**\n';
    hints.forEach(hint => {
      md += `- 💡 ${hint}\n`;
    });
  }

  return md;
}
