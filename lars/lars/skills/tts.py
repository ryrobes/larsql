"""ElevenLabs Text-to-Speech tool."""

import os
import io
import json
import tempfile
from typing import Optional

from .base import simple_eddy
from ..logs import log_message

# Configuration from environment
ELEVENLABS_API_KEY: Optional[str] = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: Optional[str] = os.environ.get("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL_ID: str = "eleven_v3"  # Hardcoded per requirements
TTS_VOLUME: float = float(os.environ.get("LARS_TTS_VOLUME", "0.70"))  # Volume 0.0-1.0 (default 70%)


def is_available() -> bool:
    """Check if ElevenLabs TTS is configured and available."""
    return bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)


@simple_eddy
def say(text: str) -> str:
    """
    Speak text aloud using ElevenLabs text-to-speech. Note: When generating the text for ElevenLabs v3 TTS, enhance expressiveness by embedding audio tags in square brackets [] directly in the script where they naturally fit the narrative or dialogue. These tags steer the AI voice for emotions, actions, sounds, accents, or styles—use them sparingly (1-3 per sentence max) to avoid overload, and only when they add meaningful impact without disrupting flow. Tags are somewhat free-form: stick to proven examples like [laughs], [sighs], [whispers], [excited], [sarcastic], [crying], [applause], [gunshot], [sings], or [strong French accent], but experiment with descriptive variations (e.g., [laughs nervously], [shouts angrily], [exhales tiredly]) to discover nuanced effects. Combine with punctuation for rhythm: use ellipses (...) for pauses, CAPS for emphasis, and standard marks for natural cadence. Prioritize matching tags to the context and voice style—e.g., don't force [shouts] on a whispery voice. Test iterations for best results, aiming for emotional depth and immersion.

    This tool converts text to speech using ElevenLabs' API and plays
    the audio through the system speakers. Use this for:

    - Announcing results or status updates
    - Reading content aloud to the user
    - Providing audio feedback

    Note: When generating the text for ElevenLabs v3 TTS, enhance expressiveness by embedding audio tags in square brackets [] directly in the script where they naturally fit the narrative or dialogue. These tags steer the AI voice for emotions, actions, sounds, accents, or styles—use them sparingly (1-3 per sentence max) to avoid overload, and only when they add meaningful impact without disrupting flow. Tags are somewhat free-form: stick to proven examples like [laughs], [sighs], [whispers], [excited], [sarcastic], [crying], [applause], [gunshot], [sings], or [strong French accent], but experiment with descriptive variations (e.g., [laughs nervously], [shouts angrily], [exhales tiredly]) to discover nuanced effects. Combine with punctuation for rhythm: use ellipses (...) for pauses, CAPS for emphasis, and standard marks for natural cadence. Prioritize matching tags to the context and voice style—e.g., don't force [shouts] on a whispery voice. Test iterations for best results, aiming for emotional depth and immersion.

    Output the final script with tags embedded inline.

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

        # Save audio to temporary file for persistence
        temp_audio_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.mp3', delete=False)
        temp_audio_path = temp_audio_file.name
        temp_audio_file.write(audio_data)
        temp_audio_file.close()

        log_message(None, "system", f"say: saved audio to temp file {temp_audio_path}",
                    metadata={"tool": "say", "temp_path": temp_audio_path})

        # Decode MP3 and play using miniaudio
        decoded = miniaudio.decode(audio_data, output_format=miniaudio.SampleFormat.SIGNED16)

        # Apply volume scaling (default 70% to avoid being too loud)
        # Configurable via LARS_TTS_VOLUME env var (0.0-1.0)
        import array
        samples = array.array('h', decoded.samples)  # 'h' = signed 16-bit
        scaled_samples = array.array('h', (int(s * TTS_VOLUME) for s in samples))
        scaled_bytes = scaled_samples.tobytes()

        # Create playback device and play
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=decoded.nchannels,
            sample_rate=decoded.sample_rate
        )

        # Generator that yields scaled audio samples following miniaudio's protocol
        # Miniaudio calls send(framecount) on the generator to request audio chunks
        def scaled_audio_generator():
            nonlocal scaled_bytes
            bytes_per_sample = 2  # 16-bit = 2 bytes
            bytes_per_frame = bytes_per_sample * decoded.nchannels
            offset = 0
            required_frames = yield b""  # First yield primes the generator
            while offset < len(scaled_bytes):
                required_bytes = required_frames * bytes_per_frame
                chunk = scaled_bytes[offset:offset + required_bytes]
                offset += len(chunk)
                required_frames = yield chunk

        # Create and prime the generator before passing to miniaudio
        gen = scaled_audio_generator()
        next(gen)  # Prime the generator (advances to first yield)
        device.start(gen)

        # Wait for playback to complete
        import time
        # Calculate duration: samples / sample_rate
        duration_seconds = len(decoded.samples) / (decoded.sample_rate * decoded.nchannels)
        time.sleep(duration_seconds + 0.5)  # Add small buffer

        device.close()

        log_message(None, "system", f"say: playback complete",
                    metadata={"tool": "say", "duration_seconds": duration_seconds})

        # Return audio protocol (similar to image protocol)
        return json.dumps({
            "content": f'Spoke: "{text_preview}"',
            "audio": [temp_audio_path]
        })

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
