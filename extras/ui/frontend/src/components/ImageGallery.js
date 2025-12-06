import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import './ImageGallery.css';

/**
 * ImageGallery - Displays thumbnails for images generated during a cascade session.
 * Polls the backend API when the session is running to show images in pseudo real-time.
 */
function ImageGallery({ sessionId, isRunning, refreshTrigger }) {
  const [images, setImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchImages = useCallback(async () => {
    if (!sessionId) return;

    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}/images`);
      if (response.ok) {
        const data = await response.json();
        setImages(data.images || []);
      }
    } catch (err) {
      console.error('Error fetching images:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Fetch images on mount and when refreshTrigger changes
  useEffect(() => {
    fetchImages();
  }, [fetchImages, refreshTrigger]);

  // Poll for new images when session is running
  useEffect(() => {
    if (!isRunning || !sessionId) return;

    const pollInterval = setInterval(() => {
      fetchImages();
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(pollInterval);
  }, [isRunning, sessionId, fetchImages]);

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
