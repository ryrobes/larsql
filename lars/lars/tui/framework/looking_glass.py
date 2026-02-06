#!/usr/bin/env python3
"""
Looking Glass - A Glass Morphism System for Textual
===================================================

A working glass effect system that provides transparent widgets over
ANSI art backgrounds with true absolute positioning.

Based on the proven glass_working_system.py with enhancements for
absolute positioning, z-index support, and page management.
"""

import os
from typing import Optional, Union, Literal, Tuple, List, Dict
from functools import lru_cache
import tempfile
import re
import time
import colorsys

# Check if we're in headless mode
HEADLESS_MODE = os.environ.get('REACTIVE_HEADLESS', 'false').lower() == 'true'

if HEADLESS_MODE:
    # Headless mode - provide minimal implementations
    class App:
        def __init__(self, *args, **kwargs): pass
        def run(self): pass
        def exit(self): pass
        def call_later(self, callback, *args):
            # In headless mode, execute immediately
            if callable(callback):
                callback()
        
    ComposeResult = list
    
    class Widget:
        def __init__(self, *args, **kwargs): pass
        def refresh(self): pass
        
    class Strip:
        pass
        
    def reactive(x):
        return x
        
    class Region:
        def __init__(self, x=0, y=0, width=0, height=0):
            self.x = x
            self.y = y
            self.width = width
            self.height = height
            
    class Segment:
        def __init__(self, text, style=None):
            self.text = text
            self.style = style
            
    class RichStyle:
        def __init__(self, **kwargs): pass
        
    # Lazy imports for heavy dependencies - create mock classes
    class np:
        ndarray = object
        @staticmethod
        def array(*args, **kwargs): return []
        @staticmethod
        def mean(*args, **kwargs): return 0
        @staticmethod
        def sin(*args, **kwargs): return 0
        float32 = float
        uint8 = int
        
    climage = None
    
    class Image:
        @staticmethod
        def open(*args, **kwargs): return None
        @staticmethod
        def fromarray(*args, **kwargs): return None
        
    ColorThief = None
    
else:
    # Normal mode - import everything
    from textual.app import App, ComposeResult
    from textual.widget import Widget
    from textual.strip import Strip
    from textual.reactive import reactive
    from textual.geometry import Region
    from rich.segment import Segment
    from rich.style import Style as RichStyle
    import numpy as np
    import climage
    from PIL import Image
    from colorthief import ColorThief
from .image_transition import transition_manager, create_transition, SimpleColorTransition

# Import pure functions - always use the main module which handles Cython fallback internally
from .glass_pure_functions import (
    color_to_rgb, rgb_to_hex, vectorized_hex_conversion,
    vectorized_blur_zero_sampling, sample_with_blur,
    batch_blend_colors, parse_ansi_line, get_content_hash,
    calculate_image_region
)

# Import bounded cache implementations
from collections import OrderedDict, defaultdict

# class SimpleBoundedCache(OrderedDict):
#     """Simple bounded OrderedDict that maintains maximum size"""

#     def __init__(self, max_size: int = 1000):
#         super().__init__()
#         self.max_size = max_size

#     def __setitem__(self, key, value):
#         # If key exists, delete it first so it moves to end
#         if key in self:
#             del self[key]

#         super().__setitem__(key, value)

#         # Evict oldest if over capacity
#         if len(self) > self.max_size:
#             self.popitem(last=False)  # Remove oldest

from .adaptive_cache import AdaptiveCache as SimpleBoundedCache

# Optional: Import adaptive cache for better performance
# Uncomment to use adaptive caching instead of simple bounded cache
# try:
#     from .adaptive_cache import AdaptiveCache as SimpleBoundedCache
# except ImportError:
#     pass  # Use simple bounded cache above

# Type aliases
EdgeSticky = Literal["left", "right", "top", "bottom", "center"]
SizeValue = Union[int, str]


# ==============================================================================
# BACKGROUND SYSTEM - Ultra-fast ANSI rendering
# ==============================================================================

