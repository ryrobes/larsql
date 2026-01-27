import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import html2canvas from 'html2canvas';
import CanvasRenderer from './components/CanvasRenderer';
import GridLayoutEditor from './components/GridLayoutEditor';
import ParamsPanel from './components/ParamsPanel';
import SqlFileModal from './components/SqlFileModal';
import CaptureOverlay from './components/CaptureOverlay';
import IntentReviewModal from './components/IntentReviewModal';
import TabBar from './components/TabBar';
import CostBadges from './components/CostBadges';
import CostAnalysisDashboard from './components/CostAnalysisDashboard';
import { useTabs, parseTabNameFromSql } from './hooks/useTabs';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount } from '../../studio/utils/monacoTheme';
import { API_BASE_URL } from '../../config/api';
import { getAuthHeaders } from '../../stores/authStore';
import { fillCascadeTemplate } from './utils/cascadeTemplate';
import { injectRenderDimensions } from './utils/sqlPanelLayout';
import { useQueryExplain } from './hooks/useQueryExplain';
import { useQueryViewZones } from './hooks/useQueryViewZones';
import { parsePanelMetadata, generateGridLayout, extractParamInfo } from './utils/panelParser';
import { parseQueries, hashQuery } from './utils/querySplitter';
// import PanelSkeleton from './components/PanelSkeleton'; // Kept for future use
import './CanvasView.css';
//import { fontFamily } from 'html2canvas/dist/types/css/property-descriptors/font-family';

// Default example query demonstrating SQL-native chart specs
const DEFAULT_QUERY = `--- HYPER 'Sales Dashboard'
-- SQL-Native Charts Demo with Interactive Filters
-- ON_SELECT[] = multi-select (checkboxes), ON_SELECT = single-select (click row)
-- Charts use format + config columns - data comes from the query itself

SELECT * FROM (VALUES
  ('Jan', 'Electronics', 12400, 89),
  ('Jan', 'Clothing', 8200, 156),
  ('Jan', 'Food', 15600, 423),
  ('Feb', 'Electronics', 14100, 102),
  ('Feb', 'Clothing', 9800, 178),
  ('Feb', 'Food', 14200, 398),
  ('Mar', 'Electronics', 15800, 118),
  ('Mar', 'Clothing', 11200, 201),
  ('Mar', 'Food', 16800, 445),
  ('Apr', 'Electronics', 13900, 95),
  ('Apr', 'Clothing', 12400, 223),
  ('Apr', 'Food', 18200, 489)
) AS t(month, category, revenue, units)
 THEN PASS INTO shared_sales;

--- PANEL 'Click a Slice' (1, 1, 1, 1) ON_SELECT @param_set('cat', label) HIDE_TITLE
SELECT
  'plotly' as format,
  {type: 'pie', values: 'total', labels: 'category', title: 'By Category'} as config,
  category, SUM(revenue) as total
FROM into_shared_sales GROUP BY category;

--- PANEL 'Click a Bar' (2, 1, 1, 1) ON_SELECT @param_set('month', month) HIDE_TITLE
SELECT
  'vega-lite' as format,
  {mark: 'bar', x: 'month', y: 'total', title: 'By Month'} as config,
  month, SUM(revenue) as total
FROM into_shared_sales GROUP BY month;

--- PANEL 'Monthly Trend' (1, 2, 1, 1)
SELECT
  'vega-lite' as format,
  {mark: 'line', x: 'month', y: 'total_revenue', title: 'Monthly Revenue'} as config,
  month, SUM(revenue) as total_revenue
FROM into_shared_sales
WHERE (CASE WHEN @param_get('cat') IS NULL THEN true ELSE category = @param_get('cat') END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END)
GROUP BY month;

--- PANEL 'Category Breakdown' (2, 2, 1, 1)
SELECT
  'vega-lite' as format,
  {
    mark: {type: 'bar', cornerRadius: 4},
    encoding: {
      x: {field: 'category', type: 'nominal', axis: {labelAngle: 0}},
      y: {field: 'revenue', type: 'quantitative', title: 'Revenue ($)'},
      color: {field: 'category', type: 'nominal', legend: null}
    }
  } as config,
  category, SUM(revenue) as revenue
FROM into_shared_sales
WHERE (CASE WHEN @param_get('cat') IS NULL THEN true ELSE category = @param_get('cat') END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END)
GROUP BY category;

--- PANEL 'Stacked Area' (1, 3, 2, 1) HIDE_BORDER HIDE_TITLE
SELECT
  'vega-lite' as format,
  {
    mark: 'area',
    encoding: {
      x: {field: 'month', type: 'ordinal'},
      y: {field: 'revenue', type: 'quantitative', stack: 'zero'},
      color: {field: 'category', type: 'nominal'}
    },
    title: 'Revenue Over Time'
  } as config,
  month, category, revenue
FROM into_shared_sales
WHERE (CASE WHEN @param_get('cat') IS NULL THEN true ELSE category = @param_get('cat') END)
  AND (CASE WHEN @param_get('month') IS NULL THEN true ELSE month = @param_get('month') END);`;

/**
 * HyperView - Hypermedia SQL Client
 *
 * A SQL-native HATEOAS system where queries return self-describing data.
 * The UI interprets the response format and renders accordingly.
 */
