"""
Artifact Resolver for Rabbitize Browser Automation

Provides Jinja2-accessible artifact resolution for browser automation phases.
Supports:
- {{ browser_1.images.0 }} → Base64 data URL (multimodal attachment)
- {{ browser_1.dom_coords.0 }} → File contents as text
- {{ browser_1.dom_snapshots.0 }} → File contents as text
- {{ browser_1.video }} → File path
"""

import os
import glob
from typing import Optional, Dict, Any, Union
from .utils import encode_image_base64
from .config import get_config


class ArtifactCollection:
    """
    Lazy-loading collection for artifact files.

    Supports indexed access: collection[0], collection[1], etc.
    """

    def __init__(self, phase_name: str, artifact_type: str, session_id: str):
        self.phase_name = phase_name
        self.artifact_type = artifact_type
        self.session_id = session_id
        self._files = None

    def _discover_files(self):
        """Discover artifact files on disk"""
        if self._files is not None:
            return

        # Build path: rabbitize-runs/{client_id}/{test_id}/{session}/artifacts/
        # For now, search for the pattern - in real runs, test_id will have session suffix
        root = get_config().root_dir
        rabbitize_runs = os.path.join(root, "rabbitize-runs")

        # Search for this phase's artifacts (wildcards for session suffix)
        # Pattern: rabbitize-runs/*/{phase_name}.*/screenshots/*.png
        pattern_map = {
            'images': 'screenshots/*.png',
            'dom_snapshots': 'dom-snapshots/*.html',
            'dom_coords': 'dom-coords/*.json',
        }

        if self.artifact_type not in pattern_map:
            self._files = []
            return

        # Search pattern: rabbitize-runs/*/{phase_name}.*/{artifact_subdir}/*
        search_pattern = os.path.join(
            rabbitize_runs,
            '*',  # Any client_id
            f'{self.phase_name}.*',  # test_id starts with phase_name
            pattern_map[self.artifact_type]
        )

        found_files = glob.glob(search_pattern)
        # Sort by filename (typically numbered: 0.png, 1.png, etc.)
        found_files.sort()

        self._files = found_files

    def __getitem__(self, index: int) -> str:
        """Get artifact by index"""
        self._discover_files()

        if not self._files or index >= len(self._files):
            return f"[Artifact not found: {self.phase_name}.{self.artifact_type}.{index}]"

        file_path = self._files[index]

        # For images, return base64 data URL (enables multimodal attachment)
        if self.artifact_type == 'images':
            try:
                return encode_image_base64(file_path)
            except Exception as e:
                return f"[Error loading image: {e}]"

        # For text files (dom_coords, dom_snapshots), return contents
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                return f"[Error reading file: {e}]"

    def __len__(self):
        """Get count of artifacts"""
        self._discover_files()
        return len(self._files) if self._files else 0

    def __repr__(self):
        """String representation"""
        return f"<ArtifactCollection {self.phase_name}.{self.artifact_type} ({len(self)} items)>"


class VideoArtifact:
    """
    Single video artifact.
    Returns path to video file.
    """

    def __init__(self, phase_name: str, session_id: str):
        self.phase_name = phase_name
        self.session_id = session_id

    def __str__(self):
        """Return path to video file"""
        root = get_config().root_dir
        rabbitize_runs = os.path.join(root, "rabbitize-runs")

        # Search for video: rabbitize-runs/*/{phase_name}.*/video.webm
        search_pattern = os.path.join(
            rabbitize_runs,
            '*',
            f'{self.phase_name}.*',
            'video.webm'
        )

        found = glob.glob(search_pattern)
        if found:
            return found[0]

        return f"[Video not found for {self.phase_name}]"

    def __repr__(self):
        return f"<VideoArtifact {self.phase_name}>"


