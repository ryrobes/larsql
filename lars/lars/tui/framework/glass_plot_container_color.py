#!/usr/bin/env python3
"""
Glass Plot Container with Color Support - Preserves plotext ANSI colors
======================================================================

This module wraps plotext charts with proper ANSI color containment.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any
import re


class GlassPlotextDirectColor(AbsoluteGlassPanel):
    """
    Direct plotext rendering in a glass panel with ANSI color support.
    
    This version preserves plotext's ANSI color codes while ensuring they
    don't leak to subsequent lines.
    """
    
    # ANSI code patterns
    ANSI_PATTERN = re.compile(r'(\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))')
    ANSI_SGR_PATTERN = re.compile(r'\x1B\[([0-9;]*)m')
    ANSI_RESET = '\x1B[0m'
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """Initialize with plot data."""
        self._plot_data = plot_data or {}
        self._raw_plot_output = ''
        self._processed_lines = []
        
        # Start with empty content
        super().__init__(content='Generating plot...', *args, **kwargs)
    
    def _parse_ansi_codes(self, text: str) -> List[tuple]:
        """
        Parse text into segments of (text, ansi_codes).
        
        Returns:
            List of tuples (text_segment, ansi_codes_before_segment)
        """
        segments = []
        current_codes = []
        
        # Split by ANSI codes
        parts = self.ANSI_PATTERN.split(text)
        
        for i, part in enumerate(parts):
            if i % 2 == 0:  # Text part
                if part:  # Skip empty strings
                    segments.append((part, list(current_codes)))
            else:  # ANSI code part
                # Check if it's an SGR (Select Graphic Rendition) code
                sgr_match = self.ANSI_SGR_PATTERN.match(part)
                if sgr_match:
                    params = sgr_match.group(1)
                    if not params or params == '0':  # Reset
                        current_codes = []
                    else:
                        # Add to current codes
                        current_codes.append(part)
        
        return segments
    
    def _process_plot_output(self, raw_output: str) -> List[str]:
        """
        Process plotext output to contain ANSI codes per line.
        
        Args:
            raw_output: Raw plotext output with ANSI codes
            
        Returns:
            List of processed lines with proper ANSI containment
        """
        lines = raw_output.split('\n')
        processed_lines = []
        active_codes = []  # Track codes that carry over between lines
        
        for line in lines:
            # Parse ANSI codes in this line
            segments = self._parse_ansi_codes(line)
            
            # Build the processed line
            processed_line = ''
            
            # Apply any active codes from previous lines
            if active_codes:
                processed_line = ''.join(active_codes)
            
            # Process each segment
            line_codes = []
            for text, codes in segments:
                # Apply codes before this segment
                if codes:
                    processed_line += ''.join(codes)
                    line_codes.extend(codes)
                
                # Add the text
                processed_line += text
            
            # Reset at end of line to prevent leakage
            if line_codes or active_codes:
                processed_line += self.ANSI_RESET
            
            # Update active codes for next line
            # (In plotext, colors typically continue across lines)
            active_codes = line_codes
            
            processed_lines.append(processed_line)
        
        return processed_lines
    
    def _generate_plot(self):
        """Generate plot using plotext with color support."""
        try:
            import plotext as plt
            
            # Clear any previous plot
            plt.clf()
            
            # Configure for string output (not terminal)
            width = self._plot_data.get('width', 40)
            height = self._plot_data.get('height', 10)
            plt.plotsize(width, height)
            
            # Use theme that supports colors (not 'clear')
            theme = self._plot_data.get('theme', 'dark')  # Default to 'dark' for colors
            if theme != 'clear':  # Only set theme if not 'clear'
                plt.theme(theme)
            
            # Get plot data
            plot_type = self._plot_data.get('type', 'bar')
            title = self._plot_data.get('title', 'Sample Chart')
            
            # Set colors if provided
            colors = self._plot_data.get('colors', None)
            
            # Create the plot based on type
            if plot_type == 'histogram':
                # Histogram uses single data array
                data = self._plot_data.get('data', [1, 2, 3, 4, 5])
                bins = self._plot_data.get('bins', 10)
                if data:  # Only plot if we have data
                    if colors:
                        plt.hist(data, bins=bins, color=colors)
                    else:
                        plt.hist(data, bins=bins)
            else:
                # Other plots use x,y data
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
            
            # Get the plot as string without showing it
            import io
            import sys
            
            # Capture output
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            
            try:
                plt.show()
                self._raw_plot_output = buffer.getvalue()
            finally:
                sys.stdout = old_stdout
            
            # Process the output to contain ANSI codes
            self._processed_lines = self._process_plot_output(self._raw_plot_output)
            
            # Set content as processed lines
            self.content = self._processed_lines
            
        except ImportError:
            self.content = "plotext not installed\nRun: pip install plotext"
        except Exception as e:
            self.content = f"Error generating plot:\n{str(e)}"
    
    def on_mount(self):
        """Generate plot after mounting."""
        self._generate_plot()
    
    def update_plot(self, plot_data: Dict[str, Any]):
        """Update the plot with new data."""
        self._plot_data = plot_data
        self._generate_plot()
        self.refresh()