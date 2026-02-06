#!/usr/bin/env python3
"""
Safe subset of pure functions for Cython compilation.
Excludes NumPy-heavy operations that can cause core dumps.
"""

from typing import Tuple, List, Optional, Union


# ==============================================================================
# COLOR OPERATIONS - Pure color conversion (No NumPy)
# ==============================================================================

def color_to_rgb(color: str) -> Tuple[int, int, int]:
    """Convert color name or hex to RGB tuple. Pure function with no side effects."""
    # Handle hex colors
    if color.startswith('#'):
        try:
            # Remove # and convert hex to RGB
            hex_color = color.lstrip('#')
            if len(hex_color) == 6:
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                return (r, g, b)
            elif len(hex_color) == 3:
                # Handle short form like #FFF
                r = int(hex_color[0] * 2, 16)
                g = int(hex_color[1] * 2, 16)
                b = int(hex_color[2] * 2, 16)
                return (r, g, b)
        except ValueError:
            pass  # Fall through to color map
    
    # Predefined color map
    colors = {
        "yellow": (255, 255, 0),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "darkblue": (0, 0, 139),
        "darkred": (139, 0, 0),
        "darkgreen": (0, 100, 0),
        "darkcyan": (0, 139, 139),
        "purple": (128, 0, 128),
        "orange": (255, 165, 0),
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "gray": (128, 128, 128),
        "lightblue": (173, 216, 230),
    }
    return colors.get(color, (128, 128, 128))


def rgb_to_hex(rgb_tuple: Tuple[int, int, int]) -> str:
    """Convert RGB tuple to hex string. Pure function."""
    return f"#{rgb_tuple[0]:02x}{rgb_tuple[1]:02x}{rgb_tuple[2]:02x}"


# ==============================================================================
# ANSI PARSING - Pure ANSI escape sequence parsing (No NumPy)
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
# UTILITY FUNCTIONS - Pure helper functions (No NumPy)
# ==============================================================================

def get_content_hash(content: Union[str, List[str]]) -> int:
    """Get a hash of content for cache invalidation. Pure function."""
    if isinstance(content, list):
        content = '\n'.join(str(item) for item in content)
    return hash(content)


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