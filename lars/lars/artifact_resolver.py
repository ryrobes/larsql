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
import re
import json
import glob
from typing import Dict, Any, List, Union
from .utils import encode_image_base64
from .config import get_config


def load_rabbitize_artifacts(cell_name: str, session_id: str, browser_session_id: str | None = None) -> Dict[str, Any]:
    """
    Load all browser artifacts for a cell into a plain dict structure.

    Args:
        cell_name: Name of the browser cell (e.g., "browser_1")
        session_id: Cascade session ID (e.g., "studio_new_10ee35")
        browser_session_id: Deprecated - no longer used with new folder structure

    Path structure: browsers/<session_id>/<cell_name>/

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
    root = get_config().root_dir
    browsers_dir = os.path.join(root, "browsers")
    print(f"[ARTIFACT] Loading artifacts for cell '{cell_name}' from {browsers_dir}")

    # Initialize with empty lists for all types (so Jinja can access even if no files)
    artifacts = {
        'images': [],
        'dom_snapshots': [],
        'dom_coords': [],
        'video': None
    }

    # Simple path: browsers/<session_id>/<cell_name>/
    session_folder = os.path.join(browsers_dir, session_id, cell_name)

    if not os.path.isdir(session_folder):
        print(f"[ARTIFACT] No session folder found at {session_folder}")
        return artifacts

    print(f"[ARTIFACT] Using session folder: {session_folder}")

    # Helper to find artifact files in the session folder
    def find_artifacts_in_session(subdir: str, pattern: str) -> List[str]:
        """Find and sort artifact files in the session folder"""
        search_pattern = os.path.join(session_folder, subdir, pattern)
        found = glob.glob(search_pattern)
        found.sort()  # Sort by filename (0.png, 1.png, etc.)
        return found

    # Load screenshots as base64 data URLs (try multiple extensions)
    screenshot_files = []
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        screenshot_files.extend(find_artifacts_in_session('screenshots', ext))

    # Filter to numbered screenshots only (0.jpg, 1.jpg, not 0-pre-move.jpg)
    screenshot_files = [f for f in screenshot_files if re.search(r'/\d+\.(png|jpe?g)$', f)]
    screenshot_files.sort()

    if screenshot_files:
        print(f"[ARTIFACT] Found {len(screenshot_files)} screenshot files: {screenshot_files}")
        artifacts['images'] = []
        for img_path in screenshot_files:
            try:
                data_url = encode_image_base64(img_path)
                artifacts['images'].append(data_url)
                print(f"[ARTIFACT]   Loaded {img_path} -> {len(data_url)} char data URL")
            except Exception as e:
                print(f"[ARTIFACT]   ERROR loading {img_path}: {e}")
                artifacts['images'].append(f"[Error loading image: {e}]")
    else:
        print(f"[ARTIFACT] No screenshot files found")

    # Load DOM snapshots as markdown text (rabbitize saves as .md files)
    dom_files = find_artifacts_in_session('dom_snapshots', 'dom_*.md')
    if dom_files:
        artifacts['dom_snapshots'] = []
        for md_path in dom_files:
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    artifacts['dom_snapshots'].append(f.read())
            except Exception as e:
                artifacts['dom_snapshots'].append(f"[Error loading DOM: {e}]")

    # Load DOM coords as JSON text (filter to numbered coords only)
    coord_files = find_artifacts_in_session('dom_coords', 'dom_coords_*.json')
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
                artifacts['dom_coords'].append(f"[Error loading coords: {e}]")

    # Find video file in session folder
    video_files = find_artifacts_in_session('video', '*.webm')
    if video_files:
        artifacts['video'] = video_files[0]  # Just the path

    #print(f"[ArtifactResolver] Loaded artifacts for {cell_name}: {', '.join(f'{k}={len(v) if isinstance(v, list) else 1}' for k, v in artifacts.items())}")

    return artifacts


def enrich_outputs_with_artifacts(outputs: Dict[str, Any], cascade_cells: list, session_id: str) -> Dict[str, Any]:
    """
    Enrich the outputs dict with artifact resolvers for browser/rabbitize cells.

    For the native 'browser' tool, the output already contains artifacts (images, dom_snapshots, etc.),
    so no file system lookup is needed.

    For the legacy shell-based rabbitize approach (linux_shell_dangerous), this function
    loads artifacts from the file system based on the session_id.

    Args:
        outputs: Standard outputs dict {cell_name: output}
        cascade_cells: List of CellConfig objects
        session_id: Current session ID

    Returns:
        Enriched outputs dict with plain artifact dicts
    """
    enriched = outputs.copy()

    for cell in cascade_cells:
        cell_name = getattr(cell, 'name', None)
        cell_tool = getattr(cell, 'tool', None)
        cell_inputs = getattr(cell, 'inputs', None)

        if not cell_name:
            continue

        # Check if this is a native browser tool
        # Native browser tool returns artifacts directly in output - no enrichment needed
        if cell_tool == 'browser':
            cell_output = outputs.get(cell_name)
            if isinstance(cell_output, dict) and 'images' in cell_output:
                # Output already has artifacts, no enrichment needed
                print(f"[ARTIFACT] Cell '{cell_name}' uses native browser tool - artifacts already in output")
                continue

        # Check if this is a shell-based rabbitize cell (legacy)
        is_shell_tool = cell_tool in ('linux_shell', 'linux_shell_dangerous')

        # Check if inputs contains rabbitize command
        has_rabbitize = False

        if cell_inputs:
            if isinstance(cell_inputs, dict):
                command = cell_inputs.get('command', '')
            else:
                command = getattr(cell_inputs, 'command', '')
            has_rabbitize = 'rabbitize' in command if command else False

        # Fallback: Check cell dict directly (Pydantic model might have inputs in __dict__)
        if not has_rabbitize and is_shell_tool:
            cell_dict = getattr(cell, '__dict__', {}) or getattr(cell, 'dict', lambda: {})()
            if isinstance(cell_dict, dict) and 'inputs' in cell_dict:
                inputs_dict = cell_dict['inputs']
                if isinstance(inputs_dict, dict) and 'command' in inputs_dict:
                    command = inputs_dict['command']
                    has_rabbitize = 'rabbitize' in command if command else False

        # Fallback: linux_shell_dangerous is primarily for rabbitize
        if not has_rabbitize and cell_tool == 'linux_shell_dangerous':
            has_rabbitize = True

        is_rabbitize = is_shell_tool and has_rabbitize

        if is_rabbitize:
            # Shell-based rabbitize - need to load artifacts from file system
            browser_session_id = None
            cell_output = outputs.get(cell_name)
            if cell_output:
                if isinstance(cell_output, dict):
                    browser_session_id = cell_output.get('session_id')
                elif isinstance(cell_output, str):
                    try:
                        parsed = json.loads(cell_output)
                        if isinstance(parsed, dict):
                            browser_session_id = parsed.get('session_id')
                    except (json.JSONDecodeError, TypeError):
                        pass

            print(f"[ARTIFACT] Cell '{cell_name}' (shell-based) browser_session_id: {browser_session_id}")
            # Load artifacts into plain dict from file system
            enriched[cell_name] = load_rabbitize_artifacts(cell_name, session_id, browser_session_id)

    return enriched


def extract_images_from_rendered_text(rendered_text: str) -> tuple[str, list[str]]:
    """
    Extract data:image URLs from rendered Jinja text.

    Returns:
        (clean_text, image_urls) where clean_text has URLs replaced with placeholders
    """
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

    # Debug logging for multimodal content
    if image_urls or video_urls:
        print(f"[MULTIMODAL] Extracted {len(image_urls)} image(s) and {len(video_urls)} video(s)")
        for i, url in enumerate(image_urls):
            print(f"[MULTIMODAL]   Image {i}: {url[:80]}... ({len(url)} chars total)")

    if not image_urls and not video_urls:
        return text

    # Build multimodal content: text first, then videos, then images
    content: list[dict] = [{"type": "text", "text": clean_text}]

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

    print(f"[MULTIMODAL] Built multimodal content with {len(content)} blocks")
    return content


def extract_videos_from_rendered_text(rendered_text: str) -> tuple[str, list[str]]:
    """
    Extract data:video URLs from rendered Jinja text.

    Returns:
        (clean_text, video_urls) where clean_text has URLs replaced with placeholders
    """
    # Pattern to match data:video URLs
    pattern = r'data:video/[^;]+;base64,[A-Za-z0-9+/=]+'

    # Find all data URLs
    data_urls = re.findall(pattern, rendered_text)

    # Replace them with placeholders (so they don't clutter the text)
    clean_text = rendered_text
    for i, url in enumerate(data_urls):
        clean_text = clean_text.replace(url, f'[Video {i}]', 1)

    return clean_text, data_urls
