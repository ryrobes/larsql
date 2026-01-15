import React, { useMemo, useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import InputLayer from './components/InputLayer';
import ContextLayer from './components/ContextLayer';
import WardsLayer from './components/WardsLayer';
import CandidatesLayer from './components/CandidatesLayer';
import ParetoLayer from './components/ParetoLayer';
import ConvergenceSection from './components/ConvergenceSection';
import ReforgeLayer from './components/ReforgeLayer';
import OutputLayer from './components/OutputLayer';
import SummaryBar from './components/SummaryBar';
import LayerDivider from './components/LayerDivider';
import './CellAnatomyPanel.css';

/**
 * CellAnatomyPanel - Visualizes the internal structure of a WRVBBITcell
 *
 * Shows all the machinery inside a cell:
 * - Entry: Context injection, pre-wards
 * - Candidates: Parallel execution lanes with turns
 * - Convergence: Evaluator, pre-validator
 * - Reforge: Iterative refinement loop
 * - Exit: Post-wards, output extraction
 *
 * Two modes:
 * - Spec mode: Shows cell configuration (what CAN happen)
 * - Execution mode: Shows actual execution data (what DID happen)
 */
const CellAnatomyPanel = ({ cell, cellLogs = [], cellState = {}, onClose, cascadeAnalytics, cellAnalytics }) => {
  // Derive execution data from logs
  const executionData = useMemo(() => {
    if (!cellLogs || cellLogs.length === 0) return null;

    // Group logs by candidate index
    const candidates = {};
    let winnerIndex = null;
    let reforgeData = null;
    const toolCalls = [];
    const wardResults = { pre: [], post: [] };
    let evaluatorResult = null;
    let manifestSelection = null; // Quartermaster auto-tool selection

    // Helper to parse timestamp
    const parseTs = (ts) => {
      if (!ts) return null;
      return new Date(ts).getTime();
    };

    // Helper to parse metadata_json
    const parseMetadata = (meta) => {
      if (!meta) return {};
      if (typeof meta === 'string') {
        try { return JSON.parse(meta); } catch { return {}; }
      }
      return meta;
    };

    for (const log of cellLogs) {
      const metadata = parseMetadata(log.metadata_json);

      // Track winning candidate (check both old and new field names)
      const logWinner = log.winner_index ?? log.winning_candidate_index ?? metadata.winner_index;
      if (logWinner !== null && logWinner !== undefined && logWinner >= 0) {
        winnerIndex = logWinner;
      }

      // Extract evaluator result (role === 'evaluator' or node_type === 'evaluator')
      if (log.role === 'evaluator' || log.node_type === 'evaluator') {
        let content = log.content_json;
        if (typeof content === 'string') {
          try { content = JSON.parse(content); } catch {}
        }
        evaluatorResult = {
          content: typeof content === 'string' ? content : (content?.content || content?.reasoning || JSON.stringify(content)),
          winnerIndex: log.winning_candidate_index,
          model: log.model,
          timestamp: log.timestamp_iso
        };
      }

      // Group by candidate - prefer top-level candidate_index, fall back to metadata
      // Use explicit null/undefined check since log.candidate_index may be null
      let candidateIdx = (log.candidate_index !== null && log.candidate_index !== undefined)
        ? log.candidate_index
        : metadata.candidate_index;

      // For non-candidate cells (factor=1), logs won't have candidate_index
      // Use index 0 as fallback for relevant execution logs
      const isExecutionLog = ['assistant', 'tool_call', 'structure', 'tool', 'cell_complete', 'error'].includes(log.role) ||
                             ['agent', 'turn', 'tool_call', 'tool_result'].includes(log.node_type);
      if ((candidateIdx === null || candidateIdx === undefined) && isExecutionLog) {
        candidateIdx = 0; // Virtual candidate for non-candidate cells
      }

      if (candidateIdx !== null && candidateIdx !== undefined && candidateIdx >= 0) {
        if (!candidates[candidateIdx]) {
          candidates[candidateIdx] = {
            index: candidateIdx,
            turns: [],
            toolCalls: [],
            model: null,
            mutation: null,
            cost: 0,
            duration: 0,
            status: 'running',
            firstTs: null,
            lastTs: null
          };
        }

        const candidate = candidates[candidateIdx];

        // Track timestamps for duration calculation
        const logTs = parseTs(log.timestamp_iso);
        if (logTs) {
          if (!candidate.firstTs || logTs < candidate.firstTs) candidate.firstTs = logTs;
          if (!candidate.lastTs || logTs > candidate.lastTs) candidate.lastTs = logTs;
        }

        // Track turns from structure/turn markers OR from metadata.turn_number
        const turnNumber = metadata.turn_number;
        if (turnNumber !== null && turnNumber !== undefined && turnNumber >= 0) {
          // Use 0-indexed (turn_number starts at 1 in logs)
          const turnIdx = turnNumber > 0 ? turnNumber - 1 : 0;
          while (candidate.turns.length <= turnIdx) {
            candidate.turns.push({
              index: candidate.turns.length,
              toolCalls: [],
              validationResult: null,
              status: 'pending',
              duration: 0,
              firstTs: null,
              lastTs: null
            });
          }

          const turn = candidate.turns[turnIdx];

          // Track turn timestamps
          if (logTs) {
            if (!turn.firstTs || logTs < turn.firstTs) turn.firstTs = logTs;
            if (!turn.lastTs || logTs > turn.lastTs) turn.lastTs = logTs;
          }

          // Mark turn as used when we see a turn structure marker
          if (log.node_type === 'turn') {
            turn.status = 'running';
          }
        }

        // Track tool calls (role='tool_call' or node_type='tool_call')
        if (log.role === 'tool_call' || log.node_type === 'tool_call') {
          const toolName = metadata.tool_name || 'unknown';
          candidate.toolCalls.push(toolName);

          // Add to current turn if we know which turn
          const turnNumber = metadata.turn_number;
          let turnIdx = 0;
          if (turnNumber !== null && turnNumber !== undefined && turnNumber >= 0) {
            turnIdx = turnNumber > 0 ? turnNumber - 1 : 0;
          }

          // Ensure turn exists
          if (!candidate.turns[turnIdx]) {
            while (candidate.turns.length <= turnIdx) {
              candidate.turns.push({
                index: candidate.turns.length,
                toolCalls: [],
                validationResult: null,
                status: 'running',
                duration: 0,
                firstTs: null,
                lastTs: null
              });
            }
          }

          candidate.turns[turnIdx].toolCalls.push({
            name: toolName,
            duration: log.duration_ms
          });
        }

        // Mark turn complete on assistant response
        if (log.role === 'assistant' && log.node_type === 'agent') {
          // Find the current turn and mark it complete
          const turnNumber = metadata.turn_number;
          if (turnNumber !== null && turnNumber !== undefined && turnNumber >= 0) {
            const turnIdx = turnNumber > 0 ? turnNumber - 1 : 0;
            if (candidate.turns[turnIdx]) {
              candidate.turns[turnIdx].status = 'complete';
              if (log.duration_ms) {
                candidate.turns[turnIdx].duration += parseFloat(log.duration_ms);
              }
            }
          } else {
            // No explicit turn_number - create/update turn 0 as fallback
            if (candidate.turns.length === 0) {
              candidate.turns.push({
                index: 0,
                toolCalls: [],
                validationResult: null,
                status: 'complete',
                duration: log.duration_ms ? parseFloat(log.duration_ms) : 0,
                firstTs: null,
                lastTs: null
              });
            } else {
              // Mark last turn as complete
              const lastTurn = candidate.turns[candidate.turns.length - 1];
              lastTurn.status = 'complete';
              if (log.duration_ms) {
                lastTurn.duration += parseFloat(log.duration_ms);
              }
            }
          }
        }

        // Track model
        if (log.model) {
          candidate.model = log.model;
        }

        // Track mutation type (stored as direct column, not in metadata_json)
        // Set it whenever we see it in the log (overwrites if already set)
        if (log.mutation_type) {
          candidate.mutation = log.mutation_type;
        }

        // Accumulate cost
        if (log.cost) candidate.cost += parseFloat(log.cost);

        // Track completion from candidate_attempt or cell_complete
        if (log.role === 'candidate_attempt' || log.node_type === 'candidate_attempt') {
          // Mark all turns as complete
          candidate.status = 'complete';
          candidate.turns.forEach(t => { if (t.status === 'running') t.status = 'complete'; });
        }
        if (log.role === 'cell_complete') {
          candidate.status = 'complete';
        }
        if (log.role === 'error') {
          candidate.status = 'error';
        }
      }

      // Track tool calls globally
      if (log.role === 'tool_call' || log.node_type === 'tool_call') {
        const toolName = metadata.tool_name || 'unknown';
        const toolSoundingIdx = (log.candidate_index !== null && log.candidate_index !== undefined)
          ? log.candidate_index
          : metadata.candidate_index;
        toolCalls.push({
          name: toolName,
          candidate: toolSoundingIdx,
          turn: metadata.turn_number,
          duration: log.duration_ms
        });
      }

      // Track ward results (pre_ward, post_ward node types)
      if (log.node_type === 'pre_ward' || log.node_type === 'post_ward' || log.role === 'ward') {
        // Ward data is in metadata_json: valid, reason, mode, validator
        const wardResult = {
          name: metadata.validator || metadata.tool_name || 'validator',
          status: metadata.valid === true ? 'passed' :
                  metadata.valid === false ? 'failed' : 'unknown',
          mode: metadata.mode || 'blocking',
          reason: metadata.reason || null
        };

        // Determine if pre or post ward based on node_type or ward_type
        if (log.node_type === 'pre_ward' || metadata.ward_type === 'pre') {
          wardResults.pre.push(wardResult);
        } else {
          wardResults.post.push(wardResult);
        }
      }

      // Track loop_until validation results (role='validation', node_type='validation')
      if (log.role === 'validation' && log.node_type === 'validation') {
        // Validation data is in metadata_json: valid, reason, validator, attempt, max_attempts
        const validationResult = {
          validator: metadata.validator || 'validator',
          valid: metadata.valid,
          reason: metadata.reason || null,
          attempt: metadata.attempt || 1,
          maxAttempts: metadata.max_attempts || 1,
          timestamp: log.timestamp_iso
        };

        // Associate with the current turn in candidate 0 (or the active candidate)
        const targetCandidate = candidates[0];
        if (targetCandidate && targetCandidate.turns.length > 0) {
          const lastTurn = targetCandidate.turns[targetCandidate.turns.length - 1];
          lastTurn.validationResult = validationResult;
          // Mark as early exit if validation passed
          if (validationResult.valid) {
            lastTurn.validationPassed = true;
          }
        }
      }

      // Track reforge steps
      if (log.reforge_step !== null && log.reforge_step !== undefined) {
        if (!reforgeData) {
          reforgeData = { steps: [] };
        }
        // Add reforge tracking here
      }

      // Track quartermaster/manifest selection (role='quartermaster', node_type='quartermaster_result')
      if (log.role === 'quartermaster' || log.node_type === 'quartermaster_result') {
        // Manifest data is in metadata_json: selected_skills, model, manifest_context
        manifestSelection = {
          selectedTools: metadata.selected_skills || metadata.selected_tackle || [],
          model: metadata.model || log.model || null,
          context: metadata.manifest_context || 'current',
          timestamp: log.timestamp_iso
        };
      }
    }

    // Calculate durations from timestamps for candidates and turns
    const candidatesList = Object.values(candidates);
    for (const candidate of candidatesList) {
      // Candidate duration from first to last timestamp
      if (candidate.firstTs && candidate.lastTs) {
        candidate.duration = candidate.lastTs - candidate.firstTs;
      }
      // Turn durations
      for (const turn of candidate.turns) {
        if (turn.firstTs && turn.lastTs && !turn.duration) {
          turn.duration = turn.lastTs - turn.firstTs;
        }
      }
    }

    return {
      candidates: candidatesList,
      winnerIndex,
      toolCalls,
      wardResults,
      reforgeData,
      evaluatorResult,
      manifestSelection,
      hasCandidates: candidatesList.length > 0
    };
  }, [cellLogs]);

  // Determine mode based on whether we have execution data
  const hasExecutionData = executionData && executionData.hasCandidates;

  // Fetch Pareto frontier data if available
  const [paretoData, setParetoData] = useState(null);

  useEffect(() => {
    // Extract session_id from cellLogs
    const sessionId = cellLogs.length > 0 ? cellLogs[0].session_id : null;

    if (!sessionId || !cell?.name) {
      setParetoData(null);
      return;
    }

    // Fetch pareto data from API
    const fetchParetoData = async () => {
      try {
        const response = await fetch(`http://localhost:5050/api/pareto/${sessionId}`);
        if (response.ok) {
          const data = await response.json();
          // Only set if this pareto data matches the current cell
          if (data.has_pareto && data.cell_name === cell.name) {
            setParetoData(data);
          } else {
            setParetoData(null);
          }
        } else {
          setParetoData(null);
        }
      } catch (error) {
        console.error('[CellAnatomyPanel] Failed to fetch pareto data:', error);
        setParetoData(null);
      }
    };

    fetchParetoData();
  }, [cellLogs, cell?.name]);

  // Extract cell configuration
  const cellConfig = useMemo(() => ({
    // Inputs schema
    inputsSchema: cell?.inputs_schema || {},

    // Context configuration
    context: cell?.context || null,

    // Pre-wards
    preWards: cell?.wards?.pre || [],

    // Post-wards
    postWards: cell?.wards?.post || [],

    // Candidates configuration
    candidates: cell?.candidates || null,
    factor: cell?.candidates?.factor || 1,
    mutate: cell?.candidates?.mutate || false,
    models: cell?.candidates?.models || null,
    evaluator: cell?.candidates?.evaluator_instructions || null,
    preValidator: cell?.candidates?.validator || null,
    mode: cell?.candidates?.mode || 'evaluate',

    // Reforge configuration
    reforge: cell?.candidates?.reforge || null,

    // Rules
    maxTurns: cell?.rules?.max_turns || 1,
    maxAttempts: cell?.rules?.max_attempts || 1,
    loopUntil: cell?.rules?.loop_until || null,

    // Skills (tools)
    skills: cell?.skills || [],

    // Output configuration
    outputSchema: cell?.output_schema || null,
    outputExtraction: cell?.output_extraction || null,
    callouts: cell?.callouts || null,

    // Handoffs
    handoffs: cell?.handoffs || [],

    // LLM config
    model: cell?.model || null,
    instructions: cell?.instructions || null,

    // Deterministic
    tool: cell?.tool || null
  }), [cell]);

  const isLLMCell = !cellConfig.tool && cellConfig.instructions;
  const isDeterministic = !!cellConfig.tool;

  return (
    <div className="cell-anatomy-panel">
      {/* Header */}
      <div className="cell-anatomy-header">
        <div className="cell-anatomy-header-left">
          <Icon icon="mdi:cpu" width="18" className="cell-anatomy-icon" />
          <span className="cell-anatomy-title">Cell Anatomy</span>
          <span className="cell-anatomy-name">{cell?.name || 'Unknown'}</span>
          {isLLMCell && (
            <span className="cell-anatomy-type cell-anatomy-type-llm">
              <Icon icon="mdi:robot" width="12" />
              LLM
            </span>
          )}
          {isDeterministic && (
            <span className="cell-anatomy-type cell-anatomy-type-deterministic">
              <Icon icon="mdi:cog" width="12" />
              Deterministic
            </span>
          )}
        </div>
        <div className="cell-anatomy-header-right">
          <span className={`cell-anatomy-mode ${hasExecutionData ? 'execution' : 'spec'}`}>
            <Icon icon={hasExecutionData ? "mdi:play-circle" : "mdi:file-document-outline"} width="14" />
            {hasExecutionData ? 'Execution' : 'Spec'}
          </span>
          {onClose && (
            <button className="cell-anatomy-close" onClick={onClose}>
              <Icon icon="mdi:close" width="16" />
            </button>
          )}
        </div>
      </div>

      {/* Body - Layered Structure */}
      <div className="cell-anatomy-body">
        {/* Input Layer */}
        <InputLayer
          inputsSchema={cellConfig.inputsSchema}
          instructions={cellConfig.instructions}
          tool={cellConfig.tool}
        />

        {/* Context Layer */}
        {cellConfig.context && (
          <>
            <LayerDivider type="minor" />
            <ContextLayer context={cellConfig.context} />
          </>
        )}

        {/* Pre-Wards Layer */}
        {cellConfig.preWards.length > 0 && (
          <>
            <LayerDivider type="minor" />
            <WardsLayer
              type="pre"
              wards={cellConfig.preWards}
              results={executionData?.wardResults?.pre}
            />
          </>
        )}

        <LayerDivider type="major" label="Execution Chamber" />

        {/* Candidates Layer - The Main Event */}
        <CandidatesLayer
          config={cellConfig}
          execution={executionData}
          isLLMCell={isLLMCell}
        />

        {/* Pareto Frontier Layer - Cost vs Quality Analysis */}
        {paretoData && (
          <ParetoLayer paretoData={paretoData} />
        )}

        {/* Convergence Section (inside Candidates visual) */}
        {(cellConfig.factor > 1 || cellConfig.preValidator || cellConfig.evaluator) && (
          <ConvergenceSection
            config={cellConfig}
            winnerIndex={executionData?.winnerIndex}
            mode={cellConfig.mode}
            evaluatorResult={executionData?.evaluatorResult}
          />
        )}

        <LayerDivider type="major" />

        {/* Reforge Layer */}
        {cellConfig.reforge && (
          <>
            <ReforgeLayer
              config={cellConfig.reforge}
              execution={executionData?.reforgeData}
            />
            <LayerDivider type="major" />
          </>
        )}

        {/* Post-Wards Layer */}
        {cellConfig.postWards.length > 0 && (
          <>
            <WardsLayer
              type="post"
              wards={cellConfig.postWards}
              results={executionData?.wardResults?.post}
            />
            <LayerDivider type="minor" />
          </>
        )}

        {/* Output Layer */}
        <OutputLayer
          outputSchema={cellConfig.outputSchema}
          outputExtraction={cellConfig.outputExtraction}
          callouts={cellConfig.callouts}
          handoffs={cellConfig.handoffs}
          result={cellState?.result}
        />
      </div>

      {/* Summary Bar */}
      <SummaryBar
        cellState={cellState}
        executionData={executionData}
        config={cellConfig}
        cascadeAnalytics={cascadeAnalytics}
        cellAnalytics={cellAnalytics}
      />
    </div>
  );
};

export default CellAnatomyPanel;