class UltraFastTrueColorBackground(Widget):
    """Background widget with ultra-fast ANSI parsing"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._raw_lines = []
        self._segments_by_line = []
        self._style_cache = SimpleBoundedCache(max_size=500)  # Bounded cache for RichStyle objects

        # PERFORMANCE: Cache parsed strips to avoid re-parsing same lines
        self._strip_cache = SimpleBoundedCache(max_size=200)  # line_number -> Strip object

    def render_line(self, y: int) -> Strip:
        """PERFORMANCE: Fast rendering with strip caching"""
        # Check cache first
        if y in self._strip_cache:
            return self._strip_cache[y]

        # Generate strip and cache it
        if self._segments_by_line and y < len(self._segments_by_line):
            strip = Strip(self._segments_by_line[y])
        else:
            strip = Strip([])

        # Cache the strip (bounded cache handles size limit automatically)
        self._strip_cache[y] = strip
        return strip

    def update_ansi_ultra(self, ansi_output: str):
        """Update with pre-parsed ANSI"""
        # Check if content actually changed
        new_lines = ansi_output.split('\n')
        if hasattr(self, '_raw_lines') and self._raw_lines == new_lines:
            # No change, don't refresh
            return

        self._raw_lines = new_lines
        self._segments_by_line = []

        # PERFORMANCE: Clear strip cache when background changes
        self._strip_cache = {}

        for line in self._raw_lines:
            segments = self._ultra_fast_truecolor_segments(line)
            self._segments_by_line.append(segments)

        self.refresh()

    def _ultra_fast_truecolor_segments(self, line: str) -> List[Segment]:
        """PERFORMANCE: Optimized ANSI parsing using pure function"""
        if not line:
            return []

        segments = []
        parsed_segments = parse_ansi_line(line)

        for text, fg, bg in parsed_segments:
            style_key = (fg, bg)
            if style_key not in self._style_cache:
                self._style_cache[style_key] = RichStyle(color=fg, bgcolor=bg) if (fg or bg) else RichStyle()
            segments.append(Segment(text, self._style_cache[style_key]))

        return segments


# ==============================================================================
# GLASS WIDGET SYSTEM - Transparent widgets with blending
# ==============================================================================

class BlazingFastBlendWidget(Widget):
    """Base glass widget with transparency effects"""

    # Class-level flag to track if ANY widget needs re-render
    _any_widget_dirty = True

    def _get_content_hash(self, content):
        """Get a hash of content for cache invalidation"""
        return get_content_hash(content)

    def __init__(self, content: str = "", overlay_color: str = "blue",
                 blend_opacity: float = 0.5, darken_factor: float = 0.0,
                 blur: int = 2, padding: int = 0, **kwargs):
        super().__init__(**kwargs)
        self._content = content
        self.overlay_color = overlay_color
        self.blend_opacity = blend_opacity
        self.darken_factor = darken_factor
        self.blur = max(0, blur)  # Ensure non-negative
        self._padding = max(0, padding)  # Ensure non-negative padding
        self._image_array = None
        self._precomputed_colors = None
        self._overlay_rgb = color_to_rgb(overlay_color)
        self._background_cache = SimpleBoundedCache(max_size=100)  # Cache for background segments when blur=0
        self._style_cache = SimpleBoundedCache(max_size=1000)  # Cache for RichStyle objects to reduce allocations
        self._precomputed_hex = None  # Cache for hex color strings
        self._strip_cache = SimpleBoundedCache(max_size=200)  # Cache rendered strips for unchanged content
        self._last_content_hash = self._get_content_hash(content)  # Track content changes

        # PERFORMANCE FIX: Track state to prevent unnecessary precompute calls
        self._last_precompute_region = None
        self._last_precompute_image_id = None
        self._last_precompute_visual_state = None
        self._precompute_counter = 0  # Debug counter

        # PERFORMANCE: Pre-create common styles to avoid repeated allocations
        self._common_styles = {}
        self._warm_style_cache()

        # HIGH-LEVEL CACHE: Cache entire widget rendering
        self._full_render_cache = SimpleBoundedCache(max_size=50)  # Maps (cache_key) -> List[Strip]
        self._content_lines_cache = None  # Cache split content
        self._content_lines_cache_key = None

        # SEGMENT CACHE: Reuse segment objects
        self._segment_cache = SimpleBoundedCache(max_size=5000)  # (char, style_key) -> Segment

        # PERFORMANCE: Cache for sampled regions - pure computation so safe to cache
        self._sampled_region_cache = SimpleBoundedCache(max_size=50)  # (region, blur, image_id) -> sampled_region

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, value):
        self._content = value
        # Clear strip cache when content changes
        if self._get_content_hash(value) != self._last_content_hash:
            self._strip_cache = {}
            self._last_content_hash = self._get_content_hash(value)
        self.refresh()

    @property
    def padding(self):
        return self._padding

    @padding.setter
    def padding(self, value):
        old_padding = self._padding
        self._padding = max(0, value)  # Ensure non-negative
        # Clear strip cache when padding changes
        if old_padding != self._padding:
            self._strip_cache = {}
            # Force content hash update
            self._last_content_hash = None
            self.refresh()

    def set_image_data(self, image_array: np.ndarray):
        """Store image data and precompute colors"""
        self._image_array = image_array
        self._precompute_colors()
        # Clear strip cache when background changes
        self._strip_cache = {}

    def _clear_caches(self):
        """Clear all internal caches - useful when visual properties change"""
        self._strip_cache = {}
        # Note: We keep style_cache as styles are reusable across changes

    def _precompute_colors(self):
        """Precompute all colors for the widget area using numpy"""
        # PERFORMANCE FIX: Check if we actually need to recompute
        current_region = (self.region.x, self.region.y, self.region.width, self.region.height) if self.region else None
        current_image_id = id(self._image_array) if self._image_array is not None else None
        current_visual_state = (
            getattr(self, 'blend_opacity', 0.5),
            getattr(self, 'overlay_color', 'blue'),
            getattr(self, 'darken_factor', 0.0),
            getattr(self, 'blur', 2)
        )

        if (current_region == self._last_precompute_region and
            current_image_id == self._last_precompute_image_id and
            current_visual_state == self._last_precompute_visual_state and
            self._precomputed_colors is not None):
            # No need to recompute - cache hit!
            return

        # Update overlay RGB in case overlay_color changed
        self._overlay_rgb = color_to_rgb(self.overlay_color)

        # Track this computation
        self._precompute_counter += 1
        self._last_precompute_region = current_region
        self._last_precompute_image_id = current_image_id
        self._last_precompute_visual_state = current_visual_state

        # Skip if we don't need blending at all (pure optimization)
        if self.blend_opacity == 0 and self.darken_factor == 0 and self.blur == 0:
            self._precomputed_colors = None
            self._precomputed_hex = None
            return

        if self._image_array is None or self.region is None:
            if 'Canvas' in self.__class__.__name__:
                # Store for debug display
                self._last_precompute_info = f"SKIP: img={self._image_array is not None}, reg={self.region is not None}"
            self._precomputed_hex = None  # Clear hex cache when no image/region
            return

        # Force refresh values from instance
        blur_val = getattr(self, 'blur', 2)
        opacity_val = getattr(self, 'blend_opacity', 0.5)

        # Don't use passthrough mode anymore - it still causes distortion
        # Instead, we'll handle blur=0 in the sampling logic
        self._passthrough_mode = False

        region = self.region
        h, w = region.height, region.width

        # Widget position in terminal (needed for cache key)
        widget_y = region.y
        widget_x = region.x

        # Use pure function for image region calculation
        img_y_start, img_y_end, img_x_start, img_x_end = calculate_image_region(
            widget_x, widget_y, w, h,
            self._image_array.shape[1], self._image_array.shape[0]
        )

        if 'Canvas' in self.__class__.__name__:
            self._last_precompute_info = f"COORDS: y{img_y_start}-{img_y_end}, x{img_x_start}-{img_x_end}"

        # PERFORMANCE FIX: Early return if widget has zero size
        if h == 0 or w == 0 or img_y_end <= img_y_start or img_x_end <= img_x_start:
            self._precomputed_colors = None
            self._precomputed_hex = None
            return

        if img_y_end > img_y_start and img_x_end > img_x_start:
            # Get the image region
            img_region = self._image_array[img_y_start:img_y_end, img_x_start:img_x_end]

            # Debug for canvas
            if 'Canvas' in self.__class__.__name__:
                self._last_precompute_info = f"IMG_REGION: {img_region.shape}, need h={h} w={w}"

            # PERFORMANCE: Cache sampled regions since they're pure/immutable
            sampled_cache_key = (
                (widget_x, widget_y, h, w),  # Region info
                self.blur,                   # Blur setting
                current_image_id,           # Image data
                img_region.shape            # Image region shape for extra safety
            )

            if sampled_cache_key in self._sampled_region_cache:
                # Cache hit!
                sampled_region = self._sampled_region_cache[sampled_cache_key]
            else:
                # Cache miss - compute and store
                if self.blur == 0:
                    # PERFORMANCE: Vectorized blur=0 sampling - no Python loops!
                    sampled_region = vectorized_blur_zero_sampling(img_region, h, w)
                else:
                    # Blur > 0: average NxN blocks
                    if 'Canvas' in self.__class__.__name__:
                        self.log(f"CANVAS USING BLUR SAMPLING! blur={self.blur}")
                    sampled_region = sample_with_blur(img_region, h, w, self.blur, 2)

                # Store in cache (bounded cache handles size limit automatically)
                self._sampled_region_cache[sampled_cache_key] = sampled_region

            # Pre-blend all colors
            self._precomputed_colors = batch_blend_colors(sampled_region, self._overlay_rgb,
                                                          self.blend_opacity, self.darken_factor)

        # PERFORMANCE: Skip hex pre-conversion - convert on-demand is faster
        # if self._precomputed_colors is not None:
        #     self._precomputed_hex = self._vectorized_hex_conversion(self._precomputed_colors)
        self._precomputed_hex = None  # Disable pre-conversion

        if 'Canvas' in self.__class__.__name__:
            # Check what colors we actually got
            if self._precomputed_colors is not None and self._precomputed_colors.size > 0:
                first_pixel = self._precomputed_colors[0, 0]
                avg_color = np.mean(self._precomputed_colors[:5, :5], axis=(0,1)).astype(int)
                self._last_precompute_info = f"DONE: shape={self._precomputed_colors.shape}, first={first_pixel}, avg5x5={avg_color}"
            else:
                self._last_precompute_info = f"DONE: precomp={self._precomputed_colors.shape if self._precomputed_colors is not None else 'None'}"


    def _warm_style_cache(self):
        """PERFORMANCE: Pre-create common style combinations"""
        # Common colors used in glass effects
        common_bg_colors = ['black', 'blue', 'cyan', 'green', 'red', 'yellow', 'magenta']
        common_text_colors = ['white', 'black']

        for bg in common_bg_colors:
            for text in common_text_colors:
                for bold in [True, False]:
                    style_key = (bg, text, bold)
                    if bold:
                        self._style_cache[style_key] = RichStyle(bgcolor=bg, color=text, bold=True)
                    else:
                        self._style_cache[style_key] = RichStyle(bgcolor=bg, color=text)

                # Background-only style (for spaces)
                bg_only_key = (bg, None, False)
                self._style_cache[bg_only_key] = RichStyle(bgcolor=bg)




    def _get_content_lines(self):
        """Get content lines with caching"""
        content_hash = self._last_content_hash
        if self._content_lines_cache_key == content_hash:
            return self._content_lines_cache

        # Cache miss - split and cache
        self._content_lines_cache = self.content.split('\n')
        self._content_lines_cache_key = content_hash
        return self._content_lines_cache

    def render_line(self, y: int) -> Strip:
        """Render with glass effect"""
        # PERFORMANCE: Early exit if widget hasn't been marked dirty
        if hasattr(self, '_render_cache_valid') and self._render_cache_valid:
            if hasattr(self, '_cached_strips') and y < len(self._cached_strips):
                return self._cached_strips[y]

        # ULTRA HIGH-LEVEL CACHE: Check if we can return pre-rendered strip
        # This avoids ALL the work below if nothing has changed
        render_state_key = (
            self._last_content_hash,
            self._precompute_counter,
            self.size.width if self.size else 0,
            self.size.height if self.size else 0,
            self.blend_opacity,
            self.darken_factor,
            self.blur,
            self.overlay_color,
            id(self._precomputed_colors) if self._precomputed_colors is not None else None
        )

        if render_state_key in self._full_render_cache:
            strips = self._full_render_cache[render_state_key]
            if y < len(strips):
                # Cache for next time
                if not hasattr(self, '_cached_strips'):
                    self._cached_strips = strips
                    self._render_cache_valid = True
                return strips[y]

        # Check strip cache first
        # PERFORMANCE FIX: Use stable cache key that doesn't invalidate unnecessarily
        cache_key = (
            y,
            self._last_content_hash,
            self._precompute_counter,  # Only changes when precompute actually runs
            self.size.width if self.size else 0
        )

        if cache_key in self._strip_cache:
            return self._strip_cache[cache_key]

        # Special handling for blur=0 and opacity=0 - get original background
        if self.blur == 0 and self.blend_opacity == 0 and self.app:
            try:
                # Get the background widget
                bg = self.app.query_one("#background", UltraFastTrueColorBackground)
                if bg and self.region:
                    # Get the background strip at the widget's position
                    bg_y = self.region.y + y
                    if bg_y < bg.size.height:
                        bg_strip = bg.render_line(bg_y)
                        # Extract segments for our width
                        if bg_strip and bg_strip._segments:
                            segments = [None] * self.size.width  # Pre-allocate
                            x_start = self.region.x
                            x_end = min(x_start + self.size.width, len(bg_strip._segments))

                            # Get our content
                            content_lines = self._get_content_lines()
                            text = ""
                            if y < len(content_lines):
                                text = content_lines[y].center(self.size.width)

                            # Copy background segments but overlay our text
                            for i, x in enumerate(range(x_start, x_end)):
                                if x < len(bg_strip._segments):
                                    bg_seg = bg_strip._segments[x]
                                    char = text[i] if i < len(text) and text[i] != ' ' else bg_seg.text
                                    # Keep background style but use our text
                                    segments[i] = Segment(char, bg_seg.style)

                            # Fill remaining slots if needed
                            for i in range(x_end - x_start, self.size.width):
                                segments[i] = Segment(" ", RichStyle())

                            strip = Strip(segments)
                            # Limit cache size
                            if len(self._strip_cache) > 100:
                                oldest_key = next(iter(self._strip_cache))
                                del self._strip_cache[oldest_key]
                            self._strip_cache[cache_key] = strip
                            return strip
            except:
                pass

        # PERFORMANCE FIX: Remove frequent precompute check - let the method handle its own caching
        # Old code: if self.region and self._image_array is not None: self._precompute_colors()
        # New: Only precompute if we actually need colors and don't have them
        if (self._precomputed_colors is None and self.region and self._image_array is not None and
            not (self.blend_opacity == 0 and self.darken_factor == 0 and self.blur == 0)):
            self._precompute_colors()

        width = self.size.width
        segments = [None] * width  # Pre-allocate segments list

        # Normal glass effect rendering
        content_lines = self._get_content_lines()

        if y < len(content_lines):
            # Text line
            text = content_lines[y].center(width)

            for x in range(width):
                char = text[x] if x < len(text) else ' '

                # PERFORMANCE: Convert colors on-demand instead of pre-converting
                if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    # Fallback to overlay color
                    bg_hex = self.overlay_color

                # Use cached style to avoid creating new objects every frame
                style_key = (bg_hex, "white", True)  # bgcolor, color, bold
                if style_key not in self._style_cache:
                    self._style_cache[style_key] = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                style = self._style_cache[style_key]

                # PERFORMANCE: Cache segments too
                segment_key = (char, style_key)
                if segment_key not in self._segment_cache:
                    self._segment_cache[segment_key] = Segment(char, style)
                segments[x] = self._segment_cache[segment_key]
        else:
            # Empty line with glass effect
            for x in range(width):
                # PERFORMANCE: Convert colors on-demand
                if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color

                # Use cached style for empty lines too
                style_key = (bg_hex, None, False)  # bgcolor only, no color or bold
                if style_key not in self._style_cache:
                    self._style_cache[style_key] = RichStyle(bgcolor=bg_hex)
                style = self._style_cache[style_key]

                # PERFORMANCE: Cache segments
                segment_key = (" ", style_key)
                if segment_key not in self._segment_cache:
                    self._segment_cache[segment_key] = Segment(" ", style)
                segments[x] = self._segment_cache[segment_key]

        strip = Strip(segments)
        # Store in cache (bounded cache handles size limit automatically)
        self._strip_cache[cache_key] = strip
        return strip

    def _render_line_internal(self, y: int, cache_key):
        """Internal render without caching - used by batch renderer"""
        width = self.size.width
        segments = [None] * width

        # Get content lines
        content_lines = self._get_content_lines()

        if y < len(content_lines):
            # Text line
            text = content_lines[y].center(width)

            for x in range(width):
                char = text[x] if x < len(text) else ' '

                if self._precomputed_hex is not None and y < self._precomputed_hex.shape[0] and x < self._precomputed_hex.shape[1]:
                    bg_hex = self._precomputed_hex[y, x]
                else:
                    bg_hex = self.overlay_color

                style_key = (bg_hex, "white", True)
                if style_key not in self._style_cache:
                    self._style_cache[style_key] = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                style = self._style_cache[style_key]
                segments[x] = Segment(char, style)
        else:
            # Empty line
            for x in range(width):
                if self._precomputed_hex is not None and y < self._precomputed_hex.shape[0] and x < self._precomputed_hex.shape[1]:
                    bg_hex = self._precomputed_hex[y, x]
                else:
                    bg_hex = self.overlay_color

                style_key = (bg_hex, None, False)
                if style_key not in self._style_cache:
                    self._style_cache[style_key] = RichStyle(bgcolor=bg_hex)
                style = self._style_cache[style_key]
                segments[x] = Segment(" ", style)

        return Strip(segments)

    def refresh(self, *regions, repaint: bool = True, layout: bool = False, **kwargs) -> None:
        """Override refresh to invalidate render cache"""
        self._render_cache_valid = False
        if hasattr(self, '_cached_strips'):
            delattr(self, '_cached_strips')
        super().refresh(*regions, repaint=repaint, layout=layout, **kwargs)



# ==============================================================================
# CONNECTION CANVAS - Single widget for drawing all connections
# ==============================================================================

class GlassConnectionCanvas(BlazingFastBlendWidget):
    """A full-viewport canvas for drawing connection lines between widgets."""

    def __init__(self, **kwargs):
        """Initialize the connection canvas."""
        # Pop out any conflicting parameters to avoid conflicts
        kwargs.pop('blend_opacity', None)
        kwargs.pop('darken_factor', None)
        kwargs.pop('overlay_color', None)
        kwargs.pop('blur', None)
        kwargs.pop('content', None)  # Also pop content

        # Force settings for transparent background with no blur
        # These will take precedence over anything in kwargs
        super().__init__(
            content='',
            blend_opacity=0.0,
            darken_factor=0.0,
            overlay_color='black',
            blur=0,  # THIS IS THE KEY - NO BLUR!
            **kwargs
        )
        self._connection_metadata = {}  # Store color info for lines
        self.connections = []  # List of connection definitions
        self._line_chars = {
            'solid': {'horizontal': '─', 'vertical': '│', 'corner': '┼'},
            'double': {'horizontal': '═', 'vertical': '║', 'corner': '╬'},
            'thick': {'horizontal': '━', 'vertical': '┃', 'corner': '╋'},
            'block': {'horizontal': '█', 'vertical': '█', 'corner': '█'},
            'dashed': {'horizontal': '╌', 'vertical': '╎', 'corner': '┼'},
            'dotted': {'horizontal': '┄', 'vertical': '┆', 'corner': '┼'}
        }
        self._grid = []  # Store the grid

    def update_connections(self, connections):
        """Update the list of connections to draw."""
        self.connections = connections
        # self.log(f"Canvas updating with {len(connections)} connections")
        # for conn in connections:
        #     self.log(f"  Connection: {conn['start']} -> {conn['end']}")
        self._render_connections()

    def on_mount(self):
        """Initial render when mounted."""
        self.log(f"Canvas mounted with size: {self.size}")
        # Initialize empty grid if needed
        if not self._grid and self.size:
            self._grid = [[' ' for _ in range(self.size.width)] for _ in range(self.size.height)]
        self._render_connections()
        # Try to render after a delay
        self.set_timer(0.1, self._render_connections)
        self.set_timer(0.5, self._render_connections)
        self.set_timer(1.0, self._render_connections)

    def on_resize(self, event):
        """Re-render when resized."""
        self._render_connections()

    def _render_connections(self):
        """Render all connections onto the canvas."""
        if not self.size:
            self.log("No size yet, skipping render")
            return

        width = self.size.width
        height = self.size.height
        # self.log(f"Rendering canvas {width}x{height} with {len(self.connections)} connections")

        # Clear metadata
        self._connection_metadata = {}

        # Create a 2D grid for the canvas
        grid = [[' ' for _ in range(width)] for _ in range(height)]

        # Draw each connection
        for conn in self.connections:
            self._draw_connection(grid, conn)

        # Count non-space characters
        non_space = sum(1 for row in grid for char in row if char != ' ')

        # Convert grid to content string
        lines = [''.join(row) for row in grid]
        self.content = '\n'.join(lines)

        # Force refresh to apply colors through render_line override
        self.refresh()

    def render_line(self, y: int) -> Strip:
        """Custom render for connection lines with transparent background."""
        # Make sure to precompute colors if needed
        if self.region and self._image_array is not None and self._precomputed_colors is None:
            self._precompute_colors()

        # TEMPORARILY DISABLE DEBUG to test
        if False and y < 8:
            img_shape = self._image_array.shape if self._image_array is not None else 'None'
            precomp_shape = self._precomputed_colors.shape if self._precomputed_colors is not None else 'None'
            region_info = f"{self.region}" if self.region else 'None'
            # Store last precompute call info
            if not hasattr(self, '_last_precompute_info'):
                self._last_precompute_info = "No precompute called yet"
            # Get render info for first pixel
            first_pixel_info = "No render yet"
            if self._precomputed_colors is not None and self._precomputed_colors.shape[0] > 0:
                color = self._precomputed_colors[0, 0]
                first_pixel_info = f"[0,0]={color} -> #{color[0]:02x}{color[1]:02x}{color[2]:02x}"

            # Check what we're actually rendering
            render_check = "No render check"
            if hasattr(self, '_last_rendered_bg'):
                render_check = f"Last rendered bg: {self._last_rendered_bg}"

            debug_info = [
                f"CANVAS DEBUG: blur={self.blur} opacity={self.blend_opacity}",
                f"image_array: {img_shape}",
                f"precomputed: {precomp_shape}",
                f"region: {region_info}",
                f"overlay_color: {self.overlay_color}",
                f"first_pixel: {first_pixel_info}",
                f"render_check: {render_check}",
                f"last_info: {self._last_precompute_info[:60] if len(self._last_precompute_info) > 60 else self._last_precompute_info}"
            ]
            if y < len(debug_info):
                # Create debug strip
                segments = []
                for i, char in enumerate(debug_info[y]):
                    if i < self.size.width:
                        segments.append(Segment(char, RichStyle(color="yellow", bgcolor="red", bold=True)))
                # Fill rest with spaces
                for i in range(len(debug_info[y]), self.size.width):
                    segments.append(Segment(' ', RichStyle(bgcolor="red")))
                return Strip(segments)

        # No debug offset when debug is disabled
        actual_y = y

        # Just call parent's render_line and add connection lines
        strip = super().render_line(y)

        # Get our content
        width = self.size.width if self.size else 0
        content_lines = self.content.split('\n') if self.content else []

        if y < len(content_lines) and strip._segments:
            line = content_lines[y]
            segments = list(strip._segments)

            # Update only the connection characters
            for x in range(min(len(line), len(segments))):
                char = line[x]
                if char != ' ' and (x, y) in self._connection_metadata:
                    # Replace with colored connection character
                    metadata = self._connection_metadata[(x, y)]
                    color = metadata.get('color', 'white')
                    old_segment = segments[x]
                    # Keep the background, update the character and color
                    segments[x] = Segment(char, RichStyle(color=color, bgcolor=old_segment.style.bgcolor if old_segment.style else None))

            return Strip(segments)

        return strip

    def _draw_connection(self, grid, conn):
        """Draw a single connection on the grid."""
        px1, py1 = conn['start']
        px2, py2 = conn['end']
        style = conn.get('style', 'solid')

        chars = self._line_chars.get(style, self._line_chars['solid'])

        # Store connection metadata for rendering
        if not hasattr(self, '_connection_metadata'):
            self._connection_metadata = {}

        # Draw horizontal segment first (Manhattan routing)
        if px1 != px2:
            y = py1
            start_x = min(px1, px2)
            end_x = max(px1, px2)
            for x in range(start_x, end_x + 1):
                if 0 <= x < len(grid[0]) and 0 <= y < len(grid):
                    grid[y][x] = chars['horizontal']
                    # Store metadata for coloring
                    self._connection_metadata[(x, y)] = {
                        'color': conn.get('color', 'cyan'),
                        'opacity': conn.get('opacity', 0.3)
                    }

        # Draw vertical segment
        if py1 != py2:
            x = px2
            start_y = min(py1, py2)
            end_y = max(py1, py2)
            for y in range(start_y, end_y + 1):
                if 0 <= x < len(grid[0]) and 0 <= y < len(grid):
                    # Use corner character at the intersection
                    if y == py1 and px1 != px2:
                        grid[y][x] = chars['corner']
                    else:
                        grid[y][x] = chars['vertical']
                    # Store metadata for coloring
                    self._connection_metadata[(x, y)] = {
                        'color': conn.get('color', 'cyan'),
                        'opacity': conn.get('opacity', 0.3)
                    }

# ==============================================================================
# GLASS LINE SEGMENT - Connection lines between widgets
# ==============================================================================

class GlassLineSegment(BlazingFastBlendWidget):
    """A single line segment for connecting widgets with glass morphism."""

    def __init__(self,
                 direction: str = 'horizontal',
                 line_style: str = 'solid',
                 **kwargs):
        """
        Initialize a line segment.

        Args:
            direction: 'horizontal' or 'vertical'
            line_style: 'solid', 'dashed', 'dotted', 'double'
            **kwargs: Standard widget parameters
        """
        self.direction = direction
        self.line_style = line_style

        # Line characters based on style
        self._line_chars = {
            'solid': {'horizontal': '─', 'vertical': '│', 'corner': '┼'},
            'double': {'horizontal': '═', 'vertical': '║', 'corner': '╬'},
            'thick': {'horizontal': '━', 'vertical': '┃', 'corner': '╋'},
            'block': {'horizontal': '█', 'vertical': '█', 'corner': '█'},
            'dashed': {'horizontal': '╌', 'vertical': '╎', 'corner': '┼'},
            'dotted': {'horizontal': '┄', 'vertical': '┆', 'corner': '┼'}
        }

        # Extract content if provided in kwargs, otherwise use empty
        initial_content = kwargs.pop('content', "")
        self._custom_content = bool(initial_content)  # Track if custom content was provided
        
        # Initialize with provided or empty content
        super().__init__(content=initial_content, **kwargs)

    def on_mount(self):
        """Update content when dimensions are known."""
        self._update_content()

    def on_resize(self, event):
        """Update content when resized."""
        self._update_content()

    def _update_content(self):
        """Update the content based on current dimensions."""
        # Don't update if custom content was provided
        if self._custom_content:
            return
            
        if not self.size:
            return

        width = self.size.width
        height = self.size.height

        # Get appropriate character
        chars = self._line_chars.get(self.line_style, self._line_chars['solid'])
        char = chars['horizontal'] if self.direction == 'horizontal' else chars['vertical']

        # Special handling for block style - use half blocks for thinner lines
        if self.line_style == 'block' and self.direction == 'horizontal':
            # Use upper half block for horizontal lines to make them thinner
            char = '▀'


        # Build content lines
        lines = []
        for y in range(height):
            if self.direction == 'vertical':
                # For vertical lines, only render the character on x=0
                line = char + ' ' * (width - 1) if width > 0 else ''
            else:
                # For horizontal lines, fill the width
                line = char * width
            lines.append(line)

        # Update content
        self.content = '\n'.join(lines)


# ==============================================================================
# GLASS PANEL - Bordered widget with title
# ==============================================================================

class GlassPanel(BlazingFastBlendWidget):
    """Panel widget with title and border"""

    def __init__(self, title: str = "", content: Union[str, List[str]] = "",
                 border: bool = True, show_title: bool = True, padding: int = 0, **kwargs):
        # Convert content list to string
        if isinstance(content, list):
            content_str = '\n'.join(content)
        else:
            content_str = content

        # Pass padding to base class
        super().__init__(content=content_str, padding=padding, **kwargs)
        self._title = title
        self.border = border
        self.show_title = show_title
        self._content_lines = content if isinstance(content, list) else content.split('\n')

        # CSS merge properties for border and title
        self._border_css = {}
        self._title_css = {}

        # Direct color properties
        self._title_color = None
        self._border_color = None

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        self._title = value
        self.refresh()

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, value):
        self._content = value
        if isinstance(value, list):
            self._content_lines = value
        else:
            self._content_lines = value.split('\n')
        self.refresh()


    def render_line(self, y: int) -> Strip:
        """Render panel with border and glass effect"""
        # Get glass background first
        if self.region and self._image_array is not None:
            self._precompute_colors()

        width = self.size.width
        height = self.size.height
        segments = []

        # Determine line content
        if not self.border:
            # No border
            # Check if we should show title on first line
            if y == 0 and self._title and self.show_title:
                # Show title without border
                title_display = self._title
                if len(title_display) > width:
                    title_display = title_display[:width]
                text = title_display.center(width)
            # Check if we're in padding area
            elif y < self._padding + (1 if self._title and self.show_title else 0) or y >= height - self._padding:
                # Top or bottom padding
                text = ""
            else:
                # Content area (adjust for title if shown)
                content_y = y - self._padding - (1 if self._title and self.show_title else 0)
                if content_y < len(self._content_lines):
                    inner_text = self._content_lines[content_y]
                    # Apply horizontal padding
                    max_width = width - (2 * self._padding)
                    if max_width > 0:
                        if len(inner_text) > max_width:
                            inner_text = inner_text[:max_width]
                        # Center with padding on sides
                        text = " " * self._padding + inner_text.center(max_width) + " " * self._padding
                    else:
                        text = ""
                else:
                    text = ""
        else:
            # With border
            if y == 0:
                # Top border with title
                if self._title and self.show_title:
                    title_display = f" {self._title} "
                    padding = max(0, width - len(title_display) - 2)
                    left_pad = padding // 2
                    right_pad = padding - left_pad
                    text = "┌" + "─" * left_pad + title_display + "─" * right_pad + "┐"
                else:
                    text = "┌" + "─" * (width - 2) + "┐"
            elif y == height - 1:
                # Bottom border
                text = "└" + "─" * (width - 2) + "┘"
            else:
                # Check if we're in padding area
                if y <= self._padding or y >= height - self._padding - 1:
                    # Top or bottom padding rows - empty with side borders
                    text = "│" + " " * (width - 2) + "│"
                else:
                    # Content area with side borders
                    content_y = y - 1 - self._padding  # Adjust for both border and padding
                    if content_y < len(self._content_lines):
                        inner_text = self._content_lines[content_y]
                        # Account for side borders (2 chars) + spaces (2 chars) + padding
                        max_width = width - 4 - (2 * self._padding)
                        if max_width > 0:
                            if len(inner_text) > max_width:
                                inner_text = inner_text[:max_width]
                            # Add padding spaces inside the borders
                            padding_str = " " * self._padding
                            text = f"│ {padding_str}{inner_text.ljust(max_width)}{padding_str} │"
                        else:
                            text = "│" + " " * (width - 2) + "│"
                    else:
                        text = "│" + " " * (width - 2) + "│"

        # Render with glass background
        text = text[:width].ljust(width)  # Ensure correct width

        # Track if we're in the title area
        in_title = False
        title_start = -1
        title_end = -1
        if self.border and y == 0 and self._title and self.show_title:
            # Find title boundaries
            title_display = f" {self._title} "
            title_start = text.find(title_display)
            if title_start >= 0:
                title_end = title_start + len(title_display)

        for x in range(width):
            char = text[x]

            # Get background color - convert on demand
            if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                color = self._precomputed_colors[y, x]
                bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            else:
                bg_hex = self.overlay_color

            # Determine if this character is part of border, title, or content
            is_border_char = False
            is_title_char = False

            if self.border:
                if y == 0 or y == height - 1:
                    # Top or bottom border
                    if char in '┌┐└┘─':
                        is_border_char = True
                    elif title_start <= x < title_end:
                        is_title_char = True
                elif char in '│':
                    # Side borders
                    is_border_char = True

            # Apply appropriate styling
            if is_title_char:
                # Apply title styling - use direct _title_color first, then CSS
                text_color = self._title_color or self._title_css.get('color', 'white')
                text_style = self._title_css.get('text_style', '')
                style_kwargs = {'bgcolor': bg_hex, 'color': text_color}
                if 'bold' in text_style:
                    style_kwargs['bold'] = True
                if 'italic' in text_style:
                    style_kwargs['italic'] = True
                style = RichStyle(**style_kwargs)
            elif is_border_char:
                # Apply border styling - use direct _border_color first, then CSS
                border_color = self._border_color or self._border_css.get('color', 'white')
                border_style = self._border_css.get('text_style', '')
                style_kwargs = {'bgcolor': bg_hex, 'color': border_color}
                if 'bold' in border_style:
                    style_kwargs['bold'] = True
                style = RichStyle(**style_kwargs)
            elif char != ' ' or self.border:
                # Default styling - also check if this is title without border
                if not self.border and y == 0 and self._title and self.show_title:
                    # Title without border - use title color
                    text_color = self._title_color or self._title_css.get('color', 'white')
                    text_style = self._title_css.get('text_style', '')
                    style_kwargs = {'bgcolor': bg_hex, 'color': text_color}
                    if 'bold' in text_style:
                        style_kwargs['bold'] = True
                    if 'italic' in text_style:
                        style_kwargs['italic'] = True
                    style = RichStyle(**style_kwargs)
                else:
                    # Regular content
                    style = RichStyle(bgcolor=bg_hex, color="white", bold=(y == 0 and self.border))
            else:
                style = RichStyle(bgcolor=bg_hex)

            segments.append(Segment(char, style))

        return Strip(segments)


# ==============================================================================
# ABSOLUTE POSITIONING SYSTEM
# ==============================================================================

class AbsoluteGlassMixin:
    """Mixin to add absolute positioning to glass widgets"""

    # Absolute positioning properties
    abs_x = reactive(0)
    abs_y = reactive(0)
    abs_width = reactive("30")
    abs_height = reactive("10")
    sticky_x = reactive(None)
    sticky_y = reactive(None)
    z_index = reactive(0)

    def __init__(self, *args, **kwargs):
        # Initialize pages first
        self.pages = set()
        # Extract positioning params
        x = kwargs.pop('x', 0)
        y = kwargs.pop('y', 0)
        width = str(kwargs.pop('width', 30))
        height = str(kwargs.pop('height', 10))
        sticky_x = kwargs.pop('sticky_x', None)
        sticky_y = kwargs.pop('sticky_y', None)
        z_index = kwargs.pop('z_index', 0)
        pages = kwargs.pop('pages', None)

        # ID is handled by parent class, don't pop it
        # blur is also handled by parent class, don't pop it

        # Call parent init
        super().__init__(*args, **kwargs)

        # Set positioning after init
        self.abs_x = x
        self.abs_y = y
        self.abs_width = width
        self.abs_height = height
        self.sticky_x = sticky_x
        self.sticky_y = sticky_y
        self.z_index = z_index
        self.pages = set(pages) if pages else set(["default"])

    def calculate_position(self, container_width: int, container_height: int) -> Tuple[int, int, int, int]:
        """Calculate absolute position and size"""
        # Calculate dimensions
        width = self._calculate_dimension(self.abs_width, container_width)
        height = self._calculate_dimension(self.abs_height, container_height)

        # Start with absolute position
        x = self.abs_x
        y = self.abs_y

        # Apply sticky positioning
        if self.sticky_x == "right":
            x = container_width - width - self.abs_x
        elif self.sticky_x == "center":
            x = (container_width - width) // 2 + self.abs_x

        if self.sticky_y == "bottom":
            y = container_height - height - self.abs_y
        elif self.sticky_y == "center":
            y = (container_height - height) // 2 + self.abs_y

        # Clamp to bounds
        x = max(0, min(x, container_width - 1))
        y = max(0, min(y, container_height - 1))
        width = min(width, container_width - x)
        height = min(height, container_height - y)

        return x, y, width, height

    def _calculate_dimension(self, value: str, container_size: int) -> int:
        """Calculate actual dimension from percentage or absolute value"""
        if value.endswith('%'):
            percentage = float(value[:-1]) / 100.0
            return max(1, int(container_size * percentage))
        return max(1, int(value))


class AbsoluteGlassWidget(AbsoluteGlassMixin, BlazingFastBlendWidget):
    """Glass widget with absolute positioning"""
    pass


class AbsoluteGlassLineSegment(AbsoluteGlassMixin, GlassLineSegment):
    """Line segment with absolute positioning for widget connections"""
    pass


class AbsoluteGlassPanel(AbsoluteGlassMixin, GlassPanel):
    """Glass panel with absolute positioning"""
    pass


class AbsoluteGlassConnectionCanvas(AbsoluteGlassMixin, GlassConnectionCanvas):
    """Absolute positioned connection canvas."""
    pass


# ==============================================================================
# LOOKING GLASS APP - Main application class
# ==============================================================================

class LookingGlassApp(App):
    """Main app with glass system and absolute positioning"""

    CSS = """
    Screen {
        layers: background shadow overlay;
        overflow: hidden;
        scrollbar-size: 0 0;
    }

    #background {
        layer: background;
        width: 100%;
        height: 100%;
        background: transparent;
        padding: 0;
        margin: 0;
        border: none;
        overflow: hidden;
    }

    .blend-widget {
        layer: overlay;
        border: none;
        outline: none;
        padding: 0;
        margin: 0;
        background: transparent;
        overflow: hidden;
    }
    """

    def __init__(self, background_darken: float = 0.0):
        super().__init__()
        self.background_darken = background_darken
        self._image_array = None
        self._absolute_widgets: List[Union[AbsoluteGlassWidget, AbsoluteGlassPanel]] = []
        self._compose_order: List[Union[AbsoluteGlassWidget, AbsoluteGlassPanel]] = []
        self._initial_positions_set = False
        self._is_resizing = False
        self._last_size = (0, 0)
        self._background_path = None
        self._current_page = "default"

        # Image transition system - DISABLED for performance
        self._current_background_image = None
        self._enable_transitions = False  # DISABLED
        self._transition_duration = 3.5
        self._transition_pattern = 'wave'
        self._transition_easing = 'smoothstep'
        self._transition_timer = None

        # Data-driven widget definitions
        self.widget_definitions = []

        # Simple color transition support for testing
        self._simple_color_transition = None
        self._current_solid_color = None

        # Store target image for high-quality final frame
        self._transition_target_image = None

        # Transition frame cache for performance
        self._transition_cache = {}  # (img1_hash, img2_hash, settings) -> [cached_frames]
        self._cache_playback_active = False
        self._cache_playback_frames = []
        self._cache_playback_index = 0

        # ANSI conversion cache - this is the real performance win!
        self._ansi_cache = {}  # image_hash -> ansi_string
        self._ansi_cache_hits = 0
        self._ansi_cache_misses = 0

    def define_widget(self, widget_def: dict):
        """Add a widget definition to the data-driven system"""
        self.widget_definitions.append(widget_def)

    def define_widgets(self, widget_defs: List[dict]):
        """Add multiple widget definitions"""
        self.widget_definitions.extend(widget_defs)

    def compose(self) -> ComposeResult:
        """Data-driven compose that creates widgets from definitions"""
        # Always yield background first
        yield UltraFastTrueColorBackground(id="background")

        # Sort widget definitions by Y coordinate for consistent ordering
        sorted_defs = sorted(self.widget_definitions, key=lambda w: (w.get('y', 0), w.get('x', 0)))

        # Create and yield widgets from definitions
        for widget_def in sorted_defs:
            widget = self._create_widget_from_definition(widget_def)
            if widget:
                yield widget

    def _create_widget_from_definition(self, definition: dict):
        """Create a widget from a data definition"""
        widget_type = definition.get('type', 'widget')

        # Common parameters
        params = {
            'x': definition.get('x', 0),
            'y': definition.get('y', 0),
            'width': definition.get('width', 30),
            'height': definition.get('height', 10),
            'sticky_x': definition.get('sticky_x'),
            'sticky_y': definition.get('sticky_y'),
            'z_index': definition.get('z_index', 0),
            'overlay_color': definition.get('overlay_color', 'blue'),
            'blend_opacity': definition.get('blend_opacity', 0.5),
            'darken_factor': definition.get('darken_factor', 0.0)
        }

        # Add ID to params if provided
        if 'id' in definition:
            params['id'] = definition['id']

        # Create appropriate widget type
        if widget_type == 'panel':
            widget = AbsoluteGlassPanel(
                title=definition.get('title', ''),
                content=definition.get('content', ''),
                border=definition.get('border', True),
                **params
            )
        else:  # Default to basic widget
            widget = AbsoluteGlassWidget(
                content=definition.get('content', ''),
                **params
            )

        # Add to tracking
        self.add_absolute_widget(widget, definition.get('id'))

        return widget

    def add_absolute_widget(
        self,
        widget: Union[AbsoluteGlassWidget, AbsoluteGlassPanel],
        widget_id: Optional[str] = None
    ):
        """Register an absolute widget"""
        widget.classes = "blend-widget"
        # Don't set ID - it should already be set in the widget constructor
        self._absolute_widgets.append(widget)
        self._compose_order.append(widget)
        return widget

    def on_mount(self):
        """Set initial positions after mount"""
        self.load_background()
        # Sort by z-index before initial positioning
        self._absolute_widgets.sort(key=lambda w: w.z_index)
        self._update_all_positions()
        self._initial_positions_set = True

        # Initialize transition timer (will be started when needed)
        self._transition_timer = None

        # Set up periodic garbage collection to maintain performance
        import gc
        gc.collect()  # Clean start
        self.set_interval(30.0, self._periodic_maintenance)  # Every 30 seconds

    def on_resize(self, event):
        """Handle terminal resize by reloading the background"""
        # Only reload if size actually changed
        new_size = (self.size.width, self.size.height)
        if new_size == self._last_size or new_size[0] < 10 or new_size[1] < 10:
            return

        self._last_size = new_size

        # Reload background with new dimensions (no transition on resize)
        self.load_background(self._background_path, use_transition=False)

        # Update positions if initialized
        if self._initial_positions_set:
            self._update_all_positions()

    def _update_all_positions(self):
        """Update all widget positions"""
        if not self.size:
            return

        # First pass: calculate true positions for all widgets
        widget_positions = {}
        for widget in self._absolute_widgets:
            x, y, width, height = widget.calculate_position(self.size.width, self.size.height)
            widget_positions[widget] = (x, y, width, height)

        # Sort by z-index for render order
        self._absolute_widgets.sort(key=lambda w: w.z_index)

        # Second pass: apply positions
        # Track where Textual is placing widgets (cumulative)
        textual_y = 0

        for i, widget in enumerate(self._compose_order):
            if widget in widget_positions:
                x, y, width, height = widget_positions[widget]

                # Calculate offset: where we want it - where Textual put it
                offset_y = y - textual_y
                widget.styles.offset = (x, offset_y)

                widget.styles.width = width
                widget.styles.height = height

                # Update where Textual will place the next widget
                # Remove the +1 margin adjustment that was pushing things up
                textual_y += height  # No more +1

                if hasattr(self, 'log'):
                    self.log(f"Widget {i} {getattr(widget, 'id', 'unknown')}: want y={y}, textual_y={textual_y-height}, offset=({x}, {offset_y})")

    def _fix_absolute_positions(self):
        """Fix widget positions after Textual has rendered them"""
        if not self._absolute_widgets:
            return

        # For each widget, check where Textual put it and adjust
        for widget in self._absolute_widgets:
            if hasattr(widget, 'region') and widget.region and hasattr(widget, '_desired_x'):
                # Get where we want the widget
                desired_x = widget._desired_x
                desired_y = widget._desired_y

                # Get where Textual actually put it (without any offset)
                actual_x = widget.region.x - widget.styles.offset.x
                actual_y = widget.region.y - widget.styles.offset.y

                # Calculate the offset needed
                offset_x = desired_x - actual_x
                offset_y = desired_y - actual_y

                # Apply the offset
                widget.styles.offset = (offset_x, offset_y)

                if hasattr(self, 'log'):
                    self.log(f"Post-render fix {getattr(widget, 'id', 'unknown')}: actual=({actual_x},{actual_y}), desired=({desired_x},{desired_y}), offset=({offset_x},{offset_y})")

    def _periodic_maintenance(self):
        """Periodic maintenance to maintain consistent FPS"""
        import gc

        # Run a quick generation 0 collection
        gc.collect(0)

        # Optional: Log cache sizes for monitoring
        if hasattr(self, 'debug_cache_stats') and self.debug_cache_stats:
            total_cache_items = 0
            for widget in self.query(".blend-widget"):
                if hasattr(widget, '_strip_cache'):
                    total_cache_items += len(widget._strip_cache)
                if hasattr(widget, '_style_cache'):
                    total_cache_items += len(widget._style_cache)

            print(f"[Cache Stats] Total items: {total_cache_items}")

    def _update_transitions(self):
        """Update active image transitions"""
        if not transition_manager.is_active():
            # Stop the timer if no active transition
            if hasattr(self, '_transition_timer') and self._transition_timer:
                self._transition_timer.stop()
                self._transition_timer = None
                print("🎬 Stopped transition update timer")

                # CRITICAL: Save recorded frames to cache
                if (hasattr(self, '_current_cache_key') and hasattr(self, '_recorded_frames') and
                    self._recorded_frames and len(self._recorded_frames) > 5):  # Only cache if we got decent frames
                    print(f"🎬 Saving {len(self._recorded_frames)} frames to transition cache")
                    self._transition_cache[self._current_cache_key] = self._recorded_frames.copy()
                    # Limit cache size
                    if len(self._transition_cache) > 10:  # Keep last 10 transitions
                        oldest_key = next(iter(self._transition_cache))
                        del self._transition_cache[oldest_key]
                        print(f"🎬 Cache limit reached, removed oldest transition")

                # CRITICAL: Process the final high-quality image when transition completes
                if hasattr(self, '_transition_target_image') and self._transition_target_image:
                    print("🎬 Transition complete - switching to high-quality version")
                    # Process the original high-quality target image (no transition)
                    self._process_image(self._transition_target_image, use_transition=False)
                    self._transition_target_image = None

                # Restore normal caching behavior
                self._restore_normal_caches()
            return

        # Get current transition frame
        current_frame = transition_manager.update()

        if current_frame:
            # Clear caches before processing to ensure updates are visible
            self._bust_transition_caches()

            # Process the transition frame without creating another transition
            self._process_transition_frame(current_frame)

            # Force screen refresh to show the new frame
            #self.screen.refresh()

            # If we have a reactive render method, trigger it too
            if hasattr(self, 'render_ui'):
                self.call_after_refresh(self.render_ui)

    def _process_transition_frame(self, img: Image):
        """Process a single frame from an image transition"""
        import time
        import hashlib

        # Generate unique frame hash for vDOM invalidation
        frame_timestamp = str(time.time())
        frame_hash = hashlib.md5(frame_timestamp.encode()).hexdigest()[:8]

        # This is similar to _process_image but without transition logic
        term_width = self.size.width
        term_height = self.size.height

        # Resize for terminal - climage expects 2x height for proper aspect ratio
        char_height_ratio = 2.0
        effective_term_height = term_height * char_height_ratio

        scale_w = term_width / img.width
        scale_h = effective_term_height / img.height
        scale = max(scale_w, scale_h)

        scaled_width = int(img.width * scale)
        scaled_height = int(img.height * scale)

        resized = img.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

        # Crop
        crop_width = term_width
        crop_height = int(term_height * char_height_ratio)

        left = (scaled_width - crop_width) // 2
        top = (scaled_height - crop_height) // 2
        cropped = resized.crop((left, top, left + crop_width, top + crop_height))

        self._image_array = np.array(cropped)

        # Extract color palette from the cropped image (before darkening)
        self._extract_color_palette(cropped)

        # Apply darkening if requested
        display_img = cropped
        if self.background_darken > 0:
            darkened_array = self._image_array.astype(np.float32)
            darkened_array = darkened_array * (1 - self.background_darken)
            display_img = Image.fromarray(darkened_array.astype(np.uint8))

        # Generate ANSI using cached conversion (HUGE performance boost!)
        ansi_output = self._get_cached_ansi_or_convert(display_img, term_width)

        # Update background
        bg = self.query_one("#background", UltraFastTrueColorBackground)
        bg.update_ansi_ultra(ansi_output)

        # CRITICAL: Force background widget to have a new data_hash for vDOM detection
        if hasattr(bg, 'data_hash'):
            bg.data_hash = f"transition_frame_{frame_hash}"
        else:
            # Create the attribute if it doesn't exist
            bg.data_hash = f"transition_frame_{frame_hash}"

        # Share with all glass widgets AND force data_hash updates
        for widget in self.query(".blend-widget"):
            if hasattr(widget, 'set_image_data'):
                widget.set_image_data(self._image_array)

            # CRITICAL: Force each widget to have a new data_hash for vDOM detection
            if hasattr(widget, 'data_hash'):
                widget.data_hash = f"transition_frame_{frame_hash}"
            else:
                # Create the attribute if it doesn't exist
                widget.data_hash = f"transition_frame_{frame_hash}"

        # CRITICAL: Record this frame for caching (if we're recording)
        if (hasattr(self, '_recorded_frames') and hasattr(self, '_current_cache_key') and
            not getattr(self, '_cache_playback_active', False)):  # Don't record during playback
            frame_data = (ansi_output, self._image_array.copy())
            self._recorded_frames.append(frame_data)

            # Debug every 15th frame
            if len(self._recorded_frames) % 15 == 0:
                print(f"🎬 Recorded frame #{len(self._recorded_frames)} for caching")

        print(f"🎬 Processed transition frame with hash: {frame_hash}")

    def load_background(self, image_path: Optional[str] = None, use_transition: bool = True):
        """
        Load and process background image.

        Note: First image load will always be high-quality (no transition).
        Transitions only occur when switching between loaded images.
        """
        try:
            # Store the path for reloading on resize
            if image_path:
                self._background_path = image_path

            # CRITICAL: First image should never use transition - ensure high quality
            is_first_load = self._current_background_image is None
            if is_first_load:
                use_transition = False
                print("🎯 First background load - disabling transitions for high quality")

            # Check for background image
            if image_path and os.path.exists(image_path):
                with Image.open(image_path) as img:
                    self._process_image(img, use_transition=use_transition)
                self.notify(f"Loaded {image_path}")
            elif os.path.exists("background.png"):
                self._background_path = "background.png"
                with Image.open("background.png") as img:
                    self._process_image(img, use_transition=use_transition)
                self.notify("Loaded background.png")
            else:
                # Create test pattern
                self._background_path = None
                img = self._create_test_pattern()
                self._process_image(img, use_transition=use_transition)
                self.notify("No background found - using test pattern")

        except Exception as e:
            self.notify(f"Error loading background: {e}", severity="error")

    def _process_image(self, img: Image, use_transition: bool = True):
        """Process image for terminal display with optional transition"""
        term_width = self.size.width
        term_height = self.size.height

        # Store current size
        self._last_size = (term_width, term_height)

        # PERFORMANCE: Skip all transition logic when disabled
        if not self._enable_transitions:
            use_transition = False

        # Check if new image is solid color
        new_solid_color = self._is_solid_color_image(img) if use_transition else None

        # CRITICAL: First image should ALWAYS be high quality - no transitions on boot
        is_first_image = self._current_background_image is None

        if is_first_image:
            print("🎯 First image load - forcing high-quality processing (no transition)")
            use_transition = False

        # Check if we should create a transition
        if (use_transition and
            self._enable_transitions and
            self._current_background_image is not None and
            transition_manager is not None):

            transition_start_time = time.time()

                        # Try simple color transition first for solid colors
            if new_solid_color is not None and self._current_solid_color is not None:
                print(f"🎨 Using SIMPLE color transition: {self._current_solid_color} → {new_solid_color}")

                # CRITICAL: Store the target image for high-quality final processing
                self._transition_target_image = img.copy()

                # Create simple color transition
                self._simple_color_transition = SimpleColorTransition(
                    self._current_solid_color,
                    new_solid_color,
                    duration=self._transition_duration
                )

                # Start timer for simple transition updates
                if not hasattr(self, '_transition_timer') or self._transition_timer is None:
                    self._transition_timer = self.set_interval(1/40, self._update_simple_transition)
                    setup_time = (time.time() - transition_start_time) * 1000
                    print(f"🎨 Started simple transition timer (40 FPS) - setup took {setup_time:.1f}ms")

                # Update current solid color
                self._current_solid_color = new_solid_color
                return

            # Fall back to complex image transition

            # Check if we have this transition cached
            cache_key = self._generate_transition_cache_key(self._current_background_image, img)
            if cache_key in self._transition_cache:
                print(f"🎬 Using CACHED transition frames! ({len(self._transition_cache[cache_key])} frames)")

                # CRITICAL: Store the target image for high-quality final processing
                self._transition_target_image = img.copy()

                # Start cached playback
                self._cache_playback_active = True
                self._cache_playback_frames = self._transition_cache[cache_key].copy()
                self._cache_playback_index = 0

                # Start playback timer
                if not hasattr(self, '_transition_timer') or self._transition_timer is None:
                    self._transition_timer = self.set_interval(1/40, self._update_cached_transition)
                    #self._transition_timer = self.set_interval(0.016, self._update_cached_transition)
                    setup_time = (time.time() - transition_start_time) * 1000
                    print(f"🎬 Started cached playback timer (40 FPS) - setup took {setup_time:.1f}ms")

                # Store new image for next transition
                self._current_background_image = img.copy()
                return

            print(f"🎬 Starting NEW image transition ({self._transition_pattern}, {self._transition_duration}s)")

            # CRITICAL: Store the target image for high-quality final processing
            self._transition_target_image = img.copy()

            # Start transition from current to new image
            create_transition(
                self._current_background_image,
                img,
                duration=self._transition_duration,
                pattern=self._transition_pattern,
                easing=self._transition_easing
            )

            # Prepare to record frames for caching
            self._current_cache_key = cache_key
            self._recorded_frames = []

            # Store new image for next transition
            self._current_background_image = img.copy()

            # Start transition update timer (40 FPS for smooth animation)
            if not hasattr(self, '_transition_timer') or self._transition_timer is None:
                self._transition_timer = self.set_interval(1/40, self._update_transitions)
                #self._transition_timer = self.set_interval(0.016, self._update_transitions)
                setup_time = (time.time() - transition_start_time) * 1000
                print(f"🎬 Started transition update timer (40 FPS) - setup took {setup_time:.1f}ms")

            # Clear all caches to ensure updates are visible
            self._bust_transition_caches()

            # Don't process the image immediately - let the transition handle it
            return

                # Store current image for future transitions
        self._current_background_image = img.copy()

        # Store solid color if detected
        if new_solid_color:
            self._current_solid_color = new_solid_color
            print(f"🎨 Detected solid color: {new_solid_color}")
        else:
            self._current_solid_color = None

        # CRITICAL: Ensure first/non-transition images get high-quality processing
        if is_first_image:
            print(f"🎯 Processing FIRST image at full quality (no transition)")
        else:
            print(f"🎯 Processing image at full quality (no transition)")
        # Continue with normal high-quality processing below...

        # Resize for terminal - climage expects 2x height for proper aspect ratio
        # This is because terminal characters are typically 2:1 (tall)
        char_height_ratio = 2.0
        effective_term_height = term_height * char_height_ratio

        scale_w = term_width / img.width
        scale_h = effective_term_height / img.height
        scale = max(scale_w, scale_h)

        scaled_width = int(img.width * scale)
        scaled_height = int(img.height * scale)

        resized = img.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

        # Crop
        crop_width = term_width
        crop_height = int(term_height * char_height_ratio)

        left = (scaled_width - crop_width) // 2
        top = (scaled_height - crop_height) // 2
        cropped = resized.crop((left, top, left + crop_width, top + crop_height))

        self._image_array = np.array(cropped)

        # Extract color palette from the cropped image (before darkening)
        self._extract_color_palette(cropped)

        # Apply darkening if requested
        display_img = cropped
        if self.background_darken > 0:
            darkened_array = self._image_array.astype(np.float32)
            darkened_array = darkened_array * (1 - self.background_darken)
            display_img = Image.fromarray(darkened_array.astype(np.uint8))

        # Generate ANSI using cached conversion (HUGE performance boost!)
        ansi_output = self._get_cached_ansi_or_convert(display_img, term_width)

        # Update background
        bg = self.query_one("#background", UltraFastTrueColorBackground)
        bg.update_ansi_ultra(ansi_output)

        # Share with all glass widgets
        for widget in self.query(".blend-widget"):
            if hasattr(widget, 'set_image_data'):
                widget.set_image_data(self._image_array)

    def _extract_color_palette(self, image: Image):
        """Extract color palette from background image for use by apps"""
        try:
            # Save image temporarily for ColorThief (it requires a file path)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp.name)
                tmp_path = tmp.name

            # Extract colors using ColorThief
            color_thief = ColorThief(tmp_path)

            # Get dominant color
            dominant_color = color_thief.get_color(quality=1)

            # Get color palette (6 colors should be enough)
            palette = color_thief.get_palette(color_count=6, quality=1)

            # Clean up temp file
            os.unlink(tmp_path)

            # Convert to hex and create comprehensive palette
            # Choose the brightest color from palette as accent for better "pop"
            accent_color = palette[0]  # Default to first palette color
            if len(palette) > 1:
                # Find brightest color based on luminance
                brightest_lum = 0
                for color in palette:
                    r, g, b = [x/255.0 for x in color]
                    # Calculate relative luminance
                    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    if lum > brightest_lum:
                        brightest_lum = lum
                        accent_color = color

            self.color_palette = {
                'dominant': self._rgb_to_hex(dominant_color),
                'palette': [self._rgb_to_hex(color) for color in palette],
                'complementary': self._get_complementary_color(dominant_color),
                'analogous': self._get_analogous_colors(dominant_color),
                'triadic': self._get_triadic_colors(dominant_color),
                'light_variants': [self._lighten_color(color, 0.3) for color in palette[:3]],
                'dark_variants': [self._darken_color(color, 0.3) for color in palette[:3]],
                # Accent-based colors for better contrast and "pop"
                'accent': self._rgb_to_hex(accent_color),
                'accent_complementary': self._get_complementary_color(accent_color),
                'accent_analogous': self._get_analogous_colors(accent_color),
                'accent_triadic': self._get_triadic_colors(accent_color),
                'accent_light': self._lighten_color(accent_color, 0.4),
                'accent_dark': self._darken_color(accent_color, 0.4),
            }

            # Store for easy access by apps
            if hasattr(self, 'state'):
                self.state['_color_palette'] = self.color_palette

        except Exception as e:
            # Fallback palette if extraction fails
            accent_fallback = (245, 166, 35)  # #f5a623
            self.color_palette = {
                'dominant': '#4a90e2',
                'palette': ['#4a90e2', '#7ed321', '#f5a623', '#d0021b', '#9013fe', '#50e3c2'],
                'complementary': '#e24a4a',
                'analogous': ['#4a90e2', '#4ae290', '#904ae2'],
                'triadic': ['#4a90e2', '#e24a90', '#90e24a'],
                'light_variants': ['#7da5e8', '#a1dc4c', '#f7b549'],
                'dark_variants': ['#356ba6', '#5ca218', '#c2891a'],
                # Accent-based colors
                'accent': '#f5a623',
                'accent_complementary': self._get_complementary_color(accent_fallback),
                'accent_analogous': self._get_analogous_colors(accent_fallback),
                'accent_triadic': self._get_triadic_colors(accent_fallback),
                'accent_light': self._lighten_color(accent_fallback, 0.4),
                'accent_dark': self._darken_color(accent_fallback, 0.4),
            }
            if hasattr(self, 'state'):
                self.state['_color_palette'] = self.color_palette

    def _rgb_to_hex(self, rgb_tuple):
        """Convert RGB tuple to hex string"""
        return rgb_to_hex(rgb_tuple)

    def _get_complementary_color(self, rgb_tuple):
        """Get complementary color on the color wheel"""
        r, g, b = [x/255.0 for x in rgb_tuple]
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        # Complementary is 180 degrees opposite
        comp_h = (h + 0.5) % 1.0
        comp_r, comp_g, comp_b = colorsys.hls_to_rgb(comp_h, l, s)

        return self._rgb_to_hex((int(comp_r*255), int(comp_g*255), int(comp_b*255)))

    def _get_analogous_colors(self, rgb_tuple):
        """Get analogous colors (neighbors on color wheel)"""
        r, g, b = [x/255.0 for x in rgb_tuple]
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        colors = []
        for offset in [-0.083, 0, 0.083]:  # -30°, 0°, +30°
            new_h = (h + offset) % 1.0
            new_r, new_g, new_b = colorsys.hls_to_rgb(new_h, l, s)
            colors.append(self._rgb_to_hex((int(new_r*255), int(new_g*255), int(new_b*255))))

        return colors

    def _get_triadic_colors(self, rgb_tuple):
        """Get triadic colors (120° apart on color wheel)"""
        r, g, b = [x/255.0 for x in rgb_tuple]
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        colors = []
        for offset in [0, 0.333, 0.667]:  # 0°, 120°, 240°
            new_h = (h + offset) % 1.0
            new_r, new_g, new_b = colorsys.hls_to_rgb(new_h, l, s)
            colors.append(self._rgb_to_hex((int(new_r*255), int(new_g*255), int(new_b*255))))

        return colors

    def _lighten_color(self, rgb_tuple, factor=0.3):
        """Lighten a color by mixing with white"""
        r, g, b = rgb_tuple
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return self._rgb_to_hex((r, g, b))

    def _darken_color(self, rgb_tuple, factor=0.3):
        """Darken a color by reducing luminance"""
        r, g, b = rgb_tuple
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return self._rgb_to_hex((r, g, b))

    def _create_test_pattern(self) -> Image:
        """Create a vibrant test pattern"""
        img = Image.new('RGB', (800, 600))
        pixels = img.load()

        for y in range(img.height):
            for x in range(img.width):
                r = int(128 + 127 * np.sin(x * 0.02))
                g = int(128 + 127 * np.sin(y * 0.02))
                b = int(128 + 127 * np.sin((x + y) * 0.02))
                pixels[x, y] = (r, g, b)

        return img


    def set_z_index(self, widget_id: str, z_index: int):
        """Update z-index value (visual change on next restart)"""
        for widget in self._absolute_widgets:
            if hasattr(widget, 'id') and widget.id == widget_id:
                widget.z_index = z_index
                self.notify(f"Z-index set to {z_index} (will apply on restart)")
                break

    def get_color_palette(self) -> dict:
        """
        Get the extracted color palette from the background image.

        Returns:
            Dict containing:
            - 'dominant': Main color from image
            - 'palette': List of 6 prominent colors
            - 'complementary': Complementary color to dominant
            - 'analogous': 3 analogous colors (neighbors on color wheel)
            - 'triadic': 3 triadic colors (120° apart)
            - 'light_variants': Lightened versions of top 3 colors
            - 'dark_variants': Darkened versions of top 3 colors
        """
        return getattr(self, 'color_palette', {
            'dominant': '#4a90e2',
            'palette': ['#4a90e2', '#7ed321', '#f5a623', '#d0021b', '#9013fe', '#50e3c2'],
            'complementary': '#e24a4a',
            'analogous': ['#4a90e2', '#4ae290', '#904ae2'],
            'triadic': ['#4a90e2', '#e24a90', '#90e24a'],
            'light_variants': ['#7da5e8', '#a1dc4c', '#f7b549'],
            'dark_variants': ['#356ba6', '#5ca218', '#c2891a'],
        })

    # ==============================================================================
    # IMAGE TRANSITION METHODS
    # ==============================================================================

    def set_transition_settings(self,
                               duration: float = 3.0,
                               pattern: str = 'linear',
                               easing: str = 'linear',
                               enabled: bool = True):
        """
        Configure image transition settings.

        Args:
            duration: Transition duration in seconds
            pattern: Transition pattern ('linear', 'wave', 'spiral', 'random')
            easing: Easing function ('linear', 'smoothstep', 'ease_in_out', 'bounce')
            enabled: Enable/disable transitions
        """
        self._transition_duration = duration
        self._transition_pattern = pattern
        self._transition_easing = easing
        self._enable_transitions = enabled

        print(f"🎬 Transition settings: {pattern} {duration}s {easing} (enabled: {enabled})")

    def switch_background(self, image_path: str):
        """
        Switch to a new background (no transition when disabled).

        Args:
            image_path: Path to new background image
        """
        if os.path.exists(image_path):
            # Use transition only if enabled
            self.load_background(image_path, use_transition=self._enable_transitions)
            print(f"🖼️  Switching to background: {image_path}")
        else:
            self.notify(f"Background not found: {image_path}", severity="error")

    def get_transition_progress(self) -> float:
        """Get progress of active transition (0.0 to 1.0)."""
        # Check simple color transition first
        if self._simple_color_transition:
            return self._simple_color_transition.get_progress()
        # Fall back to complex transition
        return transition_manager.get_progress() if transition_manager else 1.0

    def is_transition_active(self) -> bool:
        """Check if a transition is currently active."""
        # Check simple color transition first
        if self._simple_color_transition and not self._simple_color_transition.is_complete:
            return True
        # Fall back to complex transition
        return transition_manager.is_active() if transition_manager else False

    def _bust_transition_caches(self):
        """Clear all caches during transitions to ensure visual updates"""
        try:
            # Clear background-related caches
            if hasattr(self, '_image_array'):
                # Force image array to be considered "dirty"
                self._image_array = None

            # Clear color palette cache
            if hasattr(self, 'color_palette'):
                delattr(self, 'color_palette')

            # Clear all glass widget caches
            for widget in self.query(".blend-widget"):
                if hasattr(widget, '_clear_caches'):
                    widget._clear_caches()

                # Clear the critical precompute cache
                if hasattr(widget, '_last_precompute_visual_state'):
                    widget._last_precompute_visual_state = None
                if hasattr(widget, '_last_precomputed_region'):
                    widget._last_precomputed_region = None
                if hasattr(widget, '_last_precomputed_image_id'):
                    widget._last_precomputed_image_id = None

            # Clear any LRU caches
            if hasattr(BlazingFastBlendWidget, '_color_to_rgb'):
                BlazingFastBlendWidget._color_to_rgb.cache_clear()

            # Force widgets to consider themselves dirty
            for widget in self.query(".blend-widget"):
                if hasattr(widget, 'refresh'):
                    widget.refresh()

        except Exception as e:
            print(f"⚠️  Error busting transition caches: {e}")

    def _restore_normal_caches(self):
        """Restore normal caching behavior after transition completes"""
        try:
            # Just trigger a refresh to let normal caching resume
            for widget in self.query(".blend-widget"):
                if hasattr(widget, 'refresh'):
                    widget.refresh()

            print("🔄 Restored normal caching behavior")
        except Exception as e:
            print(f"⚠️  Error restoring normal caches: {e}")

    def _is_solid_color_image(self, img: Image) -> tuple:
        """
        Check if image is mostly solid color and return dominant color.
        Returns (r, g, b) if solid, None if complex image.
        """
        # Sample center 100x100 region
        center_x = img.width // 2
        center_y = img.height // 2
        sample_size = min(100, img.width // 2, img.height // 2)

        if sample_size < 10:
            return None

        # Get center region
        left = center_x - sample_size // 2
        top = center_y - sample_size // 2
        right = left + sample_size
        bottom = top + sample_size

        sample = img.crop((left, top, right, bottom))
        pixels = list(sample.getdata())

        if not pixels:
            return None

        # Check if all pixels are very similar
        first_pixel = pixels[0][:3]  # RGB only

        # Count pixels within small tolerance
        tolerance = 20
        similar_count = 0

        for pixel in pixels:
            r, g, b = pixel[:3]
            if (abs(r - first_pixel[0]) <= tolerance and
                abs(g - first_pixel[1]) <= tolerance and
                abs(b - first_pixel[2]) <= tolerance):
                similar_count += 1

        # If 80%+ pixels are similar, consider it solid
        if similar_count / len(pixels) > 0.8:
            return first_pixel

        return None

    def _generate_ansi_cache_key(self, img: Image, width: int) -> str:
        """Generate a fast cache key for ANSI conversion"""
        import hashlib

        # Sample key pixels for speed (corners + center)
        w, h = img.size
        try:
            # Get a few sample pixels to create a unique signature
            samples = [
                img.getpixel((0, 0)),           # Top-left
                img.getpixel((w-1, 0)),         # Top-right
                img.getpixel((0, h-1)),         # Bottom-left
                img.getpixel((w-1, h-1)),       # Bottom-right
                img.getpixel((w//2, h//2)),     # Center
                img.getpixel((w//4, h//4)),     # Quarter
                img.getpixel((3*w//4, 3*h//4)), # Three-quarter
            ]

            # Include image size and conversion width
            key_data = f"{samples}_{img.size}_{width}_truecolor"
            return hashlib.md5(key_data.encode()).hexdigest()[:12]

        except Exception:
            # Fallback: use image size and a simple hash
            return hashlib.md5(f"{img.size}_{width}_{id(img)}".encode()).hexdigest()[:12]

    def _get_cached_ansi_or_convert(self, img: Image, width: int) -> str:
        """Get ANSI from cache or convert and cache it"""
        cache_key = self._generate_ansi_cache_key(img, width)

        # # # Check cache first
        if cache_key in self._ansi_cache:
            self._ansi_cache_hits += 1
            if self._ansi_cache_hits % 10 == 0:  # Log every 10th hit
                print(f"🚀 ANSI cache hit #{self._ansi_cache_hits} (vs {self._ansi_cache_misses} misses)")
            return self._ansi_cache[cache_key]

        # Cache miss - do expensive conversion
        self._ansi_cache_misses += 1

        # Generate ANSI with climage (expensive!)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name

        ansi_output = climage.convert(
            tmp_path,
            is_unicode=True,
            is_truecolor=True,
            is_256color=False,
            is_16color=False,
            is_8color=False,
            width=width
        )

        os.unlink(tmp_path)

        # Store in cache
        self._ansi_cache[cache_key] = ansi_output

        # Limit cache size to prevent memory bloat
        if len(self._ansi_cache) > 200:  # Keep last 200 conversions
            # Remove oldest entry
            oldest_key = next(iter(self._ansi_cache))
            del self._ansi_cache[oldest_key]
            print(f"🧹 ANSI cache cleanup - removed oldest entry")

        print(f"💾 ANSI cache miss #{self._ansi_cache_misses} - converted and cached")
        return ansi_output

    def _generate_transition_cache_key(self, img1: Image, img2: Image) -> str:
        """Generate a cache key for a transition between two images"""
        import hashlib

        # Hash the first image (sample for speed)
        img1_small = img1.resize((50, 50), Image.Resampling.NEAREST)
        img1_bytes = img1_small.tobytes()
        img1_hash = hashlib.md5(img1_bytes).hexdigest()[:8]

        # Hash the second image
        img2_small = img2.resize((50, 50), Image.Resampling.NEAREST)
        img2_bytes = img2_small.tobytes()
        img2_hash = hashlib.md5(img2_bytes).hexdigest()[:8]

        # Include transition settings in key
        settings = f"{self._transition_duration}_{self._transition_pattern}_{self._transition_easing}"

        return f"{img1_hash}_to_{img2_hash}_{settings}"

    def _update_cached_transition(self):
        """Play back cached transition frames"""
        if not self._cache_playback_active or self._cache_playback_index >= len(self._cache_playback_frames):
            # Playback complete
            if hasattr(self, '_transition_timer') and self._transition_timer:
                self._transition_timer.stop()
                self._transition_timer = None
                print(f"🎬 Cached playback complete ({self._cache_playback_index} frames)")

                # Process final high-quality image
                if hasattr(self, '_transition_target_image') and self._transition_target_image:
                    print("🎬 Cached transition complete - switching to high-quality version")
                    self._process_image(self._transition_target_image, use_transition=False)
                    self._transition_target_image = None

                # Reset playback state
                self._cache_playback_active = False
                self._cache_playback_frames = []
                self._cache_playback_index = 0
            return

        # Get current cached frame
        cached_frame_data = self._cache_playback_frames[self._cache_playback_index]
        self._cache_playback_index += 1

        # Apply the cached frame
        self._apply_cached_frame(cached_frame_data)

    def _apply_cached_frame(self, frame_data):
        """Apply a cached frame to the display"""
        # Frame data contains the processed ANSI and image array
        ansi_output, image_array = frame_data

        # Generate unique frame hash for vDOM
        import hashlib
        frame_hash = hashlib.md5(f"cached_{self._cache_playback_index}".encode()).hexdigest()[:8]

        # Update background
        bg = self.query_one("#background", UltraFastTrueColorBackground)
        bg.update_ansi_ultra(ansi_output)
        bg.data_hash = f"cached_frame_{frame_hash}"

        # Update image data for glass widgets
        self._image_array = image_array
        for widget in self.query(".blend-widget"):
            if hasattr(widget, 'set_image_data'):
                widget.set_image_data(image_array)
            widget.data_hash = f"cached_frame_{frame_hash}"

        # Force refresh
        #self.screen.refresh()

    def _update_simple_transition(self):
        """Update simple color transitions (much cheaper than image transitions)"""
        if not self._simple_color_transition or self._simple_color_transition.is_complete:
            # Stop the timer if transition is complete
            if hasattr(self, '_transition_timer') and self._transition_timer:
                self._transition_timer.stop()
                self._transition_timer = None
                print("🎨 Stopped simple transition timer")

                # CRITICAL: Process the final high-quality image when simple transition completes
                if hasattr(self, '_transition_target_image') and self._transition_target_image:
                    print("🎨 Simple transition complete - switching to high-quality version")
                    # Process the original high-quality target image (no transition)
                    self._process_image(self._transition_target_image, use_transition=False)
                    self._transition_target_image = None

                self._simple_color_transition = None
            return

        # Get current color
        current_color = self._simple_color_transition.get_current_color()

        # Create a solid color image
        solid_img = Image.new('RGB', (400, 300), current_color)

        # Process this frame (no transition recursion since _simple_color_transition is active)
        self._process_simple_color_frame(solid_img)

    def _process_simple_color_frame(self, img: Image):
        """Process a simple solid color frame (cheaper than full image processing)"""
        import time
        import hashlib

        # Generate unique frame hash for vDOM invalidation
        frame_timestamp = str(time.time())
        frame_hash = hashlib.md5(frame_timestamp.encode()).hexdigest()[:8]

        # Simplified processing for solid colors
        term_width = self.size.width
        term_height = self.size.height

        # Just use the image as-is (it's already small and solid color)
        self._image_array = np.array(img)

        # Extract color palette (will be simple since it's solid)
        self._extract_color_palette(img)

        # Apply darkening if requested
        display_img = img
        if self.background_darken > 0:
            darkened_array = self._image_array.astype(np.float32)
            darkened_array = darkened_array * (1 - self.background_darken)
            display_img = Image.fromarray(darkened_array.astype(np.uint8))

        # Generate ANSI using cached conversion - resize to terminal size for efficiency
        resized = display_img.resize((term_width, term_height * 2), Image.Resampling.NEAREST)
        ansi_output = self._get_cached_ansi_or_convert(resized, term_width)

        # Update background
        bg = self.query_one("#background", UltraFastTrueColorBackground)
        bg.update_ansi_ultra(ansi_output)

        # Force background widget to have a new data_hash for vDOM detection
        bg.data_hash = f"simple_transition_{frame_hash}"

        # Share with all glass widgets AND force data_hash updates
        for widget in self.query(".blend-widget"):
            if hasattr(widget, 'set_image_data'):
                widget.set_image_data(self._image_array)

            # Force each widget to have a new data_hash for vDOM detection
            widget.data_hash = f"simple_transition_{frame_hash}"

        # Force screen refresh
        #self.screen.refresh()

        print(f"🎨 Simple transition frame: {frame_hash}")


# ==============================================================================
# FACTORY FUNCTIONS
# ==============================================================================

def glass_widget(
    content: str,
    x: int = 0,
    y: int = 0,
    width: SizeValue = 30,
    height: SizeValue = 10,
    z_index: int = 0,
    pages: Optional[List[str]] = None,
    sticky_x: Optional[EdgeSticky] = None,
    sticky_y: Optional[EdgeSticky] = None,
    **kwargs
) -> AbsoluteGlassWidget:
    """Create an absolutely positioned glass widget"""
    return AbsoluteGlassWidget(
        content=content,
        x=x, y=y,
        width=width, height=height,
        z_index=z_index,
        pages=pages,
        sticky_x=sticky_x, sticky_y=sticky_y,
        **kwargs
    )


def glass_panel(
    title: str,
    content: Union[str, List[str]],
    x: int = 0,
    y: int = 0,
    width: SizeValue = 30,
    height: SizeValue = 10,
    z_index: int = 0,
    pages: Optional[List[str]] = None,
    sticky_x: Optional[EdgeSticky] = None,
    sticky_y: Optional[EdgeSticky] = None,
    **kwargs
) -> AbsoluteGlassPanel:
    """Create an absolutely positioned glass panel"""
    return AbsoluteGlassPanel(
        title=title,
        content=content,
        x=x, y=y,
        width=width, height=height,
        z_index=z_index,
        pages=pages,
        sticky_x=sticky_x, sticky_y=sticky_y,
        **kwargs
    )