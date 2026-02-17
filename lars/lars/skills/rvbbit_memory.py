"""
RVBBIT Companion memory — persistent notes that survive across sessions.

This is Calliope's long-term memory. A simple markdown file (CALLIOPE.md)
in the warren directory that she can read/write/append to freely.

Anything she thinks is important — user preferences, data patterns,
configuration decisions, project context — goes here. The file is
always injected into her context window, so she "remembers" it.

Think of it like OpenClaw's MEMORY.md — the agent controls its own memory.
"""

import os
import json
import time
from typing import Optional
from .base import simple_eddy
from ..skill_registry import register_skill
from ..console_style import S


def _get_memory_path() -> str:
    """Get path to Calliope's memory file in the current warren."""
    # Check for warren-specific memory first
    warren_dir = os.environ.get("RVBBIT_WARREN_DIR", "")
    if warren_dir and os.path.isdir(warren_dir):
        return os.path.join(warren_dir, "CALLIOPE.md")
    
    # Fall back to RVBBIT app support directory
    app_support = os.path.expanduser("~/Library/Application Support/RVBBIT")
    os.makedirs(app_support, exist_ok=True)
    return os.path.join(app_support, "CALLIOPE.md")


def _ensure_memory_file(path: str) -> None:
    """Create the memory file with a header if it doesn't exist."""
    if not os.path.exists(path):
        header = """# CALLIOPE.md — Companion Memory

*This file is mine. I write things here that I want to remember across sessions.*
*It's always in my context window, so anything here, I know.*

---

## User Preferences
*(What the user likes, how they work, their style)*

## Data Sources
*(Connected databases, what they contain, important tables)*

## Decisions
*(Architecture choices, configuration decisions, things we agreed on)*

## Observations
*(Patterns I've noticed, anomalies, things to watch)*

## Notes
*(Anything else worth remembering)*

---
"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(header)


@simple_eddy
def memory_read() -> str:
    """
    Read your persistent memory file (CALLIOPE.md).
    
    Returns the full contents of your memory file. This is automatically
    injected into your context, but you can read it explicitly to review
    or decide what to update.
    
    Returns:
        The full text of CALLIOPE.md
    """
    from rich.console import Console
    console = Console()
    
    path = _get_memory_path()
    _ensure_memory_file(path)
    
    try:
        with open(path, "r") as f:
            content = f.read()
        console.print(f"[cyan]{S.OK} Memory loaded ({len(content)} chars)[/cyan]")
        return content
    except Exception as e:
        return f"Error reading memory: {e}"


@simple_eddy
def memory_write(content: str) -> str:
    """
    Replace your entire memory file with new content.
    
    Use this for major reorganizations. For adding individual items,
    prefer memory_append instead.
    
    ⚠️ This overwrites the entire file. Make sure you include everything
    you want to keep.
    
    Args:
        content: Full new content for CALLIOPE.md
    
    Returns:
        Confirmation message
    """
    from rich.console import Console
    console = Console()
    
    path = _get_memory_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    try:
        with open(path, "w") as f:
            f.write(content)
        console.print(f"[green]{S.OK} Memory updated ({len(content)} chars)[/green]")
        return f"Memory file updated ({len(content)} chars)"
    except Exception as e:
        return f"Error writing memory: {e}"


@simple_eddy
def memory_append(section: str, text: str) -> str:
    """
    Append a note to a specific section of your memory file.
    
    Finds the section heading (## Section Name) and appends the text
    right after it. If the section doesn't exist, creates it at the end.
    
    Args:
        section: The section heading to append under (e.g., "User Preferences", 
                 "Data Sources", "Observations"). Don't include the ##.
        text: The text to append (will be added as a bullet point with timestamp)
    
    Returns:
        Confirmation message
    """
    from rich.console import Console
    console = Console()
    
    path = _get_memory_path()
    _ensure_memory_file(path)
    
    try:
        with open(path, "r") as f:
            content = f.read()
        
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {text}"
        
        # Find the section
        section_marker = f"## {section}"
        if section_marker in content:
            # Find the next section or end of file
            idx = content.index(section_marker)
            after_header = content.index("\n", idx) + 1
            
            # Find next ## or end
            next_section = content.find("\n## ", after_header)
            if next_section == -1:
                # Append at end
                content = content.rstrip() + f"\n{entry}\n"
            else:
                # Insert before next section
                content = content[:next_section] + f"{entry}\n" + content[next_section:]
        else:
            # Create the section at the end
            content = content.rstrip() + f"\n\n## {section}\n{entry}\n"
        
        with open(path, "w") as f:
            f.write(content)
        
        console.print(f"[green]{S.OK} Appended to [{section}]: {text[:60]}...[/green]")
        return f"Added to {section}: {text[:80]}"
    except Exception as e:
        return f"Error appending to memory: {e}"


# ── Registration ──

register_skill("memory_read", memory_read)
register_skill("memory_write", memory_write)
register_skill("memory_append", memory_append)
