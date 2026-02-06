#!/usr/bin/env python3
"""
Glass Plot Container Fixed - Proper ANSI handling with glass effect
===================================================================

Combines background stripping with proper ANSI rendering.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any, Tuple
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import re


class GlassPlotextFixed(AbsoluteGlassPanel):
    """
    Fixed plotext rendering with proper ANSI color support and glass effect.
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
    
    def _strip_background_codes(self, text: str) -> str:
        """Strip all background color codes while preserving foreground codes."""
        # First handle RGB backgrounds: \x1b[48;2;r;g;bm
        text = re.sub(r'\x1b\[48;2;\d+;\d+;\d+m', '', text)
        
        # 256 color backgrounds: \x1b[48;5;nm
        text = re.sub(r'\x1b\[48;5;\d+m', '', text)
        
        # Standard backgrounds: \x1b[40-47m
        text = re.sub(r'\x1b\[4[0-7]m', '', text)
        
        # Handle combined codes
        def clean_combined_codes(match):
            codes = match.group(1).split(';')
            cleaned_codes = []
            
            i = 0
            while i < len(codes):
                code = codes[i]
                
                # Skip background-related codes
                if code in ['40', '41', '42', '43', '44', '45', '46', '47']:
                    i += 1
                    continue
                elif code == '48':
                    # Skip the 48 and its parameters
                    if i + 1 < len(codes):
                        if codes[i + 1] == '5' and i + 2 < len(codes):
                            # 256 color - skip 48;5;n
                            i += 3
                            continue
                        elif codes[i + 1] == '2' and i + 4 < len(codes):
                            # RGB - skip 48;2;r;g;b
                            i += 5
                            continue
                    i += 1
                    continue
                else:
                    # Keep this code
                    cleaned_codes.append(code)
                    i += 1
            
            # If we have any codes left, return them
            if cleaned_codes:
                return f"\x1b[{';'.join(cleaned_codes)}m"
            else:
                return ''
        
        # Process combined codes
        text = re.sub(r'\x1b\[([0-9;]+)m', clean_combined_codes, text)
        
        return text
    
    def _parse_ansi_line(self, line: str) -> List[Tuple[str, Optional[RichStyle]]]:
        """Parse a line with ANSI codes into segments with styles."""
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
        """Parse SGR codes and create a new style."""
        # Start with base style attributes
        color = base_style.color
        bold = base_style.bold
        italic = base_style.italic
        underline = base_style.underline
        
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
        
        return RichStyle(
            color=color,
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
            
            # Use theme that supports colors
            theme = self._plot_data.get('theme', 'dark')
            plt.theme(theme)
            
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
            
            # Strip background codes FIRST
            clean_output = self._strip_background_codes(plot_output)
            
            # Store cleaned lines with ANSI codes
            self._raw_lines = clean_output.split('\n')
            self._has_ansi = any(self.ANSI_PATTERN.search(line) for line in self._raw_lines)
            
            # For the content property, store lines without ANSI
            # (This is what will be used for panel dimensions)
            clean_lines = []
            for line in self._raw_lines:
                clean_line = self.ANSI_PATTERN.sub('', line)
                clean_lines.append(clean_line)
            self.content = clean_lines
            
        except ImportError:
            self.content = "plotext not installed\nRun: pip install plotext"
            self._raw_lines = []
            self._has_ansi = False
        except Exception as e:
            self.content = f"Error generating plot:\n{str(e)}"
            self._raw_lines = []
            self._has_ansi = False
    
    def render_line(self, y: int) -> Strip:
        """Custom render that handles ANSI codes with glass background."""
        # Get glass background first
        if self.region and self._image_array is None:
            # Try to get the image array from the app
            app = self.app
            if hasattr(app, '_image_array'):
                self._image_array = app._image_array
        
        if self.region and self._image_array is not None and self._precomputed_colors is None:
            self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        segments = []
        
        # Get the line to render
        if not self.border:
            # No border - direct content
            if y < len(self._raw_lines) and self._has_ansi:
                line = self._raw_lines[y]
                # Parse and render with ANSI
                return self._render_ansi_line(line, y, width)
            else:
                # No ANSI codes, use parent renderer
                return super().render_line(y)
        else:
            # With border
            if y == 0 or y == height - 1:
                # Top/bottom border - use parent renderer
                return super().render_line(y)
            else:
                # Content with side borders
                content_y = y - 1
                if content_y < len(self._raw_lines) and self._has_ansi:
                    line = self._raw_lines[content_y]
                    
                    # Build segments with border and content
                    segments = []
                    
                    # Left border with glass
                    for idx, char in enumerate("│ "):
                        bg_color = self._get_glass_bg(y, idx)
                        segments.append(Segment(char, RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                    
                    # Parse ANSI content
                    parsed_segments = self._parse_ansi_line(line)
                    current_x = 2  # After border and space
                    
                    for text, style in parsed_segments:
                        for char in text:
                            if current_x < width - 2:
                                bg_color = self._get_glass_bg(y, current_x)
                                if bg_color:
                                    combined_style = RichStyle(
                                        color=style.color,
                                        bgcolor=bg_color,
                                        bold=style.bold,
                                        italic=style.italic,
                                        underline=style.underline
                                    )
                                else:
                                    combined_style = style
                                segments.append(Segment(char, combined_style))
                                current_x += 1
                    
                    # Pad to right border
                    while current_x < width - 2:
                        bg_color = self._get_glass_bg(y, current_x)
                        segments.append(Segment(" ", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                        current_x += 1
                    
                    # Right border
                    bg_color = self._get_glass_bg(y, current_x)
                    segments.append(Segment("│", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                    
                    return Strip(segments)
                else:
                    # No ANSI codes in this line, use parent renderer
                    return super().render_line(y)
    
    def _render_ansi_line(self, line: str, y: int, width: int) -> Strip:
        """Render a line with ANSI codes and glass background."""
        segments = []
        parsed_segments = self._parse_ansi_line(line)
        current_x = 0
        
        for text, style in parsed_segments:
            for char in text:
                if current_x < width:
                    bg_color = self._get_glass_bg(y, current_x)
                    if bg_color:
                        combined_style = RichStyle(
                            color=style.color,
                            bgcolor=bg_color,
                            bold=style.bold,
                            italic=style.italic,
                            underline=style.underline
                        )
                    else:
                        combined_style = style
                    segments.append(Segment(char, combined_style))
                    current_x += 1
        
        # Pad remainder
        while current_x < width:
            bg_color = self._get_glass_bg(y, current_x)
            segments.append(Segment(" ", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
            current_x += 1
        
        return Strip(segments)
    
    def _get_glass_bg(self, y: int, x: int) -> Optional[str]:
        """Get glass background color for a position."""
        if self._precomputed_colors is not None:
            abs_y = self.abs_y + y
            abs_x = self.abs_x + x
            
            if (0 <= abs_y < self._precomputed_colors.shape[0] and
                0 <= abs_x < self._precomputed_colors.shape[1]):
                glass_color = self._precomputed_colors[abs_y, abs_x]
                return f"#{glass_color[0]:02x}{glass_color[1]:02x}{glass_color[2]:02x}"
        return None
    
    def on_mount(self):
        """Generate plot after mounting."""
        self._generate_plot()
    
    def update_plot(self, plot_data: Dict[str, Any]):
        """Update the plot with new data."""
        self._plot_data = plot_data
        self._generate_plot()
        self.refresh()