#!/usr/bin/env python3
"""
Glass Plot Container with ANSI Color Support - Advanced Implementation
=====================================================================

This version properly handles ANSI codes by parsing them during rendering.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any, Tuple
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import re
import numpy as np


class GlassPlotextAnsi(AbsoluteGlassPanel):
    """
    Direct plotext rendering with proper ANSI color handling.
    
    This version overrides render_line to properly parse and apply ANSI codes.
    """
    
    # ANSI code patterns
    ANSI_PATTERN = re.compile(r'(\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))')
    ANSI_SGR_PATTERN = re.compile(r'\x1B\[([0-9;]*)m')
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """Initialize with plot data."""
        self._plot_data = plot_data or {}
        self._raw_lines = []
        self._has_ansi = False
        
        # Start with empty content
        super().__init__(content='Generating plot...', *args, **kwargs)
    
    def _parse_ansi_line(self, line: str) -> List[Tuple[str, Optional[RichStyle]]]:
        """
        Parse a line with ANSI codes into segments with styles.
        
        Returns:
            List of (text, style) tuples
        """
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
                        new_style = self._parse_sgr_codes(codes, current_style)
                        current_style = new_style
        
        return segments
    
    def _parse_sgr_codes(self, codes: List[int], base_style: RichStyle) -> RichStyle:
        """Parse SGR (Select Graphic Rendition) codes and create a new style."""
        # Start with base style attributes
        color = base_style.color
        bgcolor = None  # IGNORE background colors to preserve glass effect!
        bold = base_style.bold
        italic = base_style.italic
        underline = base_style.underline
        
        i = 0
        while i < len(codes):
            code = codes[i]
            
            # Text attributes
            if code == 0:  # Reset
                # Keep only foreground attributes on reset
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
            
            # Background colors - SKIP THESE!
            elif 40 <= code <= 47:  # Standard background colors
                # Ignore background colors to preserve glass effect
                pass
            elif code == 48:  # Extended background color
                # Skip the parameters
                if i + 2 < len(codes) and codes[i + 1] == 5:  # 256 color
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:  # RGB color
                    i += 4
            
            i += 1
        
        return RichStyle(
            color=color,
            bgcolor=bgcolor,  # Always None to preserve glass
            bold=bold,
            italic=italic,
            underline=underline
        )
    
    def _generate_plot(self):
        """Generate plot using plotext."""
        try:
            import plotext as plt
            
            # Clear any previous plot
            plt.clf()
            
            # Configure for string output
            width = self._plot_data.get('width', 40)
            height = self._plot_data.get('height', 10)
            plt.plotsize(width, height)
            
            # Use theme - 'dark' supports colors, we'll strip backgrounds in parsing
            theme = self._plot_data.get('theme', 'dark')
            plt.theme(theme)
            
            # Ensure no background fill
            plt.canvas_color('default')  # This should help avoid background fill
            
            # Get plot data
            plot_type = self._plot_data.get('type', 'bar')
            title = self._plot_data.get('title', 'Sample Chart')
            
            # Set colors if provided
            colors = self._plot_data.get('colors', None)
            
            # Create the plot based on type
            if plot_type == 'histogram':
                data = self._plot_data.get('data', [1, 2, 3, 4, 5])
                bins = self._plot_data.get('bins', 10)
                if data:
                    if colors:
                        plt.hist(data, bins=bins, color=colors)
                    else:
                        plt.hist(data, bins=bins)
            else:
                x_data = self._plot_data.get('x', [1, 2, 3, 4, 5])
                y_data = self._plot_data.get('y', [1, 4, 2, 5, 3])
                
                if plot_type == 'bar':
                    if colors:
                        plt.bar(x_data, y_data, color=colors)
                    else:
                        plt.bar(x_data, y_data)
                elif plot_type == 'line':
                    if colors:
                        plt.plot(x_data, y_data, color=colors)
                    else:
                        plt.plot(x_data, y_data)
                elif plot_type == 'scatter':
                    if colors:
                        plt.scatter(x_data, y_data, color=colors)
                    else:
                        plt.scatter(x_data, y_data)
            
            # Set labels
            plt.title(title)
            if 'xlabel' in self._plot_data:
                plt.xlabel(self._plot_data['xlabel'])
            if 'ylabel' in self._plot_data:
                plt.ylabel(self._plot_data['ylabel'])
            
            # Get the plot as string
            import io
            import sys
            
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            
            try:
                plt.show()
                plot_output = buffer.getvalue()
            finally:
                sys.stdout = old_stdout
            
            # Store raw lines with ANSI codes
            self._raw_lines = plot_output.split('\n')
            self._has_ansi = any(self.ANSI_PATTERN.search(line) for line in self._raw_lines)
            
            # For the content property, store lines without ANSI
            # (This is what will be used for panel dimensions)
            if self._has_ansi:
                clean_lines = []
                for line in self._raw_lines:
                    clean_line = self.ANSI_PATTERN.sub('', line)
                    clean_lines.append(clean_line)
                self.content = clean_lines
            else:
                self.content = self._raw_lines
            
        except ImportError:
            self.content = "plotext not installed\nRun: pip install plotext"
            self._raw_lines = self.content.split('\n')
            self._has_ansi = False
        except Exception as e:
            self.content = f"Error generating plot:\n{str(e)}"
            self._raw_lines = self.content.split('\n')
            self._has_ansi = False
    
    def render_line(self, y: int) -> Strip:
        """Custom render that handles ANSI codes."""
        # If we don't have ANSI codes, use parent's renderer
        if not self._has_ansi:
            return super().render_line(y)
        
        # Get glass background first - ensure we have it
        if self.region:
            if self._image_array is None:
                # Try to get the image array from the app
                app = self.app
                if hasattr(app, '_image_array'):
                    self._image_array = app._image_array
            
            if self._image_array is not None and self._precomputed_colors is None:
                self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        segments = []
        
        # Determine line content
        if not self.border:
            # No border - direct content
            if y < len(self._raw_lines):
                line = self._raw_lines[y]
            else:
                line = ""
        else:
            # With border
            if y == 0:
                # Top border - no ANSI codes here
                return super().render_line(y)
            elif y == height - 1:
                # Bottom border - no ANSI codes here
                return super().render_line(y)
            else:
                # Content with side borders
                content_y = y - 1
                if content_y < len(self._raw_lines):
                    line = self._raw_lines[content_y]
                else:
                    line = ""
                
                # Parse ANSI codes
                parsed_segments = self._parse_ansi_line(line)
                
                # Add left border with glass background
                for idx, border_char in enumerate("│ "):
                    if self._precomputed_colors is not None:
                        abs_y = self.abs_y + y
                        abs_x = self.abs_x + idx
                        
                        if (0 <= abs_y < self._precomputed_colors.shape[0] and
                            0 <= abs_x < self._precomputed_colors.shape[1]):
                            glass_color = self._precomputed_colors[abs_y, abs_x]
                            bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                            segments.append(Segment(border_char, RichStyle(bgcolor=bg_color)))
                        else:
                            segments.append(Segment(border_char, RichStyle()))
                    else:
                        segments.append(Segment(border_char, RichStyle()))
                
                # Add content with styles
                current_x = 2  # After border and space
                for text, style in parsed_segments:
                    if current_x + len(text) > width - 2:
                        # Truncate if too long
                        text = text[:max(0, width - 2 - current_x)]
                    
                    if text:
                        # Apply glass effect to each character
                        for char in text:
                            if current_x < width - 2:
                                # Get glass color for this position
                                if self._precomputed_colors is not None:
                                    abs_y = self.abs_y + y
                                    abs_x = self.abs_x + current_x
                                    
                                    if (0 <= abs_y < self._precomputed_colors.shape[0] and
                                        0 <= abs_x < self._precomputed_colors.shape[1]):
                                        glass_color = self._precomputed_colors[abs_y, abs_x]
                                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                                        
                                        # Combine ANSI style with glass background
                                        combined_style = RichStyle(
                                            color=style.color,
                                            bgcolor=bg_color,
                                            bold=style.bold,
                                            italic=style.italic,
                                            underline=style.underline
                                        )
                                        segments.append(Segment(char, combined_style))
                                    else:
                                        # No glass color available - use style WITHOUT background
                                        segments.append(Segment(char, RichStyle(
                                            color=style.color,
                                            bold=style.bold,
                                            italic=style.italic,
                                            underline=style.underline
                                        )))
                                else:
                                    # No precomputed colors - use style WITHOUT background
                                    segments.append(Segment(char, RichStyle(
                                        color=style.color,
                                        bold=style.bold,
                                        italic=style.italic,
                                        underline=style.underline
                                    )))
                                
                                current_x += 1
                
                # Pad to right border with glass background
                padding = width - 2 - current_x
                if padding > 0:
                    for _ in range(padding):
                        if self._precomputed_colors is not None:
                            abs_y = self.abs_y + y
                            abs_x = self.abs_x + current_x
                            
                            if (0 <= abs_y < self._precomputed_colors.shape[0] and
                                0 <= abs_x < self._precomputed_colors.shape[1]):
                                glass_color = self._precomputed_colors[abs_y, abs_x]
                                bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                                segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                            else:
                                segments.append(Segment(" ", RichStyle()))  # No background
                        else:
                            segments.append(Segment(" ", RichStyle()))  # No background
                        current_x += 1
                
                # Add right border with glass background
                if self._precomputed_colors is not None and current_x < width:
                    abs_y = self.abs_y + y
                    abs_x = self.abs_x + current_x
                    
                    if (0 <= abs_y < self._precomputed_colors.shape[0] and
                        0 <= abs_x < self._precomputed_colors.shape[1]):
                        glass_color = self._precomputed_colors[abs_y, abs_x]
                        bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                        segments.append(Segment("│", RichStyle(bgcolor=bg_color)))
                    else:
                        segments.append(Segment("│", RichStyle()))
                else:
                    segments.append(Segment("│", RichStyle()))
                
                return Strip(segments)
        
        # For non-border content, parse and render with ANSI
        parsed_segments = self._parse_ansi_line(line)
        current_x = 0
        
        for text, style in parsed_segments:
            if current_x + len(text) > width:
                text = text[:max(0, width - current_x)]
            
            if text:
                for char in text:
                    if current_x < width:
                        # Apply glass effect
                        if self._precomputed_colors is not None:
                            abs_y = self.abs_y + y
                            abs_x = self.abs_x + current_x
                            
                            if (0 <= abs_y < self._precomputed_colors.shape[0] and
                                0 <= abs_x < self._precomputed_colors.shape[1]):
                                glass_color = self._precomputed_colors[abs_y, abs_x]
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
                                # No glass color - use style without background
                                segments.append(Segment(char, RichStyle(
                                    color=style.color,
                                    bold=style.bold,
                                    italic=style.italic,
                                    underline=style.underline
                                )))
                        else:
                            # No precomputed colors - use style without background
                            segments.append(Segment(char, RichStyle(
                                color=style.color,
                                bold=style.bold,
                                italic=style.italic,
                                underline=style.underline
                            )))
                        
                        current_x += 1
        
        # Pad remainder with glass background
        while current_x < width:
            if self._precomputed_colors is not None:
                abs_y = self.abs_y + y
                abs_x = self.abs_x + current_x
                
                if (0 <= abs_y < self._precomputed_colors.shape[0] and
                    0 <= abs_x < self._precomputed_colors.shape[1]):
                    glass_color = self._precomputed_colors[abs_y, abs_x]
                    bg_color = f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
                    segments.append(Segment(" ", RichStyle(bgcolor=bg_color)))
                else:
                    segments.append(Segment(" ", RichStyle()))
            else:
                segments.append(Segment(" ", RichStyle()))
            current_x += 1
        
        return Strip(segments)
    
    def on_mount(self):
        """Generate plot after mounting."""
        self._generate_plot()
    
    def update_plot(self, plot_data: Dict[str, Any]):
        """Update the plot with new data."""
        self._plot_data = plot_data
        self._generate_plot()
        self.refresh()