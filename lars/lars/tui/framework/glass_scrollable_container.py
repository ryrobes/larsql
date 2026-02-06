#!/usr/bin/env python3
"""
Glass Scrollable Container - Scrollable container with glass morphism effects
===========================================================================

This module provides a scrollable container that maintains glass transparency
while allowing content to scroll within it.
"""

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, VerticalScroll, HorizontalScroll
from textual.widget import Widget
from .looking_glass import AbsoluteGlassPanel, AbsoluteGlassMixin
from typing import Dict, List, Union, Optional, Any
from rich.text import Text
from rich.console import Group
from rich.align import Align
from rich.panel import Panel
from textual.strip import Strip, Segment
from textual.geometry import Region
from rich.style import Style as RichStyle


class GlassScrollableContainer(AbsoluteGlassPanel):
    """
    A scrollable container with glass morphism effects.
    
    This container allows content to scroll while maintaining
    the glass transparency effect.
    """
    
    def __init__(
        self,
        content_lines: Optional[List[str]] = None,
        scroll_x: bool = False,
        scroll_y: bool = True,
        *args,
        **kwargs
    ):
        """
        Initialize the scrollable glass container.
        
        Args:
            content_lines: List of content lines to display
            scroll_x: Enable horizontal scrolling
            scroll_y: Enable vertical scrolling
            *args, **kwargs: Passed to AbsoluteGlassPanel
        """
        self._content_lines = content_lines or []
        self._scroll_x = scroll_x
        self._scroll_y = scroll_y
        self._scroll_offset_y = 0
        self._scroll_offset_x = 0
        self._viewport_height = 0
        self._viewport_width = 0
        
        # Initialize with empty content - we'll render it ourselves
        super().__init__(content='', *args, **kwargs)
    
    def _update_viewport_dimensions(self):
        """Update viewport dimensions based on current size."""
        if hasattr(self, 'size') and self.size:
            if self.border:
                self._viewport_height = max(0, self.size.height - 4)  # Title, border top/bottom
                self._viewport_width = max(0, self.size.width - 2)   # Border left/right
            else:
                self._viewport_height = max(0, self.size.height)
                self._viewport_width = max(0, self.size.width)
    
    def update_content(self, content_lines: List[str]):
        """Update the scrollable content."""
        self._content_lines = content_lines
        self.refresh()
    
    def scroll_up(self, lines: int = 1):
        """Scroll content up."""
        if self._scroll_y:
            self._scroll_offset_y = max(0, self._scroll_offset_y - lines)
            self.refresh()
    
    def scroll_down(self, lines: int = 1):
        """Scroll content down."""
        if self._scroll_y:
            max_scroll = max(0, len(self._content_lines) - self._viewport_height)
            self._scroll_offset_y = min(max_scroll, self._scroll_offset_y + lines)
            self.refresh()
    
    def scroll_to_top(self):
        """Scroll to the top."""
        self._scroll_offset_y = 0
        self.refresh()
    
    def scroll_to_bottom(self):
        """Scroll to the bottom."""
        if self._scroll_y:
            self._scroll_offset_y = max(0, len(self._content_lines) - self._viewport_height)
            self.refresh()
    
    def render_line(self, y: int) -> Strip:
        """Override to render scrollable content with glass effect."""
        # Update viewport dimensions if needed
        self._update_viewport_dimensions()
        
        # First handle title and border as normal
        if self.border:
            # Title line
            if y == 0:
                return super().render_line(y)
            # Top border
            elif y == 1:
                return super().render_line(y)
            # Bottom border
            elif y == self.size.height - 1:
                return super().render_line(y)
            # Content area
            else:
                content_y = y - 2  # Adjust for title and top border
        else:
            content_y = y
        
        # Calculate which line of content to show
        content_index = content_y + self._scroll_offset_y
        
        # Prepare content line
        if content_index < len(self._content_lines):
            line_text = self._content_lines[content_index]
        else:
            line_text = ""
        
        # Handle horizontal scrolling if enabled
        if self._scroll_x and self._scroll_offset_x > 0:
            line_text = line_text[self._scroll_offset_x:]
        
        # Render with glass effect
        width = self.size.width - (2 if self.border else 0)
        segments = []
        
        # Add scroll indicators on the right edge
        show_scrollbar = self._scroll_y and len(self._content_lines) > self._viewport_height
        render_width = width
        if show_scrollbar:
            # Reserve last column for scrollbar
            render_width = width - 1
        
        # Ensure precomputed colors exist
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0]:
            for x in range(render_width):
                # Get character or space
                char = line_text[x] if x < len(line_text) else ' '
                
                # Get glass color
                actual_x = x + (1 if self.border else 0)
                if actual_x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, actual_x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                
                # Use Rich Style object
                style = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                segments.append(Segment(char, style))
        else:
            # Fallback rendering
            padded_text = line_text[:render_width].ljust(render_width)
            for char in padded_text:
                segments.append(Segment(char, f"bold white on {self.overlay_color}"))
        
        # Add scrollbar indicator if needed
        if show_scrollbar:
            # Calculate scrollbar position
            total_lines = len(self._content_lines)
            scrollbar_height = max(1, int(self._viewport_height * self._viewport_height / total_lines))
            scrollbar_pos = int(self._scroll_offset_y * self._viewport_height / total_lines)
            
            # Determine if this line should show the scrollbar
            is_scrollbar_line = content_y >= scrollbar_pos and content_y < scrollbar_pos + scrollbar_height
            
            # Get glass color for scrollbar position
            scrollbar_x = self.size.width - 1
            if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and scrollbar_x < self._precomputed_colors.shape[1]:
                color = self._precomputed_colors[y, scrollbar_x]
                bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            else:
                bg_hex = self.overlay_color
            
            # Create scrollbar character
            if is_scrollbar_line:
                # Scrollbar thumb
                style = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                segments.append(Segment("█", style))
            else:
                # Scrollbar track - use 'grey' or hex color
                style = RichStyle(bgcolor=bg_hex, color="#808080")
                segments.append(Segment("│", style))
        
        return Strip(segments)
    
    @property
    def can_scroll_up(self) -> bool:
        """Check if we can scroll up."""
        return self._scroll_y and self._scroll_offset_y > 0
    
    @property
    def can_scroll_down(self) -> bool:
        """Check if we can scroll down."""
        return self._scroll_y and self._scroll_offset_y < max(0, len(self._content_lines) - self._viewport_height)
    
    @property
    def scroll_position(self) -> tuple[int, int]:
        """Get current scroll position (x, y)."""
        return (self._scroll_offset_x, self._scroll_offset_y)