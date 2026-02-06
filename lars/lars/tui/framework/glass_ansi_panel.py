#!/usr/bin/env python3
"""
Glass ANSI Panel Widget - Simple ANSI rendering with glass effects
==================================================================

A minimal ANSI-aware panel widget that properly renders ANSI escape sequences.
Based on GlassPanel but with ANSI parsing capability.
"""

from typing import List, Union, Optional, Tuple
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
from .looking_glass import AbsoluteGlassMixin, BlazingFastBlendWidget
import re


class GlassAnsiPanel(AbsoluteGlassMixin, BlazingFastBlendWidget):
    """A glass panel that interprets ANSI escape sequences"""
    
    # ANSI code patterns
    ANSI_PATTERN = re.compile(r'(\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))')
    ANSI_SGR_PATTERN = re.compile(r'\x1B\[([0-9;]*)m')
    
    def __init__(self, 
                 content: Union[str, List[str]] = "",
                 title: str = "",
                 border: bool = True,
                 show_title: bool = True,
                 padding: int = 0,
                 **kwargs):
        """Initialize the ANSI panel"""
        # Convert content to list of lines
        if isinstance(content, str):
            content_lines = content.split('\n')
        else:
            content_lines = content
            
        # Initialize parent
        super().__init__(content="", padding=padding, **kwargs)
        
        self._content_lines = content_lines
        self._title = title
        self.border = border
        self.show_title = show_title
        
    @property
    def content(self):
        return '\n'.join(self._content_lines)
        
    @content.setter
    def content(self, value):
        if isinstance(value, list):
            self._content_lines = value
        else:
            self._content_lines = value.split('\n')
        self.refresh()
        
    def _parse_ansi_line(self, line: str) -> List[Tuple[str, Optional[RichStyle]]]:
        """Parse a line with ANSI codes into segments with styles"""
        segments = []
        current_style = RichStyle()
        
        # Split by ANSI codes
        parts = self.ANSI_PATTERN.split(line)
        
        for i, part in enumerate(parts):
            if i % 2 == 0:  # Text part
                if part:  # Skip empty strings
                    segments.append((part, current_style))
            else:  # ANSI code part
                # Parse SGR codes
                sgr_match = self.ANSI_SGR_PATTERN.match(part)
                if sgr_match:
                    params = sgr_match.group(1)
                    if not params or params == '0':  # Reset
                        current_style = RichStyle()
                    else:
                        # Parse parameters
                        codes = [int(x) for x in params.split(';') if x]
                        current_style = self._parse_sgr_codes(codes, current_style)
        
        return segments
    
    def _parse_sgr_codes(self, codes: List[int], base_style: RichStyle) -> RichStyle:
        """Parse SGR (Select Graphic Rendition) codes"""
        # Start with base style attributes - preserve existing values
        color = base_style.color if base_style.color else None
        bgcolor = None  # Ignore background colors to preserve glass effect
        bold = base_style.bold if base_style.bold else False
        italic = base_style.italic if base_style.italic else False
        underline = base_style.underline if base_style.underline else False
        
        i = 0
        while i < len(codes):
            code = codes[i]
            
            # Text attributes
            if code == 0:  # Reset
                return RichStyle()
            elif code == 1:  # Bold
                bold = True
            elif code == 3:  # Italic
                italic = True
            elif code == 4:  # Underline
                underline = True
            elif code == 22:  # Not bold
                bold = False
            elif code == 23:  # Not italic
                italic = False
            elif code == 24:  # Not underline
                underline = False
            
            # Foreground colors
            elif 30 <= code <= 37:  # Standard colors
                color_map = {
                    30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
                    34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white'
                }
                color = color_map[code]
            elif 90 <= code <= 97:  # Bright colors
                color_map = {
                    90: 'bright_black', 91: 'bright_red', 92: 'bright_green', 
                    93: 'bright_yellow', 94: 'bright_blue', 95: 'bright_magenta',
                    96: 'bright_cyan', 97: 'bright_white'
                }
                color = color_map[code]
            elif code == 38:  # Extended foreground color
                if i + 2 < len(codes) and codes[i + 1] == 5:  # 256 color
                    color = f"color({codes[i + 2]})"
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:  # RGB color
                    r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                    color = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            
            i += 1
        
        # Only set color if it was explicitly changed in this call
        # This preserves existing color when only attributes like bold are set
        if color is None and base_style.color:
            color = base_style.color
            
        return RichStyle(
            color=color,
            bgcolor=bgcolor,
            bold=bold,
            italic=italic,
            underline=underline
        )
    
    def render_line(self, y: int) -> Strip:
        """Render a line with ANSI code support"""
        # Get glass background first
        if self.region and self._image_array is not None:
            self._precompute_colors()
            
        width = self.size.width
        height = self.size.height
        segments = []
        
        # Handle border and content
        if not self.border:
            # No border - direct content
            if y < len(self._content_lines):
                line = self._content_lines[y]
                parsed_segments = self._parse_ansi_line(line)
                
                # Render parsed segments with glass effect
                x = 0
                for text, style in parsed_segments:
                    for char in text:
                        if x < width:
                            # Apply glass effect
                            if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                                glass_color = self._precomputed_colors[y, x]
                                bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                                combined_style = RichStyle(
                                    color=style.color,
                                    bgcolor=bg_color,
                                    bold=style.bold,
                                    italic=style.italic,
                                    underline=style.underline
                                )
                                segments.append(Segment(char, combined_style))
                            else:
                                segments.append(Segment(char, style))
                            x += 1
                
                # Pad remainder
                while x < width:
                    if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                        glass_color = self._precomputed_colors[y, x]
                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                        segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                    else:
                        segments.append(Segment(" ", RichStyle()))
                    x += 1
            else:
                # Empty line
                for x in range(width):
                    if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                        glass_color = self._precomputed_colors[y, x]
                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                        segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                    else:
                        segments.append(Segment(" ", RichStyle()))
        else:
            # With border - use parent's border rendering but parse content
            if y == 0:
                # Top border
                return super().render_line(y)
            elif y == height - 1:
                # Bottom border
                return super().render_line(y)
            else:
                # Content line with borders
                content_y = y - 1 - self._padding
                
                # Left border
                x = 0
                for char in "│ ":
                    if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                        glass_color = self._precomputed_colors[y, x]
                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                        segments.append(Segment(char, RichStyle(bgcolor=bg_color)))
                    else:
                        segments.append(Segment(char, RichStyle()))
                    x += 1
                
                # Add padding
                for _ in range(self._padding):
                    if x < width - 2:
                        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                            glass_color = self._precomputed_colors[y, x]
                            bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                            segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                        else:
                            segments.append(Segment(" ", RichStyle()))
                        x += 1
                
                # Content
                if 0 <= content_y < len(self._content_lines):
                    line = self._content_lines[content_y]
                    parsed_segments = self._parse_ansi_line(line)
                    
                    content_max_x = width - 2 - self._padding
                    for text, style in parsed_segments:
                        for char in text:
                            if x < content_max_x:
                                # Apply glass effect
                                if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                                    glass_color = self._precomputed_colors[y, x]
                                    bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                                    combined_style = RichStyle(
                                        color=style.color,
                                        bgcolor=bg_color,
                                        bold=style.bold,
                                        italic=style.italic,
                                        underline=style.underline
                                    )
                                    segments.append(Segment(char, combined_style))
                                else:
                                    segments.append(Segment(char, style))
                                x += 1
                
                # Fill to right border
                while x < width - 1:
                    if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                        glass_color = self._precomputed_colors[y, x]
                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                        segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                    else:
                        segments.append(Segment(" ", RichStyle()))
                    x += 1
                
                # Right border
                if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                    glass_color = self._precomputed_colors[y, x]
                    bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                    segments.append(Segment("│", RichStyle(bgcolor=bg_color)))
                else:
                    segments.append(Segment("│", RichStyle()))
        
        return Strip(segments)