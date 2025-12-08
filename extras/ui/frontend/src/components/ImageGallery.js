import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import './ImageGallery.css';

/**
 * ImageGallery - Displays thumbnails for images generated during a cascade session.
 * Uses SSE events for real-time updates. Caches images for completed sessions.
 * @param {string} phaseName - Optional: filter to only show images from this phase
 */
function ImageGallery({ sessionId, isRunning, sessionUpdate, phaseName }) {
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

  // Filter images by phase if phaseName is provided
  const filteredImages = phaseName
    ? images.filter(img => img.phase_name === phaseName)
    : images;

  if (filteredImages.length === 0 && !loading) {
    return null; // Don't show anything if no images
  }

  // Group images hierarchically: sounding -> reforge -> images
  const imagesBySounding = {};
  filteredImages.forEach(image => {
    const soundingKey = image.sounding_index !== null && image.sounding_index !== undefined
      ? `sounding_${image.sounding_index}`
      : 'main';

    if (!imagesBySounding[soundingKey]) {
      imagesBySounding[soundingKey] = {};
    }

    const reforgeKey = image.reforge_step !== null && image.reforge_step !== undefined
      ? `reforge_${image.reforge_step}`
      : 'main';

    if (!imagesBySounding[soundingKey][reforgeKey]) {
      imagesBySounding[soundingKey][reforgeKey] = {
        images: [],
        winner_index: image.reforge_winner_index
      };
    }

    imagesBySounding[soundingKey][reforgeKey].images.push(image);
  });

  // Sort sounding groups: main first, then by sounding index
  const sortedSoundingGroups = Object.entries(imagesBySounding).sort(([keyA], [keyB]) => {
    if (keyA === 'main') return -1;
    if (keyB === 'main') return 1;
    const idxA = parseInt(keyA.split('_')[1]);
    const idxB = parseInt(keyB.split('_')[1]);
    return idxA - idxB;
  });

  return (
    <div className="image-gallery">
      {sortedSoundingGroups.map(([soundingKey, reforgeGroups]) => {
        const isSounding = soundingKey !== 'main';
        const soundingIndex = isSounding ? parseInt(soundingKey.split('_')[1]) : null;

        // Sort reforge groups: main first, then by step number
        const sortedReforgeGroups = Object.entries(reforgeGroups).sort(([keyA], [keyB]) => {
          if (keyA === 'main') return -1;
          if (keyB === 'main') return 1;
          const stepA = parseInt(keyA.split('_')[1]);
          const stepB = parseInt(keyB.split('_')[1]);
          return stepA - stepB;
        });

        return (
          <div key={soundingKey} className="sounding-images-group">
            {isSounding && (
              <div className="sounding-label">
                <span className="source-badge" style={{background: '#4ec9b0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px', marginBottom: '4px', display: 'inline-block'}}>
                  S{soundingIndex}
                </span>
              </div>
            )}

            {/* Render reforge groups within this sounding */}
            {sortedReforgeGroups.map(([reforgeKey, reforgeData]) => {
              const isReforge = reforgeKey !== 'main';
              const reforgeStep = isReforge ? parseInt(reforgeKey.split('_')[1]) : null;
              const { images: reforgeImages, winner_index } = reforgeData;

              return (
                <div key={reforgeKey} className="reforge-images-group">
                  {isReforge && (
                    <div className="reforge-label">
                      <span className="source-badge" style={{background: '#c586c0', color: '#1e1e1e', padding: '2px 6px', borderRadius: '3px', fontSize: '11px', marginBottom: '2px', display: 'inline-block'}}>
                        R{reforgeStep}
                      </span>
                      {isSounding && (
                        <span style={{fontSize: '10px', color: '#9AA5B1', marginLeft: '4px'}}>
                          (from S{soundingIndex})
                        </span>
                      )}
                    </div>
                  )}

                  <div className="image-gallery-grid">
                    {reforgeImages.map((image, index) => {
                      // Only highlight images from the WINNING reforge attempt
                      const isReforgeWinner = image.reforge_is_winner === true;

                      return (
                        <div
                          key={image.path}
                          className={`image-thumbnail-container ${isReforgeWinner ? 'reforge-winner-image' : ''}`}
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
                          {isReforgeWinner && (
                            <div className="winner-overlay" title="Winning reforge attempt"><Icon icon="mdi:trophy" width="16" /></div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}

      {/* Full-size image modal - rendered via portal at document root to avoid hover interaction issues */}
      {selectedImage && createPortal(
        <div className="image-modal-overlay" onClick={handleCloseModal}>
          <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="image-modal-close" onClick={handleCloseModal}><Icon icon="mdi:close" width="20" /></button>
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
              {selectedImage.sounding_index !== null && selectedImage.sounding_index !== undefined && (
                <span className="image-modal-sounding">Sounding: {selectedImage.sounding_index}</span>
              )}
              {selectedImage.reforge_step !== null && selectedImage.reforge_step !== undefined && (
                <span className="image-modal-reforge">Reforge Step: {selectedImage.reforge_step}</span>
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
