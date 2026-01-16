"""
Stability detection for browser automation.

Detects when a page has stopped changing using pixel-diff comparison,
allowing commands to wait for page idle before continuing.
"""

from collections import deque
from typing import Optional
import io
import logging

logger = logging.getLogger(__name__)

# Try to import image processing libraries
try:
    from PIL import Image
    import numpy as np

    HAS_IMAGING = True
except ImportError:
    HAS_IMAGING = False
    logger.warning(
        "PIL/numpy not available - stability detection will use fallback timing"
    )


class StabilityDetector:
    """
    Detect when a page has stopped changing using pixel-diff comparison.

    Compares sequential screenshots to determine if the page is "stable"
    (no visual changes for N consecutive frames).

    Args:
        threshold: Max allowed diff ratio (0-1). Lower = more sensitive.
        stable_frames_required: Consecutive unchanged frames needed for stability.
        downscale_size: Resolution for comparison (smaller = faster).
        max_buffer_size: Maximum frames to keep in buffer.
    """

    def __init__(
        self,
        threshold: float = 0.01,
        stable_frames_required: int = 6,
        downscale_size: tuple[int, int] = (200, 150),
        max_buffer_size: int = 10,
    ):
        self.threshold = threshold
        self.stable_frames_required = stable_frames_required
        self.downscale_size = downscale_size
        self.max_buffer_size = max_buffer_size

        # Runtime state
        self.frame_buffer: deque = deque(maxlen=max_buffer_size)
        self.stable_count: int = 0
        self._last_diff: float = 0.0

    def add_frame(self, image_bytes: bytes) -> bool:
        """
        Add a frame and check stability.

        Args:
            image_bytes: JPEG/PNG screenshot bytes

        Returns:
            True if page is stable (no changes for stable_frames_required frames)
        """
        if not HAS_IMAGING:
            # Fallback: just count frames
            self.stable_count += 1
            return self.stable_count >= self.stable_frames_required

        try:
            # Decode and downscale
            img = Image.open(io.BytesIO(image_bytes))
            img = img.convert("RGB").resize(
                self.downscale_size, Image.Resampling.LANCZOS
            )
            arr = np.array(img, dtype=np.float32) / 255.0

            if len(self.frame_buffer) > 0:
                # Compare to previous frame
                prev = self.frame_buffer[-1]
                diff = float(np.mean(np.abs(arr - prev)))
                self._last_diff = diff

                if diff < self.threshold:
                    self.stable_count += 1
                else:
                    self.stable_count = 0
            else:
                # First frame - not stable yet
                self.stable_count = 0

            self.frame_buffer.append(arr)

        except Exception as e:
            logger.debug(f"Error processing frame for stability: {e}")
            # On error, increment counter anyway
            self.stable_count += 1

        return self.stable_count >= self.stable_frames_required

    def reset(self):
        """Reset stability tracking."""
        self.frame_buffer.clear()
        self.stable_count = 0
        self._last_diff = 0.0

    def is_stable(self) -> bool:
        """Check if currently stable without adding a frame."""
        return self.stable_count >= self.stable_frames_required

    @property
    def last_diff(self) -> float:
        """Get the last computed difference value."""
        return self._last_diff

    @property
    def frames_until_stable(self) -> int:
        """Get number of frames needed until stability is reached."""
        remaining = self.stable_frames_required - self.stable_count
        return max(0, remaining)


class TimingBasedStability:
    """
    Simple timing-based stability detection as fallback.

    Waits a fixed duration after the last detected change.
    """

    def __init__(self, stable_duration: float = 1.0):
        """
        Args:
            stable_duration: Seconds to wait after last change.
        """
        self.stable_duration = stable_duration
        self._last_change_time: Optional[float] = None
        self._frame_count: int = 0

    def add_frame(self, image_bytes: bytes) -> bool:
        """
        Add a frame. Always returns True after stable_duration.

        This is a fallback when PIL/numpy aren't available.
        """
        import time

        now = time.time()

        if self._last_change_time is None:
            self._last_change_time = now
            return False

        # Simple heuristic: assume stable after N frames
        self._frame_count += 1
        if self._frame_count >= 6:  # ~2 seconds at 3 FPS
            return True

        elapsed = now - self._last_change_time
        return elapsed >= self.stable_duration

    def reset(self):
        """Reset timing."""
        self._last_change_time = None
        self._frame_count = 0

    def is_stable(self) -> bool:
        """Check if stable."""
        if self._last_change_time is None:
            return False
        import time

        return (time.time() - self._last_change_time) >= self.stable_duration


def create_stability_detector(
    use_pixel_diff: bool = True, **kwargs
) -> StabilityDetector | TimingBasedStability:
    """
    Factory function to create appropriate stability detector.

    Args:
        use_pixel_diff: If True, use pixel-diff detection (requires PIL/numpy).
                       Falls back to timing if libraries not available.
        **kwargs: Arguments passed to detector constructor.

    Returns:
        StabilityDetector or TimingBasedStability instance.
    """
    if use_pixel_diff and HAS_IMAGING:
        return StabilityDetector(**kwargs)
    else:
        stable_duration = kwargs.get("stable_duration", 1.0)
        return TimingBasedStability(stable_duration=stable_duration)
