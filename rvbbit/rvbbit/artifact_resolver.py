"""
Artifact Resolver for Rabbitize Browser Automation

Loads rabbitize artifacts into plain dict structures for Jinja templates.
Supports:
- {{ outputs.browser_1.images.0 }} → Base64 data URL (multimodal attachment)
- {{ outputs.browser_1.dom_coords.0 }} → File contents as text
- {{ outputs.browser_1.dom_snapshots.0 }} → File contents as text
- {{ outputs.browser_1.video }} → File path

Simple approach: Load all artifacts into memory as regular Python dicts/lists.
No custom classes, no magic methods - just plain data.
"""

import os
import glob
from typing import Dict, Any, List, Union
from .utils import encode_image_base64
from .config import get_config


def load_rabbitize_artifacts(cell_name: str, session_id: str) -> Dict[str, Any]:
    """
    Load all rabbitize artifacts for a phase into a plain dict structure.

    Returns structure like:
    {
        'images': ['data:image/png;base64,...', 'data:image/png;base64,...'],
        'dom_snapshots': ['<html>...</html>', '<html>...</html>'],
        'dom_coords': ['{"x": 123, ...}', '{"x": 456, ...}'],
        'video': '/path/to/video.webm'
    }

    This is just regular data - Jinja templates work naturally.
    Images are base64 data URLs, which convert_to_multimodal_content() auto-detects.
    """
    import re

    root = get_config().root_dir
    rabbitize_runs = os.path.join(root, "rabbitize-runs")

    # Initialize with empty lists for all types (so Jinja can access even if no files)
    artifacts = {
        'images': [],
        'dom_snapshots': [],
        'dom_coords': [],
        'video': None
    }

    # Helper to find artifact directory
    def find_artifacts_dir(subdir: str, pattern: str) -> List[str]:
        """Find and sort artifact files"""
        search_pattern = os.path.join(
            rabbitize_runs,
            '*',  # Any client_id
            f'{cell_name}.*',  # test_id starts with cell_name
            '*',  # Timestamp session subdirectory
            subdir,
            pattern
        )
        print(f"[ArtifactResolver]   Searching: {search_pattern}")
        found = glob.glob(search_pattern)
        print(f"[ArtifactResolver]   Found {len(found)} files: {found[:3]}")
        found.sort()  # Sort by filename (0.png, 1.png, etc.)
        return found

    # Load screenshots as base64 data URLs (try multiple extensions)
    screenshot_files = []
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        screenshot_files.extend(find_artifacts_dir('screenshots', ext))

    # Filter to numbered screenshots only (0.jpg, 1.jpg, not 0-pre-move.jpg)
    import re
    screenshot_files = [f for f in screenshot_files if re.search(r'/\d+\.(png|jpe?g)$', f)]
    screenshot_files.sort()

    if screenshot_files:
        artifacts['images'] = []
        for img_path in screenshot_files:
            try:
                data_url = encode_image_base64(img_path)
                artifacts['images'].append(data_url)
            except Exception as e:
                print(f"[ArtifactResolver] Failed to load image {img_path}: {e}")
                artifacts['images'].append(f"[Error loading image: {e}]")

    # Load DOM snapshots as markdown text (rabbitize saves as .md files)
    dom_files = find_artifacts_dir('dom_snapshots', 'dom_*.md')
    if dom_files:
        artifacts['dom_snapshots'] = []
        for md_path in dom_files:
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    artifacts['dom_snapshots'].append(f.read())
            except Exception as e:
                print(f"[ArtifactResolver] Failed to load DOM snapshot {md_path}: {e}")
                artifacts['dom_snapshots'].append(f"[Error loading DOM: {e}]")

    # Load DOM coords as JSON text (filter to numbered coords only)
    coord_files = find_artifacts_dir('dom_coords', 'dom_coords_*.json')
    # Filter to just numbered files (exclude dom_coords_initial.json)
    coord_files = [f for f in coord_files if re.search(r'/dom_coords_\d+\.json$', f)]
    coord_files.sort()

    if coord_files:
        artifacts['dom_coords'] = []
        for json_path in coord_files:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    artifacts['dom_coords'].append(f.read())
            except Exception as e:
                print(f"[ArtifactResolver] Failed to load DOM coords {json_path}: {e}")
                artifacts['dom_coords'].append(f"[Error loading coords: {e}]")

    # Find video file
    video_pattern = os.path.join(rabbitize_runs, '*', f'{cell_name}.*', '*', 'video', '*.webm')
    print(f"[ArtifactResolver]   Searching video: {video_pattern}")
    video_files = glob.glob(video_pattern)
    print(f"[ArtifactResolver]   Found {len(video_files)} video files")
    if video_files:
        artifacts['video'] = video_files[0]  # Just the path

    print(f"[ArtifactResolver] Loaded artifacts for {cell_name}: {', '.join(f'{k}={len(v) if isinstance(v, list) else 1}' for k, v in artifacts.items())}")

    return artifacts


