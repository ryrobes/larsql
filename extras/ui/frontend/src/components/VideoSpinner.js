import React, { useState } from 'react';
import './VideoSpinner.css';

/**
 * VideoSpinner - A loading spinner using a black & white webm video
 * Uses mix-blend-mode: screen to make black transparent and white visible
 *
 * Props:
 *   - message: Optional loading message to display below the video
 *   - size: Size in pixels (default: 120)
 *   - opacity: Opacity of the white parts (default: 0.7)
 */
function VideoSpinner({ message, size = 120, opacity = 0.7 }) {
  const [videoError, setVideoError] = useState(false);

  // Fallback to CSS spinner if video fails to load
  if (videoError) {
    return (
      <div className="video-spinner-container">
        <div className="spinner-fallback" style={{ width: size * 0.4, height: size * 0.4 }}></div>
        {message && <span className="spinner-message">{message}</span>}
      </div>
    );
  }

  return (
    <div className="video-spinner-container">
      <video
        autoPlay
        loop
        muted
        playsInline
        className="video-spinner"
        style={{
          width: size,
          height: size,
          opacity: opacity
        }}
        onError={() => setVideoError(true)}
      >
        <source src="/loading.webm" type="video/webm" />
      </video>
      {message && <span className="spinner-message">{message}</span>}
    </div>
  );
}

export default VideoSpinner;
