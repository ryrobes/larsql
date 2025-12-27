import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './GlobalVoiceInput.css';

/**
 * GlobalVoiceInput - Floating voice input button for universal speech-to-text
 *
 * Features:
 * - Subtle floating button in bottom-right corner (Windlass-themed)
 * - Tracks currently focused input/textarea across the entire app
 * - Records audio and transcribes via backend API
 * - Inserts transcript into the last focused input (smart cursor positioning)
 * - Keyboard shortcut: Ctrl+Shift+V (or Cmd+Shift+V on Mac)
 * - Visual feedback for all states (idle, ready, recording, processing, success, error)
 * - Auto-hides if voice API unavailable
 *
 * State Machine:
 * - idle: Waiting, semi-transparent
 * - ready: Valid input focused, cyan accent
 * - recording: Red pulsing with audio level visualization
 * - processing: Cyan spinner while transcribing
 * - success: Green checkmark, auto-closes
 * - error: Red with error message, auto-closes
 */
function GlobalVoiceInput() {
  const [status, setStatus] = useState('idle'); // idle, ready, recording, processing, success, error
  const [audioLevel, setAudioLevel] = useState(0);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [transcript, setTranscript] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);
  const [targetInfo, setTargetInfo] = useState(null); // Info about the target input

  const lastFocusedInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const animationFrameRef = useRef(null);
  const durationIntervalRef = useRef(null);

  // Track focused input elements
  useEffect(() => {
    const handleFocus = (e) => {
      const target = e.target;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.contentEditable === 'true'
      ) {
        // Check if it's a text-type input
        if (target.tagName === 'INPUT') {
          const textTypes = ['text', 'search', 'email', 'url', 'tel', 'password', ''];
          if (!textTypes.includes(target.type)) return;
        }

        lastFocusedInputRef.current = target;

        // Get info about the target for display
        const placeholder = target.placeholder || target.getAttribute('aria-label') || '';
        const label = target.closest('label')?.textContent ||
                     document.querySelector(`label[for="${target.id}"]`)?.textContent || '';

        setTargetInfo({
          type: target.tagName.toLowerCase(),
          placeholder: placeholder.slice(0, 30),
          label: label.slice(0, 30),
        });

        // Show ready state briefly when a valid input is focused
        if (status === 'idle') {
          setStatus('ready');
        }
      }
    };

    const handleBlur = (e) => {
      // Don't clear if clicking on the voice button itself
      const relatedTarget = e.relatedTarget;
      if (relatedTarget?.closest('.wl-global-voice-input')) return;

      // Keep the reference but update status
      setTimeout(() => {
        if (status === 'ready') {
          setStatus('idle');
        }
      }, 200);
    };

    document.addEventListener('focusin', handleFocus);
    document.addEventListener('focusout', handleBlur);

    return () => {
      document.removeEventListener('focusin', handleFocus);
      document.removeEventListener('focusout', handleBlur);
    };
  }, [status]);

  // Keyboard shortcut: Ctrl+Shift+V (or Cmd+Shift+V)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'V') {
        e.preventDefault();
        if (status === 'recording') {
          stopRecording();
        } else if (status === 'idle' || status === 'ready') {
          startRecording();
        }
      }
      // Escape to cancel
      if (e.key === 'Escape' && status === 'recording') {
        cancelRecording();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [status]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (durationIntervalRef.current) {
        clearInterval(durationIntervalRef.current);
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  // Audio level visualization
  const updateAudioLevel = useCallback(() => {
    if (analyserRef.current && status === 'recording') {
      const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(dataArray);
      const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      setAudioLevel(Math.min(100, (average / 128) * 100));
      animationFrameRef.current = requestAnimationFrame(updateAudioLevel);
    }
  }, [status]);

  const startRecording = useCallback(async () => {
    if (!lastFocusedInputRef.current) {
      setErrorMessage('Click on a text field first');
      setStatus('error');
      setTimeout(() => setStatus('idle'), 2000);
      return;
    }

    try {
      setErrorMessage('');
      setTranscript('');
      audioChunksRef.current = [];
      setIsExpanded(true);

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
      setStatus('recording');
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

      mediaRecorder.onstop = async () => {
        cleanup();
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        if (audioBlob.size > 0) {
          await transcribeAudio(audioBlob, mimeType);
        } else {
          setStatus('idle');
          setIsExpanded(false);
        }
      };

      mediaRecorder.start(100);
      setRecordingDuration(0);
      durationIntervalRef.current = setInterval(() => {
        setRecordingDuration(prev => prev + 1);
      }, 1000);

    } catch (err) {
      console.error('Recording error:', err);
      setStatus('error');
      setErrorMessage(
        err.name === 'NotAllowedError'
          ? 'Mic access denied'
          : 'Recording failed'
      );
      setTimeout(() => {
        setStatus('idle');
        setIsExpanded(false);
      }, 2000);
    }
  }, [updateAudioLevel]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const cancelRecording = useCallback(() => {
    cleanup();
    audioChunksRef.current = [];
    setStatus('idle');
    setIsExpanded(false);
  }, []);

  const cleanup = () => {
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
    setAudioLevel(0);
  };

  const transcribeAudio = async (audioBlob, mimeType) => {
    setStatus('processing');

    try {
      const reader = new FileReader();
      const base64Promise = new Promise((resolve, reject) => {
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.onerror = reject;
      });
      reader.readAsDataURL(audioBlob);
      const base64Audio = await base64Promise;

      const format = mimeType.includes('webm') ? 'webm' :
                     mimeType.includes('mp4') ? 'm4a' : 'webm';

      const response = await fetch('http://localhost:5001/api/voice/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_base64: base64Audio,
          format: format,
        }),
      });

      if (!response.ok) {
        throw new Error('Transcription failed');
      }

      const result = await response.json();
      const text = result.text || '';

      if (text.trim()) {
        setTranscript(text);
        insertText(text);
        setStatus('success');
        setTimeout(() => {
          setStatus('idle');
          setIsExpanded(false);
          setTranscript('');
        }, 1500);
      } else {
        setStatus('error');
        setErrorMessage('No speech detected');
        setTimeout(() => {
          setStatus('idle');
          setIsExpanded(false);
        }, 2000);
      }

    } catch (err) {
      console.error('Transcription error:', err);
      setStatus('error');
      setErrorMessage('Transcription failed');
      setTimeout(() => {
        setStatus('idle');
        setIsExpanded(false);
      }, 2000);
    }
  };

  const insertText = (text) => {
    const input = lastFocusedInputRef.current;
    if (!input) return;

    // Focus the input first
    input.focus();

    if (input.tagName === 'INPUT' || input.tagName === 'TEXTAREA') {
      const start = input.selectionStart || 0;
      const end = input.selectionEnd || 0;
      const currentValue = input.value || '';

      // Insert text at cursor position
      const newValue = currentValue.slice(0, start) + text + currentValue.slice(end);
      input.value = newValue;

      // Move cursor to end of inserted text
      const newPosition = start + text.length;
      input.setSelectionRange(newPosition, newPosition);

      // Trigger input event for React controlled components
      const event = new Event('input', { bubbles: true });
      input.dispatchEvent(event);

      // Also trigger change event
      const changeEvent = new Event('change', { bubbles: true });
      input.dispatchEvent(changeEvent);

    } else if (input.contentEditable === 'true') {
      // For contenteditable elements
      document.execCommand('insertText', false, text);
    }
  };

  const handleClick = () => {
    if (status === 'recording') {
      stopRecording();
    } else if (status === 'idle' || status === 'ready') {
      startRecording();
    }
  };

  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Don't render if voice isn't available
  const [voiceAvailable, setVoiceAvailable] = useState(true);
  useEffect(() => {
    fetch('http://localhost:5001/api/voice/status')
      .then(r => r.json())
      .then(data => setVoiceAvailable(data.available))
      .catch(() => setVoiceAvailable(false));
  }, []);

  if (!voiceAvailable) return null;

  return (
    <div className={`wl-global-voice-input ${status} ${isExpanded ? 'expanded' : ''}`}>
      {/* Main button */}
      <button
        className="wl-voice-button"
        onClick={handleClick}
        disabled={status === 'processing'}
        title={status === 'recording' ? 'Click to stop' : 'Voice input (Ctrl+Shift+V)'}
      >
        {/* Audio level ring */}
        {status === 'recording' && (
          <div
            className="wl-level-ring"
            style={{
              transform: `scale(${1 + (audioLevel / 100) * 0.4})`,
              opacity: 0.4 + (audioLevel / 100) * 0.6,
            }}
          />
        )}

        {/* Icon */}
        <Icon
          icon={
            status === 'processing' ? 'mdi:loading' :
            status === 'recording' ? 'mdi:stop' :
            status === 'success' ? 'mdi:check' :
            status === 'error' ? 'mdi:alert' :
            'mdi:microphone'
          }
          className={`wl-voice-icon ${status === 'processing' ? 'spinning' : ''}`}
        />

        {/* Recording duration badge */}
        {status === 'recording' && (
          <span className="wl-duration-badge">
            {formatDuration(recordingDuration)}
          </span>
        )}
      </button>

      {/* Expanded info panel */}
      {isExpanded && (
        <div className="wl-info-panel">
          {status === 'recording' && (
            <>
              <div className="wl-waveform">
                {[...Array(5)].map((_, i) => (
                  <div
                    key={i}
                    className="wl-waveform-bar"
                    style={{
                      height: `${Math.max(4, (audioLevel / 100) * 20 * (1 + Math.sin(Date.now() / 200 + i)))}px`
                    }}
                  />
                ))}
              </div>
              <span className="wl-status-text">Listening...</span>
              <span className="wl-hint">Click to stop</span>
            </>
          )}

          {status === 'processing' && (
            <span className="wl-status-text">Transcribing...</span>
          )}

          {status === 'success' && transcript && (
            <div className="wl-transcript-preview">
              <Icon icon="mdi:check-circle" className="wl-success-icon" />
              <span className="wl-transcript-text">
                {transcript.length > 50 ? transcript.slice(0, 47) + '...' : transcript}
              </span>
            </div>
          )}

          {status === 'error' && (
            <span className="wl-error-text">{errorMessage}</span>
          )}

          {(status === 'idle' || status === 'ready') && targetInfo && (
            <span className="wl-target-hint">
              Ready for {targetInfo.placeholder || targetInfo.label || 'input'}
            </span>
          )}
        </div>
      )}

      {/* Keyboard hint - show on hover when idle */}
      <div className="wl-keyboard-hint">
        <kbd>⌘</kbd><kbd>⇧</kbd><kbd>V</kbd>
      </div>
    </div>
  );
}

export default GlobalVoiceInput;
