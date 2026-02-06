#!/usr/bin/env python3
"""
Glass Rich DSL Widget - Rich markup rendering with glass effects
================================================================

A Looking Glass widget that renders Rich DSL markup with glass morphism
effects. Follows the exact same pattern as GlassFigletWidget to avoid
any positioning issues.
"""

from typing import Optional, List, Union
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from rich.console import Console
from textual.strip import Strip
from .looking_glass import AbsoluteGlassMixin, BlazingFastBlendWidget
import re


class GlassRichDSLWidget(AbsoluteGlassMixin, BlazingFastBlendWidget):
    """
    A glass widget that renders Rich DSL markup.

    Features:
    - Supports Rich-style markup syntax
    - Glass morphism effects
    - Dynamic content updates
    - Automatic text wrapping/cropping
    - CSS merge support for styling

    Example usage in ReactiveGlassApp:
    {
        'id': 'rich_content',
        'type': 'rich_dsl',
        'content': ['[bright_green]Hello[/bright_green]', '[red]World[/red]'],
        'x': 10,
        'y': 5,
        'width': 60,
        'height': 10,
        'overlay_color': 'cyan',
        'blend_opacity': 0.3,
    }
    """

    # ANSI color codes
    COLORS = {
        'black': 30, 'red': 31, 'green': 32, 'yellow': 33,
        'blue': 34, 'magenta': 35, 'cyan': 36, 'white': 37,
        'bright_black': 90, 'bright_red': 91, 'bright_green': 92, 'bright_yellow': 93,
        'bright_blue': 94, 'bright_magenta': 95, 'bright_cyan': 96, 'bright_white': 97,
        'gray': 90, 'grey': 90
    }

    BG_COLORS = {name: code + 10 for name, code in COLORS.items()}

    STYLES = {
        'bold': 1, 'dim': 2, 'italic': 3, 'underline': 4,
        'blink': 5, 'reverse': 7, 'strike': 9
    }

    def __init__(self,
                 content: Union[str, List[str]] = "",
                 justify: str = "left",  # left, center, right
                 title: str = "",
                 border: bool = True,
                 show_title: bool = True,
                 padding: int = 0,
                 **kwargs):
        """
        Initialize the Rich DSL widget.

        Args:
            content: Content to render (string or list of strings)
            justify: Text justification
            title: Widget title
            border: Whether to show border
            show_title: Whether to show title in border
            padding: Padding to apply to content
            **kwargs: Passed to parent classes
        """
        # Pass padding to parent class
        super().__init__(content="", padding=padding, **kwargs)
        self._content = content
        self._justify = justify
        self._title = title
        self.border = border
        self.show_title = show_title
        self._rendered_lines = []

        # PERFORMANCE: Cache parsed segments to avoid re-parsing
        self._segment_cache = {}  # line_content -> parsed_segments
        self._rich_console = Console()  # Single console instance

        self._update_content()

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, value: Union[str, List[str]]):
        self._content = value
        # PERFORMANCE: Clear segment cache when content changes
        self._segment_cache.clear()
        self._update_content()
        self.refresh()

    def _parse_markup(self, text: str) -> List[tuple]:
        """
        Parse Rich-style markup into segments.
        Returns list of (text, style_dict) tuples.
        """
        segments = []
        current_pos = 0

        # Pattern to match Rich markup tags
        pattern = r'\[([^\]]+)\]([^\[]*?)(?:\[/(?:[^\]]+)?\]|$)'

        for match in re.finditer(pattern, text):
            # Add any plain text before this tag
            if match.start() > current_pos:
                segments.append((text[current_pos:match.start()], {}))

            # Parse the tag
            tag = match.group(1)
            content = match.group(2)

            if tag == '/':
                # Just reset
                segments.append((content, {}))
            else:
                style = {}
                attrs = tag.lower().split()

                for attr in attrs:
                    # Check for hex colors first (#RRGGBB)
                    if attr.startswith('#') and len(attr) == 7:
                        style['hex_color'] = attr
                    elif attr.startswith('on_#') and len(attr) == 10:
                        style['hex_bgcolor'] = attr[3:]  # Remove 'on_' prefix
                    # Check for named colors
                    elif attr in self.COLORS:
                        style['color'] = attr
                    elif attr.startswith('on_') and attr[3:] in self.COLORS:
                        style['bgcolor'] = attr[3:]
                    elif attr in self.STYLES:
                        style[attr] = True

                segments.append((content, style))

            current_pos = match.end()

        # Add any remaining text
        if current_pos < len(text):
            segments.append((text[current_pos:], {}))

        return segments

    def _update_content(self):
        """Update the rendered content."""
        # Convert content to list of lines
        if isinstance(self._content, str):
            lines = self._content.split('\n')
        elif isinstance(self._content, list):
            lines = []
            for item in self._content:
                if isinstance(item, str):
                    lines.extend(item.split('\n'))
                else:
                    lines.append(str(item))
        else:
            lines = [str(self._content)]

        self._rendered_lines = lines

    def render_line(self, y: int) -> Strip:
        """Render a line with Rich DSL markup and glass effect."""
        # Get glass background first
        if self.region and self._image_array is not None:
            self._precompute_colors()

        width = self.size.width
        height = self.size.height
        segments = []

        # Handle border rendering
        if self.border:
            # Determine content area
            content_width = width - 2  # Account for left and right borders
            content_height = height - 2  # Account for top and bottom borders

            # Apply padding to content area
            padding = self._padding
            padded_content_start_x = 1 + padding  # 1 for border, then padding
            padded_content_end_x = width - 1 - padding  # width-1 for border, then padding
            padded_content_width = padded_content_end_x - padded_content_start_x
            padded_content_start_y = 1 + padding
            padded_content_end_y = height - 1 - padding

            if y == 0:
                # Top border
                if self.show_title and self._title:
                    # Title with borders
                    title_text = f" {self._title} "
                    title_len = len(title_text)
                    if title_len > content_width - 2:
                        title_text = title_text[:content_width - 2]
                        title_len = len(title_text)

                    left_border_len = (content_width - title_len) // 2
                    right_border_len = content_width - title_len - left_border_len

                    line = '┌' + '─' * left_border_len + title_text + '─' * right_border_len + '┐'
                else:
                    # No title
                    line = '┌' + '─' * content_width + '┐'
            elif y == height - 1:
                # Bottom border
                line = '└' + '─' * content_width + '┘'
            else:
                # Content lines with side borders
                content_y = y - 1

                # Check if we're in the padding area
                if content_y < padding or content_y >= height - 1 - padding:
                    # In vertical padding area - just render borders with empty content
                    line = None
                    content_line = ''
                else:
                    # Adjust for padding
                    padded_y = content_y - padding
                    if padded_y < len(self._rendered_lines):
                        content_line = self._rendered_lines[padded_y]
                    else:
                        content_line = ''

                    # We'll handle the content line parsing after this
                    line = None  # Mark for special handling
        else:
            # No border - handle padding directly
            padding = self._padding

            # Check if we're in vertical padding area
            if y < padding or y >= height - padding:
                line = ''  # Empty line in padding area
            else:
                # Adjust y for padding
                padded_y = y - padding
                if padded_y < len(self._rendered_lines):
                    line = self._rendered_lines[padded_y]
                else:
                    line = ''

        # Now render the line
        if line is None and self.border:
            # Special handling for content lines with borders
            # content_line was already set above based on padding

            # Render left border
            x = 0
            self._render_char('│', x, y, segments, width, {})
            x += 1

            # Add left padding spaces
            padding = self._padding
            for _ in range(padding):
                if x < width - 1:
                    x = self._render_char(' ', x, y, segments, width, {})

            # Parse and render content (only if we have content to render)
            if content_line:
                # Use Rich's built-in markup parser
                rich_text = Text.from_markup(content_line)

                # Calculate available width for content
                content_start_x = x
                content_max_x = width - 1 - padding  # Leave room for right padding and border
                available_width = content_max_x - content_start_x

                # Apply justification
                if self._justify != 'left' and available_width > 0:
                    text_len = len(rich_text.plain)
                    visible_len = min(text_len, available_width)
                    if self._justify == 'center':
                        justify_padding = (available_width - visible_len) // 2
                        # Add padding before text
                        for _ in range(justify_padding):
                            if x < content_max_x:
                                x = self._render_char(' ', x, y, segments, width, {})
                    elif self._justify == 'right':
                        justify_padding = available_width - visible_len
                        # Add padding before text
                        for _ in range(justify_padding):
                            if x < content_max_x:
                                x = self._render_char(' ', x, y, segments, width, {})

                # PERFORMANCE: Check cache first
                if content_line not in self._segment_cache:
                    # Get segments from Rich text (includes proper hex color parsing)
                    rich_segments = list(self._rich_console.render(rich_text, options=self._rich_console.options.update(no_wrap=True)))
                    # Limit cache size
                    if len(self._segment_cache) > 10000:
                        # Remove oldest entry
                        self._segment_cache.pop(next(iter(self._segment_cache)))
                    self._segment_cache[content_line] = rich_segments
                else:
                    rich_segments = self._segment_cache[content_line]

                # Render each segment
                for segment in rich_segments:
                    if segment.text == '\n':  # Skip newlines from console render
                        continue
                    for char in segment.text:
                        if x < content_max_x:
                            x = self._render_char_with_style(char, x, y, segments, width, segment.style)

            # Fill to right padding area
            while x < width - 1 - padding:
                x = self._render_char(' ', x, y, segments, width, {})

            # Add right padding spaces
            for _ in range(padding):
                if x < width - 1:
                    x = self._render_char(' ', x, y, segments, width, {})

            # Render right border
            self._render_char('│', width - 1, y, segments, width, {})

        elif line is not None:
            # Check if this is a border line or content
            if self.border and (y == 0 or y == height - 1):
                # Border line - render as-is
                x = 0
                for char in line:
                    x = self._render_char(char, x, y, segments, width, {})

                # Fill remaining width
                while x < width:
                    x = self._render_char(' ', x, y, segments, width, {})
            else:
                # Content line without border - use Rich's markup parser
                x = 0

                # Add left padding
                padding = self._padding
                for _ in range(padding):
                    if x < width:
                        x = self._render_char(' ', x, y, segments, width, {})

                # Calculate available width for content
                content_start_x = x
                content_max_x = width - padding  # Leave room for right padding
                available_width = content_max_x - content_start_x

                if line:  # Only render if we have content
                    # Use Rich's built-in markup parser
                    rich_text = Text.from_markup(line)

                    # Apply justification
                    if self._justify != 'left' and available_width > 0:
                        text_len = len(rich_text.plain)
                        visible_len = min(text_len, available_width)
                        if self._justify == 'center':
                            justify_padding = (available_width - visible_len) // 2
                            # Add padding before text
                            for _ in range(justify_padding):
                                if x < content_max_x:
                                    x = self._render_char(' ', x, y, segments, width, {})
                        elif self._justify == 'right':
                            justify_padding = available_width - visible_len
                            # Add padding before text
                            for _ in range(justify_padding):
                                if x < content_max_x:
                                    x = self._render_char(' ', x, y, segments, width, {})

                    # PERFORMANCE: Check cache first
                    if line not in self._segment_cache:
                        # Get segments from Rich text (includes proper hex color parsing)
                        rich_segments = list(self._rich_console.render(rich_text, options=self._rich_console.options.update(no_wrap=True)))
                        # Limit cache size
                        if len(self._segment_cache) > 10000:
                            # Remove oldest entry
                            self._segment_cache.pop(next(iter(self._segment_cache)))
                        self._segment_cache[line] = rich_segments
                    else:
                        rich_segments = self._segment_cache[line]

                    # Render each segment
                    for segment in rich_segments:
                        if segment.text == '\n':  # Skip newlines from console render
                            continue
                        for char in segment.text:
                            if x < content_max_x:
                                x = self._render_char_with_style(char, x, y, segments, width, segment.style)

                # Fill to right padding
                while x < width - padding:
                    x = self._render_char(' ', x, y, segments, width, {})

                # Add right padding
                for _ in range(padding):
                    if x < width:
                        x = self._render_char(' ', x, y, segments, width, {})
        else:
            # Empty line with glass effect
            for x in range(width):
                if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0] and x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = "#000000"

                style = RichStyle(bgcolor=bg_hex)
                segments.append(Segment(' ', style))

        return Strip(segments)

    def update_content(self, content: Union[str, List[str]]):
        """Update the displayed content."""
        self.content = content

    def _render_char(self, char: str, x: int, y: int, segments: list, width: int, style_dict: dict):
        """Helper to render a single character with glass effect."""
        if x >= width:
            return x

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

        # Build style
        style_kwargs = {'bgcolor': bg_hex}

        # Apply hex background color if specified
        if 'hex_bgcolor' in style_dict:
            style_kwargs['bgcolor'] = style_dict['hex_bgcolor']

        # Apply markup styles
        if 'hex_color' in style_dict:
            # Use hex color directly
            style_kwargs['color'] = style_dict['hex_color']
        elif 'color' in style_dict:
            style_kwargs['color'] = style_dict['color']
        else:
            style_kwargs['color'] = 'white'

        # Apply text decorations
        for attr in ['bold', 'italic', 'underline', 'reverse', 'strike']:
            if style_dict.get(attr):
                style_kwargs[attr] = True

        # Override with CSS styles if present
        if hasattr(self, '_css_styles') and self._css_styles:
            if 'color' in self._css_styles and 'color' not in style_dict:
                style_kwargs['color'] = self._css_styles['color']

        style = RichStyle(**style_kwargs)
        segments.append(Segment(char, style))
        return x + 1

    def _render_char_with_style(self, char: str, x: int, y: int, segments: list, width: int, rich_style: Optional[RichStyle]):
        """Helper to render a single character with a Rich Style object."""
        if x >= width:
            return x

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

        # If we have a rich_style, combine it with our glass background
        if rich_style:
            # Create a new style that combines the rich style with our glass background
            style = rich_style + RichStyle(bgcolor=bg_hex)
        else:
            # No markup style, just use glass background with white text
            style = RichStyle(color='white', bgcolor=bg_hex)

        # Override with CSS styles if present
        if hasattr(self, '_css_styles') and self._css_styles:
            if 'color' in self._css_styles and not (rich_style and rich_style.color):
                style = style + RichStyle(color=self._css_styles['color'])

        segments.append(Segment(char, style))
        return x + 1