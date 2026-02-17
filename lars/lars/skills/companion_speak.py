"""
Companion speak skill — pushes text to RVBBIT for TTS playback.

The cascade calls speak("Hello!") → HTTP POST to RVBBIT embedded server
→ ElevenLabs TTS with visemes → particle mouth speaks with karaoke captions.

RVBBIT handles all audio/visual — LARS just sends text.
"""

import os
import requests
from .base import simple_eddy
from ..skill_registry import register_skill
from ..console_style import S


@simple_eddy
def companion_speak(text: str, wait: bool = True) -> str:
    """
    Speak text through the RVBBIT companion overlay.
    
    Sends text to RVBBIT's embedded server which generates ElevenLabs TTS
    with character-level timing, then plays it through the particle mouth
    with viseme lip-sync and karaoke captions.
    
    Args:
        text: The text to speak out loud
        wait: If True, wait for TTS generation to complete before returning
    
    Returns:
        "ok" if successful, error message otherwise
    """
    from rich.console import Console
    console = Console()
    
    rvbbit_port = int(os.environ.get("RVBBIT_PORT", "9876"))
    url = f"http://127.0.0.1:{rvbbit_port}/companion/speak"
    
    console.print(f"[cyan]{S.AGENT} Speaking:[/cyan] {text[:80]}{'...' if len(text) > 80 else ''}")
    
    try:
        resp = requests.post(url, json={"text": text}, timeout=30)
        if resp.status_code == 200:
            console.print(f"[green]{S.OK} Speech dispatched to RVBBIT[/green]")
            return "ok"
        else:
            error_msg = f"RVBBIT returned {resp.status_code}: {resp.text[:200]}"
            console.print(f"[red]{S.WARN} {error_msg}[/red]")
            return error_msg
    except requests.exceptions.ConnectionError:
        msg = f"RVBBIT not reachable on port {rvbbit_port}"
        console.print(f"[yellow]{S.WARN} {msg}[/yellow]")
        return msg
    except Exception as e:
        console.print(f"[red]{S.WARN} Speak failed: {e}[/red]")
        return str(e)


register_skill("companion_speak", companion_speak)
