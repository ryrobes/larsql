#!/usr/bin/env python3
"""
Glass Plot Container - Minimal color approach
============================================

Uses the exact same approach as GlassPlotextDirect but keeps foreground colors.
"""

from .looking_glass import AbsoluteGlassPanel
from typing import Dict, List, Optional, Any
import re


class GlassPlotextMinimal(AbsoluteGlassPanel):
    """
    Minimal approach - strip only background colors, keep foreground.
    Does NOT override render_line - uses parent's implementation.
    """
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """Initialize with plot data."""
        self._plot_data = plot_data or {}
        
        # Start with empty content
        super().__init__(content='Generating plot...', *args, **kwargs)
    
    def _strip_only_backgrounds(self, text: str) -> str:
        """
        Strip ONLY background color codes, keep everything else.
        
        This is a minimal approach that preserves foreground colors
        while removing backgrounds that interfere with glass effect.
        """
        # Strip RGB backgrounds: \x1b[48;2;r;g;bm
        text = re.sub(r'\x1b\[48;2;\d+;\d+;\d+m', '', text)
        
        # Strip 256 color backgrounds: \x1b[48;5;nm
        text = re.sub(r'\x1b\[48;5;\d+m', '', text)
        
        # Strip standard backgrounds: \x1b[40-47m
        text = re.sub(r'\x1b\[4[0-7]m', '', text)
        
        # Handle combined codes that include backgrounds
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
                    # Keep this code (foreground colors, text attributes)
                    cleaned_codes.append(code)
                    i += 1
            
            # Return the cleaned sequence
            if cleaned_codes:
                return f"\x1b[{';'.join(cleaned_codes)}m"
            else:
                # No codes left, return empty
                return ''
        
        # Process combined codes
        text = re.sub(r'\x1b\[([0-9;]+)m', clean_combined_codes, text)
        
        return text
    
    def _generate_plot(self):
        """Generate plot using plotext - similar to GlassPlotextDirect."""
        try:
            import plotext as plt
            
            # Clear any previous plot
            plt.clf()
            
            # Configure for string output
            width = self._plot_data.get('width', 40)
            height = self._plot_data.get('height', 10)
            plt.plotsize(width, height)
            
            # Use theme
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
            
            # Strip ONLY background codes, keep foreground colors
            clean_output = self._strip_only_backgrounds(plot_output)
            
            # Set as content - let parent handle rendering
            self.content = clean_output
            
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
    
    # NO render_line override - use parent's implementation!