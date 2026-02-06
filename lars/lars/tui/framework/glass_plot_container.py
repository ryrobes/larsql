#!/usr/bin/env python3
"""
Glass Plot Container - Wrapper for textual-plotext charts with glass morphism
============================================================================

This module attempts to wrap textual-plotext charts in our glass containers.
"""

from .looking_glass import AbsoluteGlassPanel
from .glass_native_container import GlassNativeContainer
from typing import Dict, List, Optional, Any, Callable
from textual.app import ComposeResult

try:
    from textual_plotext import PlotextPlot
    HAS_PLOTEXT = True
except ImportError:
    HAS_PLOTEXT = False
    PlotextPlot = None


class GlassPlotContainer(GlassNativeContainer):
    """
    A container for textual-plotext charts with glass morphism effects.
    
    This attempts to wrap PlotextPlot widgets while maintaining transparency.
    """
    
    def __init__(
        self,
        plot_data: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ):
        """
        Initialize the plot container.
        
        Args:
            plot_data: Dictionary containing plot configuration
            *args, **kwargs: Passed to GlassNativeContainer
        """
        if not HAS_PLOTEXT:
            # Fallback to a panel with message
            super().__init__(
                widget_class='Static',
                widget_props={'markup': '[red]textual-plotext not installed[/red]'},
                *args,
                **kwargs
            )
            return
        
        self._plot_data = plot_data or {}
        
        # Initialize with PlotextPlot widget
        super().__init__(
            widget_class=PlotextPlot,
            widget_props={},
            *args,
            **kwargs
        )
    
    def on_mount(self):
        """Configure the plot after mounting."""
        try:
            pass  # GlassNativeContainer doesn't have on_mount
            
            if HAS_PLOTEXT and self._native_widget and isinstance(self._native_widget, PlotextPlot):
                # Configure the plot
                plt = self._native_widget.plt
                
                # Try to make background transparent
                plt.theme('clear')  # Use clear theme
                
                # Get plot data
                plot_type = self._plot_data.get('type', 'bar')
                x_data = self._plot_data.get('x', [1, 2, 3, 4, 5])
                y_data = self._plot_data.get('y', [1, 4, 2, 5, 3])
                title = self._plot_data.get('title', 'Sample Chart')
                
                # Create the plot based on type
                if plot_type == 'bar':
                    plt.bar(x_data, y_data)
                elif plot_type == 'line':
                    plt.plot(x_data, y_data)
                elif plot_type == 'scatter':
                    plt.scatter(x_data, y_data)
                
                # Set labels
                plt.title(title)
                if 'xlabel' in self._plot_data:
                    plt.xlabel(self._plot_data['xlabel'])
                if 'ylabel' in self._plot_data:
                    plt.ylabel(self._plot_data['ylabel'])
        except Exception as e:
            self.log.error(f"Error configuring plot: {e}")


class GlassPlotextDirect(AbsoluteGlassPanel):
    """
    Direct plotext rendering in a glass panel without textual-plotext wrapper.
    
    This renders plotext output directly as text content.
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
    
    def _generate_plot(self):
        """Generate plot using plotext directly."""
        try:
            import plotext as plt
            
            # Debug log
            # with open('color_debug.log', 'a') as f:
            #     f.write(f"GlassPlotextDirect: plot_data = {self._plot_data}\n")
            #     if 'color' in self._plot_data:
            #         f.write(f"GlassPlotextDirect: color = {self._plot_data['color']}\n")
            
            # Clear any previous plot
            plt.clf()
            
            # Configure for string output (not terminal)
            width = self._plot_data.get('width', 40)
            height = self._plot_data.get('height', 10)
            plt.plotsize(width, height)
            
            # Use clear theme for compatibility
            theme = self._plot_data.get('theme', 'clear')
            plt.theme(theme)
            
            # Get plot data
            plot_type = self._plot_data.get('type', 'bar')
            title = self._plot_data.get('title', 'Sample Chart')
            
            # Get color if provided
            color = self._plot_data.get('color', None)
            
            # Convert hex colors to RGB tuples for plotext
            if color and isinstance(color, str) and color.startswith('#'):
                try:
                    # Convert hex to RGB tuple
                    hex_color = color.lstrip('#')
                    r = int(hex_color[0:2], 16)
                    g = int(hex_color[2:4], 16)
                    b = int(hex_color[4:6], 16)
                    color = (r, g, b)
                    # with open('color_debug.log', 'a') as f:
                    #     f.write(f"GlassPlotextDirect: Converted {self._plot_data.get('color')} to RGB {color}\n")
                except (ValueError, IndexError):
                    # If conversion fails, use the color as-is
                    pass
            
            # Create the plot based on type
            if plot_type == 'histogram':
                # Histogram uses single data array
                data = self._plot_data.get('data', [1, 2, 3, 4, 5])
                bins = self._plot_data.get('bins', 10)
                if data:  # Only plot if we have data
                    if color:
                        plt.hist(data, bins=bins, color=color)
                    else:
                        plt.hist(data, bins=bins)
            else:
                # Other plots use x,y data
                x_data = self._plot_data.get('x', [1, 2, 3, 4, 5])
                y_data = self._plot_data.get('y', [1, 4, 2, 5, 3])
                
                if plot_type == 'bar':
                    orientation = self._plot_data.get('orientation', 'vertical')
                    if color:
                        plt.bar(x_data, y_data, orientation=orientation, color=color)
                    else:
                        plt.bar(x_data, y_data, orientation=orientation)
                elif plot_type == 'line':
                    if color:
                        plt.plot(x_data, y_data, color=color)
                    else:
                        plt.plot(x_data, y_data)
                elif plot_type == 'scatter':
                    if color:
                        plt.scatter(x_data, y_data, color=color)
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
                plot_output = buffer.getvalue()
            finally:
                sys.stdout = old_stdout
            
            # Keep the plot output with ANSI colors intact
            # Don't strip ANSI codes - we want to preserve colors!
            self.content = plot_output
            
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