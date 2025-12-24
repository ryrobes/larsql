/**
 * Derive phase state from log rows
 *
 * Shared by: polling hook + direct fetch for URL loading
 *
 * Extracts:
 * - Status (pending/running/success/error)
 * - Output (result data)
 * - Duration
 * - Error message
 * - Cost (accumulated)
 * - Model (last used)
 * - Tokens (in/out)
 * - Images (from metadata)
 */
export function derivePhaseState(logs, phaseName) {
  const phaseLogs = logs.filter(r => r.phase_name === phaseName);

  if (phaseLogs.length === 0) {
    return { status: 'pending', result: null, error: null, duration: null, images: null, cost: null, model: null, tokens_in: null, tokens_out: null };
  }

  //console.log('[derivePhaseState]', phaseName, 'has', phaseLogs.length, 'log rows');

  let status = 'pending';
  let result = null;
  let error = null;
  let duration = null;
  let images = null;
  let cost = 0;
  let model = null;
  let tokens_in = 0;
  let tokens_out = 0;

  for (const row of phaseLogs) {
    const role = row.role;

    // Phase running
    if (role === 'phase_start' || role === 'structure') {
      //console.log('[derivePhaseState]', phaseName, 'Setting status to running (role:', role, ')');
      status = 'running';
    }

    // Phase complete
    if (role === 'phase_complete') {
      //console.log('[derivePhaseState]', phaseName, 'Setting status to SUCCESS (found phase_complete)');
      status = 'success';
    }

    // Errors
    if (role === 'error' || row.node_type === 'error') {
      status = 'error';
      error = row.content_json || row.content || 'Unknown error';
    }

    // Extract result from tool execution (sql_data, python_data, etc.)
    if (role === 'tool' && row.content_json) {
      let toolResult = row.content_json;

      // Parse if JSON-encoded string (may need multiple parses for double-encoding)
      while (typeof toolResult === 'string') {
        try {
          const parsed = JSON.parse(toolResult);
          toolResult = parsed;
          //console.log('[derivePhaseState]', phaseName, '✓ Parsed tool result, now type:', typeof toolResult);
        } catch (e) {
          // Can't parse further - it's a plain string result
          //console.log('[derivePhaseState]', phaseName, 'Result is plain string (not JSON)');
          break;
        }
      }

      //console.log('[derivePhaseState]', phaseName, '✓ Found tool result, type:', typeof toolResult, 'has rows?', toolResult?.rows?.length);
      result = toolResult;
    }

    // Extract output from LLM/assistant messages
    if (role === 'assistant' && row.content_json) {
      let content = row.content_json;

      // Parse if JSON-encoded string (may need multiple parses for double-encoding)
      while (typeof content === 'string' && content.startsWith('"')) {
        try {
          const parsed = JSON.parse(content);
          content = parsed;
          //console.log('[derivePhaseState]', phaseName, '✓ Parsed assistant content, now type:', typeof content);
        } catch {
          // Can't parse further
          break;
        }
      }

      //console.log('[derivePhaseState]', phaseName, '✓ Found assistant result, type:', typeof content);
      result = content;
    }

    // Extract images from metadata_json
    if (row.metadata_json) {
      let metadata = row.metadata_json;
      // Parse if JSON-encoded string
      if (typeof metadata === 'string') {
        try {
          metadata = JSON.parse(metadata);
        } catch (e) {
          console.warn('[derivePhaseState] Failed to parse metadata_json:', e);
        }
      }

      // Check for images in metadata
      if (metadata?.images && Array.isArray(metadata.images)) {
        //console.log('[derivePhaseState]', phaseName, 'Found images in metadata:', metadata.images);
        images = metadata.images;
      }
    }

    // Accumulate duration
    if (row.duration_ms !== undefined && row.duration_ms !== null) {
      const ms = parseFloat(row.duration_ms);
      if (!isNaN(ms) && ms > 0) {
        duration = (duration || 0) + ms;
        //console.log('[derivePhaseState]', phaseName, '✓ Added duration:', ms, 'ms from', role, '- Total:', duration);
      }
    }

    // Accumulate cost
    if (row.cost !== undefined && row.cost !== null) {
      const c = parseFloat(row.cost);
      if (!isNaN(c)) {
        cost += c;
      }
    }

    // Accumulate tokens
    if (row.tokens_in !== undefined && row.tokens_in !== null) {
      const ti = parseFloat(row.tokens_in);
      if (!isNaN(ti)) {
        tokens_in += ti;
      }
    }

    if (row.tokens_out !== undefined && row.tokens_out !== null) {
      const to = parseFloat(row.tokens_out);
      if (!isNaN(to)) {
        tokens_out += to;
      }
    }

    // Track model (use last non-null model seen)
    if (row.model) {
      model = row.model;
    }
  }

  const finalState = {
    status,
    result,
    error,
    duration: duration ? Math.round(duration) : null,
    images: images,
    cost: cost > 0 ? cost : null,
    model: model,
    tokens_in: tokens_in > 0 ? Math.round(tokens_in) : null,
    tokens_out: tokens_out > 0 ? Math.round(tokens_out) : null,
  };

  // Log final state
  console.log('[derivePhaseState]', phaseName, 'Final state:', {
    status,
    hasResult: !!result,
    resultType: result ? typeof result : 'null',
    hasRows: result?.rows?.length,
    duration: finalState.duration,
    cost: finalState.cost,
    hasImages: !!images
  });

  return finalState;
}
