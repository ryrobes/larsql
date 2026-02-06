#!/usr/bin/env python3
"""
Live Data Glass Widget - Direct terminal updates for real-time data
================================================================

Bypasses Textual's batching system for immediate updates while maintaining
glass morphism effects and proper coordinate positioning.
"""

import sys
import time
from typing import Optional
from .looking_glass import AbsoluteGlassWidget
import numpy as np


class LiveDataGlassWidget(AbsoluteGlassWidget):
    """Widget that updates directly to terminal without waiting for render cycles"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._live_mode = True
        self._last_live_content = ""
        self._live_update_count = 0
        self._test_mode = False  # Disable test mode to see glass effects
        self._live_content_lines = []  # Store live content for render method

    def update_live(self, content: str):
        """Immediate terminal update - bypasses Textual entirely"""
        if not hasattr(self, 'region') or not self.region or content == self._last_live_content:
            return

        self._live_update_count += 1

        # Store content for render method
        self._live_content_lines = content.split('\n')

        # DEBUG: Write to file to see if this is being called
        # try:
        #     with open('/tmp/live_widget_debug.log', 'a') as f:
        #         f.write(f"[{time.time():.3f}] update_live called: count={self._live_update_count}, region=({self.region.x},{self.region.y}), content='{content[:50]}...'\n")
        # except:
        #     pass

        # METHOD 1: Try direct terminal writes (original approach)
        if getattr(self, '_use_direct_writes', True):
            lines = content.split('\n')
            for y, line in enumerate(lines):
                if y >= self.region.height:
                    break

                # Apply glass effect and write the line
                self._write_live_line(y, line)

            # Flush immediately for instant updates
            sys.stdout.flush()

        # METHOD 2: Force immediate re-render through Textual
        else:
            self.refresh()

        self._last_live_content = content

    def _write_live_line(self, y: int, text: str):
        """Write a single line with glass effect directly to terminal"""
        if not hasattr(self, 'region') or not self.region:
            return

        screen_x = self.region.x
        screen_y = self.region.y + y

        # Safety check for valid coordinates
        if screen_x < 0 or screen_y < 0:
            return

        # DEBUG: Log what we're about to write
        try:
            with open('/tmp/live_widget_debug.log', 'a') as f:
                f.write(f"  Writing line {y}: '{text}' at ({screen_x},{screen_y})\n")
        except:
            pass

        # Position cursor
        sys.stdout.write(f"\x1b[{screen_y+1};{screen_x+1}H")

        # TEST: Try writing to multiple locations to see if Textual overwrites
        if getattr(self, '_test_mode', False):
            # Write to our intended location
            simple_text = f"\x1b[41m\x1b[37m\x1b[1m{text.ljust(25)}\x1b[0m"
            sys.stdout.write(simple_text)

            # ALSO write to visible bottom area (safe coordinates)
            sys.stdout.write(f"\x1b[35;1HTEST-{self._live_update_count}-LINE{y}\x1b[0m")

            # ALSO write to top-left (definitely visible)
            sys.stdout.write(f"\x1b[1;1HLIVE-{self._live_update_count}\x1b[0m")

        else:
            # Apply glass effect to each character
            styled_line = self._apply_glass_effect_to_line(text, y)
            sys.stdout.write(styled_line)

        # Force immediate flush
        sys.stdout.flush()

        # DEBUG: Also write to log what styled line looks like
        try:
            with open('/tmp/live_widget_debug.log', 'a') as f:
                f.write(f"  Styled: test_mode={getattr(self, '_test_mode', False)}, flushed\n")
        except:
            pass

    def _apply_glass_effect_to_line(self, text: str, y: int) -> str:
        """Apply glass effect to a single line for live updates"""
        if (self._precomputed_colors is None or
            not hasattr(self, 'region') or
            self.region is None or
            y >= self._precomputed_colors.shape[0]):
            # Fallback to BRIGHT visible text if no glass effect available
            width = self.region.width if hasattr(self, 'region') and self.region else 25
            # Use bright white text on blue background - very visible
            return f"\x1b[48;5;21m\x1b[38;5;15m\x1b[1m{text.ljust(width)}\x1b[0m"

        ansi_line = ""
        padded_text = text.ljust(self.region.width)

        for x, char in enumerate(padded_text):
            if x >= self.region.width:
                break

            if x < self._precomputed_colors.shape[1]:
                # Use precomputed glass effect color
                color = self._precomputed_colors[y, x]
                # Write character with glass background and white text
                ansi_line += f"\x1b[48;2;{color[0]};{color[1]};{color[2]}m\x1b[38;2;255;255;255m\x1b[1m{char}"
            else:
                # Fallback color for edge cases - bright and visible
                ansi_line += f"\x1b[48;5;21m\x1b[38;5;15m\x1b[1m{char}"

        # Reset colors at end of line
        ansi_line += "\x1b[0m"
        return ansi_line

    def render_line(self, y: int):
        """Override render to show live content when available"""
        # If we have live content, use it instead of base content
        if hasattr(self, '_live_content_lines') and self._live_content_lines:
            if y < len(self._live_content_lines):
                line_content = self._live_content_lines[y]

                # INTEGRATE WITH GLASS EFFECTS - use parent's glass rendering!
                # First, set our content to the live content
                original_content = self.content
                self.content = '\n'.join(self._live_content_lines)

                # Call parent's render_line which has all the glass effect logic
                strip = super().render_line(y)

                # Restore original content
                self.content = original_content

                return strip

        # Fall back to parent render
        return super().render_line(y)


class LiveFPSCounter(LiveDataGlassWidget):
    """Live FPS counter that updates immediately without render batching"""

    def __init__(self, **kwargs):
        # Set default size for FPS counter
        kwargs.setdefault('width', 25)
        kwargs.setdefault('height', 6)
        kwargs.setdefault('overlay_color', 'darkblue')
        kwargs.setdefault('blend_opacity', 0.7)

        super().__init__(**kwargs)

        # FPS tracking
        self._frame_times = []
        self._last_update_time = time.time()
        self._update_count = 0

    def update_fps(self, fps: float, frame_time: float):
        """Update FPS display immediately"""
        current_time = time.time()

        # Track frame times for sparkline
        self._frame_times.append(frame_time)
        if len(self._frame_times) > 20:  # Keep last 20 frames
            self._frame_times = self._frame_times[-20:]

        # Create sparkline
        sparkline = self._create_mini_sparkline(self._frame_times, 12)

        # Format display content
        content = [
            f"FPS: {fps:5.1f}",
            f"Frame: {frame_time:5.1f}ms",
            f"Spark: {sparkline}",
            f"Live: {self._live_update_count:4d}",
            f"Time: {current_time:.1f}"
        ]

        # Update immediately via direct terminal write
        self.update_live('\n'.join(content))

        self._last_update_time = current_time
        self._update_count += 1

    def _create_mini_sparkline(self, values, width: int) -> str:
        """Create a tiny sparkline for FPS visualization"""
        if not values or len(values) < 2:
            return "─" * width

        # Use last 'width' values
        data = values[-width:] if len(values) > width else values

        # Normalize to 0-1 range
        min_val = min(data)
        max_val = max(data)
        if max_val == min_val:
            return "─" * len(data)

        # Unicode block characters for sparkline
        blocks = " ▁▂▃▄▅▆▇█"

        sparkline = ""
        for val in data:
            normalized = (val - min_val) / (max_val - min_val)
            block_idx = min(len(blocks) - 1, int(normalized * (len(blocks) - 1)))
            sparkline += blocks[block_idx]

        # Pad to width
        return sparkline.ljust(width)


# Integration helper for adding to existing apps
def create_live_fps_counter(x: int = 2, y: int = 2, widget_id: str = "live_fps") -> dict:
    """Create a live FPS counter widget definition"""
    return {
        'id': widget_id,
        'type': 'live_fps',
        'x': x,
        'y': y,
        'width': 25,
        'height': 6,
        'overlay_color': 'purple',
        'padding': 1,
        'blend_opacity': 0.4,
        'live_mode': True  # Flag to exclude from normal reconciliation
    }