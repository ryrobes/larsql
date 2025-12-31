import React, { useMemo } from 'react';
import './VideoLoader.css';

/**
 * VideoLoader - Displays a random looping video as a loading indicator
 *
 * Uses videos from /public/videos/:
 * - Large (800px, full color): 001, 002, 004, 006, 008, 010, 012, 014.mp4
 * - Medium (340px, grayscale): 001-015_gray_340.mp4
 * - Small (200px, grayscale): 001-015_gray_200.mp4
 *
 * @param {string} size - 'large' | 'medium' | 'small' (default: 'large')
 * @param {string} className - Additional CSS class
 */
const VideoLoader = ({
  size = 'large',
  className = ''
}) => {
  // Available video indices by size
  const VIDEO_INDICES = {
    large: [1, 2, 4, 6, 8, 10, 12, 14],  // Full color 800px (only these exist)
    medium: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],  // Gray 340px
    small: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]   // Gray 200px
  };

  // Pick a random video on mount (stable for component lifetime)
  const videoSrc = useMemo(() => {
    const indices = VIDEO_INDICES[size] || VIDEO_INDICES.large;
    const randomIndex = indices[Math.floor(Math.random() * indices.length)];
    const paddedIndex = String(randomIndex).padStart(3, '0');

    switch (size) {
      case 'medium':
        return `/videos/${paddedIndex}_gray_340.mp4`;
      case 'small':
        return `/videos/${paddedIndex}_gray_200.mp4`;
      case 'large':
      default:
        return `/videos/${paddedIndex}.mp4`;
    }
  }, [size]);

  return (
    <div className={`video-loader video-loader--${size} ${className}`.trim()}>
      <div className="video-loader__container">
        <video
          autoPlay
          loop
          muted
          playsInline
          className="video-loader__video"
        >
          <source src={videoSrc} type="video/mp4" />
        </video>
      </div>
    </div>
  );
};

export default VideoLoader;
