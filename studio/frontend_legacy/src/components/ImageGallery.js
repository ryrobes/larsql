import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import './ImageGallery.css';

/**
 * ImageGallery - Displays thumbnails for images generated during a cascade session.
 * Reorganized to show clear hierarchy: Soundings row → Reforges section
 * @param {string} phaseName - Optional: filter to only show images from this phase
 */
function ImageGallery({ sessionId, isRunning, sessionUpdate, phaseName }) {
  const [images, setImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cachedForSession, setCachedForSession] = useState(null);

  const [apiSoundingWinner, setApiSoundingWinner] = useState(null);

  const fetchImages = useCallback(async () => {
    if (!sessionId) return;

    // Smart caching: If session completed and we already have images, don't re-fetch
    if (!isRunning && cachedForSession === sessionId && images.length > 0) {
      return;
    }

    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5050/api/session/${sessionId}/images`);
      if (response.ok) {
        const data = await response.json();
        setImages(data.images || []);
        setApiSoundingWinner(data.sounding_winner_index);
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

  useEffect(() => {
    fetchImages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (sessionUpdate) {
      fetchImages();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionUpdate]);

  const handleImageClick = (image) => {
    setSelectedImage(image);
  };

  const handleCloseModal = () => {
    setSelectedImage(null);
  };

  // Reorganize images into a clearer structure
  const { soundingImages, reforgeImages, mainImages, soundingWinnerIndex, ultimateWinner } = useMemo(() => {
    const filteredImages = phaseName
      ? images.filter(img => img.cell_name === phaseName)
      : images;

    // Separate into categories
    const main = [];
    const soundings = {};
    const reforges = [];
    let winnerIdx = null;

    filteredImages.forEach(image => {
      const hasReforge = image.reforge_step !== null && image.reforge_step !== undefined;
      const hasSounding = image.candidate_index !== null && image.candidate_index !== undefined;

      if (hasReforge) {
        // This is a reforge image
        reforges.push(image);
      } else if (hasSounding) {
        // This is a sounding image (not reforge)
        const idx = image.candidate_index;
        if (!soundings[idx]) {
          soundings[idx] = [];
        }
        soundings[idx].push(image);
        // Track sounding winner from API-provided field
        if (image.sounding_is_winner && winnerIdx === null) {
          winnerIdx = idx;
        }
      } else {
        // Main/baseline image
        main.push(image);
      }
    });

    // Find the ultimate winner (reforge_is_winner = true)
    const ultimate = reforges.find(img => img.reforge_is_winner === true) || null;

    // Sort reforges by step
    reforges.sort((a, b) => (a.reforge_step || 0) - (b.reforge_step || 0));

    // Prefer API-provided sounding winner, fall back to derived value
    const finalWinnerIdx = apiSoundingWinner !== null ? apiSoundingWinner : winnerIdx;

    return {
      soundingImages: soundings,
      reforgeImages: reforges,
      mainImages: main,
      soundingWinnerIndex: finalWinnerIdx,
      ultimateWinner: ultimate
    };
  }, [images, phaseName, apiSoundingWinner]);

  if (!sessionId) {
    return null;
  }

  const hasSoundings = Object.keys(soundingImages).length > 0;
  const hasReforges = reforgeImages.length > 0;
  const hasMain = mainImages.length > 0;

  if (!hasSoundings && !hasReforges && !hasMain && !loading) {
    return null;
  }

  // Get sorted sounding indices
  const sortedSoundingIndices = Object.keys(soundingImages)
    .map(k => parseInt(k))
    .sort((a, b) => a - b);

  return (
    <div className="image-gallery">
      {/* Main/baseline images (no soundings) */}
      {hasMain && (
        <div className="gallery-section main-section">
          <div className="gallery-row">
            {mainImages.map((image, index) => (
              <ImageThumbnail
                key={image.path}
                image={image}
                onClick={handleImageClick}
                isUltimateWinner={!hasSoundings && !hasReforges && index === 0}
              />
            ))}
          </div>
        </div>
      )}

      {/* Soundings row */}
      {hasSoundings && (
        <div className="gallery-section soundings-section">
          <div className="section-header">
            <Icon icon="mdi:source-fork" width="14" />
            <span>Soundings</span>
            <span className="section-count">{sortedSoundingIndices.length} attempts</span>
          </div>
          <div className="gallery-row soundings-row">
            {sortedSoundingIndices.map(idx => {
              const imgs = soundingImages[idx];
              const isWinner = idx === soundingWinnerIndex;
              // Take first image as representative thumbnail
              const representativeImg = imgs[0];

              return (
                <div key={idx} className={`sounding-item ${isWinner ? 'is-winner' : ''}`}>
                  <div className="sounding-badge">
                    S{idx}
                    {isWinner && <Icon icon="mdi:trophy" width="12" className="winner-icon" />}
                  </div>
                  <div className="sounding-thumbnails">
                    {imgs.slice(0, 3).map((image, i) => (
                      <ImageThumbnail
                        key={image.path}
                        image={image}
                        onClick={handleImageClick}
                        size="small"
                        isSoundingWinner={isWinner}
                        showOverlay={i === 2 && imgs.length > 3}
                        overlayCount={imgs.length - 3}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Reforges section */}
      {hasReforges && (
        <div className="gallery-section reforges-section">
          <div className="section-header reforge-header">
            <Icon icon="mdi:auto-fix" width="14" />
            <span>Reforges</span>
            {soundingWinnerIndex !== null && (
              <span className="refined-from">refined from S{soundingWinnerIndex}</span>
            )}
          </div>
          <div className="gallery-row reforges-row">
            {reforgeImages.map((image, index) => {
              const isUltimate = ultimateWinner && image.path === ultimateWinner.path;
              const step = image.reforge_step;

              return (
                <div key={image.path} className={`reforge-item ${isUltimate ? 'is-ultimate-winner' : ''}`}>
                  <div className={`reforge-badge ${isUltimate ? 'ultimate' : ''}`}>
                    R{step}
                    {isUltimate && <Icon icon="mdi:crown" width="12" className="crown-icon" />}
                  </div>
                  <ImageThumbnail
                    image={image}
                    onClick={handleImageClick}
                    isUltimateWinner={isUltimate}
                    isReforge={true}
                  />
                  {isUltimate && (
                    <div className="ultimate-label">Final Output</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Full-size image modal */}
      {selectedImage && createPortal(
        <div className="image-modal-overlay" onClick={handleCloseModal}>
          <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="image-modal-close" onClick={handleCloseModal}>
              <Icon icon="mdi:close" width="20" />
            </button>
            <img
              src={`http://localhost:5050${selectedImage.url}`}
              alt={selectedImage.filename}
              className="image-modal-full"
            />
            <div className="image-modal-info">
              <span className="image-modal-filename">{selectedImage.filename}</span>
              {selectedImage.cell_name && (
                <span className="image-modal-phase">Phase: {selectedImage.cell_name}</span>
              )}
              {selectedImage.candidate_index !== null && selectedImage.candidate_index !== undefined && (
                <span className="image-modal-sounding">Sounding: S{selectedImage.candidate_index}</span>
              )}
              {selectedImage.reforge_step !== null && selectedImage.reforge_step !== undefined && (
                <span className="image-modal-reforge">
                  Reforge: R{selectedImage.reforge_step}
                  {selectedImage.reforge_is_winner && ' (Winner)'}
                </span>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

// Thumbnail component for consistent rendering
function ImageThumbnail({
  image,
  onClick,
  size = 'normal',
  isSoundingWinner = false,
  isUltimateWinner = false,
  isReforge = false,
  showOverlay = false,
  overlayCount = 0
}) {
  const className = [
    'image-thumbnail-container',
    size === 'small' ? 'size-small' : '',
    isSoundingWinner ? 'sounding-winner' : '',
    isUltimateWinner ? 'ultimate-winner' : '',
    isReforge && !isUltimateWinner ? 'reforge-image' : ''
  ].filter(Boolean).join(' ');

  return (
    <div
      className={className}
      onClick={(e) => {
        e.stopPropagation();
        onClick(image);
      }}
    >
      <img
        src={`http://localhost:5050${image.url}`}
        alt={image.filename}
        className="image-thumbnail"
        loading="lazy"
      />
      {isUltimateWinner && (
        <div className="ultimate-winner-badge">
          <Icon icon="mdi:trophy" width="16" />
        </div>
      )}
      {showOverlay && overlayCount > 0 && (
        <div className="more-images-overlay">+{overlayCount}</div>
      )}
    </div>
  );
}

export default ImageGallery;
