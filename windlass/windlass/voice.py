"""
Voice Transcription Service - Speech-to-Text via OpenRouter

This module provides speech-to-text transcription using Agent.transcribe(),
ensuring proper cost tracking and logging through the unified system.

Key Features:
- Uses Agent.transcribe() which goes through litellm for proper tracking
- Default model: mistralai/voxtral-small-24b-2507 (configurable via config.stt_model)
- Logs to unified_logs with cost tracking via request_id
- Supports session context for cascade integration

Configuration:
- WINDLASS_STT_MODEL: Model name (default: mistralai/voxtral-small-24b-2507)
- Uses standard OPENROUTER_API_KEY from config
"""

import os
import base64
from typing import Optional, Dict, Any
from datetime import datetime

from .config import get_config
from .logs import log_message


# ============================================================================
# Configuration
# ============================================================================

def get_stt_config() -> Dict[str, Any]:
    """Get STT configuration from environment."""
    cfg = get_config()

    return {
        "api_key": cfg.provider_api_key,
        "base_url": cfg.provider_base_url,
        "model": cfg.stt_model,
    }


def is_available() -> bool:
    """Check if STT is configured and available."""
    config = get_stt_config()
    return bool(config["api_key"])


# ============================================================================
# Transcription Functions
# ============================================================================

def transcribe(
    audio_file_path: str,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    # Logging context
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcribe audio file to text using Agent.transcribe().

    All calls go through the standard Agent pipeline for proper
    cost tracking and logging.

    Args:
        audio_file_path: Path to audio file (mp3, mp4, mpeg, mpga, m4a, wav, webm)
        language: ISO-639-1 language code (e.g., 'en', 'es', 'fr') - auto-detect if None
        prompt: Optional context/prompt to guide transcription
        session_id: Session ID for logging (auto-generated if None)
        trace_id: Trace ID for logging (auto-generated if None)
        parent_id: Parent trace ID for hierarchy
        phase_name: Phase name for cascade context
        cascade_id: Cascade ID for cascade context

    Returns:
        dict with keys:
            - text: Transcribed text
            - language: Detected/specified language
            - model: Model used
            - tokens: Total tokens used
            - session_id: Session ID used for logging
            - trace_id: Trace ID used for logging
    """
    from .agent import Agent

    # Generate session_id if not provided
    if session_id is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"voice_stt_{timestamp}"

    # Validate file exists
    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    # Get file info
    file_size = os.path.getsize(audio_file_path)
    file_name = os.path.basename(audio_file_path)

    # Check file size (reasonable limit)
    if file_size > 25 * 1024 * 1024:
        raise ValueError(f"Audio file too large: {file_size} bytes (max 25MB)")

    log_message(session_id, "system", f"transcribe: starting for {file_name} ({file_size} bytes)",
                metadata={"tool": "transcribe", "file_path": audio_file_path, "file_size": file_size})

    # Read and encode audio as base64
    with open(audio_file_path, 'rb') as f:
        audio_bytes = f.read()
    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

    # Determine format from extension
    ext = os.path.splitext(audio_file_path)[1].lower().lstrip('.')
    audio_format = ext if ext else "webm"

    # Use Agent.transcribe() for the actual call
    result = Agent.transcribe(
        audio_base64=audio_base64,
        audio_format=audio_format,
        language=language,
        prompt=prompt,
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        phase_name=phase_name,
        cascade_id=cascade_id,
    )

    log_message(session_id, "system", f"transcribe: complete",
                metadata={
                    "tool": "transcribe",
                    "text_length": len(result.get("text", "")),
                    "tokens": result.get("tokens", 0),
                })

    return result


def transcribe_from_base64(
    base64_data: str,
    file_format: str = "webm",
    language: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Transcribe base64-encoded audio directly using Agent.transcribe().

    This is the preferred method for browser integration where audio
    comes as base64-encoded data from MediaRecorder.

    Args:
        base64_data: Base64-encoded audio data
        file_format: Audio format (webm, mp3, wav, etc.)
        language: Language code for transcription
        session_id: Session ID for logging
        **kwargs: Additional arguments (ignored for compatibility)

    Returns:
        Transcription result dict
    """
    from .agent import Agent

    # Generate session_id if not provided
    if session_id is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"voice_stt_{timestamp}"

    log_message(session_id, "system", f"transcribe_from_base64: starting ({file_format})",
                metadata={"tool": "transcribe", "format": file_format, "data_length": len(base64_data)})

    # Use Agent.transcribe() directly with base64 data
    result = Agent.transcribe(
        audio_base64=base64_data,
        audio_format=file_format,
        language=language,
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        phase_name=phase_name,
        cascade_id=cascade_id,
    )

    log_message(session_id, "system", f"transcribe_from_base64: complete",
                metadata={
                    "tool": "transcribe",
                    "text_length": len(result.get("text", "")),
                    "tokens": result.get("tokens", 0),
                })

    return result


def save_audio_from_base64(
    base64_data: str,
    file_format: str = "webm",
    session_id: Optional[str] = None,
) -> str:
    """
    Save base64-encoded audio data to a file.

    Used when you need to persist the audio file (e.g., for auditing).
    For transcription, prefer transcribe_from_base64() which doesn't
    need to save the file.

    Args:
        base64_data: Base64-encoded audio data
        file_format: Audio format (webm, mp3, wav, etc.)
        session_id: Session ID for naming the file

    Returns:
        Path to saved audio file
    """
    cfg = get_config()

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    session_suffix = f"_{session_id}" if session_id else ""
    filename = f"recording_{timestamp}{session_suffix}.{file_format}"
    filepath = os.path.join(cfg.audio_dir, filename)

    # Decode and save
    audio_bytes = base64.b64decode(base64_data)

    with open(filepath, 'wb') as f:
        f.write(audio_bytes)

    log_message(session_id, "system", f"save_audio: saved {len(audio_bytes)} bytes to {filename}",
                metadata={"tool": "save_audio", "filepath": filepath, "size": len(audio_bytes)})

    return filepath
