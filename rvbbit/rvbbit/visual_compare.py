"""
Visual comparison utilities for screenshot regression testing.

Uses Pillow for image comparison and diff generation.
"""

import os
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

try:
    from PIL import Image, ImageChops
    import numpy as np
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


@dataclass
class ScreenshotComparison:
    """Result of comparing two screenshots."""
    name: str
    similarity: float
    passed: bool
    previous_path: Optional[str] = None
    current_path: Optional[str] = None
    diff_path: Optional[str] = None
    error: Optional[str] = None
    dimensions_match: bool = True
    previous_size: Optional[Tuple[int, int]] = None
    current_size: Optional[Tuple[int, int]] = None


@dataclass
class VisualTestResult:
    """Result of a visual regression test run."""
    test_id: str
    current_session_id: str
    previous_session_id: Optional[str]
    threshold: float
    overall_score: float
    passed: bool
    is_baseline: bool  # True if no previous run exists
    screenshots: List[ScreenshotComparison] = field(default_factory=list)
    failed_count: int = 0
    total_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['screenshots'] = [asdict(s) for s in self.screenshots]
        return result


def calculate_similarity(img1: 'Image.Image', img2: 'Image.Image') -> float:
    """
    Calculate similarity between two images (0-1 scale).

    Uses normalized pixel difference - simple but effective for regression testing.
    """
    if not HAS_PILLOW:
        raise ImportError("Pillow is required for image comparison: pip install Pillow")

    # Convert to RGB for consistent comparison
    img1_rgb = img1.convert('RGB')
    img2_rgb = img2.convert('RGB')

    # Resize if dimensions differ (use smaller dimensions)
    if img1_rgb.size != img2_rgb.size:
        target_size = (
            min(img1_rgb.size[0], img2_rgb.size[0]),
            min(img1_rgb.size[1], img2_rgb.size[1])
        )
        img1_rgb = img1_rgb.resize(target_size, Image.Resampling.LANCZOS)
        img2_rgb = img2_rgb.resize(target_size, Image.Resampling.LANCZOS)

    # Calculate pixel-wise difference
    arr1 = np.array(img1_rgb, dtype=np.float32)
    arr2 = np.array(img2_rgb, dtype=np.float32)

    # Normalized difference (0-1 per pixel, averaged)
    diff = np.abs(arr1 - arr2) / 255.0
    mean_diff = np.mean(diff)

    # Similarity is inverse of difference
    similarity = 1.0 - mean_diff

    return float(similarity)


def generate_diff_image(
    img1: 'Image.Image',
    img2: 'Image.Image',
    amplify: float = 3.0
) -> 'Image.Image':
    """
    Generate a diff image highlighting differences between two images.

    Args:
        img1: First image (previous/baseline)
        img2: Second image (current)
        amplify: Amplification factor for differences (makes small changes visible)

    Returns:
        Diff image with differences highlighted
    """
    if not HAS_PILLOW:
        raise ImportError("Pillow is required for image comparison: pip install Pillow")

    # Convert to RGB
    img1_rgb = img1.convert('RGB')
    img2_rgb = img2.convert('RGB')

    # Resize if needed
    if img1_rgb.size != img2_rgb.size:
        target_size = (
            min(img1_rgb.size[0], img2_rgb.size[0]),
            min(img1_rgb.size[1], img2_rgb.size[1])
        )
        img1_rgb = img1_rgb.resize(target_size, Image.Resampling.LANCZOS)
        img2_rgb = img2_rgb.resize(target_size, Image.Resampling.LANCZOS)

    # Create difference image
    diff = ImageChops.difference(img1_rgb, img2_rgb)

    # Amplify differences for visibility
    if amplify != 1.0:
        arr = np.array(diff, dtype=np.float32)
        arr = np.clip(arr * amplify, 0, 255).astype(np.uint8)
        diff = Image.fromarray(arr)

    return diff


def compare_screenshots(
    previous_path: str,
    current_path: str,
    diff_output_path: Optional[str] = None,
    threshold: float = 0.95
) -> ScreenshotComparison:
    """
    Compare two screenshot files.

    Args:
        previous_path: Path to previous/baseline screenshot
        current_path: Path to current screenshot
        diff_output_path: Optional path to save diff image
        threshold: Similarity threshold (0-1) for pass/fail

    Returns:
        ScreenshotComparison with results
    """
    name = os.path.basename(current_path)

    if not HAS_PILLOW:
        return ScreenshotComparison(
            name=name,
            similarity=0.0,
            passed=False,
            previous_path=previous_path,
            current_path=current_path,
            error="Pillow not installed"
        )

    try:
        # Load images
        if not os.path.exists(previous_path):
            return ScreenshotComparison(
                name=name,
                similarity=0.0,
                passed=False,
                current_path=current_path,
                error=f"Previous screenshot not found: {previous_path}"
            )

        if not os.path.exists(current_path):
            return ScreenshotComparison(
                name=name,
                similarity=0.0,
                passed=False,
                previous_path=previous_path,
                error=f"Current screenshot not found: {current_path}"
            )

        prev_img = Image.open(previous_path)
        curr_img = Image.open(current_path)

        dimensions_match = prev_img.size == curr_img.size

        # Calculate similarity
        similarity = calculate_similarity(prev_img, curr_img)
        passed = similarity >= threshold

        # Generate diff image if failed and output path provided
        diff_path = None
        if not passed and diff_output_path:
            os.makedirs(os.path.dirname(diff_output_path), exist_ok=True)
            diff_img = generate_diff_image(prev_img, curr_img)
            diff_img.save(diff_output_path, quality=85)
            diff_path = diff_output_path

        return ScreenshotComparison(
            name=name,
            similarity=similarity,
            passed=passed,
            previous_path=previous_path,
            current_path=current_path,
            diff_path=diff_path,
            dimensions_match=dimensions_match,
            previous_size=prev_img.size,
            current_size=curr_img.size
        )

    except Exception as e:
        return ScreenshotComparison(
            name=name,
            similarity=0.0,
            passed=False,
            previous_path=previous_path,
            current_path=current_path,
            error=str(e)
        )


