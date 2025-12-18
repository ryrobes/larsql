import React, { useState, useEffect, useRef } from 'react';
import './NarrationCaption.css';

/**
 * NarrationCaption - Live transcription display with word-by-word highlighting
 *
 * Shows narration text at bottom of screen with animated highlighting as words are spoken.
 * Uses duration to calculate per-word timing for synchronized highlighting.
 */
function NarrationCaption({ text, duration, isPlaying, amplitude }) {
  const [currentWordIndex, setCurrentWordIndex] = useState(-1);
  const [words, setWords] = useState([]);
  const timeoutsRef = useRef([]);

  // Parse text into words when new narration starts
  useEffect(() => {
    if (!text || !isPlaying) {
      setWords([]);
      setCurrentWordIndex(-1);
      // Clear any pending timeouts
      timeoutsRef.current.forEach(clearTimeout);
      timeoutsRef.current = [];
      return;
    }

    // Remove ElevenLabs voice hints [like this] before displaying
    const cleanedText = text.replace(/\[[^\]]+\]/g, '').trim();

    // Split text into words (preserve punctuation)
    const wordList = cleanedText.split(/(\s+)/).filter(w => w.trim().length > 0);
    setWords(wordList);
    setCurrentWordIndex(0);

    // Calculate timing based on ORIGINAL text length (includes tags)
    // This keeps sync with actual audio timing
    const originalWordCount = text.split(/(\s+)/).filter(w => w.trim().length > 0).length;
    const msPerWord = (duration * 1000) / originalWordCount;

    // Schedule word highlighting
    const timeouts = wordList.map((word, index) => {
      return setTimeout(() => {
        setCurrentWordIndex(index);
      }, index * msPerWord);
    });

    timeoutsRef.current = timeouts;

    // Cleanup
    return () => {
      timeouts.forEach(clearTimeout);
      timeoutsRef.current = [];
    };
  }, [text, duration, isPlaying]);

  // Auto-hide after playback ends
  useEffect(() => {
    if (!isPlaying && currentWordIndex >= 0) {
      // Keep visible for 5 seconds after narration ends
      const hideTimeout = setTimeout(() => {
        setCurrentWordIndex(-1);
        setWords([]);
      }, 5000);

      return () => clearTimeout(hideTimeout);
    }
  }, [isPlaying, currentWordIndex]);

  // Don't render if no words
  if (words.length === 0) return null;

  return (
    <div className={`narration-caption ${isPlaying ? 'active' : 'fading'}`}>
      <div className="caption-text">
        {words.map((word, index) => {
          const isSpoken = index <= currentWordIndex;
          const isCurrent = index === currentWordIndex;

          return (
            <span
              key={index}
              className={`caption-word ${isSpoken ? 'spoken' : ''} ${isCurrent ? 'current' : ''}`}
              style={isCurrent ? {
                // Pulse current word with amplitude
                transform: `scale(${1 + amplitude * 0.15})`,
                textShadow: `0 0 ${8 + amplitude * 12}px rgba(167, 139, 250, ${0.6 + amplitude * 0.4})`
              } : undefined}
            >
              {word}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export default NarrationCaption;