class RabbitizeArtifacts:
    """
    Main artifact resolver for a rabbitize phase.

    Provides attribute access to artifact collections:
    - .images → ArtifactCollection (base64 data URLs)
    - .dom_snapshots → ArtifactCollection (HTML text)
    - .dom_coords → ArtifactCollection (JSON text)
    - .video → VideoArtifact (path)
    """

    def __init__(self, phase_name: str, session_id: str):
        self.phase_name = phase_name
        self.session_id = session_id
        self._collections = {}

    def __getattr__(self, name: str):
        """Lazy-load artifact collections"""
        if name.startswith('_'):
            # Internal attributes
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        if name == 'video':
            return VideoArtifact(self.phase_name, self.session_id)

        if name in ['images', 'dom_snapshots', 'dom_coords']:
            if name not in self._collections:
                self._collections[name] = ArtifactCollection(
                    self.phase_name,
                    name,
                    self.session_id
                )
            return self._collections[name]

        raise AttributeError(f"Unknown artifact type: {name}")

    def __repr__(self):
        return f"<RabbitizeArtifacts {self.phase_name}>"


def create_artifact_resolver(phase_name: str, session_id: str) -> RabbitizeArtifacts:
    """
    Factory function to create an artifact resolver for a phase.

    Usage in Jinja templates:
        {{ browser_1.images.0 }}        → Base64 image data URL
        {{ browser_1.dom_coords.2 }}    → JSON file contents
        {{ browser_1.video }}           → Video file path
    """
    return RabbitizeArtifacts(phase_name, session_id)


def enrich_outputs_with_artifacts(outputs: Dict[str, Any], cascade_phases: list, session_id: str) -> Dict[str, Any]:
    """
    Enrich the outputs dict with artifact resolvers for rabbitize phases.

    Args:
        outputs: Standard outputs dict {phase_name: output}
        cascade_phases: List of PhaseConfig objects
        session_id: Current session ID

    Returns:
        Enriched outputs dict with artifact resolvers
    """
    enriched = outputs.copy()

    print(f"[ArtifactResolver] Enriching outputs with artifacts for session: {session_id}")
    print(f"[ArtifactResolver] Input outputs keys: {list(outputs.keys())}")
    print(f"[ArtifactResolver] Cascade has {len(cascade_phases)} phases")

    for phase in cascade_phases:
        # Check if this is a rabbitize phase
        phase_name = getattr(phase, 'name', None)
        phase_tool = getattr(phase, 'tool', None)
        phase_inputs = getattr(phase, 'inputs', None)

        print(f"[ArtifactResolver] Checking phase: {phase_name}, tool: {phase_tool}, inputs type: {type(phase_inputs)}")

        is_shell_tool = phase_tool in ('linux_shell', 'linux_shell_dangerous')

        # Check if inputs contains rabbitize command
        has_rabbitize = False
        if phase_inputs:
            if isinstance(phase_inputs, dict):
                command = phase_inputs.get('command', '')
            else:
                command = getattr(phase_inputs, 'command', '')
            has_rabbitize = 'rabbitize' in command if command else False
            print(f"[ArtifactResolver]   -> has_rabbitize: {has_rabbitize}, command: {command[:100] if command else None}")

        is_rabbitize = is_shell_tool and has_rabbitize

        if is_rabbitize:
            if phase_name:
                print(f"[ArtifactResolver] ✓ Enriching outputs for rabbitize phase: {phase_name}")
                # Replace output with artifact resolver (even if output is a string)
                enriched[phase_name] = create_artifact_resolver(phase_name, session_id)
            else:
                print(f"[ArtifactResolver] ✗ Rabbitize phase has no name!")

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


def convert_to_multimodal_content(text: str, extract_images: bool = True) -> Union[str, list]:
    """
    Convert a text string with embedded data:image URLs to multimodal content.

    Args:
        text: Rendered text (possibly with data:image URLs)
        extract_images: If True, extract images and return multimodal content

    Returns:
        - str: Original text if no images found
        - list: Multimodal content blocks if images found
    """
    if not extract_images:
        return text

    clean_text, image_urls = extract_images_from_rendered_text(text)

    if not image_urls:
        return text

    # Build multimodal content: text first, then images
    content = [{"type": "text", "text": clean_text}]

    for url in image_urls:
        content.append({
            "type": "image_url",
            "image_url": {"url": url}
        })

    return content
