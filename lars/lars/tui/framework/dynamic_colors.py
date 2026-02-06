#!/usr/bin/env python3
"""
Dynamic Colors Module for Looking Glass
=======================================

Provides dynamic color palette management that extracts colors from background images
and generates a comprehensive color scheme with semantic names.
"""

from typing import Dict, Optional, Any


class DynamicColorManager:
    """Manages dynamic color palettes with caching for performance"""
    
    def __init__(self):
        self._cached_colors: Optional[Dict[str, str]] = None
        self._cached_palette_id: Optional[str] = None
    
    def get_colors(self, color_palette: Dict[str, Any]) -> Dict[str, str]:
        """
        Get the current dynamic color palette with caching.
        
        Args:
            color_palette: The color palette dict from the app (usually self.color_palette)
                          Contains 'dominant', 'palette', 'analogous', 'triadic', etc.
        
        Returns:
            Dict mapping color names to hex values
        """
        # Use dominant color as cache key (changes when background changes)
        palette_id = color_palette.get('dominant', 'default') if color_palette else 'default'
        
        # Return cached colors if palette hasn't changed
        if self._cached_colors is not None and self._cached_palette_id == palette_id:
            return self._cached_colors
        
        # Otherwise rebuild and cache the colors
        self._cached_palette_id = palette_id
        
        if color_palette and 'dominant' in color_palette:
            # Get the dynamic color arrays
            analogous = color_palette.get('analogous', ['#4a90e2', '#4ae290', '#904ae2'])
            triadic = color_palette.get('triadic', ['#4a90e2', '#e24a90', '#90e24a'])
            light_variants = color_palette.get('light_variants', ['#7da5e8', '#a1dc4c', '#f7b549'])
            dark_variants = color_palette.get('dark_variants', ['#356ba6', '#5ca218', '#c2891a'])
            
            # Get accent-based colors for better contrast
            accent_analogous = color_palette.get('accent_analogous', ['#f5a623', '#f56223', '#f5e623'])
            accent_triadic = color_palette.get('accent_triadic', ['#f5a623', '#23f5a6', '#a623f5'])
            
            self._cached_colors = {
                'dominant': color_palette['dominant'],
                'complementary': color_palette.get('complementary', '#e24a4a'),
                'primary': color_palette['dominant'],
                'secondary': color_palette['palette'][0] if color_palette.get('palette') else '#7ed321',
                'accent': color_palette.get('accent', '#f5a623'),
                'accent_complementary': color_palette.get('accent_complementary', '#2359dc'),
                'accent_light': color_palette.get('accent_light', '#f7c865'),
                'accent_dark': color_palette.get('accent_dark', '#935f15'),
                'light': light_variants[0] if light_variants else '#7da5e8',
                'dark': dark_variants[0] if dark_variants else '#356ba6',
                'analogous_1': analogous[0] if len(analogous) > 0 else '#4a90e2',
                'analogous_2': analogous[1] if len(analogous) > 1 else '#4ae290',
                'analogous_3': analogous[2] if len(analogous) > 2 else '#904ae2',
                'triadic_1': triadic[0] if len(triadic) > 0 else '#4a90e2',
                'triadic_2': triadic[1] if len(triadic) > 1 else '#e24a90',
                'triadic_3': triadic[2] if len(triadic) > 2 else '#90e24a',
                # Accent-based variations for "pop"
                'pop_1': accent_analogous[0] if len(accent_analogous) > 0 else '#f5a623',
                'pop_2': accent_analogous[1] if len(accent_analogous) > 1 else '#f56223',
                'pop_3': accent_analogous[2] if len(accent_analogous) > 2 else '#f5e623',
                'vibrant_1': accent_triadic[0] if len(accent_triadic) > 0 else '#f5a623',
                'vibrant_2': accent_triadic[1] if len(accent_triadic) > 1 else '#23f5a6',
                'vibrant_3': accent_triadic[2] if len(accent_triadic) > 2 else '#a623f5',
            }
        else:
            # Fallback colors
            self._cached_colors = {
                'dominant': '#4a90e2',
                'complementary': '#e24a4a',
                'primary': '#4a90e2',
                'secondary': '#7ed321',
                'accent': '#f5a623',
                'accent_complementary': '#2359dc',
                'accent_light': '#f7c865',
                'accent_dark': '#935f15',
                'light': '#7da5e8',
                'dark': '#356ba6',
                'analogous_1': '#4a90e2',
                'analogous_2': '#4ae290',
                'analogous_3': '#904ae2',
                'triadic_1': '#4a90e2',
                'triadic_2': '#e24a90',
                'triadic_3': '#90e24a',
                # Accent-based variations
                'pop_1': '#f5a623',
                'pop_2': '#f56223',
                'pop_3': '#f5e623',
                'vibrant_1': '#f5a623',
                'vibrant_2': '#23f5a6',
                'vibrant_3': '#a623f5',
            }
        
        return self._cached_colors