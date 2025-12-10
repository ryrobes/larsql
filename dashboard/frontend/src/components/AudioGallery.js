import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '@iconify/react';
import './AudioGallery.css';

/**
 * AudioGallery - Displays audio players for audio files generated during a cascade session.
 * Uses SSE events for real-time updates. Caches audio for completed sessions.
 * @param {string} phaseName - Optional: filter to only show audio from this phase
 */
function AudioGallery({ sessionId, isRunning, sessionUpdate, phaseName }) {
  const [audioFiles, setAudioFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cachedForSession, setCachedForSession] = useState(null);
  const [playingAudio, setPlayingAudio] = useState(null);
  const audioRefs = useRef({});

  const fetchAudio = useCallback(async () => {
    if (!sessionId) return;

    // Smart caching: If session completed and we already have audio, don't re-fetch
    if (!isRunning && cachedForSession === sessionId && audioFiles.length > 0) {
      return;
    }

    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}/audio`);
      if (response.ok) {
        const data = await response.json();
        setAudioFiles(data.audio || []);
        // Mark as cached for this session
        if (!isRunning) {
          setCachedForSession(sessionId);
        }
      }
    } catch (err) {
      console.error('Error fetching audio:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isRunning, cachedForSession, audioFiles.length]);

  // Fetch on mount
  useEffect(() => {
    fetchAudio();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Fetch when THIS session gets an SSE update
  useEffect(() => {
    if (sessionUpdate) {
      fetchAudio();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionUpdate]);

  const handlePlay = (audioPath) => {
    // Pause any currently playing audio
    if (playingAudio && playingAudio !== audioPath) {
      const prevAudio = audioRefs.current[playingAudio];
      if (prevAudio) {
        prevAudio.pause();
      }
    }
    setPlayingAudio(audioPath);
  };

  const handlePause = () => {
    setPlayingAudio(null);
  };

  const handleEnded = () => {
    setPlayingAudio(null);
  };

  if (!sessionId) {
    return null;
  }

  // Filter audio by phase if phaseName is provided
  const filteredAudio = phaseName
    ? audioFiles.filter(audio => audio.phase_name === phaseName)
    : audioFiles;

  if (filteredAudio.length === 0 && !loading) {
    return null; // Don't show anything if no audio
  }

  return (
    <div className="audio-gallery">
      {filteredAudio.map((audio) => {
        const isPlaying = playingAudio === audio.path;
        const audioUrl = `http://localhost:5001${audio.url}`;

        return (
          <div key={audio.path} className={`audio-player-container ${isPlaying ? 'playing' : ''}`}>
            <div className="audio-player-info">
              <Icon icon="mdi:music" width="14" className="audio-icon" />
              <span className="audio-filename" title={audio.filename}>
                {audio.filename.length > 20 ? audio.filename.substring(0, 17) + '...' : audio.filename}
              </span>
            </div>
            <audio
              ref={(el) => { audioRefs.current[audio.path] = el; }}
              src={audioUrl}
              onPlay={() => handlePlay(audio.path)}
              onPause={handlePause}
              onEnded={handleEnded}
              controls
              className="audio-element"
              preload="metadata"
            />
          </div>
        );
      })}
    </div>
  );
}

export default AudioGallery;
