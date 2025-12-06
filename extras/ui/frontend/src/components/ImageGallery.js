import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import './ImageGallery.css';

/**
 * ImageGallery - Displays thumbnails for images generated during a cascade session.
 * Uses SSE events for real-time updates. Caches images for completed sessions.
 */
function ImageGallery({ sessionId, isRunning, sessionUpdate }) {
  const [images, setImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cachedForSession, setCachedForSession] = useState(null);

  const fetchImages = useCallback(async () => {
    if (!sessionId) return;

    // Smart caching: If session completed and we already have images, don't re-fetch
    if (!isRunning && cachedForSession === sessionId && images.length > 0) {
      console.log(`[ImageGallery] Using cached images for completed session ${sessionId.substring(0, 8)}`);
      return;
    }

    console.log(`[ImageGallery] Fetching images for session ${sessionId.substring(0, 8)} (running: ${isRunning})`);
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}/images`);
      if (response.ok) {
        const data = await response.json();
        setImages(data.images || []);
        console.log(`[ImageGallery] Fetched ${data.images?.length || 0} images for ${sessionId.substring(0, 8)}`);
        // Mark as cached for this session
        if (!isRunning) {
          setCachedForSession(sessionId);
        }
      }
    } catch (err) {
      console.error('Error fetching images:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isRunning, cachedForSession, images.length]);

  // Fetch on mount
  useEffect(() => {
    fetchImages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Fetch when THIS session gets an SSE update (not global updates)
  useEffect(() => {
    if (sessionUpdate) {
      console.log(`[ImageGallery] Session update detected for ${sessionId.substring(0, 8)}, fetching images`);
      fetchImages();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionUpdate]);

  // No polling! SSE events drive updates via sessionUpdate (per-session timestamp).
  // Completed sessions: Images cached after first fetch, won't re-fetch on subsequent updates.

  const handleImageClick = (image) => {
    setSelectedImage(image);
  };

  const handleCloseModal = () => {
    setSelectedImage(null);
  };

  if (!sessionId) {
    return null;
  }

  if (images.length === 0 && !loading) {
    return null; // Don't show anything if no images
  }

  return (
    <div className="image-gallery">
      <div className="image-gallery-grid">
        {images.map((image, index) => (
          <div
            key={image.path}
            className="image-thumbnail-container"
            onClick={(e) => {
              e.stopPropagation();
              handleImageClick(image);
            }}
          >
            <img
              src={`http://localhost:5001${image.url}`}
              alt={`Image ${index + 1}`}
              className="image-thumbnail"
              loading="lazy"
            />
          </div>
        ))}
      </div>

      {/* Full-size image modal - rendered via portal at document root to avoid hover interaction issues */}
      {selectedImage && createPortal(
        <div className="image-modal-overlay" onClick={handleCloseModal}>
          <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="image-modal-close" onClick={handleCloseModal}>×</button>
            <img
              src={`http://localhost:5001${selectedImage.url}`}
              alt={selectedImage.filename}
              className="image-modal-full"
            />
            <div className="image-modal-info">
              <span className="image-modal-filename">{selectedImage.filename}</span>
              {selectedImage.phase_name && (
                <span className="image-modal-phase">Phase: {selectedImage.phase_name}</span>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

export default ImageGallery;
