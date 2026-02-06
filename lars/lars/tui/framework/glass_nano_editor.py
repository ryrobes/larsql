#!/usr/bin/env python3
"""
Glass Nano Editor - A nano-style text editor widget
===================================================

A glass widget that provides a nano-style editing experience without
needing to embed an actual terminal. This avoids PTY complexity while
providing a familiar interface.
"""

from .looking_glass import AbsoluteGlassPanel
from textual.strip import Strip, Segment
from rich.style import Style as RichStyle
from typing import List, Optional, Callable
from datetime import datetime
import tempfile
from pathlib import Path


class GlassNanoEditor(AbsoluteGlassPanel):
    """
    A nano-style text editor with glass morphism effects.
    
    Features:
    - Nano-style keyboard shortcuts
    - Status bar with help
    - File operations
    - Glass transparency
    """
    
    def __init__(self, 
                 file_path: Optional[str] = None,
                 on_save: Optional[Callable[[str], None]] = None,
                 title: str = "SQL Editor - ^O Save | ^X Exit",
                 **kwargs):
        """Initialize the nano-style editor."""
        # File handling
        if file_path:
            self.file_path = Path(file_path)
            self._temp_file = None
            if self.file_path.exists():
                content = self.file_path.read_text()
            else:
                content = ""
        else:
            # Create temp file
            self._temp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.sql', delete=False
            )
            nano_content = """-- Nano-style Editor
-- Use Ctrl+O to save, Ctrl+X to exit
-- Arrow keys to navigate

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(255)
);
"""
            self._temp_file.write(nano_content)
            self._temp_file.flush()
            self.file_path = Path(self._temp_file.name)
            content = nano_content
            
        # Initialize parent
        super().__init__(content='', title=title, **kwargs)
        
        # Editor state
        self._lines = content.splitlines() if content else ['']
        self._cursor_row = 0
        self._cursor_col = 0
        self._scroll_offset_y = 0
        self._has_focus = True
        self._modified = False
        self.on_save_callback = on_save
        
        # Status messages
        self._status_message = ""
        self._status_time = None
        
    def get_viewport_height(self) -> int:
        """Get the number of visible lines."""
        if hasattr(self, 'size') and self.size:
            # Account for border, title, and bottom help bar
            height = self.size.height - 4 if self.border else self.size.height - 2
            return max(1, height)
        return 10
        
    def get_viewport_width(self) -> int:
        """Get the number of visible columns."""
        if hasattr(self, 'size') and self.size:
            return max(1, self.size.width - (2 if self.border else 0))
        return 40
        
    def insert_char(self, char: str):
        """Insert a character at cursor position."""
        if self._cursor_row >= len(self._lines):
            self._lines.append("")
            
        line = self._lines[self._cursor_row]
        self._lines[self._cursor_row] = (
            line[:self._cursor_col] + char + line[self._cursor_col:]
        )
        self._cursor_col += 1
        self._modified = True
        self.refresh()
        
    def insert_newline(self):
        """Insert newline at cursor position."""
        if self._cursor_row >= len(self._lines):
            self._lines.append("")
            
        line = self._lines[self._cursor_row]
        current_line = line[:self._cursor_col]
        next_line = line[self._cursor_col:]
        
        self._lines[self._cursor_row] = current_line
        self._lines.insert(self._cursor_row + 1, next_line)
        
        self._cursor_row += 1
        self._cursor_col = 0
        self._modified = True
        self._adjust_scroll()
        self.refresh()
        
    def delete_char(self):
        """Delete character before cursor (backspace)."""
        if self._cursor_col > 0:
            line = self._lines[self._cursor_row]
            self._lines[self._cursor_row] = (
                line[:self._cursor_col-1] + line[self._cursor_col:]
            )
            self._cursor_col -= 1
            self._modified = True
        elif self._cursor_row > 0:
            # Join with previous line
            prev_line = self._lines[self._cursor_row - 1]
            curr_line = self._lines[self._cursor_row]
            self._cursor_col = len(prev_line)
            self._lines[self._cursor_row - 1] = prev_line + curr_line
            self._lines.pop(self._cursor_row)
            self._cursor_row -= 1
            self._modified = True
            self._adjust_scroll()
        self.refresh()
        
    def move_cursor(self, direction: str):
        """Move cursor in specified direction."""
        if direction == 'up' and self._cursor_row > 0:
            self._cursor_row -= 1
            self._cursor_col = min(self._cursor_col, len(self._lines[self._cursor_row]))
            self._adjust_scroll()
        elif direction == 'down' and self._cursor_row < len(self._lines) - 1:
            self._cursor_row += 1
            self._cursor_col = min(self._cursor_col, len(self._lines[self._cursor_row]))
            self._adjust_scroll()
        elif direction == 'left':
            if self._cursor_col > 0:
                self._cursor_col -= 1
            elif self._cursor_row > 0:
                self._cursor_row -= 1
                self._cursor_col = len(self._lines[self._cursor_row])
                self._adjust_scroll()
        elif direction == 'right':
            if self._cursor_col < len(self._lines[self._cursor_row]):
                self._cursor_col += 1
            elif self._cursor_row < len(self._lines) - 1:
                self._cursor_row += 1
                self._cursor_col = 0
                self._adjust_scroll()
        self.refresh()
        
    def _adjust_scroll(self):
        """Adjust scroll offset to keep cursor visible."""
        viewport_height = self.get_viewport_height()
        
        if self._cursor_row < self._scroll_offset_y:
            self._scroll_offset_y = self._cursor_row
        elif self._cursor_row >= self._scroll_offset_y + viewport_height:
            self._scroll_offset_y = self._cursor_row - viewport_height + 1
            
    def save_file(self):
        """Save content to file."""
        content = '\n'.join(self._lines)
        self.file_path.write_text(content)
        self._modified = False
        self.set_status("Saved")
        
        # Trigger callback
        if self.on_save_callback:
            self.on_save_callback(content)
            
    def set_status(self, message: str):
        """Set status message."""
        self._status_message = message
        self._status_time = datetime.now()
        self.refresh()
        
    def get_text(self) -> str:
        """Get full text content."""
        return '\n'.join(self._lines)
        
    def render_line(self, y: int) -> Strip:
        """Render a line with nano-style interface."""
        # Handle title and border
        if self.border:
            if y == 0:
                return super().render_line(y)
            elif y == 1 and self.show_title and self.title:
                return super().render_line(y)
            elif y == self.size.height - 1:
                return super().render_line(y)
                
        # Bottom help bar (2 lines from bottom)
        if y == self.size.height - 2:
            help_text = "^G Help  ^O Save  ^X Exit  ^K Cut  ^U Paste"
            if self._modified:
                help_text = "[Modified] " + help_text
                
            # Add status message if recent
            if self._status_message and self._status_time:
                elapsed = (datetime.now() - self._status_time).total_seconds()
                if elapsed < 3:
                    help_text = f"{self._status_message} | {help_text}"
                    
            # Create help bar with inverted colors
            segments = []
            bg_color = "white"
            fg_color = "black"
            
            for i, char in enumerate(help_text):
                segments.append(Segment(char, RichStyle(color=fg_color, bgcolor=bg_color)))
                
            # Pad to full width
            width = self.size.width - (2 if self.border else 0)
            if len(help_text) < width:
                padding = " " * (width - len(help_text))
                for char in padding:
                    segments.append(Segment(char, RichStyle(color=fg_color, bgcolor=bg_color)))
                    
            return Strip(segments)
            
        # Calculate content area
        if self.border:
            content_y = y - 2 if (self.show_title and self.title) else y - 1
        else:
            content_y = y
            
        # Adjust for help bar
        viewport_height = self.get_viewport_height()
        
        # Get line to display
        line_index = content_y + self._scroll_offset_y
        
        if line_index < len(self._lines) and content_y < viewport_height:
            line_text = self._lines[line_index]
        else:
            line_text = ""
            
        # Check if cursor is on this line
        cursor_on_line = (self._has_focus and 
                         line_index == self._cursor_row and 
                         content_y < viewport_height)
        
        # Render with glass effect
        width = self.size.width - (2 if self.border else 0)
        segments = []
        
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0]:
            for x in range(width):
                # Get character
                char = line_text[x] if x < len(line_text) else ' '
                
                # Check if this is cursor position
                is_cursor = cursor_on_line and x == self._cursor_col
                
                # Get glass color
                actual_x = x + (1 if self.border else 0)
                if actual_x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, actual_x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                
                # Create style
                if is_cursor:
                    style = RichStyle(bgcolor="white", color=bg_hex, bold=True)
                else:
                    style = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                
                segments.append(Segment(char, style))
        else:
            # Fallback rendering
            for x in range(width):
                char = line_text[x] if x < len(line_text) else ' '
                is_cursor = cursor_on_line and x == self._cursor_col
                
                if is_cursor:
                    style = RichStyle(bgcolor="white", color=self.overlay_color, bold=True)
                else:
                    style = RichStyle(bgcolor=self.overlay_color, color="white", bold=True)
                
                segments.append(Segment(char, style))
        
        return Strip(segments)
        
    def on_key(self, event) -> None:
        """Handle key events with nano-style bindings."""
        if not self._has_focus:
            return
            
        key = event.key
        
        # Nano shortcuts
        if key == "ctrl+o":
            self.save_file()
        elif key == "ctrl+x":
            # Exit - save if modified
            if self._modified:
                self.save_file()
            # Request app to close editor
            if hasattr(self.app, 'dispatch'):
                from looking_glass_reactive import Action
                self.app.dispatch(Action('TOGGLE_SQL_EDITOR'))
                
        # Navigation
        elif key == "up":
            self.move_cursor("up")
        elif key == "down":
            self.move_cursor("down")
        elif key == "left":
            self.move_cursor("left")
        elif key == "right":
            self.move_cursor("right")
        elif key == "home" or key == "ctrl+a":
            self._cursor_col = 0
            self.refresh()
        elif key == "end" or key == "ctrl+e":
            if self._cursor_row < len(self._lines):
                self._cursor_col = len(self._lines[self._cursor_row])
                self.refresh()
        elif key == "pageup":
            for _ in range(self.get_viewport_height()):
                self.move_cursor("up")
        elif key == "pagedown":
            for _ in range(self.get_viewport_height()):
                self.move_cursor("down")
                
        # Editing
        elif key == "enter":
            self.insert_newline()
        elif key == "backspace":
            self.delete_char()
        elif key == "delete" or key == "ctrl+d":
            # Delete forward
            if self._cursor_col < len(self._lines[self._cursor_row]):
                self._cursor_col += 1
                self.delete_char()
            elif self._cursor_row < len(self._lines) - 1:
                # Join with next line
                self._cursor_row += 1
                self._cursor_col = 0
                self.delete_char()
        elif key == "tab":
            self.insert_char("    ")  # 4 spaces
            
        # Text input
        elif len(key) == 1 and key.isprintable():
            self.insert_char(key)
            
    def on_mount(self):
        """Set focus when mounted."""
        self._has_focus = True
        
    def on_click(self, event) -> None:
        """Handle mouse clicks."""
        self._has_focus = True
        
    def set_focus(self, focused: bool) -> None:
        """Set focus state."""
        self._has_focus = focused
        if hasattr(self, 'refresh'):
            self.refresh()
        
    def on_unmount(self):
        """Clean up temp file if needed."""
        if self._temp_file and self.file_path.exists():
            try:
                import os
                os.unlink(self.file_path)
            except:
                pass