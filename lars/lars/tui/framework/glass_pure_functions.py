#!/usr/bin/env python3
"""
Pure functional components extracted from looking_glass.py for potential Cython compilation.
These functions have no side effects and can be compiled for performance gains.
"""

from typing import Tuple, List, Optional, Union
import numpy as np

# Import safe functions that can be compiled with Cython
try:
    # Try to import Cython-compiled versions
    from glass_pure_functions_safe_cython import (
        color_to_rgb, rgb_to_hex, parse_ansi_line, 
        get_content_hash, calculate_image_region
    )
    _using_cython = True
except ImportError:
    # Fall back to pure Python versions
    from glass_pure_functions_safe import (
        color_to_rgb, rgb_to_hex, parse_ansi_line,
        get_content_hash, calculate_image_region
    )
    _using_cython = False

# Export the safe functions
__all__ = [
    'color_to_rgb', 'rgb_to_hex', 'parse_ansi_line',
    'get_content_hash', 'calculate_image_region',
    'vectorized_hex_conversion', 'vectorized_blur_zero_sampling',
    'sample_with_blur', 'batch_blend_colors'
]


def vectorized_hex_conversion(colors_array: np.ndarray) -> np.ndarray:
    """Vectorized RGB to hex conversion using numpy. Pure function."""
    if colors_array.size == 0:
        return np.empty((0, 0), dtype=object)
    
    # Flatten for vectorized operations, then reshape back
    h, w = colors_array.shape[:2]
    flat_colors = colors_array.reshape(-1, colors_array.shape[-1])
    
    # Use numpy's array operations to convert to hex strings
    hex_strings = np.array([
        f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        for rgb in flat_colors
    ], dtype=object)
    
    return hex_strings.reshape(h, w)


# ==============================================================================
# IMAGE SAMPLING - Pure image sampling algorithms
# ==============================================================================

def vectorized_blur_zero_sampling(img_region: np.ndarray, h: int, w: int) -> np.ndarray:
    """Vectorized blur=0 sampling using pure numpy - 10x+ faster than loops."""
    # Create output array
    sampled_region = np.zeros((h, w, img_region.shape[2]), dtype=np.float32)
    
    # Create coordinate arrays for vectorized operations
    y_coords = np.arange(h)[:, None]  # Shape: (h, 1)
    x_coords = np.arange(w)[None, :]  # Shape: (1, w)
    
    # Calculate pixel coordinates
    y1_coords = y_coords * 2              # Top pixels
    y2_coords = y1_coords + 1             # Bottom pixels
    
    # Bounds checking
    y1_valid = y1_coords < img_region.shape[0]
    y2_valid = y2_coords < img_region.shape[0]
    x_valid = x_coords < img_region.shape[1]
    
    # Both pixels valid - average them
    both_valid = y1_valid & y2_valid & x_valid
    if np.any(both_valid):
        # Get the coordinates where both are valid
        y_indices, x_indices = np.where(both_valid)
        y1_vals = y1_coords[y_indices, 0]
        y2_vals = y2_coords[y_indices, 0]
        x_vals = x_coords[0, x_indices]
        
        pixel1 = img_region[y1_vals, x_vals].astype(np.float32)
        pixel2 = img_region[y2_vals, x_vals].astype(np.float32)
        sampled_region[y_indices, x_indices] = (pixel1 + pixel2) / 2.0
    
    # Only top pixel valid
    only_top_valid = y1_valid & (~y2_valid) & x_valid
    if np.any(only_top_valid):
        y_indices, x_indices = np.where(only_top_valid)
        y1_vals = y1_coords[y_indices, 0]
        x_vals = x_coords[0, x_indices]
        sampled_region[y_indices, x_indices] = img_region[y1_vals, x_vals].astype(np.float32)
    
    return sampled_region.astype(img_region.dtype)


