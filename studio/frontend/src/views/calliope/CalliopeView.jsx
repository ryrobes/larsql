import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import html2canvas from 'html2canvas';
import CaptureOverlay from '../canvas/components/CaptureOverlay';
import IntentReviewModal from '../canvas/components/IntentReviewModal';
import { API_BASE_URL } from '../../config/api';
import { getAuthHeaders } from '../../stores/authStore';
import { useToast } from '../../stores/toastStore';
import './CalliopeView.css';

/**
 * CalliopeView - Micro-App Builder
 *
 * Build full-stack micro-apps (FastAPI + React) through voice and drawing.
 * Hold spacebar to draw and talk, release to iterate.
 */
const CalliopeView = () => {
  const { kitId: urlKitId } = useParams();
  const navigate = useNavigate();

  // Kit state
  const [kits, setKits] = useState([]);
  const [activeKit, setActiveKit] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [creating, setCreating] = useState(false);
  const [starting, setStarting] = useState(false);
  const [loadingKits, setLoadingKits] = useState(true);
  const [error, setError] = useState(null);

  // Capture state
  const [captureMode, setCaptureMode] = useState('idle'); // 'idle' | 'capturing' | 'reviewing'
  const [capturedScreenshot, setCapturedScreenshot] = useState(null);
  const [capturedTranscript, setCapturedTranscript] = useState('');
  const [capturedStrokes, setCapturedStrokes] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);

  // Building state - for background generation
  const [isBuilding, setIsBuilding] = useState(false);
  const [buildingSessionId, setBuildingSessionId] = useState(null);

  // Toasts
  const { showToast } = useToast();

  // Message polling refs
  const lastMessageTimeRef = useRef(null);
  const seenMessagesRef = useRef(new Set());
  const messagePollingRef = useRef(null);

  // Audio state
  const [audioLevel, setAudioLevel] = useState(0);
  const [recordingDuration, setRecordingDuration] = useState(0);

  // Refs
  const viewRef = useRef(null);
  const captureOverlayRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const animationFrameRef = useRef(null);
  const durationIntervalRef = useRef(null);
  const spacebarDownRef = useRef(false);
  const iframeRef = useRef(null);
  const interceptRef = useRef(null);
  const captureModeRef = useRef('idle'); // Mirror of captureMode for use in callbacks
  const streamRef = useRef(null);
  const screenshotResolversRef = useRef({}); // Pending screenshot request resolvers

  // Request screenshot from iframe via postMessage
  const requestIframeScreenshot = useCallback(() => {
    return new Promise((resolve, reject) => {
      if (!iframeRef.current?.contentWindow) {
        reject(new Error('Iframe not available'));
        return;
      }

      const requestId = `screenshot-${Date.now()}`;
      const timeout = setTimeout(() => {
        delete screenshotResolversRef.current[requestId];
        reject(new Error('Screenshot request timed out'));
      }, 5000);

      screenshotResolversRef.current[requestId] = { resolve, reject, timeout };

      iframeRef.current.contentWindow.postMessage({
        type: 'CALLIOPE_SCREENSHOT_REQUEST',
        requestId,
      }, '*');
    });
  }, []);

  // Listen for screenshot responses from iframe
  useEffect(() => {
    const handleMessage = (event) => {
      if (event.data?.type === 'CALLIOPE_SCREENSHOT_RESPONSE') {
        const { requestId, screenshot, error } = event.data;
        const pending = screenshotResolversRef.current[requestId];
        if (pending) {
          clearTimeout(pending.timeout);
          delete screenshotResolversRef.current[requestId];
          if (error) {
            pending.reject(new Error(error));
          } else {
            pending.resolve(screenshot);
          }
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // Fetch templates and kits on mount
  useEffect(() => {
    fetchTemplates();
    fetchKits();
  }, []);

  const fetchTemplates = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/calliope/templates`, {
        headers: getAuthHeaders(),
      });
      if (response.ok) {
        const data = await response.json();
        const templateList = data.templates || [];
        setTemplates(templateList);
        // Set default selection to first template
        if (templateList.length > 0 && !selectedTemplate) {
          setSelectedTemplate(templateList[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch templates:', err);
    }
  };

  // Handle URL kit ID
  useEffect(() => {
    if (urlKitId && kits.length > 0) {
      const kit = kits.find(k => k.kit_id === urlKitId);
      if (kit) {
        if (kit.status === 'running') {
          setActiveKit(kit);
        } else {
          // Start the kit
          startKit(kit.kit_id);
        }
      }
    }
  }, [urlKitId, kits]);

  const fetchKits = async () => {
    try {
      setLoadingKits(true);
      const response = await fetch(`${API_BASE_URL}/api/calliope/kit`, {
        headers: getAuthHeaders(),
      });
      if (response.ok) {
        const data = await response.json();
        setKits(data.kits || []);
      }
    } catch (err) {
      console.error('Failed to fetch kits:', err);
    } finally {
      setLoadingKits(false);
    }
  };

  const createKit = async () => {
    try {
      setCreating(true);
      setError(null);
      const response = await fetch(`${API_BASE_URL}/api/calliope/kit`, {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ template: selectedTemplate }),
      });

      if (response.ok) {
        const data = await response.json();
        // Refresh kits list and start the new kit
        await fetchKits();
        await startKit(data.kit_id);
      } else {
        const err = await response.json();
        setError(err.error || 'Failed to create kit');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const startKit = async (kitId) => {
    try {
      setStarting(true);
      setError(null);
      const response = await fetch(`${API_BASE_URL}/api/calliope/kit/${kitId}/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });

      if (response.ok) {
        const data = await response.json();
        setActiveKit(data);
        navigate(`/calliope/${kitId}`);
        // Refresh kits to update status
        fetchKits();
      } else {
        const err = await response.json();
        setError(err.error || 'Failed to start kit');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  };

  const stopKit = async () => {
    if (!activeKit) return;

    try {
      await fetch(`${API_BASE_URL}/api/calliope/kit/${activeKit.kit_id}/stop`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      setActiveKit(null);
      navigate('/calliope');
      fetchKits();
    } catch (err) {
      console.error('Failed to stop kit:', err);
    }
  };

  // ============================================
  // SPACEBAR CAPTURE (from CanvasView)
  // ============================================

  const startCapture = useCallback(async () => {
    if (captureModeRef.current !== 'idle') return;

    captureModeRef.current = 'capturing';
    setCaptureMode('capturing');
    setRecordingDuration(0);
    setAudioLevel(0);
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
      const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
      const updateLevel = () => {
        if (analyserRef.current) {
          analyserRef.current.getByteFrequencyData(dataArray);
          const avg = dataArray.reduce((a, b) => a + b) / dataArray.length;
          setAudioLevel(Math.min(100, (avg / 128) * 100));
        }
        animationFrameRef.current = requestAnimationFrame(updateLevel);
      };
      updateLevel();

      // MediaRecorder setup - pick best supported format
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
  }, []);

  const stopCapture = useCallback(async () => {
    if (captureModeRef.current !== 'capturing') return;
    captureModeRef.current = 'processing';

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

    // Get strokes from overlay before clearing
    const strokes = captureOverlayRef.current?.getStrokes?.() || [];

    // Get iframe position for coordinate adjustment
    const iframeRect = iframeRef.current?.getBoundingClientRect() || { left: 0, top: 0 };

    // Wait for repaint
    setAudioLevel(0);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    // Capture screenshot from iframe and composite with strokes
    let screenshotDataUrl = null;
    try {
      const iframeScreenshot = await requestIframeScreenshot();

      // Load the iframe screenshot into an image
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = iframeScreenshot;
      });

      // Create compositing canvas
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');

      // Draw iframe screenshot as base
      ctx.drawImage(img, 0, 0);

      // Draw strokes on top, adjusting coordinates for iframe offset
      strokes.forEach(stroke => {
        if (stroke.points.length < 2) return;

        ctx.beginPath();
        ctx.strokeStyle = stroke.color;
        ctx.lineWidth = stroke.size;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        // Adjust first point by iframe offset
        const startX = stroke.points[0].x - iframeRect.left;
        const startY = stroke.points[0].y - iframeRect.top;
        ctx.moveTo(startX, startY);

        // Draw remaining points
        for (let i = 1; i < stroke.points.length; i++) {
          const x = stroke.points[i].x - iframeRect.left;
          const y = stroke.points[i].y - iframeRect.top;
          ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      screenshotDataUrl = canvas.toDataURL('image/png');
    } catch (err) {
      console.error('Failed to capture/composite screenshot:', err);
      // Fallback: capture parent (will show grey iframe but includes overlay drawings)
      try {
        if (viewRef.current) {
          const canvas = await html2canvas(viewRef.current, {
            backgroundColor: '#0a0a0f',
            scale: 1,
            logging: false,
            useCORS: true,
          });
          screenshotDataUrl = canvas.toDataURL('image/png');
        }
      } catch (fallbackErr) {
        console.error('Fallback screenshot also failed:', fallbackErr);
      }
    }

    // Transcribe audio
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

    // Clear overlay after screenshot
    captureOverlayRef.current?.clear?.();

    // Store captured data and show review modal
    setCapturedScreenshot(screenshotDataUrl);
    setCapturedTranscript(transcript);
    setCapturedStrokes(strokes);
    captureModeRef.current = 'reviewing';
    setCaptureMode('reviewing');
  }, [requestIframeScreenshot]);

  // Spacebar detection - use capture phase to intercept before iframe gets events
  useEffect(() => {
    if (!activeKit) return;

    const handleKeyDown = (e) => {
      // Escape key steals focus back from iframe
      if (e.code === 'Escape') {
        viewRef.current?.focus();
        return;
      }

      if (e.code === 'Space' && !spacebarDownRef.current) {
        // Ignore if in input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        e.preventDefault();
        e.stopPropagation();
        spacebarDownRef.current = true;
        startCapture();
      }
    };

    const handleKeyUp = (e) => {
      if (e.code === 'Space' && spacebarDownRef.current) {
        e.preventDefault();
        e.stopPropagation();
        spacebarDownRef.current = false;
        stopCapture();
      }
    };

    // When window loses focus (e.g., iframe clicked), release spacebar
    const handleBlur = () => {
      if (spacebarDownRef.current) {
        spacebarDownRef.current = false;
        stopCapture();
      }
    };

    // Use capture phase (true) to intercept events before they reach iframe
    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('keyup', handleKeyUp, true);
    window.addEventListener('blur', handleBlur);

    return () => {
      document.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('keyup', handleKeyUp, true);
      window.removeEventListener('blur', handleBlur);
    };
  }, [activeKit, startCapture, stopCapture]);

  // Keep the intercept layer focused so spacebar works
  useEffect(() => {
    if (!activeKit || captureMode !== 'idle') return;

    // Focus intercept layer on mount
    interceptRef.current?.focus();

    // Refocus when mouse moves near the edges of the canvas area
    // This allows iframe interaction in the center while enabling spacebar near edges
    let lastRefocus = 0;
    const handleMouseMove = (e) => {
      if (captureModeRef.current !== 'idle') return;

      const now = Date.now();
      if (now - lastRefocus < 100) return; // Throttle

      const canvasArea = document.querySelector('.calliope-canvas-area');
      if (!canvasArea) return;

      const rect = canvasArea.getBoundingClientRect();
      const edgeThreshold = 50; // pixels from edge

      const nearEdge =
        e.clientY < rect.top + edgeThreshold ||
        e.clientY > rect.bottom - edgeThreshold ||
        e.clientX < rect.left + edgeThreshold ||
        e.clientX > rect.right - edgeThreshold;

      if (nearEdge && document.activeElement !== interceptRef.current) {
        lastRefocus = now;
        interceptRef.current?.focus();
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, [activeKit, captureMode]);

  // Poll for session messages while building (debounced)
  const pollSessionMessages = useCallback(async (sessionId) => {
    if (!sessionId) return;

    try {
      const after = lastMessageTimeRef.current || new Date(Date.now() - 10000).toISOString();
      const response = await fetch(
        `${API_BASE_URL}/api/calliope/session/${sessionId}/messages?after=${encodeURIComponent(after)}`,
        { headers: getAuthHeaders() }
      );

      if (response.ok) {
        const data = await response.json();
        const messages = data.messages || [];

        // Show new messages as toasts (deduplicated)
        for (const msg of messages) {
          const key = `${msg.timestamp}-${msg.content}`;
          if (!seenMessagesRef.current.has(key)) {
            seenMessagesRef.current.add(key);

            // Format message for toast
            let text = msg.content;
            if (msg.node_type === 'tool_call') {
              text = `🔧 ${msg.content}`;
            } else if (msg.cell_name) {
              text = `[${msg.cell_name}] ${text}`;
            }

            showToast(text, { type: 'info', duration: 3000, icon: 'mdi:message-processing' });

            // Update cursor
            if (msg.timestamp > (lastMessageTimeRef.current || '')) {
              lastMessageTimeRef.current = msg.timestamp;
            }
          }
        }
      }
    } catch (e) {
      // Ignore polling errors
    }
  }, [showToast]);

  // Start/stop message polling when building state changes
  useEffect(() => {
    if (isBuilding && buildingSessionId) {
      // Reset tracking
      seenMessagesRef.current = new Set();
      lastMessageTimeRef.current = null;

      // Poll every 2 seconds (debounced)
      messagePollingRef.current = setInterval(() => {
        pollSessionMessages(buildingSessionId);
      }, 2000);

      // Initial poll
      pollSessionMessages(buildingSessionId);
    } else {
      // Stop polling
      if (messagePollingRef.current) {
        clearInterval(messagePollingRef.current);
        messagePollingRef.current = null;
      }
    }

    return () => {
      if (messagePollingRef.current) {
        clearInterval(messagePollingRef.current);
      }
    };
  }, [isBuilding, buildingSessionId, pollSessionMessages]);

  // Poll kit health and refresh iframe when server restarts
  const waitForServerAndRefresh = useCallback(async (port, maxAttempts = 30) => {
    const baseUrl = `http://localhost:${port}`;
    let serverWasDown = false;

    for (let i = 0; i < maxAttempts; i++) {
      try {
        // Quick health check
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 1000);
        await fetch(`${baseUrl}/api/health`, { signal: controller.signal });
        clearTimeout(timeout);

        // If server was down and is now up, refresh
        if (serverWasDown) {
          console.log('[Calliope] Server restarted, refreshing iframe');
          if (iframeRef.current) {
            iframeRef.current.src = `${baseUrl}?_t=${Date.now()}`;
          }
          return true;
        }
      } catch (e) {
        // Server is down (restarting)
        serverWasDown = true;
      }
      await new Promise(r => setTimeout(r, 500));
    }
    return false;
  }, []);

  // Handle intent submission
  const handleIntentSubmit = async ({ transcript, annotatedScreenshot }) => {
    if (!activeKit) return;

    // Close modal immediately so user can watch the app update
    captureModeRef.current = 'idle';
    setCaptureMode('idle');
    setCapturedScreenshot(null);
    setCapturedTranscript('');
    setCapturedStrokes([]);

    // Start building in background
    setIsBuilding(true);
    showToast('Building your changes...', { type: 'info', icon: 'mdi:hammer-wrench', duration: 3000 });

    try {
      const response = await fetch(`${API_BASE_URL}/api/calliope/kit/${activeKit.kit_id}/generate`, {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          request: transcript,
          annotated_screenshot: annotatedScreenshot,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('Generation result:', data);
        setBuildingSessionId(data.session_id);

        // Wait for server to restart and refresh iframe
        await waitForServerAndRefresh(activeKit.port);

        showToast('Build complete!', { type: 'success', duration: 4000 });
      } else {
        const err = await response.json();
        console.error('Generation failed:', err);
        showToast(`Build failed: ${err.error || 'Unknown error'}`, { type: 'error', duration: 6000 });
      }
    } catch (err) {
      console.error('Generation error:', err);
      showToast(`Build error: ${err.message}`, { type: 'error', duration: 6000 });
    } finally {
      setIsBuilding(false);
      setBuildingSessionId(null);
    }
  };

  // Close review modal
  const handleCloseReview = () => {
    captureModeRef.current = 'idle';
    setCaptureMode('idle');
    setCapturedScreenshot(null);
    setCapturedTranscript('');
    setCapturedStrokes([]);
  };

  // ============================================
  // RENDER: Kit Selector (no active kit)
  // ============================================

  if (!activeKit) {
    return (
      <div className="calliope-view calliope-selector">
        <div className="calliope-selector-content">
          <div className="calliope-selector-header">
            <Icon icon="mdi:brush" className="calliope-logo" />
            <h1>Calliope</h1>
            <p>Build micro-apps with voice and drawing</p>
          </div>

          {error && (
            <div className="calliope-error">
              <Icon icon="mdi:alert-circle" />
              {error}
            </div>
          )}

          {/* Create new kit */}
          <section className="calliope-section">
            <h2>Create New Kit</h2>
            <div className="calliope-template-select">
              <label>Template</label>
              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                disabled={creating}
              >
                {templates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <p className="calliope-template-desc">
                {templates.find(t => t.id === selectedTemplate)?.description}
              </p>
            </div>
            <button
              className="calliope-create-btn"
              onClick={createKit}
              disabled={creating || !selectedTemplate}
            >
              {creating ? (
                <>
                  <Icon icon="mdi:loading" className="spinning" />
                  Creating...
                </>
              ) : (
                <>
                  <Icon icon="mdi:plus" />
                  Create Kit
                </>
              )}
            </button>
          </section>

          {/* Existing kits */}
          <section className="calliope-section">
            <h2>Your Kits</h2>
            {loadingKits ? (
              <div className="calliope-loading">
                <Icon icon="mdi:loading" className="spinning" />
                Loading kits...
              </div>
            ) : kits.length === 0 ? (
              <div className="calliope-empty">
                <Icon icon="mdi:folder-open-outline" />
                <p>No kits yet. Create one to get started!</p>
              </div>
            ) : (
              <div className="calliope-kit-grid">
                {kits.map(kit => (
                  <div key={kit.kit_id} className={`calliope-kit-card ${kit.status}`}>
                    <div className="calliope-kit-header">
                      <span className="calliope-kit-name">{kit.kit_id}</span>
                      <span className={`calliope-kit-status ${kit.status}`}>
                        {kit.status}
                      </span>
                    </div>
                    <div className="calliope-kit-meta">
                      <span>Template: {kit.template}</span>
                      {kit.port && <span>Port: {kit.port}</span>}
                    </div>
                    <button
                      className="calliope-kit-action"
                      onClick={() => kit.status === 'running' ? setActiveKit(kit) && navigate(`/calliope/${kit.kit_id}`) : startKit(kit.kit_id)}
                      disabled={starting}
                    >
                      {kit.status === 'running' ? (
                        <>
                          <Icon icon="mdi:open-in-new" />
                          Open
                        </>
                      ) : (
                        <>
                          <Icon icon="mdi:play" />
                          Start
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    );
  }

  // ============================================
  // RENDER: Active Kit (building mode)
  // ============================================

  return (
    <div
      className="calliope-view calliope-builder"
      ref={viewRef}
      tabIndex={-1}
    >
      {/* Header */}
      <header className="calliope-header">
        <div className="calliope-header-left">
          <Icon icon="mdi:brush" className="calliope-header-icon" />
          <h1>{activeKit.kit_id}</h1>
          <span className="calliope-status running">Running on port {activeKit.port}</span>
        </div>
        <div className="calliope-header-right">
          <span className="calliope-hint">
            Move to edge, hold <kbd>Space</kbd> to draw + talk
          </span>
          <button className="calliope-stop-btn" onClick={stopKit}>
            <Icon icon="mdi:stop" />
            Stop Kit
          </button>
        </div>
      </header>

      {/* Kit iframe */}
      <div className="calliope-canvas-area">
        <iframe
          ref={iframeRef}
          src={`http://localhost:${activeKit.port}`}
          title="Kit Preview"
          className="calliope-iframe"
        />

        {/* Spacebar intercept layer - maintains keyboard focus for spacebar capture */}
        <div
          className="calliope-spacebar-intercept"
          tabIndex={0}
          ref={interceptRef}
          onKeyDown={(e) => {
            if (e.code === 'Space' && captureModeRef.current === 'idle' && !spacebarDownRef.current) {
              e.preventDefault();
              e.stopPropagation();
              spacebarDownRef.current = true;
              startCapture();
            }
          }}
          onKeyUp={(e) => {
            if (e.code === 'Space' && spacebarDownRef.current) {
              e.preventDefault();
              e.stopPropagation();
              spacebarDownRef.current = false;
              stopCapture();
            }
          }}
        />

        {/* Capture overlay */}
        <CaptureOverlay
          ref={captureOverlayRef}
          active={captureMode === 'capturing'}
          audioLevel={audioLevel}
          recordingDuration={recordingDuration}
        />
      </div>

      {/* Intent review modal */}
      <IntentReviewModal
        isOpen={captureMode === 'reviewing'}
        onClose={handleCloseReview}
        onSubmit={handleIntentSubmit}
        screenshotDataUrl={capturedScreenshot}
        initialTranscript={capturedTranscript}
        initialStrokes={capturedStrokes}
        isProcessing={isProcessing}
      />

      {/* Building indicator - floating pill */}
      {isBuilding && (
        <div className="calliope-building-indicator">
          <Icon icon="mdi:loading" className="spinning" />
          <span>Building...</span>
        </div>
      )}
    </div>
  );
};

export default CalliopeView;
