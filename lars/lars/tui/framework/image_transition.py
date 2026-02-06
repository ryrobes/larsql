#!/usr/bin/env python3
"""
Image Transition System for Looking Glass
=========================================

Provides smooth, cinematic transitions between background images using
block-based color interpolation.

Features:
- Block-based color averaging for performance
- Smooth easing functions
- Multiple transition patterns (linear, spiral, wave)
- Real-time interpolation
- Integration with Looking Glass rendering
"""

import time
import math
import numpy as np
from PIL import Image
from typing import Tuple, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class ColorBlock:
    """Represents a color block in the transition"""
    r: float
    g: float
    b: float
    x: int
    y: int
    width: int
    height: int


class ImageTransition:
    """
    Handles smooth transitions between two images using block-based interpolation.

    The transition works by:
    1. Dividing both images into blocks
    2. Calculating average color per block
    3. Interpolating between old and new block colors over time
    4. Applying easing functions for smooth motion
    """

    def __init__(self,
                 old_image: Image.Image,
                 new_image: Image.Image,
                 duration: float = 4.5,
                 block_size: int = 150,
                 pattern: str = 'linear',
                 easing: str = 'linear'):
        """
        Initialize image transition.

        Args:
            old_image: Source image
            new_image: Target image
            duration: Transition duration in seconds
            block_size: Size of blocks for averaging (4x4, 8x8, etc.)
            pattern: Transition pattern ('linear', 'spiral', 'wave', 'random')
            easing: Easing function ('linear', 'smoothstep', 'ease_in_out')
        """
        self.duration = duration
        self.block_size = block_size
        self.pattern = pattern
        self.easing = easing
        self.start_time = None  # Don't start timer until first frame request
        self.is_complete = False
        self.frame_count = 0

        # Resize images to same size if needed
        if old_image.size != new_image.size:
            target_size = new_image.size
            old_image = old_image.resize(target_size, Image.Resampling.LANCZOS)

        self.image_width, self.image_height = new_image.size

        # Extract color blocks from both images
        self.old_blocks = self._extract_blocks(old_image)
        self.new_blocks = self._extract_blocks(new_image)

        # Generate transition timing for each block based on pattern
        self.block_timings = self._generate_block_timings()

        print(f"🎬 Image transition initialized: {len(self.old_blocks)} blocks, {duration:.1f}s duration")

    def _extract_blocks(self, image: Image.Image) -> List[ColorBlock]:
        """Extract average colors from image blocks."""
        blocks = []
        img_array = np.array(image.convert('RGB'))

        blocks_x = self.image_width // self.block_size
        blocks_y = self.image_height // self.block_size

        for by in range(blocks_y):
            for bx in range(blocks_x):
                x1 = bx * self.block_size
                y1 = by * self.block_size
                x2 = min(x1 + self.block_size, self.image_width)
                y2 = min(y1 + self.block_size, self.image_height)

                # Extract block and calculate average color
                block = img_array[y1:y2, x1:x2]
                avg_color = block.mean(axis=(0, 1))

                blocks.append(ColorBlock(
                    r=avg_color[0] / 255.0,
                    g=avg_color[1] / 255.0,
                    b=avg_color[2] / 255.0,
                    x=x1, y=y1,
                    width=x2-x1, height=y2-y1
                ))

        return blocks

    def _generate_block_timings(self) -> List[float]:
        """Generate transition timing offsets for each block based on pattern."""
        num_blocks = len(self.old_blocks)
        timings = []

        if self.pattern == 'linear':
            # All blocks transition simultaneously
            timings = [0.0] * num_blocks

        elif self.pattern == 'wave':
            # Horizontal wave pattern
            blocks_x = self.image_width // self.block_size
            for i, block in enumerate(self.old_blocks):
                bx = i % blocks_x
                # Stagger by 10% of duration across width
                offset = (bx / blocks_x) * 0.1 * self.duration
                timings.append(offset)

        elif self.pattern == 'spiral':
            # Spiral pattern from center outward
            blocks_x = self.image_width // self.block_size
            blocks_y = self.image_height // self.block_size
            center_x, center_y = blocks_x // 2, blocks_y // 2

            max_distance = math.sqrt(center_x**2 + center_y**2)

            for i, block in enumerate(self.old_blocks):
                bx = i % blocks_x
                by = i // blocks_x

                # Distance from center
                distance = math.sqrt((bx - center_x)**2 + (by - center_y)**2)
                # Stagger by 20% of duration based on distance
                offset = (distance / max_distance) * 0.2 * self.duration
                timings.append(offset)

        elif self.pattern == 'random':
            # Random staggered timing
            import random
            timings = [random.uniform(0, 0.15 * self.duration) for _ in range(num_blocks)]

        else:
            # Default to linear
            timings = [0.0] * num_blocks

        return timings

    def _ease(self, t: float) -> float:
        """Apply easing function to transition progress."""
        t = max(0.0, min(1.0, t))  # Clamp to [0, 1]

        if self.easing == 'linear':
            return t
        elif self.easing == 'smoothstep':
            return t * t * (3.0 - 2.0 * t)
        elif self.easing == 'ease_in_out':
            return 0.5 * (1 + math.sin(math.pi * (t - 0.5)))
        elif self.easing == 'bounce':
            if t < 0.5:
                return 2 * t * t
            else:
                return 1 - 2 * (1 - t) * (1 - t)
        else:
            return t

    def _lerp_color(self, old_block: ColorBlock, new_block: ColorBlock, t: float) -> ColorBlock:
        """Linear interpolation between two color blocks."""
        t = self._ease(t)

        return ColorBlock(
            r=old_block.r + t * (new_block.r - old_block.r),
            g=old_block.g + t * (new_block.g - old_block.g),
            b=old_block.b + t * (new_block.b - old_block.b),
            x=old_block.x,
            y=old_block.y,
            width=old_block.width,
            height=old_block.height
        )

    def get_current_frame(self) -> List[ColorBlock]:
        """Get the current interpolated frame."""
        current_time = time.time()

        # Start timer on first frame request (not during __init__)
        if self.start_time is None:
            self.start_time = current_time
            print(f"🎬 Starting transition timer now (frame #{self.frame_count + 1})")

        elapsed = current_time - self.start_time
        self.frame_count += 1

        # Debug: Print frame info every 15 frames
        if self.frame_count % 15 == 0:
            print(f"🎬 Frame #{self.frame_count}: {elapsed:.3f}s elapsed, {(elapsed/self.duration)*100:.1f}% complete")

        if elapsed >= self.duration:
            self.is_complete = True
            print(f"🎬 Transition complete after {self.frame_count} frames in {elapsed:.3f}s")
            return self.new_blocks

        interpolated_blocks = []

        for i, (old_block, new_block) in enumerate(zip(self.old_blocks, self.new_blocks)):
            # Adjust elapsed time by block timing offset
            block_elapsed = elapsed - self.block_timings[i]

            if block_elapsed <= 0:
                # Transition hasn't started for this block yet
                interpolated_blocks.append(old_block)
            elif block_elapsed >= self.duration:
                # Transition complete for this block
                interpolated_blocks.append(new_block)
            else:
                # Block is mid-transition
                progress = block_elapsed / self.duration
                interpolated_blocks.append(self._lerp_color(old_block, new_block, progress))

        return interpolated_blocks

    def get_progress(self) -> float:
        """Get overall transition progress (0.0 to 1.0)."""
        if self.start_time is None:
            return 0.0  # Transition hasn't started yet
        elapsed = time.time() - self.start_time
        return min(1.0, elapsed / self.duration)

    def blocks_to_image(self, blocks: List[ColorBlock]) -> Image.Image:
        """Convert color blocks back to an image."""
        img_array = np.zeros((self.image_height, self.image_width, 3), dtype=np.uint8)

        for block in blocks:
            x1, y1 = block.x, block.y
            x2, y2 = x1 + block.width, y1 + block.height

            # Fill block with averaged color
            img_array[y1:y2, x1:x2] = [
                int(block.r * 255),
                int(block.g * 255),
                int(block.b * 255)
            ]

        return Image.fromarray(img_array, 'RGB')