def sample_with_blur(img_region: np.ndarray, term_h: int, term_w: int, 
                     blur: int, char_height_ratio: int = 2) -> np.ndarray:
    """Sample image region with blur averaging - using SQUARE regions!"""
    sampled = np.zeros((term_h, term_w, img_region.shape[2]), dtype=np.float32)
    
    for char_y in range(term_h):
        for char_x in range(term_w):
            # Center of current character in image space
            center_y = char_y * char_height_ratio + 1  # +1 to get center of 2-pixel block
            center_x = char_x
            
            # Calculate blur region - make it square in terminal space
            blur_size_y = blur * char_height_ratio  # 2x for terminal height
            blur_size_x = blur  # 1x for terminal width
            
            img_y_start = max(0, center_y - blur_size_y // 2)
            img_y_end = min(img_region.shape[0], center_y + (blur_size_y + 1) // 2)
            img_x_start = max(0, center_x - blur_size_x // 2)
            img_x_end = min(img_region.shape[1], center_x + (blur_size_x + 1) // 2)
            
            if img_y_end > img_y_start and img_x_end > img_x_start:
                # Average the pixels in the square blur region
                blur_region = img_region[img_y_start:img_y_end, img_x_start:img_x_end]
                sampled[char_y, char_x] = np.mean(blur_region, axis=(0, 1))
            else:
                # Fallback for edge cases
                if center_y < img_region.shape[0] and center_x < img_region.shape[1]:
                    sampled[char_y, char_x] = img_region[min(center_y, img_region.shape[0]-1),
                                                         min(center_x, img_region.shape[1]-1)]
    
    return sampled.astype(img_region.dtype)


# ==============================================================================
# COLOR BLENDING - Pure color blending operations
# ==============================================================================

def batch_blend_colors(img_region: np.ndarray, overlay_rgb: Tuple[int, int, int],
                      blend_opacity: float, darken_factor: float) -> np.ndarray:
    """Batch blend colors using numpy. Pure function."""
    # If no blending needed, return original colors
    if blend_opacity == 0 and darken_factor == 0:
        return img_region
    
    overlay = np.array(overlay_rgb, dtype=np.float32)
    
    if img_region.shape[-1] == 4:
        # RGBA
        rgb_region = img_region[..., :3].astype(np.float32)
        alpha = img_region[..., 3:4]
        blended_rgb = rgb_region * (1 - blend_opacity) + overlay * blend_opacity
        
        if darken_factor > 0:
            blended_rgb = blended_rgb * (1 - darken_factor)
        
        blended = np.concatenate([blended_rgb, alpha], axis=-1)
    else:
        # RGB
        blended = img_region.astype(np.float32) * (1 - blend_opacity) + overlay * blend_opacity
        
        if darken_factor > 0:
            blended = blended * (1 - darken_factor)
    
    return blended.astype(np.uint8)


# ==============================================================================
# ANSI PARSING - Pure ANSI escape sequence parsing
# ==============================================================================

def parse_ansi_line(line: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """
    Parse ANSI escape sequences in a line and return list of (text, fg_color, bg_color).
    Pure function with no side effects.
    """
    if not line:
        return []
    
    segments = []
    current_fg = None
    current_bg = None
    i = 0
    line_len = len(line)
    
    while i < line_len:
        # Look for escape sequence
        esc_pos = line.find('\x1b[', i)
        
        if esc_pos == -1:
            # No more escape sequences - add remaining text
            if i < line_len:
                text = line[i:]
                segments.append((text, current_fg, current_bg))
            break
        
        # Add text before escape sequence
        if esc_pos > i:
            text = line[i:esc_pos]
            segments.append((text, current_fg, current_bg))
        
        # Parse escape sequence
        m_pos = line.find('m', esc_pos)
        if m_pos == -1:
            # Malformed escape - skip rest of line
            break
        
        codes = line[esc_pos + 2:m_pos]
        
        # Fast parsing for common cases
        if codes == '0':
            current_fg = None
            current_bg = None
        elif codes.startswith('38;2;'):
            # Foreground RGB - parse manually for speed
            parts = codes.split(';', 4)
            if len(parts) >= 5:
                try:
                    r, g, b = int(parts[2]), int(parts[3]), int(parts[4])
                    current_fg = f"#{r:02x}{g:02x}{b:02x}"
                except ValueError:
                    pass
        elif codes.startswith('48;2;'):
            # Background RGB - parse manually for speed
            parts = codes.split(';', 4)
            if len(parts) >= 5:
                try:
                    r, g, b = int(parts[2]), int(parts[3]), int(parts[4])
                    current_bg = f"#{r:02x}{g:02x}{b:02x}"
                except ValueError:
                    pass
        
        i = m_pos + 1
    
    return segments


# ==============================================================================
# UTILITY FUNCTIONS - Pure helper functions
# ==============================================================================

def calculate_image_region(widget_x: int, widget_y: int, widget_w: int, widget_h: int,
                          img_width: int, img_height: int, char_height_ratio: int = 2) -> Tuple[int, int, int, int]:
    """
    Calculate the image region that corresponds to a widget position.
    Returns (y_start, y_end, x_start, x_end) for array slicing.
    Pure function.
    """
    # Convert to image coordinates - image has 2x height
    img_y_start = widget_y * char_height_ratio
    img_x_start = widget_x
    img_y_end = min(img_height, img_y_start + (widget_h * char_height_ratio))
    img_x_end = min(img_width, img_x_start + widget_w)
    
    # Bounds check
    img_y_start = max(0, img_y_start)
    img_x_start = max(0, img_x_start)
    
    return img_y_start, img_y_end, img_x_start, img_x_end


def get_content_hash(content: Union[str, List[str]]) -> int:
    """Get a hash of content for cache invalidation. Pure function."""
    if isinstance(content, list):
        content = '\n'.join(str(item) for item in content)
    return hash(content)