def enrich_outputs_with_artifacts(outputs: Dict[str, Any], cascade_phases: list, session_id: str) -> Dict[str, Any]:
    """
    Enrich the outputs dict with artifact resolvers for rabbitize phases.

    Args:
        outputs: Standard outputs dict {cell_name: output}
        cascade_phases: List of CellConfig objects
        session_id: Current session ID

    Returns:
        Enriched outputs dict with plain artifact dicts
    """
    enriched = outputs.copy()

    print(f"[ArtifactResolver] Enriching outputs with artifacts for session: {session_id}")
    print(f"[ArtifactResolver] Input outputs keys: {list(outputs.keys())}")
    print(f"[ArtifactResolver] Cascade has {len(cascade_phases)} phases")

    for phase in cascade_phases:
        # Check if this is a rabbitize phase
        cell_name = getattr(phase, 'name', None)
        phase_tool = getattr(phase, 'tool', None)
        phase_inputs = getattr(phase, 'inputs', None)

        # print(f"[ArtifactResolver] Checking phase: {cell_name}, tool: {phase_tool}, inputs type: {type(phase_inputs)}")
        # print(f"[ArtifactResolver]   Phase attributes: {dir(phase)[:20]}")  # Debug what's available

        is_shell_tool = phase_tool in ('linux_shell', 'linux_shell_dangerous')

        # Check if inputs contains rabbitize command (multiple strategies)
        has_rabbitize = False

        if phase_inputs:
            if isinstance(phase_inputs, dict):
                command = phase_inputs.get('command', '')
            else:
                command = getattr(phase_inputs, 'command', '')
            has_rabbitize = 'rabbitize' in command if command else False
            print(f"[ArtifactResolver]   -> has_rabbitize: {has_rabbitize}, command preview: {command[:100] if command else None}")

        # Fallback: Check phase dict directly (Pydantic model might have inputs in __dict__)
        if not has_rabbitize and is_shell_tool:
            phase_dict = getattr(phase, '__dict__', {}) or getattr(phase, 'dict', lambda: {})()
            if isinstance(phase_dict, dict) and 'inputs' in phase_dict:
                inputs_dict = phase_dict['inputs']
                if isinstance(inputs_dict, dict) and 'command' in inputs_dict:
                    command = inputs_dict['command']
                    has_rabbitize = 'rabbitize' in command if command else False
                    print(f"[ArtifactResolver]   -> Fallback dict check: has_rabbitize={has_rabbitize}")

        # Simple fallback: linux_shell_dangerous is primarily for rabbitize
        # (until we have a better Docker image)
        if not has_rabbitize and phase_tool == 'linux_shell_dangerous':
            has_rabbitize = True
            print(f"[ArtifactResolver]   -> Using fallback: linux_shell_dangerous = rabbitize")

        is_rabbitize = is_shell_tool and has_rabbitize

        if is_rabbitize:
            if cell_name:
                print(f"[ArtifactResolver] ✓ Loading artifacts for rabbitize phase: {cell_name}")
                # Load artifacts into plain dict (no custom classes)
                enriched[cell_name] = load_rabbitize_artifacts(cell_name, session_id)
            else:
                print(f"[ArtifactResolver] ✗ Rabbitize phase has no name!")

    print(f"[ArtifactResolver] Final enriched outputs keys: {list(enriched.keys())}")
    return enriched


def extract_images_from_rendered_text(rendered_text: str) -> tuple[str, list[str]]:
    """
    Extract data:image URLs from rendered Jinja text.

    Returns:
        (clean_text, image_urls) where clean_text has URLs replaced with placeholders
    """
    import re

    # Pattern to match data:image URLs
    pattern = r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+'

    # Find all data URLs
    data_urls = re.findall(pattern, rendered_text)

    # Replace them with placeholders (so they don't clutter the text)
    clean_text = rendered_text
    for i, url in enumerate(data_urls):
        clean_text = clean_text.replace(url, f'[Image {i}]', 1)

    return clean_text, data_urls


def convert_to_multimodal_content(text: str, extract_images: bool = True, extract_videos: bool = True) -> Union[str, list]:
    """
    Convert a text string with embedded data:image/video URLs to multimodal content.

    Args:
        text: Rendered text (possibly with data:image or data:video URLs)
        extract_images: If True, extract images and return multimodal content
        extract_videos: If True, extract videos and return multimodal content

    Returns:
        - str: Original text if no media found
        - list: Multimodal content blocks if images/videos found
    """
    if not extract_images and not extract_videos:
        return text

    clean_text = text
    image_urls = []
    video_urls = []

    if extract_images:
        clean_text, image_urls = extract_images_from_rendered_text(clean_text)

    if extract_videos:
        clean_text, video_urls = extract_videos_from_rendered_text(clean_text)

    if not image_urls and not video_urls:
        return text

    # Build multimodal content: text first, then videos, then images
    content = [{"type": "text", "text": clean_text}]

    for url in video_urls:
        content.append({
            "type": "video_url",
            "video_url": {"url": url}
        })

    for url in image_urls:
        content.append({
            "type": "image_url",
            "image_url": {"url": url}
        })

    return content


def extract_videos_from_rendered_text(rendered_text: str) -> tuple[str, list[str]]:
    """
    Extract data:video URLs from rendered Jinja text.

    Returns:
        (clean_text, video_urls) where clean_text has URLs replaced with placeholders
    """
    import re

    # Pattern to match data:video URLs
    pattern = r'data:video/[^;]+;base64,[A-Za-z0-9+/=]+'

    # Find all data URLs
    data_urls = re.findall(pattern, rendered_text)

    # Replace them with placeholders (so they don't clutter the text)
    clean_text = rendered_text
    for i, url in enumerate(data_urls):
        clean_text = clean_text.replace(url, f'[Video {i}]', 1)

    return clean_text, data_urls