class TransitionManager:
    """
    Manages multiple simultaneous transitions and provides
    integration with the Looking Glass rendering system.
    """

    def __init__(self):
        self.active_transition: Optional[ImageTransition] = None
        self.transition_callbacks: List[Callable] = []

    def start_transition(self,
                        old_image: Image.Image,
                        new_image: Image.Image,
                        **kwargs) -> ImageTransition:
        """
        Start a new image transition.

        Args:
            old_image: Current background image
            new_image: New background image
            **kwargs: Transition parameters (duration, pattern, easing, etc.)

        Returns:
            ImageTransition object
        """
        # Stop any existing transition
        if self.active_transition and not self.active_transition.is_complete:
            print("🔄 Interrupting previous transition")

        self.active_transition = ImageTransition(old_image, new_image, **kwargs)

        # Notify callbacks that transition started
        for callback in self.transition_callbacks:
            try:
                callback('start', self.active_transition)
            except Exception as e:
                print(f"⚠️  Transition callback error: {e}")

        return self.active_transition

    def update(self) -> Optional[Image.Image]:
        """
        Update active transition and return current frame.

        Returns:
            Current transition frame as PIL Image, or None if no active transition
        """
        if not self.active_transition:
            return None

        # Get current frame
        current_blocks = self.active_transition.get_current_frame()
        current_image = self.active_transition.blocks_to_image(current_blocks)

        # Check if transition completed
        if self.active_transition.is_complete:
            print("✅ Image transition completed")

            # Notify callbacks
            for callback in self.transition_callbacks:
                try:
                    callback('complete', self.active_transition)
                except Exception as e:
                    print(f"⚠️  Transition callback error: {e}")

            self.active_transition = None

        return current_image

    def add_callback(self, callback: Callable):
        """Add callback for transition events (start, update, complete)."""
        self.transition_callbacks.append(callback)

    def is_active(self) -> bool:
        """Check if a transition is currently active."""
        return self.active_transition is not None and not self.active_transition.is_complete

    def get_progress(self) -> float:
        """Get progress of active transition (0.0 to 1.0)."""
        if not self.active_transition:
            return 1.0
        return self.active_transition.get_progress()


