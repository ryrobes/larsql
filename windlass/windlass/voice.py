"""
Voice Transcription Service - Speech-to-Text via OpenAI Whisper

This module provides speech-to-text transcription with proper logging to the
unified logging system. All calls are logged to ClickHouse with cost tracking.

Key Features:
- Uses OpenAI Whisper API (works with OpenRouter API keys)
- Logs to unified_logs with cost tracking
- Supports session context for cascade integration
- Auto-generates session IDs for standalone use (voice_stt_<timestamp>)

Configuration:
- WINDLASS_STT_API_KEY: API key (falls back to OPENROUTER_API_KEY)
- WINDLASS_STT_BASE_URL: API base URL (default: https://api.openai.com/v1)
- WINDLASS_STT_MODEL: Model name (default: whisper-1)
"""

import os
import json
import time
import uuid
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from .config import get_config
from .logs import log_message


# ============================================================================
# Configuration
# ============================================================================

def get_stt_config() -> Dict[str, Any]:
    """Get STT configuration from environment."""
    cfg = get_config()

    # API key: prefer dedicated STT key, fall back to OpenRouter key
    api_key = os.getenv("WINDLASS_STT_API_KEY") or cfg.provider_api_key

    # Base URL: OpenAI's endpoint by default (Whisper API)
    base_url = os.getenv("WINDLASS_STT_BASE_URL", "https://api.openai.com/v1")

    # Model: whisper-1 is the default
    model = os.getenv("WINDLASS_STT_MODEL", "whisper-1")

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def is_available() -> bool:
    """Check if STT is configured and available."""
    config = get_stt_config()
    return bool(config["api_key"])


# ============================================================================
# Transcription Function
# ============================================================================

