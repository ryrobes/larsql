"""
Speech-to-Text Tools for Cascades

Provides skills (tools) for voice input in cascades:
- listen: Interactive voice input (waits for user to speak)
- transcribe_audio: Transcribe an existing audio file

These tools integrate with the unified logging system for
cost tracking and observability.

Configuration:
- RVBBIT_STT_MODEL: Model name (default: mistralai/voxtral-small-24b-2507)
- Uses standard OPENROUTER_API_KEY from config
"""

import os
import json
from typing import Optional

from .base import simple_eddy
from ..logs import log_message
from ..voice import (
    transcribe,
    transcribe_from_base64,
    save_audio_from_base64,
    is_available as voice_is_available,
    get_stt_config,
)


def is_available() -> bool:
    """Check if STT tools are available."""
    return voice_is_available()


@simple_eddy
def transcribe_audio(
    audio_file_path: str,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    """
    Transcribe an audio file to text using OpenRouter's audio models.

    Use this tool to convert speech in an audio file to text.
    Supports common audio formats: mp3, mp4, mpeg, mpga, m4a, wav, webm.

    Args:
        audio_file_path: Absolute path to the audio file to transcribe
        language: Optional ISO-639-1 language code (e.g., 'en', 'es', 'fr').
                  If not provided, the language will be auto-detected.
        prompt: Optional context or prompt to guide the transcription.
                Useful for domain-specific vocabulary or names.

    Returns:
        JSON string with transcription result:
        {
            "content": "The transcribed text...",
            "metadata": {
                "language": "en",
                "audio_file": "/path/to/audio.mp3"
            }
        }
    """
    # Import here to get current context
    from ..echo import get_echo

    echo = get_echo()

    # Get session context if available
    session_id = None
    trace_id = None
    cell_name = None
    cascade_id = None

    if echo:
        session_id = echo.session_id
        cell_name = getattr(echo, 'current_cell', None)
        cascade_id = getattr(echo, 'cascade_id', None)

    log_message(session_id, "system", f"transcribe_audio: starting for {audio_file_path}",
                metadata={"tool": "transcribe_audio", "file_path": audio_file_path})

    try:
        result = transcribe(
            audio_file_path=audio_file_path,
            language=language,
            prompt=prompt,
            session_id=session_id,
            trace_id=trace_id,
            cell_name=cell_name,
            cascade_id=cascade_id,
        )

        # Return in multi-modal protocol format
        return json.dumps({
            "content": result["text"],
            "metadata": {
                "language": result["language"],
                "audio_file": audio_file_path,
                "model": result["model"],
                "tokens": result.get("tokens", 0),
            },
            "audio": [audio_file_path],
        })

    except FileNotFoundError as e:
        log_message(session_id, "system", f"transcribe_audio: file not found",
                    metadata={"tool": "transcribe_audio", "error": "file_not_found"})
        return json.dumps({
            "content": f"Error: Audio file not found: {audio_file_path}",
            "error": True,
        })

    except Exception as e:
        log_message(session_id, "system", f"transcribe_audio: error {type(e).__name__}: {e}",
                    metadata={"tool": "transcribe_audio", "error": type(e).__name__})
        return json.dumps({
            "content": f"Error transcribing audio: {type(e).__name__}: {e}",
            "error": True,
        })


@simple_eddy
def listen(
    prompt_message: str = "Listening for voice input...",
    language: Optional[str] = None,
    timeout_seconds: int = 30,
) -> str:
    """
    Listen for voice input from the user.

    This tool requests voice input from the user interface. When called,
    the UI will prompt the user to speak, record their audio, and return
    the transcription.

    Note: This tool requires a UI that supports voice recording.
    In CLI mode, this will return an error. Use with the web UI
    or a cascade that has voice UI support.

    Args:
        prompt_message: Message to display while listening (shown in UI)
        language: Optional ISO-639-1 language code for transcription
        timeout_seconds: Maximum time to wait for voice input (default 30s)

    Returns:
        JSON string with transcription result:
        {
            "content": "What the user said...",
            "metadata": {
                "language": "en",
                "duration_seconds": 5.2,
                "input_type": "voice"
            }
        }
    """
    from ..echo import get_echo

    echo = get_echo()
    session_id = echo.session_id if echo else None

    log_message(session_id, "system", f"listen: requesting voice input",
                metadata={
                    "tool": "listen",
                    "prompt": prompt_message,
                    "timeout": timeout_seconds,
                    "language": language
                })

    # Check if we're in a context that supports voice input
    # This requires integration with the UI layer
    #
    # The UI integration works as follows:
    # 1. This tool emits a "voice_input_requested" event
    # 2. The UI listens for this event and shows the recording UI
    # 3. When the user finishes speaking, the UI calls the voice API
    # 4. The transcription is returned via the event system

    try:
        from ..events import get_event_bus, Event
        from datetime import datetime

        bus = get_event_bus()

        # Create a unique request ID for this listen call
        import uuid
        request_id = str(uuid.uuid4())

        # Publish event requesting voice input
        bus.publish(Event(
            type="voice_input_requested",
            session_id=session_id or "unknown",
            timestamp=datetime.now().isoformat(),
            data={
                "request_id": request_id,
                "prompt": prompt_message,
                "language": language,
                "timeout_seconds": timeout_seconds,
            }
        ))

        # Wait for response event
        # This is a synchronous wait - the UI must respond within timeout
        import time
        import threading

        response_received = threading.Event()
        response_data = {"text": None, "error": None}

        def on_voice_response(event):
            if event.data.get("request_id") == request_id:
                response_data["text"] = event.data.get("text")
                response_data["language"] = event.data.get("language")
                response_data["duration"] = event.data.get("duration", 0)
                response_data["error"] = event.data.get("error")
                response_received.set()

        # Subscribe to response events
        bus.subscribe("voice_input_response", on_voice_response)

        try:
            # Wait for response with timeout
            if response_received.wait(timeout=timeout_seconds):
                if response_data["error"]:
                    return json.dumps({
                        "content": f"Voice input error: {response_data['error']}",
                        "error": True,
                    })

                log_message(session_id, "system", f"listen: received transcription",
                            metadata={
                                "tool": "listen",
                                "text_length": len(response_data["text"] or ""),
                                "language": response_data.get("language"),
                            })

                return json.dumps({
                    "content": response_data["text"],
                    "metadata": {
                        "language": response_data.get("language", "unknown"),
                        "duration_seconds": response_data.get("duration", 0),
                        "input_type": "voice",
                    }
                })
            else:
                log_message(session_id, "system", f"listen: timeout",
                            metadata={"tool": "listen", "error": "timeout"})
                return json.dumps({
                    "content": "Voice input timed out. No audio received.",
                    "error": True,
                    "metadata": {"input_type": "voice", "timeout": True}
                })

        finally:
            # Unsubscribe from events
            bus.unsubscribe("voice_input_response", on_voice_response)

    except ImportError:
        # Events module not available - fall back to error
        log_message(session_id, "system", f"listen: events not available",
                    metadata={"tool": "listen", "error": "no_events"})
        return json.dumps({
            "content": "Voice input not available: Event system not configured.",
            "error": True,
            "metadata": {"input_type": "voice"}
        })

    except Exception as e:
        log_message(session_id, "system", f"listen: error {type(e).__name__}: {e}",
                    metadata={"tool": "listen", "error": type(e).__name__})
        return json.dumps({
            "content": f"Voice input error: {type(e).__name__}: {e}",
            "error": True,
        })


@simple_eddy
def process_voice_recording(
    base64_audio: str,
    audio_format: str = "webm",
    language: Optional[str] = None,
) -> str:
    """
    Process a base64-encoded voice recording.

    This tool is called by the UI after recording audio. It saves the
    audio file and transcribes it.

    Args:
        base64_audio: Base64-encoded audio data from browser MediaRecorder
        audio_format: Audio format (webm, mp3, wav, etc.)
        language: Optional language code for transcription

    Returns:
        JSON string with transcription result
    """
    from ..echo import get_echo

    echo = get_echo()
    session_id = echo.session_id if echo else None
    cell_name = getattr(echo, 'current_cell', None) if echo else None
    cascade_id = getattr(echo, 'cascade_id', None) if echo else None

    log_message(session_id, "system", f"process_voice_recording: processing {audio_format} audio",
                metadata={
                    "tool": "process_voice_recording",
                    "format": audio_format,
                    "data_length": len(base64_audio)
                })

    try:
        result = transcribe_from_base64(
            base64_data=base64_audio,
            file_format=audio_format,
            language=language,
            session_id=session_id,
            cell_name=cell_name,
            cascade_id=cascade_id,
        )

        return json.dumps({
            "content": result["text"],
            "metadata": {
                "language": result["language"],
                "model": result["model"],
                "tokens": result.get("tokens", 0),
                "input_type": "voice",
            }
        })

    except Exception as e:
        log_message(session_id, "system", f"process_voice_recording: error {type(e).__name__}: {e}",
                    metadata={"tool": "process_voice_recording", "error": type(e).__name__})
        return json.dumps({
            "content": f"Error processing voice recording: {type(e).__name__}: {e}",
            "error": True,
        })
