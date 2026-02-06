#!/usr/bin/env python3
"""
Glass Plot Container - Simple ANSI approach
==========================================

Direct ANSI parsing with proper glass integration.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any, Tuple
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import re


class GlassPlotextSimple(AbsoluteGlassPanel):
    """
    Simple ANSI color support - overrides render_line to handle colors.
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
        """Override to handle ANSI codes."""
        # Get glass background
        if self.region and self._image_array is None:
            app = self.app
            if hasattr(app, '_image_array'):
                self._image_array = app._image_array
        
        if self.region and self._image_array is not None and self._precomputed_colors is None:
            self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        
        # For borders, use parent
        if self.border and (y == 0 or y == height - 1):
            return super().render_line(y)
        
        # Get the ANSI line
        content_y = (y - 1) if self.border else y
        if content_y >= len(self._ansi_lines):
            return super().render_line(y)
        
        line = self._ansi_lines[content_y]
        
        # Parse ANSI codes
        segments = []
        current_x = 0
        current_color = None
        current_bg = None  # We'll ignore this
        bold = False
        italic = False
        underline = False
        
        # Add left border if needed
        if self.border:
            bg = self._get_glass_bg(y, 0)
            segments.append(Segment("│", RichStyle(bgcolor=bg) if bg else RichStyle()))
            bg = self._get_glass_bg(y, 1)
            segments.append(Segment(" ", RichStyle(bgcolor=bg) if bg else RichStyle()))
            current_x = 2
        
        # Parse the line
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
                        codes = [int(x) for x in codes_str.split(';') if x.isdigit()]
                        for code in codes:
                            if code == 0:  # Reset
                                current_color = None
                                bold = italic = underline = False
                            elif code == 1:
                                bold = True
                            elif code == 3:
                                italic = True
                            elif code == 4:
                                underline = True
                            elif 30 <= code <= 37:  # Standard colors
                                colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
                                current_color = colors[code - 30]
                            elif 90 <= code <= 97:  # Bright colors
                                colors = ['bright_black', 'bright_red', 'bright_green', 'bright_yellow',
                                         'bright_blue', 'bright_magenta', 'bright_cyan', 'bright_white']
                                current_color = colors[code - 90]
                            # Ignore background colors (40-47, 48)
                
                i = j + 1
            else:
                # Regular character
                if current_x < (width - 2 if self.border else width):
                    char = line[i] if i < len(line) else ' '
                    bg = self._get_glass_bg(y, current_x)
                    style = RichStyle(
                        color=current_color,
                        bgcolor=bg,
                        bold=bold,
                        italic=italic,
                        underline=underline
                    )
                    segments.append(Segment(char, style))
                    current_x += 1
                i += 1
        
        # Pad to right
        if self.border:
            while current_x < width - 2:
                bg = self._get_glass_bg(y, current_x)
                segments.append(Segment(" ", RichStyle(bgcolor=bg) if bg else RichStyle()))
                current_x += 1
            bg = self._get_glass_bg(y, current_x)
            segments.append(Segment("│", RichStyle(bgcolor=bg) if bg else RichStyle()))
        else:
            while current_x < width:
                bg = self._get_glass_bg(y, current_x)
                segments.append(Segment(" ", RichStyle(bgcolor=bg) if bg else RichStyle()))
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