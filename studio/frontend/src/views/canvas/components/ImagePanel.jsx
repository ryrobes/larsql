import React, { useState, useMemo } from 'react';
import './ImagePanel.css';

/**
 * ImagePanel - Renders images with lightbox support
 *
 * Supports:
 * - Single image or gallery (multiple images)
 * - Base64 data URLs
 * - File paths (served via /api/file-image)
 * - HTTP/HTTPS URLs
 *
 * Explicit format:
 * {
 *   format: "image",
 *   src: "/path/to/image.png",  // or base64, or URL
 *   caption: "Optional caption"
 * }
 *
 * For galleries, multiple rows with format: "image"
 *
 * @param {any} content - Image content (single object, array of objects, or raw data)
 */
const ImagePanel = ({ content }) => {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [loadErrors, setLoadErrors] = useState({});

  // Normalize content to array of image objects
  const images = useMemo(() => {
    if (!content) return [];

    // Array of image objects
    if (Array.isArray(content)) {
      return content.map((item, idx) => normalizeImageItem(item, idx));
    }

    // Single image object - check if it has an 'images' array (from cascade output)
    if (typeof content === 'object') {
      // If content has 'images' array (e.g., from image generation cascade)
      if (Array.isArray(content.images) && content.images.length > 0) {
        return content.images.map((imgPath, idx) => ({
          src: resolveImageSrc(imgPath),
          caption: content.caption || '',
          key: idx
        }));
      }
      // Single image object with src/image/etc fields
      return [normalizeImageItem(content, 0)];
    }

    // Raw string (path, URL, or base64)
    if (typeof content === 'string') {
      return [{ src: resolveImageSrc(content), caption: '', key: 0 }];
    }

    return [];
  }, [content]);

  // Normalize a single image item to { src, caption, key }
  function normalizeImageItem(item, idx) {
    if (!item) return { src: '', caption: '', key: idx };

    // Check for various source field names
    const srcField = item.src || item.base64 || item.url || item.path ||
                     item.image || item.img || item.photo || item.thumbnail;

    const src = resolveImageSrc(srcField);
    const caption = item.caption || item.title || item.name || item.alt || '';

    return { src, caption, key: idx };
  }

  // Resolve image source to a usable URL
  function resolveImageSrc(src) {
    if (!src || typeof src !== 'string') return '';

    // Already a data URL
    if (src.startsWith('data:')) {
      return src;
    }

    // HTTP/HTTPS URL
    if (src.startsWith('http://') || src.startsWith('https://')) {
      return src;
    }

    // API image paths (from cascade image generation) - use directly
    if (src.startsWith('/api/images/')) {
      return src;
    }

    // Other API paths - use directly
    if (src.startsWith('/api/')) {
      return src;
    }

    // File path - serve via backend
    // Absolute path or relative path
    if (src.startsWith('/') || src.match(/^[a-zA-Z]:\\/)) {
      return `/api/file-image?path=${encodeURIComponent(src)}`;
    }

    // Relative path without leading slash
    return `/api/file-image?path=${encodeURIComponent(src)}`;
  }

  // Handle image load error
  const handleError = (idx) => {
    setLoadErrors(prev => ({ ...prev, [idx]: true }));
  };

  // Open lightbox
  const openLightbox = (idx) => {
    setLightboxIndex(idx);
    setLightboxOpen(true);
  };

  // Close lightbox
  const closeLightbox = () => {
    setLightboxOpen(false);
  };

  // Navigate lightbox
  const nextImage = (e) => {
    e.stopPropagation();
    setLightboxIndex((prev) => (prev + 1) % images.length);
  };

  const prevImage = (e) => {
    e.stopPropagation();
    setLightboxIndex((prev) => (prev - 1 + images.length) % images.length);
  };

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!lightboxOpen) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowRight') nextImage(e);
    if (e.key === 'ArrowLeft') prevImage(e);
  };

  React.useEffect(() => {
    if (lightboxOpen) {
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [lightboxOpen, images.length]);

  if (images.length === 0) {
    return (
      <div className="image-panel image-panel-empty">
        <span>No image data</span>
      </div>
    );
  }

  const isGallery = images.length > 1;

  // Calculate optimal grid layout for gallery
  // Aims for a roughly square layout that fits the images well
  const getGalleryLayout = (count) => {
    if (count <= 1) return { cols: 1, rows: 1 };
    if (count === 2) return { cols: 2, rows: 1 };
    if (count === 3) return { cols: 3, rows: 1 };
    if (count === 4) return { cols: 2, rows: 2 };
    if (count <= 6) return { cols: 3, rows: 2 };
    if (count <= 9) return { cols: 3, rows: 3 };
    if (count <= 12) return { cols: 4, rows: 3 };
    if (count <= 16) return { cols: 4, rows: 4 };
    // For larger counts, use 4-5 columns
    const cols = count <= 20 ? 5 : Math.min(6, Math.ceil(Math.sqrt(count)));
    const rows = Math.ceil(count / cols);
    return { cols, rows };
  };

  const galleryLayout = getGalleryLayout(images.length);

  return (
    <div className={`image-panel ${isGallery ? 'image-panel-gallery' : ''}`}>
      {/* Image grid */}
      <div
        className={`image-panel-grid ${isGallery ? 'gallery-grid' : 'single-image'}`}
        style={isGallery ? { '--gallery-cols': galleryLayout.cols } : {}}
      >
        {images.map((img, idx) => (
          <div
            key={img.key}
            className="image-panel-item"
            onClick={() => openLightbox(idx)}
          >
            {loadErrors[idx] ? (
              <div className="image-panel-error">
                <span className="error-icon">!</span>
                <span className="error-text">Failed to load</span>
              </div>
            ) : (
              <>
                <img
                  src={img.src}
                  alt={img.caption || `Image ${idx + 1}`}
                  className="image-panel-img"
                  onError={() => handleError(idx)}
                />
                {img.caption && (
                  <div className="image-panel-caption">{img.caption}</div>
                )}
              </>
            )}
          </div>
        ))}
      </div>

      {/* Lightbox modal */}
      {lightboxOpen && (
        <div className="image-lightbox" onClick={closeLightbox}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <img
              src={images[lightboxIndex]?.src}
              alt={images[lightboxIndex]?.caption || ''}
              className="lightbox-img"
            />
            {images[lightboxIndex]?.caption && (
              <div className="lightbox-caption">{images[lightboxIndex].caption}</div>
            )}

            {/* Navigation for gallery */}
            {isGallery && (
              <>
                <button className="lightbox-nav lightbox-prev" onClick={prevImage}>
                  &#8249;
                </button>
                <button className="lightbox-nav lightbox-next" onClick={nextImage}>
                  &#8250;
                </button>
                <div className="lightbox-counter">
                  {lightboxIndex + 1} / {images.length}
                </div>
              </>
            )}

            {/* Close button */}
            <button className="lightbox-close" onClick={closeLightbox}>
              &times;
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ImagePanel;
