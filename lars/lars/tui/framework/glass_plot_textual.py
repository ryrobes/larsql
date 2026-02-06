#!/usr/bin/env python3
"""
Glass Plot Container using Textual's ANSI decoder
=================================================

Uses Textual's built-in ANSI decoding to parse plotext output.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any
from rich.text import Text
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import re


class GlassPlotextTextual(AbsoluteGlassPanel):
    """
    Uses Textual's ANSI decoder to properly handle colors.
    """
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """Initialize with plot data."""
        self._plot_data = plot_data or {}
        self._decoded_lines = []  # Will store decoded Text objects
        
        # Start with empty content
        super().__init__(content='Generating plot...', *args, **kwargs)
    
    def _strip_backgrounds(self, text: str) -> str:
        """Strip background codes before decoding."""
        # RGB backgrounds
        text = re.sub(r'\x1b\[48;2;\d+;\d+;\d+m', '', text)
        # 256 color backgrounds
        text = re.sub(r'\x1b\[48;5;\d+m', '', text)
        # Standard backgrounds
        text = re.sub(r'\x1b\[4[0-7]m', '', text)
        
        # Handle combined codes
        def clean_combined(match):
            codes = match.group(1).split(';')
            cleaned = []
            i = 0
            while i < len(codes):
                code = codes[i]
                if code in ['40', '41', '42', '43', '44', '45', '46', '47']:
                    i += 1
                elif code == '48':
                    if i + 1 < len(codes):
                        if codes[i + 1] == '5' and i + 2 < len(codes):
                            i += 3
                        elif codes[i + 1] == '2' and i + 4 < len(codes):
                            i += 5
                        else:
                            i += 1
                    else:
                        i += 1
                else:
                    cleaned.append(code)
                    i += 1
            return f"\x1b[{';'.join(cleaned)}m" if cleaned else ''
        
        return re.sub(r'\x1b\[([0-9;]+)m', clean_combined, text)
    
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
                
                if plot_type == 'bar' and colors:
                    plt.bar(x_data, y_data, color=colors)
                elif plot_type == 'bar':
                    plt.bar(x_data, y_data)
                elif plot_type == 'line' and colors:
                    plt.plot(x_data, y_data, color=colors)
                elif plot_type == 'line':
                    plt.plot(x_data, y_data)
                elif plot_type == 'scatter' and colors:
                    plt.scatter(x_data, y_data, color=colors)
                elif plot_type == 'scatter':
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
            
            # Strip background codes
            clean_output = self._strip_backgrounds(plot_output)
            
            # Decode ANSI to Text objects
            lines = clean_output.split('\n')
            self._decoded_lines = []
            plain_lines = []
            
            for line in lines:
                # Create Text object from ANSI
                text_obj = Text.from_ansi(line)
                self._decoded_lines.append(text_obj)
                # Get plain version for content
                plain_lines.append(text_obj.plain)
            
            self.content = plain_lines
            
        except ImportError:
            self.content = "plotext not installed\nRun: pip install plotext"
            self._decoded_lines = []
        except Exception as e:
            self.content = f"Error generating plot:\n{str(e)}"
            self._decoded_lines = []
    
    def render_line(self, y: int) -> Strip:
        """Custom render using decoded Text objects."""
        # Get glass background first
        if self.region and self._image_array is None:
            app = self.app
            if hasattr(app, '_image_array'):
                self._image_array = app._image_array
        
        if self.region and self._image_array is not None and self._precomputed_colors is None:
            self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        
        # Handle borders using parent
        if self.border and (y == 0 or y == height - 1):
            return super().render_line(y)
        
        # Get content line
        if self.border:
            content_y = y - 1
        else:
            content_y = y
        
        # Check if we have decoded content
        if content_y < len(self._decoded_lines):
            text_obj = self._decoded_lines[content_y]
            segments = []
            
            if self.border:
                # Add left border
                for idx, char in enumerate("│ "):
                    bg_color = self._get_glass_bg(y, idx)
                    segments.append(Segment(char, RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                current_x = 2
            else:
                current_x = 0
            
            # Render the text with styles and glass background
            # Iterate through characters with their styles
            plain_text = text_obj.plain
            for char_idx, char in enumerate(plain_text):
                if current_x < (width - 2 if self.border else width):
                    # Get style at this position
                    style = text_obj.get_style_at_offset(console=None, offset=char_idx)
                    
                    bg_color = self._get_glass_bg(y, current_x)
                    if bg_color:
                        # Combine text style with glass background
                        if style:
                            combined_style = RichStyle(
                                color=style.color,
                                bgcolor=bg_color,
                                bold=style.bold,
                                italic=style.italic,
                                underline=style.underline
                            )
                        else:
                            combined_style = RichStyle(bgcolor=bg_color)
                    else:
                        combined_style = style if style else RichStyle()
                    segments.append(Segment(char, combined_style))
                    current_x += 1
            
            # Pad to right
            if self.border:
                while current_x < width - 2:
                    bg_color = self._get_glass_bg(y, current_x)
                    segments.append(Segment(" ", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                    current_x += 1
                # Right border
                bg_color = self._get_glass_bg(y, current_x)
                segments.append(Segment("│", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
            else:
                while current_x < width:
                    bg_color = self._get_glass_bg(y, current_x)
                    segments.append(Segment(" ", RichStyle(bgcolor=bg_color) if bg_color else RichStyle()))
                    current_x += 1
            
            return Strip(segments)
        else:
            # No decoded content, use parent
            return super().render_line(y)
    
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