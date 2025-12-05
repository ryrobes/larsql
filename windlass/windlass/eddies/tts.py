"""ElevenLabs Text-to-Speech tool."""

import os
import io
from typing import Optional

from .base import simple_eddy
from ..logs import log_message

# Configuration from environment
ELEVENLABS_API_KEY: Optional[str] = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: Optional[str] = os.environ.get("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL_ID: str = "eleven_v3"  # Hardcoded per requirements


def is_available() -> bool:
    """Check if ElevenLabs TTS is configured and available."""
    return bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)


@simple_eddy
def say(text: str) -> str:
    """
    Speak text aloud using ElevenLabs text-to-speech.

    This tool converts text to speech using ElevenLabs' API and plays
    the audio through the system speakers. Use this for:
    - Announcing results or status updates
    - Reading content aloud to the user
    - Providing audio feedback

    Args:
        text: The text to speak aloud (max ~5000 characters recommended)

    Returns:
        Confirmation message indicating the text was spoken
    """
    import requests

    # Validate configuration (defensive - should be caught at registration)
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return "Error: ElevenLabs not configured. Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID."

    # Try to import miniaudio
    try:
        import miniaudio
    except ImportError:
        return "Error: miniaudio not installed. Run: pip install miniaudio"

    text_preview = text[:100] + "..." if len(text) > 100 else text
    log_message(None, "system", f"say: requesting TTS for {len(text)} chars",
                metadata={"tool": "say", "text_length": len(text)})

    # Build API request
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}?output_format=mp3_44100_128"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
        },
    }

    try:
        # Request audio from ElevenLabs
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        # Get audio bytes
        audio_data = response.content

        log_message(None, "system", f"say: received {len(audio_data)} bytes of audio",
                    metadata={"tool": "say", "audio_bytes": len(audio_data)})

        # Decode MP3 and play using miniaudio
        decoded = miniaudio.decode(audio_data, output_format=miniaudio.SampleFormat.SIGNED16)

        # Create playback device and play
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=decoded.nchannels,
            sample_rate=decoded.sample_rate
        )

        # Convert to generator for streaming playback
        audio_generator = miniaudio.stream_memory(audio_data, output_format=miniaudio.SampleFormat.SIGNED16)
        device.start(audio_generator)

        # Wait for playback to complete
        import time
        # Calculate duration: samples / sample_rate
        duration_seconds = len(decoded.samples) / (decoded.sample_rate * decoded.nchannels)
        time.sleep(duration_seconds + 0.5)  # Add small buffer

        device.close()

        log_message(None, "system", f"say: playback complete",
                    metadata={"tool": "say", "duration_seconds": duration_seconds})

        return f'Spoke: "{text_preview}"'

    except requests.exceptions.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.text[:200]
        except Exception:
            pass
        log_message(None, "system", f"say: API error {e.response.status_code}",
                    metadata={"tool": "say", "error": "http", "status_code": e.response.status_code})
        return f"Error: ElevenLabs API error: {e.response.status_code} - {error_detail}"

    except requests.exceptions.Timeout:
        log_message(None, "system", "say: request timeout",
                    metadata={"tool": "say", "error": "timeout"})
        return "Error: ElevenLabs API request timed out"

    except Exception as e:
        log_message(None, "system", f"say: error {type(e).__name__}: {e}",
                    metadata={"tool": "say", "error": type(e).__name__})
        return f"Error: {type(e).__name__}: {e}"
