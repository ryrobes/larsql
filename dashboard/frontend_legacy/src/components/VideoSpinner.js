import React, { useState } from 'react';
import './VideoSpinner.css';

/**
 * VideoSpinner - A loading spinner using a black & white webm video
 * Uses mix-blend-mode: screen to make black transparent and white visible
 *
 * Props:
 *   - message: Optional loading message to display below the video
 *   - size: Size in pixels (number) or CSS value (string like "80%") (default: 120)
 *   - opacity: Opacity of the white parts (default: 0.7)
 *   - messageStyle: Optional custom style object for the message text
 *   - messageClassName: Optional additional class name for the message
 */
function VideoSpinner({ message, size = 120, opacity = 0.7, messageStyle, messageClassName }) {
  const [videoError, setVideoError] = useState(false);

  // Determine if size is a pixel value or a CSS string (like "80%")
  const isPixelSize = typeof size === 'number';
  const sizeValue = isPixelSize ? size : size;
  const fallbackSize = isPixelSize ? size * 0.4 : 48; // For fallback spinner

  // Fallback to CSS spinner if video fails to load
  if (videoError) {
    return (
      <div className="video-spinner-container">
        <div className="spinner-fallback" style={{ width: fallbackSize, height: fallbackSize }}></div>
        {message && (
          <span
            className={`spinner-message ${messageClassName || ''}`}
            style={messageStyle}
          >
            {message}
          </span>
        )}
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
          width: sizeValue,
          height: 'auto', // Maintain aspect ratio when using percentage
          maxWidth: isPixelSize ? undefined : '100%',
          opacity: opacity
        }}
        onError={() => setVideoError(true)}
      >
        <source src="/loading.webm" type="video/webm" />
      </video>
      {message && (
        <span
          className={`spinner-message ${messageClassName || ''}`}
          style={messageStyle}
        >
          {message}
        </span>
      )}
    </div>
  );
}

export default VideoSpinner;
