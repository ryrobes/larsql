// Shared utilities for debug message rendering
// Used by both DebugModal and LiveDebugLog (DetailView)

export const deduplicateEntries = (entries) => {
  const filtered = [];
  const seenAgentContent = new Map();

  for (const entry of entries) {
    // Track agent entries by timestamp + content hash
    if (entry.node_type === 'agent') {
      const contentKey = `${entry.timestamp}-${entry.content?.substring(0, 100)}`;
      seenAgentContent.set(contentKey, true);
      filtered.push(entry);
      continue;
    }

    // Skip turn_output if we've already seen this content from agent
    if (entry.node_type === 'turn_output') {
      const contentKey = `${entry.timestamp}-${entry.content?.substring(0, 100)}`;
      if (seenAgentContent.has(contentKey)) {
        continue; // Skip duplicate
      }
    }

    filtered.push(entry);
  }

  return filtered;
};

export const isStructural = (entry) => {
  const structuralTypes = ['cascade', 'cell', 'turn', 'soundings'];
  const structuralRoles = ['structure', 'cell_start', 'soundings_start', 'turn_start'];

  return structuralTypes.includes(entry.node_type) ||
         structuralRoles.includes(entry.role);
};

export const isConversational = (entry) => {
  // Filter out debug-only messages (not sent to LLM)
  const meta = entry.metadata;
  if (meta) {
    const metaObj = typeof meta === 'string' ? JSON.parse(meta) : meta;
    if (metaObj?.not_sent_to_llm === true || metaObj?.debug_only === true) {
      return false; // Filter out debug-only messages
    }
  }

  // Filter out "Initialization" cell entries (duplicates logged before cell assignment)
  if (entry.cell_name === 'Initialization' || entry.cell_name === null) {
    // Allow structural messages, but not conversation messages from Initialization
    const conversationalTypes = ['user', 'agent', 'assistant', 'tool_call', 'tool_result', 'system'];
    if (conversationalTypes.includes(entry.node_type)) {
      return false; // Filter out Initialization conversation messages
    }
  }

  // Core conversation messages
  const conversationalTypes = ['user', 'agent', 'assistant', 'tool_call', 'tool_result', 'follow_up', 'injection'];
  const conversationalSystemRoles = ['system']; // System prompts sent to LLM

  // Include validation/ward messages - these are part of the conversation flow
  const validationTypes = ['validation', 'validation_start', 'validation_error', 'validation_retry',
                          'ward_blocking', 'ward_retry', 'ward_advisory',
                          'pre_ward', 'post_ward', 'schema_validation', 'schema_validation_failed',
                          'sub_cascade_ref', 'sub_cascade_start', 'sub_cascade_complete'];

  // Include soundings/evaluation messages - critical for understanding workflow decisions
  const soundingsTypes = ['evaluation', 'evaluator', 'soundings_result', 'sounding_attempt',
                         'sounding_evaluation', 'soundings_start', 'reforge_start', 'reforge_result'];

  return conversationalTypes.includes(entry.node_type) ||
         (entry.node_type === 'system' && conversationalSystemRoles.includes(entry.role)) ||
         validationTypes.includes(entry.node_type) ||
         soundingsTypes.includes(entry.node_type);
};

export const filterEntriesByViewMode = (entries, viewMode, showStructural = false) => {
  if (viewMode === 'all') {
    return showStructural ? entries : entries.filter(e => !isStructural(e));
  } else if (viewMode === 'conversation') {
    return entries.filter(e => isConversational(e));
  } else if (viewMode === 'structural') {
    return entries.filter(e => isStructural(e));
  }
  return entries;
};

export const groupEntriesByCell = (entries) => {
  const grouped = [];
  let currentCell = null;
  let currentSoundingIndex = null;
  let currentGroup = null;

  entries.forEach((entry, idx) => {
    const cellName = entry.cell_name || 'Initialization';
    const soundingIndex = entry.candidate_index;

    // Start new cell group when EITHER cell name OR sounding index changes
    if (cellName !== currentCell || soundingIndex !== currentSoundingIndex) {
      if (currentGroup) {
        grouped.push(currentGroup);
      }
      currentCell = cellName;
      currentSoundingIndex = soundingIndex;
      currentGroup = {
        cell: cellName,
        entries: [],
        totalCost: 0,
        soundingIndex: soundingIndex
      };
    }

    // Add entry to current group with time gap info
    const enrichedEntry = { ...entry };

    // Calculate time gap from previous entry
    if (idx > 0) {
      const prevEntry = entries[idx - 1];
      const timeDiff = entry.timestamp - prevEntry.timestamp;
      enrichedEntry.timeDiff = timeDiff;
    }

    if (currentGroup) {
      currentGroup.entries.push(enrichedEntry);
      if (entry.cost) {
        currentGroup.totalCost += entry.cost;
      }
    }
  });

  // Add final group
  if (currentGroup) {
    grouped.push(currentGroup);
  }

  return grouped;
};