def transcribe(
    audio_file_path: str,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    response_format: str = "verbose_json",
    temperature: float = 0.0,
    # Logging context
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcribe audio file to text using Whisper API.

    All calls are logged to unified_logs with proper cost tracking.

    Args:
        audio_file_path: Path to audio file (mp3, mp4, mpeg, mpga, m4a, wav, webm)
        language: ISO-639-1 language code (e.g., 'en', 'es', 'fr') - auto-detect if None
        prompt: Optional context/prompt to guide transcription
        response_format: Output format (json, text, srt, verbose_json, vtt)
        temperature: Sampling temperature (0.0-1.0)
        session_id: Session ID for logging (auto-generated if None)
        trace_id: Trace ID for logging (auto-generated if None)
        parent_id: Parent trace ID for hierarchy
        phase_name: Phase name for cascade context
        cascade_id: Cascade ID for cascade context

    Returns:
        dict with keys:
            - text: Transcribed text
            - language: Detected/specified language
            - duration: Audio duration in seconds
            - segments: Word-level timestamps (if verbose_json)
            - model: Model used
            - session_id: Session ID used for logging
            - trace_id: Trace ID used for logging
    """
    config = get_stt_config()

    if not config["api_key"]:
        raise ValueError("STT API key not configured. Set WINDLASS_STT_API_KEY or OPENROUTER_API_KEY.")

    # Generate IDs if not provided
    # Use a recognizable session prefix for standalone voice calls
    if session_id is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"voice_stt_{timestamp}"

    if trace_id is None:
        trace_id = str(uuid.uuid4())

    # Validate file exists
    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    # Get file info
    file_size = os.path.getsize(audio_file_path)
    file_name = os.path.basename(audio_file_path)

    # Check file size (Whisper limit is 25MB)
    if file_size > 25 * 1024 * 1024:
        raise ValueError(f"Audio file too large: {file_size} bytes (max 25MB)")

    log_message(session_id, "system", f"transcribe: starting for {file_name} ({file_size} bytes)",
                metadata={"tool": "transcribe", "file_path": audio_file_path, "file_size": file_size})

    # Build API request
    url = f"{config['base_url'].rstrip('/')}/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
    }

    start_time = time.time()

    try:
        with open(audio_file_path, 'rb') as f:
            # Prepare multipart form data
            files = {
                'file': (file_name, f, 'audio/mpeg'),
            }
            data = {
                'model': config['model'],
                'response_format': response_format,
                'temperature': str(temperature),
            }

            if language:
                data['language'] = language
            if prompt:
                data['prompt'] = prompt

            # Make API request
            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, headers=headers, files=files, data=data)
                response.raise_for_status()

        duration_ms = (time.time() - start_time) * 1000

        # Parse response based on format
        if response_format in ("json", "verbose_json"):
            result_data = response.json()
        else:
            # text, srt, vtt formats return plain text
            result_data = {"text": response.text}

        # Extract key fields
        text = result_data.get("text", "")
        detected_language = result_data.get("language", language or "unknown")
        audio_duration = result_data.get("duration", 0)
        segments = result_data.get("segments", [])

        log_message(session_id, "system", f"transcribe: complete in {duration_ms:.0f}ms",
                    metadata={
                        "tool": "transcribe",
                        "text_length": len(text),
                        "duration_ms": duration_ms,
                        "audio_duration": audio_duration,
                        "language": detected_language
                    })

        # Log to unified logging system
        # This ensures the call appears in the database with cost tracking
        _log_transcription(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            phase_name=phase_name,
            cascade_id=cascade_id,
            model=config['model'],
            audio_file=audio_file_path,
            audio_duration=audio_duration,
            text=text,
            language=detected_language,
            duration_ms=duration_ms,
            file_size=file_size,
        )

        return {
            "text": text,
            "language": detected_language,
            "duration": audio_duration,
            "segments": segments,
            "model": config['model'],
            "session_id": session_id,
            "trace_id": trace_id,
        }

    except httpx.HTTPStatusError as e:
        duration_ms = (time.time() - start_time) * 1000
        error_detail = ""
        try:
            error_detail = e.response.text[:500]
        except Exception:
            pass

        log_message(session_id, "system", f"transcribe: API error {e.response.status_code}",
                    metadata={
                        "tool": "transcribe",
                        "error": "http",
                        "status_code": e.response.status_code,
                        "detail": error_detail
                    })

        raise RuntimeError(f"Whisper API error {e.response.status_code}: {error_detail}") from e

    except httpx.TimeoutException as e:
        log_message(session_id, "system", "transcribe: request timeout",
                    metadata={"tool": "transcribe", "error": "timeout"})
        raise RuntimeError("Whisper API request timed out") from e

    except Exception as e:
        log_message(session_id, "system", f"transcribe: error {type(e).__name__}: {e}",
                    metadata={"tool": "transcribe", "error": type(e).__name__})
        raise


def _log_transcription(
    session_id: str,
    trace_id: str,
    parent_id: Optional[str],
    phase_name: Optional[str],
    cascade_id: Optional[str],
    model: str,
    audio_file: str,
    audio_duration: float,
    text: str,
    language: str,
    duration_ms: float,
    file_size: int,
):
    """Log transcription to unified logging system."""
    from .unified_logs import log_unified

    # Estimate cost: Whisper is $0.006 per minute
    # Round up to nearest minute for cost calculation
    import math
    minutes = math.ceil(audio_duration / 60) if audio_duration > 0 else 1
    estimated_cost = minutes * 0.006

    log_unified(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        node_type="transcription",
        role="assistant",  # Treat as assistant response for cost tracking
        depth=0,
        phase_name=phase_name,
        cascade_id=cascade_id,
        model=model,
        provider="openai",  # Whisper is OpenAI
        duration_ms=duration_ms,
        cost=estimated_cost,
        content=text,
        audio=[audio_file],
        metadata={
            "tool": "transcribe",
            "audio_duration_seconds": audio_duration,
            "language": language,
            "file_size": file_size,
            "estimated_cost": estimated_cost,
        }
    )


# ============================================================================
# Streaming Transcription (Future)
# ============================================================================

async def transcribe_stream(
    audio_stream,
    language: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """
    Stream audio for real-time transcription.

    This is a placeholder for future streaming support.
    Currently, Whisper API doesn't support streaming, but this
    could be implemented using:
    - Chunked processing with VAD (voice activity detection)
    - Alternative providers with streaming support
    - Local Whisper with streaming
    """
    raise NotImplementedError("Streaming transcription not yet implemented")


# ============================================================================
# Audio Recording (Browser Integration)
# ============================================================================

def save_audio_from_base64(
    base64_data: str,
    file_format: str = "webm",
    session_id: Optional[str] = None,
) -> str:
    """
    Save base64-encoded audio data to a file.

    Used when receiving audio from browser's MediaRecorder API.

    Args:
        base64_data: Base64-encoded audio data
        file_format: Audio format (webm, mp3, wav, etc.)
        session_id: Session ID for naming the file

    Returns:
        Path to saved audio file
    """
    import base64

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


def transcribe_from_base64(
    base64_data: str,
    file_format: str = "webm",
    language: Optional[str] = None,
    session_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Save base64 audio and transcribe in one call.

    Convenience function for browser integration where audio
    comes as base64-encoded data from MediaRecorder.

    Args:
        base64_data: Base64-encoded audio data
        file_format: Audio format (webm, mp3, wav, etc.)
        language: Language code for transcription
        session_id: Session ID for logging
        **kwargs: Additional arguments passed to transcribe()

    Returns:
        Transcription result dict
    """
    # Save audio file
    audio_path = save_audio_from_base64(base64_data, file_format, session_id)

    # Transcribe
    return transcribe(
        audio_file_path=audio_path,
        language=language,
        session_id=session_id,
        **kwargs
    )