const CanvasView = () => {
  // Tab management
  const {
    tabs,
    activeTab,
    activeTabId,
    updateActiveTab,
    switchTab,
    addTab,
    closeTab,
    renameTab,
    openCostAnalysisTab,
    openFileAsTab,
    markDirty,
  } = useTabs(DEFAULT_QUERY);

  // Core state - now derived from/synced with active tab
  const [sql, setSqlState] = useState(activeTab.sql);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [executionTime, setExecutionTime] = useState(null);
  const [databases, setDatabases] = useState([
    { name: 'memory', type: 'memory' },
    { name: 'workspace', type: 'persistent' },
  ]);
  const [selectedDatabase, setSelectedDatabase] = useState('memory');
  const [lastExecutionCallerId, setLastExecutionCallerId] = useState(null);
  const [_partialResults, setPartialResults] = useState(new Map()); // Map<queryIndex, resultData> - setter used for clearing
  const [soloRenderMode, setSoloRenderMode] = useState('naked'); // 'naked' or 'rendered'

  // Panel-based execution state (for parallel execution)
  const [panelLayout, setPanelLayout] = useState(null); // Parsed panel layout from SQL
  const [panelResults, setPanelResults] = useState(new Map()); // Map<panelIndex, {data, columns, status, error}>
  const [panelExecutionState, setPanelExecutionState] = useState('idle'); // 'idle' | 'setup' | 'executing' | 'complete'
  const [lastSoloQuery, setLastSoloQuery] = useState(null); // Track last solo query for re-run
  const [isSoloResult, setIsSoloResult] = useState(false); // Track if current result is from solo execution
  const [paramValues, setParamValues] = useState({}); // Map of param_key -> value for interactive panel selection state

  // Track if we're in the middle of loading a tab to avoid circular saves
  const isLoadingTabRef = useRef(false);

  // Wrapper for setSql that also updates the active tab and name
  const setSql = useCallback((newSql) => {
    const sqlValue = typeof newSql === 'function' ? newSql(sql) : newSql;
    setSqlState(sqlValue);
    if (!isLoadingTabRef.current && !activeTab.isSystem) {
      // Check if tab name should be updated from HYPER comment
      const parsedName = parseTabNameFromSql(sqlValue);
      const updates = { sql: sqlValue, isDirty: true };

      // Update name if it changed and we don't have a file-based name
      if (parsedName && parsedName !== activeTab.name && !activeTab.fileName) {
        updates.name = parsedName;
      }

      updateActiveTab(updates);
    }
  }, [sql, updateActiveTab, activeTab.isSystem, activeTab.name, activeTab.fileName]);

  // Sync state when tab changes
  const prevTabIdRef = useRef(activeTabId);
  useEffect(() => {
    if (prevTabIdRef.current !== activeTabId) {
      // Tab changed - load the new tab's state
      isLoadingTabRef.current = true;
      setSqlState(activeTab.sql);
      setResult(activeTab.result || null);
      setError(activeTab.error || null);
      setPanelLayout(activeTab.panelLayout || null);
      setPanelResults(activeTab.panelResults || new Map());
      setLastExecutionCallerId(activeTab.lastExecutionCallerId || null);
      setSelectedDatabase(activeTab.database || 'memory');
      // IMPORTANT: Clear param values when switching tabs to prevent
      // old values from being applied to new dashboard's panels
      setParamValues({});
      // Reset interaction counter to prevent in-flight interactions from old tab
      // affecting the new tab's state
      interactionCounterRef.current = 0;
      prevParamKeysRef.current = new Set();
      prevTabIdRef.current = activeTabId;
      // Reset loading flag after a tick
      requestAnimationFrame(() => {
        isLoadingTabRef.current = false;
      });
    }
  }, [activeTabId, activeTab]);

  // Save state back to tab when it changes (skip during tab loading)
  const updateActiveTabRef = useRef(updateActiveTab);
  updateActiveTabRef.current = updateActiveTab;

  useEffect(() => {
    if (!activeTab.isSystem && !isLoadingTabRef.current) {
      updateActiveTabRef.current({
        result,
        error,
        panelLayout,
        panelResults,
        lastExecutionCallerId,
        database: selectedDatabase,
      });
    }
  }, [result, error, panelLayout, panelResults, lastExecutionCallerId, selectedDatabase, activeTab.isSystem]);

  // Params panel state
  const [paramsCollapsed, setParamsCollapsed] = useState(true);
  const [paramsRefreshTrigger, setParamsRefreshTrigger] = useState(0);

  // Editor panel visibility
  const [editorHidden, setEditorHidden] = useState(false);

  // Layout edit mode
  const [layoutEditMode, setLayoutEditMode] = useState(false);

  // Editor ready state - triggers initial explain on mount
  const [editorReady, setEditorReady] = useState(false);

  // SQL Files modal
  const [showFileModal, setShowFileModal] = useState(false);

  // Spacebar capture mode state
  const [captureMode, setCaptureMode] = useState('idle'); // idle | capturing | processing | reviewing | generating
  const [overlayUiHidden, setOverlayUiHidden] = useState(false); // Hide overlay UI but keep strokes for clean screenshot
  const [audioLevel, setAudioLevel] = useState(0);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [capturedScreenshot, setCapturedScreenshot] = useState(null);
  const [capturedTranscript, setCapturedTranscript] = useState('');
  const [capturedStrokes, setCapturedStrokes] = useState([]);

  const editorRef = useRef(null);
  const monacoRef = useRef(null);
  const sqlRef = useRef(sql);
  const queryExplainsRef = useRef(new Map());
  const soloRenderModeRef = useRef(soloRenderMode);
  const executeQueryRef = useRef(null);
  const executeSingleQueryInPositionRef = useRef(null);
  const resultWrapperRef = useRef(null);
  const canvasViewRef = useRef(null);
  const captureOverlayRef = useRef(null);

  // Audio recording refs
  const mediaRecorderRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const animationFrameRef = useRef(null);
  const durationIntervalRef = useRef(null);
  const spacebarDownRef = useRef(false);

  // Track previous panel data for smart re-render diffing
  const prevPanelsRef = useRef({});

  // Track interaction counter for race condition prevention
  const interactionCounterRef = useRef(0);

  // Track setup execution per (database, setupSql) so interactions can re-run panels
  // without re-running setup SQL (THEN PASS INTO materialization, etc.)
  const setupExecutionRef = useRef({ database: null, setupHash: null, completed: false });

  // Track previous param keys to detect dashboard changes
  const prevParamKeysRef = useRef(new Set());

  // Clear param values when panel structure changes (new dashboard pasted)
  // This prevents old param keys from bleeding into new dashboards
  useEffect(() => {
    if (!panelLayout) {
      if (prevParamKeysRef.current.size > 0) {
        setParamValues({});
        prevParamKeysRef.current = new Set();
      }
      return;
    }

    // Get current param keys from panel layout
    const currentKeys = new Set(
      panelLayout.panels
        .map(p => p.param_key)
        .filter(Boolean)
    );

    // Check if the param key set changed (different dashboard)
    const keysChanged = currentKeys.size !== prevParamKeysRef.current.size ||
      ![...currentKeys].every(k => prevParamKeysRef.current.has(k));

    if (keysChanged) {
      console.log('[paramValues] Panel param keys changed, clearing old values');
      console.log('[paramValues] Old keys:', [...prevParamKeysRef.current]);
      console.log('[paramValues] New keys:', [...currentKeys]);
      setParamValues({});
      prevParamKeysRef.current = currentKeys;
    }
  }, [panelLayout]);

  // Fetch current param values for interactive panels
  // This is needed to show selection state in charts/grids when using parallel execution mode
  const fetchParamValues = useCallback(async () => {
    if (!panelLayout) return;

    // Find all unique param keys from interactive panels
    const paramKeys = new Set();
    panelLayout.panels.forEach(panel => {
      if (panel.param_key) {
        paramKeys.add(panel.param_key);
      }
    });

    if (paramKeys.size === 0) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/sql/params/${selectedDatabase}`, {
        headers: getAuthHeaders(),
      });
      const data = await response.json();

      if (data.params && Array.isArray(data.params)) {
        const newParamValues = {};
        data.params.forEach(param => {
          if (paramKeys.has(param.key)) {
            newParamValues[param.key] = param.value;
          }
        });
        setParamValues(newParamValues);
      }
    } catch (err) {
      console.error('Failed to fetch param values:', err);
    }
  }, [panelLayout, selectedDatabase]);

  // Fetch param values ONLY when panel layout changes (new dashboard loaded)
  // Do NOT refetch after interactions - the optimistic update is correct
  // and refetching can cause race conditions with stale server data
  useEffect(() => {
    if (panelLayout) {
      fetchParamValues();
    }
  }, [panelLayout, fetchParamValues]);

  // Auto-explain and cost tracking
  const {
    queryExplains,
    totalEstimatedCost,
    totalActualCost,
    queryCount,
    costPollingStatus,
    operatorCosts,
  } = useQueryExplain({
    editorValue: sql,
    editorRef,
    monacoRef,
    database: selectedDatabase,
    lastExecutionCallerId,
    editorReady,
  });

  // Execute single query and render in position (for panel mode)
  const executeSingleQueryInPositionHandler = useCallback(async (query, panelIdx, sqlToExecute) => {
    setLoading(true);
    setError(null);

    const startTime = Date.now();

    try {
      const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ query: sqlToExecute, database: selectedDatabase })
      });

      const data = await response.json();
      setExecutionTime(Date.now() - startTime);

      if (data.caller_id) {
        setLastExecutionCallerId(data.caller_id);
      }

      if (!data.success) {
        setError(data.error || 'Query execution failed');
        return;
      }

      // Store this panel's result in partial results
      setPartialResults(prev => {
        const updated = new Map(prev);
        updated.set(panelIdx, {
          columns: data.columns,
          data: data.data,
          rowCount: data.row_count,
        });
        return updated;
      });

      console.log('[codelens] Stored partial result for panel', panelIdx, 'at query lines', query.startLine, '-', query.endLine);

    } catch (err) {
      setError(err.message || 'Failed to execute query');
    } finally {
      setLoading(false);
    }
  }, [selectedDatabase]);

  // Fetch available databases on mount
  useEffect(() => {
    const fetchDatabases = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/sql/databases`, {
          headers: getAuthHeaders(),
        });
        const data = await response.json();
        if (data.databases && data.databases.length > 0) {
          setDatabases(data.databases);
        }
      } catch (err) {
        console.error('Failed to fetch databases:', err);
      }
    };
    fetchDatabases();
  }, []);

  // Audio level visualization
  const updateAudioLevel = useCallback(() => {
    if (analyserRef.current && captureMode === 'capturing') {
      const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(dataArray);
      const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      setAudioLevel(Math.min(100, (average / 128) * 100));
      animationFrameRef.current = requestAnimationFrame(updateAudioLevel);
    }
  }, [captureMode]);

  // Start capture mode (spacebar down)
  const startCapture = useCallback(async () => {
    if (captureMode !== 'idle') return;

    setCaptureMode('capturing');
    setAudioLevel(0);
    setRecordingDuration(0);
    audioChunksRef.current = [];

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        }
      });
      streamRef.current = stream;

      // Audio analysis for visualization
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContextRef.current.createMediaStreamSource(stream);
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      source.connect(analyserRef.current);

      // Start level monitoring
      updateAudioLevel();

      // MediaRecorder setup
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.start(100);

      // Duration counter
      durationIntervalRef.current = setInterval(() => {
        setRecordingDuration(prev => prev + 1);
      }, 1000);

    } catch (err) {
      console.error('Failed to start audio capture:', err);
      // Continue without audio - user can still draw and type
    }
  }, [captureMode, updateAudioLevel]);

  // Stop capture mode (spacebar up)
  const stopCapture = useCallback(async () => {
    if (captureMode !== 'capturing') return;

    // Stop audio recording
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }

    // Cleanup audio
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Get strokes from overlay before it unmounts
    const strokes = captureOverlayRef.current?.getStrokes() || [];

    // Step 1: Hide overlay UI but keep strokes visible for clean screenshot
    setOverlayUiHidden(true);
    setAudioLevel(0);

    // Step 2: Wait for repaint, then take screenshot
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    // Capture screenshot of the entire view (now clean - no recording bar/border)
    let screenshotDataUrl = null;
    try {
      if (canvasViewRef.current) {
        const canvas = await html2canvas(canvasViewRef.current, {
          backgroundColor: '#0a0a0f',
          scale: 1,
          logging: false,
          useCORS: true,
        });
        screenshotDataUrl = canvas.toDataURL('image/png');
      }
    } catch (err) {
      console.error('Failed to capture screenshot:', err);
    }

    // Step 3: Now show processing overlay (screenshot is done)
    setOverlayUiHidden(false);
    setCaptureMode('processing');

    // Step 4: Transcribe audio
    let transcript = '';
    if (audioChunksRef.current.length > 0) {
      try {
        const mimeType = mediaRecorderRef.current?.mimeType || 'audio/webm';
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });

        if (audioBlob.size > 0) {
          // Convert to base64
          const reader = new FileReader();
          const base64Promise = new Promise((resolve, reject) => {
            reader.onloadend = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
          });
          reader.readAsDataURL(audioBlob);
          const base64Audio = await base64Promise;

          const format = mimeType.includes('webm') ? 'webm' :
                         mimeType.includes('mp4') ? 'm4a' : 'webm';

          const response = await fetch(`${API_BASE_URL}/api/voice/transcribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({
              audio_base64: base64Audio,
              format: format,
            }),
          });

          if (response.ok) {
            const result = await response.json();
            transcript = result.text || '';
          }
        }
      } catch (err) {
        console.error('Transcription failed:', err);
      }
    }

    // Store captured data and show review modal
    setCapturedScreenshot(screenshotDataUrl);
    setCapturedTranscript(transcript);
    setCapturedStrokes(strokes);
    setCaptureMode('reviewing');

  }, [captureMode]);

  // Spacebar event handlers
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Only trigger on spacebar, ignore if already down or in input
      if (e.code !== 'Space') return;
      if (spacebarDownRef.current) return;

      // Don't trigger if we're in the review modal or generating
      if (captureMode === 'reviewing' || captureMode === 'generating') return;

      // Don't trigger if focus is in an input, textarea, or contenteditable
      const activeElement = document.activeElement;
      const isInput = activeElement?.tagName === 'INPUT' ||
                      activeElement?.tagName === 'TEXTAREA' ||
                      activeElement?.contentEditable === 'true';

      // Check if we're in Monaco editor
      const isMonaco = activeElement?.closest('.monaco-editor');

      // If in Monaco or input, don't capture - let them type space
      if (isInput || isMonaco) return;

      e.preventDefault();
      spacebarDownRef.current = true;
      startCapture();
    };

    const handleKeyUp = (e) => {
      if (e.code !== 'Space') return;
      if (!spacebarDownRef.current) return;

      e.preventDefault();
      spacebarDownRef.current = false;

      if (captureMode === 'capturing') {
        stopCapture();
      }
    };

    // Handle losing focus while spacebar is held
    const handleBlur = () => {
      if (spacebarDownRef.current && captureMode === 'capturing') {
        spacebarDownRef.current = false;
        stopCapture();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [captureMode, startCapture, stopCapture]);

  // Handle intent review modal close
  const handleReviewClose = useCallback(() => {
    setCaptureMode('idle');
    setCapturedScreenshot(null);
    setCapturedTranscript('');
    setCapturedStrokes([]);
  }, []);

  // Handle intent review modal submit
  const handleReviewSubmit = useCallback(async ({ transcript, annotatedScreenshot, strokes, includeData, panelData, currentSql }) => {
    setCaptureMode('generating');

    try {
      // Call the dashboard builder cascade
      const response = await fetch(`${API_BASE_URL}/api/hyper/generate-dashboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          request: transcript,
          current_sql: includeData ? currentSql : sql,
          annotated_screenshot: annotatedScreenshot,
          panel_data: includeData ? panelData : null,
        }),
      });

      const data = await response.json();

      if (data.success && data.sql) {
        // Insert the generated SQL into the editor
        setSql(data.sql);
        console.log('[Hyper] Dashboard generated, session:', data.session_id);
      } else {
        console.error('[Hyper] Generation failed:', data.error);
        setError(data.error || 'Failed to generate dashboard');
      }
    } catch (err) {
      console.error('[Hyper] API error:', err);
      setError(err.message || 'Failed to connect to dashboard builder');
    } finally {
      setCaptureMode('idle');
      setCapturedScreenshot(null);
      setCapturedTranscript('');
      setCapturedStrokes([]);
    }
  }, [sql]);

  // Debounced panel layout parsing - updates grid layout as user types
  const panelLayoutTimerRef = useRef(null);
  useEffect(() => {
    if (panelLayoutTimerRef.current) {
      clearTimeout(panelLayoutTimerRef.current);
    }

    panelLayoutTimerRef.current = setTimeout(() => {
      const parsed = parsePanelMetadata(sql);
      console.log('[panelLayout] Parsed panels:', parsed.panels.map(p => ({ name: p.name, on_select: p.on_select, param_key: p.param_key })));
      if (parsed.panels.length > 0) {
        const layout = generateGridLayout(parsed.panels);
        console.log('[panelLayout] Generated layout panels:', layout.panels.map(p => ({ name: p.name, on_select: p.on_select, param_key: p.param_key })));
        setPanelLayout({
          ...layout,
          hasSetup: parsed.hasSetup,
          setupLineCount: parsed.setupLineCount,
          setupSql: parsed.setupSql,
        });
      } else {
        setPanelLayout(null);
      }
    }, 150); // 150ms debounce for responsive feel

    return () => {
      if (panelLayoutTimerRef.current) {
        clearTimeout(panelLayoutTimerRef.current);
      }
    };
  }, [sql]);

  // Parallel panel execution
  const executeParallel = useCallback(async (options = {}) => {
    const { skipSetup = false, interactionId = null } = options;

    if (!panelLayout || panelLayout.panels.length === 0) {
      // No panels, fall back to regular execution
      return false;
    }

    const isStaleInteraction = () =>
      interactionId !== null && interactionId !== interactionCounterRef.current;

    setLoading(true);
    setError(null);
    setPanelExecutionState('setup');

    // Keep previous panel content on re-runs (filters, refreshes) to avoid the
    // jarring "explain flash". Only preserve when it's the same panel query.
    setPanelResults(prev => {
      const prevByQueryHash = new Map();
      const prevByName = new Map();
      prev.forEach((value) => {
        if (value?.name) {
          prevByName.set(value.name, value);
        }
        if (value?.queryHash) {
          prevByQueryHash.set(value.queryHash, value);
        }
      });

      const next = new Map();
      panelLayout.panels.forEach((panel, idx) => {
        const fullQueryText = panel.panelMarkerLine
          ? `${panel.panelMarkerLine}\n${panel.query}`
          : panel.query;
        const queryHash = hashQuery(fullQueryText);
        const existing = prevByQueryHash.get(queryHash) || prevByName.get(panel.name);

        const isSameQuery = existing?.queryHash ? existing.queryHash === queryHash : true;

        if (existing && isSameQuery && (existing.status === 'complete' || existing.status === 'refreshing')) {
          next.set(idx, { ...existing, status: 'refreshing', name: panel.name, queryHash });
        } else {
          next.set(idx, { status: 'pending', name: panel.name, queryHash });
        }
      });
      return next;
    });

    const startTime = Date.now();

    try {
      // Step 1: Execute setup SQL if present
      if (panelLayout.hasSetup && panelLayout.setupSql) {
        const setupHash = hashQuery(panelLayout.setupSql);
        const setupAlreadyRan =
          setupExecutionRef.current.completed &&
          setupExecutionRef.current.database === selectedDatabase &&
          setupExecutionRef.current.setupHash === setupHash;

        const shouldRunSetup = !skipSetup || !setupAlreadyRan;

        if (shouldRunSetup) {
          console.log('[parallel] Executing setup SQL...');
          const setupResponse = await fetch(`${API_BASE_URL}/api/sql/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({
              query: panelLayout.setupSql,
              database: selectedDatabase,
            }),
          });
          const setupData = await setupResponse.json();
          if (!setupData.success) {
            setupExecutionRef.current = {
              database: selectedDatabase,
              setupHash,
              completed: false,
            };
            setError(`Setup SQL failed: ${setupData.error}`);
            setLoading(false);
            setPanelExecutionState('complete');
            return true;
          }
          setupExecutionRef.current = {
            database: selectedDatabase,
            setupHash,
            completed: true,
          };
          console.log('[parallel] Setup SQL complete');
        } else {
          console.log('[parallel] Skipping setup SQL (already executed for this dashboard)');
        }
      }

      // Step 2: Execute panels with limited concurrency
      // This prevents overwhelming the server when running expensive semantic queries
      // (Flask dev server shares a single DuckDB connection lock across threads)
      const MAX_CONCURRENT = 1;
      setPanelExecutionState('executing');
      console.log(`[parallel] Executing ${panelLayout.panels.length} panels (max ${MAX_CONCURRENT} concurrent)...`);

      // Helper to execute a single panel
      const executePanel = async (panel, idx) => {
        if (isStaleInteraction()) return { idx, success: false, stale: true };

        const fullQueryText = panel.panelMarkerLine
          ? `${panel.panelMarkerLine}\n${panel.query}`
          : panel.query;
        const queryHash = hashQuery(fullQueryText);

        // Mark panel as loading
        setPanelResults(prev => {
          // Don't apply stale interaction updates
          if (isStaleInteraction()) return prev;
          const updated = new Map(prev);
          const existing = updated.get(idx);
          const hasPreviousContent = existing && (existing.status === 'complete' || existing.status === 'refreshing');
          updated.set(idx, {
            ...existing,
            status: hasPreviousContent ? 'refreshing' : 'loading',
            name: panel.name,
            queryHash,
          });
          return updated;
        });

        try {
          const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({
              query: panel.query,
              database: selectedDatabase,
            }),
          });

          const data = await response.json();

          if (data.caller_id) {
            setLastExecutionCallerId(data.caller_id);
          }

          if (data.success) {
            // Update this panel with result
            setPanelResults(prev => {
              if (isStaleInteraction()) return prev;
              const updated = new Map(prev);
              updated.set(idx, {
                status: 'complete',
                name: panel.name,
                queryHash,
                columns: data.columns,
                data: data.data,
                row_count: data.row_count,
              });
              return updated;
            });
            console.log(`[parallel] Panel "${panel.name}" complete (${data.row_count} rows)`);
          } else {
            setPanelResults(prev => {
              if (isStaleInteraction()) return prev;
              const updated = new Map(prev);
              updated.set(idx, {
                status: 'error',
                name: panel.name,
                queryHash,
                error: data.error,
              });
              return updated;
            });
            console.error(`[parallel] Panel "${panel.name}" failed:`, data.error);
          }

          return { idx, success: data.success, data };
        } catch (err) {
          setPanelResults(prev => {
            if (isStaleInteraction()) return prev;
            const updated = new Map(prev);
            updated.set(idx, {
              status: 'error',
              name: panel.name,
              error: err.message,
            });
            return updated;
          });
          console.error(`[parallel] Panel "${panel.name}" error:`, err);
          return { idx, success: false, error: err };
        }
      };

      // Execute with concurrency limit using a worker pool pattern
      const panels = panelLayout.panels;
      const results = new Array(panels.length);
      let nextIndex = 0;

      const runNext = async () => {
        while (nextIndex < panels.length) {
          const idx = nextIndex++;
          results[idx] = await executePanel(panels[idx], idx);
        }
      };

      // Start up to MAX_CONCURRENT workers
      const workers = [];
      for (let i = 0; i < Math.min(MAX_CONCURRENT, panels.length); i++) {
        workers.push(runNext());
      }
      await Promise.all(workers);

      if (!isStaleInteraction()) {
        setExecutionTime(Date.now() - startTime);
        setPanelExecutionState('complete');
        setParamsRefreshTrigger(t => t + 1);
      }

    } catch (err) {
      if (!isStaleInteraction()) {
        setError(err.message || 'Failed to execute query');
        setExecutionTime(Date.now() - startTime);
      }
    } finally {
      if (!isStaleInteraction()) {
        setLoading(false);
      }
    }

    return true; // Indicate parallel execution was used
  }, [panelLayout, selectedDatabase]);

  // Execute query (optionally with provided SQL to avoid state timing issues)
  const executeQuery = useCallback(async (overrideSql) => {
    // Handle case where overrideSql is an event object from onClick
    let queryToRun = (typeof overrideSql === 'string') ? overrideSql : sql;
    if (!queryToRun.trim()) return;

    // If running full editor (not solo), clear solo state
    // But don't clear if we're re-running from toggle (lastSoloQuery exists)
    if (queryToRun === sql && !lastSoloQuery) {
      setIsSoloResult(false);
    }

    // Try parallel execution if we have a panel layout and running full SQL
    if (queryToRun === sql && panelLayout && panelLayout.panels.length > 0) {
      console.log('[execute] Using parallel panel execution');
      setResult(null); // Clear old single-result mode
      const usedParallel = await executeParallel();
      if (usedParallel) return;
    }

    // Fall back to single-request execution (for non-panel queries or solo mode)
    // Inject RENDER dimensions based on container size
    // This ensures rendered images match the panel's actual pixel dimensions
    const containerWidth = resultWrapperRef.current?.offsetWidth || null;
    const containerHeight = resultWrapperRef.current?.offsetHeight || null;
    queryToRun = injectRenderDimensions(queryToRun, containerWidth, containerHeight);

    setLoading(true);
    setError(null);
    setResult(null);
    setPanelResults(new Map()); // Clear panel-mode results

    const startTime = Date.now();

    try {
      const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ query: queryToRun, database: selectedDatabase })
      });

      const data = await response.json();

      setExecutionTime(Date.now() - startTime);

      // Track caller_id for actual cost lookup
      if (data.caller_id) {
        setLastExecutionCallerId(data.caller_id);
      }

      if (!data.success) {
        setError(data.error || 'Query execution failed');
        return;
      }

      // Update previous panels ref for smart diffing
      if (data.multi_panel && data.panels) {
        const panelMap = {};
        data.panels.forEach(p => {
          panelMap[p.name] = JSON.stringify(p.data);
        });
        prevPanelsRef.current = panelMap;
      }

      setResult(data);

      // Trigger params panel refresh
      setParamsRefreshTrigger(t => t + 1);
    } catch (err) {
      setError(err.message || 'Failed to execute query');
      setExecutionTime(Date.now() - startTime);
    } finally {
      setLoading(false);
    }
  }, [sql, selectedDatabase, panelLayout, executeParallel, lastSoloQuery]);

  // Handle panel interactions (clicks, etc.)
  // Executes the cascade and re-runs the dashboard
  // Uses interaction counter to prevent race conditions from rapid clicks
  const handleInteraction = useCallback(async (event) => {
    const { panelName, data: rowData, onSelectTemplate } = event;

    if (!onSelectTemplate) return;

    // Increment interaction counter - used to detect stale results
    const thisInteraction = ++interactionCounterRef.current;

    // Extract param key and check if multi-select
    const { paramKey, selectField } = extractParamInfo(onSelectTemplate);
    const isMultiSelect = onSelectTemplate.includes('@params_set');

    let cascadeToExecute;
    let isDeselect = false;

    // Check for deselect (toggle off) - single-select only
    if (rowData._isDeselect) {
      isDeselect = true;
      // Extract param key from template like @param_set('level', level)
      const match = onSelectTemplate.match(/@param_set\(['"]([^'"]+)['"]/);
      if (match) {
        cascadeToExecute = `@param_clear('${match[1]}')`;
      } else {
        return; // Can't determine param key
      }
    } else {
      // Fill the cascade template with values from clicked row
      cascadeToExecute = fillCascadeTemplate(onSelectTemplate, rowData);
    }

    try {
      // Execute the cascade (e.g., @param_set('region', 'US') or @param_clear('region'))
      const cascadeResponse = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          query: `SELECT ${cascadeToExecute}`,
          database: selectedDatabase
        })
      });
      const cascadeResult = await cascadeResponse.json();

      // Check if a newer interaction has started - if so, skip this stale result
      if (thisInteraction !== interactionCounterRef.current) {
        console.log('[interaction] Skipping stale cascade result (interaction', thisInteraction, 'superseded by', interactionCounterRef.current, ')');
        return;
      }

      // Optimistic update for paramValues to provide immediate visual feedback
      // This is authoritative - we trust the cascade result, not server refetch
      if (paramKey && cascadeResult.success) {
        if (isMultiSelect) {
          // For multi-select (@params_set), the cascade should return the updated array.
          // Some execution paths return empty arrays as NULL / strings; when that happens,
          // fall back to a local toggle so the grid can fully deselect the last item.
          let serverArray = null;
          if (cascadeResult.data && cascadeResult.data.length > 0) {
            const firstRow = cascadeResult.data[0];
            const resultKey = Object.keys(firstRow)[0];
            const newArrayRaw = firstRow[resultKey];

            if (Array.isArray(newArrayRaw)) {
              serverArray = newArrayRaw;
            } else if (typeof newArrayRaw === 'string') {
              const trimmed = newArrayRaw.trim();
              if (trimmed === '' || trimmed === '[]' || trimmed === '{}' || trimmed.toUpperCase() === 'NULL') {
                serverArray = [];
              } else if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
                try {
                  const parsed = JSON.parse(trimmed);
                  if (Array.isArray(parsed)) {
                    serverArray = parsed;
                  }
                } catch (err) {
                  // Ignore parse errors; we'll fall back to local toggle.
                }
              }
            }
          }

          // Determine the toggled value from the clicked row.
          const toggleValueRaw =
            selectField && rowData && rowData[selectField] !== undefined
              ? rowData[selectField]
              : Object.values(rowData || {})[0];
          const toggleValue = toggleValueRaw === null || toggleValueRaw === undefined ? null : String(toggleValueRaw);

          setParamValues(prev => {
            if (Array.isArray(serverArray)) {
              return { ...prev, [paramKey]: serverArray.map(v => String(v)) };
            }

            if (toggleValue === null) {
              return prev;
            }

            const currentRaw = prev[paramKey];
            const currentArray = Array.isArray(currentRaw)
              ? currentRaw.map(v => String(v))
              : (currentRaw === null || currentRaw === undefined ? [] : [String(currentRaw)]);

            const nextArray = currentArray.includes(toggleValue)
              ? currentArray.filter(v => v !== toggleValue)
              : [...currentArray, toggleValue];

            return { ...prev, [paramKey]: nextArray };
          });
        } else if (isDeselect) {
          // For single-select deselect (@param_clear), remove the param
          setParamValues(prev => {
            const newValues = { ...prev };
            delete newValues[paramKey];
            return newValues;
          });
        } else {
          // For single-select (@param_set), set the specific value
          const value = selectField && rowData[selectField] !== undefined
            ? rowData[selectField]
            : Object.values(rowData)[0];
          setParamValues(prev => ({ ...prev, [paramKey]: value }));
        }
      }

      // Re-run the entire dashboard query
      // For panel dashboards, re-run panels via parallel execution (PGWire path) and
      // skip setup SQL when it's already been executed for the current dashboard.
      if (panelLayout && panelLayout.panels && panelLayout.panels.length > 0) {
        await executeParallel({ skipSetup: true, interactionId: thisInteraction });
        return;
      }

      // Fallback: non-panel dashboards run as a single query
      const startTime = Date.now();

      const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ query: sql, database: selectedDatabase })
      });

      const newResult = await response.json();

      // Check again if a newer interaction has started before applying results
      if (thisInteraction !== interactionCounterRef.current) {
        console.log('[interaction] Skipping stale dashboard result (interaction', thisInteraction, 'superseded by', interactionCounterRef.current, ')');
        return;
      }

      setExecutionTime(Date.now() - startTime);

      if (!newResult.success) {
        setError(newResult.error || 'Query execution failed');
        return;
      }

      // Smart update: compare with previous panel data
      // Only panels with changed data will get new object references
      if (newResult.multi_panel && newResult.panels) {
        newResult.panels = newResult.panels.map(panel => {
          const prevDataStr = prevPanelsRef.current[panel.name];
          const newDataStr = JSON.stringify(panel.data);

          // If data is the same, preserve the previous data reference
          // This helps React skip re-rendering unchanged panels
          if (prevDataStr === newDataStr) {
            return { ...panel, _unchanged: true };
          }

          // Update the ref with new data
          prevPanelsRef.current[panel.name] = newDataStr;
          return panel;
        });
      }

      setResult(newResult);

      // Trigger params panel refresh
      setParamsRefreshTrigger(t => t + 1);
    } catch (err) {
      console.error('Interaction failed:', err);
      setError(err.message || 'Failed to execute interaction');
    }
  }, [sql, selectedDatabase, panelLayout, executeParallel]);

  // Handle loading a file from the modal - opens in a new tab
  const handleLoadFile = useCallback((loadedSql, fileName, filePath) => {
    if (fileName && filePath) {
      // Open file in a new tab
      openFileAsTab(loadedSql, fileName, filePath);
    } else {
      // Legacy: just update current tab's SQL
      setSql(loadedSql);
      setResult(null);
      setError(null);
      setPartialResults(new Map());
    }
  }, [openFileAsTab, setSql]);

  // Keep refs up to date (AFTER all callbacks are defined)
  useEffect(() => {
    sqlRef.current = sql;
  }, [sql]);

  useEffect(() => {
    queryExplainsRef.current = queryExplains;
  }, [queryExplains]);

  useEffect(() => {
    executeQueryRef.current = executeQuery;
  }, [executeQuery]);

  useEffect(() => {
    executeSingleQueryInPositionRef.current = executeSingleQueryInPositionHandler;
  }, [executeSingleQueryInPositionHandler]);

  useEffect(() => {
    soloRenderModeRef.current = soloRenderMode;
  }, [soloRenderMode]);

  // Handle running solo query
  const handleRunSolo = useCallback((query, queryIdx) => {
    // Extract query text and apply solo render mode
    let queryText = query.text;
    const queryLines = queryText.split('\n');

    const currentSoloMode = soloRenderModeRef.current;

    if (currentSoloMode === 'naked') {
      const cleanLines = queryLines.filter(line => !line.trim().startsWith('---'));
      queryText = cleanLines.join('\n').trim();
    } else {
      const cleanLines = queryLines.filter(line => !line.trim().startsWith('---'));
      const cleanQuery = cleanLines.join('\n').trim();
      queryText = `--- PANEL 'Preview' (1, 1)\n${cleanQuery}`;
    }

    // Include setup SQL
    let sqlToExecute = queryText;
    const metadata = parsePanelMetadata(sql);

    if (metadata?.hasSetup) {
      const lines = sql.split('\n');
      const setupLines = lines.slice(0, metadata.setupLineCount);
      const setupSql = setupLines.join('\n').trim();

      if (setupSql) {
        sqlToExecute = `${setupSql}\n\n${queryText}`;
      }
    }

    // Execute solo
    setPartialResults(new Map());
    setIsSoloResult(true);
    setLastSoloQuery({ query, queryIdx, queryText: query.text });

    executeQuery(sqlToExecute);
  }, [sql, executeQuery]);

  // Use View Zones for rich query action bars (AFTER handleRunSolo is defined)
  useQueryViewZones({
    editorRef,
    monacoRef,
    queries: parseQueries(sql),
    queryExplains,
    onRunSoloQuery: handleRunSolo,
    isExecuting: loading,
    costPollingStatus,
    actualCost: totalActualCost,
  });

  // Auto-rerun when solo render mode changes
  const prevSoloModeRef = useRef(soloRenderMode);
  useEffect(() => {
    // Only re-run if mode actually changed (not initial mount)
    if (prevSoloModeRef.current !== soloRenderMode && lastSoloQuery && isSoloResult) {
      console.log('[toggle] Solo render mode changed to:', soloRenderMode, '- re-running last query');

      // Re-execute the last solo query with new mode
      const currentSql = sql;
      const query = lastSoloQuery;

      // Extract query text and apply mode
      let queryText = query.queryText;
      const queryLines = queryText.split('\n');

      if (soloRenderMode === 'naked') {
        const cleanLines = queryLines.filter(line => !line.trim().startsWith('---'));
        queryText = cleanLines.join('\n').trim();
      } else {
        const cleanLines = queryLines.filter(line => !line.trim().startsWith('---'));
        const cleanQuery = cleanLines.join('\n').trim();
        queryText = `--- PANEL 'Preview' (1, 1)\n${cleanQuery}`;
      }

      // Include setup SQL
      let sqlToExecute = queryText;
      const metadata = parsePanelMetadata(currentSql);

      if (metadata?.hasSetup) {
        const lines = currentSql.split('\n');
        const setupLines = lines.slice(0, metadata.setupLineCount);
        const setupSql = setupLines.join('\n').trim();

        if (setupSql) {
          sqlToExecute = `${setupSql}\n\n${queryText}`;
        }
      }

      executeQuery(sqlToExecute);
    }

    prevSoloModeRef.current = soloRenderMode;
  }, [soloRenderMode, lastSoloQuery, isSoloResult, sql, executeQuery]);

  // Handle editor mount
  const handleEditorDidMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Signal that editor is ready - triggers initial explain
    setEditorReady(true);

    // Expose to window for Playwright automation (verify_hyper tool)
    window.monacoEditor = editor;
    window.hyperSqlMonaco = editor;

    handleEditorMount(editor, monaco);

    // Configure SQL settings
    editor.updateOptions({
      tabSize: 2,
      insertSpaces: true,
      detectIndentation: false,
      codeLens: false, // Disable CodeLens - we use View Zones instead
    });

    // Ctrl+Enter to execute all queries
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      executeQuery();
    });

    // Ctrl+Shift+Enter to execute current query only (solo mode)
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter,
      () => {
        // Get current query block where cursor is
        const position = editor.getPosition();
        const currentSql = sqlRef.current;
        const queries = parseQueries(currentSql);
        const currentQuery = queries.find(q =>
          position.lineNumber >= q.startLine &&
          position.lineNumber <= q.endLine
        );

        if (currentQuery) {
          const queryIdx = queries.indexOf(currentQuery);
          handleRunSolo(currentQuery, queryIdx);
        }
      }
    );
  }, [executeQuery, handleRunSolo]);

  // Editor options
  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 13,
    fontFamily: "'Google Sans Code', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    insertSpaces: true,
    folding: true,
    bracketPairColorization: { enabled: true },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    cursorBlinking: 'smooth',
    glyphMargin: true, // Enable glyph margin for cost icons
  };

  // Parse panel metadata from SQL (for skeleton preview)
  const panelMetadata = parsePanelMetadata(sql);
  const hasPanelMetadata = panelMetadata?.panels && panelMetadata.panels.length > 0;

  // Build unified panel data from panelLayout + panelResults for parallel execution mode
  const unifiedPanelData = useMemo(() => {
    if (!panelLayout) return null;

    return panelLayout.panels.map((panel, idx) => {
      const panelResult = panelResults.get(idx);
      const status = panelResult?.status || 'pending';

      // Look up explain data for this panel's query
      // Must include the --- PANEL marker line to match how parseQueries hashes queries
      let panelExplain = null;
      if (panel.query) {
        const fullQueryText = panel.panelMarkerLine
          ? `${panel.panelMarkerLine}\n${panel.query}`
          : panel.query;
        const queryHash = hashQuery(fullQueryText);
        panelExplain = queryExplains.get(queryHash);
      }

      // Look up current selection state from param values
      let selectedValue = null;
      let selectedValues = null;
      if (panel.param_key && paramValues[panel.param_key] !== undefined) {
        const paramValue = paramValues[panel.param_key];
        if (panel.multi_select) {
          // Multi-select: param value is an array
          selectedValues = Array.isArray(paramValue) ? paramValue : [paramValue];
        } else {
          // Single-select: param value is a scalar
          selectedValue = paramValue;
        }
      }

      // Build panel object compatible with CanvasRenderer
      return {
        name: panel.name,
        position: panel.position,
        hide_border: panel.hide_border,
        hide_title: panel.hide_title,
        opacity: panel.opacity,
        blur: panel.blur,
        object_fit: panel.object_fit,
        // Status and data from results
        status,
        error: panelResult?.error,
        columns: panelResult?.columns || [],
        data: panelResult?.data || [],
        row_count: panelResult?.row_count || 0,
        // Explain data for skeleton preview
        explain: panelExplain,
        // Interaction metadata for click handlers
        on_select: panel.on_select,
        multi_select: panel.multi_select,
        select_field: panel.select_field,
        selected_value: selectedValue,
        selected_values: selectedValues,
      };
    });
  }, [panelLayout, panelResults, queryExplains, paramValues]);

  // Detect result format: multi-panel, canvas, or error
  const isMultiPanelResult = result?.multi_panel === true;
  const multiPanelData = isMultiPanelResult ? result.panels : null;
  const isCanvasResult = result?.data?.[0]?.format === 'canvas';
  const canvasData = isCanvasResult ? result.data[0].canvas : null;
  const isErrorResult = result?.data?.[0]?.format === 'error';
  const errorMessage = isErrorResult ? result.data[0].error : null;

  return (
    <div className="canvas-view" ref={canvasViewRef}>
      {/* Spacebar Capture Overlay */}
      <CaptureOverlay
        ref={captureOverlayRef}
        active={captureMode === 'capturing'}
        hideUi={overlayUiHidden}
        audioLevel={audioLevel}
        recordingDuration={recordingDuration}
      />

      {/* Processing Overlay - shows while transcribing */}
      {captureMode === 'processing' && (
        <div className="capture-processing-overlay">
          <div className="capture-processing-content">
            <Icon icon="mdi:loading" className="spinning" width="32" />
            <span>Processing voice...</span>
          </div>
        </div>
      )}

      {/* Intent Review Modal */}
      <IntentReviewModal
        isOpen={captureMode === 'reviewing' || captureMode === 'generating'}
        onClose={handleReviewClose}
        onSubmit={handleReviewSubmit}
        screenshotDataUrl={capturedScreenshot}
        initialTranscript={capturedTranscript}
        initialStrokes={capturedStrokes}
        isProcessing={captureMode === 'generating'}
        panelData={result}
        currentSql={sql}
      />

      {/* Header */}
      <div className="canvas-header">
        <div className="canvas-header-left"  >
          <Icon icon="ic:twotone-dashboard" width="41" />
          <div className="canvas-head-title">Hyper</div>
          <span className="canvas-subtitle">Hypermedia SQL Client</span>
        </div>
        <div className="canvas-header-right">
          {/* Database selector */}
          <div className="canvas-db-selector">
            <Icon icon="mdi:database" width="14" />
            <select
              value={selectedDatabase}
              onChange={(e) => setSelectedDatabase(e.target.value)}
              className="canvas-db-select"
            >
              {databases.map((db) => (
                <option key={db.name} value={db.name}>
                  {db.name}
                  {db.type === 'persistent' && db.size_mb !== null ? ` (${db.size_mb}MB)` : ''}
                </option>
              ))}
            </select>
          </div>

          {executionTime !== null && (
            <span className="canvas-execution-time">
              {executionTime}ms
            </span>
          )}

          {/* Cost badges - glanceable cost indicators */}
          <CostBadges
            queryExplains={queryExplains}
            totalEstimatedCost={totalEstimatedCost}
            totalActualCost={totalActualCost}
            costPollingStatus={costPollingStatus}
            onOpenCostAnalysis={() => {
              // Open cost analysis tab with current explain data
              openCostAnalysisTab(queryExplains, { total_cost: totalActualCost }, lastExecutionCallerId);
            }}
          />

          <div className="canvas-ai-hint" title="Hold spacebar to draw + speak, release to generate">
            <Icon icon="mdi:gesture-tap-hold" width="14" />
            <span>SPACE</span>
          </div>
          <button
            className="canvas-file-btn"
            onClick={() => setShowFileModal(true)}
            title="Open saved SQL files"
          >
            <Icon icon="mdi:folder-open" width="16" />
            Files
          </button>
          <button
            className={`canvas-layout-btn ${layoutEditMode ? 'active' : ''}`}
            onClick={() => setLayoutEditMode(m => !m)}
            title={layoutEditMode ? "Exit layout editor" : "Edit layout"}
          >
            <Icon icon="mdi:grid" width="16" />
            {layoutEditMode ? 'Exit Editor' : 'Edit Layout'}
          </button>
          <button
            className="canvas-run-btn"
            onClick={executeQuery}
            disabled={loading || !sql.trim()}
          >
            <Icon
              icon={loading ? "mdi:loading" : "mdi:play"}
              width="16"
              className={loading ? "spinning" : ""}
            />
            Run
          </button>
        </div>
      </div>

      {/* Tab Bar */}
      <TabBar
        tabs={tabs}
        activeTabId={activeTabId}
        onTabClick={switchTab}
        onTabClose={closeTab}
        onTabAdd={() => addTab()}
        onTabRename={renameTab}
      />

      {/* System Tab: Cost Analysis Dashboard */}
      {activeTab.isSystem && activeTab.systemType === 'cost-analysis' && (
        <div className="canvas-system-tab-content">
          <CostAnalysisDashboard
            explainData={activeTab.explainData}
            actualCostData={activeTab.actualCostData}
            callerId={activeTab.callerId}
            sourceTabName={tabs.find(t => t.id === activeTab.sourceTabId)?.name}
          />
        </div>
      )}

      {/* Main layout - only show for query tabs */}
      {!activeTab.isSystem && (
      <div className={`canvas-layout ${editorHidden ? 'canvas-editor-hidden' : ''}`}>
        {/* Collapsed editor bar - shows when editor is hidden */}
        {editorHidden && (
          <div className="canvas-editor-collapsed" onClick={() => setEditorHidden(false)}>
            <Icon icon="mdi:chevron-right" width="16" />
            <span className="canvas-editor-collapsed-label">SQL</span>
          </div>
        )}

        {/* Editor pane */}
        {!editorHidden && (
        <div className="canvas-editor-pane">
          <div className="canvas-editor-header">
            <Icon icon="mdi:code-tags" width="14" />
            <span>SQL Query</span>
            <span className="canvas-hint">Ctrl+Enter to run all</span>
            <span className="canvas-hint">Ctrl+Shift+Enter for current query</span>
            <button
              className="canvas-editor-toggle"
              onClick={() => setEditorHidden(true)}
              title="Hide editor"
            >
              <Icon icon="mdi:chevron-left" width="16" />
            </button>
          </div>
          <div className="canvas-editor-wrapper">
            <Editor
              height="100%"
              language="sql"
              theme={STUDIO_THEME_NAME}
              value={sql}
              onChange={setSql}
              onMount={handleEditorDidMount}
              beforeMount={configureMonacoTheme}
              options={editorOptions}
            />
          </div>
          <ParamsPanel
            database={selectedDatabase}
            refreshTrigger={paramsRefreshTrigger}
            collapsed={paramsCollapsed}
            onToggle={() => setParamsCollapsed(c => !c)}
            onParamChange={executeQuery}
          />
        </div>
        )}

        {/* Result pane */}
        <div className="canvas-result-pane">
          <div className="canvas-result-header">
            <Icon icon="mdi:monitor-dashboard" width="14" />
            <span>Output</span>
            {result && (
              <span className="canvas-result-info">
                {isMultiPanelResult
                  ? `${multiPanelData?.length || 0} panels`
                  : isCanvasResult
                    ? `${canvasData?.panels?.length || 0} panels`
                    : `${result.row_count} rows`
                }
              </span>
            )}

            {/* Solo render mode toggle - only show for solo results */}
            {result && isSoloResult && (
              <div className="canvas-solo-mode-toggle">
                <button
                  className={`solo-mode-btn ${soloRenderMode === 'naked' ? 'active' : ''}`}
                  onClick={() => setSoloRenderMode('naked')}
                  title="Show raw data (good for debugging)"
                >
                  <Icon icon="mdi:table" width="14" />
                  Naked
                </button>
                <button
                  className={`solo-mode-btn ${soloRenderMode === 'rendered' ? 'active' : ''}`}
                  onClick={() => setSoloRenderMode('rendered')}
                  title="Render charts/visualizations"
                >
                  <Icon icon="mdi:chart-box" width="14" />
                  Rendered
                </button>
              </div>
            )}
          </div>
          <div className="canvas-result-wrapper" ref={resultWrapperRef}>
            {/* Only show center spinner for single-query mode (no panel layout) */}
            {loading && !panelLayout && (
              <div className="canvas-loading">
                <Icon icon="mdi:loading" width="32" className="spinning" />
                <span>Executing query...</span>
              </div>
            )}

            {error && (
              <div className="canvas-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <div className="canvas-error-content">
                  <h3>Error</h3>
                  <pre>{error}</pre>
                </div>
              </div>
            )}

            {/* Panel layout preview / parallel execution results */}
            {!error && !layoutEditMode && panelLayout && unifiedPanelData && (
              <CanvasRenderer
                data={[]}
                columns={[]}
                isCanvas={false}
                canvasData={null}
                isMultiPanel={true}
                multiPanelData={unifiedPanelData}
                onInteraction={handleInteraction}
              />
            )}

            {!loading && !error && !result && !panelLayout && (
              <div className="canvas-empty canvas-empty-clickable" onClick={executeQuery}>
                <Icon icon="mdi:play-circle-outline" width="48" />
                <h3>Run a query to see results</h3>
                <p>Click here, press Ctrl+Enter, or click Run</p>
              </div>
            )}

            {!loading && !error && result && isErrorResult && (
              <div className="canvas-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <div className="canvas-error-content">
                  <h3>Query Error</h3>
                  <pre>{errorMessage}</pre>
                </div>
              </div>
            )}

            {/* Single-request result (non-panel mode) */}
            {!loading && !error && result && !isErrorResult && !layoutEditMode && !panelLayout && (
              <CanvasRenderer
                data={result.data}
                columns={result.columns}
                isCanvas={isCanvasResult}
                canvasData={canvasData}
                isMultiPanel={isMultiPanelResult}
                multiPanelData={multiPanelData}
                onInteraction={handleInteraction}
              />
            )}

            {/* Layout Editor Mode */}
            {layoutEditMode && (
              <GridLayoutEditor
                sql={sql}
                onSqlChange={setSql}
                multiPanelData={multiPanelData}
                onInteraction={handleInteraction}
                editMode={layoutEditMode}
                onExitEdit={(updatedSql) => {
                  if (updatedSql) {
                    setSql(updatedSql);
                  }
                  setLayoutEditMode(false);
                  // Don't auto-run - skeleton layout will show the preview
                  // User can manually run when ready
                }}
              />
            )}
          </div>
        </div>
      </div>
      )}

      {/* SQL Files Modal */}
      <SqlFileModal
        isOpen={showFileModal}
        onClose={() => setShowFileModal(false)}
        onLoad={handleLoadFile}
        currentSql={sql}
      />
    </div>
  );
};

export default CanvasView;