def get_screenshot_list(session_path: str, cell_name: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Get list of screenshots from a browser session's commands.json.

    Args:
        session_path: Path to session directory (e.g., browsers/<session_id>)
        cell_name: Specific cell name to use. If None, scans for first cell directory.

    Returns list of dicts with 'name' and 'path' keys for post-action screenshots.
    """
    # Find cell directory
    if cell_name:
        cell_path = os.path.join(session_path, cell_name)
    else:
        # Scan for first cell directory that has commands.json
        if not os.path.exists(session_path):
            return []

        cell_path = None
        for entry in os.listdir(session_path):
            candidate = os.path.join(session_path, entry)
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, 'commands.json')):
                cell_path = candidate
                break

        if not cell_path:
            return []

    commands_path = os.path.join(cell_path, 'commands.json')

    if not os.path.exists(commands_path):
        return []

    with open(commands_path) as f:
        commands = json.load(f)

    screenshots = []
    for cmd in commands:
        if 'screenshots' in cmd and 'post' in cmd['screenshots']:
            post_path = cmd['screenshots']['post']
            name = os.path.basename(post_path)
            screenshots.append({
                'name': name,
                'path': post_path,
                'index': cmd.get('index', 0),
                'command': cmd.get('command', [])
            })

    return screenshots


def compare_sessions(
    previous_session_path: str,
    current_session_path: str,
    test_id: str,
    threshold: float = 0.95,
    diff_output_dir: Optional[str] = None
) -> VisualTestResult:
    """
    Compare all screenshots between two browser sessions.

    Args:
        previous_session_path: Path to previous session directory
        current_session_path: Path to current session directory
        test_id: Test identifier
        threshold: Similarity threshold for pass/fail
        diff_output_dir: Directory to save diff images

    Returns:
        VisualTestResult with all comparisons
    """
    current_session_id = os.path.basename(current_session_path)
    previous_session_id = os.path.basename(previous_session_path) if previous_session_path else None

    # Handle baseline case (no previous run)
    if not previous_session_path or not os.path.exists(previous_session_path):
        current_screenshots = get_screenshot_list(current_session_path)
        return VisualTestResult(
            test_id=test_id,
            current_session_id=current_session_id,
            previous_session_id=None,
            threshold=threshold,
            overall_score=1.0,
            passed=True,
            is_baseline=True,
            screenshots=[],
            failed_count=0,
            total_count=len(current_screenshots)
        )

    # Get screenshot lists
    prev_screenshots = get_screenshot_list(previous_session_path)
    curr_screenshots = get_screenshot_list(current_session_path)

    # Create lookup by name
    prev_by_name = {s['name']: s for s in prev_screenshots}

    comparisons = []
    total_similarity = 0.0
    failed_count = 0

    for curr in curr_screenshots:
        name = curr['name']

        # Find matching previous screenshot
        prev = prev_by_name.get(name)

        if not prev:
            # No matching previous screenshot
            comparisons.append(ScreenshotComparison(
                name=name,
                similarity=0.0,
                passed=False,
                current_path=curr['path'],
                error="No matching previous screenshot"
            ))
            failed_count += 1
            continue

        # Generate diff path if needed
        diff_path = None
        if diff_output_dir:
            diff_path = os.path.join(diff_output_dir, f"{name}_diff.jpg")

        # Compare
        comparison = compare_screenshots(
            previous_path=prev['path'],
            current_path=curr['path'],
            diff_output_path=diff_path,
            threshold=threshold
        )

        comparisons.append(comparison)
        total_similarity += comparison.similarity

        if not comparison.passed:
            failed_count += 1

    # Calculate overall score
    total_count = len(comparisons)
    overall_score = total_similarity / total_count if total_count > 0 else 1.0

    return VisualTestResult(
        test_id=test_id,
        current_session_id=current_session_id,
        previous_session_id=previous_session_id,
        threshold=threshold,
        overall_score=overall_score,
        passed=failed_count == 0,
        is_baseline=False,
        screenshots=comparisons,
        failed_count=failed_count,
        total_count=total_count
    )