export const formatCost = (cost) => {
  if (!cost || cost === 0) return '$0';
  if (cost < 0.001) return `$${cost.toFixed(6)}`;
  if (cost < 0.01) return `$${cost.toFixed(5)}`;
  if (cost < 0.1) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
};

export const formatTimestamp = (timestamp) => {
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString();
};

export const getDirectionBadge = (entry) => {
  // SENT to LLM
  if (entry.node_type === 'user' ||
      (entry.node_type === 'system' && entry.role === 'system')) {
    return { label: '→ SENT', className: 'sent' };
  }

  // RECEIVED from LLM
  if (entry.node_type === 'agent' ||
      entry.node_type === 'assistant' ||
      entry.role === 'agent' ||
      entry.role === 'assistant') {
    return { label: '← RECEIVED', className: 'received' };
  }

  return null;
};

export const getNodeIcon = (nodeType) => {
  switch (nodeType) {
    case 'user':
      return 'mdi:account';
    case 'agent':
    case 'assistant':
      return 'mdi:robot';
    case 'tool_call':
      return 'mdi:hammer-wrench';
    case 'tool_result':
      return 'mdi:check-circle';
    case 'injection':
      return 'mdi:image-multiple';
    case 'system':
      return 'mdi:cog';
    case 'cell_start':
      return 'mdi:play-circle';
    case 'cell_complete':
      return 'mdi:check-circle-outline';
    case 'error':
      return 'mdi:alert-circle';
    case 'cost_update':
      return 'mdi:currency-usd';
    case 'validation':
    case 'validation_start':
    case 'validation_error':
    case 'validation_retry':
      return 'mdi:shield-check';
    case 'pre_ward':
    case 'post_ward':
    case 'ward_blocking':
    case 'ward_retry':
    case 'ward_advisory':
      return 'mdi:shield-alert';
    case 'sub_cascade_ref':
    case 'sub_cascade_start':
    case 'sub_cascade_complete':
      return 'mdi:file-tree';
    case 'evaluation':
    case 'evaluator':
    case 'sounding_evaluation':
      return 'mdi:scale-balance';
    case 'soundings_result':
    case 'sounding_attempt':
      return 'mdi:chart-tree';
    case 'soundings_start':
      return 'mdi:chart-multiple';
    case 'reforge_start':
    case 'reforge_result':
      return 'mdi:hammer';
    default:
      return 'mdi:message';
  }
};

export const getNodeColor = (nodeType) => {
  switch (nodeType) {
    case 'user':
      return '#60a5fa'; // Blue
    case 'agent':
    case 'assistant':
      return '#a78bfa'; // Purple
    case 'tool_call':
    case 'tool_result':
      return '#f472b6'; // Pink
    case 'injection':
      return '#34d399'; // Green (images injected into context)
    case 'system':
      return '#666'; // Gray
    case 'cell_start':
    case 'cell_complete':
      return '#34d399'; // Green
    case 'error':
    case 'validation_error':
      return '#f87171'; // Red
    case 'cost_update':
      return '#34d399'; // Green
    case 'validation':
    case 'validation_start':
    case 'validation_retry':
      return '#fbbf24'; // Yellow
    case 'pre_ward':
    case 'post_ward':
    case 'ward_blocking':
    case 'ward_retry':
    case 'ward_advisory':
      return '#60a5fa'; // Blue (wards)
    case 'sub_cascade_ref':
    case 'sub_cascade_start':
    case 'sub_cascade_complete':
      return '#a78bfa'; // Purple (sub-cascades)
    case 'evaluation':
    case 'evaluator':
    case 'sounding_evaluation':
      return '#fbbf24'; // Yellow (evaluation/decision)
    case 'soundings_result':
    case 'sounding_attempt':
      return '#fb923c'; // Orange (soundings)
    case 'soundings_start':
      return '#fb923c'; // Orange
    case 'reforge_start':
    case 'reforge_result':
      return '#fb923c'; // Orange (reforge)
    default:
      return '#666';
  }
};