# Global transition manager instance
transition_manager = TransitionManager()


def create_transition(old_image: Image.Image,
                     new_image: Image.Image,
                     duration: float = 1.5,
                     pattern: str = 'wave',
                     easing: str = 'smoothstep') -> ImageTransition:
    """
    Convenience function to create and start an image transition.

    Args:
        old_image: Source image
        new_image: Target image
        duration: Transition duration in seconds
        pattern: Transition pattern ('linear', 'spiral', 'wave', 'random')
        easing: Easing function ('linear', 'smoothstep', 'ease_in_out', 'bounce')

    Returns:
        ImageTransition object
    """
    return transition_manager.start_transition(
        old_image, new_image,
        duration=duration,
        pattern=pattern,
        easing=easing
    )


class SimpleColorTransition:
    """
    Super simple transition that just blends between two solid colors.
    No blocks, no complex easing, just pure RGB interpolation.
    """

    def __init__(self, old_color: tuple, new_color: tuple, duration: float = 1.5):
        """
        Args:
            old_color: (r, g, b) tuple 0-255
            new_color: (r, g, b) tuple 0-255
            duration: Transition duration in seconds
        """
        self.old_color = old_color
        self.new_color = new_color
        self.duration = duration
        self.start_time = None
        self.is_complete = False
        self.frame_count = 0

    def get_current_color(self) -> tuple:
        """Get current interpolated color as (r, g, b) tuple"""
        current_time = time.time()

        # Start timer on first request
        if self.start_time is None:
            self.start_time = current_time
            print(f"🎨 Starting simple color transition")

        elapsed = current_time - self.start_time
        self.frame_count += 1

        if elapsed >= self.duration:
            self.is_complete = True
            print(f"🎨 Simple transition complete after {self.frame_count} frames")
            return self.new_color

        # Simple linear interpolation
        progress = elapsed / self.duration

        r = int(self.old_color[0] + (self.new_color[0] - self.old_color[0]) * progress)
        g = int(self.old_color[1] + (self.new_color[1] - self.old_color[1]) * progress)
        b = int(self.old_color[2] + (self.new_color[2] - self.old_color[2]) * progress)

        return (r, g, b)

    def get_progress(self) -> float:
        """Get progress 0.0 to 1.0"""
        if self.start_time is None:
            return 0.0
        elapsed = time.time() - self.start_time
        return min(1.0, elapsed / self.duration)


if __name__ == "__main__":
    # Test the transition system
    print("🎬 Testing Image Transition System")

    # Create test images
    img1 = Image.new('RGB', (100, 100), (255, 0, 0))    # Red
    img2 = Image.new('RGB', (100, 100), (0, 0, 255))    # Blue

    # Create transition
    transition = create_transition(img1, img2, duration=2.0, pattern='spiral')

    # Simulate animation loop
    while not transition.is_complete:
        current_frame = transition_manager.update()
        progress = transition.get_progress()
        print(f"Transition progress: {progress:.1%}")
        time.sleep(0.1)

    print("🎉 Transition test completed!")