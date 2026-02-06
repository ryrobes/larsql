#!/usr/bin/env python3
"""
Glass Plot Container - Final Implementation
==========================================

Following the exact pattern from GlassRichDSLWidget for proper glass+color rendering.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import re


class GlassPlotextFinal(AbsoluteGlassPanel):
    """
    Final implementation following GlassRichDSLWidget pattern.
    """
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """Initialize with plot data."""
        self._plot_data = plot_data or {}
        self._ansi_lines = []  # Store lines with ANSI codes
        
        # Start with empty content
        super().__init__(content='Generating plot...', *args, **kwargs)
    
    def _generate_plot(self):
        """Generate plot using plotext."""
        try:
            import plotext as plt
            
            # Debug log
            # with open('color_debug.log', 'a') as f:
            #     f.write(f"GlassPlotextFinal: plot_data = {self._plot_data}\n")
            #     if 'color' in self._plot_data:
            #         f.write(f"GlassPlotextFinal: color = {self._plot_data['color']}\n")
            
            # Clear any previous plot
            plt.clf()
            
            # Configure for string output
            width = self._plot_data.get('width', 40)
            height = self._plot_data.get('height', 10)
            plt.plotsize(width, height)
            
            # Use theme that supports colors
            theme = self._plot_data.get('theme', 'pro') ## 'pro' 'dark'
            plt.theme(theme)
            
            # Get plot data
            plot_type = self._plot_data.get('type', 'bar')
            title = self._plot_data.get('title', 'Sample Chart')
            
            # Set colors if provided - check both 'color' and 'colors' keys
            colors = self._plot_data.get('color', self._plot_data.get('colors', None))
            
            # Convert hex colors to RGB tuples for plotext
            if colors and isinstance(colors, str) and colors.startswith('#'):
                try:
                    # Convert hex to RGB tuple
                    hex_color = colors.lstrip('#')
                    r = int(hex_color[0:2], 16)
                    g = int(hex_color[2:4], 16)
                    b = int(hex_color[4:6], 16)
                    colors = (r, g, b)
                    # with open('color_debug.log', 'a') as f:
                    #     f.write(f"GlassPlotextFinal: Converted {self._plot_data.get('color')} to RGB {colors}\n")
                except (ValueError, IndexError):
                    # If conversion fails, use the color as-is
                    pass
            
            # Create the plot based on type
            if plot_type == 'histogram':
                data = self._plot_data.get('data', [1, 2, 3, 4, 5])
                bins = self._plot_data.get('bins', 10)
                if data and colors:
                    plt.hist(data, bins=bins, color=colors)
                elif data:
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
            
            # Store lines with ANSI codes
            self._ansi_lines = plot_output.split('\n')
            
            # For content, store plain text (strip all ANSI)
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            plain_lines = []
            for line in self._ansi_lines:
                plain_lines.append(ansi_escape.sub('', line))
            
            self.content = plain_lines
            
        except ImportError:
            self.content = "plotext not installed\nRun: pip install plotext"
            self._ansi_lines = []
        except Exception as e:
            self.content = f"Error generating plot:\n{str(e)}"
            self._ansi_lines = []
    
    def render_line(self, y: int) -> Strip:
        """Override to handle ANSI codes with glass background."""
        # Get glass background precomputed colors
        if self.region and self._image_array is None:
            app = self.app
            if hasattr(app, '_image_array'):
                self._image_array = app._image_array
        
        if self.region and self._image_array is not None and self._precomputed_colors is None:
            self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        segments = []
        
        # Get padding value (default to 1 if not set)
        padding = getattr(self, 'padding', 1)
        
        # For top/bottom borders, use parent
        if self.border and (y == 0 or y == height - 1):
            return super().render_line(y)
        
        # Get the content line
        content_y = (y - 1) if self.border else y
        if content_y >= len(self._ansi_lines):
            return super().render_line(y)
        
        line = self._ansi_lines[content_y]
        
        # Track ANSI state
        current_fg_color = 'white'
        bold = False
        italic = False
        underline = False
        
        # Add left border if needed
        if self.border:
            segments.append(self._render_char('│', 0, y, current_fg_color, bold, italic, underline))
            # Add padding spaces after border
            for p in range(padding):
                segments.append(self._render_char(' ', 1 + p, y, current_fg_color, bold, italic, underline))
            current_x = 1 + padding
        else:
            # Add padding spaces at the start
            for p in range(padding):
                segments.append(self._render_char(' ', p, y, current_fg_color, bold, italic, underline))
            current_x = padding
        
        # Parse the line character by character
        i = 0
        while i < len(line):
            if i < len(line) - 1 and line[i:i+2] == '\x1b[':
                # Find end of ANSI sequence
                j = i + 2
                while j < len(line) and line[j] not in 'mGKHJED':
                    j += 1
                
                if j < len(line) and line[j] == 'm':
                    # Parse SGR codes
                    codes_str = line[i+2:j]
                    if codes_str:
                        try:
                            parts = codes_str.split(';')
                            i_code = 0
                            while i_code < len(parts):
                                if not parts[i_code].isdigit():
                                    i_code += 1
                                    continue
                                    
                                code = int(parts[i_code])
                                
                                if code == 0:  # Reset
                                    current_fg_color = 'white'
                                    bold = italic = underline = False
                                elif code == 1:
                                    bold = True
                                elif code == 3:
                                    italic = True
                                elif code == 4:
                                    underline = True
                                elif 30 <= code <= 37:  # Standard colors
                                    colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
                                    current_fg_color = colors[code - 30]
                                elif 90 <= code <= 97:  # Bright colors
                                    colors = ['bright_black', 'bright_red', 'bright_green', 'bright_yellow',
                                             'bright_blue', 'bright_magenta', 'bright_cyan', 'bright_white']
                                    current_fg_color = colors[code - 90]
                                elif code == 38:  # Extended foreground color
                                    if i_code + 2 < len(parts) and parts[i_code + 1] == '5':
                                        # 256 color: 38;5;n
                                        color_num = int(parts[i_code + 2])
                                        current_fg_color = f"color({color_num})"
                                        i_code += 2
                                    elif i_code + 4 < len(parts) and parts[i_code + 1] == '2':
                                        # RGB: 38;2;r;g;b
                                        r = int(parts[i_code + 2])
                                        g = int(parts[i_code + 3])
                                        b = int(parts[i_code + 4])
                                        current_fg_color = f"#{r:02x}{g:02x}{b:02x}"
                                        i_code += 4
                                elif code == 48:  # Skip background colors
                                    if i_code + 1 < len(parts):
                                        if parts[i_code + 1] == '5':
                                            i_code += 2  # Skip 48;5;n
                                        elif parts[i_code + 1] == '2':
                                            i_code += 4  # Skip 48;2;r;g;b
                                elif 40 <= code <= 47:  # Skip standard backgrounds
                                    pass
                                    
                                i_code += 1
                        except:
                            # If parsing fails, just continue
                            pass
                
                i = j + 1
            else:
                # Regular character - only render if we have space
                # Account for border and padding on both sides
                if self.border:
                    max_x = width - 1 - padding  # Leave room for right padding and border
                else:
                    max_x = width - padding  # Leave room for right padding
                if current_x < max_x:
                    char = line[i] if i < len(line) else ' '
                    segments.append(self._render_char(char, current_x, y, current_fg_color, bold, italic, underline))
                    current_x += 1
                i += 1
        
        # Pad to right border/edge
        if self.border:
            # Pad with spaces up to right padding area
            while current_x < width - 1 - padding:
                segments.append(self._render_char(' ', current_x, y, 'white', False, False, False))
                current_x += 1
            # Add right padding spaces
            for p in range(padding):
                segments.append(self._render_char(' ', current_x, y, 'white', False, False, False))
                current_x += 1
            # Add right border at the last position
            if current_x == width - 1:
                segments.append(self._render_char('│', current_x, y, 'white', False, False, False))
        else:
            # Pad with spaces up to right padding area
            while current_x < width - padding:
                segments.append(self._render_char(' ', current_x, y, 'white', False, False, False))
                current_x += 1
            # Add right padding spaces
            for p in range(padding):
                if current_x < width:
                    segments.append(self._render_char(' ', current_x, y, 'white', False, False, False))
                    current_x += 1
        
        return Strip(segments)
    
    def _render_char(self, char: str, x: int, y: int, fg_color: str, bold: bool, italic: bool, underline: bool) -> Segment:
        """Render a single character with glass background and text style."""
        # Get glass background color (following GlassRichDSLWidget pattern)
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
            color = self._precomputed_colors[y, x]
            bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        else:
            # Fallback blending
            if hasattr(self, '_overlay_rgb'):
                r, g, b = self._overlay_rgb
            else:
                # Default to blue if not set
                r, g, b = 0, 0, 255
            
            blend_factor = self.blend_opacity
            darken = 1 - self.darken_factor
            
            r = int(r * blend_factor * darken)
            g = int(g * blend_factor * darken)
            b = int(b * blend_factor * darken)
            bg_hex = f"#{r:02x}{g:02x}{b:02x}"
        
        # Create style with glass background and text attributes
        style = RichStyle(
            color=fg_color,
            bgcolor=bg_hex,  # THIS is the key - explicit glass background
            bold=bold,
            italic=italic,
            underline=underline
        )
        
        return Segment(char, style)
    
    def on_mount(self):
        """Generate plot after mounting."""
        self._generate_plot()
    
    def update_plot(self, plot_data: Dict[str, Any]):
        """Update the plot with new data."""
        self._plot_data = plot_data
        self._generate_plot()
        self.refresh()
