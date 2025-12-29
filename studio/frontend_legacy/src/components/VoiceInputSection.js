import React, { useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import VoiceRecorder from './VoiceRecorder';
import './VoiceInputSection.css';

/**
 * VoiceInputSection - A voice input component for checkpoint panels
 *
 * Provides a rich voice input experience with:
 * - Optional text fallback input
 * - Transcript editing
 * - Visual feedback
 *
 * @param {object} section - Section configuration from checkpoint spec
 * @param {string} section.label - Label for the input
 * @param {string} section.prompt - Prompt message while recording
 * @param {string} section.placeholder - Placeholder for text fallback
 * @param {boolean} section.allow_text_fallback - Show text input option
 * @param {boolean} section.editable_transcript - Allow editing transcript
 * @param {string} section.language - ISO-639-1 language code
 * @param {string} value - Current value
 * @param {function} onChange - Called when value changes
 * @param {string} sessionId - Session ID for transcription logging
 * @param {boolean} disabled - Disable input
 */
function VoiceInputSection({
  section = {},
  value,
  onChange,
  sessionId,
  disabled = false,
}) {
  const [mode, setMode] = useState('voice'); // 'voice' or 'text'
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');

  const {
    label = 'Voice Input',
    prompt = 'Speak your response...',
    placeholder = 'Or type your response here...',
    allow_text_fallback = true,
    editable_transcript = true,
    language,
  } = section;

  const handleTranscript = useCallback((result) => {
    const text = result.text || '';
    onChange(text);
  }, [onChange]);

  const handleTextChange = useCallback((e) => {
    onChange(e.target.value);
  }, [onChange]);

  const handleStartEdit = useCallback(() => {
    setEditValue(value || '');
    setIsEditing(true);
  }, [value]);

  const handleSaveEdit = useCallback(() => {
    onChange(editValue);
    setIsEditing(false);
  }, [editValue, onChange]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setEditValue('');
  }, []);

  const handleClear = useCallback(() => {
    onChange('');
    setIsEditing(false);
  }, [onChange]);

  return (
    <div className={`voice-input-section ${disabled ? 'disabled' : ''}`}>
      {label && (
        <div className="voice-input-label">{label}</div>
      )}

      {/* Mode toggle if text fallback is allowed */}
      {allow_text_fallback && (
        <div className="voice-input-mode-toggle">
          <button
            className={`mode-button ${mode === 'voice' ? 'active' : ''}`}
            onClick={() => setMode('voice')}
            disabled={disabled}
          >
            <Icon icon="mdi:microphone" />
            <span>Voice</span>
          </button>
          <button
            className={`mode-button ${mode === 'text' ? 'active' : ''}`}
            onClick={() => setMode('text')}
            disabled={disabled}
          >
            <Icon icon="mdi:keyboard" />
            <span>Type</span>
          </button>
        </div>
      )}

      {/* Voice input mode */}
      {mode === 'voice' && (
        <div className="voice-input-recorder">
          {!value ? (
            <>
              <VoiceRecorder
                onTranscript={handleTranscript}
                sessionId={sessionId}
                language={language}
                promptMessage={prompt}
                disabled={disabled}
                size="large"
              />
              <div className="voice-input-hint">
                Click the microphone to start recording
              </div>
            </>
          ) : (
            <div className="voice-input-result">
              <div className="result-header">
                <Icon icon="mdi:check-circle" className="success-icon" />
                <span>Transcription complete</span>
              </div>

              {isEditing ? (
                <div className="result-edit">
                  <textarea
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    className="edit-textarea"
                    rows={3}
                    autoFocus
                  />
                  <div className="edit-actions">
                    <button
                      className="edit-button save"
                      onClick={handleSaveEdit}
                    >
                      <Icon icon="mdi:check" />
                      Save
                    </button>
                    <button
                      className="edit-button cancel"
                      onClick={handleCancelEdit}
                    >
                      <Icon icon="mdi:close" />
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="result-content">
                  <div className="result-text">
                    <Icon icon="mdi:format-quote-open" className="quote-icon" />
                    {value}
                  </div>
                  <div className="result-actions">
                    {editable_transcript && (
                      <button
                        className="result-action"
                        onClick={handleStartEdit}
                        disabled={disabled}
                        title="Edit transcript"
                      >
                        <Icon icon="mdi:pencil" />
                      </button>
                    )}
                    <button
                      className="result-action"
                      onClick={handleClear}
                      disabled={disabled}
                      title="Record again"
                    >
                      <Icon icon="mdi:refresh" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Text input mode */}
      {mode === 'text' && (
        <div className="voice-input-text">
          <textarea
            value={value || ''}
            onChange={handleTextChange}
            placeholder={placeholder}
            className="text-input"
            rows={3}
            disabled={disabled}
          />
        </div>
      )}
    </div>
  );
}

export default VoiceInputSection;
