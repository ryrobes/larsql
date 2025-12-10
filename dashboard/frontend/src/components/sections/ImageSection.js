import React, { useState } from 'react';
import './ImageSection.css';

/**
 * ImageSection - Display images with lightbox support
 *
 * Supports:
 * - Single image display with optional caption
 * - Click to expand in lightbox
 * - Multiple images as gallery
 * - Both URL and base64 sources
 */
function ImageSection({ spec }) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  // Handle multiple images or single image
  const images = spec.gallery && spec.images
    ? spec.images
    : [{ src: spec.src, base64: spec.base64, caption: spec.caption, alt: spec.alt }];

  const getImageSrc = (img) => {
    if (img.base64) {
      // Check if it already has data: prefix
      if (img.base64.startsWith('data:')) {
        return img.base64;
      }
      return `data:image/png;base64,${img.base64}`;
    }
    return img.src;
  };

  const openLightbox = (index) => {
    if (spec.clickable !== false) {
      setCurrentIndex(index);
      setLightboxOpen(true);
    }
  };

  const closeLightbox = () => {
    setLightboxOpen(false);
  };

  const navigateLightbox = (direction) => {
    setCurrentIndex((prev) => {
      const newIndex = prev + direction;
      if (newIndex < 0) return images.length - 1;
      if (newIndex >= images.length) return 0;
      return newIndex;
    });
  };

  return (
    <div className="ui-section image-section">
      <div className={`image-container ${spec.gallery ? 'gallery' : ''}`}>
        {images.map((img, idx) => (
          <div
            key={idx}
            className={`image-wrapper ${spec.clickable !== false ? 'clickable' : ''}`}
            onClick={() => openLightbox(idx)}
            style={{
              maxHeight: spec.max_height || 400,
              maxWidth: spec.max_width || '100%'
            }}
          >
            <img
              src={getImageSrc(img)}
              alt={img.alt || spec.alt || 'Image'}
              style={{
                objectFit: spec.fit || 'contain',
                maxHeight: spec.max_height || 400
              }}
            />
            {spec.clickable !== false && (
              <div className="image-overlay">
                <span className="expand-icon">+</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {spec.caption && (
        <p className="image-caption">{spec.caption}</p>
      )}

      {/* Lightbox Modal */}
      {lightboxOpen && (
        <div className="lightbox-overlay" onClick={closeLightbox}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <button className="lightbox-close" onClick={closeLightbox}>
              &times;
            </button>

            {images.length > 1 && (
              <button
                className="lightbox-nav prev"
                onClick={() => navigateLightbox(-1)}
              >
                &#8249;
              </button>
            )}

            <img
              src={getImageSrc(images[currentIndex])}
              alt={images[currentIndex].alt || 'Image'}
              className="lightbox-image"
            />

            {images.length > 1 && (
              <button
                className="lightbox-nav next"
                onClick={() => navigateLightbox(1)}
              >
                &#8250;
              </button>
            )}

            {images[currentIndex].caption && (
              <p className="lightbox-caption">{images[currentIndex].caption}</p>
            )}

            {images.length > 1 && (
              <div className="lightbox-counter">
                {currentIndex + 1} / {images.length}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default ImageSection;
