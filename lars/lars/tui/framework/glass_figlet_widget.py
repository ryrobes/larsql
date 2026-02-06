#!/usr/bin/env python3
"""
Glass Figlet Widget - ASCII art text rendering with glass effects
=================================================================

A Looking Glass widget that renders text using FIGlet fonts with
glass morphism effects. Supports all standard FIGlet fonts and
dynamic text updates.
"""

from typing import Optional, List, Union
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
from pyfiglet import Figlet, FigletFont
from .looking_glass import AbsoluteGlassMixin, BlazingFastBlendWidget
import os


class GlassFigletWidget(AbsoluteGlassMixin, BlazingFastBlendWidget):
    """
    A glass widget that renders text using FIGlet ASCII art fonts.
    
    Features:
    - Aggressive caching of figlet renders
    - Supports all pyfiglet fonts
    - Glass morphism effects
    - Dynamic text updates
    - Automatic text wrapping/cropping
    - CSS merge support for styling
    
    Example usage in ReactiveGlassApp:
    {
        'id': 'title_figlet',
        'type': 'figlet',
        'text': 'HELLO',
        'font': 'slant',  # Optional, defaults to 'slant'
        'x': 10,
        'y': 5,
        'width': 60,
        'height': 10,
        'overlay_color': 'cyan',
        'blend_opacity': 0.3,
        'css_merge': {
            'color': 'yellow',
            'text_style': 'bold'
        }
    }
    """
    
    # Class-level cache for figlet renders shared across all instances
    # Key: (text, font, justify, width) -> rendered_lines
    _FIGLET_RENDER_CACHE = {}
    _MAX_CACHE_ENTRIES = 1000  # Limit cache size
    
    # Class-level cache for Figlet instances
    _FIGLET_INSTANCE_CACHE = {}
    
    def __init__(self, 
                 text: str = "",
                 font: str = "slant",
                 justify: str = "auto",  # auto, left, center, right
                 width_mode: str = "default",  # default, full, fitted
                 padding: int = 0,
                 **kwargs):
        """
        Initialize the Figlet widget.
        
        Args:
            text: Text to render
            font: FIGlet font name (default: 'slant')
            justify: Text justification (auto, left, center, right)
            width_mode: How to handle width (default, full, fitted)
            padding: Padding to apply to content
            **kwargs: Passed to parent classes
        """
        # Initialize all attributes BEFORE calling parent __init__
        self._text = text
        self._font = font
        self._justify = justify
        self._width_mode = width_mode
        self._figlet = None
        self._rendered_lines = []
        
        # Instance-specific strip cache for the entire figlet render
        self._figlet_strip_cache = {}  # y -> Strip
        self._last_render_state = None  # Track when to invalidate strip cache
        
        # NOW call parent __init__ which might trigger refresh()
        super().__init__(content="", padding=padding, **kwargs)
        
        # Update figlet after parent initialization
        self._update_figlet()
    
    @property
    def text(self):
        return self._text
    
    @text.setter
    def text(self, value: str):
        if self._text != value:
            self._text = value
            self._update_figlet()
            self._invalidate_strip_cache()
            self.refresh()
    
    @property
    def font(self):
        return self._font
    
    @font.setter
    def font(self, value: str):
        if self._font != value:
            self._font = value
            self._figlet = None  # Force recreation
            self._update_figlet()
            self._invalidate_strip_cache()
            self.refresh()
    
    def _invalidate_strip_cache(self):
        """Invalidate the strip cache when content changes"""
        self._figlet_strip_cache.clear()
        self._last_render_state = None
    
    def _get_render_state(self):
        """Get current render state for cache validation"""
        return (
            self._text,
            self._font,
            self._justify,
            self._width_mode,
            self.size.width if self.size else 0,
            self.size.height if self.size else 0,
            self._padding,
            getattr(self, '_css_styles', None),
            self.overlay_color,
            self.blend_opacity,
            self.darken_factor,
            id(self._precomputed_colors)  # Changes when glass effect changes
        )
    
    def _get_or_create_figlet(self):
        """Get or create a cached Figlet instance"""
        cache_key = (self._font, self._justify, 9999)  # Fixed width for consistency
        
        if cache_key in self._FIGLET_INSTANCE_CACHE:
            return self._FIGLET_INSTANCE_CACHE[cache_key]
        
        # Create new instance
        figlet = None
        font_loaded = False
        
        # First try to load as a built-in font
        try:
            figlet = Figlet(font=self._font, justify=self._justify, width=9999)
            font_loaded = True
        except:
            pass
        
        # If built-in font not found, try loading from fonts directory
        if not font_loaded:
            font_path = os.path.join('fonts', f'{self._font}.flf')
            if os.path.exists(font_path):
                try:
                    # For now, use fallback font
                    if self._font.replace('-', '_').lower() not in FigletFont.getFonts():
                        print(f"Note: Custom font '{self._font}' found at {font_path}, but using built-in font for now.")
                    figlet = Figlet(font='slant', justify=self._justify, width=9999)
                    font_loaded = True
                except Exception as e:
                    print(f"Warning: Error handling custom font '{self._font}': {e}")
            
            if not font_loaded:
                # Final fallback to default font
                print(f"Warning: Font '{self._font}' not found, using default 'slant' font")
                figlet = Figlet(font='slant', justify=self._justify, width=9999)
        
        # Cache the instance
        if len(self._FIGLET_INSTANCE_CACHE) > 50:  # Limit instance cache
            # Remove oldest entry
            oldest_key = next(iter(self._FIGLET_INSTANCE_CACHE))
            del self._FIGLET_INSTANCE_CACHE[oldest_key]
        
        self._FIGLET_INSTANCE_CACHE[cache_key] = figlet
        return figlet
    
    def _update_figlet(self):
        """Update the rendered FIGlet text with caching."""
        if not self._text:
            self._rendered_lines = []
            return
        
        # Create cache key for the figlet render
        cache_key = (self._text, self._font, self._justify, 9999)  # Fixed width for caching
        
        # Check class-level cache first
        if cache_key in self._FIGLET_RENDER_CACHE:
            self._rendered_lines = self._FIGLET_RENDER_CACHE[cache_key].copy()
            return
        
        # Not in cache, need to render
        figlet = self._get_or_create_figlet()
        if not figlet:
            self._rendered_lines = [f"Error: Could not create figlet"]
            return
        
        # Render the text
        try:
            rendered = figlet.renderText(self._text)
            rendered_lines = rendered.rstrip('\n').split('\n')
            
            # Store in cache
            if len(self._FIGLET_RENDER_CACHE) > self._MAX_CACHE_ENTRIES:
                # Remove oldest entries (FIFO)
                for _ in range(100):  # Remove 100 at a time
                    oldest_key = next(iter(self._FIGLET_RENDER_CACHE))
                    del self._FIGLET_RENDER_CACHE[oldest_key]
            
            self._FIGLET_RENDER_CACHE[cache_key] = rendered_lines.copy()
            self._rendered_lines = rendered_lines
            
        except Exception as e:
            print(f"Error rendering text: {e}")
            self._rendered_lines = [f"Error: {str(e)}"]
    
    def render_line(self, y: int) -> Strip:
        """Render a line of the FIGlet text with glass effect."""
        # Check if render state changed
        current_state = self._get_render_state()
        if self._last_render_state != current_state:
            self._invalidate_strip_cache()
            self._last_render_state = current_state
        
        # Check strip cache first
        if y in self._figlet_strip_cache:
            return self._figlet_strip_cache[y]
        
        # Get glass background first
        if self.region and self._image_array is not None:
            self._precompute_colors()
        
        width = self.size.width
        height = self.size.height
        segments = []
        padding = self._padding
        
        # Check if we're in vertical padding area
        if y < padding or y >= height - padding:
            # Just render empty line with glass effect
            line = ' ' * width
        else:
            # Adjust y for padding
            padded_y = y - padding
            
            # Get the figlet line if it exists
            if padded_y < len(self._rendered_lines):
                line = self._rendered_lines[padded_y]
            
                # Calculate available width for content (accounting for horizontal padding)
                available_width = width - (2 * padding)
                
                # Handle width cropping or padding
                if len(line) > available_width and available_width > 0:
                    # Crop to fit available width
                    line = line[:available_width]
                elif len(line) < available_width:
                    # Pad based on justification within available width
                    space_padding = available_width - len(line)
                    if self._justify == 'center' or (self._justify == 'auto' and self._width_mode == 'default'):
                        left_pad = space_padding // 2
                        right_pad = space_padding - left_pad
                        line = ' ' * left_pad + line + ' ' * right_pad
                    elif self._justify == 'right':
                        line = ' ' * space_padding + line
                    else:  # left or auto with non-default width_mode
                        line = line + ' ' * space_padding
                
                # Add horizontal padding and ensure total width
                line = ' ' * padding + line + ' ' * padding
                
                # Ensure line is exactly width characters
                if len(line) > width:
                    line = line[:width]
                elif len(line) < width:
                    line = line + ' ' * (width - len(line))
            else:
                # Empty line
                line = ' ' * width
        
        # Render each character with glass effect
        for x, char in enumerate(line):
            # Get background color from precomputed or generate
            if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                color = self._precomputed_colors[y, x]
                bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            else:
                # Fallback blending
                r, g, b = self._overlay_rgb
                blend_factor = self.blend_opacity
                darken = 1 - self.darken_factor
                
                r = int(r * blend_factor * darken)
                g = int(g * blend_factor * darken)
                b = int(b * blend_factor * darken)
                bg_hex = f"#{r:02x}{g:02x}{b:02x}"
            
            # Apply CSS styling if available
            if hasattr(self, '_css_styles') and self._css_styles:
                # Text color from CSS
                text_color = self._css_styles.get('color', 'white')
                text_style = self._css_styles.get('text_style', '')
                
                style_kwargs = {'bgcolor': bg_hex, 'color': text_color}
                
                # Add text style attributes
                if 'bold' in text_style:
                    style_kwargs['bold'] = True
                if 'italic' in text_style:
                    style_kwargs['italic'] = True
                if 'underline' in text_style:
                    style_kwargs['underline'] = True
                if 'reverse' in text_style:
                    style_kwargs['reverse'] = True
                if 'strike' in text_style:
                    style_kwargs['strike'] = True
                
                style = RichStyle(**style_kwargs)
            else:
                # Default styling - only color non-space characters
                if char != ' ':
                    style = RichStyle(bgcolor=bg_hex, color="white")
                else:
                    style = RichStyle(bgcolor=bg_hex)
            
            segments.append(Segment(char, style))
        
        # Cache the strip
        strip = Strip(segments)
        if len(self._figlet_strip_cache) > height * 2:  # Keep reasonable cache size
            self._figlet_strip_cache.clear()
        self._figlet_strip_cache[y] = strip
        
        return strip
    
    def update_text(self, text: str):
        """Update the displayed text."""
        self.text = text
    
    def update_font(self, font: str):
        """Update the FIGlet font."""
        self.font = font
    
    def get_available_fonts(self) -> List[str]:
        """Get list of available FIGlet fonts."""
        from pyfiglet import FigletFont
        return FigletFont.getFonts()
    
    def refresh(self, *regions, repaint: bool = True, layout: bool = False, **kwargs) -> None:
        """Override refresh to control strip cache invalidation"""
        # Only invalidate if visual properties changed
        current_state = self._get_render_state()
        if self._last_render_state != current_state:
            self._invalidate_strip_cache()
            self._last_render_state = current_state
        super().refresh(*regions, repaint=repaint, layout=layout, **kwargs)