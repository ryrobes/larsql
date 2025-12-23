import React, { memo, useCallback, useState, useRef, useEffect, useMemo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';
import usePlaygroundStore from '../../stores/playgroundStore';
import useNodeResize from '../hooks/useNodeResize';
import RichMarkdown from '../../../components/RichMarkdown';
import PhaseExplosionView from '../PhaseExplosionView';
import './PhaseCard.css';

// Default dimensions (grid-aligned to 16px)
const DEFAULT_WIDTH = 320;
const DEFAULT_HEIGHT = 288;

// Default YAML template
const DEFAULT_YAML = `name: llm_transform
instructions: |
  {{ input.prompt }}
model: google/gemini-2.5-flash-lite
rules:
  max_turns: 1
`;

// Pattern to discover {{ input.X }} references
const INPUT_PATTERN_STR = '\\{\\{\\s*input\\.(\\w+)(?:\\s*\\|[^}]*)?\\s*\\}\\}';

/**
 * Derive rarity from phase configuration
 */
function deriveRarity(parsedYaml, status) {
  if (status === 'error') return 'broken';
  if (!parsedYaml?.soundings) return 'common';
  if (parsedYaml.soundings.mode === 'aggregate') return 'legendary';
  if (parsedYaml.soundings.reforge) return 'rare';
  return 'uncommon';
}

/**
 * Derive model element from model string
 */
function deriveModelElement(model) {
  if (!model) return 'local';
  const m = model.toLowerCase();
  if (m.includes('claude') || m.includes('anthropic')) return 'anthropic';
  if (m.includes('gpt') || m.includes('openai')) return 'openai';
  if (m.includes('gemini') || m.includes('google')) return 'google';
  if (m.includes('mistral')) return 'mistral';
  if (m.includes('grok') || m.includes('xai')) return 'xai';
  return 'local';
}

/**
 * Get stack depth from soundings factor + reforge steps
 * NOTE: All soundings (S0, S1, S2...) are separate runs that fan out.
 * The main card shows the winner's output, not any specific sounding.
 */
function getStackDepth(soundingsFactor, reforgeSteps = 0) {
  // All soundings are shown in the stack (S0, S1, S2...)
  const soundingsDepth = soundingsFactor > 0 ? soundingsFactor : 0;
  const reforgeDepth = reforgeSteps || 0;
  // Total depth is soundings + reforge, max 10
  return Math.min(10, soundingsDepth + reforgeDepth);
}

/**
 * PhaseCard - Two-sided card node for LLM phases
 *
 * Front: Output/execution preview
 * Back: YAML configuration editor
 *
 * Features:
 * - Flip animation between front/back
 * - Stacked deck effect for soundings
 * - Rarity frames based on complexity
 * - Model element border colors
 */
function PhaseCard({ id, data, selected }) {
  const removeNode = usePlaygroundStore((state) => state.removeNode);
  const updateNodeData = usePlaygroundStore((state) => state.updateNodeData);
  const runFromNode = usePlaygroundStore((state) => state.runFromNode);
  const lastSuccessfulSessionId = usePlaygroundStore((state) => state.lastSuccessfulSessionId);
  const executionStatus = usePlaygroundStore((state) => state.executionStatus);

  const editorRef = useRef(null);
  const monacoRef = useRef(null);
  const cardRef = useRef(null);

  // Card state
  const [isFlipped, setIsFlipped] = useState(false); // false = front (output), true = back (yaml)
  const [isFlipping, setIsFlipping] = useState(false); // true during flip animation
  const [isTilted, setIsTilted] = useState(false); // true when tilted to reveal actions
  const [isFanned, setIsFanned] = useState(false); // true when stack is fanned out for peek
  const [localYaml, setLocalYaml] = useState(data.yaml || DEFAULT_YAML);
  const [parseError, setParseError] = useState(null);
  const [discoveredInputs, setDiscoveredInputs] = useState(data.discoveredInputs || []);
  const [isDirty, setIsDirty] = useState(false);

  // Explosion view state
  const [showExplosion, setShowExplosion] = useState(false);
  const [explosionOriginRect, setExplosionOriginRect] = useState(null);

  // Track last synced value
  const lastSyncedYamlRef = useRef(data.yaml);

  // Track content for per-card update detection
  const prevContentCountRef = useRef({ soundings: new Set(), reforge: new Set() });

  // Editable name state
  const [isEditingName, setIsEditingName] = useState(false);
  const [editingNameValue, setEditingNameValue] = useState('');
  const nameInputRef = useRef(null);

  const {
    status = 'idle',
    output = '',
    liveLog = [],            // Scrolling log during execution: [{ id, label, content, isWinner, soundingIndex, reforgeStep }]
    finalOutput = '',        // Clean winner output after completion
    lastStatusMessage = '',  // Short status message for footer display
    cost,
    duration,
    width: dataWidth,
    height: dataHeight,
    name: customName,
    // Soundings execution state
    soundingsProgress = [],  // Array of { index, status: 'pending'|'running'|'complete'|'error', output?: string }
    winnerIndex = null,      // Which sounding won (0-based)
    currentReforgeStep = 0,  // Current reforge step (1-based when running)
    totalReforgeSteps = 0,   // Total reforge steps
    soundingsOutputs = {},   // Map of sounding index to output content { 0: "...", 1: "...", ... }
    reforgeOutputs = {},     // Flattened reforge outputs: step -> winner content
  } = data;

  // Parse YAML for phase config
  const parsedYaml = useMemo(() => {
    try {
      return yaml.load(localYaml);
    } catch {
      return null;
    }
  }, [localYaml]);

  // Derive display properties
  const phaseName = parsedYaml?.name || 'llm_phase';
  const displayName = customName || phaseName || 'LLM Phase';
  const rarity = deriveRarity(parsedYaml, status);
  const modelElement = deriveModelElement(parsedYaml?.model);
  const soundingsFactor = parsedYaml?.soundings?.factor || 0;
  const hasReforge = !!parsedYaml?.soundings?.reforge;
  const reforgeSteps = parsedYaml?.soundings?.reforge?.steps || 0;
  const stackDepth = getStackDepth(soundingsFactor, reforgeSteps);
  const isAggregate = parsedYaml?.soundings?.mode === 'aggregate';

  // Mutation traits - show Iconify icons in header corner
  const hasMutate = parsedYaml?.soundings?.mutate;
  const mutationMode = parsedYaml?.soundings?.mutation_mode; // 'rewrite' | 'augment' | 'approach'
  const mutationTraits = [];
  if (hasMutate || mutationMode) {
    // All mutation modes use DNA icon
    mutationTraits.push({
      iconName: 'mdi:dna',
      mode: mutationMode || 'default',
      tooltip: mutationMode
        ? `Mutation: ${mutationMode} mode`
        : 'Mutations enabled'
    });
  }
  // Check for multi-model
  const hasMultiModel = parsedYaml?.soundings?.models && (
    Array.isArray(parsedYaml.soundings.models) ||
    typeof parsedYaml.soundings.models === 'object'
  );
  if (hasMultiModel) {
    mutationTraits.push({ iconName: 'mdi:robot-outline', mode: 'multimodel', tooltip: 'Multi-model soundings' });
  }

  // Dimensions
  const width = dataWidth || DEFAULT_WIDTH;
  const height = dataHeight || DEFAULT_HEIGHT;

  // Resize hook
  const { onResizeStart } = useNodeResize(id, {
    minWidth: 256,
    minHeight: 192,
    maxWidth: 640,
    maxHeight: 576,
  });

  // Discover input references
  const discoverInputs = useCallback((yamlString) => {
    const pattern = new RegExp(INPUT_PATTERN_STR, 'g');
    const matches = [...yamlString.matchAll(pattern)];
    return [...new Set(matches.map(m => m[1]))];
  }, []);

  // Sync when external changes occur (use editor ref for uncontrolled Monaco)
  useEffect(() => {
    if (data.yaml && data.yaml !== lastSyncedYamlRef.current) {
      // Only sync if editor exists and value is truly external
      if (editorRef.current) {
        const currentValue = editorRef.current.getValue();
        if (data.yaml !== currentValue) {
          editorRef.current.setValue(data.yaml);
          lastSyncedYamlRef.current = data.yaml;
          setDiscoveredInputs(discoverInputs(data.yaml));
          setParseError(null);
          setIsDirty(false);
        }
      }
    }
  }, [data.yaml, discoverInputs]);

  // Debounce ref for store updates
  const storeUpdateTimeoutRef = useRef(null);

  // Handle YAML changes - Monaco is uncontrolled, debounce store sync
  const handleYamlChange = useCallback((newValue) => {
    // Mark dirty immediately
    setIsDirty(true);
    lastSyncedYamlRef.current = newValue;

    // Debounce store updates to avoid excessive re-renders
    if (storeUpdateTimeoutRef.current) {
      clearTimeout(storeUpdateTimeoutRef.current);
    }
    storeUpdateTimeoutRef.current = setTimeout(() => {
      // Parse YAML and update store
      try {
        const parsed = yaml.load(newValue);
        setParseError(null);
        const inputs = discoverInputs(newValue);
        setDiscoveredInputs(inputs);
        setLocalYaml(newValue); // Update for display purposes (name, rarity, etc.)

        updateNodeData(id, {
          yaml: newValue,
          parsedPhase: parsed,
          discoveredInputs: inputs,
        });
      } catch (err) {
        setParseError(err.message);
      }
    }, 300);
  }, [id, updateNodeData, discoverInputs]);

  // Cleanup debounce timeout on unmount
  useEffect(() => {
    return () => {
      if (storeUpdateTimeoutRef.current) {
        clearTimeout(storeUpdateTimeoutRef.current);
      }
    };
  }, []);

  // Initialize on mount
  useEffect(() => {
    const inputs = discoverInputs(localYaml);
    setDiscoveredInputs(inputs);
    if (!data.yaml) {
      updateNodeData(id, {
        yaml: localYaml,
        discoveredInputs: inputs,
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Track which stack cards recently got updates (for highlight effect)
  const [recentlyUpdated, setRecentlyUpdated] = useState(new Set());
  // Track per-card update timestamps to manage individual timeouts
  const cardUpdateTimesRef = useRef({});

  // Detect when specific soundings/reforge cards get new content and highlight them
  useEffect(() => {
    const now = Date.now();
    const newlyUpdated = new Set();

    // Check soundings
    Object.keys(soundingsOutputs).forEach(idx => {
      const key = `S${idx}`;
      if (!prevContentCountRef.current.soundings?.has(idx)) {
        newlyUpdated.add(key);
        cardUpdateTimesRef.current[key] = now;
      }
    });

    // Check reforge
    Object.keys(reforgeOutputs).forEach(step => {
      const key = `R${step}`;
      if (!prevContentCountRef.current.reforge?.has(step)) {
        newlyUpdated.add(key);
        cardUpdateTimesRef.current[key] = now;
      }
    });

    if (newlyUpdated.size > 0) {
      setRecentlyUpdated(prev => new Set([...prev, ...newlyUpdated]));
    }

    // Update tracking
    prevContentCountRef.current = {
      soundings: new Set(Object.keys(soundingsOutputs)),
      reforge: new Set(Object.keys(reforgeOutputs)),
    };
  }, [soundingsOutputs, reforgeOutputs]);

  // Separate effect to clear old updates - runs on interval, not tied to content changes
  useEffect(() => {
    const ANIMATION_DURATION = 2000;

    const checkAndClear = () => {
      const now = Date.now();
      const stillActive = new Set();

      for (const [key, time] of Object.entries(cardUpdateTimesRef.current)) {
        if (now - time < ANIMATION_DURATION) {
          stillActive.add(key);
        } else {
          delete cardUpdateTimesRef.current[key];
        }
      }

      setRecentlyUpdated(prev => {
        // Only update if different
        if (prev.size !== stillActive.size || [...prev].some(k => !stillActive.has(k))) {
          return stillActive;
        }
        return prev;
      });
    };

    // Check every 500ms
    const interval = setInterval(checkAndClear, 500);

    return () => clearInterval(interval);
  }, []);

  // Clear all animations when phase completes
  useEffect(() => {
    if (status === 'completed' || status === 'idle') {
      setRecentlyUpdated(new Set());
      cardUpdateTimesRef.current = {};
    }
  }, [status]);

  // Card flip handler - triggered by right-click on header
  const handleFlip = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();

    // Start flipping animation
    setIsFlipping(true);
    setIsFlipped(prev => !prev);
    setIsTilted(false); // Untilt when flipping

    // Clear flipping state after animation completes (600ms)
    setTimeout(() => {
      setIsFlipping(false);
    }, 600);
  }, []);

  // Tilt toggle - click to tilt, click again or click action to untilt
  const handleTiltToggle = useCallback((e) => {
    e.stopPropagation();
    if (!isFlipping) {
      setIsTilted(prev => !prev);
      setIsFanned(false); // Close fan when tilting
    }
  }, [isFlipping]);

  // Fan toggle - click stack to fan out cards for quick peek
  const handleFanToggle = useCallback((e) => {
    e.stopPropagation();
    if (!isFlipping && stackDepth > 0) {
      setIsFanned(prev => !prev);
      setIsTilted(false); // Close tilt when fanning
    }
  }, [isFlipping, stackDepth]);

  // Explosion view - double-click to explode cards into 3D view
  const handleOpenExplosion = useCallback((e) => {
    e.stopPropagation();
    if (stackDepth > 0 && cardRef.current) {
      // Capture card's current screen position as animation origin
      const rect = cardRef.current.getBoundingClientRect();
      setExplosionOriginRect(rect);
      setShowExplosion(true);
      setIsFanned(false); // Close fan when exploding
      setIsTilted(false); // Close tilt when exploding
    }
  }, [stackDepth]);

  const handleCloseExplosion = useCallback(() => {
    setShowExplosion(false);
  }, []);

  // Delete handler - untilts then deletes
  const handleDelete = useCallback((e) => {
    e.stopPropagation();
    setIsTilted(false);
    // Small delay so user sees the untilt before deletion
    setTimeout(() => removeNode(id), 100);
  }, [id, removeNode]);

  // Run from here - untilts then runs
  const handleRunFromHere = useCallback(async (e) => {
    e.stopPropagation();
    setIsTilted(false);
    const result = await runFromNode(id);
    if (!result.success) {
      console.error('[PhaseCard] Run from here failed:', result.error);
    }
  }, [id, runFromNode]);

  const canRunFromHere = lastSuccessfulSessionId && executionStatus !== 'running';

  // Name editing handlers
  const startEditingName = useCallback((e) => {
    e.stopPropagation();
    setEditingNameValue(customName || '');
    setIsEditingName(true);
  }, [customName]);

  const saveName = useCallback(() => {
    const trimmedName = editingNameValue.trim();
    if (trimmedName && /^[a-zA-Z][a-zA-Z0-9_]*$/.test(trimmedName)) {
      updateNodeData(id, { name: trimmedName });
    }
    setIsEditingName(false);
  }, [id, editingNameValue, updateNodeData]);

  const cancelEditingName = useCallback(() => {
    setIsEditingName(false);
  }, []);

  const handleNameKeyDown = useCallback((e) => {
    e.stopPropagation();
    if (e.key === 'Enter') saveName();
    else if (e.key === 'Escape') cancelEditingName();
  }, [saveName, cancelEditingName]);

  useEffect(() => {
    if (isEditingName && nameInputRef.current) {
      nameInputRef.current.focus();
      nameInputRef.current.select();
    }
  }, [isEditingName]);

  // Monaco editor config
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
    });
  }, []);

  const handleEditorWillMount = useCallback((monaco) => {
    monaco.editor.defineTheme('windlass-phase', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'key', foreground: '79c0ff' },
        { token: 'string', foreground: '9be9a8' },
        { token: 'string.yaml', foreground: '9be9a8' },
        { token: 'number', foreground: 'd2a8ff' },
        { token: 'keyword', foreground: 'ff9eb8' },
        { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
      ],
      colors: {
        'editor.background': '#000000',
        'editor.foreground': '#e6edf3',
        'editor.lineHighlightBackground': '#161b22',
        'editor.selectionBackground': '#264f78',
        'editorLineNumber.foreground': '#6e7681',
        'editorLineNumber.activeForeground': '#e6edf3',
        'editorCursor.foreground': '#79c0ff',
        'editorIndentGuide.background': '#21262d',
        'editorGutter.background': '#000000',
      },
    });
  }, []);

  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 11,
    fontFamily: "'Google Sans Code', 'Menlo', 'Ubuntu Mono', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    renderLineHighlightOnlyWhenFocus: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    foldingStrategy: 'indentation',
    padding: { top: 8, bottom: 8 },
    scrollbar: {
      vertical: 'auto',
      horizontal: 'hidden',
      verticalScrollbarSize: 8,
    },
  };

  // Format helpers
  const formatCost = (cost) => {
    if (!cost) return null;
    if (cost < 0.01) return '<$0.01';
    return `$${cost.toFixed(3)}`;
  };

  const formatDuration = (ms) => {
    if (!ms) return null;
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const statusConfig = {
    idle: { icon: 'mdi:circle-outline', label: 'Ready', className: 'idle' },
    pending: { icon: 'mdi:clock-outline', label: 'Pending', className: 'pending' },
    running: { icon: 'mdi:loading', label: 'Running...', className: 'running' },
    soundings_running: { icon: 'mdi:cards-outline', label: 'Soundings...', className: 'soundings_running' },
    evaluating: { icon: 'mdi:scale-balance', label: 'Evaluating...', className: 'evaluating' },
    winner_selected: { icon: 'mdi:trophy', label: 'Winner!', className: 'winner_selected' },
    reforge_running: { icon: 'mdi:auto-fix', label: 'Reforging...', className: 'reforge_running' },
    aggregate_running: { icon: 'mdi:merge', label: 'Fusing...', className: 'aggregate_running' },
    completed: { icon: 'mdi:check-circle', label: 'Done', className: 'completed' },
    error: { icon: 'mdi:alert-circle', label: 'Error', className: 'error' },
  };

  const statusInfo = statusConfig[status] || statusConfig.idle;
  const formattedCost = formatCost(cost);
  const formattedDuration = formatDuration(duration);
  // Show footer during any soundings-related status or when completed with soundings
  const showFooter = status === 'completed' || soundingsFactor > 0 ||
    ['soundings_running', 'evaluating', 'winner_selected', 'reforge_running', 'aggregate_running'].includes(status);

  // Build class names
  const cardClasses = [
    'phase-card',
    `rarity-${rarity}`,
    `model-${modelElement}`,
    `status-${status}`,
    selected ? 'selected' : '',
    isFlipped ? 'flipped' : '',
    isFlipping ? 'is-flipping' : '',
    isTilted ? 'is-tilted' : '',
    isFanned ? 'is-fanned' : '',
    hasReforge ? 'has-reforge' : '',
    stackDepth > 0 ? `stack-${stackDepth}` : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      ref={cardRef}
      className={cardClasses}
      style={{
        width,
        height,
        '--card-width': `${width}px`,
        '--card-height': `${height}px`,
      }}
      onDoubleClick={handleOpenExplosion}
    >
      {/* Stacked deck edges (behind the card) - click to fan */}
      {stackDepth > 0 && (
        <div
          className="stack-click-zone"
          onClick={handleFanToggle}
          title={isFanned ? "Click to collapse" : `Click to fan out (${stackDepth} cards)`}
        />
      )}
      {/* Render stack edges dynamically - each is a mini card preview */}
      {/* Soundings are S0, S1, S2... ; Reforge steps are R1, R2... */}
      {Array.from({ length: Math.min(stackDepth, 10) }, (_, i) => {
        const idx = i + 1; // CSS class index (stack-edge-1, stack-edge-2, etc.)
        const isReforgeCard = hasReforge && i >= soundingsFactor;
        const soundingIndex = isReforgeCard ? null : i; // 0-based for display (S0, S1, S2...)
        const reforgeStep = isReforgeCard ? i - soundingsFactor + 1 : null;

        // Get progress status for this card (soundings array is 0-indexed)
        const cardProgress = soundingsProgress.find(p => p.index === soundingIndex);
        const progressStatus = cardProgress?.status || 'pending';
        const isRunning = progressStatus === 'running';
        const isComplete = progressStatus === 'complete';
        const isWinner = winnerIndex !== null && soundingIndex === winnerIndex;
        const isLoser = winnerIndex !== null && soundingIndex !== null && !isWinner && isComplete;

        // Get output content for this card
        // Soundings use soundingsOutputs[index], Reforge uses reforgeOutputs[step]
        const cardOutput = isReforgeCard
          ? reforgeOutputs[reforgeStep]
          : soundingsOutputs[soundingIndex];
        const hasContent = !!cardOutput;

        // Reforge cards are "running" if currentReforgeStep === reforgeStep
        const isReforgeRunning = isReforgeCard && currentReforgeStep === reforgeStep;
        const isReforgeComplete = isReforgeCard && reforgeStep < currentReforgeStep;

        // Check if this card was recently updated
        const cardKey = isReforgeCard ? `R${reforgeStep}` : `S${soundingIndex}`;
        const isRecentlyUpdated = recentlyUpdated.has(cardKey);

        return (
          <div
            key={`stack-${idx}`}
            className={[
              'stack-edge',
              `stack-edge-${idx}`,
              isReforgeCard ? 'reforge-card' : 'sounding-card',
              isWinner ? 'is-winner' : '',
              isRecentlyUpdated ? 'just-updated' : '',
              isLoser ? 'is-loser' : '',
              isRunning || isReforgeRunning ? 'is-running' : '',
              isComplete || isReforgeComplete ? 'is-complete' : '',
            ].filter(Boolean).join(' ')}
          >
            <div className="stack-card-preview">
              <div className="stack-card-header">
                {isReforgeCard ? `R${reforgeStep}` : `S${soundingIndex}`}
              </div>
              {/* Content preview when available - full content, CSS handles overflow */}
              {hasContent && (
                <div className="stack-card-content">
                  <RichMarkdown>{String(cardOutput || '')}</RichMarkdown>
                </div>
              )}
              {/* Progress indicator during execution */}
              {!isReforgeCard && (status === 'soundings_running' || status === 'evaluating') && (
                <div className={`stack-card-progress ${progressStatus}`} />
              )}
              {isReforgeCard && isReforgeRunning && (
                <div className="stack-card-progress running" />
              )}
            </div>
          </div>
        );
      })}

      {/* Tilt zone - click to toggle tilt and reveal actions */}
      <div
        className="card-tilt-zone"
        onClick={handleTiltToggle}
        title={isTilted ? "Click card to close" : "Click for actions"}
      />

      {/* Actions tray - revealed when tilted */}
      <div className="card-actions-tray">
        <button
          className="tray-action action-delete"
          onClick={handleDelete}
          title="Delete phase"
        >
          <Icon icon="mdi:trash-can-outline" width="14" />
        </button>
        {canRunFromHere && (
          <button
            className="tray-action action-run"
            onClick={handleRunFromHere}
            title="Run from here"
          >
            <Icon icon="mdi:play" width="14" />
          </button>
        )}
      </div>

      {/* Winner badge - shown when winner is selected or after completion */}
      {winnerIndex !== null && (status === 'winner_selected' || status === 'completed') && (
        <div className="winner-badge" title={`Winner: S${winnerIndex}`}>
          S{winnerIndex}★
        </div>
      )}

      {/* Evaluator indicator - shown during evaluation */}
      {status === 'evaluating' && (
        <div className="evaluator-indicator" title="Evaluating soundings...">
          <Icon icon="mdi:scale-balance" width="20" />
        </div>
      )}

      {/* Fusion symbol - shown during aggregate mode */}
      {status === 'aggregate_running' && (
        <div className="fusion-symbol" title="Fusing outputs...">
          ∞
        </div>
      )}

      {/* Input handles - outside the flipper so they don't rotate */}
      <Handle
        type="target"
        position={Position.Left}
        id="image-in"
        className="card-handle input-handle handle-image"
        style={{ top: '15%' }}
        title="Image input"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="text-in"
        className="card-handle input-handle handle-text"
        style={{ top: '50%' }}
        title="Text input"
      />

      {/* Output handle - outside the flipper so it doesn't rotate */}
      <Handle
        type="source"
        position={Position.Right}
        id="text-out"
        className="card-handle output-handle handle-text"
        title="Text output"
      />

      {/* 3D Card flip container */}
      <div
        className="card-scene"
        onClick={isTilted ? handleTiltToggle : (isFanned ? handleFanToggle : undefined)}
        style={(isTilted || isFanned) ? { cursor: 'pointer' } : undefined}
      >
        <div className={`card-flipper ${isFlipped ? 'is-flipped' : ''}`}>
          {/* FRONT: Output/Execution view */}
          <div className="card-face card-front">
            {/* Header - right-click to flip */}
            <div
              className="card-header"
              onContextMenu={handleFlip}
              title="Right-click to edit YAML"
            >
              <div className="card-icon">
                <Icon icon="mdi:cards-playing-outline" width="16" />
              </div>
              {isEditingName ? (
                <input
                  ref={nameInputRef}
                  type="text"
                  className="card-name-input nodrag"
                  value={editingNameValue}
                  onChange={(e) => setEditingNameValue(e.target.value)}
                  onBlur={saveName}
                  onKeyDown={handleNameKeyDown}
                  placeholder="Enter name..."
                />
              ) : (
                <span
                  className="card-title"
                  onDoubleClick={startEditingName}
                  title="Double-click to rename, right-click to edit YAML"
                >
                  {displayName}
                </span>
              )}
              {/* Mutation trait icons */}
              {mutationTraits.length > 0 && (
                <div className="card-traits">
                  {mutationTraits.map((trait, idx) => (
                    <span
                      key={idx}
                      className={`trait-icon trait-${trait.mode}`}
                      title={trait.tooltip}
                    >
                      <Icon icon={trait.iconName} width="12" />
                    </span>
                  ))}
                </div>
              )}
              <div className={`card-status ${statusInfo.className}`}>
                <Icon
                  icon={statusInfo.icon}
                  width="14"
                  className={['running', 'soundings_running', 'evaluating', 'reforge_running', 'aggregate_running'].includes(status) ? 'spinning' : ''}
                />
              </div>
            </div>

            {/* Content area - shows live log during execution, final output when done */}
            <div className="card-content">
              {/* Idle state - no execution yet */}
              {status === 'idle' && !output && !finalOutput && liveLog.length === 0 && (
                <div className="card-idle-state">
                  <Icon icon="mdi:play-circle-outline" width="32" />
                  <span>Ready to execute</span>
                </div>
              )}
              {/* Pending/waiting state - waiting for upstream phases */}
              {status === 'pending' && (
                <div className="card-waiting-state">
                  <Icon icon="mdi:clock-outline" width="28" />
                  <span>Waiting...</span>
                </div>
              )}
              {/* Live log during execution - simple scrolling log, newest at top */}
              {['running', 'soundings_running', 'evaluating', 'reforge_running', 'aggregate_running', 'winner_selected'].includes(status) && (
                <div className="card-live-log">
                  {liveLog.length === 0 ? (
                    <div className="card-running-state">
                      <Icon icon="mdi:loading" width="24" className="spinning" />
                      <span>Executing...</span>
                    </div>
                  ) : (
                    <div className="live-log-scroll">
                      {/* Reverse order - newest first */}
                      {[...liveLog].reverse().map((entry) => (
                        <div
                          key={entry.id}
                          className={`log-row ${entry.isWinner ? 'winner' : ''}`}
                        >
                          <span className="log-label">{entry.label || '•'}</span>
                          <span className="log-text">
                            {String(entry.content || '').slice(0, 80)}
                            {String(entry.content || '').length > 80 ? '…' : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* Final output after completion - show full winner content */}
              {status === 'completed' && (
                <div className="card-output-preview">
                  {(finalOutput || output) ? (
                    <RichMarkdown>{String(finalOutput || output)}</RichMarkdown>
                  ) : liveLog.length > 0 ? (
                    // Fallback: show last live log entry if no explicit output
                    <RichMarkdown>{String(liveLog[liveLog.length - 1]?.content || 'Completed')}</RichMarkdown>
                  ) : (
                    <span className="text-muted">Completed</span>
                  )}
                </div>
              )}
              {status === 'error' && (
                <div className="card-error-state">
                  <Icon icon="mdi:alert-circle" width="32" />
                  <span>Execution failed</span>
                </div>
              )}
            </div>

            {/* Footer */}
            {showFooter && (
              <div className="card-footer">
                <div className="footer-left">
                  {/* Soundings running - show progress */}
                  {status === 'soundings_running' && (
                    <span className="footer-indicator soundings-indicator">
                      <Icon icon="mdi:cards-outline" width="12" className="spinning" />
                      {soundingsProgress.filter(p => p.status === 'complete').length}/{soundingsFactor}
                    </span>
                  )}
                  {/* Evaluating - show evaluator indicator */}
                  {status === 'evaluating' && (
                    <span className="footer-indicator evaluating-indicator">
                      <Icon icon="mdi:scale-balance" width="12" className="spinning" />
                      Evaluating...
                    </span>
                  )}
                  {/* Winner selected - show winner (also after completion) */}
                  {winnerIndex !== null && (status === 'winner_selected' || status === 'completed') && (
                    <span className="footer-indicator winner-indicator">
                      S{winnerIndex}★
                    </span>
                  )}
                  {/* Reforge running - show step progress */}
                  {status === 'reforge_running' && (
                    <span className="footer-indicator reforge-running-indicator">
                      <Icon icon="mdi:auto-fix" width="12" className="spinning" />
                      R{currentReforgeStep}/{totalReforgeSteps || reforgeSteps}
                    </span>
                  )}
                  {/* Aggregate running */}
                  {status === 'aggregate_running' && (
                    <span className="footer-indicator aggregate-indicator">
                      <Icon icon="mdi:merge" width="12" className="spinning" />
                      Fusing...
                    </span>
                  )}
                  {/* Status message during running states */}
                  {lastStatusMessage && ['running', 'soundings_running', 'evaluating', 'reforge_running', 'aggregate_running', 'winner_selected'].includes(status) && (
                    <span className="footer-indicator status-message" title={lastStatusMessage}>
                      {lastStatusMessage.slice(0, 30)}{lastStatusMessage.length > 30 ? '…' : ''}
                    </span>
                  )}
                  {/* Idle or completed - show config summary */}
                  {(status === 'idle' || status === 'completed') && soundingsFactor > 0 && (
                    <span className="footer-indicator soundings-indicator" title={`${soundingsFactor} soundings`}>
                      {isAggregate ? '∞' : `★${soundingsFactor}`}
                    </span>
                  )}
                  {(status === 'idle' || status === 'completed') && hasReforge && (
                    <span className="footer-indicator reforge-indicator" title={`${reforgeSteps} reforge steps`}>
                      {'◆'.repeat(Math.min(reforgeSteps, 3))}
                    </span>
                  )}
                </div>
                <div className="footer-right">
                  {formattedDuration && (
                    <span className="footer-stat duration">
                      {formattedDuration}
                    </span>
                  )}
                  {formattedCost && (
                    <span className="footer-stat cost">
                      {formattedCost}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* BACK: YAML Editor view */}
          <div className="card-face card-back">
            {/* Back header - right-click to flip back */}
            <div
              className="card-header card-header-back"
              onContextMenu={handleFlip}
              title="Right-click to show output"
            >
              <div className="card-icon">
                <Icon icon="mdi:code-braces" width="16" />
              </div>
              <span className="card-title">{displayName}</span>
              {parseError && (
                <div className="card-parse-error" title={parseError}>
                  <Icon icon="mdi:alert" width="14" />
                </div>
              )}
            </div>

            {/* Monaco Editor */}
            <div
              className="card-editor-container nodrag"
              onKeyDown={(e) => e.stopPropagation()}
              onKeyUp={(e) => e.stopPropagation()}
              onKeyPress={(e) => e.stopPropagation()}
            >
              <Editor
                key={`editor-${id}`}
                height="100%"
                defaultLanguage="yaml"
                defaultValue={localYaml}
                onChange={handleYamlChange}
                onMount={handleEditorDidMount}
                beforeMount={handleEditorWillMount}
                theme="windlass-phase"
                options={editorOptions}
                loading={
                  <div className="editor-loading">
                    <Icon icon="mdi:loading" width="16" className="spinning" />
                  </div>
                }
              />
            </div>
          </div>
        </div>
      </div>

      {/* Resize handle */}
      <div
        className="card-resize-handle nodrag"
        onPointerDown={onResizeStart}
      />

      {/* Explosion view - rendered as portal when active */}
      {showExplosion && explosionOriginRect && (
        <PhaseExplosionView
          phaseData={{
            name: displayName,
            soundingsProgress,
            soundingsOutputs,
            reforgeOutputs,
            winnerIndex,
            currentReforgeStep,
            totalReforgeSteps: totalReforgeSteps || reforgeSteps, // Use execution state or fall back to config
            // Extract evaluator reasoning from liveLog
            evaluatorReasoning: (() => {
              // Look for evaluator messages in liveLog
              const evalLog = liveLog.find(e =>
                e.content &&
                typeof e.content === 'string' &&
                (e.content.toLowerCase().includes('winner') ||
                 e.content.toLowerCase().includes('best') ||
                 e.content.toLowerCase().includes('pick'))
              );
              return evalLog?.content || '';
            })(),
            aggregatorReasoning: liveLog.find(e =>
              e.content &&
              typeof e.content === 'string' &&
              e.content.toLowerCase().includes('aggregate')
            )?.content || '',
            parsedPhase: parsedYaml,
            liveLog, // Pass full log for debugging
          }}
          originRect={explosionOriginRect}
          onClose={handleCloseExplosion}
        />
      )}
    </div>
  );
}

export default memo(PhaseCard);
