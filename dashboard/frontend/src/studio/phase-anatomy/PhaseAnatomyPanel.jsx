import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import InputLayer from './components/InputLayer';
import ContextLayer from './components/ContextLayer';
import WardsLayer from './components/WardsLayer';
import SoundingsLayer from './components/SoundingsLayer';
import ConvergenceSection from './components/ConvergenceSection';
import ReforgeLayer from './components/ReforgeLayer';
import OutputLayer from './components/OutputLayer';
import SummaryBar from './components/SummaryBar';
import LayerDivider from './components/LayerDivider';
import './PhaseAnatomyPanel.css';

/**
 * PhaseAnatomyPanel - Visualizes the internal structure of a Windlass phase
 *
 * Shows all the machinery inside a phase:
 * - Entry: Context injection, pre-wards
 * - Soundings: Parallel execution lanes with turns
 * - Convergence: Evaluator, pre-validator
 * - Reforge: Iterative refinement loop
 * - Exit: Post-wards, output extraction
 *
 * Two modes:
 * - Spec mode: Shows phase configuration (what CAN happen)
 * - Execution mode: Shows actual execution data (what DID happen)
 */
const PhaseAnatomyPanel = ({ phase, phaseLogs = [], cellState = {}, onClose }) => {
  // Derive execution data from logs
  const executionData = useMemo(() => {
    if (!phaseLogs || phaseLogs.length === 0) return null;

    // Group logs by sounding index
    const soundings = {};
    let winnerIndex = null;
    let reforgeData = null;
    const toolCalls = [];
    const wardResults = { pre: [], post: [] };
    let evaluatorResult = null;

    // Helper to parse timestamp
    const parseTs = (ts) => {
      if (!ts) return null;
      return new Date(ts).getTime();
    };

    for (const log of phaseLogs) {
      // Track winning sounding
      if (log.winning_sounding_index !== null && log.winning_sounding_index !== undefined) {
        winnerIndex = log.winning_sounding_index;
      }

      // Extract evaluator result (role === 'evaluator' or node_type === 'evaluator')
      if (log.role === 'evaluator' || log.node_type === 'evaluator') {
        let content = log.content_json;
        if (typeof content === 'string') {
          try { content = JSON.parse(content); } catch {}
        }
        evaluatorResult = {
          content: typeof content === 'string' ? content : (content?.content || content?.reasoning || JSON.stringify(content)),
          winnerIndex: log.winning_sounding_index,
          model: log.model,
          timestamp: log.timestamp_iso
        };
      }

      // Group by sounding
      if (log.sounding_index !== null && log.sounding_index !== undefined) {
        if (!soundings[log.sounding_index]) {
          soundings[log.sounding_index] = {
            index: log.sounding_index,
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

        const sounding = soundings[log.sounding_index];

        // Track timestamps for duration calculation
        const logTs = parseTs(log.timestamp_iso);
        if (logTs) {
          if (!sounding.firstTs || logTs < sounding.firstTs) sounding.firstTs = logTs;
          if (!sounding.lastTs || logTs > sounding.lastTs) sounding.lastTs = logTs;
        }

        // Track turns
        if (log.turn_number !== null && log.turn_number !== undefined) {
          const turnIdx = log.turn_number;
          while (sounding.turns.length <= turnIdx) {
            sounding.turns.push({
              index: sounding.turns.length,
              toolCalls: [],
              validationResult: null,
              status: 'pending',
              duration: 0,
              firstTs: null,
              lastTs: null
            });
          }

          const turn = sounding.turns[turnIdx];

          // Track turn timestamps
          if (logTs) {
            if (!turn.firstTs || logTs < turn.firstTs) turn.firstTs = logTs;
            if (!turn.lastTs || logTs > turn.lastTs) turn.lastTs = logTs;
          }

          if (log.role === 'tool') {
            sounding.turns[turnIdx].toolCalls.push({
              name: log.tool_name || 'unknown',
              duration: log.duration_ms
            });
            sounding.toolCalls.push(log.tool_name || 'unknown');
            // Accumulate duration per turn (if available)
            if (log.duration_ms) {
              sounding.turns[turnIdx].duration += parseFloat(log.duration_ms);
            }
          }

          if (log.role === 'assistant' || log.role === 'phase_complete') {
            sounding.turns[turnIdx].status = 'complete';
            // Track LLM call duration for this turn (if available)
            if (log.duration_ms) {
              sounding.turns[turnIdx].duration += parseFloat(log.duration_ms);
            }
          }
        }

        // Track model
        if (log.model) {
          sounding.model = log.model;
        }

        // Accumulate cost
        if (log.cost) sounding.cost += parseFloat(log.cost);

        // Track completion
        if (log.role === 'phase_complete') {
          sounding.status = 'complete';
        }
        if (log.role === 'error') {
          sounding.status = 'error';
        }
      }

      // Track tool calls globally
      if (log.role === 'tool' && log.tool_name) {
        toolCalls.push({
          name: log.tool_name,
          sounding: log.sounding_index,
          turn: log.turn_number,
          duration: log.duration_ms
        });
      }

      // Track ward results
      if (log.node_type === 'ward' || log.role === 'ward') {
        const wardResult = {
          name: log.tool_name || 'validator',
          status: log.content_json?.valid === true ? 'passed' :
                  log.content_json?.valid === false ? 'failed' : 'unknown',
          mode: log.metadata_json?.mode || 'blocking',
          reason: log.content_json?.reason
        };

        // Determine if pre or post ward based on timing/position
        if (log.metadata_json?.position === 'pre') {
          wardResults.pre.push(wardResult);
        } else {
          wardResults.post.push(wardResult);
        }
      }

      // Track reforge steps
      if (log.reforge_step !== null && log.reforge_step !== undefined) {
        if (!reforgeData) {
          reforgeData = { steps: [] };
        }
        // Add reforge tracking here
      }
    }

    // Calculate durations from timestamps for soundings and turns
    const soundingsList = Object.values(soundings);
    for (const sounding of soundingsList) {
      // Sounding duration from first to last timestamp
      if (sounding.firstTs && sounding.lastTs) {
        sounding.duration = sounding.lastTs - sounding.firstTs;
      }
      // Turn durations
      for (const turn of sounding.turns) {
        if (turn.firstTs && turn.lastTs && !turn.duration) {
          turn.duration = turn.lastTs - turn.firstTs;
        }
      }
    }

    return {
      soundings: soundingsList,
      winnerIndex,
      toolCalls,
      wardResults,
      reforgeData,
      evaluatorResult,
      hasSoundings: soundingsList.length > 0
    };
  }, [phaseLogs]);

  // Determine mode based on whether we have execution data
  const hasExecutionData = executionData && executionData.hasSoundings;

  // Extract phase configuration
  const phaseConfig = useMemo(() => ({
    // Inputs schema
    inputsSchema: phase?.inputs_schema || {},

    // Context configuration
    context: phase?.context || null,

    // Pre-wards
    preWards: phase?.wards?.pre || [],

    // Post-wards
    postWards: phase?.wards?.post || [],

    // Soundings configuration
    soundings: phase?.soundings || null,
    factor: phase?.soundings?.factor || 1,
    mutate: phase?.soundings?.mutate || false,
    models: phase?.soundings?.models || null,
    evaluator: phase?.soundings?.evaluator_instructions || null,
    preValidator: phase?.soundings?.validator || null,
    mode: phase?.soundings?.mode || 'evaluate',

    // Reforge configuration
    reforge: phase?.soundings?.reforge || null,

    // Rules
    maxTurns: phase?.rules?.max_turns || 1,
    maxAttempts: phase?.rules?.max_attempts || 1,
    loopUntil: phase?.rules?.loop_until || null,

    // Tackle (tools)
    tackle: phase?.tackle || [],

    // Output configuration
    outputSchema: phase?.output_schema || null,
    outputExtraction: phase?.output_extraction || null,
    callouts: phase?.callouts || null,

    // Handoffs
    handoffs: phase?.handoffs || [],

    // LLM config
    model: phase?.model || null,
    instructions: phase?.instructions || null,

    // Deterministic
    tool: phase?.tool || null
  }), [phase]);

  const isLLMPhase = !phaseConfig.tool && phaseConfig.instructions;
  const isDeterministic = !!phaseConfig.tool;

  return (
    <div className="phase-anatomy-panel">
      {/* Header */}
      <div className="phase-anatomy-header">
        <div className="phase-anatomy-header-left">
          <Icon icon="mdi:cpu" width="18" className="phase-anatomy-icon" />
          <span className="phase-anatomy-title">Phase Anatomy</span>
          <span className="phase-anatomy-name">{phase?.name || 'Unknown'}</span>
          {isLLMPhase && (
            <span className="phase-anatomy-type phase-anatomy-type-llm">
              <Icon icon="mdi:robot" width="12" />
              LLM
            </span>
          )}
          {isDeterministic && (
            <span className="phase-anatomy-type phase-anatomy-type-deterministic">
              <Icon icon="mdi:cog" width="12" />
              Deterministic
            </span>
          )}
        </div>
        <div className="phase-anatomy-header-right">
          <span className={`phase-anatomy-mode ${hasExecutionData ? 'execution' : 'spec'}`}>
            <Icon icon={hasExecutionData ? "mdi:play-circle" : "mdi:file-document-outline"} width="14" />
            {hasExecutionData ? 'Execution' : 'Spec'}
          </span>
          {onClose && (
            <button className="phase-anatomy-close" onClick={onClose}>
              <Icon icon="mdi:close" width="16" />
            </button>
          )}
        </div>
      </div>

      {/* Body - Layered Structure */}
      <div className="phase-anatomy-body">
        {/* Input Layer */}
        <InputLayer
          inputsSchema={phaseConfig.inputsSchema}
          instructions={phaseConfig.instructions}
          tool={phaseConfig.tool}
        />

        {/* Context Layer */}
        {phaseConfig.context && (
          <>
            <LayerDivider type="minor" />
            <ContextLayer context={phaseConfig.context} />
          </>
        )}

        {/* Pre-Wards Layer */}
        {phaseConfig.preWards.length > 0 && (
          <>
            <LayerDivider type="minor" />
            <WardsLayer
              type="pre"
              wards={phaseConfig.preWards}
              results={executionData?.wardResults?.pre}
            />
          </>
        )}

        <LayerDivider type="major" label="Execution Chamber" />

        {/* Soundings Layer - The Main Event */}
        <SoundingsLayer
          config={phaseConfig}
          execution={executionData}
          isLLMPhase={isLLMPhase}
        />

        {/* Convergence Section (inside Soundings visual) */}
        {(phaseConfig.factor > 1 || phaseConfig.preValidator || phaseConfig.evaluator) && (
          <ConvergenceSection
            config={phaseConfig}
            winnerIndex={executionData?.winnerIndex}
            mode={phaseConfig.mode}
            evaluatorResult={executionData?.evaluatorResult}
          />
        )}

        <LayerDivider type="major" />

        {/* Reforge Layer */}
        {phaseConfig.reforge && (
          <>
            <ReforgeLayer
              config={phaseConfig.reforge}
              execution={executionData?.reforgeData}
            />
            <LayerDivider type="major" />
          </>
        )}

        {/* Post-Wards Layer */}
        {phaseConfig.postWards.length > 0 && (
          <>
            <WardsLayer
              type="post"
              wards={phaseConfig.postWards}
              results={executionData?.wardResults?.post}
            />
            <LayerDivider type="minor" />
          </>
        )}

        {/* Output Layer */}
        <OutputLayer
          outputSchema={phaseConfig.outputSchema}
          outputExtraction={phaseConfig.outputExtraction}
          callouts={phaseConfig.callouts}
          handoffs={phaseConfig.handoffs}
          result={cellState?.result}
        />
      </div>

      {/* Summary Bar */}
      <SummaryBar
        cellState={cellState}
        executionData={executionData}
        config={phaseConfig}
      />
    </div>
  );
};

export default PhaseAnatomyPanel;
