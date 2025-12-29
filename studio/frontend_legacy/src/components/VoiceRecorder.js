import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './VoiceRecorder.css';

/**
 * VoiceRecorder - A reusable voice recording component using MediaRecorder API
 *
 * Features:
 * - Click to start/stop recording
 * - Optional hold-to-record mode
 * - Visual audio level indicator
 * - Transcription via backend API
 * - Real-time status updates
 *
 * @param {function} onTranscript - Called with transcription result
 * @param {function} onRecordingStart - Called when recording starts
 * @param {function} onRecordingEnd - Called when recording ends (before transcription)
 * @param {function} onError - Called on any error
 * @param {string} sessionId - Session ID for logging (optional)
 * @param {string} language - ISO-639-1 language code (optional)
 * @param {boolean} holdToRecord - If true, record while button is held (default: false)
 * @param {boolean} disabled - Disable the recorder
 * @param {string} size - Size variant: 'small', 'medium', 'large' (default: 'medium')
 * @param {string} promptMessage - Message to display while listening
 * @param {boolean} autoTranscribe - Automatically transcribe after recording (default: true)
 */
function VoiceRecorder({
  onTranscript,
  onRecordingStart,
  onRecordingEnd,
  onError,
  sessionId,
  language,
  holdToRecord = false,
  disabled = false,
  size = 'medium',
  promptMessage = 'Listening...',
  autoTranscribe = true,
}) {
  const [status, setStatus] = useState('idle'); // idle, recording, processing, error
  const [audioLevel, setAudioLevel] = useState(0);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [errorMessage, setErrorMessage] = useState(null);
  const [transcript, setTranscript] = useState(null);

  const mediaRecorderRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const animationFrameRef = useRef(null);
  const durationIntervalRef = useRef(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecording();
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (durationIntervalRef.current) {
        clearInterval(durationIntervalRef.current);
      }
    };
  }, []);

  // Update audio level visualization
  const updateAudioLevel = useCallback(() => {
    if (analyserRef.current && status === 'recording') {
      const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(dataArray);

      // Calculate average level
      const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      setAudioLevel(Math.min(100, (average / 128) * 100));

      animationFrameRef.current = requestAnimationFrame(updateAudioLevel);
    }
  }, [status]);

  const startRecording = useCallback(async () => {
    try {
      setErrorMessage(null);
      setTranscript(null);
      audioChunksRef.current = [];

      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        }
      });
      streamRef.current = stream;

      // Set up audio analysis for visualization
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContextRef.current.createMediaStreamSource(stream);
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      source.connect(analyserRef.current);

      // Start audio level monitoring
      updateAudioLevel();

      // Create MediaRecorder with best available format
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
        if (animationFrameRef.current) {
          cancelAnimationFrame(animationFrameRef.current);
        }
        if (durationIntervalRef.current) {
          clearInterval(durationIntervalRef.current);
        }

        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });

        if (onRecordingEnd) {
          onRecordingEnd(audioBlob);
        }

        if (autoTranscribe && audioBlob.size > 0) {
          await transcribeAudio(audioBlob, mimeType);
        } else {
          setStatus('idle');
        }
      };

      // Start recording
      mediaRecorder.start(100); // Collect data every 100ms
      setStatus('recording');
      setRecordingDuration(0);

      // Start duration timer
      durationIntervalRef.current = setInterval(() => {
        setRecordingDuration(prev => prev + 1);
      }, 1000);

      if (onRecordingStart) {
        onRecordingStart();
      }

    } catch (err) {
      console.error('Error starting recording:', err);
      setStatus('error');
      setErrorMessage(
        err.name === 'NotAllowedError'
          ? 'Microphone access denied. Please allow microphone access.'
          : 'Failed to start recording: ' + err.message
      );
      if (onError) {
        onError(err);
      }
    }
  }, [onRecordingStart, onRecordingEnd, autoTranscribe, updateAudioLevel, onError]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
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
  }, []);

  const transcribeAudio = async (audioBlob, mimeType) => {
    setStatus('processing');

    try {
      // Convert blob to base64
      const reader = new FileReader();
      const base64Promise = new Promise((resolve, reject) => {
        reader.onloadend = () => {
          const base64 = reader.result.split(',')[1];
          resolve(base64);
        };
        reader.onerror = reject;
      });
      reader.readAsDataURL(audioBlob);
      const base64Audio = await base64Promise;

      // Determine format from MIME type
      const format = mimeType.includes('webm') ? 'webm' :
                     mimeType.includes('mp4') ? 'm4a' : 'webm';

      // Send to backend for transcription
      const response = await fetch('http://localhost:5050/api/voice/transcribe', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          audio_base64: base64Audio,
          format: format,
          language: language,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Transcription failed: ${response.status}`);
      }

      const result = await response.json();
      setTranscript(result.text);
      setStatus('idle');

      if (onTranscript) {
        onTranscript(result);
      }

    } catch (err) {
      console.error('Transcription error:', err);
      setStatus('error');
      setErrorMessage('Transcription failed: ' + err.message);
      if (onError) {
        onError(err);
      }
    }
  };

  const handleClick = () => {
    if (disabled) return;

    if (status === 'recording') {
      stopRecording();
    } else if (status === 'idle' || status === 'error') {
      startRecording();
    }
  };

  const handleMouseDown = () => {
    if (holdToRecord && !disabled && status !== 'processing') {
      startRecording();
    }
  };

  const handleMouseUp = () => {
    if (holdToRecord && status === 'recording') {
      stopRecording();
    }
  };

  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getStatusIcon = () => {
    switch (status) {
      case 'recording':
        return 'mdi:microphone';
      case 'processing':
        return 'mdi:loading';
      case 'error':
        return 'mdi:microphone-off';
      default:
        return 'mdi:microphone';
    }
  };

  const getStatusText = () => {
    switch (status) {
      case 'recording':
        return promptMessage;
      case 'processing':
        return 'Transcribing...';
      case 'error':
        return errorMessage || 'Error';
      default:
        return holdToRecord ? 'Hold to speak' : 'Click to speak';
    }
  };

  return (
    <div className={`voice-recorder voice-recorder-${size} voice-recorder-${status}`}>
      <button
        className={`voice-recorder-button ${status === 'recording' ? 'recording' : ''}`}
        onClick={holdToRecord ? undefined : handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={holdToRecord && status === 'recording' ? handleMouseUp : undefined}
        onTouchStart={handleMouseDown}
        onTouchEnd={handleMouseUp}
        disabled={disabled || status === 'processing'}
        aria-label={getStatusText()}
      >
        {/* Audio level ring */}
        {status === 'recording' && (
          <div
            className="audio-level-ring"
            style={{
              transform: `scale(${1 + (audioLevel / 100) * 0.5})`,
              opacity: 0.3 + (audioLevel / 100) * 0.7,
            }}
          />
        )}

        <Icon
          icon={getStatusIcon()}
          className={`voice-icon ${status === 'processing' ? 'spinning' : ''}`}
        />

        {/* Recording duration */}
        {status === 'recording' && (
          <div className="recording-duration">
            {formatDuration(recordingDuration)}
          </div>
        )}
      </button>

      <div className="voice-recorder-status">
        {getStatusText()}
      </div>

      {/* Show transcript result */}
      {transcript && status === 'idle' && (
        <div className="voice-transcript">
          <Icon icon="mdi:format-quote-open" className="quote-icon" />
          <span className="transcript-text">{transcript}</span>
        </div>
      )}
    </div>
  );
}

export default VoiceRecorder;
