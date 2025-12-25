import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import { getSequentialColor } from './CascadeBar';
import './MediaGalleryFooter.css';

/**
 * MediaGalleryFooter - Fixed footer showing all media (images, audio, human inputs)
 * from a session with clear phase and sounding attribution.
 * Only renders if there is media to show.
 */
function MediaGalleryFooter({ sessionId, isRunning, sessionUpdate, phases }) {
  const [images, setImages] = useState([]);
  const [audioFiles, setAudioFiles] = useState([]);
  const [humanInputs, setHumanInputs] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cachedForSession, setCachedForSession] = useState(null);
  const [apiSoundingWinner, setApiSoundingWinner] = useState(null);
  const [playingAudio, setPlayingAudio] = useState(null);
  const audioRefs = useRef({});

  const fetchMedia = useCallback(async () => {
    if (!sessionId) return;

    // Smart caching: If session completed and we already have data, don't re-fetch
    if (!isRunning && cachedForSession === sessionId) {
      return;
    }

    try {
      setLoading(true);

      // Fetch all media types in parallel
      const [imagesRes, audioRes, humanRes] = await Promise.all([
        fetch(`http://localhost:5001/api/session/${sessionId}/images`),
        fetch(`http://localhost:5001/api/session/${sessionId}/audio`),
        fetch(`http://localhost:5001/api/session/${sessionId}/human-inputs`)
      ]);

      if (imagesRes.ok) {
        const data = await imagesRes.json();
        setImages(data.images || []);
        setApiSoundingWinner(data.sounding_winner_index);
      }

      if (audioRes.ok) {
        const data = await audioRes.json();
        setAudioFiles(data.audio || []);
      }

      if (humanRes.ok) {
        const data = await humanRes.json();
        setHumanInputs(data.human_inputs || []);
      }

      if (!isRunning) {
        setCachedForSession(sessionId);
      }
    } catch (err) {
      console.error('Error fetching media:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isRunning, cachedForSession]);

  useEffect(() => {
    fetchMedia();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (sessionUpdate) {
      fetchMedia();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionUpdate]);

  // Build phase index map for colors
  const cellIndexMap = useMemo(() => {
    const map = {};
    (phases || []).forEach((phase, idx) => {
      map[phase.name] = idx;
    });
    return map;
  }, [phases]);

  // Group images by phase, then by sounding/reforge
  const groupedImages = useMemo(() => {
    const byPhase = {};

    images.forEach(image => {
      const phaseName = image.cell_name || 'Unknown';
      if (!byPhase[phaseName]) {
        byPhase[phaseName] = {
          phaseName,
          cellIndex: cellIndexMap[phaseName] ?? -1,
          soundings: {},
          reforges: [],
          main: [],
          soundingWinnerIndex: null
        };
      }

      const hasReforge = image.reforge_step !== null && image.reforge_step !== undefined;
      const hasSounding = image.candidate_index !== null && image.candidate_index !== undefined;

      if (hasReforge) {
        byPhase[phaseName].reforges.push(image);
      } else if (hasSounding) {
        const idx = image.candidate_index;
        if (!byPhase[phaseName].soundings[idx]) {
          byPhase[phaseName].soundings[idx] = {
            index: idx,
            images: [],
            isWinner: false
          };
        }
        byPhase[phaseName].soundings[idx].images.push(image);
        if (image.sounding_is_winner) {
          byPhase[phaseName].soundings[idx].isWinner = true;
          byPhase[phaseName].soundingWinnerIndex = idx;
        }
      } else {
        byPhase[phaseName].main.push(image);
      }
    });

    // Use API-provided winner if available
    if (apiSoundingWinner !== null) {
      Object.values(byPhase).forEach(phase => {
        if (phase.candidates[apiSoundingWinner]) {
          phase.soundingWinnerIndex = apiSoundingWinner;
          Object.values(phase.candidates).forEach(s => {
            s.isWinner = s.index === apiSoundingWinner;
          });
        }
      });
    }

    // Sort reforges by step
    Object.values(byPhase).forEach(phase => {
      phase.reforges.sort((a, b) => (a.reforge_step || 0) - (b.reforge_step || 0));
    });

    return Object.values(byPhase).sort((a, b) => a.cellIndex - b.cellIndex);
  }, [images, cellIndexMap, apiSoundingWinner]);

  // Group audio by phase
  const groupedAudio = useMemo(() => {
    const byPhase = {};
    audioFiles.forEach(audio => {
      const phaseName = audio.cell_name || 'Unknown';
      if (!byPhase[phaseName]) {
        byPhase[phaseName] = {
          phaseName,
          cellIndex: cellIndexMap[phaseName] ?? -1,
          files: []
        };
      }
      byPhase[phaseName].files.push(audio);
    });
    return Object.values(byPhase).sort((a, b) => a.cellIndex - b.cellIndex);
  }, [audioFiles, cellIndexMap]);

  // Flatten human inputs interactions
  const allHumanInteractions = useMemo(() => {
    return humanInputs.flatMap(p =>
      (p.interactions || []).map(i => ({
        ...i,
        cell_name: p.cell_name,
        cellIndex: cellIndexMap[p.cell_name] ?? -1
      }))
    );
  }, [humanInputs, cellIndexMap]);

  const handleImageClick = (image) => {
    setSelectedImage(image);
  };

  const handleCloseModal = () => {
    setSelectedImage(null);
  };

  const handleAudioPlay = (audioPath) => {
    if (playingAudio && playingAudio !== audioPath) {
      const prevAudio = audioRefs.current[playingAudio];
      if (prevAudio) prevAudio.pause();
    }
    setPlayingAudio(audioPath);
  };

  const handleAudioPause = () => {
    setPlayingAudio(null);
  };

  // Check if we have any media
  const hasImages = images.length > 0;
  const hasAudio = audioFiles.length > 0;
  const hasHumanInputs = allHumanInteractions.length > 0;
  const hasAnyMedia = hasImages || hasAudio || hasHumanInputs;

  if (!hasAnyMedia && !loading) {
    return null;
  }

  const totalCount = images.length + audioFiles.length + allHumanInteractions.length;

  return (
    <div className="media-gallery-footer">
      <div className="media-footer-header">
        <Icon icon="mdi:folder-multiple-image" width="14" />
        <span>Media</span>
        <span className="media-count">{totalCount}</span>
      </div>

      <div className="media-footer-content">
        {/* Images Section */}
        {hasImages && (
          <div className="media-section">
            <div className="media-section-label">
              <Icon icon="mdi:image" width="12" />
              <span>{images.length}</span>
            </div>
            <div className="media-section-content">
              {groupedImages.map((phaseGroup) => {
                const phaseColor = phaseGroup.cellIndex >= 0
                  ? getSequentialColor(phaseGroup.cellIndex)
                  : '#6B7280';

                const soundingIndices = Object.keys(phaseGroup.candidates)
                  .map(k => parseInt(k))
                  .sort((a, b) => a - b);

                const hasContent = phaseGroup.main.length > 0 ||
                  soundingIndices.length > 0 ||
                  phaseGroup.reforges.length > 0;

                if (!hasContent) return null;

                const ultimateWinner = phaseGroup.reforges.find(img => img.reforge_is_winner);

                return (
                  <div key={phaseGroup.phaseName} className="media-phase-group">
                    <div className="media-phase-badge" style={{ backgroundColor: phaseColor }}>
                      {phaseGroup.phaseName}
                    </div>

                    <div className="media-phase-content">
                      {/* Main images */}
                      {phaseGroup.main.length > 0 && (
                        <div className="media-sounding-group">
                          <div className="media-images-row">
                            {phaseGroup.main.map((image) => (
                              <MediaThumbnail
                                key={image.path}
                                image={image}
                                onClick={handleImageClick}
                              />
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Sounding groups */}
                      {soundingIndices.map(idx => {
                        const sounding = phaseGroup.candidates[idx];
                        const isWinner = sounding.isWinner;

                        return (
                          <div key={`s${idx}`} className={`media-sounding-group ${isWinner ? 'is-winner' : ''}`}>
                            <div className="media-sounding-header">
                              <span className={`media-sounding-badge ${isWinner ? 'winner' : ''}`}>
                                S{idx}
                                {isWinner && <Icon icon="mdi:trophy" width="12" />}
                              </span>
                              <span className="media-sounding-count">{sounding.images.length}</span>
                            </div>
                            <div className="media-images-row">
                              {sounding.images.map((image) => (
                                <MediaThumbnail
                                  key={image.path}
                                  image={image}
                                  onClick={handleImageClick}
                                  isWinner={isWinner}
                                />
                              ))}
                            </div>
                          </div>
                        );
                      })}

                      {/* Reforge groups */}
                      {phaseGroup.reforges.length > 0 && (
                        <div className="media-reforge-section">
                          <div className="media-reforge-header">
                            <Icon icon="mdi:auto-fix" width="12" />
                            <span>Reforges</span>
                            {phaseGroup.soundingWinnerIndex !== null && (
                              <span className="media-refined-from">from S{phaseGroup.soundingWinnerIndex}</span>
                            )}
                          </div>
                          <div className="media-images-row">
                            {phaseGroup.reforges.map((image) => {
                              const isUltimate = ultimateWinner && image.path === ultimateWinner.path;
                              return (
                                <div key={image.path} className={`media-reforge-item ${isUltimate ? 'is-ultimate' : ''}`}>
                                  <span className={`media-reforge-badge ${isUltimate ? 'ultimate' : ''}`}>
                                    R{image.reforge_step}
                                    {isUltimate && <Icon icon="mdi:crown" width="10" />}
                                  </span>
                                  <MediaThumbnail
                                    image={image}
                                    onClick={handleImageClick}
                                    isUltimate={isUltimate}
                                  />
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Audio Section */}
        {hasAudio && (
          <div className="media-section audio-section">
            <div className="media-section-label">
              <Icon icon="mdi:music" width="12" />
              <span>{audioFiles.length}</span>
            </div>
            <div className="media-section-content">
              {groupedAudio.map((phaseGroup) => {
                const phaseColor = phaseGroup.cellIndex >= 0
                  ? getSequentialColor(phaseGroup.cellIndex)
                  : '#6B7280';

                return (
                  <div key={phaseGroup.phaseName} className="media-phase-group">
                    <div className="media-phase-badge" style={{ backgroundColor: phaseColor }}>
                      {phaseGroup.phaseName}
                    </div>
                    <div className="media-audio-list">
                      {phaseGroup.files.map((audio) => {
                        const isPlaying = playingAudio === audio.path;
                        return (
                          <div key={audio.path} className={`media-audio-item ${isPlaying ? 'playing' : ''}`}>
                            <audio
                              ref={(el) => { audioRefs.current[audio.path] = el; }}
                              src={`http://localhost:5001${audio.url}`}
                              onPlay={() => handleAudioPlay(audio.path)}
                              onPause={handleAudioPause}
                              onEnded={handleAudioPause}
                              controls
                              preload="metadata"
                            />
                            <span className="media-audio-name" title={audio.filename}>
                              {audio.filename.length > 15 ? audio.filename.substring(0, 12) + '...' : audio.filename}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Human Input Section */}
        {hasHumanInputs && (
          <div className="media-section human-section">
            <div className="media-section-label">
              <Icon icon="mdi:account-question" width="12" />
              <span>{allHumanInteractions.length}</span>
            </div>
            <div className="media-section-content">
              {allHumanInteractions.map((interaction, idx) => {
                const phaseColor = interaction.cellIndex >= 0
                  ? getSequentialColor(interaction.cellIndex)
                  : '#6B7280';

                return (
                  <div key={idx} className="media-human-item">
                    <div className="media-phase-badge small" style={{ backgroundColor: phaseColor }}>
                      {interaction.cell_name}
                    </div>
                    <div className="media-human-content">
                      <span className="media-human-question" title={interaction.question}>
                        {interaction.question?.length > 40
                          ? interaction.question.substring(0, 37) + '...'
                          : interaction.question}
                      </span>
                      <span className={`media-human-response ${interaction.type}`}>
                        {interaction.response || 'Pending...'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Full-size image modal */}
      {selectedImage && createPortal(
        <div className="media-modal-overlay" onClick={handleCloseModal}>
          <div className="media-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="media-modal-close" onClick={handleCloseModal}>
              <Icon icon="mdi:close" width="24" />
            </button>
            <img
              src={`http://localhost:5001${selectedImage.url}`}
              alt={selectedImage.filename}
              className="media-modal-image"
            />
            <div className="media-modal-info">
              <span className="media-modal-filename">{selectedImage.filename}</span>
              <div className="media-modal-badges">
                {selectedImage.cell_name && (
                  <span className="media-modal-phase">
                    <Icon icon="mdi:layers" width="12" />
                    {selectedImage.cell_name}
                  </span>
                )}
                {selectedImage.candidate_index !== null && selectedImage.candidate_index !== undefined && (
                  <span className={`media-modal-sounding ${selectedImage.sounding_is_winner ? 'winner' : ''}`}>
                    S{selectedImage.candidate_index}
                    {selectedImage.sounding_is_winner && <Icon icon="mdi:trophy" width="12" />}
                  </span>
                )}
                {selectedImage.reforge_step !== null && selectedImage.reforge_step !== undefined && (
                  <span className={`media-modal-reforge ${selectedImage.reforge_is_winner ? 'ultimate' : ''}`}>
                    R{selectedImage.reforge_step}
                    {selectedImage.reforge_is_winner && <Icon icon="mdi:crown" width="12" />}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

/**
 * MediaThumbnail - Individual image thumbnail
 */
function MediaThumbnail({ image, onClick, isWinner, isUltimate }) {
  let className = 'media-thumbnail';
  if (isWinner) className += ' is-winner';
  if (isUltimate) className += ' is-ultimate';

  return (
    <div
      className={className}
      onClick={(e) => {
        e.stopPropagation();
        onClick(image);
      }}
      title={image.filename}
    >
      <img
        src={`http://localhost:5001${image.url}`}
        alt={image.filename}
        loading="lazy"
      />
    </div>
  );
}

export default MediaGalleryFooter;
